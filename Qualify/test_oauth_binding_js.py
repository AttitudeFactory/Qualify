"""The connect handlers' bound redirect (m-24921205): cookie first, then the consent page.

String-level checks always run; the behavioural ones execute the script under Node with a
stub `window`/`document` (skipped when Node is not installed)."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from qualify_api.connections.state_token import StartedConnect

from .oauth_binding_js import bound_redirect, bound_redirect_script, script_for

CALLBACK = "https://qualify.attitudefactory.co/api/connections/callback"
CONSENT = "https://www.facebook.com/dialog/oauth?state=abc.def&redirect_uri=x"


def _script(**overrides: object) -> str:
    values: dict[str, object] = {
        "authorization_url": CONSENT,
        "cookie_name": "qoauth_meta_0123456789abcdef",
        "cookie_value": "nonce-value_-",
        "max_age": 600,
        "callback_url": CALLBACK,
    }
    values.update(overrides)
    return bound_redirect_script(**values)  # type: ignore[arg-type]


def test_every_value_is_a_json_string_literal() -> None:
    hostile = 'https://evil.example/"); alert(1); ("</script>\\'
    script = _script(authorization_url=hostile, cookie_value='a"b\\c')
    assert json.dumps(hostile) in script
    assert json.dumps('a"b\\c') in script
    assert 'alert(1); ("' not in script.replace(json.dumps(hostile), "")


def test_cookie_is_set_before_leaving_and_carries_the_binding_attributes() -> None:
    script = _script()
    assert script.index("document.cookie") < script.index(json.dumps(CONSENT))
    assert "Path=/api/connections; Max-Age=600; SameSite=Lax" in script
    assert '"; Secure"' in script and 'window.location.protocol === "http:"' in script
    assert "Domain=" not in script  # host-only


def test_script_for_uses_the_started_flow() -> None:
    started = StartedConnect(
        authorization_url=CONSENT,
        binding_cookie_name="qoauth_tiktok_fedcba9876543210",
        binding_nonce="n0nce",
        max_age=300,
        callback_url=CALLBACK,
    )
    script = script_for(started)
    assert '"qoauth_tiktok_fedcba9876543210"' in script and '"n0nce"' in script
    assert "Max-Age=300" in script
    spec = bound_redirect(started)
    assert spec.handler.fn.__qualname__ == "_call_script"


def test_no_host_guard_without_a_parsable_callback() -> None:
    assert "location.hostname" not in _script(callback_url="")


_NODE = shutil.which("node")


def test_bound_redirect_uses_the_apps_public_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_APP_URL", "https://qualify.attitudefactory.co")
    started = StartedConnect(
        authorization_url=CONSENT,
        binding_cookie_name="qoauth_meta_0123456789abcdef",
        binding_nonce="n",
        max_age=600,
        callback_url=CALLBACK,
    )
    spec = bound_redirect(started)
    args = {name._js_expr: value._var_value for name, value in spec.args}
    assert (
        '"https://qualify.attitudefactory.co" + window.location.pathname'
        in (args["javascript_code"])
    )


def test_invalid_state_copy_names_the_other_app_case() -> None:
    from . import connections_vm, tiktok_vm

    meta = connections_vm.CONNECT_RESULT_NOTICES["invalid_state"][0]
    tiktok = tiktok_vm.CONNECT_RESULT_NOTICES["invalid_state"][0]
    for text, button in ((meta, "«Conectar cuenta»"), (tiktok, "el botón de TikTok")):
        assert "otra aplicación" in text and button in text and "termina desde aquí" in text


def _run(script: str, page_url: str) -> dict[str, object]:
    harness = f"""
const u = new URL({json.dumps(page_url)});
const out = {{cookie: null, assigned: null}};
globalThis.window = {{location: {{
  hostname: u.hostname, protocol: u.protocol, pathname: u.pathname, search: u.search,
  assign: (to) => {{ out.assigned = to; }} }}}};
