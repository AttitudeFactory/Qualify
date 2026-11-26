"""m-25114465 (ADR 50 §10, proposed): transitions between a Clip's blocks — the recipe's
contract. `SourceSegment.transition_in` («Corte» = None, never dumped, so a Clip of cuts
serializes and digests as before), what `validate_recipe` refuses (first block, not a
transition, blocks too short — `transitions_longer_than_block` with its Spanish text),
what is still `recipe_unavailable` (a Clip not `local`, a part's blocks) and the public
room per block for the screen. Offline and pure: the real effects library (v5), no file
is read. The join itself is `test_video_pipeline_local.py`'s."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import (
    RECIPE_REFUSALS,
    ContentBrief,
    EffectUse,
    MediaInputs,
    SourceSegment,
    VideoPartPlan,
)

from qualify_api.creative.video_pipeline import PartRecipe, RecipeRefused, validate_recipe
from qualify_api.creative.video_pipeline.recipe import (
    BLOCK_MIN_FREE_FRAMES,
    BLOCK_TRANSITION_UNAVAILABLE_TEXT,
    CLIP_BLOCK_TRANSITIONS_SWITCH,
    TRANSITION_ON_CLIP_TEXT,
    TRANSITION_ON_FIRST_BLOCK_TEXT,
    TRANSITIONS_LONGER_THAN_BLOCK_TEXT,
    block_overlaps,
    block_transition_room_problems,
    block_transition_room_s,
    block_transitions_seconds,
    clip_block_transitions_on,
    clip_seconds,
    refuse_unbuilt_recipe,
    transition_duration_range,
    transitions_longer_than_block_text,
    unbuilt_recipe_problems,
    validate_brief_recipe,
)

from .test_content_service import TENANT_ID, make_brief

VIDEO = f"uploads/{TENANT_ID}/mi-cocina.mp4"
PHOTO = f"uploads/{TENANT_ID}/mi-plato.png"
FADE = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5})
WIPE = EffectUse(effect_id="barrido", version=2, params={"duration_s": 0.8, "direction": "up"})
CUT = EffectUse(effect_id="corte", version=1)


@pytest.fixture(autouse=True)
def transitions_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The coordinator's switch, on for these tests (off is the default:
    `test_with_the_switch_off_*`)."""
    monkeypatch.setenv(CLIP_BLOCK_TRANSITIONS_SWITCH, "on")


def _video(start: float = 0.0, end: float = 4.0, speed: float = 1.0, **extra: Any) -> SourceSegment:
    return SourceSegment(key=VIDEO, start_s=start, end_s=end, speed=speed, **extra)


def _photo(seconds: float = 2.0, **extra: Any) -> SourceSegment:
    return SourceSegment(key=PHOTO, start_s=0.0, end_s=seconds, kind="photo", **extra)


def _part(*segments: SourceSegment, mode: str = "local", **extra: Any) -> PartRecipe:
    return PartRecipe(index=1, mode=mode, seconds=5, segments=segments, **extra)  # type: ignore[arg-type]


def _clip(*segments: SourceSegment, mode: str = "local", **media: Any) -> ContentBrief:
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(
            **{
                "duration_seconds": 5,
                "clip_reference_mode": mode,
                "segments": segments,
                **media,
            }
        ),
    )


def _codes(problems: tuple) -> list[tuple[str, str]]:
    return [(p.code, p.field) for p in problems]


def _digest(model: Any) -> str:
    canonical = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# the contract: «Corte» changes nothing


def test_a_block_with_no_transition_serializes_exactly_as_before() -> None:
    """The dump a stored stretch had before the field existed — no `transition_in` key."""
    assert _video(0, 4, 2).model_dump(mode="json") == {
        "key": VIDEO,
        "start_s": 0.0,
        "end_s": 4.0,
        "speed": 2.0,
        "rotate": 0,
        "kind": "video",
    }
    assert "transition_in" not in _photo().model_dump_json()


