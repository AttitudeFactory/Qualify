"""Reflex state for the Stories screens (QUA-106): `/stories` (propose + review queue)
and `/stories/[proposal_id]` (the single mandatory approval gate before publish).

**Media is always the operator's own upload.** There is no AI generation, no reuse of
scraped third-party content — QUA-106 v1 decision, and the only functioning media
source in this codebase today (see the QUA-106 discovery notes). Video only
(`.mp4`/`.mov`) — Stories via `create_image_container` would need a Meta parameter
this repo has never sent; out of this slice.

**Caption is 100% manual/editable.** No `ContentService` integration in this v1 — the
operator types the caption, and may edit it again at decision time (`edited`).

**Trending audio is reference-only.** `suggest_audio` shows Meta's own `GET /ig_audio`
list; `select_trend_audio` only remembers a display choice (`trend_audio_id`/`_title`
persisted on the proposal for the human's own context) — nothing here ever threads it
into a Meta publish call (`audio_configuration` is out of this slice).

**Trending TikTok/Instagram discovery (QUA-107) is a second, independent source of the
same kind of reference.** `discover_tiktok_trending`/`discover_instagram_trending`
read ScrapeCreators — a vendor with NO per-tenant credentials and NO relationship to
`selected_connection_id`, unlike `suggest_audio`'s Meta call. Selecting a TikTok song
(`expand_song` then `select_trend_audio`) reuses the EXACT SAME `selected_trend_audio_id`/
`_title` fields Meta's suggestion already writes to — a proposal carries one audio
reference, so a new choice from either source simply replaces the previous one. A
Reel is shown for visual reference only; there is no selection action for it and
nothing about it is ever persisted.

**No path from a fresh proposal to a publish.** `approve_and_publish`/`save_and_
publish` always call `decide_proposal` before `publish_proposal` — mirrors
`replies_state.py`'s own "decide, then send" chaining, and the SERVICE layer refuses
the send regardless (`StoryProposalService.publish`)."""

from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx

