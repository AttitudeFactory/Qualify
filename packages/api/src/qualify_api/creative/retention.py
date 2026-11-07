"""Piece retention (m-24828907, ADR 39): a piece's files leave R2 90 days after it was
last used, and the app warns 15 days before.

The rule, in one place:

- **Deadline** = the later of (a) when the piece's current revision was generated
  (`MAX(image_assets.created_at)` over its R2 files) and (b) its last calendar event that
  is or was going out (`scheduled`, `publishing`, `published`), plus `RETENTION` (90 days).
  Regenerating or scheduling a piece again therefore gives it another 90 days, and a
  recurring piece with future occurrences keeps moving its own deadline.
  **(c) since 2026-11-04 (founder decision, m-24945888):** its last WhatsApp send from a
  chat — the newest `sent` `whatsapp_outbox` row whose `attachment->>'draft_id'` is the
  piece (migration 0123). Sending a piece to a customer is a use, like publishing it.
- **Held**: a piece with a `scheduled` or `publishing` event is never purged, whatever the
  date (criterion 3 — the publisher reads the bytes from R2 at publish time). `failed` and
  `cancelled` events do not hold or extend anything.
- **Scope**: only pieces whose files live in R2 under `t/{tenant}/generated/{draft_id}/`.
  Pieces made before 2026-10-06 (local `generated/{tenant}/…`) are out of scope: no
  warning, no purge.

What is deleted is the WHOLE folder of the piece (`PURGE_ROOT`), not the keys the
database still points at: a regeneration replaces the `image_assets` rows but leaves the
earlier revisions' files in R2, and the template's intermediate files never had a row.
The row, its copy and its provenance stay; `content_drafts.media_purged_at` says the
files are gone («Contenido eliminado») and every reader honours it.

Nothing here is a stored deadline: it is derived each time from what is already stored,
so it cannot go stale. The purge itself is idempotent — the folder is listed, deleted
(only with `execute=True`), logged in `content_draft_purges`, and the piece is marked
AFTER the delete succeeded; a crash in between is finished by the next run.

**Logical purge (m-24973446, founder 2026-11-06).** The production bucket refuses
deletes under `t/` (lock rule), so a real delete there never succeeds. When the bucket
REFUSES (`is_delete_refused`), the piece is still marked `media_purged_at` — the app
stops showing and serving it (`creative.purged_media`) — and also
`media_objects_pending_at`: its objects are still in R2. The log row says
`logical_only`. `purge_pending_objects` deletes them later, once deletes work; the
daily run probes it (stopping at the first refusal) and `just piece-purge --pending`
runs it by hand. Any other failure (R2 down, credentials) marks nothing, as before.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import DELETE_REFUSAL_CODES, is_bucket_refusal
from sqlalchemy import bindparam, exists, func, literal_column, select, update
from sqlalchemy.orm import Session

from qualify_api.creative.models import ContentDraft, ContentDraftPurge, ImageAsset
from qualify_api.planner.fsm import EventStatus
from qualify_api.planner.models import CalendarEvent

logger = logging.getLogger("qualify_api.creative.retention")

RETENTION_DAYS = 90
WARN_DAYS = 15
RETENTION = timedelta(days=RETENTION_DAYS)
WARN_BEFORE = timedelta(days=WARN_DAYS)

#: Events that extend a piece's life: it is going out, or it went out.
_EXTENDING = (
    EventStatus.SCHEDULED.value,
    EventStatus.PUBLISHING.value,
    EventStatus.PUBLISHED.value,
)
#: Events that hold a piece: the publisher will still read its files.
_HOLDING = (EventStatus.SCHEDULED.value, EventStatus.PUBLISHING.value)


def piece_prefix(tenant_id: UUID, draft_id: UUID) -> str:
    """The R2 folder holding every revision of a piece (`media.generated_object_key`)."""
    return f"t/{tenant_id}/generated/{draft_id}/"


def _generated_root(tenant_id: UUID) -> str:
    return f"t/{tenant_id}/generated/"


class RetentionState(StrEnum):
    NOT_APPLICABLE = "not_applicable"  # no R2 files (still drafting, failed, or pre-R2)
    ACTIVE = "active"  # more than WARN_DAYS left
    WARNING = "warning"  # WARN_DAYS or fewer left: «Descarga esta pieza»
    HELD = "held"  # past (or near) the deadline, but a live event still needs the files
    EXPIRED = "expired"  # the next purge deletes its files
    PURGED = "purged"  # «Contenido eliminado»


@dataclass(frozen=True)
class RetentionFacts:
    """What the rule reads about one piece — all already stored, nothing derived."""

    generated_at: datetime | None
    last_event_at: datetime | None = None
    #: (c) the last WhatsApp send of the piece from a chat (m-24945888).
    last_whatsapp_at: datetime | None = None
    held: bool = False
    purged_at: datetime | None = None


@dataclass(frozen=True)
class Retention:
    state: RetentionState
    deadline: datetime | None = None
    purged_at: datetime | None = None

    def days_left(self, now: datetime) -> int | None:
        """Whole days until the deadline (0 on the last day), or None without one."""
        if self.deadline is None:
            return None
        return max(0, (self.deadline - now).days)

    @property
    def is_purged(self) -> bool:
        return self.state is RetentionState.PURGED


NOT_APPLICABLE = Retention(RetentionState.NOT_APPLICABLE)


def deadline(facts: RetentionFacts) -> datetime | None:
    if facts.generated_at is None:
        return None
    uses = (facts.last_event_at, facts.last_whatsapp_at)
    base = max([facts.generated_at, *(use for use in uses if use is not None)])
    return base + RETENTION


def evaluate(facts: RetentionFacts, now: datetime) -> Retention:
    """The one retention verdict — the warning, the «Contenido eliminado» state and the
    purge all come from here, so they cannot disagree."""
    if facts.purged_at is not None:
        return Retention(RetentionState.PURGED, deadline(facts), facts.purged_at)
    due = deadline(facts)
    if due is None:
        return NOT_APPLICABLE
    if now < due - WARN_BEFORE:
        return Retention(RetentionState.ACTIVE, due)
    if facts.held:
        return Retention(RetentionState.HELD, due)
    if now < due:
        return Retention(RetentionState.WARNING, due)
    return Retention(RetentionState.EXPIRED, due)


# -- reading the facts ---------------------------------------------------------------------


def read_facts(
    session: Session, tenant_id: UUID, draft_ids: Iterable[UUID]
) -> dict[UUID, RetentionFacts]:
    """The facts of a batch of pieces in four queries, under the caller's RLS session.
    A piece absent from the result has no R2 files (→ `NOT_APPLICABLE`)."""
    ids = list(dict.fromkeys(draft_ids))
    if not ids:
        return {}
    generated = dict(
        session.execute(
            select(ImageAsset.draft_id, func.max(ImageAsset.created_at))
            .where(
                ImageAsset.draft_id.in_(ids),
                ImageAsset.object_key.startswith(_generated_root(tenant_id), autoescape=True),
            )
            .group_by(ImageAsset.draft_id)
        ).all()
    )
    purged = dict(
        session.execute(
            select(ContentDraft.id, ContentDraft.media_purged_at).where(
                ContentDraft.id.in_(ids), ContentDraft.media_purged_at.is_not(None)
            )
        ).all()
    )
    events = {
        post_id: (last, int(holding) > 0)
        for post_id, last, holding in session.execute(
            select(
                CalendarEvent.post_id,
                func.max(CalendarEvent.scheduled_at),
                func.count().filter(CalendarEvent.status.in_(_HOLDING)),
            )
            .where(CalendarEvent.post_id.in_(ids), CalendarEvent.status.in_(_EXTENDING))
            .group_by(CalendarEvent.post_id)
        ).all()
    }
    whatsapp = _last_whatsapp_sends(session, ids)
    facts: dict[UUID, RetentionFacts] = {}
    for draft_id in set(generated) | set(purged):
        last_event_at, held = events.get(draft_id, (None, False))
        facts[draft_id] = RetentionFacts(
            generated_at=generated.get(draft_id),
            last_event_at=last_event_at,
            last_whatsapp_at=whatsapp.get(draft_id),
            held=held,
            purged_at=purged.get(draft_id),
        )
    return facts


def _last_whatsapp_sends(session: Session, ids: Sequence[UUID]) -> dict[UUID, datetime]:
    """(c): per piece, when it last went out over WhatsApp from a chat — derived from the
    outbox rows that reference it (0123 `attachment`), never a stored flag. Only `sent`
    rows count: a queued or refused send is not a use. Served by
    `ix_wa_outbox_attachment_draft`; RLS bounds it to the caller's tenant."""
    from qualify_api.whatsapp.models import WhatsAppOutboxItem  # noqa: PLC0415

    # Literal SQL, not bound parameters: the same text as the partial index
    # (`(attachment->>'draft_id')` WHERE `attachment ? 'draft_id'`), so the planner uses
    # it and the GROUP BY matches the SELECT expression exactly.
    draft_key = literal_column("(whatsapp_outbox.attachment->>'draft_id')")
    rows = session.execute(
        select(draft_key, func.max(WhatsAppOutboxItem.sent_at))
        .where(
            literal_column("whatsapp_outbox.attachment ? 'draft_id'"),
            draft_key.in_(bindparam("wa_draft_ids", [str(i) for i in ids], expanding=True)),
            WhatsAppOutboxItem.status == "sent",
            WhatsAppOutboxItem.sent_at.is_not(None),
        )
        .group_by(draft_key)
    ).all()
    return {UUID(draft): sent_at for draft, sent_at in rows}


