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
    ["/signup", "/brand/connect", "/brand/manual", "/brand"],
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
        (brand_finish.KitStatus(True, {"completed": True, "flow": "connect"}), "/signup"),
        (brand_finish.KitStatus(False, {"completed": False, "flow": "connect"}), "/brand/connect"),
        (brand_finish.KitStatus(False, {"completed": False, "flow": "manual"}), "/brand/manual"),
        (brand_finish.KitStatus(False, None), "/brand"),
    ]
    for status, expected in cases:
        monkeypatch.setattr(brand_finish, "tenant_kit_status", lambda t, s=status: s)
        assert auth_state_module._draft_destination_blocking(_DRAFT) == expected


def test_the_dev_skip_link_exists_only_outside_production(monkeypatch) -> None:
    from reflex.utils import exec as rx_exec

    from . import auth_pages

    monkeypatch.setattr(rx_exec, "is_prod_mode", lambda: False)
    assert auth_pages._show_dev_skip() is True
    monkeypatch.setattr(rx_exec, "is_prod_mode", lambda: True)
    assert auth_pages._show_dev_skip() is False


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
    redirect_at = source.index('rx.redirect("/login")')
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
