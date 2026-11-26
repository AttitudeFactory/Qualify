"""m-25129405 (ADR 50 §13.2 and §13.6): the «parte con IA» block of a Clip — the contract.

An AI block is a `SourceSegment` of `kind="ai_part"` whose `key` (`ai_part:<n>`) names
its entry of `MediaInputs.ai_parts` (a `VideoPartPlan`, unchanged). The switch
`QUALIFY_CLIP_AI_PARTS` refuses it with `switched_off` before anything is read; on, every
rule of §13.2 has its stable code and its Spanish words. Offline and pure: the real
effects library, no file, no database, no vendor."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import (
    AI_PART_KIND,
    RECIPE_REFUSALS,
    SEGMENT_KINDS,
    ContentBrief,
    EffectUse,
    MediaInputs,
    SourceSegment,
    VideoPartPlan,
    VideoTextLayer,
    ai_part_key,
)

from qualify_api.creative.video_pipeline import (
    PartRecipe,
    RecipeRefused,
    recipe,
    refuse_unbuilt_recipe,
    validate_recipe,
)
from qualify_api.creative.video_pipeline.ai_parts import (
    AI_CHILDREN_MAX,
    AI_PART_TEXTS,
    CLIP_AI_PARTS_SWITCH,
    ai_children_of,
    ai_part_text,
    clip_ai_parts_on,
    own_seconds,
)
from qualify_api.creative.video_pipeline.recipe import (
    CLIP_BLOCK_TRANSITIONS_SWITCH,
    clip_seconds,
    unbuilt_recipe_problems,
    validate_brief_recipe,
)

from .test_content_service import TENANT_ID, make_brief

VIDEO = f"uploads/{TENANT_ID}/mi-cocina.mp4"
PHOTO = f"uploads/{TENANT_ID}/mi-plato.png"
ANALYSIS = UUID("00000000-0000-4000-8000-0000000000aa")
FADE = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5})
#: The codes this contract appended, in order.
CODES = (
    "switched_off",
    "too_many_blocks",
    "too_many_ai_children",
    "extend_needs_block_before",
    "edit_needs_reel_window",
    "ai_part_with_speed",
    "own_media_too_short",
    "ai_parts_mismatch",
    "ai_part_length_mismatch",
    "ai_part_outside_clip",
    "ai_part_local",
    "ai_part_own_recipe",
    "ai_part_guide_type",
    "extend_after_own_media",
    "extend_not_same_moment",
)


@pytest.fixture
def ai_parts_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "on")


@pytest.fixture(autouse=True)
def _switches_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CLIP_AI_PARTS_SWITCH, raising=False)
    monkeypatch.delenv(CLIP_BLOCK_TRANSITIONS_SWITCH, raising=False)


def _video(start: float = 0.0, end: float = 4.0, **extra: Any) -> SourceSegment:
    return SourceSegment(key=VIDEO, start_s=start, end_s=end, **extra)


def _photo(seconds: float = 2.0) -> SourceSegment:
    return SourceSegment(key=PHOTO, start_s=0.0, end_s=seconds, kind="photo")


def _ai(at: int, seconds: float = 5.0, **extra: Any) -> SourceSegment:
    return SourceSegment(key=ai_part_key(at), start_s=0.0, end_s=seconds, kind="ai_part", **extra)


def _entry(mode: str = "reference", seconds: int = 5, **extra: Any) -> VideoPartPlan:
    return VideoPartPlan(mode=mode, seconds=seconds, description="Una arepa", **extra)  # type: ignore[arg-type]


def _part(*segments: SourceSegment, mode: str = "local") -> PartRecipe:
    return PartRecipe(index=1, mode=mode, seconds=5, segments=segments)  # type: ignore[arg-type]


def _clip(
    segments: tuple[SourceSegment, ...], ai_parts: tuple[VideoPartPlan, ...] = (), **media: Any
) -> ContentBrief:
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(
            duration_seconds=5,
            clip_reference_mode=media.pop("mode", "local"),
            segments=segments,
            ai_parts=ai_parts,
            **media,
        ),
    )


def _codes(problems: tuple) -> list[tuple[str, str]]:
    return [(p.code, p.field) for p in problems]


def _check(
    segments: tuple[SourceSegment, ...],
    ai_parts: tuple[VideoPartPlan, ...],
    **extra: Any,
) -> list[tuple[str, str]]:
    return _codes(
        validate_recipe(
            (_part(*segments),),
            video_by_parts=False,
            tenant_id=TENANT_ID,
            ai_parts=ai_parts,
            **extra,
        )
    )


# ---------------------------------------------------------------------------
# the block's shape


def test_an_ai_block_names_its_entry_and_reads_it_back() -> None:
    block = _ai(2)
    assert block.kind == AI_PART_KIND and block.key == "ai_part:2" and block.ai_part_at == 2
    assert _video().ai_part_at is None
    # the owner's own kinds are unchanged: the screen's contract keeps writing these
    assert SEGMENT_KINDS == ("video", "photo")


@pytest.mark.parametrize(
    "bad",
    [
        {"key": VIDEO},  # not a pointer to `ai_parts`
        {"key": "ai_part:x"},
        {"start_s": 1.0, "end_s": 6.0},  # a block made by AI starts at its start
        {"rotate": 90},  # and is upright
    ],
)
def test_an_ai_block_that_names_no_entry_or_is_cut_does_not_read(bad: dict[str, Any]) -> None:
    data = {"key": ai_part_key(0), "start_s": 0.0, "end_s": 5.0, "kind": "ai_part", **bad}
    with pytest.raises(ValidationError):
        SourceSegment.model_validate(data)


def test_a_clip_without_ai_parts_serializes_as_before_plus_an_empty_list() -> None:
    brief = _clip((_video(),))
    assert brief.media.model_dump(mode="json")["ai_parts"] == []
    assert "ai_part" not in _video().model_dump_json()


# ---------------------------------------------------------------------------
# the switch (§13.6)


@pytest.mark.parametrize(("value", "on"), [("on", True), ("ON", True), ("off", False), ("", False)])
def test_the_switch_reads_on_or_off(monkeypatch: pytest.MonkeyPatch, value: str, on: bool) -> None:
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, value)
    assert clip_ai_parts_on() is on


def test_a_typo_in_the_switch_reads_as_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "yes")
    assert clip_ai_parts_on() is False


def test_switched_off_an_ai_block_is_refused_before_anything_is_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_reading() -> None:
        raise AssertionError("the effects library was read")

    monkeypatch.setattr(recipe, "load_effects", no_reading)
    brief = _clip((_video(), _ai(0), _ai(1, 3.0)), (_entry(), _entry(seconds=3)))
    expected = [("switched_off", "segments[1]"), ("switched_off", "segments[2]")]
    assert _codes(validate_brief_recipe(brief, tenant_id=TENANT_ID)) == expected
    assert _codes(unbuilt_recipe_problems(brief)) == expected
    with pytest.raises(RecipeRefused) as refused:
        refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)
    assert refused.value.reason == "switched_off"
    assert _codes(refused.value.problems) == expected
    assert _check((_ai(0),), (_entry(),)) == [("switched_off", "segments[0]")]


def test_switched_off_entries_alone_are_refused_too() -> None:
    brief = _clip((_video(),), (_entry(),))
    assert _codes(validate_brief_recipe(brief)) == [("switched_off", "ai_parts")]


def test_switched_off_a_clip_without_ai_parts_reads_as_before() -> None:
    brief = _clip((_video(),))
    assert validate_brief_recipe(brief, tenant_id=TENANT_ID) == ()
    refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)


def test_the_switch_is_off_in_every_example_environment() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for name in (".env.example", "deploy/.env.prod.example"):
        text = (root / name).read_text(encoding="utf-8")
        assert f"{CLIP_AI_PARTS_SWITCH}=off" in text, name


# ---------------------------------------------------------------------------
# the rules (§13.2), switch on


@pytest.mark.usefixtures("ai_parts_on")
def test_a_valid_clip_with_own_blocks_and_ai_parts_has_no_problem() -> None:
    brief = _clip(
        (_photo(2), _video(0, 4), _ai(0), _ai(1, 3.0)),
        (
            _entry(analysis_id=ANALYSIS, shot_indexes=(3, 4)),
            _entry(
                mode="extend",
                original_mode="extend",
                seconds=3,
                analysis_id=ANALYSIS,
                shot_indexes=(4,),
            ),
        ),
    )
    assert validate_brief_recipe(brief, tenant_id=TENANT_ID) == ()
    # the AI blocks count in the Clip's length, at ×1: 2 + 4 + 5 + 3
    assert clip_seconds(recipe.recipe_of(brief)[0]) == 14


@pytest.mark.usefixtures("ai_parts_on")
def test_a_clip_made_only_of_ai_parts_is_valid() -> None:
    """§13.10, answer 3: the «3 s of own» rule is only for scenes and avatars."""
    assert _check((_ai(0), _ai(1)), (_entry(), _entry())) == []


@pytest.mark.usefixtures("ai_parts_on")
def test_a_clip_lasts_3_to_60_seconds_counting_its_ai_parts() -> None:
    assert _check((_ai(0, 2.0),), (_entry(seconds=2),)) == [
        ("local_length_out_of_range", "segments")
    ]
    blocks = tuple(_ai(at, 10.0) for at in range(6)) + (_video(0, 5),)
    entries = tuple(_entry(seconds=10) for _ in range(6))
    assert _check(blocks, entries) == [("local_length_out_of_range", "segments")]


@pytest.mark.usefixtures("ai_parts_on")
def test_at_most_8_blocks() -> None:
    nine = tuple(_video(0, 1) for _ in range(8)) + (_ai(0),)
    part = PartRecipe.model_construct(
        index=1, mode="local", seconds=5, segments=nine, effects=(), text_layers=()
    )
    found = _codes(validate_recipe((part,), video_by_parts=False, ai_parts=(_entry(),)))
    assert ("too_many_blocks", "segments") in found


@pytest.mark.usefixtures("ai_parts_on")
def test_at_most_6_ai_children_counting_character_scenes_and_avatars() -> None:
    blocks = tuple(_ai(at, 2.0) for at in range(4)) + (_video(0, 3),)
    entries = tuple(_entry(seconds=2) for _ in range(4))
    assert _check(blocks, entries, other_ai_children=2) == []
    assert _check(blocks, entries, other_ai_children=3) == [("too_many_ai_children", "ai_parts")]
    assert AI_CHILDREN_MAX == 6


def test_the_other_children_are_scenes_and_avatars_when_the_fields_exist() -> None:
    assert ai_children_of(MediaInputs()) == 0
    scenes = SimpleNamespace(character_scenes=(object(), object()), clip_avatar_plan=(object(),))
    assert ai_children_of(scenes) == 3  # type: ignore[arg-type]


def _take(*cuts: int, **extra: Any) -> VideoPartPlan:
    """An entry of the analysed reel's cuts (a «Nueva» part unless `mode` says)."""
    return _entry(analysis_id=ANALYSIS, shot_indexes=cuts, **extra)


