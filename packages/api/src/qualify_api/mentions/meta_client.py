"""The `mentioned_media`/`mentioned_comment` read seam (QUA-49) — same shape as every
other Meta client in this codebase (`inbox/client.py`, `inbox/media_client.py`,
`publishing/client.py`): a `Protocol`, a real HTTP implementation, one `_parse_*`
function per endpoint, the credential arriving pre-authenticated via
`AuthenticatedClient` so this module never sees a token.

## Why this exists and what it is NOT

`resolve_external_account` only ever produces IDs (`media_id`/`comment_id`). To show a
human anything (caption, author, likes, date) for a mention on content the connected
account does NOT own, Meta requires going through these two special nodes —
`GET /{ig-comment-id}` is explicitly refused for a comment "discovered through the
Mentions API" unless the requester owns it (`ig-comment.md:39`). This module is that
one sanctioned bypass, nothing else.

**No `views`/`plays` field is requested or modeled anywhere here.** `mentioned_media.md`'s
entire Fields table carries no such field for any media type — view-count metrics are an
Insights concept scoped to media the app user owns, and a mention lives on content the
account does NOT own by definition. See
`qualify_shared.social.ig_shapes.MENTIONED_MEDIA_NO_VIEWS_CITATION`.

## `[UNVERIFIED LIVE]`

Unlike `inbox/client.py`'s `_parse_comments_response` (verified 2026-08-14 against a real
comment), neither `_parse_mentioned_media_response` nor `_parse_mentioned_comment_response`
below has ever been exercised against a real Meta response — Business Verification and
Advanced Access for `instagram_manage_comments` are still pending (external blocker, not a
code gap). Every field/shape here is fixed against the harvested corpus only. The first
real call this module makes must be logged as the observation that promotes it to
`[VERIFIED]`, same discipline `inbox/client.py`'s own history documents.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from qualify_shared.social.ig_shapes import (
    MENTIONED_COMMENT_FIELDS,
    MENTIONED_MEDIA_FIELDS,
    MentionedComment,
    MentionedMedia,
    parse_mentioned_comment,
    parse_mentioned_media,
)

from qualify_api.connections.resolver import AuthenticatedClient


class MentionedContentReadError(Exception):
    """A `mentioned_media`/`mentioned_comment` read failed. Never carries the token or the
    response body — same discipline as every sibling `*ReadError` in this package."""

    def __init__(
        self,
        message: str,
        *,
        platform_code: int | None = None,
        platform_subcode: int | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.platform_code = platform_code
        self.platform_subcode = platform_subcode
        self.http_status = http_status


class MentionedContentClient(Protocol):
    async def get_mentioned_media(self, *, ig_user_id: str, media_id: str) -> MentionedMedia: ...

    async def get_mentioned_comment(
        self, *, ig_user_id: str, comment_id: str
    ) -> MentionedComment: ...


# --- response parsing. One function per endpoint; the only place reality lands. ---


def _error_codes(response: httpx.Response) -> tuple[int | None, int | None]:
    """Duplicated from the sibling clients rather than imported — each client module is
    self-contained, same discipline `inbox/client.py`'s `_error_codes` already follows."""
    try:
        error = dict(response.json()).get("error")
    except ValueError:
        return None, None
    if not isinstance(error, dict):
        return None, None
    code = error.get("code")
    subcode = error.get("error_subcode")
    return (
        code if isinstance(code, int) else None,
        subcode if isinstance(subcode, int) else None,
    )


def _parse_mentioned_media_response(payload: dict[str, Any]) -> MentionedMedia:
    """[UNVERIFIED LIVE] `{"mentioned_media": {...}, "id": "<ig-user-id>"}`
    (`mentioned_media.md:71-79`). Delegates entirely to
    `qualify_shared.social.ig_shapes.parse_mentioned_media`."""
    inner = payload.get("mentioned_media")
    if not isinstance(inner, dict):
        raise MentionedContentReadError("response carried no mentioned_media object")
    try:
        return parse_mentioned_media(inner)
    except ValueError as exc:
        # Never interpolate the payload itself: a mention's caption/username is
        # user-generated content, same discipline `inbox.client`'s
        # `_parse_comments_response` already establishes for comment text.
        raise MentionedContentReadError(
            f"mentioned_media response did not match the contract ({type(exc).__name__})"
        ) from exc


def _parse_mentioned_comment_response(payload: dict[str, Any]) -> MentionedComment:
    """[UNVERIFIED LIVE] `{"mentioned_comment": {...}, "id": "<ig-user-id>"}`
    (`mentioned_comment.md:66-76`). Delegates entirely to
    `qualify_shared.social.ig_shapes.parse_mentioned_comment`."""
    inner = payload.get("mentioned_comment")
    if not isinstance(inner, dict):
        raise MentionedContentReadError("response carried no mentioned_comment object")
    try:
        return parse_mentioned_comment(inner)
    except ValueError as exc:
        raise MentionedContentReadError(
            f"mentioned_comment response did not match the contract ({type(exc).__name__})"
        ) from exc


class HttpMentionedContentClient:
    """Real client over one already-authenticated client — `graph.facebook.com` only,
    same posture as every sibling client in this package. Both endpoints are field
    expansions on the `ig-user-id` node itself (`GET /{ig-user-id}?fields=...`), not on
    the media/comment id directly — that asymmetry is Meta's, not this module's."""

    def __init__(self, *, graph_client: AuthenticatedClient, graph_url: str) -> None:
        self._graph = graph_client
        self._graph_url = graph_url.rstrip("/")

    async def _get(self, ig_user_id: str, fields_expr: str) -> dict[str, Any]:
        response = await self._graph.get(
            f"{self._graph_url}/{ig_user_id}", params={"fields": fields_expr}
        )
        if response.status_code != 200:
            code, subcode = _error_codes(response)
            raise MentionedContentReadError(
                f"GET /{ig_user_id} failed with HTTP {response.status_code}",
                platform_code=code,
                platform_subcode=subcode,
                http_status=response.status_code,
            )
        return dict(response.json())

    async def get_mentioned_media(self, *, ig_user_id: str, media_id: str) -> MentionedMedia:
        fields_expr = f"mentioned_media.media_id({media_id}){{{MENTIONED_MEDIA_FIELDS}}}"
        return _parse_mentioned_media_response(await self._get(ig_user_id, fields_expr))

    async def get_mentioned_comment(self, *, ig_user_id: str, comment_id: str) -> MentionedComment:
        fields_expr = f"mentioned_comment.comment_id({comment_id}){{{MENTIONED_COMMENT_FIELDS}}}"
        return _parse_mentioned_comment_response(await self._get(ig_user_id, fields_expr))
