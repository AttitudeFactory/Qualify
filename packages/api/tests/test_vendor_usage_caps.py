"""Per-business caps on ScrapeCreators reads (ADR 42 R5, m-24854849) — offline: the
gate's raw request is replaced by a counting fake and the usage store is an
`InMemoryUsageStore`. Nothing here can reach the vendor or Postgres (the atomic
check-and-book over Postgres is `test_vendor_usage_caps_db.py`).

Acceptance (ticket m-24854849):
1. with 149 credits spent today, of two calls only the first goes; the second is refused
   (`tenant_daily_cap`) and the run records the stop (`budget_stopped`, `stopped`);
2. the monthly cap (600) over events spread across several days, in local time;
3. a shared account read by one business is charged to that business only.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest

from qualify_api.referentes import MemoryReferentesRepository, reels
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_store import (
    STATUS_BUDGET_STOPPED,
    STATUS_OK,
    TRIGGER_OPERATOR_90D,
    MemoryReelRunStore,
)
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

from .test_referentes_reel_runs import (
    FEEDS,
    NOW,
    TENANT_A,
    TENANT_B,
    Claude,
    Clock,
    Vendor,
    _brand,
    _run,
)

BOGOTA = "America/Bogota"


class Wire:
    """The vendor's side of `sc._vendor_request`: answers 200, counts requests."""

    def __init__(self, body: dict[str, Any] | None = None) -> None:
        self.body = body or {"success": True, "credits_remaining": 5000, "credits_charged": 1}
        self.requests: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, client: httpx.Client, path: str, params: dict[str, str]) -> httpx.Response:
        with self._lock:
            self.requests.append(path)
        return httpx.Response(
            200, json=self.body, request=httpx.Request("GET", f"https://vendor.test{path}")
        )


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_caps")
    fake = Wire()
    monkeypatch.setattr(sc, "_vendor_request", fake)
    return fake


@pytest.fixture
def store() -> usage.InMemoryUsageStore:
    active = usage.InMemoryUsageStore({TENANT_A: BOGOTA, TENANT_B: BOGOTA})
    usage.configure_store(active)
    return active


def _spend(
    store: usage.InMemoryUsageStore, tenant: UUID, credits: int, at: datetime | None = None
) -> None:
    """Credits already booked for `tenant` (default: a minute ago)."""
    store.events.append(
        usage.UsageEvent(
            tenant_id=tenant,
            brand_id=None,
            vendor=usage.SCRAPECREATORS,
            feature=sc.FEATURE_REELS_LIST,
            credits=credits,
            usd_estimate=Decimal("0"),
            pricing_table_version=usage.PRICING_TABLE_VERSION,
            request_key=f"seed:{uuid4()}",
            created_at=at or datetime.now(UTC) - timedelta(minutes=1),
        )
    )


def _call(charge: usage.UsageCharge | None, feature: str = sc.FEATURE_PROFILE) -> dict:
    with usage.bind(httpx.Client(), charge) as client:
        return sc.metered_get(client, "/v1/tiktok/profile", {"handle": "x"}, feature=feature)


def _spent_now(store: usage.InMemoryUsageStore, tenant: UUID) -> usage.Spent:
    return store.spent(tenant, usage.SCRAPECREATORS, datetime.now(UTC))


# --------------------------------------------------------------------------------------
# criterion 1 — 149 + 2: the second call is not made, the stop is recorded
# --------------------------------------------------------------------------------------


def test_at_149_the_first_call_goes_and_the_second_is_not_made(
    wire: Wire, store: usage.InMemoryUsageStore
) -> None:
    _spend(store, TENANT_A, 149)
    charge = usage.UsageCharge(TENANT_A)
    assert _call(charge)["success"] is True
    with pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _call(charge)
    assert caught.value.reason == usage.REASON_DAILY_CAP
    assert len(wire.requests) == 1  # the second request never left
    assert _spent_now(store, TENANT_A).day == 150  # the refused call booked nothing


