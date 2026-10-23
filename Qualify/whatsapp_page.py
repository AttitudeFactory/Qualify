"""`/whatsapp` (WA-12): the WhatsApp module's page shell + the Conexión, Perfil and QR tabs.

Layout, per docs/design-system.md §9.1: `app_shell(page_header(...), page_body(...))`;
every state is a TONE (`ok`/`warn`/`error`/`info`/`neutral`) through `signal_pill` /
`tone_badge` / `callout`, never a raw Radix colour; identity through
`platform_badge("whatsapp")`.

**The shell.** Header + number selector (only when the tenant has more than one number)
+ a tab strip (segmented control, the skinned widget the app already uses for flows —
there is no `rx.tabs` precedent here) + the active tab's body. The body renders ONLY the
active tab, inside a box keyed by `WhatsAppState.selected_connection_id`, so a tab's root
`on_mount` fires on tab entry and on every number switch: that is how Perfil and QR load
their data, and how Chats (WA-11, `whatsapp_tab_chats.py`) and Menú (WA-16,
`whatsapp_tab_menu.py`) plug in from their own files without touching this one.
"""

from __future__ import annotations

import reflex as rx

from .connections_vm import WHATSAPP_RECONNECT_HINT
from .ui import (
    app_shell,
    callout,
    card,
    dropzone,
    empty_state,
    kv,
    media_thumb,
    mono,
    page_body,
    page_header,
    platform_badge,
    signal_pill,
    skeleton_card,
    skeleton_rows,
    tag,
)
from .ui import tokens as T
from .whatsapp_metrics_block import metrics_block
from .whatsapp_state import WhatsAppState
from .whatsapp_tab_campaigns import campaigns_tab
from .whatsapp_tab_chats import chats_tab
from .whatsapp_tab_contacts import contacts_tab
from .whatsapp_tab_menu import menu_tab
from .whatsapp_tab_templates import templates_tab
from .whatsapp_vm import (
    MAX_ABOUT_CHARS,
    MAX_ADDRESS_CHARS,
    MAX_DESCRIPTION_CHARS,
    MAX_EMAIL_CHARS,
    MAX_QR_MESSAGE_CHARS,
    MAX_WEBSITE_CHARS,
    QR_CHANNELS,
    TAB_CAMPAIGNS,
    TAB_CHATS,
    TAB_CONNECTION,
    TAB_CONTACTS,
    TAB_MENU,
    TAB_PROFILE,
    TAB_QR,
    TAB_TEMPLATES,
    TABS,
    VERTICALS,
    QrCodeVM,
    WhatsAppNumberVM,
)

_TONES = ("ok", "warn", "error", "info", "neutral")
_PHOTO_UPLOAD_ID = "whatsapp_profile_photo"
_PHOTO_ACCEPT = {"image/jpeg": [".jpg", ".jpeg"], "image/png": [".png"]}


# ======================================================================================
# Tone helpers — the VM ships the tone as data, the system needs it at build time.
# ======================================================================================


