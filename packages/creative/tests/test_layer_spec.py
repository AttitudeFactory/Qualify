"""m-25017283: `LayerSpec`, the contract between the layer stage and the Remotion
composition, enforces the closed catalog (docs/catalogo-disenos-imagen-carrusel.md)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from qualify_creative.layer_spec import (
    LAYOUT_VERSION,
    LayerSpec,
    catalog,
    free_text_problems,
    json_schema,
)
from qualify_creative.layer_spec.schema import SCHEMA_FILE

PHOTO = {
    "subject_box": [0.3, 0.1, 0.8, 0.6],
    "logo_in_photo": False,
    "base_has_invented_text": False,
}


def _spec(**fields):  # noqa: ANN003, ANN202
    return LayerSpec.model_validate(fields)


def test_the_committed_json_schema_is_the_model_s() -> None:
    """The file `packages/render` reads is regenerated with `export_json_schema`."""
    import qualify_creative.layer_spec.schema as module

    committed = json.loads(Path(module.__file__).with_name(SCHEMA_FILE).read_text("utf-8"))
    assert committed == json.loads(json.dumps(json_schema()))


def test_the_catalog_has_the_seven_layouts() -> None:
    assert set(catalog()["layouts"]) == {
        "photo_only",
        "plate",
        "scrim",
        "band",
        "info_card",
        "brand_fill",
        "highlight_circle",
    }
    assert LAYOUT_VERSION == 1


@pytest.mark.parametrize(
    "fields",
    [
        {"layout_id": "photo_only", "format": "4:5", "photo": PHOTO},
        {
            "layout_id": "plate",
            "format": "4:5",
            "photo": PHOTO,
            "anchor": "top_left",
            "container_color": "surface",
            "accent_word": 1,
            "title": "Tu shawarma, recién hecho",
            "subtitle": "Salsa de la casa",
            "call_phrase": "Pídelo por WhatsApp",
            "price_ref": {"product_id": str(uuid4())},
        },
        {
            "layout_id": "scrim",
            "format": "9:16",
            "photo": PHOTO,
            "anchor": "bottom",
            "title": "Helado de yogur con fresas",
        },
        {
            "layout_id": "band",
            "format": "1:1",
            "photo": PHOTO,
            "anchor": "bottom",
            "title": "Tu combo de mediodía",
            "call_phrase": "Pídelo por WhatsApp",
        },
        {
            "layout_id": "info_card",
            "format": "4:5",
            "title": "Ven por tu shawarma",
            "info_blocks": [
                {"kind": "location", "label": "Dónde estamos", "value": "C.C. Las Palmas, local 5"},
                {"kind": "payment", "label": "Formas de pago", "value": "Efectivo · Nequi"},
            ],
        },
        {
            "layout_id": "brand_fill",
            "format": "4:5",
            "container_color": "accent",
            "title": "Este lunes festivo también abrimos",
            "info_blocks": [{"kind": "hours", "label": "Horario", "value": "Lunes de 11 a 9"}],
        },
        {
            "layout_id": "highlight_circle",
            "format": "9:16",
            "highlight_content": {"kind": "word", "word": "Menú"},
        },
        {
            "layout_id": "brand_fill",
            "format": "4:5",
            "title": "Te esperamos hoy",
            "carousel": {"role": "closing", "index": 4, "count": 5},
        },
    ],
)
def test_catalog_conformant_specs_pass(fields) -> None:  # noqa: ANN001
    spec = _spec(**fields)
    assert spec.spec_sha256() == _spec(**fields).spec_sha256()  # stable fingerprint


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (
            {
                "layout_id": "plate",
                "format": "4:5",
                "photo": PHOTO,
                "anchor": "top_left",
                "title": "x" * 29,
            },
            "at most 28",
        ),
        (
            {
                "layout_id": "plate",
                "format": "4:5",
                "photo": PHOTO,
                "anchor": "top",
                "title": "Tu shawarma",
            },
            "takes no anchor top",
        ),
        (
            {
                "layout_id": "scrim",
                "format": "4:5",
                "photo": PHOTO,
                "anchor": "top",
                "title": "Helado",
                "price_ref": {"product_id": str(uuid4())},
            },
            "prints no price",
        ),
        (
            {
                "layout_id": "scrim",
                "format": "4:5",
                "photo": PHOTO,
                "anchor": "top",
                "title": "Helado de yogur",
                "accent_word": 0,
            },
            "takes no accent_word",
        ),
        (
            {
                "layout_id": "scrim",
                "format": "1:1",
                "photo": PHOTO,
                "anchor": "top",
                "title": "Helado",
                "call_phrase": "Ven hoy",
            },
            "has no call_phrase",
        ),
        (
            {
                "layout_id": "band",
                "format": "4:5",
                "photo": PHOTO,
                "anchor": "bottom",
                "title": "Ubicación",
            },
            "is a label",
        ),
        (
            {
                "layout_id": "band",
                "format": "4:5",
                "photo": PHOTO,
                "anchor": "bottom",
                "title": "Combo a $25.000",
            },
            "currency",
        ),
        (
            {
                "layout_id": "band",
                "format": "4:5",
                "photo": PHOTO,
                "anchor": "bottom",
                "title": "Abrimos a las 9 a. m.",
            },
            "hour",
        ),
        (
            {
                "layout_id": "band",
                "format": "1:1",
                "photo": PHOTO,
                "anchor": "bottom",
                "title": "Tu combo",
                "subtitle": "Shawarma y bebida",
                "call_phrase": "Pídelo",
            },
            "only without a subtitle",
        ),
        (
            {"layout_id": "plate", "format": "4:5", "anchor": "top_left", "title": "Tu shawarma"},
            "needs what was seen",
        ),
        (
            {
                "layout_id": "brand_fill",
                "format": "4:5",
                "title": "Te esperamos",
                "info_blocks": [{"kind": "payment", "label": "Formas de pago", "value": "Nequi"}],
            },
            "takes no payment block",
        ),
        (
            {
                "layout_id": "info_card",
                "format": "4:5",
                "title": "Ven",
                "info_blocks": [{"kind": "location", "label": "Ubicación", "value": "Calle 5"}],
            },
            "label of a location block",
        ),
        (
            {
                "layout_id": "plate",
                "format": "4:5",
                "photo": PHOTO,
                "anchor": "top_left",
                "title": "Tu shawarma",
                "carousel": {"role": "closing", "index": 2, "count": 3},
            },
            "closing slide takes",
        ),
        (
            {
                "layout_id": "highlight_circle",
                "format": "4:5",
                "highlight_content": {"kind": "icon", "icon_id": "clock"},
            },
            "has no 4:5",
        ),
        (
            {
                "layout_id": "photo_only",
                "format": "4:5",
                "photo": {**PHOTO, "subject_box": [0.31, 0.1, 0.8, 0.6]},
            },
            "rounded to 0.05",
        ),
    ],
)
def test_specs_outside_the_catalog_are_refused(fields, message: str) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError) as raised:
        _spec(**fields)
    assert message in str(raised.value)


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Llámanos al 3001234567", "phone number"),
        ("Solo 25.000", "price figure"),
        ("Desde las 21:00", "hour"),
        ("Tu shawarma 🔥", "emoji"),
        ("#shawarma", "hashtag"),
        ("OFERTA de hoy", "sustained capitals"),
    ],
)
def test_no_datum_travels_in_free_text(text: str, problem: str) -> None:
    assert problem in free_text_problems(text)


def test_a_promotion_count_is_not_a_price() -> None:
    assert free_text_problems("2x1 en shawarmas este martes") == []


@pytest.mark.parametrize(
    "text",
    [
        "Solo 15 mil",
        "15mil el combo",
        "A 20bs",
        "Por 5usd",
        "12 lucas",
        "20 soles",
        "USD 5",
        "Combo a $25.000",
        "Solo 25.000",
        "Ahora 10,50",
        "Por 15k",
        "Desde 2500",
    ],
)
def test_a_price_in_any_spelling_is_refused(text: str) -> None:
    assert {"currency", "price figure"} & set(free_text_problems(text)), text


@pytest.mark.parametrize(
    "text",
    [
        "Novedades 2026",
        "Desde 1998 contigo",
        "100% natural",
        "500 g de pollo",
        "2x1 en shawarmas",
        "3x2 este martes",
        "Mil sabores en tu mesa",
        "Pesos pesados del sabor",
        "1 litro de limonada",
        # written-out numbers are out of a rule's reach: left to the prompt
        "Por veinte mil",
    ],
)
def test_years_units_and_claims_are_not_prices(text: str) -> None:
    assert not {"currency", "price figure"} & set(free_text_problems(text)), text


def test_brand_fill_square_info_value_follows_the_doc_limit() -> None:
    """60 characters in 1:1: the general value limit (catalog §1.5); 44 is `info_card`'s
    alone (§2.5). Agreed with m-25017285's manifest."""
    fields = {
        "layout_id": "brand_fill",
        "format": "1:1",
        "title": "Te esperamos",
        "info_blocks": [{"kind": "hours", "label": "Horario", "value": "x" * 60}],
    }
    _spec(**fields)
    fields["info_blocks"][0]["value"] = "x" * 61
    with pytest.raises(ValidationError):
        _spec(**fields)
