"""R5 (ADR 42, m-24854849) through the `reels-worker` (R8, m-24854855): every paid read of
a run the worker starts — the Monday run, option A's first run, a failed check retried 15
min later — is booked by the REAL gate (`scrapecreators.metered_get`) to the business and
brand the run is for; a business at its daily cap gets its run `budget_stopped` and the
next request never leaves.

Offline: the vendor's wire is a counting fake (`sc._vendor_request`, as in
`test_vendor_usage_caps.py`), the usage ledger is R5's `InMemoryUsageStore`, Claude is
scripted. The runs are R4's real `reel_runs.run` — the function `production_run` calls —
with a list read and a transcript that pay through the gate on the run's own client.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.claude_tools import CallStats
from qualify_api.referentes import (
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
    reels_ai,
)
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reel_runs as rr
from qualify_api.referentes.reel_queue import MemoryReelQueue
from qualify_api.referentes.reel_store import (
    STATUS_BUDGET_STOPPED,
    STATUS_CHECK_FAILED,
    STATUS_OK,
    TRIGGER_WEEKLY,
    MemoryReelRunStore,
)
from qualify_api.referentes.reel_worker import ReelsWorker
from qualify_api.referentes.reels_ai import ReelReview, ReelToReview
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

BOGOTA = "America/Bogota"
#: Monday 2026-11-09 06:00 in Bogotá (UTC-5): the weekly window opens.
SIX_AM = datetime(2026, 11, 9, 11, 0, tzinfo=UTC)
TENANT_A = UUID("a0000000-0000-4000-8000-0000000000a1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000000b2")
BRIEF = review_ai.BrandBrief(handle="burgerco", rubro=("hamburguesería",))


def _reel(network: str, handle: str, reel_id: str, days_ago: float, caption: str) -> dict:
    return {
        "id": reel_id,
        "network": network,
        "handle": handle,
        "url": f"https://www.instagram.com/reel/{reel_id}/",
        "caption": caption,
        "cover": "",
        "takenAt": SIX_AM.timestamp() - days_ago * 86_400,
        "views": 9_000,
        "likes": 900,
        "comments": 1,
        "shares": None,
        "saves": None,
        "seconds": 12,
        "sound": "Audio original",
        "video": f"https://scontent.cdninstagram.com/{reel_id}.mp4",
    }


FEEDS: dict[str, list[dict[str, Any]]] = {
    "foodie": [_reel("instagram", "foodie", "F1", 2, "la smash burger del centro")],
    "vecino": [_reel("instagram", "vecino", "V1", 1, "papas y burger")],
}


class Wire:
    """The vendor's side of `sc._vendor_request`: answers 200, records each request."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, client: httpx.Client, path: str, params: dict[str, str]) -> httpx.Response:
        with self._lock:
            self.requests.append(path)
        body = {"success": True, "credits_remaining": 5000, "credits_charged": 1}
        return httpx.Response(
            200, json=body, request=httpx.Request("GET", f"https://api.scrapecreators.com{path}")
        )


def _paying_fetch(
    network: str, handle: str, *, since: float, client: httpx.Client, max_pages: int
) -> list[dict[str, Any]]:
    """A list read that pays through the real gate, on the run's own (bound) client."""
    sc.metered_get(client, f"/v1/{network}/reels", {"handle": handle}, feature="reels_list")
    return [dict(r) for r in FEEDS[handle]]


def _paying_transcript(reel: dict[str, Any], client: httpx.Client) -> str:
    sc.metered_get(client, "/v1/instagram/media/transcript", {}, feature="reels_transcript")
    return f"dicen {reel['caption']}"


@dataclass
class Claude:
    asked: list[int] = field(default_factory=list)

    def review(self, brief: Any, batch: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
        self.asked.append(len(batch))
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


def _brand(repo: MemoryReferentesRepository, tenant: UUID, handles: tuple[str, ...]) -> UUID:
    """A brand of `tenant` whose referentes are `handles` (Instagram)."""
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
            accounts=tuple(
                NewDiscoveredAccount(network="instagram", handle=h, card={"kind": "creador"})
                for h in handles
            ),
        )
    )
    for handle in handles:
        repo.set_label(
            tenant_id=tenant,
            brand_id=brand,
            network="instagram",
            handle=handle,
            label="referente",
            labeled_by=None,
        )
    return brand


