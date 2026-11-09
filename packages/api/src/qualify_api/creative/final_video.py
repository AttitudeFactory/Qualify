"""«Tu video completo» of a video by parts, as the screen reads it (m-24921084, ADR 44).

What the parent's card needs in one read, and the two actions it adds:

- **The joined preview's state** (`JoinState`): `waiting` (a part still has no vista
  previa, or one failed, expired or must be redone), `joining` (every part has one and
  the first join is on its way), `rejoining` (a part changed: the earlier joined preview
  is still shown while they are joined again), `ready` (the joined preview IS the parts'
  active versions), `failed` (the join run finished without a joined preview: «No
  pudimos juntar tus partes»), `approved` (approved whole: the screen goes on as for any
  approved piece), `purged` (the video's files were deleted by retention, ADR 39: only a
  new video is possible).
- **«Aprobar»** is active only when every part has its vista previa, none failed, needs
  redoing or expired, and the joined preview on screen is theirs — the same rule
  `ContentService.approve_parts` enforces (`part_final.approval_problem`), so the button
  never offers what the approval would refuse.
- **The month's video** at approval: what approving uses (`ContentService.
  parts_approval_videos`, the sum `charge_videos_many` would charge), the month's quota,
  what is left and what would remain — seconds under ADR 44 F1 = (b).
- **«Apruébalo antes del …»**: the nearest of the parts' deadlines (`draft_expires_at`
  over every part's draft block), and which parts expired.

Actions (nothing changes without the owner pressing them):

- `rejoin` — «Juntar otra vez»: opens (dirties) the parent's `join` run; the creative
  worker joins again. Ours, 0 USD, no charge.
- `FinalVideoReader.recreate_expired_parts` — «Crear la parte 3 otra vez»: ONLY the
  parts whose vista previa expired are made again (`PartsService.regenerate_part` with
  no change: 1 vista previa each, at the part's next revision), ALL in one unit of work
  under the parent's lock: the month is checked under that lock, and if any part cannot
  be made again none is, and nothing is charged.

«Cambiar una parte» is `PartsService.regenerate_part` (VE-10b), unchanged.

Purged parts (m-24921069, `retention.py`): retention treats the video and its parts as
ONE piece, so a part is purged only with its video — by then its 7-day vista previa
expired long ago. The only other way (a race the purge's own safety net sweeps) also
leaves the video's files gone. Either way the card reads `purged` and offers no part
action: changing a part of a purged video is refused (`parts.refuse_if_parent_purged`).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from qualify_creative.creations import CreationNotOffered, weight_for
from qualify_shared.db.session import tenant_session, tenant_unit_of_work
from sqlalchemy import text

from qualify_api.creative.creations import CreationsBalance, PreviewCharge, summed_price
from qualify_api.creative.draft_mode import draft_expired, draft_expires_at, draft_state
from qualify_api.creative.fsm import APPROVED, FAILED, GENERATED
from qualify_api.creative.part_final import approval_problem, preview_fingerprint
from qualify_api.creative.part_join import (
    _KEPT_JOIN,
    JOIN_PHASE,
    JOIN_PREVIEW_STATUS,
    DbPartJoins,
    PartJoinStore,
    PartPreview,
    PartsToJoin,
    ready_parts,
)

logger = logging.getLogger(__name__)

#: The part states whose active version IS a vista previa the owner has seen — the only
#: ones that can be «Venció». A part being made again (`drafting`) still points at its
#: old file until the new one lands: it has not expired, it is on its way.
_SHOWN = frozenset({GENERATED, APPROVED})


class JoinState(StrEnum):
    WAITING = "waiting"
    JOINING = "joining"
    REJOINING = "rejoining"
    READY = "ready"
    FAILED = "failed"
    APPROVED = "approved"
    PURGED = "purged"


class Blocker(StrEnum):
    """Why «Aprobar» is not active (the first that applies, in this order)."""

    APPROVED = "approved"
    PURGED = "purged"
    PART_FAILED = "part_failed"
    NEEDS_REDO = "needs_redo"
    EXPIRED = "expired"
    NOT_READY = "not_ready"  # a part has no vista previa yet
    JOINING = "joining"  # every part has one; the joined preview is not theirs yet
    JOIN_FAILED = "join_failed"


@dataclass(frozen=True)
class JoinRun:
    """The parent's `join` run: the revision it is for and whether it still has work
    (dirty or leased). `None` in `FinalVideo` inputs = no run at all."""

    pending: bool
    revision: int | None = None


@dataclass(frozen=True)
class PartCondition:
    """One planned part as «Tu video completo» needs it."""

    index: int
    draft_id: UUID | None  # None: planned, not made yet
    has_preview: bool  # a live vista previa the join can use
    failed: bool
    expired: bool
    needs_redo: bool
    expires_at: datetime | None  # its vista previa's deadline (UTC), None when not waiting
    purged: bool = False


@dataclass(frozen=True)
class VideoUse:
    """The month's video at approval, in the balance's unit (seconds under v3)."""

    uses: int
    quota: int
    left: int
    unlimited: bool = False
    in_seconds: bool = True
    renews_on: date | None = None

    @property
    def after(self) -> int:
        return self.left - self.uses

    @property
    def short(self) -> bool:
        return not self.unlimited and self.quota > 0 and self.uses > self.left


@dataclass(frozen=True)
class PreviewUse:
    """What making the expired parts again uses of the month's vistas previas."""

    uses: int
    left: int
    quota: int
    unlimited: bool = False
    renews_on: date | None = None

    @property
    def short(self) -> bool:
        return not self.unlimited and self.quota > 0 and self.uses > self.left


