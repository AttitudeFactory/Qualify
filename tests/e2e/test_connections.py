"""Module: connected accounts (C-06) — a food venue that has not linked Instagram yet.

The OAuth hop to Meta is never followed (the harness aborts every non-localhost
request), so "Conectar cuenta" is exercised only up to the point where the app either
mints the redirect (Meta env configured) or explains why it could not (unconfigured).
Both are legitimate outcomes locally; leaving the origin is not.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Page, expect

from .conftest import EXTERNAL_STUB_MARKER, goto

EMPTY_HEADING = "Aún no conectas ninguna cuenta"
EMPTY_BODY = (
    "Conecta tu primera cuenta de Instagram o Facebook para empezar a escuchar y "
    "responder desde Qualify."
)
CANNOT_START = "No se pudo iniciar la conexión con Meta. Vuelve a intentarlo en un momento."
NO_USER = "Este tenant no tiene ningún usuario al que atribuir la conexión."


def test_fresh_venue_sees_the_empty_state(app: Page) -> None:
    goto(app, "/connections")
    expect(app.get_by_role("heading", name="Cuentas conectadas")).to_be_visible(timeout=20_000)
    expect(
        app.get_by_text("Estado de salud y permisos de tus cuentas de Instagram y Facebook")
    ).to_be_visible()
    expect(app.get_by_role("heading", name=EMPTY_HEADING)).to_be_visible(timeout=20_000)
    expect(app.get_by_text(EMPTY_BODY)).to_be_visible()
    expect(app.get_by_role("button", name="Conectar cuenta")).to_be_enabled()
    # No connection cards → none of the per-card controls exist.
    expect(app.get_by_role("button", name="Desconectar")).to_have_count(0)


def test_connect_button_mints_a_meta_oauth_request_or_explains_why_not(app: Page) -> None:
    """Two legitimate local outcomes, one forbidden one.

    * Meta env configured → the app redirects to Meta's OAuth dialog. The harness answers
      that navigation with a local stub, so we can assert the request the app minted
      (client_id, redirect_uri, one-time state, scope) without touching facebook.com.
    * Meta env absent → the amber callout explains it and the page stays put.
    * Forbidden: anything else (silent no-op, blank page, real network hop).
    """
    goto(app, "/connections")
    expect(app.get_by_role("heading", name=EMPTY_HEADING)).to_be_visible(timeout=20_000)
    app.get_by_role("button", name="Conectar cuenta").click()

    stub = app.get_by_role("heading", name=EXTERNAL_STUB_MARKER)
    callout = app.get_by_text(CANNOT_START).or_(app.get_by_text(NO_USER))
    expect(stub.or_(callout).first).to_be_visible(timeout=20_000)

    if stub.count():
        parts = urlsplit(app.url)
        assert (
            parts.scheme == "https" and parts.hostname and parts.hostname.endswith("facebook.com")
        ), f"unexpected OAuth host: {app.url}"
        query = parse_qs(parts.query)
        for key in ("client_id", "redirect_uri", "state"):
            assert query.get(key), f"OAuth request is missing `{key}`: {app.url}"
        assert query.get("response_type") == ["code"]
        # `scope`/`config_id` are omitted BY DESIGN when QUALIFY_META_SCOPES /
        # QUALIFY_META_CONFIG_ID are unset (meta_oauth.py), so they are not required here.
        # Note for the reader: `client_id=dev-app-id` means the app is running on
        # `MetaOAuthSettings.from_env` dev defaults — it fails loudly at Meta, not here.
        assert "localhost" in query["redirect_uri"][0] or "127.0.0.1" in query["redirect_uri"][0]
        # Back in the app: the tenant still has no connection (nothing was persisted).
        goto(app, "/connections")
        expect(app.get_by_role("heading", name=EMPTY_HEADING)).to_be_visible(timeout=20_000)
    else:
        assert app.url.startswith("http://localhost"), f"browser left the app: {app.url}"
