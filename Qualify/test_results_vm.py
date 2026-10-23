"""Resultados (m-24843003, RESULTADOS-5): tabs with their own address (N5), one name per
place (N1), every figure opens its list (N11), no tab without a way out (N8), and the old
`/clarity` and `/menciones` addresses still work."""

from __future__ import annotations

import ast
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from qualify_api.home import ResultsCounts

from . import results_vm as V
from .mentions_paging import SENTIMENT_PARAM, sentiment_from_param
from .ui.layout import NAV_ITEMS

_HERE = Path(__file__).parent


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


# --- tabs and addresses ---------------------------------------------------------------


def test_the_four_tabs_in_the_guide_order() -> None:
    assert [label for _key, label in V.TABS] == [
        "Redes",
        "WhatsApp",
        "Tu página web",
        "Quién habla de ti",
    ]


@pytest.mark.parametrize("key", sorted(V.TAB_KEYS))
def test_every_tab_has_its_own_address_and_reads_it_back(key: str) -> None:
    url = V.tab_url(key)
    assert urlparse(url).path == V.RESULTS_ROUTE
    assert V.resolve_tab(_query(url)[V.TAB_PARAM][0]) == key


def test_junk_or_missing_tab_lands_on_redes() -> None:
    assert V.resolve_tab("") == V.TAB_SOCIAL
    assert V.resolve_tab("<script>") == V.TAB_SOCIAL


def test_switching_a_tab_pushes_its_address_and_names_the_browser_tab() -> None:
    script = V.tab_switch_script(V.TAB_MENTIONS)
    assert "history.pushState" in script
    assert '"/resultados?tab=menciones"' in script
    assert '"Qualify · Quién habla de ti"' in script
    # Entering the page (or «atrás») only names the tab; it never adds a history step.
    assert "pushState" not in V.tab_title_script(V.TAB_WEB)


def test_browser_tab_titles() -> None:
    assert V.tab_title(V.TAB_SOCIAL) == "Qualify · Resultados"
    assert V.tab_title(V.TAB_WEB) == "Qualify · Tu página web"
    assert V.tab_title(V.TAB_MENTIONS) == "Qualify · Quién habla de ti"
    # Never the WhatsApp module's own name alone (N1: one name per place).
    assert V.tab_title(V.TAB_WHATSAPP) != "Qualify · WhatsApp"


# --- old addresses --------------------------------------------------------------------


def test_old_mentions_link_keeps_its_filter() -> None:
    url = V.legacy_mentions_url({SENTIMENT_PARAM: "negativas"})
    query = _query(url)
    assert query[V.TAB_PARAM] == [V.TAB_MENTIONS]
    assert sentiment_from_param(query[SENTIMENT_PARAM][0]) == "Negativa"


def test_old_clarity_link_opens_the_website_tab() -> None:
    assert V.legacy_clarity_url({}) == "/resultados?tab=web"
    # A stray `tab` in the old address never overrides the destination tab.
    assert V.legacy_clarity_url({"tab": "redes"}) == "/resultados?tab=web"


def _routes() -> dict[str, ast.Call]:
    tree = ast.parse((_HERE / "Qualify.py").read_text(encoding="utf-8"))
    found: dict[str, ast.Call] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_page":
            route = {k.arg: k.value for k in node.keywords}.get("route")
            if isinstance(route, ast.Constant):
                found[route.value] = node
    return found


@pytest.mark.parametrize(
    ("route", "handler"),
    [("/menciones", "redirect_mentions"), ("/clarity", "redirect_clarity")],
)
def test_old_routes_only_redirect(route: str, handler: str) -> None:
    call = _routes()[route]
    on_load = {k.arg: k.value for k in call.keywords}["on_load"]
    assert ast.unparse(on_load) == f"ResultsState.{handler}"


def test_menu_has_resultados_and_no_longer_the_two_old_entries() -> None:
    routes = {route: label for label, _icon, route, _enabled in NAV_ITEMS}
    assert routes[V.RESULTS_ROUTE] == "Resultados"
    assert "/menciones" not in routes and "/clarity" not in routes


def test_no_app_link_points_at_the_old_addresses() -> None:
    offenders = []
    for path in sorted(_HERE.glob("*.py")):
        if path.name.startswith("test_") or path.name == "Qualify.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and node.value in ("/clarity", "/menciones"):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders


# --- figures --------------------------------------------------------------------------


def _counts(**over: object) -> ResultsCounts:
    base: dict[str, object] = {
        "messages_week_dm": 5,
        "people_week_dm": 3,
        "comments_week": 4,
        "published_week": 2,
        "messages_week_whatsapp": 7,
        "people_week_whatsapp": 1,
        "mentions_week": 1,
        "instagram_connected": True,
        "whatsapp_connected": True,
    }
    base.update(over)
    return ResultsCounts(**base)  # type: ignore[arg-type]


def test_every_figure_opens_its_list() -> None:
    vm = V.build_results_vm(_counts())
    social = {stat.key: (stat.label, stat.value, stat.href) for stat in vm.social}
    assert social == {
        "messages": ("Te escribieron por Instagram", 5, "/conversations"),
        "comments": ("Comentaron", 4, "/inbox"),
        "published": ("Publicaste", 2, "/planner"),
        "mentions": ("Hablaron de ti", 1, "/resultados?tab=menciones"),
    }
    assert {stat.href for stat in vm.whatsapp} == {V.WHATSAPP_CHATS_URL}
    assert [stat.value for stat in vm.whatsapp] == [7, 1]


def test_people_hint_is_singular_or_plural() -> None:
    assert V.people_hint(1) == "1 persona"
    assert V.people_hint(3) == "3 personas"
    assert V.build_results_vm(_counts()).social[0].hint == "3 personas"


def test_without_connections_each_tab_says_what_to_connect() -> None:
    vm = V.build_results_vm(ResultsCounts())
    assert vm.social_needs_connection and not vm.social_quiet
    assert vm.whatsapp_needs_connection and not vm.whatsapp_quiet
    assert vm == V.EMPTY_RESULTS


def test_connected_but_quiet_week_offers_a_way_out_not_zeros() -> None:
    zeros = {
        k: 0
        for k in (
            "messages_week_dm",
            "people_week_dm",
            "comments_week",
            "published_week",
            "messages_week_whatsapp",
            "people_week_whatsapp",
            "mentions_week",
        )
    }
    vm = V.build_results_vm(_counts(**zeros))
    assert vm.social_quiet and not vm.social_needs_connection
    assert vm.whatsapp_quiet and not vm.whatsapp_needs_connection


def test_figures_show_even_without_the_connection_when_there_is_something() -> None:
    """A disconnected account with history still shows its week, never «connect»."""
    vm = V.build_results_vm(_counts(instagram_connected=False, whatsapp_connected=False))
    assert not vm.social_needs_connection and not vm.whatsapp_needs_connection


# --- the page -------------------------------------------------------------------------


def test_page_title_is_the_menu_name() -> None:
    source = (_HERE / "results_page.py").read_text(encoding="utf-8")
    assert 'page_header("Resultados"' in source
    assert _routes()["/resultados"] is not None


def test_every_empty_state_of_the_page_has_a_way_out() -> None:
    tree = ast.parse((_HERE / "results_page.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "empty_state"
    ]
    assert calls
    for call in calls:
        assert "action" in {k.arg for k in call.keywords}, ast.unparse(call)
