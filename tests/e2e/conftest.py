"""Playwright browser tests for the Reflex app (`Qualify/`) — the minimal harness.

Not part of the offline gate: the root `testpaths` never collects `tests/`, and every
test here skips unless Playwright is importable. Run with `just e2e`.

How it runs
-----------
* Against an app already running: `QUALIFY_E2E_BASE_URL=http://localhost:3400`. That app
  must run with `QUALIFY_AUTH_FAKE=1` (offline identity) and `QUALIFY_SIGNUP_OPEN=1`
  (signup without an invite, dev only), because each test signs up its own business.
* Or the harness boots one on the agreed E2E ports (3390 frontend / 8390 backend), never
  3100 (main) or 3400 (preview), which belong to other sessions.

Everything else is real: the compose Postgres (RLS, tenants), the compiled frontend and
the websocket state. Every signup creates a real local tenant, greppable by its
`e2e-<hex>@example.com` email.

Reflex keeps the client token per tab (sessionStorage), so one test = one page: a new
page is a new, unauthenticated session.
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
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api")
expect = playwright_sync.expect

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_PORT = int(os.environ.get("QUALIFY_E2E_FRONTEND_PORT", "3390"))
BACKEND_PORT = int(os.environ.get("QUALIFY_E2E_BACKEND_PORT", "8390"))
BOOT_TIMEOUT_S = float(os.environ.get("QUALIFY_E2E_BOOT_TIMEOUT", "420"))
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


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: drives the compiled Reflex app in a real browser")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(pytest.mark.e2e)


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


@pytest.fixture(scope="session")
def app_server() -> Iterator[str]:
    """Base URL of an app in fake-auth, open-signup mode; boots one when none is given."""
    external = os.environ.get("QUALIFY_E2E_BASE_URL")
    if external:
        yield external.rstrip("/")
        return
    if _port_open(FRONTEND_PORT) or _port_open(BACKEND_PORT):
        raise RuntimeError(
            f"ports {FRONTEND_PORT}/{BACKEND_PORT} are busy; stop that process or point "
            "QUALIFY_E2E_BASE_URL at it"
        )
    env = dict(os.environ)
    env.update(
        QUALIFY_AUTH_FAKE="1",
        QUALIFY_SIGNUP_OPEN="1",
        REFLEX_TELEMETRY_ENABLED="false",
        REFLEX_CHECK_LATEST_VERSION="false",
        # Dev mode reloads on any .py change; an edit mid-run would wipe every session.
        REFLEX_HOT_RELOAD_OVERRIDE_PATHS=tempfile.mkdtemp(prefix="qualify-e2e-noreload-"),
    )
    env["PYTHONPATH"] = _PYTHONPATH + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    log = (REPO_ROOT / ".e2e-reflex.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603 — fixed argv, our own repo
        [
            "uv",
            "run",
            "--no-sync",
            "reflex",
            "run",
            "--frontend-port",
            str(FRONTEND_PORT),
            "--backend-port",
            str(BACKEND_PORT),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    base = f"http://localhost:{FRONTEND_PORT}"
    try:
        deadline = time.monotonic() + BOOT_TIMEOUT_S
        while not (_http_ok(f"http://localhost:{BACKEND_PORT}/ping") and _http_ok(base)):
            if proc.poll() is not None:
                raise RuntimeError("reflex exited during boot; see .e2e-reflex.log")
            if time.monotonic() > deadline:
                raise RuntimeError("reflex did not boot in time; see .e2e-reflex.log")
            time.sleep(1.0)
        yield base
    finally:
        os.killpg(proc.pid, signal.SIGINT)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
        log.close()


def _finish_brand_kit(email: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Give the just-registered business a (bare) finished Brand Kit, straight in the
    local database. Every app page except the Brand Kit's own sends a business without
    one to /brand (`AuthState.require_login`); the kit wizard is not what these tests
    are about. The tenant is found by the signup email, then written under its own RLS
    scope through the sanctioned doors."""
    from qualify_api.creative.brand_service import BrandKitService
    from qualify_api.tenancy.models import Brand, User
    from qualify_creative.schemas import BrandKit, ToneAxes
    from qualify_shared.db.admin import admin_session
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    with admin_session() as session:
        row = session.execute(select(User.tenant_id, User.id).where(User.email == email)).first()
    assert row is not None, f"signup created no user for {email}"
    tenant_id, user_id = row
    with tenant_session(tenant_id) as session:
        brand_id = session.scalar(select(Brand.id).order_by(Brand.created_at))
    assert brand_id is not None
    kit = BrandKit(
        brand_id=brand_id,
        positioning="Arepas hechas al momento",
        audience="Vecinos del barrio",
        tone_axes=ToneAxes(
            formal_casual=50, sober_enthusiastic=50, technical_plain=50, brief_elaborate=50
        ),
    )
    BrandKitService().upsert_kit(tenant_id=tenant_id, brand_id=brand_id, kit=kit, user_id=user_id)
    # The signup opens the Brand Kit wizard, which records its position as unfinished
    # (`connect.progress.completed = False`) — and an unfinished kit sends every page
    # back to /brand (`brand_finish.kit_status`). Mark it finished, as the wizard's last
    # step would.
    from qualify_api.creative.brand_kit_store import BrandKitStore

    BrandKitStore().set_document_key(
        tenant_id=tenant_id,
        brand_id=brand_id,
        document="connect",
        key="progress",
        value={"completed": True},
    )
    return tenant_id, user_id


