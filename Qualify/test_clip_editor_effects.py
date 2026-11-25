"""ED-04 (m-25026627): the effects as blocks of «Arma tu video».

- each effect put is a block with its start and end, moved and trimmed like a text, the
  same effect several times but never twice at once, at most 8 in all;
- «+ Pista» (Deivid 2026-11-17): rows of «Efectos», screen only — the recipe is the same;
- the preview's layer as strong as the final video (the library's default intensity as
  its CSS `opacity`, EF-08 `effects_data/v3.json`) and still with reduced motion;
- the list by the business's rubro first, «Todos» with every effect (Deivid 2026-11-16);
- «¿En qué partes va?» (Deivid 2026-11-17): one effect per group of blocks side by side,
  stuck to them when they move, are cut or removed.

A standalone `CreativeState`, handlers called through `.fn` (`test_creative_state.py`
explains why); the view model's rules tested on their own."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
import qualify_creative

from . import clip_editor_vm as vm
from . import creative_state as module
from . import edit_sequence
from . import editor_preview_contract as contract
from .creative_state import CreativeState
from .ui import edit_preview as ep

_PHOTO = "uploads/t/clip/foto.jpg"
_KEY = "uploads/t/clip/video.mp4"
_SECOND = "uploads/t/clip/otro.mp4"
_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND = UUID("c0000000-0000-4000-8000-000000000003")
_LIBRARY = Path(qualify_creative.__file__).parent / "effects_data" / "v3.json"
_ASSETS = Path(__file__).resolve().parent.parent / "assets"


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vm, "CLIP_EDITOR_ON", True)


def _three() -> CreativeState:
    """Block 1 a photo (0:00–0:02), block 2 the own video (20 s: its first 15 s,
    0:02–0:17), block 3 a second video (8 s, 0:17–0:25)."""
    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    state.clip_images = [{"key": _PHOTO, "name": "foto.jpg", "source": "upload", "role": "product"}]
    state.clip_videos = [
        {"key": _KEY, "name": "video.mp4", "source": "upload"},
        {"key": _SECOND, "name": "otro.mp4", "source": "upload"},
    ]
    state.clip_sequence = [_PHOTO, _KEY, _SECOND]
    CreativeState.report_clip_source.fn(state, _KEY, 20.0, 1080, 1920)
    CreativeState.report_clip_media.fn(state, _SECOND, 8.0, 1080, 1920)
    return state


def _spans(state: CreativeState) -> list[tuple[str, float, float]]:
    return [(str(u["effect_id"]), u["start"], u["end"]) for u in state._clip_effect_resolved()]  # type: ignore[misc]


def _put(state: CreativeState, effect_id: str, parts: list[str]) -> None:
    """«+ Efecto» with `parts` marked in «¿En qué partes va?», then the effect."""
    CreativeState.open_clip_flow.fn(state, vm.FLOW_EFFECT)
    for block in [r["id"] for r in state.clip_effect_part_rows]:
        if (block in parts) != (block in state.clip_effect_parts):
            CreativeState.toggle_clip_effect_part.fn(state, block)
    CreativeState.add_clip_effect.fn(state, effect_id)


def _use(uid: str, effect_id: str, start: float, end: float, lane: int = 0) -> dict[str, object]:
    return {
        "uid": uid,
        "effect_id": effect_id,
        "start": start,
        "end": end,
        "lane": lane,
        "blocks": [],
    }


# -- «¿En qué partes va?» -------------------------------------------------------------------


def test_part_groups_are_blocks_side_by_side() -> None:
    media = [{"id": n, "kind": "photo", "dur": 2.0} for n in ("a", "b", "c")]
    assert vm.part_groups(media, ["a", "b"]) == [["a", "b"]]
    assert vm.part_groups(media, ["c", "a"]) == [["a"], ["c"]]
    assert vm.part_groups(media, []) == []


def test_marking_blocks_1_and_2_gives_one_effect_to_the_end_of_block_2(
    editor_on: None,
) -> None:
    state = _three()
    _put(state, "vapor_capa", [_PHOTO, _KEY])
    assert _spans(state) == [("vapor_capa", 0.0, 17.0)]
    assert state.clip_effect_uses[0]["blocks"] == [_PHOTO, _KEY]
    (use,) = state._clip_edit_recipe().effects
    assert (use.effect_id, use.start_s, use.end_s) == ("vapor_capa", 0.0, 17.0)
    assert state.clip_edit_notice == "Pusiste Vapor."


def test_marking_blocks_1_and_3_gives_two_effects(editor_on: None) -> None:
    state = _three()
    _put(state, "vapor_capa", [_PHOTO, _SECOND])
    assert _spans(state) == [("vapor_capa", 0.0, 2.0), ("vapor_capa", 17.0, 25.0)]
    recipe = state._clip_edit_recipe()
    assert [(u.start_s, u.end_s) for u in recipe.effects] == [(0.0, 2.0), (17.0, 25.0)]
    assert contract.recipe_problems(recipe) == []
    assert state.clip_edit_notice == "Pusiste Vapor en 2 partes."


def test_the_parts_open_on_the_chosen_block_else_on_all(editor_on: None) -> None:
    state = _three()
    events = CreativeState.open_clip_flow.fn(state, vm.FLOW_EFFECT)
    assert state.clip_effect_parts == [_PHOTO, _KEY, _SECOND]
    # the business's rubro is read once, when «+ Efecto» first opens
    assert CreativeState.load_clip_effect_rubro in events
    CreativeState.done_clip_block.fn(state)
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.open_clip_flow.fn(state, vm.FLOW_EFFECT)
    assert state.clip_effect_parts == [_KEY]
    assert [r["on"] for r in state.clip_effect_part_rows] == ["", "1", ""]
    assert state.clip_effect_part_rows[1]["name"] == "Video 2, de 0:02 a 0:17"
    # none marked: nothing to put, and it says so
    CreativeState.toggle_clip_effect_part.fn(state, _KEY)
    assert state.clip_effect_add_reason == vm.PARTS_NONE
    assert CreativeState.add_clip_effect.fn(state, "vapor_capa") == []
    assert state.clip_effect_uses == []


def test_moving_block_2_moves_the_effect_stuck_to_it(editor_on: None) -> None:
    state = _three()
    _put(state, "vapor_capa", [_KEY])
    assert _spans(state) == [("vapor_capa", 2.0, 17.0)]
    CreativeState.drop_clip_block.fn(state, _KEY, "move", 0)  # the video first now
    assert _spans(state) == [("vapor_capa", 0.0, 15.0)]
    effects = state._clip_sequence().effects
    assert (effects[0].start, effects[0].end) == (0.0, 15.0)


def test_a_group_split_by_a_move_becomes_one_effect_per_group(editor_on: None) -> None:
    state = _three()
    _put(state, "vapor_capa", [_PHOTO, _KEY])
    CreativeState.drop_clip_block.fn(state, _SECOND, "move", 1)  # between them now
    assert _spans(state) == [("vapor_capa", 0.0, 2.0), ("vapor_capa", 10.0, 25.0)]
    assert [u["blocks"] for u in state.clip_effect_uses] == [[_PHOTO], [_KEY]]


def test_a_cut_keeps_the_effect_on_both_halves(editor_on: None) -> None:
    state = _three()
    _put(state, "vapor_capa", [_KEY])
    CreativeState.select_clip_block.fn(state, _KEY)
    state.clip_edit_playhead = 8.0
    CreativeState.cut_clip_video.fn(state)
    second = vm.piece_id(_KEY, 1)
    assert [r["id"] for r in state.clip_tl_media_rows] == [_PHOTO, _KEY, second, _SECOND]
    assert state.clip_effect_uses[0]["blocks"] == [_KEY, second]
    assert _spans(state) == [("vapor_capa", 2.0, 17.0)]


def test_a_trim_moves_the_effect_end(editor_on: None) -> None:
    state = _three()
    _put(state, "vapor_capa", [_KEY])
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 10.0)  # 15 s → 10 s of video
    assert _spans(state) == [("vapor_capa", 2.0, 12.0)]


def test_removing_the_only_block_of_an_effect_removes_it_and_says_so(editor_on: None) -> None:
    state = _three()
    _put(state, "vapor_capa", [_PHOTO])
    CreativeState.select_clip_block.fn(state, _PHOTO)
    CreativeState.clip_block_action.fn(state, vm.REMOVE)
    assert state.clip_effect_uses == []
    assert state.clip_edit_notice == (
        "Quitaste la foto 1. También quitamos Vapor, que iba solo en esa parte."
    )


def test_the_pieces_are_renamed_by_place() -> None:
    assert vm.cut_mapping("k", 2, 0) == {"k": ["k", "k#parte-2"], "k#parte-2": ["k#parte-3"]}
    assert vm.removed_mapping("k", 3, 1) == {
        "k": ["k"],
        "k#parte-2": [],
        "k#parte-3": ["k#parte-2"],
    }
    assert vm.order_mapping("k", [1, 0]) == {"k#parte-2": ["k"], "k": ["k#parte-2"]}
    uses = [{"uid": "u1", "blocks": ["k", "k#parte-2"]}]
    assert vm.remap_effect_blocks(uses, vm.collapse_mapping("k", 2))[0]["blocks"] == ["k"]


# -- the blocks: times, rows, limits ----------------------------------------------------------


def test_two_uses_of_vapor_go_as_two_effect_uses(editor_on: None) -> None:
    """Criterion: two Vapor blocks, 0:00–0:03 and 0:06–0:09, are two `EffectUse`; the
    preview shows Vapor in those seconds only."""
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 3), _use("u2", "vapor_capa", 6, 9)]
    recipe = state._clip_edit_recipe()
    assert [(u.effect_id, u.start_s, u.end_s) for u in recipe.effects] == [
        ("vapor_capa", 0.0, 3.0),
        ("vapor_capa", 6.0, 9.0),
    ]
    assert contract.recipe_problems(recipe) == []
    sequence = state._clip_sequence()
    assert sequence.overlays_at(1.0)[1] == [0]
    assert sequence.overlays_at(4.5)[1] == []
    assert sequence.overlays_at(8.9)[1] == [1]
    assert sequence.overlays_at(9.0)[1] == []


def test_each_block_reads_its_effect_and_its_seconds(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 4, 9)]
    (row,) = state.clip_tl_effect_rows
    assert row["name"] == "Vapor, de 0:04 a 0:09"
    assert row["panel"] == "Vapor · de 0:04 a 0:09"
    assert row["id"] == "efecto-u1"


def test_two_effects_at_the_same_time_go_on_two_rows_with_their_names(editor_on: None) -> None:
    state = _three()
    _put(state, "vapor_capa", [_PHOTO, _KEY, _SECOND])
    _put(state, "brasas_capa", [_KEY])
    lanes = state.clip_tl_effect_lanes
    assert [[r["label"] for r in lane] for lane in lanes] == [["Vapor"], ["Brasas"]]
    assert [n["name"] for n in state.clip_tl_effect_lane_names] == ["Efectos 1", "Efectos 2"]
    # the recipe does not change: two uses, whatever row they sit on
    assert [u.effect_id for u in state._clip_edit_recipe().effects] == [
        "vapor_capa",
        "brasas_capa",
    ]


def test_the_same_effect_never_twice_at_once(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 3, 0), _use("u2", "vapor_capa", 6, 9, 1)]
    # a handle stops at the edge of the other use
    CreativeState.drop_clip_block.fn(state, "efecto-u1", "end", 8.0)
    assert _spans(state)[0] == ("vapor_capa", 0.0, 6.0)
    # a whole block dropped half on it takes only the free room (Deivid 2026-11-20)
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 3, 0), _use("u2", "vapor_capa", 6, 9, 1)]
    CreativeState.drop_clip_block.fn(state, "efecto-u1", "time", 5.0)
    assert _spans(state)[0] == ("vapor_capa", 5.0, 6.0)
    assert state.clip_edit_notice == ("Cambiaste cuándo sale Vapor. Lo acortamos al espacio libre.")
    # and «+ Efecto» says so (Vapor is on 0:03–0:09, inside the video's block)
    _put(state, "vapor_capa", [_KEY])
    assert (
        state.clip_effect_error
        == "Vapor ya está en esa parte. Un mismo efecto no puede ir dos veces a la vez."
    )


def test_a_dragged_effect_gets_its_own_seconds(editor_on: None) -> None:
    state = _three()
    _put(state, "vapor_capa", [_KEY])
    block = state.clip_edit_block
    CreativeState.nudge_clip_block.fn(state, block, "start", 0.5)
    (use,) = state.clip_effect_uses
    assert (use["start"], use["end"], use["blocks"]) == (2.5, 17.0, [])


def test_eight_effects_turn_plus_efecto_off(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [
        _use(f"u{n}", effect, float(start), float(start) + 2.0, lane)
        for n, (effect, start, lane) in enumerate(
            [
                ("vapor_capa", 0, 0),
                ("vapor_capa", 4, 0),
                ("vapor_capa", 8, 0),
                ("humo_capa", 0, 1),
                ("humo_capa", 4, 1),
                ("humo_capa", 8, 1),
                ("brasas_capa", 0, 2),
                ("brasas_capa", 4, 2),
            ],
            start=1,
        )
    ]
    assert vm.EFFECTS_FULL == "Ya usas 8 efectos. Quita uno para poner otro."
    CreativeState.open_clip_flow.fn(state, vm.FLOW_EFFECT)
    assert state.clip_effect_add_reason == vm.EFFECTS_FULL
    CreativeState.add_clip_effect.fn(state, "brasas_capa")
    assert len(state.clip_effect_uses) == 8 and state.clip_effect_error == vm.EFFECTS_FULL


def test_an_effect_repeats_only_as_often_as_the_library_lets_it(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [
        _use(f"u{n}", "vapor_capa", n * 3.0, n * 3.0 + 1, 0) for n in range(3)
    ]
    _put(state, "vapor_capa", [_SECOND])
    assert (
        state.clip_effect_error
        == "Ya pusiste Vapor 3 veces. Quítalo de una parte para ponerlo en otra."
    )
    assert vm.effect_max_uses("vapor_capa") == 3


def test_too_many_parts_for_the_room_left(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [
        _use(f"u{n}", effect, 20.0 + n * 0.1, 20.05 + n * 0.1, n)
        for n, effect in enumerate(["vapor_capa", "humo_capa", "brasas_capa"] * 2 + ["humo_capa"])
    ]
    _put(state, "brasas_capa", [_PHOTO, _SECOND])
    assert state.clip_effect_error == vm.effects_room_line(2, 1)


def test_quitar_removes_only_that_block(editor_on: None) -> None:
    state = _three()
    _put(state, "vapor_capa", [_PHOTO, _SECOND])
    assert state.clip_edit_block == "efecto-u1"  # the first one put is chosen
    CreativeState.clip_block_action.fn(state, vm.REMOVE)
    assert _spans(state) == [("vapor_capa", 17.0, 25.0)]
    assert state.clip_edit_notice == "Quitaste Vapor."


def test_before_crear_an_effect_twice_at_once_is_said() -> None:
    uses = (
        contract.EffectUse("vapor_capa", 1, start_s=0.0, end_s=4.0),
        contract.EffectUse("vapor_capa", 1, start_s=2.0, end_s=6.0),
    )
    assert vm.effects_problem(uses) == vm.EFFECT_TWICE_LINE
    many = tuple(contract.EffectUse("vapor_capa", 1, start_s=n, end_s=n + 1.0) for n in range(9))
    assert vm.effects_problem(many) == vm.too_many_effects_line(9)


# -- the preview as strong as the final video (EF-08 v3) ---------------------------------------


def test_the_preview_opacity_is_the_library_intensity() -> None:
    library = json.loads(_LIBRARY.read_text(encoding="utf-8"))
    layers = {
        entry["id"]: entry["params"]["intensity"]["default"]
        for entry in library["entries"]
        if entry.get("preview_asset") and "intensity" in entry.get("params", {})
    }
    assert layers == {"humo_capa": 0.6, "brasas_capa": 0.5, "vapor_capa": 0.5}
    for effect in contract.CLIP_EFFECTS:
        if effect.preview_asset:
            assert vm.effect_opacity(effect.effect_id) == layers[effect.effect_id]
    assert vm.effect_opacity("camara_rapida") == 1.0  # no layer: nothing to fade


def test_the_sequence_carries_each_layer_opacity(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "humo_capa", 0, 3), _use("u2", "vapor_capa", 3, 6)]
    effects = state._clip_sequence().effects
    assert [(e.effect_id, e.opacity) for e in effects] == [("humo_capa", 0.6), ("vapor_capa", 0.5)]
    assert [e.url for e in effects] == [
        "/effects/humo_capa/v1/preview.webm",
        "/effects/vapor_capa/v1/preview.webm",
    ]
    assert [row["opacity"] for row in state.clip_seq_effects] == ["0.6", "0.5"]
    data = json.loads(state._clip_sequence().to_json())
    assert data["effects"][0]["opacity"] == 0.6


def test_a_recipe_sequence_takes_the_opacity_too() -> None:
    recipe = contract.PartRecipe(
        effects=(contract.EffectUse("brasas_capa", 1, start_s=0.0, end_s=2.0),),
        segments=(contract.SourceSegment("p.jpg", 0.0, 2.0, kind="photo"),),
    )
    plain = edit_sequence.from_recipe(recipe, {})
    assert plain.effects[0].opacity == 1.0
    strong = edit_sequence.from_recipe(
        recipe, {}, effect_opacity={"brasas_capa": vm.effect_opacity("brasas_capa")}
    )
    assert strong.effects[0].opacity == 0.5


def test_the_single_stretch_preview_layers_take_their_opacity() -> None:
    assert ep._effect_opacities() == {
        "/effects/vapor_capa/v1/preview.webm": "0.5",
        "/effects/humo_capa/v1/preview.webm": "0.6",
        "/effects/brasas_capa/v1/preview.webm": "0.5",
    }


def test_reduced_motion_keeps_the_loops_still() -> None:
    script = (_ASSETS / "edit-preview.js").read_text(encoding="utf-8")
    assert "(prefers-reduced-motion: reduce)" in script
    assert "stillFrame(" in script


# -- the rubro first, «Todos» with every effect (Deivid 2026-11-16) ----------------------------


def test_the_business_category_comes_from_its_rubro() -> None:
    assert vm.business_category(sector="", rubro="Shawarma y ensaladas") == "comida"
    assert vm.business_category(sector="", rubro="Heladería de yogur") == "comida"
    assert vm.business_category(sector="food_drink", rubro="") == "comida"
    assert vm.business_category(sector="real_estate", rubro="Inmobiliaria") == ""
    assert vm.business_category(sector="technology", rubro="Reparación de celulares") == ""


def test_the_business_effects_come_first_and_todos_shows_every_one() -> None:
    ids = ["humo_capa", "vapor_capa", "chispas"]
    categories = {"humo_capa": ("general",), "vapor_capa": ("comida",), "chispas": ("general",)}
    # a food business: its effects first, its category as the filter
    assert vm.default_filter(ids, categories, "comida") == "comida"
    assert vm.filter_effects(ids, categories, business="comida", chosen="comida") == ["vapor_capa"]
    assert vm.filter_effects(ids, categories, business="comida", chosen=vm.FILTER_ALL) == [
        "vapor_capa",
        "humo_capa",
        "chispas",
    ]
    assert vm.effect_filters(ids, categories, "comida") == [
        ("todos", "Todos"),
        ("comida", "Comida"),
        ("general", "Para todo"),
    ]
    # a technology business: no category of its own, «Todos», every effect usable
    assert vm.default_filter(ids, categories, "") == vm.FILTER_ALL
    assert vm.filter_effects(ids, categories, business="", chosen=vm.FILTER_ALL) == ids


def test_the_panel_lists_the_rubro_first_and_todos_lists_all(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = {"vapor_capa": ("comida",), "humo_capa": ("general",), "brasas_capa": ("comida",)}
    monkeypatch.setattr(vm, "effect_categories", lambda effect_id: fake.get(effect_id, ()))
    state = _three()
    state.clip_effect_category = "comida"
    assert state.clip_effect_filter_shown == "comida"
    assert [r["id"] for r in state.clip_tl_effect_choices] == ["vapor_capa", "brasas_capa"]
    assert [r["mine"] for r in state.clip_tl_effect_choices] == ["1", "1"]
    CreativeState.set_clip_effect_filter.fn(state, vm.FILTER_ALL)
    assert [r["id"] for r in state.clip_tl_effect_choices] == [
        "vapor_capa",
        "brasas_capa",
        "humo_capa",
    ]
    # smoke in a technology video: listed under «Todos», and it can be put
    state.clip_effect_category = ""
    state.clip_effect_filter = ""
    assert state.clip_effect_filter_shown == vm.FILTER_ALL
    assert len(state.clip_tl_effect_choices) == 3
    _put(state, "humo_capa", [_PHOTO])
    assert _spans(state) == [("humo_capa", 0.0, 2.0)]
    # an unknown filter is not taken
    CreativeState.set_clip_effect_filter.fn(state, "nada")
    assert state.clip_effect_filter_shown == vm.FILTER_ALL


async def test_the_rubro_is_read_once_from_the_brand_kit(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[UUID, UUID]] = []

    async def tenant(self: CreativeState) -> UUID:
        return _TENANT

    def kind(tenant_id: UUID, brand_id: UUID) -> tuple[str, str]:
        calls.append((tenant_id, brand_id))
        return "", "Shawarma y ensaladas"

    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", tenant)
    monkeypatch.setattr(module, "default_brand_id", lambda tenant_id: _BRAND)
    monkeypatch.setattr(module, "business_kind", kind)
    state = _three()
    await CreativeState.load_clip_effect_rubro.fn(state)
    await CreativeState.load_clip_effect_rubro.fn(state)
    assert state.clip_effect_category == "comida"
    assert calls == [(_TENANT, _BRAND)]


async def test_a_rubro_that_cannot_be_read_leaves_every_effect(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def tenant(self: CreativeState) -> UUID:
        return _TENANT

    def broken(tenant_id: UUID, brand_id: UUID) -> tuple[str, str]:
        raise RuntimeError("db down")

    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", tenant)
    monkeypatch.setattr(module, "default_brand_id", lambda tenant_id: _BRAND)
    monkeypatch.setattr(module, "business_kind", broken)
    state = _three()
    await CreativeState.load_clip_effect_rubro.fn(state)
    assert state.clip_effect_category == "" and state.clip_effect_category_read
    assert len(state.clip_tl_effect_choices) == 3


# -- several effects on one row, and from row to row (Deivid 2026-11-20) ---------------------


def test_several_effects_one_after_another_on_the_same_row(editor_on: None) -> None:
    """«poder poner varios efectos sobre una misma pista»: Humo on parts 1-2 and Vapor
    on part 3 do not overlap, so both go on the first row."""
    state = _three()
    _put(state, "humo_capa", [_PHOTO, _KEY])
    _put(state, "vapor_capa", [_SECOND])
    assert [int(u["lane"]) for u in state.clip_effect_uses] == [0, 0]  # type: ignore[call-overload]
    assert state._clip_lane_count() == 1
    assert [[r["label"] for r in lane] for lane in state.clip_tl_effect_lanes] == [
        ["Humo", "Vapor"]
    ]


def test_an_effect_dragged_onto_a_row_with_room_moves_there(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 5, 0), _use("u2", "humo_capa", 6, 9, 1)]
    CreativeState.drop_clip_block.fn(state, "efecto-u2", "time@0", 6.0)
    assert [int(u["lane"]) for u in state.clip_effect_uses] == [0, 0]  # type: ignore[call-overload]
    assert _spans(state)[1] == ("humo_capa", 6.0, 9.0)
    assert state.clip_edit_notice == "Pasaste Humo a Efectos."  # the only row now


def test_an_effect_dragged_onto_a_busy_row_comes_back(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 5, 0), _use("u2", "humo_capa", 2, 4, 1)]
    CreativeState.drop_clip_block.fn(state, "efecto-u2", "time@0", 2.0)
    assert [int(u["lane"]) for u in state.clip_effect_uses] == [0, 1]  # type: ignore[call-overload]
    assert (
        state.clip_effect_error
        == state.clip_edit_notice
        == (
            "En Efectos 1 no queda espacio libre en ese momento. Llévalo a otra pista o a "
            "un hueco libre."
        )
    )


def test_an_effect_moves_in_time_and_row_in_one_drag(editor_on: None) -> None:
    state = _three()
    _put(state, "vapor_capa", [_PHOTO])  # row 1, 0:00–0:02, stuck to the photo
    state.clip_effect_uses = [*state.clip_effect_uses, _use("u9", "humo_capa", 2, 4, 1)]
    CreativeState.drop_clip_block.fn(state, "efecto-u9", "time@0", 6.0)
    (vapor, humo) = state.clip_effect_uses
    assert (int(humo["lane"]), humo["start"], humo["end"], humo["blocks"]) == (0, 6.0, 8.0, [])  # type: ignore[call-overload]
    assert vapor["blocks"] == [_PHOTO]


def test_up_and_down_keys_move_an_effect_a_row(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 5, 0), _use("u2", "humo_capa", 6, 9, 1)]
    CreativeState.clip_block_key.fn(state, "efecto-u2", "", "ArrowUp")
    assert int(state.clip_effect_uses[1]["lane"]) == 0  # type: ignore[call-overload]
    CreativeState.clip_block_key.fn(state, "efecto-u2", "", "ArrowUp")  # no row above
    assert int(state.clip_effect_uses[1]["lane"]) == 0  # type: ignore[call-overload]
    CreativeState.clip_block_key.fn(state, "efecto-u2", "", "ArrowDown")
    assert int(state.clip_effect_uses[1]["lane"]) == 1  # type: ignore[call-overload]


def test_an_effect_that_follows_its_block_onto_another_changes_row(editor_on: None) -> None:
    """The video moved: the effect stuck to it follows it in time and keeps its row —
    unless it would then overlap another effect there: then IT (the one that moved)
    goes to the first row where it fits."""
    state = _three()
    _put(state, "vapor_capa", [_SECOND])  # row 1, 0:17–0:25
    state.clip_effect_uses = [*state.clip_effect_uses, _use("u9", "humo_capa", 0, 2, 0)]
    CreativeState.drop_clip_block.fn(state, _SECOND, "move", 0)  # now 0:00–0:08
    vapor, humo = state.clip_effect_uses
    assert (vapor["start"], vapor["end"], int(vapor["lane"])) == (0.0, 8.0, 1)  # type: ignore[call-overload]
    assert int(humo["lane"]) == 0  # type: ignore[call-overload]
    assert state._clip_lane_count() == 2
    # and moving it back where it fits, it keeps its new row (no surprise jumps)
    CreativeState.drop_clip_block.fn(state, _SECOND, "move", 2)
    assert int(state.clip_effect_uses[0]["lane"]) == 1  # type: ignore[call-overload]


def test_settle_lanes_moves_only_what_moved() -> None:
    uses = [
        {"uid": "a", "effect_id": "humo_capa", "start": 0, "end": 4, "lane": 0, "blocks": []},
        {"uid": "b", "effect_id": "vapor_capa", "start": 2, "end": 6, "lane": 0, "blocks": ["x"]},
        {"uid": "c", "effect_id": "brasas_capa", "start": 6, "end": 8, "lane": 0, "blocks": ["y"]},
    ]
    settled, lanes = vm.settle_lanes(uses, lanes=1)
    assert [(u["uid"], u["lane"]) for u in settled] == [("a", 0), ("b", 1), ("c", 0)]
    assert lanes == 2


# -- round 3 (Deivid 2026-11-20): no «+ Pista», never one effect over another on a row -------


def test_free_room_of_a_row() -> None:
    assert vm.free_gaps([(0, 4), (6, 9)], 12) == [(4.0, 6.0), (9.0, 12.0)]
    assert vm.free_gaps([], 5) == [(0.0, 5.0)]
    # the room it overlaps most, trimmed to it; under 1 s of room: None (it goes back)
    assert vm.fit_in_gap((2, 6), [(0, 4)], 25) == (4.0, 6.0)
    assert vm.fit_in_gap((3, 6), [(0, 4), (4.5, 10)], 25) is None
    assert vm.fit_in_gap((12, 15), [(0, 4)], 25) == (12.0, 15.0)


def test_rows_come_and_go_on_their_own() -> None:
    uses = [{"uid": "a", "lane": 0}, {"uid": "b", "lane": 3}, {"uid": "c", "lane": 3}]
    assert [u["lane"] for u in vm.compact_lanes(uses)] == [0, 1, 1]


def test_dropping_on_a_busy_spot_trims_to_the_free_room(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "humo_capa", 0, 4, 0), _use("u2", "vapor_capa", 6, 10, 0)]
    CreativeState.drop_clip_block.fn(state, "efecto-u2", "time", 2.0)
    assert _spans(state) == [("humo_capa", 0.0, 4.0), ("vapor_capa", 4.0, 6.0)]
    assert state.clip_edit_notice == ("Cambiaste cuándo sale Vapor. Lo acortamos al espacio libre.")


def test_too_little_room_puts_the_effect_back_and_says_why(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [
        _use("u1", "humo_capa", 0, 4, 0),
        _use("u2", "brasas_capa", 4.5, 10, 0),
        _use("u3", "vapor_capa", 12, 15, 0),
    ]
    CreativeState.drop_clip_block.fn(state, "efecto-u3", "time", 3.0)
    assert _spans(state)[2] == ("vapor_capa", 12.0, 15.0)
    assert state.clip_effect_error == state.clip_edit_notice == vm.EFFECT_NO_ROOM_LINE


def test_a_handle_stops_at_the_neighbour_on_its_row(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "humo_capa", 0, 4, 0), _use("u2", "vapor_capa", 6, 9, 0)]
    CreativeState.drop_clip_block.fn(state, "efecto-u2", "start", 2.0)
    assert _spans(state)[1] == ("vapor_capa", 4.0, 9.0)
    CreativeState.drop_clip_block.fn(state, "efecto-u1", "end", 7.0)
    assert _spans(state)[0] == ("humo_capa", 0.0, 4.0)


def test_up_onto_a_busy_row_trims_to_its_free_room(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 5, 0), _use("u2", "humo_capa", 3, 8, 1)]
    CreativeState.clip_block_key.fn(state, "efecto-u2", "", "ArrowUp")
    assert [int(u["lane"]) for u in state.clip_effect_uses] == [0, 0]  # type: ignore[call-overload]
    assert _spans(state)[1] == ("humo_capa", 5.0, 8.0)
    assert state.clip_edit_notice == "Subiste Humo una pista. Lo acortamos al espacio libre."
    assert state._clip_lane_count() == 1  # the row it left disappeared


def test_dragged_onto_a_busy_row_it_takes_the_free_room(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 5, 0), _use("u2", "humo_capa", 3, 7, 1)]
    CreativeState.drop_clip_block.fn(state, "efecto-u2", "time@0", 3.0)
    assert _spans(state)[1] == ("humo_capa", 5.0, 7.0)
    assert int(state.clip_effect_uses[1]["lane"]) == 0  # type: ignore[call-overload]


def test_dragged_under_the_last_row_it_opens_a_new_one(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 5, 0), _use("u2", "humo_capa", 6, 9, 0)]
    assert state._clip_lane_count() == 1
    CreativeState.drop_clip_block.fn(state, "efecto-u2", "time@1", 6.0)
    assert [int(u["lane"]) for u in state.clip_effect_uses] == [0, 1]  # type: ignore[call-overload]
    assert [n["name"] for n in state.clip_tl_effect_lane_names] == ["Efectos 1", "Efectos 2"]
    # back up: the empty row goes and the rows are one again
    CreativeState.clip_block_key.fn(state, "efecto-u2", "", "ArrowUp")
    assert state._clip_lane_count() == 1
    # the only effect of the last row: «down» would be its own row again
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 5, 0)]
    CreativeState.clip_block_key.fn(state, "efecto-u1", "", "ArrowDown")
    assert state._clip_lane_count() == 1


def test_no_plus_pista_and_no_effect_choice_in_the_panel() -> None:
    view = (Path(__file__).resolve().parent / "clip_editor_view.py").read_text(encoding="utf-8")
    assert "add_clip_effect_lane" not in view and "remove_clip_effect_lane" not in view
    assert "swap_clip_effect" not in view
    # round 5 (Deivid 2026-11-20): no row buttons either — dragged, or ↑/↓ on the block
    assert "set_clip_effect_lane" not in view and "Mover a la pista" not in view
    # round 6: no «¿En qué partes va?» on a chosen effect, no «¿En qué pista va?»
    assert "_effect_panel" not in view and "_target_lane" not in view
    for gone in (
        "add_clip_effect_lane",
        "remove_clip_effect_lane",
        "swap_clip_effect",
        "set_clip_effect_lane",
        "set_clip_effect_target_lane",
        "clip_effect_target_lane",
    ):
        assert not hasattr(CreativeState, gone)


# -- round 6 (Deivid 2026-11-20) --------------------------------------------------------------


def test_a_new_effect_takes_the_first_row_where_it_fits(editor_on: None) -> None:
    """No «¿En qué pista va?»: the first row where it fits, else a new one — even when an
    effect of another row was chosen before «+ Efecto»."""
    state = _three()
    _put(state, "vapor_capa", [_PHOTO, _KEY, _SECOND])  # row 1, the whole video
    _put(state, "brasas_capa", [_KEY])  # row 1 is busy then: row 2, and chosen
    _put(state, "humo_capa", [_SECOND])  # fits row 2 (after Brasas): not a third row
    assert [int(u["lane"]) for u in state.clip_effect_uses] == [0, 1, 1]  # type: ignore[call-overload]
    assert state.clip_edit_notice == "Pusiste Humo."


def test_a_chosen_effects_panel_does_not_ask_for_its_parts(editor_on: None) -> None:
    """Choosing an effect shows its title, Empieza/Termina and «Listo»: the boxes of
    «¿En qué partes va?» are only «+ Efecto»'s; the effect stays stuck to its blocks."""
    state = _three()
    _put(state, "vapor_capa", [_KEY])
    assert state.clip_edit_block == "efecto-u1"
    assert [r["on"] for r in state.clip_effect_part_rows] == ["", "", ""]
    CreativeState.toggle_clip_effect_part.fn(state, _SECOND)  # not «+ Efecto»: nothing
    assert state.clip_effect_uses[0]["blocks"] == [_KEY]
    CreativeState.drop_clip_block.fn(state, _KEY, "move", 0)
    assert _spans(state) == [("vapor_capa", 0.0, 15.0)]  # still stuck: it follows


