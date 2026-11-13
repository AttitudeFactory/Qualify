"""m-25021431 — every route the FastAPI app serves must be routed to it by the app's Caddy.

The incident: PR #618 mounted `/public/catalog-media/*` (ADR 48 §8, the stable signed URL Meta
fetches a catalog product's photo from) on the FastAPI app, but `deploy/Caddyfile` only sent
`/api/*` and `/public/media/*` to `api:8000`. In production the new path fell through to the
static frontend and answered `200 text/html` instead of FastAPI's `404 application/json`.

This is the FastAPI twin of `Qualify/test_caddy_backend_routes.py` (the Reflex backend app):
it reads every path the app mounts, with no network and no docker, and asserts each one is
matched by the `@fastapi` matcher.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI

from qualify_api.http.app import create_app

ROOT = Path(__file__).resolve().parents[3]
CADDYFILE = ROOT / "deploy" / "Caddyfile"

# FastAPI's own documentation pages: never linked by the app, never routed by Caddy.
FASTAPI_OWN_PAGES = ("/docs", "/openapi.json", "/redoc")


def _fastapi_matcher(caddyfile: str | None = None) -> list[str]:
    text = CADDYFILE.read_text() if caddyfile is None else caddyfile
    match = re.search(r"^\s*@fastapi path (.+)$", text, re.M)
    assert match, "deploy/Caddyfile lost its @fastapi matcher"
    # A trailing ` # comment` is not part of the matcher (Caddyfile comments need a space
    # before `#`).
    return re.split(r"\s#", match[1], maxsplit=1)[0].split()


def _caddy_path_matches(pattern: str, path: str) -> bool:
    """Caddy's `path` matcher for the forms the Caddyfile uses: a trailing `*` is a prefix
    match, anything else is exact."""
    if pattern.endswith("*"):
        return path.startswith(pattern[:-1])
    return path == pattern


def _walk(routes: Iterable[object], prefix: str = "") -> Iterator[str]:
    """Every path the app serves. FastAPI ≥0.147 keeps an included router as one
    `_IncludedRouter` entry (`original_router` + `include_context.prefix`) instead of
    copying its routes into `app.routes`; older versions copy them. Both are walked."""
    for route in routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            context = getattr(route, "include_context", None)
            yield from _walk(original.routes, prefix + getattr(context, "prefix", ""))
            continue
        path = getattr(route, "path", None)
        if path:
            yield prefix + path


def _sample(path: str) -> str:
    """A concrete request path for a route template: `{param}` → `x`."""
    return re.sub(r"\{[^}]+\}", "x", path)


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return create_app(configure_production=False)


@pytest.fixture(scope="module")
def served_paths(app: FastAPI) -> set[str]:
    paths = {p for p in _walk(app.routes) if not p.startswith(FASTAPI_OWN_PAGES)}
    # The walk must see at least what the schema sees, or it is passing vacuously after a
    # FastAPI internals change.
    schema_paths = set(app.openapi()["paths"])
    assert schema_paths <= paths, f"route walk missed {sorted(schema_paths - paths)}"
    return paths


def test_the_routes_outside_api_are_the_ones_this_test_knows(served_paths: set[str]) -> None:
    """A new top-level prefix on the FastAPI app must be added here AND to the Caddyfile."""
    outside_api = {p for p in served_paths if not p.startswith("/api/")}
    prefixes = {"/" + "/".join(p.strip("/").split("/")[:2]) for p in outside_api}
    assert prefixes == {"/public/media", "/public/catalog-media"}


def test_every_fastapi_route_is_proxied_by_caddy(served_paths: set[str]) -> None:
    matcher = _fastapi_matcher()
    unrouted = sorted(
        path
        for path in served_paths
        if not any(_caddy_path_matches(pattern, _sample(path)) for pattern in matcher)
    )
    assert not unrouted, (
        f"not routed to api:8000 by deploy/Caddyfile's @fastapi matcher {matcher}: {unrouted}"
    )


def test_the_matcher_parser_ignores_a_trailing_comment() -> None:
    caddyfile = ":80 {\n\t@fastapi path /api/* /public/media/*  # FastAPI prefixes\n}\n"
    assert _fastapi_matcher(caddyfile) == ["/api/*", "/public/media/*"]
