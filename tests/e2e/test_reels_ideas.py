"""m-24854854 (ADR 42 R7): «Ideas para tus reels» opens on what is stored, in a real
browser.

A brand-new business follows no account and has no reels run, so opening the option
shows the empty state at once — no waiting on a search. That nothing reaches the vendor
or the model is pinned offline (`Qualify/test_reels_discovery.py`), where the paid doors
are faked to fail, and so is the absence of «Actualizar», the 90 days and the paid
transcript; here the browser checks the screen the owner sees.
"""

from __future__ import annotations

import os
from pathlib import Path

from .conftest import expect

# Set to a directory to save a screenshot of the state (for a PR description).
_SHOTS = os.environ.get("QUALIFY_E2E_SHOTS", "")


def test_a_new_business_sees_the_empty_state_at_once(
    signed_up_page,  # noqa: ANN001 — a Playwright Page
    app_server: str,
) -> None:
    page = signed_up_page
    page.goto(f"{app_server}/create")
    page.get_by_text("Descubrir ideas de videos").first.click()
    expect(page.get_by_role("heading", name="Aún no hay cuentas que te inspiren")).to_be_visible(
        timeout=60_000
    )
    expect(page.get_by_text("Elegir cuentas")).to_be_visible()
    if _SHOTS:
        Path(_SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(_SHOTS) / "ideas-vacio.png"), full_page=True)
