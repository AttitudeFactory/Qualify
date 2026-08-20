"""Modules: publishing (Parte 4-A) and inbox/content (Parte 4-B) — a food venue with no
Instagram connection yet. Both screens must degrade to a truthful, actionable state
rather than a blank page or a live Meta call."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from .conftest import goto


def test_publish_without_connections_keeps_publicar_disabled(app: Page) -> None:
    goto(app, "/publish")
    expect(app.get_by_role("heading", name="Publicar", exact=True)).to_be_visible(timeout=20_000)
    expect(
        app.get_by_text("Sube un reel y publícalo en una de tus cuentas de Instagram conectadas")
    ).to_be_visible()
    for label in ("Cuenta", "Video", "Caption"):
        expect(app.get_by_text(label, exact=True).first).to_be_visible()
    expect(app.get_by_text("Arrastra un video o haz clic para elegirlo")).to_be_visible()
    caption = app.get_by_placeholder("Escribe el caption...")
    caption.fill("Martes de 2x1 en arepas de queso de mano después de las 8 pm 🫓")
    # Typing a caption is not enough: without an account chosen, nothing can be sent.
    expect(app.get_by_role("button", name="Publicar", exact=True)).to_be_disabled()


def test_inbox_without_connections_points_to_connections(app: Page) -> None:
    goto(app, "/inbox")
    expect(app.get_by_role("heading", name="Contenido de Instagram")).to_be_visible(timeout=20_000)
    expect(
        app.get_by_role("heading", name="No hay cuentas de Instagram listas para monitorear")
    ).to_be_visible(timeout=20_000)
    expect(
        app.get_by_text(
            "Conecta una cuenta de Instagram con el permiso de comentarios en Conexiones "
            "para elegir qué contenido monitorear."
        )
    ).to_be_visible()
    # The temporary manual-sync scaffolding must NOT show for a tenant with no account.
    expect(app.get_by_role("button", name="Sincronizar comentarios")).to_have_count(0)
    app.get_by_role("link", name="Ir a Conexiones").or_(
        app.get_by_role("button", name="Ir a Conexiones")
    ).first.click()
    expect(app).to_have_url(re.compile(r"/connections/?$"), timeout=20_000)
    expect(app.get_by_role("heading", name="Cuentas conectadas")).to_be_visible(timeout=20_000)
