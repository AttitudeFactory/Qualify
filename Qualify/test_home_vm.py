"""Inicio (m-24842962, NAV-4): view models, routing and the filtered destinations."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from qualify_api.home import HomeCounts

from .conversations_vm import FILTER_PENDING, filter_from_param
from .home_vm import (
    COMMENTS_URL,
    CONNECTIONS_URL,
    CONVERSATIONS_PENDING_URL,
    CONVERSATIONS_URL,
    CREATE_URL,
    DRAFTS_TO_APPROVE_URL,
    MENTIONS_URL,
    WHATSAPP_CHATS_URL,
    build_home_vm,
    comments_unanswered_label,
    drafts_to_approve_label,
    people_waiting_label,
)
from .planner_vm import gallery_filter_from_param
from .ui.layout import NAV_ITEMS

_HERE = Path(__file__).parent

_SET_UP = {"instagram_connected": True, "has_publication": True}


def test_zero_data_is_never_empty_first_steps_show() -> None:
    vm = build_home_vm(HomeCounts())
    assert vm.today == []
    assert [s.href for s in vm.first_steps] == [CONNECTIONS_URL, CREATE_URL]
    assert vm.first_steps[0].label == "Conecta tu Instagram para publicar desde aquí"
    assert vm.first_steps[1].label == "Crea tu primera publicación con la foto de un producto"
    assert not vm.all_clear
    assert vm.week_needs_connection


def test_each_first_step_disappears_when_done() -> None:
    connected = build_home_vm(HomeCounts(instagram_connected=True))
    assert [s.key for s in connected.first_steps] == ["create"]
    created = build_home_vm(HomeCounts(has_publication=True))
    assert [s.key for s in created.first_steps] == ["connect"]


def test_nothing_pending_and_set_up_is_all_clear() -> None:
    vm = build_home_vm(HomeCounts(**_SET_UP))
    assert vm.all_clear
    assert not vm.week_needs_connection  # connected: the zeros are real figures


def test_today_shows_only_what_waits_and_links_filtered() -> None:
    vm = build_home_vm(HomeCounts(people_waiting=2, comments_unanswered=5, **_SET_UP))
    assert [(c.label, c.href) for c in vm.today] == [
        ("2 personas esperan tu respuesta", CONVERSATIONS_PENDING_URL),
        ("5 comentarios sin responder", COMMENTS_URL),
    ]
    assert not vm.all_clear


def test_today_has_at_most_three_cards_in_order() -> None:
    vm = build_home_vm(
        HomeCounts(people_waiting=1, drafts_to_approve=3, comments_unanswered=1, **_SET_UP)
    )
    assert [c.href for c in vm.today] == [
        CONVERSATIONS_PENDING_URL,
        DRAFTS_TO_APPROVE_URL,
        COMMENTS_URL,
    ]


@pytest.mark.parametrize(
    ("fn", "one", "many"),
    [
        (people_waiting_label, "1 persona espera tu respuesta", "3 personas esperan tu respuesta"),
        (
            drafts_to_approve_label,
            "1 publicación lista para que la apruebes",
            "3 publicaciones listas para que las apruebes",
        ),
        (comments_unanswered_label, "1 comentario sin responder", "3 comentarios sin responder"),
    ],
)
def test_labels_agree_in_number(fn, one: str, many: str) -> None:
    assert fn(1) == one
    assert fn(3) == many


def test_week_figures_link_to_their_detail() -> None:
    vm = build_home_vm(
        HomeCounts(
            messages_week_dm=4,
            messages_week_whatsapp=1,
            comments_week=7,
            mentions_week=2,
            **_SET_UP,
        )
    )
    assert [(s.label, s.value, s.href) for s in vm.week] == [
        ("Te escribieron", 5, CONVERSATIONS_URL),
        ("Comentaron", 7, COMMENTS_URL),
        ("Hablaron de ti", 2, MENTIONS_URL),
    ]
    assert vm.week[0].hint == "4 por Instagram · 1 por WhatsApp"


def test_messages_open_whatsapp_when_it_carried_the_week() -> None:
    vm = build_home_vm(HomeCounts(messages_week_dm=1, messages_week_whatsapp=6))
    assert vm.week[0].href == WHATSAPP_CHATS_URL
    # Data from WhatsApp alone is something to show, even without Instagram.
    assert not vm.week_needs_connection


def test_destination_filters_are_read_by_the_lists() -> None:
    assert CONVERSATIONS_PENDING_URL.endswith("filtro=pendientes")
    assert filter_from_param("pendientes") == FILTER_PENDING
    assert filter_from_param("") is None and filter_from_param("xx") is None
    assert DRAFTS_TO_APPROVE_URL.endswith("estado=por-completar")
    assert gallery_filter_from_param("por-completar") == "needs_action"
    assert gallery_filter_from_param("") is None and gallery_filter_from_param("xx") is None


def _routes() -> dict[str, tuple[str, str]]:
    """route → (page function, title) of every `app.add_page(...)` in Qualify.py."""
    tree = ast.parse((_HERE / "Qualify.py").read_text(encoding="utf-8"))
    found: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_page":
            kw = {k.arg: k.value for k in node.keywords}
            route = kw.get("route")
            title = kw.get("title")
            page = node.args[0]
            if isinstance(route, ast.Constant) and isinstance(title, ast.Constant):
                found[route.value] = (getattr(page, "id", ""), title.value)
    return found


def test_root_is_inicio_and_mentions_has_its_own_route() -> None:
    routes = _routes()
    assert routes["/"] == ("home_index", "Qualify · Inicio")
    assert routes[MENTIONS_URL] == ("mentions_index", "Qualify · Menciones")


def test_menu_has_inicio_on_top_and_mentions_off_root() -> None:
    assert NAV_ITEMS[0] == ("Inicio", "house", "/", True)
    mentions = [route for label, _icon, route, _enabled in NAV_ITEMS if label == "Menciones"]
    assert mentions == [MENTIONS_URL]


def test_login_lands_on_inicio() -> None:
    source = (_HERE / "auth_state.py").read_text(encoding="utf-8")
    assert 'return rx.redirect("/")' in source


_ENGLISH = ("post", "feed", "dashboard", "engagement", "lead", "inbox", "Brand Kit")


def test_home_copy_has_no_english() -> None:
    strings = [
        node.value
        for name in ("home_page.py", "home_vm.py", "home_state.py")
        for node in ast.walk(ast.parse((_HERE / name).read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and " " in node.value
    ]
    for text in strings:
        if text.lstrip().startswith(("Inicio (", "State for", "Inicio's", "The ", "A ", "`")):
            continue  # docstrings and comments in English, by convention
        for word in _ENGLISH:
            assert word.lower() not in text.lower().split(), (word, text)
