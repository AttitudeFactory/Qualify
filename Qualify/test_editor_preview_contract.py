"""ED-01 (m-25026605): the editor preview's data contract — EF-02's names, validation,
rounding round trip, the half-second rules of «Cortar» and #674's text design."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import get_args

import pytest

from . import editor_preview_contract as c

#: The render's own vectors for `boxInk` (ED-13): the preview's mirror reads the same file.
_BOX_INK_VECTORS = (
    Path(__file__).parents[1] / "packages" / "render" / "server" / "box-ink-vectors.json"
)


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
        "transition_in",  # m-25114465: the join into this block, always last
    ]
    assert list(c.VideoTextLayer.__dataclass_fields__) == [
        "text",
        "place",
        "start_s",
        "end_s",
        "layout_id",
        "layout_version",
        "fade_s",  # EF-05
        "motion_in",  # ED-13
        "motion_out",  # ED-13
        "box_color",  # ED-13 (round 2)
        "text_color",
        "text_size",  # ED-13 round 4  # ED-13 (round 3)
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
    assert not c.is_backend_effect_url("/effects/vapor_capa/v1/preview.webm")


def _platform(key: str) -> c.PreviewEffect:
    return c.PreviewEffect("humo_denso", "Humo denso", "compose", preview_asset=key)


def test_an_r2_platform_preview_is_its_r2effects_route(tmp_path: Path) -> None:
    """m-25120474: `platform/effects/<id>/v<n>/preview.mp4` → `/r2effects/<id>/v<n>`, a
    path on the BACKEND's origin (the caller puts the origin in front); offered without a
    local file — nothing in `assets/` is needed."""
    effect = _platform("platform/effects/humo_denso/v1/preview.mp4")
    url = c.preview_effect_url(effect, tmp_path)
    assert url == "/r2effects/humo_denso/v1"
    assert c.is_backend_effect_url(url)
    assert c.effect_available(effect, tmp_path)
    assert c.preview_effect_url(_platform("platform/effects/a1_b/v9999/preview.mp4"), tmp_path)


@pytest.mark.parametrize(
    "key",
    [
        "platform/effects/../v1/preview.mp4",
        "platform/effects/humo_denso/../../secret/preview.mp4",
        "platform/effects/humo_denso/v1/../preview.mp4",
        "platform/effects/Humo_Denso/v1/preview.mp4",
        "PLATFORM/effects/humo_denso/v1/preview.mp4",
        "platform/effects/humo_denso/V1/preview.mp4",
        "platform/effects/humo_denso/v0/preview.mp4",
        "platform/effects/humo_denso/v01/preview.mp4",
        "platform/effects/humo_denso/v10000/preview.mp4",
        "platform/effects/humo_denso/v1/preview.webm",
        "platform/effects/humo_denso/v1/other.mp4",
        "platform/effects/humo_denso/v1/preview.mp4/x",
        "platform/effects/humo_denso/preview.mp4",
        "platform/effects/1humo/v1/preview.mp4",
        "platform/effects/" + "a" * 41 + "/v1/preview.mp4",
        "/platform/effects/humo_denso/v1/preview.mp4",
        "t/tenant/platform/effects/humo_denso/v1/preview.mp4",
    ],
)
def test_a_malformed_platform_key_gives_no_address(tmp_path: Path, key: str) -> None:
    effect = _platform(key)
    assert c.preview_effect_url(effect, tmp_path) == ""
    assert not c.effect_available(effect, tmp_path)


@pytest.mark.parametrize(
    "key",
    [
        "platform/effects/humo_denso/v1/preview.mp4",
        "platform/effects/z/v42/preview.mp4",
        "platform/effects/Humo/v1/preview.mp4",
        "platform/effects/humo/v01/preview.mp4",
        "platform/effects/humo/v1/preview.webm",
        "platform/effects/../v1/preview.mp4",
    ],
)
def test_the_editor_and_the_route_agree_on_every_key(tmp_path: Path, key: str) -> None:
    """The editor's pattern is the server's (`effect_preview_routes.path_for_key`)."""
    from qualify_api.http.effect_preview_routes import path_for_key  # noqa: PLC0415

    assert c.preview_effect_url(_platform(key), tmp_path) == path_for_key(key)


def test_the_local_layers_keep_their_assets_address(tmp_path: Path) -> None:
    """The three library loops already under `assets/effects/` do not change."""
    for effect_id in ("vapor_capa", "humo_capa", "brasas_capa"):
        effect = c.effect_of(effect_id)
        assert effect is not None and effect.preview_asset
        loop = tmp_path / effect.preview_asset
        loop.parent.mkdir(parents=True)
        loop.write_bytes(b"x")
        url = c.preview_effect_url(effect, tmp_path)
        assert url == "/" + effect.preview_asset
        assert url.startswith("/effects/") and not c.is_backend_effect_url(url)


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


# -- ED-13 (m-25029108): backgrounds and motions — the shared contract's mirror ---------------


def test_ed13_constants_are_the_contracts() -> None:
    assert c.VIDEO_TEXT_MOTIONS_IN == ("fade", "slide", "zoom", "typewriter")
    assert c.VIDEO_TEXT_MOTIONS_OUT == ("none", "fade", "slide", "zoom")
    assert (c.VIDEO_TEXT_MOTION_IN_DEFAULT, c.VIDEO_TEXT_MOTION_OUT_DEFAULT) == ("fade", "none")
    assert c.VIDEO_TEXT_LAYOUTS == ("scrim", "band", "brand_fill", "shadow")
    assert (c.VIDEO_TEXT_BOX_PAD_PX, c.VIDEO_TEXT_BOX_RADIUS_PX) == (48, 24)
    # «Sin fondo» has no shadow any more (Deivid 2026-11-23)
    assert not hasattr(c, "VIDEO_TEXT_SHADOW") and not hasattr(c, "text_shadow_css")
    assert (c.VIDEO_TEXT_SLIDE_FRACTION, c.VIDEO_TEXT_ZOOM_FROM) == (0.05, 0.9)
    assert c.VIDEO_TEXT_TYPEWRITER_MAX_CHARS == 40
    assert c.VIDEO_TEXT_TYPEWRITER_S_PER_CHAR == 0.06
    assert c.VIDEO_TEXT_MOTION_MAX_SHARE == 1 / 3
    # the new refusals, appended at the end (never reordered)
    assert get_args(c.RecipeProblem)[-6:] == (
        "unknown_text_motion",
        "typewriter_text_too_long",
        "bad_text_box_color",
        "bad_text_color",  # round 3
        "unknown_text_size",  # round 4
        "text_too_long_for_large",
    )
    assert c.VIDEO_TEXT_SIZES == ("small", "medium", "large")
    assert c.VIDEO_TEXT_SIZE_SCALE == {"small": 0.75, "medium": 1.0, "large": 1.25}
    assert c.VIDEO_TEXT_LARGE_MAX_CHARS == 40
    assert c.large_fits("a" * 40) and not c.large_fits("a" * 41)
    assert c.VIDEO_TEXT_TEXT_COLOR_LAYOUTS == ("shadow",)
    assert c.VIDEO_TEXT_BOX_COLOR_LAYOUTS == ("band", "brand_fill")
    assert (c.VIDEO_TEXT_INK_LIGHT, c.VIDEO_TEXT_INK_DARK) == ("#FFFFFF", "#111111")


def test_motions_travel_only_when_not_the_schemas_default() -> None:
    plain = c.to_dict(c.PartRecipe(text_layers=(c.VideoTextLayer("Hoy"),)))
    raw = plain["text_layers"][0]  # type: ignore[index]
    assert "motion_in" not in raw and "motion_out" not in raw  # v1's exact shape
    moving = c.VideoTextLayer(
        "Hoy", layout_id="band", layout_version=3, motion_in="slide", motion_out="fade"
    )
    data = c.to_dict(c.PartRecipe(text_layers=(moving,)))
    raw = data["text_layers"][0]  # type: ignore[index]
    assert (raw["motion_in"], raw["motion_out"], raw["layout_id"]) == ("slide", "fade", "band")
    assert c.from_dict(data).text_layers[0] == moving
    old = {"text_layers": [{"text": "Hoy"}]}
    layer = c.from_dict(old).text_layers[0]
    assert (layer.motion_in, layer.motion_out) == ("fade", "none")


def test_motion_and_layout_problems() -> None:
    def problems(**kw: object) -> list[str]:
        return c.recipe_problems(c.PartRecipe(text_layers=(c.VideoTextLayer(**kw),)))  # type: ignore[arg-type]

    assert problems(text="Hoy", motion_in="typewriter", motion_out="zoom") == []
    assert "unknown_text_motion" in problems(text="Hoy", motion_in="spin")
    assert "unknown_text_motion" in problems(text="Hoy", motion_out="typewriter")
    assert problems(text="a" * 40, motion_in="typewriter") == []
    assert "typewriter_text_too_long" in problems(text="a" * 41, motion_in="typewriter")
    for layout in c.VIDEO_TEXT_LAYOUTS:
        assert problems(text="Hoy", layout_id=layout, layout_version=3) == []
    assert "bad_text_layout" in problems(text="Hoy", layout_id="plate", layout_version=3)
    # ED-13: a picked colour is a #RRGGBB hex in capitals
    assert problems(text="Hoy", layout_id="band", layout_version=3, box_color="#FFE600") == []
    for bad in ("#ffe600", "#FFF", "rojo", ""):
        assert "bad_text_box_color" in problems(
            text="Hoy", layout_id="band", layout_version=3, box_color=bad
        )


def test_a_picked_box_colour_travels_only_when_there_is_one() -> None:
    plain = c.VideoTextLayer("Hoy", layout_id="band", layout_version=3)
    raw = c.to_dict(c.PartRecipe(text_layers=(plain,)))["text_layers"][0]  # type: ignore[index]
    assert "box_color" not in raw
    picked = c.VideoTextLayer("Hoy", layout_id="brand_fill", layout_version=3, box_color="#2563EB")
    data = c.to_dict(c.PartRecipe(text_layers=(picked,)))
    assert data["text_layers"][0]["box_color"] == "#2563EB"  # type: ignore[index]
    assert c.from_dict(data).text_layers[0] == picked
    assert c.from_dict({"text_layers": [{"text": "Hoy"}]}).text_layers[0].box_color is None


def test_box_ink_takes_the_shared_vectors() -> None:
    """The render's `layout.ts` `boxInk` and this mirror read the same vectors."""
    vectors = json.loads(_BOX_INK_VECTORS.read_text(encoding="utf-8"))
    assert (vectors["light"], vectors["dark"]) == (c.VIDEO_TEXT_INK_LIGHT, c.VIDEO_TEXT_INK_DARK)
    for background, ink in vectors["vectors"]:
        assert c.box_ink(background) == ink, background


