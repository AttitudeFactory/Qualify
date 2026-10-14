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

import json
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


# Meta's throttling codes (Graph API "Rate Limiting"): 4 app, 17 user, 32 page, 613 custom,
# 80001/80002 Business Use Case (80002 is Instagram's). Instagram endpoints count against a
# rolling 24 h budget of 4800 calls x impressions per app/account pair
# (`instagram-platform/overview.md` §Rate Limiting).
_RATE_LIMIT_CODES = frozenset({4, 17, 32, 613, 80001, 80002})
# 1 "unknown error" and 2 "service temporarily unavailable": worth one more try.
_TRANSIENT_CODES = frozenset({1, 2})


def is_rate_limited(exc: MentionedContentReadError) -> bool:
    """Meta is throttling this app/account: stop calling, do not retry now."""
    return exc.http_status == 429 or exc.platform_code in _RATE_LIMIT_CODES


def is_transient(exc: MentionedContentReadError) -> bool:
    """A failure a later attempt may not repeat (server side). A 4xx about the content
    itself — deleted, comments disabled, no permission — is not, and neither is a 200 whose
    body did not match the contract (`http_status=None`): asking again returns the same."""
    if is_rate_limited(exc):
        return False
    status = exc.http_status
    return (status is not None and status >= 500) or exc.platform_code in _TRANSIENT_CODES


def usage_percent(headers: httpx.Headers) -> int:
    """The highest usage Meta reports for this app (`X-App-Usage`) or this account's
    Business Use Case budget (`X-Business-Use-Case-Usage`), 0-100. Unreadable or absent
    headers read as 0 — they inform the pacing, they never fail a read."""
    values: list[int] = []
    for name in ("x-app-usage", "x-business-use-case-usage"):
        raw = headers.get(name)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except ValueError:
            continue
        entries = [parsed] if name == "x-app-usage" else _buc_entries(parsed)
        for entry in entries:
            if isinstance(entry, dict):
                for key in ("call_count", "total_cputime", "total_time"):
                    value = entry.get(key)
                    if isinstance(value, int | float) and not isinstance(value, bool):
                        values.append(int(value))
    return max(values, default=0)


def _buc_entries(parsed: object) -> list[object]:
    if not isinstance(parsed, dict):
        return []
    return [entry for group in parsed.values() if isinstance(group, list) for entry in group]


class MentionedContentClient(Protocol):
    async def get_mentioned_media(self, *, ig_user_id: str, media_id: str) -> MentionedMedia: ...

    async def get_mentioned_comment(
        self, *, ig_user_id: str, comment_id: str
    ) -> MentionedComment: ...

    async def get_mentioned_permalink(
        self, *, ig_user_id: str, media_id: str, comment_id: str | None
    ) -> str | None: ...


# QUA-152: the "Ver" link. `permalink` is a Public IG Media field but is NOT in the
# `mentioned_media`/`mentioned_comment` field tables, so it is read by its OWN call — a
# refusal here can never break the content read above. [VERIFIED LIVE 2026-10-13 by the
# founder in production: the link opens the mentioned publication.] Only an https link on
# instagram.com is accepted: it is opened in the user's browser.
_PERMALINK_HOSTS = ("https://www.instagram.com/", "https://instagram.com/")


def safe_permalink(value: object) -> str | None:
    if isinstance(value, str) and value.startswith(_PERMALINK_HOSTS):
        return value
    return None


def _parse_permalink_response(payload: dict[str, Any], *, comment: bool) -> str | None:
    if comment:
        inner = payload.get("mentioned_comment")
        media = inner.get("media") if isinstance(inner, dict) else None
        return safe_permalink(media.get("permalink")) if isinstance(media, dict) else None
    inner = payload.get("mentioned_media")
    return safe_permalink(inner.get("permalink")) if isinstance(inner, dict) else None


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
        # The highest usage Meta reported on the last response (QUA-152): a refresh run
        # stops dispatching new reads when it gets close to the limit.
        self.usage_percent = 0

    async def aclose(self) -> None:
        """Close the underlying HTTP client (its connection pool). Callers own the
        lifecycle: an unclosed client keeps sockets open until garbage collection."""
        close = getattr(self._graph, "aclose", None)
        if close is not None:
            await close()

    async def _get(self, ig_user_id: str, fields_expr: str) -> dict[str, Any]:
        response = await self._graph.get(
            f"{self._graph_url}/{ig_user_id}", params={"fields": fields_expr}
        )
        self.usage_percent = usage_percent(response.headers)
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

    async def get_mentioned_permalink(
        self, *, ig_user_id: str, media_id: str, comment_id: str | None
    ) -> str | None:
        """The media's permalink (for a comment mention: the media the comment is on), or
        None when Meta omits it. Raises `MentionedContentReadError` on a refused call."""
        if comment_id is not None:
            fields_expr = f"mentioned_comment.comment_id({comment_id}){{media{{permalink}}}}"
        else:
            fields_expr = f"mentioned_media.media_id({media_id}){{permalink}}"
        payload = await self._get(ig_user_id, fields_expr)
        return _parse_permalink_response(payload, comment=comment_id is not None)
