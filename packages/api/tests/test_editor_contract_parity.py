"""ED-15 (m-25029105): the editor screen's copy of the recipe contract
(`Qualify/editor_preview_contract.py`, pure, no `qualify_creative` import) keeps the
backend's names and limits (`qualify_creative.schemas`). Loaded by its path: the module
imports nothing of the app, so no Reflex is needed. Offline.

Both sides took v2 in the same change (texts up to 3, still photos, an effect repeated
where its uses do not overlap), so every name and limit is checked, v1's and v2's."""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import get_args

import pytest
from pydantic import ValidationError
from qualify_creative import schemas

CONTRACT = Path(__file__).parents[3] / "Qualify" / "editor_preview_contract.py"
#: ED-13: the render's `boxInk` vectors (`layout.ts`), which the screen's mirror must meet.
BOX_INK_VECTORS = (
    Path(__file__).parents[3] / "packages" / "render" / "server" / "box-ink-vectors.json"
)


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
    # m-25114465: the server reads a block's `transition_in` before the screen writes it
    # (the Clip editor's join selector adds it to `editor_preview_contract.SourceSegment`)
    full = list(schemas.SourceSegment.model_fields)
    assert _fields(screen.SourceSegment) in (full, [f for f in full if f != "transition_in"])
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


def test_the_screens_text_backgrounds_and_motions_are_the_backends(screen: ModuleType) -> None:
    """ED-13 (m-25029108): the four backgrounds, the closed motions and their numbers are
    the same on both sides (the screen's preview draws what the compose step lays)."""
    assert tuple(screen.VIDEO_TEXT_LAYOUTS) == schemas.VIDEO_TEXT_LAYOUTS
    assert schemas.VIDEO_TEXT_LAYOUTS == ("scrim", "band", "brand_fill", "shadow")
    assert screen.VIDEO_TEXT_BOX_PAD_PX == schemas.VIDEO_TEXT_BOX_PAD_PX == 48
    assert screen.VIDEO_TEXT_BOX_RADIUS_PX == schemas.VIDEO_TEXT_BOX_RADIUS_PX == 24
    # «Sin fondo» (Deivid 2026-11-23): clean letters — no shadow constant on either side
    assert not hasattr(schemas, "VIDEO_TEXT_SHADOW") and not hasattr(screen, "VIDEO_TEXT_SHADOW")
    # the colour the owner picks for «Franja» / «Recuadro de tu color», and its letters
    assert screen.VIDEO_TEXT_BOX_COLOR_PATTERN == schemas.VIDEO_TEXT_BOX_COLOR_PATTERN
    assert tuple(screen.VIDEO_TEXT_BOX_COLOR_LAYOUTS) == schemas.VIDEO_TEXT_BOX_COLOR_LAYOUTS
    assert screen.VIDEO_TEXT_INK_LIGHT == schemas.VIDEO_TEXT_INK_LIGHT == "#FFFFFF"
    assert screen.VIDEO_TEXT_INK_DARK == schemas.VIDEO_TEXT_INK_DARK == "#111111"
    vectors = json.loads(BOX_INK_VECTORS.read_text(encoding="utf-8"))
    assert (vectors["light"], vectors["dark"]) == (
        schemas.VIDEO_TEXT_INK_LIGHT,
        schemas.VIDEO_TEXT_INK_DARK,
    )
    for background, ink in vectors["vectors"]:
        assert screen.box_ink(background) == ink, background
    # «Franja»: a fixed dark neutral strip with white letters (never the brand's surface)
    assert screen.VIDEO_TEXT_BAND_COLOR == schemas.VIDEO_TEXT_BAND_COLOR == "#111111"
    assert screen.VIDEO_TEXT_BAND_INK == schemas.VIDEO_TEXT_BAND_INK == "#FFFFFF"
    assert screen.contrast(schemas.VIDEO_TEXT_BAND_INK, schemas.VIDEO_TEXT_BAND_COLOR) >= 4.5
    assert screen.text_box_colors("band", screen.palette_of(["#F4C2C2", "#5A2A27", "#FFFFFF"])) == (
        schemas.VIDEO_TEXT_BAND_COLOR,
        schemas.VIDEO_TEXT_BAND_INK,
    )
    assert tuple(screen.VIDEO_TEXT_MOTIONS_IN) == schemas.VIDEO_TEXT_MOTIONS_IN
    assert tuple(screen.VIDEO_TEXT_MOTIONS_OUT) == schemas.VIDEO_TEXT_MOTIONS_OUT
    assert schemas.VIDEO_TEXT_MOTIONS_IN == ("fade", "slide", "zoom", "typewriter")
    assert schemas.VIDEO_TEXT_MOTIONS_OUT == ("none", "fade", "slide", "zoom")
    assert screen.VIDEO_TEXT_SLIDE_FRACTION == schemas.VIDEO_TEXT_SLIDE_FRACTION == 0.05
    assert screen.VIDEO_TEXT_ZOOM_FROM == schemas.VIDEO_TEXT_ZOOM_FROM == 0.9
    assert screen.VIDEO_TEXT_TYPEWRITER_MAX_CHARS == schemas.VIDEO_TEXT_TYPEWRITER_MAX_CHARS
    assert schemas.VIDEO_TEXT_TYPEWRITER_MAX_CHARS == 40
    assert screen.VIDEO_TEXT_TYPEWRITER_S_PER_CHAR == schemas.VIDEO_TEXT_TYPEWRITER_S_PER_CHAR
    assert schemas.VIDEO_TEXT_TYPEWRITER_S_PER_CHAR == 0.06
    assert screen.VIDEO_TEXT_MOTION_MAX_SHARE == pytest.approx(schemas.VIDEO_TEXT_MOTION_MAX_SHARE)
    assert schemas.VIDEO_TEXT_MOTION_MAX_SHARE == pytest.approx(1 / 3)
    # the new refusal codes, appended on both sides
    codes = (
        "unknown_text_motion",
        "typewriter_text_too_long",
        "bad_text_box_color",
        "bad_text_color",
        "unknown_text_size",
        "text_too_long_for_large",
    )
    assert get_args(screen.RecipeProblem)[-6:] == codes
    # m-25114465 appended two block codes after them (the screen has no use for them yet)
    assert schemas.RECIPE_REFUSALS[-8:-2] == codes
    # the text's new fields close the list, in this order
    assert list(schemas.VideoTextLayer.model_fields)[-6:] == [
        "fade_s",
        "motion_in",
        "motion_out",
        "box_color",
        "text_color",
        "text_size",
    ]
    assert [f.name for f in dataclasses.fields(screen.VideoTextLayer)][-3:] == [
        "box_color",
        "text_color",
        "text_size",
    ]
    # ED-13 round 4: the sizes, their scales (copied by the render's `layout.ts`) and
    # «Grande»'s limit
    assert tuple(screen.VIDEO_TEXT_SIZES) == schemas.VIDEO_TEXT_SIZES
    assert schemas.VIDEO_TEXT_SIZES == ("small", "medium", "large")
    assert screen.VIDEO_TEXT_SIZE_SCALE == schemas.VIDEO_TEXT_SIZE_SCALE
    assert screen.VIDEO_TEXT_LARGE_MAX_CHARS == schemas.VIDEO_TEXT_LARGE_MAX_CHARS == 40
    layout_ts = (
        Path(__file__).resolve().parents[3] / "packages/render/src/templates/video_text/layout.ts"
    ).read_text(encoding="utf-8")
    scales = ", ".join(f"{k}: {v:g}" for k, v in schemas.VIDEO_TEXT_SIZE_SCALE.items())
    assert f"SIZE_SCALE: Readonly<Record<string, number>> = {{{scales}}}" in layout_ts
    assert screen.VIDEO_TEXT_TEXT_COLOR_LAYOUTS == schemas.VIDEO_TEXT_TEXT_COLOR_LAYOUTS
    assert screen.VIDEO_TEXT_TEXT_COLOR_PATTERN == schemas.VIDEO_TEXT_TEXT_COLOR_PATTERN


