"""«Buscar reels nuevos» — RF-14 of the reels-filter epic (m-25129383, under m-24872324;
ADR 42 R9, `docs/adr-42-ideas-reels-costo.md`).

The ideas come by themselves every Monday and opening the screen pays nothing (ADR 42 R7).
This is the owner's one paid search on top of that: a `manual` run of the brand for the
business's local day, queued through `reel_runs.enqueue_run` and run by the
`reels-worker` through `reel_runs.run` — the one door that pays. It reads the same accounts
as the Monday run (the referentes and the 6 competitors the owner picked, RF-05) and pays
nothing already read: an account read in the last 24 h, a stored transcript or verdict.

- **At most one a day** per brand and local day (`tenants.timezone`): a second press — a
  double click, or later the same day — never queues another run (the `UNIQUE (brand_id,
  trigger, run_date)` of 0117 holds it even for two presses at once). A finished search is
  never queued again that day, whatever it found — except one the gate stopped BEFORE the
  business's cap (paid reads paused, the vendor's floor: `STATE_STOPPED`), which did not
  happen and is re-queued on the next press, the same row. A failed check the worker will
  retry by itself (R8) still reads as searching; a search in line past `WAIT_LIMIT` reads
  as `STATE_SLOW`, so the button is never busy all day.
- **Inside the business's cap** (`usage.DAILY_CAP` 150 / `usage.MONTHLY_CAP` 600 credits):
  with the cap spent nothing is queued and the owner reads the limit; the gate
  (`scrapecreators.metered_get`) still holds it if it is reached mid-run.
- `search_state` only reads (the screen asks it on opening and while a search runs): it
  never queues, never pays.

This module never calls the vendor nor the model: it reads and writes the brand's own rows
through `tenant_session` (RLS) and leaves the paying to the worker.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from qualify_api.referentes import reel_runs
from qualify_api.referentes.competitors import (
    DAILY_LIMIT_TEXT,
    MONTHLY_LIMIT_TEXT,
    business_zone,
    cap_reached,
)
from qualify_api.referentes.reel_store import (
    STATUS_BUDGET_STOPPED,
    STATUS_CHECK_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TRIGGER_MANUAL,
    ReelRunStore,
    RunRecord,
)
from qualify_api.vendors import usage

# -- what the owner reads (exact, ticket m-25129383; plain Spanish per qualify-copy-es) --
SEARCH_BUTTON = "Buscar reels nuevos"
#: The day's search was already made (whatever it found).
USED_TODAY_TEXT = "Ya buscaste reels nuevos hoy. Vuelve a intentarlo mañana."
#: While the search runs, over the list.
SEARCHING_TEXT = "Estamos buscando reels nuevos. La lista se actualiza sola en unos minutos."
#: The search has been in line longer than `WAIT_LIMIT` (the worker is late or down).
SLOW_TEXT = "La búsqueda está tardando más de lo normal. Vuelve a mirar en un rato."
#: The gate stopped the search before the business's cap: it did not happen.
STOPPED_TEXT = "No pudimos buscar reels nuevos ahora. Inténtalo de nuevo más tarde."
#: How long a search may wait before the screen stops showing it as running (the button
#: works again — a press only reads the list — and the clock stops). A search runs in a
#: few minutes; `reels_ideas_vm.PREPARING_LIMIT` is 10 for the first run.
WAIT_LIMIT = timedelta(minutes=15)

#: `SearchNow.state`.
#: No search today: the button searches.
STATE_IDLE = "idle"
#: Today's search is queued or running.
STATE_SEARCHING = "searching"
#: Today's search ended: another press only reloads what is stored.
STATE_USED = "used"
#: The business's daily or monthly cap is spent: nothing is queued.
STATE_LIMIT = "limit"
#: Today's search is still in line past `WAIT_LIMIT`: the screen stops waiting.
STATE_SLOW = "slow"
#: Today's search was stopped by the gate before the business's cap (paid reads paused,
#: the vendor's floor): it did not happen, so a press queues it again.
STATE_STOPPED = "stopped"
#: The brand cannot search yet (no brief or no account to read): nothing is queued.
STATE_NOT_READY = "not_ready"

#: The cap reasons, by the sentence the owner reads.
_DAILY = usage.REASON_DAILY_CAP
_MONTHLY = usage.REASON_MONTHLY_CAP


@dataclass(frozen=True)
class SearchNow:
    """Where the brand's «Buscar reels nuevos» of today stands."""

    state: str
    #: The sentence the screen shows ("" for `STATE_IDLE` and `STATE_NOT_READY`).
    message: str
    run: RunRecord | None = None


def _today_run(
    store: ReelRunStore, tenant_id: UUID, brand_id: UUID, now: datetime
) -> RunRecord | None:
    today = now.astimezone(business_zone(store, tenant_id)).date()
    return store.manual_run(tenant_id, brand_id, run_date=today)


