"""The `/stories` screen (QUA-106 V1 redesign) — a single publish screen for
Instagram Stories, structurally the same as `/publish`: pick a connected account,
select one video (real thumbnail in the grid, reusing `ui/video_preview.py` exactly
as `/publish` does), hit "Publicar", poll until Meta settles. A panel of trending
content/audio (QUA-107 + Meta's `GET /ig_audio`) sits alongside the form, purely for
reference — no field here ever reaches the publish call.

No propuesta, no aprobación, no revisión, no historial: there is no second screen —
`/stories` is it, same as `/publish` is one screen for itself.
"""

from __future__ import annotations

import reflex as rx

from .stories_state import _UPLOAD_ID, StoriesState
from .stories_vm import TrendAudioOptionVM, TrendingVideoVM
from .ui import app_shell, callout, card, page_body, page_header, section
from .ui import tokens as T
from .ui.video_preview import gallery_preview_capture_anchor, video_frame_preview_src

_GALLERY_ROOT_ID = "stories-gallery-root"

# ---------------------------------------------------------------------------
# "Abrir en Instagram" -- Web Share API handoff (PoC validated on real
# Android + iPhone devices: `navigator.share` with the video File opens
# Instagram's own Story composer with the video pre-loaded and the Music
# sticker fully available). An ALTERNATIVE to "Publicar", never a step of it:
# Meta's Graph API cannot attach a native Music sticker to a Story
# (`audio_configuration` only ever applies to Reels), so this hands the video
# to the phone's OS share sheet instead, and the user finishes the post
# themselves inside Instagram. No connected account is needed for this path
# — it never touches Meta's Graph API.
#
# The video File itself never round-trips through Reflex state or the
# server: `ui/video_preview.py`'s existing drop/change capture listener
# (already mounted for the real-thumbnail feature) stashes the raw File at
# `window.__qualifyPreviews.lastFile`, and this script reads it directly —
# a Story is never a carousel, so "the last file dropped" is always exactly
# the one file currently in the gallery.
_SHARE_TO_INSTAGRAM_SCRIPT = """
(function () {
  try {
    // Desktop OS share panels (Windows' "Compartir", macOS' share sheet) may list
    // "Instagram" too, but Instagram there is web/desktop -- it never registers
    // itself to actually RECEIVE the shared file into a Story composer the way the
    // real Instagram mobile app does. Selecting it just drops the user on a plain
    // "select a story" screen with nothing attached (reported 2026-09-23 testing
    // from a Windows PC). Gating on the OS keeps that dead-end out of reach.
    var isMobileOS = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent || "");
    if (!isMobileOS) { return "desktop"; }
    if (!window.isSecureContext) { return "insecure"; }
    if (!navigator.share || !navigator.canShare) { return "unsupported"; }
    var file = window.__qualifyPreviews && window.__qualifyPreviews.lastFile;
    if (!file) { return "no_file"; }
    if (!navigator.canShare({ files: [file] })) { return "cannot_share_file"; }
    return navigator.share({ files: [file] }).then(
      function () { return "shared"; },
      function (err) {
        if (err && err.name === "AbortError") { return "cancelled"; }
        return "error:" + (err && err.message ? err.message : String(err));
      }
    );
  } catch (e) {
    return "error:" + (e && e.message ? e.message : String(e));
  }
})()
"""


def _connection_item(conn) -> rx.Component:
    return rx.select.item(conn.external_username + " · " + conn.platform, value=conn.id)


def _connection_selector() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(placeholder="Elige una cuenta conectada", width="100%"),
        rx.select.content(rx.foreach(StoriesState.connections, _connection_item)),
        value=StoriesState.selected_connection_id,
        on_change=StoriesState.select_connection,
        size="3",
        width="100%",
    )


def _connection_section() -> rx.Component:
    return section(
        "Cuenta",
        _connection_selector(),
        description="La cuenta de Instagram conectada donde se publicará la Story.",
    )


