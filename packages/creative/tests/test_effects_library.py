"""EF-02 (ADR 50): the effects library v1 and the recipe types — the loader refuses a
broken file, `preview_asset` is where the screen needs it, the effect checks return
stable codes, and the recipe types are pure data that round-trip through JSON. Offline."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from qualify_creative.effects import (
    EffectEntry,
    EffectsLibrary,
    MissingPreviewAsset,
    effect_use_problems,
    load_effects,
    parse_library,
    part_effect_problems,
    preview_file,
    transition_problems,
)
from qualify_creative.schemas import (
    RECIPE_REFUSALS,
    EffectUse,
    MediaInputs,
    PartRef,
    SourceSegment,
    VideoPartPlan,
    VideoTextLayer,
)

#: These tests are of the library v1 (ED-15 made v2 the default; v1 reads unchanged).
LIBRARY = load_effects("v1")
RAW = json.loads(
    (Path(__file__).parents[1] / "src" / "qualify_creative" / "effects_data" / "v1.json").read_text(
        encoding="utf-8"
    )
)


def _offering(root: Path, names: tuple[str, ...], measured: bool = False) -> EffectsLibrary:
    """The v1 library with `names` OFFERED, each with a preview file written under `root`
    (and, for a «Con IA» effect, a bench result): the checks of an offered effect, apart
    from whether v1 offers it yet."""
    bench = {
        "successes": 4,
        "n": 4,
        "wilson_low": 0.5,
        "wilson_high": 1.0,
        "measured_on": "2026-11-20",
        "model": "dreamina-seedance-2-5-260628",
    }
    entries = []
    for entry in copy.deepcopy(RAW["entries"]):
        if entry["id"] in names:
            preview = f"effects/{entry['id']}/v1/preview.webm"
            file = preview_file(preview, root)
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"webm")
            entry.update(offered=True, preview_asset=preview)
            if entry["stage"] == "seedance_prompt" and measured:
                entry["measured"] = bench
        entries.append(entry)
    return parse_library({"version": 1, "entries": entries}, assets_root=root)


#: v1 with its three layers and fast motion offered (previews in a temporary folder).
OFFERING = _offering(
    Path(tempfile.mkdtemp()), ("humo_capa", "brasas_capa", "vapor_capa", "camara_rapida")
)


def _entry(effect_id: str) -> dict[str, Any]:
    return copy.deepcopy(next(e for e in RAW["entries"] if e["id"] == effect_id))


def _with(entry: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "entries": [entry]}


def _codes(problems: tuple) -> list[str]:
    return [p.code for p in problems]


# ---------------------------------------------------------------------------
# The stable codes


def test_recipe_refusals_are_pinned() -> None:
    """The screen and stored outcomes branch on these: a rename is deliberate."""
    assert RECIPE_REFUSALS == (
        "unknown_effect",
        "unknown_version",
        "unknown_param",
        "param_out_of_range",
        "not_offered",
        "too_many_ai_effects",
        "too_many_of_effect",
        "effect_needs_own_video",
        "transition_on_clip",
        "transition_in_effects",
        "transition_not_a_transition",
        "transition_on_first_part",
        "local_needs_own_video",
        "segments_length_mismatch",
        "local_length_out_of_range",
        "local_with_ai_effect",
        "local_unavailable",
        "recipe_unavailable",
        "effects_not_for_kind",
        "span_outside_part",
        "unknown_layout",
        "malformed_key",
        "foreign_key",
        # ED-15 (contract v2), appended
        "too_many_texts",
        "texts_overlap",
        "effect_uses_overlap",
        "photo_with_speed",
        "photo_length_out_of_range",
        "photo_not_from_start",
        "segment_source_too_long",
        "transitions_longer_than_part",
        "text_bottom_with_subtitles",
        # ED-13 (m-25029108), appended
        "unknown_text_motion",
        "typewriter_text_too_long",
        "bad_text_box_color",
        # ED-13 round 3, appended
        "bad_text_color",
        # ED-13 round 4, appended
        "unknown_text_size",
        "text_too_long_for_large",
    )


# ---------------------------------------------------------------------------
# The library v1


def test_the_v1_library_has_every_planned_effect_in_its_stage() -> None:
    stages = {(e.id, e.version): e.stage for e in LIBRARY.entries}
    assert stages == {
        ("camara_rapida", 1): "local",
        ("texto", 1): "compose",
        ("corte", 1): "transition",
        ("fundido", 1): "transition",
        ("barrido", 1): "transition",
        ("humo_capa", 1): "compose",
        ("brasas_capa", 1): "compose",
        ("vapor_capa", 1): "compose",
        ("fuego_lena_base", 1): "seedance_prompt",
        ("quemadores_brillan", 1): "seedance_prompt",
        ("vapor_sobre_comida", 1): "seedance_prompt",
        ("humo_denso", 1): "seedance_prompt",
        ("brasas", 1): "seedance_prompt",
    }
    for entry in LIBRARY.entries:
        assert (entry.scope == "between_parts") == (entry.stage == "transition")


def test_every_entry_has_spanish_label_and_cost_note() -> None:
    for entry in LIBRARY.entries:
        assert entry.label.strip() and entry.cost_note in ("Gratis", "Con IA")
        assert (entry.cost_note == "Con IA") == (entry.stage == "seedance_prompt")


def test_every_default_is_within_its_range() -> None:
    for entry in LIBRARY.entries:
        for spec in entry.params.values():
            assert spec.accepts(spec.default)


def test_the_library_is_loaded_once() -> None:
    assert load_effects() is load_effects("v5")  # EF-16: v5 is what new requests use
    assert load_effects("v1") is load_effects("v1")


def test_an_unknown_library_version_is_a_key_error() -> None:
    with pytest.raises(KeyError, match="v99"):
        load_effects("v99")


# ---------------------------------------------------------------------------
# preview_asset (editor contract §4.1)


@pytest.mark.parametrize("name", ["texto", "corte", "fundido", "barrido"])
def test_a_null_preview_where_the_screen_simulates_it_passes(name: str) -> None:
    parse_library(_with(_entry(name)))


def test_a_null_preview_on_an_unoffered_ai_template_passes() -> None:
    parse_library(_with(_entry("humo_denso")))


@pytest.mark.parametrize(
    "path",
    [
        "effects/humo_capa/v1/../../t/x/preview.webm",
        "https://cdn.example.com/effects/humo_capa/v1/preview.webm",
        "t/effects/humo_capa/v1/preview.webm",
        "/effects/humo_capa/v1/preview.webm",
        "effects\\humo_capa\\v1\\preview.webm",
        "effects/brasas_capa/v1/preview.webm",  # another effect's folder
        "effects/humo_capa/v2/preview.webm",  # another version's folder
        "effects/humo_capa/v1//preview.webm",
        "effects/humo_capa/v1/",  # a folder, not a file
        "",
    ],
)
def test_a_malformed_preview_is_refused(path: str) -> None:
    entry = _entry("humo_capa")
    entry["preview_asset"] = path
    with pytest.raises(ValidationError):
        parse_library(_with(entry))


def test_an_entry_with_a_seed_or_an_unknown_key_is_refused() -> None:
    entry = _entry("brasas")
    entry["seed"] = 42
    with pytest.raises(ValidationError, match="seed"):
        parse_library(_with(entry))


def test_a_template_without_its_slots_is_refused() -> None:
    entry = _entry("brasas")
    entry["prompt_template"] = "Embers in the frame."
    with pytest.raises(ValidationError, match="zone"):
        parse_library(_with(entry))


def test_a_repeated_effect_version_is_refused() -> None:
    with pytest.raises(ValidationError, match="once per version"):
        parse_library({"version": 1, "entries": [_entry("corte"), _entry("corte")]})


def test_a_default_out_of_range_is_refused() -> None:
    entry = _entry("camara_rapida")
    entry["params"]["speed"]["default"] = 100.0
    with pytest.raises(ValidationError, match="default"):
        EffectEntry.model_validate(entry)


# ---------------------------------------------------------------------------
# One effect against the library: every refusal has its code


def _use(effect_id: str, version: int = 1, **params: Any) -> EffectUse:
    return EffectUse(effect_id=effect_id, version=version, params=params)


@pytest.mark.parametrize(
    ("use", "code"),
    [
        (_use("chispas"), "unknown_effect"),
        (_use("humo_capa", 7), "unknown_version"),
        (_use("humo_capa", color="rojo"), "unknown_param"),
        (_use("humo_capa", intensity=3.0), "param_out_of_range"),
        (_use("humo_capa", zone="left"), "param_out_of_range"),
        (_use("camara_rapida", speed="rápido"), "param_out_of_range"),
        (_use("humo_denso"), "not_offered"),
    ],
)
def test_an_effect_use_is_refused_with_its_code(use: EffectUse, code: str) -> None:
    assert _codes(effect_use_problems(use, OFFERING, part=1, field="effects[0]")) == [code]


def test_a_good_effect_use_has_no_problem() -> None:
    use = _use("humo_capa", intensity=0.8, zone="bottom")
    assert effect_use_problems(use, OFFERING, part=None, field="effects[0]") == ()


def test_an_unoffered_ai_effect_in_a_local_part_says_both() -> None:
    problems = part_effect_problems(
        (_use("brasas"),), LIBRARY, part=1, mode="local", has_own_video=True
    )
    assert _codes(problems) == ["not_offered", "local_with_ai_effect"]


def test_the_same_effect_twice_and_fast_motion_without_own_video_are_refused() -> None:
    problems = part_effect_problems(
        (_use("humo_capa"), _use("humo_capa"), _use("camara_rapida", speed=10)),
        OFFERING,
        part=1,
        mode="reference",
        has_own_video=False,
    )
    assert _codes(problems) == ["too_many_of_effect", "effect_needs_own_video"]


def test_a_transition_among_the_effects_is_refused() -> None:
    in_part = part_effect_problems(
        (_use("fundido"),), OFFERING, part=2, mode="reference", has_own_video=False
    )
    in_clip = part_effect_problems(
        (_use("fundido"),), OFFERING, part=None, mode="reference", has_own_video=False, in_clip=True
    )
    assert _codes(in_part) == ["transition_in_effects"]
    assert _codes(in_clip) == ["transition_on_clip"]


def test_a_span_past_the_part_is_refused() -> None:
    use = EffectUse(effect_id="humo_capa", version=1, start_s=3.0, end_s=7.0)
    problems = part_effect_problems(
        (use,), OFFERING, part=1, mode="reference", has_own_video=False, window=(0.0, 5.0)
    )
    assert _codes(problems) == ["span_outside_part"]


@pytest.mark.parametrize(
    ("transition", "first", "in_clip", "codes"),
    [
        (_use("fundido", duration_s=0.5), False, False, []),
        (_use("fundido"), True, False, ["transition_on_first_part"]),
        (_use("fundido"), False, True, ["transition_on_clip"]),
        (_use("humo_capa"), False, False, ["transition_not_a_transition"]),
        (_use("barrido", duration_s=3.0), False, False, ["param_out_of_range"]),
    ],
)
def test_a_transition_is_only_between_parts(
    transition: EffectUse, first: bool, in_clip: bool, codes: list[str]
) -> None:
    problems = transition_problems(transition, OFFERING, part=2, first=first, in_clip=in_clip)
    assert _codes(problems) == codes


# ---------------------------------------------------------------------------
# The recipe types: pure data, JSON both ways


def test_recipe_types_round_trip_through_json() -> None:
    plan = VideoPartPlan(
        mode="local",
        seconds=6,
        effects=(
            EffectUse(effect_id="camara_rapida", version=1, params={"speed": 12.0}),
            EffectUse(
                effect_id="humo_capa",
                version=1,
                params={"zone": "top", "intensity": 0.7},
                start_s=1.0,
                end_s=4.0,
            ),
        ),
        text_layer=VideoTextLayer(text="Shawarma mixto", place="top", start_s=0.5),
        segments=(
            SourceSegment(key="uploads/t/a.mp4", start_s=3.0, end_s=40.0, speed=12.0),
            SourceSegment(key="uploads/t/b.mp4", start_s=0.0, end_s=2.0, rotate=90),
        ),
        transition_in=EffectUse(effect_id="fundido", version=1, params={"duration_s": 0.4}),
        mode_rule_version=1,
        mode_reason="own_video_local",
        mode_changed_by_owner=True,
    )
    dumped = json.loads(plan.model_dump_json())
    assert dumped["effects"][1]["params"] == {"intensity": 0.7, "zone": "top"}
    again = VideoPartPlan.model_validate(dumped)
    assert again == plan and hash(again) == hash(plan)
    assert VideoPartPlan.model_validate(plan.model_dump()) == plan
    with pytest.raises(ValidationError):
        plan.effects[0].params = ()  # type: ignore[misc]


def test_params_are_immutable_and_order_free() -> None:
    a = EffectUse(effect_id="humo_capa", version=1, params={"zone": "top", "intensity": 0.5})
    b = EffectUse(effect_id="humo_capa", version=1, params={"intensity": 0.5, "zone": "top"})
    assert a == b and a.param_values == {"intensity": 0.5, "zone": "top"}
    a.param_values["zone"] = "bottom"  # a copy: the use itself never changes
    assert a.param_values["zone"] == "top"


@pytest.mark.parametrize(
    "bad",
    [
        {"effect_id": "Humo", "version": 1},
        {"effect_id": "humo_capa", "version": 0},
        {"effect_id": "humo_capa", "version": 1, "start_s": 2.0},
        {"effect_id": "humo_capa", "version": 1, "start_s": 2.0, "end_s": 1.0},
        {"effect_id": "humo_capa", "version": 1, "params": [["zone", "a"], ["zone", "b"]]},
    ],
)
def test_a_malformed_effect_use_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        EffectUse.model_validate(bad)


@pytest.mark.parametrize(
    "bad",
    [
        {"key": "uploads/t/a.mp4", "start_s": 2.0, "end_s": 1.0},
        {"key": "uploads/t/a.mp4", "start_s": 0.0, "end_s": 1.0, "rotate": 45},
        {"key": "uploads/t/a.mp4", "start_s": 0.0, "end_s": 1.0, "speed": 0},
        {"key": "", "start_s": 0.0, "end_s": 1.0},
    ],
)
def test_a_malformed_segment_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        SourceSegment.model_validate(bad)


def test_a_segment_lasts_its_stretch_at_its_speed() -> None:
    assert SourceSegment(key="k/t/a.mp4", start_s=0, end_s=60, speed=12).output_seconds == 5


def test_a_video_text_needs_words_and_order() -> None:
    with pytest.raises(ValidationError):
        VideoTextLayer(text="   ")
    with pytest.raises(ValidationError):
        VideoTextLayer(text="Hola", start_s=3.0, end_s=2.0)
    with pytest.raises(ValidationError):
        VideoTextLayer(text="Hola", place="left")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# `local` needs the owner's own video — a code, in the brief's own validator


def _error_types(exc: ValidationError) -> list[str]:
    return [e["type"] for e in exc.errors()]


def test_a_local_part_without_own_video_is_refused_with_its_code() -> None:
    with pytest.raises(ValidationError) as refused:
        VideoPartPlan(mode="local", seconds=5)
    assert _error_types(refused.value) == ["local_needs_own_video"]
    with pytest.raises(ValidationError) as refused:
        PartRef(index=1, mode="local", seconds=5, clip_video_keys=("uploads/t/ref.mp4",))
    assert _error_types(refused.value) == ["local_needs_own_video"]
    with pytest.raises(ValidationError) as refused:
        MediaInputs(clip_reference_mode="local", duration_seconds=5)
    assert _error_types(refused.value) == ["local_needs_own_video"]


def test_a_local_part_with_a_stretch_of_own_video_is_valid() -> None:
    segment = SourceSegment(key="uploads/t/a.mp4", start_s=0, end_s=5)
    assert VideoPartPlan(mode="local", seconds=5, segments=(segment,)).mode == "local"
    media = MediaInputs(clip_reference_mode="local", duration_seconds=5, segments=(segment,))
    assert media.effects_pipeline_version == 0


# ---------------------------------------------------------------------------
# ED-13 (m-25029108): a text's entrance and exit, closed


def test_a_video_text_moves_in_closed_ways_and_a_stored_one_reads_as_before() -> None:
    from qualify_creative import schemas

    stored = VideoTextLayer.model_validate({"text": "Hoy", "place": "top", "fade_s": 0.5})
    assert (stored.motion_in, stored.motion_out) == ("fade", "none")
    for motion_in in schemas.VIDEO_TEXT_MOTIONS_IN:
        for motion_out in schemas.VIDEO_TEXT_MOTIONS_OUT:
            layer = VideoTextLayer(text="Hoy", motion_in=motion_in, motion_out=motion_out)
            assert VideoTextLayer.model_validate_json(layer.model_dump_json()) == layer
    for bad in ({"motion_in": "spin"}, {"motion_out": "typewriter"}, {"motion_in": None}):
        with pytest.raises(ValidationError) as caught:
            VideoTextLayer.model_validate({"text": "Hoy", **bad})
        assert [e["type"] for e in caught.value.errors()] == ["unknown_text_motion"]
    # «Letra por letra»: up to 40 characters (the trimmed text), never more
    limit = schemas.VIDEO_TEXT_TYPEWRITER_MAX_CHARS
    assert VideoTextLayer(text=" " + "x" * limit + " ", motion_in="typewriter")
    with pytest.raises(ValidationError) as caught:
        VideoTextLayer(text="x" * (limit + 1), motion_in="typewriter")
    assert [e["type"] for e in caught.value.errors()] == ["typewriter_text_too_long"]
    assert VideoTextLayer(text="x" * (limit + 1), motion_in="zoom")
    # the contract's numbers
    assert schemas.VIDEO_TEXT_SLIDE_FRACTION == 0.05 and schemas.VIDEO_TEXT_ZOOM_FROM == 0.9
    assert schemas.VIDEO_TEXT_TYPEWRITER_S_PER_CHAR == 0.06
    assert schemas.VIDEO_TEXT_MOTION_MAX_SHARE == pytest.approx(1 / 3)


def test_a_video_text_box_colour_is_a_capital_hex_kept_only_when_picked() -> None:
    """ED-13 (Deivid, 2026-11-23): «Franja» / «Recuadro de tu color» in the owner's colour —
    `#RRGGBB` in capitals or refused (`bad_text_box_color`); not dumped while None, so a
    stored text keeps its shape; it counts only on `band` / `brand_fill`."""
    from qualify_creative import schemas

    plain = VideoTextLayer(text="Hoy", layout_id="band", layout_version=3)
    assert plain.box_color is None and "box_color" not in plain.model_dump(mode="json")
    picked = VideoTextLayer(text="Hoy", layout_id="band", layout_version=3, box_color="#FFE600")
    assert picked.model_dump(mode="json")["box_color"] == "#FFE600"
    assert VideoTextLayer.model_validate_json(picked.model_dump_json()) == picked
    assert list(VideoTextLayer.model_fields)[-3:] == ["box_color", "text_color", "text_size"]
    assert picked.effective_box_color == "#FFE600"
    fill = VideoTextLayer(text="Hoy", layout_id="brand_fill", layout_version=3, box_color="#111111")
    assert fill.effective_box_color == "#111111"
    for layout in ("scrim", "shadow"):
        ignored = VideoTextLayer(
            text="Hoy", layout_id=layout, layout_version=3, box_color="#FFE600"
        )
        assert ignored.effective_box_color is None
    assert VideoTextLayer(text="Hoy", box_color="#FFE600").effective_box_color is None
    for bad in ("#ffe600", "#FFF", "red", "#FFE6001A", 0xFFE600, ""):
        with pytest.raises(ValidationError) as caught:
            VideoTextLayer.model_validate({"text": "Hoy", "box_color": bad})
        assert [e["type"] for e in caught.value.errors()] == ["bad_text_box_color"]
    assert schemas.VIDEO_TEXT_BOX_COLOR_LAYOUTS == ("band", "brand_fill")
    assert (schemas.VIDEO_TEXT_INK_LIGHT, schemas.VIDEO_TEXT_INK_DARK) == ("#FFFFFF", "#111111")
    assert not hasattr(schemas, "VIDEO_TEXT_SHADOW")


def test_a_video_text_letters_colour_counts_only_without_a_background() -> None:
    """ED-13 round 3 (Deivid, 2026-11-23): «Sin fondo»'s letters in the owner's colour —
    `#RRGGBB` in capitals or refused (`bad_text_color`); not dumped while None; it counts
    only on `shadow`."""
    from qualify_creative import schemas

    plain = VideoTextLayer(text="Hoy", layout_id="shadow", layout_version=3)
    assert plain.text_color is None and "text_color" not in plain.model_dump(mode="json")
    picked = VideoTextLayer(text="Hoy", layout_id="shadow", layout_version=3, text_color="#111111")
    assert picked.model_dump(mode="json")["text_color"] == "#111111"
    assert VideoTextLayer.model_validate_json(picked.model_dump_json()) == picked
    assert picked.effective_text_color == "#111111"
    for layout in ("scrim", "band", "brand_fill"):
        ignored = VideoTextLayer(
            text="Hoy", layout_id=layout, layout_version=3, text_color="#111111"
        )
        assert ignored.effective_text_color is None
    assert VideoTextLayer(text="Hoy", text_color="#111111").effective_text_color is None
    for bad in ("#111", "#2563eb", "black", "#1111111A", 0x111111, ""):
        with pytest.raises(ValidationError) as caught:
            VideoTextLayer.model_validate({"text": "Hoy", "text_color": bad})
        assert [e["type"] for e in caught.value.errors()] == ["bad_text_color"]
    assert schemas.VIDEO_TEXT_TEXT_COLOR_LAYOUTS == ("shadow",)


# ---------------------------------------------------------------------------
# D1: the video text names an ADR 49 design, never a style of its own


def test_a_video_text_names_its_design_with_both_fields() -> None:
    from qualify_creative.effects import text_layer_problems
    from qualify_creative.layer_spec import LAYOUT_VERSION, LayoutId

    named = VideoTextLayer(text="Hola", layout_id=LayoutId.SCRIM, layout_version=LAYOUT_VERSION)
    assert VideoTextLayer.model_validate_json(named.model_dump_json()) == named
    assert text_layer_problems(named, part=1) == ()
    assert text_layer_problems(VideoTextLayer(text="Hola"), part=1) == ()
    with pytest.raises(ValidationError, match="layout"):
        VideoTextLayer(text="Hola", layout_id=LayoutId.BAND)
    # ED-13 (m-25029108): the four backgrounds the video's text layer draws are accepted —
    # `shadow` («Sin fondo») is no ADR 49 design and names the catalog version all the same
    for layout_id in (LayoutId.SCRIM, LayoutId.BAND, LayoutId.BRAND_FILL, "shadow"):
        layer = VideoTextLayer(text="Hola", layout_id=layout_id, layout_version=LAYOUT_VERSION)
        assert text_layer_problems(layer, part=1) == (), layout_id
        assert VideoTextLayer.model_validate_json(layer.model_dump_json()) == layer
    # a design the video's text layer does not draw (plate, photo_only…), or a stale
    # version — of `shadow` too — is refused
    for layout_id, version in (
        (LayoutId.PHOTO_ONLY, LAYOUT_VERSION),
        (LayoutId.BAND, 99),
        ("shadow", 99),
        (LayoutId.PLATE, LAYOUT_VERSION),
        (LayoutId.INFO_CARD, LAYOUT_VERSION),
    ):
        layer = VideoTextLayer(text="Hola", layout_id=layout_id, layout_version=version)
        problems = text_layer_problems(layer, part=2)
        assert [(p.code, p.part, p.field) for p in problems] == [
            ("unknown_layout", 2, "text_layer.layout_id")
        ]


# ---------------------------------------------------------------------------
# Criterion 4: what v1 offers, and every non-null preview exists


def test_seedance_templates_are_unmeasured_unoffered_and_seedless() -> None:
    templates = [e for e in LIBRARY.entries if e.stage == "seedance_prompt"]
    assert len(templates) == 5
    for entry in templates:
        assert entry.measured is None and not entry.offered and entry.preview_asset is None
        assert entry.prompt_version and "{zone}" in entry.prompt_template
        assert "{subject}" in entry.prompt_template
    assert all("seed" not in e for e in RAW["entries"])


def test_v1_offers_only_what_the_browser_simulates() -> None:
    offered = LIBRARY.offered()
    assert [e.id for e in offered] == ["texto", "corte", "fundido", "barrido"]
    assert all(e.simulated_in_browser and e.preview_asset is None for e in offered)


def test_layers_stay_in_v1_unoffered_and_without_preview() -> None:
    for name in ("humo_capa", "brasas_capa", "vapor_capa"):
        entry = LIBRARY.get(name, 1)
        assert entry is not None and not entry.offered and entry.preview_asset is None
        assert entry.asset == f"effects/{name}/v1/" and entry.blend == "screen"
        assert not entry.simulated_in_browser


def test_an_unoffered_layer_cannot_be_chosen() -> None:
    problems = effect_use_problems(_use("humo_capa"), LIBRARY, part=1, field="effects[0]")
    assert [(p.code, p.field) for p in problems] == [("not_offered", "effects[0]")]


def test_an_offered_layer_without_its_preview_is_refused() -> None:
    entry = {**_entry("humo_capa"), "offered": True}
    with pytest.raises(ValidationError, match="preview"):
        parse_library(_with(entry))


def test_an_offered_ai_effect_needs_its_bench_and_its_example() -> None:
    entry = {**_entry("humo_denso"), "offered": True}
    with pytest.raises(ValidationError, match="measured"):
        parse_library(_with(entry))
    entry["measured"] = {
        "successes": 4,
        "n": 5,
        "wilson_low": 0.38,
        "wilson_high": 0.96,
        "measured_on": "2026-11-20",
        "model": "dreamina-seedance-2-5-260628",
    }
    with pytest.raises(ValidationError, match="preview"):
        parse_library(_with(entry))


def test_a_preview_whose_file_is_missing_is_refused(tmp_path: Path) -> None:
    entry = {
        **_entry("humo_capa"),
        "offered": True,
        "preview_asset": "effects/humo_capa/v1/no-existe.webm",
    }
    with pytest.raises(MissingPreviewAsset, match="no-existe.webm"):
        parse_library(_with(entry), assets_root=tmp_path)
    with pytest.raises(MissingPreviewAsset):
        parse_library(_with(entry))  # nor in the packaged folder


def test_a_preview_whose_file_exists_passes(tmp_path: Path) -> None:
    preview = "effects/humo_capa/v1/preview.webm"
    (tmp_path / "humo_capa" / "v1").mkdir(parents=True)
    (tmp_path / "humo_capa" / "v1" / "preview.webm").write_bytes(b"webm")
    assert preview_file(preview, tmp_path) == tmp_path / "humo_capa" / "v1" / "preview.webm"
    entry = {**_entry("humo_capa"), "offered": True, "preview_asset": preview}
    assert parse_library(_with(entry), assets_root=tmp_path).entries[0].offered


def test_the_packaged_assets_folder_exists() -> None:
    folder = preview_file("effects/x/v1/y").parents[2]
    assert folder.name == "effects_assets" and (folder / "README.md").is_file()


# ---------------------------------------------------------------------------
# Criterion 2: more than one «Con IA» effect per part, when both are offered


def test_more_than_one_ai_effect_per_part_is_refused(tmp_path: Path) -> None:
    measured = _offering(tmp_path, ("brasas", "humo_denso"), measured=True)
    assert all(measured.get(n, 1).offered for n in ("brasas", "humo_denso"))
    problems = part_effect_problems(
        (_use("brasas"), _use("humo_denso")),
        measured,
        part=2,
        mode="reference",
        has_own_video=False,
    )
    assert [(p.code, p.part, p.field) for p in problems] == [
        ("too_many_ai_effects", 2, "effects[1]")
    ]  # the limit, not «not offered»
    local = part_effect_problems(
        (_use("brasas"),), measured, part=1, mode="local", has_own_video=True
    )
    assert _codes(local) == ["local_with_ai_effect"]


def test_fast_motion_is_a_stretchs_speed_not_an_effect_to_choose() -> None:
    """D-T3: «Cámara rápida» is `SourceSegment.speed`. The v1 entry stays, NOT offered and
    without a preview, for EF-04's provenance — choosing it in a part or a Clip is
    `not_offered`."""
    entry = LIBRARY.get("camara_rapida", 1)
    assert entry is not None and not entry.offered and entry.preview_asset is None
    for part, in_clip in ((2, False), (None, True)):
        problems = part_effect_problems(
            (_use("camara_rapida", speed=8.0),),
            LIBRARY,
            part=part,
            mode="local",
            has_own_video=True,
            in_clip=in_clip,
        )
        assert [(p.code, p.part) for p in problems] == [("not_offered", part)]


# ---------------------------------------------------------------------------
# D-T3: one speed range — the stretch's, the speed step's (EF-04) and fast motion's


def test_segment_speed_bounds_match_the_speed_step() -> None:
    """`schemas` copies the bounds instead of importing `video` (PyAV): pinned here."""
    from qualify_creative.schemas import (
        LOCAL_TOTAL_MAX_S,
        LOCAL_TOTAL_MIN_S,
        SEGMENT_SPEED_MAX,
        SEGMENT_SPEED_MIN,
    )
    from qualify_creative.video.speed import MAX_SPEED, MAX_TOTAL_S, MIN_SPEED, MIN_TOTAL_S

    assert (SEGMENT_SPEED_MIN, SEGMENT_SPEED_MAX) == (MIN_SPEED, MAX_SPEED) == (1.0, 30.0)
    assert (LOCAL_TOTAL_MIN_S, LOCAL_TOTAL_MAX_S) == (MIN_TOTAL_S, MAX_TOTAL_S) == (3.0, 60.0)
    spec = LIBRARY.get("camara_rapida", 1).params["speed"]  # provenance of EF-04's step
    assert (spec.min, spec.max) == (MIN_SPEED, MAX_SPEED)


@pytest.mark.parametrize(("speed", "ok"), [(0.5, False), (45.0, False), (1.0, True), (30.0, True)])
def test_a_stretch_plays_between_1x_and_30x(speed: float, ok: bool) -> None:
    def stretch() -> SourceSegment:
        return SourceSegment(key="uploads/t/a.mp4", start_s=0.0, end_s=10.0, speed=speed)

    if ok:
        assert stretch().speed == speed
    else:
        with pytest.raises(ValidationError, match="speed"):
            stretch()


def test_a_span_falls_in_its_parts_own_length() -> None:
    """Times are seconds of the part's own output, from its start: a 5 s part takes [1, 2],
    not [6, 7]."""
    inside = EffectUse(effect_id="texto", version=1, start_s=1.0, end_s=2.0)
    outside = EffectUse(effect_id="texto", version=1, start_s=6.0, end_s=7.0)
    for use, codes in ((inside, []), (outside, ["span_outside_part"])):
        problems = part_effect_problems(
            (use,), LIBRARY, part=3, mode="reference", has_own_video=False, window=(0.0, 5.0)
        )
        assert _codes(problems) == codes


# ---------------------------------------------------------------------------
# Categories (Deivid, 2026-11-16): for filtering, never for hiding


def _v3_raw() -> dict[str, Any]:
    path = Path(__file__).parents[1] / "src" / "qualify_creative" / "effects_data" / "v3.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_v3_names_a_category_for_every_entry() -> None:
    from qualify_creative.effects import EFFECT_CATEGORIES

    library = load_effects("v3")
    assert all(entry.categories for entry in library.entries)
    assert {c for e in library.entries for c in e.categories} <= set(EFFECT_CATEGORIES)
    by_id = {e.id: e.categories for e in library.entries}
    assert by_id["humo_capa"] == by_id["brasas_capa"] == by_id["vapor_capa"] == ("comida",)
    assert by_id["texto"] == ("texto",) and by_id["camara_rapida"] == ("movimiento",)
    assert by_id["corte"] == by_id["fundido"] == by_id["barrido"] == ("transicion",)


@pytest.mark.parametrize("categories", [[], ["postres"], ["comida", "comida"]])
def test_a_v3_entry_without_a_known_single_category_is_refused(categories: list[str]) -> None:
    raw = _v3_raw()
    raw["entries"][0]["categories"] = categories
    with pytest.raises(ValidationError):
        parse_library(raw)


def test_a_v3_entry_with_no_categories_key_is_refused() -> None:
    raw = _v3_raw()
    del raw["entries"][0]["categories"]
    with pytest.raises(ValidationError, match="category"):
        parse_library(raw)


def test_v1_and_v2_have_no_categories_and_read_as_before() -> None:
    for version in ("v1", "v2"):
        library = load_effects(version)
        assert all(entry.categories == () for entry in library.entries)
        path = Path(__file__).parents[1] / "src" / "qualify_creative" / "effects_data"
        raw = json.loads((path / f"{version}.json").read_text(encoding="utf-8"))
        assert all("categories" not in entry for entry in raw["entries"])


def test_the_offer_does_not_depend_on_the_category() -> None:
    v2, v3 = load_effects("v2"), load_effects("v3")
    layers = {"humo_capa", "brasas_capa", "vapor_capa"}
    # the same offer as v2 plus the recorded layers, whatever their category
    assert (
        [e.id for e in v3.offered()]
        == [e.id for e in v3.entries if e.offered]
        == [e.id for e in v2.entries if e.offered or e.id in layers]
    )
    # and a library with every category changed offers exactly the same effects
    raw = _v3_raw()
    for entry in raw["entries"]:
        entry["categories"] = ["general"]
    assert [e.id for e in parse_library(raw).offered()] == [e.id for e in v3.offered()]


def test_no_library_method_filters_by_business() -> None:
    import inspect

    from qualify_creative.effects import EffectsLibrary

    for name, member in inspect.getmembers(EffectsLibrary, inspect.isfunction):
        if name.startswith("_"):
            continue
        params = set(inspect.signature(member).parameters) - {"self"}
        assert not params & {"tenant_id", "tenant", "business", "brand_id", "category"}, name


# --- ADR 50 D9 (Deivid, 2026-11-20): only `corte` is offered until EF-16 ------------------


def test_v4_offers_corte_as_its_only_transition() -> None:
    """D9: the join does not draw `fundido` nor `barrido` yet, so the library new requests
    use offers only `corte` among the transitions — the screen never offers what creating
    would refuse (v4; EF-16 offers them again in v5)."""
    library = load_effects("v4")
    assert library.version == 4
    assert [e.id for e in library.offered() if e.stage == "transition"] == ["corte"]
    for name in ("fundido", "barrido"):
        entry = library.get(name, 1)
        assert entry is not None and not entry.offered


def test_v4_is_v3_but_for_the_hidden_transitions() -> None:
    """v4 only flips `offered` of `fundido` and `barrido` (entry version 1, same params):
    every other field of every entry is v3's, and v3 still reads as it was."""
    v3, v4 = load_effects("v3"), load_effects("v4")
    hidden = ("fundido", "barrido")
    assert [(e.id, e.version) for e in v3.entries] == [(e.id, e.version) for e in v4.entries]
    for old, new in zip(v3.entries, v4.entries, strict=True):
        changed = {"offered"} if new.id in hidden else set()
        assert old.model_dump(exclude=changed) == new.model_dump(exclude=changed)
    assert [e.id for e in v3.offered() if e.stage == "transition"] == ["corte", *hidden]
    assert [e.id for e in v4.offered()] == [e.id for e in v3.offered() if e.id not in hidden]