def test_a_picked_colour_draws_the_box_with_legible_letters() -> None:
    palette = c.palette_of(["#0F766E", "#FFFFFF", "#F8FAFC"])
    assert c.text_box_colors("band", palette, "#FFE600") == ("#FFE600", "#111111")
    assert c.text_box_colors("brand_fill", palette, "#111111") == ("#111111", "#FFFFFF")
    # scrim and «Sin fondo» have no box: a colour means nothing there
    assert c.text_box_colors("scrim", palette, "#FFE600") == ("", "#FFFFFF")
    assert c.text_box_colors("shadow", palette, "#FFE600") == ("", "#FFFFFF")
    # none (or a bad one) = the background's default
    assert c.text_box_colors("band", palette, None) == ("#111111", "#FFFFFF")
    assert c.text_box_colors("brand_fill", palette, "#ffe600") == ("#0F766E", "#FFFFFF")
    assert c.default_box_color("band", palette) == "#111111"
    assert c.default_box_color("brand_fill", palette) == "#0F766E"
    assert c.default_box_color("shadow", palette) == ""


def test_palette_and_ink_mirror_the_render() -> None:
    """`props.ts` `paletteOf` and `engine.ts` `textColorOn` / `opaque`."""
    assert c.palette_of([]) == c.TextPalette("#0F766E", "#FFFFFF", "#F8FAFC")
    assert c.palette_of(["#123", "nope", "#ABCDEF80"]) == c.TextPalette(
        "#123", "#FFFFFF", "#ABCDEF80"
    )
    assert c.opaque("#abc") == "#AABBCC" and c.opaque("#ABCDEF80") == "#ABCDEF"
    # the catalog's finding: on #777777 only pure black clears 4.5
    color, ratio = c.text_color_on("#777777", c.TextPalette(text="#FFFFFF"))
    assert color == "#000000" and ratio >= 4.5
    # the brand's own text colour first, when it reads
    assert c.text_color_on("#0F766E", c.TextPalette(text="#FFFFFF"))[0] == "#FFFFFF"
    palette = c.palette_of(["#0F766E", "#FFFFFF", "#F8FAFC"])
    # «Franja» is fixed dark and neutral with white letters, whatever the brand's surface
    assert c.text_box_colors("band", palette) == ("#111111", "#FFFFFF")
    polette = c.palette_of(["#F4C2C2", "#5A2A27", "#FFFFFF"])
    assert c.text_box_colors("band", polette) == ("#111111", "#FFFFFF")
    assert c.text_box_colors("brand_fill", palette) == ("#0F766E", "#FFFFFF")
    assert c.text_box_colors("scrim", palette) == ("", "#FFFFFF")
    assert c.text_box_colors("shadow", palette) == ("", "#FFFFFF")
    for layout in ("band", "brand_fill"):
        background, ink = c.text_box_colors(layout, palette)
        assert c.contrast(ink, background) >= c.TEXT_MIN_CONTRAST


