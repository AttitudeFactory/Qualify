"""Tests for the auth screens' state (QUA-66) and the logout-hygiene criteria of
`docs/modelo-negocio-operador-multi-emprendimiento.md` §6.1.

Same harness split the other state tests document: behavior that stops before any
`get_state`/DB touch runs against a real `AuthState` instance via the handler's `.fn`;
behavior bound to a live EventContext (the `get_state` calls in logout) is pinned by
source inspection — the pattern `test_publishing_state.py`/`test_inbox_state.py`
established. The full login round-trip against Postgres lives in the `db`-marked
backend suite (`packages/api/tests/test_auth_register_db.py`).
"""

from __future__ import annotations

import inspect
import pathlib
import re

import pytest
from qualify_api.auth import FakeAuthProvider

from . import auth_state as auth_state_module
from .auth_state import AuthState

_QUALIFY_DIR = pathlib.Path(__file__).resolve().parent


def _state() -> AuthState:
    return AuthState()


def _use_fake_provider(monkeypatch, provider: FakeAuthProvider) -> None:
    monkeypatch.setattr(auth_state_module, "default_auth_provider", lambda: provider)


# --------------------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------------------


def test_require_login_redirects_when_unauthenticated() -> None:
    state = _state()
    spec = AuthState.require_login.fn(state)
    assert spec is not None  # a redirect EventSpec, not a pass-through


def test_require_login_passes_when_authenticated() -> None:
    state = _state()
    state.session_tenant_id = "a0000000-0000-4000-8000-000000000001"
    assert AuthState.require_login.fn(state) is None


def test_a_session_without_a_finished_brand_kit_is_sent_to_make_it() -> None:
    """§ request 2026-10-02: logged in but no complete Brand Kit → the Brand Kit, from
    every protected page and from `/`; the Brand Kit's own pages stay open."""
    state = _state()
    state.session_tenant_id = "a0000000-0000-4000-8000-000000000001"
    state.brand_kit_complete = False
    assert AuthState.require_login.fn(state) is not None
    assert AuthState.require_login_or_brand_start.fn(state) is not None
    assert AuthState.require_brand_access.fn(state) is None
    state.brand_kit_complete = True
    assert AuthState.require_login.fn(state) is None
    assert AuthState.require_login_or_brand_start.fn(state) is None


async def test_login_records_whether_the_brand_kit_is_finished(monkeypatch) -> None:
    from uuid import UUID

    from qualify_api.auth import LoginResult

    tenant = UUID("a0000000-0000-4000-8000-000000000001")
    result = LoginResult(tenant, UUID(int=1), UUID(int=2), "a@b.co", "Negocio", "tok")
    monkeypatch.setattr(auth_state_module, "_login_blocking", lambda e, p: result)
    monkeypatch.setattr(auth_state_module, "_kit_complete_blocking", lambda t: False)
    state = _state()
    events = [
        e async for e in AuthState.handle_login.fn(state, {"email": "a@b.co", "password": "x" * 8})
    ]
    assert len(events) == 1 and state.session_tenant_id == str(tenant)
    assert state.brand_kit_complete is False  # every protected page now sends to /brand


def test_login_screens_bounce_an_authenticated_session() -> None:
    state = _state()
    state.session_tenant_id = "a0000000-0000-4000-8000-000000000001"
    assert AuthState.redirect_if_authenticated.fn(state) is not None
    state.session_tenant_id = ""
    assert AuthState.redirect_if_authenticated.fn(state) is None


# --------------------------------------------------------------------------------------
# The Brand Kit before login (§ request 2026-10-02)
# --------------------------------------------------------------------------------------

_DRAFT = "b0000000-0000-4000-8000-000000000002"


def test_brand_pages_ask_for_the_email_without_login_or_draft() -> None:
    state = _state()
    assert AuthState.require_brand_access.fn(state) is not None
    state.guest_tenant_id = _DRAFT
    assert AuthState.require_brand_access.fn(state) is None


