"""«Descubrir reels» service (`qualify_api.referentes.reels`, ADR 42 R1, m-24854844)
without the network: the vendor is a `MockTransport`, the referentes store is
`MemoryReferentesRepository` and the rubro check a scripted review — so these pin whose
reels are read (referentes only, the hand-added ones too unless the review said they are
another rubro), what a reel is (videos only, inside the window), what the rubro check
drops, and how a week and a month are cut and ranked.

Moved from `Qualify/test_reels_discovery.py` with the pipeline. The brand brief and the
cover signer are the Reflex app's (`Qualify/reels_discovery.py`), so here they are handed
in (`BRIEF`, `_cover`); the app's own tests pin how it builds them."""

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
from qualify_api.referentes import ai as review_ai
from qualify_api.referentes import reels as rd
from qualify_api.referentes.reels_ai import ReelReview, ReelToReview
from qualify_api.vendors import scrapecreators as sc

#: ADR 42 R5: these tests exercise the vendor module itself, not who pays — every
#: paid read is charged to the conftest's placeholder business.
pytestmark = pytest.mark.usefixtures("paid_reads_charged")


TENANT = UUID("a0000000-0000-4000-8000-000000000001")
NOW = 1_800_000_000.0
DAY = 24 * 3600

#: What the app's `brand_brief` builds from the `store` fixture's search seed.
BRIEF = review_ai.BrandBrief(handle="burgerco", rubro=("hamburguesería",))


def _cover(reel: dict[str, Any]) -> str:
    return f"/cover/{reel['network']}/{reel['id']}"


def _discover(tenant_id: UUID, brand_id: UUID, **kwargs: Any) -> rd.DiscoveredReels:
    """`rd.discover` with the brief and the cover signer the app would hand in."""
    kwargs.setdefault("brief", lambda tenant, brand: BRIEF)
    kwargs.setdefault("cover", _cover)
    return rd.discover(tenant_id, brand_id, **kwargs)


def test_without_a_cover_signer_a_card_has_no_cover() -> None:
    card = rd.reel_card(_reel("foodie", "A", 1, 10, "x"), 1, NOW)
    assert card["cover"] == ""
    assert rd.reel_card(_reel("foodie", "A", 1, 10, "x"), 1, NOW, cover=_cover)["cover"] == (
        "/cover/instagram/A"
    )
    assert (
        rd.reel_card({**_reel("f", "B", 1, 1, "x"), "cover": ""}, 1, NOW, cover=_cover)["cover"]
        == ""
    )


def test_without_a_brief_loader_nothing_is_checked(store: Any) -> None:
    repo, brand = store
    result = rd.discover(
        TENANT,
        brand,
        now=NOW,
        repository=repo,
        fetch=lambda *a, **k: [_reel("foodie", "A", 1, 10, "burger")],
        review=lambda *a, **k: pytest.fail("checked without a brief"),
        api_key="k",
    )
    assert result.check == rd.CHECK_NO_BRIEF and result.week == [] and result.read == 2