def test_a_text_motion_and_background_the_screen_writes_read_the_same_in_the_backend(
    screen: ModuleType,
) -> None:
    """ED-13: what the editor writes for a new text (fade in, fade out, a background) is
    read back as it is; a text without them keeps v1's shape and the type's defaults."""
    layer = screen.VideoTextLayer(
        "Hoy",
        place="top",
        layout_id="brand_fill",
        layout_version=screen.TEXT_LAYOUT_VERSION,
        motion_in="typewriter",
        motion_out="slide",
    )
    raw = screen.to_dict(screen.PartRecipe(text_layers=(layer,)))["text_layers"][0]
    back = schemas.VideoTextLayer.model_validate(raw)
    assert (str(back.layout_id), back.motion_in, back.motion_out) == (
        "brand_fill",
        "typewriter",
        "slide",
    )
    unmoved = screen.VideoTextLayer("Hoy", motion_in="fade", motion_out="none")
    plain = screen.to_dict(screen.PartRecipe(text_layers=(unmoved,)))
    plain_raw = plain["text_layers"][0]
    assert "motion_in" not in plain_raw and "motion_out" not in plain_raw
    old = schemas.VideoTextLayer.model_validate(plain_raw)
    assert (old.motion_in, old.motion_out) == ("fade", "none")
    shadow = screen.VideoTextLayer(
        "Hoy", layout_id="shadow", layout_version=screen.TEXT_LAYOUT_VERSION
    )
    raw_shadow = screen.to_dict(screen.PartRecipe(text_layers=(shadow,)))["text_layers"][0]
    assert schemas.VideoTextLayer.model_validate(raw_shadow).layout_id == "shadow"


