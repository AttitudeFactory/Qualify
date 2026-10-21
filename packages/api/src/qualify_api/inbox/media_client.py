"""The Instagram media-listing seam (monitored-media selection, groundwork for B2).

Same shape as `inbox/client.py`, `connections/meta_oauth.py` and `publishing/client.py`:
a `Protocol`, a real HTTP implementation, one `_parse_*` function per endpoint marked
`[V]`, and the credential arriving pre-authenticated via `AuthenticatedClient` — this
module never sees a token. Three endpoints, all on `graph.facebook.com`:

    GET /{ig-user-id}/media    — list_recent_media, for the "pick what to monitor" UI
    GET /{ig-user-id}/stories  — list_recent_stories, the same UI's stories (m-24789644)
    GET /{media-id}            — get_media, for validating a toggle request

Deliberately NOT in `inbox/client.py`: that module's own docstring states it has exactly
one endpoint (`/comments`); adding a second here would break an invariant already
committed and tested. Media listing and comment reading are different Meta edges with
different callers — same reasoning `publishing/client.py` and `connections/meta_oauth.py`
stay separate files despite both calling `graph.facebook.com`.

## `since` is Meta's own filter, not a client-side walk

Comments cannot be filtered by timestamp (`ig_shapes.COMMENT_LIMITS.filterable_by_timestamp
is False`) — that is what forces B1's pagination to walk pages and stop at a cursor. The
`/media` edge is different: it documents real **time-based pagination**, `since`/`until` as
Unix timestamps (`ig-user/media.md:384-386`). So the "only the last 2 weeks" rule is
enforced by asking Meta for exactly that window, not by fetching everything and filtering
client-side.

## `get_media`: toggle-time validation against Meta, and the QUA-149 metadata read

The product decision requires that activating monitoring on an old media is rejected — not
just hidden from the UI. Trusting a client-supplied timestamp, or a stored one, would mean
the rule holds only as long as nobody calls the toggle directly. `get_media` asks Meta
fresh at activation, addressed directly by id (`GET /{media-id}?fields=...` —
`instagram-media.md:125` — no `ig_user_id` needed in the path). `timestamp` is documented
`Public` on this node (`instagram-media.md:98`) — no `instagram_manage_comments` gate,
unlike a comment's `username`/`from`.

QUA-149: what `get_media` returns at activation is then persisted in `monitored_media`, so
the media stays readable — and can be judged expired — after it leaves Meta's 14-day
listing; the stored date is never what activation decides on. The same call reads that
metadata once for rows monitored before migration 0046.

## Fields added for the Reflex picker (2026-08-14, B2 UI slice)

`MEDIA_FIELDS` originally carried only `id,timestamp` — enough to decide the 2-week rule,
nothing to render. The picker UI needs to show a human something they can recognize, so
`media_product_type`, `caption`, `permalink` and `thumbnail_url` were added — all four
documented `Public` on `instagram-media.md:81,91,95,97` and all four already available
under the signed login fork (ADR 25), no new scope required. Deliberately still not here:
`media_url`, `like_count`, `comments_count`, `view_count` — none of them help identify
*which* piece of content a switch controls, which is the only job this field list has.

QUA-146 adds `media_type` (`instagram-media.md:92`, `Public`, same node, no new scope):
what the media IS (`IMAGE`/`VIDEO`/`CAROUSEL_ALBUM`), where `media_product_type` only says
where it lives. It rides on the same `GET` every read already makes — no extra call.
`children` is deliberately NOT requested: a carousel is monitored, and its comments
read, as the album itself (`GET /{album-id}/comments`), never per child.

QUA-146 also adds `media_url` (`instagram-media.md:93`, `Public`, same `GET`), reversing
the 2026-08-14 "not here" above for one reason: `thumbnail_url` exists ONLY on `VIDEO`
media (`instagram-media.md:97`), so without `media_url` a photo or a carousel — now
monitorable — has no picture to identify it by. It is used as a picture only for
`IMAGE`/`CAROUSEL_ALBUM` (for a `VIDEO` it is the video file); Meta omits it for media
flagged for copyright, which then falls back to the generic frame.

`media_product_type` also carries the monitorable-surface rule (same
"AD"/"FEED"/"STORY"/"REELS" vocabulary `instagram-media.md:91` documents; `REELS` and
`FEED` since QUA-146) — that filtering happens in `service.py`, next to the 2-week
window rule it sits beside, not here: this module stays a faithful mirror of what Meta
returns, same separation of concerns the module docstring above already draws between
this file and the window/eligibility rules.

## Stories live on their own edge (m-24789644)

`/media` never returns stories; `GET /{ig-user-id}/stories` (`ig-user/stories.md`) does —
the same IG Media nodes, `media_product_type == "STORY"`, so the same `MEDIA_FIELDS` and
the same parser apply. Its documented limits shape the call: only the last 24 hours
(Meta's own window — no `since` to send), no Live stories, no reshared stories. Its
documented permissions are `instagram_basic` + `pages_read_engagement` (plus `ads_read`/
`ads_management` when the Page role came through Business Manager) — a token without
them gets a `MediaReadError` like any other failed read. Only called while the
`story_comments` capability is on (`service.InboxService`, off by default).

## Token discipline

Same as every other client in this package: no token appears in this file, error messages
carry HTTP status and Meta's numeric `error.code`/`error.error_subcode` only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Protocol

import httpx
from qualify_shared.social.ig_shapes import parse_meta_timestamp

from qualify_api.connections.resolver import AuthenticatedClient

# `id,timestamp` decide the toggle/sync flow; the rest identify the content for a human
# picking what to monitor (see the module docstring's "Fields added for the Reflex
# picker" section for why exactly these four and no more). `media_type` (QUA-146) is
# what the media IS — see "QUA-146 adds `media_type`" in the module docstring.
MEDIA_FIELDS: Final = (
    "id,timestamp,media_product_type,media_type,caption,permalink,thumbnail_url,media_url"
)


@dataclass(frozen=True)
class MediaSummary:
    """One IG Media object, reduced to what monitoring needs to decide anything plus what
    a picker UI needs to identify it. The four new fields are all optional: `get_media`'s
    fixture payloads and `list_recent_media`'s pre-2026-08-14 tests never carried them,
    and a real Meta response can still omit `thumbnail_url` (video-only) or `caption`
    (none set) — `None` there is a legitimate value, not a parse failure.
    """

    id: str
    timestamp: datetime
    media_product_type: str | None = None
    caption: str | None = None
    permalink: str | None = None
    thumbnail_url: str | None = None
    # QUA-146: `IMAGE`/`VIDEO`/`CAROUSEL_ALBUM` per `instagram-media.md:92` — carried
    # verbatim, an unknown value included (interpreted only by `inbox.media_type`).
    media_type: str | None = None
    # QUA-146: the image itself for IMAGE/CAROUSEL_ALBUM (the video file for VIDEO) —
    # see "QUA-146 also adds `media_url`" in the module docstring.
    media_url: str | None = None


class MediaReadError(Exception):
    """A media-read call failed. Never carries the token or the response body — same
    discipline as `inbox.client.CommentsReadError`."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        platform_code: int | None = None,
        platform_subcode: int | None = None,
    ) -> None:
        super().__init__(message)
        # QUA-149: the status is what separates a confirmed deletion (HTTP 400 + code
        # 100/subcode 33, same signature `inbox.client.CommentsReadError` carries) from a
        # rate limit or a server error. `None` for a malformed 200 response.
        self.http_status = http_status
        self.platform_code = platform_code
        self.platform_subcode = platform_subcode


