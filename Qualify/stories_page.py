"""The Stories screens (QUA-106): `/stories` (propose + review queue, list route,
same nav zone/pattern as `/drafts`) and `/stories/[proposal_id]` (the mandatory
approval gate, detail route — mirrors `/drafts/[draft_id]`'s list+detail split rather
than bolting onto `/publish`, which has no queue/list capability to bolt onto — see
the QUA-106 plan for why).

Video only in this slice (`.mp4`/`.mov`) — no gallery, no carousel, one file per
proposal. The caption is always typed/edited by the operator; the "sugerir audio"
panel shows Meta's own trending list as a REFERENCE only, never attached to Meta's
publish call (`audio_configuration` is out of scope).
"""

from __future__ import annotations

import reflex as rx

from .stories_state import StoriesState
from .stories_vm import StoryProposalVM, TrendAudioOptionVM, TrendingVideoVM
from .ui import app_shell, callout, card, empty_state, page_body, page_header, section
from .ui import tokens as T
from .ui.primitives import skeleton_rows, tone_badge

_UPLOAD_ID = "story_upload"


def _screen(title: str, subtitle: str, *children: rx.Component) -> rx.Component:
    return app_shell(page_header(title, subtitle), page_body(*children))


# ---------------------------------------------------------------------------
# /stories — propose + queue


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


