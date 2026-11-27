"""The owner's competitors in «Ideas para tus reels» — RF-05 of the reels-filter epic
(m-25119465, under m-24872324; decision 5 of `docs/epica-filtrado-reels.md`, signed by
Deivid on 2026-11-25; amends ADR 42 R4/R8).

The Monday run (`reel_runs.run`) reads the reels of the accounts labelled `competencia`
besides the referentes — but only `reels.MAX_WEEKLY_COMPETITORS` (6) of them:

- **Choosing the 6** (`choose_weekly`): the owner ticks which ones; stored on the label
  (`brand_account_labels.read_weekly`, 0183). Nothing ticked = the first 6 of the list
  (`position`, then when it was labelled). With more than 6, the rest are never read by
  themselves (`reels.brand_competitors`).
- **«Ver sus reels ahora»** (`read_now`): any competitor, read at the owner's request —
  a `competitor_now` run for that account and the business's local day, queued through
  `reel_runs.enqueue_run` and run by the `reels-worker` through `reel_runs.run`, the one
  door that pays (ADR 42 R4/R8 as amended). Idempotent: a second press the same day
  returns the same run (`uq_brand_reel_run`), and the run itself pays nothing already
  read (an account fresh in `reel_accounts`, a stored transcript or verdict). When the
  business's daily cap is spent (`usage.DAILY_CAP`, 150 credits) nothing is queued and
  the owner reads `DAILY_LIMIT_TEXT`; the gate (`scrapecreators.metered_get`) still holds
  the cap if it is reached mid-read.

Detractors are never read nor offered (decision 3). Every competitor credit is booked under
the `competitor_reels_*` features of `vendor_usage_events`, and kept apart in
`brand_reel_runs.competitor_credits` / `competitor_cost_usd`, so the competitors' spend is
measured apart from the referentes'. Their verdicts feed «Más reels revisados»
(`reviewed_reels`, the «Competidores» kind); the 6-8 ideas stay the referentes' (R11).

This module never calls the vendor nor the model: it reads and writes the brand's own rows
through `tenant_session` (RLS) and leaves the paying to the worker.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from qualify_api.referentes import reel_runs, reel_schedule, reels
from qualify_api.referentes.reel_store import (
    STATUS_BUDGET_STOPPED,
    STATUS_OK,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TRIGGER_COMPETITOR_NOW,
    ReelRunStore,
    RunRecord,
)
from qualify_api.referentes.reels import CompetitorAccount
from qualify_api.referentes.repository import normalize_handle
from qualify_api.vendors import uncapped, usage

logger = logging.getLogger(__name__)

MAX_WEEKLY = reels.MAX_WEEKLY_COMPETITORS

# -- what the owner reads (exact, ticket m-25119465; plain Spanish per qualify-copy-es) --
#: The ticket's selector title. NOT shown any more: option A (Deivid, 2026-11-25) moved
#: the panel into a drawer titled «Tus competidores» (`Qualify/reels_competitors_vm`).
WEEKLY_PICKER_TITLE = "Elige cuáles 6 competidores leemos cada lunes"
#: The button of a competitor outside the 6.
READ_NOW_BUTTON = "Ver sus reels ahora"
#: The daily cap is spent: nothing is read.
DAILY_LIMIT_TEXT = "Hoy ya se alcanzó el límite de lecturas de tu negocio. Inténtalo mañana."
#: The monthly cap is spent (the day's sentence would promise «mañana» wrongly).
MONTHLY_LIMIT_TEXT = (
    "Este mes ya se alcanzó el límite de lecturas de tu negocio. "
    "Podrás intentarlo de nuevo desde el {renewal}."
)
#: The read is queued or running. RF-13 (m-25120327): the screen shows one list with no
#: «Más reels revisados» heading, so the sentences name «tus ideas», the screen's list.
READING_TEXT = "Estamos leyendo sus reels. En unos minutos los verás en tus ideas."
#: The read ended: its reels that fit the business are in the screen's one list.
DONE_TEXT = "Listo. Sus reels ya están en tus ideas."
#: The read could not be done (no way to review them now, or the reads are paused).
FAILED_TEXT = "No pudimos leer sus reels ahora. Inténtalo de nuevo en unos minutos."
#: More than 6 ticked.
TOO_MANY_TEXT = "Puedes elegir hasta 6 competidores."

#: `ReadNow.state`.
STATE_READING = "reading"
STATE_DONE = "done"
STATE_LIMIT = "limit"
STATE_FAILED = "failed"
#: The account is not (or no longer) one of the brand's competitors: nothing queued.
STATE_NOT_COMPETITOR = "not_competitor"


class TooManyPicks(ValueError):
    """More than `MAX_WEEKLY` competitors chosen; the owner reads `TOO_MANY_TEXT`."""


@dataclass(frozen=True)
class ReadNow:
    """Where the owner's «Ver sus reels ahora» on one competitor stands."""

    state: str
    #: The sentence the screen shows ("" for `STATE_NOT_COMPETITOR`).
    message: str
    run: RunRecord | None = None