def test_a_picked_box_colour_the_screen_writes_reads_the_same_in_the_backend(
    screen: ModuleType,
) -> None:
    """ED-13 (Deivid 2026-11-23): the colour picked for «Franja» travels as is; a text
    without one keeps its shape on both sides; a bad one is refused by both, same code."""
    layer = screen.VideoTextLayer(
        "Hoy", layout_id="band", layout_version=screen.TEXT_LAYOUT_VERSION, box_color="#FFE600"
    )
    raw = screen.to_dict(screen.PartRecipe(text_layers=(layer,)))["text_layers"][0]
    back = schemas.VideoTextLayer.model_validate(raw)
    assert back.box_color == back.effective_box_color == "#FFE600"
    assert screen.from_dict({"text_layers": [back.model_dump(mode="json")]}).text_layers[0] == layer
    plain = screen.VideoTextLayer("Hoy", layout_id="band", layout_version=3)
    plain_raw = screen.to_dict(screen.PartRecipe(text_layers=(plain,)))["text_layers"][0]
    assert "box_color" not in plain_raw
    assert "box_color" not in schemas.VideoTextLayer.model_validate(plain_raw).model_dump()
    bad = screen.VideoTextLayer("Hoy", layout_id="band", layout_version=3, box_color="#ffe600")
    assert "bad_text_box_color" in screen.recipe_problems(screen.PartRecipe(text_layers=(bad,)))
    with pytest.raises(ValidationError) as caught:
        schemas.VideoTextLayer.model_validate(
            screen.to_dict(screen.PartRecipe(text_layers=(bad,)))["text_layers"][0]
        )
    assert [e["type"] for e in caught.value.errors()] == ["bad_text_box_color"]