def _upload_zone() -> rx.Component:
    return rx.vstack(
        rx.upload(
            rx.vstack(
                rx.icon("film", size=T.ICON_LG, color=T.TEXT_FAINT),
                rx.text(
                    rx.cond(
                        StoriesState.pending_filename != "",
                        StoriesState.pending_filename,
                        "Arrastra un video (MP4/MOV) o haz clic para elegirlo",
                    ),
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
                align="center",
            ),
            id=_UPLOAD_ID,
            accept={"video/mp4": [".mp4"], "video/quicktime": [".mov"]},
            multiple=False,
            max_files=1,
            disabled=StoriesState.create_phase == "staging",
            on_drop=StoriesState.add_file,
            on_drop_rejected=rx.toast.error(
                "Formato no permitido", description="Solo se aceptan archivos MP4 o MOV."
            ),
            border=f"1.5px dashed {rx.color('gray', 7)}",
            border_radius=T.RADIUS_CARD,
            background=T.CARD_BG,
            padding="2rem",
            width="100%",
            cursor="pointer",
        ),
        rx.cond(
            StoriesState.pending_filename != "",
            rx.button(
                "Quitar archivo",
                variant="soft",
                color_scheme="gray",
                size="1",
                on_click=StoriesState.clear_file,
            ),
        ),
        width="100%",
        spacing="2",
    )


def _trend_option(option: TrendAudioOptionVM) -> rx.Component:
    """One row of the compact Meta audio list — title first (primary), artist and
    duration secondary, the whole row clickable. Deliberately a plain list row, not
    a card: no border box, no thumbnail (Meta's `ig_audio` never carries cover art —
    nothing here is invented to fill that gap), so it reads as a distinct component
    from the TikTok/Instagram trending cards next to it, not a restyled duplicate.

    The play button (QUA-107 follow-up) is a SIBLING of the selection button, never
    nested inside it — a `<button>` cannot contain another `<button>` per the HTML5
    spec; browsers close the outer one early and the layout breaks. Two buttons
    side by side in one row keeps "escuchar" and "seleccionar" independent, exactly
    as decided, with no `stop_propagation` trick needed."""
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
            ),
            # `ghost` + a tinted background only when selected — a subtle state,
            # never a solid button or a heavy badge (explicit product decision).
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
        rx.text(
            "Solo una referencia para ti — no se adjunta a la publicación.",
            size="1",
            color=T.TEXT_FAINT,
        ),
        rx.cond(
            StoriesState.trend_options.length() > 0,
            rx.vstack(
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
# Independent of the connection selector above (see `stories_state.py`'s module
# docstring): these buttons are never disabled by `selected_connection_id`, unlike
# `_trend_audio_section`'s Meta-backed suggestion.


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
        rx.button(
            "Usar esta canción",
            size="1",
            variant="soft",
            color_scheme="iris",
            on_click=StoriesState.select_trend_audio(detail.audio_id, detail.title),
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
            # Reserves the same vertical space whether or not this candidate has
            # music — Instagram Reels never do (`has_music` is always False there),
            # and without this fixed slot their cards render visibly shorter than
            # TikTok's, which was reported as an inconsistent grid.
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


def _trending_platform_column(
    *,
    label: str,
    icon: str,
    items: rx.Var[list[TrendingVideoVM]],
    is_loading: rx.Var[bool],
    on_discover: rx.event.EventHandler,
) -> rx.Component:
    return rx.vstack(
        rx.button(
            rx.icon(icon, size=14),
            label,
            variant="soft",
            size="2",
            loading=is_loading,
            on_click=on_discover,
        ),
        rx.cond(
            items.length() > 0,
            rx.vstack(rx.foreach(items, _trending_video_card), spacing="2", width="100%"),
        ),
        width="100%",
        spacing="2",
        align_items="start",
    )


def _trending_discovery_section() -> rx.Component:
    """QUA-107: TikTok + Instagram trending, shown for reference only. Explicit,
    operator-triggered per platform — never fetched on screen load. `region=US` is a
    fixed technical parameter for the TikTok call, never a claim about geography (see
    `scrapecreators_trending.DEFAULT_TIKTOK_REGION` — measured live 2026-09-21 to not
    reliably filter by country), hence the disclaimer below."""
    return rx.vstack(
        rx.text(
            "Contenido y audios en tendencia, de forma general — no representa "
            "exclusivamente una región ni tu país. Solo referencia visual: nada se "
            "descarga ni se adjunta automáticamente a la Story.",
            size="1",
            color=T.TEXT_FAINT,
        ),
        rx.grid(
            _trending_platform_column(
                label="Descubrir tendencia en TikTok",
                icon="music",
                items=StoriesState.tiktok_trending,
                is_loading=StoriesState.is_loading_tiktok_trending,
                on_discover=StoriesState.discover_tiktok_trending,
            ),
            _trending_platform_column(
                label="Descubrir tendencia en Instagram",
                icon="film",
                items=StoriesState.instagram_trending,
                is_loading=StoriesState.is_loading_instagram_trending,
                on_discover=StoriesState.discover_instagram_trending,
            ),
            columns=rx.breakpoints(initial="1", sm="2"),
            spacing="4",
            width="100%",
        ),
        width="100%",
        spacing="3",
    )


def _audio_preview_player() -> rx.Component:
    """The ONE shared player behind every play/pause button on this screen (Meta's
    audio list and the TikTok song-detail panel) — driven entirely by
    `playing_audio_url`/`is_audio_playing`, so only one preview is ever sounding at
    a time and no row mounts its own `<audio>` element. `on_error` degrades exactly
    like `on_ended`: an expired/unavailable preview URL stops cleanly instead of
    leaving a ⏸ icon showing sound that stopped playing on its own."""
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


def _create_form() -> rx.Component:
    return card(
        rx.vstack(
            _audio_preview_player(),
            section("Cuenta", _connection_selector()),
            rx.divider(),
            section("Video de la Story", _upload_zone()),
            rx.divider(),
            section(
                "Caption",
                rx.text_area(
                    placeholder="Escribe el caption (editable en cualquier momento)…",
                    value=StoriesState.caption,
                    on_change=StoriesState.set_caption,
                    width="100%",
                    rows="3",
                ),
                rx.text(
                    "Instagram no muestra texto en Stories publicadas mediante la API. "
                    "Esta nota solo se guarda como referencia.",
                    size="1",
                    color=T.TEXT_FAINT,
                ),
            ),
            rx.divider(),
            section("Audio en tendencia (opcional)", _trend_audio_section()),
            rx.divider(),
            section("Contenido en tendencia (opcional)", _trending_discovery_section()),
            rx.cond(
                StoriesState.create_error != "",
                callout(StoriesState.create_error, tone="error"),
            ),
            rx.button(
                "Crear propuesta",
                size="3",
                loading=StoriesState.create_phase == "staging",
                disabled=~StoriesState.can_create,
                on_click=StoriesState.create_proposal,
            ),
            spacing="4",
            align_items="stretch",
            width="100%",
        ),
        padding="2rem",
    )


def _proposal_row(proposal: StoryProposalVM) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.link(
                rx.cond(proposal.caption != "", proposal.caption, "(sin caption)"),
                href="/stories/" + proposal.id,
            )
        ),
        rx.table.cell(tone_badge(proposal.status_label, proposal.status_tone)),
        rx.table.cell(proposal.created_label, color=T.TEXT_MUTED),
    )


def _proposals_list() -> rx.Component:
    return section(
        "Propuestas",
        "Cada Story propuesta espera tu revisión — nada se publica sin aprobación humana.",
        rx.cond(
            StoriesState.proposals_error != "",
            callout(StoriesState.proposals_error, tone="error"),
        ),
        rx.cond(
            StoriesState.is_loading_proposals,
            skeleton_rows(3),
            rx.cond(
                StoriesState.proposals.length() > 0,
                rx.box(
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("Caption"),
                                rx.table.column_header_cell("Estado"),
                                rx.table.column_header_cell("Creada"),
                            )
                        ),
                        rx.table.body(rx.foreach(StoriesState.proposals, _proposal_row)),
                        variant="surface",
                        width="100%",
                    ),
                    overflow_x="auto",
                    width="100%",
                ),
                empty_state(
                    "film",
                    "Todavía no hay propuestas",
                    "Sube un video y crea la primera propuesta de Story arriba.",
                ),
            ),
        ),
    )


