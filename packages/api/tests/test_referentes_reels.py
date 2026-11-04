"""The reels service (`qualify_api.referentes.reels`) without the network: the vendor is
a `MockTransport` and the referentes store `MemoryReferentesRepository`. These pin whose
reels a brand follows (referentes only, the hand-added ones too unless the review said
they are another rubro), what a reel is (videos only, inside the window), which ones the
product check reads, the card the screen shows and what a failed check says.

The paid pipeline that read on every open — `discover`, its 6-hour memory and its
remembered verdicts and transcripts — was deleted by ADR 42 R7 (m-24854854): the
persistent run (`reel_runs`, its own tests) is the only door that pays now."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.referentes import (
    MemoryReferentesRepository,
    NewDiscoveredAccount,
    NewDiscoveryPhase,
)
from qualify_api.referentes import reels as rd
from qualify_api.referentes.reels_ai import ReelReview
from qualify_api.vendors import scrapecreators as sc

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
NOW = 1_800_000_000.0
DAY = 24 * 3600


def _cover(reel: dict[str, Any]) -> str:
    return f"/cover/{reel['network']}/{reel['id']}"


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


def test_the_in_process_read_and_its_memories_are_gone() -> None:
    """ADR 42 R7 (m-24854854): nothing here reads the vendor for the screen or remembers
    a read in the process — every deploy wiped that memory and every cold open paid."""
    for name in (
        "discover",
        "cached_discover",
        "remembered",
        "read_reels",
        "check_rubro",
        "transcribe",
        "transcript_for",
        "transcript_for_card",
        "CACHE_TTL_SECONDS",
        "_cache",
        "_verdicts",
        "_transcripts",
        "_transcripts_inflight",
    ):
        assert not hasattr(rd, name), name
    assert rd.view.__module__ == "qualify_api.referentes.reel_runs"  # the door that reads


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


def _plain(text: str) -> bool:
    """Spanish an owner reads: no digits (status codes), no question, no brackets."""
    return not any(ch.isdigit() for ch in text) and not set("?¿()[]") & set(text)


@pytest.mark.parametrize(
    ("name", "status", "message", "cause"),
    [
        ("NotFound", 404, "model gone", "the configured model is no longer available (404)"),
        ("Auth", 401, "bad key", "the model service rejected the key (401)"),
        ("Bad", 400, "Your credit balance is too low", "the model account has no credit balance"),
        ("Busy", 529, "Overloaded", "the model is overloaded or down (529)"),
        ("Boom", 500, "boom", "the model service failed (500)"),
        ("Quota", 429, "You exceeded your current quota", "the model's usage quota is exhausted"),
        ("APIConnectionError", None, "refused", "could not connect to the model service"),
        ("APITimeoutError", None, "slow", "the model service timed out"),
        ("KeyError", None, "x", "unexpected error (KeyError)"),
    ],
)
def test_the_screen_reason_is_one_plain_sentence_and_the_cause_is_the_logs(
    name: str, status: int | None, message: str, cause: str
) -> None:
    """m-24854854: `check_failure_reason` used to say «(429)» or «¿está encendido?» on
    screen; now every cause reads the same plain sentence, and `check_failure_cause`
    keeps why (with the code) for the log."""
    error = type(name, (Exception,), {"status_code": status})(message)
    reason = rd.check_failure_reason(error)
    assert reason == rd.CHECK_FAILED_TEXT and _plain(reason)
    # founder, 2026-11-04: a failed check retries by itself — said, never asked of the owner
    assert reason == "No pudimos revisar los videos ahora. Lo intentamos de nuevo en unos minutos."
    assert name not in reason and "IA" not in reason and "proveedor" not in reason
    assert rd.check_failure_cause(error).startswith(cause)


def test_compact_figures_round_before_choosing_the_unit() -> None:
    assert rd.compact(999_960) == "1M" and rd.compact(999_949) == "999.9K"
    assert rd.compact(1_260_000) == "1.3M" and rd.compact(0) == "0" and rd.compact(None) == "—"
    long_caption = "palabra " * 40
    card = rd.reel_card(_reel("foodie", "A", 1, 10, long_caption), 1, NOW)
    assert len(card["caption"]) == rd.CAPTION_CARD_CHARS and card["caption"].endswith("…")


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
