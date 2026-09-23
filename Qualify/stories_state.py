"""Reflex state for `/stories` (QUA-106 V1 redesign): a single publish screen for
Instagram Stories, structurally the same flow `/publish` already has — pick a
connected account, select one video, see it in the gallery, hit "Publicar", poll
until Meta settles — narrowed to exactly one file (a Story is never a carousel) and
one fixed `media_product_type`.

**No `StoryProposal`, no approval, no review, no history.** There is no concept
here of a pending/pending-review/approved/rejected item — `publish()` calls
`publishing_provider.start_publish(media_product_type="STORIES")` directly, the
EXACT seam `/publish` uses for a single video, just with a different
`media_product_type`. `publish_attempts` (already existing, already the audit trail
for every other publish in this app) is the only record this produces — no second
table, no list screen, no detail screen.

**Media is always the operator's own upload.** No AI generation, no reuse of
scraped third-party content. Video only (`.mp4`/`.mov`) — a Story published via
`create_image_container` would need a Meta parameter this repo has never sent, out
of scope here, same as it always was.

**No caption field.** Instagram never shows a caption on a Story published via the
API — confirmed during manual testing — so there is nothing to collect from the
operator; `publish_background` always sends `caption=""`.

**Trending audio/content is reference-only, informational, and never persisted.**
`suggest_audio` shows Meta's own `GET /ig_audio` list (`qualify_api.stories`);
`search_audio`/`search_song_on_meta` use that SAME call with Meta's documented
`search_query` param (QUA-107 follow-up) instead of the default trending list —
same client, same seam, no new integration. `discover_tiktok_trending`/
`discover_instagram_trending`/`expand_song` read ScrapeCreators (QUA-107,
`scrapecreators_trending.py`) — a vendor with no per-tenant credential, independent
of `selected_connection_id`. `select_trend_audio` only sets a display choice in
THIS session's Reflex state (`selected_trend_audio_id`/`_title`) — nothing here is
ever sent to Meta's publish call (`audio_configuration` stays out of scope — and per
Meta's own docs is only ever defined for Reels, never Stories) or written to any
database row: there is no row left to write it onto.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.publishing import MEDIA_TYPE_STORIES
from qualify_api.publishing.service import UnknownAttempt, UnknownConnection
from qualify_shared.objects.config import R2ConfigurationError
from qualify_shared.objects.gate import ObjectSizeExceeded, UnsizedStream
from qualify_shared.objects.keys import TenantPrefixViolation

from . import scrapecreators_trending
from .auth_state import AuthState
from .publishing_provider import active_connections, poll_publish, start_publish
from .publishing_vm import ConnectionOptionVM, PublishAttemptVM
from .scrapecreators_client import ScrapeCreatorsError
from .stories_provider import suggest_trend_audio as _suggest_trend_audio
from .stories_vm import (
    TrendAudioOptionVM,
    TrendingVideoVM,
    build_trend_audio_vm,
    build_trending_video_vm,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay ningún tenant activo. Entra a Conexiones y elige uno primero."
_NO_CONNECTIONS = "No se pudieron cargar las cuentas conectadas."
_NO_CONNECTION_SELECTED = "Elige una cuenta conectada antes de publicar."
_NO_FILE = "Sube el video de la Story antes de publicar."
_UNSUPPORTED_FORMAT = "Formato no soportado. Usa MP4 o MOV para el video de la Story."
_BAD_MEDIA = "No se pudo leer el archivo subido. Intenta con otro archivo."
_NOT_CONFIGURED = "El almacenamiento (R2) todavía no está configurado en este entorno."
_TOO_LARGE = "El video supera el tamaño máximo permitido (300 MB)."
_UNKNOWN_CONNECTION = "Esa cuenta ya no está disponible. Actualiza la lista e intenta de nuevo."
_START_FAILED = "No se pudo iniciar la publicación. Vuelve a intentarlo en un momento."
_POLL_FAILED = "No se pudo consultar el estado de la publicación."
_WAIT_EXPLANATION = "Meta está procesando la Story. Esto puede tardar varios minutos."

_MP4_CONTENT_TYPE = "video/mp4"
_MOV_CONTENT_TYPE = "video/quicktime"
_VIDEO_CONTENT_TYPES = {_MP4_CONTENT_TYPE, _MOV_CONTENT_TYPE}

_UPLOAD_ID = "story_upload"

#: UI presentation cap for Meta's `ig_audio` suggestion list — see `suggest_audio`.
_MAX_TREND_AUDIO_OPTIONS = 10

#: Client-side safety net only — the SERVER already settles an attempt as 'failed'
#: once its own ceiling elapses (`publishing/client.py`). Same belt-and-suspenders
#: posture `publishing_state.py` documents for its own identical constant.
_MAX_POLLS = 30

_RESULT_TOAST_DURATION_MS = 6000


def _success_toast() -> rx.event.EventSpec:
    return rx.toast.success("¡Story publicada en Instagram!", duration=_RESULT_TOAST_DURATION_MS)


def _failure_toast(message: str) -> rx.event.EventSpec:
    return rx.toast.error(
        "No se pudo publicar la Story", description=message, duration=_RESULT_TOAST_DURATION_MS
    )


def _resolve_video(content_type: str | None, filename: str) -> str | None:
    """`(canonical_content_type)` for one dropped/picked file, video-only — or `None`
    if it cannot be resolved. Same "no silent fallback" discipline `publishing_state.
    _resolve_media` documents for its own resolver, narrowed to video since a Story is
    never a photo."""
    ct = (content_type or "").strip().lower()
    if ct in _VIDEO_CONTENT_TYPES:
        return ct
    name = filename.lower()
    if name.endswith(".mp4"):
        return _MP4_CONTENT_TYPE
    if name.endswith(".mov"):
        return _MOV_CONTENT_TYPE
    return None


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


class StoriesState(rx.State):
    """Backs `/stories` — one screen, one file, one publish action. Structurally the
    single-item path of `PublishState` (`publishing_state.py`), plus the QUA-107
    trending/reference panel bolted on alongside it, untouched in behavior."""

    connections: list[ConnectionOptionVM] = []
    is_loading_connections: bool = False
    connections_error: str = ""

    selected_connection_id: str = ""
    pending_filename: str = ""

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

    # QUA-107: ScrapeCreators trending discovery — independent of connection_id, so
    # switching connections (unlike `select_connection` below) never clears these.
    # `_expanded` (follow-up) is separate from "has data": the fetched list stays
    # cached once loaded, so collapsing/re-expanding is instant and never re-fetches
    # the vendor — only an explicit re-click on an ALREADY-expanded button refetches.
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

    # idle | staging_and_starting | polling | success | failure — same vocabulary
    # `PublishState.phase` already uses.
    phase: str = "idle"
    attempt: PublishAttemptVM | None = None
    error: str = ""

    # Private: bridges the foreground `add_file` (the only handler allowed to receive
    # the upload) to the background `publish_background` — same split
    # `publishing_state.py`'s own upload deviation note documents, narrowed to one
    # file (a Story is never a carousel).
    _pending_bytes: bytes = b""
    _pending_content_type: str = ""
    _idempotency_key: str = ""
    _active_tenant_id: str = ""
    # `time.monotonic()` at the moment `phase` becomes "polling", purely to derive
    # `elapsed_label` — same posture `PublishState`'s own field documents.
    _poll_started_monotonic: float = 0.0

    @rx.var
    def can_publish(self) -> bool:
        return (
            bool(self.selected_connection_id)
            and bool(self.pending_filename)
            and self.phase in ("idle", "success", "failure")
        )

    @rx.var
    def can_edit_gallery(self) -> bool:
        """Whether the gallery (dropzone, remove button) may be touched right now —
        same condition `PublishState.can_edit_gallery` documents for itself, deliberately
        NOT the same as `can_publish`, which also requires a file to already be selected."""
        return self.phase in ("idle", "success", "failure")

    @rx.var
    def elapsed_label(self) -> str:
        if self.phase != "polling" or self._poll_started_monotonic <= 0:
            return ""
        elapsed = max(0, int(time.monotonic() - self._poll_started_monotonic))
        minutes, seconds = divmod(elapsed, 60)
        return f"{minutes:02d}:{seconds:02d}"

    async def _session_tenant_id(self) -> UUID | None:
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        return tenant_uuid(session_tenant_id) if session_tenant_id else None

    # -- load ----------------------------------------------------------------

    @rx.event(background=True)
    async def load_stories_screen(self) -> None:
        async with self:
            self.is_loading_connections = True
            self.connections_error = ""

        tenant_id = await self._session_tenant_id()
        if tenant_id is None:
            async with self:
                self.is_loading_connections = False
                self.connections_error = _NO_TENANT
            return
        async with self:
            self._active_tenant_id = str(tenant_id)

        try:
            connections = await asyncio.to_thread(active_connections, tenant_id)
        except Exception as exc:
            logger.error("active_connections failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_connections = False
                self.connections_error = _NO_CONNECTIONS
            return
        async with self:
            self.connections = connections
            self.is_loading_connections = False

    # -- form ------------------------------------------------------------------

    @rx.event
    def select_connection(self, connection_id: str) -> None:
        self.selected_connection_id = connection_id
        # A new connection invalidates whatever trending audio was suggested for the
        # PREVIOUS one — never carried across silently.
        self.trend_options = []
        self.trend_expanded = False
        self.audio_search_query = ""
        self.selected_trend_audio_id = ""
        self.selected_trend_audio_title = ""

    @rx.event
    async def add_file(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """Buffers ONE video file — a second drop REPLACES the first, there is no
        gallery/carousel for a Story. Must not be `background=True`: Reflex forbids
        that combination for a handler receiving `list[rx.UploadFile]` (same
        constraint `publishing_state.py`'s module docstring documents)."""
        if not files:
            return None
        if self.phase not in ("idle", "success", "failure"):
            return None
        upload = files[0]
        filename = getattr(upload, "filename", None) or getattr(upload, "name", None) or "archivo"
        content_type = _resolve_video(getattr(upload, "content_type", None), filename)
        if content_type is None:
            return rx.toast.error(_UNSUPPORTED_FORMAT)
        try:
            data = await upload.read()
        except Exception:
            return rx.toast.error(_BAD_MEDIA)
        self._pending_bytes = data
        self._pending_content_type = content_type
        self.pending_filename = filename
        return None

    @rx.event
    def clear_file(self) -> None:
        if self.phase not in ("idle", "success", "failure"):
            return
        self._pending_bytes = b""
        self._pending_content_type = ""
        self.pending_filename = ""

    async def _run_audio_search(self, search_query: str) -> None:
        """Shared body for `suggest_audio`/`search_audio`/`search_song_on_meta` —
        best-effort, an empty result is a normal outcome, never shown as an error
        unless the call itself could not even be attempted (no tenant/connection).
        See `qualify_api.stories.suggest_trend_audio_using`'s own
        degrade-don't-block posture. `search_query` empty means Meta's own trending
        list (`suggest_audio`'s behavior, unchanged); non-empty searches Meta's
        catalog by keyword instead."""
        async with self:
            connection_id = self.selected_connection_id
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
        return StoriesState.discover_tiktok_trending

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
        return StoriesState.discover_instagram_trending

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

    # -- publish -----------------------------------------------------------

    @rx.event
    def publish(self) -> rx.event.EventSpec | None:
        """Validate the buffered file and hand off to `publish_background` — same
        split `publishing_state.publish` documents for its own foreground/background
        boundary. The `self.phase` check is the SERVER-SIDE guard against a
        double-submit, same reasoning `PublishState.publish` documents for its own
        identical check."""
        if self.phase not in ("idle", "success", "failure"):
            return None  # a publish is already in flight for this session
        if not self.selected_connection_id:
            self.phase = "failure"
            self.error = _NO_CONNECTION_SELECTED
            return _failure_toast(_NO_CONNECTION_SELECTED)
        if not self._pending_bytes:
            self.phase = "failure"
            self.error = _NO_FILE
            return _failure_toast(_NO_FILE)

        self._idempotency_key = uuid4().hex
        self.phase = "staging_and_starting"
        self.error = ""
        self.attempt = None
        return StoriesState.publish_background

    async def _fail_pending(self, idempotency_key: str, message: str) -> rx.event.EventSpec | None:
        """Record a failure for the attempt `idempotency_key` names, and release the
        buffered upload — same posture `PublishState._fail_pending_attempt`
        documents. Guarded by the idempotency key: a stale (superseded) attempt's
        failure must not clobber a newer attempt's in-progress state."""
        async with self:
            if self._idempotency_key != idempotency_key:
                return None
            self.phase = "failure"
            self.error = message
            self._pending_bytes = b""
            self._pending_content_type = ""
            self.pending_filename = ""
            return _failure_toast(message)

    @rx.event(background=True)
    async def publish_background(self) -> AsyncIterator[None]:
        """Stage the bytes `publish` captured and start a `STORIES` publish attempt,
        then hand off to polling. Reads everything it needs from the private vars
        `publish` set — mirrors `PublishState.publish_background`'s single-item path
        exactly, with `media_product_type` fixed to `MEDIA_TYPE_STORIES` instead of
        resolved from the file's own type (a Story is always video)."""
        async with self:
            if self.phase != "staging_and_starting":
                return  # superseded, or nothing was actually queued
            connection_id = self.selected_connection_id
            idempotency_key = self._idempotency_key
            data = self._pending_bytes
            content_type = self._pending_content_type

        tenant_id = await self._session_tenant_id()
        if tenant_id is None:
            toast = await self._fail_pending(idempotency_key, _NO_TENANT)
            if toast is not None:
                yield toast
            return
        async with self:
            self._active_tenant_id = str(tenant_id)

        try:
            attempt = await start_publish(
                tenant_id=tenant_id,
                connection_id=UUID(connection_id),
                fileobj=io.BytesIO(data),
                content_type=content_type,
                media_product_type=MEDIA_TYPE_STORIES,
                # Instagram never shows a caption on a Story published via the API —
                # there is nothing here to collect or send (product decision,
                # confirmed during QUA-106 V1 manual testing).
                caption="",
                idempotency_key=idempotency_key,
            )
        except R2ConfigurationError:
            toast = await self._fail_pending(idempotency_key, _NOT_CONFIGURED)
            if toast is not None:
                yield toast
            return
        except (ObjectSizeExceeded, UnsizedStream):
            toast = await self._fail_pending(idempotency_key, _TOO_LARGE)
            if toast is not None:
                yield toast
            return
        except (TenantPrefixViolation, ValueError):
            toast = await self._fail_pending(idempotency_key, _BAD_MEDIA)
            if toast is not None:
                yield toast
            return
        except UnknownConnection:
            toast = await self._fail_pending(idempotency_key, _UNKNOWN_CONNECTION)
            if toast is not None:
                yield toast
            return
        except Exception as exc:
            logger.error("start_publish failed: %s", type(exc).__name__)
            toast = await self._fail_pending(idempotency_key, _START_FAILED)
            if toast is not None:
                yield toast
            return

        async with self:
            # A newer attempt (a fresh click) superseded this one while we staged.
            if self._idempotency_key != idempotency_key:
                return
            self._pending_bytes = b""  # release the buffer, the staged copy is in R2
            self.attempt = attempt
            if attempt.settled:
                self.phase = "success" if attempt.status == "published" else "failure"
                if self.phase == "failure":
                    self.error = attempt.reason or _START_FAILED
                self.pending_filename = ""
            else:
                self.phase = "polling"
                self._poll_started_monotonic = time.monotonic()
            should_poll = self.phase == "polling"
            is_success = self.phase == "success"
            if is_success:
                self.selected_connection_id = ""
                self.selected_trend_audio_id = ""
                self.selected_trend_audio_title = ""
            result_toast = (
                _success_toast()
                if is_success
                else _failure_toast(self.error)
                if self.phase == "failure"
                else None
            )
        yield

        if result_toast is not None:
            yield result_toast

        if should_poll:
            yield StoriesState.poll_attempt

    @rx.event(background=True)
    async def poll_attempt(self) -> AsyncIterator[None]:
        """Client-driven polling: one `advance()` step per iteration, self-scheduling
        by yielding itself again until the attempt settles or the safety ceiling is
        hit — same shape `PublishState.poll_attempt` already has, minus the carousel
        per-child read (a Story is never a carousel)."""
        for _ in range(_MAX_POLLS):
            async with self:
                if self.phase != "polling" or self.attempt is None:
                    return
                tenant_id = tenant_uuid(self._active_tenant_id)
                attempt_id = self.attempt.attempt_id
                idempotency_key = self._idempotency_key

            if tenant_id is None:
                return

            try:
                attempt = await poll_publish(tenant_id=tenant_id, attempt_id=UUID(attempt_id))
            except UnknownAttempt:
                toast = None
                async with self:
                    if self._idempotency_key == idempotency_key:
                        self.phase = "failure"
                        self.error = _POLL_FAILED
                        self.pending_filename = ""
                        toast = _failure_toast(_POLL_FAILED)
                yield
                if toast is not None:
                    yield toast
                return
            except Exception as exc:
                logger.error("poll_publish failed: %s", type(exc).__name__)
                toast = None
                async with self:
                    if self._idempotency_key == idempotency_key:
                        self.phase = "failure"
                        self.error = _POLL_FAILED
                        self.pending_filename = ""
                        toast = _failure_toast(_POLL_FAILED)
                yield
                if toast is not None:
                    yield toast
                return

            async with self:
                if self._idempotency_key != idempotency_key:
                    return  # superseded by a newer attempt
                self.attempt = attempt
                if attempt.settled:
                    self.phase = "success" if attempt.status == "published" else "failure"
                    if self.phase == "failure":
                        self.error = attempt.reason or _START_FAILED
                    self.pending_filename = ""
                interval = attempt.poll_interval_seconds
                settled = attempt.settled
                is_success = self.phase == "success"
                if is_success:
                    self.selected_connection_id = ""
                    self.selected_trend_audio_id = ""
                    self.selected_trend_audio_title = ""
                result_toast = (
                    _success_toast()
                    if is_success
                    else _failure_toast(self.error)
                    if self.phase == "failure"
                    else None
                )
            yield
            if result_toast is not None:
                yield result_toast
            if settled:
                return
            await asyncio.sleep(interval)

        toast = None
        async with self:
            if self._idempotency_key == idempotency_key and self.phase == "polling":
                self.phase = "failure"
                self.error = _POLL_FAILED
                self.pending_filename = ""
                toast = _failure_toast(_POLL_FAILED)
        yield
        if toast is not None:
            yield toast