@dataclass(frozen=True)
class FinalVideo:
    """«Tu video completo», read once (`FinalVideoReader.read`)."""

    parent_id: UUID
    state: JoinState
    seconds: int  # the joined preview's length, else the plan's
    planned: int
    parts: tuple[PartCondition, ...]
    can_approve: bool
    blocker: Blocker | None
    video_key: str | None  # the joined preview shown (the earlier one while rejoining)
    poster_key: str | None
    expires_at: datetime | None  # «Apruébalo antes del …»: the nearest part deadline
    video_use: VideoUse | None = None  # None: no quota wired
    recreate_use: PreviewUse | None = None  # None: no expired part, or no quota wired

    @property
    def approved(self) -> bool:
        return self.state is JoinState.APPROVED

    @property
    def expired_parts(self) -> tuple[int, ...]:
        """The parts «Crear la parte N otra vez» makes again, in plan order."""
        return tuple(p.index for p in self.parts if p.expired)

    @property
    def failed_parts(self) -> tuple[int, ...]:
        return tuple(p.index for p in self.parts if p.failed)

    @property
    def redo_parts(self) -> tuple[int, ...]:
        return tuple(p.index for p in self.parts if p.needs_redo)


# ---------------------------------------------------------------------------
# pure rules


def _utc(moment: float | None) -> datetime | None:
    return None if moment is None else datetime.fromtimestamp(moment, UTC)


def part_expired(part: PartPreview, now: float) -> bool:
    """Whether the vista previa the owner saw of this part can no longer give its final
    (7 days, `draft_expired`). Only a part showing a vista previa (`_SHOWN`): one being
    made again or failed has not «vencido». Pure."""
    block = draft_state(part.params)
    return part.status in _SHOWN and block is not None and draft_expired(block, now)


def _created_at(part: PartPreview) -> float | None:
    created = (draft_state(part.params) or {}).get("created_at")
    if isinstance(created, bool) or not isinstance(created, int | float):
        return None
    return float(created)


def extend_needs_redo(
    part: PartPreview, previous: PartPreview | None, *, part_ok: bool, previous_ok: bool
) -> bool:
    """«Hay que rehacerla»: an `extend` part («Sigue a la anterior») whose previous part
    got a newer vista previa than its own — both live (`part_ok`, `previous_ok`) and the
    previous one's draft `created_at` later than this one's. Pure.

    TODO(m-24921082): PR #567 adds the same rule as `part_progress.derive_state`; unify
    them (one function, imported here) once it is on main."""
    meta = part.params.get("part")
    if not isinstance(meta, Mapping) or meta.get("mode") != "extend":
        return False
    if previous is None or not (part_ok and previous_ok):
        return False
    own, theirs = _created_at(part), _created_at(previous)
    return own is not None and theirs is not None and theirs > own


