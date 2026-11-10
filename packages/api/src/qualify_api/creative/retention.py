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
  date (criterion 3 — the publisher reads the bytes from R2 at publish time). **Since
  2026-11-08 (m-24945889)** a piece marked «Promoción de la semana»
  (`whatsapp_weekly_promotions`, 0140) is held the same way while the mark lasts. Holds
  are read when a purge pass starts: a piece marked (or scheduled) during a pass is safe
  from the next one. `failed` and
  `cancelled` events do not hold or extend anything.
- **Scope**: only pieces whose files live in R2 under `t/{tenant}/generated/{draft_id}/`.
  Pieces made before 2026-10-06 (local `generated/{tenant}/…`) are out of scope: no
  warning, no purge.
- **Parts of a video by parts (2026-11-09, m-24921069, ADR 44).** A part is a child
  draft (`parent_draft_id`) with no calendar events of its own, so it is never judged
  alone: its deadline, hold and state are its video's, and the video's facts are those
  of the whole family (`family_facts`: the newest file among the video and its parts,
  the uses and holds of any of them, the video's purge mark). A part is never a purge
  candidate and never gets a warning (`retention_mail` lists only top-level pieces: the
  video's warning covers its parts). Purging the video purges its parts — each part's
  own folder `t/{tenant}/generated/{part_id}/`, deleted before the video's and marked
  in the same transaction as the video, real or logical-only, so a retry finishes the
  family. The joined video already lives under the video's own folder. Making,
  changing or restoring a part under a purged video is refused at the source
  (`parts.refuse_if_parent_purged`, under the video's row lock). The sweep of a part
  left unpurged under a purged video — purged at the next run whatever its own dates,
  the video not deleted or logged again — is only a safety net for races (a part
  written between `_unpurged_parts` and the mark, or a write path that skips the
  fence). Files that land after the request was accepted are handled too: a generation
  finishing for a purged piece or a part of a purged video attaches nothing and leaves
  its folder pending (`PostgresContentRepository.finish_generation`), and a member whose
  generation was written while its folder was being deleted is marked with its objects
  pending; `purge_pending_objects` deletes both. The mark locks the video's row first,
  then its parts', like the part changes.

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
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import DELETE_REFUSAL_CODES, is_bucket_refusal
from sqlalchemy import (
    ColumnElement,
    Select,
    bindparam,
    exists,
    func,
    literal_column,
    or_,
    select,
    update,
)
from sqlalchemy.orm import Session, aliased

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
    """The facts of a batch of pieces, under the caller's RLS session. A piece absent
    from the result has no R2 files (→ `NOT_APPLICABLE`).

    m-24921069: a part of a video by parts (a child draft) is read as its video — the
    facts of the whole family (`family_facts`) — so a part never has a deadline of its
    own, and the video's deadline already counts its parts' files."""
    ids = list(dict.fromkeys(draft_ids))
    if not ids:
        return {}
    root_of = {
        draft_id: parent_id or draft_id
        for draft_id, parent_id in session.execute(
            select(ContentDraft.id, ContentDraft.parent_draft_id).where(ContentDraft.id.in_(ids))
        ).all()
    }
    roots = list(dict.fromkeys(root_of.get(draft_id, draft_id) for draft_id in ids))
    parts_of = _parts_of(session, roots)
    every_part = _parts_of(session, roots, with_removed=True)
    family = list(dict.fromkeys([*ids, *roots, *(p for ps in every_part.values() for p in ps)]))
    own = _own_facts(session, tenant_id, family)
    folded: dict[UUID, RetentionFacts | None] = {}
    for root in roots:
        whole = family_facts(own.get(root), [own[p] for p in parts_of.get(root, ()) if p in own])
        if whole is None or whole.generated_at is None:
            # m-24985192: only a removed part holds files — they date the family, so the
            # purge still takes them (as `_family_candidates` falls back to them)
            every = [own[p] for p in every_part.get(root, ()) if p in own]
            whole = family_facts(own.get(root), every) or whole
        folded[root] = whole
    facts: dict[UUID, RetentionFacts] = {}
    for draft_id in ids:
        root = root_of.get(draft_id, draft_id)
        if root == draft_id:
            whole = folded.get(root)
        else:
            mine = own.get(draft_id)
            whole = part_facts(folded.get(root), mine.purged_at if mine is not None else None)
        if whole is not None:
            facts[draft_id] = whole
    return facts


def _parts_of(
    session: Session, parent_ids: Sequence[UUID], *, with_removed: bool = False
) -> dict[UUID, list[UUID]]:
    """The parts (child drafts, ADR 44) of each video by parts in `parent_ids` whose
    files count for the video's deadline. m-24985192: a part its owner removed («Quitar
    parte») is no longer part of the video — its files neither move nor hold the
    deadline (unless they are the family's only files: `with_removed`) — but the purge
    still takes them with the video (`_unpurged_parts`)."""
    parts: dict[UUID, list[UUID]] = defaultdict(list)
    if not parent_ids:
        return parts
    query = select(ContentDraft.id, ContentDraft.parent_draft_id).where(
        ContentDraft.parent_draft_id.in_(list(parent_ids))
    )
    if not with_removed:
        query = query.where(ContentDraft.part_removed_at.is_(None))
    for part_id, parent_id in session.execute(query.order_by(ContentDraft.part_index)).all():
        parts[parent_id].append(part_id)
    return parts


def family_facts(
    parent: RetentionFacts | None, parts: Sequence[RetentionFacts]
) -> RetentionFacts | None:
    """m-24921069: a video by parts is ONE piece for retention. Its newest file is the
    newest of the video's AND its parts' files (regenerating a part is a use of the
    video); its uses (events, WhatsApp sends) and holds are the video's — or a part's,
    should one ever have any; whether it is purged is the video's. None when the family
    has no R2 file and is not purged (→ `NOT_APPLICABLE`). A piece without parts gets
    exactly its own facts."""
    members = [member for member in (parent, *parts) if member is not None]
    generated_at = _newest(member.generated_at for member in members)
    purged_at = parent.purged_at if parent is not None else None
    if generated_at is None and purged_at is None:
        return None
    return RetentionFacts(
        generated_at=generated_at,
        last_event_at=_newest(member.last_event_at for member in members),
        last_whatsapp_at=_newest(member.last_whatsapp_at for member in members),
        held=any(member.held for member in members),
        purged_at=purged_at,
    )


def part_facts(
    video: RetentionFacts | None, own_purged_at: datetime | None
) -> RetentionFacts | None:
    """m-24921069: the facts of one part are its video's (`family_facts`), so its
    deadline, hold and warning window are the video's. A part already marked purged
    reads as purged even if its video is not (yet)."""
    if own_purged_at is None or (video is not None and video.purged_at is not None):
        return video
    if video is None:
        return RetentionFacts(generated_at=None, purged_at=own_purged_at)
    return replace(video, purged_at=own_purged_at)


def _newest(values: Iterable[datetime | None]) -> datetime | None:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def _own_facts(
    session: Session, tenant_id: UUID, ids: Sequence[UUID]
) -> dict[UUID, RetentionFacts]:
    """Each draft's OWN facts: one entry per draft with anything stored (an R2 file, a
    purge mark, an extending event, a WhatsApp send or a weekly mark)."""
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
    promoted = _weekly_promotions(session, ids)
    facts: dict[UUID, RetentionFacts] = {}
    for draft_id in set(generated) | set(purged) | set(events) | set(whatsapp) | promoted:
        last_event_at, held = events.get(draft_id, (None, False))
        facts[draft_id] = RetentionFacts(
            generated_at=generated.get(draft_id),
            last_event_at=last_event_at,
            last_whatsapp_at=whatsapp.get(draft_id),
            held=held or draft_id in promoted,
            purged_at=purged.get(draft_id),
        )
    return facts


def _weekly_promotions(session: Session, ids: Sequence[UUID]) -> set[UUID]:
    """m-24945889: the pieces marked «Promoción de la semana» — held like a scheduled
    piece while marked (the owner sends it from the chat at any moment). RLS-bound."""
    from qualify_api.whatsapp.models import WhatsAppWeeklyPromotion  # noqa: PLC0415

    return set(
        session.scalars(
            select(WhatsAppWeeklyPromotion.draft_id).where(
                WhatsAppWeeklyPromotion.draft_id.in_(list(ids))
            )
        ).all()
    )


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
    """Units (m-24921069): `candidates` and `errors` count PIECES — a video by parts is
    one piece; `purged` (and so `folders`, `logical_only`, `objects`, `bytes`) counts
    FOLDERS — one per draft whose R2 folder was purged, the video and each of its parts.
    For a piece without parts the two are the same."""

    tenant_id: UUID
    executed: bool
    #: Pieces found expired (a video with its parts counts once).
    candidates: int = 0
    #: One outcome per purged FOLDER (a video by parts gives one per part + the video).
    purged: list[PieceOutcome] = field(default_factory=list)
    #: One entry per PIECE that failed (keyed by the video for a video by parts).
    errors: list[tuple[UUID, str]] = field(default_factory=list)
    #: The daily probe of `purge_pending_objects` (only with `execute=True`).
    pending: PendingReport | None = None

    @property
    def folders(self) -> int:
        """How many piece folders were purged (`len(purged)`)."""
        return len(self.purged)

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
    cheap superset; `evaluate` then applies events and holds.

    m-24921069: a part's files count for its video (`COALESCE(parent_draft_id, id)`), so
    a part is never a candidate of its own — only its video is (`_family_candidates`)."""
    return list(
        session.scalars(
            _family_candidates(
                ImageAsset.object_key.startswith(_generated_root(tenant_id), autoescape=True),
                now,
            )
            .with_only_columns(func.coalesce(ContentDraft.parent_draft_id, ContentDraft.id))
            .limit(limit)
        ).all()
    )


def _family_candidates(in_scope: ColumnElement[bool], now: datetime) -> Select:
    """The families (a piece, or a video with its parts) the purge must look at, one row
    per family, oldest first. A family is a candidate while ANY member (the video or a
    part) is not purged yet, and either:

    - its video is not purged and the newest file of the family is past the window
      (`evaluate` then applies uses and holds), or
    - its video IS purged (m-24921069): a part left behind — made, regenerated or added
      after its video went — goes now, whatever its own dates. A part is never kept
      without its video."""
    owner = aliased(ContentDraft)
    piece = func.coalesce(ContentDraft.parent_draft_id, ContentDraft.id)
    # m-24985192: a part its owner removed does not date its video (`_parts_of`) — unless
    # it holds the family's only files: then they are dated by themselves, never kept in
    # R2 forever
    newest = func.coalesce(
        func.max(ImageAsset.created_at).filter(ContentDraft.part_removed_at.is_(None)),
        func.max(ImageAsset.created_at),
    )
    return (
        select(piece, ImageAsset.tenant_id)
        .select_from(ImageAsset)
        .join(ContentDraft, ContentDraft.id == ImageAsset.draft_id)
        .join(owner, (owner.tenant_id == ContentDraft.tenant_id) & (owner.id == piece))
        # Rows of a fully purged family never reach the GROUP BY: only members still
        # unpurged (or any member of a video not purged yet) can make a candidate.
        .where(
            in_scope,
            or_(owner.media_purged_at.is_(None), ContentDraft.media_purged_at.is_(None)),
        )
        .group_by(ImageAsset.tenant_id, piece, owner.media_purged_at)
        .having(
            or_(
                owner.media_purged_at.is_(None) & (newest <= now - RETENTION),
                owner.media_purged_at.is_not(None)
                & func.bool_or(ContentDraft.media_purged_at.is_(None)),
            )
        )
        .order_by(newest)
    )


def _expired_families(
    facts: dict[UUID, RetentionFacts], ids: Sequence[UUID], now: datetime
) -> list[tuple[UUID, datetime, bool]]:
    """`(piece, deadline, video already purged)` for every candidate the purge acts on.
    A piece (or video) not yet purged goes when `evaluate` says EXPIRED. A video already
    purged takes its left-behind parts with it at once (m-24921069); their log rows carry
    the family's deadline, or the video's purge time when it has no file left to date."""
    out: list[tuple[UUID, datetime, bool]] = []
    for draft_id in ids:
        found = facts.get(draft_id)
        if found is None:
            continue
        if found.purged_at is not None:
            out.append((draft_id, deadline(found) or found.purged_at, True))
            continue
        verdict = evaluate(found, now)
        if verdict.state is RetentionState.EXPIRED and verdict.deadline is not None:
            out.append((draft_id, verdict.deadline, False))
    return out


def _unpurged_parts(session: Session, parent_ids: Sequence[UUID]) -> dict[UUID, list[UUID]]:
    """m-24921069: the parts of each video in `parent_ids` that are not purged yet — the
    folders that go with their video."""
    parts: dict[UUID, list[UUID]] = defaultdict(list)
    if not parent_ids:
        return parts
    for part_id, parent_id in session.execute(
        select(ContentDraft.id, ContentDraft.parent_draft_id)
        .where(
            ContentDraft.parent_draft_id.in_(list(parent_ids)),
            ContentDraft.media_purged_at.is_(None),
        )
        .order_by(ContentDraft.part_index)
    ).all():
        parts[parent_id].append(part_id)
    return parts


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
        expired = _expired_families(read_facts(session, tenant_id, ids), ids, now)
        parts_of = _unpurged_parts(session, [draft_id for draft_id, _, _ in expired])
    report.candidates = len(expired)
    for draft_id, due, video_purged in expired:
        # m-24921069: the parts' folders go first and the video's last; every member still
        # unpurged is marked in ONE transaction after all deletes, so a crash or a failing
        # folder leaves the family unmarked and the next run finishes it (a folder already
        # emptied lists 0 objects). A video already purged is not deleted or logged again.
        members = [*parts_of.get(draft_id, ()), *(() if video_purged else (draft_id,))]
        if not members:
            continue
        try:
            with tenant_session(tenant_id) as session:
                # The files each member has before its folder is deleted: a generation
                # that lands while we delete is caught below, never lost in R2.
                known = set(
                    session.scalars(
                        select(ImageAsset.id).where(ImageAsset.draft_id.in_(members))
                    ).all()
                )
            outcomes = [
                _purge_folder(gate, tenant_id, member, due, execute=execute) for member in members
            ]
            with tenant_session(tenant_id) as session:
                late: set[UUID] = set()
                if execute:
                    # Lock order of `parts.lock_parent_for_part_change` and the part
                    # changes: the video's row first, then its parts' (part order). FOR NO
                    # KEY UPDATE (`key_share=True`), like the UPDATEs below: a part's
                    # generation finishing meanwhile holds the part and inserts runs whose
                    # foreign keys take KEY SHARE on the video (`mark_parent_dirty`) — a
                    # plain FOR UPDATE on the video would deadlock with it.
                    session.execute(
                        select(ContentDraft.id)
                        .where(ContentDraft.id == draft_id)
                        .with_for_update(key_share=True)
                    ).all()
                    session.execute(
                        select(ContentDraft.id)
                        .where(ContentDraft.id.in_(members), ContentDraft.id != draft_id)
                        .order_by(ContentDraft.part_index)
                        .with_for_update(key_share=True)
                    ).all()
                    # m-24921069: a member whose generation was written after we listed it
                    # keeps files in its folder — purged, with its objects pending, so
                    # `purge_pending_objects` deletes them.
                    late = set(
                        session.scalars(
                            select(ImageAsset.draft_id).where(
                                ImageAsset.draft_id.in_(members), ImageAsset.id.not_in(known)
                            )
                        ).all()
                    )
                for outcome in outcomes:
                    if execute or not _already_logged_dry_run(session, outcome.draft_id):
                        session.add(
                            ContentDraftPurge(
                                tenant_id=tenant_id,
                                draft_id=outcome.draft_id,
                                prefix=piece_prefix(tenant_id, outcome.draft_id),
                                object_count=outcome.objects,
                                byte_count=outcome.bytes,
                                dry_run=not execute,
                                logical_only=outcome.logical_only,
                                expired_at=due,
                                purged_at=now,
                            )
                        )
                    if execute:
                        # Guarded: a piece marked meanwhile (another run) is not re-marked.
                        session.execute(
                            update(ContentDraft)
                            .where(
                                ContentDraft.id == outcome.draft_id,
                                ContentDraft.media_purged_at.is_(None),
                            )
                            .values(
                                media_purged_at=now,
                                media_objects_pending_at=(
                                    now
                                    if outcome.logical_only or outcome.draft_id in late
                                    else None
                                ),
                            )
                        )
        except Exception as exc:  # noqa: BLE001 — one piece must not stop the rest
            logger.exception("piece purge failed tenant=%s draft=%s", tenant_id, draft_id)
            report.errors.append((draft_id, type(exc).__name__))
            continue
        report.purged.extend(outcomes)
    return report


def _purge_folder(
    gate: PrefixDeleter, tenant_id: UUID, draft_id: UUID, due: datetime, *, execute: bool
) -> PieceOutcome:
    """Delete (or list, in a dry run) ONE piece folder. A refusal by the bucket (or a
    delete that keeps the objects) is a logical-only outcome (m-24973446); any other
    failure raises and marks nothing."""
    prefix = piece_prefix(tenant_id, draft_id)
    logical = False
    try:
        found = gate.delete_prefix(tenant_id, prefix, execute=execute)
    except Exception as exc:
        if not (execute and is_delete_refused(exc)):
            raise
        # m-24973446: the bucket keeps the objects; the app purges the piece anyway.
        # Listed again so the log says what is still there.
        logger.warning(
            "piece purge refused by the bucket, purging for the app only tenant=%s draft=%s",
            tenant_id,
            draft_id,
        )
        found = gate.delete_prefix(tenant_id, prefix, execute=False)
        logical = True
    else:
        kept = _kept_after_delete(gate, tenant_id, prefix) if execute else None
        if kept is not None:
            # A delete the store "accepted" but did not carry out (the bucket's answer to
            # its lock rule was never measured): same as a refusal.
            logger.warning(
                "piece purge left objects in R2, purging for the app only tenant=%s draft=%s",
                tenant_id,
                draft_id,
            )
            found, logical = kept, True
    objects, size = int(found.objects), int(found.bytes)  # type: ignore[attr-defined]
    return PieceOutcome(draft_id, objects, size, due, logical_only=logical)


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

    # m-24921069: the same family rule as the per-tenant purge (`_family_candidates`).
    families = _family_candidates(ImageAsset.object_key.like("t/%/generated/%"), now)
    with admin_session() as session:
        rows: Sequence[UUID] = session.scalars(
            families.with_only_columns(ImageAsset.tenant_id).order_by(None)
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
    "family_facts",
    "part_facts",
    "piece_prefix",
    "purge_expired_pieces",
    "read_facts",
    "retention_of",
    "tenants_with_expired_pieces",
]
