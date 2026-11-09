"""MARCA-5 (m-24842968): the invitation notice before the Brand Kit, the code that lets
the visitor go on, and the «No tengo código» form — offline, no DB."""

from __future__ import annotations

import json

import pytest
from qualify_api.leads.interest import INTEREST_CONSENT_TEXT, InterestInvalid

from . import access_interest_state as interest_module
from . import auth_state as auth_state_module
from .access_interest_state import MODE_FORM, MODE_SENT, AccessInterestState
from .access_vm import (
    ACCESS_NOTICE,
    CODE_DEAD,
    CODE_EMPTY,
    CONSENT_LABEL,
    INTEREST_SENT,
    INTEREST_SENT_TITLE,
    interest_error_message,
    invite_token_from_text,
)
from .auth_state import AuthState


def js(text: str) -> str:
    """The compiled JSX escapes «á» as «\\u00e1»."""
    return json.dumps(text)[1:-1]


# ---- the code ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "token"),
    [
        ("abc123-_XYZ", "abc123-_XYZ"),
        ("  abc123\n", "abc123"),
        ("https://qualify.attitudefactory.co/registro?invitacion=abc123", "abc123"),
        ("http://localhost:3100/signup?invite=old-tok", "old-tok"),
        ("/registro?invitacion=abc123&x=1", "abc123"),
        ("https://qualify.attitudefactory.co/registro", ""),
        ("", ""),
    ],
)
def test_the_code_is_read_alone_or_inside_the_pasted_link(typed: str, token: str) -> None:
    assert invite_token_from_text(typed) == token


def test_the_consent_label_is_the_stored_policy_text() -> None:
    assert CONSENT_LABEL == INTEREST_CONSENT_TEXT == "Acepto que me escriban por WhatsApp"


def test_every_failure_says_what_to_do() -> None:
    for reason in ("consent", "full_name", "business_name", "whatsapp_phone"):
        assert interest_error_message(reason).startswith(("Marca", "Escribe", "Falta"))
    assert "Espera" in interest_error_message("rate_limited")
    assert "Inténtalo" in interest_error_message("anything-else")


# ---- the screens ------------------------------------------------------------------


def test_brand_start_opens_with_the_exact_notice() -> None:
    from .auth_pages import brand_start_index

    rendered = str(brand_start_index())
    assert js(ACCESS_NOTICE) in rendered
    assert js("Tu código de invitación") in rendered
    assert js("No tengo código") in rendered


def test_the_form_asks_only_name_business_and_whatsapp() -> None:
    from .auth_pages import _interest_form

    rendered = str(_interest_form())
    for label in ("Tu nombre", "Nombre de tu negocio", "Tu WhatsApp", CONSENT_LABEL):
        assert js(label) in rendered
    for name in ("full_name", "business_name", "whatsapp_phone", "website"):
        assert f'"{name}"' in rendered
    assert "email" not in rendered.replace("autoComplete", "")
    assert js("Quiero que me contacten") in rendered


def test_the_signup_without_invite_is_no_longer_a_dead_end() -> None:
    from .auth_pages import _invite_only, access_gate

    rendered = str(_invite_only())
    assert js(ACCESS_NOTICE) in rendered
    assert js("Qualify es solo por invitación") + '"' not in rendered  # no bare heading
    assert js(INTEREST_SENT) in str(access_gate("signup"))


def test_after_sending_the_card_confirms_and_offers_the_code() -> None:
    from .auth_pages import _invite_only, access_gate, brand_start_index

    for rendered in (str(brand_start_index()), str(_invite_only())):
        assert js(INTEREST_SENT_TITLE) in rendered
    assert js("Ya tengo mi código") in str(access_gate("brand"))


def test_the_code_button_says_where_it_goes() -> None:
    from .auth_pages import _code_form

    assert js("Empezar mi marca") in str(_code_form("brand"))
    assert js("Empezar mi marca") not in str(_code_form("signup"))


def test_the_consent_checkbox_is_not_browser_required() -> None:
    from .auth_pages import _interest_form

    # Radix hides the native control: `required` would block silently or in English.
    rendered = str(_interest_form())
    checkbox = rendered[rendered.index("RadixThemesCheckbox,") :]
    checkbox = checkbox[: checkbox.index("},)")]
    assert 'name:"consent"' in checkbox
    assert "required" not in checkbox