def _has_preview(part: PartPreview, tenant_id: UUID, now: float) -> bool:
    # the join's own per-part rule (`ready_parts`), asked of this part alone
    alone = PartsToJoin(
        parent_id=part.draft_id, revision=0, planned=1, parts=(replace(part, part_index=1),)
    )
    return ready_parts(alone, tenant_id, now) is not None


def part_conditions(
    snapshot: PartsToJoin, tenant_id: UUID, now: float
) -> tuple[PartCondition, ...]:
    """Every planned part's condition, in plan order (a part not made yet has no
    draft). Pure."""
    by_index = {p.part_index: p for p in snapshot.parts}
    ok = {i: _has_preview(p, tenant_id, now) for i, p in by_index.items()}
    out = []
    for index in range(1, snapshot.planned + 1):
        part = by_index.get(index)
        if part is None:
            out.append(PartCondition(index, None, False, False, False, False, None))
            continue
        previous = by_index.get(index - 1)
        out.append(
            PartCondition(
                index=index,
                draft_id=part.draft_id,
                has_preview=ok[index],
                failed=part.status == FAILED,
                expired=part_expired(part, now) and not part.purged,
                needs_redo=extend_needs_redo(
                    part,
                    previous,
                    part_ok=ok[index],
                    previous_ok=previous is not None and ok.get(index - 1, False),
                ),
                expires_at=_utc(draft_expires_at([part.params])),
                purged=part.purged,
            )
        )
    return tuple(out)


def join_state(
    snapshot: PartsToJoin,
    tenant_id: UUID,
    run: JoinRun | None,
    now: float,
    *,
    purged: bool = False,
) -> JoinState:
    """The joined preview's state for the screen (module docstring). Pure.

    `run` must be read BEFORE `snapshot`: a run seen done then is done for the snapshot
    too, so a join that finished in between reads `ready`, never «No salió». A run of
    another revision than the snapshot's (the parent moved on in between) counts as
    pending."""
    if purged or any(p.purged for p in snapshot.parts):
        return JoinState.PURGED
    if snapshot.status in _KEPT_JOIN:
        return JoinState.APPROVED
    parts = ready_parts(snapshot, tenant_id, now)
    if parts is None:
        return JoinState.WAITING
    block = snapshot.joined_block
    if (
        block is not None
        and block.get("status") == JOIN_PREVIEW_STATUS
        and block.get("parent_revision") == snapshot.revision
        and preview_fingerprint(parts, block) == snapshot.joined_fingerprint
    ):
        return JoinState.READY
    pending = run is not None and (
        run.pending or (run.revision is not None and run.revision != snapshot.revision)
    )
    if not pending:
        # the run is done (or was never opened) and these parts are not joined: the
        # join could not be made («No pudimos juntar tus partes»)
        return JoinState.FAILED
    return JoinState.REJOINING if snapshot.joined_object_key else JoinState.JOINING


