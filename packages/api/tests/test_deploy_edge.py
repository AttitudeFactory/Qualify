"""Static guards on the VPS edge proxy split (deploy/edge/ vs deploy/docker-compose.prod.yml).

Founder rule (2026-10-14): Qualify and Pedidos are two products on one VPS and must not affect
each other. The edge proxy is the only listener on 80/443 and belongs to neither; Qualify's
Caddy is an internal router reached over `qualify-edge`. These checks fail the moment someone
publishes a port from Qualify's stack again, or wires another product into it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY = REPO_ROOT / "deploy"
PROD = yaml.safe_load((DEPLOY / "docker-compose.prod.yml").read_text(encoding="utf-8"))
EDGE = yaml.safe_load((DEPLOY / "edge" / "docker-compose.yml").read_text(encoding="utf-8"))
QUALIFY_CADDYFILE = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
EDGE_CADDYFILE = (DEPLOY / "edge" / "Caddyfile").read_text(encoding="utf-8")


def _code(text: str) -> str:
    """The Caddyfile without its comment lines — what Caddy actually reads."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_qualify_stack_publishes_no_port() -> None:
    publishing = [name for name, svc in PROD["services"].items() if svc.get("ports")]
    assert publishing == [], f"only the edge proxy may publish ports, found: {publishing}"


def test_qualify_stack_knows_nothing_about_other_products() -> None:
    prod_text = (DEPLOY / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "pedidos" not in prod_text.lower()
    assert "pedidos" not in _code(QUALIFY_CADDYFILE).lower()


def test_qualify_caddy_is_a_plain_http_router_on_the_edge_network() -> None:
    caddy = PROD["services"]["caddy"]
    assert caddy["networks"]["edge"]["aliases"] == ["qualify-web"]
    assert PROD["networks"]["edge"] == {"external": True, "name": "qualify-edge"}
    code = _code(QUALIFY_CADDYFILE)
    assert re.search(r"^:80 \{", code, re.MULTILINE), "Qualify's Caddy must serve plain :80"
    assert "auto_https off" in code
    assert "email" not in code  # no ACME here: certificates live on the edge


def test_edge_owns_80_443_and_both_networks() -> None:
    edge = EDGE["services"]["edge"]
    assert sorted(edge["ports"]) == ["443:443", "443:443/udp", "80:80"]
    assert EDGE["networks"]["qualify"] == {"external": True, "name": "qualify-edge"}
    assert EDGE["networks"]["pedidos"] == {"external": True, "name": "pedidos"}
    assert edge["restart"] == "unless-stopped"


def test_edge_routes_each_host_to_its_own_product() -> None:
    code = _code(EDGE_CADDYFILE)
    assert "reverse_proxy qualify-web:80" in code
    assert "reverse_proxy pedidos-backend:8420" in code
    assert "{$QUALIFY_DOMAIN}" in code and "{$PEDIDOS_DOMAIN}" in code


def test_edge_image_matches_the_web_image_caddy_version() -> None:
    dockerfile = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    pinned = re.search(r"ARG CADDY_IMAGE=(\S+)", dockerfile)
    assert pinned is not None
    assert EDGE["services"]["edge"]["image"] == pinned.group(1)