class MediaClient(Protocol):
    async def list_recent_media(
        self, *, ig_user_id: str, since: datetime
    ) -> tuple[MediaSummary, ...]: ...

    async def get_media(self, *, media_id: str) -> MediaSummary: ...

    async def list_recent_stories(self, *, ig_user_id: str) -> tuple[MediaSummary, ...]: ...


# --- [V] response parsing. One function per endpoint; the only place reality lands. ---


def _error_codes(response: httpx.Response) -> tuple[int | None, int | None]:
    """Duplicated from the sibling clients rather than imported — each client module is
    self-contained, the same discipline `meta_oauth.py`/`publishing/client.py`/
    `inbox/client.py` already follow independently of each other."""
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


def _optional_str(payload: dict[str, Any], field: str) -> str | None:
    """A `Public` field Meta may legitimately omit (no caption set, non-video media, an
    older API version). Anything present but not a non-empty string is treated the same
    as absent — never a parse failure over a rendering-only field."""
    value = payload.get(field)
    return value if isinstance(value, str) and value else None


def _parse_media_summary(payload: dict[str, Any]) -> MediaSummary:
    """[V] `instagram-media.md:81,91,95,97,98,125,138`: `{"id": ..., "timestamp":
    "2019-...+0000", "media_product_type": "REELS", "caption": ..., "permalink": ...,
    "thumbnail_url": ...}`. Only `id`/`timestamp` are required — the rest are display
    fields and missing means "not shown", not "malformed"."""
    media_id = payload.get("id")
    raw_timestamp = payload.get("timestamp")
    if not isinstance(media_id, str) or not media_id:
        raise MediaReadError("media response carried no id")
    if not isinstance(raw_timestamp, str) or not raw_timestamp:
        raise MediaReadError("media response carried no timestamp")
    return MediaSummary(
        id=media_id,
        timestamp=parse_meta_timestamp(raw_timestamp),
        media_product_type=_optional_str(payload, "media_product_type"),
        caption=_optional_str(payload, "caption"),
        permalink=_optional_str(payload, "permalink"),
        thumbnail_url=_optional_str(payload, "thumbnail_url"),
        media_type=_optional_str(payload, "media_type"),
        media_url=_optional_str(payload, "media_url"),
    )


