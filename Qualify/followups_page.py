"""«Consultas desde comentarios» (m-24789646, PR 3): the «Quieren comprar» tab of
`/responder` (and the second view of the legacy `/conversations`).

Each card is one commercial query found in Interacciones: who wrote it and on which post,
the intents detected (in the warning tone and «revísalo» when the class is not backed
by the golden set — the Interacciones rule), how the message would go out right now and
for how long, and the draft in an editable box. Nothing leaves without «Aprobar y
enviar»; when no route can reach the person the button is off and the card says why for
each route, an unverified capability included. Work in progress is the button's own
`loading`; content loading is a skeleton (docs/design-system.md §9.1). States are tones.

With `public_notice` on, a comment's card also shows the public notice (PR 4): a box to
include it and its text, editable, approved in the same click as the message. Without the
capability the block is not rendered at all.

**Three steps** (m-24842991, ATENDER-6, guide N3/N6/N12): ① «Qué preguntó» (who, where,
the comment) ② «Qué le respondes» (the draft, already written, and «Otra idea») ③ «Revisa
y aprueba» («Le llega a @ana por mensaje privado.», the notice ticked by default) →
«Aprobar y enviar». «Atrás» keeps what was written. Approving shows «Listo. Le
escribiste a @ana. ¿Seguimos con la siguiente?» with «Siguiente» and «Volver a
comentarios». No tooltips: what used to hide behind an info icon is visible text. Every
button is at least 44 px tall and the rows wrap, so a 360 px phone gets one column.

**Whether it went out** (m-24849131, ATENDER-10): after «Aprobar y enviar» the card stays
as «Enviando a @ana…» (the kit's spinner, what was asked and what was written) until the
send ends: «Listo…» with the next step, or «No pudimos enviarle el mensaje a @ana.
Instagram no lo aceptó.» (error tone) / «No sabemos si salió. Revísalo en Instagram.»
(warning tone). A card that did not go out stays at the top of the list, with
«Entendido» to put it away. There is no «Reintentar» here (ATENDER-9 decides it).
"""

from __future__ import annotations

import reflex as rx

from .followups_state import FollowupsState
from .followups_vm import (
    ANOTHER_IDEA,
    COMMENTS_HREF,
    STEP_ASKED,
    STEP_REPLY,
    STEP_REVIEW,
    STEP_TITLES,
    SUGGEST_ONE,
    VIEW_MESSAGES,
    VIEW_QUERIES,
    FollowupCardVM,
    FollowupIntentVM,
    UndeliveredVM,
)
from .inbox_vm import UNSURE_INTENT_NOTE
from .ui import callout, card, empty_state, loading_spinner, skeleton_rows, tone_badge
from .ui import tokens as T
from .ui.flow_history import flow_sync
from .ui.steps import step_progress

F = FollowupsState

#: N12: every target on the card is at least 44 px tall.
_TAP: dict[str, str] = {"min_height": "44px"}


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
        # m-24842988: the explanation is said once per card, as visible text under the
        # chips (`UNSURE_INTENT_NOTE`) — never a tooltip, a phone has no hover.
        tone_badge(chip.label + " · revísalo", "warn"),
    )


def _origin(c: FollowupCardVM) -> rx.Component:
    """Step 1, «Qué preguntó»: who, when, on which publication (linked back to it) and
    the comment itself."""
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
            wrap="wrap",
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
        rx.cond(
            c.intent_unsure,
            rx.text(UNSURE_INTENT_NOTE, size="1", color=T.TEXT_MUTED),
        ),
        spacing="2",
        width="100%",
    )


def _asked_summary(c: FollowupCardVM) -> rx.Component:
    """Steps 2 and 3 keep the question in sight, in one line."""
    return rx.text(
        rx.text.strong(c.author),
        " preguntó: «" + c.comment_text + "»",
        size="1",
        color=T.TEXT_MUTED,
    )


def _blocked(c: FollowupCardVM) -> rx.Component:
    return rx.callout.root(
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
    )