def test_a_run_at_149_reads_one_account_and_stops_budget_stopped(
    wire: Wire, store: usage.InMemoryUsageStore, world: Any
) -> None:
    run_store, repo, vendor, claude, _ = world
    brand = _brand(repo, TENANT_A)
    _spend(store, TENANT_A, 149)
    vendor.fetch = _paying_fetch

    outcome = _run(TENANT_A, brand, world)
    assert outcome.status == STATUS_BUDGET_STOPPED
    assert outcome.stopped == usage.REASON_DAILY_CAP  # the stop, recorded on the run
    assert run_store.runs[outcome.run_id].status == STATUS_BUDGET_STOPPED
    assert len(wire.requests) == 1 and claude.asked == []  # account 2 was never read
    booked = [e for e in store.of(TENANT_A) if not e.request_key.startswith("seed:")]
    assert [(e.credits, e.brand_id, e.feature) for e in booked] == [(1, brand, "reels_list")]
    # the refused account is free again for the next run (its lock was released)
    state = run_store.account(TENANT_A, "tiktok", "vecino")
    assert state is None or state.refresh_lock_until is None


def _paying_fetch(network: str, handle: str, *, client: httpx.Client, **_: Any) -> list[dict]:
    """A list read that pays through the real gate (on the run's own client)."""
    sc.metered_get(client, f"/v1/{network}/reels", {"handle": handle}, feature="reels_list")
    return [dict(r) for r in FEEDS[handle]]


def _paying_transcript(reel: dict[str, Any], client: httpx.Client) -> str:
    sc.metered_get(client, "/v1/instagram/media/transcript", {}, feature="reels_transcript")
    return "dicen algo"


# --------------------------------------------------------------------------------------
# criterion 2 — the monthly cap, over several days, in the business's local time
# --------------------------------------------------------------------------------------


def test_the_monthly_cap_sums_the_days_of_the_local_month(
    store: usage.InMemoryUsageStore,
) -> None:
    def event(moment: datetime, credits: int = 1) -> usage.UsageEvent:
        return usage.UsageEvent(
            TENANT_A,
            None,
            usage.SCRAPECREATORS,
            "profile",
            credits,
            Decimal("0"),
            usage.PRICING_TABLE_VERSION,
            f"k:{uuid4()}",
            moment,
        )

    # 2026-11 in Bogotá (UTC-5): 150 on each of the 2nd, 9th, 16th and 23rd = 600
    for day in (2, 9, 16, 23):
        _spend(store, TENANT_A, 150, at=datetime(2026, 11, day, 15, tzinfo=UTC))
    on_the_24th = datetime(2026, 11, 24, 15, tzinfo=UTC)
    assert store.spent(TENANT_A, usage.SCRAPECREATORS, on_the_24th) == usage.Spent(0, 600)
    assert store.book(event(on_the_24th), capped=True) == usage.REASON_MONTHLY_CAP
    # the business's month starts at 00:00 in Bogotá: 04:59 UTC on Dec 1st is still Nov
    late_november = datetime(2026, 12, 1, 4, 59, tzinfo=UTC)
    assert store.book(event(late_november), capped=True) == usage.REASON_MONTHLY_CAP
    december = datetime(2026, 12, 1, 5, 0, tzinfo=UTC)
    assert store.book(event(december), capped=True) is None
    assert store.spent(TENANT_A, usage.SCRAPECREATORS, december) == usage.Spent(1, 1)


def test_the_monthly_cap_stops_the_gate(wire: Wire, store: usage.InMemoryUsageStore) -> None:
    now = datetime.now(UTC)
    day_start, month_start = usage.local_bounds(now, ZoneInfo(BOGOTA))
    if day_start == month_start:
        pytest.skip("on the 1st of the local month there are no earlier days to spread over")
    # 600 booked earlier this local month (before today), nothing today
    for n in range(4):
        _spend(store, TENANT_A, 150, at=month_start + timedelta(minutes=n))
    assert _spent_now(store, TENANT_A) == usage.Spent(0, 600)
    with pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _call(usage.UsageCharge(TENANT_A))
    assert caught.value.reason == usage.REASON_MONTHLY_CAP and wire.requests == []


