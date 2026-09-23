"""Meta's `GET /ig_audio` (QUA-106) — trending audio, shown to a human as a REFERENCE
only. Same shape as `publishing/client.py`/`replies/client.py`: a `Protocol`, a real
HTTP implementation, one `_parse_*` function.

## Evidence status — VERIFIED live, 2026-09-19

Unlike `replies/client.py`'s reply-post shape (corpus-sourced only, never observed
live), this one was confirmed against the real, active PuntoServis Instagram
connection (`audio_type=music` and `audio_type=original_sound`, both HTTP 200, 25
items each, real `paging.cursors`) — see the QUA-106 discovery notes for the full
result. Measured findings this client's parsing accounts for:

- `ig_username` appears on BOTH `music` and `original_sound` items in practice — the
  official doc's "returned for original_sound type only" does not hold. Parsed
  whenever present, regardless of `audio_type`.
- No score/timestamp field exists anywhere in the response — the array's ORDER is the
  only signal Meta gives, and it was IDENTICAL across two calls two seconds apart
  (a real, server-side list — not proof of "rising", only of "not random"). This
  client does not invent a ranking number; ordinal position in the returned list is
  the only thing a caller may treat as "more prominent."
- `is_ads_eligible`/`on_platform_audio_preview_link` (documented by Meta) were absent
  from every one of the 50 real items observed — parsed as optional, never required.

**`search_query` is doc-sourced, NOT yet verified live** (`content-publishing/
audio-api.md`: "Optional. A search string to filter results by keyword") — added
2026-09-22 to let the operator search Meta's catalog instead of only browsing the
trending list; unlike the no-query call above, this exact parameter has not been
exercised against the real endpoint yet.

## What this module deliberately does NOT do

- **No `audio_configuration` attachment.** QUA-106 v1 shows this list for reference
  only; nothing here ever reaches `PublishClient.create_container`. Attaching a
  suggested audio to a real Story is explicitly out of this first slice — and per
  Meta's own `audio-api.md`, `audio_configuration` is only ever documented for
  `media_type=REELS`, never for Stories, so this may not be a phased limitation but
  a hard one for this media type.
- **No caching, no persistence, no ranking/scoring.** A plain read, called once per
  "sugerir audio" click — the same manual-trigger-only posture `replies.service.
  generate_drafts` documents for its own module.
- **No token appears here.** Same discipline as every other client: an already-
  authenticated `AuthenticatedClient` from `CredentialResolver.client_for(...,
  scheme=...)` is the only thing this module ever sees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from qualify_api.connections.resolver import AuthenticatedClient

#: The two `audio_type` values `GET /ig_audio` accepts (`audio-api.md:37`).
AUDIO_TYPE_MUSIC = "music"
AUDIO_TYPE_ORIGINAL_SOUND = "original_sound"


class TrendAudioError(Exception):
    """A trend-audio lookup failed. Never carries the token or the response body —
    same discipline as every other Meta-facing exception in this codebase. Always
    non-fatal to the caller: `qualify_api.stories.suggest_trend_audio_using` catches
    this and degrades to "no suggestion available", never blocking a Story publish."""

    def __init__(
        self,
        message: str,
        *,
        platform_code: int | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.platform_code = platform_code
        self.http_status = http_status


@dataclass(frozen=True)
class TrendAudioOption:
    """One suggested audio track — a REFERENCE for the human, never a value forwarded
    to Meta's publish call in this slice. `rank` is this item's 0-based position in
    Meta's own returned order — the only ordering signal that exists (see module
    docstring); it is NOT a score."""

    audio_id: str
    title: str
    artist_or_creator: str  # display_artist (music) or ig_username (either type)
    audio_type: str
    duration_ms: int | None
    rank: int
    # `download_url` (QUA-107 follow-up): "A temporary URL to preview the audio
    # file. This URL expires after approximately 1.5 days. May be null when no
    # preview URL is available." (audio-api.md) — a REFERENCE preview for the
    # human only, same posture as everything else on this dataclass. Never fed
    # into a Meta publish call; never downloaded or persisted by this codebase.
    preview_url: str = ""


class TrendAudioClient(Protocol):
    async def trending_audio(
        self, *, ig_user_id: str, audio_type: str, search_query: str | None = None
    ) -> tuple[TrendAudioOption, ...]:
        """`GET /ig_audio?audio_type=<audio_type>&user_id=<ig_user_id>`, plus
        `search_query` when given — Meta's own documented parameter
        (`content-publishing/audio-api.md`: "Optional. A search string to filter
        results by keyword"; "If no search query is provided, trending audio is
        returned"). `None`/omitted keeps the existing trending-list behavior exactly.
        Raises `TrendAudioError`."""
        ...


def _error_codes(response: httpx.Response) -> tuple[int | None, int | None]:
    """Duplicated from `publishing/client.py`/`replies/client.py` rather than
    imported — each client module in this codebase is self-contained by convention."""
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


def _parse_audio_item(item: dict[str, Any], *, rank: int) -> TrendAudioOption | None:
    """One `audio[]` entry. `None` for a malformed item (missing `audio_id`) rather
    than raising — one bad entry in a 25-item reference list must not lose the other
    24, same "degrade, don't block" posture this whole module has toward the caller."""
    audio_id = item.get("audio_id")
    if not isinstance(audio_id, str) or not audio_id:
        return None
    audio_type = item.get("audio_type")
    audio_type = audio_type if isinstance(audio_type, str) else ""
    title = item.get("title")
    title = title if isinstance(title, str) else ""
    # [VERIFIED 2026-09-19] `ig_username` observed on BOTH audio_type values in the
    # real response, not just `original_sound` as the doc claims — checked generically.
    artist = item.get("display_artist")
    username = item.get("ig_username")
    if isinstance(artist, str) and artist:
        artist_or_creator = artist
    elif isinstance(username, str):
        artist_or_creator = username
    else:
        artist_or_creator = ""
    duration = item.get("duration_in_ms")
    preview_url = item.get("download_url")
    return TrendAudioOption(
        audio_id=audio_id,
        title=title or "Audio sin título",
        artist_or_creator=artist_or_creator,
        audio_type=audio_type,
        duration_ms=duration if isinstance(duration, int) else None,
        rank=rank,
        preview_url=preview_url if isinstance(preview_url, str) else "",
    )


def _parse_trending_response(payload: dict[str, Any]) -> tuple[TrendAudioOption, ...]:
    """[VERIFIED 2026-09-19] `{"audio": [...], "paging": {"cursors": {...}}}` — the
    real shape observed against the PuntoServis connection. `paging` is ignored here:
    this client never paginates (one page is plenty for a reference list)."""
    items = payload.get("audio")
    if not isinstance(items, list):
        raise TrendAudioError("ig_audio response carried no 'audio' list")
    parsed = (
        _parse_audio_item(item, rank=rank)
        for rank, item in enumerate(items)
        if isinstance(item, dict)
    )
    return tuple(option for option in parsed if option is not None)


class HttpTrendAudioClient:
    """Real client over one already-authenticated client — `graph.facebook.com` only,
    the same host `PublishClient` already uses for every non-upload call."""

    def __init__(self, *, graph_client: AuthenticatedClient, graph_url: str) -> None:
        self._graph = graph_client
        self._graph_url = graph_url.rstrip("/")

    async def trending_audio(
        self, *, ig_user_id: str, audio_type: str, search_query: str | None = None
    ) -> tuple[TrendAudioOption, ...]:
        params: dict[str, str] = {"audio_type": audio_type, "user_id": ig_user_id}
        if search_query:
            params["search_query"] = search_query
        try:
            response = await self._graph.get(f"{self._graph_url}/ig_audio", params=params)
        except httpx.TransportError as exc:
            raise TrendAudioError(f"transport failure calling ig_audio: {exc}") from exc

        if response.status_code != 200:
            code, _subcode = _error_codes(response)
            raise TrendAudioError(
                f"GET /ig_audio failed with HTTP {response.status_code}",
                platform_code=code,
                http_status=response.status_code,
            )
        return _parse_trending_response(dict(response.json()))
