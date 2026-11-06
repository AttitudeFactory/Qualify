"""WhatsApp → Tu número → «Formas de pago» (m-24955648, first PR).

Spec: `docs/ux-paso-de-pago.md` §2. Only design-system pieces: `DragCard` rows with the
`sort_handle` and a «⋯» menu (the same as «Ordenar tu menú»), `media_thumb`, `rx.switch`
with its visible label, `empty_state`, `drawer` + `step_progress`, `choice_card`,
`dropzone`, `chat_bubble`, `callout`, `tone_badge`. 375 px first, 44 px targets.
"""

from __future__ import annotations

import reflex as rx

from .ui import (
    DragCard,
    asset_script,
    callout,
    card,
    chat_bubble,
    choice_card,
    choice_card_check,
    drawer,
    dropzone,
    empty_state,
    media_thumb,
    skeleton_rows,
    sort_handle,
    tone_badge,
)
from .ui import tokens as T
from .ui.steps import step_progress
from .whatsapp_chats_vm import MAX_PHOTO_BYTES
from .whatsapp_payments_state import WhatsAppPaymentsState
from .whatsapp_payments_vm import (
    ADD,
    BACK,
    BUTTONS_OR_LIST,
    CHANGE,
    CURRENCIES,
    CURRENCY_LABEL,
    DELETE,
    DELETE_TEXT,
    EDIT,
    EMPTY_TEXT,
    EMPTY_TITLE,
    HELP,
    INSTRUCTIONS_HELP,
    INSTRUCTIONS_LABEL,
    KEEP,
    NAME_LABEL,
    NEXT,
    NO_BRAND,
    NO_QR,
    NO_QR_BUTTON,
    OFFER_NOW,
    OFFERED,
    QR_DROP,
    QR_HELP,
    QR_REMOVE,
    SAME_FOR_ALL,
    SAVE,
    SHORTCUTS,
    STEP_TITLES,
    STEPS,
    TITLE,
    WHEN_BEFORE,
    WHEN_LABEL,
    WHEN_ON_DELIVERY,
    PaymentRowVM,
)
from .whatsapp_state import WhatsAppState

P = WhatsAppPaymentsState
_TOUCH = "44px"
_BIG = {"size": "3", "min_height": _TOUCH}
_QR_UPLOAD_ID = "q-payment-qr"
_RANK_DRAG_JS = asset_script("rank-drag.js")


# -- the list ---------------------------------------------------------------------------


def _row_menu(row: rx.Var[PaymentRowVM]) -> rx.Component:
    at_top = row.position == 1
    at_end = row.position == row.total
    return rx.menu.root(
        rx.menu.trigger(
            rx.icon_button(
                rx.icon("ellipsis", size=T.ICON_MD),
                variant="ghost",
                size="3",
                type="button",
                aria_label=row.more_label,
                min_width=_TOUCH,
                min_height=_TOUCH,
                **T.tone_scheme("neutral"),
            ),
        ),
        rx.menu.content(
            rx.menu.item(
                rx.icon("pencil", size=T.ICON_SM), EDIT, on_click=P.open_edit(row.method_id)
            ),
            rx.menu.separator(),
            rx.menu.item("Primero", on_click=P.place(row.method_id, 0), disabled=at_top),
            rx.menu.item("Subir uno", on_click=P.place(row.method_id, row.up_to), disabled=at_top),
            rx.menu.item(
                "Bajar uno", on_click=P.place(row.method_id, row.down_to), disabled=at_end
            ),
            rx.menu.item("Último", on_click=P.place(row.method_id, row.last_to), disabled=at_end),
            rx.menu.separator(),
            rx.menu.item(
                rx.icon("trash-2", size=T.ICON_SM),
                DELETE,
                on_click=P.ask_delete(row.method_id),
                color=T.tone_color("error", 11),
            ),
            align="end",
        ),
    )


def _thumb(row: rx.Var[PaymentRowVM]) -> rx.Component:
    return media_thumb(
        row.thumb_url,
        size="48px",
        icon="banknote",
        alt=row.thumb_alt,
        has=row.thumb_url != "",
    )