def blocker_for(
    state: JoinState,
    parts: Sequence[PartCondition],
    problem: str | None,
) -> Blocker | None:
    """Why «Aprobar» is off, or None when it is on. `problem` is `approval_problem`'s
    answer — the approval's own rule, so the button never offers a refused approval.

    The card is STRICTER than `ContentService.approve_parts`: it also blocks on
    «Hay que rehacerla» (`extend_needs_redo`), which the approval does not check yet.
    TODO(m-24921082): unify with `part_progress.derive_state` once PR #567 is on main,
    and decide whether `approve_parts` should refuse it too."""
    if state is JoinState.APPROVED:
        return Blocker.APPROVED
    if state is JoinState.PURGED:
        return Blocker.PURGED
    if any(p.failed for p in parts):
        return Blocker.PART_FAILED
    if any(p.needs_redo for p in parts):
        return Blocker.NEEDS_REDO
    if any(p.expired for p in parts):
        return Blocker.EXPIRED
    if not all(p.has_preview for p in parts):
        return Blocker.NOT_READY
    if state is JoinState.FAILED:
        return Blocker.JOIN_FAILED
    if state is not JoinState.READY or problem is not None:
        return Blocker.JOINING
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def final_video_from(
    snapshot: PartsToJoin,
    tenant_id: UUID,
    *,
    now: float,
    run: JoinRun | None,
    plan_seconds: Sequence[int] = (),
    poster_key: str | None = None,
    video_use: VideoUse | None = None,
    recreate_use: PreviewUse | None = None,
    purged: bool = False,
) -> FinalVideo:
    """«Tu video completo» from what was read. Pure."""
    parts = part_conditions(snapshot, tenant_id, now)
    state = join_state(snapshot, tenant_id, run, now, purged=purged)
    if state in (JoinState.JOINING, JoinState.REJOINING, JoinState.FAILED) and any(
        p.needs_redo for p in parts
    ):
        # a part must be redone first: waiting for the owner, not «Juntando»
        state = JoinState.WAITING
    problem = approval_problem(snapshot, tenant_id, now)
    blocker = blocker_for(state, parts, problem)
    block = snapshot.joined_block or {}
    joined = _number(block.get("duration_seconds"))
    seconds = round(joined) if state is JoinState.READY and joined else sum(plan_seconds)
    deadlines = [p.expires_at for p in parts if p.expires_at is not None and not p.expired]
    closed = state in (JoinState.APPROVED, JoinState.PURGED)
    return FinalVideo(
        parent_id=snapshot.parent_id,
        state=state,
        seconds=int(seconds),
        planned=snapshot.planned,
        parts=parts,
        can_approve=blocker is None,
        blocker=blocker,
        video_key=None if state is JoinState.PURGED else snapshot.joined_object_key,
        poster_key=None if state is JoinState.PURGED else poster_key,
        expires_at=None if closed else min(deadlines, default=None),
        video_use=video_use,
        recreate_use=recreate_use if not closed and any(p.expired for p in parts) else None,
    )


def video_use_from(amount: int, balance: CreationsBalance) -> VideoUse:
    """`ContentService.parts_approval_videos`' answer as the card reads it. Pure."""
    return VideoUse(
        uses=amount,
        quota=balance.video_quota,
        left=balance.videos_left,
        unlimited=balance.unlimited,
        in_seconds=balance.video_in_seconds,
        renews_on=balance.renews_on,
    )


# ---------------------------------------------------------------------------
# Postgres


def _join_run(tenant_id: UUID, parent_id: UUID) -> JoinRun | None:
    """The parent's `join` run at its CURRENT revision — read before the snapshot
    (`join_state`). None when there is none."""
    with tenant_session(tenant_id) as session:
        row = (
            session.execute(
                text("""
            SELECT r.revision, r.dirty_version > r.prepared_version
                   OR (r.lease_until IS NOT NULL AND r.lease_until > now()) AS pending
            FROM content_drafts p
            JOIN creative_pipeline_runs r
              ON r.draft_id = p.id AND r.revision = p.revision AND r.phase = :phase
            WHERE p.id = :p
        """),
                {"p": parent_id, "phase": JOIN_PHASE},
            )
            .mappings()
            .first()
        )
    if row is None:
        return None
    return JoinRun(pending=bool(row["pending"]), revision=int(row["revision"]))


@dataclass(frozen=True)
class ParentExtras:
    plan: list
    poster: str | None
    purged: bool


def _extras(tenant_id: UUID, parent_id: UUID) -> ParentExtras:
    """The parent's plan, its joined preview's poster and its purge mark (RLS)."""
    with tenant_session(tenant_id) as session:
        row = (
            session.execute(
                text("""
            SELECT b.media->'parts' AS plan, p.media_purged_at IS NOT NULL AS purged,
                   (SELECT a.params->>'thumbnail_key' FROM image_assets a
                    WHERE a.draft_id = p.id AND a.params->'draft'->>'finish' = 'join'
                      AND a.version_id IS NOT DISTINCT FROM p.active_version_id
                    ORDER BY a.updated_at DESC LIMIT 1) AS poster
            FROM content_drafts p JOIN content_briefs b ON b.id = p.brief_id
            WHERE p.id = :p
        """),
                {"p": parent_id},
            )
            .mappings()
            .first()
        )
    if row is None:
        return ParentExtras([], None, False)
    plan = row["plan"] if isinstance(row["plan"], list) else []
    return ParentExtras(plan, row["poster"], bool(row["purged"]))


