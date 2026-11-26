"""RF-14 (m-25129383): «Buscar reels nuevos» — the owner's paid search, at most once per
brand and local day, through `reel_runs` (the one door that pays), inside the business's
150/600 cap, reading the same accounts as the Monday run.

Offline: the vendor's wire is a counting fake behind the REAL gate
(`scrapecreators.metered_get`, `sc._vendor_request` patched as in
`test_referentes_competitors.py`), the usage ledger is `InMemoryUsageStore`, Claude is
scripted. The runs are R4's real `reel_runs.run`, drained the way the reels-worker does.
No paid call leaves the process.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.claude_tools import CallStats
from qualify_api.referentes import (
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
    manual_search,
    reels_ai,
)
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_queue import MemoryReelQueue
from qualify_api.referentes.reel_store import (
    STATUS_BUDGET_STOPPED,
    STATUS_OK,
    STATUS_QUEUED,
    TRIGGER_MANUAL,
    TRIGGER_WEEKLY,
    MemoryReelRunStore,
)
from qualify_api.referentes.reels_ai import ReelReview, ReelToReview
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

BOGOTA = "America/Bogota"
#: Wednesday 2026-11-11 10:00 in Bogotá (UTC-5).
WEDNESDAY = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
TENANT_A = UUID("a0000000-0000-4000-8000-0000000000a1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000000b2")
BRIEF = review_ai.BrandBrief(handle="burgerco", rubro=("hamburguesería",))


def _reel(handle: str, reel_id: str, views: int) -> dict[str, Any]:
    return {
        "id": reel_id,
        "network": "instagram",
        "handle": handle,
        "url": f"https://www.instagram.com/reel/{reel_id}/",
        "caption": "burger del día",
        "cover": "",
        "takenAt": WEDNESDAY.timestamp() - 2 * 86_400,
        "views": views,
        "likes": views // 10,
        "comments": 1,
        "shares": None,
        "saves": None,
        "seconds": 20,
        "sound": "Audio original",
        "video": f"https://scontent.cdninstagram.com/{reel_id}.mp4",
    }


#: Referente: @foodie. Competitors: @rival0 … @rival7 (in this order).
FEEDS: dict[str, list[dict[str, Any]]] = {
    "foodie": [_reel("foodie", "F1", 9_000)],
    **{f"rival{i}": [_reel(f"rival{i}", f"R{i}", 1_000 + i)] for i in range(8)},
}


class Wire:
    """The vendor's side of `sc._vendor_request`: answers 200, records each path."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, client: httpx.Client, path: str, params: dict[str, str]) -> httpx.Response:
        with self._lock:
            self.requests.append(path)
        body = {"success": True, "credits_remaining": 5000, "credits_charged": 1}
        response = httpx.Response(
            200, json=body, request=httpx.Request("GET", f"https://api.scrapecreators.com{path}")
        )
        for hook in client.event_hooks["response"]:  # what `client.get` would run
            hook(response)
        return response


@dataclass
class Vendor:
    lists: list[str] = field(default_factory=list)

    def fetch(
        self, network: str, handle: str, *, since: float, client: httpx.Client, max_pages: int
    ) -> list[dict[str, Any]]:
        sc.metered_get(client, f"/v1/{network}/reels", {"handle": handle}, feature="reels_list")
        self.lists.append(handle)
        return [dict(r) for r in FEEDS[handle]]

    def transcribe(self, reel: dict[str, Any], client: httpx.Client) -> str:
        sc.metered_get(client, "/v1/instagram/media/transcript", {}, feature="reels_transcript")
        return "dicen burger del día"


