"""«Descubrir reels» — the Reflex app's side (§ request 2026-10-15), without the network.

The pipeline is `qualify_api.referentes.reels` and its tests live with it
(`packages/api/tests/test_referentes_reels.py`, ADR 42 R1, m-24854844). These pin what
only the app knows — the brand brief built from the search seed, the Brand Kit and the
catalog; the signed cover route — that the adapter hands both to the service, and the
view and state of «Descubrir reels»."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from qualify_api.claude_tools import CallStats
from qualify_api.referentes import (
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
    reels,
)
from qualify_api.referentes.reels_ai import ReelReview, ReelToReview

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


@pytest.fixture(autouse=True)
def _fresh_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """The process-wide memories start empty in every test: a verdict or an in-flight
    transcript of one test must not answer another."""
    from collections import OrderedDict

    monkeypatch.setattr(reels, "_verdicts", OrderedDict())
    monkeypatch.setattr(reels, "_transcripts_inflight", {})


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
# the adapter: the app's brief and cover reach the service
# --------------------------------------------------------------------------------------


def test_the_adapter_hands_the_brief_and_the_signed_cover_to_the_service(store: Any) -> None:
    repo, brand = store
    briefs: list[Any] = []

    def review(brief: Any, items: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
        briefs.append(brief)
        return [ReelReview(id=r.id, fits=True, reason="") for r in items], CallStats(
            "m", None, 0, 0
        )

    result = rd.discover(
        TENANT,
        brand,
        now=NOW,
        repository=repo,
        fetch=lambda network, handle, **_: [_reel(handle, f"{handle}1", 20, 5_000, "burger")],
        review=review,
        api_key="k",
    )
    assert result.reviewed and briefs and briefs[0].rubro == ("hamburguesería",)
    card = result.month[0]
    assert card["cover"].startswith("/avatar/reel/instagram/") and "&s=" in card["cover"]


def test_the_adapter_remembers_through_the_services_memory(
    store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cached_discover` is the service's: one memory per brand and depth, whichever
    caller asks."""
    repo, brand = store
    monkeypatch.setattr(reels, "_cache", {})
    monkeypatch.setattr(reels, "_brand_locks", {})
    monkeypatch.setattr(reels, "_reads", {})
    seen: list[dict[str, Any]] = []

    def fake(tenant_id: UUID, brand_id: UUID, **kwargs: Any) -> reels.DiscoveredReels:
        seen.append(kwargs)
        return reels.DiscoveredReels(fetched_at=time.time())

    monkeypatch.setattr(reels, "discover", fake)
    first = rd.cached_discover(TENANT, brand, repository=repo)
    assert rd.cached_discover(TENANT, brand, repository=repo) is first  # remembered
    assert len(seen) == 1 and seen[0]["repository"] is repo
    assert seen[0]["cover"] is rd.cover_path and seen[0]["brief"](TENANT, brand) is not None
    assert reels.remembered(TENANT, brand) is first