def stories_index() -> rx.Component:
    return _screen(
        "Stories",
        "Propone una Story con contenido/trending y apruébala antes de publicar",
        rx.cond(
            StoriesState.connections_error != "",
            callout(StoriesState.connections_error, tone="error"),
        ),
        _create_form(),
        _proposals_list(),
    )


# ---------------------------------------------------------------------------
# /stories/[proposal_id] — the mandatory approval gate


def _detail_actions(proposal: StoryProposalVM) -> rx.Component:
    return rx.cond(
        proposal.can_decide,
        rx.cond(
            StoriesState.is_editing,
            rx.vstack(
                rx.text_area(
                    value=StoriesState.edit_caption,
                    on_change=StoriesState.set_edit_caption,
                    width="100%",
                    rows="3",
                ),
                rx.hstack(
                    rx.button(
                        "Guardar y publicar",
                        size="3",
                        loading=StoriesState.is_deciding | StoriesState.is_publishing_action,
                        on_click=StoriesState.save_and_publish,
                    ),
                    rx.button(
                        "Cancelar",
                        variant="soft",
                        color_scheme="gray",
                        size="3",
                        on_click=StoriesState.cancel_edit,
                    ),
                    spacing="3",
                ),
                spacing="3",
                width="100%",
                align_items="stretch",
            ),
            rx.hstack(
                rx.button(
                    rx.icon("check", size=16),
                    "Aprobar y publicar",
                    size="3",
                    loading=StoriesState.is_deciding | StoriesState.is_publishing_action,
                    on_click=StoriesState.approve_and_publish,
                ),
                rx.button(
                    rx.icon("pencil", size=16),
                    "Editar caption",
                    variant="soft",
                    size="3",
                    on_click=StoriesState.start_edit,
                ),
                rx.button(
                    rx.icon("x", size=16),
                    "Rechazar",
                    variant="soft",
                    color_scheme="tomato",
                    size="3",
                    loading=StoriesState.is_deciding,
                    on_click=StoriesState.reject,
                ),
                spacing="3",
                wrap="wrap",
            ),
        ),
        rx.cond(
            proposal.is_publishing,
            rx.hstack(
                rx.spinner(size="2"),
                rx.text("Meta está procesando la publicación. Esto puede tardar varios minutos."),
                rx.button(
                    "Actualizar estado",
                    variant="soft",
                    size="2",
                    on_click=StoriesState.refresh_status,
                ),
                align="center",
                spacing="3",
                wrap="wrap",
            ),
            rx.fragment(),
        ),
    )


def _detail_card(proposal: StoryProposalVM) -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                rx.heading("Propuesta de Story", size="5", as_="h2"),
                tone_badge(proposal.status_label, proposal.status_tone),
                align="center",
                spacing="3",
            ),
            rx.divider(),
            section(
                "Caption",
                rx.text(rx.cond(proposal.caption != "", proposal.caption, "(sin caption)")),
                rx.text(
                    "Instagram no muestra texto en Stories publicadas mediante la API. "
                    "Esta nota solo se guarda como referencia.",
                    size="1",
                    color=T.TEXT_FAINT,
                ),
            ),
            rx.cond(
                proposal.has_trend_audio,
                section(
                    "Audio de referencia",
                    rx.hstack(
                        rx.icon("music", size=14),
                        rx.text(proposal.trend_audio_title),
                        align="center",
                        spacing="2",
                    ),
                ),
            ),
            rx.cond(
                proposal.publish_error_code != "",
                callout("La publicación falló: " + proposal.publish_error_code, tone="error"),
            ),
            rx.cond(
                StoriesState.action_error != "",
                callout(StoriesState.action_error, tone="error"),
            ),
            rx.divider(),
            _detail_actions(proposal),
            spacing="4",
            align_items="stretch",
            width="100%",
        ),
        padding="2rem",
    )


def story_detail_index() -> rx.Component:
    return _screen(
        "Propuesta de Story",
        "Revisa el contenido antes de aprobar — nada se publica sin tu decisión",
        rx.cond(
            StoriesState.is_loading_proposal,
            skeleton_rows(4),
            rx.cond(
                StoriesState.proposal_error != "",
                callout(StoriesState.proposal_error, tone="error"),
                rx.cond(
                    StoriesState.proposal,
                    _detail_card(StoriesState.proposal),
                    rx.fragment(),
                ),
            ),
        ),
    )