def tone_pill(label: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """`signal_pill` for a tone that is a Var (the VM decides it per row)."""
    return rx.match(
        tone,
        *[(t, signal_pill(label, t)) for t in _TONES[:-1]],
        signal_pill(label, "neutral"),
    )


def banner(message: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    """A `callout` in a Var tone, shown only when there is a message."""
    return rx.cond(
        message != "",
        rx.match(
            tone,
            *[(t, callout(message, t)) for t in _TONES[:-1]],
            callout(message, "neutral"),
        ),
        rx.fragment(),
    )


def retry_button(label: str, on_click: rx.event.EventHandler) -> rx.Component:
    """Shown in place of a tab's content when its read failed (the banner says why)."""
    return rx.button(
        rx.icon("refresh-cw", size=T.ICON_SM),
        label,
        on_click=on_click,
        variant="soft",
        size="2",
        **T.tone_scheme("neutral"),
    )


# ======================================================================================
# Shell
# ======================================================================================


def _number_item(number: WhatsAppNumberVM) -> rx.Component:
    return rx.select.item(number.label, value=number.connection_id)


def number_selector() -> rx.Component:
    """Shown only when the tenant has more than one WhatsApp number."""
    return rx.cond(
        WhatsAppState.has_many_numbers,
        rx.select.root(
            rx.select.trigger(placeholder="Elige un número", width="280px"),
            rx.select.content(rx.foreach(WhatsAppState.numbers, _number_item)),
            value=WhatsAppState.selected_connection_id,
            on_change=WhatsAppState.select_connection,
        ),
        rx.fragment(),
    )


def whatsapp_header() -> rx.Component:
    return page_header(
        "WhatsApp",
        "Tu número de WhatsApp Business: estado de la conexión, perfil y códigos QR.",
        number_selector(),
    )


def tab_strip() -> rx.Component:
    return rx.box(
        rx.segmented_control.root(
            *[rx.segmented_control.item(label, value=key) for key, label in TABS],
            value=WhatsAppState.active_tab,
            on_change=WhatsAppState.select_tab,
            size="2",
        ),
        max_width="100%",
        overflow_x="auto",
    )


def tab_body() -> rx.Component:
    """Only the active tab is in the tree; the key remounts it on a number switch."""
    return rx.box(
        rx.match(
            WhatsAppState.active_tab,
            (TAB_CHATS, chats_tab()),
            (TAB_CONNECTION, connection_tab()),
            (TAB_PROFILE, profile_tab()),
            (TAB_QR, qr_tab()),
            (TAB_MENU, menu_tab()),
            (TAB_TEMPLATES, templates_tab()),
            (TAB_CONTACTS, contacts_tab()),
            (TAB_CAMPAIGNS, campaigns_tab()),
            connection_tab(),
        ),
        key=WhatsAppState.selected_connection_id,
        width="100%",
    )


def _no_numbers_state() -> rx.Component:
    return empty_state(
        "message-circle",
        "Aún no hay un número de WhatsApp conectado",
        "Los números de WhatsApp se conectan desde la administración de Qualify. Pide al "
        "equipo de Qualify que conecte el número de tu negocio y aparecerá aquí.",
        # N8 (m-24842961): «Pedir ayuda 1:1» lives in Tus redes.
        action=rx.link(
            rx.button("Pedir ayuda en Tus redes", variant="soft", size="3"),
            href="/connections",
        ),
    )


def _whatsapp_body() -> rx.Component:
    return page_body(
        rx.cond(
            WhatsAppState.load_error != "",
            callout(WhatsAppState.load_error, "error"),
            rx.cond(
                WhatsAppState.is_loading & ~WhatsAppState.has_numbers,
                rx.vstack(skeleton_rows(1, height="2.25rem"), skeleton_card(5), width="100%"),
                rx.cond(
                    WhatsAppState.show_empty_state,
                    _no_numbers_state(),
                    rx.vstack(tab_strip(), tab_body(), spacing="4", width="100%"),
                ),
            ),
        ),
    )


def whatsapp_index() -> rx.Component:
    return app_shell(whatsapp_header(), _whatsapp_body())


# ======================================================================================
# Conexión
# ======================================================================================


def verify_button() -> rx.Component:
    return rx.button(
        rx.icon("shield-check", size=14),
        "Verificar ahora",
        on_click=WhatsAppState.verify_now,
        loading=WhatsAppState.verifying,
        variant="soft",
        size="2",
        **T.tone_scheme("neutral"),
    )


def _status_banner(number: rx.Var) -> rx.Component:
    """Degraded/revoked: the administrative hint, never an OAuth «Reconectar» (WA-05)."""
    return rx.match(
        number.status,
        ("degraded", callout(WHATSAPP_RECONNECT_HINT, "warn")),
        ("revoked", callout(WHATSAPP_RECONNECT_HINT, "error", icon="circle-x")),
        rx.fragment(),
    )


def _kv_pill(label: str, value: rx.Var[str], tone: rx.Var[str]) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="2", color=T.TEXT_MUTED, min_width="9rem"),
        tone_pill(value, tone),
        align="center",
        spacing="3",
        width="100%",
    )


