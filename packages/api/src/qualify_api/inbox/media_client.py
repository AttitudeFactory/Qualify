"""The Instagram media-listing seam (monitored-media selection, groundwork for B2).

Same shape as `inbox/client.py`, `connections/meta_oauth.py` and `publishing/client.py`:
a `Protocol`, a real HTTP implementation, one `_parse_*` function per endpoint marked
`[V]`, and the credential arriving pre-authenticated via `AuthenticatedClient` — this
module never sees a token. Two endpoints, both on `graph.facebook.com`:

    GET /{ig-user-id}/media    — list_recent_media, for the "pick what to monitor" UI
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

## `get_media` exists for one reason: toggle-time validation without a stored timestamp

The product decision requires that activating monitoring on an old media is rejected — not
just hidden from the UI. Trusting a client-supplied timestamp, or caching one in
`monitored_media`, would mean the rule holds only as long as nobody calls the toggle
directly. `get_media` asks Meta fresh, every time, addressed directly by id
(`GET /{media-id}?fields=...` — `instagram-media.md:125` — no `ig_user_id` needed in the
path). `timestamp` is documented `Public` on this node (`instagram-media.md:98`) — no
`instagram_manage_comments` gate, unlike a comment's `username`/`from`.

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

# Minimal by design: only what the toggle/sync flow needs (id + creation time). Richer
# fields (caption, thumbnail, permalink) are a UI-rendering concern for whenever that UI
# gets built — adding them is a one-line change to this constant, not a schema change.
MEDIA_FIELDS: Final = "id,timestamp"


@dataclass(frozen=True)
class MediaSummary:
    """One IG Media object, reduced to what monitoring needs to decide anything."""

    id: str
    timestamp: datetime


class MediaReadError(Exception):
    """A media-read call failed. Never carries the token or the response body — same
    discipline as `inbox.client.CommentsReadError`."""

    def __init__(
        self,
        message: str,
        *,
        platform_code: int | None = None,
        platform_subcode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.platform_code = platform_code
        self.platform_subcode = platform_subcode


class MediaClient(Protocol):
    async def list_recent_media(
        self, *, ig_user_id: str, since: datetime
    ) -> tuple[MediaSummary, ...]: ...

    async def get_media(self, *, media_id: str) -> MediaSummary: ...


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


def _parse_media_summary(payload: dict[str, Any]) -> MediaSummary:
    """[V] `instagram-media.md:98,125,138`: `{"id": ..., "timestamp": "2019-...+0000"}`."""
    media_id = payload.get("id")
    raw_timestamp = payload.get("timestamp")
    if not isinstance(media_id, str) or not media_id:
        raise MediaReadError("media response carried no id")
    if not isinstance(raw_timestamp, str) or not raw_timestamp:
        raise MediaReadError("media response carried no timestamp")
    return MediaSummary(id=media_id, timestamp=parse_meta_timestamp(raw_timestamp))


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
                platform_code=code,
                platform_subcode=subcode,
            )
        return dict(response.json())

    async def list_recent_media(
        self, *, ig_user_id: str, since: datetime
    ) -> tuple[MediaSummary, ...]:
        params: dict[str, str] = {
            "fields": MEDIA_FIELDS,
            "since": str(int(since.timestamp())),
        }
        results: list[MediaSummary] = []
        while True:
            payload = await self._get(f"/{ig_user_id}/media", params)
            page = _parse_media_list_response(payload)
            results.extend(page)
            cursor = ((payload.get("paging") or {}).get("cursors") or {}).get("after")
            if not cursor or not page:
                break
            params = {**params, "after": cursor}
        return tuple(results)

    async def get_media(self, *, media_id: str) -> MediaSummary:
        return _parse_media_summary(await self._get(f"/{media_id}", {"fields": MEDIA_FIELDS}))
