"""The trend-audio client seam (QUA-106), fully offline. Every call is driven through
an `httpx.MockTransport`, same discipline `test_publishing_client.py` establishes —
the real `HttpTrendAudioClient` code path runs (URL, params, parsing), zero network.

Fixture payloads are trimmed, REAL shapes from the live validation call made against
the PuntoServis connection on 2026-09-19 (see the QUA-106 discovery notes) — not
invented from the (partially inaccurate) official doc.
"""

from __future__ import annotations

import httpx

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.stories.trend_audio_client import (
    HttpTrendAudioClient,
    TrendAudioError,
)

SETTINGS = MetaOAuthSettings(
    app_id="app", app_secret="secret", redirect_uri="https://x/cb", state_secret="s"
)
TOKEN = "SUPER_SECRET_TOKEN"
GRAPH = "https://graph.facebook.com/v21.0"
IG_USER = "17841448653847824"

# Trimmed real shape (music), 2026-09-19 live call.
_MUSIC_PAYLOAD = {
    "audio": [
        {
            "audio_id": "4339192396347225",
            "duration_in_ms": 63800,
            "title": "Flourishing",
            "display_artist": "Electrum Electra",
            "audio_type": "music",
            "download_url": "https://example.test/preview1.mp4",
        },
        {
            # [VERIFIED 2026-09-19] ig_username DOES appear on a `music` item in
            # practice — the doc's "original_sound only" claim does not hold.
            "audio_id": "1452787821915786",
            "duration_in_ms": 149532,
            "title": "Touch The Sky",
            "display_artist": "Giulio Cercato",
            "audio_type": "music",
            "download_url": "https://example.test/preview2.mp4",
            "ig_username": "giuliocercato",
        },
    ],
    "paging": {"cursors": {"after": "MjUZD"}},
}

# Trimmed real shape (original_sound), 2026-09-19 live call — often untitled.
_ORIGINAL_SOUND_PAYLOAD = {
    "audio": [
        {
            "audio_id": "1334830810538413",
            "duration_in_ms": 59256,
            "title": "Audio original",
            "audio_type": "original_sound",
            "download_url": "https://example.test/preview3.mp4",
            "ig_username": "hana.effron",
        }
    ],
    "paging": {"cursors": {"after": "cursor2"}},
}


def _client(handler) -> HttpTrendAudioClient:
    transport = httpx.MockTransport(handler)
    return HttpTrendAudioClient(
        graph_client=_InjectedAuthClient(
            TOKEN, scheme=SETTINGS.graph_auth_scheme, transport=transport
        ),
        graph_url=GRAPH,
    )


def _json(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


async def test_trending_audio_sends_audio_type_and_user_id_with_no_search_query() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params))
        assert request.url.path.endswith("/ig_audio")
        return _json(_MUSIC_PAYLOAD)

    await _client(handler).trending_audio(ig_user_id=IG_USER, audio_type="music")

    assert seen == {"audio_type": "music", "user_id": IG_USER}
    assert "search_query" not in seen


async def test_parses_music_items_including_ig_username_when_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(_MUSIC_PAYLOAD)

    options = await _client(handler).trending_audio(ig_user_id=IG_USER, audio_type="music")

    assert len(options) == 2
    assert options[0].audio_id == "4339192396347225"
    assert options[0].title == "Flourishing"
    assert options[0].artist_or_creator == "Electrum Electra"
    assert options[0].rank == 0
    assert options[0].preview_url == "https://example.test/preview1.mp4"
    # This item has BOTH display_artist and ig_username — display_artist wins.
    assert options[1].artist_or_creator == "Giulio Cercato"
    assert options[1].rank == 1


async def test_parses_original_sound_items_using_ig_username_as_creator() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(_ORIGINAL_SOUND_PAYLOAD)

    options = await _client(handler).trending_audio(ig_user_id=IG_USER, audio_type="original_sound")

    assert len(options) == 1
    assert options[0].title == "Audio original"
    assert options[0].artist_or_creator == "hana.effron"
    assert options[0].audio_type == "original_sound"
    assert options[0].preview_url == "https://example.test/preview3.mp4"


async def test_preview_url_is_empty_when_the_vendor_omits_download_url() -> None:
    """ "May be null when no preview URL is available" (audio-api.md) — an absent
    preview must never be fabricated, just an empty string, same posture every
    other optional field on this dataclass already has."""
    payload = {
        "audio": [
            {"audio_id": "1", "title": "No preview", "audio_type": "music"},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return _json(payload)

    options = await _client(handler).trending_audio(ig_user_id=IG_USER, audio_type="music")

    assert options[0].preview_url == ""


async def test_missing_audio_list_raises_trend_audio_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"not_audio": []})

    try:
        await _client(handler).trending_audio(ig_user_id=IG_USER, audio_type="music")
    except TrendAudioError:
        pass
    else:
        raise AssertionError("expected TrendAudioError")


async def test_a_malformed_item_is_skipped_not_fatal_to_the_rest() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"audio": [{"title": "no id here"}, _MUSIC_PAYLOAD["audio"][0]]})

    options = await _client(handler).trending_audio(ig_user_id=IG_USER, audio_type="music")

    assert len(options) == 1
    assert options[0].audio_id == "4339192396347225"
    # rank reflects its ORIGINAL position in the response, not its position among
    # survivors — the malformed item at index 0 is dropped, this one stays index 1.
    assert options[0].rank == 1


async def test_non_200_raises_trend_audio_error_with_platform_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 100, "message": "bad request"}})

    try:
        await _client(handler).trending_audio(ig_user_id=IG_USER, audio_type="music")
    except TrendAudioError as exc:
        assert exc.platform_code == 100
        assert exc.http_status == 400
    else:
        raise AssertionError("expected TrendAudioError")