@dataclass
class Claude:
    asked: list[str] = field(default_factory=list)

    def review(self, brief: Any, batch: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
        self.asked.extend(r.id for r in batch)
        answers = [
            ReelReview(
                id=r.id,
                fits=True,
                reason=f"ok {r.id}",
                format="receta",
                hook="pregunta",
                affinity="producto",
            )
            for r in batch
        ]
        return answers, CallStats(reels_ai.REVIEW_MODEL, None, 1000, 100)


def _brand(repo: MemoryReferentesRepository, tenant: UUID, rivals: int = 8) -> UUID:
    brand = uuid4()
    repo.add_brand(tenant_id=tenant, brand_id=brand)
    handles = ["foodie", *(f"rival{i}" for i in range(rivals))]
    repo.save_phase(
        NewDiscoveryPhase(
            tenant_id=tenant,
            brand_id=brand,
            phase_key="sector",
            algorithm_version=1,
            seed_signature="s",
            seed={"handle": "burgerco", "terms": ["hamburguesería"], "hashtags": []},
            title="Sector",
            accounts=tuple(
                NewDiscoveredAccount(network="instagram", handle=h, card={"kind": "marca"})
                for h in handles
            ),
        )
    )
    repo.set_label(
        tenant_id=tenant, brand_id=brand, network="instagram", handle="foodie", label="referente"
    )
    for i in range(rivals):
        repo.set_label(
            tenant_id=tenant,
            brand_id=brand,
            network="instagram",
            handle=f"rival{i}",
            label="competencia",
        )
    repo.set_positions(
        tenant_id=tenant,
        brand_id=brand,
        positions={("instagram", f"rival{i}"): i for i in range(rivals)},
    )
    return brand


@dataclass
class World:
    store: MemoryReelRunStore = field(default_factory=MemoryReelRunStore)
    repo: MemoryReferentesRepository = field(default_factory=MemoryReferentesRepository)
    vendor: Vendor = field(default_factory=Vendor)
    claude: Claude = field(default_factory=Claude)
    now: datetime = WEDNESDAY
    #: The brands `ready_for_runs` would accept (a brief and an account to read).
    ready: set[UUID] = field(default_factory=set)

    def clock(self) -> float:
        return self.now.timestamp()

    def press(self, tenant: UUID, brand: UUID) -> manual_search.SearchNow:
        return manual_search.search_now(
            tenant,
            brand,
            store=self.store,
            ready=lambda t, b: b in self.ready,
            clock=self.clock,
        )

    def state(self, tenant: UUID, brand: UUID) -> manual_search.SearchNow:
        return manual_search.search_state(tenant, brand, store=self.store, clock=self.clock)

    def run(self, tenant_id: UUID, run_id: UUID) -> rr.RunOutcome:
        return rr.run(
            tenant_id,
            run_id,
            store=self.store,
            repository=self.repo,
            brief=lambda tenant, brand: BRIEF,
            api_key="k",
            fetch=self.vendor.fetch,
            transcribe_fetch=self.vendor.transcribe,
            review=self.claude.review,
            clock=self.clock,
            sleep=lambda seconds: None,
        )

    def drain(self) -> list[rr.RunOutcome]:
        """What the reels-worker does: run the queued runs, `manual` before `weekly`."""
        queue, out = MemoryReelQueue(self.store), []
        while (nxt := queue.next_run()) is not None:
            out.append(self.run(nxt.tenant_id, nxt.run_id))
        return out


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_rf14")
    fake = Wire()
    monkeypatch.setattr(sc, "_vendor_request", fake)
    return fake


@pytest.fixture
def ledger() -> usage.InMemoryUsageStore:
    active = usage.InMemoryUsageStore({TENANT_A: BOGOTA, TENANT_B: BOGOTA})
    usage.configure_store(active)  # the conftest puts the default back after the test
    return active


@pytest.fixture
def world() -> World:
    found = World()
    for tenant in (TENANT_A, TENANT_B):
        found.store.timezones[tenant] = BOGOTA
    return found


def _brand_ready(world: World, tenant: UUID, rivals: int = 8) -> UUID:
    brand = _brand(world.repo, tenant, rivals=rivals)
    world.ready.add(brand)
    return brand


def _spend(
    ledger: usage.InMemoryUsageStore, tenant: UUID, credits: int, *, at: datetime | None = None
) -> None:
    ledger.events.append(
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


def _manual_runs(world: World, tenant: UUID) -> list[Any]:
    return [r for r in world.store.runs.values() if r.tenant_id == tenant and r.trigger == "manual"]


def _paid(ledger: usage.InMemoryUsageStore, tenant: UUID) -> int:
    return sum(e.credits for e in ledger.of(tenant) if not e.request_key.startswith("seed:"))


# --------------------------------------------------------------------------------------
# one search a day, through the one door that pays
# --------------------------------------------------------------------------------------


def test_a_press_queues_one_manual_run_and_the_worker_reads_the_mondays_accounts(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand_ready(world, TENANT_A, rivals=8)
    pressed = world.press(TENANT_A, brand)
    assert pressed.state == manual_search.STATE_SEARCHING
    assert pressed.message == manual_search.SEARCHING_TEXT
    assert pressed.run is not None and pressed.run.status == STATUS_QUEUED
    assert pressed.run.trigger == TRIGGER_MANUAL
    # the business's local day (10:00 in Bogotá)
    assert pressed.run.run_date == WEDNESDAY.date()
    assert wire.requests == []  # pressing never pays: the worker does

    (outcome,) = world.drain()
    assert outcome.status == STATUS_OK and outcome.ideas >= 1
    # the same accounts as the Monday run: the referentes and the 6 competitors picked
    assert world.vendor.lists == ["foodie", *(f"rival{i}" for i in range(6))]
    record = world.store.get_run(TENANT_A, pressed.run.id)
    assert record is not None and record.trigger == TRIGGER_MANUAL
    # every credit booked in the usage ledger, and counted on the run
    assert record.credits == _paid(ledger, TENANT_A) > 0
    assert record.credits <= usage.DAILY_CAP
    assert world.state(TENANT_A, brand).state == manual_search.STATE_USED


def test_a_double_click_queues_one_search(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand_ready(world, TENANT_A)
    first = world.press(TENANT_A, brand)
    second = world.press(TENANT_A, brand)
    assert first.run is not None and second.run is not None
    assert second.run.id == first.run.id
    assert second.state == manual_search.STATE_SEARCHING
    assert len(_manual_runs(world, TENANT_A)) == 1


def test_two_presses_at_the_same_moment_queue_one_search(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand_ready(world, TENANT_A)
    barrier = threading.Barrier(4)
    answers: list[manual_search.SearchNow] = []
    lock = threading.Lock()

    def press() -> None:
        barrier.wait()
        answer = world.press(TENANT_A, brand)
        with lock:
            answers.append(answer)

    threads = [threading.Thread(target=press) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(_manual_runs(world, TENANT_A)) == 1
    assert {a.run.id for a in answers if a.run is not None} == {_manual_runs(world, TENANT_A)[0].id}


def test_a_second_try_the_same_day_queues_nothing_and_says_so(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand_ready(world, TENANT_A)
    world.press(TENANT_A, brand)
    world.drain()
    paid = len(wire.requests)
    world.now += timedelta(hours=8)  # 18:00 in Bogotá: the same local day
    again = world.press(TENANT_A, brand)
    assert again.state == manual_search.STATE_USED
    assert again.message == "Ya buscaste reels nuevos hoy. Vuelve a intentarlo mañana."
    assert world.drain() == []
    assert len(wire.requests) == paid
    assert len(_manual_runs(world, TENANT_A)) == 1


def test_the_day_is_the_businesss_not_the_servers(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    """23:30 in Bogotá is already tomorrow in UTC: still the business's same day."""
    brand = _brand_ready(world, TENANT_A)
    world.press(TENANT_A, brand)
    world.drain()
    world.now = datetime(2026, 11, 12, 4, 30, tzinfo=UTC)  # Wednesday 23:30 in Bogotá
    assert world.press(TENANT_A, brand).state == manual_search.STATE_USED
    world.now = datetime(2026, 11, 12, 5, 30, tzinfo=UTC)  # Thursday 00:30 in Bogotá
    tomorrow = world.press(TENANT_A, brand)
    assert tomorrow.state == manual_search.STATE_SEARCHING
    assert tomorrow.run is not None and tomorrow.run.run_date.isoformat() == "2026-11-12"
    assert len(_manual_runs(world, TENANT_A)) == 2


def test_a_search_the_day_after_the_monday_run_pays_nothing_already_read(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand_ready(world, TENANT_A)
    weekly = rr.enqueue_run(TENANT_A, brand, TRIGGER_WEEKLY, store=world.store, clock=world.clock)
    world.run(TENANT_A, weekly.id)
    paid, asked = len(wire.requests), len(world.claude.asked)
    world.now += timedelta(hours=3)  # same day: every account read under 24 h ago
    world.press(TENANT_A, brand)
    (outcome,) = world.drain()
    assert outcome.status == STATUS_OK
    assert len(wire.requests) == paid  # nothing paid twice
    assert len(world.claude.asked) == asked  # every verdict reused
    # the list keeps what is stored: the manual run's ideas are the same reels
    view = rr.view(TENANT_A, brand, store=world.store)
    assert view.shown is not None and view.shown.trigger == TRIGGER_MANUAL
    assert [i.reel.handle for i in view.ideas] == ["foodie"]


# --------------------------------------------------------------------------------------
# the business's cap
# --------------------------------------------------------------------------------------


def test_with_the_daily_cap_spent_nothing_is_queued_and_the_owner_reads_it(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand_ready(world, TENANT_A)
    _spend(ledger, TENANT_A, usage.DAILY_CAP)
    answer = world.press(TENANT_A, brand)
    assert answer.state == manual_search.STATE_LIMIT
    assert answer.message == (
        "Hoy ya se alcanzó el límite de lecturas de tu negocio. Inténtalo mañana."
    )
    assert answer.run is None
    assert _manual_runs(world, TENANT_A) == []
    assert wire.requests == []


def test_with_the_monthly_cap_spent_the_owner_reads_when_it_renews(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand_ready(world, TENANT_A)
    # the month spent on earlier days: today itself is free
    _spend(ledger, TENANT_A, usage.MONTHLY_CAP, at=WEDNESDAY - timedelta(days=3))
    answer = world.press(TENANT_A, brand)
    assert answer.state == manual_search.STATE_LIMIT
    assert answer.message == (
        "Este mes ya se alcanzó el límite de lecturas de tu negocio. "
        "Podrás intentarlo de nuevo desde el 1 de diciembre."
    )
    assert answer.run is None and wire.requests == []


def test_a_search_the_cap_stops_midway_never_passes_it_and_says_the_limit(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand_ready(world, TENANT_A)
    _spend(ledger, TENANT_A, usage.DAILY_CAP - 1)
    pressed = world.press(TENANT_A, brand)
    assert pressed.state == manual_search.STATE_SEARCHING
    _spend(ledger, TENANT_A, 1)  # another read of the business spends the last credit
    (outcome,) = world.drain()
    assert outcome.status == STATUS_BUDGET_STOPPED
    assert wire.requests == []  # the gate held the cap: nothing paid past it
    spent = ledger.spent(TENANT_A, usage.SCRAPECREATORS)
    assert spent.day <= usage.DAILY_CAP and spent.month <= usage.MONTHLY_CAP
    state = world.state(TENANT_A, brand)
    assert state.state == manual_search.STATE_LIMIT
    assert state.message == manual_search.DAILY_LIMIT_TEXT
    # pressing again queues nothing
    assert world.press(TENANT_A, brand).state == manual_search.STATE_LIMIT
    assert world.drain() == []


# --------------------------------------------------------------------------------------
# opening the screen pays nothing; a brand that cannot search queues nothing
# --------------------------------------------------------------------------------------


def test_looking_at_the_search_never_writes_nor_pays(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand_ready(world, TENANT_A)
    writes = world.store.writes
    assert world.state(TENANT_A, brand) == manual_search.SearchNow(manual_search.STATE_IDLE, "")
    assert world.store.writes == writes
    assert wire.requests == [] and _paid(ledger, TENANT_A) == 0
    world.press(TENANT_A, brand)
    writes = world.store.writes
    assert world.state(TENANT_A, brand).state == manual_search.STATE_SEARCHING
    assert world.store.writes == writes and wire.requests == []


def test_a_brand_with_nothing_to_search_queues_nothing(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A)  # not ready: no brief, say
    answer = world.press(TENANT_A, brand)
    assert answer.state == manual_search.STATE_NOT_READY and answer.run is None
    assert _manual_runs(world, TENANT_A) == []


# --------------------------------------------------------------------------------------
# tenant isolation
# --------------------------------------------------------------------------------------


def test_two_businesses_search_apart_and_never_count_each_others(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand_a = _brand_ready(world, TENANT_A)
    brand_b = _brand_ready(world, TENANT_B, rivals=0)
    world.press(TENANT_A, brand_a)
    world.drain()
    # A's search is not B's: B sees none, and may search today
    assert world.state(TENANT_B, brand_b).state == manual_search.STATE_IDLE
    assert world.store.manual_run(TENANT_B, brand_a, run_date=WEDNESDAY.date()) is None
    assert _paid(ledger, TENANT_B) == 0
    assert ledger.spent(TENANT_B, usage.SCRAPECREATORS).day == 0
    # A's cap spent does not stop B
    _spend(ledger, TENANT_A, usage.DAILY_CAP)
    assert world.press(TENANT_A, brand_a).state == manual_search.STATE_USED
    pressed_b = world.press(TENANT_B, brand_b)
    assert pressed_b.state == manual_search.STATE_SEARCHING
    assert pressed_b.run is not None and pressed_b.run.tenant_id == TENANT_B
    # B cannot queue a search on A's brand
    with pytest.raises(PermissionError):
        rr.enqueue_run(TENANT_B, brand_a, TRIGGER_MANUAL, store=world.store, clock=world.clock)


# --------------------------------------------------------------------------------------
# review of 2026-11-26: a failed check, a late worker, a gate stop before the cap
# --------------------------------------------------------------------------------------


def test_a_failed_check_the_worker_will_retry_still_reads_as_searching(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand_ready(world, TENANT_A)
    pressed = world.press(TENANT_A, brand)
    assert pressed.run is not None
    claimed = world.store.claim(TENANT_A, pressed.run.id, now=world.now)
    assert claimed is not None and claimed.started_at is not None
    world.store.finish(
        TENANT_A,
        pressed.run.id,
        status="check_failed",
        now=world.now,
        credits=0,
        cost_usd=Decimal("0"),
        brief_hash=None,
        started_at=claimed.started_at,
    )
    assert world.state(TENANT_A, brand).state == manual_search.STATE_SEARCHING
    assert world.press(TENANT_A, brand).state == manual_search.STATE_SEARCHING
    world.now += rr.CHECK_RETRY_AFTER + manual_search.WAIT_LIMIT + timedelta(minutes=1)
    assert world.state(TENANT_A, brand).state == manual_search.STATE_SLOW


def test_a_search_in_line_too_long_stops_reading_as_running(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand_ready(world, TENANT_A)
    world.press(TENANT_A, brand)
    world.now += manual_search.WAIT_LIMIT + timedelta(minutes=1)  # no worker came
    late = world.state(TENANT_A, brand)
    assert late.state == manual_search.STATE_SLOW and late.message == manual_search.SLOW_TEXT
    again = world.press(TENANT_A, brand)
    assert again.state == manual_search.STATE_SLOW
    assert len(_manual_runs(world, TENANT_A)) == 1  # still one search


def test_a_search_the_gate_stopped_before_the_cap_can_be_pressed_again(
    wire: Wire,
    ledger: usage.InMemoryUsageStore,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brand = _brand_ready(world, TENANT_A)
    monkeypatch.setenv(sc.PAID_SWITCH_ENV, "0")  # the paid reads are paused
    pressed = world.press(TENANT_A, brand)
    (stopped,) = world.drain()
    assert stopped.status == STATUS_BUDGET_STOPPED and wire.requests == []
    stopped_state = world.state(TENANT_A, brand)
    assert stopped_state.state == manual_search.STATE_STOPPED
    assert stopped_state.message == manual_search.STOPPED_TEXT
    monkeypatch.delenv(sc.PAID_SWITCH_ENV)  # back on: the day's search did not happen
    again = world.press(TENANT_A, brand)
    assert again.state == manual_search.STATE_SEARCHING
    assert pressed.run is not None and again.run is not None and again.run.id == pressed.run.id
    (outcome,) = world.drain()
    assert outcome.status == STATUS_OK
    assert world.press(TENANT_A, brand).state == manual_search.STATE_USED
