"""m-25026509: a clip and a video by parts carry the reader's awareness level, offline.

The objective the screen takes from a level (`objective_for_level`); an `unaware` brief
carries no price on any path — the brief itself (a «Precio» row, a row quoting money, a
«must mention» with a figure, `price_line`), the stored row read back, the copy prompt,
the clip video prompt (compilers 1 and 2), a part's prompt lines and a part's brief —
while every other level and a brief with no level keep their price exactly; the parts
proposal reads the brief's level when no angle gives one."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.angles import AngleBrand, CreativeAngle
from qualify_creative.brand import render_prompt
from qualify_creative.enums import (
    AwarenessLevel,
    ContentKind,
    GenerationTask,
    VoiceProfileStatus,
    objective_for_level,
)
from qualify_creative.schemas import BrandVoiceProfile, ContentBrief, ToneAxes

from qualify_api.creative import media as M
from qualify_api.creative.parts_ai import PartsBrief, propose_user_prompt
from qualify_api.creative.service import _brief_row, brief_from_row

from .test_prompt_budget_v1 import _kit, _real
from .test_video_prompt_v2 import _clip, _motion

PRICE = "$18.000"
FACTS = (("Precio", PRICE), ("Valor del combo", "20 mil pesos"), ("Horario", "Hasta las 11"))


def _with(base: ContentBrief, level: AwarenessLevel | None, **extra: Any) -> ContentBrief:
    """`base` re-validated (as every production path builds a brief) with the price
    facts, a figure to mention, a `price_line` and the level."""
    data = base.model_dump()
    data["constraints"] = {
        **data["constraints"],
        "highlights": FACTS,
        "must_mention": ("Combo doble", f"a {PRICE}"),
    }
    data["media"] = {**data["media"], "price_line": PRICE}
    data["awareness_level"] = level
    data.update(extra)
    return ContentBrief.model_validate(data)


# -- the objective ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        ("unaware", "awareness"),
        ("problem_aware", "consideration"),
        ("solution_aware", "consideration"),
        ("product_aware", "sale"),
        ("most_aware", "sale"),
        ("", "consideration"),
        (None, "consideration"),
        ("otro", "consideration"),
    ],
)
def test_the_objective_follows_the_level_and_keeps_the_default_without_one(
    level: str | None, expected: str
) -> None:
    assert objective_for_level(level, "consideration") == expected


# -- the brief --------------------------------------------------------------------------


def test_an_unaware_brief_drops_every_price_and_keeps_the_rest() -> None:
    brief = _with(_motion(), AwarenessLevel.UNAWARE)
    assert brief.constraints.highlights == (("Horario", "Hasta las 11"),)
    assert brief.constraints.must_mention == ("Combo doble",)
    assert brief.media.price_line == ""


@pytest.mark.parametrize(
    "level", [None, *(lv for lv in AwarenessLevel if lv is not AwarenessLevel.UNAWARE)]
)
def test_other_levels_and_no_level_keep_the_price_exactly(level: AwarenessLevel | None) -> None:
    brief = _with(_motion(), level)
    assert brief.constraints.highlights == FACTS
    assert brief.constraints.must_mention == ("Combo doble", f"a {PRICE}")
    assert brief.media.price_line == PRICE


def test_the_stored_unaware_brief_reads_back_without_a_price() -> None:
    brief = _with(_motion(), AwarenessLevel.UNAWARE)
    back = brief_from_row(_brief_row(uuid4(), uuid4(), brief))
    assert back.awareness_level is AwarenessLevel.UNAWARE
    assert PRICE not in str(back.model_dump())


# -- the prompts ------------------------------------------------------------------------


def _voice() -> BrandVoiceProfile:
    return BrandVoiceProfile(
        brand_id=_kit().brand_id,
        version=1,
        status=VoiceProfileStatus.ACTIVE,
        tone_axes=ToneAxes(
            formal_casual=50, sober_enthusiastic=50, technical_plain=50, brief_elaborate=50
        ),
    )


def _copy_suffix(brief: ContentBrief) -> str:
    return render_prompt(
        kit=_kit(), voice=_voice(), brief=brief, task=GenerationTask.COPY
    ).volatile_suffix


def test_the_copy_prompt_of_an_unaware_clip_quotes_no_price() -> None:
    unaware = _copy_suffix(_with(_motion(), AwarenessLevel.UNAWARE))
    assert "18.000" not in unaware and "20 mil" not in unaware
    assert "Awareness level (Eugene Schwartz): unaware" in unaware
    assert "18.000" in _copy_suffix(_with(_motion(), AwarenessLevel.PRODUCT_AWARE))


@pytest.mark.parametrize("version", [1, 2])
def test_the_clip_video_prompt_of_an_unaware_clip_quotes_no_price(version: int) -> None:
    base = _motion() if version == 2 else _real(version=1)
    unaware = _with(base, AwarenessLevel.UNAWARE)
    leveled = _with(base, AwarenessLevel.MOST_AWARE)
    if version == 2:
        assert "18.000" not in _clip(unaware, []) and "18.000" in _clip(leveled, [])
    for line in (
        M._facts_line(unaware, "use"),
        M._facts_line_v2(unaware, "use", capped=False),
        M._facts_line_v2(unaware, "use", capped=True),
    ):
        assert "18.000" not in line and "20 mil" not in line
    assert "18.000" in M._facts_line(leveled, "use")


def test_a_parts_video_and_its_parts_carry_no_price_when_unaware() -> None:
    parent = _with(_motion(), AwarenessLevel.UNAWARE)
    assert parent.kind is ContentKind.CLIP
    child = ContentBrief.model_validate(parent.model_dump())  # as `parts._child_brief`
    lines = " ".join(M._part_common_lines(child, _kit(), None))
    assert "18.000" not in lines and "20 mil" not in lines and "Hasta las 11" in lines


# -- the parts proposal -----------------------------------------------------------------


def test_the_parts_proposal_reads_the_briefs_level_when_no_angle_gives_one() -> None:
    brief = PartsBrief(
        story="Ven", brand=AngleBrand(name="Bianki"), awareness_level=AwarenessLevel.UNAWARE
    )
    text = propose_user_prompt(brief)
    assert "== A quién le habla el video ==" in text
    assert "Nivel de consciencia del público: unaware — " in text
    # an angle's own level wins; an angle without one falls back to the brief's
    angle = CreativeAngle(
        position=1, title="Mesa", scene="mesa", awareness_level=AwarenessLevel.PROBLEM_AWARE
    )
    assert "público: problem_aware" in propose_user_prompt(brief, angle)
    plain = CreativeAngle(position=1, title="Mesa", scene="mesa")
    assert "público: unaware" in propose_user_prompt(brief, plain)
    # most_aware has no line by design (v3.4), with or without an angle
    most = PartsBrief(story="Ven", awareness_level=AwarenessLevel.MOST_AWARE)
    assert "Nivel de consciencia" not in propose_user_prompt(most)


def test_problem_aware_parts_open_on_someone_living_the_dilemma() -> None:
    from qualify_api.creative.parts_ai import PROPOSE_PARTS_PROMPT_VERSION

    text = propose_user_prompt(
        PartsBrief(story="Ven", awareness_level=AwarenessLevel.PROBLEM_AWARE)
    )
    assert "la primera parte muestra a alguien viviendo ese dilema" in text
    assert "el producto, si eligió uno, o lo que cuenta el dueño" in text
    assert PROPOSE_PARTS_PROMPT_VERSION == "proponer-partes-v3.5"


@pytest.mark.parametrize(
    ("text", "flagged"),
    [("Ref 2045", False), ("ref 3", False), ("Ref. 2045", False), ("REF 7", True)],
)
def test_the_parts_guard_tells_a_reference_code_from_a_price(text: str, flagged: bool) -> None:
    from qualify_api.creative.parts_ai import parse_parts

    rows = [
        {"description": f"Unas manos muestran la blusa {text} sobre la mesa.", "seconds": 5},
        {"description": "La blusa colgada junto a la ventana del local.", "seconds": 5},
        {"description": "Una persona se prueba la blusa frente al espejo.", "seconds": 5},
    ]
    _, problems = parse_parts({"parts": rows})
    assert any("menciona un precio" in p for p in problems) is flagged