def test_corte_reads_as_no_transition_so_the_recipe_and_its_digest_do_not_change() -> None:
    plain = _clip(_video(), _photo(), _video(4, 8))
    cut = _clip(_video(), _photo(transition_in=CUT), _video(4, 8, transition_in=CUT.model_dump()))
    assert cut.media.segments[1].transition_in is None
    assert cut.media.segments == plain.media.segments
    assert cut.media.model_dump(mode="json") == plain.media.model_dump(mode="json")
    assert _digest(cut.media) == _digest(plain.media)
    assert _digest(cut) == _digest(plain)
    # a stored stretch (no key) reads back the same
    stored = {"key": VIDEO, "start_s": 0.0, "end_s": 4.0, "speed": 1.0, "rotate": 0}
    assert SourceSegment.model_validate(stored) == _video()


def test_a_chosen_transition_round_trips_and_has_no_span() -> None:
    block = _photo(transition_in=FADE)
    data = block.model_dump(mode="json")
    assert data["transition_in"] == {
        "effect_id": "fundido",
        "version": 2,
        "params": {"duration_s": 0.5},
        "start_s": None,
        "end_s": None,
    }
    assert SourceSegment.model_validate_json(block.model_dump_json()) == block
    with pytest.raises(ValidationError, match="no span of its own"):
        _photo(transition_in=EffectUse(effect_id="fundido", version=2, start_s=0, end_s=1))


# ---------------------------------------------------------------------------
# what validate_recipe allows and refuses in a normal Clip


def test_fade_and_wipe_between_blocks_of_a_local_clip_pass() -> None:
    part = _part(_video(), _photo(transition_in=FADE), _video(4, 8, transition_in=WIPE))
    assert validate_recipe((part,), video_by_parts=False) == ()
    brief = _clip(*part.segments)
    assert validate_brief_recipe(brief, tenant_id=TENANT_ID) == ()
    assert unbuilt_recipe_problems(brief) == ()
    refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)  # does not raise


def test_a_transition_on_the_first_block_is_refused() -> None:
    problems = validate_recipe((_part(_photo(transition_in=FADE), _photo()),), video_by_parts=False)
    assert _codes(problems) == [("transition_on_first_block", "segments[0].transition_in")]


@pytest.mark.parametrize(
    ("use", "code"),
    [
        (EffectUse(effect_id="humo_capa", version=1), "transition_not_a_transition"),
        (EffectUse(effect_id="fundido", version=1), "not_offered"),  # v1: the old ranges
        (
            EffectUse(effect_id="barrido", version=2, params={"duration_s": 1.2}),
            "param_out_of_range",
        ),
        (EffectUse(effect_id="disolver", version=1), "unknown_effect"),
    ],
)
def test_what_is_not_a_drawn_transition_is_refused_on_its_block(use: EffectUse, code: str) -> None:
    part = _part(_photo(3), _photo(3, transition_in=use))
    problems = validate_recipe((part,), video_by_parts=False)
    assert [(c, f) for c, f in _codes(problems) if f.startswith("segments[1].transition_in")] == [
        (code, f"segments[1].transition_in{'.params.duration_s' * (code == 'param_out_of_range')}")
    ]


def test_transition_on_clip_still_refuses_what_is_not_on_a_block() -> None:
    """The Clip as a whole has no part before it, and a transition is no effect."""
    whole = PartRecipe(index=1, seconds=5, transition_in=FADE)
    assert _codes(validate_recipe((whole,), video_by_parts=False)) == [
        ("transition_on_clip", "transition_in")
    ]
    effect = validate_brief_recipe(_clip(_photo(), _photo(), effects=(FADE,)))
    assert _codes(effect) == [("transition_on_clip", "effects[0]")]


def test_blocks_shorter_than_their_transitions_are_refused_with_the_block_text() -> None:
    """A 1 s photo (30 frames) between two 0.8 s transitions (24 + 24 frames)."""
    long_in = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.8})
    part = _part(_photo(2), _photo(1, transition_in=long_in), _photo(2, transition_in=WIPE))
    problems = block_transition_room_problems(part)
    assert [(p.code, p.field, p.duration_s, p.part) for p in problems] == [
        ("transitions_longer_than_block", "segments[1]", 1.0, None)
    ]
    assert ("transitions_longer_than_block", "segments[1]") in _codes(
        validate_recipe((part,), video_by_parts=False)
    )
    assert transitions_longer_than_block_text(2) == (
        "El bloque 2 es muy corto para sus transiciones. Alárgalo, acorta sus "
        "transiciones o deja una de sus uniones con «Corte»."
    )