def test_a_draft_opens_only_the_brand_kit() -> None:
    """A pre-login draft passes the Brand Kit's guard and NOTHING else."""
    state = _state()
    state.guest_tenant_id = _DRAFT
    assert AuthState.require_login.fn(state) is not None
    assert state.is_authenticated is False
    assert state.is_guest is True


def test_index_sends_an_anonymous_visitor_to_the_brand_kit_first() -> None:
    state = _state()
    assert AuthState.require_login_or_brand_start.fn(state) is not None
    state.session_tenant_id = "a0000000-0000-4000-8000-000000000001"
    assert AuthState.require_login_or_brand_start.fn(state) is None


def test_brand_tenant_prefers_the_login_over_the_draft() -> None:
    state = _state()
    assert auth_state_module.brand_tenant_id(state) == ""
    state.guest_tenant_id = _DRAFT
    assert auth_state_module.brand_tenant_id(state) == _DRAFT
    state.session_tenant_id = "a0000000-0000-4000-8000-000000000001"
    assert auth_state_module.brand_tenant_id(state) == state.session_tenant_id


def test_only_the_brand_kit_reads_the_draft_tenant() -> None:
    """`guest_tenant_id` must never become a general tenant source: outside AuthState
    only the Brand Kit's modules may resolve it (through `brand_tenant_id`)."""
    allowed = {
        "auth_state.py",
        "auth_pages.py",
        "brand_documents.py",
        "brand_finish.py",
        "brand_minimal.py",  # m-24848529: «Tu marca» in five steps
        "creative_state.py",
        "creative_wizard_pages.py",
        "voice_lab.py",
        "layout.py",
        "test_auth_state.py",
    }
    for path in _QUALIFY_DIR.rglob("*.py"):
        if path.name in allowed or ".web" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        assert "guest_tenant_id" not in source, path
        assert "brand_tenant_id" not in source, path


async def test_bad_email_on_the_first_view_stays_there() -> None:
    state = _state()
    async for _ in AuthState.start_brand_kit.fn(state, {"email": "sin-arroba"}):
        raise AssertionError("a refused email must not navigate")
    assert state.guest_tenant_id == ""
    assert state.guest_error != ""
    assert state.is_authenticating is False


async def test_an_email_with_an_account_is_sent_to_login(monkeypatch) -> None:
    def _has_account(email: str):
        raise auth_state_module.EmailHasAccount()

    monkeypatch.setattr(auth_state_module, "_start_draft_blocking", _has_account)
    state = _state()
    events = [e async for e in AuthState.start_brand_kit.fn(state, {"email": "a@b.co"})]
    assert len(events) == 1  # § 2026-10-02: straight to /login, not an error on screen
    assert state.login_email_hint == "a@b.co"  # /login opens with it filled in
    assert state.guest_has_account is True
    assert state.guest_tenant_id == ""


def _draft(tenant: str = _DRAFT):
    from uuid import UUID

    from qualify_api.auth import BrandKitDraftResult

    return BrandKitDraftResult(tenant_id=UUID(tenant), email="a@b.co", resumed=True)


@pytest.mark.parametrize(
    ("destination"),
    ["/registro", "/brand/connect", "/brand/manual", "/brand"],
)
async def test_the_email_lands_where_the_draft_stands(monkeypatch, destination: str) -> None:
    """Finished kit → signup; halfway → back into its wizard; nothing → the start."""
    monkeypatch.setattr(auth_state_module, "_start_draft_blocking", lambda email: _draft())
    monkeypatch.setattr(auth_state_module, "_draft_destination_blocking", lambda t: destination)
    state = _state()
    events = [e async for e in AuthState.start_brand_kit.fn(state, {"email": "a@b.co"})]
    assert len(events) == 1
    assert state.guest_tenant_id == _DRAFT


