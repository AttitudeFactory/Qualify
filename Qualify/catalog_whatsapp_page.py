"""Galería › the products in the owner's WhatsApp catalog (m-25017357) — the pieces the
catalog page places (`ux-galeria-catalogo-whatsapp.md`):

- `card_badge(product)`: at most ONE WhatsApp badge on a product card (none for «not in
  WhatsApp»); the card is already a button, so the action lives in the editor only.
- `editor_block()`: the editor's «En WhatsApp» panel — badge, what it means and the one
  verb («Subir a WhatsApp», «Guardar y subir a WhatsApp», «Actualizar en WhatsApp»,
  «Intentar de nuevo»), 44 px, full width on a phone.
- `bulk_block()`: under `group_notice()` in «Productos» — the callout and «Subir mis
  productos a WhatsApp» / «Actualizar mi catálogo de WhatsApp», the progress card, the
  closing summary, or the way to ask the team (no catalog, lost permission).
- `problems_filter()`: «Ver los {m} con problemas» beside the other filters.
- `confirm_dialog()`: the counts above zero, «Volver» first and on Esc, the verb last.
- `delete_note()`: the sentence the «¿Eliminar este producto?» dialog adds for a product
  that is in WhatsApp.

Design-system primitives only (`callout`, `tone_badge`, `card`, `progress_panel`,
`loading_spinner`, `rx.alert_dialog`); tones by name, never a raw colour.
"""

from __future__ import annotations

from collections.abc import Callable

import reflex as rx

from . import catalog_whatsapp_vm as vm
from .catalog_state import CatalogState
from .catalog_vm import ProductVM
from .catalog_whatsapp_state import CatalogWhatsAppState as W
from .ui import callout, card, loading_spinner, progress_panel, tone_badge
from .ui import tokens as T

_TOUCH_MIN = "44px"
_BIG = {"size": "3", "min_height": _TOUCH_MIN}
#: A button whose label may wrap at 360 px («Actualizar mi catálogo de WhatsApp»): it
#: grows with the text instead of squeezing two lines into 44 px (UX review).
_GROWS = {
    "height": "auto",
    "white_space": "normal",
    "padding_top": "0.6rem",
    "padding_bottom": "0.6rem",
    "text_align": "center",
}
_TONES = ("ok", "warn", "error", "info", "neutral")


def _by_tone(tone: rx.Var[str], build: Callable[[str], rx.Component]) -> rx.Component:
    """A primitive whose tone comes from the state: one branch per design-system tone."""
    return rx.match(tone, *[(t, build(t)) for t in _TONES], build("neutral"))


# -- the card ------------------------------------------------------------------------------


def card_badge(product: rx.Var[ProductVM]) -> rx.Component:
    kind = W.card_kind[product.product_id]
    return rx.cond(
        W.shows_products,
        rx.match(
            kind,
            (vm.CARD_SYNCED, tone_badge(vm.SYNCED_BADGE, "ok", icon="check")),
            # the badge's own 12 px icon, sized to its text (the ring filled the badge)
            (vm.CARD_UPLOADING, tone_badge(vm.IN_FLIGHT_BADGE, "info", icon="loader-circle")),
            (vm.CARD_OUT_OF_DATE, tone_badge(vm.OUT_OF_DATE_BADGE, "warn", icon="refresh-cw")),
            (vm.CARD_ERROR, tone_badge(vm.ERROR_BADGE, "error", icon="triangle-alert")),
            (vm.CARD_MISSING, tone_badge(W.card_text[product.product_id], "warn")),
            rx.fragment(),
        ),
    )


def card_label(product: rx.Var[ProductVM]) -> rx.Var[str]:
    """The card's screen-reader name: «Editar {producto}», plus its WhatsApp badge (UX
    review: the badges were not read)."""
    text = W.card_text[product.product_id]
    return rx.cond(
        # every listed product has an entry while the layer shows (`screen_view`)
        W.shows_products & (text != ""),
        "Editar " + product.name + ". " + text,
        "Editar " + product.name,
    )


# -- the editor ----------------------------------------------------------------------------