HALF_FADE = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5})
HALF_WIPE = EffectUse(effect_id="barrido", version=2, params={"duration_s": 0.5})


def test_a_block_eaten_whole_by_its_transitions_is_refused() -> None:
    """Review (blocking): a 1 s photo with a 0.5 s fade in and a 0.5 s wipe out keeps 0
    frames of its own — the join used to fail on it. It must keep 9 (0.3 s)."""
    part = _part(_photo(2), _photo(1, transition_in=HALF_FADE), _photo(2, transition_in=HALF_WIPE))
    assert _codes(block_transition_room_problems(part)) == [
        ("transitions_longer_than_block", "segments[1]")
    ]
    brief = _clip(*part.segments)
    with pytest.raises(RecipeRefused) as refused:
        refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)
    assert ("transitions_longer_than_block", "segments[1]") in _codes(refused.value.problems)


def test_a_block_keeping_exactly_its_free_frames_fits() -> None:
    """30 frames = 9 (0.3 s fade in) + 12 (0.4 s wipe out) + 9 of its own."""
    fade = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.3})
    wipe = EffectUse(effect_id="barrido", version=2, params={"duration_s": 0.4})
    part = _part(_photo(2), _photo(1, transition_in=fade), _photo(2, transition_in=wipe))
    assert BLOCK_MIN_FREE_FRAMES == 9
    assert block_transition_room_problems(part) == ()
    refuse_unbuilt_recipe(_clip(*part.segments), tenant_id=TENANT_ID)  # does not raise


def test_the_room_per_block_says_what_fits_before_the_owner_chooses() -> None:
    part = _part(_photo(2), _photo(1, transition_in=FADE), _photo(2, transition_in=WIPE))
    # into block 1: block 0 has 60 frames, block 1 has 30 - 24 (the wipe out of it), and
    # each keeps 9 of its own: nothing fits, only «Corte»
    assert block_transition_room_s(part, 1) == 0.0
    # into block 2: block 1 has 30 - 15 (the fade into it) - 9, block 2 has 60 - 9
    assert block_transition_room_s(part, 2) == pytest.approx(6 / 30)
    assert block_transition_room_s(part, 0) == 0.0
    assert block_transition_room_s(part, 3) == 0.0


def test_the_clip_lasts_its_blocks_minus_each_transition() -> None:
    cuts = _part(_video(0, 4, 2), _photo(1.5), _photo(2))
    assert clip_seconds(cuts) == pytest.approx(5.5)  # as before: only cuts
    assert block_transitions_seconds(cuts) == 0.0
    blended = _part(_video(0, 4, 2), _photo(1.5, transition_in=FADE), _photo(2, transition_in=WIPE))
    assert block_overlaps(blended) == (0, 15, 24)
    assert clip_seconds(blended) == pytest.approx(5.5 - 0.5 - 0.8)


def test_a_text_past_the_shortened_end_is_outside_the_clip() -> None:
    from qualify_creative.schemas import VideoTextLayer

    blended = (_photo(2), _photo(2, transition_in=FADE))  # 3.5 s
    late = VideoTextLayer(text="Pide hoy", start_s=3.0, end_s=3.8)
    brief = _clip(*blended, text_layers=(late,))
    assert ("span_outside_part", "text_layers[0]") in _codes(validate_brief_recipe(brief))


def test_a_clip_shortened_under_3_seconds_says_how_long_it_comes_out() -> None:
    long_in = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5})
    part = _part(_photo(1.5), _photo(1.5, transition_in=long_in))  # 3 s - 0.5 = 2.5 s
    (problem,) = [p for p in validate_recipe((part,), video_by_parts=False)]
    assert (problem.code, problem.duration_s) == ("local_length_out_of_range", 2.5)


# ---------------------------------------------------------------------------
# what the server still does not make


def test_a_block_transition_in_a_clip_made_by_seedance_is_unavailable() -> None:
    brief = _clip(_video(), mode="motion")
    blended = brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={"segments": (_video(), _video(4, 8, transition_in=FADE))}
            )
        }
    )
    assert ("recipe_unavailable", "segments[1].transition_in") in _codes(
        unbuilt_recipe_problems(blended)
    )
    with pytest.raises(RecipeRefused):
        refuse_unbuilt_recipe(blended, tenant_id=TENANT_ID)


