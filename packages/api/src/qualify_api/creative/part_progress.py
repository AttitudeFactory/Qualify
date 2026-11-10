"""How each part of a video by parts is doing, for its result screen (m-24921082, UI-7).

The screen (`Qualify/part_progress_vm.py`) shows one row per planned part with one of
nine states (`docs/ux-video-por-planos.md` §2), the share of parts that already have a
vista previa, who an «Sigue a la anterior» part in line waits for, and what the owner
may do with a part that did not come out. Nothing here changes a part: the actions are
`part_actions.PartRecovery` (and `PartsService.regenerate_part`), each one asked for
by the owner — never taken by the screen on its own.

Every state is DERIVED from what is already stored — no column of its own:

- `unmade` «Sin crear»: the plan has the part, no child draft yet («Crear esta parte»,
  m-24921081; the owner's ask and its refusal ride in `PartProgress.request`).
- `queued` «En fila»: the child is `drafting` and its generation jobs all wait
  (`queued`); or it is a «Sigue a la anterior» (`extend`) part whose previous part has
  no live vista previa yet and whose own job was not taken (`waiting_for`).
- `creating` «Creando»: `drafting` otherwise (a job taken, or no queue at all).
- `to_review` «Para revisar»: `generated` (or `rejected`) with a live vista previa.
- `ready` «Lista»: `approved` — the whole video was approved with it.
- `failed` «No salió»: `failed` for any reason but the ones below.
- `original_refused` «No se pudo con el original»: `failed` on an «Igual al original»
  (`edit`) part for a reason that lets it be made new (`can_make_part_new`:
  `refused_face`, `source_purged`, `not_edit_eligible`, `analysis_not_ready`,
  `window_unavailable`).
- `redo` «Hay que rehacerla»: an `extend` part whose live vista previa was made BEFORE
  its previous part's current one (the part it continues changed).
- `expired` «Venció»: its vista previa passed its 7 days (`draft_expired`), or the
  retention purge removed the files of the part or of its video (`media_purged_at`).

«Sigue a la anterior» waiting and «Hay que rehacerla» are read from the parts' own
vistas previas because VE-13 (the `extend` wiring and its `waiting_previous`) is not
built yet: the day it is, it can set what this module reads without the screen changing.

`read_part_progress` reads under `tenant_session` (RLS): another business's video
reads as missing (None). `derive_progress` is pure.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from qualify_creative.enums import FailureReason
from qualify_creative.schemas import PartsRequest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.draft_mode import draft_expired, draft_state
from qualify_api.creative.fsm import APPROVED, DRAFTING, FAILED, GENERATED, REJECTED

#: A part of the plan that has no child draft yet (as `parts.PLANNED`).
PLANNED = "planned"


class PartState(StrEnum):
    """The nine states of a part on its result screen (UX §2), in the plan's words."""

    UNMADE = "unmade"
    QUEUED = "queued"
    CREATING = "creating"
    TO_REVIEW = "to_review"
    READY = "ready"
    FAILED = "failed"
    ORIGINAL_REFUSED = "original_refused"
    REDO = "redo"
    EXPIRED = "expired"


class PartAction(StrEnum):
    """What the owner may ask for on a part's row (ticket m-24921082).

    - `retry` «Intentar de nuevo»: the same part, same form (`PartRecovery.retry_part`);
    - `change` «Cambiar»: its description or photos, then made again (`retry_part` with
      `PartChanges`; the mode never changes here);
    - `remove` «Quitar parte»: NOT served yet — removing a part already made needs a
      decision on what happens to its rows (see `SERVED_ACTIONS`);
    - `make_new` «Hacerla nueva»: an «Igual al original» part made «Nueva, inspirada en
      el original» (`PartRecovery.make_part_new`) — the one form change, and only on
      the owner's tap;
    - `recreate` «Crearla otra vez»: another version of the part as it is
      (`PartsService.regenerate_part` with empty `PartChanges`);
    - `create` «Crear esta parte» (m-24921081): a part never created (`unmade`), on its
      own (`part_request.PartsRequests.request_parts` with `(index,)`) — not offered on
      a «Sigue a la anterior» part whose previous part is not created either."""

    RETRY = "retry"
    CHANGE = "change"
    REMOVE = "remove"
    MAKE_NEW = "make_new"
    RECREATE = "recreate"
    CREATE = "create"


