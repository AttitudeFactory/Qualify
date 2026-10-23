"""m-24840590: the connection guide on /connections, walked in a real browser.

A brand-new business has no connected account, so the guide is open before the first
«Conectar cuenta»: four numbered steps, each with its instructions behind «¿Cómo lo
hago?». The card hints («Ver el paso N») need a connected account and are covered by
the view-model tests in `Qualify/test_connections.py`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .conftest import expect

# Set to a directory to save screenshots of each state (for a PR description).
_SHOTS = os.environ.get("QUALIFY_E2E_SHOTS", "")


def _shot(page, name: str) -> None:  # noqa: ANN001 — a Playwright Page
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(_SHOTS) / f"{name}.png"), full_page=True)


# (step title, a phrase that only appears once that step is open)
_STEPS = [
    ("Tu Instagram es profesional y está vinculado a tu Página de Facebook", "Cambiar a cuenta"),
    ("Permite el acceso a tus mensajes", "Permitir acceso a los mensajes"),
    ("Conecta y acepta todos los permisos", "Deja todos los permisos marcados"),
    ("¿Ya estaba conectada? Vuelve a conectarla", "Acepta los permisos nuevos"),
]


def _phrase(text: str) -> re.Pattern[str]:
    return re.compile(re.escape(text))


def test_guide_is_open_before_the_first_connection_and_walks_four_steps(
    signed_up_page,  # noqa: ANN001 — a Playwright Page
    app_server: str,
) -> None:
    page = signed_up_page
    page.goto(f"{app_server}/connections")
    guide = page.locator("#guia-conexion")
    expect(
        guide.get_by_role("heading", name="Prepara tu Instagram antes de conectar")
    ).to_be_visible(timeout=60_000)

    # Nothing connected yet: the empty state below carries the page's «Conectar cuenta»,
    # and the guide cannot be folded away (its header has no «Ocultar»).
    expect(page.get_by_text("Aún no conectas ninguna cuenta")).to_be_visible()
    expect(page.get_by_role("button", name="Conectar cuenta")).to_have_count(1)
    expect(guide.get_by_role("button", name="Ocultar")).to_have_count(0)

    # Four steps, all folded.
    for title, detail in _STEPS:
        expect(guide.get_by_text(title, exact=True)).to_be_visible()
        expect(guide.get_by_text(_phrase(detail))).to_have_count(0)
    expect(guide.get_by_role("button", name="¿Cómo lo hago?")).to_have_count(4)

    # Walk them in order: open, read, close. One step open at a time.
    for index, (_title, detail) in enumerate(_STEPS):
        guide.get_by_role("button", name="¿Cómo lo hago?").nth(index).click()
        expect(guide.get_by_text(_phrase(detail))).to_be_visible()
        expect(guide.get_by_role("button", name="Ocultar")).to_have_count(1)
        expect(guide.get_by_role("button", name="¿Cómo lo hago?")).to_have_count(3)
        guide.get_by_role("button", name="Ocultar").click()
        expect(guide.get_by_text(_phrase(detail))).to_have_count(0)

    # The messages step spells the exact Instagram path the client has to follow.
    guide.get_by_role("button", name="¿Cómo lo hago?").nth(1).click()
    for label in (
        "Mensajes y respuestas a historias",
        "Controles de mensajes",
        "Herramientas conectadas",
    ):
        expect(guide.get_by_text(_phrase(label))).to_be_visible()
    _shot(page, "guia-paso-2")


def test_card_hint_names_whats_missing_and_opens_that_step(
    pre_fase_c_page,  # noqa: ANN001 — a Playwright Page
    app_server: str,
) -> None:
    """An account connected before Fase C: its card says the messages and the Page
    permission are missing; «Ver el paso 2» unfolds the guide on the messages step."""
    page = pre_fase_c_page
    page.goto(f"{app_server}/connections")
    expect(page.get_by_role("heading", name="@arepera.e2e")).to_be_visible(timeout=60_000)

    # With an account on screen the guide is folded to one line.
    guide = page.locator("#guia-conexion")
    expect(guide).to_have_count(0)
    expect(page.get_by_role("button", name="Ver la guía de conexión")).to_be_visible()

    expect(page.get_by_text("Los mensajes directos no están activos")).to_be_visible()
    expect(page.get_by_text("Falta un permiso nuevo de tu Página")).to_be_visible()
    expect(page.get_by_role("button", name="Volver a conectar")).to_have_count(1)
    _shot(page, "tarjeta-con-pistas")

    page.get_by_role("button", name="Ver el paso 2").click()
    expect(guide).to_be_visible()
    expect(guide.get_by_text(_phrase("Permitir acceso a los mensajes"))).to_be_visible()
    # Only that step is open.
    expect(guide.get_by_role("button", name="¿Cómo lo hago?")).to_have_count(3)
    _shot(page, "tarjeta-ver-paso-2")

    page.get_by_role("button", name="Ver el paso 4").click()
    expect(guide.get_by_text(_phrase("Acepta los permisos nuevos"))).to_be_visible()
    expect(guide.get_by_text(_phrase("Permitir acceso a los mensajes"))).to_have_count(0)
    # Accounts on screen: the guide can be folded again, and carries «Conectar cuenta».
    expect(guide.get_by_role("button", name="Conectar cuenta")).to_be_visible()