def _limit(reason: str, tenant_id: UUID, store: ReelRunStore, now: datetime) -> str:
    if reason == _MONTHLY:
        renewal = usage.renewal_label(business_zone(store, tenant_id), now)
        return MONTHLY_LIMIT_TEXT.format(renewal=renewal)
    return DAILY_LIMIT_TEXT


def _state_of(
    run: RunRecord,
    tenant_id: UUID,
    store: ReelRunStore,
    usage_store: usage.UsageStore | None,
    now: datetime,
) -> SearchNow:
    if run.status in (STATUS_QUEUED, STATUS_RUNNING):
        since = reel_runs.waiting_since(run)
        if since is not None and now - since > WAIT_LIMIT:
            return SearchNow(STATE_SLOW, SLOW_TEXT, run)
        return SearchNow(STATE_SEARCHING, SEARCHING_TEXT, run)
    retry = reel_runs.next_retry_at(run, now)
    if run.status == STATUS_CHECK_FAILED and retry is not None:
        # the worker queues a failed check again by itself (R8): still searching
        if now - retry > WAIT_LIMIT:
            return SearchNow(STATE_SLOW, SLOW_TEXT, run)
        return SearchNow(STATE_SEARCHING, SEARCHING_TEXT, run)
    if run.status == STATUS_BUDGET_STOPPED:
        reason = cap_reached(tenant_id, usage_store=usage_store, now=now)
        if reason is not None:
            return SearchNow(STATE_LIMIT, _limit(reason, tenant_id, store, now), run)
        # the gate stopped it for another reason (paid reads paused, the vendor's floor):
        # the day's search did not happen — a press queues it again
        return SearchNow(STATE_STOPPED, STOPPED_TEXT, run)
    return SearchNow(STATE_USED, USED_TODAY_TEXT, run)


def search_state(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    store: ReelRunStore | None = None,
    usage_store: usage.UsageStore | None = None,
    clock: Callable[[], float] = time.time,
) -> SearchNow:
    """Today's search of the brand, for the screen to show the button's state. Only reads:
    never queues, never pays. `STATE_IDLE` when there is none (the cap is judged only when
    the owner presses)."""
    active = store or reel_runs.default_store()
    now = datetime.fromtimestamp(clock(), UTC)
    run = _today_run(active, tenant_id, brand_id, now)
    if run is None:
        return SearchNow(STATE_IDLE, "")
    return _state_of(run, tenant_id, active, usage_store, now)


def search_now(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    store: ReelRunStore | None = None,
    usage_store: usage.UsageStore | None = None,
    ready: Callable[[UUID, UUID], bool] = reel_runs.ready_for_runs,
    clock: Callable[[], float] = time.time,
) -> SearchNow:
    """The owner pressed «Buscar reels nuevos»: queue the brand's `manual` run for the
    business's local day — once — unless the day's search was already made, the cap is
    spent or the brand has nothing to search with. Never pays: the `reels-worker` runs it
    (`manual` runs go before the Monday ones)."""
    active = store or reel_runs.default_store()
    moment = clock()
    now = datetime.fromtimestamp(moment, UTC)
    existing = _today_run(active, tenant_id, brand_id, now)
    stopped = False
    if existing is not None:
        answer = _state_of(existing, tenant_id, active, usage_store, now)
        if answer.state != STATE_STOPPED:
            return answer
        stopped = True  # the gate stopped it before the cap: queue it again (below)
    reason = cap_reached(tenant_id, usage_store=usage_store, now=now)
    if reason is not None:
        return SearchNow(STATE_LIMIT, _limit(reason, tenant_id, active, now))
    if not ready(tenant_id, brand_id):
        return SearchNow(STATE_NOT_READY, "")
    run = reel_runs.enqueue_run(
        tenant_id,
        brand_id,
        TRIGGER_MANUAL,
        run_date=now.astimezone(business_zone(active, tenant_id)).date(),
        retry=stopped,
        store=active,
        clock=lambda: moment,
    )
    # a press racing another one gets the run the other queued — and its state
    return _state_of(run, tenant_id, active, usage_store, now)


__all__ = [
    "DAILY_LIMIT_TEXT",
    "MONTHLY_LIMIT_TEXT",
    "SEARCHING_TEXT",
    "SLOW_TEXT",
    "SEARCH_BUTTON",
    "STATE_IDLE",
    "STATE_LIMIT",
    "STATE_NOT_READY",
    "STATE_SEARCHING",
    "STATE_SLOW",
    "STATE_STOPPED",
    "STATE_USED",
    "STOPPED_TEXT",
    "SearchNow",
    "USED_TODAY_TEXT",
    "WAIT_LIMIT",
    "search_now",
    "search_state",
]
