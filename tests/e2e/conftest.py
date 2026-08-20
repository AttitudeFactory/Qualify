"""Playwright E2E harness for the Reflex CRM (`Qualify/`).

How it runs
-----------
* Against an app it boots itself: `reflex run` with **`QUALIFY_AUTH_FAKE=1`** (the in-memory
  `FakeAuthProvider` — signup/login work offline, no Supabase) on dedicated ports so a
  developer's own `reflex run` is never disturbed. Everything else is real: the compose
  Postgres (RLS, tenants, brands…), the compiled frontend, the websocket state layer.
* Or against an app already running: set `QUALIFY_E2E_BASE_URL=http://localhost:3100`
  (it must have been started with `QUALIFY_AUTH_FAKE=1`; the `qualify-crm-fake-auth`
  entry in `.claude/launch.json` does exactly that).

Isolation model
---------------
Reflex keeps state per *client token* (localStorage), so a fresh browser context is a
fresh, unauthenticated session. Each persona gets ONE session-scoped context that signs
up once through the real `/signup` form; module tests get a new *page* inside that
context (`app` fixture), which shares the token and therefore the login. That is the
cheapest arrangement that still exercises the auth path for real and keeps the tests
independent of ordering: any test can `goto()` any route.

Every signup creates a real tenant in the local Postgres, on purpose (the product's
whole tenancy model is what we are testing). Rows are greppable by their
`e2e-<slug>-<hex>@example.com` alias.
"""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, expect

from .personas import Persona, food_venue_persona

REPO_ROOT = Path(__file__).resolve().parents[2]

# Dedicated ports: launch.json uses 3100/8100 for the human's dev server.
E2E_FRONTEND_PORT = int(os.environ.get("QUALIFY_E2E_FRONTEND_PORT", "3390"))
E2E_BACKEND_PORT = int(os.environ.get("QUALIFY_E2E_BACKEND_PORT", "8390"))
# Cold start includes a frontend compile (and, in a fresh worktree, `bun install`).
E2E_BOOT_TIMEOUT_S = float(os.environ.get("QUALIFY_E2E_BOOT_TIMEOUT", "420"))

_PYTHONPATH = ":".join(
    str(REPO_ROOT / p)
    for p in (
        "packages/api/src",
        "packages/shared/src",
        "packages/scraper/src",
        "packages/creative/src",
        "packages/models/src",
    )
)

# Reflex renders the login/signup forms without ids; the placeholders ARE the contract
# the operator sees, so they are what the suite keys on (Playwright's accessible-name
# lookup). Centralised here so a copy change is a one-line fix.
LOGIN_EMAIL = "Email"
LOGIN_PASSWORD = "Contraseña"
LOGIN_SUBMIT = "Entrar"
SIGNUP_NAME = "Nombre del negocio"
SIGNUP_EMAIL = "Email (un alias por negocio)"
SIGNUP_PASSWORD = "Contraseña (mínimo 8 caracteres)"
SIGNUP_COUNTRY = "País"
SIGNUP_TIMEZONE = "Zona horaria"
SIGNUP_CURRENCY = "Moneda"
SIGNUP_SUBMIT = "Registrar y entrar"
LOGOUT_BUTTON = "Salir"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: drives the compiled Reflex app in a real browser")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.e2e)


# --- server -----------------------------------------------------------------------------


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310 — localhost only
            return 200 <= resp.status < 400
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return False


def _wait_until(predicate: Callable[[], bool], timeout_s: float, what: str) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(1.0)
    raise RuntimeError(f"timed out after {timeout_s:.0f}s waiting for {what}")