#: «Sigue a la anterior» split by the plan from cut 4, the long take the part before ends on.
SPLIT_EXTEND = _take(4, mode="extend", original_mode="extend")


@pytest.mark.usefixtures("ai_parts_on")
def test_extend_continues_the_ai_part_split_from_the_same_take() -> None:
    """VE-13 as the producer makes it today: the previous part's own vendor file."""
    assert _check((_ai(1), _ai(0)), (SPLIT_EXTEND, _take(3, 4))) == []


@pytest.mark.usefixtures("ai_parts_on")
def test_extend_never_opens_the_video() -> None:
    assert _check((_ai(0), _video()), (SPLIT_EXTEND,)) == [
        ("extend_needs_block_before", "ai_parts[0].mode")
    ]


@pytest.mark.usefixtures("ai_parts_on")
@pytest.mark.parametrize("before", [_video(), _photo()], ids=["video", "photo"])
def test_extend_never_continues_the_owners_own_video_or_photo(before: SourceSegment) -> None:
    """Not built: Seedance continues only its own unedited output (pending, PR 2)."""
    assert _check((before, _ai(0)), (SPLIT_EXTEND,)) == [
        ("extend_after_own_media", "ai_parts[0].mode")
    ]


@pytest.mark.usefixtures("ai_parts_on")
@pytest.mark.parametrize(
    "entry",
    [
        _entry(mode="extend"),  # no reel: not split by the plan
        _take(4, mode="extend"),  # not born «Sigue a la anterior»
        _take(5, mode="extend", original_mode="extend"),  # another take than the one before
    ],
    ids=["no-reel", "not-split", "other-take"],
)
def test_extend_only_where_both_parts_were_one_moment_of_the_original(
    entry: VideoPartPlan,
) -> None:
    assert _check((_ai(1), _ai(0)), (entry, _take(3, 4))) == [
        ("extend_not_same_moment", "ai_parts[0].mode")
    ]


