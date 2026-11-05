"""Creadores — «Tus creadores» and «Revisar un creador» (Delivery 1, m-24946129; UX
`docs/ux-creadores.md` §1.2, §2.1, §2.2; mockup `docs/mockups/creadores.html`).

`/creadores` is one menu entry with one place (N10-N12):

- a business **off** the switch (`QUALIFY_CREATORS_TENANTS`, design §11) keeps seeing
  the «Pronto» screen of before, word for word;
- a business **on** it sees its list: load error → `callout`; loading → skeleton
  cards; empty → the invitation with one solid button; else the cards, last read
  first, each a link to the sheet (`/creadores/<id>`);
- «Revisar un creador» opens the drawer at `?flujo=agregar` (N5), which accepts `@x`,
  `x` or the profile link, waits on a `progress_panel` while the read runs, and on
  success closes into the sheet (N3). Every failure is a `callout` above the button,
  in the owner's words, with what to do next — never credits, a vendor or a code;
- «Comparar creadores» turns the cards into checkboxes (`choice_card`), with a foot
  that says how many are chosen and why the button waits (2 to 4).

The «Campañas» tab (delivery 3) is not drawn: one tab alone is noise (UX §1.1).
"""

from __future__ import annotations

import reflex as rx

from .creators_access import CreatorsAccessState
from .creators_state import CreatorsState
from .creators_vm import (
    BACK_TO_LIST,
    CANCEL,
    COMPARE_ENTER,
    DRAWER_DESCRIPTION,
    DRAWER_EMPTY_REASON,
    DRAWER_SUBMIT,
    DRAWER_TITLE,
    EMPTY_BODY,
    EMPTY_HELP,
    EMPTY_TITLE,
    FIELD_HELP,
    FIELD_LABEL,
    FIELD_PLACEHOLDER,
    PICK_HEAD,
    PROGRESS_DETAIL,
    REVIEW_ONE,
    SEARCH_LABEL,
    SEE_RESULTS,
    SUBTITLE,
    TRY_AGAIN,
    WORKING_ROW,
    CreatorCardVM,
)
from .ui import (
    app_shell,
    callout,
    card,
    choice_card,
    choice_card_check,
    drawer,
    empty_state,
    loading_spinner,
    mono,
    page_body,
    page_header,
    progress_panel,
    skeleton_card,
    tone_badge,
)
from .ui import tokens as T
from .ui.flow_history import flow_sync
from .ui.route_history import route_history

TOUCH_MIN = "44px"
_FIELD_ID = "q-creator-handle"

# The «Pronto» screen of before (founder decision 4, NAV-1 m-24842957), unchanged for a
# business off the switch.
SOON_SUBTITLE = (
    "Te mostraremos personas de tu ciudad que recomiendan negocios como el tuyo, "
    "para que trabajen juntos"
)
SOON_TITLE = "Esto viene pronto"
SOON_BODY = (
    "Estamos preparando esta parte para que encuentres creadores de tu ciudad. "
    "Mientras tanto, prepara tu próxima publicación."
)


# --- pieces shared by the three Creadores screens ---------------------------------


def back_link(label: str = BACK_TO_LIST, href: str | rx.Var = "/creadores") -> rx.Component:
    """«‹ Creadores»: a way back a thumb can hit (N7 names the place, N12 the size)."""
    return rx.link(
        rx.button(
            rx.icon("chevron-left", size=T.ICON_MD),
            label,
            variant="ghost",
            size="3",
            min_height=TOUCH_MIN,
        ),
        href=href,
    )


def creator_avatar(src: rx.Var[str], fallback: rx.Var[str], size: str = "4") -> rx.Component:
    """The creator's picture; the CDN link expires, so Radix falls back to initials
    (design §10.3). No referrer to the CDN."""
    return rx.avatar(
        src=src,
        fallback=fallback,
        radius="full",
        size=size,
        custom_attrs={"referrerpolicy": "no-referrer"},
        flex_shrink="0",
    )


