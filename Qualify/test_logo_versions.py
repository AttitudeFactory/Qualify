"""Tu brandboard (§ requests 2026-09-29): no whole-brandboard upload and no brief document
any more — each version of the logo (Logotipo, Isotipo, Imagotipo, Isologo) is its own
dropzone with an example drawn from Qualify's mark, a "+" adds any other element
(stickers, patterns...), and everything uploaded takes a free-text context."""

from __future__ import annotations

from typing import Any

import pytest

from . import creative_wizard_pages as wiz
from .creative_wizard_pages import BrandWizardState


def test_the_four_versions_in_order() -> None:
    assert [name for _, name, _ in wiz.LOGO_VERSIONS] == [
        "Logotipo",
        "Isotipo",
        "Imagotipo",
        "Isologo",
    ]
    assert wiz.LOGO_VERSION_KEYS == {"logotipo", "isotipo", "imagotipo", "isologo"}


def test_tu_brandboard_has_the_versions_the_plus_and_nothing_else() -> None:
    rendered = str(wiz._step_logo(BrandWizardState.next_step))
    for key, name, _ in wiz.LOGO_VERSIONS:
        assert f"brand_logo_{key}" in rendered
        assert name in rendered
    assert wiz._EXTRA_UPLOAD_ID in rendered
    assert "Stickers, patrones" in rendered
    assert "Tienes un brief" not in rendered
    assert "Arrastra tu brandboard" not in rendered  # no whole-brandboard upload


@pytest.fixture
def wizard(monkeypatch: pytest.MonkeyPatch) -> BrandWizardState:
    state = BrandWizardState()

    async def stage(_self: Any, files: list[Any], folder: str) -> tuple[str, str, bytes] | None:
        return (f"uploads/t/{folder}/x_{files[0]}", str(files[0]), b"") if files else None

    monkeypatch.setattr(BrandWizardState, "_stage_logo_file", stage)
    return state


async def test_a_dropped_version_is_staged_under_its_own_key(wizard: BrandWizardState) -> None:
    await BrandWizardState.handle_logo_version_upload.fn(wizard, ["iso.png"], "isotipo")
    assert wizard.logo_versions == {"isotipo": "uploads/t/logo/isotipo/x_iso.png"}
    assert wizard.logo_colors == []  # a version adds no colours to the palette


async def test_an_unknown_version_is_ignored(wizard: BrandWizardState) -> None:
    await BrandWizardState.handle_logo_version_upload.fn(wizard, ["a.png"], "favicon")
    assert wizard.logo_versions == {}


def test_a_version_takes_a_context_and_removing_it_drops_both(wizard: BrandWizardState) -> None:
    wizard.logo_versions = {"isotipo": "a", "isologo": "b"}
    BrandWizardState.set_logo_version_context.fn(wizard, "isotipo", "Solo en fondos oscuros")
    BrandWizardState.set_logo_version_context.fn(wizard, "favicon", "x")  # not a version
    assert wizard.logo_version_context == {"isotipo": "Solo en fondos oscuros"}

    BrandWizardState.clear_logo_version.fn(wizard, "isotipo")
    assert wizard.logo_versions == {"isologo": "b"}
    assert wizard.logo_version_context == {}


async def test_the_plus_adds_one_element_per_file(wizard: BrandWizardState) -> None:
    await BrandWizardState.handle_extra_upload.fn(wizard, ["sticker.png", "patron.png"])
    assert [e["name"] for e in wizard.brand_extras] == ["sticker.png", "patron.png"]
    assert all(e["label"] == "" and e["context"] == "" for e in wizard.brand_extras)
    assert len({e["id"] for e in wizard.brand_extras}) == 2


async def test_an_element_takes_a_label_and_a_context(wizard: BrandWizardState) -> None:
    await BrandWizardState.handle_extra_upload.fn(wizard, ["sticker.png", "patron.png"])
    first, second = (e["id"] for e in wizard.brand_extras)
    BrandWizardState.set_extra_field.fn(wizard, first, "label", "Sticker")
    BrandWizardState.set_extra_field.fn(wizard, first, "context", "Para stories")
    BrandWizardState.set_extra_field.fn(wizard, first, "key", "hack")  # not editable
    assert wizard.brand_extras[0]["label"] == "Sticker"
    assert wizard.brand_extras[0]["context"] == "Para stories"
    assert wizard.brand_extras[0]["key"].endswith("sticker.png")

    BrandWizardState.remove_extra.fn(wizard, first)
    assert [e["id"] for e in wizard.brand_extras] == [second]