def _parse_media_list_response(payload: dict[str, Any]) -> tuple[MediaSummary, ...]:
    """[V] `ig-user/media.md:394-416`: `{"data": [{"id": ...}, ...]}`."""
    entries = payload.get("data")
    if not isinstance(entries, list):
        raise MediaReadError("media list response carried no data array")
    return tuple(_parse_media_summary(entry) for entry in entries if isinstance(entry, dict))


class HttpMediaClient:
    """Real client over one already-authenticated client — `graph.facebook.com` only,
    same posture as `inbox.client.HttpCommentsClient`."""

    def __init__(self, *, graph_client: AuthenticatedClient, graph_url: str) -> None:
        self._graph = graph_client
        self._graph_url = graph_url.rstrip("/")

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        response = await self._graph.get(f"{self._graph_url}{path}", params=params)
        if response.status_code != 200:
            code, subcode = _error_codes(response)
            raise MediaReadError(
                f"GET {path} failed with HTTP {response.status_code}",
                http_status=response.status_code,
                platform_code=code,
                platform_subcode=subcode,
            )
        # QUA-146: a 200 whose body is not a JSON object is a malformed response, raised
        # as `MediaReadError` (status `None`, see its docstring) — never a bare
        # `ValueError` that would abort a whole sync pass after its call was budgeted.
        try:
            payload = response.json()
        except ValueError as exc:
            raise MediaReadError(f"GET {path} returned a body that is not JSON") from exc
        if not isinstance(payload, dict):
            raise MediaReadError(f"GET {path} returned JSON that is not an object")
        return payload

    async def _list_edge(self, path: str, params: dict[str, str]) -> tuple[MediaSummary, ...]:
        results: list[MediaSummary] = []
        while True:
            payload = await self._get(path, params)
            page = _parse_media_list_response(payload)
            results.extend(page)
            cursor = ((payload.get("paging") or {}).get("cursors") or {}).get("after")
            if not cursor or not page:
                break
            params = {**params, "after": cursor}
        return tuple(results)

    async def list_recent_media(
        self, *, ig_user_id: str, since: datetime
    ) -> tuple[MediaSummary, ...]:
        return await self._list_edge(
            f"/{ig_user_id}/media",
            {"fields": MEDIA_FIELDS, "since": str(int(since.timestamp()))},
        )

    async def list_recent_stories(self, *, ig_user_id: str) -> tuple[MediaSummary, ...]:
        """[V] `ig-user/stories.md`: `{"data": [{"id": ...}, ...], "paging": {...}}` —
        the same shape as `/media`. No `since`: the edge itself returns only the last 24
        hours (see "Stories live on their own edge" in the module docstring)."""
        return await self._list_edge(f"/{ig_user_id}/stories", {"fields": MEDIA_FIELDS})

    async def get_media(self, *, media_id: str) -> MediaSummary:
        return _parse_media_summary(await self._get(f"/{media_id}", {"fields": MEDIA_FIELDS}))
