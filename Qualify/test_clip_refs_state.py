"""m-25142725: the reference tracks of the Clip's timeline — the state.

`CreativeState` standalone, handlers through `.fn`; the server's contract
(`references_for_parts`, `validate_brief_recipe`) is the judge. Offline: nothing is
created, read from a vendor or paid."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.video_pipeline import ai_parts as contract_ai
from qualify_api.creative.video_pipeline import validate_brief_recipe
from qualify_api.creative.video_pipeline.ai_parts import references_for_parts

from . import ai_block_vm as ai_vm
from . import clip_editor_vm
from . import clip_refs_vm as vm
from .creative_provider import build_brief
from .creative_state import CreativeState
from .ui import timeline_vm

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND = UUID("c0000000-0000-4000-8000-000000000003")
_ONE = f"uploads/{_TENANT}/clip/uno.jpg"
_TWO = f"uploads/{_TENANT}/clip/dos.jpg"
_REF = f"uploads/{_TENANT}/ref/arepa.png"
_REF_VIDEO = f"uploads/{_TENANT}/ref/baile.mp4"
_PRODUCT = "b0000000-0000-4000-8000-000000000002"


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)


@pytest.fixture
def ai_on(monkeypatch: pytest.MonkeyPatch, editor_on: None) -> None:
    monkeypatch.setenv(contract_ai.CLIP_AI_PARTS_SWITCH, "on")


@pytest.fixture
def ai_off(monkeypatch: pytest.MonkeyPatch, editor_on: None) -> None:
    monkeypatch.delenv(contract_ai.CLIP_AI_PARTS_SWITCH, raising=False)


def _state() -> CreativeState:
    """Two photos of 2 s each: blocks at 0-2 and 2-4 s."""
    state = CreativeState()
    state.choose_category("clip")
    state.brief_topic = "Promoción de 2×1 los martes"
    state.clip_images = [
        {"key": _ONE, "name": "uno.jpg", "source": "upload", "role": "product"},
        {"key": _TWO, "name": "dos.jpg", "source": "upload", "role": "product"},
    ]
    state.clip_sequence = [_ONE, _TWO]
    state._clip_session_tenant = str(_TENANT)
    return state


def _add_part(state: CreativeState, at_s: float) -> str:
    state.clip_edit_playhead = at_s
    CreativeState.open_clip_flow.fn(state, ai_vm.ADD_KEY)
    block = state.clip_edit_block
    CreativeState.set_clip_ai_description.fn(state, block, "Una mano acerca el vaso")
    return block


def _with_part() -> tuple[CreativeState, str]:
    """Photo 0-2, «Parte con IA 1» 2-7, photo 7-9."""
    state = _state()
    return state, _add_part(state, 0.5)


def _add_ref(state: CreativeState, key: str = _REF, kind: str = "photo") -> str:
    state.clip_ref_kind = kind
    state._clip_ref_put(kind, [key])
    return state.clip_edit_block


def _ref_rows(state: CreativeState) -> list[dict[str, str]]:
    return [r for r in state._clip_tl_rows() if vm.is_ref(r["id"])]


# -- the switch ----------------------------------------------------------------------------


@pytest.mark.usefixtures("ai_off")
def test_switch_off_nothing_changes() -> None:
    state = _state()
    rows = state._clip_tl_rows()
    media = state._clip_edit_media()
    state.clip_refs = [vm.new_item([], "photo", [_REF], 0, 4)]  # left in the state
    assert state._clip_tl_rows() == rows
    assert state._clip_edit_media() == media
    assert "clip_references" not in media and "references_version" not in media
    assert not state.clip_ref_shown and state.clip_ref_lanes == []
    assert state.clip_ref_columns == [] and state.clip_ref_cards == []
    assert CreativeState.open_clip_flow.fn(state, clip_editor_vm.FLOW_REF) == []
    assert state.clip_edit_block == ""
    assert clip_editor_vm.REF_TAB not in clip_editor_vm.FLOW_TABS
    # choosing a product adds nothing to the tracks
    state.clip_refs = []
    state.catalog_items = [{"id": _PRODUCT, "name": "Arepa", "photo_key": _REF}]
    state.choose_product(_PRODUCT)
    assert state.clip_refs == []


@pytest.mark.usefixtures("ai_on")
def test_without_ai_parts_the_group_is_not_drawn_and_its_references_are_kept() -> None:
    state = _state()
    state.clip_refs = [vm.new_item([], "photo", [_REF], 0, 2)]
    assert not state.clip_ref_shown
    assert _ref_rows(state) == []
    assert "clip_references" not in state._clip_edit_media()
    _add_part(state, 0.5)
    assert state.clip_ref_shown and len(_ref_rows(state)) == 1


# -- add, move, trim, remove --------------------------------------------------------------


@pytest.mark.usefixtures("ai_on")
def test_a_new_reference_goes_under_the_part_at_the_playhead_with_its_length() -> None:
    state, part = _with_part()
    state.clip_edit_playhead = 3.0
    CreativeState.open_clip_flow.fn(state, clip_editor_vm.FLOW_REF)
    assert state.clip_tl_flow == clip_editor_vm.FLOW_REF
    assert state.clip_ref_where == vm.WHERE_LINE.format(n=1)
    block = _add_ref(state)
    (item,) = state.clip_refs
    assert (item["start"], item["end"], item["row"]) == (2.0, 7.0, 0)
    assert state.clip_edit_block == block and state.clip_tl_flow == ""
    assert state.clip_edit_notice == "Agregaste una foto de referencia a la parte con IA 1."
    assert state.clip_ref_chosen["used"] == "Se usa en la parte con IA 1."
    assert state.clip_tl_chosen["kind"] == "refphoto"
    # the AI part's panel shortcut aims at that part
    state.clip_edit_block = part
    CreativeState.open_clip_ref_for_part.fn(state)
    assert state._clip_ref_target == part and state.clip_tl_flow == clip_editor_vm.FLOW_REF


@pytest.mark.usefixtures("ai_on")
def test_it_moves_and_trims_by_dragging_and_is_removed_from_the_bar() -> None:
    state, _part = _with_part()
    block = _add_ref(state)
    CreativeState.drop_clip_block.fn(state, block, "time", 0.0)
    assert (state.clip_refs[0]["start"], state.clip_refs[0]["end"]) == (0.0, 5.0)
    assert state.clip_edit_notice == "Ahora la foto de referencia 1 se usa en la parte con IA 1."
    CreativeState.drop_clip_block.fn(state, block, "end", 2.1)  # sticks to the part's edge
    assert (state.clip_refs[0]["start"], state.clip_refs[0]["end"]) == (0.0, 2.0)
    assert state.clip_ref_chosen["off"] == "1"  # 0-2 s: under no AI part
    assert state.clip_ref_chosen["used"].startswith(
        contract_ai.reference_text("reference_unused") or "?"
    )
    CreativeState.drop_clip_block.fn(state, block, "end", 4.0)
    assert state.clip_refs[0]["end"] == 4.0
    CreativeState.clip_block_key.fn(state, block, "", "ArrowRight")
    assert (state.clip_refs[0]["start"], state.clip_refs[0]["end"]) == (0.5, 4.5)
    CreativeState.clip_block_key.fn(state, block, "start", "ArrowRight")
    assert state.clip_refs[0]["start"] == 1.0
    state.clip_edit_block = block
    CreativeState.clip_block_action.fn(state, clip_editor_vm.REMOVE)
    assert state.clip_refs == []
    assert state.clip_edit_notice == "Quitaste la foto de referencia 1."


@pytest.mark.usefixtures("ai_on")
def test_overlapping_references_stack_in_rows() -> None:
    state, _part = _with_part()
    _add_ref(state)
    second = _add_ref(state, f"uploads/{_TENANT}/ref/b.png")
    assert [i["row"] for i in state.clip_refs] == [0, 1]
    names = state.clip_ref_lane_names
    assert [n["name"] for n in names] == ["Fotos de referencia 1", "Fotos de referencia 2"]
    assert state.clip_ref_folded == "Sin videos ni audios de referencia"
    # dropped up on row 0 over the other: it stays on a row of its own
    CreativeState.drop_clip_block.fn(state, second, "time@0", 2.0)
    assert sorted(i["row"] for i in state.clip_refs) == [0, 1]
    # shorter and moved away, it goes up to the first row and the second row goes
    CreativeState.drop_clip_block.fn(state, second, "end", 4.0)
    CreativeState.drop_clip_block.fn(state, second, "time@0", 7.0)
    assert [i["row"] for i in state.clip_refs] == [0, 0]
    assert [n["name"] for n in state.clip_ref_lane_names] == ["Fotos de referencia"]


@pytest.mark.usefixtures("ai_on")
def test_the_products_photos_go_as_one_block_along_the_whole_video() -> None:
    state, _part = _with_part()
    photos = [f"uploads/{_TENANT}/catalog/a.jpg", f"uploads/{_TENANT}/catalog/b.jpg"]
    state.catalog_items = [
        {
            "id": _PRODUCT,
            "name": "Combo Vecino",
            "photo_key": photos[0],
            "photo_keys": "\n".join(photos),
            "video_keys": "",
        }
    ]
    state.choose_product(_PRODUCT)
    (item,) = [i for i in state.clip_refs if i.get("origin") == "product"]
    assert item["keys"] == photos and item["whole"] == "1"
    assert state.clip_edit_notice == (
        "Pusimos las fotos de Combo Vecino en «Fotos de referencia», en todo tu video."
    )
    total = state._clip_refs_total()
    (row,) = [r for r in _ref_rows(state) if r["kind"] == "refphoto"]
    assert (float(row["start"]), float(row["length"])) == (0.0, total)
    assert row["label"] == "Combo Vecino · 2 fotos" and row["ref_tag"] == vm.PRODUCT_TAG
    # each photo is one reference of the brief, with its product
    refs = state._clip_edit_media()["clip_references"]
    assert [(r["key"], r["origin"], r["product_id"]) for r in refs] == [  # type: ignore[union-attr]
        (photos[0], "product", _PRODUCT),
        (photos[1], "product", _PRODUCT),
    ]
    # its panel removes them one by one
    state.clip_edit_block = row["id"]
    assert [p["key"] for p in state.clip_ref_chosen_photos] == photos
    assert [p["remove"] for p in state.clip_ref_chosen_photos] == [
        "Quitar la foto 1 de Combo Vecino",
        "Quitar la foto 2 de Combo Vecino",
    ]
    assert row["name"].startswith("Combo Vecino, 2 fotos de tu producto, de 0:00 a")
    CreativeState.remove_clip_ref_photo.fn(state, photos[0])
    assert state.clip_refs[0]["keys"] == [photos[1]]
    assert state.clip_edit_notice == "Quitaste una foto de Combo Vecino."
    CreativeState.remove_clip_ref_photo.fn(state, photos[1])
    assert state.clip_edit_notice == "Quitaste la última foto de Combo Vecino."
    assert not any(i.get("origin") == "product" for i in state.clip_refs)
    state.choose_product(_PRODUCT)  # chosen again: its block is back
    # another product replaces the block; letting it go takes it away
    state.clear_product()
    assert not any(i.get("origin") == "product" for i in state.clip_refs)


# -- which part takes what, the cap and «Siguiente» -----------------------------------------


@pytest.mark.usefixtures("ai_on")
def test_a_reference_applies_by_overlap_and_the_contract_agrees() -> None:
    state, _part = _with_part()
    block = _add_ref(state)
    CreativeState.drop_clip_block.fn(state, block, "time", 0.0)
    CreativeState.drop_clip_block.fn(state, block, "end", 2.0)
    assert not state._clip_refs_plan()["used_by"]
    # 0,5 s over the part: it applies (contract: more than 0,05 s)
    CreativeState.drop_clip_block.fn(state, block, "end", 2.5)
    plan = state._clip_refs_plan()
    assert plan["used_by"] == {state.clip_refs[0]["uid"]: [1]}
    brief = build_brief(_BRAND, **state._generator_form())  # type: ignore[arg-type]
    (part,) = references_for_parts(brief)
    assert [r.key for r in part.photos] == [_REF]


@pytest.mark.usefixtures("ai_on")
def test_over_the_models_cap_the_part_warns_and_siguiente_is_off() -> None:
    state, part = _with_part()
    cap = contract_ai.reference_caps()["photo"]
    keys = [f"uploads/{_TENANT}/ref/p{n}.png" for n in range(cap + 1)]
    # the tab refuses the one over the cap…
    for key in keys:
        _add_ref(state, key)
    assert len(state.clip_refs) == cap
    assert state.clip_edit_notice == vm.cap_full("photo", 1, cap)
    # …a drag may still put it there: the part warns everywhere and «Siguiente» waits
    extra = vm.new_item(state.clip_refs, "photo", [keys[-1]], 0.0, 4.0)
    state.clip_refs = [*state.clip_refs, extra]
    card = vm.cap_card("photo", 1, cap + 1, cap)
    assert card == (
        f"La parte con IA 1 tiene {cap + 1} fotos de referencia y la IA usa hasta {cap}. "
        "Quita una o muévela a otra parte para seguir."
    )
    assert state.clip_ref_cards == [card]
    (column,) = state.clip_ref_columns
    assert column["tone"] == "warn" and column["cap"] == f"⚠ {cap + 1} fotos · máx. {cap}"
    assert state.clip_editor_on_screen
    assert state._clip_ai_missing() == card
    step = state.gen_step
    assert CreativeState.next_view.fn(state) is None and state.gen_step == step
    assert CreativeState.go_to_view.fn(state, str(step + 1)) is None
    assert state.gen_step == step
    assert state._clip_edit_problem()[0] != card  # said once, by its card
    state.clip_edit_block = part
    assert state.clip_ai_chosen["refs_problem"] == contract_ai.reference_text(
        "too_many_references", kind="photo"
    )
    assert any(r["warn"] == "1" for r in _ref_rows(state))
    assert any(
        r["name"].endswith("Esta parte tiene más fotos de las que usa la IA.")
        for r in _ref_rows(state)
    )


@pytest.mark.usefixtures("ai_on")
def test_a_video_under_a_part_that_is_not_nueva_is_ignored_with_its_notice() -> None:
    state, part = _with_part()
    state.clip_ref_kind = "video"
    _add_ref(state, _REF_VIDEO, "video")
    state._clip_ai_put(part, {**state.clip_ai_parts[0]["plan"], "mode": "extend"})
    plan = state._clip_refs_plan()
    uid = state.clip_refs[0]["uid"]
    assert plan["ignored"] == {uid: [1]} and uid not in plan["used_by"]
    state.clip_edit_block = part
    (box,) = state.clip_ai_refs
    assert box["ignored"] == "1"
    assert box["note"] == contract_ai.reference_text("reference_mode_ignored")
    (row,) = _ref_rows(state)
    assert row["ref_tag"] == vm.IGNORED_TAG
    assert state._clip_ai_missing() == ""  # a notice never blocks


# -- the copies ----------------------------------------------------------------------------


@pytest.mark.usefixtures("ai_on")
def test_use_also_in_the_video_puts_a_block_at_the_nearest_join() -> None:
    state, _part = _with_part()
    block = _add_ref(state)
    CreativeState.drop_clip_block.fn(state, block, "start", 6.5)  # 6,5-7,5 s
    state.clip_edit_block = block
    CreativeState.copy_clip_ref_to_video.fn(state)
    media = state._clip_tl_media()
    assert [m["kind"] for m in media] == ["photo", "ai", "photo", "photo"]
    assert media[2]["key"] == _REF  # at the 7 s join: what came after moves on
    assert state.clip_edit_notice.startswith(
        "Copiamos la foto de referencia 1 a «Fotos y videos», a las 0:07, como «Foto 3»."
    )
    # the reference stays: the two are copies apart
    assert state.clip_refs[0]["keys"] == [_REF]
    CreativeState.copy_clip_ref_to_video.fn(state)
    assert state.clip_edit_notice == "Esta foto ya está en tu video."


@pytest.mark.usefixtures("ai_on")
def test_an_audio_reference_never_goes_in_the_video() -> None:
    state, _part = _with_part()
    _add_ref(state, f"uploads/{_TENANT}/ref/ritmo.mp3", "audio")
    assert state.clip_ref_chosen["copy"] == ""
    before = state._clip_tl_media()
    CreativeState.copy_clip_ref_to_video.fn(state)
    assert state._clip_tl_media() == before


@pytest.mark.usefixtures("ai_on")
def test_use_also_as_reference_copies_just_under_the_block() -> None:
    state, _part = _with_part()
    media = state._clip_tl_media()
    state.clip_edit_block = str(media[0]["id"])  # «Foto 1», 0-2 s: under no AI part
    assert state.clip_ref_copy_shown
    CreativeState.copy_clip_block_to_refs.fn(state)
    (item,) = state.clip_refs
    assert (item["keys"], item["start"], item["end"]) == ([_ONE], 0.0, 2.0)
    assert state.clip_edit_notice.endswith(vm.COPIED_UNUSED)
    state.clip_edit_block = str(media[2]["id"])  # «Foto 2», right after the part
    CreativeState.copy_clip_block_to_refs.fn(state)
    assert len(state.clip_refs) == 2


# -- a reference follows its AI part ------------------------------------------------------


@pytest.mark.usefixtures("ai_on")
def test_a_reference_whole_under_a_part_follows_it_when_it_moves() -> None:
    state, part = _with_part()
    _add_ref(state)  # 2-7 s, whole under the part
    wide = vm.new_item(state.clip_refs, "photo", [f"uploads/{_TENANT}/ref/w.png"], 1.0, 8.0)
    state.clip_refs = [*state.clip_refs, wide]
    state._clip_move_media(part, 0)  # the part goes first: 0-5 s
    by_key = {i["keys"][0]: i for i in state.clip_refs}
    assert (by_key[_REF]["start"], by_key[_REF]["end"]) == (0.0, 5.0)
    assert (by_key[wide["keys"][0]]["start"], by_key[wide["keys"][0]]["end"]) == (1.0, 8.0)
    assert "Las referencias de la parte con IA 1 se movieron con ella." in state.clip_edit_notice
    assert vm.STAYED_LINE in state.clip_edit_notice


# -- the brief -----------------------------------------------------------------------------


@pytest.mark.usefixtures("ai_on")
def test_the_brief_carries_the_tracks_and_passes_the_servers_validator() -> None:
    state, _part = _with_part()
    _add_ref(state)
    media = state._clip_edit_media()
    assert media["references_version"] == 1
    (entry,) = media["ai_parts"]  # type: ignore[misc]
    assert entry["clip_image_keys"] is None
    assert (entry["clip_video_keys"], entry["clip_audio_keys"]) == ([], [])
    assert media["clip_image_keys"] == [] and media["clip_video_keys"] == []
    brief = build_brief(_BRAND, **state._generator_form())  # type: ignore[arg-type]
    assert brief.media.references_version == 1
    (ref,) = brief.media.clip_references
    assert (ref.key, ref.start_s, ref.end_s, ref.origin) == (_REF, 2.0, 7.0, "owner")
    assert validate_brief_recipe(brief, tenant_id=_TENANT) == ()
    (part,) = references_for_parts(brief)
    assert [r.key for r in part.photos] == [_REF]


@pytest.mark.usefixtures("ai_on")
def test_the_ai_parts_panel_lost_its_photos_and_guide() -> None:
    state, part = _with_part()
    state.clip_edit_block = part
    chosen: dict[str, Any] = state.clip_ai_chosen
    assert "product_note" not in chosen and "guide_shown" not in chosen
    assert not hasattr(CreativeState, "toggle_clip_ai_photo")
    assert not hasattr(CreativeState, "handle_clip_ai_guide_uploads")
    assert state.clip_ai_refs == []
    _add_ref(state)
    state.clip_edit_block = part
    (box,) = state.clip_ai_refs
    assert box["name"] == "Foto de referencia 1" and box["ignored"] == ""


@pytest.mark.usefixtures("ai_on")
def test_the_upload_keeps_only_the_kinds_types(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: list[str] = []

    async def save(self: CreativeState, files: list[Any]) -> list[tuple[str, str]]:
        stored.extend(f.name for f in files)
        return [(f"uploads/{_TENANT}/clip/{f.name}", f.name) for f in files]

    monkeypatch.setattr(CreativeState, "_save_uploads", save)

    class _File:
        def __init__(self, name: str) -> None:
            self.name = name

    state, _part = _with_part()
    state.clip_ref_kind = "audio"
    asyncio.run(CreativeState.handle_clip_ref_uploads.fn(state, [_File("nota.txt")]))
    assert stored == [] and state.clip_edit_notice == vm.WRONG_TYPE
    asyncio.run(CreativeState.handle_clip_ref_uploads.fn(state, [_File("ritmo.mp3")]))
    assert stored == ["ritmo.mp3"]
    assert state.clip_refs[0]["kind"] == "audio"


def test_the_ref_kinds_slide_in_time_like_effects() -> None:
    assert set(vm.TL_KINDS.values()) <= set(clip_editor_vm.EDITOR_ACTIONS)
    assert all(k not in ("video", "photo", "ai") for k in vm.TL_KINDS.values())
    assert timeline_vm.MIN_S == vm.MIN_S


@pytest.mark.usefixtures("ai_on")
def test_without_ai_parts_mostrar_a_la_ia_is_off_with_its_reason() -> None:
    state = _state()
    assert state.clip_ref_add_off
    assert vm.NO_AI_PART in state.clip_tl_add_note
    _add_part(state, 0.5)
    assert not state.clip_ref_add_off
    assert vm.NO_AI_PART not in state.clip_tl_add_note


@pytest.mark.usefixtures("ai_on")
def test_the_folded_rows_agregar_opens_the_first_kind_it_names() -> None:
    state, _part = _with_part()
    _add_ref(state)  # a photo: the row folds videos and audios
    state.clip_ref_kind = "photo"
    CreativeState.open_clip_refs_folded.fn(state)
    assert state.clip_ref_kind == "video"
    assert state.clip_tl_flow == clip_editor_vm.FLOW_REF


# -- code review and Deivid's option A (2026-11-27) -----------------------------------------


def _two_parts() -> tuple[CreativeState, str, str]:
    """Photo 0-2, «Parte con IA 1» 2-7, «Parte con IA 2» 7-12, photo 12-14."""
    state = _state()
    first = _add_part(state, 0.5)
    second = _add_part(state, 3.0)
    spans = {s["id"]: (s["start"], s["end"]) for s in state._clip_ai_spans()}
    assert spans == {first: (2.0, 7.0), second: (7.0, 12.0)}
    return state, first, second


def _ref_at(state: CreativeState, name: str, start: float, end: float) -> dict[str, Any]:
    item = vm.new_item(state.clip_refs, "photo", [f"uploads/{_TENANT}/ref/{name}"], start, end)
    state.clip_refs = [*state.clip_refs, item]
    return item


def _span_of(state: CreativeState, uid: str) -> tuple[float, float]:
    item = next(i for i in state.clip_refs if i["uid"] == uid)
    return float(item["start"]), float(item["end"])


@pytest.mark.usefixtures("ai_on")
def test_removing_a_part_before_moves_the_next_parts_references_whole() -> None:
    state, first, second = _two_parts()
    later = _ref_at(state, "b.png", 7.0, 12.0)
    state.clip_edit_block = first
    CreativeState.clip_block_action.fn(state, clip_editor_vm.REMOVE)
    assert _span_of(state, later["uid"]) == (2.0, 7.0)  # never cut before it moves


@pytest.mark.usefixtures("ai_on")
def test_a_shorter_part_before_moves_the_last_parts_reference_whole() -> None:
    state, first, _second = _two_parts()
    later = _ref_at(state, "b.png", 7.0, 12.0)
    state.clip_edit_block = first
    for _ in range(3):
        CreativeState.step_clip_ai_seconds.fn(state, -1)  # 5 s → 2 s
    assert _span_of(state, later["uid"]) == (4.0, 9.0)


@pytest.mark.usefixtures("ai_on")
def test_a_fade_into_the_part_moves_its_reference_with_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import clip_joins_vm as joins  # noqa: PLC0415

    monkeypatch.setenv(joins.JOINS_SWITCH, "on")
    state, part = _with_part()
    ref = _ref_at(state, "a.png", 2.0, 7.0)
    CreativeState.open_clip_join.fn(state, part)
    CreativeState.set_clip_join.fn(state, joins.FADE)
    (span,) = state._clip_ai_spans()
    assert (span["start"], span["end"]) == (1.5, 6.5)
    assert _span_of(state, ref["uid"]) == (1.5, 6.5)


@pytest.mark.usefixtures("ai_on")
def test_removing_a_part_removes_its_references_whole_under_it_only() -> None:
    state, first, _second = _two_parts()
    one = _ref_at(state, "a.png", 2.0, 5.0)
    two = _ref_at(state, "b.png", 4.0, 7.0)
    across = _ref_at(state, "c.png", 6.0, 8.0)
    state.clip_edit_block = first
    assert state.clip_ai_chosen["refs_go"] == vm.GO_WITH_PART
    CreativeState.clip_block_action.fn(state, clip_editor_vm.REMOVE)
    uids = {i["uid"] for i in state.clip_refs}
    assert uids == {across["uid"]} and one["uid"] not in uids and two["uid"] not in uids
    assert state.clip_edit_notice.startswith("Quitaste la parte con IA 1 y sus 2 referencias.")
    # a part with none says nothing about them
    state2, part = _with_part()
    state2.clip_edit_block = part
    assert state2.clip_ai_chosen["refs_go"] == ""
    CreativeState.clip_block_action.fn(state2, clip_editor_vm.REMOVE)
    assert state2.clip_edit_notice.startswith("Quitaste la parte con IA 1.")


@pytest.mark.usefixtures("ai_on")
def test_a_part_joined_with_the_next_keeps_both_parts_references() -> None:
    state, first, second = _two_parts()
    one = _ref_at(state, "a.png", 2.0, 7.0)
    two = _ref_at(state, "b.png", 7.0, 12.0)
    plan = {**state._clip_ai_plan(first), "seconds": 10}
    state._clip_ai_apply_merge(first, second, plan)
    (span,) = state._clip_ai_spans()
    assert (span["start"], span["end"]) == (2.0, 12.0)
    assert _span_of(state, one["uid"]) == (2.0, 7.0)
    assert _span_of(state, two["uid"]) == (7.0, 12.0)
    used = state._clip_refs_plan()["used_by"]
    assert used == {one["uid"]: [1], two["uid"]: [1]}


@pytest.mark.usefixtures("ai_on")
def test_a_reference_of_another_business_is_refused_by_the_server() -> None:
    state, _part = _with_part()
    other = "uploads/b0000000-0000-4000-8000-000000000009/ref/ajena.png"
    _ref_at(state, "ajena.png", 2.0, 7.0)
    state.clip_refs = [{**state.clip_refs[0], "keys": [other]}]
    brief = build_brief(_BRAND, **state._generator_form())  # type: ignore[arg-type]
    problems = validate_brief_recipe(brief, tenant_id=_TENANT)
    assert [(p.code, p.field) for p in problems] == [("foreign_key", "clip_references[0].key")]


@pytest.mark.usefixtures("ai_on")
def test_an_upload_that_cannot_go_in_is_never_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: list[str] = []

    async def save(self: CreativeState, files: list[Any]) -> list[tuple[str, str]]:
        stored.extend(f.name for f in files)
        return [(f"uploads/{_TENANT}/clip/{f.name}", f.name) for f in files]

    monkeypatch.setattr(CreativeState, "_save_uploads", save)

    class _File:
        def __init__(self, name: str) -> None:
            self.name = name

    state, _part = _with_part()
    cap = contract_ai.reference_caps()["photo"]
    for n in range(cap):
        _add_ref(state, f"uploads/{_TENANT}/ref/p{n}.png")
    state.clip_ref_kind = "photo"
    asyncio.run(CreativeState.handle_clip_ref_uploads.fn(state, [_File("otra.png")]))
    assert stored == [] and state.clip_edit_notice == vm.cap_full("photo", 1, cap)


@pytest.mark.usefixtures("ai_on")
def test_the_products_block_stays_within_the_briefs_references() -> None:
    state, _part = _with_part()
    held = [_ref_at(state, f"o{n}.png", 2.0, 7.0) for n in range(vm.REFERENCES_MAX - 1)]
    photos = [f"uploads/{_TENANT}/catalog/p{n}.jpg" for n in range(3)]
    state._clip_refs_put_product(_PRODUCT, "Combo", photos)
    product = next(i for i in state.clip_refs if i.get("origin") == "product")
    assert product["keys"] == photos[:1]
    assert sum(len(i["keys"]) for i in state.clip_refs) == len(held) + 1
    assert state.clip_edit_notice.endswith(vm.TOO_MANY)


def test_the_entry_keeps_only_igual_al_originals_reel_window() -> None:
    window = f"uploads/{_TENANT}/reel/ventana.mp4"
    parts = [
        {"uid": "a", "plan": {"mode": "edit", "clip_video_keys": [window], "seconds": 5}},
        {"uid": "b", "plan": {"mode": "reference", "clip_video_keys": [window], "seconds": 5}},
    ]
    edit, new = ai_vm.plans(parts, references=True)
    assert edit["clip_video_keys"] == [window] and edit["clip_image_keys"] is None
    assert new["clip_video_keys"] == [] and new["clip_audio_keys"] == []


@pytest.mark.usefixtures("ai_on")
def test_the_server_takes_the_reel_window_only_in_igual_al_original() -> None:
    """#869: on the tracks (`references_version` 1) an entry may carry `clip_video_keys`
    only in «Igual al original» — the reel's window, never a reference."""
    window = f"uploads/{_TENANT}/reel/ventana.mp4"
    segments = [
        {"key": _ONE, "kind": "photo", "start_s": 0, "end_s": 2},
        {"key": "ai_part:0", "kind": "ai_part", "start_s": 0, "end_s": 5},
    ]
    edit = {
        "mode": "edit",
        "seconds": 5,
        "description": "Igual",
        "analysis_id": "00000000-0000-4000-8000-0000000000aa",
        "shot_indexes": [0],
        "clip_video_keys": [window],
    }

    def refused(entry: dict[str, Any]) -> list[tuple[str, str]]:
        brief = vm.brief_of(segments, [entry], [])
        return [
            (p.code, p.field or "")
            for p in validate_brief_recipe(brief, tenant_id=_TENANT)
            if p.code == "references_and_old_fields"
        ]

    (kept,) = ai_vm.plans([{"uid": "a", "plan": edit}], references=True)
    assert kept["clip_video_keys"] == [window]
    assert refused(kept) == []
    # in «Nueva» the same key is an old field: the screen never sends it…
    new = {**edit, "mode": "reference", "analysis_id": None, "shot_indexes": []}
    assert refused(new) == [("references_and_old_fields", "ai_parts[0].clip_video_keys")]
    (dropped,) = ai_vm.plans([{"uid": "b", "plan": new}], references=True)
    assert dropped["clip_video_keys"] == [] and refused(dropped) == []


