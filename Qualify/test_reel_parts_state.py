"""UI-3 (m-24921077): «Tu video, parte por parte» in `CreativeState` — the plan the poll
stores, «Quitar» / «Deshacer» (the list's only edit until UI-4: Deivid hid «Cambiar»,
«Añadir parte» and the presenter offer, 2026-11-09), «Lo que usa de tu mes» and
«Siguiente» that never waits. No database: the plan comes from the pure view model."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from qualify_api.referentes.reel_analysis_types import OBSERVED

from . import reel_parts_vm as parts_vm
from . import reel_wait_vm as vm
from .creative_state import CreativeState
from .test_reel_parts_vm import MOCKUP, analysis, entries_of, shot
from .test_reel_wait_state import (  # noqa: F401 — fixture
    TENANT,
    Proxy,
    backend,
    ok,
    poll,
    replica,
)

__all__ = ["backend"]


def planned(entries: list[dict[str, Any]] | None = None) -> CreativeState:
    """A piece from «Hacer uno parecido» whose analysis is `ok`, its plan listed."""
    state = replica("ok")
    entries = entries_of(MOCKUP) if entries is None else entries
    state._show_reel_wait(vm.ready(max(len(entries), 1)))
    state._set_reel_plan(entries)
    return state


def labels(state: CreativeState) -> list[str]:
    return [row["label"] for row in state.reel_part_rows]


# -- the poll lists the plan --------------------------------------------------------------


async def test_the_poll_lists_the_parts_of_the_plan(backend: SimpleNamespace) -> None:
    state = replica("ok")
    backend.statuses, backend.parts = [ok], 3
    await poll(state)
    assert state.reel_plan_shown and state.reel_parts_count == 3
    assert len(state.reel_part_rows) == 3 and len(state._reel_plan) == 3
    assert state.reel_parts_summary == "3 partes · 12 s"
    assert backend.plan_calls == [(UUID(TENANT), UUID(state.reel_analysis_id), ("Smash doble",))]


def test_the_rows_show_form_person_and_why() -> None:
    state = planned()
    assert labels(state) == ["Parte 1 · 5 s", "Parte 2 · 4 s", "Parte 3 · 6 s", "↳ Parte 4 · 6 s"]
    assert "aparece una persona" in state.reel_part_rows[1]["aria"]
    assert parts_vm.FORM_INSPIRED.lower() in state.reel_part_rows[1]["aria"]
    assert state.reel_part_rows[1]["why"] != "" and state.reel_part_rows[0]["why"] == ""


def test_going_without_the_reel_forgets_the_plan() -> None:
    state = planned()
    state.reel_go_without()
    assert state._reel_plan == [] and state.reel_part_rows == [] and not state.reel_plan_shown


# -- «Quitar» and «Deshacer» ------------------------------------------------------------


def test_removing_asks_nothing_and_offers_undo() -> None:
    state = planned()
    second = state.reel_part_rows[1]["key"]
    assert state.remove_reel_part(second) is not None  # the keyboard goes to «Deshacer»
    assert state.reel_parts_count == 3 and state.reel_undo_text == "Quitaste la parte 2."
    assert labels(state)[1] == "Parte 2 · 6 s"
    state.undo_reel_part()
    assert state.reel_parts_count == 4 and state.reel_undo_text == ""
    assert state.reel_part_rows[1]["key"] == second


def test_removing_every_part_leaves_the_empty_list_and_next_still_goes_on() -> None:
    state = planned(entries_of(analysis(shot(0, 0, 5))))
    state.remove_reel_part(state.reel_part_rows[0]["key"])
    assert state.reel_parts_count == 0 and state.reel_part_rows == []
    assert state.reel_undo_text == "Quitaste la parte 1."  # the empty list points to it
    assert not state.create_primary_disabled and state.create_reason == ""


def test_next_never_waits_for_the_parts() -> None:
    state = planned()
    assert not state.create_primary_disabled and state.create_reason == ""
    assert state.next_view() is not None and state.gen_step_key != "show"


# -- «Añadir parte» and «Cambiar» -------------------------------------------------------


def test_the_list_events_do_nothing_on_a_normal_clip() -> None:
    state = CreativeState()
    assert state.remove_reel_part("x") is None
    state.undo_reel_part()
    assert state._reel_plan == [] and state.reel_undo_text == ""


# -- nothing switches to a presenter from here -------------------------------------------


def test_someone_talking_changes_nothing_and_offers_nothing() -> None:
    """Never autonomous (m-24880680) and, until UI-10, no presenter offer at all."""
    talking = analysis(shot(0, 0, 5, people=OBSERVED, faces=OBSERVED, spoken="¿Ya lo probaste?"))
    state = planned(entries_of(talking))
    assert state.brief_kind == "clip" and state.reel_plan_shown
    assert not hasattr(CreativeState, "use_presenter_for_reel")
    assert not hasattr(CreativeState, "reel_presenter_offer")


# -- «Lo que usa de tu mes» -------------------------------------------------------------


def test_the_month_usage_is_said_without_money_and_only_with_a_quota() -> None:
    state = planned()
    assert state.reel_usage_lines == []  # no quota wired (creations_left = -1)
    state.creations_left, state.creations_quota = 10, 30
    state.previews_left, state.previews_quota = 12, 20
    state.videos_left, state.videos_quota = 40, 40
    assert state.reel_usage_lines == [
        "Crear las 4 partes usa 4 vistas previas. Te quedan 12.",
        "Este video dura 21 s y este mes te quedan 40 s de video. Al aprobarlo te quedarían 19 s.",
    ]
    state.videos_left, state.creations_renews = 10, "1 de diciembre"
    assert state.reel_usage_lines[1].endswith(
        "Para aprobarlo, quita partes o espera al 1 de diciembre, cuando vuelven tus 40 segundos."
    )


def test_one_part_counts_without_the_many_parts_help() -> None:
    state = planned(entries_of(analysis(shot(0, 0, 5))))
    assert state.reel_parts_summary == "1 parte · 5 s"
    assert state.reel_single_part and state.reel_parts_count == 1


def test_the_list_can_edit_and_append_parts() -> None:
    """UI-4 exposes transactional changes and appends beside UI-3's list edits."""
    for name in ("add_reel_part", "edit_reel_part", "save_reel_part", "set_reel_edit_text"):
        assert hasattr(CreativeState, name)