def test_draft_destination_follows_the_kit_status(monkeypatch) -> None:
    from . import brand_finish

    cases = [
        (brand_finish.KitStatus(True, {"completed": True, "flow": "connect"}), "/registro"),
        # m-24848529: a draft of either old flow resumes on the five steps, at /brand
        (brand_finish.KitStatus(False, {"completed": False, "flow": "connect"}), "/brand"),
        (brand_finish.KitStatus(False, {"completed": False, "flow": "manual"}), "/brand"),
        (brand_finish.KitStatus(False, {"completed": False, "flow": "minimo"}), "/brand"),
        (brand_finish.KitStatus(False, None), "/brand"),
    ]
    for status, expected in cases:
        monkeypatch.setattr(brand_finish, "tenant_kit_status", lambda t, s=status: s)
        assert auth_state_module._draft_destination_blocking(_DRAFT) == expected


def test_the_brand_kit_is_only_its_views() -> None:
    """§ request 2026-10-02: no sidebar on the wizard pages, no Atrás on a first step."""
    from . import creative_wizard_pages as wiz

    for page in (
        wiz.brand_choice_index,
        wiz.brand_connect_index,
        wiz.brand_connect_setup_index,
        wiz.brand_manual_index,
    ):
        assert "_wizard_shell(" in inspect.getsource(page), page.__name__
    assert "rail=False" in inspect.getsource(wiz._wizard_shell)
    for controls in (wiz._controls, wiz._connect_controls):
        source = inspect.getsource(controls)
        # step 0: no Atrás; its slot holds the way back to the email screen
        assert "step == 0" in source and "_change_email_button()" in source, controls.__name__


def test_the_first_view_is_the_brand_kit_not_the_login() -> None:
    """§ 2026-10-02: "/brand/start y después /login" — no protected page sends an
    anonymous visitor to the login, and the email screen has no way around it."""
    source = inspect.getsource(AuthState.require_login.fn)
    assert '"/login"' not in source and "BRAND_START_ROUTE" in source
    pages = (_QUALIFY_DIR / "auth_pages.py").read_text(encoding="utf-8")
    assert "Saltar" not in pages
    # and the login does not link back to it: the Brand Kit was already made first
    assert "sin registrarte" not in pages


# --------------------------------------------------------------------------------------
# Login refusals (they fire before any DB touch, so they run offline)
# --------------------------------------------------------------------------------------


async def test_wrong_credentials_show_one_generic_message(monkeypatch) -> None:
    _use_fake_provider(monkeypatch, FakeAuthProvider())  # empty: every login fails
    state = _state()
    async for _ in AuthState.handle_login.fn(state, {"email": "a@b.co", "password": "x" * 8}):
        raise AssertionError("a failed login must not emit navigation events")
    assert state.session_tenant_id == ""
    assert state.auth_error != ""
    assert state.is_authenticating is False


async def test_unstamped_identity_is_refused_never_guessed(monkeypatch) -> None:
    provider = FakeAuthProvider()
    provider.seed_user("stray@b.co", "password-123", tenant_id=None)
    _use_fake_provider(monkeypatch, provider)
    state = _state()
    async for _ in AuthState.handle_login.fn(
        state, {"email": "stray@b.co", "password": "password-123"}
    ):
        raise AssertionError("an incomplete registration must not emit navigation events")
    assert state.session_tenant_id == ""
    assert state.auth_error != ""


# --------------------------------------------------------------------------------------
# Logout hygiene (criteria 1-4) — source-inspection pins for the EventContext-bound part
# --------------------------------------------------------------------------------------


def test_logout_revokes_server_side_before_destroying_state() -> None:
    source = inspect.getsource(AuthState.logout.fn)
    revoke_at = source.index("_sign_out_blocking")
    reset_at = source.index("substate.reset()")
    redirect_at = source.index("rx.redirect(BRAND_START_ROUTE)")
    assert revoke_at < reset_at < redirect_at, (
        "criterion 1 ordering: revoke the session token server-side first, then destroy "
        "Reflex state, then leave via redirect — never 'clean the UI in place'"
    )
    assert "self.reset()" in source


