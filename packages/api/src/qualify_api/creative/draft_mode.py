"""Seedance 2.5 draft mode (m-24820142): the state a video made as a 480p draft carries.

A model with a draft mode (2.5) makes every video as a cheap 480p draft; approving the
piece turns it into the 1080p final from the draft's task id alone
(`MediaProducer.finalize`), which then REPLACES the draft in the same `image_assets`
row — every reader (Piezas, downloads, the Planificador) keeps reading the piece's one
video. What the final needs lives in that row's `params["draft"]`.

Its own small module so the Planificador can tell a draft from a final without
importing the media producer.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from qualify_creative.adapters.byteplus_ark import DRAFT_TTL_SECONDS
from qualify_creative.queue_errors import uncertain_error

#: `params["draft"]["status"]`: the 480p draft waiting for approval; the final being
#: made; the final in place; the final failed (retried while the draft id lives).
DRAFT_READY = "draft"
DRAFT_RENDERING = "rendering"
DRAFT_FINAL = "final"
DRAFT_FAILED = "failed"
#: Client-facing: no vendor name (qualify-copy-es) — what the operator does next.
DRAFT_EXPIRED_TEXT = (
    "Las vistas previas duran 7 días. Crea la publicación otra vez para tener una nueva."
)
#: An approved piece whose final was never ordered (the approval was saved, ordering
#: it failed): the operator orders it with «Reintentar».
FINAL_NOT_ORDERED_TEXT = "El video final no se llegó a pedir. Inténtalo de nuevo."


def draft_state(params: Mapping[str, object] | None) -> Mapping[str, Any] | None:
    """The draft block of a video's `params`, or None for a video made directly."""
    block = (params or {}).get("draft")
    return block if isinstance(block, Mapping) else None


def draft_pending(params: Mapping[str, object] | None) -> bool:
    """A video still at its 480p draft — not publishable until its final is in place."""
    block = draft_state(params)
    return block is not None and block.get("status") != DRAFT_FINAL