@pytest.mark.parametrize(
    ("use", "codes"),
    [
        (EffectUse(effect_id="corte", version=1), []),
        (EffectUse(effect_id="fundido", version=1, params={"duration_s": 0.5}), ["not_offered"]),
        (EffectUse(effect_id="barrido", version=1), ["not_offered"]),
    ],
)
def test_choosing_a_hidden_transition_is_not_offered(use: EffectUse, codes: list[str]) -> None:
    """D9: between two parts, `corte` passes the library's checks; `fundido` and `barrido`
    are `not_offered` — refused when the plan is saved, not only when it is created."""
    problems = transition_problems(use, load_effects("v4"), part=2, first=False, in_clip=False)
    assert _codes(problems) == codes


# --- EF-16 (m-25026594): the join draws them, v5 offers them again -------------------------


def test_v5_offers_the_three_transitions_the_join_makes() -> None:
    library = load_effects()
    assert library.version == 5
    offered = [(e.id, e.version) for e in library.offered() if e.stage == "transition"]
    assert offered == [("corte", 1), ("fundido", 2), ("barrido", 2)]
    for name in ("fundido", "barrido"):  # version 1 stays, unoffered: old briefs still read
        old = library.get(name, 1)
        assert old is not None and not old.offered


def test_v5_is_v4_plus_the_two_new_transitions() -> None:
    v4, v5 = load_effects("v4"), load_effects("v5")
    added = {("fundido", 2), ("barrido", 2)}
    assert [(e.id, e.version) for e in v5.entries if (e.id, e.version) not in added] == [
        (e.id, e.version) for e in v4.entries
    ]
    for old in v4.entries:
        assert v5.get(old.id, old.version) == old  # nothing edited in place


