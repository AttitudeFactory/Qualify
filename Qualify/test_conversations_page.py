"""`/conversations` as a screen (QUA-226, E2): where it sits in the sidebar, how it is
registered, what it renders, and that it reaches the backend only through its state.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from .ui.layout import NAV_ITEMS, NAV_ZONES

_HERE = Path(__file__).parent


def test_nav_item_sits_in_escuchas_after_contenido_before_creadores() -> None:
    assert ("Conversaciones", "messages-square", "/conversations", True) in NAV_ITEMS
    zones = {zone: [label for label, *_ in items] for zone, _title, items in NAV_ZONES}
    listen = zones["listen"]
    assert listen.index("Conversaciones") == listen.index("Contenido") + 1
    assert listen.index("Creadores") == listen.index("Conversaciones") + 1
    assert "Conversaciones" not in zones["publish"]


def test_route_is_registered_behind_login() -> None:
    source = (_HERE / "Qualify.py").read_text(encoding="utf-8")
    start = source.index("conversations_index,")
    block = source[start : source.index(")", source.index("on_load", start)) + 1]
    assert 'route="/conversations"' in block
    assert "AuthState.require_login" in block
    assert "ConversationsState.enter_page" in block


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
        "Ir a Conexiones",
        "Aún no hay una cuenta de Instagram conectada",
        "Todavía no se han leído mensajes de esta cuenta",
        "Aún no hay conversaciones en esta cuenta",
        "Se muestran los últimos 50 mensajes",
        "Volver a las conversaciones",
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