# -- round 6: the parts in «Orden del clip» ---------------------------------------------


def test_before_and_after_move_and_say_it_and_keep_the_keyboard() -> None:
    state = planned()
    second = state.reel_part_rows[1]["key"]
    assert state.move_reel_part_up(second) is not None  # focus stays on «Antes»
    assert state.reel_part_rows[0]["key"] == second
    assert state.reel_move_text == "Moviste la parte 2: ahora es la parte 1."
    assert state.move_reel_part_up(second) is None  # first: nothing moves
    assert state.move_reel_part_down(second) is not None
    assert state.reel_part_rows[1]["key"] == second


def test_a_drag_moves_the_unit_and_its_stuck_part() -> None:
    state = planned()
    pair = [state.reel_part_rows[2]["key"], state.reel_part_rows[3]["key"]]
    state.start_reel_part_drag("2")
    state.drop_reel_part("0")
    assert [r["key"] for r in state.reel_part_rows][:2] == pair
    assert state.reel_drag_from == -1
    assert state.reel_move_text == "Moviste la parte 3: ahora es la parte 1."


def test_undo_brings_the_part_back_in_its_place_and_a_move_ends_the_undo() -> None:
    state = planned()
    order = [r["key"] for r in state.reel_part_rows]
    state.remove_reel_part(order[1])
    assert state.reel_move_text == ""
    state.undo_reel_part()
    assert [r["key"] for r in state.reel_part_rows] == order
    state.remove_reel_part(order[1])
    state.move_reel_part_down(order[0])
    assert state.reel_undo_text == "" and state._reel_plan_before == []


def test_moving_never_replans_nor_touches_the_month(backend: SimpleNamespace) -> None:
    state = planned()
    state.creations_left, state.previews_left, state.previews_quota = 10, 12, 20
    lines = list(state.reel_usage_lines)
    state.move_reel_part_down(state.reel_part_rows[0]["key"])
    assert backend.plan_calls == [] and backend.status_calls == []
    assert state.reel_usage_lines == lines and state.previews_left == 12


def test_the_regular_orden_del_clip_is_untouched_without_a_reel_plan() -> None:
    """No reel plan: «Orden del clip» is the strip of files, dragged as before."""
    state = CreativeState()
    state.clip_images = [
        {"key": "a.png", "name": "a", "source": "upload", "role": "product"},
        {"key": "b.png", "name": "b", "source": "upload", "role": "product"},
    ]
    state._sync_clip_frames()
    assert not state.reel_plan_shown
    assert [i["key"] for i in state.clip_strip] == ["a.png", "b.png"]
    assert state.clip_first_frame_key == "a.png" and state.clip_last_frame_key == "b.png"
    state.start_clip_image_drag(1)
    state.drop_clip_image(0)
    assert [i["key"] for i in state.clip_strip] == ["b.png", "a.png"]
    assert state.clip_first_frame_key == "b.png"
    # the parts' events do nothing there
    assert state.move_reel_part_up("a.png") is None
    state.start_reel_part_drag("0")
    state.drop_reel_part("1")
    assert [i["key"] for i in state.clip_strip] == ["b.png", "a.png"]


