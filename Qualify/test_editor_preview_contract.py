"""ED-01 (m-25026605): the editor preview's data contract — EF-02's names, validation,
rounding round trip, the half-second rules of «Cortar» and #674's text design."""

from __future__ import annotations

from pathlib import Path

import pytest

from . import editor_preview_contract as c


def _recipe() -> c.PartRecipe:
    return c.PartRecipe(
        effects=(
            c.EffectUse("vapor_capa", 1),
            c.EffectUse("camara_rapida", 1, (("speed", 10.0),)),
        ),
        text_layer=c.VideoTextLayer(text="Shawarma recién hecho", place="top"),
        segments=(c.SourceSegment("uploads/t/v.mp4", 4.0, 12.0, speed=10.0, rotate=90),),
    )


def test_field_names_are_ef02s() -> None:
    assert list(c.SourceSegment.__dataclass_fields__) == [
        "key",
        "start_s",
        "end_s",
        "speed",
        "rotate",
        "kind",  # ED-15
    ]
    assert list(c.VideoTextLayer.__dataclass_fields__) == [
        "text",
        "place",
        "start_s",
        "end_s",
        "layout_id",
        "layout_version",
        "fade_s",  # EF-05
    ]
    assert list(c.EffectUse.__dataclass_fields__) == [
        "effect_id",
        "version",
        "params",
        "start_s",
        "end_s",
    ]
    assert list(c.PartRecipe.__dataclass_fields__) == [
        "effects",
        "text_layer",
        "segments",
        "text_layers",  # ED-15
    ]
    assert c.SourceSegment("k", 0, 2).kind == "video"
    assert c.SourceSegment("k", 0, 2).speed == 1.0
    assert c.SourceSegment("k", 0, 2).rotate == 0
    assert c.VideoTextLayer("x").place == "bottom"


def test_round_trip_rounds_to_the_hundredth() -> None:
    recipe = c.PartRecipe(
        segments=(c.SourceSegment("k", 1.23456, 5.98765, speed=2.0),),
        effects=(c.EffectUse("humo_capa", 1, (("intensity", 0.66666),), 0.111, 2.222),),
    )
    data = c.to_dict(recipe)
    assert data["segments"] == [
        {"key": "k", "start_s": 1.23, "end_s": 5.99, "speed": 2.0, "rotate": 0}  # v1's shape
    ]
    photo = c.to_dict(c.PartRecipe(segments=(c.SourceSegment("p", 0, 3, kind="photo"),)))
    assert photo["segments"][0]["kind"] == "photo"  # type: ignore[index]
    assert data["text_layers"] == []
    assert data["effects"][0]["params"] == {"intensity": 0.67}  # type: ignore[index]
    assert data["text_layer"] is None
    back = c.from_dict(data)
    assert back.segments[0].start_s == 1.23
    assert c.to_dict(back) == data


def test_round_trip_of_a_whole_recipe() -> None:
    data = c.to_dict(_recipe())
    assert c.from_dict(data) == _recipe()
    assert data["text_layer"] == {
        "text": "Shawarma recién hecho",
        "place": "top",
        "start_s": 0.0,
        "end_s": None,
        "layout_id": None,
        "layout_version": None,
    }
    designed = c.VideoTextLayer("Hoy", layout_id="scrim", layout_version=1)
    again = c.from_dict(c.to_dict(c.PartRecipe(text_layer=designed)))
    assert again.text_layer == designed


def test_from_dict_refuses_a_shape_it_does_not_know() -> None:
    with pytest.raises(ValueError):
        c.from_dict({"segments": "nope"})
    with pytest.raises(ValueError):
        c.from_dict({"effects": [{"effect_id": "x", "params": [1]}]})
    with pytest.raises(ValueError):
        c.from_dict({"segments": [{"key": "k", "start_s": True, "end_s": 2}]})