# ---------------------------------------------------------------------------
# Content gallery — one tile, real video-frame thumbnail (reused from /publish's
# `ui/video_preview.py`, unchanged), no "+" add tile since a Story is never a
# carousel: a second drop simply REPLACES the first (`StoriesState.add_file`).


def _pending_tile() -> rx.Component:
    """The one selected video, shown with a REAL first-frame thumbnail — same
    mechanism `publishing_page._pending_tile` uses (`video_frame_preview_src`,
    client-side only, no backend change), falling back to a film icon + filename
    while the frame has not been captured yet or never could be."""
    preview_src = video_frame_preview_src(filename=StoriesState.pending_filename)
    return rx.box(
        rx.cond(
            preview_src != "",
            rx.el.img(
                src=preview_src,
                alt=StoriesState.pending_filename,
                style={
                    "width": "100%",
                    "height": "100%",
                    "object_fit": "cover",
                    "display": "block",
                },
            ),
            rx.vstack(
                rx.icon("film", size=24, color=T.tone_color("ok", 9)),
                rx.text(
                    StoriesState.pending_filename,
                    size="1",
                    color=T.TEXT_MUTED,
                    width="100%",
                    text_align="center",
                    white_space="nowrap",
                    overflow="hidden",
                    text_overflow="ellipsis",
                ),
                spacing="1",
                align="center",
                justify="center",
                height="100%",
                padding="0.4rem",
            ),
        ),
        rx.button(
            rx.icon("x", size=14, color="white"),
            on_click=StoriesState.clear_file,
            disabled=~StoriesState.can_edit_gallery,
            title="Quitar este archivo",
            size="1",
            variant="solid",
            color_scheme="tomato",
            radius="full",
            position="absolute",
            top="0.25rem",
            right="0.25rem",
            width="1.6rem",
            height="1.6rem",
            padding="0",
            border=f"2px solid {T.CARD_BG}",
            box_shadow="0 1px 3px rgba(0, 0, 0, 0.35)",
            cursor="pointer",
            _hover={"background": rx.color("tomato", 10)},
        ),
        position="relative",
        width="8rem",
        height="8rem",
        overflow="hidden",
        border=f"1.5px solid {rx.color('grass', 7)}",
        border_radius=T.RADIUS_CARD,
        background=T.tone_color("ok", 2),
    )


def _empty_state_content() -> rx.Component:
    return rx.vstack(
        rx.icon("film", size=32, color=T.TEXT_FAINT),
        rx.text(
            "Arrastra el video de la Story aquí o haz clic para elegirlo",
            size="3",
            weight="medium",
        ),
        rx.text("MP4 o MOV · hasta 300 MB", size="1", color=T.TEXT_MUTED),
        spacing="2",
        align="center",
    )


def _upload_widget(children: rx.Component, *, compact: bool) -> rx.Component:
    return rx.upload(
        children,
        id=_UPLOAD_ID,
        accept={"video/mp4": [".mp4"], "video/quicktime": [".mov"]},
        multiple=False,
        max_files=1,
        disabled=~StoriesState.can_edit_gallery,
        on_drop=StoriesState.add_file,
        on_drop_rejected=rx.toast.error(
            "Formato no permitido", description="Solo se aceptan archivos MP4 o MOV."
        ),
        border=f"1.5px dashed {rx.color('gray', 7)}",
        border_radius=T.RADIUS_CARD,
        background=T.CARD_BG,
        width="8rem" if compact else "100%",
        height="8rem" if compact else "auto",
        padding="0" if compact else "2.5rem 1.5rem",
        display="flex",
        align_items="center",
        justify_content="center",
        transition=f"border-color {T.DUR_FAST} {T.EASE}, background {T.DUR_FAST} {T.EASE}",
        _hover={"border_color": rx.color("accent", 8), "background": T.tone_color("accent", 2)},
    )