#: The actions a service exists for today. `remove` is offered by the ticket but has no
#: service: a part already created owns charge, job and version rows, and taking it out
#: of its video needs either deleting them (losing the charge history) or a column that
#: marks it removed (a migration) — a decision for Deivid. The screen shows only these.
#: `create` has its service (`part_request.PartsRequests.request_parts`, m-24921081) but
#: is left out until the result screen has its button and handler (UI-7): the screen
#: opts in with `SERVED_ACTIONS | {PartAction.CREATE}`, never a dead button.
SERVED_ACTIONS: frozenset[PartAction] = frozenset(
    {PartAction.RETRY, PartAction.CHANGE, PartAction.MAKE_NEW, PartAction.RECREATE}
)

#: A part «Sigue a la anterior» (`VideoPartPlan.mode`).
EXTEND = "extend"
#: An «Igual al original» part.
EDIT = "edit"

#: The states whose part has a vista previa to watch (the panel's numerator).
_WITH_PREVIEW = frozenset({PartState.TO_REVIEW, PartState.READY, PartState.REDO})
#: Generation job statuses that mean the vendor call was taken.
_TAKEN = frozenset({"claimed", "submitted", "succeeded"})


@dataclass(frozen=True)
class PartFacts:
    """One part of the plan as stored: what `derive_progress` needs, nothing more."""

    index: int
    mode: str
    seconds: int
    draft_id: UUID | None = None
    status: str = PLANNED  # the child's status, or PLANNED
    failure_reason: str | None = None
    failure_detail: str | None = None
    #: the `draft` block of the child's active video (`params.draft`), if any
    preview: Mapping[str, Any] | None = None
    has_video: bool = False
    purged: bool = False
    #: the statuses of its generation jobs at its current revision (never finals)
    jobs: tuple[str, ...] = ()


@dataclass(frozen=True)
class PartProgressRow:
    """One row of the screen: the part, its state and what may be done with it."""

    index: int
    total: int
    draft_id: UUID | None
    mode: str
    seconds: int
    state: PartState
    actions: tuple[PartAction, ...] = ()
    #: «Se crea cuando esté la parte n.» — the part an `extend` in line waits for
    waiting_for: int | None = None
    #: «La parte n cambió…» — the part a `redo` part continues
    changed_part: int | None = None
    failure_reason: str | None = None
    failure_detail: str | None = None
    #: expired because its files were purged (no action brings them back)
    purged: bool = False

    @property
    def has_preview(self) -> bool:
        return self.state in _WITH_PREVIEW


@dataclass(frozen=True)
class PartProgress:
    """A video by parts on its result screen."""

    parent_id: UUID
    parts: tuple[PartProgressRow, ...]
    #: the retention purge removed the video's files (every made part reads «Venció»)
    purged: bool = False
    #: m-24921081: what the owner asked of the parts when he created the video and the
    #: outcome of the last attempt (`refused`: a `PartsRefusal` code); None = no ask
    request: PartsRequest | None = None

    @property
    def total(self) -> int:
        return len(self.parts)

    @property
    def with_preview(self) -> int:
        """How many parts have a vista previa (the panel's «2 de 4 listas»)."""
        return sum(1 for part in self.parts if part.has_preview)


# ---------------------------------------------------------------------------
# pure rules


def _live_preview(facts: PartFacts, now: float) -> bool:
    """A vista previa the owner can watch: a made child, not purged, not expired."""
    if facts.status not in (GENERATED, REJECTED, APPROVED) or facts.purged:
        return False
    if not facts.has_video:
        return False
    block = draft_state({"draft": facts.preview} if facts.preview is not None else None)
    return block is None or not draft_expired(block, now)


def _made_at(facts: PartFacts) -> float | None:
    created = (facts.preview or {}).get("created_at")
    if isinstance(created, bool) or not isinstance(created, int | float):
        return None
    return float(created)


def _reason(value: str | None) -> FailureReason | None:
    try:
        return FailureReason(value) if value else None
    except ValueError:
        return None


