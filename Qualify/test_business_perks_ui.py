"""«Lo que ofrece tu negocio» in /brand/kit and «para quién es» on each idea (0166): the
owner's perks round-trip through the editor and only their own section writes them; the
editor holds the kit's limits; each idea card says who it talks to, and an idea from
before the levels looks exactly as before; «video por partes» reads the perks too. The
database, the kit service and the save are fakes here."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.creative import brand_service
from qualify_api.creative.angle_sets import ANGLE_PROPOSED, AngleRecord, AngleView
from qualify_creative.enums import AwarenessLevel
from qualify_creative.schemas import (
    BUSINESS_PERK_MAX_CHARS,
    BUSINESS_PERKS_MAX,
    BrandKit,
    ToneAxes,
)

from . import brand_finish, creative_provider
from . import creative_wizard_pages as wiz
from . import parts_start_provider as parts_provider
from .brand_kit_editor import PERKS_SECTION, SECTIONS, BrandEditState, _editor, _summary
from .creative_state import KIT_PILL_LIMITS, CreativeState
from .creative_vm import KitFormVM, perks_count_label, perks_for_save
from .variations_vm import AUDIENCE_LABELS, audience_label, build_angle_vm

TENANT = UUID("a0000000-0000-4000-8000-0000000000c1")
BRAND = UUID("b0000000-0000-4000-8000-0000000000c1")
USER = UUID("c0000000-0000-4000-8000-0000000000c1")


_TONE = ToneAxes(formal_casual=50, sober_enthusiastic=50, technical_plain=50, brief_elaborate=50)


def _kit(**fields: Any) -> BrandKit:
    base: dict[str, Any] = {"positioning": "Comida rápida", "audience": "Vecinos"}
    return BrandKit(brand_id=BRAND, tone_axes=_TONE, **{**base, **fields})


PERKS = ("Estacionamiento gratis", "Se aceptan mascotas", "Abierto hasta las 11 de la noche")


# --- the section and its words ---------------------------------------------------------


def test_the_section_says_what_the_owner_gains_without_jargon() -> None:
    by_key = {key: (title, blurb) for key, title, _icon, blurb in SECTIONS}
    title, blurb = by_key[PERKS_SECTION]
    assert title == "Lo que ofrece tu negocio"
    assert blurb == "Tus ideas contarán por qué vale la pena visitarte o comprarte."
    _field, label, hint, example = wiz._PERKS_LIST
    words = " ".join((title, blurb, label, hint, example, wiz.PERKS_FULL_TEXT)).lower()
    for banned in ("consciencia", "awareness", "perk", "brand", "post", "funnel", "embudo"):
        assert banned not in words
    # examples for a realtor or a travel agency too, not only a restaurant
    assert hint == "Una cosa por vez. Ej.: «Pago en cuotas», «Abierto hasta las 11 de la noche»."
    assert label == "Lo que ofrece tu negocio"  # the «+»'s name only, never drawn twice


def test_the_perks_stay_out_of_todo_correcto() -> None:
    """¿Todo correcto?'s save does not write the perks, so it must not show them."""
    assert "perks" not in {spec[0] for spec in wiz._KIT_LISTS}


def test_the_section_renders_its_list_count_and_limit() -> None:
    rendered = "".join(str(c) for c in _editor(PERKS_SECTION))
    assert "Una cosa por vez." in rendered
    # the list's label is not drawn: the section title already says it
    assert "Lo que ofrece tu negocio" not in rendered
    assert "Agregar a lo que ofrece tu negocio" in rendered  # the «+»'s name
    assert "Lo que encuentran tus clientes" not in rendered
    assert "kit_perks_count_label" in rendered and "kit_perks_full" in rendered
    assert str(_summary(PERKS_SECTION))


# --- the limits, as the owner types ----------------------------------------------------


def test_the_editor_limits_are_the_kits() -> None:
    assert KIT_PILL_LIMITS["perks"] == (BUSINESS_PERKS_MAX, BUSINESS_PERK_MAX_CHARS) == (12, 80)
    assert perks_count_label(3) == "3 de 12"


def _add(state: CreativeState, value: str) -> None:
    state.kit_pill_drafts = {**state.kit_pill_drafts, "perks": value}
    state._add_kit_pill("perks")


def test_adding_stops_at_twelve_and_repeats_are_not_added() -> None:
    state = CreativeState()
    for i in range(BUSINESS_PERKS_MAX + 3):
        _add(state, f"Ventaja {i}")
    _add(state, "ventaja 0")  # a repeat, ignoring case
    items = state.kit_business_perks.splitlines()
    assert len(items) == BUSINESS_PERKS_MAX and items[0] == "Ventaja 0"
    assert CreativeState.kit_perks_full.fget(state) is True
    assert CreativeState.kit_perks_count_label.fget(state) == "12 de 12"