def _account(network: str, handle: str) -> tuple[str, str]:
    return network.strip().lower(), normalize_handle(handle)


def choose_weekly(
    tenant_id: UUID,
    brand_id: UUID,
    picks: Iterable[tuple[str, str]],
    *,
    repository: Any = None,
) -> list[CompetitorAccount]:
    """Store which competitors the Monday run reads (`read_weekly`), replacing the earlier
    choice; an empty choice goes back to «the first 6 of the list». Raises `TooManyPicks`
    above `MAX_WEEKLY` and `ValueError` for an account that is not one of the brand's
    competitors. Returns the competitors as the selector shows them now."""
    repo = repository or reels.default_repository()
    wanted = list(dict.fromkeys(_account(n, h) for n, h in picks))
    if len(wanted) > MAX_WEEKLY:
        raise TooManyPicks(TOO_MANY_TEXT)
    known = {
        (a.network, a.handle)
        for a in reels.competitor_accounts(tenant_id, brand_id, repository=repo)
    }
    unknown = [account for account in wanted if account not in known]
    if unknown:
        raise ValueError(f"not a competitor of this brand: {unknown[0][0]}/@{unknown[0][1]}")
    repo.set_weekly_picks(tenant_id=tenant_id, brand_id=brand_id, picks=wanted)
    return reels.competitor_accounts(tenant_id, brand_id, repository=repo)


def business_zone(store: ReelRunStore, tenant_id: UUID) -> ZoneInfo:
    """The business's zone (`tenants.timezone`, through the runs store); UTC when unknown."""
    try:
        return reel_schedule.zone(store.timezone(tenant_id))
    except (LookupError, ValueError):
        return ZoneInfo("UTC")


def local_day(store: ReelRunStore, tenant_id: UUID, now: datetime) -> date:
    """The business's local date at `now` (UTC when its zone is unknown): the day a manual
    read belongs to, the same day the daily cap counts."""
    return now.astimezone(business_zone(store, tenant_id)).date()


def cap_reached(
    tenant_id: UUID,
    *,
    usage_store: usage.UsageStore | None = None,
    now: datetime | None = None,
) -> str | None:
    """`usage.REASON_DAILY_CAP` / `REASON_MONTHLY_CAP` when one more credit would cross the
    business's cap, else None. A business uncapped from its «Alta de cliente» is never
    capped. Usage that cannot be read gives None: the gate refuses the read itself then."""
    if uncapped.is_uncapped(tenant_id):
        return None
    try:
        spent = (usage_store or usage.store()).spent(tenant_id, usage.SCRAPECREATORS, now)
    except Exception as exc:  # noqa: BLE001 - the gate decides when the usage is unreadable
        logger.warning("competitor read: usage of %s unreadable: %s", tenant_id, type(exc).__name__)
        return None
    return usage.refusal(spent, 1)


@dataclass(frozen=True)
class _Moment:
    """One reading of the clock, with the business's zone and usage ledger."""

    tenant_id: UUID
    now: datetime
    zone: ZoneInfo
    usage_store: usage.UsageStore | None


def _limit(reason: str, at: _Moment, run: RunRecord | None = None) -> ReadNow:
    if reason == usage.REASON_MONTHLY_CAP:
        renewal = usage.renewal_label(at.zone, at.now)
        return ReadNow(STATE_LIMIT, MONTHLY_LIMIT_TEXT.format(renewal=renewal), run)
    return ReadNow(STATE_LIMIT, DAILY_LIMIT_TEXT, run)