def test_a_reel_plan_keeps_the_owners_photos() -> None:
    state = planned()
    photos = list(state.clip_images)
    state.remove_reel_part(state.reel_part_rows[0]["key"])
    state.move_reel_part_down(state.reel_part_rows[0]["key"])
    assert state.clip_images == photos


# -- round 7: drag input checked, one card per unit -------------------------------------


def test_a_drag_with_a_bad_index_moves_nothing() -> None:
    state = planned()
    order = [r["key"] for r in state.reel_part_rows]
    for bad in (None, "x", "", 9, -1):
        state.start_reel_part_drag(bad)  # type: ignore[arg-type]
        assert state.reel_drag_from == -1
        state.drop_reel_part("0")
        state.start_reel_part_drag("1")
        state.drop_reel_part(bad)  # type: ignore[arg-type]
        assert [r["key"] for r in state.reel_part_rows] == order


def test_a_drag_lifted_before_the_list_changed_moves_nothing() -> None:
    state = planned()
    state.start_reel_part_drag("2")
    state.remove_reel_part(state.reel_part_rows[0]["key"])
    order = [r["key"] for r in state.reel_part_rows]
    assert state.reel_drag_from == -1
    state.drop_reel_part("0")
    assert [r["key"] for r in state.reel_part_rows] == order


def test_a_part_and_its_stuck_part_are_one_drag_card() -> None:
    state = planned()
    assert [[r["index"] for r in unit] for unit in state.reel_part_units] == [
        ["1"],
        ["2"],
        ["3", "4"],
    ]


def test_the_view_sends_the_unit_as_text_and_describes_only_disabled_ends() -> None:
    """Round 8: the handlers take the row's `unit` string; `aria-describedby` exists only
    on the disabled «Antes» / «Después»; the owner's photos are listed once."""
    from . import content_generator as cg

    rendered = str(cg._clip_parts_block().render())
    assert 'aria-describedby":""' not in rendered.replace(" ", "")
    assert not hasattr(cg, "_clip_parts_photos")


# -- round 15: references by category; parts move by drag or keys (no arrows) ----------


def test_each_category_lists_its_own_tiles_never_the_reels_video() -> None:
    state = planned()
    assert any(v.get("source") == "reel" for v in state.clip_videos)
    state.clip_images = [{"key": "a.png", "name": "a", "source": "upload", "role": "place"}]
    state.clip_videos = [*state.clip_videos, {"key": "m.mp4", "name": "m", "source": "upload"}]
    state.clip_audios = [{"key": "s.mp3", "name": "s", "source": "upload"}]
    tiles = state.clip_reference_tiles  # one grid, in the order added
    assert [(t["kind"], t["key"]) for t in tiles] == [
        ("image", "a.png"),
        ("video", "m.mp4"),
        ("audio", "s.mp3"),
    ]
    assert tiles[0]["role"] == "place"


def test_a_role_set_in_fotos_is_the_strips_and_survives() -> None:
    state = planned()
    state.clip_images = [{"key": "b.png", "name": "b", "source": "catalog", "role": ""}]
    assert state.clip_reference_tiles[0]["role"] == "product"
    state.set_clip_image_role("b.png", "place")
    state.reel_go_without()
    assert not state.reel_plan_shown
    strip = {item["key"]: item.get("role", "") for item in state.clip_strip}
    assert strip["b.png"] == "place" and state.clip_reference_tiles[0]["role"] == "place"


def test_removing_an_own_video_keeps_the_reels() -> None:
    state = planned()
    state.clip_videos = [*state.clip_videos, {"key": "m.mp4", "name": "m", "source": "upload"}]
    state._sync_clip_frames()
    reel = [v["key"] for v in state.clip_videos if v.get("source") == "reel"]
    state.remove_clip_video("m.mp4")
    assert [v["key"] for v in state.clip_videos if v.get("source") == "reel"] == reel
    assert all(key in state.clip_sequence for key in reel)
    assert state.reel_plan_shown and state.source_reel


class _File:
    def __init__(self, name: str) -> None:
        self.name = name


async def _save_all(self: object, files: list[_File]) -> list[tuple[str, str]]:
    return [(f"uploads/{f.name}", f.name) for f in files]