def test_logout_resets_every_business_state() -> None:
    """Every state module that reads the tenant must be reset on logout. Enumerated
    here so ADDING a new tenant-reading state without wiring its reset fails a test
    instead of leaking stale data into the next login."""
    source = inspect.getsource(AuthState.logout.fn)
    for state_name in (
        "ConnectionsState",
        "LeadsState",
        "ClarityState",
        "InboxState",
        "PublishState",
        "DashboardState",
        "CreativeState",
        # The Brand Kit wizard's own draft (request 2026-09-08): step, chosen plan,
        # staged logo, the connect flow's read profile — none of it lives in
        # CreativeState, so it needs its own line here. See
        # `creative_state.py`'s `_kit_draft_loaded` for the other half of the
        # draft/finalized split this closes: CreativeState's kit_* fields are the
        # in-session draft too, but that half survives a plain page reload/nav on
        # purpose — only logout (this list) clears it.
        "BrandWizardState",
        "BrandConnectState",
        "CatalogState",
        # m-24789472: «Preguntas iniciales» (draft questions per Instagram account)
        "IceBreakersState",
    ):
        assert state_name in source, f"logout does not reset {state_name}"


def test_every_tenant_reading_state_is_covered_by_logout() -> None:
    """The inverse direction: scan the whole UI package (not just `*_state.py` — that
    narrower glob is exactly what let `BrandWizardState`/`BrandConnectState` go
    unnoticed: both live in `creative_wizard_pages.py`, a page module, and reset
    coverage for them was missing until request 2026-09-08 caught it manually) for
    `rx.State` subclasses that read AuthState, and assert each one appears in
    logout's reset list."""
    logout_source = inspect.getsource(AuthState.logout.fn)
    for path in _QUALIFY_DIR.glob("*.py"):
        if path.name == "auth_state.py" or path.name.startswith("test_"):
            continue
        source = path.read_text(encoding="utf-8")
        if "get_state(AuthState)" not in source:
            continue
        class_names = re.findall(r"class (\w+)\(rx\.State\)", source)
        for name in class_names:
            assert name in logout_source, (
                f"{path.name} defines {name}, which reads AuthState but is not reset "
                "by AuthState.logout — stale tenant data would survive a logout"
            )


# --------------------------------------------------------------------------------------
# Criterion 2: no client-persisted business data outside tenant-namespaced keys
# --------------------------------------------------------------------------------------


def test_no_client_persistence_without_tenant_namespace() -> None:
    """Hygiene criterion 2, enforced structurally: today the app persists NOTHING in
    the client, which satisfies the criterion trivially. The moment someone introduces
    `rx.LocalStorage` / `rx.Cookie` / `rx.SessionStorage`, this test fails and forces
    the conversation: the key MUST be namespaced by tenant_id and purged on logout."""
    offenders: list[str] = []
    for path in _QUALIFY_DIR.glob("*.py"):
        if path.name.startswith("test_"):
            continue
        source = path.read_text(encoding="utf-8")
        for pattern in ("rx.LocalStorage", "rx.Cookie", "rx.SessionStorage"):
            if pattern in source:
                offenders.append(f"{path.name}: {pattern}")
    assert offenders == [], (
        "client-side persistence found; every key must be tenant-namespaced and purged "
        f"on logout (criterion 2/3 of the signed logout-hygiene doc): {offenders}"
    )


# --------------------------------------------------------------------------------------
# Single writer: only auth_state.py assigns session_tenant_id
# --------------------------------------------------------------------------------------


