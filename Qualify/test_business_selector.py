"""ADR 43 in `AuthState`: the login's business selector (S3 m-24849190) and «Cambiar de
negocio» without logging out (S4 m-24849191). Offline: the backend contract of S1
(`open_business`, `memberships_for`) and the pass store are replaced by fakes, the same
harness `test_auth_state.py` uses (handlers run through `.fn` on a bare state)."""

from __future__ import annotations

import inspect
from uuid import UUID

import pytest
from qualify_api.auth import (
    ActiveBusiness,
    LoginResult,
    NoBusinessAccess,
    NotAMember,
    UserMembership,
)

from . import auth_state as auth_state_module
from .auth_state import AuthState
from .business_switch import SwitchPass
from .business_vm import CHOICE_EXPIRED, CHOOSE_ROUTE, SWITCH_PASS_DEAD

LOGIN = UUID("11111111-1111-4111-8111-111111111111")
BIANKI = UUID("a0000000-0000-4000-8000-00000000000b")
POLETTE = UUID("a0000000-0000-4000-8000-00000000000c")
USER_B = UUID("b0000000-0000-4000-8000-00000000000b")
USER_P = UUID("b0000000-0000-4000-8000-00000000000c")
NAMES = {BIANKI: "Bianki", POLETTE: "Polette"}
USERS = {BIANKI: USER_B, POLETTE: USER_P}


def _membership(tenant: UUID) -> UserMembership:
    return UserMembership(
        tenant_id=tenant,
        tenant_name=NAMES[tenant],
        name=NAMES[tenant],
        role="owner",
        user_id=USERS[tenant],
        email="dueno@b.co",
        display_name="Dueño",
    )


def _result(*tenants: UUID) -> LoginResult:
    return LoginResult(
        tenant_id=tenants[0],
        auth_user_id=LOGIN,
        user_id=USERS[tenants[0]],
        email="dueno@b.co",
        display_name=NAMES[tenants[0]],
        access_token="tok-supabase",
        memberships=tuple(_membership(t) for t in tenants),
    )


def _active(tenant: UUID) -> ActiveBusiness:
    return ActiveBusiness(
        tenant_id=tenant,
        business_name=NAMES[tenant],
        user_id=USERS[tenant],
        email="dueno@b.co",
        display_name="Dueño",
        role="owner",
    )


class _Backend:
    """`open_business` / `memberships_for` with seats that a test can take away."""

    def __init__(self, *seats: UUID) -> None:
        self.seats = set(seats)
        self.opened: list[tuple[str, str]] = []

    def open(self, auth_user_id: str, tenant_id: str) -> ActiveBusiness:
        self.opened.append((auth_user_id, tenant_id))
        tenant = UUID(tenant_id)
        if UUID(auth_user_id) != LOGIN or tenant not in self.seats:
            raise NotAMember()
        return _active(tenant)

    def memberships(self, auth_user_id: str) -> list[tuple[str, str]]:
        assert UUID(auth_user_id) == LOGIN
        return [(str(t), NAMES[t]) for t in sorted(self.seats, key=NAMES.get)]


@pytest.fixture
def backend(monkeypatch) -> _Backend:
    fake = _Backend(BIANKI, POLETTE)
    monkeypatch.setattr(auth_state_module, "_open_business_blocking", fake.open)
    monkeypatch.setattr(auth_state_module, "_memberships_blocking", fake.memberships)
    monkeypatch.setattr(auth_state_module, "_kit_complete_blocking", lambda t: True)
    return fake


async def _login(monkeypatch, result: LoginResult) -> tuple[AuthState, list]:
    monkeypatch.setattr(auth_state_module, "_login_blocking", lambda e, p: result)
    state = AuthState()
    events = [
        e
        async for e in AuthState.handle_login.fn(
            state, {"email": "dueno@b.co", "password": "x" * 8}
        )
    ]
    return state, events


async def _run(gen) -> list:
    return [e async for e in gen]


# -- S3: the selector ---------------------------------------------------------------------


