"""Reflex state for the "Tendencias e inspiración" panel (QUA-113, Fase 1) — the
trending/reference panel that used to live inside `StoriesState`, pulled out into
its own state so it can be shown next to ANY publish flow (Publicaciones or Stories)
without either flow's state knowing about it, and without it knowing about either
flow's publish logic.

Behavior is moved, not changed: every field and handler below is the QUA-106 V1 /
QUA-107 code `StoriesState` had, byte for byte in intent. Two sources, both
reference-only and never persisted:

- **Meta `GET /ig_audio`** (`suggest_audio`/`search_audio`/`search_song_on_meta`,
  via `stories_provider.suggest_trend_audio`) — needs a connected account's
  credential, so it is scoped to `audio_connection_id`.
- **ScrapeCreators** (`discover_tiktok_trending`/`discover_instagram_trending`/
  `expand_song`, via `scrapecreators_trending.py`) — one global API key, no tenant,
  no connection (QUA-107 architecture decision).

**Which account backs the Meta audio lookup.** This state owns no connection
selector. Whichever publish flow is active tells it, through
`set_audio_connection` (the flow's account changed) and `release_audio_connection`
(the flow reset its account after a successful publish). That keeps the one coupling
the panel has — Meta needs a credential — as a single explicit event, instead of
this state reading another flow's state.

`select_trend_audio` is a display choice in this session only — nothing here ever
reaches a publish call (`audio_configuration` stays out of scope) or a database row.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import reflex as rx
from qualify_api.referentes.scrapecreators_client import ScrapeCreatorsError

from . import scrapecreators_trending
from .auth_state import AuthState
from .stories_provider import suggest_trend_audio as _suggest_trend_audio
from .stories_vm import (
    TrendAudioOptionVM,
    TrendingVideoVM,
    build_trend_audio_vm,
    build_trending_video_vm,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

# UI-only presentation cap for Meta's audio list — see `_run_audio_search`.
_MAX_TREND_AUDIO_OPTIONS = 10


def _trending_vm(video: scrapecreators_trending.TrendingVideo) -> TrendingVideoVM:
    return build_trending_video_vm(
        source=video.source,
        external_id=video.id,
        caption=video.caption,
        author_handle=video.author_handle,
        author_display_name=video.author_display_name,
        likes=video.likes,
        comments=video.comments,
        plays=video.plays,
        created_at=video.created_at,
        permalink=video.permalink,
        thumbnail_url=video.thumbnail_url,
        music_id=video.music_id,
        music_title=video.music_title,
        rank=video.rank,
    )


class TrendingState(rx.State):
    """Backs the trending/reference panel. Independent of every publish flow's
    state — see the module docstring for the one explicit link (the Meta account)."""

    # The connected account Meta's `ig_audio` lookup runs against — set by the active
    # publish flow, never chosen here. Empty means "no account": the Meta controls
    # are disabled and `_run_audio_search` is a no-op, same as before the split.
    audio_connection_id: str = ""

    trend_options: list[TrendAudioOptionVM] = []
    # Follow-up ("que también se pueda cerrar"): a successful lookup opens the list,
    # a close never clears `trend_options` — same cache-but-collapse posture
    # `tiktok_trending_expanded`/`instagram_trending_expanded` already have.
    trend_expanded: bool = False
    is_loading_trend: bool = False
    trend_error: str = ""
    selected_trend_audio_id: str = ""
    selected_trend_audio_title: str = ""
    # Meta's `GET /ig_audio` accepts an optional `search_query` (audio-api.md) — this
    # box searches Meta's own catalog by keyword instead of only browsing whatever
    # "Sugerir audio en tendencia" returns. Independent of `trend_options`: typing
    # here does not filter the CURRENT list client-side, it drives the NEXT lookup.
    audio_search_query: str = ""

    # QUA-107: ScrapeCreators trending discovery — independent of the account, so
    # `set_audio_connection` never clears these. `_expanded` (follow-up) is separate
    # from "has data": the fetched list stays cached once loaded, so collapsing/
    # re-expanding is instant and never re-fetches the vendor — only an explicit
    # re-click on an ALREADY-expanded button refetches.
    tiktok_trending: list[TrendingVideoVM] = []
    tiktok_trending_expanded: bool = False
    is_loading_tiktok_trending: bool = False
    tiktok_trending_error: str = ""

    instagram_trending: list[TrendingVideoVM] = []
    instagram_trending_expanded: bool = False
    is_loading_instagram_trending: bool = False
    instagram_trending_error: str = ""

    expanded_song_id: str = ""
    song_detail: TrendAudioOptionVM | None = None
    is_loading_song_detail: bool = False

    # QUA-107 follow-up: audio preview player. Deliberately independent of
    # `selected_trend_audio_id`/`_title` — listening to a track and choosing it as a
    # reference are two separate actions, never coupled.
    playing_audio_id: str = ""
    playing_audio_url: str = ""
    is_audio_playing: bool = False

    async def _session_tenant_id(self) -> UUID | None:
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        return tenant_uuid(session_tenant_id) if session_tenant_id else None

    # -- the account behind Meta's audio lookup -------------------------------

    @rx.event
    def set_audio_connection(self, connection_id: str) -> None:
        """The active flow picked an account. A Meta list fetched for the PREVIOUS
        account is never carried across silently — including whatever was typed in
        the search box and the selected audio. ScrapeCreators lists stay: they do not
        depend on the account."""
        self._switch_audio_connection(connection_id)

    @rx.event
    def follow_connection(self, connection_id: str) -> None:
        """The operator switched publish flow (QUA-113): follow the account the NEW
        flow has selected. Unlike `set_audio_connection` (an explicit account pick,
        which always starts the Meta list over), this keeps everything when both
        flows point at the same account — only a DIFFERENT account drops the Meta
        list, since it was fetched with the previous account's credential."""
        if connection_id == self.audio_connection_id:
            return
        self._switch_audio_connection(connection_id)

    def _switch_audio_connection(self, connection_id: str) -> None:
        self.audio_connection_id = connection_id
        self.trend_options = []
        self.trend_expanded = False
        self.audio_search_query = ""
        self.selected_trend_audio_id = ""
        self.selected_trend_audio_title = ""

    @rx.event
    def release_audio_connection(self) -> None:
        """The active flow cleared its account after a successful publish. Mirrors
        what `StoriesState` did before the split: the selection is cleared, the
        already-shown Meta list stays visible, and no new Meta lookup can run until
        an account is picked again."""
        self.audio_connection_id = ""
        self.selected_trend_audio_id = ""
        self.selected_trend_audio_title = ""

    # -- Meta trending audio (`GET /ig_audio`) ---------------------------------

    async def _run_audio_search(self, search_query: str) -> None:
        """Shared body for `suggest_audio`/`search_audio`/`search_song_on_meta` —
        best-effort, an empty result is a normal outcome, never shown as an error
        unless the call itself could not even be attempted (no tenant/account).
        See `qualify_api.stories.suggest_trend_audio_using`'s own
        degrade-don't-block posture. `search_query` empty means Meta's own trending
        list; non-empty searches Meta's catalog by keyword instead."""
        async with self:
            connection_id = self.audio_connection_id
        if not connection_id:
            return
        tenant_id = await self._session_tenant_id()
        if tenant_id is None:
            return
        async with self:
            self.is_loading_trend = True
            self.trend_error = ""
        options = await _suggest_trend_audio(
            tenant_id=tenant_id, connection_id=UUID(connection_id), search_query=search_query
        )
        async with self:
            # The account changed while Meta was answering — the result belongs to
            # the previous one, drop it rather than show it under the new account.
            if self.audio_connection_id != connection_id:
                self.is_loading_trend = False
                return
            # UI-only presentation cap (QUA-107 follow-up) — Meta's own list is
            # uncapped (~25 items measured), which read as a "wall of chips" once
            # the trending-discovery cards landed next to it. The cap lives here,
            # never in trend_audio_client.py: it is about how many we SHOW, not
            # about what Meta returns.
            self.trend_options = options[:_MAX_TREND_AUDIO_OPTIONS]
            self.trend_expanded = True
            self.is_loading_trend = False

    @rx.event
    def close_trend_audio(self) -> None:
        """Collapse the Meta audio list (follow-up: "que también se pueda
        cerrar") — never clears `trend_options`, same cache-but-collapse posture
        the TikTok/Instagram toggles already have. Clicking "Sugerir"/"Buscar"
        again re-opens it (with fresh results, since those always re-fetch)."""
        self.trend_expanded = False

    @rx.event(background=True)
    async def suggest_audio(self) -> None:
        """Browse Meta's own trending list — no search query, unchanged behavior."""
        await self._run_audio_search("")

    @rx.event(background=True)
    async def search_audio(self) -> None:
        """Search Meta's audio catalog using whatever is currently typed in
        `audio_search_query`. An empty box behaves exactly like `suggest_audio`."""
        async with self:
            query = self.audio_search_query
        await self._run_audio_search(query)

    @rx.event(background=True)
    async def search_song_on_meta(self, title: str) -> None:
        """ "Buscar esta canción" from a TikTok/Instagram trending candidate's song
        detail (QUA-107 follow-up) — fills the search box with that track's title
        and searches Meta's OWN catalog for it. TikTok's and Meta's audio catalogs
        are unrelated systems; this can only search by keyword, never guarantee a
        match — same reference-only posture every trend-audio feature here has."""
        async with self:
            self.audio_search_query = title
        await self._run_audio_search(title)

    @rx.event
    def set_audio_search_query(self, value: str) -> None:
        self.audio_search_query = value

    @rx.event
    def select_trend_audio(self, audio_id: str, title: str) -> None:
        self.selected_trend_audio_id = audio_id
        self.selected_trend_audio_title = title

    @rx.event
    def clear_trend_audio(self) -> None:
        self.selected_trend_audio_id = ""
        self.selected_trend_audio_title = ""

    # -- the one shared preview player ----------------------------------------

    @rx.event
    def toggle_audio_preview(self, audio_id: str, url: str) -> None:
        """Play/pause the ONE shared preview player. Toggling the currently-playing
        row pauses it; anything else (a different row, or a paused row) switches the
        player's source and plays. Never touches `selected_trend_audio_id`/`_title`
        — listening and selecting are independent (QUA-107 follow-up)."""
        if self.playing_audio_id == audio_id and self.is_audio_playing:
            self.is_audio_playing = False
            return
        self.playing_audio_id = audio_id
        self.playing_audio_url = url
        self.is_audio_playing = True

    @rx.event
    def audio_preview_stopped(self) -> None:
        """Fired by the player's own `on_ended`/`on_error` — a track finishing, or a
        preview URL that expired/failed mid-playback, both degrade to the same
        clean stopped state rather than leaving the ⏸ icon stuck showing sound that
        is not actually playing."""
        self.is_audio_playing = False

    # -- ScrapeCreators trending discovery (QUA-107) ---------------------------

    @rx.event
    def toggle_tiktok_trending(self) -> rx.event.EventSpec | None:
        """Collapse/expand — the same button drives both directions (follow-up).
        Collapsing never clears `tiktok_trending`, so re-expanding right after is
        instant and free; a fresh vendor call only happens the FIRST time (nothing
        cached yet)."""
        if self.tiktok_trending_expanded:
            self.tiktok_trending_expanded = False
            return None
        if self.tiktok_trending:
            self.tiktok_trending_expanded = True
            return None
        return TrendingState.discover_tiktok_trending

    @rx.event(background=True)
    async def discover_tiktok_trending(self) -> None:
        """Explicit, operator-triggered — never runs on screen load. Needs no
        tenant/connection: ScrapeCreators resolves against the one global
        `SCRAPECREATORS_API_KEY`, not a per-tenant credential (QUA-107 architecture
        decision). Any vendor failure degrades to an empty list, same "reference
        only, never blocking" posture `suggest_audio` already has for Meta."""
        async with self:
            self.is_loading_tiktok_trending = True
            self.tiktok_trending_error = ""
        try:
            videos = await asyncio.to_thread(scrapecreators_trending.fetch_tiktok_trending_feed)
        except ScrapeCreatorsError as exc:
            logger.warning("fetch_tiktok_trending_feed failed: %s", type(exc).__name__)
            async with self:
                self.tiktok_trending = []
                self.tiktok_trending_expanded = True
                self.is_loading_tiktok_trending = False
            return
        async with self:
            self.tiktok_trending = [_trending_vm(v) for v in videos]
            self.tiktok_trending_expanded = True
            self.is_loading_tiktok_trending = False

    @rx.event
    def toggle_instagram_trending(self) -> rx.event.EventSpec | None:
        """Same collapse/expand toggle as `toggle_tiktok_trending`, for Instagram."""
        if self.instagram_trending_expanded:
            self.instagram_trending_expanded = False
            return None
        if self.instagram_trending:
            self.instagram_trending_expanded = True
            return None
        return TrendingState.discover_instagram_trending

    @rx.event(background=True)
    async def discover_instagram_trending(self) -> None:
        """Same posture as `discover_tiktok_trending` — explicit trigger, no
        tenant/connection, degrades to an empty list on any vendor failure."""
        async with self:
            self.is_loading_instagram_trending = True
            self.instagram_trending_error = ""
        try:
            videos = await asyncio.to_thread(scrapecreators_trending.fetch_instagram_trending_reels)
        except ScrapeCreatorsError as exc:
            logger.warning("fetch_instagram_trending_reels failed: %s", type(exc).__name__)
            async with self:
                self.instagram_trending = []
                self.instagram_trending_expanded = True
                self.is_loading_instagram_trending = False
            return
        async with self:
            self.instagram_trending = [_trending_vm(v) for v in videos]
            self.instagram_trending_expanded = True
            self.is_loading_instagram_trending = False

    @rx.event(background=True)
    async def expand_song(self, music_id: str, music_title: str) -> None:
        """Enriches ONE TikTok candidate with `/song` — on demand, never batched
        (QUA-107 decision). A failure here degrades to `song_detail` staying `None`;
        it never blocks publishing or picking a different candidate."""
        async with self:
            self.expanded_song_id = music_id
            self.is_loading_song_detail = True
            self.song_detail = None
        try:
            detail = await asyncio.to_thread(
                scrapecreators_trending.fetch_tiktok_song, clip_id=music_id
            )
        except ScrapeCreatorsError as exc:
            logger.warning("fetch_tiktok_song failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_song_detail = False
            return
        async with self:
            self.song_detail = build_trend_audio_vm(
                audio_id=detail.id or music_id,
                title=detail.title or music_title,
                artist_or_creator=detail.author,
                duration_ms=None,
                rank=0,
                user_count=detail.user_count,
                recommend_status=detail.recommend_status,
                preview_url=detail.preview_url,
            )
            self.is_loading_song_detail = False
