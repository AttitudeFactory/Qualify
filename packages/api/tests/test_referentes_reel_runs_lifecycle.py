"""The run's lifecycle under the `reels-worker` (`reel_runs` + `reel_store`, ADR 42 R8,
m-24854855), offline over `MemoryReelRunStore`: the vendor and Claude are fakes that
count their calls (nothing reaches ScrapeCreators or Anthropic).

Pins the architect's R8 decisions: the claim counts `attempts` and «Intentar de nuevo»
resets them; `progress` and `finish` write only under the claim that set `started_at`
(fencing); `RunInterrupted` (the worker's SIGTERM) puts the run back in the queue, frees
the account lock and keeps the account's status; `mark_opened` writes only forward, at
most once an hour, and never raises; `ensure_first_run` queues this week's weekly run
(the LOCAL Monday) only for a brand with no run, a brief and accounts — and never pays.
Postgres is `test_reels_worker_db.py`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.referentes import (
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
)
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_store import (
    ACCOUNT_OK,
    STATUS_CHECK_FAILED,
    STATUS_OK,
    STATUS_QUEUED,
    STATUS_RUNNING,
    MemoryReelRunStore,
)
from qualify_api.vendors import scrapecreators as sc

TENANT = UUID("a0000000-0000-4000-8000-0000000000a1")
OTHER = UUID("b0000000-0000-4000-8000-0000000000b2")
BRIEF = review_ai.BrandBrief(handle="burgerco", rubro=("hamburguesería",))
#: Wednesday 2026-11-11 15:00 UTC = 10:00 in Bogotá: that week's Monday is 2026-11-09.
WEDNESDAY = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)


def _epoch(moment: datetime = WEDNESDAY) -> float:
    return moment.timestamp()


def _brand_with_a_referente(repo: MemoryReferentesRepository, tenant: UUID) -> UUID:
    brand = uuid4()
    repo.add_brand(tenant_id=tenant, brand_id=brand)
    repo.save_phase(
        NewDiscoveryPhase(
            tenant_id=tenant,
            brand_id=brand,
            phase_key="sector",
            algorithm_version=1,
            seed_signature="s",
            seed={"handle": "burgerco", "terms": ["hamburguesería"], "hashtags": []},
            title="Sector",
            accounts=(
                NewDiscoveredAccount(network="instagram", handle="foodie", card={"kind": "c"}),
            ),
        )
    )
    repo.set_label(
        tenant_id=tenant,
        brand_id=brand,
        network="instagram",
        handle="foodie",
        label="referente",
        labeled_by=None,
    )
    return brand


def _queued(store: MemoryReelRunStore, trigger: str = "manual") -> Any:
    return rr.enqueue_run(TENANT, uuid4(), trigger, store=store, clock=_epoch)


# --------------------------------------------------------------------------------------
# attempts and the fence
# --------------------------------------------------------------------------------------


def test_the_claim_counts_attempts_and_a_retry_resets_them() -> None:
    store = MemoryReelRunStore()
    run = _queued(store)
    assert run.attempts == 0
    claimed = store.claim(TENANT, run.id, now=WEDNESDAY)
    assert claimed is not None and claimed.attempts == 1
    assert store.claim(TENANT, run.id, now=WEDNESDAY) is None  # only a queued run
    assert store.abandon(TENANT, run.id, started_at=WEDNESDAY, now=WEDNESDAY)
    retried = rr.enqueue_run(TENANT, run.brand_id, "manual", store=store, clock=_epoch, retry=True)
    assert retried.status == STATUS_QUEUED and retried.attempts == 0


def test_progress_and_finish_write_only_under_their_own_claim() -> None:
    store = MemoryReelRunStore()
    run = _queued(store)
    first = store.claim(TENANT, run.id, now=WEDNESDAY)
    assert first is not None and first.started_at == WEDNESDAY
    # the worker recovered it (its process looked dead) and another attempt took it
    assert store.release(TENANT, run.id, started_at=WEDNESDAY)
    later = WEDNESDAY + timedelta(minutes=31)
    assert store.claim(TENANT, run.id, now=later) is not None
    # the first process wakes up: none of its writes land
    assert not store.progress(
        TENANT, run.id, accounts_total=5, accounts_done=5, started_at=WEDNESDAY
    )
    assert not store.finish(
        TENANT,
        run.id,
        status=STATUS_OK,
        now=later,
        credits=40,
        cost_usd=Decimal("1"),
        brief_hash="h",
        started_at=WEDNESDAY,
    )
    record = store.runs[run.id]
    assert (record.status, record.accounts_done, record.credits) == (STATUS_RUNNING, 0, 0)
    # the current attempt's writes do
    assert store.progress(TENANT, run.id, accounts_total=2, accounts_done=1, started_at=later)
    assert store.finish(
        TENANT,
        run.id,
        status=STATUS_OK,
        now=later,
        credits=3,
        cost_usd=Decimal("0"),
        brief_hash=None,
        started_at=later,
    )
    assert store.runs[run.id].status == STATUS_OK
    # another tenant never reaches the run
    assert not store.release(OTHER, run.id, started_at=later)


def test_a_run_recovered_meanwhile_is_not_recorded_by_the_old_process() -> None:
    store = MemoryReelRunStore()
    run = _queued(store)

    def brief(tenant_id: UUID, brand_id: UUID) -> None:
        # while this attempt works, the worker recovers the run and starts it again
        assert store.release(TENANT, run.id, started_at=WEDNESDAY)
        assert store.claim(TENANT, run.id, now=WEDNESDAY + timedelta(minutes=31)) is not None
        return None

    outcome = rr.run(TENANT, run.id, store=store, brief=brief, clock=_epoch)
    assert outcome.status == STATUS_CHECK_FAILED and outcome.recorded is False
    record = store.runs[run.id]
    assert record.status == STATUS_RUNNING and record.attempts == 2  # the new attempt's


# --------------------------------------------------------------------------------------
# the stop: RunInterrupted
# --------------------------------------------------------------------------------------


def test_an_interrupted_read_releases_the_run_and_the_account_and_keeps_its_status() -> None:
    store, repo = MemoryReelRunStore(), MemoryReferentesRepository()
    brand = _brand_with_a_referente(repo, TENANT)
    run = rr.enqueue_run(TENANT, brand, "manual", store=store, clock=_epoch)
    reads: list[str] = []

    def fetch(network: str, handle: str, **_: Any) -> list[dict[str, Any]]:
        reads.append(handle)
        raise rr.RunInterrupted("signal 15")  # the SIGTERM lands during the vendor read

    with pytest.raises(rr.RunInterrupted):
        rr.run(
            TENANT,
            run.id,
            store=store,
            repository=repo,
            brief=lambda tenant, b: BRIEF,
            api_key="k",
            fetch=fetch,
            clock=_epoch,
            sleep=lambda seconds: None,
        )
    assert reads == ["foodie"]
    record = store.runs[run.id]
    assert record.status == STATUS_QUEUED and record.started_at is None
    assert record.attempts == 1 and record.accounts_done == 0
    account = store.accounts[("instagram", "foodie")]
    assert account.refresh_lock_until is None  # the next run does not wait 10 min
    assert account.status == ACCOUNT_OK and account.page1_at is None  # nothing faked


def test_run_interrupted_is_not_an_exception_run_swallows() -> None:
    assert issubclass(rr.RunInterrupted, BaseException)
    assert not issubclass(rr.RunInterrupted, Exception)


def test_a_gate_refusal_still_keeps_the_account_status() -> None:
    """R4's behaviour, unchanged by the R8 refactor of `_refresh_account`."""
    store, repo = MemoryReelRunStore(), MemoryReferentesRepository()
    brand = _brand_with_a_referente(repo, TENANT)
    run = rr.enqueue_run(TENANT, brand, "manual", store=store, clock=_epoch)

    def refused(*_: Any, **__: Any) -> Any:
        raise sc.ScrapeCreatorsBlocked("floor", reason="below_floor")

    outcome = rr.run(
        TENANT,
        run.id,
        store=store,
        repository=repo,
        brief=lambda tenant, b: BRIEF,
        api_key="k",
        fetch=refused,
        clock=_epoch,
        sleep=lambda seconds: None,
    )
    assert outcome.status == "budget_stopped"
    assert store.accounts[("instagram", "foodie")].status == ACCOUNT_OK