def _editor_button() -> rx.Component:
    pid = CatalogState.selected_id
    action = W.ed_action[pid]
    label = rx.match(
        action,
        (vm.ACTION_UPLOAD, rx.cond(CatalogState.edit_dirty, vm.SAVE_AND_UPLOAD, vm.UPLOAD_ONE)),
        (vm.ACTION_UPDATE, rx.cond(CatalogState.edit_dirty, vm.SAVE_AND_UPDATE, vm.UPDATE_ONE)),
        (vm.ACTION_RETRY, rx.cond(CatalogState.edit_dirty, vm.SAVE_AND_RETRY, vm.RETRY_ONE)),
        "",
    )
    icon = rx.match(
        action,
        (vm.ACTION_UPLOAD, rx.icon("upload", size=T.ICON_SM)),
        (vm.ACTION_UPDATE, rx.icon("refresh-cw", size=T.ICON_SM)),
        rx.icon("rotate-ccw", size=T.ICON_SM),
    )
    return rx.cond(
        (action == vm.ACTION_UPLOAD) | (action == vm.ACTION_UPDATE) | (action == vm.ACTION_RETRY),
        rx.vstack(
            rx.button(
                icon,
                label,
                type="button",
                variant=rx.cond(action == vm.ACTION_UPLOAD, "soft", "solid"),
                on_click=W.act(pid),
                loading=(W.acting == pid) | CatalogState.edit_saving,
                disabled=W.lost_access,
                width="100%",
                **_BIG,
                **_GROWS,
            ),
            rx.cond(
                W.lost_access,
                rx.text(vm.LOST_ACCESS_REASON, size="1", color=T.TEXT_MUTED),
            ),
            spacing="1",
            width="100%",
        ),
    )


def editor_block() -> rx.Component:
    """«En WhatsApp», a `q-catalog-panel` between the badges and «Datos del producto»."""
    pid = CatalogState.selected_id
    busy = (W.ed_action[pid] == vm.ACTION_BUSY) | (W.acting == pid)
    return rx.cond(
        W.shows_products,
        rx.vstack(
            rx.hstack(
                rx.icon("message-circle", size=T.ICON_SM, color=T.TEXT_MUTED),
                rx.text(vm.SECTION_LABEL, size="2", weight="medium"),
                rx.spacer(),
                rx.cond(
                    busy,
                    rx.hstack(
                        loading_spinner("sm"),
                        rx.text(
                            rx.cond(
                                (W.sent_verbs[pid] == vm.ACTION_UPDATE)
                                | (W.ed_action[pid] == vm.ACTION_UPDATE)
                                | (W.ed_action[pid] == vm.ACTION_RETRY),
                                vm.UPDATING_ONE,
                                vm.UPLOADING_ONE,
                            ),
                            size="1",
                            color=T.TEXT_MUTED,
                        ),
                        spacing="2",
                        align="center",
                    ),
                    _by_tone(
                        W.ed_tone[pid],
                        lambda t: tone_badge(W.ed_badge[pid], t),
                    ),
                ),
                width="100%",
                align="center",
                spacing="2",
                wrap="wrap",
            ),
            rx.text(W.ed_help[pid], size="2", color=T.TEXT_MUTED),
            rx.cond(
                (W.ed_error != "") & (W.ed_error_for == pid),
                callout(W.ed_error, "error"),
            ),
            rx.cond(~busy, _editor_button()),
            # UX review: «escríbenos» needs a way there — the same ticket, once per product
            rx.cond(
                (W.ed_team[pid] == "1") & ~busy,
                _team_button(vm.ASK_RECONNECT, product_id=pid),
            ),
            spacing="3",
            width="100%",
            align_items="start",
            class_name="q-catalog-panel",
            aria_live="polite",
        ),
    )


def delete_note() -> rx.Component:
    """Decision 3 (2026-11-12): deleting does not touch WhatsApp by itself."""
    return rx.cond(
        W.shows_products & W.live_ids.contains(CatalogState.selected_id),
        rx.text(
            "Se quitará de WhatsApp la próxima vez que actualices tu catálogo.",
            size="2",
            weight="medium",
            margin_top="0.5rem",
        ),
    )


# -- «Productos»: the bulk block -----------------------------------------------------------