def kept_raw_final(block: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """The paid 1080p final a failed finish left in the store (`raw_final`, with its
    `key` and provenance), or None: a retry finishes it instead of paying again."""
    raw = (block or {}).get("raw_final")
    if isinstance(raw, Mapping) and isinstance(raw.get("key"), str) and raw["key"]:
        return raw
    return None


def draft_expired(block: Mapping[str, Any], now: float | None = None) -> bool:
    """Whether the draft's id can no longer make a final (7 days from `created_at`,
    Unix seconds). A draft whose date did not come back is left for ModelArk to judge;
    one whose raw final is already paid for and kept (`kept_raw_final`) needs the
    vendor no more, so it never expires."""
    if kept_raw_final(block) is not None:
        return False
    created = block.get("created_at")
    if isinstance(created, bool) or not isinstance(created, int | float):
        return False
    return (time.time() if now is None else now) - created >= DRAFT_TTL_SECONDS


def draft_expires_at(params: list[Mapping[str, object] | None]) -> float | None:
    """When the first of a piece's vistas previas stops being able to give its video
    final (Unix seconds: its `created_at` + 7 days) — for «Apruébala antes del …»
    (founder, 2026-10-24). Only drafts still waiting count (not a final, not one whose
    paid final is kept); None when there is none, or no date came back."""
    ends = []
    for block in (draft_state(p) for p in params):
        if block is None or kept_raw_final(block) is not None:
            continue
        if str(block.get("status") or DRAFT_READY) not in (DRAFT_READY, DRAFT_FAILED):
            continue
        created = block.get("created_at")
        if isinstance(created, bool) or not isinstance(created, int | float):
            continue
        ends.append(float(created) + DRAFT_TTL_SECONDS)
    return min(ends) if ends else None


#: A final still `rendering` this long after its work started (ordered, or claimed by
#: the thread making it) was left by a dead process (an `InlineDispatcher` thread dies
#: with it): the operator may order it again. Over the Seedance adapter's 8-minute poll
#: window plus the download and the re-encode.
FINAL_STALE_SECONDS = 20 * 60
#: What a final left half-made by a dead process says on the screen.
FINAL_STALE_TEXT = (
    "El video final se quedó a medias. Toca Reintentar: sigue donde quedó, sin cobrarte otra vez."
)


def final_stale(block: Mapping[str, Any] | None, now: float | None = None) -> bool:
    """A final `rendering` past `FINAL_STALE_SECONDS` since its work last started."""
    if block is None or block.get("status") != DRAFT_RENDERING:
        return False
    started = block.get("rendering_at")
    if isinstance(started, bool) or not isinstance(started, int | float):
        return False
    return (time.time() if now is None else now) - started >= FINAL_STALE_SECONDS


def final_retryable(
    block: Mapping[str, Any] | None, now: float | None = None, *, approved: bool = False
) -> bool:
    """A final the operator may order again: it failed, or a dead process left it — or,
    on an `approved` piece, it was never ordered (the approval was saved and ordering
    the finals failed: still at its draft)."""
    if block is None:
        return False
    if uncertain_error(block.get("failure_reason")) or uncertain_error(block.get("error")):
        return False
    status = block.get("status") or DRAFT_READY
    if approved and status == DRAFT_READY:
        return True
    return status == DRAFT_FAILED or final_stale(block, now)


def draft_rendering(params: list[Mapping[str, object] | None], now: float | None = None) -> bool:
    """Whether any of a piece's videos has its final being made right now (not stale) —
    what keeps the screen polling even when another video of it already failed."""
    return any(
        block.get("status") == DRAFT_RENDERING and not final_stale(block, now)
        for block in (draft_state(p) for p in params)
        if block is not None
    )


#: `draft_summary` adds this state: a draft (or a failed final) whose id expired.
DRAFT_EXPIRED = "expired"
#: Which state a piece with several draft videos (a carousel) shows: the one that
#: needs the operator first.
_SUMMARY_ORDER = (DRAFT_EXPIRED, DRAFT_FAILED, DRAFT_RENDERING, DRAFT_READY, DRAFT_FINAL)


def draft_summary(
    params: list[Mapping[str, object] | None],
    now: float | None = None,
    *,
    approved: bool = False,
) -> tuple[str, str | None, str]:
    """A piece's draft videos as one state for its screen: (state, the drafts' cost in
    USD as a string or None, the last failure's words). State "" = no draft video. On an
    `approved` piece a video still at its draft never had its final ordered: it shows
    as failed, so the screen offers to order it (`final_retryable`)."""
    blocks = [block for block in (draft_state(p) for p in params) if block is not None]
    if not blocks:
        return "", None, ""
    states = []
    errors = []
    for block in blocks:
        status = str(block.get("status") or DRAFT_READY)
        if status not in _SUMMARY_ORDER:
            status = DRAFT_READY
        if final_stale(block, now):
            # a dead process left it: retryable, like a failed final (`final_retryable`)
            status = DRAFT_FAILED
            errors.append(FINAL_STALE_TEXT)
        elif approved and status == DRAFT_READY:
            status = DRAFT_FAILED
            errors.append(FINAL_NOT_ORDERED_TEXT)
        elif block.get("error"):
            errors.append(str(block["error"]))
        if status in (DRAFT_READY, DRAFT_FAILED) and draft_expired(block, now):
            status = DRAFT_EXPIRED
        states.append(status)
    uncertain = next((error for error in errors if uncertain_error(error)), None)
    state = DRAFT_FAILED if uncertain else min(states, key=_SUMMARY_ORDER.index)
    costs = [block.get("cost_usd") for block in blocks]
    cost = None
    if all(isinstance(c, str) and c for c in costs):
        cost = str(sum((Decimal(str(c)) for c in costs), Decimal(0)))
    return state, cost, uncertain or (errors[-1] if errors else "")
