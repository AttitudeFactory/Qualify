"""Tu brandboard's typography (§ request 2026-10-05): a section between the logo versions
and the other elements — a tile per type face (name + optional file), "Detectar desde tu
logo", the brandboard's column centred — and the font files saved with the brandboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.brand_kit_store import FONT, LOGO_VERSION

from . import brand_finish
from . import creative_wizard_pages as wiz
from .brand_finish import KitSnapshot, StagedFile, content_type_of
from .creative_state import CreativeState, font_family_css, google_fonts_url
from .creative_vm import KitFormVM
from .creative_wizard_pages import BrandWizardState

TENANT = UUID("a0000000-0000-4000-8000-0000000000c5")
BRAND = UUID("b0000000-0000-4000-8000-0000000000c5")
USER = UUID("c0000000-0000-4000-8000-0000000000c5")
TIPOGRAFIA = "Tipograf\\u00eda"  # how the compiler escapes the label in the rendered tree


# -- the section ----------------------------------------------------------------------------


def test_there_is_one_type_face() -> None:
    """§ third round of 2026-10-05, "solo haz una tipografía": one tile, not Títulos +
    Cuerpo de texto, and the body face follows it so readers of either field agree."""
    assert [name for _, name, _ in wiz.FONT_SLOTS] == ["Tu tipografía"]
    assert wiz.FONT_SLOT_KEYS == {"heading"}
    state = CreativeState()
    CreativeState.set_kit_font_heading.fn(state, "Montserrat")
    assert (state.kit_font_heading, state.kit_font_body) == ("Montserrat", "Montserrat")
    assert state.kit_typography_summary == "Montserrat"


def test_the_detection_result_is_a_toast_not_a_note_under_the_tile() -> None:
    """§ third round of 2026-10-05: "no quiero ese tipo de notificación"."""
    assert "font_note" not in str(wiz._step_typography())


def test_tipografia_is_its_own_step_right_before_the_palette_in_every_flow() -> None:
    """§ second round of 2026-10-05: a view of its own, not a section of Tu brandboard, so
    it is asked whether or not a brandboard was uploaded."""
    from .brand_kit_editor import _PALETTE_STEP, _TYPOGRAPHY_STEP, EDIT_STEPS

    for steps, index in (
        (wiz.STEPS, wiz._M_TYPOGRAPHY_STEP),
        (wiz.CONNECT_STEPS, wiz._TYPOGRAPHY_STEP),
        (EDIT_STEPS, _TYPOGRAPHY_STEP),
    ):
        assert steps[index][0] == "Tipografía"
        assert steps[index + 1][0] == "Paleta de colores"
        assert steps[index - 1][0] == "Tu brandboard"
    assert _TYPOGRAPHY_STEP + 1 == _PALETTE_STEP
    # Tu brandboard itself is back to logo versions + other elements
    brandboard = str(wiz._step_logo(BrandWizardState.next_step))
    assert TIPOGRAFIA not in brandboard and "brand_font_heading" not in brandboard


def test_the_typography_step_has_the_tile_and_the_detection() -> None:
    rendered = str(wiz._step_typography())
    for key in wiz.FONT_SLOT_KEYS:
        assert f"brand_font_{key}" in rendered
    assert "Detectar desde tu logo" in rendered
    assert "Ej.: Montserrat" in rendered
    assert "@font-face" in rendered  # the uploaded file is what the preview is set in
    assert "stylesheet" in rendered  # a typed name is previewed through its Google Fonts sheet
    assert "si no tienes una" in rendered.lower()  # "poner una si no tiene"


def test_an_influencer_skips_typography_with_the_rest_of_the_visual_block() -> None:
    state = wiz.BrandConnectState()
    state.account_kind = "influencer"
    assert state._is_skipped(wiz._TYPOGRAPHY_STEP) and state._is_skipped(wiz._PALETTE_STEP)
    brand = wiz.BrandConnectState()
    brand.account_kind = "marca"
    brand.logo_from_profile = True  # Tu brandboard skipped, Tipografía still asked
    assert brand._is_skipped(wiz._LOGO_UPLOAD_STEP) and not brand._is_skipped(wiz._TYPOGRAPHY_STEP)


def test_todo_correcto_recaps_the_typography_next_to_the_palette() -> None:
    rendered = str(wiz._step_confirm())
    assert TIPOGRAFIA in rendered
    assert rendered.index("Paleta") < rendered.index(TIPOGRAFIA)


def test_the_brandboard_column_is_capped_and_centred_not_full_width() -> None:
    assert wiz._BRANDBOARD_COLUMN_MAX == "min(100%, 58.25rem)"  # 4 × 14rem + 3 × 0.75rem
    width = str(
        wiz._step_column_width(
            BrandWizardState.step == 3,
            BrandWizardState.step == 9,
            on_typography=BrandWizardState.step == wiz._M_TYPOGRAPHY_STEP,
        )
    )
    assert "58.25rem" in width and "26rem" in width and '"100%"' not in width
    # the one typography tile fills its own narrow, centred column
    assert wiz._FONT_GRID["grid_template_columns"] == "1fr"


# -- the previews' helpers (pure) ------------------------------------------------------------


def test_font_family_css_quotes_the_name_and_falls_back() -> None:
    assert font_family_css("Montserrat") == '"Montserrat", sans-serif'
    assert font_family_css('  Playfair  "Display" ') == '"Playfair Display", sans-serif'
    assert font_family_css("") == "inherit"
    assert font_family_css('x"; } body { display: none') == '"x body display: none", sans-serif'


def test_google_fonts_url_is_built_from_the_name() -> None:
    assert google_fonts_url("") == ""
    url = google_fonts_url("Playfair Display")
    assert url.startswith("https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700")
    assert url.endswith("&display=swap")


def test_the_typography_summary_joins_what_is_declared() -> None:
    state = CreativeState()
    assert state.kit_typography_summary == ""
    state.kit_font_heading = "Montserrat"
    assert state.kit_typography_summary == "Montserrat"
    state.kit_font_body = " Inter "  # a kit saved with two faces, before there was one
    assert state.kit_typography_summary == "Montserrat · Inter"
    assert state.kit_font_heading_family == '"Montserrat", sans-serif'
    assert "Inter" in state.kit_font_body_css_url
    state.kit_font_body = "Montserrat"
    assert state.kit_typography_summary == "Montserrat"


def test_the_names_are_kit_fields_that_round_trip_through_the_form() -> None:
    state = CreativeState()
    state._apply_kit_form(KitFormVM(font_heading="Lora", font_body="Inter"))
    assert (state.kit_font_heading, state.kit_font_body) == ("Lora", "Inter")
    form = state._kit_form()
    assert (form.font_heading, form.font_body) == ("Lora", "Inter")


# -- the files ---------------------------------------------------------------------------------


@pytest.fixture
def wizard(monkeypatch: pytest.MonkeyPatch) -> BrandWizardState:
    state = BrandWizardState()

    async def stage(_self: Any, files: list[Any], folder: str) -> tuple[str, str, bytes] | None:
        return (f"uploads/t/{folder}/x_{files[0]}", str(files[0]), b"") if files else None

    monkeypatch.setattr(BrandWizardState, "_stage_logo_file", stage)
    creative = CreativeState()

    async def get_state(_self: Any, _cls: type) -> CreativeState:
        return creative

    monkeypatch.setattr(BrandWizardState, "get_state", get_state)
    state.__dict__["_test_creative"] = creative
    return state


async def test_a_dropped_font_file_fills_the_name_and_asks_google_fonts(
    wizard: BrandWizardState,
) -> None:
    """§ request 2026-10-05: "si le subes un archivo... la busca y rellena el input"."""
    fired = await BrandWizardState.handle_font_upload.fn(
        wizard, ["PlayfairDisplay-BoldItalic.woff2"], "heading"
    )
    creative = wizard.__dict__["_test_creative"]
    assert (creative.kit_font_heading, creative.kit_font_body) == (
        "Playfair Display",
        "Playfair Display",
    )
    assert "check_font_file" in str(fired)


def test_the_font_file_toast_says_whether_it_is_open_source() -> None:
    assert wiz.font_file_message("Lato", True) == (
        "Detectamos «Lato» en tu archivo. Es open source: está en Google Fonts.",
        "ok",
    )
    message, tone = wiz.font_file_message("Marca Sans", False)
    assert "No está en Google Fonts" in message and tone == "info"
    assert wiz.font_file_message("Lato", None) == ("Detectamos «Lato» en tu archivo.", "info")
    assert "Escríbelo tú" in wiz.font_file_message("", None)[0]


async def test_a_dropped_font_file_is_staged_under_its_slot(wizard: BrandWizardState) -> None:
    await BrandWizardState.handle_font_upload.fn(wizard, ["Marca-Bold.ttf"], "heading")
    assert wizard.font_files == {"heading": "uploads/t/font/heading/x_Marca-Bold.ttf"}
    assert wizard.font_file_names == {"heading": "Marca-Bold.ttf"}
    await BrandWizardState.handle_font_upload.fn(wizard, ["x.ttf"], "footnotes")  # no such slot
    assert set(wizard.font_files) == {"heading"}
    BrandWizardState.clear_font_file.fn(wizard, "heading")
    assert wizard.font_files == {}


def test_font_files_are_known_content_types_even_where_mimetypes_is_not() -> None:
    assert content_type_of("Marca.ttf") == "font/ttf"
    assert content_type_of("Marca.WOFF2") == "font/woff2"
    assert content_type_of("logo.png") == "image/png"
    assert content_type_of("mystery.qzx", "") == ""


def test_finishing_uploads_the_font_files_with_the_brandboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .test_brand_finish import FakeGate, FakeStore

    monkeypatch.setattr(brand_finish, "save_kit", lambda *_a, **_kw: None)
    key = f"uploads/{TENANT}/font/heading/ab12_Marca-Bold.ttf"
    (tmp_path / key).parent.mkdir(parents=True)
    (tmp_path / key).write_bytes(b"ttf")
    snapshot = KitSnapshot(
        form=KitFormVM(font_heading="Marca"),
        files=[StagedFile(FONT, "heading", key, "Marca-Bold.ttf", position=0)],
    )
    gate, store = FakeGate(), FakeStore()
    uploaded = brand_finish.persist_brand_kit(
        TENANT, BRAND, USER, snapshot, upload_dir=tmp_path, store=store, gate=gate
    )
    ((tenant_id, r2_key, data, content_type),) = gate.puts
    assert tenant_id == TENANT and data == b"ttf" and content_type == "font/ttf"
    assert r2_key.startswith(f"t/{TENANT}/brand/{BRAND}/font/heading/")
    assert uploaded == {key: r2_key}
    ((asset),) = store.assets
    assert (asset.kind, asset.slot, asset.content_type) == (FONT, "heading", "font/ttf")


async def test_the_snapshot_carries_the_staged_font_files(monkeypatch: pytest.MonkeyPatch) -> None:
    wizard = BrandWizardState()
    wizard.font_files = {
        "heading": f"uploads/{TENANT}/font/heading/ab12_Texto.woff2",
        "body": f"uploads/{TENANT}/font/body/ef56_Old.woff2",  # a slot that is gone
    }
    wizard.logo_versions = {"isotipo": f"uploads/{TENANT}/logo/isotipo/cd34_iso.png"}
    creative = CreativeState()
    connect = wiz.BrandConnectState()
    by_class = {BrandWizardState: wizard, CreativeState: creative, wiz.BrandConnectState: connect}

    class Holder:
        async def get_state(self, cls: type) -> Any:
            return by_class[cls]

    snapshot = await brand_finish.snapshot_states(Holder())
    kinds = {(f.kind, f.slot): f for f in snapshot.files}
    assert kinds[(FONT, "heading")].name == "Texto.woff2"
    assert (FONT, "body") not in kinds
    assert (LOGO_VERSION, "isotipo") in kinds


async def test_a_saved_font_file_swaps_its_local_key_for_the_r2_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wizard = BrandWizardState()
    local = f"uploads/{TENANT}/font/heading/ab12_Marca.ttf"
    remote = f"t/{TENANT}/brand/{BRAND}/font/heading/ef56_Marca.ttf"
    wizard.font_files = {"heading": local, "body": "untouched"}
    monkeypatch.setattr(brand_finish, "_view_for", lambda _t, r2_key, _l: f"/r2media/{r2_key}")

    class Holder:
        async def get_state(self, _cls: type) -> Any:
            return wizard

    await brand_finish._adopt_uploaded(Holder(), TENANT, {local: remote})
    assert wizard.font_files == {"heading": remote, "body": "untouched"}
    assert wizard.asset_views[remote] == f"/r2media/{remote}"


def test_reading_a_staged_logo_for_detection_skips_what_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import reflex as rx

    monkeypatch.setattr(rx, "get_upload_dir", lambda: tmp_path)
    key = f"uploads/{TENANT}/logo/imagotipo/ab12_marca.png"
    (tmp_path / key).parent.mkdir(parents=True)
    (tmp_path / key).write_bytes(b"png")
    files = wiz._read_logo_files(TENANT, [key, f"uploads/{TENANT}/logo/isotipo/missing.png"])
    assert files == [("ab12_marca.png", b"png")]
    # an R2 key without a tenant to read it as is skipped, not fatal
    assert wiz._read_logo_files(None, [f"t/{TENANT}/brand/{BRAND}/logo_version/x.png"]) == []
