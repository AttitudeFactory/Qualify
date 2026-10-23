"""«Por responder» (`/responder`, m-24842990, ATENDER-1): the tabs and their addresses,
the four counts and their «Ver», the all-clear state, and the old routes' redirects."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from qualify_api.attention import PendingCounts

from .responder_state import ResponderState
from .responder_vm import (
    ALL_CLEAR_ACTION,
    ALL_CLEAR_HREF,
    ALL_CLEAR_TITLE,
    DEFAULT_TAB,
    TAB_BUYERS,
    TAB_COMMENTS,
    TAB_LEADS,
    TAB_MESSAGES,
    TAB_WHATSAPP,
    TABS,
    WHATSAPP_CHATS_HREF,
    all_clear,
    count_label,
    count_rows,
    legacy_target,
    resolve_tab,
    tab_href,
)

_HERE = Path(__file__).parent


# --- Tabs ------------------------------------------------------------------------------


def test_the_tabs_are_the_founders_five_in_order() -> None:
    assert [label for _key, label in TABS] == [
        "Mensajes",
        "Quieren comprar",
        "Comentarios",
        "WhatsApp",
        "Interesados",
    ]


@pytest.mark.parametrize(
    ("requested", "tab"),
    [
        ("mensajes", TAB_MESSAGES),
        ("comprar", TAB_BUYERS),
        ("COMENTARIOS", TAB_COMMENTS),
        (" whatsapp ", TAB_WHATSAPP),
        ("interesados", TAB_LEADS),
        ("", DEFAULT_TAB),
        (None, DEFAULT_TAB),
        ("<script>", DEFAULT_TAB),
    ],
)
def test_resolve_tab(requested: str | None, tab: str) -> None:
    assert resolve_tab(requested) == tab


def test_tab_href_is_the_tab_address() -> None:
    assert tab_href(TAB_COMMENTS) == "/responder?tab=comentarios"
    assert (
        tab_href(TAB_MESSAGES, filtro="pendientes") == "/responder?tab=mensajes&filtro=pendientes"
    )
    assert tab_href("nope") == "/responder?tab=mensajes"


@pytest.mark.parametrize(
    ("path", "params", "target"),
    [
        ("/inbox", {}, "/responder?tab=comentarios"),
        ("/inbox/", {}, "/responder?tab=comentarios"),
        ("/conversations", {}, "/responder?tab=mensajes"),
        ("/leads/", {}, "/responder?tab=interesados"),
        # The old Consultas deep link lands on the card, in Quieren comprar.
        ("/conversations", {"consulta": "abc"}, "/responder?tab=comprar&consulta=abc"),
        # An old `?tab=` never decides the new tab; empty values are dropped.
        ("/inbox", {"tab": "x", "empty": ""}, "/responder?tab=comentarios"),
    ],
)
def test_legacy_target(path: str, params: dict[str, str], target: str) -> None:
    assert legacy_target(path, params) == target


def test_changing_tab_is_a_navigation_to_its_address() -> None:
    state = ResponderState()
    spec = ResponderState.select_tab.fn(state, TAB_BUYERS)  # type: ignore[attr-defined]
    assert spec is not None
    assert "/responder?tab=comprar" in str(spec)
    # The tab itself changes only when the new address loads (on_load reads ?tab=).
    assert state.active_tab == DEFAULT_TAB


@pytest.mark.parametrize("tab", ["nope", ["mensajes"], DEFAULT_TAB])
def test_select_tab_refuses_unknown_values_and_the_open_tab(tab: object) -> None:
    state = ResponderState()
    assert ResponderState.select_tab.fn(state, tab) is None  # type: ignore[attr-defined]


# --- Counts ----------------------------------------------------------------------------


def test_count_rows_one_per_channel_with_their_filtered_list() -> None:
    rows = count_rows(PendingCounts(messages=3, buyers=1, comments=0, whatsapp=2))
    assert [r.key for r in rows] == [TAB_MESSAGES, TAB_BUYERS, TAB_COMMENTS, TAB_WHATSAPP]
    assert [r.count for r in rows] == [3, 1, 0, 2]
    assert [r.tone for r in rows] == ["warn", "warn", "ok", "warn"]
    assert [r.href for r in rows] == [
        "/responder?tab=mensajes&filtro=pendientes",
        "/responder?tab=comprar",
        "/responder?tab=comentarios",
        WHATSAPP_CHATS_HREF,
    ]
    assert WHATSAPP_CHATS_HREF == "/whatsapp?tab=chats&filtro=sin-leer"
    assert {r.action_label for r in rows} == {"Ver"}


@pytest.mark.parametrize(
    ("count", "label"), [(0, "Al día"), (-1, "Al día"), (1, "1 espera"), (12, "12 esperan")]
)
def test_count_label(count: int, label: str) -> None:
    assert count_label(count) == label


def test_all_clear_only_when_nobody_waits_anywhere() -> None:
    assert all_clear(PendingCounts())
    assert not all_clear(PendingCounts(whatsapp=1))
    assert ALL_CLEAR_TITLE == "¡Al día! No hay nadie esperando tu respuesta."
    assert ALL_CLEAR_HREF == "/create"
    assert ALL_CLEAR_ACTION == "Crear la próxima publicación"


def test_the_counts_are_read_off_the_event_loop() -> None:
    import inspect

    source = inspect.getsource(ResponderState.load_counts.fn)  # type: ignore[attr-defined]
    assert "asyncio.to_thread(counts_for" in source


# --- Routes ----------------------------------------------------------------------------


def _add_page_calls() -> dict[str, dict[str, str]]:
    """route → {keyword: source} of every `app.add_page(...)` in Qualify.py."""
    source = (_HERE / "Qualify.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls: dict[str, dict[str, str]] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_page"
        ):
            kw = {k.arg: ast.get_source_segment(source, k.value) or "" for k in node.keywords}
            first = ast.get_source_segment(source, node.args[0]) if node.args else ""
            kw["component"] = first or ""
            route = kw.get("route", '"/"').strip('"')
            calls[route] = kw
    return calls


def test_responder_is_registered_behind_login() -> None:
    page = _add_page_calls()["/responder"]
    assert page["component"] == "responder_index"
    assert "AuthState.require_login" in page["on_load"]
    assert "ResponderState.enter_page" in page["on_load"]
    assert page["title"] == '"Qualify · Por responder"'


@pytest.mark.parametrize("route", ["/inbox", "/conversations", "/leads"])
def test_the_old_routes_only_redirect(route: str) -> None:
    page = _add_page_calls()[route]
    assert page["component"] == "legacy_redirect"
    assert page["on_load"] == "ResponderState.redirect_legacy"


def test_reply_in_private_lands_on_the_card_in_quieren_comprar() -> None:
    source = (_HERE / "inbox_state.py").read_text(encoding="utf-8")
    assert 'rx.redirect(f"/responder?tab=comprar&consulta={followup_id}")' in source
    assert "/conversations?consulta=" not in source


# --- Page ------------------------------------------------------------------------------


def _present(rendered: str, text: str) -> bool:
    escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
    return text in rendered or escaped in rendered or json.dumps(text) in rendered


def test_the_page_renders_header_tabs_counts_and_all_clear() -> None:
    from .responder_page import responder_index

    rendered = str(responder_index().render())
    for text in (
        "Por responder",
        "Las personas que te escribieron o comentaron y todavía esperan tu respuesta.",
        "Mensajes",
        "Quieren comprar",
        "Comentarios",
        "WhatsApp",
        "Interesados",
        "Reintentar",
        "Abrir los chats sin responder",
        "Quién te espera",
    ):
        assert _present(rendered, text), text
    assert "/create" in rendered


def test_the_page_talks_to_the_state_only() -> None:
    tree = ast.parse((_HERE / "responder_page.py").read_text(encoding="utf-8"))
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any("provider" in name or name.startswith("qualify_api") for name in imported)


def test_targets_are_thumb_sized_and_nothing_is_hover_only() -> None:
    """N12: every button of the page is ≥ 44 px; no tooltip/hover card carries content."""
    source = (_HERE / "responder_page.py").read_text(encoding="utf-8")
    assert source.count("min_height=_TARGET") >= 5
    assert '_TARGET = "44px"' in source
    assert "tooltip" not in source and "hover_card" not in source
