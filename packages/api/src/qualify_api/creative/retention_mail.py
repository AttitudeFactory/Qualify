"""Frozen retention email batches, committed before sending (m-24842840).

A tenant transaction lock spans staging and delivery, while independent tenant
transactions durably stage a batch before HTTP and atomically record its success.
New pieces wait for the next pass while their brand/recipient/stage has a pending
batch. Retries use the stored mail verbatim, including its URL and provider key.

Membership, deadline and protection are rechecked before delivery. A stale batch
that was never attempted is cancelled. An attempted batch is held for review,
reserving its exact piece/deadline/stage identities without blocking new pieces.
Retries run every worker minute and stop at 23 hours after an unknown first
attempt, before Resend expires its 24-hour key. Payloads are never rewritten.
This prioritizes avoiding duplicates over blindly resending an uncertain delivery.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from qualify_api.auth.confirmed_email import confirmed_email
from qualify_api.creative.models import (
    ContentDraft,
    ContentDraftPurgeWarning,
    ContentDraftWarningBatch,
    ImageAsset,
)
from qualify_api.creative.retention import Retention, RetentionState, retention_of
from qualify_api.mail import Mailer, MailNotConfigured, MailRejected, OutgoingMail, default_mailer
from qualify_api.mail.config import public_app_url
from qualify_api.mail.retention import ExpiringPiece, WarningStage, warning_mail
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

logger = logging.getLogger(__name__)
Verifier = Callable[[UUID, str], str | None]
Group = tuple[UUID, WarningStage, str]
LivePiece = tuple[UUID, WarningStage, datetime]
# Resend retains idempotency keys for 24 h. Stop early instead of blindly resending
# an unknown acceptance after expiry. Pending batches are retried each worker minute.
RETRY_WINDOW = timedelta(hours=23)


@dataclass(frozen=True)
class _Delivery:
    batch_id: UUID
    brand_id: UUID
    recipient: str
    stage: str
    pieces: tuple[tuple[UUID, datetime], ...]
    mail: OutgoingMail
    fresh_attempt: bool


def _mark_review(
    batch: ContentDraftWarningBatch,
    now: datetime,
    reason: str = "retry_window_elapsed",
) -> None:
    batch.needs_review_at = now
    logger.error(
        "pieces.warning needs_review tenant=%s batch=%s first_attempt=%s reason=%s",
        batch.tenant_id,
        batch.id,
        batch.first_attempt_at,
        reason,
    )


def warning_review_ids(tenant_id: UUID) -> list[UUID]:
    """Read-only operational lookup of stopped deliveries; never sends or resets one."""
    with tenant_session(tenant_id) as session:
        return list(
            session.scalars(
                select(ContentDraftWarningBatch.id)
                .where(
                    ContentDraftWarningBatch.tenant_id == tenant_id,
                    ContentDraftWarningBatch.needs_review_at.is_not(None),
                )
                .order_by(ContentDraftWarningBatch.needs_review_at, ContentDraftWarningBatch.id)
            )
        )


def discover_warning_tenants(now: datetime) -> list[UUID]:
    """IDs only; all subsequent reads and writes use the tenant RLS door."""
    with admin_session() as session:
        return list(
            session.scalars(
                select(ContentDraft.tenant_id)
                .where(ContentDraft.media_purged_at.is_(None))
                .distinct()
            )
        )


def warning_stage(verdict: Retention | None, now: datetime) -> WarningStage | None:
    if verdict is None or verdict.state is not RetentionState.WARNING or verdict.deadline is None:
        return None
    remaining = verdict.deadline - now
    if remaining <= timedelta(0):
        return None
    return WarningStage.LAST_DAY if remaining <= timedelta(days=1) else WarningStage.WINDOW_15D


def pending_pieces(
    pieces: list[ExpiringPiece],
    recorded: set[tuple[UUID, datetime, str]],
    stage: WarningStage = WarningStage.WINDOW_15D,
) -> list[ExpiringPiece]:
    return [p for p in pieces if (p.draft_id, p.deadline, stage.value) not in recorded]


def _confirmed_recipients(
    session: Session,
    tenant_id: UUID,
    verify: Verifier,
    recipient: str | None = None,
) -> tuple[set[str], set[str]]:
    statement = (
        select(User)
        .join(TenantMember, TenantMember.user_id == User.id)
        .where(
            User.tenant_id == tenant_id,
            TenantMember.tenant_id == tenant_id,
            User.auth_user_id.is_not(None),
        )
    )
    if recipient is not None:
        statement = statement.where(func.lower(User.email) == recipient)
    confirmed: set[str] = set()
    unavailable: set[str] = set()
    for member in session.scalars(statement).all():
        try:
            email = verify(member.auth_user_id, member.email)
        except Exception:
            # A transient identity-provider error must not cancel a frozen retry.
            unavailable.add(member.email.casefold())
            logger.exception(
                "pieces.warning verification failed tenant=%s member=%s", tenant_id, member.id
            )
            continue
        if email:
            confirmed.add(email.casefold())
    return confirmed, unavailable - confirmed


def _snapshots(batch: ContentDraftWarningBatch) -> list[tuple[UUID, datetime]]:
    return [
        (UUID(p["draft_id"]), datetime.fromisoformat(p["deadline"]))
        for p in batch.payload["pieces"]
    ]


def _live_pieces(
    session: Session,
    tenant_id: UUID,
    now: datetime,
    scope: set[UUID] | None,
) -> tuple[dict[tuple[UUID, WarningStage], list[ExpiringPiece]], dict[UUID, LivePiece]]:
    statement = select(ContentDraft).where(
        ContentDraft.tenant_id == tenant_id,
        ContentDraft.media_purged_at.is_(None),
    )
    if scope is not None:
        statement = statement.where(ContentDraft.id.in_(scope))
    drafts = list(session.scalars(statement))
    verdicts = retention_of(session, tenant_id, [d.id for d in drafts], now)
    groups: dict[tuple[UUID, WarningStage], list[ExpiringPiece]] = defaultdict(list)
    live: dict[UUID, LivePiece] = {}
    for draft in drafts:
        verdict = verdicts.get(draft.id)
        stage = warning_stage(verdict, now)
        if stage is None:
            continue
        assert verdict is not None and verdict.deadline is not None
        groups[draft.brand_id, stage].append(ExpiringPiece(draft.id, draft.title, verdict.deadline))
        live[draft.id] = (draft.brand_id, stage, verdict.deadline)
    return groups, live


def _batch_is_live(batch: ContentDraftWarningBatch, live: dict[UUID, LivePiece]) -> bool:
    stage = WarningStage(batch.stage)
    return all(
        live.get(draft_id) == (batch.brand_id, stage, due) for draft_id, due in _snapshots(batch)
    )


def _thumbnail_urls(session: Session, draft_ids: set[UUID]) -> dict[UUID, str]:
    """Exactly one thumbnail query, only for pieces entering new frozen batches."""
    if not draft_ids:
        return {}
    return dict(
        session.execute(
            select(ImageAsset.draft_id, ImageAsset.media_url)
            .where(
                ImageAsset.draft_id.in_(draft_ids),
                ImageAsset.media_url.startswith("https://"),
            )
            .distinct(ImageAsset.draft_id)
            .order_by(
                ImageAsset.draft_id,
                ImageAsset.created_at.desc(),
                ImageAsset.id.desc(),
            )
        ).all()
    )


def _stage_batches(
    tenant_id: UUID,
    now: datetime,
    verify: Verifier,
    scope: set[UUID] | None,
    lock_session: Session,
) -> list[UUID]:
    with tenant_session(tenant_id) as session:
        if session is lock_session:
            raise RuntimeError("retention email needs independent worker transactions")
        batches = list(
            session.scalars(
                select(ContentDraftWarningBatch)
                .where(
                    ContentDraftWarningBatch.tenant_id == tenant_id,
                    ContentDraftWarningBatch.sent_at.is_(None),
                )
                .order_by(ContentDraftWarningBatch.created_at, ContentDraftWarningBatch.id)
            )
        )
        groups, live = _live_pieces(session, tenant_id, now, scope)
        if not groups and not batches:
            return []
        recipients, unavailable = _confirmed_recipients(session, tenant_id, verify)
        recorded: dict[str, set[tuple[UUID, datetime, str]]] = defaultdict(set)
        if recipients and live:
            for email, draft_id, deadline, stage in session.execute(
                select(
                    ContentDraftPurgeWarning.recipient,
                    ContentDraftPurgeWarning.draft_id,
                    ContentDraftPurgeWarning.deadline,
                    ContentDraftPurgeWarning.stage,
                ).where(
                    ContentDraftPurgeWarning.tenant_id == tenant_id,
                    ContentDraftPurgeWarning.recipient.in_(recipients),
                    ContentDraftPurgeWarning.draft_id.in_(live),
                )
            ).all():
                recorded[email].add((draft_id, deadline, stage))
        blocked: set[Group] = set()
        ready: list[UUID] = []
        for batch in batches:
            group = (batch.brand_id, WarningStage(batch.stage), batch.recipient)
            snapshots = _snapshots(batch)
            if scope is not None and not {p[0] for p in snapshots}.issubset(scope):
                if batch.cancelled_at is None and batch.needs_review_at is None:
                    blocked.add(group)
                continue
            # Unknown acceptance reserves only these piece/deadline/stage identities,
            # not the whole brand. New pieces and LAST_DAY remain eligible.
            if batch.needs_review_at is not None or (
                batch.cancelled_at is not None and batch.first_attempt_at is not None
            ):
                recorded[batch.recipient].update(
                    (draft, due, batch.stage) for draft, due in snapshots
                )
                continue
            if batch.cancelled_at is not None:
                continue
            if batch.first_attempt_at is not None and now - batch.first_attempt_at >= RETRY_WINDOW:
                _mark_review(batch, now)
                recorded[batch.recipient].update(
                    (draft, due, batch.stage) for draft, due in snapshots
                )
                continue
            blocked.add(group)
            if batch.recipient in unavailable:
                continue
            already_recorded = any(
                (draft, due, batch.stage) in recorded[batch.recipient] for draft, due in snapshots
            )
            if (
                batch.recipient not in recipients
                or not _batch_is_live(batch, live)
                or already_recorded
            ):
                if batch.first_attempt_at is not None:
                    _mark_review(batch, now, "eligibility_changed")
                    blocked.discard(group)
                    recorded[batch.recipient].update(
                        (draft, due, batch.stage) for draft, due in snapshots
                    )
                else:
                    batch.cancelled_at = now
                    blocked.discard(group)  # safe rejection must not suppress a new last-day piece
                continue
            ready.append(batch.id)
        session.flush()  # free partial unique slots before inserting new batches
        plans: list[tuple[UUID, WarningStage, str, list[ExpiringPiece]]] = []
        for (brand_id, stage), pieces in groups.items():
            for recipient in sorted(recipients):
                if (brand_id, stage, recipient) in blocked:
                    continue
                pending = pending_pieces(pieces, recorded[recipient], stage)
                if pending:
                    plans.append((brand_id, stage, recipient, pending))
        if not plans:
            return ready
        thumbnails = _thumbnail_urls(session, {p.draft_id for *_, pieces in plans for p in pieces})
        tenant = session.get(Tenant, tenant_id)
        brands = dict(
            session.execute(
                select(Brand.id, Brand.name).where(
                    Brand.id.in_({p[0] for p in plans}),
                    Brand.tenant_id == tenant_id,
                )
            ).all()
        )
        if tenant is None:
            return ready
        pieces_url = f"{public_app_url()}/drafts"
        for brand_id, stage, recipient, pieces in plans:
            if brand_id not in brands:
                continue
            pieces = [replace(p, thumbnail_url=thumbnails.get(p.draft_id)) for p in pieces]
            batch_id = uuid4()
            key = f"piece-warning/{stage.value}/{batch_id}"
            mail = replace(
                warning_mail(
                    recipient,
                    brand_id,
                    brands[brand_id],
                    pieces,
                    pieces_url=pieces_url,
                    timezone=tenant.timezone,
                    stage=stage,
                ),
                idempotency_key=key,
            )
            session.add(
                ContentDraftWarningBatch(
                    id=batch_id,
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    recipient=recipient,
                    stage=stage.value,
                    idempotency_key=key,
                    created_at=now,
                    payload={
                        "source_version": "piece-retention-v1",
                        "mail": asdict(mail),
                        "pieces": [
                            {"draft_id": str(p.draft_id), "deadline": p.deadline.isoformat()}
                            for p in pieces
                        ],
                    },
                )
            )
            ready.append(batch_id)
        session.flush()
        return ready
    # Exiting tenant_session commits the complete immutable payload BEFORE any HTTP.


def _claim_delivery(
    tenant_id: UUID,
    batch_id: UUID,
    now: datetime,
    verify: Verifier,
    scope: set[UUID] | None,
    lock_session: Session,
) -> _Delivery | None:
    with tenant_session(tenant_id) as session:
        if session is lock_session:
            raise RuntimeError("retention email needs independent worker transactions")
        batch = session.scalar(
            select(ContentDraftWarningBatch)
            .where(
                ContentDraftWarningBatch.id == batch_id,
                ContentDraftWarningBatch.tenant_id == tenant_id,
                ContentDraftWarningBatch.sent_at.is_(None),
                ContentDraftWarningBatch.cancelled_at.is_(None),
                ContentDraftWarningBatch.needs_review_at.is_(None),
            )
            .with_for_update()
        )
        if batch is None:
            return None
        snapshots = _snapshots(batch)
        ids = {draft_id for draft_id, _ in snapshots}
        if scope is not None and not ids.issubset(scope):
            return None
        if batch.first_attempt_at is not None and now - batch.first_attempt_at >= RETRY_WINDOW:
            _mark_review(batch, now)
            return None
        recipients, unavailable = _confirmed_recipients(session, tenant_id, verify, batch.recipient)
        if batch.recipient in unavailable:
            return None
        _, live = _live_pieces(session, tenant_id, now, ids)
        if batch.recipient not in recipients or not _batch_is_live(batch, live):
            if batch.first_attempt_at is not None:
                _mark_review(batch, now, "eligibility_changed")
            else:
                batch.cancelled_at = now
            return None
        mail = OutgoingMail(**batch.payload["mail"])
        if mail.idempotency_key != batch.idempotency_key:
            raise ValueError("warning batch provider key differs from its frozen payload")
        fresh_attempt = batch.first_attempt_at is None
        if fresh_attempt:
            batch.first_attempt_at = now
        delivery = _Delivery(
            batch.id,
            batch.brand_id,
            batch.recipient,
            batch.stage,
            tuple(snapshots),
            mail,
            fresh_attempt,
        )
        session.flush()
        return delivery
    # Exiting this context durably commits first_attempt_at BEFORE the HTTP call.


def _deliver_batch(
    tenant_id: UUID,
    batch_id: UUID,
    now: datetime,
    mailer: Mailer | None,
    verify: Verifier,
    scope: set[UUID] | None,
    lock_session: Session,
) -> int:
    delivery = _claim_delivery(tenant_id, batch_id, now, verify, scope, lock_session)
    if delivery is None:
        return 0
    try:
        provider_id = (mailer or default_mailer()).send(delivery.mail)
    except (MailNotConfigured, MailRejected):
        # Only clear a newly claimed attempt: an earlier timeout/crash may already
        # have been accepted, even if this subsequent request was rejected.
        if delivery.fresh_attempt:
            with tenant_session(tenant_id) as session:
                batch = session.get(ContentDraftWarningBatch, delivery.batch_id)
                if batch is not None:
                    batch.first_attempt_at = None
        logger.exception(
            "pieces.warning rejected tenant=%s brand=%s batch=%s",
            tenant_id,
            delivery.brand_id,
            delivery.batch_id,
        )
        return 0
    except Exception:
        logger.exception(
            "pieces.warning send failed tenant=%s brand=%s batch=%s",
            tenant_id,
            delivery.brand_id,
            delivery.batch_id,
        )
        return 0
    with tenant_session(tenant_id) as session:
        batch = session.get(ContentDraftWarningBatch, delivery.batch_id)
        if batch is None:
            raise RuntimeError("warning batch disappeared after delivery")
        session.execute(
            insert(ContentDraftPurgeWarning)
            .values(
                [
                    {
                        "tenant_id": tenant_id,
                        "draft_id": draft,
                        "deadline": due,
                        "recipient": delivery.recipient,
                        "stage": delivery.stage,
                        "notified_at": now,
                    }
                    for draft, due in delivery.pieces
                ]
            )
            .on_conflict_do_nothing()
        )
        batch.sent_at = now
        batch.provider_id = provider_id
    # Success ledger and outbox commit atomically; the outer tenant lock still holds.
    return 1


def send_tenant_warnings(
    tenant_id: UUID,
    now: datetime,
    *,
    mailer: Mailer | None = None,
    verify: Verifier = confirmed_email,
    draft_ids: Iterable[UUID] | None = None,
) -> int:
    """One aggregate per brand/member/stage, with durable and immutable retries."""
    scope = set(draft_ids) if draft_ids is not None else None
    with tenant_session(tenant_id) as lock_session:
        lock_session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"piece-warning:{tenant_id}"},
        )
        batches = _stage_batches(tenant_id, now, verify, scope, lock_session)
        sent = 0
        for batch_id in batches:
            sent += _deliver_batch(tenant_id, batch_id, now, mailer, verify, scope, lock_session)
        return sent


def run_piece_warnings(tenant_ids: Iterable[UUID] | None, now: datetime) -> None:
    scope = (
        list(dict.fromkeys(tenant_ids)) if tenant_ids is not None else discover_warning_tenants(now)
    )
    for tenant_id in scope:
        try:
            send_tenant_warnings(tenant_id, now)
        except Exception:
            logger.exception("pieces.warning tenant failed tenant=%s", tenant_id)


def retry_tenant_warnings(
    tenant_id: UUID,
    now: datetime,
    *,
    mailer: Mailer | None = None,
    verify: Verifier = confirmed_email,
    draft_ids: Iterable[UUID] | None = None,
) -> int:
    """Retry only frozen pending batches; never discover or stage new pieces."""
    scope = set(draft_ids) if draft_ids is not None else None
    with tenant_session(tenant_id) as lock_session:
        lock_session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"piece-warning:{tenant_id}"},
        )
        with tenant_session(tenant_id) as session:
            if session is lock_session:
                raise RuntimeError("retention email needs independent worker transactions")
            ids = list(
                session.scalars(
                    select(ContentDraftWarningBatch.id)
                    .where(
                        ContentDraftWarningBatch.tenant_id == tenant_id,
                        ContentDraftWarningBatch.sent_at.is_(None),
                        ContentDraftWarningBatch.cancelled_at.is_(None),
                        ContentDraftWarningBatch.needs_review_at.is_(None),
                    )
                    .order_by(ContentDraftWarningBatch.created_at, ContentDraftWarningBatch.id)
                )
            )
        return sum(
            _deliver_batch(tenant_id, batch_id, now, mailer, verify, scope, lock_session)
            for batch_id in ids
        )


def run_warning_retries(tenant_ids: Iterable[UUID] | None, now: datetime) -> None:
    if tenant_ids is None:
        with admin_session() as session:
            scope = list(
                session.scalars(
                    select(ContentDraftWarningBatch.tenant_id)
                    .where(
                        ContentDraftWarningBatch.sent_at.is_(None),
                        ContentDraftWarningBatch.cancelled_at.is_(None),
                        ContentDraftWarningBatch.needs_review_at.is_(None),
                    )
                    .distinct()
                )
            )
    else:
        scope = list(dict.fromkeys(tenant_ids))
    for tenant_id in scope:
        try:
            retry_tenant_warnings(tenant_id, now)
        except Exception:
            logger.exception("pieces.warning retry tenant failed tenant=%s", tenant_id)