@pytest.mark.usefixtures("ai_parts_on")
def test_edit_needs_the_reels_cuts_it_copies() -> None:
    own_original = _entry(mode="edit", clip_video_keys=(VIDEO,))
    assert _check((_video(), _ai(0)), (own_original,)) == [
        ("edit_needs_reel_window", "ai_parts[0].shot_indexes")
    ]
    window = _entry(mode="edit", analysis_id=ANALYSIS, shot_indexes=(2, 3))
    assert _check((_video(), _ai(0)), (window,)) == []


@pytest.mark.usefixtures("ai_parts_on")
def test_an_ai_block_plays_at_x1() -> None:
    assert _check((_video(), _ai(0, 10.0, speed=2.0)), (_entry(),)) == [
        ("ai_part_with_speed", "segments[1].speed")
    ]


@pytest.mark.usefixtures("ai_parts_on")
def test_an_ai_block_lasts_its_entrys_seconds() -> None:
    found = validate_recipe(
        (_part(_video(), _ai(0, 4.0)),), video_by_parts=False, ai_parts=(_entry(seconds=5),)
    )
    assert _codes(found) == [("ai_part_length_mismatch", "segments[1].end_s")]
    assert found[0].duration_s == 4.0


@pytest.mark.usefixtures("ai_parts_on")
def test_own_material_is_needed_only_with_scenes_or_avatars() -> None:
    blocks = (_ai(0), _photo(2.0))
    assert _check(blocks, (_entry(),)) == []
    found = validate_recipe(
        (_part(*blocks),), video_by_parts=False, ai_parts=(_entry(),), other_ai_children=1
    )
    assert _codes(found) == [("own_media_too_short", "segments")]
    assert found[0].duration_s == 2.0
    assert _check((_ai(0), _video(0, 3)), (_entry(),), other_ai_children=1) == []
    assert own_seconds((_ai(0), _photo(2.0), _video(0, 4))) == 6.0