def connection_tab() -> rx.Component:
    number = WhatsAppState.selected_number
    return rx.vstack(
        banner(WhatsAppState.connection_banner, WhatsAppState.connection_banner_tone),
        _status_banner(number),
        card(
            rx.vstack(
                rx.hstack(
                    platform_badge("whatsapp"),
                    rx.heading(number.label, size="4", as_="h2"),
                    rx.spacer(),
                    rx.cond(number.status == "active", verify_button(), rx.fragment()),
                    tone_pill(number.status_label, number.status_tone),
                    width="100%",
                    align="center",
                    wrap="wrap",
                    spacing="3",
                ),
                rx.divider(),
                rx.grid(
                    rx.vstack(
                        kv("Número", number.display_phone_number, mono=True),
                        kv("Nombre verificado", number.verified_name),
                        _kv_pill(
                            "Estado del nombre", number.name_status_label, number.name_status_tone
                        ),
                        _kv_pill("Calidad", number.quality_label, number.quality_tone),
                        kv("Límite de mensajes", number.tier_label),
                        spacing="3",
                        width="100%",
                    ),
                    rx.vstack(
                        _kv_pill(
                            "Estado en Meta",
                            number.platform_status_label,
                            number.platform_status_tone,
                        ),
                        kv("Marca", number.brand),
                        kv("Última verificación", number.last_health_checked_at),
                        kv("Datos de Meta al día", number.last_synced_at),
                        kv("Último mensaje recibido", number.last_inbound_at),
                        spacing="3",
                        width="100%",
                    ),
                    columns=rx.breakpoints(initial="1", md="2"),
                    spacing="4",
                    width="100%",
                ),
                spacing="4",
                width="100%",
                align_items="start",
            ),
            padding="1.25rem 1.5rem",
        ),
        rx.text(
            "«Verificar ahora» pregunta a Meta por el acceso y por los datos del número. "
            "Nada lo ejecuta solo.",
            size="1",
            color=T.TEXT_FAINT,
        ),
        metrics_block(),
        spacing="4",
        width="100%",
        align_items="start",
    )


# ======================================================================================
# Perfil
# ======================================================================================