# -- the reviews of ED-04 (2026-11-20) --------------------------------------------------------


def _two_at_the_end(state: CreativeState) -> None:
    """Two effects with their own seconds on row 1, side by side at the video's end
    (0:21–0:22,5 and 0:22,5–0:23,5 of the 25 s video)."""
    state.clip_effect_uses = [
        _use("u1", "humo_capa", 21.0, 22.5, 0),
        _use("u2", "vapor_capa", 22.5, 23.5, 0),
    ]


def _no_row_overlaps(state: CreativeState) -> None:
    uses = state._clip_effect_resolved()
    for a in uses:
        for b in uses:
            if a["uid"] < b["uid"] and a["lane"] == b["lane"]:
                assert a["end"] <= b["start"] + 1e-6 or b["end"] <= a["start"] + 1e-6, uses


def test_a_trim_never_leaves_two_effects_on_a_row(editor_on: None) -> None:
    state = _three()
    _two_at_the_end(state)
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 8.0)  # 15 s → 8 s: video of 18 s
    _no_row_overlaps(state)
    assert all(float(u["end"]) <= 18.0 for u in state._clip_effect_resolved())  # type: ignore[arg-type]


def test_taking_a_block_out_never_leaves_two_effects_on_a_row(editor_on: None) -> None:
    state = _three()
    _two_at_the_end(state)
    CreativeState.select_clip_block.fn(state, _PHOTO)
    CreativeState.clip_block_action.fn(state, vm.REMOVE)  # 25 s → 23 s
    _no_row_overlaps(state)
    assert all(float(u["end"]) <= 23.0 for u in state._clip_effect_resolved())  # type: ignore[arg-type]