@pytest.fixture(scope="session")
def app_server() -> Iterator[str]:
    """Base URL of a running app in fake-auth mode; boots one when none is given."""
    external = os.environ.get("QUALIFY_E2E_BASE_URL")
    if external:
        yield external.rstrip("/")
        return

    if _port_open(E2E_FRONTEND_PORT) or _port_open(E2E_BACKEND_PORT):
        raise RuntimeError(
            f"ports {E2E_FRONTEND_PORT}/{E2E_BACKEND_PORT} are busy; stop the other process "
            "or point QUALIFY_E2E_BASE_URL at it"
        )

    env = dict(os.environ)
    env["QUALIFY_AUTH_FAKE"] = "1"
    env["PYTHONPATH"] = _PYTHONPATH + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    # Reflex's telemetry/update checks add nothing here and can stall a cold boot.
    env.setdefault("REFLEX_TELEMETRY_ENABLED", "false")
    env.setdefault("REFLEX_CHECK_LATEST_VERSION", "false")
    # Reflex dev mode hot-reloads the backend on ANY .py change under the repo — editing a
    # test file mid-run would restart the backend, wiping the in-memory fake auth store
    # and every session (measured 2026-08-18: 42 green → auth failures right after a
    # save). Point the watcher at an empty directory so the app under test never reloads.
    env["REFLEX_HOT_RELOAD_OVERRIDE_PATHS"] = tempfile.mkdtemp(prefix="qualify-e2e-noreload-")

    log_path = REPO_ROOT / ".e2e-reflex.log"
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, our own repo
        [
            "uv",
            "run",
            "--no-sync",
            "reflex",
            "run",
            "--frontend-port",
            str(E2E_FRONTEND_PORT),
            "--backend-port",
            str(E2E_BACKEND_PORT),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,  # own process group: reflex spawns bun/vite children
    )
    base_url = f"http://localhost:{E2E_FRONTEND_PORT}"
    try:
        _wait_until(
            lambda: (
                proc.poll() is None
                and _http_ok(f"http://localhost:{E2E_BACKEND_PORT}/ping")
                and _http_ok(base_url + "/")
            ),
            E2E_BOOT_TIMEOUT_S,
            f"reflex to serve {base_url} (log: {log_path})",
        )
        if proc.poll() is not None:
            raise RuntimeError(f"reflex exited early with {proc.returncode}; see {log_path}")
        yield base_url
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
        log.close()


@pytest.fixture(scope="session")
def base_url(app_server: str) -> str:
    """Overrides pytest-base-url so `page.goto("/x")` resolves against the app."""
    return app_server


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict, base_url: str) -> dict:
    return {
        **browser_context_args,
        "base_url": base_url,
        "viewport": {"width": 1280, "height": 800},
        "locale": "es-VE",
    }


# --- app driving helpers -------------------------------------------------------------------


_HYDRATED_MARKER = '"is_hydrated_rx_state_":true'
# `QUALIFY_E2E_TRACE_WS=1` prints every Reflex websocket frame — the fastest way to see
# what the backend actually answered when a page "does nothing" (run pytest with -s).
_TRACE_WS = os.environ.get("QUALIFY_E2E_TRACE_WS", "") == "1"
_HYDRATION_ATTR = "_qualify_hydration"


def track_hydration(page: Page) -> None:
    """Watch the Reflex event websocket so `wait_app_ready` can wait for real hydration.

    Reflex paints the HTML first and only then opens `/_event` and streams the state
    delta; a click/submit issued before the hydrate delta lands is queued behind it and
    — measured 2026-08-18 — sometimes never takes effect (login "hangs" on /login with
    no error). There is no DOM marker for hydration, but the delta that flips
    `is_hydrated_rx_state_` to true is visible on the wire, so we key on that. Every
    full page load opens a fresh socket, so the flag is reset per navigation.
    """
    state = {"hydrated": False}

    def on_websocket(ws) -> None:
        if "/_event" not in ws.url:
            return
        state["hydrated"] = False

        def on_frame(payload) -> None:
            if _TRACE_WS and isinstance(payload, str):
                print(f"[ws<<] {payload[:400]}")
            if isinstance(payload, str) and _HYDRATED_MARKER in payload:
                state["hydrated"] = True

        ws.on("framereceived", on_frame)
        if _TRACE_WS:
            ws.on("framesent", lambda f: print(f"[ws>>] {f[:400]}") if isinstance(f, str) else None)

    page.on("websocket", on_websocket)
    setattr(page, _HYDRATION_ATTR, state)


def wait_app_ready(page: Page, timeout_ms: int = 20_000) -> None:
    """Block until the Reflex state for the current page has hydrated (see
    `track_hydration`); falls back to a DOM heuristic for untracked pages."""
    state = getattr(page, _HYDRATION_ATTR, None)
    if state is None:
        expect(page.locator("body")).not_to_contain_text("Connection Error", timeout=timeout_ms)
        page.wait_for_load_state("domcontentloaded")
        return
    deadline = time.monotonic() + timeout_ms / 1000
    while not state["hydrated"]:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Reflex never hydrated {page.url} within {timeout_ms} ms")
        page.wait_for_timeout(50)  # pumps Playwright events (websocket frames)


def goto(page: Page, path: str) -> None:
    """Navigate + hydrate. Protected routes redirect to /login when unauthenticated, so
    tests that expect a page must assert on its content, not just on the URL."""
    state = getattr(page, _HYDRATION_ATTR, None)
    if state is not None:
        state["hydrated"] = False  # the new document opens a new socket
    page.goto(path)
    wait_app_ready(page)


