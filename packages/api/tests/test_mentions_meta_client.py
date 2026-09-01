"""The `mentioned_media`/`mentioned_comment` client seam (QUA-49), fully offline. Same
posture as `test_inbox_media_client.py`/`test_inbox_client.py`: `httpx.MockTransport` over
the REAL `_InjectedAuthClient` — no network, no real Meta call (these endpoints are
`[UNVERIFIED LIVE]`, see `meta_client.py`'s module docstring), just the documented shape.
"""

from __future__ import annotations

import httpx

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.mentions.meta_client import (
    HttpMentionedContentClient,
    MentionedContentReadError,
)

SETTINGS = MetaOAuthSettings(
    app_id="app", app_secret="secret", redirect_uri="https://x/cb", state_secret="s"
)
GRAPH_AUTH_SCHEME = SETTINGS.graph_auth_scheme

TOKEN = "SUPER_SECRET_CONTENT_TOKEN"
GRAPH = "https://graph.facebook.com/v21.0"
IG_USER = "17841400000000000"


def _client(handler) -> HttpMentionedContentClient:
    transport = httpx.MockTransport(handler)
    return HttpMentionedContentClient(
        graph_client=_InjectedAuthClient(TOKEN, scheme=GRAPH_AUTH_SCHEME, transport=transport),
        graph_url=GRAPH,
    )


def _json(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


# --------------------------------------------------------------------------------------
# get_mentioned_media
# --------------------------------------------------------------------------------------


async def test_get_mentioned_media_queries_the_ig_user_node_with_field_expansion() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/{IG_USER}")
        seen["fields"] = request.url.params["fields"]
        return _json(
            {
                "mentioned_media": {
                    "id": "media-1",
                    "caption": "hola @qualifymkt.co",
                    "media_type": "IMAGE",
                    "like_count": 5,
                    "timestamp": "2026-08-01T00:00:00+0000",
                    "username": "someone",
                },
                "id": IG_USER,
            }
        )

    result = await _client(handler).get_mentioned_media(ig_user_id=IG_USER, media_id="media-1")

    assert "mentioned_media.media_id(media-1)" in seen["fields"]
    assert result.id == "media-1"
    assert result.caption == "hola @qualifymkt.co"
    assert result.like_count == 5


async def test_get_mentioned_media_missing_object_is_a_read_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"id": IG_USER})  # no "mentioned_media" key at all

    try:
        await _client(handler).get_mentioned_media(ig_user_id=IG_USER, media_id="media-1")
        raise AssertionError("expected MentionedContentReadError")
    except MentionedContentReadError:
        pass


async def test_get_mentioned_media_http_error_carries_no_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"error": {"code": 10, "error_subcode": 2108006}}, status=403)

    try:
        await _client(handler).get_mentioned_media(ig_user_id=IG_USER, media_id="media-1")
        raise AssertionError("expected MentionedContentReadError")
    except MentionedContentReadError as exc:
        assert exc.platform_code == 10
        assert exc.platform_subcode == 2108006
        assert exc.http_status == 403


# --------------------------------------------------------------------------------------
# get_mentioned_comment
# --------------------------------------------------------------------------------------


async def test_get_mentioned_comment_queries_the_ig_user_node_with_field_expansion() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["fields"] = request.url.params["fields"]
        return _json(
            {
                "mentioned_comment": {
                    "id": "comment-1",
                    "text": "Shout out to @qualifymkt.co",
                    "like_count": 12,
                    "timestamp": "2026-08-01T00:00:00+0000",
                },
                "id": IG_USER,
            }
        )

    result = await _client(handler).get_mentioned_comment(
        ig_user_id=IG_USER, comment_id="comment-1"
    )

    assert "mentioned_comment.comment_id(comment-1)" in seen["fields"]
    assert result.id == "comment-1"
    assert result.text == "Shout out to @qualifymkt.co"
    assert result.like_count == 12


async def test_get_mentioned_comment_missing_object_is_a_read_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"id": IG_USER})

    try:
        await _client(handler).get_mentioned_comment(ig_user_id=IG_USER, comment_id="comment-1")
        raise AssertionError("expected MentionedContentReadError")
    except MentionedContentReadError:
        pass


async def test_get_mentioned_comment_malformed_inner_object_never_echoes_the_body() -> None:
    """A `mentioned_comment` object missing its required `id` must fail as a
    `MentionedContentReadError` whose message never contains the raw payload (comment
    text is user-generated content) — same discipline `inbox.client`'s
    `_parse_comments_response` already establishes."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"mentioned_comment": {"text": "a very private complaint"}, "id": IG_USER})

    try:
        await _client(handler).get_mentioned_comment(ig_user_id=IG_USER, comment_id="comment-1")
        raise AssertionError("expected MentionedContentReadError")
    except MentionedContentReadError as exc:
        assert "a very private complaint" not in str(exc)