# Production's Facebook-Login grant BEFORE Fase C (m-24840401): basic, publishing and
# comments, but none of the messaging scopes nor the Page-subscription one.
PRE_FASE_C_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "business_management",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_comments",
]
_E2E_PLATFORM_APP = uuid.UUID("e2e00000-0000-4000-8000-000000000001")


def _seed_instagram_connection(tenant_id: uuid.UUID, user_id: uuid.UUID, scopes: list[str]) -> None:
    """An active Instagram connection with the given scopes, as a connect would leave
    it — WITHOUT a credential: these tests never call Meta. Inserted in-tenant
    (`qualify_admin` has no INSERT on `social_connections`, by design)."""
    from qualify_api.connections.models import PlatformApp, SocialConnection
    from qualify_api.tenancy.models import Brand
    from qualify_shared.db.admin import admin_session
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    with admin_session() as session:
        if session.get(PlatformApp, _E2E_PLATFORM_APP) is None:
            session.add(
                PlatformApp(
                    id=_E2E_PLATFORM_APP,
                    app_id="e2e-test-app",
                    secret_ref="env:E2E_TEST_APP_SECRET",
                    api_version="v23.0",
                )
            )
    connection_id = uuid.uuid4()
    with tenant_session(tenant_id) as session:
        brand_id = session.scalar(select(Brand.id).order_by(Brand.created_at))
        session.add(
            SocialConnection(
                id=connection_id,
                tenant_id=tenant_id,
                brand_id=brand_id,
                platform_app_id=_E2E_PLATFORM_APP,
                platform="instagram",
                account_type="business",
                external_account_id=f"e2e-{connection_id}",
                external_username="@arepera.e2e",
                linked_page_id=f"e2e-page-{connection_id}",
                granted_scopes=scopes,
                status="active",
                access_posture="development",
                current_credential_version=1,
                connected_by_user_id=user_id,
            )
        )


def _open_business(app_server: str, context, scopes: list[str] | None):  # noqa: ANN001, ANN202
    """Sign up a brand-new business through the real /registro form, finish its Brand
    Kit in the database (plus an Instagram connection when `scopes` is given), then
    log in on a NEW tab: the token is per tab, and the kit check runs at login."""
    email = f"e2e-{uuid.uuid4().hex[:10]}@example.com"
    password = "e2e-clave-segura"
    signup = context.new_page()
    signup.set_default_timeout(30_000)
    signup.goto(f"{app_server}/registro")
    # Labelled fields since m-24842967 (a placeholder is not a label); the country is
    # required since the signup deduces zone and currency from it.
    signup.locator("#signup-business").fill("E2E · Arepera Doña Carmen")
    signup.locator("#signup-email").fill(email)
    signup.locator("#signup-password").fill(password)
    signup.locator("#signup-country").click()
    signup.get_by_role("option", name="Colombia").click()
    signup.get_by_role("button", name="Registrar y entrar").click()
    expect(signup).not_to_have_url(re.compile(r"/registro"), timeout=60_000)
    # Let the wizard the signup lands on write its progress before the kit is finished
    # under it (a late write would mark the kit unfinished again).
    signup.wait_for_timeout(3_000)
    signup.close()

    tenant_id, user_id = _finish_brand_kit(email)
    if scopes is not None:
        _seed_instagram_connection(tenant_id, user_id, scopes)

    page = context.new_page()
    page.set_default_timeout(30_000)
    page.goto(f"{app_server}/login")
    page.get_by_placeholder("Correo", exact=True).fill(email)
    page.get_by_placeholder("Contraseña", exact=True).fill(password)
    page.get_by_role("button", name="Entrar", exact=True).click()
    expect(page).not_to_have_url(re.compile(r"/login"), timeout=60_000)
    return page


@pytest.fixture()
def signed_up_page(app_server: str, context):  # noqa: ANN001, ANN201 — pytest-playwright
    """A page logged into a brand-new business with no connected accounts yet."""
    return _open_business(app_server, context, scopes=None)


@pytest.fixture()
def pre_fase_c_page(app_server: str, context):  # noqa: ANN001, ANN201 — pytest-playwright
    """A page logged into a business whose Instagram was connected before Fase C."""
    return _open_business(app_server, context, scopes=list(PRE_FASE_C_SCOPES))