def retention_of(
    session: Session, tenant_id: UUID, draft_ids: Iterable[UUID], now: datetime
) -> dict[UUID, Retention]:
    """`evaluate` over `read_facts` — what a screen shows for each piece."""
    ids = list(draft_ids)
    facts = read_facts(session, tenant_id, ids)
    return {draft_id: evaluate(facts[draft_id], now) for draft_id in ids if draft_id in facts}


# -- the purge -----------------------------------------------------------------------------


class PrefixDeleter(Protocol):
    """The slice of `ObjectGate` the purge uses."""

    def delete_prefix(self, tenant_id: UUID, prefix: str, *, execute: bool = False) -> object: ...


def is_delete_refused(exc: BaseException) -> bool:
    """Whether `exc` says the bucket refused the delete (m-24973446) — as opposed to an
    outage, which must keep marking nothing.

    The store's own verdict first: `R2ObjectStore.delete_keys` raises `DeleteRefused`
    (VE-12, m-24921060) and `is_bucket_refusal` tells a lock/permission refusal from a
    transient per-key error. A raw botocore `ClientError` with a refusal code (a store
    that does not translate it) counts too."""
    if is_bucket_refusal(exc):
        return True
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = (response.get("Error") or {}).get("Code")
        return str(code) in DELETE_REFUSAL_CODES
    return False


