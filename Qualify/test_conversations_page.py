"""`/conversations` as a screen (QUA-226, E2): where it sits in the sidebar, how it is
registered, what it renders, and that it reaches the backend only through its state.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from .ui.layout import NAV_ITEMS, NAV_ZONES

_HERE = Path(__file__).parent


def test_por_responder_heads_atiende_and_reaches_the_private_inbox_today() -> None:
    """NAV-1 (m-24842957): the private inbox is reached through «Por responder», the
    first entry of «Atiende», which opens its hub (ATENDER-1, m-24842990)."""
    zones = {zone: [label for label, *_ in items] for zone, _title, items in NAV_ZONES}
    assert zones["listen"][0] == "Por responder"
    assert ("Por responder", "messages-square", "/responder", True) in NAV_ITEMS
    assert "Conversaciones" not in [label for label, *_ in NAV_ITEMS]


def test_route_is_registered_behind_login() -> None:
    """m-24842990: the inbox is the «Mensajes» tab of `/responder` (behind the login);
    `/conversations` only redirects there."""
    source = (_HERE / "Qualify.py").read_text(encoding="utf-8")
    start = source.index("responder_index,")
    block = source[start : source.index(")", source.index("on_load", start)) + 1]
    assert 'route="/responder"' in block
    assert "AuthState.require_login" in block
    assert "ResponderState.enter_page" in block
    legacy = source.index('route="/conversations"')
    assert "ResponderState.redirect_legacy" in source[legacy : source.index(")", legacy)]
    state_source = (_HERE / "responder_state.py").read_text(encoding="utf-8")
    assert "ConversationsState.enter_page" in state_source


def test_the_page_talks_to_the_state_only() -> None:
    """The page imports neither the provider nor any backend module."""
    tree = ast.parse((_HERE / "conversations_page.py").read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any("provider" in name or name.startswith("qualify_api") for name in imported)


def test_the_page_renders_list_conversation_composer_and_access_states() -> None:
    from .conversations_page import conversations_index

    rendered = str(conversations_index().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for text in (
        "Conversaciones",
        "Elige una conversación",
        "Responder",
        "Reconectar",
        "por verificar",
        "Ir a Tus redes",
        "Aún no hay una cuenta de Instagram conectada",
        "Todavía no se han leído mensajes de esta cuenta",
        "Aún no hay conversaciones en esta cuenta",
        "Se muestran los últimos 50 mensajes",
        "Escribe una respuesta",
        "Enviar una foto o un video",
        "Enviar un archivo (PDF)",
        "Grabar una nota de voz",
        "Enviar un corazón",
        "Eliminar para mí",
        "Sugerir respuesta",
        "Descartar",
        "Cerrar la conversación",
        "Quitar el adjunto",
        "q-conv-avatar",
        "q-conv-channel",
        "clock",
        "q-conv-day",
        "q-conv-filters",
        "qualify-voice.js",
    ):
        assert present(text), text
    for handler in (
        "open_conversation",
        "close_conversation",
        "send_reply",
        "send_heart",
        "suggest_reply",
        "discard_suggestion",
        "start_recording",
        "stop_recording",
        "cancel_recording",
        "select_account",
        "set_filter",
        "refresh",
        "clear_attachment",
        "conversations_media",
        "conversations_file",
        "hide_message",
    ):
        assert handler in rendered, handler
    # The old 1000-character counter is gone: a long text is split, not refused.
    assert "/1000" not in rendered


def test_no_except_clause_nests_the_db_error_tuple() -> None:
    """`except (A, _DB_ERRORS)` is a TypeError at catch time (a tuple inside a tuple),
    which left «Sugerir respuesta» spinning forever on 2026-10-16. The tuple must be
    unpacked (`*_DB_ERRORS`) or stand alone."""
    import re

    source = (_HERE / "conversations_state.py").read_text(encoding="utf-8")
    for match in re.finditer(r"except\s*\(([^)]*)\)", source):
        inner = match.group(1)
        if "_DB_ERRORS" in inner and "," in inner:
            assert "*_DB_ERRORS" in inner, match.group(0)


def test_the_inbox_opens_on_an_account_that_can_read_messages() -> None:
    from .conversations_state import default_account
    from .conversations_vm import AccountVM

    def account(cid: str, *, dms: bool = True, status: str = "active") -> AccountVM:
        return AccountVM(
            connection_id=cid,
            label=f"@{cid}",
            brand="",
            platform="instagram",
            channel_label="Instagram Direct",
            status=status,
            can_manage_dms=dms,
            dm_reason="",
        )

    assert default_account([]) == ""
    assert default_account([account("a", dms=False), account("b")]) == "b"
    assert default_account([account("a", status="degraded"), account("b")]) == "b"
    assert default_account([account("a", dms=False), account("b", dms=False)]) == "a"


def test_the_composer_offers_templates_and_their_manager() -> None:
    """m-24789472: «Plantillas» beside «Sugerir respuesta», the fill-in notice over the
    box, and the drawer that creates, edits, deletes (confirmed) and reorders."""
    from .conversations_page import conversations_index

    rendered = str(conversations_index().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for text in (
        "Plantillas",
        "Administrar plantillas",
        "Nueva plantilla",
        "Aún no tienes plantillas en esta cuenta",
        "Guardar",
        "Subir",
        "Bajar",
        "Editar",
        "Borrar",
        "No se puede deshacer",
        "plantillas en esta cuenta",
        "Nombre de la plantilla",
        "Mensaje de la plantilla",
        "{nombre}",
    ):
        assert present(text), text
    for handler in (
        "set_templates_menu_open",
        "load_templates",
        "apply_template",
        "open_templates_manager",
        "set_templates_manager_open",
        "start_new_template",
        "start_edit_template",
        "save_template",
        "ask_delete_template",
        "confirm_delete_template",
        "cancel_delete_template",
        "move_template",
        "template_fill_notice",
        "templates_counter",
    ):
        assert handler in rendered, handler


def test_the_picker_rows_fit_the_popover() -> None:
    """A Radix ghost button is `content-box`: at `width: 100%` its padding overflowed the
    popover into a horizontal scrollbar (2026-10-22). The row is `border-box` and its
    lines truncate as blocks."""
    import reflex as rx

    from .conversations_page import _template_item
    from .conversations_vm import TemplateVM

    template = TemplateVM(
        template_id="t1",
        title="Saludo",
        body="¡Hola!",
        preview="¡Hola!",
        is_default=True,
        is_first=True,
        is_last=True,
    )
    rendered = str(_template_item(rx.Var.create(template)).render())
    assert "border-box" in rendered
    assert "q-wa-ellipsis" in rendered and "block" in rendered


def test_the_composer_offers_quick_replies_and_template_buttons() -> None:
    """m-24789472 (phase 3): «Respuestas rápidas» among the tools with its panel, the
    picked template's buttons under the box, and the buttons editor in the manager."""
    from .conversations_page import conversations_index
    from .conversations_vm import (
        BUTTONS_HINT,
        BUTTONS_OFF_FORM_NOTICE,
        BUTTONS_OFF_NOTICE,
        QUICK_REPLIES_HINT,
        QUICK_REPLIES_WITH_BUTTONS,
    )

    rendered = str(conversations_index().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for text in (
        "Respuestas rápidas",
        "Nueva respuesta rápida",
        "Agregar",
        "Cerrar las respuestas rápidas",
        "Quitar esta respuesta rápida",
        "Botones que van con este mensaje",
        "Enviar sin botones",
        "Botones (opcional)",
        "Agregar botón",
        "Texto del botón",
        "Qué hace el botón",
        "Responder con un toque",
        "Abrir una página",
        "Quitar el botón",
        "Enlace que abre el botón",
        QUICK_REPLIES_HINT,
        QUICK_REPLIES_WITH_BUTTONS,
        BUTTONS_HINT,
        BUTTONS_OFF_NOTICE,
        BUTTONS_OFF_FORM_NOTICE,
    ):
        assert present(text), text
    for handler in (
        "toggle_quick_replies",
        "set_quick_reply_input",  # «Agregar» submits a form: its handler lives in a hook
        "remove_quick_reply",
        "drop_applied_buttons",
        "add_template_button",
        "remove_template_button",
        "set_template_button_kind",
        "set_template_button_title",
        "set_template_button_url",
        "template_form_body_error",
        "buttons_will_send",
        "kind_note",
    ):
        assert handler in rendered, handler


def test_no_session_is_never_confused_with_a_closed_window() -> None:
    """`WindowClosed` and `CapabilityUnavailable` subclass `PermissionError`: the send
    handlers signal a missing session with their own exception, so a closed window or
    a feature switched off is never worded as «vuelve a iniciar sesión»."""
    source = (_HERE / "conversations_state.py").read_text(encoding="utf-8")
    assert "raise PermissionError" not in source
    assert "except PermissionError" not in source


def test_picking_a_template_cannot_send() -> None:
    """B5 by construction: the picker's handler calls no send path of the gateway."""
    tree = ast.parse((_HERE / "conversations_state.py").read_text(encoding="utf-8"))
    handler = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "apply_template"
    )
    called = {
        node.attr
        for node in ast.walk(handler)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load)
    }
    assert "render_template" in called
    assert not called & {"reply", "reply_media", "reply_sticker", "send_reply", "send_heart"}
