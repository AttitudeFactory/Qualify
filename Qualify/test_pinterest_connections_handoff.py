"""Same-business handoff reuses the existing expiring, one-use switch pass."""

from __future__ import annotations

import json
import shutil
import subprocess
from uuid import UUID

import pytest
from qualify_api.auth import NotAMember

from . import auth_state as module
from .auth_state import AuthState
from .business_switch import (
    connections_tab_script,
    open_connections_tab_script,
    switch_destination,
)
from .test_business_selector import BIANKI, LOGIN, _active


def state() -> AuthState:
    auth = AuthState()
    auth.session_tenant_id = str(BIANKI)
    auth._auth_user_id = str(LOGIN)
    auth._access_token = "server-only-access-token"
    return auth


def test_child_script_never_clears_parent_storage_or_exposes_token() -> None:
    script = open_connections_tab_script()
    assert "tab.sessionStorage.removeItem" in script
    assert "tab.opener = null" in script
    assert "window.sessionStorage.removeItem" not in script
    assert "localStorage" not in script and "cookie" not in script
    assert "return id" in script
    navigation = connections_tab_script(str(LOGIN), "a-single-use-pass")
    assert "destino=redes" in navigation and "about:blank" in navigation
    assert "window.location.replace" not in navigation
    assert "tab.close()" in connections_tab_script(str(LOGIN))


@pytest.mark.parametrize("old_pass", ["", "old-pass-must-not-navigate"])
def test_exact_browser_scripts_correlate_delayed_callback_to_its_own_child(old_pass: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip(
            "Node is unavailable; exact JavaScript regression requires the Reflex toolchain"
        )
    first, second = str(LOGIN), str(BIANKI)
    script = r"""
(() => {
const assert = require('node:assert/strict');
let counter = 0;
const crypto = {randomUUID: () => [FIRST, SECOND][counter++]};
const removed = [];
function child() { return {
  closed:false, opener:{}, sessionStorage:{removeItem:key => removed.push(key)},
  location:{href:'about:blank', replace(url){this.href=url}}, close(){this.closed=true}
}; }
const children = [];
global.window = {
  open(){const tab=child(); children.push(tab); return tab},
  sessionStorage:{removeItem(){throw Error('parent storage changed')}}
};
const open = () => eval(OPEN);
assert.equal(open(), FIRST);
children[0].closed = true;
assert.equal(open(), SECOND);
eval(OLD);
assert.equal(children[1].location.href, 'about:blank');
assert.equal(children[1].closed, false);
eval(NEW);
assert.match(children[1].location.href, /new-pass/);
assert.equal(children[1].opener, null);
assert.equal(removed.length, 2);
assert.deepEqual(Object.keys(window.__qualifyConnectionsTabs), []);
window.open = () => null;
assert.equal(open(), '');
})();
"""
    for marker, value in {
        "FIRST": first,
        "SECOND": second,
        "OPEN": open_connections_tab_script(),
        "OLD": connections_tab_script(first, old_pass),
        "NEW": connections_tab_script(second, "new-pass"),
    }.items():
        script = script.replace(marker, json.dumps(value))
    result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("fragment", "expected"),
    [
        ("#pase=p&destino=redes", "/connections#pinterest"),
        ("#pase=p&destino=https://attacker.example", "/"),
        ("#pase=p&destino=redes&destino=otro", "/"),
        ("#pase=p", "/"),
    ],
)
def test_destination_is_closed(fragment: str, expected: str) -> None:
    assert switch_destination(fragment) == expected


@pytest.mark.asyncio
async def test_handoff_checks_current_membership_and_preserves_original_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = state()
    calls = []
    monkeypatch.setattr(module, "_open_business_blocking", lambda u, t: calls.append((u, t)))

    def issue(user: UUID, tenant: UUID, token: str) -> str:
        assert (user, tenant, token) == (LOGIN, BIANKI, "server-only-access-token")
        assert calls == [(str(LOGIN), str(BIANKI))]
        return "one-use-pass"

    monkeypatch.setattr(module, "issue_switch_pass", issue)
    events = [event async for event in AuthState.open_pinterest_connections.fn(auth, str(LOGIN))]
    assert "one-use-pass" in str(events)
    assert "server-only-access-token" not in str(events)
    assert auth.session_tenant_id == str(BIANKI) and auth._auth_user_id == str(LOGIN)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["popup", "membership", "actor"])
async def test_failed_handoff_never_navigates_child_or_changes_original_business(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    auth = state()

    def check(*_: object) -> None:
        if failure == "membership":
            raise NotAMember()

    def issue(*_: object) -> str:
        if failure == "actor":
            auth._auth_user_id = "changed-actor"
        return "must-not-be-emitted"

    monkeypatch.setattr(module, "_open_business_blocking", check)
    monkeypatch.setattr(module, "issue_switch_pass", issue)
    events = [
        event
        async for event in AuthState.open_pinterest_connections.fn(
            auth, "" if failure == "popup" else str(LOGIN)
        )
    ]
    assert "must-not-be-emitted" not in str(events)
    assert auth.session_tenant_id == str(BIANKI)
    if failure != "popup":
        assert "tab.close()" in str(events)


@pytest.mark.asyncio
async def test_redemption_opens_validated_business_then_canonical_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .business_switch import SwitchPass

    auth = AuthState()
    monkeypatch.setattr(module, "redeem_switch_pass", lambda _: SwitchPass(LOGIN, BIANKI, "tok"))
    monkeypatch.setattr(module, "_open_business_blocking", lambda *_: _active(BIANKI))
    monkeypatch.setattr(module, "_memberships_blocking", lambda _: [(str(BIANKI), "Bianki")])
    monkeypatch.setattr(module, "_kit_complete_blocking", lambda _: True)
    events = [event async for event in AuthState.redeem_switch.fn(auth, "#pase=x&destino=redes")]
    assert auth.session_tenant_id == str(BIANKI)
    assert "/connections#pinterest" in str(events[-1])
    assert "history.replaceState" in str(events[0])
