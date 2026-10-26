"""Daily email warnings before piece retention deletes files (m-24842840)."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from uuid import UUID

from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from qualify_api.auth.confirmed_email import confirmed_email
from qualify_api.creative.models import ContentDraft, ContentDraftPurgeWarning, ImageAsset
from qualify_api.creative.retention import Retention, RetentionState, retention_of
from qualify_api.mail import Mailer, default_mailer
from qualify_api.mail.config import public_app_url
from qualify_api.mail.retention import ExpiringPiece, WarningStage, warning_mail
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User

logger = logging.getLogger(__name__)


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
    """One relevant stage per pass; never warn for held, purged or expired pieces."""
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
    """An unchanged deadline is suppressed; renewal creates a new warning identity."""
    return [
        piece for piece in pieces if (piece.draft_id, piece.deadline, stage.value) not in recorded
    ]


def send_tenant_warnings(
    tenant_id: UUID,
    now: datetime,
    *,
    mailer: Mailer | None = None,
    verify: Callable[[UUID, str], str | None] = confirmed_email,
    draft_ids: Iterable[UUID] | None = None,
) -> int:
    """One aggregate per brand/member. Successful recipients survive partial failures.

    Tenant members have access to all its brands in the current authorization model.
    A transaction advisory lock serializes this tenant's daily warning runs. Provider
    idempotency keys cover a retry after delivery but before the ledger commit.
    """
    sent = 0
    with tenant_session(tenant_id) as session:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"piece-warning:{tenant_id}"},
        )
        statement = select(ContentDraft).where(
            ContentDraft.tenant_id == tenant_id, ContentDraft.media_purged_at.is_(None)
        )
        if draft_ids is not None:
            statement = statement.where(ContentDraft.id.in_(list(draft_ids)))
        drafts = list(session.scalars(statement))
        verdicts = retention_of(session, tenant_id, [d.id for d in drafts], now)
        groups: dict[tuple[UUID, WarningStage], list[ExpiringPiece]] = defaultdict(list)
        for draft in drafts:
            verdict = verdicts.get(draft.id)
            stage = warning_stage(verdict, now)
            if stage is None:
                continue
            assert verdict is not None and verdict.deadline is not None
            # R2 object keys are private; only include an already public HTTPS thumbnail.
            thumbnail = session.scalar(
                select(ImageAsset.media_url)
                .where(ImageAsset.draft_id == draft.id)
                .order_by(ImageAsset.created_at.desc())
                .limit(1)
            )
            groups[draft.brand_id, stage].append(
                ExpiringPiece(
                    draft.id,
                    draft.title,
                    verdict.deadline,
                    thumbnail if thumbnail and thumbnail.startswith("https://") else None,
                )
            )
        if not groups:
            return 0
        members = session.scalars(
            select(User)
            .join(TenantMember, TenantMember.user_id == User.id)
            .where(User.auth_user_id.is_not(None), TenantMember.tenant_id == tenant_id)
        ).all()
        recipients = set()
        for member in members:
            try:
                email = verify(member.auth_user_id, member.email)
            except Exception:
                logger.exception(
                    "pieces.warning verification failed tenant=%s member=%s", tenant_id, member.id
                )
                continue
            if email:
                recipients.add(email.casefold())
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            return 0
        for (brand_id, stage), pieces in groups.items():
            brand = session.get(Brand, brand_id)
            if brand is None:
                continue
            for recipient in sorted(recipients):
                recorded = set(
                    session.execute(
                        select(
                            ContentDraftPurgeWarning.draft_id,
                            ContentDraftPurgeWarning.deadline,
                            ContentDraftPurgeWarning.stage,
                        ).where(
                            ContentDraftPurgeWarning.recipient == recipient,
                            ContentDraftPurgeWarning.tenant_id == tenant_id,
                        )
                    ).all()
                )
                pending = pending_pieces(pieces, recorded, stage)
                if not pending:
                    continue
                try:
                    (mailer or default_mailer()).send(
                        warning_mail(
                            recipient,
                            brand_id,
                            brand.name,
                            pending,
                            pieces_url=f"{public_app_url()}/drafts",
                            timezone=tenant.timezone,
                            stage=stage,
                        )
                    )
                except Exception:
                    logger.exception(
                        "pieces.warning send failed tenant=%s brand=%s", tenant_id, brand_id
                    )
                    continue
                for piece in pending:
                    session.execute(
                        insert(ContentDraftPurgeWarning)
                        .values(
                            tenant_id=tenant_id,
                            draft_id=piece.draft_id,
                            deadline=piece.deadline,
                            recipient=recipient,
                            stage=stage.value,
                            notified_at=now,
                        )
                        .on_conflict_do_nothing()
                    )
                sent += 1
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