@pytest.mark.usefixtures("ai_parts_on")
def test_blocks_and_entries_match_one_to_one() -> None:
    assert _check((_video(), _ai(1)), (_entry(),)) == [
        ("ai_parts_mismatch", "segments[1]"),
        ("ai_parts_mismatch", "ai_parts[0]"),
    ]
    assert _check((_ai(0), _ai(0)), (_entry(), _entry())) == [
        ("ai_parts_mismatch", "segments[1]"),
        ("ai_parts_mismatch", "ai_parts[1]"),
    ]
    # an AI block validated without its entries is never made in silence
    assert _codes(validate_recipe((_part(_video(), _ai(0)),), video_by_parts=False)) == [
        ("ai_parts_mismatch", "segments[1]")
    ]


@pytest.mark.usefixtures("ai_parts_on")
def test_an_entry_is_never_local_nor_carries_its_own_recipe() -> None:
    local = _entry(mode="local", segments=(_video(0, 5),))
    assert _check((_video(), _ai(0)), (local,)) == [
        ("ai_part_local", "ai_parts[0].mode"),
        ("ai_part_own_recipe", "ai_parts[0]"),
    ]
    texted = _entry(text_layers=(VideoTextLayer(text="Hoy"),))
    joined = _entry(transition_in=FADE)
    assert _check((_video(), _ai(0), _ai(1)), (texted, joined)) == [
        ("ai_part_own_recipe", "ai_parts[0]"),
        ("ai_part_own_recipe", "ai_parts[1]"),
    ]


