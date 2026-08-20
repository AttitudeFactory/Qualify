"""Module: auth (QUA-66) — as a food venue registering and entering its own space.

The session-scoped `food_venue_page` fixture already proved the happy path (signup → auto
login → dashboard); these tests cover the edges around it: the wall in front of every
business page, the single generic error message, the logout hygiene, and signup
validation the operator actually hits (short password, duplicate alias).
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import (
    LOGIN_EMAIL,
    LOGIN_PASSWORD,
    LOGIN_SUBMIT,
    SIGNUP_EMAIL,
    SIGNUP_NAME,
    SIGNUP_PASSWORD,
    SIGNUP_SUBMIT,
    Persona,
    do_login,
    do_logout,
    goto,
)

PROTECTED_ROUTES = [
    "/",
    "/connections",
    "/publish",
    "/inbox",
    "/leads",
    "/clarity",
    "/brand",
    "/create",
    "/drafts",
    "/vitrina",
]


@pytest.mark.parametrize("route", PROTECTED_ROUTES)
def test_protected_route_redirects_anonymous_to_login(anon: Page, route: str) -> None:
    goto(anon, route)
    expect(anon).to_have_url(re.compile(r"/login/?$"), timeout=20_000)
    expect(anon.get_by_role("heading", name="Entrar a tu negocio")).to_be_visible()


def test_login_page_copy_states_one_login_one_business(anon: Page) -> None:
    goto(anon, "/login")
    expect(anon.get_by_text("Un login = un negocio.", exact=False)).to_be_visible()
    expect(anon.get_by_role("link", name="Regístralo aquí")).to_have_attribute("href", "/signup")


def test_wrong_password_shows_one_generic_message(
    anon: Page, registered_food_venue: Persona
) -> None:
    goto(anon, "/login")
    anon.get_by_placeholder(LOGIN_EMAIL, exact=True).fill(registered_food_venue.email)
    anon.get_by_placeholder(LOGIN_PASSWORD, exact=True).fill("not-the-password")
    anon.get_by_role("button", name=LOGIN_SUBMIT).click()
    expect(anon.get_by_text("Email o contraseña incorrectos.")).to_be_visible(timeout=15_000)
    # Still on /login: the wall did not open.
    assert anon.url.rstrip("/").endswith("/login")


def test_unknown_email_gets_the_same_message_as_wrong_password(anon: Page) -> None:
    """Criterion: never distinguish "no such user" from "wrong password"."""
    goto(anon, "/login")
    anon.get_by_placeholder(LOGIN_EMAIL, exact=True).fill("nadie-e2e@example.com")
    anon.get_by_placeholder(LOGIN_PASSWORD, exact=True).fill("whatever-123")
    anon.get_by_role("button", name=LOGIN_SUBMIT).click()
    expect(anon.get_by_text("Email o contraseña incorrectos.")).to_be_visible(timeout=15_000)


def test_login_then_logout_closes_the_session_for_real(
    anon: Page, registered_food_venue: Persona
) -> None:
    """Logout hygiene: after `Salir`, the same browser cannot reopen a business page."""
    do_login(anon, registered_food_venue)
    expect(anon.get_by_role("heading", name="Dashboard de menciones")).to_be_visible(timeout=20_000)
    do_logout(anon)
    expect(anon.get_by_role("heading", name="Entrar a tu negocio")).to_be_visible()
    goto(anon, "/leads")
    expect(anon).to_have_url(re.compile(r"/login/?$"), timeout=20_000)


def test_authenticated_session_skips_login_and_signup(app: Page, food_venue: Persona) -> None:
    """`redirect_if_authenticated`: /login and /signup bounce back to the app."""
    for route in ("/login", "/signup"):
        goto(app, route)
        expect(app).not_to_have_url(re.compile(re.escape(route) + r"/?$"), timeout=20_000)
        expect(app.get_by_text(food_venue.business_name, exact=True).first).to_be_visible(
            timeout=20_000
        )


def test_signup_rejects_short_password_before_creating_anything(anon: Page) -> None:
    goto(anon, "/signup")
    anon.get_by_placeholder(SIGNUP_NAME, exact=True).fill("Cachapas El Puente")
    anon.get_by_placeholder(SIGNUP_EMAIL, exact=True).fill("e2e-cachapas-short@example.com")
    anon.get_by_placeholder(SIGNUP_PASSWORD, exact=True).fill("corta")
    anon.get_by_role("button", name=SIGNUP_SUBMIT).click()
    expect(anon.get_by_text("La contraseña debe tener al menos 8 caracteres.")).to_be_visible(
        timeout=15_000
    )
    assert anon.url.rstrip("/").endswith("/signup")


def test_signup_refuses_an_alias_already_used_by_another_business(
    anon: Page, registered_food_venue: Persona
) -> None:
    """One alias = one business. Reusing the arepera's email for a second venue is refused
    with the operator-facing message, and nothing is created."""
    goto(anon, "/signup")
    anon.get_by_placeholder(SIGNUP_NAME, exact=True).fill("Pizzería La Esquina")
    anon.get_by_placeholder(SIGNUP_EMAIL, exact=True).fill(registered_food_venue.email)
    anon.get_by_placeholder(SIGNUP_PASSWORD, exact=True).fill("otra-clave-segura-99")
    anon.get_by_role("button", name=SIGNUP_SUBMIT).click()
    expect(anon.get_by_text("Ese email ya está registrado", exact=False)).to_be_visible(
        timeout=15_000
    )
    assert anon.url.rstrip("/").endswith("/signup")
