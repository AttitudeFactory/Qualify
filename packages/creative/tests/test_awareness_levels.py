"""Awareness levels (Eugene Schwartz) and the owner's business perks, offline: the perks'
normalization on the kit, the level plan an angle set is spread with, the angles tool
and prompt, `parse_angles` with and without a level, the brief an angle becomes (its
objective and, at `unaware`, no price), and the copy prompt — byte-identical to `main`
when a kit has no perks and a brief no level, carrying both when present.

`MAIN_DIGEST` was taken on 2026-11-13 by running `_corpus()` from this very file against
origin/main's `packages/creative/src` (`9129e688`, `git archive`; first taken on
`a6667370`): only names and kwargs `main` already has are used, so the function runs
unchanged on both trees."""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

import pytest

from qualify_creative.angles import (
    PRESETS,
    PRICE_HIGHLIGHT,
    AngleBrand,
    AngleProduct,
    CreativeAngle,
    angle_brief,
    angles_system_prompt,
    angles_tool,
    angles_user_prompt,
    awareness_level_or_none,
    level_plan,
    parse_angles,
)
from qualify_creative.brand import render_prompt
from qualify_creative.enums import (
    AwarenessLevel,
    BriefObjective,
    ContentKind,
    GenerationTask,
    ImageRoute,
    VoiceProfileStatus,
)
from qualify_creative.schemas import (
    BUSINESS_PERK_MAX_CHARS,
    BUSINESS_PERKS_MAX,
    BrandContext,
    BrandKit,
    BrandVoiceProfile,
    ContentBrief,
    HashtagPolicy,
    LengthTargets,
    MediaInputs,
    ToneAxes,
    normalize_business_perks,
)

#: Re-baselined (from origin/main's code) whenever the copy prompt changes on purpose.
MAIN_DIGEST = "1d1e2854cc5b3932139eadd500c84a41560ce6df4c27874f3b6792aefb4213c2"

BRAND_ID = UUID("a3b1c2d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")
PERKS = (
    "Parqueadero gratis",
    "Pet friendly",
    "Mesas para compartir",
    "Abierto hasta las 11 p. m.",
    "Combo con el postre de la heladería vecina",
)
PRODUCT = AngleProduct(
    product_id=uuid4(),
    name="Shawarma mixto",
    description="Pollo y carne, 350 g, salsa de ajo, pan árabe recién hecho.",
    category="Plato",
    price_label="$18.000",
    photo_keys=("uploads/t/p1.jpg",),
)
BRAND = AngleBrand(name="Bianki", sector="shawarma", location="Bogotá")


def _kit(**overrides: object) -> BrandKit:
    base: dict[str, object] = {
        "brand_id": BRAND_ID,
        "positioning": "Shawarma de patio de comidas",
        "audience": "Familias y oficinistas",
        "tone_axes": ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        ),
        "do_examples": ("Hoy el pan salió recién hecho",),
        "banned_words": ("barato",),
        "hashtag_policy": HashtagPolicy(minimum=1, maximum=5, always=("bianki",)),
        "length_targets": LengthTargets(caption_min_chars=20, caption_max_chars=400),
        "cta_patterns": ("Escríbenos",),
    }
    base.update(overrides)
    return BrandKit(**base)  # type: ignore[arg-type]


def _voice() -> BrandVoiceProfile:
    return BrandVoiceProfile(
        brand_id=BRAND_ID,
        version=1,
        status=VoiceProfileStatus.ACTIVE,
        tone_axes=ToneAxes(
            formal_casual=65, sober_enthusiastic=55, technical_plain=85, brief_elaborate=35
        ),
    )


def _brief(**overrides: object) -> ContentBrief:
    base: dict[str, object] = {
        "brand_id": BRAND_ID,
        "objective": BriefObjective.SALE,
        "topic": "Shawarma mixto — Mesa del patio",
        "image_route": ImageRoute.TEMPLATE_ONLY,
    }
    base.update(overrides)
    return ContentBrief(**base)  # type: ignore[arg-type]


def _corpus() -> str:
    """Every prompt of a kit without perks and briefs without a level, across kinds, with
    and without the business context, on compiler 0 and on compiler 5 with and without a
    product (m-24985141) — the bytes `main` renders."""
    context = BrandContext(sector="Comida", location="Bogotá, CO", hashtags=("shawarma",))
    out: list[str] = []
    for kind in (ContentKind.STATIC_FLYER, ContentKind.CLIP, ContentKind.CREATOR_SCRIPT):
        for ctx in (None, context):
            for objective in BriefObjective:
                for compiler, product_ref in ((0, None), (5, None), (5, "Shawarma mixto")):
                    brief = _brief(
                        kind=kind,
                        objective=objective,
                        product_ref=product_ref,
                        media=MediaInputs(prompt_compiler_version=compiler),
                    )
                    rendered = render_prompt(
                        kit=_kit(),
                        voice=_voice(),
                        brief=brief,
                        task=GenerationTask.COPY,
                        context=ctx,
                        variant=0,
                    )
                    out.append(rendered.stable_prefix + "\x00" + rendered.volatile_suffix)
    return "\x01".join(out)