@dataclass(frozen=True)
class PieceOutcome:
    draft_id: UUID
    objects: int
    bytes: int
    deadline: datetime
    #: m-24973446: marked purged for the app, but the bucket refused the delete.
    logical_only: bool = False


@dataclass
class PurgeReport:
    tenant_id: UUID
    executed: bool
    candidates: int = 0
    purged: list[PieceOutcome] = field(default_factory=list)
    errors: list[tuple[UUID, str]] = field(default_factory=list)
    #: The daily probe of `purge_pending_objects` (only with `execute=True`).
    pending: PendingReport | None = None

    @property
    def objects(self) -> int:
        return sum(piece.objects for piece in self.purged)

    @property
    def bytes(self) -> int:
        return sum(piece.bytes for piece in self.purged)

    @property
    def logical_only(self) -> int:
        """How many pieces were purged for the app only (their objects stayed in R2)."""
        return sum(1 for piece in self.purged if piece.logical_only)


@dataclass
class PendingReport:
    """One pass of `purge_pending_objects` over a tenant."""

    tenant_id: UUID
    executed: bool
    candidates: int = 0
    deleted: list[PieceOutcome] = field(default_factory=list)
    #: Still refused by the bucket: the pass stopped at the first one.
    refused: int = 0
    errors: list[tuple[UUID, str]] = field(default_factory=list)