def test_a_picked_letters_colour_the_screen_writes_reads_the_same_in_the_backend(
    screen: ModuleType,
) -> None:
    """ED-13 round 3 (Deivid 2026-11-23): «Sin fondo»'s letters' colour travels as is; a
    text without one keeps its shape on both sides; a bad one is refused by both."""
    layer = screen.VideoTextLayer(
        "Hoy", layout_id="shadow", layout_version=screen.TEXT_LAYOUT_VERSION, text_color="#111111"
    )
    raw = screen.to_dict(screen.PartRecipe(text_layers=(layer,)))["text_layers"][0]
    back = schemas.VideoTextLayer.model_validate(raw)
    assert back.text_color == back.effective_text_color == "#111111"
    assert screen.from_dict({"text_layers": [back.model_dump(mode="json")]}).text_layers[0] == layer
    plain = screen.VideoTextLayer("Hoy", layout_id="shadow", layout_version=3)
    plain_raw = screen.to_dict(screen.PartRecipe(text_layers=(plain,)))["text_layers"][0]
    assert "text_color" not in plain_raw
    assert "text_color" not in schemas.VideoTextLayer.model_validate(plain_raw).model_dump()
    bad = screen.VideoTextLayer("Hoy", layout_id="shadow", layout_version=3, text_color="#111")
    assert "bad_text_color" in screen.recipe_problems(screen.PartRecipe(text_layers=(bad,)))
    with pytest.raises(ValidationError) as caught:
        schemas.VideoTextLayer.model_validate(
            screen.to_dict(screen.PartRecipe(text_layers=(bad,)))["text_layers"][0]
        )
    assert [e["type"] for e in caught.value.errors()] == ["bad_text_color"]


def test_a_text_size_the_screen_writes_reads_the_same_in_the_backend(
    screen: ModuleType,
) -> None:
    """ED-13 round 4 (Deivid 2026-11-23): the letters' size travels as is; «Mediana» keeps
    the text's shape on both sides; «Grande» on a long text is refused by both."""
    layer = screen.VideoTextLayer("Hoy", text_size="large")
    raw = screen.to_dict(screen.PartRecipe(text_layers=(layer,)))["text_layers"][0]
    back = schemas.VideoTextLayer.model_validate(raw)
    assert back.text_size == "large"
    assert screen.from_dict({"text_layers": [back.model_dump(mode="json")]}).text_layers[0] == layer
    plain_raw = screen.to_dict(screen.PartRecipe(text_layers=(screen.VideoTextLayer("Hoy"),)))
    assert "text_size" not in plain_raw["text_layers"][0]
    assert (
        "text_size"
        not in schemas.VideoTextLayer.model_validate(plain_raw["text_layers"][0]).model_dump()
    )
    long = screen.VideoTextLayer("a" * 41, text_size="large")
    assert "text_too_long_for_large" in screen.recipe_problems(
        screen.PartRecipe(text_layers=(long,))
    )
    with pytest.raises(ValidationError) as caught:
        schemas.VideoTextLayer.model_validate(
            screen.to_dict(screen.PartRecipe(text_layers=(long,)))["text_layers"][0]
        )
    assert [e["type"] for e in caught.value.errors()] == ["text_too_long_for_large"]
    huge = screen.VideoTextLayer("Hoy", text_size="huge")
    assert "unknown_text_size" in screen.recipe_problems(screen.PartRecipe(text_layers=(huge,)))
    with pytest.raises(ValidationError) as caught:
        schemas.VideoTextLayer.model_validate({"text": "Hoy", "text_size": "huge"})
    assert [e["type"] for e in caught.value.errors()] == ["unknown_text_size"]


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


def test_the_screens_typewriter_clock_is_the_final_videos(screen: ModuleType) -> None:
    """ED-13: «Letra por letra» in the preview lasts what the compose step gives it (0,06 s
    per character of the trimmed text, a third of its time at most) and splits it between
    the same letters: the render's (whitespace collapsed, no space a line break eats),
    letter i at `i * d / n`, the first at once (`text_overlay._Motion`)."""
    from qualify_api.creative.video_pipeline.compose import fade_in_seconds

    for text, start, end in (("Pan fresco hoy", 1.0, 9.0), ("2×1  hoy en shawarma", 0.0, 1.2)):
        layer = schemas.VideoTextLayer(text=text, start_s=start, end_s=end, motion_in="typewriter")
        d = screen.typewriter_seconds(text, end - start)
        assert d == pytest.approx(fade_in_seconds(layer), abs=1e-6)
        # the render's letters: the collapsed text less one space per line break
        letters = len(screen.typed_chars(text)) - 1  # laid out on two lines
        step = d / letters
        shown = [
            screen.text_frame(i * step, end - start, text=text, motion_in="typewriter", breaks=1)
            for i in range(letters)
        ]
        # `_Motion.at`: min(count, int((t - start) / step + 1e-6) + 1)
        assert [f.chars for f in shown] == [min(letters, int(i + 1e-6) + 1) for i in range(letters)]


