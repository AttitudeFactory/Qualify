"""«Ideas para tus reels» («Descubrir reels» in the code) — the Reflex app's side, without
the network.

ADR 42 R7 (m-24854854): opening the screen only reads what the persistent run stored; it
never reads ScrapeCreators nor asks the model. These pin that — an empty database shows
the empty state with ZERO paid calls and no write but the «last opened» mark, a stored
`ok` run shows with its date, a brand without a run gets its first one queued and the
screen waits for it, reading again for free until the owner leaves — plus what only the
app knows: the brand brief built from the search seed, the Brand Kit and the catalog, and
the signed cover route. The pipeline's own tests live with it
(`packages/api/tests/test_referentes_reel_runs.py`); the screen's words and dates in
`test_reels_ideas_vm.py`."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from qualify_api.referentes import (
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
    reel_runs,
    reels,
    reels_ai,
)
from qualify_api.referentes.reel_store import (
    STATUS_CHECK_FAILED,
    STATUS_OK,
    STATUS_QUEUED,
    TRIGGER_MANUAL,
    TRIGGER_WEEKLY,
    MemoryReelRunStore,
    NewIdea,
    NewVerdict,
    PublicReel,
)

from . import reels_discovery as rd

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
NOW = 1_800_000_000.0
DAY = 24 * 3600


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test-key")


@pytest.fixture
def store() -> tuple[MemoryReferentesRepository, UUID]:
    repo = MemoryReferentesRepository()
    brand = uuid4()
    repo.add_brand(tenant_id=TENANT, brand_id=brand)
    accounts = (
        NewDiscoveredAccount(
            network="instagram",
            handle="foodie",
            card={"handle": "@foodie", "network": "Instagram", "kind": "creador"},
        ),
        NewDiscoveredAccount(
            network="tiktok",
            handle="rival",
            card={"handle": "@rival", "network": "TikTok", "kind": "marca"},
        ),
    )
    repo.save_phase(
        NewDiscoveryPhase(
            tenant_id=TENANT,
            brand_id=brand,
            phase_key="sector",
            algorithm_version=1,
            seed_signature="s",
            seed={"handle": "burgerco", "terms": ["hamburguesería"], "hashtags": []},
            title="Sector",
            accounts=accounts,
        )
    )
    manual = (
        NewDiscoveredAccount(
            network="instagram",
            handle="makeupqueen",
            card={"handle": "@makeupqueen", "network": "Instagram", "manual": "1", "fits": "no"},
        ),
        NewDiscoveredAccount(
            network="tiktok",
            handle="vecino",
            card={"handle": "@vecino", "network": "TikTok", "manual": "1", "fits": "si"},
        ),
        NewDiscoveredAccount(
            network="otro", handle="sinredes", card={"handle": "@sinredes", "manual": "1"}
        ),
    )
    repo.save_phase(
        NewDiscoveryPhase(
            tenant_id=TENANT,
            brand_id=brand,
            phase_key="manual",
            algorithm_version=1,
            seed_signature="manual",
            seed={"handle": "burgerco", "hashtags": []},
            title="Agregados a mano",
            accounts=manual,
            source="operator",
        )
    )
    for network, handle, label in (
        ("instagram", "foodie", "referente"),
        ("tiktok", "rival", "competencia"),
        ("instagram", "makeupqueen", "referente"),
        ("tiktok", "vecino", "referente"),
        ("otro", "sinredes", "referente"),
    ):
        repo.set_label(
            tenant_id=TENANT,
            brand_id=brand,
            network=network,
            handle=handle,
            label=label,
            labeled_by=None,
        )
    return repo, brand


@pytest.fixture(autouse=True)
def _no_kit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Brand Kit's and the catalog's doors go to Postgres; here they answer empty
    unless a test says otherwise."""
    monkeypatch.setattr(rd, "_kit_form", lambda tenant, brand: None)
    monkeypatch.setattr(rd, "_products", lambda tenant, brand: ())


def test_the_brief_is_rebuilt_from_the_search_seed(store: Any) -> None:
    repo, brand = store
    brief = rd.brand_brief(TENANT, brand, repository=repo)
    assert brief is not None and brief.rubro == ("hamburguesería",)
    assert brief.products == () and brief.publishes == ()  # no kit, no catalog: thinner