# --------------------------------------------------------------------------------------
# mark_opened
# --------------------------------------------------------------------------------------


def test_mark_opened_writes_forward_at_most_once_an_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    store, brand = MemoryReelRunStore(), uuid4()
    moment = {"now": WEDNESDAY}
    monkeypatch.setattr(rr, "time", SimpleNamespace(time=lambda: _epoch(moment["now"])))

    rr.mark_opened(TENANT, brand, store=store)
    assert store.activity[brand] == (TENANT, WEDNESDAY)
    writes = store.writes
    moment["now"] = WEDNESDAY + timedelta(minutes=59)
    rr.mark_opened(TENANT, brand, store=store)
    assert store.activity[brand] == (TENANT, WEDNESDAY) and store.writes == writes
    moment["now"] = WEDNESDAY + timedelta(hours=1)
    rr.mark_opened(TENANT, brand, store=store)
    assert store.activity[brand] == (TENANT, WEDNESDAY + timedelta(hours=1))
    moment["now"] = WEDNESDAY - timedelta(days=1)  # a clock behind: never backwards
    rr.mark_opened(TENANT, brand, store=store)
    assert store.activity[brand] == (TENANT, WEDNESDAY + timedelta(hours=1))


def test_mark_opened_never_raises(caplog: pytest.LogCaptureFixture) -> None:
    class Down(MemoryReelRunStore):
        def mark_opened(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("database away")

    assert rr.mark_opened(TENANT, uuid4(), store=Down()) is None
    assert "was not recorded" in caplog.text


# --------------------------------------------------------------------------------------
# ensure_first_run (option A)
# --------------------------------------------------------------------------------------


@pytest.fixture
def first_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A brand with a brief and one account, a tenant in Bogotá, the clock on Wednesday;
    the brief builder and the accounts are fakes of the database reads."""
    env: dict[str, Any] = {"brief": BRIEF, "accounts": ["@foodie"], "store": MemoryReelRunStore()}
    env["store"].timezones[TENANT] = "America/Bogota"
    monkeypatch.setattr(rr, "time", SimpleNamespace(time=lambda: _epoch(WEDNESDAY)))
    monkeypatch.setattr(rr.brief_builder, "brand_brief", lambda tenant, brand: env["brief"])
    monkeypatch.setattr(rr.reels, "brand_referentes", lambda tenant, brand: env["accounts"])
    return env


def test_ensure_first_run_queues_this_weeks_weekly_run_on_the_local_monday(
    first_run: dict[str, Any],
) -> None:
    store, brand = first_run["store"], uuid4()
    assert rr.ensure_first_run(TENANT, brand, store=store) is True
    [record] = store.runs.values()
    assert (record.brand_id, record.trigger, record.status) == (brand, "weekly", STATUS_QUEUED)
    assert record.run_date == date(2026, 11, 9)  # Monday, local; never a UTC "today"
    # the Monday scheduler's run for that week is the same UNIQUE row: nothing is added
    again = rr.enqueue_run(
        TENANT, brand, "weekly", run_date=date(2026, 11, 9), store=store, clock=_epoch
    )
    assert again.id == record.id and len(store.runs) == 1
    # and a second opening does nothing: the brand has a run now
    assert rr.ensure_first_run(TENANT, brand, store=store) is False and len(store.runs) == 1


def test_ensure_first_run_needs_no_run_a_brief_and_accounts(first_run: dict[str, Any]) -> None:
    store = first_run["store"]
    had_one = uuid4()
    rr.enqueue_run(TENANT, had_one, "manual", store=store, clock=_epoch)
    assert rr.ensure_first_run(TENANT, had_one, store=store) is False

    first_run["brief"] = None
    assert rr.ensure_first_run(TENANT, uuid4(), store=store) is False
    first_run["brief"], first_run["accounts"] = BRIEF, []
    assert rr.ensure_first_run(TENANT, uuid4(), store=store) is False
    assert len(store.runs) == 1  # only the manual run above


def test_ensure_first_run_never_raises(first_run: dict[str, Any]) -> None:
    store = first_run["store"]
    store.timezones.clear()  # the tenant's timezone cannot be read
    assert rr.ensure_first_run(TENANT, uuid4(), store=store) is False
    assert store.runs == {}
