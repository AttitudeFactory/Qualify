"""«Descubrir reels» (§ request 2026-10-15) without the network: the vendor is a
`MockTransport`, the referentes store is `MemoryReferentesRepository` and the rubro
check a scripted review — so these pin whose reels are read (referentes only, the
hand-added ones too unless the review said they are another rubro), what a reel is
(videos only, inside the window), what the rubro check drops, and how a week and a
month are cut and ranked."""

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
)
from qualify_api.referentes.reels_ai import ReelReview, ReelToReview

from . import reels_discovery as rd
from . import scrapecreators_client as sc

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
NOW = 1_800_000_000.0
DAY = 24 * 3600


# --------------------------------------------------------------------------------------
# the vendor read
# --------------------------------------------------------------------------------------


def _ig_item(code: str, days_ago: float, *, video: bool = True, plays: int = 100) -> dict:
    """One `/v1/instagram/user/reels` item — the media under `media`, as measured live."""
    return {"media": _ig_media(code, days_ago, video=video, plays=plays)}


def _ig_media(code: str, days_ago: float, *, video: bool, plays: int) -> dict:
    return {
        "code": code,
        "url": f"https://www.instagram.com/reel/{code}/",
        "taken_at": int(NOW - days_ago * DAY),
        "media_type": 2 if video else 1,
        "product_type": "clips" if video else "feed",
        "play_count": plays,
        "like_count": 10,
        "comment_count": 2,
        "caption": {"text": f"reel {code} #burger"},
        "image_versions2": {
            "candidates": [{"url": f"https://scontent.cdninstagram.com/{code}.jpg"}]
        },
        "video_duration": 14.6,
        "clips_metadata": {"original_sound_info": {"original_audio_title": "Audio original"}},
    }


def _client(pages: list[dict]) -> tuple[httpx.Client, list[dict[str, str]]]:
    seen: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=pages[len(seen) - 1])

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "test-key")


def test_instagram_reels_are_videos_inside_the_window() -> None:
    page_one = {
        "items": [_ig_item("A", 1), _ig_item("P", 2, video=False), _ig_item("B", 6)],
        "paging_info": {"max_id": "c1", "more_available": True},
    }
    page_two = {
        "items": [_ig_item("C", 20), _ig_item("A", 1), _ig_item("D", 40)],
        "paging_info": {"max_id": "c2", "more_available": True},
    }
    client, seen = _client([page_one, page_two])
    reels = sc.fetch_reels("instagram", "@BurgerCo", since=NOW - 30 * DAY, client=client)
    # the photo and the 40-day one out, the repeated one kept once
    assert [r["id"] for r in reels] == ["A", "B", "C"]
    assert seen[1]["max_id"] == "c1" and len(seen) == 2  # page two ended the walk
    first = reels[0]
    assert first["url"] == "https://www.instagram.com/reel/A/"
    assert first["views"] == 100 and first["seconds"] == 15 and first["sound"] == "Audio original"
    assert first["cover"].endswith("/A.jpg") and first["handle"] == "burgerco"


def test_tiktok_reels_skip_photo_posts_and_read_the_figures() -> None:
    video = {
        "aweme_id": "711",
        "create_time": int(NOW - DAY),
        "desc": "smash burger",
        "statistics": {
            "play_count": 5000,
            "digg_count": 300,
            "comment_count": 12,
            "share_count": 7,
            "collect_count": 40,
        },
        "video": {"duration": 21000, "cover": {"url_list": ["https://p16.tiktokcdn.com/c.jpg"]}},
        "music": {"title": "son original", "author": "burgerco"},
    }
    photo = {**video, "aweme_id": "712", "image_post_info": {"images": []}}
    slideshow = {**video, "aweme_id": "713", "aweme_type": 150}
    client, seen = _client([{"aweme_list": [video, photo, slideshow], "has_more": False}])
    reels = sc.fetch_reels("tiktok", "burgerco", since=NOW - 7 * DAY, client=client)
    # `popular` would be the account's whole history by likes: latest, pinned left out
    assert (seen[0]["sort_by"], seen[0]["include_pinned"]) == ("latest", "false")
    assert [r["id"] for r in reels] == ["711"]
    reel = reels[0]
    assert (reel["views"], reel["likes"], reel["shares"], reel["saves"], reel["seconds"]) == (
        5000,
        300,
        7,
        40,
        21,
    )
    assert reel["url"] == "https://www.tiktok.com/@burgerco/video/711"
    assert reel["sound"] == "son original · burgerco"