def _row(row: rx.Var[PaymentRowVM]) -> rx.Component:
    return DragCard.create(
        rx.hstack(
            rx.cond(
                row.movable,
                sort_handle(
                    row.handle_label,
                    lambda key: P.handle_key(row.method_id, key),
                    key=row.method_id,
                    lifted=P.lifted == row.method_id,
                ),
                rx.box(width="0.5rem", flex_shrink="0"),
            ),
            _thumb(row),
            rx.vstack(
                rx.hstack(
                    rx.text(row.name, size="3", weight="medium", min_width="0", truncate=True),
                    rx.cond(~row.has_qr, tone_badge(NO_QR, "neutral")),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.cond(
                    row.currency_label != "",
                    rx.text(row.currency_label, size="2", color=T.TEXT_MUTED),
                ),
                rx.hstack(
                    rx.text(row.updated_label, size="1", color=T.TEXT_MUTED),
                    rx.spacer(),
                    rx.el.label(
                        rx.hstack(
                            rx.switch(
                                checked=row.active,
                                on_change=lambda value: P.toggle_active(row.method_id, value),
                                disabled=P.busy,
                                aria_label=row.switch_label,
                            ),
                            rx.text(OFFERED, size="2"),
                            spacing="2",
                            align="center",
                            min_height=_TOUCH,
                        ),
                    ),
                    width="100%",
                    align="center",
                    wrap="wrap",
                ),
                spacing="0",
                flex="1",
                min_width="0",
                align_items="start",
            ),
            _row_menu(row),
            align="start",
            spacing="2",
            width="100%",
        ),
        class_name="q-rank-card q-order-row",
        custom_attrs={
            "data-rank-group": "payment-methods",
            "data-rank-key": row.method_id,
            "role": "listitem",
        },
        on_drag_start=P.pick(row.method_id),
        on_drop=P.drop(row.method_id),
        key=row.method_id,
        width="100%",
        padding_y="0.25rem",
    )


def _incomplete_notice() -> rx.Component:
    return rx.cond(
        P.incomplete_id != "",
        rx.vstack(
            callout(P.error, "warn"),
            rx.button(
                rx.icon("pencil", size=T.ICON_SM),
                EDIT,
                on_click=P.open_edit(P.incomplete_id),
                variant="soft",
                type="button",
                **_BIG,
            ),
            spacing="2",
            width="100%",
            align_items="start",
        ),
        rx.cond(P.error != "", callout(P.error, "error")),
    )


def _add_button(solid: bool = True) -> rx.Component:
    return rx.button(
        rx.icon("plus", size=T.ICON_SM),
        ADD,
        on_click=P.open_new,
        variant="solid" if solid else "soft",
        type="button",
        width=rx.breakpoints(initial="100%", sm="auto"),
        **_BIG,
    )


def _list() -> rx.Component:
    return rx.vstack(
        rx.vstack(
            rx.foreach(P.rows, _row),
            spacing="2",
            width="100%",
            role="list",
            aria_label=TITLE,
        ),
        rx.text(BUTTONS_OR_LIST, size="1", color=T.TEXT_MUTED),
        rx.text(P.announce, class_name="q-order-live", role="status", aria_live="polite"),
        _add_button(),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _delete_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(P.delete_title_text),
            rx.alert_dialog.description(DELETE_TEXT, size="2"),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button(KEEP, variant="soft", **_BIG, **T.tone_scheme("neutral")),
                ),
                rx.alert_dialog.action(
                    rx.button(DELETE, on_click=P.confirm_delete, **_BIG, **T.tone_scheme("error")),
                ),
                spacing="3",
                margin_top="1rem",
                justify="end",
                wrap="wrap",
            ),
            max_width="28rem",
        ),
        open=P.delete_open,
        on_open_change=P.set_delete_open,
    )


# -- the flow ---------------------------------------------------------------------------


def _label(text: str, html_for: str) -> rx.Component:
    return rx.el.label(rx.text(text, size="2", weight="medium"), html_for=html_for)


def _shortcut(key: str, name: str) -> rx.Component:
    selected = P.f_shortcut == key
    return choice_card(
        rx.hstack(
            rx.text(name, size="2", weight="medium"),
            rx.spacer(),
            rx.cond(selected, choice_card_check(), rx.fragment()),
            width="100%",
            align="center",
        ),
        selected=selected,
        on_select=P.pick_shortcut(key),
        padding="0.5rem 0.75rem",
        min_height=_TOUCH,
        width="100%",
    )