#: At most this many pieces per tenant per run: a backlog drains over a few days instead
#: of one run holding the worker for minutes.
DEFAULT_PURGE_LIMIT = 200


def _candidate_ids(session: Session, tenant_id: UUID, now: datetime, limit: int) -> list[UUID]:
    """Pieces not yet purged whose newest R2 file is older than the retention window — a
    cheap superset; `evaluate` then applies events and holds."""
    newest = func.max(ImageAsset.created_at)
    return list(
        session.scalars(
            select(ImageAsset.draft_id)
            .join(ContentDraft, ContentDraft.id == ImageAsset.draft_id)
            .where(
                ContentDraft.media_purged_at.is_(None),
                ImageAsset.object_key.startswith(_generated_root(tenant_id), autoescape=True),
            )
            .group_by(ImageAsset.draft_id)
            .having(newest <= now - RETENTION)
            .order_by(newest)
            .limit(limit)
        ).all()
    )


def _already_logged_dry_run(session: Session, draft_id: UUID) -> bool:
    return bool(
        session.scalar(
            select(
                exists().where(
                    ContentDraftPurge.draft_id == draft_id, ContentDraftPurge.dry_run.is_(True)
                )
            )
        )
    )


def purge_expired_pieces(
    *,
    tenant_id: UUID,
    gate: PrefixDeleter,
    now: datetime,
    execute: bool,
    limit: int = DEFAULT_PURGE_LIMIT,
) -> PurgeReport:
    """Delete (with `execute=True`) or report (dry run) the R2 files of every expired,
    unheld piece of ONE tenant. Everything goes through `tenant_session(tenant_id)`; one
    piece failing never stops the others.

    A dry run logs a piece once (the first run that finds it), so weeks of dry runs in
    production show what WOULD go without one row per piece per day."""
    report = PurgeReport(tenant_id=tenant_id, executed=execute)
    if execute:
        # m-24973446: the daily retry of pieces whose objects the bucket kept. A probe:
        # it stops at the first refusal, so a locked bucket costs one call per day. Its
        # failure never costs the day's expiry purge below.
        try:
            report.pending = purge_pending_objects(
                tenant_id=tenant_id, gate=gate, now=now, execute=True, limit=limit, probe=True
            )
        except Exception:  # noqa: BLE001 — logged; the expiry purge still runs
            logger.exception("pending purge probe failed tenant=%s", tenant_id)
    with tenant_session(tenant_id) as session:
        ids = _candidate_ids(session, tenant_id, now, limit)
        verdicts = retention_of(session, tenant_id, ids, now)
    expired = [
        (draft_id, verdict.deadline)
        for draft_id, verdict in verdicts.items()
        if verdict.state is RetentionState.EXPIRED and verdict.deadline is not None
    ]
    report.candidates = len(expired)
    for draft_id, due in expired:
        prefix = piece_prefix(tenant_id, draft_id)
        logical = False
        try:
            try:
                found = gate.delete_prefix(tenant_id, prefix, execute=execute)
            except Exception as exc:
                if not (execute and is_delete_refused(exc)):
                    raise
                # m-24973446: the bucket keeps the objects; the app purges the piece
                # anyway. Listed again so the log says what is still there.
                logger.warning(
                    "piece purge refused by the bucket, purging for the app only "
                    "tenant=%s draft=%s",
                    tenant_id,
                    draft_id,
                )
                found = gate.delete_prefix(tenant_id, prefix, execute=False)
                logical = True
            else:
                kept = _kept_after_delete(gate, tenant_id, prefix) if execute else None
                if kept is not None:
                    # A delete the store "accepted" but did not carry out (the bucket's
                    # answer to its lock rule was never measured): same as a refusal.
                    logger.warning(
                        "piece purge left objects in R2, purging for the app only "
                        "tenant=%s draft=%s",
                        tenant_id,
                        draft_id,
                    )
                    found, logical = kept, True
            objects, size = int(found.objects), int(found.bytes)  # type: ignore[attr-defined]
            with tenant_session(tenant_id) as session:
                if execute or not _already_logged_dry_run(session, draft_id):
                    session.add(
                        ContentDraftPurge(
                            tenant_id=tenant_id,
                            draft_id=draft_id,
                            prefix=prefix,
                            object_count=objects,
                            byte_count=size,
                            dry_run=not execute,
                            logical_only=logical,
                            expired_at=due,
                            purged_at=now,
                        )
                    )
                if execute:
                    # Guarded: a piece marked meanwhile (another run) is not re-marked.
                    session.execute(
                        update(ContentDraft)
                        .where(ContentDraft.id == draft_id, ContentDraft.media_purged_at.is_(None))
                        .values(
                            media_purged_at=now,
                            media_objects_pending_at=now if logical else None,
                        )
                    )
        except Exception as exc:  # noqa: BLE001 — one piece must not stop the rest
            logger.exception("piece purge failed tenant=%s draft=%s", tenant_id, draft_id)
            report.errors.append((draft_id, type(exc).__name__))
            continue
        report.purged.append(PieceOutcome(draft_id, objects, size, due, logical_only=logical))
    return report