def help_popover(label: rx.Var[str] | str, text: rx.Var[str] | str) -> rx.Component:
    """«¿Cómo lo contamos?»: opened with a tap, never on hover (a phone has none)."""
    return rx.popover.root(
        rx.popover.trigger(
            rx.icon_button(
                rx.icon("circle-help", size=T.ICON_MD),
                variant="ghost",
                color_scheme="gray",
                size="2",
                aria_label="Qué quiere decir " + label,
                min_width=TOUCH_MIN,
                min_height=TOUCH_MIN,
            ),
        ),
        rx.popover.content(
            rx.text("¿Cómo lo contamos?", size="2", weight="bold"),
            rx.text(text, size="2", margin_top="0.25rem"),
            max_width="20rem",
        ),
    )


def toned_callout(message: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """A `callout` whose tone arrives from the state (`error`, `warn` or `info`)."""
    return rx.match(
        tone,
        ("warn", callout(message, "warn")),
        ("info", callout(message, "info")),
        callout(message, "error"),
    )


def action_callout(
    message: rx.Var[str] | str, action: rx.Component, tone: str = "warn", icon: str = "clock"
) -> rx.Component:
    """A degraded state that can be acted on (§6.3): the sentence and its button inside
    the callout (the house recipe of `followups_page._blocked`)."""
    return rx.callout.root(
        rx.callout.icon(rx.icon(icon)),
        rx.hstack(
            rx.text(message, size="2"),
            action,
            align="center",
            spacing="3",
            wrap="wrap",
            width="100%",
        ),
        variant="surface",
        width="100%",
        role="status",
        **T.tone_scheme(tone),
    )


def stale_badge() -> rx.Component:
    return tone_badge("Datos viejos", "warn", icon="clock")


# --- the list ---------------------------------------------------------------------


def _card_body(c: rx.Var[CreatorCardVM]) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            creator_avatar(c.avatar_url, c.initials, "4"),
            rx.vstack(
                rx.heading(c.name, size="3", as_="h3", trim="both"),
                mono(c.handle, overflow_wrap="anywhere"),
                spacing="1",
                align_items="start",
                min_width="0",
            ),
            spacing="3",
            align="center",
            width="100%",
        ),
        rx.text(c.followers, size="2", color=T.TEXT_MUTED, class_name="q-nums"),
        rx.text(c.median_views, size="2", weight="medium", class_name="q-nums"),
        rx.hstack(
            rx.cond(c.stale, stale_badge()),
            rx.text(c.freshness, size="1", color=T.TEXT_MUTED),
            spacing="2",
            align="center",
            wrap="wrap",
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _ready_card(c: rx.Var[CreatorCardVM]) -> rx.Component:
    """A whole card that is a real link (keyboard and «atrás» work as with any link);
    in «elige de 2 a 4» mode, a checkbox card instead (never a link with a box inside)."""
    selected = CreatorsState.picked.contains(c.tracked_id)
    return rx.cond(
        CreatorsState.picking,
        choice_card(
            rx.box(
                rx.cond(selected, choice_card_check()),
                position="absolute",
                top="0.75rem",
                right="0.75rem",
            ),
            _card_body(c),
            selected=selected,
            on_select=CreatorsState.toggle_pick(c.tracked_id),
            role="checkbox",
            position="relative",
            width="100%",
            min_height=TOUCH_MIN,
        ),
        rx.link(
            card(_card_body(c), interactive=True, min_height=TOUCH_MIN),
            href=c.href,
            underline="none",
            width="100%",
            display="block",
            color="inherit",
        ),
    )


def _working_card(c: rx.Var[CreatorCardVM]) -> rx.Component:
    """A creator being read now: no link yet (UX §2.1, fila «trabajando»)."""
    return card(
        rx.hstack(
            loading_spinner("sm"),
            rx.vstack(
                mono(c.handle, overflow_wrap="anywhere"),
                rx.text(WORKING_ROW, size="2", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
            ),
            spacing="3",
            align="center",
        ),
        aria_busy="true",
    )


def _problem_card(c: rx.Var[CreatorCardVM]) -> rx.Component:
    """Never read, and the last try failed (or never ran): the sentence and the way
    to try again inside it — a degraded state that can be acted on (§6.3)."""
    return card(
        rx.vstack(
            rx.hstack(
                creator_avatar(c.avatar_url, c.initials, "3"),
                mono(c.handle, overflow_wrap="anywhere"),
                spacing="3",
                align="center",
            ),
            toned_callout(c.problem, c.problem_tone),
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_SM),
                rx.cond(c.state == "pending", "Revisar ahora", TRY_AGAIN),
                variant="soft",
                size="3",
                min_height=TOUCH_MIN,
                on_click=CreatorsState.retry_card(c.tracked_id),
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
    )


def _creator_card(c: rx.Var[CreatorCardVM]) -> rx.Component:
    return rx.match(
        c.state,
        ("working", _working_card(c)),
        ("failed", _problem_card(c)),
        ("pending", _problem_card(c)),
        _ready_card(c),
    )


def _grid(*children: rx.Component) -> rx.Component:
    return rx.grid(
        *children,
        columns=rx.breakpoints(initial="1", sm="2", lg="3"),
        spacing="3",
        width="100%",
    )


def _label(text: str, field_id: str) -> rx.Component:
    """A visible label tied to its field (`rx.text(as_="label")` dropped `htmlFor`)."""
    return rx.el.label(rx.text(text, as_="span", size="2", weight="medium"), html_for=field_id)


def _search() -> rx.Component:
    return rx.vstack(
        _label(SEARCH_LABEL, "q-creator-search"),
        rx.input(
            rx.input.slot(rx.icon("search", size=T.ICON_SM)),
            id="q-creator-search",
            value=CreatorsState.query,
            on_change=CreatorsState.set_query,
            size="3",
            width="100%",
            max_width="26rem",
        ),
        spacing="1",
        width="100%",
    )


def _pick_foot() -> rx.Component:
    """«Elige de 2 a 4»: what is chosen and why the button waits, fixed at the foot
    (the anatomy of `step_foot`, §4.5)."""
    return rx.box(
        rx.vstack(
            rx.hstack(
                rx.text(PICK_HEAD, size="2", weight="medium"),
                rx.spacer(),
                rx.button(
                    CANCEL,
                    variant="soft",
                    color_scheme="gray",
                    size="3",
                    min_height=TOUCH_MIN,
                    on_click=CreatorsState.cancel_pick,
                ),
                rx.button(
                    CreatorsState.pick_label,
                    size="3",
                    min_height=TOUCH_MIN,
                    disabled=~CreatorsState.pick_ready,
                    on_click=CreatorsState.go_compare,
                ),
                align="center",
                spacing="3",
                width="100%",
                wrap="wrap",
            ),
            rx.cond(
                CreatorsState.pick_hint != "",
                rx.text(
                    CreatorsState.pick_hint,
                    size="2",
                    color=T.TEXT_MUTED,
                    role="status",
                    aria_live="polite",
                ),
            ),
            spacing="2",
            width="100%",
        ),
        # The card material made opaque (like the step foot's island), so the cards never show
        # through it, and lifted above the phone's bottom bar (`--q-bottom-bar-h`, 0 on
        # a computer), so «Comparar» is never under the menu (review 2026-11-04).
        class_name="q-card",
        padding="0.75rem 1rem",
        background="var(--color-panel-solid)",
        position="sticky",
        bottom=(
            "calc(var(--q-bottom-bar-h, 0px) + 2 * var(--q-gap) + env(safe-area-inset-bottom, 0px))"
        ),
        width="100%",
        z_index="3",
    )


def _list_view() -> rx.Component:
    return rx.vstack(
        rx.cond(
            CreatorsState.picking,
            rx.hstack(
                rx.button(
                    rx.icon("chevron-left", size=T.ICON_MD),
                    BACK_TO_LIST,
                    variant="ghost",
                    size="3",
                    min_height=TOUCH_MIN,
                    on_click=CreatorsState.cancel_pick,
                ),
                rx.text(PICK_HEAD, size="3", weight="medium"),
                align="center",
                spacing="3",
            ),
        ),
        rx.cond(CreatorsState.show_search, _search()),
        _grid(rx.foreach(CreatorsState.shown_cards, _creator_card)),
        rx.cond(
            (CreatorsState.query != "") & (CreatorsState.shown_cards.length() == 0),
            rx.text(
                "Ningún creador de tu lista coincide con lo que escribiste.",
                size="2",
                color=T.TEXT_MUTED,
            ),
        ),
        rx.cond(CreatorsState.picking, _pick_foot()),
        spacing="4",
        width="100%",
    )


def _empty() -> rx.Component:
    return rx.vstack(
        empty_state(
            "users",
            EMPTY_TITLE,
            EMPTY_BODY,
            action=rx.button(
                REVIEW_ONE, size="3", min_height=TOUCH_MIN, on_click=CreatorsState.open_drawer
            ),
        ),
        rx.text(EMPTY_HELP, size="2", color=T.TEXT_MUTED, text_align="center", width="100%"),
        spacing="3",
        width="100%",
    )


def _notice() -> rx.Component:
    """A result that happened while the owner looked elsewhere, or after leaving a
    sheet: on the page (N3), with the way to it, dismissable."""
    return rx.cond(
        CreatorsState.notice != "",
        rx.hstack(
            callout(CreatorsState.notice, "info", flex="1"),
            rx.cond(
                CreatorsState.notice_href != "",
                rx.link(
                    rx.button(SEE_RESULTS, variant="soft", size="3", min_height=TOUCH_MIN),
                    href=CreatorsState.notice_href,
                ),
            ),
            rx.icon_button(
                rx.icon("x", size=T.ICON_MD),
                variant="ghost",
                color_scheme="gray",
                size="3",
                aria_label="Cerrar aviso",
                on_click=CreatorsState.dismiss_notice,
            ),
            align="center",
            spacing="2",
            width="100%",
            wrap="wrap",
        ),
    )


def _loading() -> rx.Component:
    return rx.box(
        _grid(skeleton_card(3), skeleton_card(3), skeleton_card(3)),
        aria_busy="true",
        width="100%",
    )


def _module_body() -> rx.Component:
    return rx.fragment(
        _notice(),
        rx.cond(
            CreatorsState.load_error != "",
            callout(CreatorsState.load_error, "error"),
            rx.cond(
                CreatorsState.loading,
                _loading(),
                rx.cond(CreatorsState.has_cards, _list_view(), _empty()),
            ),
        ),
        _add_drawer(),
    )


def _soon_body() -> rx.Component:
    return empty_state(
        "users",
        SOON_TITLE,
        SOON_BODY,
        action=rx.link(rx.button("Crear publicación", size="3"), href="/create"),
    )


def _header_actions() -> rx.Component:
    return rx.cond(
        CreatorsAccessState.enabled & CreatorsState.has_cards & ~CreatorsState.picking,
        rx.hstack(
            rx.cond(
                CreatorsState.can_compare,
                rx.button(
                    COMPARE_ENTER,
                    variant="outline",
                    size="3",
                    min_height=TOUCH_MIN,
                    on_click=CreatorsState.start_pick,
                ),
            ),
            rx.button(
                rx.icon("user-search", size=T.ICON_MD),
                REVIEW_ONE,
                size="3",
                min_height=TOUCH_MIN,
                on_click=CreatorsState.open_drawer,
            ),
            spacing="2",
            wrap="wrap",
        ),
    )


# --- the drawer «Revisar un creador» ----------------------------------------------


def _drawer_form() -> rx.Component:
    return rx.vstack(
        _label(FIELD_LABEL, _FIELD_ID),
        rx.input(
            rx.input.slot("@"),
            id=_FIELD_ID,
            value=CreatorsState.handle_input,
            on_change=CreatorsState.set_handle_input,
            placeholder=FIELD_PLACEHOLDER,
            size="3",
            width="100%",
            auto_complete=False,
            custom_attrs={
                "autoCapitalize": "none",
                "autoCorrect": "off",
                "spellCheck": "false",
                "inputMode": "text",
                "enterKeyHint": "go",
                "aria-describedby": "q-creator-handle-help",
            },
        ),
        rx.text(FIELD_HELP, id="q-creator-handle-help", size="1", color=T.TEXT_MUTED),
        rx.cond(
            CreatorsState.add_message != "",
            rx.vstack(
                toned_callout(CreatorsState.add_message, CreatorsState.add_tone),
                rx.hstack(
                    rx.cond(
                        CreatorsState.existing_href != "",
                        rx.link(
                            rx.button(SEE_RESULTS, size="3", min_height=TOUCH_MIN),
                            href=CreatorsState.existing_href,
                        ),
                    ),
                    rx.cond(
                        CreatorsState.action_label != "",
                        rx.button(
                            CreatorsState.action_label,
                            variant="soft",
                            size="3",
                            min_height=TOUCH_MIN,
                            on_click=CreatorsState.on_action,
                        ),
                    ),
                    spacing="2",
                    wrap="wrap",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        spacing="2",
        width="100%",
    )


def _drawer_body() -> rx.Component:
    return rx.vstack(
        flow_sync("agregar", 1, ready=CreatorsState.flow_ready),
        rx.cond(
            CreatorsState.adding,
            progress_panel(
                CreatorsState.progress_title,
                PROGRESS_DETAIL,
                steps=CreatorsState.progress_steps,
                creep_seconds=15,
            ),
            rx.form(
                _drawer_form(),
                on_submit=lambda _data: CreatorsState.submit,
                reset_on_submit=False,
                width="100%",
            ),
        ),
        width="100%",
        spacing="3",
    )


def _drawer_footer() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.button(
                CANCEL,
                variant="soft",
                color_scheme="gray",
                size="3",
                min_height=TOUCH_MIN,
                on_click=CreatorsState.close_drawer,
            ),
            rx.button(
                DRAWER_SUBMIT,
                size="3",
                min_height=TOUCH_MIN,
                loading=CreatorsState.adding,
                disabled=CreatorsState.submit_disabled,
                on_click=CreatorsState.submit,
            ),
            justify="end",
            spacing="3",
            width="100%",
        ),
        rx.cond(
            (CreatorsState.handle_input.strip() == "") & ~CreatorsState.adding,
            rx.text(DRAWER_EMPTY_REASON, size="1", color=T.TEXT_MUTED, align="right", width="100%"),
        ),
        spacing="1",
        width="100%",
    )


def _add_drawer() -> rx.Component:
    return drawer(
        _drawer_body(),
        open=CreatorsState.drawer_open,
        on_open_change=CreatorsState.set_drawer_open,
        title=DRAWER_TITLE,
        description=DRAWER_DESCRIPTION,
        footer=_drawer_footer(),
        icon="user-search",
    )


# --- the page ---------------------------------------------------------------------


def creators_index() -> rx.Component:
    off = CreatorsAccessState.access == "off"
    return app_shell(
        route_history(
            CreatorsState.enter_history,
            ack=CreatorsState.history_ack,
            on_leave=CreatorsState.leave_flow,
        ),
        page_header(
            "Creadores",
            rx.cond(off, SOON_SUBTITLE, SUBTITLE),
            _header_actions(),
            badge=rx.cond(off, tone_badge("Pronto", "neutral")),
        ),
        page_body(rx.cond(off, _soon_body(), _module_body())),
    )


__all__ = [
    "action_callout",
    "back_link",
    "creator_avatar",
    "creators_index",
    "help_popover",
    "stale_badge",
    "toned_callout",
]