def _team_button(label: str, product_id: rx.Var[str] | str = "") -> rx.Component:
    """«Pedir mi catálogo» / «Escribir al equipo»: one ticket per place (`product_id` ""
    is «Productos»), its answer shown in that same place."""
    here = W.team_notice_for == product_id
    sent = W.team_sent if isinstance(product_id, str) else W.team_asked.contains(product_id)
    return rx.vstack(
        rx.cond(
            ~sent,
            rx.button(
                rx.icon("message-circle", size=T.ICON_SM),
                label,
                type="button",
                variant="soft",
                on_click=W.ask_team(product_id),
                loading=W.team_busy & here,
                width=rx.breakpoints(initial="100%", sm="auto"),
                **_BIG,
                **_GROWS,
            ),
        ),
        rx.cond(here & (W.team_notice != ""), callout(W.team_notice, "ok")),
        rx.cond(here & (W.team_error != ""), callout(W.team_error, "error")),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _connected_block() -> rx.Component:
    return rx.vstack(
        rx.cond(
            W.running,
            card(
                progress_panel(W.progress_title, vm.PROGRESS_DETAIL, value=W.progress_value),
                padding="1rem 1.25rem",
                width="100%",
            ),
            rx.fragment(
                rx.cond(
                    W.summary_text != "",
                    _by_tone(W.summary_tone, lambda t: callout(W.summary_text, t)),
                    rx.cond(
                        W.bulk_text != "",
                        _by_tone(
                            W.bulk_tone,
                            lambda t: callout(W.bulk_text, t, icon="message-circle"),
                        ),
                    ),
                ),
                rx.cond(
                    W.bulk_button != "",
                    rx.button(
                        rx.icon("upload", size=T.ICON_SM),
                        W.bulk_button,
                        type="button",
                        on_click=W.open_dialog,
                        loading=W.planning,
                        width=rx.breakpoints(initial="100%", sm="auto"),
                        **_BIG,
                        **_GROWS,
                    ),
                ),
            ),
        ),
        rx.cond(W.bulk_error != "", callout(W.bulk_error, "error")),
        spacing="2",
        width="100%",
        align_items="start",
    )


def bulk_block() -> rx.Component:
    return rx.match(
        W.connection,
        (
            vm.NOT_CONNECTED,
            rx.vstack(
                callout(vm.NO_CATALOG_TEXT, "info", icon="message-circle"),
                _team_button(vm.ASK_CATALOG),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        (vm.CONNECTED, _connected_block()),
        (
            "missing_permission",
            rx.vstack(
                callout(vm.LOST_ACCESS_TEXT, "error"),
                _team_button(vm.ASK_RECONNECT),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        (
            "auth_error",
            rx.vstack(
                callout(vm.LOST_ACCESS_TEXT, "error"),
                _team_button(vm.ASK_RECONNECT),
                spacing="2",
                width="100%",
                align_items="start",
            ),
        ),
        rx.fragment(),
    )


def problems_filter() -> rx.Component:
    """Beside «Ver los N sin foto», the same component; warn while it invites, neutral
    once it narrows."""
    on = CatalogState.wa_filter_on
    return rx.cond(
        W.shows_products & (W.problem_count > 0),
        rx.button(
            rx.cond(on, rx.icon("list", size=T.ICON_SM), rx.icon("triangle-alert", size=T.ICON_SM)),
            rx.cond(on, vm.SHOW_ALL, W.problems_label),
            variant="soft",
            size="2",
            type="button",
            min_height=_TOUCH_MIN,
            width=rx.breakpoints(initial="100%", sm="auto"),
            on_click=W.toggle_problems,
            color_scheme=rx.cond(on, T.tone_scale("neutral"), T.tone_scale("warn")),
        ),
    )


# -- the confirmation ----------------------------------------------------------------------


def confirm_dialog() -> rx.Component:
    big = {**_BIG, "width": "100%"}
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(W.dialog_title),
            rx.alert_dialog.description(
                "Esto es lo que va a cambiar en tu catálogo de WhatsApp.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.vstack(
                rx.cond(W.dialog_notice != "", callout(W.dialog_notice, "info")),
                rx.foreach(W.dialog_lines, lambda line: rx.text(line, size="2")),
                rx.cond(
                    W.dialog_removal != "",
                    rx.text(W.dialog_removal, size="2", weight="bold"),
                ),
                rx.cond(W.dialog_blocked != "", rx.text(W.dialog_blocked, size="2")),
                rx.text(W.dialog_footer, size="1", color=T.TEXT_MUTED),
                spacing="2",
                width="100%",
                align_items="start",
                margin_top="0.75rem",
            ),
            rx.box(
                rx.alert_dialog.cancel(
                    rx.button(
                        rx.icon("arrow-left", size=T.ICON_SM),
                        "Volver",
                        variant="soft",
                        color_scheme="gray",
                        type="button",
                        disabled=W.confirming,
                        **big,
                    ),
                ),
                rx.button(
                    rx.icon("upload", size=T.ICON_SM),
                    W.dialog_confirm,
                    type="button",
                    on_click=W.confirm_all,
                    loading=W.confirming,
                    **big,
                ),
                display="grid",
                grid_template_columns=rx.breakpoints(
                    initial="minmax(0, 1fr)", sm="repeat(2, minmax(0, 1fr))"
                ),
                gap="0.75rem",
                margin_top="1.25rem",
                width="100%",
            ),
            max_width="30rem",
        ),
        open=W.dialog_open,
        on_open_change=W.set_dialog_open,
    )