def test_a_block_transition_inside_a_part_of_a_video_by_parts_is_unavailable() -> None:
    from .test_creative_parts import parent_brief

    plan = VideoPartPlan(
        seconds=5,
        mode="local",
        segments=(_photo(2.5), _photo(3, transition_in=FADE)),
    )
    problems = unbuilt_recipe_problems(parent_brief(plan))
    assert [(p.code, p.part, p.field) for p in problems] == [
        ("recipe_unavailable", 1, "segments[1].transition_in")
    ]


# ---------------------------------------------------------------------------
# the codes and the words


def test_the_block_codes_are_appended() -> None:
    at = RECIPE_REFUSALS.index("transition_on_first_block")
    assert RECIPE_REFUSALS[at : at + 2] == (
        "transition_on_first_block",
        "transitions_longer_than_block",
    )
    assert RECIPE_REFUSALS[at - 1] == "text_too_long_for_large"


def test_the_texts_are_plain_spanish_about_blocks() -> None:
    assert TRANSITIONS_LONGER_THAN_BLOCK_TEXT.startswith("El bloque {block} ")
    assert TRANSITION_ON_FIRST_BLOCK_TEXT == (
        "Antes del primer bloque no hay nada que unir. Déjalo con «Corte»."
    )
    assert BLOCK_TRANSITION_UNAVAILABLE_TEXT == (
        "Por ahora las transiciones solo funcionan en videos armados con tus fotos y videos. "
        "Deja esa unión con «Corte»."
    )
    assert "unión entre dos bloques" in TRANSITION_ON_CLIP_TEXT
    assert "«Corte»" in BLOCK_TRANSITION_UNAVAILABLE_TEXT
    for text in (
        TRANSITIONS_LONGER_THAN_BLOCK_TEXT,
        TRANSITION_ON_FIRST_BLOCK_TEXT,
        TRANSITION_ON_CLIP_TEXT,
        BLOCK_TRANSITION_UNAVAILABLE_TEXT,
    ):
        assert "parte" not in text and "clip" not in text.lower()


def test_another_business_stretch_is_still_foreign_with_a_transition() -> None:
    other = UUID("0b0b0000-0000-4000-8000-0000000000ee")
    foreign = SourceSegment(
        key=f"uploads/{other}/su-plato.png", start_s=0, end_s=2, kind="photo", transition_in=FADE
    )
    problems = validate_recipe(
        (_part(_photo(), foreign),), video_by_parts=False, tenant_id=TENANT_ID
    )
    assert ("foreign_key", "segments[1].key") in _codes(problems)


# ---------------------------------------------------------------------------
# the switch (off by default while ADR 50 §10 is unsigned) and the library's ranges


def test_with_the_switch_off_a_block_transition_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    brief = _clip(_video(), _photo(transition_in=FADE))
    for value in (None, "off", "", "yes"):  # unset, off, empty, a typo: all off
        if value is None:
            monkeypatch.delenv(CLIP_BLOCK_TRANSITIONS_SWITCH, raising=False)
        else:
            monkeypatch.setenv(CLIP_BLOCK_TRANSITIONS_SWITCH, value)
        assert clip_block_transitions_on() is False
        assert _codes(unbuilt_recipe_problems(brief)) == [
            ("recipe_unavailable", "segments[1].transition_in")
        ]
        with pytest.raises(RecipeRefused):
            refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)


def test_with_the_switch_off_a_clip_of_cuts_is_made_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CLIP_BLOCK_TRANSITIONS_SWITCH, "off")
    brief = _clip(_video(), _photo(transition_in=CUT))
    assert unbuilt_recipe_problems(brief) == ()
    refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)  # does not raise


def test_with_the_switch_on_a_block_transition_passes() -> None:
    assert clip_block_transitions_on() is True
    assert unbuilt_recipe_problems(_clip(_video(), _photo(transition_in=FADE))) == ()


def test_the_duration_ranges_are_the_librarys() -> None:
    """The library v5 is the only source: fundido and barrido v2 last 0.3-0.8 s (their v1,
    0.2-1.5 and 0.2-1.0 s, is not offered); `corte` has none."""
    assert transition_duration_range("fundido") == (0.3, 0.8)
    assert transition_duration_range("barrido") == (0.3, 0.8)
    assert transition_duration_range("corte") is None
    assert transition_duration_range("disolver") is None