# -- perks ---------------------------------------------------------------------------------


def test_perks_are_trimmed_deduplicated_capped_and_kept_in_order() -> None:
    raw = ["  Parqueadero   gratis ", "", "PARQUEADERO GRATIS", "Pet friendly", "   ", "x" * 200]
    assert normalize_business_perks(raw) == (
        "Parqueadero gratis",
        "Pet friendly",
        "x" * BUSINESS_PERK_MAX_CHARS,
    )
    many = [f"Ventaja {i}" for i in range(30)]
    assert normalize_business_perks(many) == tuple(many[:BUSINESS_PERKS_MAX])
    assert normalize_business_perks(None) == ()
    assert normalize_business_perks("Mesas\n\nMesas\nWifi") == ("Mesas", "Wifi")


def test_the_kit_normalizes_its_perks_and_is_idempotent() -> None:
    kit = _kit(business_perks=[" Pet friendly", "pet FRIENDLY", "Mesas "])
    assert kit.business_perks == ("Pet friendly", "Mesas")
    again = BrandKit.model_validate(kit.model_dump())
    assert again.business_perks == kit.business_perks
    assert _kit().business_perks == ()


# -- the level plan ------------------------------------------------------------------------


def test_ten_angles_are_two_per_level() -> None:
    assert level_plan(10) == tuple((level, 2) for level in AwarenessLevel)


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (3, (1, 1, 1, 0, 0)),
        (5, (1, 1, 1, 1, 1)),
        (7, (2, 2, 1, 1, 1)),
        (12, (3, 3, 2, 2, 2)),
    ],
)
def test_other_counts_are_as_even_as_possible_from_unaware(
    count: int, expected: tuple[int, ...]
) -> None:
    plan = dict(level_plan(count))
    assert tuple(plan.get(level, 0) for level in AwarenessLevel) == expected
    assert sum(plan.values()) == count


def test_a_top_up_fills_the_levels_the_set_is_missing() -> None:
    have = [AwarenessLevel.UNAWARE] * 2 + [AwarenessLevel.PROBLEM_AWARE] * 2 + [None]
    plan = level_plan(5, have)
    assert sum(n for _, n in plan) == 5
    assert dict(plan).get(AwarenessLevel.UNAWARE, 0) == 0
    assert dict(plan)[AwarenessLevel.MOST_AWARE] >= 1


# -- the tool, the prompt and the parse ----------------------------------------------------


def test_the_tool_requires_a_known_level_per_angle() -> None:
    row = angles_tool(10)["input_schema"]["properties"]["angles"]["items"]
    assert "awareness_level" in row["required"]
    assert row["properties"]["awareness_level"]["enum"] == [lv.value for lv in AwarenessLevel]


def test_the_system_prompt_explains_each_level_and_forbids_invented_facts() -> None:
    system = angles_system_prompt()
    for level in AwarenessLevel:
        assert f"- {level.value}:" in system
    assert "Nunca inventes un dato" in system and "formas de pago" in system
    assert "Nunca menciones el precio" in system


def test_the_user_prompt_carries_the_perks_and_the_spread() -> None:
    text = angles_user_prompt(PRODUCT, AngleBrand(name="Bianki", perks=PERKS), PRESETS[0])
    for perk in PERKS:
        assert f"- {perk}\n" in text
    assert "== Reparto por nivel de consciencia ==" in text
    for level in AwarenessLevel:
        assert f"- {level.value}: 2\n" in text


def test_without_perks_the_prompt_says_to_use_product_and_brand_only() -> None:
    text = angles_user_prompt(PRODUCT, BRAND, PRESETS[0], count=3)
    assert "el dueño no anotó ninguno" in text
    assert "- unaware: 1\n" in text and "- product_aware" not in text


_SCENES = (
    "sobre una tabla de madera en una cafetería con luz de ventana",
    "en la mano de alguien frente a un local de barrio al atardecer",
    "en un escritorio de oficina entre un portátil y un café",
    "sobre papel kraft en un picnic en el césped con sombra de árbol",
)