def test_the_brief_carries_the_brand_kit_and_the_catalog(store: Any) -> None:
    """§ request 2026-10-15: the Brand Kit (positioning, audience, what it publishes),
    the catalog's products and EVERY hashtag reach the rubro check."""
    from types import SimpleNamespace

    repo, brand = store
    kit = SimpleNamespace(
        positioning="Smash burgers callejeras",
        audience="Jóvenes de 18 a 35",
        do_examples="¡Pilla esta costra!\n\nMano, llégate hoy.",
    )
    products = [{"name": "smash doble"}, {"name": " super smash "}, {"name": ""}]
    brief = rd.brand_brief(
        TENANT,
        brand,
        repository=repo,
        kit_form=lambda tenant, b: kit,
        products=lambda tenant, b: products,
    )
    assert brief is not None
    assert (
        brief.positioning == "Smash burgers callejeras" and brief.audience == "Jóvenes de 18 a 35"
    )
    assert brief.publishes == ("¡Pilla esta costra!", "Mano, llégate hoy.")
    assert brief.products == ("smash doble", "super smash")

    # a kit that cannot be read only thins the brief, never breaks the discovery
    def broken(tenant: Any, b: Any) -> Any:
        raise RuntimeError("db down")

    thin = rd.brand_brief(TENANT, brand, repository=repo, kit_form=broken, products=broken)
    assert thin is not None and thin.products == () and thin.positioning == ""


def test_the_brief_keeps_every_hashtag_of_the_seed() -> None:
    from .creator_discovery import DiscoverySeed

    seed = DiscoverySeed(
        handle="x",
        niches=("food_drink",),
        hashtags=("hamburguesas", "burger"),
        chosen_hashtags=("smashburger", "burger"),
        catalog_hashtags=("comidarapida",),
    )
    repo = MemoryReferentesRepository()
    brand = uuid4()
    repo.add_brand(tenant_id=TENANT, brand_id=brand)
    repo.save_phase(
        NewDiscoveryPhase(
            tenant_id=TENANT,
            brand_id=brand,
            phase_key="sector",
            algorithm_version=1,
            seed_signature="s",
            seed={
                "handle": "x",
                "niches": ["food_drink"],
                "hashtags": [
                    {"tag": "hamburguesas", "origin": "profile"},
                    {"tag": "burger", "origin": "profile"},
                    {"tag": "smashburger", "origin": "operator"},
                    {"tag": "comidarapida", "origin": "catalog"},
                ],
            },
            title="Sector",
            accounts=(),
        )
    )
    brief = rd.brand_brief(TENANT, brand, repository=repo)
    assert brief is not None
    assert brief.hashtags == ("hamburguesas", "burger", "smashburger", "comidarapida")
    del seed


def _reel(handle: str, reel_id: str, days_ago: float, views: int, caption: str) -> dict:
    return {
        "id": reel_id,
        "network": "instagram",
        "handle": handle,
        "url": f"https://www.instagram.com/reel/{reel_id}/",
        "caption": caption,
        "cover": f"https://scontent.cdninstagram.com/{reel_id}.jpg",
        "takenAt": NOW - days_ago * DAY,
        "views": views,
        "likes": views // 10,
        "comments": 1,
        "shares": None,
        "seconds": 12,
        "sound": "",
    }


# --------------------------------------------------------------------------------------
# the app's cover route and the card's player
# --------------------------------------------------------------------------------------


