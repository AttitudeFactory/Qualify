"""«Tu avatar animado» on the Brand Kit editor (scaffold, § request 2026-10-19): the card
renders, «Regenerar» exists only behind the switch, and finishing the kit starts nothing
while the feature is off."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from qualify_api.creative import brand_avatar as ba

from . import brand_avatar_panel as panel
from .brand_kit_editor import _edit_view


def test_the_card_renders_with_its_placeholder_and_a_switch_gated_button() -> None:
    out = str(panel.brand_avatar_card().render())
    assert "Tu avatar animado" in out
    # the render escapes non-ASCII (á), so an ASCII stretch of the placeholder
    assert "cuando conectemos la generaci" in out
    assert "Regenerar" in out  # present in the tree, behind `BrandAvatarState.enabled`
    assert "brand_avatar_state" in out and "enabled" in out


def test_the_editor_shows_the_avatar_above_the_sections() -> None:
    out = str(_edit_view().render())
    assert out.index("Tu avatar animado") < out.index("Posicionamiento, audiencia")


def test_finishing_the_kit_starts_nothing_while_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ba.AVATAR_SWITCH_ENV, raising=False)

    def explode(*_args: object) -> None:
        raise AssertionError("generation started while off")

    monkeypatch.setattr(panel, "maybe_generate_after_kit", explode)

    async def run() -> bool:
        return panel.start_brand_avatar(uuid4(), uuid4())

    assert asyncio.run(run()) is False
    assert not panel._BACKGROUND


def test_finishing_the_kit_starts_the_avatar_in_the_background_when_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ba.AVATAR_SWITCH_ENV, "on")
    monkeypatch.setenv(ba.ARK_KEY_ENV, "ark-test-key")
    started: list[tuple[object, object]] = []
    monkeypatch.setattr(panel, "maybe_generate_after_kit", lambda t, b: started.append((t, b)))
    tenant, brand = uuid4(), uuid4()

    async def run() -> bool:
        ok = panel.start_brand_avatar(tenant, brand)
        await asyncio.gather(*panel._BACKGROUND)
        return ok

    assert asyncio.run(run()) is True
    assert started == [(tenant, brand)]