@dataclass
class World:
    store: MemoryReelRunStore = field(default_factory=MemoryReelRunStore)
    repo: MemoryReferentesRepository = field(default_factory=MemoryReferentesRepository)
    claude: Claude = field(default_factory=Claude)
    now: datetime = SIX_AM
    #: The Anthropic key the run finds (None: its check fails before any paid call).
    key: str | None = "k"

    def clock(self) -> datetime:
        return self.now

    def run(self, tenant_id: UUID, run_id: UUID) -> rr.RunOutcome:
        """What `reel_worker.production_run` does, with the vendor's wire and Claude
        faked: R4's `run`, which binds the business's charge on its own client."""
        return rr.run(
            tenant_id,
            run_id,
            store=self.store,
            repository=self.repo,
            brief=lambda tenant, brand: BRIEF,
            api_key=self.key,
            fetch=_paying_fetch,
            transcribe_fetch=_paying_transcript,
            review=self.claude.review,
            clock=lambda: self.now.timestamp(),
            sleep=lambda seconds: None,
        )

    def worker(self, **kwargs: Any) -> ReelsWorker:
        kwargs.setdefault("ready", lambda tenant, brand: True)
        return ReelsWorker(
            MemoryReelQueue(self.store), self.store, run=self.run, clock=self.clock, **kwargs
        )


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_r8_r5")
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
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


def _booked(ledger: usage.InMemoryUsageStore, tenant: UUID) -> list[tuple[UUID | None, str]]:
    """(brand, feature) of each credit the run booked for `tenant` (not the seeds)."""
    return [
        (e.brand_id, e.feature) for e in ledger.of(tenant) if not e.request_key.startswith("seed:")
    ]


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


def _opened(world: World, tenant: UUID, brand: UUID) -> None:
    """The owner opened the screen three days before Monday 06:00 (the 14-day rule)."""
    world.store.activity[brand] = (tenant, SIX_AM - timedelta(days=3))


# --------------------------------------------------------------------------------------
# who pays: the business and the brand the run is for
# --------------------------------------------------------------------------------------