async def test_a_live_reel_cover_passes_through_and_is_never_kept() -> None:
    """R12 (m-24854859): the run's R2 copy replaced the disk cache under `avatars/reels/`;
    the signed live path is a pass-through under the cover rules (the network's CDN only,
    no redirects), fetched again on each request and kept nowhere."""
    from .avatar_proxy import resolve_reel_cover

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"jpeg-bytes", headers={"content-type": "image/jpeg"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        url = "https://scontent.cdninstagram.com/A.jpg"
        first = await resolve_reel_cover("instagram", "A", url, client=client)
        again = await resolve_reel_cover("instagram", "A", url, client=client)
        no_url = await resolve_reel_cover("instagram", "Z", "", client=client)
        foreign = await resolve_reel_cover(
            "instagram", "B", "https://evil.example/x.jpg", client=client
        )
        bad_id = await resolve_reel_cover("instagram", "../x", url, client=client)
    assert first == again == (b"jpeg-bytes", "image/jpeg") and len(calls) == 2
    assert no_url is None and foreign is None and bad_id is None


def test_a_reel_plays_in_the_networks_own_player() -> None:
    """§ 2026-10-15: seen inside Qualify without downloading — the official embeds."""
    ig = reels.reel_card(_reel("foodie", "DecE2c8x7c_", 1, 10, "x"), 1, NOW)
    assert ig["embed"] == "https://www.instagram.com/reel/DecE2c8x7c_/embed/"
    tt = reels.reel_card(
        {**_reel("vecino", "7681392167478250765", 1, 10, "x"), "network": "tiktok"}, 1, NOW
    )
    assert tt["embed"].startswith("https://www.tiktok.com/player/v1/7681392167478250765?")


async def test_the_cover_route_serves_only_paths_it_signed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import avatar_proxy as ap

    async def resolved(network: str, reel_id: str, url: str, **_: Any) -> tuple[bytes, str]:
        return b"jpeg", "image/jpeg"

    monkeypatch.setattr(ap, "resolve_reel_cover", resolved)
    path = rd.cover_path(_reel("foodie", "A", 1, 10, "x"))
    assert path.startswith("/avatar/reel/instagram/A?u=https%3A%2F%2F") and "&s=" in path
    forged = path.replace("A.jpg", "B.jpg")  # another image under the same reel
    unsigned = path.split("&s=")[0]
    transport = httpx.ASGITransport(app=ap.avatar_api)
    async with httpx.AsyncClient(transport=transport, base_url="http://qualify") as client:
        assert (await client.get(path)).status_code == 200
        assert (await client.get(forged)).status_code == 404
        assert (await client.get(unsigned)).status_code == 404
        assert (await client.get(unsigned + "&s=%C3%B1")).status_code == 404  # non-ASCII


def test_the_brief_is_built_by_the_service_with_the_apps_doors(store: Any) -> None:
    """ADR 42 R4 (m-24854848): the brief builder moved to `qualify_api.referentes
    .brand_brief` so the worker can build it alone; the app's adapter gives the same brief
    as the service handed the same doors, and both trust the search phases in the same
    order as the referentes search."""
    from qualify_api.referentes import brand_brief as shared

    from . import creator_discovery, referentes_provider, referentes_review

    repo, brand = store
    kit = type("Kit", (), {"positioning": "p", "audience": "a", "do_examples": "uno\ndos"})()
    rows = ({"name": "Smash"},)
    via_app = rd.brand_brief(
        TENANT, brand, repository=repo, kit_form=lambda t, b: kit, products=lambda t, b: rows
    )
    via_service = shared.brand_brief(
        TENANT, brand, repository=repo, kit_form=lambda t, b: kit, products=lambda t, b: rows
    )
    assert via_app == via_service and via_app is not None
    assert via_app.publishes == ("uno", "dos") and via_app.products == ("Smash",)
    assert shared.DISCOVERY_PHASES == creator_discovery.PHASES
    assert referentes_provider.rebuild_seed({"handle": "x", "terms": ["t"]}) == (
        shared.rebuild_seed({"handle": "x", "terms": ["t"]})
    )
    seed = shared.rebuild_seed({"handle": "x", "terms": ["t"], "niches": ["comida"]})
    assert referentes_review.brand_brief(seed) == shared.seed_brief(seed)


# --------------------------------------------------------------------------------------
# the screen reads only what is stored (ADR 42 R7, m-24854854)
# --------------------------------------------------------------------------------------

#: Wednesday 4 November 2026, 10:00 in Bogotá — the screen's clock in these tests.
CLOCK = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)
#: The weekly run of that week: Monday 2 November, 06:05 in Bogotá.
MONDAY = datetime(2026, 11, 2, 11, 5, tzinfo=UTC)


class _FrozenClock(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:  # type: ignore[override]
        return CLOCK if tz is not None else CLOCK.replace(tzinfo=None)


class _Proxy:
    """`async with state` and `get_state` for a background handler run off the app (the
    same harness as `test_reel_replication`)."""

    def __init__(self, state: Any, auth: Any) -> None:
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "auth", auth)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_state(self, cls: Any) -> Any:
        from .auth_state import AuthState

        assert cls is AuthState
        return self.auth

    def __getattr__(self, name: str) -> Any:
        return getattr(self.state, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.state, name, value)


