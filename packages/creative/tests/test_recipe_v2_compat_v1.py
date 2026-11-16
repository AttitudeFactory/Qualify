"""ED-15 (m-25029105): the contract v2 keeps EVERYTHING of the recipe v1 (EF-02) — what
the editor screen (ED-01) already writes keeps validating the same way, with the same
names, defaults and limits. One test per item of the compatibility list. Offline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qualify_creative import schemas
from qualify_creative.effects import load_effects
from qualify_creative.schemas import (
    EffectUse,
    MediaInputs,
    PartRecipe,
    SourceSegment,
    VideoPartPlan,
    VideoTextLayer,
)

KEY = "uploads/00000000-0000-4000-8000-000000000001/cocina.mp4"

# ---------------------------------------------------------------------------
# SourceSegment: key, start_s, end_s, speed (1.0), rotate (0/90/180/270, 0); kind video


def test_a_v1_stretch_validates_as_before() -> None:
    plain = SourceSegment.model_validate({"key": KEY, "start_s": 4.0, "end_s": 12.0})
    assert (plain.speed, plain.rotate, plain.kind) == (1.0, 0, "video")
    for rotate in (0, 90, 180, 270):
        assert SourceSegment(key=KEY, start_s=0, end_s=2, rotate=rotate).rotate == rotate
    fast = SourceSegment(key=KEY, start_s=0, end_s=60, speed=12.0)
    assert fast.output_seconds == 5.0  # seconds of the output, after the speed


@pytest.mark.parametrize(
    "bad",
    [
        {"key": KEY, "start_s": 2.0, "end_s": 1.0},
        {"key": KEY, "start_s": 0.0, "end_s": 1.0, "rotate": 45},
        {"key": KEY, "start_s": 0.0, "end_s": 1.0, "speed": 0.5},
        {"key": KEY, "start_s": 0.0, "end_s": 1.0, "speed": 31.0},
        {"key": "", "start_s": 0.0, "end_s": 1.0},
        {"key": KEY, "start_s": -1.0, "end_s": 1.0},
    ],
)
def test_a_v1_stretch_is_refused_as_before(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SourceSegment.model_validate(bad)


# ---------------------------------------------------------------------------
# VideoTextLayer: text; place top/middle/bottom (bottom); start_s 0.0; end_s None; design


def test_a_v1_text_validates_as_before() -> None:
    layer = VideoTextLayer(text="Hoy")
    assert (layer.place, layer.start_s, layer.end_s) == ("bottom", 0.0, None)
    assert (layer.layout_id, layer.layout_version) == (None, None)
    for place in ("top", "middle", "bottom"):
        assert VideoTextLayer(text="Hoy", place=place).place == place  # type: ignore[arg-type]
    # what the screen sends today: the `scrim` design at version 1
    screen = VideoTextLayer.model_validate(
        {"text": "Hoy", "place": "top", "layout_id": "scrim", "layout_version": 1}
    )
    assert screen.layout_id is not None and screen.layout_id.value == "scrim"
    assert screen.layout_version == 1


@pytest.mark.parametrize(
    "bad",
    [
        {"text": "   "},
        {"text": "Hoy", "place": "side"},
        {"text": "Hoy", "start_s": 3.0, "end_s": 2.0},
        {"text": "Hoy", "layout_id": "scrim"},
        {"text": "Hoy", "layout_version": 1},
        {"text": "a" * 121},
    ],
)
def test_a_v1_text_is_refused_as_before(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        VideoTextLayer.model_validate(bad)


# ---------------------------------------------------------------------------
# EffectUse: effect_id, version, params (an object), start_s/end_s both or neither


def test_a_v1_effect_use_validates_as_before() -> None:
    data = {"effect_id": "vapor_capa", "version": 1, "params": {"intensity": 0.5}}
    use = EffectUse.model_validate(data)
    assert use.model_dump() == {**data, "start_s": None, "end_s": None}
    spanned = EffectUse.model_validate({**data, "start_s": 1.0, "end_s": 2.0})
    assert (spanned.start_s, spanned.end_s) == (1.0, 2.0)
    for bad in ({**data, "start_s": 1.0}, {**data, "end_s": 1.0}):
        with pytest.raises(ValidationError):
            EffectUse.model_validate(bad)


# ---------------------------------------------------------------------------
# A part's recipe reads with `effects`, `text_layer` and `segments` (with `text_layers`)


def test_a_v1_part_recipe_reads() -> None:
    v1 = {
        "effects": [{"effect_id": "vapor_capa", "version": 1, "params": {}}],
        "text_layer": {"text": "Hoy", "place": "top", "start_s": 0.0, "end_s": None},
        "segments": [{"key": KEY, "start_s": 4.0, "end_s": 12.0, "speed": 1.0, "rotate": 90}],
    }
    for model, extra in (
        (PartRecipe, {"index": 1, "seconds": 8}),
        (VideoPartPlan, {"mode": "local", "seconds": 8}),
        (MediaInputs, {"clip_reference_mode": "local", "duration_seconds": 10}),
    ):
        read = model.model_validate({**v1, **extra})
        assert read.text_layers == (VideoTextLayer(text="Hoy", place="top"),)
        assert read.segments[0].kind == "video" and read.segments[0].rotate == 90
        assert read.effects[0].effect_id == "vapor_capa"
    together = PartRecipe.model_validate(
        {**v1, "index": 1, "seconds": 8, "text_layers": [{"text": "Pide", "place": "bottom"}]}
    )
    assert [t.text for t in together.text_layers] == ["Hoy", "Pide"]


# ---------------------------------------------------------------------------
# Limits unchanged


def test_v1_limits_are_unchanged() -> None:
    from qualify_creative.video.speed import MAX_SPEED, MIN_SPEED

    assert (schemas.EFFECTS_MAX, schemas.SEGMENTS_MAX, schemas.VIDEO_TEXT_MAX) == (8, 8, 120)
    assert (schemas.SEGMENT_SPEED_MIN, schemas.SEGMENT_SPEED_MAX) == (1.0, 30.0)
    assert (schemas.SEGMENT_SPEED_MIN, schemas.SEGMENT_SPEED_MAX) == (MIN_SPEED, MAX_SPEED)
    assert schemas.EFFECT_ID_PATTERN == r"^[a-z][a-z0-9_]{0,39}$"
    assert schemas.VIDEO_TEXT_PLACES == ("top", "middle", "bottom")


# ---------------------------------------------------------------------------
# effects_data/v1.json: the screen's effects keep version, label, stage, preview and blend


def test_v1_json_keeps_the_screens_effects() -> None:
    expected = {
        "camara_rapida": (1, "Cámara rápida", "local", None, None),
        "texto": (1, "Texto", "compose", None, None),
        "vapor_capa": (1, "Vapor", "compose", None, "screen"),
        "humo_capa": (1, "Humo", "compose", None, "screen"),
        "brasas_capa": (1, "Brasas", "compose", None, "screen"),
    }
    raw = json.loads(
        (
            Path(__file__).parents[1] / "src" / "qualify_creative" / "effects_data" / "v1.json"
        ).read_text(encoding="utf-8")
    )
    for library in (raw["entries"], load_effects("v1").entries, load_effects("v2").entries):
        seen = {}
        for entry in library:
            e = entry if isinstance(entry, dict) else entry.model_dump()
            if e["id"] in expected:
                seen[e["id"]] = (
                    e["version"],
                    e["label"],
                    e["stage"],
                    e["preview_asset"],
                    e["blend"],
                )
        assert seen == expected
    assert all(e.max_per_part == 1 for e in load_effects("v1").entries)


# ---------------------------------------------------------------------------
# `media.edit_recipe` (the screen's own key) is still dropped without an error


def test_the_screens_edit_recipe_is_dropped_without_error() -> None:
    media = MediaInputs.model_validate(
        {"duration_seconds": 10, "edit_recipe": {"effects": [], "text_layer": None}}
    )
    assert "edit_recipe" not in media.model_dump()
    for model in (MediaInputs, VideoPartPlan, PartRecipe, SourceSegment, VideoTextLayer):
        assert model.model_config.get("extra") != "forbid", model.__name__


# ---------------------------------------------------------------------------
# Times are seconds of the part's output, after its speed; segment order = video order


def test_times_are_the_parts_output_and_order_is_the_videos() -> None:
    from qualify_creative.effects import part_effect_problems

    a = SourceSegment(key=KEY, start_s=0.0, end_s=30.0, speed=10.0)  # 3 s of output
    b = SourceSegment(key=KEY, start_s=40.0, end_s=42.0)  # 2 s
    plan = VideoPartPlan(mode="local", seconds=5, segments=(b, a))
    assert plan.segments == (b, a)  # kept as given: the video's order
    assert sum(s.output_seconds for s in plan.segments) == 5.0
    inside = EffectUse(effect_id="texto", version=1, start_s=4.0, end_s=5.0)
    outside = EffectUse(effect_id="texto", version=1, start_s=4.0, end_s=6.0)
    library = load_effects("v1")
    for use, codes in ((inside, []), (outside, ["span_outside_part"])):
        problems = part_effect_problems(
            (use,), library, part=1, mode="local", has_own_video=True, window=(0.0, 5.0)
        )
        assert [p.code for p in problems] == codes