@pytest.mark.usefixtures("ai_parts_on")
def test_an_ai_block_goes_only_in_a_clip_made_of_blocks() -> None:
    motion = _clip((_video(), _ai(0)), (_entry(),), mode="motion")
    found = _codes(validate_brief_recipe(motion))
    assert ("ai_part_outside_clip", "segments[1]") in found
    as_part = PartRecipe(index=1, mode="local", seconds=5, segments=(_ai(0),))
    assert ("ai_part_outside_clip", "segments[0]") in _codes(
        validate_recipe((as_part,), video_by_parts=True)
    )
    image = make_brief(variants=1, media=MediaInputs(ai_parts=(_entry(),)))
    assert _codes(validate_brief_recipe(image)) == [("ai_part_outside_clip", "ai_parts")]


@pytest.mark.usefixtures("ai_parts_on")
def test_an_ai_blocks_join_is_its_transition_in_as_any_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CLIP_BLOCK_TRANSITIONS_SWITCH, "on")
    assert _check((_video(), _ai(0, transition_in=FADE)), (_entry(),)) == []
    # too short for its transitions, as any block (`block_transition_room_problems`)
    short = (_video(), _ai(0, 1.0, transition_in=FADE), _video(0, 3, transition_in=FADE))
    assert ("transitions_longer_than_block", "segments[1]") in _check(short, (_entry(seconds=1),))
    assert _check((_ai(0, transition_in=FADE),), (_entry(),)) == [
        ("transition_on_first_block", "segments[0].transition_in")
    ]


@pytest.mark.usefixtures("ai_parts_on")
def test_an_ai_block_is_never_checked_as_a_file_of_the_business() -> None:
    other = UUID("00000000-0000-4000-8000-0000000000ff")
    found = _codes(
        validate_recipe(
            (_part(_video(), _ai(0)),), video_by_parts=False, tenant_id=other, ai_parts=(_entry(),)
        )
    )
    assert found == [("foreign_key", "segments[0].key")]


@pytest.mark.usefixtures("ai_parts_on")
def test_switched_on_create_draft_still_refuses_ai_blocks_until_pr2() -> None:
    """§13.7: the Clip with AI parts is created by its own service (PR 2)."""
    brief = _clip((_video(), _ai(0)), (_entry(),))
    assert validate_brief_recipe(brief, tenant_id=TENANT_ID) == ()
    assert _codes(unbuilt_recipe_problems(brief)) == [("recipe_unavailable", "segments[1]")]
    with pytest.raises(RecipeRefused) as refused:
        refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)
    assert refused.value.reason == "recipe_unavailable"


# ---------------------------------------------------------------------------
# «Video o audio tuyo»: the owner's guide on an AI part (design m-25026602)

