"""ED-15 (m-25029105): the recipe contract v2 — photos among the stretches (D-T1), up to
three texts per part (D-T2), an effect repeated where the library v2 lets it (D-T3: fast
motion stays `segments[].speed`),
and the parent's `VideoRecipe` in seconds of the whole video, kept at its absolute times
when the parts are reordered or trimmed. One test per acceptance criterion. Offline."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from qualify_creative import schemas
from qualify_creative.effects import (
    EffectsLibrary,
    load_effects,
    parse_library,
    part_effect_problems,
    preview_file,
    text_layers_problems,
)
from qualify_creative.schemas import (
    PHOTO_SECONDS_MAX,
    PHOTO_SECONDS_MIN,
    TEXT_LAYERS_MAX,
    EffectUse,
    MediaInputs,
    PartRecipe,
    PartRef,
    SourceSegment,
    VideoPartPlan,
    VideoRecipe,
    VideoTextLayer,
    refit_video_recipe,
)

DATA = Path(__file__).parents[1] / "src" / "qualify_creative" / "effects_data"
KEY = "uploads/00000000-0000-4000-8000-000000000001/cocina.mp4"
PHOTO_KEY = "uploads/00000000-0000-4000-8000-000000000001/plato.jpg"


def _offered(version: str, names: tuple[str, ...]) -> EffectsLibrary:
    """Library `version` with `names` offered (previews in a temporary folder): the
    repetition rules apart from whether a layer is offered yet."""
    root = Path(tempfile.mkdtemp())
    raw = json.loads((DATA / f"{version}.json").read_text(encoding="utf-8"))
    for entry in raw["entries"]:
        if entry["id"] in names:
            preview = f"effects/{entry['id']}/v1/preview.webm"
            preview_file(preview, root).parent.mkdir(parents=True, exist_ok=True)
            preview_file(preview, root).write_bytes(b"webm")
            entry.update(offered=True, preview_asset=preview)
    return parse_library(raw, assets_root=root)


LAYERS = ("humo_capa", "brasas_capa", "vapor_capa")
V1 = _offered("v1", LAYERS)
V2 = _offered("v2", LAYERS)


def _smoke(start: float | None = None, end: float | None = None) -> EffectUse:
    return EffectUse(
        effect_id="humo_capa", version=1, params={"zone": "top"}, start_s=start, end_s=end
    )


def _codes(problems: tuple) -> list[str]:
    return [p.code for p in problems]


def _types(exc: ValidationError) -> list[str]:
    return [e["type"] for e in exc.errors()]


# ---------------------------------------------------------------------------
# No type of the recipe forbids unknown keys (stored briefs, the screen's own keys)


def test_no_recipe_type_forbids_extra_keys() -> None:
    types: tuple[type[BaseModel], ...] = (
        EffectUse,
        VideoTextLayer,
        SourceSegment,
        VideoPartPlan,
        PartRef,
        PartRecipe,
        VideoRecipe,
        MediaInputs,
        schemas.ContentBrief,
    )
    for model in types:
        assert model.model_config.get("extra") != "forbid", model.__name__
    stray = SourceSegment.model_validate({"key": KEY, "start_s": 0, "end_s": 2, "nuevo": 1})
    assert stray == SourceSegment(key=KEY, start_s=0, end_s=2)
    assert MediaInputs.model_validate({"edit_recipe": {"x": 1}}) == MediaInputs()


# ---------------------------------------------------------------------------
# D-T1: a photo is a SourceSegment of kind "photo", in the same tuple as the videos


def test_a_stretch_without_kind_is_a_video() -> None:
    stored = {"key": KEY, "start_s": 2.0, "end_s": 62.0, "speed": 12.0, "rotate": 90}
    segment = SourceSegment.model_validate(stored)
    assert segment.kind == "video" and segment.output_seconds == 5.0
    assert {k: v for k, v in segment.model_dump().items() if k != "kind"} == stored


def test_a_photo_fits_a_source_segment() -> None:
    photo = SourceSegment(key=PHOTO_KEY, start_s=0, end_s=3, rotate=270, kind="photo")
    assert (photo.speed, photo.rotate, photo.output_seconds) == (1.0, 270, 3.0)
    video = SourceSegment(key=KEY, start_s=4, end_s=8)
    plan = VideoPartPlan(mode="local", seconds=7, segments=(video, photo))
    assert [s.kind for s in plan.segments] == ["video", "photo"]  # order = video order
    for seconds in (PHOTO_SECONDS_MIN, PHOTO_SECONDS_MAX):
        assert SourceSegment(key=PHOTO_KEY, start_s=0, end_s=seconds, kind="photo")


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"start_s": 0, "end_s": 3, "speed": 2.0}, "photo_with_speed"),
        ({"start_s": 0, "end_s": 0.5}, "photo_length_out_of_range"),
        ({"start_s": 0, "end_s": 6.0}, "photo_length_out_of_range"),
        ({"start_s": 1.0, "end_s": 3.0}, "photo_not_from_start"),
    ],
)
def test_a_photo_outside_its_rules_is_refused_with_its_code(
    fields: dict[str, Any], code: str
) -> None:
    with pytest.raises(ValidationError) as refused:
        SourceSegment.model_validate({"key": PHOTO_KEY, "kind": "photo", **fields})
    assert _types(refused.value) == [code]
    assert code in schemas.RECIPE_REFUSALS


# ---------------------------------------------------------------------------
# D-T2: up to three texts; the old `text_layer` reads as `text_layers` of one


def test_an_old_text_layer_reads_as_text_layers_of_one() -> None:
    layer = {"text": "Shawarma mixto", "place": "top", "start_s": 0.5, "end_s": None}
    words = VideoTextLayer.model_validate(layer)
    assert PartRecipe.model_validate(
        {"index": 1, "seconds": 5, "text_layer": layer}
    ).text_layers == (words,)
    plan = VideoPartPlan.model_validate({"seconds": 5, "text_layer": layer})
    assert plan.text_layers == (words,) and "text_layer" not in plan.model_dump()
    ref = PartRef.model_validate({"index": 2, "seconds": 5, "text_layer": layer})
    assert ref.text_layers == (words,)
    brief_media = MediaInputs.model_validate({"text_layer": layer})
    assert brief_media.text_layers == (words,)
    assert MediaInputs.model_validate({"text_layer": None}).text_layers == ()
    # both keys (the screen while it moves to v2): the old one once, first
    other = {"text": "Pide ya", "place": "bottom"}
    both = MediaInputs.model_validate({"text_layer": layer, "text_layers": [layer, other]})
    assert [t.text for t in both.text_layers] == ["Shawarma mixto", "Pide ya"]
    apart = MediaInputs.model_validate({"text_layer": layer, "text_layers": [other]})
    assert [t.text for t in apart.text_layers] == ["Shawarma mixto", "Pide ya"]


def test_an_old_text_layer_reads_in_a_stored_brief() -> None:
    from qualify_creative.enums import ContentFormat, ContentKind

    fixture = Path(__file__).parent / "fixtures" / "briefs_f55f1d73" / "clip.json"
    stored = json.loads(fixture.read_text(encoding="utf-8"))
    stored["media"]["text_layer"] = {"text": "Hola", "place": "middle"}
    brief = schemas.ContentBrief.model_validate(stored)
    assert brief.kind is ContentKind.CLIP and brief.format is ContentFormat.REELS_9_16
    assert brief.media.text_layers == (VideoTextLayer(text="Hola", place="middle"),)


def test_more_than_three_texts_is_refused_with_its_code() -> None:
    four = tuple(
        VideoTextLayer(text=f"Texto {i}", start_s=float(i), end_s=i + 1.0)
        for i in range(TEXT_LAYERS_MAX + 1)
    )
    for build in (
        lambda: PartRecipe(index=1, seconds=5, text_layers=four),
        lambda: VideoPartPlan(seconds=5, text_layers=four),
        lambda: MediaInputs(text_layers=four),
        lambda: VideoRecipe(parts=(PartRecipe(index=1, seconds=5),), text_layers=four),
    ):
        with pytest.raises(ValidationError) as refused:
            build()
        assert _types(refused.value) == ["too_many_texts"]
    assert _codes(text_layers_problems(four, part=1)) == ["too_many_texts"]


def test_two_texts_in_the_same_place_that_overlap_are_refused() -> None:
    first = VideoTextLayer(text="Uno", place="top", start_s=0.0, end_s=3.0)
    clash = VideoTextLayer(text="Dos", place="top", start_s=2.0, end_s=4.0)
    after = VideoTextLayer(text="Dos", place="top", start_s=3.0, end_s=4.0)  # meets: fine
    below = VideoTextLayer(text="Tres", place="bottom", start_s=0.0)  # other place: fine
    window = (0.0, 5.0)
    problems = text_layers_problems((first, clash, below), part=2, window=window)
    assert [(p.code, p.part, p.field) for p in problems] == [("texts_overlap", 2, "text_layers[1]")]
    assert text_layers_problems((first, after, below), part=2, window=window) == ()
    # «until the end» (end_s None) overlaps anything after it in the same place
    open_ended = VideoTextLayer(text="Uno", place="top", start_s=1.0)
    assert _codes(text_layers_problems((open_ended, after), part=1, window=window)) == [
        "texts_overlap"
    ]


# ---------------------------------------------------------------------------
# ED-15: repeating an effect is the library's `max_per_part`, never EffectUse's


def test_v2_lets_an_effect_repeat_v1_still_refuses_it() -> None:
    uses = (_smoke(0.0, 1.0), _smoke(2.0, 3.0))
    assert EffectUse.model_fields.keys() == {"effect_id", "version", "params", "start_s", "end_s"}
    kwargs = {"part": 1, "mode": "reference", "has_own_video": False, "window": (0.0, 5.0)}
    assert part_effect_problems(uses, V2, **kwargs) == ()
    assert _codes(part_effect_problems(uses, V1, **kwargs)) == ["too_many_of_effect"]
    four = (*uses, _smoke(3.0, 4.0), _smoke(4.0, 5.0))  # v2 allows 3 of a layer
    assert _codes(part_effect_problems(four, V2, **kwargs)) == ["too_many_of_effect"]


def test_v2_is_v1_but_for_max_per_part() -> None:
    v1, v2 = load_effects("v1"), load_effects("v2")
    assert load_effects() is v2 and (v1.version, v2.version) == (1, 2)
    assert [(e.id, e.version) for e in v1.entries] == [(e.id, e.version) for e in v2.entries]
    for old, new in zip(v1.entries, v2.entries, strict=True):
        assert old.model_dump(exclude={"max_per_part"}) == new.model_dump(exclude={"max_per_part"})
        assert old.max_per_part == 1
        assert new.max_per_part == (3 if new.id in LAYERS else 1)
    fast = v2.get("camara_rapida", 1)
    assert fast is not None and not fast.offered  # D-T3: fast motion is segments[].speed


def test_the_same_effect_overlapping_itself_is_refused() -> None:
    kwargs = {"part": 3, "mode": "reference", "has_own_video": False, "window": (0.0, 5.0)}
    clash = (_smoke(0.0, 2.0), _smoke(1.0, 3.0))
    problems = part_effect_problems(clash, V2, **kwargs)
    assert [(p.code, p.part, p.field, p.effect_id) for p in problems] == [
        ("effect_uses_overlap", 3, "effects[1]", "humo_capa")
    ]
    # a use with no span covers the whole part: a repeated effect names its times
    whole = (_smoke(), _smoke(1.0, 2.0))
    assert _codes(part_effect_problems(whole, V2, **kwargs)) == ["effect_uses_overlap"]


# ---------------------------------------------------------------------------
# The parent's VideoRecipe, and a recipe of 2 videos, 1 photo, 3 texts, 1 effect twice


def _full_part() -> PartRecipe:
    return PartRecipe(
        index=1,
        mode="local",
        seconds=8.0,
        segments=(
            SourceSegment(key=KEY, start_s=0.0, end_s=3.0),
            SourceSegment(key=PHOTO_KEY, start_s=0.0, end_s=2.0, kind="photo", rotate=90),
            SourceSegment(key=KEY, start_s=10.0, end_s=16.0, speed=2.0),
        ),
        text_layers=(
            VideoTextLayer(text="Shawarma mixto", place="top", start_s=0.0, end_s=3.0),
            VideoTextLayer(text="Recién hecho", place="top", start_s=3.0),
            VideoTextLayer(text="Pide ya", place="bottom", start_s=5.0, end_s=8.0),
        ),
        effects=(_smoke(0.0, 2.0), _smoke(5.0, 7.0)),
    )


def test_a_full_recipe_round_trips_unchanged() -> None:
    part = _full_part()
    assert PartRecipe.model_validate(part.model_dump()) == part
    assert PartRecipe.model_validate_json(part.model_dump_json()) == part
    assert PartRecipe.model_validate(json.loads(part.model_dump_json())) == part
    whole = VideoRecipe(
        parts=(part, PartRecipe(index=2, seconds=4.0)),
        text_layers=(VideoTextLayer(text="Todo el video", place="middle", start_s=6.0),),
        effects=(_smoke(9.0, 11.0), _smoke(11.0, 12.0)),
    )
    assert VideoRecipe.model_validate(whole.model_dump()) == whole
    assert VideoRecipe.model_validate_json(whole.model_dump_json()) == whole
    assert whole.seconds == 12.0
    media = MediaInputs(video_recipe=whole)
    assert MediaInputs.model_validate(json.loads(media.model_dump_json())) == media
    kwargs = {"part": 1, "mode": "local", "has_own_video": True, "window": (0.0, 8.0)}
    assert part_effect_problems(part.effects, V2, **kwargs) == ()
    assert text_layers_problems(part.text_layers, part=1, window=(0.0, 8.0)) == ()


def test_a_video_recipe_numbers_its_parts_in_order() -> None:
    with pytest.raises(ValidationError, match="numbered"):
        VideoRecipe(parts=(PartRecipe(index=2, seconds=4.0),))
    with pytest.raises(ValidationError):
        VideoRecipe(parts=())


# ---------------------------------------------------------------------------
# Reordering or trimming: each whole-video block keeps its absolute time


def test_refit_keeps_absolute_times_and_cuts_at_the_new_end() -> None:
    one = PartRecipe(index=1, seconds=5.0, text_layers=(VideoTextLayer(text="De la parte"),))
    two = PartRecipe(index=2, seconds=4.0)
    three = PartRecipe(index=3, seconds=3.0)
    early = VideoTextLayer(text="Hola", place="top", start_s=1.0, end_s=4.0)
    long = VideoTextLayer(text="Pide ya", place="bottom", start_s=6.0, end_s=11.0)
    late = VideoTextLayer(text="Al final", place="middle", start_s=10.0)
    span = _smoke(7.0, 10.0)
    gone = _smoke(9.5, 12.0)
    everywhere = EffectUse(effect_id="vapor_capa", version=1)
    recipe = VideoRecipe(
        parts=(one, two, three),
        text_layers=(early, long, late),
        effects=(span, gone, everywhere),
    )
    assert recipe.seconds == 12.0
    # reordered: same length, every block at its own second, parts renumbered
    reordered = refit_video_recipe(recipe, (three, one, two))
    assert [(p.index, p.seconds) for p in reordered.recipe.parts] == [(1, 3.0), (2, 5.0), (3, 4.0)]
    assert reordered.recipe.parts[1].text_layers == one.text_layers  # moves with its part
    assert reordered.recipe.text_layers == recipe.text_layers
    assert reordered.recipe.effects == recipe.effects
    assert reordered.dropped_text_layers == () and reordered.dropped_effects == ()
    # part 3 taken out: the video ends at 9 s
    trimmed = refit_video_recipe(recipe, (one, two))
    assert trimmed.recipe.seconds == 9.0
    assert trimmed.recipe.text_layers == (early, long.model_copy(update={"end_s": 9.0}))
    assert trimmed.recipe.effects == (span.model_copy(update={"end_s": 9.0}), everywhere)
    assert trimmed.dropped_text_layers == (late,) and trimmed.dropped_effects == (gone,)


def test_refit_with_no_parts_is_a_clear_error() -> None:
    recipe = VideoRecipe(parts=(PartRecipe(index=1, seconds=5.0),))
    with pytest.raises(ValueError, match="at least one part"):
        refit_video_recipe(recipe, ())