def _row(i: int, level: object = None) -> dict[str, object]:
    row: dict[str, object] = {
        "title": f"Ángulo {i}",
        "scene": _SCENES[i - 1],
        "composition": "plano medio",
        "hook": "Gancho",
        "cta": "Pide ya",
        "rationale": "porque sí",
    }
    if level is not None:
        row["awareness_level"] = level
    return row


def test_parse_keeps_the_level_and_tolerates_missing_or_unknown_ones() -> None:
    angles = parse_angles(
        {"angles": [_row(1, "unaware"), _row(2, " MOST_AWARE "), _row(3, "curioso"), _row(4)]},
        count=4,
    )
    assert [a.awareness_level for a in angles] == [
        AwarenessLevel.UNAWARE,
        AwarenessLevel.MOST_AWARE,
        None,
        None,
    ]
    assert awareness_level_or_none(123) is None


# -- the brief -----------------------------------------------------------------------------


def _angle(level: AwarenessLevel | None) -> CreativeAngle:
    return CreativeAngle(position=1, title="Mesa", scene="en la mesa", awareness_level=level)


@pytest.mark.parametrize(
    ("level", "objective"),
    [
        (AwarenessLevel.UNAWARE, BriefObjective.AWARENESS),
        (AwarenessLevel.PROBLEM_AWARE, BriefObjective.CONSIDERATION),
        (AwarenessLevel.SOLUTION_AWARE, BriefObjective.CONSIDERATION),
        (AwarenessLevel.PRODUCT_AWARE, BriefObjective.SALE),
        (AwarenessLevel.MOST_AWARE, BriefObjective.SALE),
        (None, BriefObjective.SALE),
    ],
)
def test_the_brief_objective_follows_the_level(
    level: AwarenessLevel | None, objective: BriefObjective
) -> None:
    brief = angle_brief(angle=_angle(level), preset=PRESETS[0], product=PRODUCT, brand_id=BRAND_ID)
    assert brief.objective is objective and brief.awareness_level is level


def test_an_unaware_brief_carries_no_price_and_the_others_keep_it() -> None:
    unaware = angle_brief(
        angle=_angle(AwarenessLevel.UNAWARE), preset=PRESETS[0], product=PRODUCT, brand_id=BRAND_ID
    )
    assert unaware.media.price_line == "" and unaware.constraints.must_mention == ()
    assert PRICE_HIGHLIGHT not in dict(unaware.constraints.highlights)
    aware = angle_brief(
        angle=_angle(AwarenessLevel.PRODUCT_AWARE),
        preset=PRESETS[0],
        product=PRODUCT,
        brand_id=BRAND_ID,
    )
    assert aware.media.price_line == "$18.000" and aware.constraints.must_mention == ("$18.000",)


# -- the copy prompt -----------------------------------------------------------------------


def test_without_perks_and_level_the_copy_prompt_is_byte_identical_to_main() -> None:
    assert hashlib.sha256(_corpus().encode()).hexdigest() == MAIN_DIGEST


def test_perks_ride_the_cached_prefix_and_the_level_the_suffix() -> None:
    kit = _kit(business_perks=PERKS)
    plain = render_prompt(kit=_kit(), voice=_voice(), brief=_brief(), task=GenerationTask.COPY)
    with_perks = render_prompt(kit=kit, voice=_voice(), brief=_brief(), task=GenerationTask.COPY)
    assert with_perks.stable_prefix.startswith(plain.stable_prefix.rstrip("\n"))
    assert "== What the business offers (facts the owner wrote) ==" in with_perks.stable_prefix
    for perk in PERKS:
        assert f"- {perk}\n" in with_perks.stable_prefix
    assert "Never invent a fact" in with_perks.stable_prefix
    assert with_perks.volatile_suffix == plain.volatile_suffix

    leveled = render_prompt(
        kit=kit,
        voice=_voice(),
        brief=_brief(awareness_level=AwarenessLevel.MOST_AWARE),
        task=GenerationTask.COPY,
    )
    assert leveled.stable_prefix == with_perks.stable_prefix
    lines = leveled.volatile_suffix.splitlines()
    objective = lines.index("Objective: sale")
    assert lines[objective + 1].startswith("Awareness level (Eugene Schwartz): most_aware")
    assert "a hook of about 6 words" in lines[objective + 1]


# -- NIVELES-001 wording fixes -------------------------------------------------------------