def _css_block(css: str, selector: str) -> str:
    """The declarations of the rule whose selector is exactly `selector`."""
    match = re.search(r"(?m)^" + re.escape(selector) + r" \{\n(.*?)\n\}", css, re.S)
    assert match, selector
    return match.group(1)


def test_the_preview_and_the_final_video_both_centre_the_text() -> None:
    """ED-13 (Deivid 2026-11-24, «que siempre esté centrado»): the preview centres every line
    and the box (`assets/qualify-creative.css`) as the render does (`layout.ts` `centred` on
    every v2 text), and every text the app sends is drawn by v2."""
    from qualify_creative.render.video_text import TEMPLATE_VERSION_V2, VideoTextRequest

    root = Path(__file__).resolve().parents[3]
    css = (root / "assets/qualify-creative.css").read_text(encoding="utf-8")
    assert "justify-content: center;" in _css_block(css, ".q-edit-preview__text")
    assert "justify-content: center;" in _css_block(css, ".q-edit-preview__text-box")
    assert "text-align: center;" in _css_block(css, ".q-edit-preview__text-line")
    assert "text-align: left" not in _css_block(css, ".q-edit-preview__text-line")
    layout_ts = (root / "packages/render/src/templates/video_text/layout.ts").read_text(
        encoding="utf-8"
    )
    assert "x: round2((width - l.width) / 2)" in layout_ts
    assert "config.box !== undefined ? centred(r.texts, fmt.width) : r.texts" in layout_ts
    brand = {"name": "", "palette": ["#112233"], "fonts": {"heading": "Inter"}}
    for layout in schemas.VIDEO_TEXT_LAYOUTS:
        for size in schemas.VIDEO_TEXT_SIZES:
            request = VideoTextRequest(
                text="Pan", place="top", brand=brand, layout_id=layout, text_size=size
            )
            assert request.template_version == TEMPLATE_VERSION_V2, (layout, size)


def test_nothing_in_the_preview_pushes_a_short_text_sideways() -> None:
    """Deivid 2026-11-24: «cuando escribo poco texto se va hacia la derecha … que siempre se
    centre en el eje x». Every rule that places the preview's text (its layer, box, lines and
    the sequence's overlay) is horizontally symmetric: a `left` only with an equal `right`,
    a horizontal margin or padding only on both sides, no `translateX`/`translate(x, …)`."""
    root = Path(__file__).resolve().parents[3]
    css = (root / "assets/qualify-creative.css").read_text(encoding="utf-8")
    text = r"(?:q-edit-preview__text|q-edit-seq__(?:overlay|full|type)|data-seq-text)"
    rules = re.findall(r"(?ms)^([^{}\n]*" + text + r"[^{}\n]*)\{(.*?)\}", css)
    assert len(rules) > 10
    for selector, body in rules:
        decls = dict(
            (k.strip(), v.strip()) for k, v in re.findall(r"([a-z-]+)\s*:\s*([^;]+);", body)
        )
        where = selector.strip()
        if "left" in decls:
            assert decls.get("right") == decls["left"], where
        for side in ("margin-left", "margin-right", "padding-left", "padding-right"):
            assert side not in decls, (where, side)
        for value in decls.values():
            assert "translateX" not in value, where
            assert not re.search(r"translate\((?!0[,)])", value), where
