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
from .stories_vm import StoryProposalVM, TrendAudioOptionVM
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
    selected = StoriesState.selected_trend_audio_id == option.audio_id
    return rx.button(
        rx.cond(selected, rx.icon("circle-check", size=14), rx.icon("music", size=14)),
        option.display_label,
        variant=rx.cond(selected, "solid", "soft"),
        color_scheme="gray",
        size="2",
        on_click=StoriesState.select_trend_audio(option.audio_id, option.title),
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
            rx.flex(
                rx.foreach(StoriesState.trend_options, _trend_option),
                wrap="wrap",
                gap="2",
            ),
        ),
        width="100%",
        spacing="2",
        align_items="start",
    )


def _create_form() -> rx.Component:
    return card(
        rx.vstack(
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