def test_unaware_keeps_to_experience_perks_in_both_prompts() -> None:
    system = angles_system_prompt()
    unaware = system.split("- unaware:")[1].split("- problem_aware:")[0]
    assert "solo las ventajas de la" in unaware and "quedan para product_aware" in unaware
    suffix = render_prompt(
        kit=_kit(business_perks=PERKS),
        voice=_voice(),
        brief=_brief(awareness_level=AwarenessLevel.UNAWARE),
        task=GenerationTask.COPY,
    ).volatile_suffix
    assert "Use only the perks about the experience" in suffix
    assert "opening hours, payment, prices and anything about cost" in suffix


def test_solution_aware_is_not_food_only() -> None:
    system = angles_system_prompt()
    solution = system.split("- solution_aware:")[1].split("- product_aware:")[0]
    assert "lo que distingue" in solution and "porción" not in solution
    suffix = render_prompt(
        kit=_kit(),
        voice=_voice(),
        brief=_brief(awareness_level=AwarenessLevel.SOLUTION_AWARE),
        task=GenerationTask.COPY,
    ).volatile_suffix
    assert "what sets this business apart" in suffix and "portion" not in suffix


def test_a_perk_is_never_turned_into_an_offer_or_a_service() -> None:
    system = angles_system_prompt()
    assert "nunca la conviertas en gratis, regalo" in system
    assert "ni reservas, ni domicilios, ni apartar" in system
    prefix = render_prompt(
        kit=_kit(business_perks=PERKS), voice=_voice(), brief=_brief(), task=GenerationTask.COPY
    ).stable_prefix
    assert "never turn it into something free, a gift, included" in prefix
    assert "Never offer a service (reservations, delivery" in prefix


# -- NIVELES-002 wording fixes -------------------------------------------------------------


def _level_text(system: str, level: str, after: str) -> str:
    return system.split(f"- {level}:")[1].split(after)[0]


def test_most_aware_buys_only_through_a_given_way_in_both_prompts() -> None:
    most = _level_text(angles_system_prompt(), "most_aware", "Datos reales del negocio")
    assert "solo una forma de comprar que esté" in most and "invita a venir o a" in most
    assert "ni reservar, ni para llevar, ni recoger, ni domicilio" in most
    suffix = render_prompt(
        kit=_kit(business_perks=PERKS),
        voice=_voice(),
        brief=_brief(awareness_level=AwarenessLevel.MOST_AWARE),
        task=GenerationTask.COPY,
    ).volatile_suffix
    assert "uses only a way to buy" in suffix
    assert "no reservations, takeaway, pickup or delivery" in suffix


def test_solution_aware_asks_for_one_concrete_given_fact() -> None:
    solution = _level_text(angles_system_prompt(), "solution_aware", "- product_aware:")
    assert "al menos un dato concreto" in solution and "frases" in solution
    assert "quedan para product_aware" in solution
    suffix = render_prompt(
        kit=_kit(),
        voice=_voice(),
        brief=_brief(awareness_level=AwarenessLevel.SOLUTION_AWARE),
        task=GenerationTask.COPY,
    ).volatile_suffix
    assert "at least one concrete fact" in suffix and "generic" in suffix


def test_the_level_decides_which_perks_a_piece_may_use() -> None:
    assert "El nivel manda" in angles_system_prompt()
    rendered = render_prompt(
        kit=_kit(business_perks=PERKS),
        voice=_voice(),
        brief=_brief(awareness_level=AwarenessLevel.UNAWARE),
        task=GenerationTask.COPY,
    )
    assert "the level decides which of them the piece may use" in rendered.stable_prefix
    assert "leave them out even though they are among" in rendered.volatile_suffix


# -- NIVELES-004 wording fixes -------------------------------------------------------------


def test_most_aware_copy_has_a_measured_length_that_yields_to_the_kit_minimum() -> None:
    suffix = render_prompt(
        kit=_kit(),
        voice=_voice(),
        brief=_brief(awareness_level=AwarenessLevel.MOST_AWARE),
        task=GenerationTask.COPY,
    ).volatile_suffix
    assert "a hook of about 6 words" in suffix
    assert "a call to action of about 5 words with one way to buy" in suffix
    assert "one or two sentences (about 25 words)" in suffix
    assert "never below the caption minimum above" in suffix


def test_solution_aware_leaves_opening_hours_to_product_aware() -> None:
    solution = _level_text(angles_system_prompt(), "solution_aware", "- product_aware:")
    assert "los horarios quedan para product_aware" in solution
    suffix = render_prompt(
        kit=_kit(),
        voice=_voice(),
        brief=_brief(awareness_level=AwarenessLevel.SOLUTION_AWARE),
        task=GenerationTask.COPY,
    ).volatile_suffix
    assert "prices, payment and opening hours belong to product_aware" in suffix