def _preview_capture_anchor() -> rx.Component:
    """Mounted UNCONDITIONALLY — see `publishing_page._preview_capture_anchor`'s
    docstring for why: without this, a video dropped while the empty-state prompt is
    still showing (always true for the FIRST file) never gets a real thumbnail."""
    return rx.box(gallery_preview_capture_anchor(root_id=_GALLERY_ROOT_ID), display="none")


def _gallery_zone() -> rx.Component:
    return rx.box(
        _preview_capture_anchor(),
        rx.cond(
            StoriesState.pending_filename != "",
            rx.flex(_pending_tile(), wrap="wrap", gap="0.75rem", width="100%"),
            _upload_widget(_empty_state_content(), compact=False),
        ),
        id=_GALLERY_ROOT_ID,
        width="100%",
    )


def _content_section() -> rx.Component:
    return section(
        "Video de la Story",
        _gallery_zone(),
        description="Tu propio video — nunca se genera ni se reutiliza contenido de terceros.",
    )


# ---------------------------------------------------------------------------
# Meta trending-audio reference (`GET /ig_audio`) — informational only.


def _trend_option(option: TrendAudioOptionVM) -> rx.Component:
    """One row of the compact Meta audio list — title first (primary), artist and
    duration secondary, the whole row clickable. Deliberately a plain list row, not
    a card: no border box, no thumbnail (Meta's `ig_audio` never carries cover art).

    The play button is a SIBLING of the selection button, never nested inside it —
    a `<button>` cannot contain another `<button>` per the HTML5 spec."""
    selected = StoriesState.selected_trend_audio_id == option.audio_id
    is_playing_this = (
        StoriesState.playing_audio_id == option.audio_id
    ) & StoriesState.is_audio_playing
    return rx.hstack(
        rx.box(
            rx.cond(
                option.has_preview,
                rx.button(
                    rx.cond(is_playing_this, rx.icon("pause", size=12), rx.icon("play", size=12)),
                    variant="ghost",
                    color_scheme=rx.cond(is_playing_this, "iris", "gray"),
                    size="1",
                    on_click=StoriesState.toggle_audio_preview(option.audio_id, option.preview_url),
                ),
            ),
            width="1.75rem",
            flex_shrink="0",
        ),
        rx.button(
            rx.hstack(
                rx.cond(
                    selected,
                    rx.icon("circle-check", size=14, color=rx.color("iris", 9), flex_shrink="0"),
                    rx.icon("music", size=14, color=T.TEXT_FAINT, flex_shrink="0"),
                ),
                rx.vstack(
                    rx.text(option.title, size="2", weight="medium"),
                    rx.cond(
                        option.artist_or_creator != "",
                        rx.text(option.artist_or_creator, size="1", color=T.TEXT_MUTED),
                    ),
                    align_items="start",
                    spacing="0",
                ),
                rx.spacer(),
                rx.cond(
                    option.duration_label != "",
                    rx.text(option.duration_label, size="1", color=T.TEXT_FAINT, flex_shrink="0"),
                ),
                align="center",
                spacing="3",
                width="100%",
                padding_right="0.5rem",
            ),
            variant="ghost",
            color_scheme=rx.cond(selected, "iris", "gray"),
            background=rx.cond(selected, rx.color("iris", 3), "transparent"),
            border_radius="0",
            size="2",
            width="100%",
            on_click=StoriesState.select_trend_audio(option.audio_id, option.title),
        ),
        align="center",
        spacing="0",
        width="100%",
        padding_right="0.5rem",
        border_bottom=f"1px solid {rx.color('gray', 4)}",
    )