def test_session_tenant_id_is_written_only_by_auth_state() -> None:
    assignment = re.compile(r"\.session_tenant_id\s*=|self\.session_tenant_id\s*=")
    offenders = [
        path.name
        for path in _QUALIFY_DIR.glob("*.py")
        if path.name not in ("auth_state.py",)
        and not path.name.startswith("test_")
        and assignment.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"session_tenant_id must be set only by a real login: {offenders}"


def test_no_module_imports_the_dev_roster_anymore() -> None:
    """The dev tenant selector is dead (QUA-66): no UI module may import the roster or
    ship a switch. Changing business = logout + login, by signed ruling."""
    for path in _QUALIFY_DIR.glob("*.py"):
        if path.name.startswith("test_"):
            continue
        source = path.read_text(encoding="utf-8")
        assert "available_tenants" not in source, f"{path.name} resurrects the dev roster"
        assert "switch_tenant" not in source, f"{path.name} resurrects the tenant switch"


def test_access_token_is_backend_only() -> None:
    """The provider session token must never be a client-serialized var: leading
    underscore is Reflex's backend-only convention."""
    annotations = AuthState.__annotations__
    assert "_access_token" in annotations
    assert "access_token" not in annotations


def test_login_form_uses_literal_email() -> None:
    """Criterion 6: no email normalization anywhere in the auth path — the `+alias`
    IS the business disambiguation."""
    source = pathlib.Path(auth_state_module.__file__).read_text(encoding="utf-8")
    assert ".lower()" not in source
    assert 'replace("+"' not in source


# --------------------------------------------------------------------------------------
# Login robustness (2026-10-06)
# --------------------------------------------------------------------------------------


@pytest.fixture
def fresh_throttles(monkeypatch):
    from qualify_api.auth import AttemptThrottle

    login = AttemptThrottle(max_attempts=2, window_seconds=600)
    reset = AttemptThrottle(max_attempts=1, window_seconds=60)
    monkeypatch.setattr(auth_state_module, "login_throttle", login)
    monkeypatch.setattr(auth_state_module, "reset_request_throttle", reset)
    return login, reset


async def test_repeated_wrong_passwords_lock_the_email_with_the_real_wait(
    monkeypatch, fresh_throttles
) -> None:
    calls: list[str] = []
    provider = FakeAuthProvider()
    _use_fake_provider(monkeypatch, provider)
    original = provider.sign_in
    monkeypatch.setattr(provider, "sign_in", lambda e, p: calls.append(e) or original(e, p))
    state = _state()
    for _ in range(3):
        async for _ in AuthState.handle_login.fn(state, {"email": "a@b.co", "password": "x"}):
            raise AssertionError("a failed login must not navigate")
    assert len(calls) == 2  # the third attempt never reaches the provider
    assert "min" in state.auth_error


async def test_the_lock_ignores_the_email_capitalisation(monkeypatch, fresh_throttles) -> None:
    seen: list[str] = []

    def fake_login(email: str, password: str):
        seen.append(email)
        from qualify_api.auth import InvalidCredentials

        raise InvalidCredentials()

    monkeypatch.setattr(auth_state_module, "_login_blocking", fake_login)
    state = _state()
    for email in ("a@b.co", "A@b.co", "a@B.CO"):
        async for _ in AuthState.handle_login.fn(state, {"email": email, "password": "x" * 8}):
            pass
    assert seen == ["a@b.co", "A@b.co"]  # one window for every spelling, literal to the provider
    assert "min" in state.auth_error


async def test_an_outage_does_not_spend_the_operator_attempts(monkeypatch, fresh_throttles) -> None:
    from qualify_api.auth import AuthProviderError

    def provider_down(email: str, password: str):
        raise AuthProviderError("down")

    monkeypatch.setattr(auth_state_module, "_login_blocking", provider_down)
    state = _state()
    for _ in range(5):
        async for _ in AuthState.handle_login.fn(state, {"email": "a@b.co", "password": "x" * 8}):
            pass
    assert state.auth_error == auth_state_module._AUTH_DOWN  # never "wait N min"
    login, _ = fresh_throttles
    assert login.retry_after("a@b.co") == 0


async def test_login_trims_only_surrounding_whitespace(monkeypatch, fresh_throttles) -> None:
    seen: list[str] = []

    def fake_login(email: str, password: str):
        seen.append(email)
        from qualify_api.auth import InvalidCredentials

        raise InvalidCredentials()

    monkeypatch.setattr(auth_state_module, "_login_blocking", fake_login)
    state = _state()
    async for _ in AuthState.handle_login.fn(
        state, {"email": "  Hlrd1993+Polet@gmail.com ", "password": "x" * 8}
    ):
        pass
    assert seen == ["Hlrd1993+Polet@gmail.com"]  # case and +alias untouched


async def test_a_rate_limited_provider_is_not_reported_as_bad_credentials(
    monkeypatch, fresh_throttles
) -> None:
    from qualify_api.auth import RateLimited

    def fake_login(email: str, password: str):
        raise RateLimited()

    monkeypatch.setattr(auth_state_module, "_login_blocking", fake_login)
    state = _state()
    async for _ in AuthState.handle_login.fn(state, {"email": "a@b.co", "password": "x" * 8}):
        pass
    assert state.auth_error == auth_state_module._RATE_LIMITED


def test_login_copy_is_not_the_old_rule_text() -> None:
    source = (_QUALIFY_DIR / "auth_pages.py").read_text(encoding="utf-8")
    assert "Un login = un negocio" not in source
    assert 'href="/forgot"' in source
    assert '"current-password"' in source and '"new-password"' in source


# --------------------------------------------------------------------------------------
# Forgotten password (2026-10-06)
# --------------------------------------------------------------------------------------


async def test_reset_request_answers_the_same_for_any_email(monkeypatch, fresh_throttles) -> None:
    provider = FakeAuthProvider()  # nobody registered
    _use_fake_provider(monkeypatch, provider)
    state = _state()
    await AuthState.request_reset.fn(state, {"email": " nobody@b.co "})
    assert state.reset_sent_to == "nobody@b.co"
    assert state.auth_error == ""


async def test_reset_request_refuses_a_malformed_email(fresh_throttles) -> None:
    state = _state()
    await AuthState.request_reset.fn(state, {"email": "not-an-email"})
    assert state.reset_sent_to == "" and state.auth_error != ""


async def test_a_second_reset_request_within_a_minute_sends_nothing(
    monkeypatch, fresh_throttles
) -> None:
    provider = FakeAuthProvider()
    provider.seed_user("a@b.co", "password-123", tenant_id=None)
    _use_fake_provider(monkeypatch, provider)
    state = _state()
    for _ in range(2):
        await AuthState.request_reset.fn(state, {"email": "a@b.co"})
    assert len(provider.sent_resets) == 1
    assert state.reset_sent_to == "a@b.co"  # same screen, no hint it was throttled


def test_recovery_link_fragment_is_read_and_kept_backend_only() -> None:
    state = _state()
    AuthState.receive_recovery_link.fn(state, "#access_token=rec-tok&type=recovery&x=1")
    assert state.reset_link_state == "ready"
    assert state._recovery_token == "rec-tok"
    assert "_recovery_token" in AuthState.__annotations__
    assert "recovery_token" not in AuthState.__annotations__


@pytest.mark.parametrize(
    "fragment",
    ["#error=access_denied&error_code=otp_expired", "", "#access_token=t&type=signup"],
)
def test_a_dead_or_missing_recovery_link_is_invalid(fragment: str) -> None:
    state = _state()
    AuthState.receive_recovery_link.fn(state, fragment)
    assert state.reset_link_state == "invalid"
    assert state.auth_error != ""


async def test_reset_without_a_link_token_does_not_call_the_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_state_module,
        "_complete_reset_blocking",
        lambda *a: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    state = _state()
    async for _ in AuthState.submit_new_password.fn(
        state, {"password": "new-password", "confirm": "new-password"}
    ):
        raise AssertionError("no navigation without a token")
    assert state.reset_link_state == "invalid"


async def test_an_expired_link_on_submit_flips_to_invalid(monkeypatch) -> None:
    from qualify_api.auth import SessionExpired

    def expired(*args):
        raise SessionExpired()

    monkeypatch.setattr(auth_state_module, "_complete_reset_blocking", expired)
    state = _state()
    state._recovery_token = "rec-tok"
    async for _ in AuthState.submit_new_password.fn(
        state, {"password": "new-password", "confirm": "new-password"}
    ):
        raise AssertionError("no navigation on an expired link")
    assert state.reset_link_state == "invalid" and state._recovery_token == ""


# --------------------------------------------------------------------------------------
# Change password (/settings)
# --------------------------------------------------------------------------------------


async def test_wrong_current_password_counts_against_the_login_throttle(
    monkeypatch, fresh_throttles
) -> None:
    login_throttle, _ = fresh_throttles
    provider = FakeAuthProvider()
    provider.seed_user("a@b.co", "password-123", tenant_id=None)
    _use_fake_provider(monkeypatch, provider)
    state = _state()
    state.user_email = "a@b.co"
    form = {"current_password": "wrong-one", "password": "new-password", "confirm": "new-password"}
    async for _ in AuthState.submit_password_change.fn(state, form):
        pass
    assert state.auth_error == "La contraseña actual no es correcta."
    assert state.password_saved is False
    login_throttle.note("a@b.co")  # one more failure reaches the limit of 2
    assert login_throttle.retry_after("a@b.co") > 0


async def test_password_change_success_swaps_the_session_token(
    monkeypatch, fresh_throttles
) -> None:
    provider = FakeAuthProvider()
    provider.seed_user("a@b.co", "password-123", tenant_id=None)
    _use_fake_provider(monkeypatch, provider)
    state = _state()
    state.user_email = "a@b.co"
    state._access_token = "old-token"
    form = {
        "current_password": "password-123",
        "password": "new-password",
        "confirm": "new-password",
    }
    events = [e async for e in AuthState.submit_password_change.fn(state, form)]
    assert events  # clears the form + toast
    assert state.password_saved is True and state.auth_error == ""
    assert state._access_token != "old-token" and provider.token_is_live(state._access_token)


def test_settings_need_a_login_but_not_a_finished_brand_kit() -> None:
    state = _state()
    state.guest_tenant_id = _DRAFT
    assert AuthState.require_session.fn(state) is not None  # a draft is not a login
    state.session_tenant_id = "a0000000-0000-4000-8000-000000000001"
    state.brand_kit_complete = False
    assert AuthState.require_session.fn(state) is None


# --------------------------------------------------------------------------------------
# Signup gate: invite-only (founder decision 2026-10-14)
# --------------------------------------------------------------------------------------


async def test_signup_page_is_closed_without_an_invite(monkeypatch) -> None:
    state = _state()
    monkeypatch.delenv("QUALIFY_SIGNUP_OPEN", raising=False)
    await AuthState.enter_signup.fn(state)
    assert state.signup_open is False and state.invite_state == ""
    monkeypatch.setenv("QUALIFY_SIGNUP_OPEN", "1")
    await AuthState.enter_signup.fn(state)
    assert state.signup_open is True


async def test_an_uninvited_signup_is_refused_before_the_provider(monkeypatch) -> None:
    monkeypatch.delenv("QUALIFY_SIGNUP_OPEN", raising=False)
    monkeypatch.setattr(
        auth_state_module,
        "register_business",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("gate must stop it first")),
    )
    state = _state()
    form = {"business_name": "Polet", "email": "a@b.co", "password": "x" * 8, "country": "VE"}
    async for _ in AuthState.handle_signup.fn(state, form):
        raise AssertionError("a refused signup must not navigate")
    assert "invitación" in state.auth_error


