"""«Consultas desde comentarios» (m-24789646, PR 3): the second view of `/conversations`.

Each card is one commercial query found in Interacciones: who wrote it and on which post,
the intents detected (in the warning tone and «no fiable» when the class is not backed
by the golden set — the Interacciones rule), how the message would go out right now and
for how long, and the draft in an editable box. Nothing leaves without «Aprobar y
enviar»; when no route can reach the person the button is off and the card says why for
each route, an unverified capability included. Work in progress is the button's own
`loading`; content loading is a skeleton (docs/design-system.md §9.1). States are tones.

With `public_notice` on, a comment's card also shows the public notice (PR 4): a box to
include it and its text, editable, approved in the same click as the message. Without the
capability the block is not rendered at all.
"""

from __future__ import annotations

import reflex as rx

from .followups_state import FollowupsState
from .followups_vm import VIEW_MESSAGES, VIEW_QUERIES, FollowupCardVM, FollowupIntentVM
from .ui import callout, card, empty_state, skeleton_rows, tone_badge
from .ui import tokens as T

F = FollowupsState


def followups_toggle() -> rx.Component:
    return rx.segmented_control.root(
        rx.segmented_control.item("Mensajes", value=VIEW_MESSAGES),
        rx.segmented_control.item(F.toggle_label, value=VIEW_QUERIES),
        value=F.view,
        on_change=F.set_view,
        size="2",
        aria_label="Qué ver",
    )


def _intent_chip(chip: FollowupIntentVM) -> rx.Component:
    return rx.cond(
        chip.reliable,
        rx.cond(chip.commercial, tone_badge(chip.label, "info"), tone_badge(chip.label, "neutral")),
        rx.tooltip(
            tone_badge(chip.label + " · no fiable", "warn"),
            content=(
                "Esta clase todavía no alcanza la precisión mínima medida; "
                "revísala antes de actuar."
            ),
        ),
    )