def failed_part(mode: str, failure_reason: str | None) -> tuple[PartState, tuple[PartAction, ...]]:
    """The state and the actions of a FAILED part, by its mode and why it failed — the
    one rule both the screen and `part_actions.PartRecovery` follow. Pure."""
    reason = _reason(failure_reason)
    if reason is not None and reason.can_make_part_new and mode == EDIT:
        return PartState.ORIGINAL_REFUSED, (PartAction.MAKE_NEW, PartAction.REMOVE)
    if reason is FailureReason.REFUSED_FACE:
        # a «Nueva» part refused for a person in ITS photos: the same photos would be
        # refused again (VE-09 note for UI-7) — change them or take the part out
        return PartState.FAILED, (PartAction.CHANGE, PartAction.REMOVE)
    return PartState.FAILED, (PartAction.RETRY, PartAction.CHANGE, PartAction.REMOVE)


def _failed_row(facts: PartFacts) -> tuple[PartState, tuple[PartAction, ...]]:
    return failed_part(facts.mode, facts.failure_reason)


def derive_state(
    facts: PartFacts,
    previous: PartFacts | None,
    *,
    parent_purged: bool = False,
    now: float | None = None,
) -> PartProgressRow:
    """The row of ONE part from its facts and its previous part's (None for the first).
    `total` is filled by `derive_progress`. Pure."""
    moment = time.time() if now is None else now
    row: dict[str, Any] = {
        "index": facts.index,
        "total": 0,
        "draft_id": facts.draft_id,
        "mode": facts.mode,
        "seconds": facts.seconds,
    }
    if facts.status == PLANNED:
        alone = facts.mode == EXTEND and (previous is None or previous.status == PLANNED)
        actions = () if alone or parent_purged else (PartAction.CREATE,)
        return PartProgressRow(**row, state=PartState.UNMADE, actions=actions)
    if facts.purged or parent_purged:
        return PartProgressRow(**row, state=PartState.EXPIRED, purged=True)
    if facts.status == DRAFTING:
        taken = any(job in _TAKEN for job in facts.jobs)
        if (
            not taken
            and facts.mode == EXTEND
            and previous is not None
            and not _live_preview(previous, moment)
        ):
            return PartProgressRow(**row, state=PartState.QUEUED, waiting_for=previous.index)
        if not taken and any(job == "queued" for job in facts.jobs):
            return PartProgressRow(**row, state=PartState.QUEUED)
        return PartProgressRow(**row, state=PartState.CREATING)
    if facts.status == FAILED:
        state, actions = _failed_row(facts)
        return PartProgressRow(
            **row,
            state=state,
            actions=actions,
            failure_reason=facts.failure_reason,
            failure_detail=facts.failure_detail,
        )
    if facts.status in (GENERATED, REJECTED, APPROVED):
        block = draft_state({"draft": facts.preview} if facts.preview is not None else None)
        if facts.has_video and block is not None and draft_expired(block, moment):
            return PartProgressRow(**row, state=PartState.EXPIRED, actions=(PartAction.RECREATE,))
        if (
            facts.mode == EXTEND
            and previous is not None
            and _live_preview(facts, moment)
            and _live_preview(previous, moment)
        ):
            mine, theirs = _made_at(facts), _made_at(previous)
            if mine is not None and theirs is not None and theirs > mine:
                return PartProgressRow(
                    **row,
                    state=PartState.REDO,
                    actions=(PartAction.RECREATE,),
                    changed_part=previous.index,
                )
        if facts.status == APPROVED:
            return PartProgressRow(**row, state=PartState.READY)
        return PartProgressRow(**row, state=PartState.TO_REVIEW)
    # staged/published: a part never is one (only its video); read as made
    return PartProgressRow(**row, state=PartState.READY)


def derive_progress(
    parent_id: UUID,
    parts: Sequence[PartFacts],
    *,
    parent_purged: bool = False,
    now: float | None = None,
    request: PartsRequest | None = None,
) -> PartProgress:
    """Every planned part's row, in plan order. Pure."""
    ordered = sorted(parts, key=lambda p: p.index)
    rows: list[PartProgressRow] = []
    for position, facts in enumerate(ordered):
        previous = ordered[position - 1] if position > 0 else None
        row = derive_state(facts, previous, parent_purged=parent_purged, now=now)
        rows.append(replace(row, total=len(ordered)))
    return PartProgress(
        parent_id=parent_id, parts=tuple(rows), purged=parent_purged, request=request
    )