def _plan_seconds(plan: Sequence[Any]) -> list[int]:
    out = []
    for entry in plan:
        seconds = _number(entry.get("seconds")) if isinstance(entry, Mapping) else None
        out.append(int(seconds) if seconds else 0)
    return out


class RecreateRefused(ValueError):
    """«Crear la parte N otra vez» asked for a part whose vista previa has not expired
    (already being made again, never shown, failed, purged, or missing): nothing made,
    nothing charged."""


class FinalVideoReader:
    """«Tu video completo» over the content service (its repository, its ledger)."""

    def __init__(
        self,
        content: Any,
        *,
        joins: PartJoinStore | None = None,
        clock: Callable[[], float] = time.time,
        runs: Callable[[UUID, UUID], JoinRun | None] = _join_run,
        extras: Callable[[UUID, UUID], ParentExtras] = _extras,
    ) -> None:
        self._content = content
        self._joins = joins or DbPartJoins()
        self._clock = clock
        self._runs = runs
        self._extras = extras

    def read(self, *, tenant_id: UUID, parent_id: UUID) -> FinalVideo | None:
        """The card of `parent_id`, or None when it is not a video by parts of this
        business (another business's reads as missing, RLS)."""
        run = self._runs(tenant_id, parent_id)  # BEFORE the snapshot (`join_state`)
        snapshot = self._joins.read(tenant_id=tenant_id, parent_id=parent_id)
        if snapshot is None:
            return None
        now = self._clock()
        extras = self._extras(tenant_id, parent_id)
        video_use = None
        found = self._content.parts_approval_videos(tenant_id=tenant_id, parent_id=parent_id)
        if found is not None:
            video_use = video_use_from(*found)
        expired = [p.draft_id for p in snapshot.parts if part_expired(p, now) and not p.purged]
        return final_video_from(
            snapshot,
            tenant_id,
            now=now,
            run=run,
            plan_seconds=_plan_seconds(extras.plan),
            poster_key=extras.poster,
            video_use=video_use,
            recreate_use=self._recreate_use(tenant_id, expired),
            purged=extras.purged,
        )

    # -- «Crear la parte N otra vez» -------------------------------------------------

    def _charges(self, tenant_id: UUID, draft_ids: Sequence[UUID]) -> list[PreviewCharge]:
        """What making each part again charges at creation (`weight_for(redo=True)`,
        exactly as `ContentService.reject(regenerate=True)` charges it)."""
        repo = self._content.repository
        out = []
        for draft_id in draft_ids:
            record = repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
            brief = (
                None
                if record is None
                else repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
            )
            if record is None or brief is None:
                continue
            try:
                price = weight_for(brief, redo=True)
            except CreationNotOffered:
                continue
            out.append(PreviewCharge(draft_id=draft_id, revision=record.revision + 1, price=price))
        return out

    def _balance(self, tenant_id: UUID, draft_ids: Sequence[UUID]) -> CreationsBalance | None:
        ledger = self._content.creations
        if ledger is None or not draft_ids:
            return None
        record = self._content.repository.get_draft(tenant_id=tenant_id, draft_id=draft_ids[0])
        if record is None:
            return None
        return ledger.balance(tenant_id=tenant_id, brand_id=record.brand_id)

    def _recreate_use(self, tenant_id: UUID, draft_ids: Sequence[UUID]) -> PreviewUse | None:
        balance = self._balance(tenant_id, draft_ids)
        if balance is None:
            return None
        price = summed_price(self._charges(tenant_id, draft_ids))
        return PreviewUse(
            uses=price.videos,
            left=balance.previews_left,
            quota=balance.preview_quota,
            unlimited=balance.unlimited,
            renews_on=balance.renews_on,
        )

    def recreate_expired_parts(
        self,
        *,
        tenant_id: UUID,
        parent_id: UUID,
        user_id: UUID,
        part_indexes: Sequence[int] | None = None,
    ) -> tuple[int, ...]:
        """«Crear la parte N otra vez»: make again ONLY the parts whose vista previa
        expired — all of them, or those of `part_indexes`. All or nothing, in ONE unit of
        work: the parent is fenced and locked first (`lock_parent_for_part_change`:
        refused while publishing, scheduled or purged), the expired parts and the
        month's vistas previas are read under that lock, then each part is
        `PartsService.regenerate_part` with no change (its own charge, 1 vista previa)
        inside the same transaction — a part that cannot be made again rolls every part
        and every charge back. `RecreateRefused` (nothing written) when a part asked for
        has not expired — e.g. it is already being made again. The parts made again, in
        plan order."""
        from qualify_api.creative.parts import (  # noqa: PLC0415
            PartChanges,
            PartsService,
            lock_parent_for_part_change,
        )

        parts = PartsService(self._content)
        with tenant_unit_of_work(tenant_id) as session:
            known = session.execute(
                text("SELECT 1 FROM content_drafts WHERE id = :p AND parent_draft_id IS NULL"),
                {"p": parent_id},
            ).scalar()
            if known is None:
                raise RecreateRefused("not a video by parts of this business")
            lock_parent_for_part_change(session, parent_id)
            snapshot = self._joins.read(tenant_id=tenant_id, parent_id=parent_id)
            if snapshot is None:
                raise RecreateRefused("not a video by parts of this business")
            now = self._clock()
            expired = {
                p.part_index: p.draft_id
                for p in snapshot.parts
                if p.part_index is not None and not p.purged and part_expired(p, now)
            }
            wanted = sorted(expired) if part_indexes is None else sorted(set(part_indexes))
            if not wanted or any(index not in expired for index in wanted):
                raise RecreateRefused(f"parts {wanted} have not all expired")
            ids = [expired[index] for index in wanted]
            balance = self._balance(tenant_id, ids)
            if balance is not None:
                short = balance.shortfall(summed_price(self._charges(tenant_id, ids)))
                if short is not None:
                    raise short
            for index in wanted:
                parts.regenerate_part(
                    tenant_id=tenant_id,
                    parent_id=parent_id,
                    part_index=index,
                    changes=PartChanges(),
                    user_id=user_id,
                )
        logger.info("parent %s: expired parts %s made again", parent_id, wanted)
        return tuple(wanted)


