"""The media-listing client seam, fully offline. Same posture as
`test_inbox_client.py`/`test_publishing_client.py`: `httpx.MockTransport` over the REAL
`_InjectedAuthClient`.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.inbox.media_client import (
    MEDIA_FIELDS,
    HttpMediaClient,
    MediaReadError,
    _parse_media_summary,
)

SETTINGS = MetaOAuthSettings(
    app_id="app", app_secret="secret", redirect_uri="https://x/cb", state_secret="s"
)
GRAPH_AUTH_SCHEME = SETTINGS.graph_auth_scheme

TOKEN = "SUPER_SECRET_MEDIA_TOKEN"
GRAPH = "https://graph.facebook.com/v21.0"
IG_USER = "17841400000000000"
MEDIA_ID = "18000000000000002"


def _client(handler) -> HttpMediaClient:
    transport = httpx.MockTransport(handler)
    return HttpMediaClient(
        graph_client=_InjectedAuthClient(TOKEN, scheme=GRAPH_AUTH_SCHEME, transport=transport),
        graph_url=GRAPH,
    )


def _json(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


# --------------------------------------------------------------------------------------
# list_recent_media
# --------------------------------------------------------------------------------------


async def test_list_recent_media_sends_since_as_a_unix_timestamp() -> None:
    seen: dict[str, str] = {}
    since = datetime(2026, 8, 1, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/{IG_USER}/media")
        seen["since"] = request.url.params["since"]
        seen["fields"] = request.url.params["fields"]
        return _json({"data": []})

    await _client(handler).list_recent_media(ig_user_id=IG_USER, since=since)
    assert seen["since"] == str(int(since.timestamp()))
    assert seen["fields"] == MEDIA_FIELDS


async def test_list_recent_media_parses_the_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"data": [{"id": "1", "timestamp": "2026-08-10T12:00:00+0000"}]})

    results = await _client(handler).list_recent_media(ig_user_id=IG_USER, since=datetime.now(UTC))
    assert len(results) == 1
    assert results[0].id == "1"
    assert results[0].timestamp == datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


async def test_list_recent_media_follows_the_cursor_across_pages() -> None:
    calls: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if "after" not in request.url.params:
            return _json(
                {
                    "data": [{"id": "1", "timestamp": "2026-08-10T12:00:00+0000"}],
                    "paging": {"cursors": {"after": "CURSOR_1"}},
                }
            )
        return _json({"data": [{"id": "2", "timestamp": "2026-08-09T12:00:00+0000"}]})

    results = await _client(handler).list_recent_media(ig_user_id=IG_USER, since=datetime.now(UTC))
    assert [m.id for m in results] == ["1", "2"]
    assert len(calls) == 2
    assert calls[1]["after"] == "CURSOR_1"


async def test_list_recent_media_stops_without_a_cursor() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json({"data": [{"id": "1", "timestamp": "2026-08-10T12:00:00+0000"}]})

    await _client(handler).list_recent_media(ig_user_id=IG_USER, since=datetime.now(UTC))
    assert calls == 1


# --------------------------------------------------------------------------------------
# get_media
# --------------------------------------------------------------------------------------


async def test_get_media_needs_no_ig_user_id_in_the_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/{MEDIA_ID}")
        assert IG_USER not in str(request.url)
        return _json({"id": MEDIA_ID, "timestamp": "2026-08-10T12:00:00+0000"})

    media = await _client(handler).get_media(media_id=MEDIA_ID)
    assert media.id == MEDIA_ID
    assert media.timestamp == datetime(2026, 8, 10, 12, 0, 0, tzinfo=UTC)


async def test_uses_the_bearer_scheme_on_graph() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        return _json({"id": MEDIA_ID, "timestamp": "2026-08-10T12:00:00+0000"})

    await _client(handler).get_media(media_id=MEDIA_ID)
    assert seen["auth"] == f"{GRAPH_AUTH_SCHEME} {TOKEN}"


# --------------------------------------------------------------------------------------
# errors — status/code only, never a body, never the token
# --------------------------------------------------------------------------------------


async def test_non_200_raises_with_status_and_platform_codes_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {"error": {"message": f"leaking {TOKEN}", "code": 100, "error_subcode": 33}},
            status=404,
        )

    with pytest.raises(MediaReadError) as exc_info:
        await _client(handler).get_media(media_id=MEDIA_ID)

    exc = exc_info.value
    assert "404" in str(exc)
    assert TOKEN not in str(exc)
    assert exc.platform_code == 100
    assert exc.platform_subcode == 33


def test_parse_rejects_a_payload_missing_the_timestamp() -> None:
    with pytest.raises(MediaReadError):
        _parse_media_summary({"id": MEDIA_ID})


def test_parse_rejects_a_payload_missing_the_id() -> None:
    with pytest.raises(MediaReadError):
        _parse_media_summary({"timestamp": "2026-08-10T12:00:00+0000"})