# ---------------------------------------------------------------------------
# the read


def _request(value: Any) -> PartsRequest | None:
    """The stored ask, or None (none kept, or a shape this code does not read)."""
    if not isinstance(value, Mapping):
        return None
    try:
        return PartsRequest.model_validate(value)
    except ValidationError:
        return None


def _int(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def read_part_progress(
    *, tenant_id: UUID, parent_id: UUID, now: float | None = None
) -> PartProgress | None:
    """The result screen of a video by parts, as the owning business (`tenant_session`,
    RLS). None when the draft is not a video by parts of this business (another
    business's reads the same as a missing one), or a part rather than its video."""
    with tenant_session(tenant_id) as session:
        parent = (
            session.execute(
                text("""
                SELECT p.parent_draft_id, b.kind, b.media->'parts' AS plan,
                       b.media->'parts_request' AS request,
                       p.media_purged_at IS NOT NULL AS purged
                FROM content_drafts p JOIN content_briefs b ON b.id = p.brief_id
                WHERE p.id = :p
                """),
                {"p": parent_id},
            )
            .mappings()
            .first()
        )
        if parent is None or parent["parent_draft_id"] is not None:
            return None
        if parent["kind"] != "shot_video":
            return None
        rows = (
            session.execute(
                text("""
                SELECT c.id, c.part_index, c.status, c.failure_reason, c.failure_detail,
                       c.media_purged_at IS NOT NULL AS purged, cb.media->'part' AS part,
                       a.object_key, a.params->'draft' AS block,
                       COALESCE((
                           SELECT array_agg(j.status::text ORDER BY j.id) FROM creative_jobs j
                           WHERE j.draft_id = c.id AND j.revision = c.revision
                             AND j.kind <> 'final'
                       ), ARRAY[]::text[]) AS jobs
                FROM content_drafts c
                JOIN content_briefs cb ON cb.id = c.brief_id
                LEFT JOIN LATERAL (
                    SELECT object_key, params FROM image_assets a
                    WHERE a.draft_id = c.id AND a.version_id = c.active_version_id
                      AND a.media_type = 'video'
                    ORDER BY a.position, a.created_at LIMIT 1
                ) a ON true
                WHERE c.parent_draft_id = :p
                ORDER BY c.part_index
                """),
                {"p": parent_id},
            )
            .mappings()
            .all()
        )
    plan = parent["plan"] if isinstance(parent["plan"], list) else []
    children = {row["part_index"]: row for row in rows}
    facts: list[PartFacts] = []
    for index, entry in enumerate(plan, start=1):
        planned = entry if isinstance(entry, Mapping) else {}
        child = children.get(index)
        if child is None:
            facts.append(
                PartFacts(
                    index=index,
                    mode=str(planned.get("mode") or "reference"),
                    seconds=_int(planned.get("seconds"), 0),
                )
            )
            continue
        own = child["part"] if isinstance(child["part"], Mapping) else planned
        block = child["block"] if isinstance(child["block"], Mapping) else None
        facts.append(
            PartFacts(
                index=index,
                mode=str(own.get("mode") or planned.get("mode") or "reference"),
                seconds=_int(own.get("seconds"), _int(planned.get("seconds"), 0)),
                draft_id=child["id"],
                status=str(child["status"]),
                failure_reason=child["failure_reason"],
                failure_detail=child["failure_detail"],
                preview=block,
                has_video=bool(child["object_key"]),
                purged=bool(child["purged"]),
                jobs=tuple(child["jobs"] or ()),
            )
        )
    return derive_progress(
        parent_id,
        facts,
        parent_purged=bool(parent["purged"]),
        now=now,
        request=_request(parent["request"]),
    )


__all__ = [
    "EDIT",
    "EXTEND",
    "PLANNED",
    "SERVED_ACTIONS",
    "PartAction",
    "PartFacts",
    "PartProgress",
    "PartProgressRow",
    "PartState",
    "derive_progress",
    "failed_part",
    "derive_state",
    "read_part_progress",
]