def test_the_signup_page_has_no_shared_code_field() -> None:
    source = (_QUALIFY_DIR / "auth_pages.py").read_text(encoding="utf-8")
    assert "signup_code" not in source and "Código de invitación" not in source


async def test_an_invite_for_another_email_is_refused(monkeypatch) -> None:
    from uuid import uuid4

    from qualify_api.auth import InviteView
    from qualify_api.auth import invites as invites_module

    view = InviteView(id=uuid4(), email="cliente@negocio.com", expires_at=None)  # type: ignore[arg-type]
    monkeypatch.setattr(invites_module, "lookup_invite", lambda token: view)
    state = _state()
    state._invite_token = "tok"
    form = {"business_name": "X", "email": "otro@negocio.com", "password": "x" * 8, "country": "CO"}
    async for _ in AuthState.handle_signup.fn(state, form):
        raise AssertionError("a refused signup must not navigate")
    assert "cliente@negocio.com" in state.auth_error


@pytest.mark.parametrize(
    ("query", "token"),
    [
        ({"invitacion": "tok-es"}, "tok-es"),  # what emails carry since 2026-10-21
        ({"invite": "tok-en"}, "tok-en"),  # a link sent before, still within its days
        ({"invitacion": "tok-es", "invite": "tok-en"}, "tok-es"),
        ({"invitacion": "", "invite": "tok-en"}, "tok-en"),
        ({}, ""),
    ],
)
def test_the_signup_reads_the_invite_under_either_name(query: dict, token: str) -> None:
    assert auth_state_module.invite_token_from_query(query) == token