def test_segment_problems() -> None:
    assert c.segment_problems(c.SourceSegment("k", 4, 12), 20) == []
    assert c.segment_problems(c.SourceSegment("k", 4, 4.5), 20) == ["too_short"]
    assert c.segment_problems(c.SourceSegment("k", 5, 4), 20) == ["ends_before_start"]
    assert c.segment_problems(c.SourceSegment("k", 4, 25), 20) == ["outside_video"]
    assert c.segment_problems(c.SourceSegment("k", 4, 25), 0) == []  # length not known yet
    assert c.segment_problems(c.SourceSegment("", 0, 2), 0) == ["empty_key"]
    assert c.segment_problems(c.SourceSegment("k", 0, 2, rotate=45), 0) == ["bad_rotate"]
    assert c.segment_problems(c.SourceSegment("k", 0, 2, speed=61), 0) == ["bad_speed"]


def test_recipe_problems() -> None:
    assert c.recipe_problems(_recipe()) == []
    bad = c.PartRecipe(
        effects=(c.EffectUse("Vapor", 0), c.EffectUse("Vapor", 1, (), 1.0, None)),
        text_layer=c.VideoTextLayer(" ", place="side"),
    )
    problems = c.recipe_problems(bad)
    for code in (
        "bad_effect_id",
        "bad_effect_version",
        "effect_uses_overlap",  # ED-15: was `effect_twice`
        "effect_span",
        "text_empty",
        "bad_text_place",
    ):
        assert code in problems
    many = c.PartRecipe(effects=tuple(c.EffectUse(f"e{i}") for i in range(9)))
    assert "too_many_effects" in c.recipe_problems(many)
    assert "text_too_long" in c.recipe_problems(
        c.PartRecipe(text_layer=c.VideoTextLayer("a" * 121))
    )


# -- ED-15 (m-25029105): contract v2 -----------------------------------------------------


def test_v2_limits() -> None:
    assert c.TEXT_LAYERS_MAX == 3
    assert (c.PHOTO_SECONDS_MIN, c.PHOTO_SECONDS_MAX) == (1.0, 5.0)
    assert c.SEGMENT_KINDS == ("video", "photo")


def test_text_layer_and_text_layers_stay_in_step() -> None:
    first, second = c.VideoTextLayer("Hoy", place="top"), c.VideoTextLayer("Ya", end_s=3)
    alone = c.PartRecipe(text_layer=first)
    assert alone.text_layers == (first,) and alone.text_layer == first
    both = c.PartRecipe(text_layers=(first, second))
    assert both.text_layer == first
    assert c.PartRecipe(text_layer=first, text_layers=(first, second)).text_layers == (
        first,
        second,
    )
    assert c.PartRecipe(text_layer=first, text_layers=(second,)).text_layers == (first, second)
    assert c.PartRecipe().text_layer is None and c.PartRecipe().text_layers == ()


def test_a_v1_recipe_reads_the_same() -> None:
    v1 = {
        "effects": [{"effect_id": "humo_capa", "version": 1, "params": {}}],
        "text_layer": {"text": "Hoy", "place": "top", "layout_id": "scrim", "layout_version": 1},
        "segments": [{"key": "k", "start_s": 0, "end_s": 4, "speed": 2, "rotate": 90}],
    }
    recipe = c.from_dict(v1)
    assert recipe.segments[0].kind == "video"
    assert recipe.text_layers == (recipe.text_layer,)
    assert recipe.text_layer == c.VideoTextLayer(
        "Hoy", place="top", layout_id="scrim", layout_version=1
    )
    assert c.recipe_problems(recipe) == []


