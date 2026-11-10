"""The backend behind the result screen of a video by parts (m-24921082, UI-7). Blocking:
callers run every function in `asyncio.to_thread`.

- `read_progress`: how each part is doing (`read_part_progress`, `tenant_session`, RLS —
  another business's video reads as None).
- `run_action`: what the owner tapped on a part's row, and nothing else — and only when a
  FRESH read (same thread, right before the service) still offers it on that row; else
  `StaleAction`, nothing called, nothing charged — «Intentar de
  nuevo» (`PartRecovery.retry_part`), «Hacerla nueva» (`PartRecovery.make_part_new`),
  «Crearla otra vez» (`PartsService.regenerate_part` with empty `PartChanges`, as
  `final_video.recreate_expired` does). Exceptions keep their types (`PartChangeRefused`,
  `NotEnoughCreations`, `InvalidTransition`, `UnknownDraft`); the state words them.
"""

from __future__ import annotations

from uuid import UUID

from qualify_api.creative.composition import production_content_service
from qualify_api.creative.part_actions import PartRecovery
from qualify_api.creative.part_progress import (
    PartAction,
    PartProgress,
    PartState,
    read_part_progress,
)
from qualify_api.creative.parts import PartChanges, PartsService


class UnservedAction(ValueError):
    """An action the screen does not carry out (no service, or not offered yet)."""


class StaleAction(ValueError):
    """The part moved on since the screen showed the button: the fresh read no longer
    offers this action on it. Nothing was called or charged."""


#: «Crearla otra vez» is another version of a MADE part: only these states may ask it
#: (`regenerate_part` itself does not check, and it charges a vista previa).
RECREATE_STATES = frozenset({PartState.REDO, PartState.EXPIRED})


def read_progress(tenant_id: UUID, parent_id: UUID) -> PartProgress | None:
    """One read of the screen (None: not a video by parts of this business)."""
    return read_part_progress(tenant_id=tenant_id, parent_id=parent_id)


def _parts() -> PartsService:
    return PartsService(production_content_service())


def run_action(
    action: str, *, tenant_id: UUID, parent_id: UUID, part_index: int, user_id: UUID
) -> UUID:
    """Carry out ONE action the owner tapped on part `part_index`. The part's draft id."""
    try:
        wanted = PartAction(action)
    except ValueError as exc:
        raise UnservedAction(action) from exc
    if wanted not in (PartAction.RETRY, PartAction.MAKE_NEW, PartAction.RECREATE):
        # CHANGE needs UI-4's sheet; REMOVE has no service (`SERVED_ACTIONS`)
        raise UnservedAction(action)
    # The screen's rows may be 3 s old: read again, in this thread, right before acting.
    # TODO: switch to PartRecovery.recreate_part once it exists (service-side guard under lock)
    fresh = read_part_progress(tenant_id=tenant_id, parent_id=parent_id)
    row = None if fresh is None else next((r for r in fresh.parts if r.index == part_index), None)
    if row is None or wanted not in row.actions:
        raise StaleAction(action)
    if wanted is PartAction.RECREATE and row.state not in RECREATE_STATES:
        raise StaleAction(action)
    if wanted is PartAction.RETRY:
        return PartRecovery(_parts()).retry_part(
            tenant_id=tenant_id, parent_id=parent_id, part_index=part_index, user_id=user_id
        )
    if wanted is PartAction.MAKE_NEW:
        return PartRecovery(_parts()).make_part_new(
            tenant_id=tenant_id, parent_id=parent_id, part_index=part_index, user_id=user_id
        )
    if wanted is PartAction.RECREATE:
        return _parts().regenerate_part(
            tenant_id=tenant_id,
            parent_id=parent_id,
            part_index=part_index,
            changes=PartChanges(),
            user_id=user_id,
        )
    raise UnservedAction(action)  # pragma: no cover - every served action returned above


__all__ = ["RECREATE_STATES", "StaleAction", "UnservedAction", "read_progress", "run_action"]