def test_the_monday_run_books_every_paid_read_to_its_own_business_and_brand(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand_a = _brand(world.repo, TENANT_A, ("foodie",))
    brand_b = _brand(world.repo, TENANT_B, ("vecino",))
    _opened(world, TENANT_A, brand_a)
    _opened(world, TENANT_B, brand_b)

    report = world.worker(batch=2).pass_once()

    assert {(d.tenant_id, d.brand_id) for d in report.enqueued} == {
        (TENANT_A, brand_a),
        (TENANT_B, brand_b),
    }
    assert [o.status for o in report.outcomes] == [STATUS_OK, STATUS_OK]
    # one list read and one Instagram transcript each, booked to the right business
    assert sorted(_booked(ledger, TENANT_A)) == [
        (brand_a, "reels_list"),
        (brand_a, "reels_transcript"),
    ]
    assert sorted(_booked(ledger, TENANT_B)) == [
        (brand_b, "reels_list"),
        (brand_b, "reels_transcript"),
    ]
    assert len(wire.requests) == 4  # every request was booked first, none for nobody


def test_option_as_first_run_is_charged_to_the_brand_that_opened_the_screen(
    wire: Wire,
    ledger: usage.InMemoryUsageStore,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brand = _brand(world.repo, TENANT_A, ("foodie",))
    # Wednesday: the screen opens for the first time (ensure_first_run reads the brief and
    # the accounts through its own loaders: the same repository here)
    world.now = SIX_AM + timedelta(days=2)
    referentes = rr.reels.brand_referentes
    monkeypatch.setattr(rr, "time", SimpleNamespace(time=lambda: world.now.timestamp()))
    monkeypatch.setattr(rr.brief_builder, "brand_brief", lambda tenant, b, **_: BRIEF)
    monkeypatch.setattr(
        rr.reels,
        "brand_referentes",
        lambda tenant, b, repository=None: referentes(tenant, b, repository=world.repo),
    )
    assert rr.ensure_first_run(TENANT_A, brand, store=world.store) is True
    assert wire.requests == []  # the screen queues; it never pays

    report = world.worker().pass_once()

    [outcome] = report.outcomes
    assert outcome.status == STATUS_OK
    assert world.store.runs[outcome.run_id].trigger == TRIGGER_WEEKLY
    assert sorted(_booked(ledger, TENANT_A)) == [
        (brand, "reels_list"),
        (brand, "reels_transcript"),
    ]
    assert _booked(ledger, TENANT_B) == []


def test_a_retried_check_books_its_paid_reads_to_the_same_business_and_brand(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    """The first attempt finds no Anthropic key: it fails its check BEFORE any paid call.
    15 min later the worker retries it by itself; with the key back, that retry is what
    pays — and it pays as the brand's business."""
    brand = _brand(world.repo, TENANT_A, ("foodie",))
    queued = rr.enqueue_run(
        TENANT_A, brand, "manual", store=world.store, clock=lambda: SIX_AM.timestamp()
    )
    world.key = None
    worker = world.worker()
    first = worker.pass_once()
    assert [o.status for o in first.outcomes] == [STATUS_CHECK_FAILED]
    assert wire.requests == [] and _booked(ledger, TENANT_A) == []

    world.key = "k"
    world.now = SIX_AM + rr.CHECK_RETRY_AFTER
    retried = worker.pass_once()

    assert [r.run_id for r in retried.retried] == [queued.id]
    assert [o.status for o in retried.outcomes] == [STATUS_OK]
    assert world.store.runs[queued.id].attempts == 2
    assert sorted(_booked(ledger, TENANT_A)) == [
        (brand, "reels_list"),
        (brand, "reels_transcript"),
    ]


# --------------------------------------------------------------------------------------
# the cap: budget_stopped, and the next request never leaves
# --------------------------------------------------------------------------------------


def test_a_business_at_its_daily_cap_gets_its_monday_run_budget_stopped(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    brand = _brand(world.repo, TENANT_A, ("foodie", "vecino"))
    _opened(world, TENANT_A, brand)
    _spend(ledger, TENANT_A, usage.DAILY_CAP - 1)  # 149: one more credit fits

    report = world.worker().pass_once()

    [outcome] = report.outcomes
    assert outcome.status == STATUS_BUDGET_STOPPED
    assert outcome.stopped == usage.REASON_DAILY_CAP
    assert world.store.runs[outcome.run_id].status == STATUS_BUDGET_STOPPED
    assert wire.requests == ["/v1/instagram/reels"]  # the second account was never read
    assert _booked(ledger, TENANT_A) == [(brand, "reels_list")]
    assert world.claude.asked == []  # nothing was checked either


def test_another_business_is_not_stopped_by_one_at_its_cap(
    wire: Wire, ledger: usage.InMemoryUsageStore, world: World
) -> None:
    capped = _brand(world.repo, TENANT_A, ("foodie",))
    free = _brand(world.repo, TENANT_B, ("vecino",))
    _opened(world, TENANT_A, capped)
    _opened(world, TENANT_B, free)
    _spend(ledger, TENANT_A, usage.DAILY_CAP)

    report = world.worker(batch=2).pass_once()

    by_tenant = {world.store.runs[o.run_id].tenant_id: o for o in report.outcomes}
    assert by_tenant[TENANT_A].status == STATUS_BUDGET_STOPPED
    assert by_tenant[TENANT_B].status == STATUS_OK
    assert _booked(ledger, TENANT_A) == []
    assert sorted(_booked(ledger, TENANT_B)) == [
        (free, "reels_list"),
        (free, "reels_transcript"),
    ]


# --------------------------------------------------------------------------------------
# what R5 books per answer (observed, not changed here)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("charged", "booked"), [(3, [1, 2]), (1, [1]), (0, [1])])
def test_a_run_books_one_credit_before_each_call_and_the_vendors_extra_after(
    wire: Wire,
    ledger: usage.InMemoryUsageStore,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    charged: int,
    booked: list[int],
) -> None:
    """R5's policy, seen from a worker's run: 1 credit is booked (capped) before every
    request; when the answer says `credits_charged` > 1 the rest is booked after
    (uncapped); an answer that cost 0 (the vendor's cache) still keeps its 1."""
    brand = _brand(world.repo, TENANT_A, ("foodie",))
    _opened(world, TENANT_A, brand)
    body = {"success": True, "credits_remaining": 5000, "credits_charged": charged}

    def answer(client: httpx.Client, path: str, params: dict[str, str]) -> httpx.Response:
        wire.requests.append(path)
        return httpx.Response(
            200, json=body, request=httpx.Request("GET", f"https://api.scrapecreators.com{path}")
        )

    monkeypatch.setattr(sc, "_vendor_request", answer)
    world.worker().pass_once()
    lists = [
        e.credits
        for e in ledger.of(TENANT_A)
        if e.feature == "reels_list" and not e.request_key.startswith("seed:")
    ]
    assert lists == booked
