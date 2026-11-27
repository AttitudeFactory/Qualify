"""«Sigue a la anterior»: a part that continues the previous one (ADR 44, m-24880328 +
VE-13 m-24921070).

A part in `extend` mode is a Seedance 2.5 omni task of type `extend` whose one reference
video is the PREVIOUS part's own vendor output, byte for byte (BytePlus accepts a face
in its own unedited outputs only — never re-encoded, `docs/diseno-video-por-planos.md`
§4.2, R11). This module holds the rules both the producer (`media.MediaProducer._clip`)
and the screens read:

- the switch (`QUALIFY_PARTS_EXTEND`): `off` until a paid draft test proves that an
  `extend` task takes `draft: true` (m-24880328). Off, nothing makes an `extend` part —
  `PartsService.create_parts` and the parts form refuse it, the screen says it is not
  available yet, and the producer never sends one to Seedance (a part created while it
  was on and made again after it went off fails `part_failed`, its vista previa given
  back);
- what the vendor hands back (`QUALIFY_SEEDANCE_EXTEND_OUTPUT`): only the new stretch
  (`segment`, the default: measured in EXT-001, 2026-11-14) or the input video followed
  by it (`whole`). A `segment` output whose length reads as input + asked is logged
  (`creative.extend.unexpected_whole`) and kept as `whole`; `auto` reads it from the
  length alone. The join keeps ONLY the new stretch either way (`extend_span`), so no
  frame of the previous part is shown twice;
- which part is «the previous one» and whether it has a vista previa yet
  (`pick_previous`, pure; `DbPreviousParts`, as the owning tenant). Without one the
  part's preparation waits (`waiting_previous`: its job stays queued, the reaper spares
  it) and `release_next_extend` lets it go when the previous part settles;
- «Hay que rehacerla» (`extend_is_stale`): the part continued a file the previous part
  no longer shows. It is never made again by itself.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.orm import Session

from qualify_api.creative.draft_mode import draft_expired, draft_state

logger = logging.getLogger(__name__)

#: `off` (default) or `draft`: whether «Sigue a la anterior» parts are made, as 480p
#: drafts (the only way a part is made: vista previa first, its 1080p on approval).
EXTEND_SWITCH = "QUALIFY_PARTS_EXTEND"
#: `segment` (default, measured in EXT-001), `auto` or `whole`: what an `extend` task
#: returns.
EXTEND_OUTPUT_SWITCH = "QUALIFY_SEEDANCE_EXTEND_OUTPUT"

SEGMENT = "segment"
WHOLE = "whole"
ExtendOutput = Literal["segment", "whole"]

#: ModelArk's reference-video bounds on Seedance 2.5 (`byteplus_ark`, 2–30 s each and in
#: total): a previous part's file outside them is refused before any spend.
EXTEND_SOURCE_MIN_S = 2.0
EXTEND_SOURCE_MAX_S = 30.0
#: m-25129406: what of the owner's OWN video an «extend» part of a Clip continues — its
#: last seconds, at most these (the input video is billed too: fewer tokens, same idea).
EXTEND_OWN_SOURCE_MAX_S = 10.0

#: The child's own record of what it continued, next to its copied source video
#: (written once per revision before the vendor request is captured).
EXTEND_MANIFEST = "extend-source.json"

#: The statuses of a previous part whose vista previa can be continued.
_SHOWN = frozenset({"generated", "rejected", "approved"})


def extend_available() -> bool:
    """Whether «Sigue a la anterior» parts may be made now (`QUALIFY_PARTS_EXTEND`).
    An unknown value is logged and read as off: never a paid call by a typo."""
    value = os.environ.get(EXTEND_SWITCH, "off").strip().lower()
    if value in ("", "off"):
        return False
    if value == "draft":
        return True
    logger.error("%s must be off or draft, not %r: read as off", EXTEND_SWITCH, value)
    return False


def extend_output(*, output_s: float | None, input_s: float | None, asked_s: float) -> ExtendOutput:
    """What an `extend` task returned: `segment` (only the new stretch) or `whole` (the
    input then the new stretch). `QUALIFY_SEEDANCE_EXTEND_OUTPUT` decides:

    - `segment` (the default; EXT-001 measured 5.000 s back for 5 s asked): `segment`,
      unless the measured length sits closer to input + asked than to asked — then it is
      logged as `creative.extend.unexpected_whole` and read as `whole`, so a vendor change
      never shows the previous part twice;
    - `auto`: whichever reading the measured length is closer to;
    - `whole`: always `whole`.

    A length that cannot be read is `segment` (the join then keeps the first `asked_s`
    seconds, as for any part). An unknown value is logged and read as `segment`. Pure but
    for the switch and the log."""
    setting = os.environ.get(EXTEND_OUTPUT_SWITCH, SEGMENT).strip().lower()
    if setting == WHOLE:
        return WHOLE
    if setting not in ("", SEGMENT, "auto"):
        logger.error("%s must be segment, auto or whole, not %r", EXTEND_OUTPUT_SWITCH, setting)
        setting = SEGMENT
    if output_s is None or input_s is None or input_s <= 0:
        return SEGMENT
    reads_whole = abs(output_s - (input_s + asked_s)) < abs(output_s - asked_s)
    if not reads_whole:
        return SEGMENT
    if setting != "auto":
        logger.warning(
            "creative.extend.unexpected_whole output_s=%.3f input_s=%.3f asked_s=%.3f",
            output_s,
            input_s,
            asked_s,
        )
    return WHOLE


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def extend_offset(part: Mapping[str, Any] | None) -> float:
    """Where the NEW stretch starts in an `extend` part's file, in seconds: the input's
    length when the vendor returned the whole video, else 0. Pure."""
    if not isinstance(part, Mapping) or part.get("mode") != "extend":
        return 0.0
    extend = part.get("extend")
    if not isinstance(extend, Mapping) or extend.get("output") != WHOLE:
        return 0.0
    offset = _number(extend.get("input_seconds"))
    return offset if offset is not None and offset > 0 else 0.0


def source_key(params: Mapping[str, Any] | None) -> str | None:
    """The file an `extend` part after this one continues: the part's raw vendor file
    (`params.part.raw_key`, the queue's byte-for-byte copy), else the file it kept as it
    came (`clean_key`: before the logo, never re-encoded). None when neither is known."""
    part = (params or {}).get("part")
    if not isinstance(part, Mapping):
        return None
    for name in ("raw_key", "clean_key"):
        value = part.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def continued_key(params: Mapping[str, Any] | None) -> str | None:
    """The previous part's file this `extend` part continued (`params.part.extend.
    source_key`), or None for another part or one made before it was recorded."""
    part = (params or {}).get("part")
    extend = part.get("extend") if isinstance(part, Mapping) else None
    value = extend.get("source_key") if isinstance(extend, Mapping) else None
    return value if isinstance(value, str) and value else None


def extend_is_stale(
    *,
    continued: str | None,
    previous_source: str | None,
    own_made_at: float | None,
    previous_made_at: float | None,
) -> bool:
    """«Hay que rehacerla»: the part continued a file the previous part no longer shows.
    With both files known, they are compared (a restored older version of the previous
    part counts too); otherwise the previous vista previa being newer than this one
    decides, as before VE-13. Pure."""
    if continued and previous_source:
        return continued != previous_source
    if own_made_at is None or previous_made_at is None:
        return False
    return previous_made_at > own_made_at


@dataclass(frozen=True)
class SiblingPart:
    """One child of the video by parts, as the lookup needs it."""

    index: int
    draft_id: UUID
    status: str
    removed: bool = False
    purged: bool = False
    asset_id: UUID | None = None
    params: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class PreviousPart:
    """The previous part's file an `extend` part continues."""

    draft_id: UUID
    index: int
    asset_id: UUID | None
    key: str
    made_at: float | None


@dataclass(frozen=True)
class PreviousLookup:
    """`ready` (with `source`), `waiting` (the previous part has no vista previa yet)
    or `missing` (no part before it: the plan was changed under it — a bug to log)."""

    state: Literal["ready", "waiting", "missing"]
    source: PreviousPart | None = None


def pick_previous(
    index: int,
    siblings: Sequence[SiblingPart],
    *,
    removed_indexes: Sequence[int] = (),
    parent_purged: bool = False,
    now: float | None = None,
) -> PreviousLookup:
    """The part right before `index` among the parts kept, and whether its vista previa
    can be continued now: made (`generated`/`rejected`/`approved`), not purged, its draft
    not expired, with a file. A previous index with no child yet (not created) or still
    being made is `waiting`. Pure."""
    removed = set(removed_indexes) | {s.index for s in siblings if s.removed}
    before = [i for i in range(index - 1, 0, -1) if i not in removed]
    if not before or parent_purged:
        return PreviousLookup("missing")
    wanted = before[0]
    previous = next((s for s in siblings if s.index == wanted and not s.removed), None)
    if previous is None or previous.status not in _SHOWN or previous.purged:
        return PreviousLookup("waiting")
    block = draft_state(previous.params)
    moment = time.time() if now is None else now
    if block is not None and draft_expired(block, moment):
        return PreviousLookup("waiting")
    key = source_key(previous.params)
    if key is None:
        return PreviousLookup("waiting")
    made = _number((block or {}).get("created_at"))
    return PreviousLookup(
        "ready",
        PreviousPart(
            draft_id=previous.draft_id,
            index=previous.index,
            asset_id=previous.asset_id,
            key=key,
            made_at=made,
        ),
    )


class DbPreviousParts:
    """`media.PreviousParts` over Postgres, always as the owning tenant (`tenant_session`,
    RLS): a part of another business reads as missing."""

    def __call__(self, *, tenant_id: UUID, draft_id: UUID) -> PreviousLookup:
        with tenant_session(tenant_id) as session:
            me = (
                session.execute(
                    text("""
                    SELECT c.part_index, c.parent_draft_id,
                           p.media_purged_at IS NOT NULL AS parent_purged
                    FROM content_drafts c JOIN content_drafts p ON p.id = c.parent_draft_id
                    WHERE c.id = :d
                    """),
                    {"d": draft_id},
                )
                .mappings()
                .first()
            )
            if me is None or me["part_index"] is None:
                return PreviousLookup("missing")
            rows = (
                session.execute(
                    text("""
                    SELECT c.id, c.part_index, c.status,
                           c.part_removed_at IS NOT NULL AS removed,
                           c.media_purged_at IS NOT NULL AS purged,
                           a.id AS asset_id, a.params
                    FROM content_drafts c
                    LEFT JOIN LATERAL (
                        SELECT id, params FROM image_assets a
                        WHERE a.draft_id = c.id AND a.version_id = c.active_version_id
                          AND a.media_type = 'video'
                        ORDER BY a.position, a.created_at LIMIT 1
                    ) a ON true
                    WHERE c.parent_draft_id = :p AND c.part_index < :i
                    """),
                    {"p": me["parent_draft_id"], "i": me["part_index"]},
                )
                .mappings()
                .all()
            )
        siblings = [
            SiblingPart(
                index=int(row["part_index"]),
                draft_id=row["id"],
                status=str(row["status"]),
                removed=bool(row["removed"]),
                purged=bool(row["purged"]),
                asset_id=row["asset_id"],
                params=row["params"] if isinstance(row["params"], Mapping) else None,
            )
            for row in rows
        ]
        return pick_previous(
            int(me["part_index"]), siblings, parent_purged=bool(me["parent_purged"])
        )


def release_next_extend(session: Session, child_id: UUID) -> None:
    """VE-13 `waiting_previous`: a part settled (its vista previa made or failed, another
    version made or restored) — the «Sigue a la anterior» part right after it, still being
    made, runs its preparation again: with the previous vista previa there it is sent,
    otherwise it waits again (its job stays queued, nothing captured, nothing paid). In the
    caller's transaction. A part already made is never touched: «Hay que rehacerla» is
    the owner's to ask."""
    session.execute(
        text("""
        INSERT INTO creative_pipeline_runs AS r
            (tenant_id, draft_id, revision, phase, pipeline_version)
        SELECT n.tenant_id, n.id, n.revision, 'generation', n.pipeline_version
        FROM content_drafts c
        JOIN content_drafts n ON n.tenant_id = c.tenant_id
            AND n.parent_draft_id = c.parent_draft_id
        JOIN content_briefs nb ON nb.id = n.brief_id
        WHERE c.id = :child AND c.parent_draft_id IS NOT NULL
          AND n.status = 'drafting' AND n.part_removed_at IS NULL
          AND nb.media->'part'->>'mode' = 'extend'
          AND n.part_index = (
              SELECT min(k.part_index) FROM content_drafts k
              WHERE k.parent_draft_id = c.parent_draft_id AND k.part_removed_at IS NULL
                AND k.part_index > c.part_index
          )
        ON CONFLICT (tenant_id, draft_id, revision, phase)
        DO UPDATE SET dirty_version = r.dirty_version + 1
        """),
        {"child": child_id},
    )


__all__ = [
    "EXTEND_MANIFEST",
    "EXTEND_OUTPUT_SWITCH",
    "EXTEND_OWN_SOURCE_MAX_S",
    "EXTEND_SOURCE_MAX_S",
    "EXTEND_SOURCE_MIN_S",
    "EXTEND_SWITCH",
    "SEGMENT",
    "WHOLE",
    "DbPreviousParts",
    "PreviousLookup",
    "PreviousPart",
    "SiblingPart",
    "continued_key",
    "extend_available",
    "extend_is_stale",
    "extend_offset",
    "extend_output",
    "pick_previous",
    "release_next_extend",
    "source_key",
]