def _origin(c: FollowupCardVM) -> rx.Component:
    where = rx.cond(
        c.permalink != "",
        rx.link(c.origin_label, href=c.permalink, is_external=True, size="1"),
        rx.text(c.origin_label, size="1", color=T.TEXT_MUTED),
    )
    return rx.vstack(
        rx.hstack(
            rx.avatar(fallback=c.initial, size="2", radius="full"),
            rx.vstack(
                rx.hstack(
                    rx.text(c.author, weight="medium", size="2"),
                    rx.text("·", size="1", color=T.TEXT_FAINT),
                    rx.text(c.posted_label, size="1", color=T.TEXT_MUTED),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                where,
                spacing="0",
            ),
            rx.spacer(),
            tone_badge(c.trigger_label, "neutral", icon="target"),
            width="100%",
            align="center",
            spacing="3",
        ),
        rx.cond(
            c.caption != "",
            rx.text("«" + c.caption + "»", size="1", color=T.TEXT_MUTED, font_style="italic"),
            rx.fragment(),
        ),
        rx.box(
            rx.text(c.comment_text, size="2"),
            padding="0.6rem 0.8rem",
            border_radius=T.RADIUS_CONTROL,
            background=T.SURFACE_BG_RAISED,
            width="100%",
        ),
        rx.cond(
            c.intents.length() > 0,
            rx.hstack(
                rx.icon("target", size=13, color=T.TEXT_FAINT),
                rx.foreach(c.intents, _intent_chip),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            rx.fragment(),
        ),
        spacing="2",
        width="100%",
    )


def _route(c: FollowupCardVM) -> rx.Component:
    return rx.cond(
        c.route_available,
        rx.hstack(
            rx.icon("send", size=T.ICON_SM, color=T.TEXT_MUTED),
            rx.text("Saldrá como ", rx.text.strong(c.route_label), size="1"),
            rx.cond(
                c.route_deadline != "",
                tone_badge(c.route_deadline, "info", icon="clock"),
                rx.fragment(),
            ),
            rx.tooltip(rx.icon("info", size=T.ICON_SM, color=T.TEXT_FAINT), content=c.route_note),
            spacing="2",
            align="center",
            wrap="wrap",
        ),
        rx.callout.root(
            rx.callout.icon(rx.icon("ban")),
            rx.vstack(
                rx.text("No disponible todavía: ahora no hay forma de escribirle.", size="1"),
                rx.foreach(c.blocked_reasons, lambda r: rx.text("• " + r, size="1")),
                spacing="1",
            ),
            variant="surface",
            size="1",
            width="100%",
            **T.tone_scheme("warn"),
        ),
    )


def _draft(c: FollowupCardVM) -> rx.Component:
    busy = F.busy_id == c.followup_id
    return rx.vstack(
        rx.hstack(
            rx.text("Borrador del mensaje privado", size="1", weight="medium"),
            rx.cond(
                c.needs_review,
                tone_badge("Requiere revisión", "warn", icon="triangle-alert"),
                rx.fragment(),
            ),
            spacing="2",
            align="center",
        ),
        rx.text_area(
            value=F.edits[c.followup_id],
            on_change=lambda text: F.set_edit(c.followup_id, text),
            placeholder=rx.cond(c.has_draft, "", "Sin borrador: escribe el mensaje o genera uno."),
            rows="4",
            max_length=1000,
            width="100%",
            disabled=busy,
        ),
        rx.cond(
            c.unsupported_claims.length() > 0,
            rx.vstack(
                rx.text("Confírmalo antes de enviar:", size="1", color=T.TEXT_MUTED),
                rx.foreach(c.unsupported_claims, lambda claim: rx.text("• " + claim, size="1")),
                spacing="1",
            ),
            rx.fragment(),
        ),
        spacing="2",
        width="100%",
    )


def _notice(c: FollowupCardVM) -> rx.Component:
    """The public notice under the comment (PR 4) — only when the card offers it."""
    busy = F.busy_id == c.followup_id
    on = F.notice_on[c.followup_id]
    return rx.cond(
        c.notice_available,
        rx.vstack(
            rx.hstack(
                rx.checkbox(
                    "Publicar también un aviso en el comentario",
                    checked=on,
                    on_change=lambda checked: F.set_notice_on(c.followup_id, checked),
                    size="2",
                    disabled=busy,
                ),
                rx.tooltip(
                    rx.icon("info", size=T.ICON_SM, color=T.TEXT_FAINT),
                    content=(
                        "Una respuesta pública al comentario. Se publica solo cuando el mensaje "
                        "privado salga; si no sale, no se publica."
                    ),
                ),
                spacing="2",
                align="center",
            ),
            rx.input(
                value=F.notice_edits[c.followup_id],
                on_change=lambda text: F.set_notice_edit(c.followup_id, text),
                max_length=300,
                width="100%",
                disabled=busy | ~on,
                aria_label="Texto del aviso público",
            ),
            spacing="2",
            width="100%",
        ),
        rx.fragment(),
    )


def _actions(c: FollowupCardVM) -> rx.Component:
    busy = F.busy_id == c.followup_id
    acting = F.busy_id != ""
    return rx.hstack(
        rx.cond(
            c.has_draft,
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_SM),
                "Regenerar",
                variant="soft",
                size="2",
                loading=busy & (F.busy_action == "regenerate"),
                disabled=acting,
                on_click=F.regenerate(c.followup_id),
            ),
            rx.button(
                rx.icon("sparkles", size=T.ICON_SM),
                "Generar borrador",
                variant="soft",
                size="2",
                loading=busy & (F.busy_action == "generate"),
                disabled=acting,
                on_click=F.generate(c.followup_id),
            ),
        ),
        rx.button(
            rx.icon("x", size=T.ICON_SM),
            "Descartar",
            variant="ghost",
            color_scheme="gray",
            size="2",
            loading=busy & (F.busy_action == "discard"),
            disabled=acting,
            on_click=F.discard(c.followup_id),
        ),
        rx.spacer(),
        rx.button(
            rx.icon("send", size=T.ICON_SM),
            "Aprobar y enviar",
            size="2",
            loading=busy & (F.busy_action == "approve"),
            disabled=acting | ~c.route_available,
            on_click=F.approve(c.followup_id),
        ),
        width="100%",
        align="center",
        wrap="wrap",
        spacing="2",
    )


def _card(c: FollowupCardVM) -> rx.Component:
    return card(
        rx.vstack(
            _origin(c), _route(c), _draft(c), _notice(c), _actions(c), spacing="3", width="100%"
        ),
        id="consulta-" + c.followup_id,
        border=rx.cond(
            F.highlight_id == c.followup_id, f"2px solid {T.tone_color('accent', 8)}", "none"
        ),
    )


def followups_panel() -> rx.Component:
    return rx.vstack(
        rx.cond(F.error != "", callout(F.error, "error"), rx.fragment()),
        rx.cond(
            ~F.loaded,
            skeleton_rows(3, height="12rem"),
            rx.cond(
                F.followups_count > 0,
                rx.vstack(rx.foreach(F.cards, _card), spacing="3", width="100%"),
                empty_state(
                    "messages-square",
                    "No hay consultas pendientes",
                    "Cuando «Analizar intención» encuentre una consulta comercial en los "
                    "comentarios, o pulses «Responder por DM» en Comentarios, aparecerá "
                    "aquí con un borrador para revisar.",
                ),
            ),
        ),
        spacing="3",
        width="100%",
    )