async def test_each_categorys_zone_takes_its_room_and_says_the_rest_there(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(CreativeState, "_save_uploads", _save_all)
    state = planned()  # the reel's video takes one of the 3
    state.clip_images = [
        {"key": f"i{n}.png", "name": "i", "source": "upload", "role": "product"} for n in range(8)
    ]
    proxy = Proxy(state, SimpleNamespace())
    await CreativeState.handle_clip_image_uploads.fn(proxy, [_File("x.png"), _File("y.jpg")])
    assert len(state.clip_images) == 9
    assert state.clip_notes["image"] == (
        "No agregamos 1 foto: ya tienes 9, el máximo. Quita una para cambiarla."
    )
    assert state.clip_full_notes["image"].startswith("Ya tienes 9 fotos")
    await CreativeState.handle_clip_video_uploads.fn(
        proxy, [_File("a.mp4"), _File("b.mov"), _File("c.mov")]
    )
    own = [v["key"] for v in state.clip_videos if v.get("source") != "reel"]
    assert own == ["uploads/a.mp4", "uploads/b.mov"]
    assert state.clip_notes["video"] == (
        "No agregamos 1 video: ya tienes 2 tuyos, el máximo con un reel. Quita uno para cambiarlo."
    )
    assert state.clip_notes["image"].startswith("No agregamos 1 foto")  # untouched
    await CreativeState.handle_clip_audio_uploads.fn(proxy, [_File("t.wav")])
    assert state.clip_notes["audio"] == "" and len(state.clip_audios) == 1
    # removing any file clears the notes
    state.remove_clip_audio("uploads/t.wav")
    assert state.clip_notes == {"image": "", "video": "", "audio": ""}


async def test_no_save_without_room(monkeypatch: pytest.MonkeyPatch) -> None:
    state = CreativeState()
    state.clip_audios = [{"key": f"s{n}.mp3", "name": "s", "source": "upload"} for n in range(3)]
    calls: list[int] = []

    async def save(self: object, files: list[_File]) -> list[tuple[str, str]]:
        calls.append(len(files))
        return []

    monkeypatch.setattr(CreativeState, "_save_uploads", save)
    await CreativeState.handle_clip_audio_uploads.fn(
        Proxy(state, SimpleNamespace()), [_File("t.wav")]
    )
    assert calls == []
    assert state.clip_notes["audio"].startswith("No agregamos 1 audio")


async def test_a_drop_with_refused_and_taken_files_says_both_in_any_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """react-dropzone fires `on_drop` and `on_drop_rejected` for one drop, in no fixed
    order — neither note wipes the other, and each stays in its category."""
    big = [{"file": {"path": "./largo.mp3"}, "errors": [{"code": "file-too-large"}]}]
    monkeypatch.setattr(CreativeState, "_save_uploads", _save_all)
    for rejected_first in (True, False):
        state = CreativeState()
        state.clip_audios = [
            {"key": f"s{n}.mp3", "name": "s", "source": "upload"} for n in range(3)
        ]
        if rejected_first:
            state.clip_files_rejected("audio", big)
        await CreativeState.handle_clip_audio_uploads.fn(
            Proxy(state, SimpleNamespace()), [_File("t.wav")]
        )
        if not rejected_first:
            state.clip_files_rejected("audio", big)
        assert state.clip_notes["audio"] == (
            "No agregamos largo.mp3: pesa más de 200 MB. "
            "No agregamos 1 audio: ya tienes 3, el máximo. Quita uno para cambiarlo."
        ), rejected_first
        assert state.clip_notes["image"] == "" and state.clip_notes["video"] == ""


def test_a_wrong_type_is_said_in_its_category_and_a_fresh_clip_forgets_it() -> None:
    state = replica("ok")
    state.clip_files_rejected(
        "image", [{"file": {"path": "x.mp4"}, "errors": [{"code": "file-invalid-type"}]}]
    )
    assert state.clip_notes["image"] == "No agregamos 1 archivo: aquí van fotos PNG, JPG o WEBP."
    state.clip_files_rejected("nada", [])  # an unknown category is ignored
    state._apply_reel_reference(
        {"key": "instagram:B", "network": "instagram", "id": "B", "url": "", "handle": "x"},
        {"key": "uploads/r.mp4", "name": "r"},
    )
    assert state.clip_notes == {"image": "", "video": "", "audio": ""}


def test_one_button_opens_the_clip_drawer_and_its_sources_switch() -> None:
    """m-24985141: «Elegir fotos, videos o audios» opens the media drawer; its sources
    are «Tus productos · Tu Galería · Subir · Publicaciones · Inspiración»."""
    state = CreativeState()
    assert not state.media_drawer_open
    state.open_media_drawer("clip", "upload", "media-open-clip")
    assert state.media_drawer_open and state.media_drawer_target == "clip"
    assert state.clip_source_tab == "upload"
    state.set_clip_source_tab(["pieces"])  # the segmented control may send a list
    assert state.clip_source_tab == "pieces"
    state.set_clip_source_tab("nada")
    assert state.clip_source_tab == "pieces"
    assert "finish" in str(state.set_media_drawer_open(False))  # what «Agregar» does
    event = state.close_media_drawer()
    assert not state.media_drawer_open and "media-open-clip" in str(event)


def test_the_notes_also_show_in_one_line_under_the_grid() -> None:
    state = CreativeState()
    state.clip_files_rejected(
        "video", [{"file": {"path": "x.png"}, "errors": [{"code": "file-invalid-type"}]}]
    )
    state.clip_files_rejected(
        "image", [{"file": {"path": "y.mp3"}, "errors": [{"code": "file-invalid-type"}]}]
    )
    assert state.clip_notes_line == (
        "No agregamos 1 archivo: aquí van fotos PNG, JPG o WEBP. "
        "No agregamos 1 archivo: aquí van videos MP4 o MOV."
    )


def test_the_order_comes_first_then_the_reels_text_then_the_references() -> None:
    from . import content_generator as cg

    rendered = str(cg._clip_references_view().render())
    order = [
        rendered.index("Orden del clip"),
        rendered.index("clip_is_reel_replica"),
        rendered.index("Referencias (opcional)"),
        rendered.index("clip_reference_tiles"),
        rendered.index("Elegir fotos, videos o audios"),
    ]
    assert order == sorted(order)
    # m-24985141: the uploads are the media drawer's «Subir», one per kind
    drawer = str(cg._clip_drawer_body().render())
    for upload_id in ("clip_images", "clip_videos", "clip_audios"):
        assert upload_id in drawer
    for label in ('"Subir fotos"', '"Subir videos"', '"Subir audios"'):
        assert label in drawer
    assert "clip_references" not in rendered  # no mixed zone


def test_the_cards_have_no_arrows_and_the_keys_press_hidden_moves() -> None:
    """Round 15 (Deivid: «no las quiero»): nothing to move on screen but the drag; with
    the focus on a card, ←/→ with no modifier press its hidden move buttons."""
    from . import content_generator as cg

    rendered = str(cg._clip_parts_block().render())
    assert "q-part-arrows" not in rendered and "Aparece una persona" not in rendered
    assert "ArrowLeft ArrowRight" in rendered and "data-part-move" in rendered
    js = cg._PART_KEYS_JS
    assert "preventDefault" in js and "altKey" in js and "data-part-move" in js
    assert "pointerdown" not in js


def test_the_arrow_keys_move_a_part_and_keep_the_focus_on_its_card() -> None:
    state = planned()
    second = state.reel_part_rows[1]["key"]
    assert state.move_reel_part_up(second) is not None  # focus back on the card
    assert state.reel_part_rows[0]["key"] == second
    assert state.reel_move_text == "Moviste la parte 2: ahora es la parte 1."
    assert state.move_reel_part_up(second) is None  # first: stays
    stuck = state.reel_part_rows[3]["key"]
    assert state.move_reel_part_down(stuck) is None  # moves with its group only


def test_the_initial_state_has_every_list_the_views_measure() -> None:
    """The lists the step's conds measure are lists from the start, the notes have
    every category, and a row carries every field a card reads."""
    state = CreativeState()
    assert state.clip_reference_tiles == [] and state.clip_notes_line == ""
    assert state.reel_usage_lines == []
    assert state.reel_part_units == [] and state.clip_strip == []
    assert state.clip_notes == {"image": "", "video": "", "audio": ""}
    assert set(state.clip_full_notes) == {"image", "video", "audio"}
    row = planned().reel_part_rows[0]
    for field in (
        "key",
        "index",
        "thumb",
        "label",
        "aria",
        "description",
        "why",
        "describe",
        "remove_label",
        "movable",
        "unit",
    ):
        assert field in row, field


def test_an_audio_tile_is_a_square_that_names_its_file() -> None:
    from . import content_generator as cg

    rendered = str(cg._clip_gallery().render())
    assert "LucideMusic" in rendered and "6.5rem" in rendered
    assert 'title:tile_rx_state_?.["name"]' in rendered.replace(" ", "")
    assert "overflowWrap" in rendered or "overflow_wrap" in rendered