# --------------------------------------------------------------------------------------
# whose reels
# --------------------------------------------------------------------------------------


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


def test_referentes_are_the_labelled_ones_of_the_brands_rubro(store: Any) -> None:
    repo, brand = store
    found = rd.brand_referentes(TENANT, brand, repository=repo)
    # competencia is not a referente; the hand-added make-up account was judged another
    # rubro; an account on no network we read cannot be read
    assert {(r.network, r.handle) for r in found} == {("instagram", "foodie"), ("tiktok", "vecino")}
    assert next(r for r in found if r.handle == "foodie").kind == "creador"


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


# --------------------------------------------------------------------------------------
# the whole pipeline
# --------------------------------------------------------------------------------------


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


def test_discover_drops_another_rubro_and_splits_week_and_month(store: Any) -> None:
    repo, brand = store
    feeds = {
        "foodie": [
            _reel("foodie", "W1", 2, 900, "la smash burger del centro"),
            _reel("foodie", "MK", 3, 99_000, "mi rutina de maquillaje"),
            _reel("foodie", "M1", 20, 5_000, "probando hamburguesas"),
        ],
        "vecino": [_reel("vecino", "W2", 1, 1_500, "papas y burger")],
    }
    asked: list[list[ReelToReview]] = []

    def fetch(network: str, handle: str, *, since: float, client: Any) -> list[dict]:
        assert since == NOW - 30 * DAY  # one walk per account covers both windows
        return feeds[handle]

    def review(brief: Any, reels: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
        asked.append(list(reels))
        return (
            [
                ReelReview(id=r.id, fits="maquillaje" not in r.caption, reason=f"ok {r.id}")
                for r in reels
            ],
            CallStats("m", None, 0, 0),
        )

    result = rd.discover(
        TENANT, brand, now=NOW, repository=repo, fetch=fetch, review=review, api_key="k"
    )
    assert result.reviewed and result.dropped == 1 and result.referentes == 2
    assert [c["key"] for c in result.week] == ["instagram:W2", "instagram:W1"]  # by views
    assert [c["key"] for c in result.month] == ["instagram:M1", "instagram:W2", "instagram:W1"]
    card = result.month[0]
    assert card["views"] == "5K" and card["age"] == "hace 20 días" and card["rank"] == "1"
    assert card["per_day"] == "250/día" and card["saves"] == ""
    assert card["cover"].startswith("/avatar/reel/instagram/M1?u=https%3A%2F%2F")
    assert card["reason"] == "ok instagram:M1"
    assert any(r.account_kind == "creador" for r in asked[0])


def test_without_the_check_nothing_is_shown_and_nothing_is_remembered(
    store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ founder 2026-10-16: an unchecked reel never reaches the screen (another
    product's promo would), the view says «inténtalo más tarde», and that read is not
    cached — the next load tries the model again."""
    repo, brand = store

    def fetch(network: str, handle: str, **_: Any) -> list[dict]:
        return [_reel(handle, f"{handle}1", 1, 10, "algo")]

    def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("400 credit balance too low")

    result = rd.discover(
        TENANT, brand, now=NOW, repository=repo, fetch=fetch, review=broken, api_key="k"
    )
    assert not result.reviewed and result.check == rd.CHECK_UNAVAILABLE
    assert result.week == [] and result.month == [] and result.dropped == 0
    assert result.read == 2  # what was read is still said

    # a reel the model skipped (or whose batch failed alone) is not shown either
    def half(brief: Any, reels: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
        return [ReelReview(id=reels[0].id, fits=True, reason="")], CallStats("m", None, 0, 0)

    shown = rd.discover(
        TENANT, brand, now=NOW, repository=repo, fetch=fetch, review=half, api_key="k"
    )
    assert shown.reviewed and shown.check == "" and len(shown.week) == 1

    key = (str(TENANT), str(brand))
    monkeypatch.setattr(rd, "_cache", {})
    monkeypatch.setattr(rd, "_brand_locks", {})
    monkeypatch.setattr(rd, "_reads", {})
    monkeypatch.setattr(rd, "discover", lambda *a, **k: result)
    rd.cached_discover(TENANT, brand)
    assert key not in rd._cache  # the next load asks the model again
    monkeypatch.setattr(rd, "discover", lambda *a, **k: shown)
    rd.cached_discover(TENANT, brand)
    assert rd._cache[key] is shown


def test_a_brand_that_never_ran_its_search_is_told_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.referentes import MemoryReferentesRepository

    monkeypatch.setattr(rd, "brand_referentes", lambda *a, **k: [rd.Referente("instagram", "x")])
    result = rd.discover(
        TENANT,
        TENANT,
        now=NOW,
        repository=MemoryReferentesRepository(),
        fetch=lambda *a, **k: [_reel("x", "A", 1, 10, "burger")],
        review=lambda *a, **k: pytest.fail("checked without a brief"),
        api_key="k",
    )
    assert result.check == rd.CHECK_NO_BRIEF and result.week == []


def test_an_unreadable_referente_is_reported_not_fatal(store: Any) -> None:
    repo, brand = store

    def fetch(network: str, handle: str, **_: Any) -> list[dict]:
        if handle == "vecino":
            raise sc.ScrapeCreatorsError("private", status_code=404)
        return [_reel(handle, "X", 1, 10, "burger")]

    def review(brief: Any, reels: list[ReelToReview], **_: Any) -> tuple[list, None]:
        return [ReelReview(id=r.id, fits=True, reason="") for r in reels], None

    result = rd.discover(
        TENANT, brand, now=NOW, repository=repo, fetch=fetch, review=review, api_key="k"
    )
    assert result.failed == ["@vecino"] and [c["key"] for c in result.week] == ["instagram:X"]


def test_labels_read_like_the_cards() -> None:
    assert rd.compact(12_400) == "12.4K" and rd.compact(None) == "—"
    assert rd.age_label(time.time() - 3600, time.time()) == "hoy"
    assert rd.engagement_label({"views": 1000, "likes": 45, "comments": 5}) == "5%"


# --------------------------------------------------------------------------------------
# the cover proxy and the view
# --------------------------------------------------------------------------------------


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


def test_a_reel_plays_in_the_networks_own_player() -> None:
    """§ 2026-10-15: seen inside Qualify without downloading — the official embeds."""
    ig = rd.reel_card(_reel("foodie", "DecE2c8x7c_", 1, 10, "x"), 1, NOW)
    assert ig["embed"] == "https://www.instagram.com/reel/DecE2c8x7c_/embed/"
    tt = rd.reel_card(
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


def test_the_summary_says_what_was_read_and_dropped() -> None:
    from .discover_reels import DiscoverReelsState

    state = DiscoverReelsState()
    state.fetched_at = time.time()
    state.referentes, state.read, state.dropped = 7, 153, 47
    assert state.summary == "De 7 referentes · 153 reels del mes · 47 de otro producto"


# --------------------------------------------------------------------------------------
# card «C»: how a reel does against its own account, what it is, just the video
# --------------------------------------------------------------------------------------


def test_the_lift_is_against_the_accounts_median() -> None:
    reels = [_reel("foodie", f"F{n}", 1, v, "x") for n, v in enumerate([100, 100, 120, 400])]
    reels.append(_reel("tiny", "T1", 1, 999, "x"))  # one reel: no typical to compare to
    lifts = rd.account_lifts(reels)
    assert round(lifts["instagram:F3"], 2) == round(400 / 110, 2)  # median of 100,100,120,400
    assert "instagram:T1" not in lifts
    assert rd.lift_label(3.64) == ("x3.6 sobre su media", "ok")
    assert rd.lift_label(1.5) == ("x1.5 sobre su media", "neutral")
    assert rd.lift_label(2.0) == ("x2 sobre su media", "ok")
    assert rd.lift_label(0.8) == ("", "")
    assert rd.lift_label(None) == ("", "")


def test_the_card_carries_the_video_the_lift_and_the_tags() -> None:
    reel = {**_reel("foodie", "A", 1, 10, "x"), "video": "https://scontent.cdninstagram.com/a.mp4"}
    review = ReelReview(
        id="instagram:A",
        fits=True,
        reason="Receta.",
        format="receta",
        hook="otro",
        affinity="producto",
    )
    card = rd.reel_card(reel, 1, NOW, lift=2.5, review=review)
    assert card["video"].endswith("/a.mp4")
    assert (card["lift"], card["lift_tone"]) == ("x2.5 sobre su media", "ok")
    assert (card["format"], card["hook"], card["reason"]) == ("receta", "", "Receta.")
    assert card["affinity"] == "producto"  # the card's «Tu producto» tag


def test_the_reel_readers_keep_the_mp4() -> None:
    ig = sc._instagram_reel(
        {
            "media": {
                **_ig_media("A", 1, video=True, plays=5),
                "video_versions": [{"url": "https://scontent.cdninstagram.com/a.mp4"}],
            }
        },
        "x",
    )
    assert ig["video"].endswith("/a.mp4")
    tt = sc._tiktok_reel(
        {
            "aweme_id": "1",
            "create_time": int(NOW),
            "video": {"play_addr": {"url_list": ["https://v16m.tiktokcdn-eu.com/v.mp4"]}},
        },
        "x",
    )
    assert tt["video"].endswith("/v.mp4")


# --------------------------------------------------------------------------------------
# what they say
# --------------------------------------------------------------------------------------


def test_vtt_becomes_plain_spoken_text() -> None:
    vtt = (
        "WEBVTT\n\n\n00:00:00.660 --> 00:00:01.460\nDolores!\n\n"
        "1\n00:00:02.460 --> 00:00:05.160 align:start\nDolores, tus hot dogs.\n\n"
        "00:00:05.161 --> 00:00:06.000\nDolores, tus hot dogs.\n"
    )
    assert sc.vtt_text(vtt) == "Dolores! Dolores, tus hot dogs."


def test_the_instagram_transcript_is_one_cached_call() -> None:
    payload = {
        "success": True,
        "transcripts": [{"id": "1", "text": "La salsa de trufa "}, {"id": "2", "text": None}],
    }
    client, seen = _client([payload])
    text = sc.fetch_instagram_transcript("https://www.instagram.com/reel/A/", client=client)
    assert text == "La salsa de trufa"
    assert seen[0]["url"] == "https://www.instagram.com/reel/A/"
    assert seen[0]["cache_max_age"] == sc.TRANSCRIPT_CACHE_DAYS  # a cached one costs nothing


def test_tiktok_captions_only_come_from_tiktoks_cdn() -> None:
    assert sc.fetch_tiktok_captions("https://evil.example/x.vtt") == ""
    item = {
        "aweme_id": "9",
        "create_time": int(NOW),
        "video": {
            "cla_info": {
                "caption_infos": [
                    {"lang": "eng-US", "url": "https://v16-cla.tiktokcdn-eu.com/en"},
                    {"lang": "spa-ES", "url": "https://v16-cla.tiktokcdn-eu.com/es"},
                ]
            }
        },
    }
    assert sc._tiktok_reel(item, "x")["captionUrl"].endswith("/es")  # Spanish first


def test_a_transcript_is_fetched_only_when_asked_and_paid_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 2026-10-15: no transcript on a read; one reel's on demand, remembered."""
    monkeypatch.setattr(rd, "_transcripts", {})
    calls: list[str] = []

    def fetch(reel: dict, client: Any) -> str:
        calls.append(reel["id"])
        return "  la mejor   smash burger "

    card = rd.reel_card(_reel("foodie", "A", 1, 10, "x"), 1, NOW)
    assert card["transcript"] == "" and card["transcript_state"] == ""
    assert rd.transcript_for_card(card, fetch=fetch) == "la mejor smash burger"
    assert rd.transcript_for_card(card, fetch=fetch) == "la mejor smash burger"
    assert calls == ["A"]  # the second ask is free: remembered


def test_a_failed_transcript_is_not_remembered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rd, "_transcripts", {})

    def broken(reel: dict, client: Any) -> str:
        raise sc.ScrapeCreatorsError("timeout")

    card = rd.reel_card(_reel("foodie", "B", 1, 10, "x"), 1, NOW)
    with pytest.raises(sc.ScrapeCreatorsError):
        rd.transcript_for_card(card, fetch=broken)
    assert rd._transcripts == {}  # asking again retries


def test_a_read_transcribes_the_candidates_for_the_rubro_check(
    store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§ 2026-10-15 (restored): what is said reaches the filter — a known transcript
    from memory, an unknown one fetched — and the reel it convicts is dropped."""
    repo, brand = store
    monkeypatch.setattr(rd, "_transcripts", {"instagram:foodie1": "hoy pruebo este labial"})
    seen: list[ReelToReview] = []
    fetched: list[str] = []

    def fetch(network: str, handle: str, **_: Any) -> list[dict]:
        return [_reel(handle, f"{handle}1", 1, 10, "😂")]

    def review(brief: Any, reels: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
        seen.extend(reels)
        return (
            [ReelReview(id=r.id, fits="labial" not in r.transcript, reason="") for r in reels],
            CallStats("m", None, 0, 0),
        )

    def transcribe_fetch(reel: dict, client: Any) -> str:
        fetched.append(reel["id"])
        return "la mejor smash burger"

    result = rd.discover(
        TENANT,
        brand,
        now=NOW,
        repository=repo,
        fetch=fetch,
        review=review,
        api_key="k",
        transcribe_fetch=transcribe_fetch,
    )
    assert {r.id: r.transcript for r in seen} == {
        "instagram:foodie1": "hoy pruebo este labial",  # remembered: not paid again
        "instagram:vecino1": "la mejor smash burger",  # new: fetched before the check
    }
    assert fetched == ["vecino1"]
    assert [c["key"] for c in result.week] == ["instagram:vecino1"]
    assert (result.transcribed, result.paid_transcripts) == (1, 1)
    assert result.week[0]["transcript"] == "la mejor smash burger"  # and the card has it


def test_transcripts_are_paid_once_and_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rd, "_transcripts", {})
    monkeypatch.setattr(rd, "MAX_PAID_TRANSCRIPTS", 2)
    calls: list[str] = []

    def fetch(reel: dict, client: Any) -> str:
        calls.append(reel["id"])
        return f"dice {reel['id']}"

    reels = [_reel("foodie", f"R{n}", 1, 100 - n, "x") for n in range(3)]
    reels.append({**_reel("vecino", "T1", 1, 5, "x"), "network": "tiktok", "captionUrl": "u"})
    reels.append({**_reel("vecino", "T2", 1, 4, "x"), "network": "tiktok"})  # no subtitles
    fetched, paid = rd.transcribe(reels, fetch=fetch)
    assert (fetched, paid) == (3, 2)  # the third Instagram one is over the ceiling
    assert [r["transcript"] for r in reels] == ["dice R0", "dice R1", "", "dice T1", ""]
    calls.clear()
    again = [_reel("foodie", "R0", 1, 100, "x")]
    assert rd.transcribe(again, fetch=fetch) == (0, 0) and again[0]["transcript"] == "dice R0"
    assert calls == []  # remembered: never paid twice


def test_the_card_fetches_its_transcript_on_demand(monkeypatch: pytest.MonkeyPatch) -> None:
    from .discover_reels import DiscoverReelsState

    card = rd.reel_card(_reel("foodie", "A", 1, 10, "x"), 1, NOW)
    state = DiscoverReelsState()
    state.week = [card]
    state.month = [card]
    state._set_transcript(card["key"], "hola")
    assert state.week[0]["transcript"] == state.month[0]["transcript"] == "hola"
    assert state.week[0]["transcript_state"] == "said"
    state._set_transcript(card["key"], "")
    assert state.month[0]["transcript_state"] == "none"  # «Este video no tiene voz»


# --------------------------------------------------------------------------------------
# review findings of 2026-10-15: transient failures, money, the public cover route
# --------------------------------------------------------------------------------------


def test_tiktok_captions_that_cannot_be_read_raise_instead_of_meaning_no_speech() -> None:
    url = "https://v16-cla.tiktokcdn-eu.com/es"

    def answering(status: int, body: str) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(status, text=body))
        )

    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhola\n"
    assert sc.fetch_tiktok_captions(url, client=answering(200, vtt)) == "hola"
    for status, body in ((403, ""), (500, ""), (200, "<html></html>")):
        with pytest.raises(sc.ScrapeCreatorsError):
            sc.fetch_tiktok_captions(url, client=answering(status, body))

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(sc.ScrapeCreatorsError):
        sc.fetch_tiktok_captions(url, client=httpx.Client(transport=httpx.MockTransport(down)))


def test_vtt_drops_cue_identifiers_that_are_not_numbers() -> None:
    vtt = (
        "WEBVTT\n\nintro\n00:00.000 --> 00:01.000\nHola\n\nNOTE una nota\n\n"
        "c-2\n00:01.000 --> 00:02.000 align:start\nqué tal\n"
    )
    assert sc.vtt_text(vtt) == "Hola qué tal"


def test_a_failed_transcript_is_neither_counted_nor_remembered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rd, "_transcripts", {})

    def flaky(reel: dict, client: Any) -> str:
        if reel["id"] == "R1":
            raise sc.ScrapeCreatorsError("timeout")
        return "dice algo"

    reels = [_reel("foodie", "R0", 1, 10, "x"), _reel("foodie", "R1", 1, 9, "x")]
    assert rd.transcribe(reels, fetch=flaky) == (1, 1)  # one read, one paid
    assert "instagram:R1" not in rd._transcripts  # the next read retries it


def test_without_an_api_key_a_read_buys_no_transcript(
    store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No key → no product check → nothing would read a new transcript: none is bought,
    and nothing unchecked is shown."""
    repo, brand = store
    monkeypatch.setattr(rd, "_env_key", lambda: None)

    def fetch(network: str, handle: str, **_: Any) -> list[dict]:
        return [_reel(handle, f"{handle}1", 1, 10, "x")]

    def never(reel: dict, client: Any) -> str:
        raise AssertionError("paid for a transcript nobody reads")

    result = rd.discover(
        TENANT, brand, now=NOW, repository=repo, fetch=fetch, transcribe_fetch=never
    )
    assert not result.reviewed and (result.transcribed, result.paid_transcripts) == (0, 0)
    assert result.check == rd.CHECK_UNAVAILABLE and result.week == []


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


def test_the_summarys_age_is_rendered_by_the_browser() -> None:
    """No heartbeat to the server just to move «hace 3 minutos»: the summary is the
    static part and the toolbar hands the age to `rx.moment(from_now)`, in Spanish."""
    import inspect

    from . import discover_reels
    from .discover_reels import DiscoverReelsState, discover_view

    state = DiscoverReelsState()
    state.referentes, state.fetched_at = 1, NOW
    assert state.summary == "De 1 referente"
    assert not hasattr(state, "tick")
    rendered = str(discover_view().render())
    assert "fromNow" in rendered and "actualizado" in rendered
    assert "interval=" not in inspect.getsource(discover_reels)  # no heartbeat event


def test_two_loads_of_a_brand_at_once_read_it_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(rd, "_cache", {})
    monkeypatch.setattr(rd, "_brand_locks", {})
    monkeypatch.setattr(rd, "_reads", {})
    reading = threading.Event()
    calls: list[float] = []

    def slow(tenant_id: UUID, brand_id: UUID, **_: Any) -> rd.DiscoveredReels:
        started = time.time()  # stamped at the start, like the real `discover`
        calls.append(started)
        reading.set()
        time.sleep(0.3)
        return rd.DiscoveredReels(fetched_at=started)

    monkeypatch.setattr(rd, "discover", slow)

    def second() -> rd.DiscoveredReels:
        reading.wait(5)
        return rd.cached_discover(TENANT, TENANT, refresh=True)

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(rd.cached_discover, TENANT, TENANT, refresh=True)
        other = pool.submit(second)
        assert first.result() is other.result()
    assert len(calls) == 1  # the second waited for the first read instead of paying again
    rd.cached_discover(TENANT, TENANT, refresh=True)
    assert len(calls) == 2  # a refresh asked after that read does read again


# --------------------------------------------------------------------------------------
# second review of 2026-10-15
# --------------------------------------------------------------------------------------


def test_a_fresh_hit_is_answered_while_another_load_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    key = (str(TENANT), str(TENANT))
    hit = rd.DiscoveredReels(fetched_at=time.time())
    lock = threading.Lock()
    monkeypatch.setattr(rd, "_cache", {key: hit})
    monkeypatch.setattr(rd, "_brand_locks", {key: lock})
    monkeypatch.setattr(rd, "_reads", {})
    monkeypatch.setattr(rd, "discover", lambda *a, **k: pytest.fail("read the vendor"))
    lock.acquire()  # another tab's «Actualizar» is reading this brand right now
    pool = ThreadPoolExecutor(1)
    try:
        assert pool.submit(rd.cached_discover, TENANT, TENANT).result(timeout=2) is hit
    finally:
        lock.release()
        pool.shutdown()


def test_tiktok_captions_may_start_with_a_bom() -> None:
    vtt = "﻿WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhola\n"
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, text=vtt)))
    assert sc.fetch_tiktok_captions("https://v16.tiktokcdn.com/es", client=client) == "hola"
    assert sc.vtt_text(vtt) == "hola"