def test_the_day_is_the_business_local_day(store: usage.InMemoryUsageStore) -> None:
    # 23:30 in Bogotá on Nov 10 is 04:30 UTC on Nov 11: it is Nov 10's spending
    _spend(store, TENANT_A, 150, at=datetime(2026, 11, 11, 4, 30, tzinfo=UTC))
    same_local_day = datetime(2026, 11, 11, 4, 45, tzinfo=UTC)
    assert store.spent(TENANT_A, usage.SCRAPECREATORS, same_local_day).day == 150
    next_local_day = datetime(2026, 11, 11, 5, 0, tzinfo=UTC)  # 00:00 in Bogotá
    assert store.spent(TENANT_A, usage.SCRAPECREATORS, next_local_day).day == 0


# --------------------------------------------------------------------------------------
# criterion 3 — a shared account is charged to the business that triggered the read
# --------------------------------------------------------------------------------------


def test_a_shared_account_is_charged_only_to_the_business_that_read_it(
    wire: Wire, store: usage.InMemoryUsageStore, world: Any
) -> None:
    _, repo, vendor, _, _ = world
    brand_a, brand_b = _brand(repo, TENANT_A), _brand(repo, TENANT_B)
    vendor.fetch, vendor.transcribe = _paying_fetch, _paying_transcript

    first = _run(TENANT_A, brand_a, world)
    paid = len(wire.requests)
    assert paid > 2  # the two lists and the transcripts
    second = _run(TENANT_B, brand_b, world)
    assert first.status == STATUS_OK and second.status == STATUS_OK
    assert len(wire.requests) == paid  # B found everything stored: no call at all
    assert store.of(TENANT_B) == []  # ... so B is charged nothing
    a = store.of(TENANT_A)
    assert len(a) == paid and {e.brand_id for e in a} == {brand_a}
    assert {e.feature for e in a} == {"reels_list", "reels_transcript"}
    assert all(e.pricing_table_version == usage.PRICING_TABLE_VERSION for e in a)
    assert all(e.usd_estimate == usage.usd_per_credit() for e in a)


# --------------------------------------------------------------------------------------
# the gate's other rules
# --------------------------------------------------------------------------------------


def test_a_call_no_business_is_charged_for_is_not_made(
    wire: Wire, store: usage.InMemoryUsageStore
) -> None:
    # founder decision 2026-11-04 («incluir todo»): every paid read is some business's
    with usage.uncharged(), pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _call(None)
    assert caught.value.reason == usage.REASON_NO_TENANT
    assert wire.requests == [] and store.events == []


def test_the_context_charges_a_client_bound_to_nobody(
    wire: Wire, store: usage.InMemoryUsageStore
) -> None:
    brand = uuid4()
    with usage.charge_to(TENANT_A, brand):
        _call(None, feature=sc.FEATURE_SEARCH)
    assert [(e.tenant_id, e.brand_id, e.feature) for e in store.events] == [
        (TENANT_A, brand, "referentes_search")
    ]


def test_extra_credits_the_vendor_charged_are_booked_after_the_answer(
    wire: Wire, store: usage.InMemoryUsageStore
) -> None:
    wire.body = {"success": True, "credits_remaining": 5000, "credits_charged": 3}
    _call(usage.UsageCharge(TENANT_A))
    assert sorted(e.credits for e in store.of(TENANT_A)) == [1, 2]
    assert _spent_now(store, TENANT_A).day == 3