# -- second code review ----------------------------------------------------------------------


@pytest.mark.usefixtures("ai_on")
def test_removing_a_photo_before_a_part_moves_its_reference_with_it() -> None:
    state, _part = _with_part()  # photo 0-2, part 2-7, photo 7-9
    ref = _ref_at(state, "a.png", 2.0, 7.0)
    state._clip_refs_store(list(state.clip_refs))  # laid against the timeline now
    state.clip_edit_block = str(state._clip_tl_media()[0]["id"])
    CreativeState.clip_block_action.fn(state, clip_editor_vm.REMOVE)
    (span,) = state._clip_ai_spans()
    assert (span["start"], span["end"]) == (0.0, 5.0)
    assert _span_of(state, ref["uid"]) == (0.0, 5.0)
    assert "se movieron con ella" in state.clip_edit_notice


@pytest.mark.usefixtures("ai_on")
def test_joining_6_and_6_seconds_cuts_the_second_parts_references_to_10() -> None:
    state, first, second = _two_parts()
    for block in (first, second):
        state.clip_edit_block = block
        CreativeState.step_clip_ai_seconds.fn(state, 1)  # 5 s → 6 s
    spans = {s["id"]: (s["start"], s["end"]) for s in state._clip_ai_spans()}
    assert spans == {first: (2.0, 8.0), second: (8.0, 14.0)}
    near = _ref_at(state, "a.png", 8.0, 11.0)
    far = _ref_at(state, "b.png", 12.0, 14.0)  # wholly past the joined part's end
    edge = _ref_at(state, "c.png", 11.0, 12.2)  # 0,2 s past it: cut to 11-12
    state._clip_refs_store(list(state.clip_refs))
    plan = {**state._clip_ai_plan(first), "seconds": 10}
    state._clip_ai_apply_merge(first, second, plan)
    (span,) = state._clip_ai_spans()
    assert (span["start"], span["end"]) == (2.0, 12.0)
    assert far["uid"] not in {i["uid"] for i in state.clip_refs}
    assert _span_of(state, near["uid"]) == (8.0, 11.0)
    assert _span_of(state, edge["uid"]) == (11.0, 12.0)