def test_instagram_views_fall_back_when_play_count_is_null() -> None:
    media = {**_ig_media("A", 1, video=True, plays=0), "play_count": None, "ig_play_count": 250}
    reel = sc._instagram_reel({"media": media}, "burgerco")
    assert reel is not None and reel["views"] == 250


def test_vendor_links_and_videos_are_taken_only_over_https() -> None:
    media = {
        **_ig_media("A", 1, video=True, plays=1),
        "url": "javascript:alert(1)",
        "video_versions": [{"url": "http://evil.example/a.mp4"}],
    }
    ig = sc._instagram_reel({"media": media}, "burgerco")
    assert ig is not None and ig["url"] == "https://www.instagram.com/reel/A/" and ig["video"] == ""
    tt = sc._tiktok_reel(
        {
            "aweme_id": "7",
            "create_time": int(NOW),
            "url": "https://not-tiktok.example/@x/video/7",
            "video": {"play_addr": {"url_list": ["https://v16-webapp.tiktok.com/7.mp4"]}},
        },
        "vecino",
    )
    assert tt is not None and tt["url"] == "https://www.tiktok.com/@vecino/video/7"
    assert tt["video"] == "https://v16-webapp.tiktok.com/7.mp4"


def test_a_failed_check_says_why_on_screen(store: Any) -> None:
    """«No pudimos filtrar los reels» used to say nothing more: the reason travels with
    the result (`check_detail`), in a few words, and the log keeps the whole error."""
    repo, brand = store

    def fetch(network: str, handle: str, **_: Any) -> list[dict]:
        return [_reel(handle, f"{handle}1", 1, 10, "algo")]

    class Quota(Exception):
        status_code = 429

    def exhausted(*_: Any, **__: Any) -> Any:
        raise Quota("You exceeded your current quota")

    result = rd.discover(
        TENANT, brand, now=NOW, repository=repo, fetch=fetch, review=exhausted, api_key="k"
    )
    assert result.check == rd.CHECK_UNAVAILABLE and result.week == []
    assert result.check_detail == "el modelo de IA agotó su cuota de uso (429)"