def test_the_switch_and_the_floor_refuse_before_anything_is_booked(
    wire: Wire, store: usage.InMemoryUsageStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(sc.PAID_SWITCH_ENV, "off")
    with pytest.raises(sc.ScrapeCreatorsBlocked):
        _call(usage.UsageCharge(TENANT_A))
    assert store.events == [] and wire.requests == []


def test_an_unreadable_usage_store_fails_closed(wire: Wire) -> None:
    class Broken:
        def book(self, event: usage.UsageEvent, *, capped: bool) -> str | None:
            raise RuntimeError("db down")

        def spent(self, *_: Any) -> usage.Spent:
            raise RuntimeError("db down")

    usage.configure_store(Broken())
    with pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _call(usage.UsageCharge(TENANT_A))
    assert caught.value.reason == usage.REASON_USAGE_UNREADABLE and wire.requests == []


def test_parallel_calls_at_149_let_exactly_one_through(
    wire: Wire, store: usage.InMemoryUsageStore
) -> None:
    _spend(store, TENANT_A, 149)
    charge = usage.UsageCharge(TENANT_A)
    outcomes: list[str] = []
    barrier = threading.Barrier(8)

    def one() -> None:
        barrier.wait()
        try:
            _call(charge)
            outcomes.append("ok")
        except sc.ScrapeCreatorsBlocked as exc:
            outcomes.append(exc.reason)

    threads = [threading.Thread(target=one) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["ok"] + [usage.REASON_DAILY_CAP] * 7
    assert len(wire.requests) == 1


def test_the_operators_90_day_run_is_capped_too(
    wire: Wire, store: usage.InMemoryUsageStore, world: Any
) -> None:
    # founder decision 2026-11-04 («incluir todo»): no read is exempt from the cap
    _, repo, vendor, _, _ = world
    brand = _brand(repo, TENANT_A)
    _spend(store, TENANT_A, 150)
    vendor.fetch = _paying_fetch

    outcome = _run(TENANT_A, brand, world, trigger=TRIGGER_OPERATOR_90D)
    assert outcome.status == STATUS_BUDGET_STOPPED
    assert outcome.stopped == usage.REASON_DAILY_CAP and wire.requests == []


def test_the_legacy_discover_charges_its_reads_to_the_business(
    wire: Wire, store: usage.InMemoryUsageStore, world: Any
) -> None:
    _, repo, _, _, _ = world
    brand = _brand(repo, TENANT_A)
    clients: list[Any] = []

    def fetch(network: str, handle: str, *, client: httpx.Client, **_: Any) -> list[dict]:
        clients.append(usage.charge_of(client))
        return [dict(r) for r in FEEDS[handle]]

    reels.discover(TENANT_A, brand, now=NOW, repository=repo, fetch=fetch, brief=None)
    assert clients and all(c == usage.UsageCharge(TENANT_A, brand) for c in clients)


@pytest.fixture
def world() -> Any:
    return MemoryReelRunStore(), MemoryReferentesRepository(), Vendor(), Claude(), Clock()


def test_the_run_binds_its_charge_for_the_worker_threads() -> None:
    ctx = rr._Context(
        tenant_id=TENANT_A,
        brand_id=uuid4(),
        run_id=uuid4(),
        days=30,
        now=datetime.now(UTC),
        store=None,  # type: ignore[arg-type]
        clock=lambda: NOW,
        sleep=lambda s: None,
        charge=usage.UsageCharge(TENANT_A),
    )
    with rr._counting_client(ctx, 1.0) as client:
        seen: list[Any] = []
        worker = threading.Thread(target=lambda: seen.append(usage.charge_of(client)))
        worker.start()
        worker.join()
    assert seen == [usage.UsageCharge(TENANT_A)]


# --------------------------------------------------------------------------------------
# R5 round 2: the Reflex paths, the in-process serialisation, the copy
# --------------------------------------------------------------------------------------


async def test_charge_to_survives_asyncio_to_thread() -> None:
    import asyncio

    with usage.charge_to(TENANT_B):
        seen = await asyncio.to_thread(usage.current)
    assert seen == usage.UsageCharge(TENANT_B)


def test_bookings_of_one_tenant_hold_at_most_one_connection_per_process() -> None:
    """C1: a 12-thread fan-out never drains the pool waiting on the advisory lock."""
    import contextlib
    import time

    active = 0
    peak = 0
    guard = threading.Lock()

    class Session:
        def execute(self, statement: Any, params: dict | None = None) -> Any:
            sql = str(statement)

            class Result:
                def scalar_one_or_none(self) -> str:
                    return "America/Bogota"

                def scalar_one(self) -> datetime:
                    return datetime.now(UTC)

                def one(self) -> Any:
                    return type("Row", (), {"day": 0, "month": 0})()

            if "pg_advisory_xact_lock" in sql:
                time.sleep(0.01)  # the wait a real advisory lock would cost
            return Result()

    @contextlib.contextmanager
    def session_factory(tenant: UUID) -> Any:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        try:
            yield Session()
        finally:
            with guard:
                active -= 1

    pg = usage.PostgresUsageStore(session_factory=session_factory)
    barrier = threading.Barrier(12)

    def one(tenant: UUID) -> None:
        barrier.wait()
        pg.book(
            usage.UsageEvent(
                tenant, None, usage.SCRAPECREATORS, "profile", 1, Decimal("0"), "v7", str(uuid4())
            ),
            capped=True,
        )

    threads = [threading.Thread(target=one, args=(TENANT_A,)) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1  # one tenant: one connection at a time in this process

    peak = 0
    barrier = threading.Barrier(12)
    threads = [threading.Thread(target=one, args=(t,)) for t in [TENANT_A, TENANT_B] * 6]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 2  # two tenants do not wait on each other


def test_an_unreadable_zone_counts_in_utc_and_warns_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING", logger="qualify_api.vendors.usage")
    subject = str(uuid4())
    assert usage.zone_of("Mars/Olympus", subject=subject).key == "UTC"
    assert usage.zone_of("Mars/Olympus", subject=subject).key == "UTC"
    assert usage.zone_of(None, subject=subject).key == "UTC"
    warnings = [r for r in caplog.records if subject in r.getMessage()]
    assert len(warnings) == 2  # once per unreadable value, never per booking


def test_the_cap_copy_names_when_to_search_again() -> None:
    bogota = ZoneInfo(BOGOTA)
    # 2026-12-01 03:00 UTC is still Nov 30 in Bogotá: the renewal is Dec 1st
    end_of_november = datetime(2026, 12, 1, 3, tzinfo=UTC)
    assert usage.cap_notice(usage.REASON_DAILY_CAP, zone=bogota) == (
        "Ya hiciste todas las búsquedas de hoy. Mañana puedes buscar de nuevo."
    )
    assert usage.cap_notice(usage.REASON_MONTHLY_CAP, zone=bogota, now=end_of_november) == (
        "Este mes ya hiciste todas las búsquedas. Desde el 1 de diciembre puedes buscar de nuevo."
    )
    december = datetime(2026, 12, 15, tzinfo=UTC)
    assert usage.cap_notice(usage.REASON_MONTHLY_CAP, zone=bogota, now=december) == (
        "Este mes ya hiciste todas las búsquedas. Desde el 1 de enero puedes buscar de nuevo."
    )
    assert usage.cap_notice(usage.REASON_DAILY_CAP, zone=bogota, profile=True) == (
        "Hoy ya no podemos leer tu perfil. Completa tus datos tú mismo; mañana podremos leerlo."
    )
    assert usage.cap_notice(
        usage.REASON_MONTHLY_CAP, zone=bogota, profile=True, now=end_of_november
    ) == (
        "Este mes ya no podemos leer tu perfil. Completa tus datos tú mismo; "
        "desde el 1 de diciembre podremos leerlo."
    )
    assert usage.cap_title(usage.REASON_DAILY_CAP) == "Por hoy ya no hay más búsquedas"
    assert usage.cap_title(usage.REASON_MONTHLY_CAP) == "Este mes ya no hay más búsquedas"
    for other in ("below_floor", "switch_off", "halted", usage.REASON_NO_TENANT, None):
        assert usage.cap_notice(other, zone=bogota) is None  # keeps its screen's own copy
        assert usage.cap_title(other) is None


def test_a_capped_legacy_read_carries_its_notice(
    wire: Wire, store: usage.InMemoryUsageStore, world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, repo, _, _, _ = world
    brand = _brand(repo, TENANT_A)
    _spend(store, TENANT_A, 150)
    monkeypatch.setattr(usage, "tenant_zone", lambda tenant: ZoneInfo(BOGOTA))
    found = reels.discover(TENANT_A, brand, now=NOW, repository=repo, fetch=_paying_fetch)
    assert found.check == reels.CHECK_READ_UNAVAILABLE
    assert found.cap_notice == usage.DAILY_CAP_NOTICE and wire.requests == []
    assert found.cap_title == "Por hoy ya no hay más búsquedas"