@pytest.mark.usefixtures("ai_on")
def test_down_on_the_last_row_opens_no_new_one() -> None:
    state, _part = _with_part()
    block = _add_ref(state)
    CreativeState.clip_block_key.fn(state, block, "", "ArrowDown")
    assert state.clip_refs[0]["row"] == 0


@pytest.mark.usefixtures("ai_on")
def test_use_also_as_reference_respects_the_parts_cap() -> None:
    state, _part = _with_part()
    cap = contract_ai.reference_caps()["photo"]
    for n in range(cap):
        _add_ref(state, f"uploads/{_TENANT}/ref/p{n}.png")
    # «Foto 1» (0-2 s) is under no part: its copy goes in
    state.clip_edit_block = str(state._clip_tl_media()[0]["id"])
    CreativeState.copy_clip_block_to_refs.fn(state)
    assert len(state.clip_refs) == cap + 1


@pytest.mark.usefixtures("ai_on")
def test_use_also_as_reference_is_refused_over_the_cap_of_a_part_it_lands_under(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import clip_joins_vm as joins  # noqa: PLC0415

    monkeypatch.setenv(joins.JOINS_SWITCH, "on")
    state, part = _with_part()
    cap = contract_ai.reference_caps()["photo"]
    for n in range(cap):
        _add_ref(state, f"uploads/{_TENANT}/ref/p{n}.png")
    # a fade into the part lays its start over «Foto 1»: a copy of «Foto 1» lands under it
    CreativeState.open_clip_join.fn(state, part)
    CreativeState.set_clip_join.fn(state, joins.FADE)
    state.clip_join_open = ""
    state.clip_edit_block = str(state._clip_tl_media()[0]["id"])
    before = len(state.clip_refs)
    CreativeState.copy_clip_block_to_refs.fn(state)
    assert len(state.clip_refs) == before
    assert state.clip_edit_notice == vm.cap_full("photo", 1, cap)


# -- third code review ---------------------------------------------------------------------

_NEW = f"uploads/{_TENANT}/clip/nueva.jpg"


def _laid(state: CreativeState, name: str, start: float, end: float) -> dict[str, Any]:
    """A reference laid against the timeline as it is now (as the tab puts one)."""
    item = vm.new_item(state.clip_refs, "photo", [f"uploads/{_TENANT}/ref/{name}"], start, end)
    state._clip_refs_store([*state.clip_refs, item])
    return item


@pytest.mark.usefixtures("ai_on")
def test_a_galeria_pick_at_the_start_moves_the_reference_before_the_next_one_is_put() -> None:
    state, _part = _with_part()  # photo 0-2, part 2-7, photo 7-9
    first = _laid(state, "a.png", 2.0, 7.0)
    # «Tu Galería»: a photo aimed at the start, as its pick puts it (`_sync_clip_frames`)
    state._clip_aim(0)
    state.clip_images = [
        *state.clip_images,
        {"key": _NEW, "name": "nueva.jpg", "source": "gallery", "role": "product"},
    ]
    state._sync_clip_frames()
    (span,) = state._clip_ai_spans()
    assert (span["start"], span["end"]) == (4.0, 9.0)
    _add_ref(state, f"uploads/{_TENANT}/ref/b.png")
    assert _span_of(state, first["uid"]) == (4.0, 9.0)


@pytest.mark.usefixtures("ai_on")
def test_a_reference_of_the_second_part_over_a_fade_is_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import clip_joins_vm as joins  # noqa: PLC0415

    monkeypatch.setenv(joins.JOINS_SWITCH, "on")
    state, _first, second = _two_parts()
    CreativeState.open_clip_join.fn(state, second)
    CreativeState.set_clip_join.fn(state, joins.FADE)  # the second starts 0,5 s earlier
    state.clip_join_open = ""
    spans = {s["id"]: (s["start"], s["end"]) for s in state._clip_ai_spans()}
    assert spans[second] == (6.5, 11.5)
    ref = _laid(state, "b.png", 6.5, 11.5)  # over the fade, the second part's
    CreativeState.remove_clip_image.fn(state, _ONE)  # «Foto 1» goes: everything 2 s left
    assert _span_of(state, ref["uid"]) == (4.5, 9.5)
    state.clip_edit_block = second
    assert state.clip_ai_chosen["refs_go"] == vm.GO_WITH_PART
    CreativeState.clip_block_action.fn(state, clip_editor_vm.REMOVE)
    assert ref["uid"] not in {i["uid"] for i in state.clip_refs}


@pytest.mark.usefixtures("ai_on")
def test_a_video_removed_before_the_part_moves_its_reference() -> None:
    state, _part = _with_part()
    video = f"uploads/{_TENANT}/clip/antes.mp4"
    state.clip_media_seconds = {video: 3.0}
    state.clip_videos = [{"key": video, "name": "antes.mp4", "source": "upload"}]
    state.clip_sequence = [video, *state._clip_order_keys()]
    state._sync_clip_frames()
    (span,) = state._clip_ai_spans()
    ref = _laid(state, "a.png", span["start"], span["end"])
    CreativeState.remove_clip_video.fn(state, video)
    (after,) = state._clip_ai_spans()
    assert after["start"] < span["start"]  # the video's block left: the part moved
    assert _span_of(state, ref["uid"]) == (after["start"], after["end"])


@pytest.mark.usefixtures("ai_on")
def test_files_added_before_the_part_move_its_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import clip_gallery_vm  # noqa: PLC0415

    async def save(self: CreativeState, files: list[Any]) -> list[tuple[str, str]]:
        return [(f"uploads/{_TENANT}/clip/{f.name}", f.name) for f in files]

    monkeypatch.setattr(CreativeState, "_save_uploads", save)

    class _File:
        def __init__(self, name: str) -> None:
            self.name = name

    state, _part = _with_part()
    ref = _laid(state, "a.png", 2.0, 7.0)
    state._clip_aim(0)
    asyncio.run(state._add_clip_files(clip_gallery_vm.IMAGE, [_File("subida.jpg")]))
    assert _span_of(state, ref["uid"]) == (4.0, 9.0)


@pytest.mark.usefixtures("ai_on")
def test_a_longer_photo_before_the_part_moves_its_reference() -> None:
    state, _part = _with_part()
    ref = _laid(state, "a.png", 2.0, 7.0)
    assert state._clip_photo_set(str(state._clip_tl_media()[0]["id"]), 4.0)
    assert _span_of(state, ref["uid"]) == (4.0, 9.0)


@pytest.mark.usefixtures("ai_on")
def test_a_longer_fade_moves_the_parts_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    from . import clip_joins_vm as joins  # noqa: PLC0415

    monkeypatch.setenv(joins.JOINS_SWITCH, "on")
    state, part = _with_part()
    CreativeState.open_clip_join.fn(state, part)
    CreativeState.set_clip_join.fn(state, joins.FADE)
    (span,) = state._clip_ai_spans()
    ref = _laid(state, "a.png", span["start"], span["end"])
    CreativeState.set_clip_join_seconds.fn(state, [1.0])
    (after,) = state._clip_ai_spans()
    assert after["start"] < span["start"]
    assert _span_of(state, ref["uid"]) == (after["start"], after["end"])


@pytest.mark.usefixtures("ai_on")
def test_over_the_cap_crear_is_off_on_the_last_step_and_going_back_works() -> None:
    state, _part = _with_part()
    cap = contract_ai.reference_caps()["photo"]
    items: list[dict[str, Any]] = []
    for n in range(cap + 1):
        items.append(vm.new_item(items, "photo", [f"uploads/{_TENANT}/ref/p{n}.png"], 2.0, 7.0))
    state._clip_refs_store(items)
    card = vm.cap_card("photo", 1, cap + 1, cap)
    state.gen_step = len(state._gen_steps()) - 1  # «Revisa y crea», off the editor
    assert state.gen_is_last_view
    assert state.create_primary_disabled
    assert state.create_reason == card
    # going back is never held by the cap
    last = state.gen_step
    CreativeState.go_to_view.fn(state, str(last - 1))
    assert state.gen_step == last - 1


# -- fourth code review: the live line ---------------------------------------------------

_FOLLOWED = "Las referencias de la parte con IA 1 se movieron con ella."


@pytest.mark.usefixtures("ai_on")
def test_use_also_in_the_video_says_its_copy_and_that_the_references_followed() -> None:
    state, _part = _with_part()  # photo 0-2, part 2-7, photo 7-9
    _laid(state, "a.png", 2.0, 7.0)
    early = _laid(state, "b.png", 0.0, 1.5)  # nearest join: the start of the video
    state.clip_edit_block = vm.ref_id(early["uid"])
    CreativeState.copy_clip_ref_to_video.fn(state)
    assert state.clip_edit_notice.startswith("Copiamos la foto de referencia 1 a «Fotos y videos»")
    assert state.clip_edit_notice.endswith(_FOLLOWED)


@pytest.mark.usefixtures("ai_on")
def test_a_longer_photo_says_its_line_and_that_the_references_followed() -> None:
    state, _part = _with_part()
    _laid(state, "a.png", 2.0, 7.0)
    assert state._clip_photo_set(str(state._clip_tl_media()[0]["id"]), 4.0)
    assert state.clip_edit_notice.endswith(_FOLLOWED)
    assert state.clip_edit_notice != _FOLLOWED  # its own line goes first


@pytest.mark.usefixtures("ai_on")
def test_an_old_line_is_never_kept_in_front_of_the_follow_words() -> None:
    state, _part = _with_part()
    _laid(state, "a.png", 2.0, 7.0)
    state.clip_edit_notice = "Quitaste el texto."
    CreativeState.remove_clip_image.fn(state, _ONE)  # the ✕ of «Fotos y videos»
    assert state.clip_edit_notice == _FOLLOWED
    # from the bar: its own line, then the words
    state2, _part2 = _with_part()
    _laid(state2, "a.png", 2.0, 7.0)
    state2.clip_edit_notice = "Quitaste el texto."
    state2.clip_edit_block = str(state2._clip_tl_media()[0]["id"])
    CreativeState.clip_block_action.fn(state2, clip_editor_vm.REMOVE)
    assert state2.clip_edit_notice == f"Quitaste la foto 1. {_FOLLOWED}"
    assert "Quitaste el texto." not in state2.clip_edit_notice


# -- last review: whose line it is (a flag, never the text) -------------------------------


@pytest.mark.usefixtures("ai_on")
def test_the_same_photo_line_twice_keeps_its_words_before_the_follow() -> None:
    state, _part = _with_part()
    _laid(state, "a.png", 2.0, 7.0)
    photo = str(state._clip_tl_media()[0]["id"])
    assert state._clip_photo_set(photo, 3.5)
    first = state.clip_edit_notice
    assert first.endswith(_FOLLOWED) and first != _FOLLOWED
    assert state._clip_photo_set(photo, 2.0)  # another change in between
    assert state._clip_photo_set(photo, 3.5)  # the same words as two changes ago
    assert state.clip_edit_notice == first


@pytest.mark.usefixtures("ai_on")
def test_two_syncs_in_one_change_say_the_follow_once() -> None:
    state, first, _second = _two_parts()
    _laid(state, "b.png", 7.0, 12.0)  # under the second part
    state.clip_edit_notice = "Algo de antes."
    state._clip_ref_change_starts()
    for seconds in (4, 3):  # the first part shorter, twice: the second moves twice
        state._clip_ai_put(first, ai_vm.with_seconds(state._clip_ai_plan(first), seconds))
        state._clip_refs_sync()
    notice = state.clip_edit_notice
    assert notice == "Las referencias de la parte con IA 2 se movieron con ella."
    assert "Algo de antes." not in notice


@pytest.mark.usefixtures("ai_on")
def test_a_trim_of_the_own_video_says_its_line_and_the_follow() -> None:
    own = f"uploads/{_TENANT}/clip/propio.mp4"
    state = CreativeState()
    state.choose_category("clip")
    state.brief_topic = "Promoción"
    state.clip_videos = [{"key": own, "name": "propio.mp4", "source": "upload"}]
    state._clip_session_tenant = str(_TENANT)
    CreativeState.report_clip_source.fn(state, own, 20.0, 1080, 1920)
    part = _add_part(state, 0.5)
    (span,) = state._clip_ai_spans()
    ref = _laid(state, "a.png", span["start"], span["end"])
    CreativeState.drop_clip_block.fn(state, own, "end", 8.0)
    (after,) = state._clip_ai_spans()
    assert after["start"] < span["start"] and part
    assert _span_of(state, ref["uid"]) == (after["start"], after["end"])
    assert state.clip_edit_notice.startswith("Recortaste el video 1.")
    assert state.clip_edit_notice.endswith(_FOLLOWED)


@pytest.mark.usefixtures("ai_off")
def test_with_the_switch_off_the_live_line_is_as_on_main() -> None:
    state = _state()
    state.clip_edit_notice = "Quitaste el texto."
    state.clip_edit_block = str(state._clip_tl_media()[0]["id"])
    CreativeState.clip_block_action.fn(state, clip_editor_vm.REMOVE)
    assert state.clip_edit_notice == "Quitaste la foto 1."
    photo = str(state._clip_tl_media()[0]["id"])
    assert state._clip_photo_set(photo, 3.5)
    assert "referencias" not in state.clip_edit_notice