async def test_one_business_opens_straight_away_without_the_selector(monkeypatch, backend) -> None:
    state, events = await _login(monkeypatch, _result(BIANKI))
    assert state.session_tenant_id == str(BIANKI)
    assert CHOOSE_ROUTE not in str(events[0])
    assert state.awaiting_business_choice is False
    assert state.can_switch_business is False
    assert state.business_chip_label == "Estás en Bianki"
    assert backend.opened == []


async def test_two_businesses_go_to_the_selector_with_no_business_open(
    monkeypatch, backend
) -> None:
    state, events = await _login(monkeypatch, _result(BIANKI, POLETTE))
    assert CHOOSE_ROUTE in str(events[0])
    assert state.session_tenant_id == ""  # nothing opens before the choice
    assert state.is_authenticated is False
    assert state.awaiting_business_choice is True
    assert state.business_names == ["Bianki", "Polette"]
    assert state.business_choices == [
        {"index": "0", "name": "Bianki"},
        {"index": "1", "name": "Polette"},
    ]
    # every protected page still refuses this browser
    assert AuthState.require_login.fn(state) is not None


async def test_choosing_opens_that_business_through_the_fresh_check(monkeypatch, backend) -> None:
    state, _ = await _login(monkeypatch, _result(BIANKI, POLETTE))
    events = await _run(AuthState.choose_business.fn(state, "1"))
    assert backend.opened == [(str(LOGIN), str(POLETTE))]
    assert state.session_tenant_id == str(POLETTE)
    assert state._session_user_id == str(USER_P)  # the local user of THAT business
    assert state.business_name == "Polette"
    assert state.business_chip_label == "Estás en Polette"
    assert state.active_business_index == 1
    assert state.can_switch_business is True
    assert state.switch_options == [{"index": "0", "name": "Bianki"}]
    assert len(events) == 1 and '"/"' in str(events[0])


@pytest.mark.parametrize("position", ["2", "-1", str(POLETTE), "1; drop", ""])
async def test_a_manipulated_choice_opens_nothing(monkeypatch, backend, position: str) -> None:
    state, _ = await _login(monkeypatch, _result(BIANKI, POLETTE))
    events = await _run(AuthState.choose_business.fn(state, position))
    assert events == []
    assert backend.opened == []
    assert state.session_tenant_id == ""
    assert state.auth_error != ""


async def test_a_seat_removed_before_the_tap_starts_over_at_login(monkeypatch, backend) -> None:
    state, _ = await _login(monkeypatch, _result(BIANKI, POLETTE))
    backend.seats.discard(POLETTE)
    events = await _run(AuthState.choose_business.fn(state, "1"))
    assert "/login" in str(events[0])
    assert state.session_tenant_id == ""
    assert state.awaiting_business_choice is False and state._auth_user_id == ""
    AuthState.redirect_if_authenticated.fn(state)  # /login's on_load shows it once
    assert state.auth_error == NotAMember.message
    AuthState.redirect_if_authenticated.fn(state)
    assert state.auth_error == ""


def test_the_selector_without_a_waiting_login_sends_to_login() -> None:
    state = AuthState()
    assert "/login" in str(AuthState.enter_business_choice.fn(state))
    AuthState.redirect_if_authenticated.fn(state)
    assert state.auth_error == CHOICE_EXPIRED


async def test_going_back_to_login_drops_the_waiting_choice(monkeypatch, backend) -> None:
    state, _ = await _login(monkeypatch, _result(BIANKI, POLETTE))
    AuthState.redirect_if_authenticated.fn(state)
    assert state.awaiting_business_choice is False
    assert state._auth_user_id == "" and state._access_token == ""
    assert await _run(AuthState.choose_business.fn(state, "0")) == []
    assert state.session_tenant_id == ""


async def test_no_business_left_shows_its_own_text(monkeypatch) -> None:
    def refuse(email, password):
        raise NoBusinessAccess()

    monkeypatch.setattr(auth_state_module, "_login_blocking", refuse)
    state = AuthState()
    await _run(AuthState.handle_login.fn(state, {"email": "a@b.co", "password": "x" * 8}))
    no_access = "Ya no tienes acceso a este negocio. Vuelve a entrar para elegir otro."
    assert state.auth_error == no_access
    assert state.auth_error != auth_state_module._INCOMPLETE
    assert state.session_tenant_id == ""