def _step_name() -> rx.Component:
    return rx.vstack(
        rx.grid(
            *[_shortcut(key, name) for key, name, *_rest in SHORTCUTS],
            columns=rx.breakpoints(initial="2", sm="3"),
            spacing="2",
            width="100%",
            role="radiogroup",
            aria_label=STEP_TITLES[0],
        ),
        _label(NAME_LABEL, "q-pay-name"),
        rx.input(
            id="q-pay-name",
            value=P.f_name,
            on_change=P.set_f_name,
            placeholder="Por ejemplo: Pago móvil",
            size="3",
            width="100%",
            aria_describedby="q-pay-name-count q-pay-name-error",
        ),
        rx.cond(
            P.f_error != "",
            rx.text(
                P.f_error,
                size="2",
                color=T.tone_color("error", 11),
                role="alert",
                id="q-pay-name-error",
            ),
        ),
        rx.text(
            P.name_count, size="1", color=T.TEXT_MUTED, class_name="q-nums", id="q-pay-name-count"
        ),
        _label(CURRENCY_LABEL, "q-pay-currency"),
        rx.select.root(
            rx.select.trigger(id="q-pay-currency", width="100%", min_height=_TOUCH),
            rx.select.content(*[rx.select.item(name, value=code) for code, name in CURRENCIES]),
            value=P.f_currency,
            on_change=P.set_f_currency,
            size="3",
        ),
        rx.text(WHEN_LABEL, size="2", weight="medium"),
        rx.vstack(
            choice_card(
                rx.text(WHEN_BEFORE, size="2"),
                selected=~P.f_on_delivery,
                on_select=P.set_f_on_delivery("antes"),
                padding="0.5rem 0.75rem",
                min_height=_TOUCH,
                width="100%",
            ),
            choice_card(
                rx.text(WHEN_ON_DELIVERY, size="2"),
                selected=P.f_on_delivery,
                on_select=P.set_f_on_delivery("entrega"),
                padding="0.5rem 0.75rem",
                min_height=_TOUCH,
                width="100%",
            ),
            spacing="2",
            width="100%",
            role="radiogroup",
            aria_label=WHEN_LABEL,
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _step_instructions() -> rx.Component:
    return rx.vstack(
        rx.text(INSTRUCTIONS_HELP, size="2", color=T.TEXT_MUTED, id="q-pay-instr-help"),
        _label(INSTRUCTIONS_LABEL, "q-pay-instr"),
        rx.text_area(
            id="q-pay-instr",
            value=P.f_instructions,
            on_change=P.set_f_instructions,
            rows="5",
            size="3",
            width="100%",
            aria_describedby="q-pay-instr-help q-pay-instr-count",
        ),
        rx.text(
            P.instructions_count,
            size="1",
            color=T.TEXT_MUTED,
            class_name="q-nums",
            id="q-pay-instr-count",
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )


def _step_qr() -> rx.Component:
    return rx.vstack(
        rx.cond(
            P.preview_qr != "",
            rx.vstack(
                media_thumb(P.preview_qr, size="10rem", alt="Tu QR", fit="contain"),
                rx.button(
                    rx.icon("trash-2", size=T.ICON_SM),
                    QR_REMOVE,
                    on_click=P.drop_qr,
                    variant="soft",
                    type="button",
                    **_BIG,
                    **T.tone_scheme("neutral"),
                ),
                spacing="2",
                align_items="start",
            ),
        ),
        dropzone(
            rx.vstack(
                rx.icon("qr-code", size=T.ICON_LG, color=T.TEXT_FAINT, aria_hidden="true"),
                rx.button(
                    rx.icon("image-plus", size=T.ICON_SM),
                    QR_DROP,
                    type="button",
                    **_BIG,
                ),
                rx.text(QR_HELP, size="2", color=T.TEXT_MUTED, text_align="center"),
                spacing="3",
                align="center",
                width="100%",
            ),
            upload_id=_QR_UPLOAD_ID,
            on_drop=P.handle_qr(rx.upload_files(upload_id=_QR_UPLOAD_ID)),
            on_drop_rejected=P.qr_rejected,
            accept={"image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"]},
            max_files=1,
            max_size=MAX_PHOTO_BYTES,
            disabled=P.saving,
        ),
        rx.cond(P.f_qr_error != "", callout(P.f_qr_error, "warn")),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _change(step: int, label: str) -> rx.Component:
    return rx.button(
        CHANGE,
        on_click=P.go_step(step),
        variant="ghost",
        size="2",
        min_height=_TOUCH,
        type="button",
        aria_label=f"{CHANGE}: {label}",
    )


def _step_preview() -> rx.Component:
    return rx.vstack(
        rx.cond(
            P.editing,
            rx.hstack(
                rx.text(P.f_name, size="3", weight="bold"),
                rx.spacer(),
                _change(1, "el nombre, la moneda y cuándo te paga"),
                width="100%",
                align="center",
            ),
        ),
        rx.hstack(
            rx.spacer(),
            chat_bubble(
                rx.vstack(
                    rx.cond(
                        P.preview_qr != "",
                        media_thumb(P.preview_qr, size="9rem", alt="Tu QR", fit="contain"),
                    ),
                    rx.foreach(P.preview_text, lambda line: rx.text(line, size="2")),
                    spacing="2",
                    align_items="start",
                ),
                direction="out",
                max_width="22rem",
            ),
            width="100%",
        ),
        rx.cond(
            P.editing,
            rx.hstack(
                _change(2, "tus datos para que te pague"),
                _change(3, "el QR"),
                spacing="2",
                wrap="wrap",
            ),
        ),
        rx.el.label(
            rx.hstack(
                rx.switch(checked=P.f_active, on_change=P.set_f_active),
                rx.text(OFFER_NOW, size="2"),
                spacing="2",
                align="center",
                min_height=_TOUCH,
            ),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )


def _footer() -> rx.Component:
    back = rx.button(
        rx.icon("chevron-left", size=T.ICON_SM),
        BACK,
        on_click=P.back_step,
        variant="soft",
        type="button",
        **_BIG,
        **T.tone_scheme("neutral"),
    )
    return rx.vstack(
        # step 1's problems are the name's: they show under the name field
        rx.cond((P.f_error != "") & (P.step != 1), callout(P.f_error, "warn")),
        rx.hstack(
            rx.cond((P.step > 1) & ~(P.editing & (P.step == STEPS)), back),
            rx.spacer(),
            rx.match(
                P.step,
                (
                    3,
                    rx.hstack(
                        rx.cond(
                            P.preview_qr == "",
                            rx.button(
                                NO_QR_BUTTON,
                                on_click=P.skip_qr,
                                variant="soft",
                                type="button",
                                **_BIG,
                                **T.tone_scheme("neutral"),
                            ),
                        ),
                        rx.button(NEXT, on_click=P.next_step, type="button", **_BIG),
                        spacing="2",
                    ),
                ),
                (
                    STEPS,
                    rx.button(SAVE, on_click=P.save_flow, loading=P.saving, type="button", **_BIG),
                ),
                rx.button(
                    NEXT,
                    rx.icon("arrow-right", size=T.ICON_SM),
                    on_click=P.next_step,
                    type="button",
                    **_BIG,
                ),
            ),
            width="100%",
            align="center",
        ),
        spacing="2",
        width="100%",
    )


def _flow() -> rx.Component:
    return drawer(
        rx.match(
            P.step,
            (1, _step_name()),
            (2, _step_instructions()),
            (3, _step_qr()),
            (STEPS, _step_preview()),
            _step_name(),
        ),
        open=P.flow_open,
        on_open_change=P.set_flow_open,
        title=rx.cond(P.editing, "Editar forma de pago", ADD),
        step=rx.vstack(
            step_progress(P.step, STEPS),
            rx.match(
                P.step,
                *[
                    (i + 1, rx.text(t, size="2", weight="medium"))
                    for i, t in enumerate(STEP_TITLES)
                ],
                rx.fragment(),
            ),
            spacing="1",
            width="100%",
        ),
        footer=_footer(),
        width="34rem",
        icon="wallet",
    )


def payments_tab() -> rx.Component:
    """The panel: the list (or its empty state), the flow and the delete dialog."""
    return rx.vstack(
        rx.box(display="none", on_mount=rx.call_script(_RANK_DRAG_JS)),
        rx.heading(TITLE, size="4", as_="h2"),
        rx.text(HELP, size="2", color=T.TEXT_MUTED),
        rx.cond(
            WhatsAppState.numbers.length() > 1,
            rx.text(SAME_FOR_ALL, size="2", color=T.TEXT_MUTED),
        ),
        rx.cond(
            P.no_brand,
            callout(NO_BRAND, "warn"),
            rx.fragment(
                _incomplete_notice(),
                rx.cond(
                    P.loading,
                    skeleton_rows(rows=3, height="4.5rem"),
                    rx.cond(
                        P.has_methods,
                        _list(),
                        card(
                            empty_state("wallet", EMPTY_TITLE, EMPTY_TEXT, _add_button()),
                            padding="1rem",
                        ),
                    ),
                ),
            ),
        ),
        _flow(),
        _delete_dialog(),
        spacing="3",
        width="100%",
        align_items="start",
        on_mount=P.ensure_loaded,
    )
