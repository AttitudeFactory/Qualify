"""`qualify_creative.angles` (ticket 24803289), offline: the presets, the prompt the
angles call carries (the price as exact data, or its explicit absence), the strict tool,
the bounded de-duplicating parse, the distinctness check, the price guard and the brief
one angle becomes — one draft of the existing pipeline with the catalog's price in both
the highlights and `price_line`."""

from __future__ import annotations

from uuid import uuid4

import pytest

from qualify_creative.angles import (
    ANGLES_TOOL,
    DEFAULT_ANGLE_COUNT,
    MAX_ANGLE_COUNT,
    MIN_ANGLE_COUNT,
    PRESETS,
    PRICE_HIGHLIGHT,
    AngleBrand,
    AngleProduct,
    CreativeAngle,
    UnknownPreset,
    angle_brief,
    angles_tool,
    angles_user_prompt,
    distinct_problems,
    parse_angles,
    preset_by_key,
    preset_problem,
    price_conflicts,
    price_mentions,
)
from qualify_creative.enums import AdImageMode, ContentFormat, ContentKind, ImageRoute

BRAND_ID = uuid4()
PRODUCT = AngleProduct(
    product_id=uuid4(),
    name="Shawarma mixto",
    description="Pollo y carne, salsa de ajo, pan árabe recién hecho.",
    category="Plato",
    tags=("shawarma", "mixto"),
    price_label="$18.000",
    photo_keys=("uploads/t/p1.jpg", "uploads/t/p2.jpg"),
)
NO_PRICE = AngleProduct(
    product_id=uuid4(), name="Helado de yogurt", photo_keys=("uploads/t/h.jpg",)
)
BRAND = AngleBrand(name="Bianki", sector="shawarma", location="Bogotá", audience="oficinistas")


def _angle(i: int, scene: str, title: str | None = None, **extra: str) -> dict[str, str]:
    return {
        "title": title or f"Ángulo {i}",
        "scene": scene,
        "composition": extra.get("composition", "plano medio, producto a la derecha"),
        "hook": extra.get("hook", f"Gancho {i}"),
        "cta": extra.get("cta", "Pide ya"),
        "rationale": extra.get("rationale", "porque sí"),
    }


SCENES = [
    "sobre una tabla de madera en una mesa de cafetería con luz de ventana",
    "en la mano de alguien frente a un local de barrio al atardecer",
    "sobre una roca junto a un río con luz dura de mediodía",
    "en un escritorio de oficina entre un portátil y un café",
    "sobre papel kraft en un picnic en el césped con sombra de árbol",
    "en la barra del local con la plancha encendida al fondo",
    "en una bandeja de reparto dentro de una moto con casco al lado",
    "sobre mármol blanco con cubiertos dorados y una copa",
    "en el asiento de un carro con luces de ciudad desenfocadas",
    "sobre una toalla de playa con arena y mar al fondo",
    "en una mesa de reunión con cuatro cajas abiertas",
    "flotando sobre fondo negro con humo y luz lateral",
]


def payload(n: int = DEFAULT_ANGLE_COUNT) -> dict[str, list[dict[str, str]]]:
    return {"angles": [_angle(i + 1, SCENES[i]) for i in range(n)]}


# -- presets -------------------------------------------------------------------------------


def test_presets_cover_both_engines_and_only_known_formats() -> None:
    engines = {p.engine for p in PRESETS}
    assert engines == {"ad_image", "template"}
    for preset in PRESETS:
        assert preset.format in preset.kind.formats
        if preset.engine == "template":
            assert preset.template_id and preset.needs_render_service
        else:
            assert preset.template_id is None and not preset.needs_render_service
    assert preset_by_key("escena_producto").kind is ContentKind.STATIC_FLYER
    with pytest.raises(UnknownPreset):
        preset_by_key("nope")


# -- the prompt and the tool ---------------------------------------------------------------


def test_the_prompt_names_the_price_as_exact_catalog_data() -> None:
    text = angles_user_prompt(PRODUCT, BRAND, PRESETS[0])
    assert "$18.000" in text and "dato exacto del catálogo" in text
    assert "Shawarma mixto" in text and "Bianki" in text and "shawarma" in text
    assert ANGLES_TOOL in text and "10 ángulos" in text