def _route(c: FollowupCardVM) -> rx.Component:
    """Step 3, in words: who gets it and how, how long it is still possible and the
    route's rule — visible text, never behind a hover-only icon (N12)."""
    return rx.cond(
        c.route_available,
        rx.vstack(
            rx.hstack(
                rx.icon("send", size=T.ICON_SM, color=T.TEXT_MUTED),
                rx.text(c.recipient_line, size="2", weight="medium"),
                rx.cond(
                    c.route_deadline != "",
                    tone_badge(c.route_deadline, "info", icon="clock"),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            rx.text(c.route_note, size="1", color=T.TEXT_MUTED),
            spacing="1",
            width="100%",
        ),
        _blocked(c),
    )


def _draft(c: FollowupCardVM) -> rx.Component:
    """Step 2, «Qué le respondes»: the draft already written, editable."""
    busy = F.busy_id == c.followup_id
    return rx.vstack(
        rx.cond(
            c.needs_review,
            tone_badge("Requiere revisión", "warn", icon="triangle-alert"),
            rx.fragment(),
        ),
        rx.text_area(
            value=F.edits[c.followup_id],
            on_change=lambda text: F.set_edit(c.followup_id, text),
            placeholder="Escribe tu respuesta o toca «" + SUGGEST_ONE + "».",
            rows="4",
            max_length=1000,
            width="100%",
            disabled=busy,
            aria_label="Qué le respondes",
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
    """The public notice under the comment (PR 4) — only when the card offers it. Ticked
    by default; what it does is said in the label and the line under it, not a tooltip."""
    busy = F.busy_id == c.followup_id
    on = F.notice_on[c.followup_id]
    return rx.cond(
        c.notice_available,
        rx.vstack(
            rx.checkbox(
                # Fixed label (UX review): the box below holds the live text.
                "También dejamos “" + c.notice_default + "” en su comentario.",
                checked=on,
                on_change=lambda checked: F.set_notice_on(c.followup_id, checked),
                size="3",
                disabled=busy,
            ),
            rx.cond(
                on,
                rx.vstack(
                    rx.input(
                        value=F.notice_edits[c.followup_id],
                        on_change=lambda text: F.set_notice_edit(c.followup_id, text),
                        max_length=300,
                        width="100%",
                        size="3",
                        disabled=busy,
                        aria_label="Texto del aviso en su comentario",
                    ),
                    rx.text(
                        "Se publica en su comentario solo cuando el mensaje privado salga.",
                        size="1",
                        color=T.TEXT_MUTED,
                    ),
                    spacing="1",
                    width="100%",
                ),
                rx.fragment(),
            ),
            spacing="2",
            width="100%",
        ),
        rx.fragment(),
    )


def _row(*children: rx.Component) -> rx.Component:
    return rx.hstack(*children, width="100%", align="center", wrap="wrap", spacing="2")


def _back(c: FollowupCardVM, step: int) -> rx.Component:
    return rx.button(
        rx.icon("arrow-left", size=T.ICON_SM),
        "Atrás",
        variant="soft",
        color_scheme="gray",
        size="2",
        disabled=F.busy_id != "",
        on_click=F.go_step(c.followup_id, step),
        **_TAP,
    )


def _forward(c: FollowupCardVM, step: int, blank: rx.Var | bool = False) -> rx.Component:
    return rx.button(
        "Siguiente",
        rx.icon("arrow-right", size=T.ICON_SM),
        size="2",
        disabled=(F.busy_id != "") | blank,
        on_click=F.go_step(c.followup_id, step),
        **_TAP,
    )


def _to_comments() -> rx.Component:
    """Step 1 when nobody can be written to: a way out instead of two dead steps."""
    return rx.link(
        rx.button(
            rx.icon("arrow-left", size=T.ICON_SM),
            "Volver a comentarios",
            variant="soft",
            size="2",
            **_TAP,
        ),
        href=COMMENTS_HREF,
    )


def _step_asked(c: FollowupCardVM) -> rx.Component:
    return rx.vstack(
        _origin(c),
        # UX review: say it on step 1, not after the whole message is written.
        rx.cond(c.route_available, rx.fragment(), _blocked(c)),
        spacing="3",
        width="100%",
    )


def _step_asked_actions(c: FollowupCardVM) -> rx.Component:
    busy = F.busy_id == c.followup_id
    return _row(
        rx.button(
            rx.icon("x", size=T.ICON_SM),
            "Descartar",
            variant="ghost",
            color_scheme="gray",
            size="2",
            loading=busy & (F.busy_action == "discard"),
            disabled=F.busy_id != "",
            on_click=F.discard(c.followup_id),
            **_TAP,
        ),
        rx.spacer(),
        rx.cond(c.route_available, _forward(c, STEP_REPLY), _to_comments()),
    )


def _step_reply(c: FollowupCardVM) -> rx.Component:
    empty = F.edits[c.followup_id].strip() == ""
    return rx.vstack(
        _asked_summary(c),
        _draft(c),
        rx.cond(
            empty,
            rx.text(
                "Escribe tu respuesta o toca «" + SUGGEST_ONE + "» para seguir.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.fragment(),
        ),
        spacing="3",
        width="100%",
    )


def _step_reply_actions(c: FollowupCardVM) -> rx.Component:
    busy = F.busy_id == c.followup_id
    acting = F.busy_id != ""
    # go_step still refuses an empty message; this only says so before the tap.
    empty = F.edits[c.followup_id].strip() == ""
    idea = rx.cond(
        c.has_draft,
        rx.button(
            rx.icon("refresh-cw", size=T.ICON_SM),
            ANOTHER_IDEA,
            variant="soft",
            size="2",
            loading=busy & (F.busy_action == "regenerate"),
            disabled=acting,
            on_click=F.regenerate(c.followup_id),
            **_TAP,
        ),
        rx.button(
            rx.icon("sparkles", size=T.ICON_SM),
            SUGGEST_ONE,
            variant="soft",
            size="2",
            loading=busy & (F.busy_action == "generate"),
            disabled=acting,
            on_click=F.generate(c.followup_id),
            **_TAP,
        ),
    )
    return _row(
        _back(c, STEP_ASKED),
        idea,
        rx.spacer(),
        _forward(c, STEP_REVIEW, blank=empty),
    )


def _step_review(c: FollowupCardVM) -> rx.Component:
    return rx.vstack(
        _asked_summary(c),
        _route(c),
        rx.vstack(
            rx.text("Tu mensaje:", size="1", weight="medium", color=T.TEXT_MUTED),
            rx.box(
                rx.text(F.edits[c.followup_id], size="2", white_space="pre-wrap"),
                padding="0.6rem 0.8rem",
                border_radius=T.RADIUS_CONTROL,
                background=T.SURFACE_BG_RAISED,
                width="100%",
            ),
            rx.button(
                rx.icon("pencil", size=T.ICON_SM),
                "Cambiar mensaje",
                variant="ghost",
                size="2",
                disabled=F.busy_id != "",
                on_click=F.go_step(c.followup_id, STEP_REPLY),
                **_TAP,
            ),
            spacing="1",
            width="100%",
        ),
        _notice(c),
        spacing="3",
        width="100%",
    )


def _step_review_actions(c: FollowupCardVM) -> rx.Component:
    busy = F.busy_id == c.followup_id
    return _row(
        _back(c, STEP_REPLY),
        rx.spacer(),
        rx.button(
            rx.icon("send", size=T.ICON_SM),
            "Aprobar y enviar",
            size="2",
            loading=busy & (F.busy_action == "approve"),
            disabled=(F.busy_id != "") | ~c.route_available,
            on_click=F.approve(c.followup_id),
            **_TAP,
        ),
    )


def _frame_props(active: bool | rx.Var[bool]) -> dict:
    """The active card borrows the drawer's bounded head/body/foot anatomy."""
    limit = (
        "calc(100dvh - var(--q-sticky-header-height, 8rem) - var(--q-bottom-bar-h, 64px) - 2rem)"
    )
    height = (
        (limit if active else "auto")
        if isinstance(active, bool)
        else rx.cond(active, limit, "auto")
    )
    return {
        "display": "flex",
        "flex_direction": "column",
        "gap": "0.75rem",
        "height": height,
        "min_height": "0",
        "padding": "1rem",
        "box_sizing": "border-box",
    }


def _card(c: FollowupCardVM) -> rx.Component:
    step = F.steps[c.followup_id]
    active = F.active_query_id == c.followup_id
    count_id = "consulta-count-" + c.followup_id
    return card(
        flow_sync(
            "consulta",
            step,
            ready=F.loaded & (F.flow_card_id == c.followup_id),
            consulta=c.followup_id,
        ),
        rx.vstack(
            step_progress(step, 3, count_id=count_id),
            rx.heading(
                rx.match(
                    step,
                    (STEP_REPLY, STEP_TITLES[STEP_REPLY]),
                    (STEP_REVIEW, STEP_TITLES[STEP_REVIEW]),
                    STEP_TITLES[STEP_ASKED],
                ),
                as_="h2",
                size="4",
                id="consulta-title-" + c.followup_id,
                tab_index=-1,
                aria_describedby=count_id,
            ),
            spacing="2",
            width="100%",
            flex_shrink="0",
        ),
        rx.box(
            rx.match(
                step, (STEP_REPLY, _step_reply(c)), (STEP_REVIEW, _step_review(c)), _step_asked(c)
            ),
            id="consulta-body-" + c.followup_id,
            width="100%",
            min_height="0",
            flex="1 1 auto",
            overflow_y=rx.cond(active, "auto", "visible"),
            class_name=rx.cond(active, "q-step-body", "q-query-body"),
            custom_attrs={"data-dir": rx.cond(active, F.flow_direction, "next")},
            key=step,
        ),
        rx.box(
            rx.match(
                step,
                (STEP_REPLY, _step_reply_actions(c)),
                (STEP_REVIEW, _step_review_actions(c)),
                _step_asked_actions(c),
            ),
            width="100%",
            flex_shrink="0",
            padding_top="0.75rem",
            border_top=T.BORDER,
            class_name="q-query-actions",
        ),
        id="consulta-" + c.followup_id,
        scroll_margin_top=T.SCROLL_MARGIN_TOP,
        class_name=rx.cond(
            active, "q-card q-query-card q-query-card--active", "q-card q-query-card"
        ),
        border=rx.cond(
            F.highlight_id == c.followup_id, f"2px solid {T.tone_color('accent', 8)}", "none"
        ),
        **_frame_props(active),
    )


def _what_was_sent(c: FollowupCardVM) -> rx.Component:
    """The card itself stays in view while its send is in flight or did not go out."""
    return rx.vstack(
        _asked_summary(c),
        rx.text("Tu mensaje:", size="1", weight="medium", color=T.TEXT_MUTED),
        rx.box(
            rx.text(F.delivery_text, size="2", white_space="pre-wrap"),
            padding="0.6rem 0.8rem",
            border_radius=T.RADIUS_CONTROL,
            background=T.SURFACE_BG_RAISED,
            width="100%",
        ),
        spacing="1",
        width="100%",
    )


def _outcome_line() -> rx.Component:
    """One line per outcome: sending (spinner), sent (ok), refused (error), unknown
    (warning). Tones only, through the design system."""
    return rx.box(
        rx.cond(
            F.delivery_pending,
            rx.hstack(
                loading_spinner("sm"),
                rx.text(F.done_text, size="3", weight="medium"),
                spacing="2",
                align="center",
            ),
            rx.cond(
                F.delivery_sent,
                rx.hstack(
                    rx.icon("circle-check", size=T.ICON_MD, color=T.tone_color("ok", 11)),
                    rx.text(F.done_text, size="3", weight="medium"),
                    spacing="2",
                    align="start",
                ),
                rx.cond(
                    F.delivery_failed,
                    callout(F.done_text, "error"),
                    callout(F.done_text, "warn"),
                ),
            ),
        ),
        # UX review (m-24849131): one live region, so all four outcomes are announced.
        role="status",
        aria_live="polite",
        width="100%",
    )


def _done() -> rx.Component:
    """N3: the task ends with «Listo», the next query (solid) and the way back (soft;
    solid when nobody is left) — but «Siguiente» only once the send's result is
    known (m-24849131): while it goes out the card stays, with only the way back."""
    return card(
        rx.vstack(
            _outcome_line(),
            rx.cond(
                F.done_note != "",
                rx.text(F.done_note, size="2", color=T.TEXT_MUTED),
                rx.fragment(),
            ),
            rx.cond(
                F.delivery_sent,
                rx.fragment(),
                rx.foreach(F.delivery_card, _what_was_sent),
            ),
            rx.cond(F.delivery_pending, _back_while_sending(), _done_actions()),
            spacing="3",
            width="100%",
        ),
        id="consulta-listo",
    )


def _back_while_sending() -> rx.Component:
    """UX review (m-24849131, N3): while it goes out only «Siguiente» is held back —
    the way out stays, and the result still reaches the list through `undelivered`."""
    return _row(
        rx.link(
            rx.button("Volver a comentarios", variant="soft", size="2", **_TAP),
            href=COMMENTS_HREF,
        ),
    )


def _done_actions() -> rx.Component:
    return _row(
        rx.cond(
            F.followups_count > 0,
            rx.button(
                "Siguiente",
                rx.icon("arrow-right", size=T.ICON_SM),
                size="2",
                on_click=F.next_query,
                **_TAP,
            ),
            rx.fragment(),
        ),
        rx.link(
            rx.button(
                "Volver a comentarios",
                variant=rx.cond(F.followups_count > 0, "soft", "solid"),
                size="2",
                **_TAP,
            ),
            href=COMMENTS_HREF,
        ),
    )


def _undelivered(u: UndeliveredVM) -> rx.Component:
    """A card whose message did not go out stays in the list until the person says
    «Entendido» — nothing is re-sent from here (N13)."""
    return card(
        rx.vstack(
            rx.cond(u.failed, callout(u.headline, "error"), callout(u.headline, "warn")),
            rx.text(
                rx.text.strong(u.author),
                " preguntó: «" + u.comment_text + "»",
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.text("Tu mensaje:", size="1", weight="medium", color=T.TEXT_MUTED),
            rx.box(
                rx.text(u.message, size="2", white_space="pre-wrap"),
                padding="0.6rem 0.8rem",
                border_radius=T.RADIUS_CONTROL,
                background=T.SURFACE_BG_RAISED,
                width="100%",
            ),
            rx.cond(
                u.next_step != "",
                rx.text(u.next_step, size="2", color=T.TEXT_MUTED),
                rx.fragment(),
            ),
            _row(
                rx.spacer(),
                rx.button(
                    "Entendido",
                    variant="soft",
                    color_scheme="gray",
                    size="2",
                    on_click=F.dismiss_undelivered(u.followup_id),
                    **_TAP,
                ),
            ),
            spacing="2",
            width="100%",
        ),
        id="consulta-no-salio-" + u.followup_id,
    )


def followups_panel() -> rx.Component:
    return rx.vstack(
        rx.cond(F.error != "", callout(F.error, "error"), rx.fragment()),
        rx.cond(
            ~F.loaded,
            skeleton_rows(3, height="12rem"),
            rx.cond(
                F.showing_done,
                _done(),
                rx.vstack(
                    rx.foreach(F.undelivered, _undelivered),
                    _list_or_empty(),
                    spacing="3",
                    width="100%",
                ),
            ),
        ),
        spacing="3",
        width="100%",
    )


def _list_or_empty() -> rx.Component:
    return rx.cond(
        F.followups_count > 0,
        rx.vstack(rx.foreach(F.cards, _card), spacing="3", width="100%"),
        rx.cond(
            F.undelivered_count > 0,
            rx.fragment(),
            empty_state(
                "shopping-bag",
                "Nadie más está esperando para comprar",
                "Cuando alguien pregunte por precios o pedidos en tus comentarios, "
                "aparecerá aquí con un mensaje listo para que lo revises y lo envíes.",
                action=rx.link(
                    rx.button("Ver comentarios", size="3", min_height="44px"),
                    href=COMMENTS_HREF,
                ),
            ),
        ),
    )