def test_no_shadow_in_the_preview() -> None:
    """«Sin fondo»: the preview draws the letters clean, as the final video does."""
    css = (Path(__file__).parents[1] / "assets" / "qualify-creative.css").read_text(
        encoding="utf-8"
    )
    rule = css.split('.q-edit-preview__text[data-layout="shadow"] .q-edit-preview__text-line {')[1]
    assert rule.split("}")[0].split("text-shadow:")[1].strip().startswith("none")


def _css_rules(css: str) -> list[tuple[str, str]]:
    """`(selector, body)` of every flat rule (comments dropped; an `@media` block's own
    rules come out with its prelude glued to the first selector, enough to search)."""
    flat = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [
        (selector.strip(), body) for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", flat)
    ]


def test_only_the_scrim_paints_the_gradient_behind_the_text() -> None:
    """Deivid 2026-11-23: «Franja», «Recuadro de tu color» and «Sin fondo» never get the
    dark gradient of «Sombra» (`scrim`) in the preview, nor any shadow on the letters. The
    place rules used to share the backgrounds' specificity and come later, so they won."""
    css = (Path(__file__).parents[1] / "assets" / "qualify-creative.css").read_text(
        encoding="utf-8"
    )
    others = '[data-layout="band"], [data-layout="brand_fill"], [data-layout="shadow"]'
    gradients = [
        (selector, body)
        for selector, body in _css_rules(css)
        if "q-edit-preview__text" in selector and "gradient(" in body
    ]
    assert len(gradients) == 3  # top, middle, bottom
    for selector, body in gradients:
        # each selector of the rule leaves the other three backgrounds out
        for one in selector.split(",\n"):
            assert f":not({others})" in one, one
        # and only it sets the 45 % band and its padding
        assert "height: 45%" in body
    for selector, body in _css_rules(css):
        if "q-edit-preview__text" not in selector:
            continue
        assert "drop-shadow" not in body, selector
        assert "box-shadow" not in body, selector
        shadow = re.search(r"text-shadow:\s*([^;]+);", body)
        assert shadow is None or shadow.group(1).strip() == "none", selector
    # the backgrounds' own rules keep the text block's height and no background
    reset = next(
        body
        for selector, body in _css_rules(css)
        if selector.startswith('.q-edit-preview__text[data-layout="band"],')
    )
    assert "height: auto" in reset and "background: none" in reset