def test_without_a_catalog_price_the_prompt_forbids_any_figure() -> None:
    text = angles_user_prompt(NO_PRICE, BRAND, PRESETS[0])
    assert "NO HAY" in text and "No menciones ningún precio" in text
    assert "$" not in text


def test_a_top_up_prompt_lists_the_angles_to_avoid() -> None:
    existing = parse_angles(payload(3))
    text = angles_user_prompt(PRODUCT, BRAND, PRESETS[0], count=7, avoid=existing)
    assert "NO los repitas" in text and SCENES[2] in text and "Propón 7 ángulos" in text


def test_the_tool_is_strict_and_asks_for_exactly_n_angles() -> None:
    tool = angles_tool(10)
    assert tool["strict"] is True and tool["name"] == ANGLES_TOOL
    schema = tool["input_schema"]
    assert schema["additionalProperties"] is False and schema["required"] == ["angles"]
    items = schema["properties"]["angles"]
    # the count is asked for in words: structured outputs reject array bounds other than
    # minItems 0/1 (defect 11), and `parse_angles` enforces the count on the answer
    assert "minItems" not in items and "maxItems" not in items
    assert "10" in tool["description"] and "maxItems: 10" in items["description"]
    row = items["items"]
    assert row["additionalProperties"] is False
    assert set(row["required"]) == {"title", "scene", "composition", "hook", "cta", "rationale"}