def test_a_speed_up_never_leaves_two_effects_on_a_row(editor_on: None) -> None:
    state = _three()
    _two_at_the_end(state)
    CreativeState.set_clip_block_speed.fn(state, _KEY, "2")  # the own video sped up
    _no_row_overlaps(state)
    total = vm.media_total(state._clip_tl_media())
    assert all(float(u["end"]) <= total + 1e-6 for u in state._clip_effect_resolved())  # type: ignore[arg-type]


def test_settle_lanes_moves_a_squeezed_effect_with_its_own_seconds() -> None:
    uses = [
        {"uid": "a", "effect_id": "humo_capa", "start": 7, "end": 8.5, "lane": 0, "blocks": []},
        {"uid": "b", "effect_id": "vapor_capa", "start": 8.5, "end": 9.5, "lane": 0, "blocks": []},
    ]
    settled, lanes = vm.settle_lanes(uses, lanes=1, total=9.0)
    # «b» squeezed to 8–9 would overlap «a» and only ½ s is free on its row: row 2
    assert [(u["uid"], u["lane"], u["start"], u["end"]) for u in settled] == [
        ("a", 0, 7, 8.5),
        ("b", 1, 8.0, 9.0),
    ]
    assert lanes == 2


def test_an_old_session_s_layers_become_uses_once(editor_on: None) -> None:
    """Before ED-04 a layer was an id in `clip_effect_ids`: it is moved to a use (its
    seconds kept), never on the video twice; «Cámara rápida» stays a flag."""
    state = _three()
    state.clip_effect_ids = ["vapor_capa", "humo_capa", "camara_rapida"]
    state.clip_effect_times = {"humo_capa": [3.0, 6.0]}
    state._clip_migrate_layers()
    assert state.clip_effect_ids == ["camara_rapida"] and state.clip_effect_times == {}
    total = vm.media_total(state._clip_tl_media())  # «Cámara rápida» sped the video up
    assert _spans(state) == [("vapor_capa", 0.0, round(total, 2)), ("humo_capa", 3.0, 6.0)]
    state._clip_migrate_layers()  # again: nothing more
    assert len(state.clip_effect_uses) == 2
    assert [u.effect_id for u in state._clip_edit_recipe().effects] == ["vapor_capa", "humo_capa"]