def test_v5_transitions_are_what_the_join_draws() -> None:
    """Drift guard: the library's ranges are the join's (`JoinTransition`), so an owner
    can never choose a duration or a direction the join refuses."""
    from qualify_creative.video.join import TRANSITION_MAX_S, TRANSITION_MIN_S, WIPE_DIRECTIONS

    library = load_effects()
    for name in ("fundido", "barrido"):
        spec = library.get(name, 2).params["duration_s"]
        assert (spec.min, spec.max) == (TRANSITION_MIN_S, TRANSITION_MAX_S)
        assert TRANSITION_MIN_S <= float(spec.default) <= TRANSITION_MAX_S
    direction = library.get("barrido", 2).params["direction"]
    assert direction.values == WIPE_DIRECTIONS
    assert set(library.get("fundido", 2).params) == {"duration_s"}


@pytest.mark.parametrize(
    ("use", "codes"),
    [
        (EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5}), []),
        (EffectUse(effect_id="barrido", version=2, params={"direction": "up"}), []),
        (
            EffectUse(effect_id="fundido", version=2, params={"duration_s": 1.0}),
            ["param_out_of_range"],
        ),
        (EffectUse(effect_id="fundido", version=1), ["not_offered"]),
    ],
)
def test_choosing_a_v5_transition(use: EffectUse, codes: list[str]) -> None:
    problems = transition_problems(use, load_effects(), part=2, first=False, in_clip=False)
    assert _codes(problems) == codes