def _state_of(run: RunRecord, at: _Moment) -> ReadNow:
    if run.status in (STATUS_QUEUED, STATUS_RUNNING):
        return ReadNow(STATE_READING, READING_TEXT, run)
    if run.status == STATUS_OK:
        return ReadNow(STATE_DONE, DONE_TEXT, run)
    if run.status == STATUS_BUDGET_STOPPED:
        reason = cap_reached(at.tenant_id, usage_store=at.usage_store, now=at.now)
        if reason is not None:
            return _limit(reason, at, run)
    return ReadNow(STATE_FAILED, FAILED_TEXT, run)


def read_now(
    tenant_id: UUID,
    brand_id: UUID,
    network: str,
    handle: str,
    *,
    store: ReelRunStore | None = None,
    repository: Any = None,
    usage_store: usage.UsageStore | None = None,
    clock: Callable[[], float] = time.time,
) -> ReadNow:
    """The owner pressed «Ver sus reels ahora» on a competitor: queue its read for today —
    once — unless the business's cap is spent. Returns where it stands. Never pays: the
    `reels-worker` runs the read (`competitor_now` runs go before the Monday ones)."""
    account = _account(network, handle)
    competitors = reels.competitor_accounts(tenant_id, brand_id, repository=repository)
    if account not in {(a.network, a.handle) for a in competitors}:
        return ReadNow(STATE_NOT_COMPETITOR, "")
    active = store or reel_runs.default_store()
    moment = clock()
    at = _Moment(
        tenant_id=tenant_id,
        now=datetime.fromtimestamp(moment, UTC),
        zone=business_zone(active, tenant_id),
        usage_store=usage_store,
    )
    today = at.now.astimezone(at.zone).date()
    existing = _today(active, tenant_id, brand_id, today).get(account)
    if existing is not None and existing.status in (STATUS_QUEUED, STATUS_RUNNING, STATUS_OK):
        return _state_of(existing, at)
    reason = cap_reached(tenant_id, usage_store=usage_store, now=at.now)
    if reason is not None:
        return _limit(reason, at, existing)
    run = reel_runs.enqueue_run(
        tenant_id,
        brand_id,
        TRIGGER_COMPETITOR_NOW,
        run_date=today,
        retry=True,  # a read that failed today is queued again by pressing again
        account=account,
        store=active,
        clock=lambda: moment,
    )
    return _state_of(run, at)


def _today(
    store: ReelRunStore, tenant_id: UUID, brand_id: UUID, today: date
) -> dict[tuple[str, str], RunRecord]:
    out: dict[tuple[str, str], RunRecord] = {}
    for run in store.competitor_runs(tenant_id, brand_id, run_date=today):  # newest first
        if run.account_network and run.account_handle:
            out.setdefault((run.account_network, run.account_handle), run)
    return out


def read_states(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    store: ReelRunStore | None = None,
    usage_store: usage.UsageStore | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[tuple[str, str], ReadNow]:
    """`(network, handle) → ReadNow` of today's manual reads of the brand's competitors,
    for the screen to show each button's state. Only reads."""
    active = store or reel_runs.default_store()
    at = _Moment(
        tenant_id=tenant_id,
        now=datetime.fromtimestamp(clock(), UTC),
        zone=business_zone(active, tenant_id),
        usage_store=usage_store,
    )
    today = at.now.astimezone(at.zone).date()
    return {
        account: _state_of(run, at)
        for account, run in _today(active, tenant_id, brand_id, today).items()
    }


__all__ = [
    "DAILY_LIMIT_TEXT",
    "DONE_TEXT",
    "FAILED_TEXT",
    "MAX_WEEKLY",
    "MONTHLY_LIMIT_TEXT",
    "READING_TEXT",
    "READ_NOW_BUTTON",
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_LIMIT",
    "STATE_NOT_COMPETITOR",
    "STATE_READING",
    "TOO_MANY_TEXT",
    "WEEKLY_PICKER_TITLE",
    "ReadNow",
    "TooManyPicks",
    "business_zone",
    "cap_reached",
    "choose_weekly",
    "local_day",
    "read_now",
    "read_states",
]