globalThis.document = {{ set cookie(v) {{ out.cookie = v; }} }};
{script};
console.log(JSON.stringify(out));
"""
    done = subprocess.run(
        [_NODE or "node", "-e", harness], capture_output=True, text=True, check=True, timeout=20
    )
    return json.loads(done.stdout)


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_https_on_the_callback_host_sets_a_secure_cookie_then_leaves() -> None:
    out = _run(_script(), "https://qualify.attitudefactory.co/connections")
    assert out["cookie"] == (
        "qoauth_meta_0123456789abcdef=nonce-value_-; Path=/api/connections; Max-Age=600;"
        " SameSite=Lax; Secure"
    )
    assert out["assigned"] == CONSENT


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_local_http_dev_omits_secure_and_ignores_the_port() -> None:
    script = _script(callback_url="http://localhost:8000/api/connections/callback")
    out = _run(script, "http://localhost:3000/connections")
    assert out["cookie"] is not None and not str(out["cookie"]).endswith("Secure")
    assert out["assigned"] == CONSENT


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_another_host_moves_to_the_app_origin_keeping_path_and_query() -> None:
    script = _script(app_origin="https://qualify.attitudefactory.co")
    out = _run(script, "https://app.qualify.la/inbox?tab=dm&x=1")
    assert out["cookie"] is None
    assert out["assigned"] == "https://qualify.attitudefactory.co/inbox?tab=dm&x=1"


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_without_a_usable_app_origin_falls_back_to_the_callback_host_without_port() -> None:
    callback = "https://qualify.attitudefactory.co:8443/api/connections/callback"
    for origin in ("", "https://app.qualify.la"):  # unknown, or one that would loop
        out = _run(
            _script(callback_url=callback, app_origin=origin), "https://app.qualify.la/p?q=1"
        )
        assert out["cookie"] is None
        assert out["assigned"] == "https://qualify.attitudefactory.co/p?q=1"


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_local_dev_on_the_callback_hostname_starts_the_flow() -> None:
    script = _script(
        callback_url="http://localhost:8000/api/connections/callback",
        app_origin="http://localhost:3000",
    )
    out = _run(script, "http://localhost:3000/connections")
    assert out["assigned"] == CONSENT and out["cookie"] is not None


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_hostile_values_stay_data_when_executed() -> None:
    hostile = 'https://evil.example/"); globalThis.pwned = 1; ("'
    out = _run(
        _script(authorization_url=hostile) + "; out.pwned = globalThis.pwned ?? null",
        "https://qualify.attitudefactory.co/connections",
    )
    assert out["assigned"] == hostile
    assert out.get("pwned") is None


@pytest.mark.skipif(_NODE is None, reason="node not installed")
def test_a_callback_on_the_page_host_sets_the_cookie_there_and_leaves() -> None:
    """m-24947215: the seam put the callback on app.qualify.la, so no bounce to the other
    host (where the client has no session) — the cookie is set on this host."""
    script = _script(
        callback_url="https://app.qualify.la/api/connections/tiktok/callback",
        app_origin="https://qualify.attitudefactory.co",
    )
    out = _run(script, "https://app.qualify.la/connections")
    assert out["assigned"] == CONSENT
    assert str(out["cookie"]).startswith("qoauth_meta_0123456789abcdef=nonce-value_-;")


class _Headers:
    def __init__(self, origin: object) -> None:
        self.origin = origin


class _Router:
    def __init__(self, origin: object) -> None:
        self.headers = _Headers(origin)


class _State:
    def __init__(self, origin: object) -> None:
        self.router = _Router(origin)


def test_page_origin_reads_the_websocket_origin_and_tolerates_none() -> None:
    from .oauth_binding_js import page_origin

    assert page_origin(_State("https://app.qualify.la")) == "https://app.qualify.la"  # type: ignore[arg-type]
    assert page_origin(_State(None)) == ""  # type: ignore[arg-type]
    assert page_origin(object()) == ""  # type: ignore[arg-type]