def test_the_service_never_imports_the_reflex_app() -> None:
    """A `qualify_api` worker runs this module: nothing of `Qualify/` may be on its path."""
    import inspect

    source = inspect.getsource(rd)
    assert "from Qualify" not in source and "import Qualify" not in source
    assert "from ." not in source


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
def _fresh_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """The process-wide memories start empty in every test: a verdict or an in-flight
    transcript of one test must not answer another."""
    from collections import OrderedDict

    monkeypatch.setattr(rd, "_verdicts", OrderedDict())
    monkeypatch.setattr(rd, "_transcripts_inflight", {})


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

    def fetch(
        network: str, handle: str, *, since: float, client: Any, max_pages: int
    ) -> list[dict]:
        assert since == NOW - 30 * DAY  # one walk per account covers both windows
        assert max_pages == sc.REEL_MAX_PAGES  # the month read keeps the month's cap
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

    result = _discover(
        TENANT, brand, now=NOW, repository=repo, fetch=fetch, review=review, api_key="k"
    )
    assert result.reviewed and result.dropped == 1 and result.referentes == 2
    assert [c["key"] for c in result.week] == ["instagram:W2", "instagram:W1"]  # by views
    assert [c["key"] for c in result.month] == ["instagram:M1", "instagram:W2", "instagram:W1"]
    card = result.month[0]
    assert card["views"] == "5K" and card["age"] == "hace 20 días" and card["rank"] == "1"
    assert card["per_day"] == "250/día" and card["saves"] == ""
    assert card["cover"] == "/cover/instagram/M1"  # the caller's signer, handed in
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

    result = _discover(
        TENANT, brand, now=NOW, repository=repo, fetch=fetch, review=broken, api_key="k"
    )
    assert not result.reviewed and result.check == rd.CHECK_UNAVAILABLE
    assert result.week == [] and result.month == [] and result.dropped == 0
    assert result.read == 2  # what was read is still said

    # a reel the model skipped (or whose batch failed alone) is not shown either
    def half(brief: Any, reels: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
        return [ReelReview(id=reels[0].id, fits=True, reason="")], CallStats("m", None, 0, 0)

    shown = _discover(
        TENANT, brand, now=NOW, repository=repo, fetch=fetch, review=half, api_key="k"
    )
    assert shown.reviewed and shown.check == "" and len(shown.week) == 1

    key = (str(TENANT), str(brand), rd.MONTH_DAYS)
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

    result = _discover(
        TENANT, brand, now=NOW, repository=repo, fetch=fetch, review=review, api_key="k"
    )
    assert result.failed == ["@vecino"] and [c["key"] for c in result.week] == ["instagram:X"]


def test_a_refused_read_is_unavailable_not_unreadable_and_not_remembered(
    store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 42 R2: when the metered gate refuses (switch off, floor, 402), no account is
    «unreadable», nothing is checked or paid for, and the read is not cached 6 h."""
    repo, brand = store
    reviewed: list[int] = []

    def fetch(network: str, handle: str, **_: Any) -> list[dict]:
        if handle == "vecino":
            raise sc.ScrapeCreatorsBlocked("refused", reason="below_floor")
        return [_reel(handle, "X", 1, 10, "burger")]

    def review(brief: Any, reels: list[ReelToReview], **_: Any) -> tuple[list, None]:
        reviewed.append(len(reels))
        return [ReelReview(id=r.id, fits=True, reason="") for r in reels], None

    def no_transcript(*_: Any, **__: Any) -> Any:
        raise AssertionError("a refused read buys no transcript")

    result = _discover(
        TENANT,
        brand,
        now=NOW,
        repository=repo,
        fetch=fetch,
        review=review,
        api_key="k",
        transcribe_fetch=no_transcript,
    )
    assert result.check == rd.CHECK_READ_UNAVAILABLE
    assert result.failed == [] and result.week == [] and result.month == []
    assert reviewed == []

    key = (str(TENANT), str(brand), rd.MONTH_DAYS)
    monkeypatch.setattr(rd, "_cache", {})
    monkeypatch.setattr(rd, "_brand_locks", {})
    monkeypatch.setattr(rd, "_reads", {})
    monkeypatch.setattr(rd, "discover", lambda *a, **k: result)
    rd.cached_discover(TENANT, brand)
    assert key not in rd._cache


def test_labels_read_like_the_cards() -> None:
    assert rd.compact(12_400) == "12.4K" and rd.compact(None) == "—"
    assert rd.age_label(time.time() - 3600, time.time()) == "hoy"
    assert rd.engagement_label({"views": 1000, "likes": 45, "comments": 5}) == "5%"


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

    result = _discover(
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

    result = _discover(TENANT, brand, now=NOW, repository=repo, fetch=fetch, transcribe_fetch=never)
    assert not result.reviewed and (result.transcribed, result.paid_transcripts) == (0, 0)
    assert result.check == rd.CHECK_UNAVAILABLE and result.week == []


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


def test_a_fresh_hit_is_answered_while_another_load_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import threading
    from concurrent.futures import ThreadPoolExecutor

    key = (str(TENANT), str(TENANT), rd.MONTH_DAYS)
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

    result = _discover(
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
    assert rd.compact(999_960) == "1M" and rd.compact(999_949) == "999.9K"
    assert rd.compact(1_260_000) == "1.3M" and rd.compact(0) == "0" and rd.compact(None) == "—"
    long_caption = "palabra " * 40
    card = rd.reel_card(_reel("foodie", "A", 1, 10, long_caption), 1, NOW)
    assert len(card["caption"]) == rd.CAPTION_CARD_CHARS and card["caption"].endswith("…")


def _fits_all(brief: Any, reels: list[ReelToReview], **_: Any) -> tuple[list, CallStats]:
    return (
        [ReelReview(id=r.id, fits=True, reason="", affinity="producto") for r in reels],
        CallStats("m", None, 0, 0),
    )


def test_the_90_days_are_a_read_of_their_own(store: Any) -> None:
    """The deep read walks 90 days with three times the month's page cap and fills the
    90-day tab; the month read never does."""
    repo, brand = store
    walks: list[tuple[float, int]] = []

    def fetch(network: str, handle: str, *, since: float, max_pages: int, **_: Any) -> list:
        walks.append((since, max_pages))
        return [
            {**_reel(handle, f"{handle}-old", 60, 9_000, "burger"), "network": network},
            {**_reel(handle, f"{handle}-new", 2, 100, "burger"), "network": network},
        ]

    deep = _discover(
        TENANT,
        brand,
        now=NOW,
        repository=repo,
        fetch=fetch,
        review=_fits_all,
        api_key="k",
        days=rd.QUARTER_DAYS,
    )
    assert set(walks) == {(NOW - 90 * DAY, 3 * sc.REEL_MAX_PAGES)}
    assert deep.days == 90
    assert {c["key"] for c in deep.quarter[:2]} == {"instagram:foodie-old", "tiktok:vecino-old"}
    assert all("old" not in c["key"] for c in deep.month)  # 60 days ago is not the month
    month = _discover(
        TENANT, brand, now=NOW, repository=repo, fetch=fetch, review=_fits_all, api_key="k"
    )
    assert month.days == 30 and month.quarter == []
    assert walks[-1] == (NOW - 30 * DAY, sc.REEL_MAX_PAGES)
    with pytest.raises(ValueError):
        _discover(TENANT, brand, now=NOW, repository=repo, fetch=fetch, days=60)


def test_every_referente_has_its_top_reels_checked(store: Any) -> None:
    """A quiet referente's reels never make the brand-wide top, yet filtering to it must
    find them: each account's own most viewed go to the check too."""
    repo, brand = store
    big = [_reel("foodie", f"B{n}", 1, 100_000 + n, "burger") for n in range(40)]
    small = [
        {**_reel("vecino", f"S{n}", 2, 50 + n, "burger"), "network": "tiktok"} for n in range(5)
    ]
    checked: list[str] = []

    def review(brief: Any, reels: list[ReelToReview], **kw: Any) -> tuple[list, CallStats]:
        checked.extend(r.id for r in reels)
        return _fits_all(brief, reels, **kw)

    result = _discover(
        TENANT,
        brand,
        now=NOW,
        repository=repo,
        fetch=lambda network, handle, **_: big if handle == "foodie" else small,
        review=review,
        api_key="k",
    )
    small_keys = {k for k in checked if k.startswith("tiktok:")}
    assert small_keys == {"tiktok:S4", "tiktok:S3", "tiktok:S2"}  # its 3 most viewed
    assert len(checked) == rd.REVIEWED_PER_WINDOW + 3  # the brand top, plus the quiet one's
    # every kept reel is handed over (the view cuts after filtering), with its account
    assert len(result.month) == rd.REVIEWED_PER_WINDOW + 3 > rd.SHOWN_PER_WINDOW
    assert {c["account"] for c in result.month} == {"instagram:foodie", "tiktok:vecino"}
    assert result.accounts == [
        {"key": "instagram:foodie", "network": "instagram", "handle": "@foodie"},
        {"key": "tiktok:vecino", "network": "tiktok", "handle": "@vecino"},
    ]


def test_the_90_day_read_is_remembered_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rd, "_cache", {})
    monkeypatch.setattr(rd, "_brand_locks", {})
    monkeypatch.setattr(rd, "_reads", {})
    reads: list[int] = []

    def fake(tenant_id: UUID, brand_id: UUID, *, days: int, **_: Any) -> rd.DiscoveredReels:
        reads.append(days)
        return rd.DiscoveredReels(fetched_at=time.time(), days=days)

    monkeypatch.setattr(rd, "discover", fake)
    assert rd.remembered(TENANT, TENANT, days=rd.QUARTER_DAYS) is None  # nothing paid yet
    deep = rd.cached_discover(TENANT, TENANT, days=rd.QUARTER_DAYS)
    assert rd.cached_discover(TENANT, TENANT, days=rd.QUARTER_DAYS) is deep  # cached
    rd.cached_discover(TENANT, TENANT, refresh=True)  # «Actualizar» on the week…
    assert reads == [90, 30]
    assert rd.remembered(TENANT, TENANT, days=rd.QUARTER_DAYS) is deep  # …keeps the 90 days
    deep.fetched_at -= rd.CACHE_TTL_SECONDS + 1
    assert rd.remembered(TENANT, TENANT, days=rd.QUARTER_DAYS) is None  # stale


def test_two_reads_pay_one_transcript_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """The month and the 90-day reads may run at once: the second to ask for the same
    Instagram reel waits for the first instead of paying the vendor again."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    monkeypatch.setattr(rd, "_transcripts", {})
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def slow(reel: dict, client: Any) -> str:
        calls.append(reel["id"])
        started.set()
        release.wait(5)
        return "dice algo"

    def read() -> tuple[int, int]:
        return rd.transcribe([_reel("foodie", "R0", 1, 100, "x")], fetch=slow)

    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(read)
        started.wait(5)
        second = pool.submit(read)
        release.set()
        results = {first.result(timeout=5), second.result(timeout=5)}
    assert calls == ["R0"]  # paid once
    assert results == {(1, 1), (0, 0)}  # the waiting read paid nothing
    assert rd._transcripts == {"instagram:R0": "dice algo"} and rd._transcripts_inflight == {}


def test_a_reel_judged_before_is_not_paid_for_again() -> None:
    """The 90-day read (or «Actualizar») does not ask Claude again about a reel it
    already judged against the same brief — unless what the model would read changed."""
    brief = BRIEF
    asked: list[list[str]] = []

    def review(brief: Any, reels: list[ReelToReview], **kw: Any) -> tuple[list, CallStats]:
        asked.append([r.id for r in reels])
        return _fits_all(brief, reels, **kw)

    reels = [_reel("foodie", "A", 1, 10, "burger"), _reel("foodie", "B", 2, 9, "burger")]
    first = rd.check_rubro(brief, reels, api_key="k", review=review)
    again = rd.check_rubro(brief, reels, api_key="k", review=review)
    assert asked == [["instagram:A", "instagram:B"]] and again == first  # no second call
    heard = [{**reels[0], "transcript": "ahora sí se oye"}, reels[1]]
    rd.check_rubro(brief, heard, api_key="k", review=review)
    assert asked[-1] == ["instagram:A"]  # a new transcript is a new question

    def broken(*_: Any, **__: Any) -> Any:
        raise RuntimeError("down")

    # the model is down: what was judged before still stands, the new reel is unchecked
    mixed = rd.check_rubro(
        brief, [*reels, _reel("foodie", "C", 1, 8, "burger")], api_key="k", review=broken
    )
    assert set(mixed) == {"instagram:A", "instagram:B"}
    with pytest.raises(rd.ReelCheckUnavailable):
        rd.check_rubro(brief, [_reel("foodie", "D", 1, 7, "x")], api_key="k", review=broken)


def test_only_the_widest_window_adds_each_accounts_top(store: Any) -> None:
    """The per-account extras are paid once per read, on its widest window — not once
    per tab."""
    week_only_quiet = [
        *(_reel("foodie", f"B{n}", 1, 100_000 + n, "burger") for n in range(40)),
        *(
            {**_reel("vecino", f"S{n}", 20, 50 + n, "burger"), "network": "tiktok"}
            for n in range(5)
        ),
    ]
    picked = rd._candidates(week_only_quiet, NOW - 7 * DAY, per_account=False)
    assert len(picked) == rd.REVIEWED_PER_WINDOW
    wide = rd._candidates(week_only_quiet, NOW - 30 * DAY, per_account=True)
    assert {r["id"] for r in wide if r["handle"] == "vecino"} == {"S4", "S3", "S2"}
