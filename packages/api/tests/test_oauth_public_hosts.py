"""The OAuth round trip stays on the public host the client uses (m-24947215).

Pure URL building: the allow-list, the per-host redirect URI and the landing page. An
arbitrary `Host`/`Origin` must never become a redirect target."""

from __future__ import annotations

import pytest

from qualify_api.connections.public_hosts import (
    browser_hostname,
    meta_redirect_hosts,
    page_url_on_host,
    public_hosts,
    redirect_uri_for,
    request_origin,
)

PROD = {
    "QUALIFY_PUBLIC_URL": "https://qualify.attitudefactory.co",
    "QUALIFY_PUBLIC_HOSTS": "app.qualify.la, qualify.attitudefactory.co",
}
TIKTOK_CB = "https://qualify.attitudefactory.co/api/connections/tiktok/callback"


def test_public_hosts_default_to_the_public_url_host() -> None:
    assert public_hosts({"QUALIFY_PUBLIC_URL": "https://qualify.attitudefactory.co"}) == {
        "qualify.attitudefactory.co"
    }
    assert public_hosts({}) == frozenset()


def test_public_hosts_parse_commas_spaces_case_and_drop_junk() -> None:
    env = {
        "QUALIFY_PUBLIC_URL": "https://Qualify.AttitudeFactory.co/",
        "QUALIFY_PUBLIC_HOSTS": " APP.qualify.la  bad_host,https://x.example ,, a.b:443",
    }
    assert public_hosts(env) == {"app.qualify.la", "qualify.attitudefactory.co"}


def test_meta_redirect_hosts_are_opt_in_and_must_be_public() -> None:
    assert meta_redirect_hosts(PROD) == frozenset()
    env = {**PROD, "QUALIFY_META_REDIRECT_HOSTS": "app.qualify.la evil.example"}
    assert meta_redirect_hosts(env) == {"app.qualify.la"}


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("https://app.qualify.la", "app.qualify.la"),
        ("https://APP.qualify.la/", "app.qualify.la"),
        ("http://app.qualify.la", ""),  # not https
        ("https://app.qualify.la:8443", ""),  # a port is never a public host
        ("https://app.qualify.la/connections", ""),  # an origin has no path
        ("https://user@app.qualify.la", ""),
        ("null", ""),
        ("", ""),
        ("https://[::1", ""),  # unparseable
    ],
)
def test_browser_hostname(origin: str, expected: str) -> None:
    assert browser_hostname(origin) == expected


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("https://app.qualify.la", "https://app.qualify.la/api/connections/tiktok/callback"),
        ("https://qualify.attitudefactory.co", TIKTOK_CB),
        ("https://evil.example", TIKTOK_CB),  # not allow-listed: configured URI
        ("http://app.qualify.la", TIKTOK_CB),
        ("", TIKTOK_CB),
    ],
)
def test_redirect_uri_follows_only_an_allow_listed_origin(origin: str, expected: str) -> None:
    assert redirect_uri_for(TIKTOK_CB, origin, public_hosts(PROD)) == expected


def test_redirect_uri_never_rewrites_a_dev_http_callback() -> None:
    dev = "http://localhost:8000/api/connections/callback"
    assert redirect_uri_for(dev, "https://app.qualify.la", {"app.qualify.la"}) == dev


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("app.qualify.la", "https://app.qualify.la"),
        ("qualify.attitudefactory.co", "https://qualify.attitudefactory.co"),
        ("evil.example", ""),
        ("app.qualify.la:8000", ""),
        ("app.qualify.la/../x", ""),
        (None, ""),
    ],
)
def test_request_origin_allow_list(host: str | None, expected: str) -> None:
    assert request_origin(host, PROD) == expected


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("app.qualify.la", "https://app.qualify.la/connections"),
        ("qualify.attitudefactory.co", "https://qualify.attitudefactory.co/connections"),
        ("evil.example", "https://qualify.attitudefactory.co/connections"),
        ("", "https://qualify.attitudefactory.co/connections"),
    ],
)
def test_page_url_lands_on_the_callback_host_only_when_public(host: str, expected: str) -> None:
    default = "https://qualify.attitudefactory.co/connections"
    assert page_url_on_host(default, host, PROD) == expected


def test_page_url_in_local_dev_keeps_the_frontend_port() -> None:
    env = {"QUALIFY_PUBLIC_URL": "http://localhost:3000"}
    assert (
        page_url_on_host("http://localhost:3000/connections", "localhost", env)
        == "http://localhost:3000/connections"
    )
    assert (
        page_url_on_host("http://localhost:3000/connections", "localhost:8000", env)
        == "http://localhost:3000/connections"
    )