async def test_no_other_tenant_id_and_no_login_id_reach_the_browser(monkeypatch, backend) -> None:
    """Only names and positions are sent: what the client receives for this state holds
    neither the other business's tenant id, nor the login's provider id, nor the token."""
    state, _ = await _login(monkeypatch, _result(BIANKI, POLETTE))
    assert state._choice_ids == [str(BIANKI), str(POLETTE)]  # held, server side
    waiting = str(state.dict())
    assert str(BIANKI) not in waiting and str(POLETTE) not in waiting
    await _run(AuthState.choose_business.fn(state, "0"))
    opened = str(state.dict())
    assert str(POLETTE) not in opened  # the other business: only its name, «Polette»
    assert str(LOGIN) not in opened and "tok-supabase" not in opened


# -- S4: «Cambiar de negocio» -------------------------------------------------------------


@pytest.fixture
def passes(monkeypatch) -> dict[str, SwitchPass]:
    store: dict[str, SwitchPass] = {}

    def issue(auth_user_id: UUID, tenant_id: UUID, access_token: str) -> str:
        value = f"pase-{len(store)}"
        store[value] = SwitchPass(auth_user_id, tenant_id, access_token)
        return value

    monkeypatch.setattr(auth_state_module, "issue_switch_pass", issue)
    monkeypatch.setattr(auth_state_module, "redeem_switch_pass", lambda v: store.pop(v, None))
    return store


async def _in_bianki(monkeypatch) -> AuthState:
    state, _ = await _login(monkeypatch, _result(BIANKI, POLETTE))
    await _run(AuthState.choose_business.fn(state, "0"))
    assert state.session_tenant_id == str(BIANKI)
    return state


async def test_switching_mints_a_pass_and_abandons_this_state(monkeypatch, backend, passes) -> None:
    state = await _in_bianki(monkeypatch)
    backend.opened.clear()
    events = await _run(AuthState.switch_business.fn(state, "1"))
    assert backend.opened == [(str(LOGIN), str(POLETTE))]  # fresh check before the pass
    assert list(passes) == ["pase-0"]
    assert passes["pase-0"] == SwitchPass(LOGIN, POLETTE, "tok-supabase")
    script = str(events[-1])
    assert "sessionStorage.removeItem" in script and "/cambiar#pase=pase-0" in script
    # this state is NOT reset in place: it is left behind as it was
    assert state.session_tenant_id == str(BIANKI)
    assert state.business_chip_label == "Abriendo Polette…"


async def test_switching_to_a_business_without_a_seat_keeps_the_current_session(
    monkeypatch, backend, passes
) -> None:
    state = await _in_bianki(monkeypatch)
    backend.seats.discard(POLETTE)
    events = await _run(AuthState.switch_business.fn(state, "1"))
    assert passes == {}
    assert state.session_tenant_id == str(BIANKI)
    assert state.business_name == "Bianki" and state.opening_business == ""
    assert "Ya no tienes acceso" in str(events[-1])
    assert state.business_names == ["Bianki"]  # the menu no longer offers it
    assert state.can_switch_business is False


@pytest.mark.parametrize("position", ["0", "7", str(POLETTE), "-1"])
async def test_a_manipulated_or_current_switch_does_nothing(
    monkeypatch, backend, passes, position: str
) -> None:
    state = await _in_bianki(monkeypatch)
    backend.opened.clear()
    assert await _run(AuthState.switch_business.fn(state, position)) == []
    assert passes == {} and backend.opened == []
    assert state.session_tenant_id == str(BIANKI)


async def test_a_pass_store_outage_keeps_the_current_session(monkeypatch, backend) -> None:
    state = await _in_bianki(monkeypatch)

    def down(*args):
        raise ConnectionError("redis down")

    monkeypatch.setattr(auth_state_module, "issue_switch_pass", down)
    events = await _run(AuthState.switch_business.fn(state, "1"))
    assert state.session_tenant_id == str(BIANKI) and state.opening_business == ""
    assert "Sigues en Bianki" in str(events[-1])