class _World:
    """One business: its reels runs (`MemoryReelRunStore`), its referentes, and every
    door the screen may touch, recorded."""

    def __init__(self, repo: MemoryReferentesRepository, brand: UUID) -> None:
        self.runs = MemoryReelRunStore()
        self.repo = repo
        self.brand = brand
        self.opened: list[tuple[UUID, UUID]] = []
        self.first_runs: list[tuple[UUID, UUID]] = []
        self.reads: list[bool] = []
        self.paid: list[str] = []
        self.analyses: Any = None

    def ok_run(self, *, finished: datetime = MONDAY, ideas: int = 2) -> UUID:
        """What the worker leaves after a weekly run: reels, verdicts, ideas, `ok`."""
        run = self.runs.enqueue(
            TENANT,
            self.brand,
            trigger=TRIGGER_WEEKLY,
            run_date=finished.date(),
            days=30,
            pipeline_version="test",
            now=finished - timedelta(minutes=5),
        )
        claimed = self.runs.claim(TENANT, run.id, now=finished - timedelta(minutes=4))
        assert claimed is not None and claimed.started_at is not None
        stored = [
            PublicReel(
                network="instagram",
                reel_id=f"R{n}",
                handle="foodie",
                taken_at=finished - timedelta(days=n + 2),
                metrics_at=finished - timedelta(hours=1),
                parser_version=1,
                caption="Smash burger doble",
                views=10_000 - n,
                transcript="la mejor smash" if n == 0 else None,
                transcript_at=finished if n == 0 else None,
            )
            for n in range(ideas)
        ]
        self.runs.upsert_reels(TENANT, stored)
        verdicts = self.runs.save_verdicts(
            TENANT,
            self.brand,
            [
                NewVerdict(
                    network="instagram",
                    reel_id=reel.reel_id,
                    brief_hash="b",
                    input_hash=f"i{reel.reel_id}",
                    fits=True,
                    model_id="claude",
                    prompt_version="p",
                    affinity="producto",
                )
                for reel in stored
            ],
        )
        by_reel = {v.reel_id: v for v in verdicts.values()}
        self.runs.save_ideas(
            TENANT,
            self.brand,
            run.id,
            [
                NewIdea("instagram", reel.reel_id, n, 7, by_reel[reel.reel_id].id)
                for n, reel in enumerate(stored, 1)
            ],
            started_at=claimed.started_at,
        )
        self.runs.finish(
            TENANT,
            run.id,
            status=STATUS_OK,
            now=finished,
            credits=0,
            cost_usd=Decimal("0"),
            brief_hash="b",
            started_at=claimed.started_at,
        )
        return run.id


@pytest.fixture
def world(store: Any, monkeypatch: pytest.MonkeyPatch) -> _World:
    """The `store` business (two readable referentes and a search seed: accounts and a
    brief) wired into the screen; every paid door fails the test if touched."""
    from . import discover_reels, referentes_provider

    repo, brand = store
    world = _World(repo, brand)
    monkeypatch.setattr(discover_reels, "default_brand_id", lambda tenant: brand)
    monkeypatch.setattr(referentes_provider, "REPOSITORY", repo)
    monkeypatch.setattr(reel_runs, "default_store", lambda: world.runs)
    monkeypatch.setattr(rd, "_business_timezone", lambda tenant: "America/Bogota")
    # UI-1: the reels' shared analyses (global tables) in memory
    from qualify_api.referentes import reel_analysis
    from qualify_api.referentes.reel_analysis_store import InMemoryAnalysisStore

    world.analyses = InMemoryAnalysisStore()
    monkeypatch.setattr(reel_analysis, "default_store", lambda: world.analyses)
    monkeypatch.setattr(rd, "datetime", _FrozenClock)

    def mark_opened(tenant: UUID, brand: UUID, *, store: Any = None) -> None:
        world.opened.append((tenant, brand))

    def ensure_first_run(tenant: UUID, brand: UUID, *, store: Any = None) -> bool:
        """Like the backend's: this week's weekly run, queued only when there is none."""
        world.first_runs.append((tenant, brand))
        if world.runs.latest_run(tenant, brand) is not None:
            return False
        reel_runs.enqueue_run(
            tenant, brand, TRIGGER_WEEKLY, run_date=MONDAY.date(), store=world.runs
        )
        return True

    # the backend lands both doors in this same PR (decisions of 2026-11-04)
    monkeypatch.setattr(reel_runs, "mark_opened", mark_opened, raising=False)
    monkeypatch.setattr(reel_runs, "ensure_first_run", ensure_first_run, raising=False)

    def paid(name: str) -> Any:
        def call(*_: Any, **__: Any) -> Any:
            world.paid.append(name)
            raise AssertionError(f"opening the screen called {name}")

        return call

    from qualify_api.vendors import scrapecreators

    for name in (
        "metered_get",
        "fetch_reels",
        "fetch_instagram_transcript",
        "fetch_tiktok_captions",
        "fetch_profile",
    ):
        monkeypatch.setattr(scrapecreators, name, paid(f"scrapecreators.{name}"))
    monkeypatch.setattr(reels_ai, "review_reels", paid("reels_ai.review_reels"))
    monkeypatch.setattr(reel_runs, "run", paid("reel_runs.run"))
    monkeypatch.setattr(httpx.Client, "send", paid("httpx.Client.send"))
    monkeypatch.setattr(httpx.AsyncClient, "send", paid("httpx.AsyncClient.send"))

    real = rd.load_ideas

    def load_ideas(tenant: UUID, brand: UUID, **kwargs: Any) -> Any:
        world.reads.append(kwargs.get("first_run", True))
        return real(tenant, brand, **kwargs)

    monkeypatch.setattr(rd, "load_ideas", load_ideas)
    return world