def test_a_v2_recipe_round_trips() -> None:
    texts = (
        c.VideoTextLayer("Abre hoy", place="top", start_s=0, end_s=3),
        c.VideoTextLayer("Pide ya", place="top", start_s=3, end_s=6),
        c.VideoTextLayer("Domicilios", place="bottom"),
    )
    recipe = c.PartRecipe(
        effects=(
            c.EffectUse("humo_capa", 1, (), 0.0, 2.0),
            c.EffectUse("humo_capa", 1, (), 4.0, 6.0),
        ),
        segments=(
            c.SourceSegment("a.mp4", 0, 4),
            c.SourceSegment("p.jpg", 0, 3, kind="photo", rotate=90),
            c.SourceSegment("b.mp4", 2, 6, speed=2.0),
        ),
        text_layers=texts,
    )
    assert c.recipe_problems(recipe) == []
    assert all(c.segment_problems(s, 0) == [] for s in recipe.segments)
    data = c.to_dict(recipe)
    assert data["text_layer"] == data["text_layers"][0]  # type: ignore[index]
    assert c.from_dict(data) == recipe
    assert c.used_seconds(recipe.segments) == 8.0  # the photo is not the owner's video


def test_v2_problems() -> None:
    four = c.PartRecipe(
        text_layers=tuple(c.VideoTextLayer(f"t{i}", start_s=i, end_s=i + 1) for i in range(4))
    )
    assert "too_many_texts" in c.recipe_problems(four)
    top_twice = c.PartRecipe(
        text_layers=(
            c.VideoTextLayer("a", place="top", end_s=4),
            c.VideoTextLayer("b", place="top", start_s=2, end_s=6),
        )
    )
    assert c.recipe_problems(top_twice) == ["texts_overlap"]
    stacked = c.PartRecipe(
        effects=(
            c.EffectUse("vapor_capa", 1, (), 0.0, 3.0),
            c.EffectUse("vapor_capa", 1, (), 2.0, 5.0),
        )
    )
    assert c.recipe_problems(stacked) == ["effect_uses_overlap"]
    whole_and_span = c.PartRecipe(
        effects=(c.EffectUse("vapor_capa"), c.EffectUse("vapor_capa", 1, (), 2.0, 5.0))
    )
    assert c.recipe_problems(whole_and_span) == ["effect_uses_overlap"]


def test_photo_problems() -> None:
    photo = c.SourceSegment
    assert c.segment_problems(photo("p", 0, 1, kind="photo"), 0) == []
    assert c.segment_problems(photo("p", 0, 3, speed=2.0, kind="photo"), 0) == ["photo_with_speed"]
    assert c.segment_problems(photo("p", 0, 6, kind="photo"), 0) == ["photo_length_out_of_range"]
    assert c.segment_problems(photo("p", 0, 0.5, kind="photo"), 0) == ["photo_length_out_of_range"]
    assert c.segment_problems(photo("p", 1, 3, kind="photo"), 0) == ["photo_not_from_start"]
    assert c.segment_problems(photo("p", 0, 2, kind="gif"), 0) == ["bad_kind"]


def test_whole_video_is_up_to_fifteen_seconds() -> None:
    assert c.whole_video("k", 8.4) == c.SourceSegment("k", 0.0, 8.5)  # on the grid
    assert c.whole_video("k", 8) == c.SourceSegment("k", 0.0, 8.0)
    assert (c.grid_end(7.33), c.max_units(7.33), c.max_units(0)) == (7.5, 15, 2)
    assert c.whole_video("k", 40) == c.SourceSegment("k", 0.0, 15.0)


def test_nudge_keeps_one_second_and_the_video() -> None:
    assert c.nudge(4, 12, handle="start", delta=0.5, source_duration_s=20) == (4.5, 12)
    assert c.nudge(4, 12, handle="end", delta=-0.5, source_duration_s=20) == (4, 11.5)
    assert c.nudge(4, 5, handle="start", delta=0.5, source_duration_s=20) == (4, 5)  # < 1 s
    assert c.nudge(0, 5, handle="start", delta=-0.5, source_duration_s=20) == (0, 5)
    assert c.nudge(4, 20, handle="end", delta=0.5, source_duration_s=20) == (4, 20)