def _trend_audio_section() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.button(
                rx.icon("sparkles", size=14),
                "Sugerir audio en tendencia",
                variant="soft",
                size="2",
                loading=StoriesState.is_loading_trend,
                disabled=StoriesState.selected_connection_id == "",
                on_click=StoriesState.suggest_audio,
            ),
            rx.cond(
                StoriesState.selected_trend_audio_id != "",
                rx.badge(
                    StoriesState.selected_trend_audio_title,
                    rx.icon("x", size=12, on_click=StoriesState.clear_trend_audio),
                    variant="soft",
                    color_scheme="iris",
                    size="2",
                ),
            ),
            align="center",
            spacing="2",
            wrap="wrap",
        ),
        rx.hstack(
            rx.input(
                rx.input.slot(rx.icon("search", size=14)),
                placeholder="Buscar audio por nombre o artista…",
                value=StoriesState.audio_search_query,
                on_change=StoriesState.set_audio_search_query,
                disabled=StoriesState.selected_connection_id == "",
                size="2",
                width="100%",
            ),
            rx.button(
                "Buscar",
                variant="soft",
                size="2",
                loading=StoriesState.is_loading_trend,
                disabled=StoriesState.selected_connection_id == "",
                on_click=StoriesState.search_audio,
            ),
            align="center",
            spacing="2",
            width="100%",
        ),
        rx.text(
            "Solo una referencia para ti — no se adjunta a la publicación.",
            size="1",
            color=T.TEXT_FAINT,
        ),
        rx.cond(
            StoriesState.trend_expanded & (StoriesState.trend_options.length() > 0),
            rx.vstack(
                rx.hstack(
                    rx.text("Resultados", size="1", weight="medium", color=T.TEXT_MUTED),
                    rx.spacer(),
                    rx.button(
                        rx.icon("x", size=12),
                        "Ocultar",
                        variant="soft",
                        color_scheme="gray",
                        size="1",
                        on_click=StoriesState.close_trend_audio,
                    ),
                    align="center",
                    width="100%",
                    padding_bottom="0.25rem",
                ),
                rx.foreach(StoriesState.trend_options, _trend_option),
                spacing="0",
                width="100%",
            ),
        ),
        width="100%",
        spacing="2",
        align_items="start",
    )


# ---------------------------------------------------------------------------
# QUA-107: ScrapeCreators trending discovery — TikTok + Instagram, reference only.
# Independent of the connection selector above: these buttons are never disabled by
# `selected_connection_id`, unlike `_trend_audio_section`'s Meta-backed suggestion.


def _trending_thumbnail(candidate: TrendingVideoVM) -> rx.Component:
    return rx.cond(
        candidate.has_thumbnail,
        rx.image(
            src=candidate.thumbnail_url,
            width="56px",
            height="56px",
            object_fit="cover",
            border_radius="0.5rem",
            flex_shrink="0",
        ),
        rx.center(
            rx.icon("film", size=20, color=T.TEXT_FAINT),
            width="56px",
            height="56px",
            border_radius="0.5rem",
            background=T.SURFACE_BG_RAISED,
            flex_shrink="0",
        ),
    )


