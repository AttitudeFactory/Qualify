"""The backend behind the result screen of a video by parts (m-24921082, UI-7). Blocking:
callers run every function in `asyncio.to_thread`.

- `read_progress`: how each part is doing (`read_part_progress`, `tenant_session`, RLS —
  another business's video reads as None).
- `run_action`: what the owner tapped on a part's row, and nothing else — and only when a
  FRESH read (same thread, right before the service) still offers it on that row; else
  `StaleAction`, nothing called, nothing charged. Every action goes through
  `PartRecovery`, which checks again under the video's lock: «Intentar de nuevo»
  (`retry_part`), «Hacerla nueva» (`make_part_new`), «Crearla otra vez»
  (`recreate_part`), «Quitar parte» (`remove_part`, m-24985192). Exceptions keep their
  types (`PartChangeRefused`, `NotEnoughCreations`, `InvalidTransition`, `UnknownDraft`);
  the state words them.
- `part_previews` (m-24992894): what each part with a vista previa plays on its row —
  short-lived `/r2media` paths of its video and poster (`r2_media.issue_view_path`, the
  same door as «Tu video completo»: "" when no token can be minted, never an error)
  and its length in seconds. No database read: it signs what `read_progress` returned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from qualify_api.creative.composition import production_content_service
from qualify_api.creative.part_actions import PartRecovery
from qualify_api.creative.part_progress import (
    PartAction,
    PartProgress,
    PartState,
    read_part_progress,
)
from qualify_api.creative.parts import PartsService

from .r2_media import is_r2_key, issue_view_path

logger = logging.getLogger(__name__)


class UnservedAction(ValueError):
    """An action the screen does not carry out (no service, or not offered yet)."""


class StaleAction(ValueError):
    """The part moved on since the screen showed the button: the fresh read no longer
    offers this action on it. Nothing was called or charged."""


#: «Crearla otra vez» is another version of a MADE part: only these states may ask it
#: (`recreate_part` checks it again under the video's lock; it charges a vista previa).
RECREATE_STATES = frozenset({PartState.REDO, PartState.EXPIRED})


def read_progress(tenant_id: UUID, parent_id: UUID) -> PartProgress | None:
    """One read of the screen (None: not a video by parts of this business)."""
    return read_part_progress(tenant_id=tenant_id, parent_id=parent_id)


@dataclass(frozen=True)
class PartPreview:
    """The vista previa a part's row plays (m-24992894). `video_url` / `poster_url`:
    `/r2media/<token>` paths (1 h; "" when not minted — the row then shows no player /
    no poster). `seconds`: the clip's own length, else the part's planned seconds."""

    index: int
    video_url: str
    poster_url: str
    seconds: float


def _view(tenant_id: UUID, key: str, media_type: str) -> str:
    """A short-lived `/r2media` path for an R2 key of this business ("" otherwise, or
    when no token can be minted: a preview is not worth failing the screen)."""
    if not key or not is_r2_key(key):
        return ""
    try:
        return issue_view_path(tenant_id, key, media_type)
    except Exception as exc:  # noqa: BLE001 — a missing preview must not break the rows
        logger.warning("part preview token not issued: %s", type(exc).__name__)
        return ""


def part_previews(tenant_id: UUID, progress: PartProgress | None) -> dict[int, PartPreview]:
    """Each row with a vista previa to watch (`has_preview`) by its `index` (its place
    in the plan, as the state's rows), with its signed video and poster. A row without
    one is absent. Mints tokens (Redis), reads no row."""
    if progress is None:
        return {}
    previews: dict[int, PartPreview] = {}
    for row in progress.parts:
        if not row.has_preview or not row.preview_video_key:
            continue
        previews[row.index] = PartPreview(
            index=row.index,
            video_url=_view(tenant_id, row.preview_video_key, "video"),
            poster_url=_view(tenant_id, row.preview_poster_key, "image"),
            seconds=float(row.preview_seconds or row.seconds),
        )
    return previews


def _parts() -> PartsService:
    return PartsService(production_content_service())


#: What the screen carries out, each through `PartRecovery` (CHANGE waits for UI-4).
_SERVED = (PartAction.RETRY, PartAction.MAKE_NEW, PartAction.RECREATE, PartAction.REMOVE)


def run_action(
    action: str, *, tenant_id: UUID, parent_id: UUID, part_index: int, user_id: UUID
) -> UUID | bool:
    """Carry out ONE action the owner tapped on part `part_index`: the part's draft id,
    or for «Quitar parte» whether this call removed it (`remove_part`)."""
    try:
        wanted = PartAction(action)
    except ValueError as exc:
        raise UnservedAction(action) from exc
    if wanted not in _SERVED:
        raise UnservedAction(action)  # CHANGE needs UI-4's sheet
    # The screen's rows may be 3 s old: read again, in this thread, right before acting
    # (the services check again under the video's lock).
    fresh = read_part_progress(tenant_id=tenant_id, parent_id=parent_id)
    row = None if fresh is None else next((r for r in fresh.parts if r.index == part_index), None)
    if row is None or wanted not in row.actions:
        raise StaleAction(action)
    if wanted is PartAction.RECREATE and row.state not in RECREATE_STATES:
        raise StaleAction(action)
    recovery = PartRecovery(_parts())
    ids = {
        "tenant_id": tenant_id,
        "parent_id": parent_id,
        "part_index": part_index,
        "user_id": user_id,
    }
    if wanted is PartAction.RETRY:
        return recovery.retry_part(**ids)
    if wanted is PartAction.MAKE_NEW:
        return recovery.make_part_new(**ids)
    if wanted is PartAction.RECREATE:
        return recovery.recreate_part(**ids)
    return recovery.remove_part(**ids)


__all__ = [
    "RECREATE_STATES",
    "PartPreview",
    "StaleAction",
    "UnservedAction",
    "part_previews",
    "read_progress",
    "run_action",
]