def test_a_pasted_long_perk_is_held_to_eighty_characters() -> None:
    state = CreativeState()
    _add(state, "x" * 120)
    assert state.kit_business_perks == "x" * BUSINESS_PERK_MAX_CHARS
    state.start_kit_pill_edit("perks", 0)
    state.kit_pill_edit_value = "y" * 100
    state.save_kit_pill_edit()
    assert state.kit_business_perks == "y" * BUSINESS_PERK_MAX_CHARS


def test_the_other_lists_keep_no_limit() -> None:
    state = CreativeState()
    for i in range(BUSINESS_PERKS_MAX + 2):
        state.kit_pill_drafts = {**state.kit_pill_drafts, "do": f"Frase {i}"}
        state._add_kit_pill("do")
    assert len(state.kit_do_examples.splitlines()) == BUSINESS_PERKS_MAX + 2


def test_what_the_owner_sees_is_what_is_saved() -> None:
    text = "\n".join(PERKS)
    assert perks_for_save(text) == PERKS
    assert perks_for_save("") == ()


# --- the round trip --------------------------------------------------------------------


class FakeKits:
    def __init__(self, stored: BrandKit | None = None) -> None:
        self.stored = stored
        self.upserts: list[BrandKit] = []

    def get_kit(self, **_kw: Any) -> BrandKit | None:
        return self.stored

    def upsert_kit(self, *, kit: BrandKit, **_kw: Any) -> None:
        self.upserts.append(kit)


@pytest.fixture
def kits(monkeypatch: pytest.MonkeyPatch) -> FakeKits:
    fake = FakeKits(_kit(business_perks=PERKS))
    monkeypatch.setattr(creative_provider, "BrandKitService", lambda: fake)
    return fake


def test_the_stored_perks_load_into_the_form_and_the_state(kits: FakeKits) -> None:
    form = creative_provider.load_kit_form(TENANT, BRAND)
    assert form is not None and form.business_perks == "\n".join(PERKS)
    state = CreativeState()
    state._apply_kit_form(form)
    assert CreativeState.kit_perks_items.fget(state) == list(PERKS)
    assert CreativeState.kit_perks_summary.fget(state) == " · ".join(PERKS)
    assert state._kit_form().business_perks == form.business_perks


def test_saving_the_perks_section_sends_the_list_and_an_empty_one_clears(kits: FakeKits) -> None:
    creative_provider.save_kit(
        TENANT, BRAND, USER, KitFormVM(), adopt_voice=False, business_perks=PERKS[:2]
    )
    creative_provider.save_kit(
        TENANT, BRAND, USER, KitFormVM(), adopt_voice=False, business_perks=()
    )
    sent, cleared = kits.upserts
    assert "business_perks" in sent.model_fields_set and sent.business_perks == PERKS[:2]
    assert "business_perks" in cleared.model_fields_set and cleared.business_perks == ()


def test_saving_another_section_keeps_the_stored_perks(kits: FakeKits) -> None:
    """Every save but «Lo que ofrece tu negocio»'s own builds a kit WITHOUT the perks, so
    the service leaves the stored list alone (`brand_service._apply_kit`)."""
    creative_provider.save_kit(
        TENANT, BRAND, USER, KitFormVM(positioning="Otro texto"), adopt_voice=False
    )
    (kit,) = kits.upserts
    assert "business_perks" not in kit.model_fields_set
    row = SimpleNamespace(business_perks=list(PERKS), ads_destination_url=None)
    brand_service._apply_kit(row, kit)  # type: ignore[arg-type]
    assert row.business_perks == list(PERKS) and row.positioning == "Otro texto"


def _holder(creative: CreativeState) -> Any:
    by_class = {
        CreativeState: creative,
        wiz.BrandWizardState: wiz.BrandWizardState(),
        wiz.BrandConnectState: wiz.BrandConnectState(),
    }

    class Holder:
        async def get_state(self, cls: type) -> Any:
            return by_class[cls]

    return Holder()


def test_only_the_perks_save_puts_them_in_the_snapshot() -> None:
    creative = CreativeState()
    creative.kit_business_perks = "\n".join(PERKS)
    other = asyncio.run(brand_finish.snapshot_states(_holder(creative)))
    own = asyncio.run(brand_finish.snapshot_states(_holder(creative), with_perks=True))
    assert other.business_perks is None
    assert own.business_perks == PERKS


