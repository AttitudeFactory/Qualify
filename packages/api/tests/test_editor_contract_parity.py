"""ED-15 (m-25029105): the editor screen's copy of the recipe contract
(`Qualify/editor_preview_contract.py`, pure, no `qualify_creative` import) keeps the
backend's names and limits (`qualify_creative.schemas`). Loaded by its path: the module
imports nothing of the app, so no Reflex is needed. Offline.

Both sides took v2 in the same change (texts up to 3, still photos, an effect repeated
where its uses do not overlap), so every name and limit is checked, v1's and v2's."""

from __future__ import annotations

import dataclasses
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import get_args

import pytest
from qualify_creative import schemas

CONTRACT = Path(__file__).parents[3] / "Qualify" / "editor_preview_contract.py"


@pytest.fixture(scope="module")
def screen() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_editor_preview_contract", CONTRACT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def _fields(cls: type) -> list[str]:
    return [f.name for f in dataclasses.fields(cls)]


def test_the_screen_contract_loads_without_the_app(screen: ModuleType) -> None:
    lines = CONTRACT.read_text(encoding="utf-8").splitlines()
    assert not [line for line in lines if re.match(r"(from|import) qualify_creative", line)]
    assert dataclasses.is_dataclass(screen.PartRecipe)


def test_shared_limits_are_equal(screen: ModuleType) -> None:
    assert screen.EFFECTS_MAX == schemas.EFFECTS_MAX
    assert screen.SEGMENTS_MAX == schemas.SEGMENTS_MAX
    assert screen.VIDEO_TEXT_MAX == schemas.VIDEO_TEXT_MAX
    assert screen.SEGMENT_SPEED_MIN == schemas.SEGMENT_SPEED_MIN
    assert screen.SEGMENT_SPEED_MAX == schemas.SEGMENT_SPEED_MAX
    assert screen.EFFECT_ID_PATTERN == schemas.EFFECT_ID_PATTERN
    assert tuple(screen.VIDEO_TEXT_PLACES) == schemas.VIDEO_TEXT_PLACES
    assert tuple(screen.ROTATIONS) == get_args(schemas.SegmentRotation)
    # ED-15 (v2)
    assert screen.TEXT_LAYERS_MAX == schemas.TEXT_LAYERS_MAX
    assert screen.PHOTO_SECONDS_MIN == schemas.PHOTO_SECONDS_MIN
    assert screen.PHOTO_SECONDS_MAX == schemas.PHOTO_SECONDS_MAX
    assert tuple(screen.SEGMENT_KINDS) == tuple(schemas.SEGMENT_KINDS)
    # EF-05: the fade the owner chooses
    assert screen.VIDEO_TEXT_FADE_MIN_S == schemas.VIDEO_TEXT_FADE_MIN_S
    assert screen.VIDEO_TEXT_FADE_MAX_S == schemas.VIDEO_TEXT_FADE_MAX_S
    assert screen.VIDEO_TEXT_FADE_DEFAULT_S == schemas.VIDEO_TEXT_FADE_DEFAULT_S


def test_the_screens_v2_codes_are_the_backends(screen: ModuleType) -> None:
    v2 = {
        "too_many_texts",
        "texts_overlap",
        "effect_uses_overlap",
        "photo_with_speed",
        "photo_length_out_of_range",
        "photo_not_from_start",
    }
    screen_codes = set(get_args(screen.RecipeProblem)) | set(get_args(screen.SegmentProblem))
    assert v2 <= screen_codes
    assert v2 <= set(schemas.RECIPE_REFUSALS)


def test_shared_field_names_are_the_backends(screen: ModuleType) -> None:
    def check(cls: type, model: type, legacy: set[str] = frozenset()) -> None:
        mine = set(_fields(cls)) - legacy
        theirs = set(model.model_fields)
        assert mine <= theirs, (cls.__name__, mine - theirs)
        missing = {f"{cls.__name__}.{name}" for name in theirs - mine}
        assert missing <= {f"{cls.__name__}.{n}" for n in _SERVER_ONLY}, missing

    check(screen.SourceSegment, schemas.SourceSegment)
    check(screen.VideoTextLayer, schemas.VideoTextLayer)
    check(screen.EffectUse, schemas.EffectUse)
    assert _fields(screen.SourceSegment) == list(schemas.SourceSegment.model_fields)
    # the screen's PartRecipe is the subset it writes; `text_layer` is v1's key, which the
    # backend still reads (as `text_layers` of one)
    check(screen.PartRecipe, schemas.PartRecipe, legacy={"text_layer"})
    assert _fields(screen.VideoTextLayer) == list(schemas.VideoTextLayer.model_fields)
    assert _fields(screen.EffectUse) == list(schemas.EffectUse.model_fields)