from . import scrapecreators_trending
from .auth_state import AuthState
from .connections_provider import acting_user_id
from .publishing_provider import active_connections
from .publishing_vm import ConnectionOptionVM
from .scrapecreators_client import ScrapeCreatorsError
from .stories_provider import (
    decide_proposal,
    list_proposals,
    propose_story,
    publish_proposal,
    refresh_proposal,
)
from .stories_provider import get_proposal as _get_proposal
from .stories_provider import suggest_trend_audio as _suggest_trend_audio
from .stories_vm import (
    StoryProposalVM,
    TrendAudioOptionVM,
    TrendingVideoVM,
    build_trend_audio_vm,
    build_trending_video_vm,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_TENANT = "No hay ningún tenant activo. Entra a Conexiones y elige uno primero."
_NO_CONNECTIONS = "No se pudieron cargar las cuentas conectadas."
_NO_CONNECTION_SELECTED = "Elige una cuenta conectada antes de crear la propuesta."
_NO_FILE = "Sube el video de la Story antes de crear la propuesta."
_UNSUPPORTED_FORMAT = "Formato no soportado. Usa MP4 o MOV para el video de la Story."
_BAD_MEDIA = "No se pudo leer el archivo subido. Intenta con otro archivo."
_CREATE_FAILED = "No se pudo crear la propuesta. Vuelve a intentarlo en un momento."
_LIST_FAILED = "No se pudieron cargar las propuestas."
_PROPOSAL_GONE = "Esa propuesta ya no está disponible."
_NO_ACTING_USER = "Este tenant no tiene un usuario asignado todavía."
_DECIDE_FAILED = "No se pudo registrar la decisión. Actualiza la página e intenta de nuevo."
_PUBLISH_FAILED = "No se pudo iniciar la publicación. Vuelve a intentarlo en un momento."

_MP4_CONTENT_TYPE = "video/mp4"
_MOV_CONTENT_TYPE = "video/quicktime"
_VIDEO_CONTENT_TYPES = {_MP4_CONTENT_TYPE, _MOV_CONTENT_TYPE}

_UPLOAD_ID = "story_upload"

# UI presentation cap for Meta's `ig_audio` suggestion list — see `suggest_audio`.
_MAX_TREND_AUDIO_OPTIONS = 10


def _resolve_video(content_type: str | None, filename: str) -> str | None:
    """`(canonical_content_type)` for one dropped/picked file, video-only — or `None`
    if it cannot be resolved. Same "no silent fallback" discipline `publishing_state.
    _resolve_media` documents for its own resolver, narrowed to video since a Story in
    this slice is never a photo (see module docstring)."""
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
    """Backs both `/stories` (propose + queue) and `/stories/[proposal_id]`
    (the approval gate) — same one-state-two-routes pattern `CreativeState` already
    uses for `/drafts` + `/drafts/[draft_id]`."""

    # -- /stories: connections + create form ---------------------------------
    connections: list[ConnectionOptionVM] = []
    is_loading_connections: bool = False
    connections_error: str = ""

    selected_connection_id: str = ""
    caption: str = ""
    pending_filename: str = ""

    trend_options: list[TrendAudioOptionVM] = []
    is_loading_trend: bool = False
    trend_error: str = ""
    selected_trend_audio_id: str = ""
    selected_trend_audio_title: str = ""

    # -- QUA-107: ScrapeCreators trending discovery — independent of connection_id,
    # so switching connections (unlike `select_connection` above) never clears these.
    tiktok_trending: list[TrendingVideoVM] = []
    is_loading_tiktok_trending: bool = False
    tiktok_trending_error: str = ""

    instagram_trending: list[TrendingVideoVM] = []
    is_loading_instagram_trending: bool = False
    instagram_trending_error: str = ""

    expanded_song_id: str = ""
    song_detail: TrendAudioOptionVM | None = None
    is_loading_song_detail: bool = False

    # -- QUA-107 follow-up: audio preview player. Deliberately independent of
    # `selected_trend_audio_id`/`_title` — listening to a track and choosing it as
    # the proposal's reference are two separate actions, never coupled.
    playing_audio_id: str = ""
    playing_audio_url: str = ""
    is_audio_playing: bool = False

    # idle | staging | failure (a success resets straight back to idle)
    create_phase: str = "idle"
    create_error: str = ""

    # -- /stories: the list ---------------------------------------------------
    proposals: list[StoryProposalVM] = []
    is_loading_proposals: bool = False
    proposals_error: str = ""

    # Private: bridges the foreground `add_file` (the only handler allowed to receive
    # the upload) to the background `create_proposal_background` — same split
    # `publishing_state.py`'s own upload deviation note documents, narrowed to one
    # file (no gallery/carousel in this slice).
    _pending_bytes: bytes = b""
    _pending_content_type: str = ""
    _active_tenant_id: str = ""

    # -- /stories/[proposal_id]: the approval gate ----------------------------
    # `proposal_id` is DELIBERATELY not declared here — Reflex auto-binds a dynamic
    # route arg (`app.add_page(..., route="/stories/[proposal_id]")`) onto the state
    # by name, and declaring it explicitly raises `DynamicRouteArgShadowsStateVarError`
    # (measured). Same posture `CreativeState.draft_id`/`_route_proposal_id` below
    # already establish for `/drafts/[draft_id]`.
    proposal: StoryProposalVM | None = None
    is_loading_proposal: bool = False
    proposal_error: str = ""

    is_editing: bool = False
    edit_caption: str = ""
    action_error: str = ""
    is_deciding: bool = False
    is_publishing_action: bool = False

    @rx.var
    def can_create(self) -> bool:
        return (
            bool(self.selected_connection_id)
            and bool(self.pending_filename)
            and self.create_phase in ("idle", "failure")
        )

    def _route_proposal_id(self) -> str:
        """The dynamic route arg, read defensively (same posture `CreativeState.
        _route_draft_id` documents for its own) — `getattr` rather than `self.
        proposal_id` because the attribute only exists once Reflex has bound the
        route, never declared as a class var here (see the field comment above)."""
        return str(getattr(self, "proposal_id", "") or "")

    async def _session_tenant_id(self) -> UUID | None:
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        return tenant_uuid(session_tenant_id) if session_tenant_id else None

    # -- /stories: load ---------------------------------------------------------

    @rx.event(background=True)
    async def load_stories_screen(self) -> None:
        async with self:
            self.is_loading_connections = True
            self.is_loading_proposals = True
            self.connections_error = ""
            self.proposals_error = ""

        tenant_id = await self._session_tenant_id()
        if tenant_id is None:
            async with self:
                self.is_loading_connections = False
                self.is_loading_proposals = False
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
            connections = None
        else:
            async with self:
                self.connections = connections
                self.is_loading_connections = False

        try:
            proposals = await asyncio.to_thread(list_proposals, tenant_id)
        except Exception as exc:
            logger.error("list_proposals failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_proposals = False
                self.proposals_error = _LIST_FAILED
            return
        async with self:
            self.proposals = proposals
            self.is_loading_proposals = False

    # -- /stories: create form ----------------------------------------------

    @rx.event
    def select_connection(self, connection_id: str) -> None:
        self.selected_connection_id = connection_id
        # A new connection invalidates whatever trending audio was suggested for the
        # PREVIOUS one — never carried across silently.
        self.trend_options = []
        self.selected_trend_audio_id = ""
        self.selected_trend_audio_title = ""

    @rx.event
    def set_caption(self, value: str) -> None:
        self.caption = value

    @rx.event
    async def add_file(self, files: list[rx.UploadFile]) -> rx.event.EventSpec | None:
        """Buffers ONE video file — a second drop REPLACES the first, there is no
        gallery in this slice. Must not be `background=True`: Reflex forbids that
        combination for a handler receiving `list[rx.UploadFile]` (same constraint
        `publishing_state.py`'s module docstring documents)."""
        if not files:
            return None
        if self.create_phase not in ("idle", "failure"):
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
        if self.create_phase not in ("idle", "failure"):
            return
        self._pending_bytes = b""
        self._pending_content_type = ""
        self.pending_filename = ""

    @rx.event(background=True)
    async def suggest_audio(self) -> None:
        """Best-effort — an empty result is a normal outcome (see
        `StoryProposalService.suggest_trend_audio`), never shown as an error unless
        the call itself could not even be attempted (no tenant/connection)."""
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
        options = await _suggest_trend_audio(tenant_id=tenant_id, connection_id=UUID(connection_id))
        async with self:
            # UI-only presentation cap (QUA-107 follow-up) — Meta's own list is
            # uncapped (~25 items measured), which read as a "wall of chips" once
            # the trending-discovery cards landed next to it. The cap lives here,
            # never in trend_audio_client.py: it is about how many we SHOW, not
            # about what Meta returns.
            self.trend_options = options[:_MAX_TREND_AUDIO_OPTIONS]
            self.is_loading_trend = False

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
                self.is_loading_tiktok_trending = False
            return
        async with self:
            self.tiktok_trending = [_trending_vm(v) for v in videos]
            self.is_loading_tiktok_trending = False

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
                self.is_loading_instagram_trending = False
            return
        async with self:
            self.instagram_trending = [_trending_vm(v) for v in videos]
            self.is_loading_instagram_trending = False

    @rx.event(background=True)
    async def expand_song(self, music_id: str, music_title: str) -> None:
        """Enriches ONE TikTok candidate with `/song` — on demand, never batched
        (QUA-107 decision). A failure here degrades to `song_detail` staying `None`;
        it never blocks proposing or picking a different candidate."""
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

    @rx.event
    def create_proposal(self) -> rx.event.EventSpec | None:
        """Validates the buffered upload and hands off to the background handler —
        same split `publishing_state.publish` documents for its own foreground/
        background boundary."""
        if self.create_phase not in ("idle", "failure"):
            return None
        if not self.selected_connection_id:
            self.create_phase = "failure"
            self.create_error = _NO_CONNECTION_SELECTED
            return rx.toast.error(_NO_CONNECTION_SELECTED)
        if not self._pending_bytes:
            self.create_phase = "failure"
            self.create_error = _NO_FILE
            return rx.toast.error(_NO_FILE)
        self.create_phase = "staging"
        self.create_error = ""
        return StoriesState.create_proposal_background

    @rx.event(background=True)
    async def create_proposal_background(self) -> AsyncIterator[None]:
        async with self:
            if self.create_phase != "staging":
                return  # superseded
            connection_id = self.selected_connection_id
            caption = self.caption
            data = self._pending_bytes
            content_type = self._pending_content_type
            trend_audio_id = self.selected_trend_audio_id
            trend_audio_title = self.selected_trend_audio_title

        tenant_id = await self._session_tenant_id()
        if tenant_id is None:
            async with self:
                self.create_phase = "failure"
                self.create_error = _NO_TENANT
            yield rx.toast.error(_NO_TENANT)
            return

        try:
            await propose_story(
                tenant_id=tenant_id,
                connection_id=UUID(connection_id),
                fileobj=io.BytesIO(data),
                content_type=content_type,
                caption=caption,
                trend_audio_id=trend_audio_id,
                trend_audio_title=trend_audio_title,
            )
        except Exception as exc:
            logger.error("propose_story failed: %s", type(exc).__name__)
            async with self:
                self.create_phase = "failure"
                self.create_error = _CREATE_FAILED
            yield rx.toast.error(_CREATE_FAILED)
            return

        async with self:
            self.create_phase = "idle"
            self.caption = ""
            self.pending_filename = ""
            self._pending_bytes = b""
            self._pending_content_type = ""
            self.trend_options = []
            self.selected_trend_audio_id = ""
            self.selected_trend_audio_title = ""
            self.tiktok_trending = []
            self.instagram_trending = []
            self.expanded_song_id = ""
            self.song_detail = None
            self.playing_audio_id = ""
            self.playing_audio_url = ""
            self.is_audio_playing = False
        yield rx.toast.success("Propuesta creada — queda pendiente de revisión.")
        yield StoriesState.load_stories_screen

    # -- /stories/[proposal_id]: the approval gate --------------------------

    @rx.event(background=True)
    async def load_proposal(self) -> None:
        async with self:
            self.is_loading_proposal = True
            self.proposal_error = ""
            self.action_error = ""
            self.is_editing = False
            proposal_id = self._route_proposal_id()
        tenant_id = await self._session_tenant_id()
        if tenant_id is None:
            async with self:
                self.is_loading_proposal = False
                self.proposal_error = _NO_TENANT
            return
        try:
            proposal_uuid = UUID(proposal_id)
        except ValueError:
            async with self:
                self.is_loading_proposal = False
                self.proposal_error = _PROPOSAL_GONE
            return
        try:
            proposal = await asyncio.to_thread(
                _get_proposal, tenant_id=tenant_id, proposal_id=proposal_uuid
            )
        except Exception as exc:
            logger.error("get_proposal failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_proposal = False
                self.proposal_error = _PROPOSAL_GONE
            return
        async with self:
            self.proposal = proposal
            self.edit_caption = proposal.caption
            self.is_loading_proposal = False

    @rx.event
    def start_edit(self) -> None:
        if self.proposal is None:
            return
        self.edit_caption = self.proposal.caption
        self.is_editing = True

    @rx.event
    def cancel_edit(self) -> None:
        self.is_editing = False

    @rx.event
    def set_edit_caption(self, value: str) -> None:
        self.edit_caption = value

    async def _decide_and_maybe_publish(
        self, *, decision: str, final_caption: str | None
    ) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            proposal_id = self._route_proposal_id()
            self.is_deciding = True
            self.action_error = ""
        tenant_id = await self._session_tenant_id()
        if tenant_id is None:
            async with self:
                self.is_deciding = False
                self.action_error = _NO_TENANT
            yield rx.toast.error(_NO_TENANT)
            return
        user_id = await asyncio.to_thread(acting_user_id, tenant_id)
        if user_id is None:
            async with self:
                self.is_deciding = False
                self.action_error = _NO_ACTING_USER
            yield rx.toast.error(_NO_ACTING_USER)
            return

        try:
            proposal_uuid = UUID(proposal_id)
            decided = await asyncio.to_thread(
                decide_proposal,
                tenant_id=tenant_id,
                proposal_id=proposal_uuid,
                decision=decision,
                final_caption=final_caption,
                decided_by_user_id=user_id,
            )
        except Exception as exc:
            logger.error("decide_proposal failed: %s", type(exc).__name__)
            async with self:
                self.is_deciding = False
                self.action_error = _DECIDE_FAILED
            yield rx.toast.error(_DECIDE_FAILED)
            return

        async with self:
            self.proposal = decided
            self.is_deciding = False
            self.is_editing = False

        if decision == "rejected":
            yield rx.toast.success("Propuesta rechazada.")
            return

        async with self:
            self.is_publishing_action = True
        try:
            published = await publish_proposal(tenant_id=tenant_id, proposal_id=proposal_uuid)
        except Exception as exc:
            logger.error("publish_proposal failed: %s", type(exc).__name__)
            async with self:
                self.is_publishing_action = False
                self.action_error = _PUBLISH_FAILED
            yield rx.toast.error(_PUBLISH_FAILED)
            return
        async with self:
            self.proposal = published
            self.is_publishing_action = False
        yield rx.toast.success("¡Aprobada! Publicando en Instagram…")

    @rx.event(background=True)
    async def approve_and_publish(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._decide_and_maybe_publish(decision="approved", final_caption=None):
            yield event

    @rx.event(background=True)
    async def save_and_publish(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            final_caption = self.edit_caption
        async for event in self._decide_and_maybe_publish(
            decision="edited", final_caption=final_caption
        ):
            yield event

    @rx.event(background=True)
    async def reject(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._decide_and_maybe_publish(decision="rejected", final_caption=None):
            yield event

    @rx.event(background=True)
    async def refresh_status(self) -> None:
        """The manual poll button — this slice does not auto-poll (v1 simplification,
        see the QUA-106 implementation notes): a Story publish can take minutes
        (`CONTAINER_POLL_INTERVAL_SECONDS`/`CEILING_SECONDS`, `publishing/client.py`),
        and the operator clicks "Actualizar estado" rather than this screen running an
        automatic timer loop."""
        async with self:
            proposal_id = self._route_proposal_id()
        tenant_id = await self._session_tenant_id()
        if tenant_id is None:
            return
        try:
            proposal_uuid = UUID(proposal_id)
            refreshed = await refresh_proposal(tenant_id=tenant_id, proposal_id=proposal_uuid)
        except Exception as exc:
            logger.error("refresh_proposal failed: %s", type(exc).__name__)
            return
        async with self:
            self.proposal = refreshed
