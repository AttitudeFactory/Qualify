"""Whether a business has a generation in progress right now (m-24973458).

The menu's «Crear publicación» shows the design system's ring while this is true, on
every screen, so the owner can work elsewhere while a piece is made. One read, one
round trip, through `tenant_session` (RLS confines every table to the business; nothing
here filters by `tenant_id` by hand).

"In progress" is what the generator itself treats as work being done — never a guess
from the browser:

- a piece in ``drafting`` (Seedream, Seedance, OmniHuman, a template render…) with a
  recent sign of life: ``content_drafts.updated_at``, which the run stamps on entry and
  on every kept file (``dispatch.py``). The window is the reaper's longest one, so a
  draft a dead process left stops lighting the menu when the reaper would fail it —
  never an eternal ring;
- or a ``drafting`` piece whose job waits in the immediate lane of the generation queue
  (ADR 41): it has no stamps while it waits, and the reaper spares it too. A job of the
  nightly lane is not "now" and does not light the menu;
- or a 1080p final being made (``image_assets.params.draft.status = 'rendering'``)
  whose ``rendering_at`` is within the final's stale threshold (``draft_mode``). A final
  waiting for its night (no ``rendering_at``) is not "now" either.

Blocking — the Reflex state calls it with ``asyncio.to_thread``.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.dispatch import DEFAULT_REAP_AFTER_MINUTES, OMNIHUMAN_REAP_AFTER_MINUTES
from qualify_api.creative.draft_mode import DRAFT_RENDERING, FINAL_STALE_SECONDS
from qualify_api.creative.fsm import DRAFTING
from qualify_api.creative.job_queue import CLAIMED, LANE_IMMEDIATE, QUEUED, SUBMITTED

#: How long a ``drafting`` piece without progress still counts as alive: the reaper's
#: longest threshold (a talking presenter), so the ring and the reaper agree.
ALIVE_MINUTES = max(DEFAULT_REAP_AFTER_MINUTES, OMNIHUMAN_REAP_AFTER_MINUTES)

IN_FLIGHT_SQL = text("""
    SELECT EXISTS (
        SELECT 1 FROM content_drafts d
        WHERE d.status = :drafting
          AND (d.updated_at > :alive_after OR EXISTS (
              SELECT 1 FROM creative_jobs j
              WHERE j.draft_id = d.id AND j.revision = d.revision
                AND j.lane = :immediate
                AND j.status IN (:queued, :claimed, :submitted)
          ))
    ) OR EXISTS (
        SELECT 1 FROM image_assets a
        WHERE a.params -> 'draft' ->> 'status' = :rendering
          AND jsonb_typeof(a.params -> 'draft' -> 'rendering_at') = 'number'
          AND (a.params -> 'draft' ->> 'rendering_at')::double precision > :rendering_after
    )
""")


def in_flight_params(*, now: datetime, epoch_now: float) -> dict[str, object]:
    """The bind values of `IN_FLIGHT_SQL` (pure — tested offline)."""
    return {
        "drafting": DRAFTING,
        "alive_after": now - timedelta(minutes=ALIVE_MINUTES),
        "immediate": LANE_IMMEDIATE,
        "queued": QUEUED,
        "claimed": CLAIMED,
        "submitted": SUBMITTED,
        "rendering": DRAFT_RENDERING,
        "rendering_after": epoch_now - FINAL_STALE_SECONDS,
    }


def generation_in_flight(
    tenant_id: UUID, *, now: datetime | None = None, epoch_now: float | None = None
) -> bool:
    """True while the business has a piece or a final being made (module docstring)."""
    params = in_flight_params(
        now=now or datetime.now(UTC),
        epoch_now=time.time() if epoch_now is None else epoch_now,
    )
    with tenant_session(tenant_id) as session:
        return bool(session.execute(IN_FLIGHT_SQL, params).scalar_one())


__all__ = ["ALIVE_MINUTES", "IN_FLIGHT_SQL", "generation_in_flight", "in_flight_params"]
