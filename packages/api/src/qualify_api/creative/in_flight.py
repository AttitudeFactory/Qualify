"""Whether a business has a generation in progress right now (m-24973458).

The menu's «Crear publicación» shows the design system's ring while this is true, on
every screen, so the owner can work elsewhere while a piece is made. One read, one
round trip of three EXISTS branches, through `tenant_session` (RLS confines every
table to the business; nothing here filters by `tenant_id` by hand). Postgres stops at
the first branch that answers; no index is dedicated to it yet (`content_drafts` and
`image_assets` are read through their RLS tenant filter) — fine at today's volume; a
partial index per branch is the next step if a tenant's history grows large.

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
  whose ``rendering_at`` is within the final's stale threshold (``draft_mode``);
- or a final whose queue job waits in the immediate lane and is already due
  (``not_before`` passed): a final sped up from its night, or a retried one, waits there
  with no ``rendering_at`` until the worker claims it — for at most the final's stale
  threshold since it became due (``GREATEST(queued_at, not_before)``: «make it now» and
  a retry set ``not_before`` to now on an older job), past which the piece's screen
  calls it stuck and the menu goes dark too (a worker outage never keeps it lit). A
  final waiting for its night is not "now" and does not light the menu. Not counted: a
  nightly job promoted to the immediate lane after its night passed, or one the worker
  re-queued after a lost lease, when both stamps are older than the threshold — the
  menu lights again as soon as the worker stamps ``rendering_at``.

Not counted (a decision, m-24973458): a piece whose vendor task is still pending after
its run went silent past the window. The reaper spares it up to 49 h and a later run
may resume it, but a ring lit for two days says nothing useful to the owner; the
generator's own screen still shows that piece as waiting.

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
from qualify_api.creative.job_queue import (
    CLAIMED,
    KIND_FINAL,
    LANE_IMMEDIATE,
    QUEUED,
    SUBMITTED,
)

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
          AND CASE WHEN jsonb_typeof(a.params -> 'draft' -> 'rendering_at') = 'number'
                   THEN (a.params -> 'draft' ->> 'rendering_at')::double precision
              END > :rendering_after
    ) OR EXISTS (
        SELECT 1 FROM creative_jobs f
        WHERE f.kind = :final
          AND f.lane = :immediate
          AND f.status IN (:queued, :claimed, :submitted)
          AND f.not_before <= :now
          AND GREATEST(f.queued_at, f.not_before) > :final_after
    )
""")


def in_flight_params(*, now: datetime, epoch_now: float) -> dict[str, object]:
    """The bind values of `IN_FLIGHT_SQL` (pure — tested offline)."""
    return {
        "drafting": DRAFTING,
        "now": now,
        "final": KIND_FINAL,
        "alive_after": now - timedelta(minutes=ALIVE_MINUTES),
        "immediate": LANE_IMMEDIATE,
        "queued": QUEUED,
        "claimed": CLAIMED,
        "submitted": SUBMITTED,
        "rendering": DRAFT_RENDERING,
        "rendering_after": epoch_now - FINAL_STALE_SECONDS,
        # a final queued longer than its stale threshold is what the piece's own
        # screen already calls stuck («Reintentar»): the menu agrees and goes dark
        "final_after": now - timedelta(seconds=FINAL_STALE_SECONDS),
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