def test_clamp_stretch() -> None:
    assert c.clamp_stretch(3.3, 7.8, 20) == (3.5, 8.0)
    assert c.clamp_stretch(19.5, 19.5, 20) == (19.0, 20.0)
    assert c.clamp_stretch(2, 30, 10) == (2.0, 10.0)
    assert c.clamp_stretch(0, 30, 7.33) == (0.0, 7.5)  # the grid's end, never lost


def test_rotate_and_seconds() -> None:
    assert [c.rotate_quarter(r) for r in (0, 90, 180, 270)] == [90, 180, 270, 0]
    segments = (c.SourceSegment("k", 4, 12, speed=10), c.SourceSegment("k", 0, 2))
    assert c.used_seconds(segments) == 10
    assert c.output_seconds(segments) == 2.8


def test_preview_rate_stops_at_sixteen() -> None:
    assert c.preview_rate(10) == 10
    assert c.preview_rate(20) == 16
    assert c.preview_is_slower(20) and not c.preview_is_slower(16)


def test_effects_offered() -> None:
    assert [e.effect_id for e in c.effects_offered(has_own_video=True)] == [
        "vapor_capa",
        "humo_capa",
        "brasas_capa",
        "camara_rapida",
    ]
    assert "camara_rapida" not in [e.effect_id for e in c.effects_offered(has_own_video=False)]
    vapor = c.effect_of("vapor_capa")
    assert vapor is not None and vapor.preview_asset == "effects/vapor_capa/v1/preview.webm"
    assert vapor.blend == "screen"


def test_only_existing_layers_are_offered(tmp_path: Path) -> None:
    vapor, fast = c.effect_of("vapor_capa"), c.effect_of("camara_rapida")
    assert vapor is not None and fast is not None
    assert not c.effect_available(vapor, tmp_path)
    assert c.effect_available(fast, tmp_path)  # no file: the preview simulates it
    loop = tmp_path / "effects" / "vapor_capa" / "v1" / "preview.webm"
    loop.parent.mkdir(parents=True)
    loop.write_bytes(b"x")
    assert c.effect_available(vapor, tmp_path)


def test_a_missing_preview_loop_gives_no_address(tmp_path: Path) -> None:
    vapor = c.effect_of("vapor_capa")
    assert vapor is not None
    assert c.preview_effect_url(vapor, tmp_path) == ""
    loop = tmp_path / "effects" / "vapor_capa" / "v1" / "preview.webm"
    loop.parent.mkdir(parents=True)
    loop.write_bytes(b"x")
    assert c.preview_effect_url(vapor, tmp_path) == "/effects/vapor_capa/v1/preview.webm"
    sneaky = c.PreviewEffect("x", "X", "compose", preview_asset="effects/../secret.webm")
    assert c.preview_effect_url(sneaky, tmp_path) == ""


def test_text_design_is_674s_scrim() -> None:
    top = c.text_design("top")
    assert (top.layout_id, top.layout_version, top.anchor) == ("scrim", 3, "top")
    assert top.top == round(270 / 1920, 4) and top.bottom == 0.2
    assert (top.font_px_max, top.font_px_min) == (112, 76)
    assert c.text_design("middle").anchor == "middle"
    assert c.text_is_long("a" * 33) and not c.text_is_long("a" * 32)


def test_words() -> None:
    assert c.seconds_text(8) == "8"
    assert c.seconds_text(8.5) == "8,5"
    assert c.clock_text(4) == "0:04"
    assert c.clock_text(62) == "1:02"
    assert c.clock_text(4.5) == "0:04,5"


def test_a_text_without_start_begins_with_its_part() -> None:
    """EF-02: `start_s` 0.0 = from the start of its part (seconds of the part's output,
    so it moves with the part); a null start in the JSON is read as 0.0."""
    layer = c.VideoTextLayer("Hoy")
    assert layer.start_s == 0.0
    recipe = c.PartRecipe(text_layer=layer)
    data = c.to_dict(recipe)
    assert data["text_layer"]["start_s"] == 0.0  # type: ignore[index]
    assert c.from_dict(data).text_layer == layer
    nulled = {**data, "text_layer": {**data["text_layer"], "start_s": None}}  # type: ignore[dict-item]
    assert c.from_dict(nulled).text_layer == layer
    assert c.recipe_problems(recipe) == []
    late = c.PartRecipe(text_layer=c.VideoTextLayer("Hoy", start_s=2.0, end_s=1.0))
    assert "text_span" in c.recipe_problems(late)