def _screen_state(tenant: str = str(TENANT)) -> tuple[Any, _Proxy]:
    from types import SimpleNamespace

    from .discover_reels import DiscoverReelsState

    state = DiscoverReelsState()
    return state, _Proxy(state, SimpleNamespace(session_tenant_id=tenant))


async def _open(proxy: _Proxy) -> None:
    from .discover_reels import DiscoverReelsState

    await DiscoverReelsState.load.fn(proxy)


async def test_opening_with_an_empty_database_shows_the_empty_state_and_pays_nothing(
    world: _World,
) -> None:
    """The acceptance test of R7: no accounts, no run — the empty state, ZERO calls to
    the vendor or the model, and no write but the «last opened» mark."""
    for label in world.repo.labels(tenant_id=TENANT, brand_id=world.brand):
        world.repo.set_label(
            tenant_id=TENANT,
            brand_id=world.brand,
            network=label.network,
            handle=label.handle,
            label="competencia",
            labeled_by=None,
        )
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.screen == rd.reels_ideas_vm.SCREEN_NO_ACCOUNTS
    assert state.title == "Aún no hay cuentas que te inspiren"
    assert state.action == "Elegir cuentas" and state.reels == []
    assert world.paid == [] and world.runs.writes == 0 and world.first_runs == []
    assert world.opened == [(TENANT, world.brand)]  # the «last opened» mark (R8's rule)


async def test_a_stored_ok_run_shows_at_once_with_its_date(world: _World) -> None:
    world.ok_run()
    writes = world.runs.writes
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.screen == rd.reels_ideas_vm.SCREEN_IDEAS and state.load_error == ""
    assert state.title == "Ideas de esta semana"
    assert state.body == "Listas desde el lunes 2. Las próximas llegan el lunes 9."
    assert [c["key"] for c in state.reels] == ["instagram:R0", "instagram:R1"]
    assert state.reels[0]["transcript"] == "la mejor smash"  # the stored one, not fetched
    assert world.paid == [] and world.runs.writes == writes  # read-only
    assert world.reads == [True] and world.first_runs == []


async def test_each_idea_says_what_its_analysis_saw_in_one_read(world: _World) -> None:
    """UI-1 (design §13.7): «Aparece una persona» when a face was seen, «Aún no lo revisamos»
    without an `ok`; the ideas never disappear for it, and nothing is paid."""
    from qualify_api.referentes.reel_analysis_store import AnalysisRecord
    from qualify_api.referentes.reel_analysis_types import (
        ANALYSIS_VERSION,
        OBSERVED,
        STATUS_OK,
        ShotAnalysis,
    )

    world.ok_run()
    seen = AnalysisRecord(
        id=uuid4(),
        network="instagram",
        post_id="R0",
        analysis_version=ANALYSIS_VERSION,
        status=STATUS_OK,
        post_url="https://www.instagram.com/reel/R0/",
        created_at=MONDAY,
    )
    world.analyses.put(seen, [ShotAnalysis(0, 0, 2, visible_faces=OBSERVED)])
    state, proxy = _screen_state()
    await _open(proxy)
    assert [(c["key"], c["analysis"]) for c in state.reels] == [
        ("instagram:R0", "person"),
        ("instagram:R1", "not_analyzed"),
    ]
    assert world.paid == []