async def test_a_reel_cover_is_fetched_once_and_kept(tmp_path: Any) -> None:
    from .avatar_proxy import resolve_reel_cover

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=b"jpeg-bytes", headers={"content-type": "image/jpeg"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        url = "https://scontent.cdninstagram.com/A.jpg"
        first = await resolve_reel_cover("instagram", "A", url, client=client, directory=tmp_path)
        again = await resolve_reel_cover("instagram", "A", "", client=client, directory=tmp_path)
        foreign = await resolve_reel_cover(
            "instagram", "B", "https://evil.example/x.jpg", client=client, directory=tmp_path
        )
        bad_id = await resolve_reel_cover(
            "instagram", "../x", url, client=client, directory=tmp_path
        )
    assert first == again == (b"jpeg-bytes", "image/jpeg") and len(calls) == 1
    assert foreign is None and bad_id is None


def test_the_view_renders_its_tabs_and_grid() -> None:
    from .discover_reels import discover_view

    rendered = str(discover_view().render())
    assert "Esta semana" in rendered and "Este mes" in rendered and "q-dr-grid" in rendered
    # without the product check: «inténtalo más tarde», or «run your search» — never a list
    assert "No pudimos filtrar los reels ahora mismo" in rendered
    assert "vende tu marca" in rendered  # «Aún no sabemos qué…» (accents come escaped)
    assert "revísalos antes de" not in rendered  # the old «shown unchecked» notice is gone


def test_a_refused_read_says_try_later_not_unreadable_or_no_reels() -> None:
    """ADR 42 R2 (UX review): when the metered gate refused, the view says «Ahora no
    pudimos buscar…», never «No pudimos leer @a (privada…)» nor «no publicaron reels»;
    and no error names the vendor or the database."""
    from . import discover_reels
    from .discover_reels import DiscoverReelsState, discover_view

    rendered = str(discover_view().render())
    assert "Ahora no pudimos buscar los reels de tus referentes" in rendered
    assert rd.CHECK_READ_UNAVAILABLE in rendered  # the branch the refused read takes
    state = DiscoverReelsState()
    state._reads = {"month": {"check": rd.CHECK_READ_UNAVAILABLE, "failed": ""}}
    assert state.failed_note == ""  # no «No pudimos leer @… (privada, sin reels…)»
    for message in (discover_reels.READ_ERROR, discover_reels.QUARTER_READ_ERROR):
        assert "proveedor" not in message and "base de datos" not in message
        assert "(" not in message


def test_a_reel_plays_in_the_networks_own_player() -> None:
    """§ 2026-10-15: seen inside Qualify without downloading — the official embeds."""
    ig = reels.reel_card(_reel("foodie", "DecE2c8x7c_", 1, 10, "x"), 1, NOW)
    assert ig["embed"] == "https://www.instagram.com/reel/DecE2c8x7c_/embed/"
    tt = reels.reel_card(
        {**_reel("vecino", "7681392167478250765", 1, 10, "x"), "network": "tiktok"}, 1, NOW
    )
    assert tt["embed"].startswith("https://www.tiktok.com/player/v1/7681392167478250765?")


def test_the_reel_plays_inside_its_card_one_at_a_time() -> None:
    """§ 2026-10-15: no dialog — the card swaps its cover for the network's player."""
    from .discover_reels import DiscoverReelsState, discover_view

    state = DiscoverReelsState()
    state.play("instagram:A")
    assert state.playing_key == "instagram:A"
    state.play("tiktok:7")  # starting another stops the first (its iframe unmounts)
    assert state.playing_key == "tiktok:7"
    state.stop()
    assert state.playing_key == ""
    rendered = str(discover_view().render())
    # just the video (its MP4), the embed as the fallback, «Detalles» as an accordion
    assert '"video"' in rendered and "iframe" in rendered
    assert "q-dr-more-panel" in rendered and "Detalles" in rendered
    assert "Replicar con mi marca" in rendered and "Gancho" not in rendered
    assert "dialog" not in rendered.lower()
    state.video_failed("tiktok:7")
    state.video_failed("tiktok:7")
    assert state.failed_videos == ["tiktok:7"]  # its MP4 died: the embed takes over
    state.toggle_details("instagram:A")
    state.toggle_details("tiktok:7")
    state.toggle_details("instagram:A")
    assert state.expanded == ["tiktok:7"]  # opens and closes per card, several at once


def test_changing_period_stops_the_reel_even_when_it_remains_visible() -> None:
    """Switching periods returns the playing reel to its cover, even if it is shared."""
    import reflex as rx

    from .discover_reels import DiscoverReelsState, _reel_tile

    state = DiscoverReelsState()
    current = {"key": "instagram:A", "affinity": "producto"}
    older = {"key": "instagram:B", "affinity": "producto"}
    state._cards = {"week": [current], "month": [older, current]}
    state.play(current["key"])
    assert state.reels.index(current) == 0
    state.set_window("month")
    assert state.reels.index(current) == 1
    assert state.playing_key == ""
    state.set_window("week")
    assert state.playing_key == ""  # returning to the old period must not autoplay

    # Check the identity emitted for React, not just the backend's playing selection.
    rendered = rx.foreach(DiscoverReelsState.reels, _reel_tile).render()
    card_props = rendered["children"][0]["props"]
    assert f'key:{rendered["arg_name"]}?.["key"]' in card_props


@pytest.mark.parametrize("change", ["network", "account", "clear"])
def test_changing_reel_filters_stops_playback(change: str) -> None:
    from .discover_reels import ALL, DiscoverReelsState

    state = DiscoverReelsState()
    state.accounts = [{"key": "instagram:foodie", "network": "instagram"}]
    if change == "clear":
        state.set_account("instagram:foodie")
    state.play("instagram:A")
    if change == "network":
        state.set_network("instagram")
    elif change == "account":
        state.set_account("instagram:foodie")
    else:
        state.clear_filters()
        assert state.network == state.account == ALL
    assert state.playing_key == ""


def test_invalid_or_unchanged_reel_filters_do_not_interrupt_playback() -> None:
    from .discover_reels import ALL, DiscoverReelsState

    state = DiscoverReelsState()
    state.play("instagram:A")
    state.set_window("week")
    state.set_window("invalid")
    state.set_network(ALL)
    state.set_network("invalid")
    state.set_account(ALL)
    state.set_account("instagram:unknown")
    state.clear_filters()
    assert state.playing_key == "instagram:A"


def test_the_toolbar_says_only_when_the_read_was_made() -> None:
    """§ founder 2026-10-20: «Actualizado hace 2 minutos», no counts of referentes, reels
    or dropped ones; the 90-day tab says it only once its own read exists."""
    from .discover_reels import DiscoverReelsState

    state = DiscoverReelsState()
    state._store("month", rd.DiscoveredReels(fetched_at=NOW, referentes=7, read=153, dropped=47))
    assert state.shown_iso == "2027-01-15T08:00:00+00:00"
    state.set_window("quarter")
    assert state.shown_iso == ""
    state._store("quarter", rd.DiscoveredReels(fetched_at=NOW - 3600, days=90))
    assert state.shown_iso == "2027-01-15T07:00:00+00:00"
    assert not hasattr(state, "summary")


def test_the_card_fetches_its_transcript_on_demand(monkeypatch: pytest.MonkeyPatch) -> None:
    from .discover_reels import DiscoverReelsState

    card = reels.reel_card(_reel("foodie", "A", 1, 10, "x"), 1, NOW)
    state = DiscoverReelsState()
    state._cards = {"week": [card], "month": [card], "quarter": [card]}
    state._set_transcript(card["key"], "hola")
    assert {cards[0]["transcript"] for cards in state._cards.values()} == {"hola"}
    assert state._cards["week"][0]["transcript_state"] == "said"
    state._set_transcript(card["key"], "")
    assert state._cards["quarter"][0]["transcript_state"] == "none"  # «no tiene voz»


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


def test_the_age_is_rendered_by_the_browser() -> None:
    """No heartbeat to the server just to move «hace 3 minutos»: the toolbar hands the
    age to `rx.moment(from_now)`, in Spanish."""
    import inspect

    from . import discover_reels
    from .discover_reels import DiscoverReelsState, discover_view

    assert not hasattr(DiscoverReelsState(), "tick")
    rendered = str(discover_view().render())
    assert "fromNow" in rendered and "Actualizado" in rendered
    assert "interval=" not in inspect.getsource(discover_reels)  # no heartbeat event


def _card(network: str, handle: str, key: str, affinity: str = "producto") -> dict[str, str]:
    return {
        "key": key,
        "network": network,
        "account": rd.account_key(network, handle),
        "affinity": affinity,
    }


def _filter_state() -> Any:
    from .discover_reels import DiscoverReelsState

    state = DiscoverReelsState()
    state.accounts = [
        {"key": "instagram:foodie", "network": "instagram", "handle": "@foodie"},
        {"key": "tiktok:vecino", "network": "tiktok", "handle": "@vecino"},
        {"key": "tiktok:rival", "network": "tiktok", "handle": "@rival"},
    ]
    state._cards = {
        "week": [
            _card("instagram", "foodie", "instagram:A"),
            _card("tiktok", "vecino", "tiktok:B"),
            _card("tiktok", "rival", "tiktok:C", affinity="rubro"),  # never shown
        ]
    }
    return state


def test_filters_cut_the_read_cards_without_reading(monkeypatch: pytest.MonkeyPatch) -> None:
    """§ m-24820844: changing platform or referente never calls the vendor nor the model."""
    monkeypatch.setattr(reels, "discover", lambda *a, **k: pytest.fail("read the vendor"))
    monkeypatch.setattr(reels, "check_rubro", lambda *a, **k: pytest.fail("called the model"))
    state = _filter_state()
    assert [c["key"] for c in state.reels] == ["instagram:A", "tiktok:B"]
    assert state.networks == ["instagram", "tiktok"]
    assert [o[1] for o in state.account_options] == [
        "@foodie · Instagram",
        "@vecino · TikTok",
        "@rival · TikTok",
    ]
    state.set_network("tiktok")
    assert [c["key"] for c in state.reels] == ["tiktok:B"] and state.filtering
    assert [o[1] for o in state.account_options] == ["@vecino", "@rival"]
    state.set_account("tiktok:rival")
    assert state.reels == [] and state.filtered_out  # its only reel is another rubro
    state.set_network("instagram")  # a TikTok referente is let go with its platform
    assert state.account == "all" and [c["key"] for c in state.reels] == ["instagram:A"]
    state.set_account("instagram:ghost")  # not a referente of this read: ignored
    assert state.account == "all"
    state.clear_filters()
    assert not state.filtering and len(state.reels) == 2


def test_the_shown_cards_are_cut_after_the_filters() -> None:
    state = _filter_state()
    state._cards = {
        "week": [
            *(_card("instagram", "foodie", f"instagram:F{n}") for n in range(30)),
            _card("tiktok", "vecino", "tiktok:V"),
        ]
    }
    assert len(state.reels) == rd.SHOWN_PER_WINDOW  # the vecino reel is past the cut…
    state.set_account("tiktok:vecino")
    assert [c["key"] for c in state.reels] == ["tiktok:V"]  # …and found by its filter
    # every card stays on the backend: the browser only ever receives `reels`
    from .discover_reels import DiscoverReelsState

    assert "_cards" in DiscoverReelsState.get_fields()
    assert "_cards" not in DiscoverReelsState.vars
    deps = DiscoverReelsState.computed_vars["reels"]._deps(objclass=DiscoverReelsState)
    assert "_cards" in deps[DiscoverReelsState.get_full_name()]  # it recomputes on a read


def test_the_90_day_tab_says_it_has_an_extra_charge() -> None:
    """§ founder 2026-10-20: a plain «cargo extra» before reading — no credits, no
    dollars on screen."""
    from . import discover_reels

    assert "cargo extra" in discover_reels.QUARTER_NOTE
    assert "cargo extra" in discover_reels.QUARTER_REFRESH_TITLE
    for text in (discover_reels.QUARTER_NOTE, discover_reels.QUARTER_REFRESH_TITLE):
        assert "crédito" not in text and "US$" not in text


def test_the_view_has_the_90_day_tab_and_the_filters() -> None:
    from .discover_reels import discover_view

    rendered = str(discover_view().render())
    assert "90 d" in rendered and '"Leer"' in rendered  # «días» comes escaped
    assert "Todos los referentes" in rendered and "Quitar filtros" in rendered
    assert "Plataforma" in rendered


def test_a_read_drops_filters_the_brand_no_longer_has() -> None:
    """A platform filter whose control vanished (one network left) must not keep hiding
    every card; nor a referente that is no longer one."""
    state = _filter_state()
    state.set_network("tiktok")
    state.set_account("tiktok:vecino")
    instagram_only = rd.DiscoveredReels(
        fetched_at=NOW,
        referentes=1,
        accounts=[{"key": "instagram:foodie", "network": "instagram", "handle": "@foodie"}],
        week=[_card("instagram", "foodie", "instagram:A")],
    )
    state._store("month", instagram_only)
    assert (state.network, state.account) == ("all", "all")
    assert [c["key"] for c in state.reels] == ["instagram:A"]


def test_the_month_and_the_90_days_are_stored_apart() -> None:
    """`_store` is what `load` / `load_quarter` hand their read to: the month fills the
    week and the month, the 90 days their own tab, each with its own check and moment."""
    from .discover_reels import DiscoverReelsState

    accounts = [{"key": "instagram:foodie", "network": "instagram", "handle": "@foodie"}]
    state = DiscoverReelsState()
    assert not state.loaded and not state.quarter_loaded
    state._store(
        "quarter",
        rd.DiscoveredReels(
            fetched_at=NOW,
            days=90,
            accounts=accounts,
            check=rd.CHECK_UNAVAILABLE,
            check_detail="el servicio de IA falló (500)",
            failed=["@vecino"],
        ),
    )
    assert state.quarter_loaded and not state.loaded and state.accounts == accounts
    state._store(
        "month",
        rd.DiscoveredReels(
            fetched_at=NOW,
            referentes=2,
            accounts=[*accounts, {"key": "tiktok:v", "network": "tiktok", "handle": "@v"}],
            week=[_card("instagram", "foodie", "instagram:W")],
            month=[_card("instagram", "foodie", "instagram:M")],
        ),
    )
    assert state.loaded and state.referentes == 2 and len(state.accounts) == 2
    assert [c["key"] for c in state.reels] == ["instagram:W"] and state.shown_check == ""
    state.set_window("quarter")
    assert state.shown_check == rd.CHECK_UNAVAILABLE and "falló (500)" in state.unchecked_note
    assert state.failed_note.startswith("No pudimos leer @vecino")
    state._store("quarter", rd.DiscoveredReels(fetched_at=NOW, days=90, accounts=accounts))
    assert len(state.accounts) == 2  # the month read's referentes stay the filter's


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