def test_the_signup_is_served_at_registro_and_at_the_old_signup() -> None:
    from qualify_api.auth import LEGACY_SIGNUP_ROUTE, SIGNUP_ROUTE

    assert (SIGNUP_ROUTE, LEGACY_SIGNUP_ROUTE) == ("/registro", "/signup")
    source = (_QUALIFY_DIR / "Qualify.py").read_text(encoding="utf-8")
    start = source.index("for _signup_route in (SIGNUP_ROUTE, LEGACY_SIGNUP_ROUTE):")
    block = source[start : source.index(")", source.index("on_load", start)) + 1]
    assert "signup_index" in block and "route=_signup_route" in block
    assert "AuthState.enter_signup" in block


def test_invite_token_is_backend_only() -> None:
    assert "_invite_token" in AuthState.__annotations__
    assert "invite_token" not in AuthState.__annotations__


def test_an_adopting_signup_ends_on_tu_marca_esta_lista() -> None:
    """m-24842965: the signup that adopted the pre-login Brand Kit lands on the wizard's
    «Tu marca está lista» card, the same end a logged-in finish has — and the login's
    allow-list lets that route through."""
    assert auth_state_module.BRAND_READY_ROUTE in auth_state_module._POST_LOGIN_ROUTES
    assert auth_state_module.BRAND_READY_ROUTE.startswith("/brand/manual?")
    source = inspect.getsource(AuthState.handle_signup.fn)
    assert '"next": BRAND_READY_ROUTE if adopted else "/"' in source