def test_motion_lengths_take_a_third_at_most() -> None:
    assert c.motion_seconds(0.5, 6.0) == 0.5
    assert c.motion_seconds(0.5, 1.2) == pytest.approx(0.4)
    assert c.motion_is_cut(0.5, 1.2) and not c.motion_is_cut(0.5, 1.5)
    assert c.typewriter_seconds("Hola", 6.0) == pytest.approx(0.24)
    assert c.typewriter_seconds("a" * 40, 3.0) == pytest.approx(1.0)  # 2,4 s → a third
    assert c.typewriter_fits("a" * 40) and not c.typewriter_fits("a" * 41)


def test_text_frame_follows_the_contracts_curves() -> None:
    f = c.text_frame
    # fade in 0,5 s then a fade out 0,5 s, over 4 s
    assert f(0.0, 4.0, motion_out="fade").alpha == 0.0
    assert f(0.25, 4.0).alpha == 0.5
    assert f(2.0, 4.0) == c.TextFrame(alpha=1.0)
    assert f(3.75, 4.0, motion_out="fade").alpha == 0.5
    assert f(3.75, 4.0).alpha == 1.0  # «De golpe»: none
    assert f(4.0, 4.0).alpha == 0.0  # gone at its end
    # slide: from 5 % lower, eased in (1-(1-p)^3); out goes down with p^3
    half_in = f(0.25, 4.0, motion_in="slide")
    assert half_in.dy == pytest.approx(0.05 * (1 - (1 - (1 - 0.5) ** 3)), abs=1e-4)
    assert f(3.75, 4.0, motion_out="slide").dy == pytest.approx(0.05 * 0.125, abs=1e-4)
    # zoom: 0,9 → 1 in, 1 → 0,9 out
    assert f(0.0, 4.0, motion_in="zoom").scale == 0.9
    assert f(3.75, 4.0, motion_out="zoom").scale == pytest.approx(1 - 0.1 * 0.125, abs=1e-4)
    # a third at most: a 0,9 s text animates for 0,3 s
    assert f(0.15, 0.9, fade_s=1.0).alpha == 0.5
    # typewriter: letters in order, each at once (0,06 s each)
    typed = [f(t, 4.0, text="Hola", motion_in="typewriter").chars for t in (0, 0.07, 0.13, 0.3)]
    assert typed == [1, 2, 3, -1]
    # the final video's clock: whitespace runs collapse, a space a line break eats is no
    # letter, and the d = 0,06 s per character of the trimmed text is split between the rest
    assert c.typed_chars("  Pan   fresco\thoy ") == list("Pan fresco hoy")
    d = 14 * 0.06  # "Pan fresco hoy": 14 characters
    one_line = [
        f(i * d / 14, 9.0, text="Pan fresco hoy", motion_in="typewriter").chars for i in range(14)
    ]
    assert one_line == list(range(1, 15))
    two_lines = [
        f(i * d / 13, 9.0, text="Pan fresco hoy", motion_in="typewriter", breaks=1).chars
        for i in range(13)
    ]
    assert two_lines == list(range(1, 14))
    assert f(d, 9.0, text="Pan fresco hoy", motion_in="typewriter", breaks=1).chars == -1
    # prefers-reduced-motion: only the alpha, every letter at once
    calm = f(0.25, 4.0, motion_in="slide", reduced=True)
    assert (calm.alpha, calm.dy, calm.scale) == (0.5, 0.0, 1.0)
    assert f(0.1, 4.0, text="Hola", motion_in="typewriter", reduced=True).chars == -1