async def test_the_new_state_redeems_the_pass_and_opens_the_business(backend, passes) -> None:
    passes["p1"] = SwitchPass(LOGIN, POLETTE, "tok-supabase")
    fresh = AuthState()  # what the browser gets after dropping its Reflex token
    events = await _run(AuthState.redeem_switch.fn(fresh, "#pase=p1"))
    assert "history.replaceState" in str(events[0])  # the pass leaves the address bar
    assert '"/"' in str(events[-1])
    assert fresh.session_tenant_id == str(POLETTE)
    assert fresh._session_user_id == str(USER_P)
    assert fresh._auth_user_id == str(LOGIN) and fresh._access_token == "tok-supabase"
    assert fresh.business_chip_label == "Estás en Polette"
    assert fresh.switch_options == [{"index": "0", "name": "Bianki"}]
    assert backend.opened == [(str(LOGIN), str(POLETTE))]  # checked again at redemption
    assert passes == {}  # single use


@pytest.mark.parametrize("fragment", ["", "#pase=", "#pase=unknown", "#otra=p1"])
async def test_a_dead_pass_goes_to_login(backend, passes, fragment: str) -> None:
    passes["p1"] = SwitchPass(LOGIN, POLETTE, "tok-supabase")
    fresh = AuthState()
    events = await _run(AuthState.redeem_switch.fn(fresh, fragment))
    assert "/login" in str(events[-1])
    assert fresh.session_tenant_id == ""
    AuthState.redirect_if_authenticated.fn(fresh)
    assert fresh.auth_error == SWITCH_PASS_DEAD


async def test_going_back_onto_cambiar_from_the_opened_business_stays_in_it(
    monkeypatch, backend, passes
) -> None:
    """«Atrás» after a switch lands on /cambiar again, without a pass: the session that
    pass opened is already there, so it goes home without an error."""
    state = await _in_bianki(monkeypatch)
    events = await _run(AuthState.redeem_switch.fn(state, ""))
    assert '"/"' in str(events[-1]) and state.session_tenant_id == str(BIANKI)
    assert state._login_notice == ""


async def test_a_used_pass_cannot_open_a_second_tab(backend, passes) -> None:
    passes["p1"] = SwitchPass(LOGIN, POLETTE, "tok-supabase")
    first, second = AuthState(), AuthState()
    await _run(AuthState.redeem_switch.fn(first, "#pase=p1"))
    await _run(AuthState.redeem_switch.fn(second, "#pase=p1"))
    assert first.session_tenant_id == str(POLETTE)
    assert second.session_tenant_id == ""


async def test_a_seat_removed_before_redemption_goes_to_login(backend, passes) -> None:
    passes["p1"] = SwitchPass(LOGIN, POLETTE, "tok-supabase")
    backend.seats.discard(POLETTE)
    fresh = AuthState()
    events = await _run(AuthState.redeem_switch.fn(fresh, "#pase=p1"))
    assert "/login" in str(events[-1]) and fresh.session_tenant_id == ""


async def test_a_state_that_kept_its_token_is_wiped_before_the_business_opens(
    monkeypatch, backend, passes
) -> None:
    """Defence in depth: should a browser keep its Reflex token, the redemption still
    resets every business substate and this state before writing the new business."""
    state = await _in_bianki(monkeypatch)
    resets: list[bool] = []

    async def fake_reset(self) -> None:
        resets.append(True)

    monkeypatch.setattr(AuthState, "_reset_business_states", fake_reset)
    passes["p1"] = SwitchPass(LOGIN, POLETTE, "tok-supabase")
    await _run(AuthState.redeem_switch.fn(state, "#pase=p1"))
    assert resets == [True]
    assert state.session_tenant_id == str(POLETTE) and state.business_name == "Polette"


def test_switching_never_resets_the_state_it_leaves() -> None:
    """ADR 43 §2.2: the old state is abandoned, not reset — «Duplicar pestaña» may still
    be using it, and a background event of the old business writes only there."""
    source = inspect.getsource(AuthState.switch_business.fn)
    assert "reset" not in source.replace("_SWITCH_STORE_ERRORS", "")