async def test_unreadable_analyses_leave_the_ideas_without_pills(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_api.referentes import reel_analysis

    def down(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database down")

    world.ok_run()
    monkeypatch.setattr(reel_analysis, "analysis_badges", down)
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.screen == rd.reels_ideas_vm.SCREEN_IDEAS and state.load_error == ""
    assert [c["analysis"] for c in state.reels] == ["", ""]


async def _tick(proxy: _Proxy, *, after_a_while: bool = True) -> None:
    """One beat of the «preparando» screen's browser clock (`_ticker`)."""
    from .discover_reels import DiscoverReelsState

    if after_a_while:
        proxy.state._read_at = 0.0  # the last read was a while ago
    await DiscoverReelsState.tick.fn(proxy, "")


async def test_a_brand_without_a_run_gets_its_first_one_and_the_screen_waits_for_it(
    world: _World,
) -> None:
    """Option A (founder, 2026-11-04): opening queues the first run (the worker pays, not
    the screen); the screen says it is being prepared, and its browser clock reads the
    view again — free, never queueing — until the run ends."""
    state, proxy = _screen_state()
    await _open(proxy)
    assert world.first_runs == [(TENANT, world.brand)]  # queued once, by the open
    assert state.screen == rd.reels_ideas_vm.SCREEN_PREPARING and state.waiting
    assert state.body == (
        "Tardan unos minutos. Puedes seguir con otra cosa: quedan guardadas aquí."
    )
    # the worker finishes the run meanwhile
    queued = world.runs.latest_run(TENANT, world.brand)
    assert queued is not None and queued.status == STATUS_QUEUED
    world.runs.runs.pop(queued.id)
    world.ok_run(finished=CLOCK - timedelta(minutes=1))
    await _tick(proxy)
    assert world.reads == [True, False]  # the clock's read never queues
    assert world.first_runs == [(TENANT, world.brand)] and len(world.opened) == 1
    # the first run is this week's weekly run: dated the day it was ready
    assert state.screen == rd.reels_ideas_vm.SCREEN_IDEAS and len(state.reels) == 2
    assert state.title == "Ideas de esta semana"
    assert state.body == "Listas desde el miércoles 4. Las próximas llegan el lunes 9."
    assert not state.waiting and world.paid == []


async def test_the_clock_reads_only_while_the_screen_waits_and_never_after_leaving(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    reel_runs.enqueue_run(TENANT, world.brand, TRIGGER_MANUAL, store=world.runs)  # in flight
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.screen == rd.reels_ideas_vm.SCREEN_PREPARING and world.reads == [True]
    await _tick(proxy, after_a_while=False)  # its first beat comes right after the read
    assert world.reads == [True]
    await _tick(proxy)
    assert world.reads == [True, False] and world.first_runs == []
    # the owner leaves while a read is in flight: it never paints
    real = rd.load_ideas
    world.ok_run(finished=CLOCK - timedelta(minutes=1))

    def leave_meanwhile(tenant: UUID, brand: UUID, **kwargs: Any) -> Any:
        state.leave()
        return real(tenant, brand, **kwargs)

    monkeypatch.setattr(rd, "load_ideas", leave_meanwhile)
    await _tick(proxy)
    assert state.screen == rd.reels_ideas_vm.SCREEN_PREPARING
    # on a screen that does not wait the clock does nothing
    state.screen, state.waiting = rd.reels_ideas_vm.SCREEN_IDEAS, False
    reads = list(world.reads)
    await _tick(proxy)
    assert world.reads == reads


async def test_a_run_in_line_too_long_stops_the_spinner_and_looks_again_on_demand(
    world: _World,
) -> None:
    """UX review 3: past 10 min in line — counted from the run's `queued_at`, so a reload
    or a deploy never restarts it — no spinner; «Ver si ya están» reads once more."""
    world.runs.enqueue(
        TENANT,
        world.brand,
        trigger=TRIGGER_MANUAL,
        run_date=CLOCK.date(),
        days=30,
        pipeline_version="test",
        now=CLOCK - timedelta(minutes=11),
    )
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.screen == rd.reels_ideas_vm.SCREEN_SLOW and not state.waiting
    assert (state.title, state.action) == ("Están tardando más de lo normal", "Ver si ya están")
    await _open(proxy)  # «Ver si ya están» is one more read
    assert world.reads == [True, True] and world.first_runs == []


def _failed_run(world: _World, *, minutes_ago: int, attempts: int) -> None:
    """A run that ended `check_failed` `minutes_ago`, claimed `attempts` times."""
    run = world.runs.enqueue(
        TENANT,
        world.brand,
        trigger=TRIGGER_MANUAL,
        run_date=CLOCK.date(),
        days=30,
        pipeline_version="test",
        now=CLOCK - timedelta(minutes=minutes_ago + 5),
    )
    claimed = None
    for _ in range(attempts):  # each attempt is a claim (the worker puts it back in line)
        world.runs.runs[run.id] = dataclasses.replace(world.runs.runs[run.id], status=STATUS_QUEUED)
        claimed = world.runs.claim(TENANT, run.id, now=CLOCK - timedelta(minutes=minutes_ago + 4))
    assert claimed is not None and claimed.started_at is not None
    assert claimed.attempts == attempts
    world.runs.finish(
        TENANT,
        run.id,
        status=STATUS_CHECK_FAILED,
        now=CLOCK - timedelta(minutes=minutes_ago),
        credits=0,
        cost_usd=Decimal("0"),
        brief_hash="b",
        started_at=claimed.started_at,
    )


async def test_a_failed_check_tried_again_keeps_reading_until_its_ideas_arrive(
    world: _World,
) -> None:
    """UX re-check 1: while the worker will try the failed check again, the screen keeps
    reading from the browser and offers «Ver si ya están»."""
    _failed_run(world, minutes_ago=2, attempts=1)
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.screen == rd.reels_ideas_vm.SCREEN_CHECK_FAILED and state.waiting
    assert (state.action, state.action_to) == ("Ver si ya están", rd.reels_ideas_vm.ACTION_REREAD)
    assert state.body.endswith("Lo intentamos de nuevo en unos minutos.")
    world.ok_run(finished=CLOCK - timedelta(minutes=1))  # the retry found ideas
    await _tick(proxy)
    assert state.screen == rd.reels_ideas_vm.SCREEN_IDEAS and not state.waiting
    assert world.paid == []


async def test_a_failed_check_with_its_retries_spent_offers_to_create(world: _World) -> None:
    _failed_run(world, minutes_ago=30, attempts=reel_runs.MAX_ATTEMPTS)
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.screen == rd.reels_ideas_vm.SCREEN_CHECK_FAILED and not state.waiting
    assert state.body.endswith("Lo intentamos de nuevo el lunes 9.")
    assert (state.action, state.action_to) == (
        "Crear una publicación",
        rd.reels_ideas_vm.ACTION_CREATE,
    )


def test_create_a_publication_goes_back_to_the_create_flow() -> None:
    from .creative_state import CreativeState

    creative = CreativeState()
    creative.gen_mode = "discover"
    fired = CreativeState.open_create_options.fn(creative)
    assert creative.gen_mode == "create" and creative.create_options_open
    assert "create-kind-options" in str(fired)  # on a phone, the options come into view
    creative.gen_mode = "discover"
    creative.is_submitting = True  # a piece is being created (`gen_generating`)
    assert CreativeState.open_create_options.fn(creative) is None
    assert creative.gen_mode == "discover"  # never while a piece is being made


async def test_a_failed_opened_mark_never_costs_the_owner_the_screen(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(reel_runs, "mark_opened", broken, raising=False)
    world.ok_run()
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.screen == rd.reels_ideas_vm.SCREEN_IDEAS and state.load_error == ""


async def test_an_unreadable_database_says_try_again_and_reads_again(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    def down(*_: Any, **__: Any) -> Any:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(rd, "load_ideas", down)
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.load_error == rd.reels_ideas_vm.LOAD_ERROR and state.screen == ""
    assert world.paid == []


async def test_a_read_for_a_tenant_that_logged_out_never_paints(world: _World) -> None:
    world.ok_run()
    state, proxy = _screen_state()
    real_get_state = proxy.get_state

    async def logged_out_meanwhile(cls: Any) -> Any:
        auth = await real_get_state(cls)
        if state._load_id and world.reads:  # after the read: another session now
            auth.session_tenant_id = "c0000000-0000-4000-8000-000000000003"
        return auth

    object.__setattr__(proxy, "get_state", logged_out_meanwhile)
    await _open(proxy)
    assert state.screen == "" and state.reels == []


# --------------------------------------------------------------------------------------
# the view
# --------------------------------------------------------------------------------------


def test_the_view_has_every_state_and_nothing_that_pays() -> None:
    import inspect

    from . import discover_reels
    from .discover_reels import discover_view

    rendered = str(discover_view().render())
    assert "q-dr-grid" in rendered and "Detalles" in rendered
    assert "Hacer uno parecido" in rendered and "Lo que se dice" in rendered
    assert "Replicar" not in rendered and "replicar" not in rendered
    assert "aria-busy" in rendered.replace("ariaBusy", "aria-busy")  # skeletons, not a spinner
    for gone in ("Actualizar", '"Leer"', "Ver transcripci", "Esta semana", "Este mes"):
        assert gone not in rendered, gone  # «Actualizar», 90 días, the paid transcript
    for gone in ("Todos los referentes", "Plataforma", "cargo extra", "fromNow"):
        assert gone not in rendered, gone
    source = inspect.getsource(discover_reels)
    for door in ("cached_discover", "discover(", "transcript_for", "load_quarter", "metered"):
        assert door not in source, door
    # the one clock is the «preparando» screen's: no heartbeat anywhere else
    # the one browser clock, mounted only while the screen waits
    assert source.count("interval=") == 1
    view_source = inspect.getsource(discover_reels.discover_view)
    assert "_ticker()" in view_source and "DiscoverReelsState.waiting" in view_source
    # UX re-check 1: the failures' «Crear una publicación» goes back to the create flow
    assert "open_create_options" in rendered
    # UX review 4: the empty states lead to «Negocios parecidos al tuyo» and back
    assert "/brand/kit?seccion=referentes&volver=%2Fcreate%3Fmodo%3Dideas" in rendered
    # founder, 2026-11-04: a newer failed run over stored ideas is said calmly
    ideas_source = inspect.getsource(discover_reels._ideas)
    assert '"info"' in ideas_source and '"warn"' not in ideas_source


def test_a_reel_plays_inside_its_card_one_at_a_time() -> None:
    """§ 2026-10-15: no dialog — the card swaps its cover for the network's player."""
    from .discover_reels import DiscoverReelsState, discover_view

    state = DiscoverReelsState()
    state.play("instagram:A")
    state.play("tiktok:7")  # starting another stops the first (its iframe unmounts)
    assert state.playing_key == "tiktok:7"
    state.leave()  # leaving the view stops it too
    assert state.playing_key == ""
    rendered = str(discover_view().render())
    assert '"video"' in rendered and "iframe" in rendered and "q-dr-more-panel" in rendered
    assert "dialog" not in rendered.lower()
    state.video_failed("tiktok:7")
    state.video_failed("tiktok:7")
    assert state.failed_videos == ["tiktok:7"]  # its MP4 died: the embed takes over
    state.cover_failed("instagram:A")
    state.cover_failed("instagram:A")
    assert state.failed_covers == ["instagram:A"]  # its cover expired: the placeholder
    state.toggle_details("instagram:A")
    state.toggle_details("tiktok:7")
    state.toggle_details("instagram:A")
    assert state.expanded == ["tiktok:7"]


def test_a_card_whose_cover_fails_shows_the_placeholder() -> None:
    import reflex as rx

    from .discover_reels import DiscoverReelsState, _reel_tile

    rendered = str(rx.foreach(DiscoverReelsState.reels, _reel_tile).render())
    assert "onError" in rendered and "cover_failed" in rendered
    assert "failed_covers" in rendered and "film" in rendered.lower()


def test_the_cards_stay_on_the_backend_and_only_the_product_reaches_the_browser() -> None:
    from .discover_reels import DiscoverReelsState

    state = DiscoverReelsState()
    state._cards = [
        {"key": "instagram:A", "affinity": "producto"},
        {"key": "instagram:B", "affinity": "categoria"},
        {"key": "instagram:C", "affinity": "rubro"},  # never shown
    ]
    assert [c["key"] for c in state.reels] == ["instagram:A", "instagram:B"]
    assert "_cards" in DiscoverReelsState.get_fields()
    assert "_cards" not in DiscoverReelsState.vars
    deps = DiscoverReelsState.computed_vars["reels"]._deps(objclass=DiscoverReelsState)
    assert "_cards" in deps[DiscoverReelsState.get_full_name()]  # it recomputes on a read


def test_the_adapter_never_reaches_a_paid_door() -> None:
    """Nothing in the app's door to the stored ideas reads the vendor or asks the model."""
    import inspect

    source = inspect.getsource(rd)
    for door in ("scrapecreators", "review_reels", "reel_runs.run(", "cached_discover"):
        assert door not in source, door
