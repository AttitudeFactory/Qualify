"""RF-05 (m-25119465): the competitors' reels — the Monday run reads the 6 `competencia`
accounts the owner picked (the first 6 of the list when none), «Ver sus reels ahora» reads
any other one at once, inside the daily cap, and every credit and dollar is booked apart
from the referentes'.

Offline: the vendor's wire is a counting fake behind the REAL gate
(`scrapecreators.metered_get`, `sc._vendor_request` patched as in
`test_reels_worker_r5_charges.py`), the usage ledger is `InMemoryUsageStore`, Claude is
scripted. The runs are R4's real `reel_runs.run`.
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
    competitors,
    reels,
    reels_ai,
)
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_queue import MemoryReelQueue
from qualify_api.referentes.reel_store import (
    STATUS_OK,
    STATUS_QUEUED,
    TRIGGER_COMPETITOR_NOW,
    TRIGGER_WEEKLY,
    MemoryReelRunStore,
)
from qualify_api.referentes.reels_ai import ReelReview, ReelToReview
from qualify_api.referentes.reviewed_reels import (
    KIND_COMPETENCIA,
    MemoryReviewedReelsStore,
    ReelFilters,
    reviewed_reels,
)
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

BOGOTA = "America/Bogota"
#: Monday 2026-11-09 06:00 in Bogotá (UTC-5).
MONDAY = datetime(2026, 11, 9, 11, 0, tzinfo=UTC)
TENANT_A = UUID("a0000000-0000-4000-8000-0000000000a1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000000b2")
BRIEF = review_ai.BrandBrief(handle="burgerco", rubro=("hamburguesería",))


def _reel(handle: str, reel_id: str, views: int, caption: str = "burger del día") -> dict:
    return {
        "id": reel_id,
        "network": "instagram",
        "handle": handle,
        "url": f"https://www.instagram.com/reel/{reel_id}/",
        "caption": caption,
        "cover": "",
        "takenAt": MONDAY.timestamp() - 2 * 86_400,
        "views": views,
        "likes": views // 10,
        "comments": 1,
        "shares": None,
        "saves": None,
        "seconds": 20,
        "sound": "Audio original",
        "video": f"https://scontent.cdninstagram.com/{reel_id}.mp4",
    }


#: Referentes: @foodie. Competitors: @rival0 … @rival7 (in this order). Detractor: @feo.
FEEDS: dict[str, list[dict[str, Any]]] = {
    "foodie": [_reel("foodie", "F1", 9_000)],
    "feo": [_reel("feo", "X1", 50_000)],
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
    """List reads and transcripts that pay through the real gate, on the run's client."""

    lists: list[str] = field(default_factory=list)
    transcripts: list[str] = field(default_factory=list)

    def fetch(
        self, network: str, handle: str, *, since: float, client: httpx.Client, max_pages: int
    ) -> list[dict[str, Any]]:
        sc.metered_get(client, f"/v1/{network}/reels", {"handle": handle}, feature="reels_list")
        self.lists.append(handle)
        return [dict(r) for r in FEEDS[handle]]

    def transcribe(self, reel: dict[str, Any], client: httpx.Client) -> str:
        sc.metered_get(client, "/v1/instagram/media/transcript", {}, feature="reels_transcript")
        self.transcripts.append(reel["id"])
        return f"dicen {reel['caption']}"


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
    """@foodie is a referente, @feo a detractor, @rival0..@rival{n-1} competitors in that
    order (`position`)."""
    brand = uuid4()
    repo.add_brand(tenant_id=tenant, brand_id=brand)
    handles = ["foodie", "feo", *(f"rival{i}" for i in range(rivals))]
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
    repo.set_label(
        tenant_id=tenant, brand_id=brand, network="instagram", handle="feo", label="detractor"
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
    now: datetime = MONDAY

    def clock(self) -> float:
        return self.now.timestamp()

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

    def weekly(self, tenant: UUID, brand: UUID) -> rr.RunOutcome:
        queued = rr.enqueue_run(tenant, brand, TRIGGER_WEEKLY, store=self.store, clock=self.clock)
        return self.run(tenant, queued.id)

    def read_now(self, tenant: UUID, brand: UUID, handle: str) -> competitors.ReadNow:
        return competitors.read_now(
            tenant,
            brand,
            "instagram",
            handle,
            store=self.store,
            repository=self.repo,
            clock=self.clock,
        )

    def drain(self) -> list[rr.RunOutcome]:
        """What the reels-worker does: run the queued runs, `competitor_now` first."""
        queue, out = MemoryReelQueue(self.store), []
        while (nxt := queue.next_run()) is not None:
            out.append(self.run(nxt.tenant_id, nxt.run_id))
        return out


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_rf05")
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


def _features(ledger: usage.InMemoryUsageStore, tenant: UUID) -> list[str]:
    return [e.feature for e in ledger.of(tenant) if not e.request_key.startswith("seed:")]


def _spend(ledger: usage.InMemoryUsageStore, tenant: UUID, credits: int) -> None:
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
            created_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )


# --------------------------------------------------------------------------------------
# which competitors the Monday run reads
# --------------------------------------------------------------------------------------


def test_without_a_choice_the_monday_run_reads_the_first_six_and_no_more(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    outcome = world.weekly(TENANT_A, brand)
    assert outcome.status == STATUS_OK
    assert world.vendor.lists == ["foodie", *(f"rival{i}" for i in range(6))]
    assert "rival6" not in world.vendor.lists and "rival7" not in world.vendor.lists
    # decision 3: a detractor is never read
    assert "feo" not in world.vendor.lists
    assert outcome.competitors_read == 6


def test_the_owners_choice_replaces_the_first_six(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    shown = competitors.choose_weekly(
        TENANT_A,
        brand,
        [("instagram", "@Rival7"), ("instagram", "rival2")],
        repository=world.repo,
    )
    assert [a.handle for a in shown if a.weekly] == ["rival2", "rival7"]
    world.weekly(TENANT_A, brand)
    assert world.vendor.lists == ["foodie", "rival2", "rival7"]


def test_more_than_six_or_a_non_competitor_is_refused(world: World) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    with pytest.raises(competitors.TooManyPicks):
        competitors.choose_weekly(
            TENANT_A,
            brand,
            [("instagram", f"rival{i}") for i in range(7)],
            repository=world.repo,
        )
    for handle in ("foodie", "feo"):  # a referente, a detractor
        with pytest.raises(ValueError):
            competitors.choose_weekly(
                TENANT_A, brand, [("instagram", handle)], repository=world.repo
            )
    assert competitors.TOO_MANY_TEXT == "Puedes elegir hasta 6 competidores."


def test_relabelling_a_picked_competitor_drops_the_pick(world: World) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    competitors.choose_weekly(TENANT_A, brand, [("instagram", "rival7")], repository=world.repo)
    world.repo.set_label(
        tenant_id=TENANT_A, brand_id=brand, network="instagram", handle="rival7", label="referente"
    )
    world.repo.set_label(
        tenant_id=TENANT_A,
        brand_id=brand,
        network="instagram",
        handle="rival7",
        label="competencia",
    )
    accounts = reels.competitor_accounts(TENANT_A, brand, repository=world.repo)
    assert not any(a.picked for a in accounts)
    # back to the default: the first six
    assert [a.handle for a in accounts if a.weekly] == [f"rival{i}" for i in range(6)]


# --------------------------------------------------------------------------------------
# the spend, apart
# --------------------------------------------------------------------------------------


def test_every_competitor_credit_is_booked_and_counted_apart(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=2)
    outcome = world.weekly(TENANT_A, brand)
    features = _features(ledger, TENANT_A)
    # @foodie: its list + its transcript; each competitor: its list + its transcript
    assert features.count(sc.FEATURE_REELS_LIST) == 1
    assert features.count(sc.FEATURE_REELS_TRANSCRIPT) == 1
    assert features.count(sc.FEATURE_COMPETITOR_REELS_LIST) == 2
    assert features.count(sc.FEATURE_COMPETITOR_REELS_TRANSCRIPT) == 2
    record = world.store.get_run(TENANT_A, outcome.run_id)
    assert record is not None
    assert record.credits == 6 and record.competitor_credits == 4
    # Claude's verdicts of the competitors' reels are their own part of the cost
    assert Decimal("0") < record.competitor_cost_usd < record.cost_usd
    # the ideas stay the referentes' (R11): only @foodie's reel
    view = rr.view(TENANT_A, brand, store=world.store)
    assert [i.reel.handle for i in view.ideas] == ["foodie"]


def test_the_gate_turns_only_reels_features_into_competitor_ones() -> None:
    rival = usage.UsageCharge(TENANT_A, None, account_label=usage.LABEL_COMPETITOR)
    plain = usage.UsageCharge(TENANT_A)
    assert sc.labelled_feature("reels_list", rival) == "competitor_reels_list"
    assert sc.labelled_feature("reels_transcript", rival) == "competitor_reels_transcript"
    assert sc.labelled_feature("profile", rival) == "profile"
    assert sc.labelled_feature("reels_list", plain) == "reels_list"
    assert sc.labelled_feature("reels_list", None) == "reels_list"
    assert {"competitor_reels_list", "competitor_reels_transcript"} <= sc.FEATURES


def test_a_second_run_does_not_pay_again_for_what_was_read(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=2)
    world.weekly(TENANT_A, brand)
    paid = len(wire.requests)
    asked = len(world.claude.asked)
    retry = rr.enqueue_run(TENANT_A, brand, "manual", store=world.store, clock=world.clock)
    again = world.run(TENANT_A, retry.id)
    assert again.status == STATUS_OK
    assert len(wire.requests) == paid  # no list, no transcript paid twice
    assert len(world.claude.asked) == asked  # every verdict reused


# --------------------------------------------------------------------------------------
# «Ver sus reels ahora»
# --------------------------------------------------------------------------------------


def test_read_now_queues_one_read_of_that_account_and_the_worker_reads_it(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    first = world.read_now(TENANT_A, brand, "rival7")
    assert first.state == competitors.STATE_READING
    assert first.message == competitors.READING_TEXT
    assert first.run is not None and first.run.status == STATUS_QUEUED
    assert first.run.trigger == TRIGGER_COMPETITOR_NOW
    assert (first.run.account_network, first.run.account_handle) == ("instagram", "rival7")
    # a double press is the same read
    assert world.read_now(TENANT_A, brand, "@Rival7").run.id == first.run.id

    (outcome,) = world.drain()
    assert outcome.status == STATUS_OK
    assert world.vendor.lists == ["rival7"]
    assert world.vendor.transcripts == ["R7"]
    assert _features(ledger, TENANT_A) == [
        sc.FEATURE_COMPETITOR_REELS_LIST,
        sc.FEATURE_COMPETITOR_REELS_TRANSCRIPT,
    ]
    record = world.store.get_run(TENANT_A, first.run.id)
    assert record is not None
    assert record.credits == record.competitor_credits == 2
    assert record.cost_usd == record.competitor_cost_usd > 0

    done = world.read_now(TENANT_A, brand, "rival7")
    assert done.state == competitors.STATE_DONE and done.message == competitors.DONE_TEXT
    assert world.drain() == []  # nothing queued again the same day
    assert competitors.read_states(TENANT_A, brand, store=world.store, clock=world.clock)[
        ("instagram", "rival7")
    ].state == (competitors.STATE_DONE)


def test_read_now_the_next_day_pays_nothing_already_read(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    world.read_now(TENANT_A, brand, "rival7")
    world.drain()
    paid, asked = len(wire.requests), len(world.claude.asked)
    world.now += timedelta(hours=20)  # Tuesday morning in Bogotá: another local day
    again = world.read_now(TENANT_A, brand, "rival7")
    assert again.state == competitors.STATE_READING
    world.drain()
    assert len(wire.requests) == paid  # page 1 is fresh (< 24 h), the transcript stored
    assert len(world.claude.asked) == asked  # the verdict reused


def test_a_manual_read_never_becomes_the_run_the_screen_shows(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    weekly = world.weekly(TENANT_A, brand)
    world.now += timedelta(hours=1)
    world.read_now(TENANT_A, brand, "rival7")
    world.drain()
    view = rr.view(TENANT_A, brand, store=world.store)
    assert view.latest is not None and view.latest.id == weekly.run_id
    assert view.shown is not None and view.shown.id == weekly.run_id
    assert [i.reel.handle for i in view.ideas] == ["foodie"]


def test_read_now_with_the_daily_cap_spent_reads_nothing_and_says_so(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    _spend(ledger, TENANT_A, usage.DAILY_CAP)
    answer = world.read_now(TENANT_A, brand, "rival7")
    assert answer.state == competitors.STATE_LIMIT
    assert answer.message == (
        "Hoy ya se alcanzó el límite de lecturas de tu negocio. Inténtalo mañana."
    )
    assert answer.run is None
    assert world.store.competitor_runs(TENANT_A, brand, run_date=MONDAY.date()) == []
    assert wire.requests == []


def test_a_read_the_gate_stops_midway_says_the_limit(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    _spend(ledger, TENANT_A, usage.DAILY_CAP - 1)
    assert world.read_now(TENANT_A, brand, "rival7").state == competitors.STATE_READING
    _spend(ledger, TENANT_A, 1)  # another read of the business spends the last credit
    (outcome,) = world.drain()
    assert outcome.status == "budget_stopped"
    assert wire.requests == []  # the gate held the cap: nothing left
    state = competitors.read_states(TENANT_A, brand, store=world.store, clock=world.clock)
    assert state[("instagram", "rival7")].state == competitors.STATE_LIMIT
    assert state[("instagram", "rival7")].message == competitors.DAILY_LIMIT_TEXT


def test_a_read_the_gate_stopped_for_another_reason_can_be_pressed_again(
    wire: Wire,
    ledger: usage.InMemoryUsageStore,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    monkeypatch.setenv(sc.PAID_SWITCH_ENV, "0")  # the paid reads are paused
    world.read_now(TENANT_A, brand, "rival7")
    (stopped,) = world.drain()
    assert stopped.status == "budget_stopped"
    state = competitors.read_states(TENANT_A, brand, store=world.store, clock=world.clock)
    assert state[("instagram", "rival7")].state == competitors.STATE_FAILED
    monkeypatch.delenv(sc.PAID_SWITCH_ENV)  # back on: pressing again reads it
    again = world.read_now(TENANT_A, brand, "rival7")
    assert again.state == competitors.STATE_READING
    assert again.run is not None and again.run.id == stopped.run_id
    (outcome,) = world.drain()
    assert outcome.status == STATUS_OK and world.vendor.lists == ["rival7"]


def test_the_referentes_transcripts_are_paid_before_any_competitor_is_read(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=6)
    # room for @foodie's list and transcript only
    _spend(ledger, TENANT_A, usage.DAILY_CAP - 2)
    outcome = world.weekly(TENANT_A, brand)
    assert outcome.status == STATUS_OK
    assert world.vendor.transcripts == ["F1"]  # the referente's, not lost to a competitor
    assert world.vendor.lists == ["foodie"]  # the competitors were stopped by the cap
    assert [i.reel.handle for i in rr.view(TENANT_A, brand, store=world.store).ideas] == ["foodie"]


def test_read_now_with_the_monthly_cap_spent_names_the_renewal(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    ledger.events.append(
        usage.UsageEvent(
            tenant_id=TENANT_A,
            brand_id=None,
            vendor=usage.SCRAPECREATORS,
            feature=sc.FEATURE_REELS_LIST,
            credits=usage.MONTHLY_CAP,
            usd_estimate=Decimal("0"),
            pricing_table_version=usage.PRICING_TABLE_VERSION,
            request_key=f"seed:{uuid4()}",
            # earlier this month, not today: only the month is spent
            created_at=datetime(2026, 11, 2, 15, tzinfo=UTC),
        )
    )
    answer = world.read_now(TENANT_A, brand, "rival7")
    assert answer.state == competitors.STATE_LIMIT
    assert answer.message == (
        "Este mes ya se alcanzó el límite de lecturas de tu negocio. "
        "Podrás intentarlo de nuevo desde el 1 de diciembre."
    )
    assert answer.run is None


def test_read_now_only_reads_the_brands_competitors(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=2)
    for handle in ("foodie", "feo", "desconocido"):
        answer = world.read_now(TENANT_A, brand, handle)
        assert answer.state == competitors.STATE_NOT_COMPETITOR
    assert world.drain() == []
    assert wire.requests == []


def test_the_owners_words() -> None:
    assert competitors.WEEKLY_PICKER_TITLE == "Elige cuáles 6 competidores leemos cada lunes"
    assert competitors.READ_NOW_BUTTON == "Ver sus reels ahora"
    assert competitors.DAILY_LIMIT_TEXT == (
        "Hoy ya se alcanzó el límite de lecturas de tu negocio. Inténtalo mañana."
    )


# --------------------------------------------------------------------------------------
# the «Competidores» filter is no longer empty — and two businesses never mix
# --------------------------------------------------------------------------------------


def test_the_competitors_filter_shows_their_reels_after_the_monday_run(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=2)
    library = MemoryReviewedReelsStore(world.store, world.repo)
    filters = ReelFilters.of(kinds=[KIND_COMPETENCIA])
    before = reviewed_reels(TENANT_A, brand, filters=filters, store=world.store, library=library)
    assert before.more == []
    world.weekly(TENANT_A, brand)
    after = reviewed_reels(TENANT_A, brand, filters=filters, store=world.store, library=library)
    assert sorted(r.reel.handle for r in after.more) == ["rival0", "rival1"]
    assert all(r.account_kind == KIND_COMPETENCIA for r in after.more)
    assert after.ideas == []  # the ideas are the referentes', filtered out here


def test_a_manual_read_shows_at_once_even_without_a_monday_run(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, rivals=8)
    world.read_now(TENANT_A, brand, "rival7")
    world.drain()
    library = MemoryReviewedReelsStore(world.store, world.repo)
    seen = reviewed_reels(
        TENANT_A,
        brand,
        filters=ReelFilters.of(kinds=[KIND_COMPETENCIA]),
        store=world.store,
        library=library,
        now=world.now,
    )
    assert seen.view.shown is None  # no weekly run yet
    assert [r.reel.handle for r in seen.more] == ["rival7"]


def test_two_businesses_never_see_nor_count_each_others_competitors(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand_a = _brand(world.repo, TENANT_A, rivals=2)
    brand_b = _brand(world.repo, TENANT_B, rivals=0)
    world.weekly(TENANT_A, brand_a)
    world.read_now(TENANT_A, brand_a, "rival1")
    world.drain()
    # B follows none of A's competitors: it cannot ask for their reads...
    assert world.read_now(TENANT_B, brand_b, "rival1").state == competitors.STATE_NOT_COMPETITOR
    # ...nor sees A's reads, runs or reviewed reels...
    assert competitors.read_states(TENANT_B, brand_b, store=world.store, clock=world.clock) == {}
    assert world.store.competitor_runs(TENANT_B, brand_a, run_date=MONDAY.date()) == []
    library = MemoryReviewedReelsStore(world.store, world.repo)
    seen_b = reviewed_reels(TENANT_B, brand_b, store=world.store, library=library)
    assert seen_b.more == [] and seen_b.accounts.get(("instagram", "rival1")) is None
    # ...and none of A's credits counts against B's cap
    assert _features(ledger, TENANT_B) == []
    assert ledger.spent(TENANT_B, usage.SCRAPECREATORS).day == 0
    # a pick of A's is not B's
    with pytest.raises(ValueError):
        competitors.choose_weekly(
            TENANT_B, brand_b, [("instagram", "rival1")], repository=world.repo
        )