def test_speeds_are_the_ones_the_backend_makes() -> None:
    """EF-04's own bounds (light import: no PyAV)."""
    from qualify_creative.video import speed

    assert (c.SEGMENT_SPEED_MIN, c.SEGMENT_SPEED_MAX) == (speed.MIN_SPEED, speed.MAX_SPEED)
    assert "bad_speed" in c.segment_problems(c.SourceSegment("k", 0, 8, speed=0.5), 10.0)


def test_a_text_design_is_both_or_neither() -> None:
    def problems(layer: c.VideoTextLayer) -> list[str]:
        return c.recipe_problems(c.PartRecipe(text_layer=layer))

    assert "bad_text_layout" in problems(c.VideoTextLayer("Hoy", layout_id="scrim"))
    assert "bad_text_layout" in problems(c.VideoTextLayer("Hoy", layout_version=1))
    bad_version = c.VideoTextLayer("Hoy", layout_id="scrim", layout_version=0)
    assert "bad_text_layout" in problems(bad_version)
    assert problems(c.VideoTextLayer("Hoy", layout_id="scrim", layout_version=1)) == []
    assert problems(c.VideoTextLayer("Hoy")) == []


def test_the_text_design_is_the_image_catalog_s_current_one() -> None:
    """ADR 50 D1: the video text uses the image catalog's designs. Its copied version and
    title limit must be the catalog's, or the backend flags every edited text
    `unknown_layout` (2026-11-15: the catalog went to layout_version 2, this stayed at 1)."""
    from qualify_creative.effects import text_layer_problems
    from qualify_creative.layer_spec import LAYOUT_VERSION, catalog
    from qualify_creative.schemas import VideoTextLayer

    assert c.TEXT_LAYOUT_VERSION == LAYOUT_VERSION
    scrim = catalog()["layouts"][c.TEXT_LAYOUT_ID]
    assert scrim["slots"]["title"]["9:16"][0] == c.TITLE_MAX_CHARS
    layer = VideoTextLayer(
        text="Hoy", layout_id=c.TEXT_LAYOUT_ID, layout_version=c.TEXT_LAYOUT_VERSION
    )
    assert text_layer_problems(layer, part=None) == ()


# -- EF-05 (m-25026573): the fade the owner chooses ---------------------------------------


def test_a_text_fade_is_chosen_between_its_limits() -> None:
    assert (c.VIDEO_TEXT_FADE_MIN_S, c.VIDEO_TEXT_FADE_DEFAULT_S, c.VIDEO_TEXT_FADE_MAX_S) == (
        0.3,
        0.5,
        1.0,
    )

    def problems(fade: float) -> list[str]:
        return c.recipe_problems(c.PartRecipe(text_layer=c.VideoTextLayer("Hoy", fade_s=fade)))

    assert problems(0.3) == [] and problems(1.0) == [] and problems(0.5) == []
    assert "bad_text_fade" in problems(0.29)
    assert "bad_text_fade" in problems(1.01)
    assert c.VideoTextLayer("Hoy").fade_s == 0.5


def test_a_text_fade_round_trips_and_an_old_text_reads_the_default() -> None:
    recipe = c.PartRecipe(text_layers=(c.VideoTextLayer("Hoy", place="top", fade_s=0.8),))
    data = c.to_dict(recipe)
    assert data["text_layers"][0]["fade_s"] == 0.8  # type: ignore[index]
    assert c.from_dict(data) == recipe
    old = {"text_layers": [{"text": "Hoy", "place": "top", "start_s": 0, "end_s": None}]}
    assert c.from_dict(old).text_layers[0].fade_s == 0.5