#: `PartRecipe` fields only the server sets (the screen never writes them).
_SERVER_ONLY = (
    "index",
    "mode",
    "seconds",
    "transition_in",
    "mode_rule_version",
    "mode_reason",
    "mode_changed_by_owner",
)


def test_what_the_screen_writes_validates_in_the_backend(screen: ModuleType) -> None:
    recipe = screen.PartRecipe(
        effects=(screen.EffectUse("vapor_capa", 1),),
        text_layer=screen.VideoTextLayer(
            "Hoy", place="top", layout_id="scrim", layout_version=screen.TEXT_LAYOUT_VERSION
        ),
        segments=(screen.SourceSegment("uploads/t/v.mp4", 4.0, 12.0, speed=10.0, rotate=90),),
    )
    data = screen.to_dict(recipe)
    part = schemas.PartRecipe.model_validate({**data, "index": 1, "seconds": 0.8})
    assert part.text_layers[0].text == "Hoy" and len(part.text_layers) == 1
    assert part.segments[0].kind == "video" and part.segments[0].output_seconds == 0.8
    assert part.effects[0].effect_id == "vapor_capa"


def test_a_v2_recipe_the_screen_writes_reads_the_same_in_the_backend(
    screen: ModuleType,
) -> None:
    """2 videos, 1 photo, 3 texts, the same effect twice: what `to_dict` writes is read by
    the backend as the same recipe (each text once, despite `text_layer` + `text_layers`)."""
    texts = (
        screen.VideoTextLayer("Abre hoy", place="top", start_s=0.0, end_s=2.0),
        screen.VideoTextLayer("Pide ya", place="top", start_s=2.0, end_s=4.0),
        screen.VideoTextLayer("Domicilios", place="bottom"),
    )
    recipe = screen.PartRecipe(
        effects=(
            screen.EffectUse("humo_capa", 1, (), 0.0, 1.0),
            screen.EffectUse("humo_capa", 1, (), 2.0, 3.0),
        ),
        segments=(
            screen.SourceSegment("uploads/t/a.mp4", 0.0, 2.0),
            screen.SourceSegment("uploads/t/p.jpg", 0.0, 2.0, kind="photo", rotate=90),
            screen.SourceSegment("uploads/t/b.mp4", 0.0, 4.0, speed=2.0),
        ),
        text_layers=texts,
    )
    assert screen.recipe_problems(recipe) == []
    part = schemas.PartRecipe.model_validate({**screen.to_dict(recipe), "index": 1, "seconds": 6})
    assert [t.text for t in part.text_layers] == ["Abre hoy", "Pide ya", "Domicilios"]
    assert [s.kind for s in part.segments] == ["video", "photo", "video"]
    assert [(e.effect_id, e.start_s) for e in part.effects] == [
        ("humo_capa", 0.0),
        ("humo_capa", 2.0),
    ]
    back = screen.from_dict(part.model_dump(mode="json"))
    assert back == recipe


def test_a_text_fade_the_screen_writes_reads_the_same_in_the_backend(screen: ModuleType) -> None:
    """EF-05: the fade the owner chose travels in the text dict; a dict without it reads
    as the default on both sides."""
    layer = screen.VideoTextLayer("Hoy", place="top", fade_s=0.8)
    data = screen.to_dict(screen.PartRecipe(text_layers=(layer,)))
    raw = data["text_layers"][0]
    assert raw["fade_s"] == 0.8
    assert schemas.VideoTextLayer.model_validate(raw).fade_s == 0.8
    old = {k: v for k, v in raw.items() if k != "fade_s"}
    assert schemas.VideoTextLayer.model_validate(old).fade_s == schemas.VIDEO_TEXT_FADE_DEFAULT_S
    back = screen.from_dict({"text_layers": [old]})
    assert back.text_layers[0].fade_s == screen.VIDEO_TEXT_FADE_DEFAULT_S