def _unsupported(node: object, path: str = "") -> list[str]:
    """Every keyword structured outputs reject, anywhere in a schema."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in {"minLength", "maxLength", "minimum", "maximum", "multipleOf", "maxItems"}:
                found.append(f"{path}/{key}")
            if key == "minItems" and value not in (0, 1):
                found.append(f"{path}/minItems={value}")
            if key == "additionalProperties" and value is not False:
                found.append(f"{path}/additionalProperties={value}")
            found.extend(_unsupported(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            found.extend(_unsupported(item, f"{path}/{i}"))
    return found


@pytest.mark.parametrize("count", [MIN_ANGLE_COUNT, DEFAULT_ANGLE_COUNT, MAX_ANGLE_COUNT])
def test_the_tool_schema_carries_nothing_structured_outputs_reject(count: int) -> None:
    schema = angles_tool(count)["input_schema"]
    assert _unsupported(schema) == []
    # the shape the SDK's own transform produces: sending it as is changes nothing
    anthropic = pytest.importorskip("anthropic")
    assert anthropic.transform_schema(schema) == schema


# -- parsing ----------------------------------------------------------------------------------


def test_parse_keeps_order_bounds_fields_and_numbers_positions() -> None:
    raw = payload(10)
    raw["angles"][0]["title"] = "  Mesa   de   cafetería  " + "x" * 100
    raw["angles"][0]["hook"] = "h" * 500
    angles = parse_angles(raw)
    assert len(angles) == 10
    assert [a.position for a in angles] == list(range(1, 11))
    assert angles[0].title.startswith("Mesa de cafetería") and len(angles[0].title) <= 60
    assert len(angles[0].hook) <= 80


def test_parse_drops_duplicates_sloppy_rows_and_caps_at_count() -> None:
    raw = payload(10)
    raw["angles"].insert(1, dict(raw["angles"][0]))  # the same scene again
    raw["angles"].insert(3, {"title": "sin escena"})  # no scene at all
    raw["angles"].insert(4, "not a row")  # type: ignore[arg-type]
    raw["angles"].append(_angle(99, SCENES[10]))
    angles = parse_angles(raw, count=10)
    assert len(angles) == 10
    assert len({a.scene for a in angles}) == 10
    assert parse_angles({"angles": "nope"}) == ()
    assert parse_angles(None) == ()


def test_parse_against_existing_angles_continues_the_numbering() -> None:
    existing = parse_angles(payload(8))
    more = parse_angles(
        {
            "angles": [
                _angle(1, SCENES[0], title="Repetido"),
                _angle(2, SCENES[8], title="Nuevo A"),
                _angle(3, SCENES[9], title="Nuevo B"),
                _angle(4, SCENES[10], title="Nuevo C"),
            ]
        },
        count=10,
        existing=existing,
    )
    # the first repeats an existing scene and is dropped; two complete the ten; the
    # fourth is past the count
    assert [a.position for a in more] == [9, 10]
    assert more[0].scene == SCENES[8]


def test_distinct_problems_names_the_pair_and_the_shortfall() -> None:
    angles = parse_angles(payload(10))
    assert distinct_problems(angles, minimum=10) == ()
    assert "only 8" in distinct_problems(angles[:8], minimum=10)[0]
    twin = angles[1].model_copy(update={"scene": angles[0].scene, "position": 11})
    problems = distinct_problems((*angles, twin), minimum=10)
    assert any("same scene" in p for p in problems)


def test_scene_prompt_joins_scene_and_composition_within_the_cap() -> None:
    angle = CreativeAngle(position=1, title="t", scene="s" * 400, composition="c" * 200)
    assert angle.scene_prompt.startswith("s" * 400 + ". Composición: ")
    assert len(angle.scene_prompt) <= 600


# -- the price guard ------------------------------------------------------------------------


def test_price_mentions_find_money_tokens_in_spanish_copy() -> None:
    assert price_mentions("Hoy a $18.000, o 2 por 30.000 pesos") == ("$18.000", "30.000 pesos")
    assert price_mentions("Sin cifras aquí") == ()


def test_price_conflicts_flag_only_figures_other_than_the_catalogs() -> None:
    texts = ("Shawarma mixto a $18.000", "Llévalo hoy por $ 18.000 — antes $22.000")
    assert price_conflicts(texts, "$18.000") == ("$22.000",)
    assert price_conflicts(("A USD 18,000 todo el día",), "$18.000") == ()
    assert price_conflicts(("A 18.5 USD",), "USD 18.50") == ()


def test_without_a_catalog_price_every_figure_is_a_conflict() -> None:
    assert price_conflicts(("Solo $9.900 hoy",), "") == ("$9.900",)
    assert price_conflicts(("Pide el tuyo",), "") == ()


# -- one angle → one brief ----------------------------------------------------------------


def test_the_brief_carries_the_catalog_price_twice_and_the_scene_once() -> None:
    angle = parse_angles(payload(1))[0]
    brief = angle_brief(
        angle=angle, preset=preset_by_key("escena_producto"), product=PRODUCT, brand_id=BRAND_ID
    )
    assert brief.kind is ContentKind.STATIC_FLYER and brief.format is ContentFormat.FEED_4_5
    assert brief.variants_requested == 1
    assert brief.media.product_keys == PRODUCT.photo_keys
    assert brief.media.scene_prompt == angle.scene_prompt
    assert brief.media.ad_mode is AdImageMode.PRODUCT
    assert brief.media.price_line == "$18.000"
    assert (PRICE_HIGHLIGHT, "$18.000") in brief.constraints.highlights
    assert "$18.000" in brief.constraints.must_mention
    assert brief.image_route is ImageRoute.FROM_UPLOAD
    assert brief.source_media_key == PRODUCT.photo_keys[0]
    assert brief.product_ref == "Shawarma mixto"
    assert brief.topic.startswith("Shawarma mixto — Ángulo 1")


def test_without_a_price_nothing_is_printed_and_nothing_is_demanded() -> None:
    angle = parse_angles(payload(1))[0]
    brief = angle_brief(
        angle=angle, preset=preset_by_key("historia_vertical"), product=NO_PRICE, brand_id=BRAND_ID
    )
    assert brief.format is ContentFormat.STORY_9_16
    assert brief.media.price_line == ""
    assert brief.constraints.highlights == ()
    assert brief.constraints.must_mention == ()


def test_the_template_preset_pins_the_template_and_keeps_the_scene() -> None:
    angle = parse_angles(payload(1))[0]
    brief = angle_brief(
        angle=angle, preset=preset_by_key("plantilla_promo"), product=PRODUCT, brand_id=BRAND_ID
    )
    assert brief.kind is ContentKind.TEMPLATE
    assert brief.media.template_id == "promo_producto"
    assert brief.media.ad_mode is None
    assert brief.media.scene_prompt == angle.scene_prompt  # the validator allows it
    assert brief.media.price_line == "$18.000"


def test_a_scene_prompt_is_refused_on_kinds_that_have_none() -> None:
    from pydantic import ValidationError

    from qualify_creative.schemas import ContentBrief, MediaInputs

    with pytest.raises(ValidationError):
        ContentBrief(
            brand_id=BRAND_ID,
            objective="sale",
            topic="x",
            kind=ContentKind.CREATOR_SCRIPT,
            format=ContentFormat.REELS_9_16,
            media=MediaInputs(scene_prompt="una mesa"),
        )


# -- review findings (block 2) -------------------------------------------------------------


def test_positions_never_pass_the_cap_however_many_are_asked_for() -> None:
    # R1: 8 kept + 10 asked would number angles up to 18 and raise; the set stops at 12
    kept = parse_angles(payload(8))
    scenes = [
        "cocina industrial acero brillante vapor",
        "terraza azotea atardecer naranja ciudad",
        "biblioteca antigua estanterías madera oscura",
        "estadio graderías hinchas camisetas",
        "bosque niebla pinos musgo",
        "aeropuerto maleta ventanal pista",
        "taller mecánico herramientas grasa",
        "piscina tumbona flotador verano",
        "museo galería cuadros pedestal",
        "tren vagón ventanilla paisaje",
    ]
    rows = [_angle(i, scene, title=f"Nuevo {i}") for i, scene in enumerate(scenes)]
    more = parse_angles({"angles": rows}, count=len(kept) + 10, existing=kept)
    assert len(kept) + len(more) == MAX_ANGLE_COUNT
    assert max(a.position for a in more) == MAX_ANGLE_COUNT


def test_a_template_preset_names_a_product_without_photos_before_anything_is_paid() -> None:
    # R2: ContentBrief refuses a template without a real photo — say so up front
    bare = AngleProduct(product_id=uuid4(), name="Helado", price_label="$5.000")
    problem = preset_problem(preset_by_key("plantilla_promo"), bare)
    assert problem is not None and "foto" in problem
    assert preset_problem(preset_by_key("plantilla_promo"), PRODUCT) is None
    assert preset_problem(preset_by_key("escena_producto"), bare) is None  # a scene can do


@pytest.mark.parametrize(
    "copy", ["Set de 6 copas por $25.000", "2 pendientes de plata", "3 arsenales de sabor"]
)
def test_a_word_starting_like_a_currency_is_not_a_price(copy: str) -> None:
    # R3: "6 copas" is not "6 COP"; only the real figure is a mention
    assert all(not m.lower().endswith(("cop", "pen", "ars")) for m in price_mentions(copy))
    assert price_conflicts([copy], "$25.000") == ()


def test_the_expected_amount_is_the_labels_money_token() -> None:
    # R5: "2x $10" is a ten, not a two
    assert price_conflicts(["Llévalos por $10"], "2x $10") == ()
    assert price_conflicts(["Llévalos por $2"], "2x $10") == ("$2",)


def test_a_label_too_long_for_the_price_line_is_not_printed_cut() -> None:
    # R4: whole or not at all — the copy still states it through the highlight
    label = "Bs. 1.250.000,00 c/u (precio de lanzamiento)"
    assert len(label) > 40
    product = AngleProduct(
        product_id=uuid4(), name="Mesa", price_label=label, photo_keys=("uploads/t/m.jpg",)
    )
    brief = angle_brief(
        angle=parse_angles(payload(1))[0],
        preset=preset_by_key("escena_producto"),
        product=product,
        brand_id=BRAND_ID,
    )
    assert brief.media.price_line == ""
    assert (PRICE_HIGHLIGHT, label) in brief.constraints.highlights


def test_extra_highlights_are_cleaned_capped_and_never_a_second_price() -> None:
    # R6: blank or over-long facts are skipped, «precio» stays the catalog's, at most 12
    extra = [("  ", "x"), ("Precio", "$9.990"), ("k" * 41, "v"), ("Envío", "  gratis  ")]
    extra += [(f"Dato {i}", f"valor {i}") for i in range(20)]
    brief = angle_brief(
        angle=parse_angles(payload(1))[0],
        preset=preset_by_key("escena_producto"),
        product=PRODUCT,
        brand_id=BRAND_ID,
        extra_highlights=extra,
    )
    highlights = brief.constraints.highlights
    assert len(highlights) == 12
    assert [fact for name, fact in highlights if name.casefold() == "precio"] == ["$18.000"]
    assert ("Envío", "gratis") in highlights