def test_a_layer_is_no_flag_any_more(editor_on: None) -> None:
    state = _three()
    CreativeState.toggle_clip_effect.fn(state, "vapor_capa")
    assert state.clip_effect_ids == [] and state.clip_effect_uses == []


def test_once_is_one_time_and_over_the_most_both_numbers() -> None:
    assert vm.effect_repeat_full_line("Fuego", 1) == (
        "Ya pusiste Fuego 1 vez. Quítalo de una parte para ponerlo en otra."
    )
    uses = tuple(
        contract.EffectUse("vapor_capa", 1, start_s=n * 2.0, end_s=n * 2.0 + 1) for n in range(4)
    )
    assert vm.effects_problem(uses) == "Pusiste Vapor 4 veces y solo caben 3. Quítalo de una parte."


def test_the_lane_hint_shows_until_the_first_row_change(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 5, 0), _use("u2", "humo_capa", 6, 9, 1)]
    CreativeState.select_clip_block.fn(state, "efecto-u2")
    assert state.clip_trim_hint == "Arrástralo arriba o abajo para pasarlo a otra pista."
    CreativeState.clip_block_key.fn(state, "efecto-u2", "", "ArrowUp")
    assert state.clip_edit_notice == "Subiste Humo una pista."
    assert state.clip_trim_hint == ""