def test_persist_hands_the_snapshots_perks_to_the_kit_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(
        brand_finish, "save_kit", lambda *_a, **kw: calls.append(kw.get("business_perks"))
    )

    class Store:
        def replace_assets(self, **_kw: Any) -> None:
            pass

        def save_details(self, **_kw: Any) -> None:
            pass

    for perks in (None, PERKS):
        brand_finish.persist_brand_kit(
            TENANT,
            BRAND,
            USER,
            brand_finish.KitSnapshot(form=KitFormVM(), business_perks=perks),
            upload_dir=None,  # type: ignore[arg-type]
            store=Store(),  # type: ignore[arg-type]
        )
    assert calls == [None, PERKS]


@pytest.mark.parametrize(("section", "expected"), [(PERKS_SECTION, True), ("marca", False)])
def test_the_editor_saves_the_perks_only_from_their_section(
    monkeypatch: pytest.MonkeyPatch, section: str, expected: bool
) -> None:
    creative = CreativeState()
    connect = wiz.BrandConnectState()
    flags: list[bool] = []

    class Editor:
        open_section = section
        _before: dict = {}

        async def __aenter__(self) -> Editor:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get_state(self, cls: type) -> Any:
            return creative if cls is CreativeState else connect

    async def save(_state: Any, *, with_perks: bool = False) -> bool:
        flags.append(with_perks)
        return True

    monkeypatch.setattr(brand_finish, "save_brand_kit", save)

    async def run() -> None:
        async for _ in BrandEditState.save_section.fn(Editor(), {}):
            pass

    asyncio.run(run())
    assert flags == [expected]


# --- who each idea talks to ------------------------------------------------------------


def _view(level: AwarenessLevel | None) -> AngleView:
    record = AngleRecord(
        id=uuid4(),
        set_id=uuid4(),
        position=1,
        title="Mesa de cafetería",
        scene="sobre una tabla",
        composition="plano medio",
        hook="Hoy se antoja",
        cta="Pide ya",
        rationale="vende",
        status=ANGLE_PROPOSED,
        awareness_level=level,
    )
    return AngleView(angle=record)


def test_each_level_has_its_plain_label() -> None:
    assert AUDIENCE_LABELS == {
        AwarenessLevel.UNAWARE: "Para quien aún no piensa en ti",
        AwarenessLevel.PROBLEM_AWARE: "Para quien ya busca algo así",
        AwarenessLevel.SOLUTION_AWARE: "Para quien está comparando opciones",
        AwarenessLevel.PRODUCT_AWARE: "Para quien te conoce pero no se decide",
        AwarenessLevel.MOST_AWARE: "Para quien está listo para comprar",
    }
    for level in AwarenessLevel:
        label = build_angle_vm(_view(level), lambda _k: "").audience_label
        assert label == AUDIENCE_LABELS[level]
        assert "consciencia" not in label.lower()


def test_an_idea_without_a_level_has_no_tag() -> None:
    assert audience_label(None) == ""
    assert build_angle_vm(_view(None), lambda _k: "").audience_label == ""


def test_the_card_shows_the_tag_only_when_there_is_one() -> None:
    from . import variations_view

    rendered = str(variations_view._angle_card(variations_view.VariationsState.angles[0]))
    assert "audience_label" in rendered


# --- «video por partes» ----------------------------------------------------------------


def test_the_parts_proposal_reads_the_kits_perks(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative import brand_context, brand_names, composition

    kit = _kit(positioning="Shawarma", business_perks=PERKS)
    monkeypatch.setattr(brand_names, "DbBrandNames", lambda: lambda **_kw: "Bianki")
    monkeypatch.setattr(
        composition, "DbBrandKitReader", lambda: SimpleNamespace(kit=lambda **_kw: kit)
    )
    monkeypatch.setattr(
        brand_context,
        "DbBrandContextReader",
        lambda: SimpleNamespace(
            context=lambda **_kw: SimpleNamespace(sector="Comida", location="Cúcuta")
        ),
    )
    brand = parts_provider.brand_facts(TENANT, BRAND)
    assert brand.perks == PERKS and brand.name == "Bianki"


def test_the_parts_proposal_without_a_kit_has_no_perks(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative import brand_context, brand_names, composition

    monkeypatch.setattr(brand_names, "DbBrandNames", lambda: lambda **_kw: "Bianki")
    monkeypatch.setattr(
        composition, "DbBrandKitReader", lambda: SimpleNamespace(kit=lambda **_kw: None)
    )
    monkeypatch.setattr(
        brand_context, "DbBrandContextReader", lambda: SimpleNamespace(context=lambda **_kw: None)
    )
    assert parts_provider.brand_facts(TENANT, BRAND).perks == ()