@pytest.mark.parametrize(
    ("status", "message", "reason"),
    [
        (404, "model gone", "el modelo de IA configurado ya no está disponible (404)"),
        (401, "bad key", "el servicio de IA rechazó la clave (401)"),
        (400, "Your credit balance is too low", "la cuenta del servicio de IA no tiene saldo"),
        (529, "Overloaded", "el modelo de IA está saturado o caído (529)"),
        (500, "boom", "el servicio de IA falló (500)"),
    ],
)
def test_failure_reasons_are_short_and_human(status: int, message: str, reason: str) -> None:
    class Refused(Exception):
        status_code = status

    assert rd.check_failure_reason(Refused(message)) == reason


def test_compact_figures_round_before_choosing_the_unit() -> None:
    from .creator_discovery import _compact

    assert rd.compact(999_960) == "1M" and rd.compact(999_949) == "999.9K"
    assert rd.compact(1_260_000) == "1.3M" and rd.compact(0) == "0" and rd.compact(None) == "—"
    assert _compact(0) == "—"  # a candidate without a figure reads as unknown
    long_caption = "palabra " * 40
    card = rd.reel_card(_reel("foodie", "A", 1, 10, long_caption), 1, NOW)
    assert len(card["caption"]) == rd.CAPTION_CARD_CHARS and card["caption"].endswith("…")