def _kept_after_delete(gate: PrefixDeleter, tenant_id: UUID, prefix: str) -> object | None:
    """What the store still lists under `prefix` after an executed delete, or None when
    it is empty. R2's answer to its own lock rule was never measured: a delete that
    returns without error but keeps the objects must not read as a real delete."""
    left = gate.delete_prefix(tenant_id, prefix, execute=False)
    return left if int(left.objects) > 0 else None  # type: ignore[attr-defined]


def purge_pending_objects(
    *,
    tenant_id: UUID,
    gate: PrefixDeleter,
    now: datetime,
    execute: bool,
    limit: int = DEFAULT_PURGE_LIMIT,
    probe: bool = False,
) -> PendingReport:
    """Delete (with `execute=True`) or list (dry run) the objects R2 kept of pieces
    already purged for the app (`media_objects_pending_at`, m-24973446). On success the
    pending mark is cleared and a log row (`logical_only=False`) records the real delete;
    a refusal leaves the mark for the next pass. With `probe=True` (the daily run) the
    pass stops at the first refusal: the bucket is still locked, nothing else would go.

    The piece stays purged either way — this pass never touches `media_purged_at`."""
    report = PendingReport(tenant_id=tenant_id, executed=execute)
    with tenant_session(tenant_id) as session:
        pending = session.execute(
            select(ContentDraft.id, ContentDraft.media_purged_at)
            .where(ContentDraft.media_objects_pending_at.is_not(None))
            .order_by(ContentDraft.media_objects_pending_at, ContentDraft.id)
            .limit(limit)
        ).all()
    report.candidates = len(pending)
    for draft_id, purged_at in pending:
        prefix = piece_prefix(tenant_id, draft_id)
        try:
            found = gate.delete_prefix(tenant_id, prefix, execute=execute)
        except Exception as exc:  # noqa: BLE001 — one piece must not stop the rest
            if is_delete_refused(exc):
                report.refused += 1
                if probe:
                    break
                continue
            logger.exception("pending purge failed tenant=%s draft=%s", tenant_id, draft_id)
            report.errors.append((draft_id, type(exc).__name__))
            continue
        if execute:
            try:
                kept = _kept_after_delete(gate, tenant_id, prefix)
            except Exception as exc:  # noqa: BLE001 — cannot confirm: keep the mark
                logger.exception(
                    "pending purge re-list failed tenant=%s draft=%s", tenant_id, draft_id
                )
                report.errors.append((draft_id, type(exc).__name__))
                continue
            if kept is not None:  # "accepted" but kept: a refusal by another name
                report.refused += 1
                if probe:
                    break
                continue
        objects, size = int(found.objects), int(found.bytes)  # type: ignore[attr-defined]
        outcome = PieceOutcome(draft_id, objects, size, purged_at)
        if execute:
            try:
                with tenant_session(tenant_id) as session:
                    session.add(
                        ContentDraftPurge(
                            tenant_id=tenant_id,
                            draft_id=draft_id,
                            prefix=prefix,
                            object_count=objects,
                            byte_count=size,
                            dry_run=False,
                            logical_only=False,
                            # Not the deadline: the physical pass carries the piece's
                            # `media_purged_at` (when the app purged it); the deadline is
                            # in the earlier `logical_only` row of the same piece.
                            expired_at=purged_at,
                            purged_at=now,
                        )
                    )
                    session.execute(
                        update(ContentDraft)
                        .where(
                            ContentDraft.id == draft_id,
                            ContentDraft.media_objects_pending_at.is_not(None),
                        )
                        .values(media_objects_pending_at=None)
                    )
            except Exception as exc:  # noqa: BLE001 — the next pass deletes 0 and clears it
                logger.exception(
                    "pending purge mark failed tenant=%s draft=%s", tenant_id, draft_id
                )
                report.errors.append((draft_id, type(exc).__name__))
                continue
        report.deleted.append(outcome)
    if report.candidates:
        logger.info(
            "pieces.pending tenant=%s execute=%s candidates=%d deleted=%d refused=%d errors=%d",
            tenant_id,
            execute,
            report.candidates,
            len(report.deleted),
            report.refused,
            len(report.errors),
        )
    return report


