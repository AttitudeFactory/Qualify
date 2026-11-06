"""Crawler metadata is present without a login, hydration or any tenant data."""

from __future__ import annotations

import ast
import json
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import reflex as rx
from reflex.compiler.compiler import compile_unevaluated_page
from reflex.plugins.sitemap import generate_links_for_sitemap
from reflex_base.registry import RegistrationContext

from . import page_metadata as metadata

_SOURCE = Path(__file__).with_name("Qualify.py")
_ROUTE_NAMES = {
    "CHOOSE_ROUTE": ["/elegir-negocio"],
    "SWITCH_ROUTE": ["/cambiar"],
    "_signup_route": ["/registro", "/signup"],
    "RESET_ROUTE": ["/reset"],
    "BRAND_START_ROUTE": ["/brand/start"],
}


def _registrations() -> list[tuple[str, str]]:
    """Read the actual registrations without booting services or worker lifespans."""
    found = []
    for node in ast.walk(ast.parse(_SOURCE.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call) or getattr(node.func, "attr", "") != "add_page":
            continue
        args = {keyword.arg: keyword.value for keyword in node.keywords}
        route = args["route"]
        if isinstance(route, ast.Constant):
            routes = [route.value]
        else:
            assert isinstance(route, ast.Name), ast.dump(route)
            routes = _ROUTE_NAMES[route.id]
        title = args["title"]
        title = title.value if isinstance(title, ast.Constant) else "Qualify · Elige un negocio"
        found.extend((path, title) for path in routes)
    return found


@pytest.fixture(autouse=True)
def _production_origin(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(
        metadata, "get_config", lambda: SimpleNamespace(deploy_url="https://app.qualify.la")
    )
    with RegistrationContext.get().fork():
        yield


def _literal(component: rx.Component, attribute: str) -> Any:
    value = getattr(component, attribute, None)
    return json.loads(str(value)) if value is not None else None


@pytest.mark.parametrize(("route", "title"), _registrations())
def test_every_registered_page_compiles_complete_metadata_without_a_session(
    route: str, title: str
) -> None:
    assert route in metadata.PAGE_DESCRIPTIONS, f"Describe the new screen: {route}"
    app = metadata.QualifyApp()
    app.add_page(lambda: rx.box("Pantalla"), route=route, title=title)
    page = next(iter(app._unevaluated_pages.values()))
    component = compile_unevaluated_page(page.route, page)
    tags = [child for child in component.children if child.tag == "meta"]
    keys = [_literal(tag, "name") or _literal(tag, "property") for tag in tags]
    assert all(count == 1 for count in Counter(keys).values()), keys
    values = dict(zip(keys, (_literal(tag, "content") for tag in tags), strict=True))
    assert values["description"] == metadata.PAGE_DESCRIPTIONS[route]
    assert values["og:description"] == values["twitter:description"] == values["description"]
    assert values["og:title"] == values["twitter:title"] == title
    assert values["og:type"] == "website"
    assert values["robots"] == "noindex, follow"
    assert values["og:image"] == values["twitter:image"] == metadata.SOCIAL_IMAGE_URL
    assert values["twitter:card"] == "summary_large_image"
    assert values["og:url"].startswith("https://app.qualify.la/")
    assert "[" not in values["og:url"]
    assert "?" not in values["og:url"]
    canonicals = [child for child in component.children if child.tag == "link"]
    if "[" in route:
        assert not canonicals
    else:
        assert len(canonicals) == 1
        assert _literal(canonicals[0], "rel") == "canonical"
        assert _literal(canonicals[0], "href") == values["og:url"]
    assert page.context["sitemap"] is None
    assert generate_links_for_sitemap([page], trailing_slash="preserve") == []


def test_real_app_installs_the_shared_metadata_policy() -> None:
    assignments = [
        node
        for node in ast.walk(ast.parse(_SOURCE.read_text(encoding="utf-8")))
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "app" for target in node.targets)
    ]
    assert len(assignments) == 1
    assert isinstance(assignments[0].value, ast.Call)
    assert assignments[0].value.func.id == "QualifyApp"


@pytest.mark.parametrize("route", ["/reset", "/canva/callback", "/registro"])
def test_query_and_fragment_secrets_never_enter_metadata(route: str) -> None:
    result = metadata.page_metadata(route + "?token=private-token#email=private-email", "Qualify")
    text = str(result)
    assert "private-token" not in text
    assert "private-email" not in text
    assert "?" not in text


def test_legacy_signup_uses_the_current_canonical() -> None:
    tags = metadata.page_metadata("/signup", "Qualify")["meta"]
    og_url = next(
        tag["content"] for tag in tags if isinstance(tag, dict) and tag.get("property") == "og:url"
    )
    assert og_url == "https://app.qualify.la/registro"


def test_new_routes_inherit_noindex_and_sitemap_exclusion() -> None:
    app = metadata.QualifyApp()
    on_load = rx.redirect("/login")
    app.add_page(
        lambda: rx.box(),
        route="/future-screen",
        title="Qualify",
        description="Tenant-provided data must not become a description",
        image="favicon.ico",
        meta=[
            {"name": "robots", "content": "index"},
            {"name": "theme-color", "content": "teal"},
            rx.el.meta(property="og:image", content="favicon.ico"),
            rx.el.link(rel="canonical", href="https://wrong.example/"),
        ],
        context={"sitemap": {}, "other": "preserved"},
        on_load=on_load,
    )
    page = app._unevaluated_pages["future-screen"]
    assert page.context == {"sitemap": None, "other": "preserved"}
    assert page.image == metadata.SOCIAL_IMAGE_URL
    assert page.description == metadata.DEFAULT_DESCRIPTION
    assert page.on_load is on_load
    assert [tag for tag in page.meta if isinstance(tag, dict) and tag.get("name") == "robots"] == [
        {"name": "robots", "content": "noindex, follow"}
    ]
    assert {"name": "theme-color", "content": "teal"} in page.meta
    assert sum(isinstance(tag, rx.Component) and tag.tag == "link" for tag in page.meta) == 1
    assert "favicon.ico" not in str(page.meta)


def test_empty_optional_meta_is_supported() -> None:
    app = metadata.QualifyApp()
    app.add_page(lambda: rx.box(), route="/login", title="Qualify", meta=None)
    assert app._unevaluated_pages["login"].description == metadata.PAGE_DESCRIPTIONS["/login"]


def test_metadata_uses_existing_deploy_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        metadata, "get_config", lambda: SimpleNamespace(deploy_url="https://preview.example/app/")
    )
    result = metadata.page_metadata("/login", "Qualify")
    assert {"property": "og:url", "content": "https://preview.example/app/login"} in result["meta"]