# --------------------------------------------------------------------------------------
# m-24842967 (MARCA-3): the signup asks the country, never the zone or the currency
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("country", "timezone", "currency"),
    [
        ("CO", "America/Bogota", "COP"),
        ("UY", "America/Montevideo", "UYU"),
        ("VE", "America/Caracas", "USD"),  # founder decision 10
    ],
)
async def test_the_signup_deduces_zone_and_currency_from_the_country(
    monkeypatch, country: str, timezone: str, currency: str
) -> None:
    seen: dict[str, str] = {}

    def fake_signup(business_name, email, password, country_, timezone_, currency_, token=""):
        seen.update(country=country_, timezone=timezone_, currency=currency_)
        raise auth_state_module.SignupNotAllowed("stop here")

    monkeypatch.setattr(auth_state_module, "_signup_blocking", fake_signup)
    state = _state()
    form = {
        "business_name": "Polet",
        "email": "a@b.co",
        "password": "x" * 8,
        "country": country,
        # a stale page still posting the old fields is ignored
        "timezone": "Europe/Madrid",
        "currency": "EUR",
    }
    async for _ in AuthState.handle_signup.fn(state, form):
        raise AssertionError("a refused signup must not navigate")
    assert seen == {"country": country, "timezone": timezone, "currency": currency}


async def test_a_signup_without_country_asks_for_it(monkeypatch) -> None:
    def must_not_run(*args, **kwargs):
        raise AssertionError("must stop before the provider")

    monkeypatch.setattr(auth_state_module, "_signup_blocking", must_not_run)
    state = _state()
    form = {"business_name": "Polet", "email": "a@b.co", "password": "x" * 8}
    async for _ in AuthState.handle_signup.fn(state, form):
        raise AssertionError("a refused signup must not navigate")
    assert state.auth_error == "Elige el país de tu negocio: Colombia, Venezuela o Uruguay."
    assert state.is_authenticating is False