def rejoin(*, tenant_id: UUID, parent_id: UUID) -> bool:
    """«Juntar otra vez»: open (or dirty) the parent's `join` run at its revision so the
    creative worker joins its parts again — ours, 0 USD, nothing charged. False (nothing
    written) when it is not a video by parts of this business with parts, it is
    approved already (its join is kept, `part_join._KEPT_JOIN`) or purged."""
    from qualify_api.creative.parts import open_parent_join  # noqa: PLC0415

    with tenant_unit_of_work(tenant_id) as session:
        row = session.execute(
            text("""
            SELECT p.status, p.media_purged_at IS NOT NULL AS purged
            FROM content_drafts p JOIN content_briefs b ON b.id = p.brief_id
            WHERE p.id = :p AND p.parent_draft_id IS NULL AND b.kind = 'shot_video'
              AND EXISTS (SELECT 1 FROM content_drafts c WHERE c.parent_draft_id = p.id)
            FOR UPDATE OF p
        """),
            {"p": parent_id},
        ).first()
        if row is None or row.status in _KEPT_JOIN or row.purged:
            return False
        open_parent_join(session, parent_id)
    logger.info("parent %s: join asked again by its owner", parent_id)
    return True


__all__ = [
    "Blocker",
    "FinalVideo",
    "FinalVideoReader",
    "JoinRun",
    "JoinState",
    "ParentExtras",
    "PartCondition",
    "PreviewUse",
    "RecreateRefused",
    "VideoUse",
    "blocker_for",
    "extend_needs_redo",
    "final_video_from",
    "join_state",
    "part_conditions",
    "part_expired",
    "rejoin",
    "video_use_from",
]