def _field(label: str, control: rx.Component, hint: str | None = None) -> rx.Component:
    return rx.vstack(
        rx.text(label, size="2", weight="medium"),
        control,
        *([rx.text(hint, size="1", color=T.TEXT_FAINT)] if hint else []),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _text_input(field: str, value: rx.Var[str], max_length: int, **props: object) -> rx.Component:
    return rx.input(
        value=value,
        on_change=lambda v: WhatsAppState.set_profile_field(field, v),
        max_length=max_length,
        width="100%",
        **props,
    )


def _photo_block() -> rx.Component:
    profile = WhatsAppState.profile
    return rx.hstack(
        media_thumb(
            profile.picture_url, size="72px", round=True, icon="store", alt="Foto de perfil"
        ),
        rx.vstack(
            rx.text("Foto de perfil", size="2", weight="medium"),
            dropzone(
                rx.hstack(
                    rx.cond(
                        WhatsAppState.photo_uploading,
                        rx.text("Subiendo foto…", size="2", color=T.TEXT_MUTED),
                        rx.hstack(
                            rx.icon("image-up", size=T.ICON_SM),
                            rx.text("Cambiar foto (JPG o PNG, hasta 5 MB)", size="2"),
                            spacing="2",
                            align="center",
                        ),
                    ),
                    align="center",
                ),
                upload_id=_PHOTO_UPLOAD_ID,
                accept=_PHOTO_ACCEPT,
                on_drop=WhatsAppState.handle_photo_upload(
                    rx.upload_files(upload_id=_PHOTO_UPLOAD_ID)
                ),
                variant="compact",
                disabled=WhatsAppState.photo_uploading,
            ),
            spacing="1",
            align_items="start",
        ),
        spacing="4",
        align="center",
        width="100%",
        wrap="wrap",
    )


def _vertical_select() -> rx.Component:
    return rx.select.root(
        rx.select.trigger(placeholder="Elige una categoría", width="100%"),
        rx.select.content(*[rx.select.item(label, value=key) for key, label in VERTICALS]),
        value=WhatsAppState.form_vertical,
        on_change=lambda v: WhatsAppState.set_profile_field("vertical", v),
    )


def profile_form() -> rx.Component:
    return card(
        rx.vstack(
            _photo_block(),
            rx.divider(),
            rx.grid(
                _field(
                    "Descripción corta",
                    _text_input("about", WhatsAppState.form_about, MAX_ABOUT_CHARS),
                    f"Lo primero que ve el cliente bajo tu nombre. Hasta {MAX_ABOUT_CHARS} "
                    "caracteres.",
                ),
                _field("Categoría", _vertical_select()),
                _field(
                    "Correo",
                    _text_input("email", WhatsAppState.form_email, MAX_EMAIL_CHARS, type="email"),
                ),
                _field(
                    "Dirección",
                    _text_input("address", WhatsAppState.form_address, MAX_ADDRESS_CHARS),
                ),
                _field(
                    "Web",
                    _text_input(
                        "website_1",
                        WhatsAppState.form_website_1,
                        MAX_WEBSITE_CHARS,
                        placeholder="https://",
                    ),
                ),
                _field(
                    "Otra web (opcional)",
                    _text_input(
                        "website_2",
                        WhatsAppState.form_website_2,
                        MAX_WEBSITE_CHARS,
                        placeholder="https://",
                    ),
                ),
                columns=rx.breakpoints(initial="1", md="2"),
                spacing="4",
                width="100%",
            ),
            _field(
                "Descripción",
                rx.text_area(
                    value=WhatsAppState.form_description,
                    on_change=lambda v: WhatsAppState.set_profile_field("description", v),
                    max_length=MAX_DESCRIPTION_CHARS,
                    rows="4",
                    width="100%",
                ),
                f"Hasta {MAX_DESCRIPTION_CHARS} caracteres.",
            ),
            rx.hstack(
                rx.button(
                    rx.icon("refresh-cw", size=T.ICON_SM),
                    "Volver a leer de Meta",
                    on_click=WhatsAppState.reload_profile,
                    variant="ghost",
                    size="2",
                    **T.tone_scheme("neutral"),
                ),
                rx.spacer(),
                rx.button(
                    "Descartar cambios",
                    on_click=WhatsAppState.reset_profile_form,
                    variant="soft",
                    size="2",
                    **T.tone_scheme("neutral"),
                ),
                rx.button(
                    rx.icon("save", size=15),
                    "Guardar",
                    on_click=WhatsAppState.save_profile_form,
                    loading=WhatsAppState.profile_saving,
                    size="2",
                ),
                width="100%",
                align="center",
                spacing="3",
                wrap="wrap",
            ),
            spacing="4",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
    )


def profile_tab() -> rx.Component:
    return rx.vstack(
        banner(WhatsAppState.profile_banner, WhatsAppState.profile_banner_tone),
        rx.cond(
            WhatsAppState.profile_ready,
            profile_form(),
            rx.cond(
                WhatsAppState.profile_failed,
                retry_button("Volver a leer el perfil", WhatsAppState.reload_profile),
                skeleton_card(5),
            ),
        ),
        spacing="4",
        width="100%",
        align_items="start",
        on_mount=WhatsAppState.ensure_profile_loaded,
    )


# ======================================================================================
# QR
# ======================================================================================


def _qr_create_card() -> rx.Component:
    return card(
        rx.vstack(
            rx.heading("Crear código", size="3", as_="h2"),
            rx.text(
                "Cada código abre un chat con tu número y un mensaje ya escrito. El canal "
                "va al principio del mensaje: así sabemos por dónde llegó cada cliente.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.grid(
                _field(
                    "Canal",
                    rx.select.root(
                        rx.select.trigger(width="100%"),
                        rx.select.content(
                            *[rx.select.item(label, value=key) for key, label, _ in QR_CHANNELS]
                        ),
                        value=WhatsAppState.qr_channel,
                        on_change=WhatsAppState.set_qr_channel,
                    ),
                ),
                _field(
                    "Mensaje (opcional)",
                    rx.input(
                        value=WhatsAppState.qr_text,
                        on_change=WhatsAppState.set_qr_text,
                        max_length=MAX_QR_MESSAGE_CHARS,
                        placeholder="Ej.: quiero ver el menú",
                        width="100%",
                    ),
                ),
                columns=rx.breakpoints(initial="1", md="2"),
                spacing="4",
                width="100%",
            ),
            rx.hstack(
                rx.vstack(
                    rx.text("El cliente verá escrito", size="1", color=T.TEXT_MUTED),
                    rx.text(
                        rx.cond(WhatsAppState.qr_preview != "", WhatsAppState.qr_preview, "—"),
                        size="2",
                    ),
                    spacing="0",
                    align_items="start",
                ),
                rx.spacer(),
                rx.text(
                    WhatsAppState.qr_preview_count,
                    size="1",
                    color=T.TEXT_FAINT,
                    class_name="q-nums",
                ),
                rx.button(
                    rx.icon("qr-code", size=15),
                    "Crear código",
                    on_click=WhatsAppState.create_qr,
                    loading=WhatsAppState.qr_creating,
                    size="2",
                ),
                width="100%",
                align="center",
                spacing="3",
                wrap="wrap",
            ),
            spacing="3",
            width="100%",
            align_items="start",
        ),
        padding="1.25rem 1.5rem",
    )


def _qr_delete_action(qr: QrCodeVM) -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("trash-2", size=T.ICON_SM),
                "Eliminar",
                loading=WhatsAppState.qr_deleting_code == qr.code,
                variant="soft",
                size="1",
                **T.tone_scheme("neutral"),
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title("Eliminar código QR"),
            rx.alert_dialog.description(
                "Los códigos ya impresos dejarán de abrir el chat. Esta acción no se puede "
                "deshacer."
            ),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button("Cancelar", variant="soft", **T.tone_scheme("neutral")),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        "Eliminar",
                        on_click=WhatsAppState.delete_qr(qr.code),
                        **T.tone_scheme("error"),
                    ),
                ),
                spacing="3",
                margin_top="1rem",
                justify="end",
            ),
        ),
    )


