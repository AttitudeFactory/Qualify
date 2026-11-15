"""m-25017861 (BU-A9, decision D1): «Ajustes de chats», apart from the messages."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from .chat_settings_page import chat_settings_index
from .chat_settings_state import ChatSettingsState
from .chat_settings_vm import (
    ALL_CHATS_ROWS,
    ALL_CHATS_TITLE,
    CHAT_SETTINGS_TITLE,
    MENU_TITLE,
    STARTER_QUESTIONS_LINE,
    STARTER_QUESTIONS_TITLE,
    WHATSAPP_ROWS,
    account_to_open,
    instagram_rows,
    instagram_settings_href,
)
from .ui.layout import NAV_ITEMS, NAV_ZONES
from .whatsapp_vm import TAB_MENU, legacy_panel_target, legacy_settings_target, tab_url

_HERE = Path(__file__).parent
_A = "00000000-0000-4000-8000-0000000000aa"
_B = "00000000-0000-4000-8000-0000000000bb"


def _present(rendered: str, text: str) -> bool:
    escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
    return text in rendered or escaped in rendered


# --- the names (decision vi, D1, D5) ----------------------------------------------------


def test_the_names_are_the_founders() -> None:
    assert CHAT_SETTINGS_TITLE == "Ajustes de chats"
    assert ALL_CHATS_TITLE == "Para todos tus chats"
    assert MENU_TITLE == "Tu menú de bienvenida"
    assert STARTER_QUESTIONS_TITLE == "Preguntas iniciales"
    assert STARTER_QUESTIONS_LINE == "Lo que tu cliente puede tocar al abrir el chat"


def test_no_text_says_qualify_answers_by_itself() -> None:
    """Decision vi: never «Respuesta automática», on the hub or its rows."""
    rendered = str(chat_settings_index().render())
    for gone in ("Respuesta automática", "respuesta automática", "Atajos"):
        assert not _present(rendered, gone), gone


def test_the_hub_has_three_cards_and_every_setting_of_today() -> None:
    """The ticket's list: nothing that is set up today is lost — each row says where."""
    rendered = str(chat_settings_index().render())
    for text in (CHAT_SETTINGS_TITLE, ALL_CHATS_TITLE, "WhatsApp", "Instagram"):
        assert _present(rendered, text), text
    keys = [row.key for row in ALL_CHATS_ROWS]
    assert keys == ["mensajes-guardados", "formas-de-pago", "como-llegar"]
    assert {row.href for row in ALL_CHATS_ROWS} == {
        "/responder?tab=mensajes",
        "/whatsapp?tab=numero&sub=pagos",
        "/whatsapp?tab=numero&sub=perfil",
    }
    assert [row.title for row in WHATSAPP_ROWS] == [MENU_TITLE, STARTER_QUESTIONS_TITLE]
    assert all(row.href == tab_url(TAB_MENU) for row in WHATSAPP_ROWS)
    assert STARTER_QUESTIONS_LINE in WHATSAPP_ROWS[1].detail
    # The Instagram drawer is on this page (its rows open it in place).
    assert "ice_breakers_panel()" in (_HERE / "chat_settings_page.py").read_text("utf-8")


def test_the_page_uses_the_design_system_and_the_state_only() -> None:
    source = (_HERE / "chat_settings_page.py").read_text(encoding="utf-8")
    imported = {
        node.module or ""
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("provider" in name or name.startswith("qualify_api") for name in imported)
    assert "rx.color(" not in source and "color_scheme=" not in source
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", source)  # no hardcoded colour


# --- Instagram rows and the «Ajustes de este canal» address ----------------------------


def test_instagram_rows_name_the_account_only_when_there_are_several() -> None:
    one = instagram_rows([(_A, "@bianki")])
    assert [(r.connection_id, r.title, r.detail) for r in one] == [
        (_A, "Preguntas iniciales", STARTER_QUESTIONS_LINE)
    ]
    two = instagram_rows([(_A, "@bianki"), (_B, "@polette")])
    assert [r.title for r in two] == [
        "Preguntas iniciales de @bianki",
        "Preguntas iniciales de @polette",
    ]
    assert instagram_rows([]) == []


def test_the_account_to_open_is_one_of_the_business() -> None:
    assert instagram_settings_href(_A) == f"/chats/ajustes/instagram?cuenta={_A}"
    assert account_to_open(_B, [_A, _B]) == _B
    assert account_to_open("<script>", [_A, _B]) == _A
    assert account_to_open("", []) == ""


def test_account_context_is_only_for_the_loaded_accounts() -> None:
    state = SimpleNamespace(_accounts=[(_A, "@bianki")], _zone_name="America/Bogota")
    assert ChatSettingsState._account_context(state, _A) == ("@bianki", "America/Bogota")  # type: ignore[arg-type]
    assert ChatSettingsState._account_context(state, _B) is None  # type: ignore[arg-type]


# --- old addresses -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("params", "target"),
    [
        ({"tab": "respuesta"}, "/chats/ajustes/whatsapp"),
        ({"tab": "menu", "cuenta": _A}, f"/chats/ajustes/whatsapp?cuenta={_A}"),
        (
            {"tab": "menu", "flujo": "menu", "paso": "2", "objeto": _B, "otro": "x"},
            f"/chats/ajustes/whatsapp?flujo=menu&paso=2&objeto={_B}",
        ),
        ({"tab": "menu", "flujo": "menu", "paso": "999"}, "/chats/ajustes/whatsapp?flujo=menu"),
        ({"tab": "menu", "objeto": _B}, "/chats/ajustes/whatsapp"),  # no form, no id
        ({"tab": "chats"}, None),
        ({"tab": "numero", "sub": "pagos"}, None),
        ({}, None),
    ],
)
def test_an_old_menu_address_lands_in_ajustes(params: dict, target: str | None) -> None:
    assert legacy_settings_target(params) == target
    assert legacy_panel_target(params) == target


def test_the_promotions_redirect_still_wins_for_its_addresses() -> None:
    assert legacy_panel_target({"tab": "plantillas"}) == "/whatsapp/promociones?sub=aprobados"


# --- routes and menu -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("route", "handler"),
    [
        ("/chats/ajustes", "ChatSettingsState.enter_page"),
        ("/chats/ajustes/instagram", "ChatSettingsState.enter_page"),
        ("/chats/ajustes/whatsapp", "WhatsAppState.enter_page"),
    ],
)
def test_routes_are_registered_behind_login(route: str, handler: str) -> None:
    source = (_HERE / "Qualify.py").read_text(encoding="utf-8")
    start = source.index(f'    route="{route}",')
    block = source[start : source.index(")", source.index("on_load", start)) + 1]
    assert "AuthState.require_login" in block and handler in block


def test_the_entry_sits_last_in_atiende() -> None:
    assert ("Ajustes de chats", "sliders-horizontal", "/chats/ajustes", True) in NAV_ITEMS
    zones = {zone: [label for label, *_ in items] for zone, _t, items in NAV_ZONES}
    assert zones["listen"][-1] == "Ajustes de chats"


def test_logout_resets_this_state() -> None:
    from .auth_state import business_state_classes

    assert "ChatSettingsState" in {cls.__name__ for cls in business_state_classes()}


def test_the_whatsapp_settings_page_has_its_name_and_way_back() -> None:
    from .whatsapp_page import whatsapp_settings_index

    rendered = str(whatsapp_settings_index().render())
    for text in (MENU_TITLE, CHAT_SETTINGS_TITLE, "/chats/ajustes"):
        assert _present(rendered, text), text
    assert not _present(rendered, "Secciones de WhatsApp")  # no messages strip here
