"""The comments read client seam (B1), fully offline.

Same posture as `test_publishing_client.py`: every call is driven through an
`httpx.MockTransport` over the REAL `_InjectedAuthClient`, so the real `HttpCommentsClient`
code path runs end to end — URL, params, headers, parsing — with zero network.

Fixture data is SYNTHETIC, not the real comment observed live on 2026-08-14
(`@qualifymkt.co`, media `18034792133641940`) — same convention as
`tests/fixtures/synthetic_ig_comments.json`: a real, identifiable person's comment does
not get committed to the repo. The shape is real; the words and the person are not.
"""

from __future__ import annotations

import httpx
import pytest
from qualify_shared.social.ig_shapes import UNSUPPORTED_FIELDS

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.inbox.client import (
    COMMENT_FIELDS,
    CommentsReadError,
    HttpCommentsClient,
    _parse_comments_response,
)

SETTINGS = MetaOAuthSettings(
    app_id="app", app_secret="secret", redirect_uri="https://x/cb", state_secret="s"
)
GRAPH_AUTH_SCHEME = SETTINGS.graph_auth_scheme

TOKEN = "SUPER_SECRET_COMMENTS_TOKEN"
GRAPH = "https://graph.facebook.com/v21.0"
MEDIA_ID = "18000000000000001"

SYNTHETIC_COMMENT = {
    "id": "18100000000000001",
    "text": "synthetic comment for the offline suite",
    "timestamp": "2026-08-01T12:00:00+0000",
    "from": {"id": "1000000000000001", "username": "synthetic_user"},
    "username": "synthetic_user",
    "hidden": False,
    "like_count": 2,
    "media": {"id": MEDIA_ID},
}


def _client(handler) -> HttpCommentsClient:
    """Drives the REAL credential-injection path, exactly as
    `CredentialResolver.client_for(..., scheme=...)` would return it."""
    transport = httpx.MockTransport(handler)
    return HttpCommentsClient(
        graph_client=_InjectedAuthClient(TOKEN, scheme=GRAPH_AUTH_SCHEME, transport=transport),
        graph_url=GRAPH,
    )


def _json(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


# --------------------------------------------------------------------------------------
# list_comments — happy paths
# --------------------------------------------------------------------------------------


async def test_list_comments_parses_a_real_shaped_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(f"/{MEDIA_ID}/comments")
        return _json({"data": [SYNTHETIC_COMMENT]})

    page = await _client(handler).list_comments(ig_media_id=MEDIA_ID)
    assert len(page.data) == 1
    comment = page.data[0]
    assert comment.id == "18100000000000001"
    assert comment.text == "synthetic comment for the offline suite"
    assert comment.from_.username == "synthetic_user"
    assert comment.username == "synthetic_user"
    assert comment.hidden is False
    assert comment.like_count == 2
    assert comment.media.id == MEDIA_ID
    assert comment.parent_id is None
    assert comment.replies is None


async def test_list_comments_empty_page_is_observed_zero_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"data": []})

    page = await _client(handler).list_comments(ig_media_id=MEDIA_ID)
    assert page.data == []
    assert page.paging is None


async def test_list_comments_surfaces_paging_when_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"data": [], "paging": {"cursors": {"after": "NEXT_CURSOR"}}})

    page = await _client(handler).list_comments(ig_media_id=MEDIA_ID)
    assert page.paging == {"cursors": {"after": "NEXT_CURSOR"}}


# --------------------------------------------------------------------------------------
# request shape
# --------------------------------------------------------------------------------------


async def test_requests_exactly_the_verified_field_list() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["fields"] = request.url.params["fields"]
        return _json({"data": []})

    await _client(handler).list_comments(ig_media_id=MEDIA_ID)
    assert seen["fields"] == COMMENT_FIELDS


def test_unsupported_fields_are_never_in_the_requested_field_list() -> None:
    requested = set(COMMENT_FIELDS.split(","))
    assert requested.isdisjoint(UNSUPPORTED_FIELDS.keys())


async def test_after_cursor_is_forwarded_when_given() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["after"] = request.url.params.get("after", "")
        return _json({"data": []})

    await _client(handler).list_comments(ig_media_id=MEDIA_ID, after="SOME_CURSOR")
    assert seen["after"] == "SOME_CURSOR"


async def test_after_cursor_is_absent_when_not_given() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "after" not in request.url.params
        return _json({"data": []})

    await _client(handler).list_comments(ig_media_id=MEDIA_ID)


async def test_uses_the_bearer_scheme_on_graph() -> None:
    """`comment-moderation.md:17` / R12 — the comments edge is a graph.facebook.com read,
    Bearer throughout."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        return _json({"data": []})

    await _client(handler).list_comments(ig_media_id=MEDIA_ID)
    assert seen["auth"] == f"{GRAPH_AUTH_SCHEME} {TOKEN}"


# --------------------------------------------------------------------------------------
# errors — status/code only, never a body, never the token
# --------------------------------------------------------------------------------------


async def test_non_200_raises_with_status_and_platform_codes_only() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "error": {
                    "message": f"leaking {TOKEN} would be a bug",
                    "code": 10,
                    "error_subcode": 2108006,
                }
            },
            status=403,
        )

    with pytest.raises(CommentsReadError) as exc_info:
        await _client(handler).list_comments(ig_media_id=MEDIA_ID)

    exc = exc_info.value
    assert "403" in str(exc)
    assert TOKEN not in str(exc)
    assert exc.platform_code == 10
    assert exc.platform_subcode == 2108006


async def test_non_200_with_unparseable_body_still_raises_cleanly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="not json")

    with pytest.raises(CommentsReadError) as exc_info:
        await _client(handler).list_comments(ig_media_id=MEDIA_ID)

    assert exc_info.value.platform_code is None
    assert exc_info.value.platform_subcode is None


# --------------------------------------------------------------------------------------
# contract violations funnel through CommentsReadError, not a raw pydantic error
# --------------------------------------------------------------------------------------


def test_parse_rejects_a_payload_whose_data_is_not_a_list() -> None:
    with pytest.raises(CommentsReadError):
        _parse_comments_response({"data": "not-a-list"})


def test_parse_rejects_an_unsupported_field_even_if_meta_ever_sent_one() -> None:
    with pytest.raises(CommentsReadError):
        _parse_comments_response({"data": [{"id": "1", "comment_type": "should not exist"}]})


def test_a_validation_error_never_leaks_comment_content_into_the_error_message() -> None:
    """Confirmed empirically (not assumed) that pydantic's `ValidationError.__str__()`
    echoes the offending `input_value` verbatim. This payload fails validation
    (`like_count` must be an int) with a marker standing in for real, identifiable
    comment content — text/a username that must never end up in a log. `from exc` is
    deliberately kept (the original ValidationError still carries the marker on
    `__cause__`, for a developer reading a traceback) — only `CommentsReadError`'s own
    message/str() must be clean, which is the part a log line usually captures.
    """
    marker = "SENSITIVE_COMMENT_CONTENT_MUST_NOT_LEAK"
    payload = {"data": [{"id": "1", "like_count": marker}]}

    with pytest.raises(CommentsReadError) as exc_info:
        _parse_comments_response(payload)

    exc = exc_info.value
    assert marker not in str(exc)
    assert "ValidationError" in str(exc)
    # The marker DOES still exist on the original cause — that is the intended tradeoff,
    # not a gap: local debugging keeps the detail, CommentsReadError's own message does not.
    assert marker in str(exc.__cause__)