def test_the_signup_gate_has_one_login_exit_as_a_footer() -> None:
    from .auth_pages import _invite_only

    rendered = str(_invite_only())
    assert js("Inicia sesión") in rendered
    assert js("Iniciar sesión") not in rendered


# ---- the code handler -------------------------------------------------------------


async def _run(handler, state, form):
    return [event async for event in handler.fn(state, form)]


async def test_an_empty_code_asks_for_it() -> None:
    state = AuthState()
    await _run(AuthState.redeem_invite_code, state, {"code": "  "})
    assert state.invite_code_error == CODE_EMPTY
    assert state.invite_state == ""


async def test_a_dead_code_says_so_and_opens_nothing(monkeypatch) -> None:
    monkeypatch.setattr(auth_state_module, "_invite_blocking", lambda token: ("", "", False))
    state = AuthState()
    events = await _run(AuthState.redeem_invite_code, state, {"code": "nope"})
    assert state.invite_code_error == CODE_DEAD
    assert state.invite_state == "" and state._invite_token == ""
    assert events == []


async def test_a_good_code_goes_on_into_the_brand_kit(monkeypatch) -> None:
    seen: list[str] = []

    def lookup(token: str) -> tuple[str, str, bool]:
        seen.append(token)
        return ("ana@esquina.co", "La Esquina", False)

    monkeypatch.setattr(auth_state_module, "_invite_blocking", lookup)
    state = AuthState()
    link = "https://qualify.attitudefactory.co/registro?invitacion=tok-1"
    events = await _run(AuthState.redeem_invite_code, state, {"code": link, "next": "brand"})
    assert seen == ["tok-1"]
    assert state.invite_state == "ok" and state.invite_email == "ana@esquina.co"
    assert state._invite_token == "tok-1"
    assert len(events) == 1 and "start_brand_kit" in str(events[0])


async def test_a_good_code_on_the_signup_page_just_opens_the_form(monkeypatch) -> None:
    monkeypatch.setattr(auth_state_module, "_invite_blocking", lambda t: ("a@b.co", "", False))
    state = AuthState()
    events = await _run(AuthState.redeem_invite_code, state, {"code": "t", "next": "signup"})
    assert state.invite_state == "ok"
    assert events == []


async def test_add_business_code_opens_password_confirmation_instead_of_a_brand_draft(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        auth_state_module, "_invite_blocking", lambda t: ("a@b.co", "Polette", True)
    )
    state = AuthState()
    events = await _run(AuthState.redeem_invite_code, state, {"code": "t", "next": "brand"})
    assert state.invite_is_add_business and state.invite_state == "ok"
    assert len(events) == 1 and "/registro" in str(events[0])
    assert "start_brand_kit" not in str(events[0])


# ---- the interest handler ---------------------------------------------------------


class _Router:
    class headers:  # noqa: N801 — mirrors Reflex's attribute names
        raw_headers = {"x-forwarded-for": "9.9.9.9, 10.0.0.1"}

    class session:  # noqa: N801
        client_ip = "10.0.0.1"


@pytest.fixture
def interest_state(monkeypatch) -> AccessInterestState:
    state = AccessInterestState()
    monkeypatch.setattr(AccessInterestState, "router", _Router(), raising=False)
    return state


FORM = {"full_name": "Ana", "business_name": "La Esquina", "whatsapp_phone": "+584141234567"}


async def test_a_sent_form_shows_the_confirmation(monkeypatch, interest_state) -> None:
    calls = []
    monkeypatch.setattr(
        interest_module, "_submit_blocking", lambda req, key: calls.append((req, key)) or True
    )
    AccessInterestState.open_form.fn(interest_state)
    assert interest_state.mode == MODE_FORM
    AccessInterestState.set_consent.fn(interest_state, True)
    await AccessInterestState.submit.fn(interest_state, FORM)
    assert interest_state.mode == MODE_SENT and interest_state.error == ""
    ((request, key),) = calls
    assert request.consent is True and key == "9.9.9.9"


async def test_a_refused_form_stays_with_the_reason(monkeypatch, interest_state) -> None:
    def refuse(req, key):
        raise InterestInvalid("consent")

    monkeypatch.setattr(interest_module, "_submit_blocking", refuse)
    AccessInterestState.open_form.fn(interest_state)
    await AccessInterestState.submit.fn(interest_state, FORM)
    assert interest_state.mode == MODE_FORM
    assert interest_state.error == interest_error_message("consent")