def _song_detail_panel() -> rx.Component:
    """Renders `StoriesState.song_detail` — only mounted once it is non-`None` (see
    `_trending_video_card`'s guard), so no field here needs its own None-check
    besides `user_count`/`recommend_status`, which the vendor may omit."""
    detail = StoriesState.song_detail
    is_playing_this = (
        StoriesState.playing_audio_id == detail.audio_id
    ) & StoriesState.is_audio_playing
    return rx.vstack(
        rx.text(detail.display_label, size="2", weight="medium"),
        rx.cond(
            detail.has_preview,
            rx.hstack(
                rx.button(
                    rx.cond(is_playing_this, rx.icon("pause", size=12), rx.icon("play", size=12)),
                    variant="soft",
                    color_scheme=rx.cond(is_playing_this, "iris", "gray"),
                    size="1",
                    on_click=StoriesState.toggle_audio_preview(detail.audio_id, detail.preview_url),
                ),
                rx.text("Escuchar preview", size="1", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
        ),
        rx.cond(
            detail.has_user_count,
            rx.hstack(
                rx.icon("users", size=12, color=T.TEXT_FAINT),
                rx.text(detail.user_count, " videos la usan", size="1", color=T.TEXT_MUTED),
                spacing="1",
            ),
        ),
        rx.cond(
            detail.has_recommend_status,
            rx.hstack(
                rx.icon("flame", size=12, color=T.TEXT_FAINT),
                rx.text(
                    "Puntaje de tendencia del vendor: ",
                    detail.recommend_status,
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                spacing="1",
            ),
        ),
        rx.hstack(
            rx.button(
                "Usar esta canción",
                size="1",
                variant="soft",
                color_scheme="iris",
                on_click=StoriesState.select_trend_audio(detail.audio_id, detail.title),
            ),
            rx.button(
                rx.icon("search", size=12),
                "Buscar en Meta",
                size="1",
                variant="soft",
                color_scheme="gray",
                disabled=StoriesState.selected_connection_id == "",
                loading=StoriesState.is_loading_trend,
                on_click=StoriesState.search_song_on_meta(detail.title),
            ),
            spacing="2",
            wrap="wrap",
        ),
        spacing="2",
        padding="0.5rem",
        background=T.SURFACE_BG_RAISED,
        border_radius="0.5rem",
        align_items="start",
        width="100%",
    )


def _trending_video_card(candidate: TrendingVideoVM) -> rx.Component:
    is_expanded = StoriesState.expanded_song_id == candidate.music_id
    return rx.box(
        rx.hstack(
            _trending_thumbnail(candidate),
            rx.vstack(
                rx.text(
                    rx.cond(candidate.caption != "", candidate.caption, "(sin descripción)"),
                    size="2",
                    weight="medium",
                    max_width="360px",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                rx.text(candidate.author_label, size="1", color=T.TEXT_MUTED),
                rx.hstack(
                    rx.text("♥ ", candidate.likes_label, size="1", color=T.TEXT_FAINT),
                    rx.text("💬 ", candidate.comments_label, size="1", color=T.TEXT_FAINT),
                    rx.cond(
                        candidate.plays_label != "",
                        rx.text("▶ ", candidate.plays_label, size="1", color=T.TEXT_FAINT),
                    ),
                    spacing="3",
                ),
                rx.cond(
                    candidate.permalink != "",
                    rx.link("Ver original", href=candidate.permalink, target="_blank", size="1"),
                ),
                align_items="start",
                spacing="1",
            ),
            align_items="start",
            spacing="3",
            width="100%",
        ),
        rx.box(
            rx.cond(
                candidate.has_music,
                rx.vstack(
                    rx.button(
                        "Ver detalle de la canción",
                        variant="ghost",
                        size="1",
                        loading=is_expanded & StoriesState.is_loading_song_detail,
                        on_click=StoriesState.expand_song(
                            candidate.music_id, candidate.music_title
                        ),
                    ),
                    rx.cond(
                        is_expanded,
                        rx.cond(StoriesState.song_detail, _song_detail_panel()),
                    ),
                    spacing="1",
                    width="100%",
                ),
            ),
            min_height="2.25rem",
            margin_top="0.5rem",
            width="100%",
        ),
        padding="0.75rem",
        border=f"1px solid {rx.color('gray', 5)}",
        border_radius=T.RADIUS_CARD,
        width="100%",
    )


def _trending_platform_section(
    *,
    label: str,
    icon: str,
    items: rx.Var[list[TrendingVideoVM]],
    expanded: rx.Var[bool],
    is_loading: rx.Var[bool],
    on_toggle: rx.event.EventHandler,
    on_refresh: rx.event.EventHandler,
) -> rx.Component:
    """One platform's trending block, full width — stacked with its sibling below
    (never a side-by-side column) precisely because a TikTok card can expand a song
    detail panel inline and an Instagram one never does (Reels carry no music), so
    two columns of these next to each other drift out of alignment the moment one
    expands. Stacking removes the "must match height" problem structurally instead
    of bounding it with a fixed/scrollable height.

    The main button drives fetch AND collapse/expand (follow-up: "cómo cierro
    esto") — `on_toggle` never re-fetches once `items` is already cached, only the
    very first click per platform does. The separate refresh icon (follow-up: "cómo
    actualizo") ALWAYS re-fetches, bypassing that cache — it only appears once there
    is something to refresh."""
    return rx.vstack(
        rx.hstack(
            rx.button(
                rx.icon(icon, size=14),
                label,
                rx.cond(
                    items.length() > 0,
                    rx.icon(rx.cond(expanded, "chevron-up", "chevron-down"), size=14),
                    rx.fragment(),
                ),
                variant="soft",
                size="2",
                loading=is_loading,
                on_click=on_toggle,
            ),
            rx.cond(
                items.length() > 0,
                rx.icon_button(
                    rx.icon("refresh-cw", size=14),
                    variant="ghost",
                    color_scheme="gray",
                    size="2",
                    loading=is_loading,
                    title="Actualizar con contenido nuevo",
                    on_click=on_refresh,
                ),
                rx.fragment(),
            ),
            align="center",
            spacing="2",
        ),
        rx.cond(
            expanded & (items.length() > 0),
            rx.vstack(rx.foreach(items, _trending_video_card), spacing="2", width="100%"),
        ),
        width="100%",
        spacing="2",
        align_items="start",
    )


def _trending_discovery_section() -> rx.Component:
    """QUA-107: TikTok + Instagram trending, shown for reference only. Explicit,
    operator-triggered per platform — never fetched on screen load."""
    return rx.vstack(
        rx.text(
            "Contenido y audios en tendencia, de forma general — no representa "
            "exclusivamente una región ni tu país. Solo referencia visual: nada se "
            "descarga ni se adjunta automáticamente a la Story.",
            size="1",
            color=T.TEXT_FAINT,
        ),
        _trending_platform_section(
            label="Tendencia en TikTok",
            icon="music",
            items=StoriesState.tiktok_trending,
            expanded=StoriesState.tiktok_trending_expanded,
            is_loading=StoriesState.is_loading_tiktok_trending,
            on_toggle=StoriesState.toggle_tiktok_trending,
            on_refresh=StoriesState.discover_tiktok_trending,
        ),
        rx.divider(),
        _trending_platform_section(
            label="Tendencia en Instagram",
            icon="film",
            items=StoriesState.instagram_trending,
            expanded=StoriesState.instagram_trending_expanded,
            is_loading=StoriesState.is_loading_instagram_trending,
            on_toggle=StoriesState.toggle_instagram_trending,
            on_refresh=StoriesState.discover_instagram_trending,
        ),
        width="100%",
        spacing="3",
    )


def _audio_preview_player() -> rx.Component:
    """The ONE shared player behind every play/pause button on this screen (Meta's
    audio list and the TikTok song-detail panel) — driven entirely by
    `playing_audio_url`/`is_audio_playing`, so only one preview is ever sounding at
    a time."""
    return rx.box(
        rx.audio(
            src=StoriesState.playing_audio_url,
            playing=StoriesState.is_audio_playing,
            controls=False,
            on_ended=StoriesState.audio_preview_stopped,
            on_error=StoriesState.audio_preview_stopped,
        ),
        display="none",
    )


def _trending_card() -> rx.Component:
    return card(
        rx.vstack(
            _audio_preview_player(),
            rx.hstack(
                rx.icon("sparkles", size=T.ICON_MD, color=T.tone_color("info", 9)),
                rx.heading("Tendencias e inspiración", size="3", as_="h2"),
                spacing="2",
                align="center",
            ),
            rx.divider(),
            section("Audio en tendencia (Meta)", _trend_audio_section()),
            rx.divider(),
            section("Contenido en tendencia", _trending_discovery_section()),
            spacing="4",
            align_items="stretch",
            width="100%",
        ),
        padding="1.5rem",
    )


# ---------------------------------------------------------------------------
# Publish form + status — same shape `publishing_page.py` uses for `/publish`.


def _status_block() -> rx.Component:
    return rx.match(
        StoriesState.phase,
        (
            "staging_and_starting",
            rx.callout(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text("Subiendo el video y arrancando la publicación...", size="2"),
                    spacing="2",
                    align="center",
                ),
                color_scheme="gray",
                width="100%",
            ),
        ),
        (
            "polling",
            rx.callout(
                rx.vstack(
                    rx.hstack(
                        rx.spinner(size="2"),
                        rx.text(
                            "Publicando, esperando confirmación de Meta...",
                            size="2",
                            weight="medium",
                        ),
                        rx.cond(
                            StoriesState.elapsed_label != "",
                            rx.text(
                                StoriesState.elapsed_label,
                                size="1",
                                color=T.TEXT_FAINT,
                                font_family="monospace",
                            ),
                            rx.fragment(),
                        ),
                        spacing="2",
                        align="center",
                        width="100%",
                    ),
                    rx.text(
                        "Meta está procesando la Story. Esto puede tardar varios minutos.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                icon="clock",
                color_scheme="amber",
                width="100%",
            ),
        ),
        (
            "failure",
            rx.callout(
                StoriesState.error, icon="triangle-alert", color_scheme="tomato", width="100%"
            ),
        ),
        rx.fragment(),
    )


def _publish_button() -> rx.Component:
    return rx.button(
        rx.icon("send", size=16),
        "Publicar",
        on_click=StoriesState.publish(),
        disabled=~StoriesState.can_publish,
        size="3",
        width="100%",
    )


def _share_to_instagram_button() -> rx.Component:
    """Alternative to `_publish_button` — see the module-level comment above
    `_SHARE_TO_INSTAGRAM_SCRIPT` for why this exists and what it does. Gated only
    on having a video selected: unlike "Publicar", it needs no connected account."""
    return rx.button(
        rx.icon("share-2", size=16),
        "Abrir en Instagram",
        on_click=rx.call_script(
            _SHARE_TO_INSTAGRAM_SCRIPT, callback=StoriesState.handle_share_result
        ),
        disabled=StoriesState.pending_filename == "",
        variant="soft",
        size="3",
        width="100%",
    )


def _form_card() -> rx.Component:
    return card(
        rx.vstack(
            _connection_section(),
            rx.divider(),
            _content_section(),
            rx.divider(),
            rx.vstack(
                _publish_button(),
                rx.hstack(
                    rx.divider(flex_grow="1"),
                    rx.text("o", size="1", color=T.TEXT_FAINT),
                    rx.divider(flex_grow="1"),
                    align="center",
                    width="100%",
                    spacing="2",
                ),
                _share_to_instagram_button(),
                rx.text(
                    "Te permite seleccionar música oficial y personalizar tu historia "
                    "desde la app.",
                    size="1",
                    color=T.TEXT_FAINT,
                ),
                _status_block(),
                spacing="3",
                width="100%",
                align_items="stretch",
            ),
            spacing="5",
            align_items="stretch",
            width="100%",
        ),
        padding="2rem",
    )


def _connections_error() -> rx.Component:
    return callout(StoriesState.connections_error, tone="error")


def stories_index() -> rx.Component:
    return app_shell(
        page_header(
            "Stories",
            "Sube tu video, mira tendencias como referencia, y publícalo directo en Instagram",
        ),
        page_body(
            rx.cond(StoriesState.connections_error != "", _connections_error(), rx.fragment()),
            rx.vstack(
                _form_card(),
                _trending_card(),
                spacing="5",
                width="100%",
                align_items="stretch",
            ),
        ),
    )