def _qr_card(qr: QrCodeVM) -> rx.Component:
    has_image = qr.image_url != ""
    return card(
        rx.hstack(
            media_thumb(qr.image_url, size="112px", icon="qr-code", alt="Código QR", fit="contain"),
            rx.vstack(
                rx.hstack(
                    rx.cond(qr.channel_label != "", tag(qr.channel_label), rx.fragment()),
                    mono(qr.code, size="1", color=T.TEXT_FAINT),
                    spacing="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.text(qr.prefilled_message, size="2", weight="medium"),
                mono(qr.deep_link_url, size="1", overflow_wrap="anywhere", color=T.TEXT_MUTED),
                rx.cond(
                    has_image,
                    rx.fragment(),
                    rx.text(
                        "Meta solo entrega la imagen al crear el código. Usa el enlace, o "
                        "crea el código de nuevo para descargarla.",
                        size="1",
                        color=T.TEXT_FAINT,
                    ),
                ),
                rx.hstack(
                    rx.cond(
                        has_image,
                        rx.link(
                            rx.button(
                                rx.icon("download", size=T.ICON_SM),
                                "Descargar PNG",
                                variant="soft",
                                size="1",
                                **T.tone_scheme("neutral"),
                            ),
                            href=qr.image_url,
                            is_external=True,
                            custom_attrs={"download": "qr-whatsapp.png"},
                        ),
                        rx.fragment(),
                    ),
                    rx.button(
                        rx.icon("copy", size=T.ICON_SM),
                        "Copiar enlace",
                        on_click=[
                            rx.set_clipboard(qr.deep_link_url),
                            rx.toast.success("Enlace copiado"),
                        ],
                        variant="soft",
                        size="1",
                        **T.tone_scheme("neutral"),
                    ),
                    _qr_delete_action(qr),
                    spacing="2",
                    wrap="wrap",
                ),
                spacing="2",
                align_items="start",
                width="100%",
                min_width="0",
            ),
            spacing="4",
            align="start",
            width="100%",
        ),
        padding="1rem 1.25rem",
    )


def _qr_list() -> rx.Component:
    return rx.cond(
        WhatsAppState.qr_ready,
        rx.cond(
            WhatsAppState.qr_codes.length() > 0,
            rx.vstack(rx.foreach(WhatsAppState.qr_codes, _qr_card), spacing="3", width="100%"),
            empty_state(
                "qr-code",
                "Aún no tienes códigos QR",
                "Crea uno por cada lugar donde te encuentran tus clientes: el mostrador, el "
                "empaque, la bio de Instagram.",
            ),
        ),
        rx.cond(
            WhatsAppState.qr_failed,
            retry_button("Volver a leer los códigos", WhatsAppState.reload_qr),
            skeleton_rows(3, height="8rem", radius=T.RADIUS_CARD),
        ),
    )


def qr_tab() -> rx.Component:
    return rx.vstack(
        banner(WhatsAppState.qr_banner, WhatsAppState.qr_banner_tone),
        _qr_create_card(),
        rx.hstack(
            rx.heading("Tus códigos", size="3", as_="h2"),
            rx.spacer(),
            rx.button(
                rx.icon("refresh-cw", size=T.ICON_SM),
                "Actualizar",
                on_click=WhatsAppState.reload_qr,
                variant="ghost",
                size="1",
                **T.tone_scheme("neutral"),
            ),
            width="100%",
            align="center",
        ),
        _qr_list(),
        spacing="4",
        width="100%",
        align_items="start",
        on_mount=WhatsAppState.ensure_qr_loaded,
    )