GUIDE_VIDEO = f"uploads/{TENANT_ID}/mi-baile.mp4"
GUIDE_AUDIO = f"uploads/{TENANT_ID}/mi-cancion.mp3"


@pytest.mark.usefixtures("ai_parts_on")
def test_a_new_part_takes_the_owners_video_and_audio_as_its_guide() -> None:
    guided = _entry(clip_video_keys=(GUIDE_VIDEO,), clip_audio_keys=(GUIDE_AUDIO,))
    brief = _clip((_video(), _ai(0)), (guided,))
    assert validate_brief_recipe(brief, tenant_id=TENANT_ID) == ()
    # it travels in the entry unchanged, as a part's references do today
    stored = brief.media.model_dump(mode="json")["ai_parts"][0]
    assert stored["clip_video_keys"] == [GUIDE_VIDEO]
    assert stored["clip_audio_keys"] == [GUIDE_AUDIO]


@pytest.mark.usefixtures("ai_parts_on")
def test_a_guide_of_another_business_or_not_a_file_is_refused() -> None:
    other = f"uploads/{UUID('00000000-0000-4000-8000-0000000000ff')}/su-baile.mp4"
    guided = _entry(clip_video_keys=(other,), clip_audio_keys=("cancion.mp3",))
    assert _check((_video(), _ai(0)), (guided,)) == [
        ("foreign_key", "ai_parts[0].clip_video_keys[0]"),
        ("malformed_key", "ai_parts[0].clip_audio_keys[0]"),
    ]


@pytest.mark.usefixtures("ai_parts_on")
def test_a_guide_of_another_type_is_refused() -> None:
    guided = _entry(
        clip_video_keys=(f"uploads/{TENANT_ID}/mi-baile.gif",),
        clip_audio_keys=(f"uploads/{TENANT_ID}/mi-cancion.ogg",),
    )
    assert _check((_video(), _ai(0)), (guided,)) == [
        ("ai_part_guide_type", "ai_parts[0].clip_video_keys[0]"),
        ("ai_part_guide_type", "ai_parts[0].clip_audio_keys[0]"),
    ]


@pytest.mark.parametrize(
    "bad",
    [
        {"mode": "extend", "clip_video_keys": (GUIDE_VIDEO,)},
        {"mode": "extend", "clip_audio_keys": (GUIDE_AUDIO,)},
        {"mode": "edit", "clip_video_keys": (GUIDE_VIDEO,), "clip_audio_keys": (GUIDE_AUDIO,)},
        {"clip_video_keys": (GUIDE_VIDEO,) * 4},
    ],
)
def test_a_guide_outside_a_new_part_does_not_read(bad: dict[str, Any]) -> None:
    """Only «Nueva» takes the owner's guide: the type refuses it elsewhere, as today."""
    with pytest.raises(ValidationError):
        VideoPartPlan.model_validate({"seconds": 5, "description": "Una arepa", **bad})


# ---------------------------------------------------------------------------
# the codes and the words


def test_the_codes_are_appended_in_order() -> None:
    at = RECIPE_REFUSALS.index(CODES[0])
    assert RECIPE_REFUSALS[at : at + len(CODES)] == CODES
    assert RECIPE_REFUSALS[at - 1] == "transitions_longer_than_block"


def test_every_code_has_its_spanish_words() -> None:
    assert set(AI_PART_TEXTS) == set(CODES)
    for code in CODES:
        text = ai_part_text(code)
        assert text and text.lstrip("«")[0].isupper() and text.endswith("."), code
        # no English words the owner would read (`qualify-copy-es`)
        # and never «bloque» (Deivid, D1 of the editor's mockups)
        for word in ("clip", "post", "block", "bloque", "AI ", "switch", "timeline", "ai_part"):
            assert word not in text, (code, word)
    assert ai_part_text("foreign_key") is None
    assert AI_PART_TEXTS["switched_off"] == (
        "Las partes con IA todavía no están disponibles. Quítalas para crear tu video."
    )