def do_login(page: Page, persona: Persona) -> None:
    goto(page, "/login")
    page.get_by_placeholder(LOGIN_EMAIL, exact=True).fill(persona.email)
    page.get_by_placeholder(LOGIN_PASSWORD, exact=True).fill(persona.password)
    page.get_by_role("button", name=LOGIN_SUBMIT).click()
    expect(page).not_to_have_url(re.compile(r"/login/?$"), timeout=20_000)
    expect(page.get_by_text(persona.business_name, exact=True).first).to_be_visible(timeout=20_000)


def do_signup(page: Page, persona: Persona) -> None:
    goto(page, "/signup")
    page.get_by_placeholder(SIGNUP_NAME, exact=True).fill(persona.business_name)
    page.get_by_placeholder(SIGNUP_EMAIL, exact=True).fill(persona.email)
    page.get_by_placeholder(SIGNUP_PASSWORD, exact=True).fill(persona.password)
    page.get_by_placeholder(SIGNUP_COUNTRY, exact=True).fill(persona.country)
    page.get_by_placeholder(SIGNUP_TIMEZONE, exact=True).fill(persona.timezone)
    page.get_by_placeholder(SIGNUP_CURRENCY, exact=True).fill(persona.currency)
    page.get_by_role("button", name=SIGNUP_SUBMIT).click()
    # Signup auto-signs in and lands on the dashboard, whose topbar names the business.
    expect(page).not_to_have_url(re.compile(r"/signup/?$"), timeout=30_000)
    expect(page.get_by_text(persona.business_name, exact=True).first).to_be_visible(timeout=20_000)


def do_logout(page: Page) -> None:
    page.get_by_role("button", name=LOGOUT_BUTTON).click()
    expect(page).to_have_url(re.compile(r"/login/?$"), timeout=20_000)


# --- personas -----------------------------------------------------------------------------


@pytest.fixture(scope="session")
def food_venue() -> Persona:
    """Niche 1 — locales de comida. Fresh identity per session."""
    return food_venue_persona()


@pytest.fixture(scope="session")
def food_venue_page(
    browser: Browser, browser_context_args: dict, food_venue: Persona
) -> Iterator[Page]:
    """ONE tab per persona, signed up through the real form exactly once.

    Reflex keys server-side state by a client token kept in **sessionStorage**, i.e. per
    tab — a second tab in the same context is a second, unauthenticated session, and two
    tabs sharing a token get forcibly split (duplicate-tab detection). So the persona's
    session is a single long-lived page that every test navigates within; that mirrors
    how an operator actually uses the app and keeps the auth path real.
    """
    context = browser.new_context(**browser_context_args)
    block_external_hosts(context)
    page = context.new_page()
    track_hydration(page)
    do_signup(page, food_venue)
    yield page
    context.close()


@pytest.fixture(scope="session")
def registered_food_venue(food_venue_page: Page, food_venue: Persona) -> Persona:
    """The persona *after* its signup went through — for tests that log in as it from
    another browser context (depending on `food_venue` alone would not guarantee the
    account exists yet)."""
    return food_venue


@pytest.fixture
def app(food_venue_page: Page) -> Page:
    """The food-venue tab (already authenticated). Tests always `goto()` first."""
    return food_venue_page


@pytest.fixture
def anon(browser: Browser, browser_context_args: dict) -> Iterator[Page]:
    """A page in a brand-new context: no token, no session, nobody logged in."""
    context = browser.new_context(**browser_context_args)
    block_external_hosts(context)
    page = context.new_page()
    track_hydration(page)
    yield page
    context.close()


def area_under_label(page: Page, label: str):
    """The Brand Kit textareas have no name/placeholder — only a sibling label text."""
    return page.get_by_text(label, exact=True).locator("..").locator("textarea")


_EXTERNAL = re.compile(r"^https?://(?!localhost|127\.0\.0\.1)")


EXTERNAL_STUB_MARKER = "E2E-BLOCKED-EXTERNAL-NAVIGATION"


def block_external_hosts(context: BrowserContext) -> None:
    """The browser must never leave localhost during E2E: no Meta OAuth hop, no CDN,
    no vendor. Top-level navigations to another host are answered with a local stub
    page (so a test can still inspect the URL the app minted — e.g. the OAuth request —
    without a single packet reaching that host); every other external request is
    aborted."""

    def _handle(route) -> None:
        req = route.request
        if req.is_navigation_request() and req.resource_type == "document":
            route.fulfill(
                status=200,
                content_type="text/html",
                body=f"<html><body><h1>{EXTERNAL_STUB_MARKER}</h1><p>{req.url}</p></body></html>",
            )
        else:
            route.abort()

    context.route(_EXTERNAL, _handle)