def test_up_and_down_at_the_ends_say_so(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 5, 0)]
    CreativeState.clip_block_key.fn(state, "efecto-u1", "", "ArrowUp")
    assert state.clip_edit_notice == "Vapor ya está en la primera pista."
    CreativeState.clip_block_key.fn(state, "efecto-u1", "", "ArrowDown")
    assert state.clip_edit_notice == "Vapor ya está solo en la última pista."
    # with another one on its row, ↓ opens a new row
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 5, 0), _use("u2", "humo_capa", 6, 9, 0)]
    CreativeState.clip_block_key.fn(state, "efecto-u2", "", "ArrowDown")
    assert state.clip_edit_notice == "Bajaste Humo una pista."
    assert state._clip_lane_count() == 2


def test_a_drag_to_another_row_names_it_as_shown(editor_on: None) -> None:
    state = _three()
    state.clip_effect_uses = [_use("u1", "vapor_capa", 0, 5, 0), _use("u2", "humo_capa", 6, 9, 0)]
    CreativeState.drop_clip_block.fn(state, "efecto-u2", "time@1", 6.0)
    assert state.clip_edit_notice == "Pasaste Humo a Efectos 2."


def test_the_texts_of_the_review() -> None:
    from .ui import timeline_vm as tl

    assert tl.EFFECT_HELP == (
        "Usa las flechas izquierda y derecha para cambiar cuándo sale, y arriba y abajo para "
        "pasarlo a otra pista."
    )
    assert vm.EFFECT_NO_ROOM_LINE == (
        "Ahí ya hay otro efecto y no queda espacio libre. Llévalo a un hueco libre de la pista."
    )
    assert vm.put_label("Vapor") == "Poner Vapor, gratis"
    assert vm.put_label("Vapor", mine=True) == "Poner Vapor, gratis, de tu rubro"