def tenants_with_expired_pieces(now: datetime) -> list[UUID]:
    """PRODUCTION discovery for `--all-tenants`: ids of tenants with at least one unpurged
    piece whose newest R2 file is older than the window. Same narrow terms as
    `planner.discovery.DiscoveredTenants`: read-only, ids only, `qualify_admin` already
    holds SELECT on both tables (0009); everything after it is `tenant_session`."""
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415 — production only

    newest = func.max(ImageAsset.created_at)
    with admin_session() as session:
        rows: Sequence[UUID] = session.scalars(
            select(ImageAsset.tenant_id)
            .join(ContentDraft, ContentDraft.id == ImageAsset.draft_id)
            .where(
                ContentDraft.media_purged_at.is_(None),
                ImageAsset.object_key.like("t/%/generated/%"),
            )
            .group_by(ImageAsset.tenant_id, ImageAsset.draft_id)
            .having(newest <= now - RETENTION)
        ).all()
    return sorted(set(rows) | set(tenants_with_pending_objects()), key=str)


def tenants_with_pending_objects() -> list[UUID]:
    """PRODUCTION discovery (m-24973446): tenants with pieces purged for the app whose
    objects are still in R2 — same narrow terms as `tenants_with_expired_pieces`."""
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415 — production only

    with admin_session() as session:
        rows: Sequence[UUID] = session.scalars(
            select(ContentDraft.tenant_id)
            .where(ContentDraft.media_objects_pending_at.is_not(None))
            .distinct()
        ).all()
    return sorted(set(rows), key=str)


__all__ = [
    "DEFAULT_PURGE_LIMIT",
    "PendingReport",
    "is_delete_refused",
    "purge_pending_objects",
    "tenants_with_pending_objects",
    "NOT_APPLICABLE",
    "RETENTION",
    "RETENTION_DAYS",
    "WARN_BEFORE",
    "WARN_DAYS",
    "PieceOutcome",
    "PurgeReport",
    "Retention",
    "RetentionFacts",
    "RetentionState",
    "deadline",
    "evaluate",
    "piece_prefix",
    "purge_expired_pieces",
    "read_facts",
    "retention_of",
    "tenants_with_expired_pieces",
]