def test_no_second_tag_and_no_filter_with_one_category(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _three()
    # the library today: the three layers are «Comida» only — nothing to filter by
    assert not state.clip_effect_filter_offered
    state.clip_effect_category = "comida"
    # «De tu rubro» says it: no «Comida» tag beside it
    assert {r["category"] for r in state.clip_tl_effect_choices} == {""}
    assert state.clip_tl_effect_choices[0]["put_label"] == "Poner Vapor, gratis, de tu rubro"
    fake = {"vapor_capa": ("comida",), "humo_capa": ("general",), "brasas_capa": ("comida",)}
    monkeypatch.setattr(vm, "effect_categories", lambda effect_id: fake.get(effect_id, ()))
    other = _three()
    assert other.clip_effect_filter_offered
    CreativeState.set_clip_effect_filter.fn(other, "general")
    # under the «Para todo» filter, Humo's own tag would say it again: none
    assert [(r["id"], r["category"]) for r in other.clip_tl_effect_choices] == [("humo_capa", "")]
    CreativeState.set_clip_effect_filter.fn(other, vm.FILTER_ALL)
    assert {r["category"] for r in other.clip_tl_effect_choices} == {"Comida", "Para todo"}


def test_a_new_drag_keeps_its_own_blocks_when_an_old_one_cleans_up() -> None:
    drag = (Path(__file__).resolve().parent.parent / "assets" / "timeline-drag.js").read_text(
        encoding="utf-8"
    )
    strays = drag[drag.index("function strays(d)") : drag.index("function clearTransforms")]
    assert "var active = drag && drag !== d ? drag : null;" in strays
    assert 'if (!active) d.root.removeAttribute("data-tl-new-lane");' in strays
    preview = (Path(__file__).resolve().parent.parent / "assets" / "edit-preview.js").read_text(
        encoding="utf-8"
    )
    still = preview[
        preview.index("function stillFrame(el)") : preview.index("function seqPaint(host)")
    ]
    assert "el.currentSrc" in still and "el.__qStill === src" in still


def test_a_new_effect_scrolls_the_tracks_sideways_to_its_block(editor_on: None) -> None:
    """m-25114465: the block is chosen (`__qTimeline.reveal` moves up or down to its
    panel) and the tracks scroll sideways to it (`__qTimelineRevealNew`)."""
    state = _three()
    CreativeState.open_clip_flow.fn(state, vm.FLOW_EFFECT)
    events = CreativeState.add_clip_effect.fn(state, "humo_capa")
    block = state.clip_edit_block
    assert block.startswith(vm.EFFECT_ID_PREFIX)
    scripts = str(events)
    assert f'__qTimelineRevealNew("{block}")' in scripts
    assert f'__qTimeline?.reveal("{block}")' in scripts
