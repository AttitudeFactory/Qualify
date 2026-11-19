"""ED-02/03 (m-25026621, m-25026623) and D-E6: the Clip editor's state — the switch
`QUALIFY_CLIP_EDITOR` (off = the Clip exactly as before), the stretch the browser's
length proposes, «Cortar», «Girar», «Cámara rápida», the live line that says each change
(no «Deshacer» since Deivid 2026-11-19), and the recipe the brief carries. A standalone
`CreativeState`, handlers called through `.fn` (`test_creative_state.py` explains why)."""

from __future__ import annotations

from uuid import UUID

import pytest

from . import clip_editor_vm, r2_media
from . import creative_state as creative_state_module
from . import editor_preview_contract as editor_contract
from .clip_editor_vm import TOO_SHORT
from .creative_state import CreativeState

_KEY = "uploads/t/clip/video.mp4"
_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_OTHER = UUID("b0000000-0000-4000-8000-000000000002")


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)


def _state() -> CreativeState:
    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    state.clip_videos = [{"key": _KEY, "name": "video.mp4", "source": "upload"}]
    return state


def _measured(seconds: float = 20.0, width: int = 1080, height: int = 1920) -> CreativeState:
    state = _state()
    CreativeState.report_clip_source.fn(state, _KEY, seconds, width, height)
    return state


# -- the switch -----------------------------------------------------------------------------


def test_switch_values_follow_the_house_convention() -> None:
    assert clip_editor_vm.switch_on("1")
    assert clip_editor_vm.switch_on(" ON ")
    assert clip_editor_vm.switch_on("true")
    for value in ("off", "0", "", None, "draft", "yes please"):
        assert not clip_editor_vm.switch_on(value)


def test_switch_off_leaves_the_clip_exactly_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", False)
    state = _measured(20.0)
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert not state.clip_editor_shown
    assert not state.clip_editor_on_screen  # the side panel keeps its «Producto» row
    assert state.create_step_title == "Qué mostrar"
    assert [step["label"] for step in state.gen_view_steps][0] == "Qué mostrar"
    assert state._clip_edit_media() == {}
    assert "edit_recipe" not in state._clip_media()


def test_switch_on_shows_the_editor(editor_on: None) -> None:
    state = _state()
    assert state.clip_editor_shown
    assert state.clip_editor_on_screen
    assert state.create_step_title == "Arma tu video"
    assert [step["label"] for step in state.gen_view_steps][0] == "Arma tu video"
    state.clip_videos = [{"key": "r", "name": "reel", "source": "reel"}]
    assert not state.clip_editor_shown
    state.clip_videos = []
    state.gen_category = "image"
    assert not state.clip_editor_shown


# -- «Cortar» -------------------------------------------------------------------------------


def test_the_measured_length_proposes_the_whole_video_up_to_fifteen_seconds(
    editor_on: None,
) -> None:
    state = _measured(20.0)
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 15.0)
    assert state.clip_cut_ready
    assert state.clip_cut_usage_text == "Usas 15 s de tu video."
    # ED-10: the card «Tu video» is gone — the timeline's block says it
    assert state.clip_tl_media_rows[0]["name"] == "Video 1 de 1, usas de 0:00 a 0:15, dura 15 s"
    assert state.clip_edit_notice == ""  # the owner changed nothing
    CreativeState.report_clip_source.fn(state, "someone-elses-key", 3.0, 0, 0)
    assert state.clip_source_seconds == 20.0


def test_a_length_off_the_grid_keeps_its_end_reachable(editor_on: None) -> None:
    state = _measured(7.33)
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 7.5)  # ceil, never lost
    assert state.clip_cut_check == ["", ""]  # EF-03 cuts 7.5 at 7.33, never refuses it


def test_the_length_is_taken_again_after_a_reset(editor_on: None) -> None:
    state = _measured(20.0)
    state._reset_clip_editor()
    assert not state.clip_cut_ready
    CreativeState.report_clip_source.fn(state, _KEY, 20.0, 1080, 1920)
    assert state.clip_cut_ready


def test_a_handle_trims_and_says_why_it_stops(editor_on: None) -> None:
    """ED-03 (m-25026623): the Radix slider and its ±½ s are gone — a handle trims the
    piece; past the least a piece takes it stops and says why."""
    state = _measured(20.0)
    assert not hasattr(CreativeState, "commit_clip_cut")
    assert not hasattr(CreativeState, "nudge_clip_cut")
    assert not hasattr(CreativeState, "slide_clip_cut")
    # review ED-03: dead code gone — the handles reach the screen through the drop
    for name in ("trim_clip_block", "clip_edit_rate", "clip_edit_slower"):
        assert not hasattr(CreativeState, name)
    for name in ("clip_edit_output_seconds", "clip_cut_focus", "clip_cut_play"):
        assert not hasattr(CreativeState, name)
    CreativeState.drop_clip_block.fn(state, _KEY, "start", 4.0)
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 12.0)
    assert (state.clip_cut_start, state.clip_cut_end) == (4.0, 12.0)
    assert state.clip_cut_range_text == "Desde 0:04 · Hasta 0:12"
    assert state.clip_edit_notice == "Recortaste el video 1."
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 4.5)  # under 1 s: stops at 5
    assert state.clip_cut_error == TOO_SHORT
    assert (state.clip_cut_start, state.clip_cut_end) == (4.0, 5.0)
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 5.5)
    assert state.clip_cut_error == ""
    assert state.clip_cut_end == 5.5
    assert state.clip_edit_notice == "Alargaste el video 1."


def test_a_video_that_cannot_play_stops_waiting(editor_on: None) -> None:
    state = _state()
    assert state._clip_cut_offered()
    CreativeState.report_clip_source.fn(state, _KEY, -1.0, 0, 0)
    assert state.clip_source_broken
    assert not state._clip_cut_offered()
    CreativeState.report_clip_source.fn(state, _KEY, 9.0, 1080, 1920)
    assert not state.clip_source_broken
    assert state._clip_cut_offered()


class _Tokens:
    """A stand-in for `MediaTokenStore`: hands out a fixed token, remembers the asks."""

    def __init__(self) -> None:
        self.asked: list[tuple[UUID, str]] = []

    def issue(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        self.asked.append((tenant_id, object_key))
        return "tok-" + str(len(self.asked))


def _r2_door(monkeypatch: pytest.MonkeyPatch) -> _Tokens:
    """The real `issue_view_path` (its tenant-prefix check included) on a token double,
    and the session's tenant faked (`_clip_preview_tenant` reads `AuthState`)."""
    tokens = _Tokens()

    def issue(tenant_id: UUID, key: str, media_type: str) -> str:
        return r2_media.issue_view_path(tenant_id, key, media_type, store=tokens)

    async def tenant(self: CreativeState) -> UUID:
        return _TENANT

    monkeypatch.setattr(creative_state_module, "issue_view_path", issue)
    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", tenant)
    return tokens


def test_a_publications_local_video_plays_and_has_cut(editor_on: None) -> None:
    state = _state()
    key = f"generated/{_TENANT}/piece/video.mp4"
    state.piece_items = [{"key": key, "view": "/r2media/thumb", "media_type": "video"}]
    state.clip_videos = [{"key": key, "name": "Publicación", "source": "existing"}]
    assert state.clip_edit_video_key == key
    assert state.clip_edit_video_playable and not state.clip_edit_video_r2
    assert not state.clip_edit_remote
    assert state._clip_cut_offered()


async def test_an_r2_video_of_the_business_plays_through_r2media(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = _r2_door(monkeypatch)
    state = _state()
    key = f"gallery/{_TENANT}/m1/video.mp4"
    state.clip_videos = [{"key": key, "name": "Galería", "source": "existing"}]
    assert state.clip_edit_video_r2
    assert not state.clip_edit_video_playable
    assert not state.clip_edit_remote  # still being minted: not said «remote» yet
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked == [(_TENANT, key)]
    assert state.clip_preview_url.startswith("/r2media/tok-")
    assert state.clip_edit_video_playable and not state.clip_edit_remote
    assert state._clip_cut_offered()


async def test_an_r2_key_of_another_business_gets_no_path(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = _r2_door(monkeypatch)
    state = _state()
    key = f"t/{_OTHER}/media/video.mp4"
    state.clip_videos = [{"key": key, "name": "ajeno", "source": "existing"}]
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked == []  # the prefix check refused it before any token
    assert state.clip_preview_url == ""
    assert not state.clip_edit_video_playable
    assert state.clip_edit_remote
    assert not state._clip_cut_offered()


async def test_a_token_that_cannot_be_minted_is_not_playable(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _r2_door(monkeypatch)

    def broken(tenant_id: UUID, key: str, media_type: str) -> str:
        raise ConnectionError("redis down")

    monkeypatch.setattr(creative_state_module, "issue_view_path", broken)
    state = _state()
    state.clip_videos = [{"key": f"gallery/{_TENANT}/m1/v.mp4", "name": "G", "source": "existing"}]
    await CreativeState.resolve_clip_preview.fn(state)
    assert state.clip_edit_remote and not state.clip_edit_video_playable


async def test_with_the_switch_off_no_path_is_minted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", False)
    tokens = _r2_door(monkeypatch)
    state = _state()
    state.clip_videos = [{"key": f"gallery/{_TENANT}/m1/v.mp4", "name": "G", "source": "existing"}]
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked == [] and state.clip_preview_url == ""
    assert not state.clip_editor_shown
    assert state._clip_edit_media() == {}


def test_low_resolution_warns_with_width_and_height(editor_on: None) -> None:
    state = _measured(20.0, 640, 360)
    assert state.clip_cut_check == [
        "",
        "Al ponerlo vertical, tu video se vería borroso. Si puedes, grábalo en vertical.",
    ]
    CreativeState.rotate_clip_video.fn(state)  # 360×640 upright: still narrow, vertical
    assert state.clip_cut_check[1] == (
        "Al ponerlo vertical, tu video se vería borroso. Sube el video original desde tu teléfono."
    )


# -- «Cámara rápida» and the live line ---------------------------------------------------------


def test_fast_motion_proposes_the_whole_video_and_a_five_second_result(editor_on: None) -> None:
    state = _measured(40.0)
    assert state.clip_cut_end == 15.0
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 40.0)  # no 15 s cap
    assert state.clip_speed == 10  # 40 / 10 = 4 s, the closest to 5 s
    assert state.clip_speed_line == "Tu video durará 4 s."
    assert state.clip_fast_warning == ""
    # ×20 would leave 2 s: off, and a tap says why (Deivid 2026-11-17)
    assert state.clip_speed_reasons["20"] == "Con ×20 tu video duraría 2 s."
    CreativeState.set_clip_speed.fn(state, "20")
    assert state.clip_speed == 10
    assert state.clip_speed_note == "Con ×20 tu video duraría 2 s."
    CreativeState.set_clip_speed.fn(state, "5")  # 8 s: on
    assert state.clip_speed == 5 and state.clip_speed_note == ""


def test_there_is_no_deshacer_and_each_change_says_its_line(editor_on: None) -> None:
    """Deivid 2026-11-19 («quitemos el botón de deshacer»): no «Deshacer» — its stack and
    its event are gone; the live line still says each change."""
    assert not hasattr(CreativeState, "undo_clip_edit")
    assert not hasattr(clip_editor_vm, "push_undo") and not hasattr(clip_editor_vm, "UNDO")
    state = _measured(20.0)
    assert not hasattr(state, "_clip_edit_undo")
    CreativeState.rotate_clip_video.fn(state)
    assert state.clip_rotate == 90
    assert state.clip_edit_notice == "Giraste tu video."
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert state.clip_speed == 5  # 20 / 5 = 4 s
    CreativeState.set_clip_speed.fn(state, "3")
    assert state.clip_speed == 3


def test_the_live_line_has_no_timer_and_ends_with_the_step(editor_on: None) -> None:
    state = _measured()
    CreativeState.rotate_clip_video.fn(state)
    assert state.clip_edit_notice == "Giraste tu video."
    assert not hasattr(CreativeState, "expire_clip_edit_notice")
    CreativeState.next_view.fn(state)
    assert state.clip_edit_notice == ""


def test_text_is_kept_when_the_field_is_left(editor_on: None) -> None:
    state = _measured()
    CreativeState.set_clip_overlay_text.fn(state, "2×1 hoy")
    assert state.clip_edit_text_shown == "2×1 hoy"
    assert state.clip_edit_notice == ""  # typing is not a change yet
    CreativeState.commit_clip_overlay_text.fn(state, "")
    assert state.clip_edit_notice == "Cambiaste el texto de tu video."
    # the place while typing a new text: the line names the place
    CreativeState.set_clip_overlay_text.fn(state, "2×1 mañana")
    CreativeState.set_clip_text_place.fn(state, "top")
    assert state.clip_edit_notice == "Cambiaste el lugar del texto."
    assert (state.clip_text_place, state.clip_overlay_text) == ("top", "2×1 mañana")


def test_effects_offer_only_what_exists(editor_on: None) -> None:
    # EF-08 (m-25029102): the smoke, ember and steam loops exist in assets/effects/
    state = _measured()
    assert [row["id"] for row in state.clip_edit_effect_rows] == [
        "vapor_capa",
        "humo_capa",
        "brasas_capa",
        "camara_rapida",
    ]
    CreativeState.toggle_clip_effect.fn(state, "humo_capa")
    assert state.clip_effect_ids == ["humo_capa"]
    assert state.clip_edit_effect_srcs == ["/effects/humo_capa/v1/preview.webm"]


def test_photos_only_has_no_cut_nor_fast_motion(editor_on: None) -> None:
    state = _state()
    state.clip_videos = []
    assert not state._clip_cut_offered()
    # the layers need no own video (EF-08: their loops exist); fast motion does
    assert [row["id"] for row in state.clip_edit_effect_rows] == [
        "vapor_capa",
        "humo_capa",
        "brasas_capa",
    ]
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert state.clip_effect_ids == []


def test_the_brief_carries_the_recipe(editor_on: None) -> None:
    state = _measured(20.0)
    state.clip_cut_start, state.clip_cut_end = 4.0, 12.0
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    recipe = state._clip_edit_media()
    # B6 (m-25048789): EF-06's `local` Clip, in `MediaInputs`' own fields
    assert recipe["clip_reference_mode"] == "local"
    assert recipe["segments"] == [
        {"key": _KEY, "start_s": 0.0, "end_s": 20.0, "speed": 5.0, "rotate": 0}
    ]
    # the speed travels in the stretch only: `camara_rapida` is never an effect
    assert recipe["effects"] == [] and recipe["text_layers"] == []
    # silent and without the AI's subtitles; nothing goes as `edit_recipe` any more
    assert (recipe["clip_audio"], recipe["clip_subtitles"]) == (False, False)
    media = state._clip_media()
    assert {key: media[key] for key in recipe} == recipe
    assert "edit_recipe" not in media and "text_layer" not in media
    state.clip_videos = [{"key": "r", "name": "reel", "source": "reel"}]
    assert state._clip_edit_media() == {}


def test_fast_motion_says_so_and_unmarking_restores_the_stretch(editor_on: None) -> None:
    state = _measured(200.0)
    state.clip_cut_start, state.clip_cut_end = 4.0, 12.0
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    # it had its own cut (4–12 s): the line says it comes back; a 200 s video gives its
    # first minute only (A9: a stretch takes at most a minute of its video)
    assert state.clip_edit_notice == (
        "Pusiste tu video ×10: usamos su primer minuto. "
        "Si vuelves a la velocidad normal, recuperas tu pedazo."
    )
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 60.0)
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert state.clip_edit_notice == "Volviste tu video a la velocidad normal."
    assert (state.clip_cut_start, state.clip_cut_end) == (4.0, 12.0)
    assert state.clip_edit_speed_real == 1.0


def test_unmarking_without_a_kept_stretch_trims_to_fifteen_seconds(editor_on: None) -> None:
    state = _measured(200.0)
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    state._clip_fast_before = {}  # e.g. a stretch from a session before this change
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 15.0)


def test_the_history_does_not_bring_the_line_back(editor_on: None) -> None:
    state = _measured()
    CreativeState.rotate_clip_video.fn(state)
    assert state.clip_edit_notice != ""
    step = state.create_step_n
    CreativeState.reconcile_reel_editor_route.fn(state, f"?paso={step}")
    assert state.clip_edit_notice != ""  # the same step (only `?bloque=` moved): it stays
    CreativeState.reconcile_reel_editor_route.fn(state, f"?paso={step + 1}")
    assert state.clip_edit_notice == ""  # another step through the history: gone
    CreativeState.rotate_clip_video.fn(state)
    CreativeState.reconcile_reel_editor_route.fn(state, f"?paso={state.create_step_n}&parte=1")
    assert state.clip_edit_notice == ""  # a part sheet: gone too


def test_media_inputs_read_the_recipe_and_still_read_an_old_edit_recipe(
    editor_on: None,
) -> None:
    """B6 (m-25048789): qualify_creative's real `MediaInputs` reads the editor's video as
    EF-06's `local` Clip — and a media stored before B6 with `edit_recipe` still reads
    WITHOUT an error (extra keys are ignored: it is dropped)."""
    from qualify_creative.schemas import MediaInputs

    state = _measured(20.0)
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    CreativeState.set_clip_overlay_text.fn(state, "2×1 hoy")
    CreativeState.commit_clip_overlay_text.fn(state, "")
    media = state._clip_media()
    inputs = MediaInputs.model_validate(media)
    assert inputs.clip_reference_mode == "local"
    assert [(s.key, s.speed) for s in inputs.segments] == [(_KEY, 5.0)]
    assert [layer.text for layer in inputs.text_layers] == ["2×1 hoy"]
    old = {**media, "edit_recipe": {"effects": [], "text_layer": None, "segments": []}}
    assert "edit_recipe" not in MediaInputs.model_validate(old).model_dump()


def test_fast_motion_on_a_long_video_takes_its_first_minute(editor_on: None) -> None:
    """ED-03 with A9 (m-25042483): a stretch takes at most a minute of its video, so
    cámara rápida of a 1300 s video takes its first minute (×10 = 6 s), never all of it
    — the backend would refuse it as `segment_source_too_long`."""
    state = _measured(1300.0)
    row = next(r for r in state.clip_edit_effect_rows if r["id"] == "camara_rapida")
    assert row["off"] == ""
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert (state.clip_cut_start, state.clip_cut_end, state.clip_speed) == (0.0, 60.0, 10)
    assert state.clip_edit_notice == "Pusiste tu video ×10: usamos su primer minuto."
    assert state._clip_edit_problem() == ("", "")


def test_inspiration_stock_stays_a_reference(editor_on: None) -> None:
    """Deivid 2026-11-14: Inspiración stock is a reference for the AI only — the editor
    never cuts it and it never becomes a stretch of the recipe."""
    state = _state()
    stock = {"key": f"t/{_TENANT}/stock/v.mp4", "name": "Inspiración", "source": "stock"}
    state.clip_videos = [stock]
    assert not state._clip_cut_offered()
    assert state._clip_edit_media() == {} or not state._clip_edit_media().get("segments")
    state.clip_videos = [stock, {"key": _KEY, "name": "video.mp4", "source": "upload"}]
    CreativeState.report_clip_source.fn(state, _KEY, 20.0, 1080, 1920)
    segments = state._clip_edit_media()["segments"]
    assert [segment["key"] for segment in segments] == [_KEY]  # type: ignore[index]
    # B6: an Inspiración video would not come out — «Crear» says so and does not go on
    assert state.clip_edit_problem == [clip_editor_vm.NOT_IN_VIDEO, "warn"]
    assert state._clip_problem() == clip_editor_vm.NOT_IN_VIDEO


async def test_a_video_picked_from_publicaciones_is_the_own_video(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA 2026-11-14: a video chosen in the drawer's «Publicaciones» is the video the
    editor plays and cuts (source «pieces»), in R2 or in the upload store."""
    tokens = _r2_door(monkeypatch)
    state = _state()
    state.clip_videos = []
    r2_key = f"t/{_TENANT}/drafts/d1/video.mp4"
    local_key = f"generated/{_TENANT}/d2/video.mp4"
    state.piece_items = [
        {"key": r2_key, "media_type": "video", "label": "Costra", "view": ""},
        {"key": local_key, "media_type": "video", "label": "Otra", "view": ""},
    ]
    CreativeState.pick_media.fn(state, "clip_videos", "pieces", r2_key)
    assert state.clip_videos == [{"key": r2_key, "name": "Costra", "source": "pieces"}]
    assert state.clip_edit_video_key == r2_key
    assert state.clip_edit_r2_pending  # the preview asks for its address
    assert not state.clip_edit_remote
    await CreativeState.resolve_clip_preview.fn(state)
    assert tokens.asked == [(_TENANT, r2_key)]
    assert not state.clip_edit_r2_pending
    assert state.clip_edit_video_playable and state._clip_cut_offered()
    # a publication's video kept in the upload store plays at once, no token
    CreativeState.pick_media.fn(state, "clip_videos", "pieces", r2_key)  # takes it out
    CreativeState.pick_media.fn(state, "clip_videos", "pieces", local_key)
    assert state.clip_edit_video_key == local_key
    assert not state.clip_edit_r2_pending
    assert state.clip_edit_video_playable and state._clip_cut_offered()


def test_no_low_resolution_advice_for_a_video_qualify_made(editor_on: None) -> None:
    """QA 2026-11-14: a publication (720p, made by Qualify) never came from the phone."""
    state = _state()
    key = f"generated/{_TENANT}/d1/video.mp4"
    state.clip_videos = [{"key": key, "name": "Publicación", "source": "pieces"}]
    CreativeState.report_clip_source.fn(state, key, 12.04, 1280, 720)
    assert state.clip_cut_check == ["", ""]
    # the same file uploaded by the owner keeps the advice
    state.clip_videos = [{"key": key, "name": "video.mp4", "source": "upload"}]
    assert state.clip_cut_check[1].startswith("Al ponerlo vertical, tu video se vería")


def test_what_the_owner_reads_ends_with_the_video(editor_on: None) -> None:
    """QA 2026-11-14: a 12.04 s video — the slider's end is 12.5 (the grid, rounded up),
    but the card, «Usas», «Hasta» and the preview say 12.04, never past the video."""
    state = _measured(12.04)
    assert state.clip_cut_end == 12.5
    assert state.clip_cut_end_shown == 12.04
    assert state.clip_tl_media_rows[0]["label"] == "Video 1"
    assert state.clip_tl_total == "12"
    assert state.clip_cut_usage_text == "Usas 12 s de tu video."
    assert state.clip_cut_range_text == "Desde 0:00 · Hasta 0:12"
    recipe = state._clip_edit_media()
    assert recipe["segments"][0]["end_s"] == 12.04  # type: ignore[index]


def test_the_heading_and_usas_round_the_same_stretch_alike(editor_on: None) -> None:
    """Deivid, 2026-11-16: the chosen video's heading said «6,5 s» and «Usas» «6,6 s»
    for the same stretch — both now round with the timeline's ½ s."""
    state = _measured(6.6)
    CreativeState.select_clip_block.fn(state, state.clip_tl_media_rows[0]["id"])
    heading = state.clip_tl_chosen["panel"]
    assert heading.endswith("· 6,5 s"), heading
    assert state.clip_cut_usage_text == "Usas 6,5 s de tu video."


async def test_a_failing_session_never_leaves_the_preview_pending(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _r2_door(monkeypatch)

    async def no_session(self: CreativeState) -> UUID:
        raise LookupError("no session")

    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", no_session)
    state = _state()
    key = f"gallery/{_TENANT}/m1/video.mp4"
    state.clip_videos = [{"key": key, "name": "Galería", "source": "existing"}]
    await CreativeState.resolve_clip_preview.fn(state)
    assert not state.clip_edit_r2_pending
    assert state.clip_edit_remote  # said plainly, not waiting forever


async def test_a_dead_r2_path_is_renewed_once_then_breaks(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens = _r2_door(monkeypatch)
    state = _state()
    key = f"gallery/{_TENANT}/m1/video.mp4"
    state.clip_videos = [{"key": key, "name": "Galería", "source": "existing"}]
    await CreativeState.resolve_clip_preview.fn(state)
    first = state.clip_preview_url
    # an hour later (a reload kept the state): the browser cannot play the old path
    monkeypatch.setattr(r2_media, "_issued", {})  # its token is past reuse
    CreativeState.report_clip_source.fn(state, key, -1.0, 0, 0)
    assert state.clip_edit_r2_pending and not state.clip_source_broken
    await CreativeState.resolve_clip_preview.fn(state)
    assert state.clip_preview_url != first and len(tokens.asked) == 2
    assert state.clip_edit_video_playable
    # the new path fails too: now it is broken, no endless renewals
    CreativeState.report_clip_source.fn(state, key, -1.0, 0, 0)
    assert state.clip_source_broken and not state.clip_edit_r2_pending
    assert not state._clip_cut_offered()


async def test_a_renewal_that_gives_the_same_path_breaks(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _r2_door(monkeypatch)
    state = _state()
    key = f"gallery/{_TENANT}/m1/video.mp4"
    state.clip_videos = [{"key": key, "name": "Galería", "source": "existing"}]
    await CreativeState.resolve_clip_preview.fn(state)
    CreativeState.report_clip_source.fn(state, key, -1.0, 0, 0)  # the token was alive
    await CreativeState.resolve_clip_preview.fn(state)  # same path back: the file fails
    assert state.clip_source_broken


async def test_a_same_path_renewal_breaks_without_cut(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """review-agent: token issued → the browser reports -1 → the renewal gives the SAME
    path back → broken like the browser's own report: no «Cortar», no endless wait."""
    _r2_door(monkeypatch)
    state = _state()
    key = f"gallery/{_TENANT}/m1/video.mp4"
    state.clip_videos = [{"key": key, "name": "Galería", "source": "existing"}]
    await CreativeState.resolve_clip_preview.fn(state)
    CreativeState.report_clip_source.fn(state, key, -1.0, 0, 0)
    await CreativeState.resolve_clip_preview.fn(state)
    assert state.clip_source_broken
    assert (state.clip_source_key, state.clip_source_seconds) == (key, 0.0)
    assert not state._clip_cut_offered()
    assert not state.clip_cut_ready


def test_fast_motion_is_off_on_a_video_under_six_seconds(editor_on: None) -> None:
    state = _measured(4.0)
    row = next(r for r in state.clip_edit_effect_rows if r["id"] == "camara_rapida")
    assert row["off"] == "true"
    assert row["reason"] == "Para hacerlo más rápido, tu video tiene que durar al menos 6 s."
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert state.clip_effect_ids == []
    # «Velocidad» still shows: every speed off, with that line under it
    assert state.clip_tl_speed_offered
    assert state.clip_speed_note == clip_editor_vm.FAST_NEEDS_LONGER
    CreativeState.set_clip_block_speed.fn(state, _KEY, "2")
    assert state.clip_effect_ids == []
    state = _measured(6.0)
    row = next(r for r in state.clip_edit_effect_rows if r["id"] == "camara_rapida")
    assert row["off"] == "" and row["reason"] == ""
    assert state.clip_speed_note == ""


def test_each_speed_is_on_only_for_a_three_to_sixty_second_result(editor_on: None) -> None:
    """Deivid 2026-11-17: ×2 and ×3 join; each is on only when the whole video at it
    lasts 3–60 s, and a tap on an off one says why."""
    six = _measured(6.0)
    assert [v for v in ("2", "3", "5", "10", "20") if not six.clip_speed_reasons[v]] == ["2"]
    eight = _measured(8.0)
    assert eight.clip_speed_reasons["2"] == ""
    assert eight.clip_speed_reasons["3"] == "Con ×3 tu video duraría 2,7 s."
    CreativeState.set_clip_block_speed.fn(eight, _KEY, "3")
    assert eight.clip_effect_ids == []
    assert eight.clip_speed_note == "Con ×3 tu video duraría 2,7 s."
    CreativeState.set_clip_block_speed.fn(eight, _KEY, "2")
    assert eight.clip_effect_ids == ["camara_rapida"] and eight.clip_speed == 2
    assert eight.clip_speed_note == ""
    # ED-03 with A9: sped up, a 130 s video takes its first minute (×2 = 30 s)
    long = _measured(130.0)
    assert long.clip_speed_reasons["2"] == "" and long.clip_speed_reasons["20"] == ""
    CreativeState.toggle_clip_effect.fn(long, "camara_rapida")
    assert (long.clip_cut_end, long.clip_speed) == (60.0, 10)  # 6 s: the closest to 5 s
    assert long.clip_speed_reasons["2"] == ""  # 30 s
    # ×10 is past what the browser plays: the preview says it looks slower
    assert long._clip_sequence().slower == editor_contract.preview_is_slower(10)


def test_fast_motion_that_cannot_reach_three_seconds_stays_out_of_the_recipe(
    editor_on: None,
) -> None:
    """Even the whole video at ×2 under 3 s (a marked fast motion on a video whose real
    length came in shorter): the line says so and `camara_rapida` leaves the recipe."""
    state = _measured(20.0)
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    CreativeState.report_clip_source.fn(state, _KEY, 5.0, 1080, 1920)  # measured again
    assert state.clip_fast_warning == (
        "Tu video duraría 2,5 s: muy poco para un reel. Vuelve a la velocidad normal o usa "
        "un video más largo."
    )
    recipe = state._clip_edit_media()
    assert [e["effect_id"] for e in recipe["effects"]] == []  # type: ignore[index]
    # B6: the timeline still plays it at the chosen speed (here 1 s), so «Crear» does not
    # go on (option A) — the recipe is what the preview shows, never a silent speed 1
    assert state._clip_problem() == (
        "Tu video dura 1 s y necesita al menos 3 s. Agrega otra foto o video, o baja la velocidad."
    )


def test_marking_fast_motion_says_what_it_did(editor_on: None) -> None:
    state = _measured(40.0)  # the whole proposal: 0–15, no cut of the owner's
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert state.clip_edit_notice == "Pusiste tu video ×10: usamos todo tu video."


def test_the_order_notes_a_second_video_only_on_the_editor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    other = "uploads/t/clip/second.mp4"
    state.clip_videos = [
        {"key": _KEY, "name": "video.mp4", "source": "upload"},
        {"key": other, "name": "second.mp4", "source": "upload"},
    ]
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", False)
    assert state.clip_strip_motion_keys == []
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)
    state.clip_videos = [*state.clip_videos]  # recompute with the switch on
    assert state.clip_strip_motion_keys == [other]


# -- ED-10 m-25026648: the timeline -------------------------------------------------------

_PHOTO = "uploads/t/clip/foto.jpg"
_SECOND = "uploads/t/clip/otro.mp4"


def _timeline_state() -> CreativeState:
    """A photo, the own video (20 s, measured) and a second video (8 s, measured)."""
    state = _measured(20.0)
    state.clip_images = [{"key": _PHOTO, "name": "foto.jpg", "source": "upload", "role": "product"}]
    state.clip_videos = [
        {"key": _KEY, "name": "video.mp4", "source": "upload"},
        {"key": _SECOND, "name": "otro.mp4", "source": "upload"},
    ]
    state.clip_sequence = [_PHOTO, _KEY, _SECOND]
    CreativeState.report_clip_media.fn(state, _SECOND, 8.0, 1080, 1920)
    return state


def _scripts(events: object) -> str:
    return str(events)


def test_on_entering_everything_is_in_its_order(editor_on: None) -> None:
    state = _timeline_state()
    rows = state.clip_tl_media_rows
    assert [r["id"] for r in rows] == [_PHOTO, _KEY, _SECOND]
    assert [r["name"] for r in rows] == [
        "Foto 1 de 3, se ve 2 s",
        "Video 2 de 3, usas de 0:00 a 0:15, dura 15 s",
        "Video 3 de 3, usas de 0:00 a 0:08, dura 8 s",
    ]
    assert state.clip_tl_total == "25"
    # ED-03: the own video has its trim handles; a photo and another video none yet
    assert [r["handles"] for r in rows] == ["", "1", ""]
    assert [r["own"] for r in rows] == ["", "1", ""]
    assert state.clip_tl_text_rows == [] and state.clip_tl_effect_rows == []
    # the preview in sequence plays the same blocks, from the browser's backend
    sequence = state.clip_seq_json
    assert f"{clip_editor_vm.SEQ_BASE}/_upload/{_KEY}" in sequence
    assert f"{clip_editor_vm.SEQ_BASE}/_upload/{_PHOTO}" in sequence
    assert '"total":25' in sequence


def test_siguiente_untouched_leaves_ed02s_recipe(editor_on: None) -> None:
    """Criterion 5: «Siguiente» without touching anything = ED-02's recipe (its default
    values), through `recipe_of`."""
    from . import editor_preview_contract as contract

    state = _timeline_state()
    CreativeState.set_clip_overlay_text.fn(state, "2×1 hoy")
    CreativeState.commit_clip_overlay_text.fn(state, "")
    expected = clip_editor_vm.recipe_of(
        video_key=_KEY,
        start=0.0,
        end=15.0,
        rotate=0,
        effects=[],
        speed=state.clip_speed,
        text="2×1 hoy",
        place="bottom",
        timeline=state._clip_tl_media(),
    )
    data = contract.to_dict(expected)
    media = state._clip_edit_media()
    assert (media["segments"], media["text_layers"]) == (data["segments"], data["text_layers"])
    # B6: every block of the timeline, in its order — the photo held 2 s, the own video
    # 0–15 s, the second video 0–8 s — and the text from 0 to the end (ED-02's)
    shown = [(s["key"], s["start_s"], s["end_s"], s.get("kind")) for s in data["segments"]]
    assert shown == [
        (_PHOTO, 0.0, 2.0, "photo"),
        (_KEY, 0.0, 15.0, None),
        (_SECOND, 0.0, 8.0, None),
    ]
    assert (data["text_layers"][0]["start_s"], data["text_layers"][0]["end_s"]) == (0.0, None)


def test_choosing_a_block_writes_the_address_and_back_lets_it_go(editor_on: None) -> None:
    state = _timeline_state()
    events = CreativeState.select_clip_block.fn(state, _KEY)
    assert state.clip_edit_block == _KEY and state.clip_tl_selected == _KEY
    text = _scripts(events)
    assert "bloque" in text and "video-2" in text and "pushState" in text
    assert "reveal" in text  # its panel comes into view
    assert state.clip_tl_chosen_kind == "video" and state.clip_tl_chosen_label == "Video 2"
    # another block replaces the entry; the same block again lets it go
    assert "replaceState" in _scripts(CreativeState.select_clip_block.fn(state, _PHOTO))
    CreativeState.select_clip_block.fn(state, _PHOTO)
    assert state.clip_edit_block == ""
    # the phone's «atrás» (popstate onto `?paso=1`) lets the chosen block go, same step
    CreativeState.select_clip_block.fn(state, _KEY)
    step = state.create_step_n
    CreativeState.reconcile_reel_editor_route.fn(state, "?paso=1")
    assert state.clip_edit_block == "" and state.create_step_n == step
    # unknown ids choose nothing
    assert CreativeState.select_clip_block.fn(state, "nope") == []


def test_reloading_the_address_shows_the_same_block(editor_on: None) -> None:
    state = _timeline_state()
    events = CreativeState.reconcile_reel_editor_route.fn(state, "?paso=1&bloque=video-3")
    assert state.clip_edit_block == _SECOND
    assert "reveal" in _scripts(events)
    CreativeState.reconcile_reel_editor_route.fn(state, "?paso=1&bloque=foto-1")
    assert state.clip_edit_block == _PHOTO
    CreativeState.reconcile_reel_editor_route.fn(state, "?paso=1&bloque=video-9")
    assert state.clip_edit_block == ""


def test_listo_and_escape_let_the_block_go(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.select_clip_block.fn(state, _KEY)
    events = CreativeState.done_clip_block.fn(state)
    assert state.clip_edit_block == "" and "history.back" in _scripts(events)
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.clip_block_key.fn(state, _KEY, "", "Escape")
    assert state.clip_edit_block == ""


def test_dragging_a_block_reorders_the_clip(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.drop_clip_block.fn(state, _PHOTO, "move", 2.0)
    assert [r["id"] for r in state.clip_tl_media_rows] == [_KEY, _SECOND, _PHOTO]
    assert state.clip_sequence == [_KEY, _SECOND, _PHOTO]
    assert state.clip_edit_notice == "Moviste la foto 3."
    # the AI's opening and closing frames follow the order, as the strip did
    assert (state.clip_first_frame_key, state.clip_last_frame_key) == (_KEY, _PHOTO)
    # B6: the recipe follows the timeline's order, as the preview plays it
    keys = [s["key"] for s in state._clip_edit_media()["segments"]]  # type: ignore[union-attr]
    assert keys == [_KEY, _SECOND, _PHOTO]


def test_the_keyboard_moves_a_block_one_place(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.clip_block_key.fn(state, _SECOND, "", "ArrowLeft")
    assert [r["id"] for r in state.clip_tl_media_rows] == [_PHOTO, _SECOND, _KEY]
    assert state.clip_edit_notice == "Moviste el video 2."
    CreativeState.clip_block_key.fn(state, _PHOTO, "", "ArrowLeft")  # already first
    assert [r["id"] for r in state.clip_tl_media_rows] == [_PHOTO, _SECOND, _KEY]


def test_a_text_slides_in_time_and_the_recipe_carries_it(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.set_clip_overlay_text.fn(state, "2×1 hoy")
    CreativeState.commit_clip_overlay_text.fn(state, "")
    text = state.clip_tl_text_rows[0]
    assert (text["start"], text["length"]) == ("0", "25")
    # a text covering the whole video cannot move; shorten it first (±½ s on its end)
    for _ in range(10):
        CreativeState.nudge_clip_block.fn(state, "texto-1", "end", -0.5)
    assert state.clip_tl_text_rows[0]["length"] == "20"
    CreativeState.drop_clip_block.fn(state, "texto-1", "time", 3.3)
    text = state.clip_tl_text_rows[0]
    assert (text["start"], text["length"]) == ("3.5", "20")
    assert state.clip_edit_notice == "Cambiaste cuándo sale el texto."
    layer = state._clip_edit_media()["text_layers"][0]  # type: ignore[index]
    assert (layer["start_s"], layer["end_s"]) == (3.5, 23.5)
    CreativeState.clip_block_key.fn(state, "texto-1", "", "ArrowRight")
    assert state.clip_tl_text_rows[0]["start"] == "4"
    # «Quitar» takes it away, and the line says so
    CreativeState.select_clip_block.fn(state, "texto-1")
    CreativeState.clip_block_action.fn(state, "Quitar")
    assert state.clip_tl_text_rows == []
    assert state.clip_edit_notice == "Quitaste el texto de tu video."


def test_quitar_keeps_its_line_after_the_address_walks_back(editor_on: None) -> None:
    """Review of ED-10: «Quitar» lets the block go with `history.back()`; the popstate
    reaches `reconcile_reel_editor_route` with the same step and no `?bloque=` — the
    line stays."""
    state = _timeline_state()
    CreativeState.set_clip_overlay_text.fn(state, "2×1 hoy")
    CreativeState.commit_clip_overlay_text.fn(state, "")
    CreativeState.select_clip_block.fn(state, "texto-1")
    step = state.create_step_n
    CreativeState.reconcile_reel_editor_route.fn(state, f"?paso={step}&bloque=texto-1")
    CreativeState.clip_block_action.fn(state, "Quitar")
    assert state.clip_edit_notice == "Quitaste el texto de tu video."
    CreativeState.reconcile_reel_editor_route.fn(state, f"?paso={step}")
    assert state.clip_edit_notice == "Quitaste el texto de tu video."
    assert state.create_step_n == step
    assert state.clip_tl_text_rows == []


def test_listo_after_editing_a_text_keeps_its_line(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.set_clip_overlay_text.fn(state, "2×1 hoy")
    CreativeState.commit_clip_overlay_text.fn(state, "")
    CreativeState.select_clip_block.fn(state, "texto-1")
    CreativeState.clip_block_key.fn(state, "texto-1", "", "ArrowRight")
    notice = state.clip_edit_notice
    assert notice != ""
    step = state.create_step_n
    events = CreativeState.done_clip_block.fn(state)
    assert "history.back" in _scripts(events)
    CreativeState.reconcile_reel_editor_route.fn(state, f"?paso={step}")
    assert state.clip_edit_notice == notice
    assert state.clip_edit_block == ""


def test_listo_and_quitar_put_the_focus_where_the_owner_goes_on(editor_on: None) -> None:
    """ED-10 UX review: «Listo» gives the focus back to the block (as Escape does);
    «Quitar» to the block now in its place in the track, else to «+»."""
    state = _timeline_state()
    CreativeState.select_clip_block.fn(state, _KEY)
    listo = _scripts(CreativeState.done_clip_block.fn(state))
    assert f'focusAfter("{_KEY}")' in listo
    # «Quitar» on the photo (first of «Fotos y videos»): the own video takes its place
    CreativeState.select_clip_block.fn(state, _PHOTO)
    removed = _scripts(CreativeState.clip_block_action.fn(state, "Quitar"))
    assert f'focusAfter("{_KEY}")' in removed
    # «Quitar» on the only text: no block after it in «Textos» — «+»
    CreativeState.set_clip_overlay_text.fn(state, "2×1 hoy")
    CreativeState.commit_clip_overlay_text.fn(state, "")
    CreativeState.select_clip_block.fn(state, "texto-1")
    removed = _scripts(CreativeState.clip_block_action.fn(state, "Quitar"))
    assert 'focusAfter("")' in removed


def test_the_timeline_script_offers_focus_after() -> None:
    from pathlib import Path

    script = (Path(__file__).resolve().parent.parent / "assets" / "timeline.js").read_text(
        encoding="utf-8"
    )
    body = script[script.index("function focusAfter(id, tries)") :]
    assert ".q-tl-add [data-orbit-trigger]" in body  # «+» when nothing follows
    assert "focusAfter: focusAfter" in script


def test_the_own_video_has_no_desde_hasta_and_its_handles_take_the_arrows(
    editor_on: None,
) -> None:
    """Deivid 2026-11-17: no «Desde/Hasta ±½ s» in the panel. ED-03: ←/→ on a trim handle
    moves that edge ½ s of the video (with its line); a photo has none."""
    state = _timeline_state()
    CreativeState.select_clip_block.fn(state, _KEY)
    assert CreativeState.nudge_clip_block.fn(state, _KEY, "start", 0.5) is None
    CreativeState.clip_block_key.fn(state, _KEY, "end", "ArrowLeft")
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 14.5)
    assert state.clip_edit_notice == "Recortaste el video 2."
    CreativeState.clip_block_key.fn(state, _KEY, "start", "ArrowRight")
    assert (state.clip_cut_start, state.clip_cut_end) == (0.5, 14.5)
    assert CreativeState.nudge_clip_block.fn(state, _PHOTO, "end", 0.5) is None


# -- «Cortar» where the marker is (Deivid 2026-11-17) -------------------------------------


def test_cortar_in_the_middle_splits_the_video_in_two_blocks(editor_on: None) -> None:
    from . import editor_preview_contract as contract

    state = _timeline_state()  # photo 0–2 s, own video 2–17 s (0:00–0:15), second video
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.hear_clip_time.fn(state, 7.0, "pause")  # 5 s into the own video
    assert state.clip_cut_here_reason == ""
    events = CreativeState.cut_clip_video.fn(state)
    assert "bloque" in _scripts(events)
    second = clip_editor_vm.piece_id(_KEY, 1)
    rows = state.clip_tl_media_rows
    assert [r["id"] for r in rows] == [_PHOTO, _KEY, second, _SECOND]
    assert rows[1]["name"] == "Video 2 de 4, usas de 0:00 a 0:05, dura 5 s"
    assert rows[2]["name"] == "Video 3 de 4, usas de 0:05 a 0:15, dura 10 s"
    assert state.clip_tl_total == "25"  # nothing lost: two blocks, the same seconds
    assert state.clip_edit_notice == "Cortaste el video 2 en dos."
    # the marker rests where the halves meet: the piece that starts there is chosen
    assert state.clip_edit_block == second
    # the recipe: two stretches of the same video, in order (contract v2's segments)
    segments = state._clip_edit_media()["segments"]
    assert [(s["key"], s["start_s"], s["end_s"]) for s in segments] == [  # type: ignore[union-attr]
        (_PHOTO, 0.0, 2.0),
        (_KEY, 0.0, 5.0),
        (_KEY, 5.0, 15.0),
        (_SECOND, 0.0, 8.0),
    ]
    recipe = contract.from_dict(state._clip_edit_media())
    assert contract.recipe_problems(recipe) == []
    assert all(contract.segment_problems(seg, 20.0) == [] for seg in recipe.segments)
    # the second half (already chosen) goes away with «Quitar»: the video uses 0:00–0:05
    CreativeState.clip_block_action.fn(state, "Quitar")
    assert [r["id"] for r in state.clip_tl_media_rows] == [_PHOTO, _KEY, _SECOND]
    assert (state.clip_cut_start, state.clip_cut_end, state.clip_cut_pieces) == (0.0, 5.0, [])
    assert state.clip_edit_notice == "Quitaste el video 3."
    assert state.clip_videos[0]["key"] == _KEY  # the file itself stays


def test_cortar_respects_the_speed_and_copies_it_to_both_halves(editor_on: None) -> None:
    state = _measured(20.0)
    CreativeState.set_clip_block_speed.fn(state, _KEY, "5")  # the whole 20 s at ×5 = 4 s
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 20.0)
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.hear_clip_time.fn(state, 1.0, "seek")  # 1 s of the video = 5 s of source
    CreativeState.cut_clip_video.fn(state)
    assert state.clip_cut_pieces == [[0.0, 5.0, 5.0], [5.0, 20.0, 5.0]]
    segments = state._clip_edit_media()["segments"]
    assert [s["speed"] for s in segments] == [5.0, 5.0]  # type: ignore[index]


def test_cortar_is_off_at_an_edge_or_off_the_video(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.hear_clip_time.fn(state, 2.3, "pause")  # 0.3 s into the video
    assert state.clip_cut_here_reason == clip_editor_vm.CUT_TOO_CLOSE
    CreativeState.hear_clip_time.fn(state, 16.8, "pause")  # 0.2 s before its end
    assert state.clip_cut_here_reason == clip_editor_vm.CUT_TOO_CLOSE
    CreativeState.hear_clip_time.fn(state, 1.0, "pause")  # on the photo
    assert state.clip_cut_here_reason == clip_editor_vm.CUT_NOT_HERE
    assert CreativeState.cut_clip_video.fn(state) == []
    assert state.clip_cut_pieces == [] and state.clip_edit_notice == ""
    assert len(state.clip_tl_media_rows) == 3


def test_cortar_works_again_after_a_cut(editor_on: None) -> None:
    """Deivid 2026-11-17: «porque el cortar se desactiva cuando corto una vez?». Two cuts
    in a row at different points, the second piece cut too, each said by the live line."""
    state = _timeline_state()  # photo 0–2 s, own video 2–17 s (0:00–0:15), second video
    second = clip_editor_vm.piece_id(_KEY, 1)
    third = clip_editor_vm.piece_id(_KEY, 2)
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.hear_clip_time.fn(state, 5.0, "pause")  # 3 s into the own video
    CreativeState.cut_clip_video.fn(state)
    assert state.clip_cut_pieces == [[0.0, 3.0, 1.0], [3.0, 15.0, 1.0]]
    # right on the new line: off, saying why — not a dead button
    assert state.clip_edit_block == second
    assert state.clip_cut_here_reason == clip_editor_vm.CUT_TOO_CLOSE
    # the marker moves into the second piece: «Cortar» is back and cuts that piece
    CreativeState.hear_clip_time.fn(state, 11.0, "pause")  # 6 s into the second piece
    assert state.clip_cut_here_reason == ""
    CreativeState.cut_clip_video.fn(state)
    assert state.clip_cut_pieces == [[0.0, 3.0, 1.0], [3.0, 9.0, 1.0], [9.0, 15.0, 1.0]]
    assert state.clip_edit_block == third
    assert [r["id"] for r in state.clip_tl_media_rows] == [_PHOTO, _KEY, second, third, _SECOND]
    # the marker back on the FIRST piece, with the third one chosen: it cuts the first
    CreativeState.hear_clip_time.fn(state, 3.5, "pause")  # 1.5 s into the first piece
    assert state.clip_cut_here_reason == ""
    CreativeState.cut_clip_video.fn(state)
    assert state.clip_cut_pieces == [
        [0.0, 1.5, 1.0],
        [1.5, 3.0, 1.0],
        [3.0, 9.0, 1.0],
        [9.0, 15.0, 1.0],
    ]
    assert state.clip_edit_block == second
    assert state.clip_edit_notice == "Cortaste el video 2 en dos."


def test_the_pieces_move_together(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.hear_clip_time.fn(state, 7.0, "pause")
    CreativeState.cut_clip_video.fn(state)
    second = clip_editor_vm.piece_id(_KEY, 1)
    CreativeState.select_clip_block.fn(state, _KEY)  # the first piece chosen
    # the second piece before the first: the recipe follows
    CreativeState.drop_clip_block.fn(state, second, "move", 1.0)
    assert state.clip_cut_pieces == [[5.0, 15.0, 1.0], [0.0, 5.0, 1.0]]
    assert state.clip_edit_block == second  # the chosen piece is still the chosen one
    # a move that would split the pieces up is not taken
    CreativeState.drop_clip_block.fn(state, _PHOTO, "move", 1.0)
    assert [r["id"] for r in state.clip_tl_media_rows][0] == _PHOTO


def test_velocidad_is_the_pieces_own(editor_on: None) -> None:
    """«Velocidad» of the own video while it is ONE stretch (ED-10, kept with «Por
    pedazo»): sped up from normal it takes the whole video, back to normal its stretch
    comes back — with its line; a speed is on only when the WHOLE
    video lasts 3–60 s with it. Cut in pieces, only the chosen one changes
    (`test_speed_by_piece_changes_only_that_segment`)."""
    state = _timeline_state()  # photo 2 s + own 0:00–0:15 + second 8 s = 25 s
    assert state.clip_tl_speed == "1" and state.clip_tl_speed_offered
    CreativeState.set_clip_block_speed.fn(state, _KEY, "3")
    assert state.clip_effect_ids == ["camara_rapida"] and state.clip_speed == 3
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 20.0)  # the whole video
    assert state.clip_tl_speed == "3"
    assert state.clip_edit_notice == "Pusiste tu video ×3: usamos todo tu video."
    CreativeState.set_clip_block_speed.fn(state, _KEY, "5")  # only the speed
    assert (state.clip_cut_end, state.clip_speed) == (20.0, 5)
    assert state.clip_edit_notice == "Pusiste el video 2 ×5."
    assert state.clip_tl_total == "14"  # 2 + 4 + 8
    CreativeState.set_clip_block_speed.fn(state, _KEY, "1")
    assert state.clip_effect_ids == [] and state.clip_tl_speed == "1"
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 15.0)  # its stretch back
    assert state.clip_edit_notice == "Volviste tu video a la velocidad normal."
    # one change, one line
    CreativeState.set_clip_block_speed.fn(state, _KEY, "2")
    assert state.clip_edit_notice == "Pusiste tu video ×2: usamos todo tu video."
    # a video alone of 9 s: ×10 would leave 0,9 s — off, says why; ×3 on (3 s)
    short = _measured(9.0)
    CreativeState.set_clip_block_speed.fn(short, _KEY, "10")
    assert short.clip_effect_ids == []
    assert short.clip_speed_note == "Con ×10 tu video duraría 0,9 s."
    CreativeState.set_clip_block_speed.fn(short, _KEY, "3")
    assert short.clip_effect_ids == ["camara_rapida"]
    # never on another block: the other video's speed leaves the own video's as it was
    before = (list(state.clip_effect_ids), state.clip_speed)
    CreativeState.set_clip_block_speed.fn(state, _SECOND, "10")
    assert (list(state.clip_effect_ids), state.clip_speed) == before


def test_agregar_opens_one_flow_at_a_time(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.open_clip_flow.fn(state, "media")
    assert state.clip_tl_flow == "media" and state.clip_tl_selected == ""
    assert state.clip_tl_chosen_kind == ""  # the orbit stays
    CreativeState.open_clip_flow.fn(state, "idea")
    assert state.clip_tl_flow == "idea"
    assert CreativeState.open_clip_flow.fn(state, "nope") == []
    # «+ Texto»: typed and left, the text starts where the playhead rests; the panel
    # stays on «Texto» (Deivid 2026-11-17: one panel with tabs)
    CreativeState.hear_clip_time.fn(state, 4.2, "pause")
    CreativeState.open_clip_flow.fn(state, "text")
    CreativeState.set_clip_overlay_text.fn(state, "Hola")
    CreativeState.commit_clip_overlay_text.fn(state, "")
    assert state.clip_tl_text_rows[0]["start"] == "4"
    assert state.clip_tl_flow == "text" and state.clip_flow_drawer_open
    # with a text there, «+ Texto» opens the same tab (to edit it)
    CreativeState.done_clip_block.fn(state)
    CreativeState.open_clip_flow.fn(state, "text")
    assert state.clip_tl_flow == "text"
    # Deivid 2026-11-16: a flow opens in the side panel with its own history entry (no
    # word in the address), so the phone's «atrás» closes the panel first, same step
    CreativeState.done_clip_block.fn(state)
    events = CreativeState.open_clip_flow.fn(state, "idea")
    assert state.clip_flow_drawer_open
    assert "pushState" in _scripts(events) and "qBloque" in _scripts(events)
    step = state.create_step_n
    CreativeState.reconcile_reel_editor_route.fn(state, "?paso=1")
    assert state.clip_tl_flow == "" and not state.clip_flow_drawer_open
    assert state.create_step_n == step


def test_the_flows_side_panel_closes_like_listo(editor_on: None) -> None:
    """✕, Escape and the backdrop close the flow's side panel as «Listo» does (walking
    back through its history entry); a block chosen from a flow reuses that entry."""
    state = _timeline_state()
    CreativeState.open_clip_flow.fn(state, "effect")
    assert CreativeState.set_clip_flow_drawer_open.fn(state, True) == []
    events = CreativeState.set_clip_flow_drawer_open.fn(state, False)
    assert state.clip_edit_block == "" and "history.back" in _scripts(events)
    # nothing open: nothing to close
    assert CreativeState.set_clip_flow_drawer_open.fn(state, False) == []
    # a block chosen while a flow's entry is up replaces that entry, never stacks one
    CreativeState.open_clip_flow.fn(state, "media")
    text = _scripts(CreativeState.select_clip_block.fn(state, _KEY))
    assert "qBloque" in text and "replaceState" in text


def test_one_side_panel_with_tabs(editor_on: None) -> None:
    """Deivid 2026-11-17: «¿Con qué lo armamos?», «Texto», «Efecto» and «Pedir una idea»
    are tabs of ONE side panel; the media selector lives in it (the media drawer never
    opens on top), and closing it adds what «Tu Galería» holds chosen."""
    state = _timeline_state()
    events = CreativeState.open_clip_flow.fn(state, "media")
    assert state.clip_flow_drawer_open and not state.media_drawer_open
    # the selector works on the Clip's own target, on «Tus productos» with no product
    assert state.media_drawer_target == creative_state_module.MEDIA_DRAWER_CLIP
    assert state.clip_source_tab == "catalog"
    assert "reset_choice" in _scripts(events)
    # a tab switch keeps the panel open, on that tab
    CreativeState.switch_clip_flow.fn(state, "effect")
    assert state.clip_tl_flow == "effect" and state.clip_flow_drawer_open
    CreativeState.switch_clip_flow.fn(state, ["idea"])
    assert state.clip_tl_flow == "idea"
    assert CreativeState.switch_clip_flow.fn(state, "nope") == []
    CreativeState.switch_clip_flow.fn(state, "media")
    # ✕ / Escape / «Listo»: closed, and «Tu Galería»'s choice goes in (`finish`)
    events = CreativeState.set_clip_flow_drawer_open.fn(state, False)
    assert state.clip_tl_flow == "" and not state.clip_flow_drawer_open
    assert "finish" in _scripts(events)
    # a tab switch with the panel closed does nothing
    assert CreativeState.switch_clip_flow.fn(state, "text") == []
    # «atrás» closes it too
    CreativeState.open_clip_flow.fn(state, "media")
    CreativeState.reconcile_reel_editor_route.fn(state, "?paso=1")
    assert not state.media_drawer_open and state.clip_tl_flow == ""


def test_cambiar_of_the_product_row_opens_the_panel(editor_on: None) -> None:
    """The «Producto» row is above the options again (Deivid 2026-11-17); on «Arma tu
    video» its «Cambiar» opens the side panel on «¿Con qué lo armamos?» → «Tus
    productos», and the focus goes back to it."""
    state = _timeline_state()
    assert state.clip_editor_on_screen
    CreativeState.change_product.fn(state)
    assert state.clip_tl_flow == "media" and not state.media_drawer_open
    assert state.clip_source_tab == "catalog"
    assert state.clip_flow_opener == creative_state_module.PRODUCT_ROW_ID
    CreativeState.open_clip_flow.fn(state, "text")
    assert state.clip_flow_opener == ""  # the «+» opened it: the focus goes there


def test_an_inspiration_goes_in_as_a_reference(editor_on: None) -> None:
    """Deivid 2026-11-17 («las inspiraciones no se ponen»): a stock pick is added to the
    Clip as a reference — in the panel's tiles, the «Producto» row's bubbles and the
    panel's foot — and stays off the timeline (Deivid 2026-11-14: stock only guides the
    AI)."""
    state = _timeline_state()
    stock_key = "t/x/stock/pixabay/9/vaso.jpg"
    state._add_inspiration_file({"key": stock_key, "author": "Ana", "view": "/r2/x"}, "image")
    state._pick("clip_images", "inspiration", stock_key)
    assert [i["key"] for i in state.clip_images][-1] == stock_key
    assert any(t["key"] == stock_key for t in state.clip_reference_tiles)
    assert any(t["key"] == stock_key for t in state._product_row_items())
    assert state.clip_refs_summary == "2 fotos y 2 videos en tus referencias"
    assert stock_key not in [r["id"] for r in state.clip_tl_media_rows]
    # a stock video too: a reference, never the video the editor cuts
    video_key = "t/x/stock/pixabay/10/mar.mp4"
    state.clip_videos = []
    state._add_inspiration_file({"key": video_key, "author": "Ana", "view": "/r2/v"}, "video")
    state._pick("clip_videos", "inspiration", video_key)
    assert state.clip_videos[0]["source"] == "inspiration"
    assert state.clip_edit_video_key == ""
    assert video_key not in [r["id"] for r in state.clip_tl_media_rows]


def test_the_effect_panel_offers_the_layers_whose_loop_exists(editor_on: None) -> None:
    state = _timeline_state()
    # EF-08: the three loops exist; «Cámara rápida» is «Velocidad» now, never a choice
    ids = [row["id"] for row in state.clip_tl_effect_choices]
    assert sorted(ids) == ["brasas_capa", "humo_capa", "vapor_capa"]
    CreativeState.add_clip_effect.fn(state, "vapor_capa")
    assert state.clip_effect_ids == ["vapor_capa"]


def test_the_quitar_of_a_photo_removes_it_from_the_clip(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.select_clip_block.fn(state, _PHOTO)
    CreativeState.clip_block_action.fn(state, "Quitar")
    assert state.clip_images == [] and state.clip_edit_block == ""
    assert [r["id"] for r in state.clip_tl_media_rows] == [_KEY, _SECOND]


def test_switch_off_keeps_step_one_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    """Criterion 9: with `QUALIFY_CLIP_EDITOR` off the Clip's step 1 is «Qué mostrar»
    with its «Orden del clip» strip — no timeline, no `?bloque=`."""
    from . import content_generator

    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", False)
    state = _timeline_state()
    assert not state.clip_editor_shown
    assert state.create_step_title == "Qué mostrar"
    CreativeState.reconcile_reel_editor_route.fn(state, "?paso=1&bloque=video-2")
    assert state.clip_edit_block == ""
    rendered = str(content_generator._clip_references_view().render())
    assert "data-q-timeline" not in rendered and "q-tl" not in rendered
    assert "clip_strip" in rendered  # the strip of always


def test_the_page_order_and_the_side_panel(editor_on: None) -> None:
    """Deivid, 2026-11-16: preview (centred) → timeline → bar → the chosen block's panel
    under it → «Armar mi video por partes»; «¿Con qué lo armamos?» and the other flows
    only in the ONE side panel (`ui.drawer`, with its tabs), never on the page."""
    import reflex as rx

    from . import clip_editor_view

    rendered = str(clip_editor_view.arma_tu_video(rx.text("MEDIA-BODY-MARK")))
    order = [
        rendered.index(name)
        for name in ("q-edit__preview", "q-edit__timeline", "q-edit__main", "q-edit__parts")
    ]
    assert order == sorted(order)
    drawer_at = rendered.index("q-drawer")
    assert drawer_at > order[-1]  # the side panel is not part of the page's flow
    assert "MEDIA-BODY-MARK" in rendered[drawer_at:]
    assert "clip_flow_drawer_open" in rendered and "set_clip_flow_drawer_open" in rendered
    for question in clip_editor_vm.FLOW_QUESTIONS.values():
        assert question not in rendered[:drawer_at], question
    # one panel, its tabs (the non-ASCII names render escaped: the ASCII ones and the
    # tabs' marks are enough here)
    assert rendered[drawer_at:].count("data-flow-tab") >= len(clip_editor_vm.FLOW_TABS)
    for name in ("Texto", "Efecto", "Pedir una idea"):
        assert name in rendered[drawer_at:], name
    assert "switch_clip_flow" in rendered and "data-flow-opener" in rendered
    assert "Usar el video entero" not in rendered and "use_whole_clip_video" not in rendered
    assert "cut_clip_video" in rendered and "clip_cut_here_reason" in rendered
    main = rendered[order[2] : order[3]]
    assert "data-tl-panel" in main  # the block's panel («menú de control») on the page


def test_the_text_place_control_is_never_cut(editor_on: None) -> None:
    """Deivid 2026-11-17: «en el texto el selector de la posicion esta bugeado se corta
    mal». Radix's track is `min-width: max-content` and 32 px tall with 44 px options:
    in the side panel it ran past the edge. `.q-seg-fill` fills its row with equal
    columns, grows with its options and lets a long name wrap inside its option."""
    from pathlib import Path

    from . import clip_editor_view

    rendered = str(clip_editor_view._text_block().render())
    assert clip_editor_view.TEXT_PLACE_CLASS == "q-seg-fill"
    assert "q-seg-fill" in rendered
    css = (Path(__file__).resolve().parent.parent / "assets" / "qualify.css").read_text(
        encoding="utf-8"
    )
    rule = css[css.index(".rt-SegmentedControlRoot.q-seg-fill {") :]
    rule = rule[: rule.index("}")]
    assert "min-width: 0" in rule and "grid-auto-columns: minmax(0, 1fr)" in rule
    assert "height: auto" in rule and "max-content" not in rule
    label = css[css.index(".q-seg-fill .rt-SegmentedControlItemLabel {") :]
    assert "white-space: normal" in label[: label.index("}")]
    # not only on a phone: the drawer is narrow at 1280 px too (top level, no @media)
    at = css.index(".radix-themes .rt-SegmentedControlRoot.q-seg-fill {")
    assert css[:at].count("{") == css[:at].count("}")


def test_velocidad_fills_its_row_and_reads_x1(editor_on: None) -> None:
    """ED-10 UX review: «Velocidad» was cut at 375 px. It fills its row as the text's
    place does (`.q-seg-fill`), and «Normal» reads «×1» (named «Velocidad normal»)."""
    from . import clip_editor_view

    rendered = str(clip_editor_view._speed().render())
    assert "q-source-seg q-tl-seg q-seg-fill" in rendered
    from .ui import timeline_vm

    assert ("1", "×1", "Velocidad normal") in timeline_vm.SPEEDS


def test_the_empty_effect_tab_offers_a_text(editor_on: None) -> None:
    """ED-10 UX review: no effect yet — the tab says what to do and its button opens
    the «Texto» tab of the same panel."""
    from . import clip_editor_view

    rendered = str(clip_editor_view._effects().render())
    assert "Mientras tanto, agrega un texto." in rendered
    assert clip_editor_vm.NO_EFFECTS_GO_TEXT in rendered
    assert "switch_clip_flow" in rendered
    state = _timeline_state()
    CreativeState.open_clip_flow.fn(state, clip_editor_vm.FLOW_EFFECT)
    CreativeState.switch_clip_flow.fn(state, clip_editor_vm.FLOW_TEXT)
    assert clip_editor_vm.flow_of(state.clip_edit_block) == clip_editor_vm.FLOW_TEXT


def test_with_own_media_on_the_timeline_inspiration_and_music_are_not_offered(
    editor_on: None,
) -> None:
    """UX review B6: once the owner's photos or videos are on the timeline the video is
    made from them only — «Inspiración» is not offered (nor kept chosen), and «Más
    opciones» names no sound nor subtitles. An empty timeline is the AI's Clip, which
    keeps them."""
    state = _state()
    state.clip_videos = []  # nothing on the timeline yet
    assert not state.clip_edit_local
    assert "inspiration" in state._clip_source_tabs()
    CreativeState.set_clip_source_tab.fn(state, "inspiration")
    assert state.clip_source_tab_shown == "inspiration"
    assert state.gen_campaign_hint.startswith("El sonido, los subtítulos")
    state.clip_videos = [{"key": _KEY, "name": "video.mp4", "source": "upload"}]
    CreativeState.report_clip_source.fn(state, _KEY, 20.0, 1080, 1920)
    assert state.clip_edit_local
    assert "inspiration" not in state._clip_source_tabs()
    assert state.clip_source_tab_shown == "catalog"  # the hidden tab is not shown
    assert CreativeState.set_clip_source_tab.fn(state, "inspiration") is None
    CreativeState.set_clip_source_tab.fn(state, "upload")
    assert state.clip_source_tab == state.clip_source_tab_shown == "upload"
    assert "sonido" not in state.gen_campaign_hint
    assert "subtítulos" not in state.gen_campaign_hint


# -- ED-03 m-25026623: the trim handles, «Cortar»'s limits, speed by piece ---------------------


def _cut_at(state: CreativeState, t: float) -> None:
    CreativeState.hear_clip_time.fn(state, t, "pause")
    CreativeState.cut_clip_video.fn(state)


def test_the_start_handle_dragged_to_three_point_two_leaves_three(editor_on: None) -> None:
    """The ticket's case: the start handle dragged from 0:00 to 0:03,2 — the browser's
    ½ s magnet sends 3.0 (`assets/timeline-drag-core.js`); the piece starts at 0:03, the
    blocks after it move 3 s earlier (no gap), with its line."""
    state = _timeline_state()  # photo 0–2, own 2–17 (0:00–0:15), second 17–25
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.drop_clip_block.fn(state, _KEY, "start", 3.0)
    assert (state.clip_cut_start, state.clip_cut_end) == (3.0, 15.0)
    rows = state.clip_tl_media_rows
    assert rows[1]["name"] == "Video 2 de 3, usas de 0:03 a 0:15, dura 12 s"
    assert [r["start"] for r in rows] == ["0", "2", "14"]  # the second video moved up 3 s
    assert state.clip_tl_total == "22"
    assert state.clip_edit_notice == "Recortaste el video 2."
    segments = state._clip_edit_media()["segments"]
    assert [(s["key"], s["start_s"], s["end_s"]) for s in segments] == [  # type: ignore[index]
        (_PHOTO, 0.0, 2.0),
        (_KEY, 3.0, 15.0),
        (_SECOND, 0.0, 8.0),
    ]


def test_the_handles_are_sliders_with_their_names_and_ranges(editor_on: None) -> None:
    state = _timeline_state()
    row = state.clip_tl_media_rows[1]
    assert (row["start_handle"], row["end_handle"]) == ("Inicio de video 2", "Final de video 2")
    assert (row["start_text"], row["end_text"]) == ("0:00", "0:15")
    # what a screen reader hears, and the drag's bubble (UX review)
    assert (row["start_value"], row["end_value"]) == ("Desde 0:00", "Hasta 0:15")
    # inside its own material (0…20 s), never under 1 s
    assert (row["start_min"], row["start_max"]) == ("0", "14")
    assert (row["end_min"], row["end_max"]) == ("1", "20")
    from .ui import timeline as tl

    html = str(tl._handle(state.clip_tl_media_rows[1], "start").render())  # type: ignore[arg-type]
    assert '"slider"' in html and "data-tl-from" in html and "data-tl-speed" in html
    # a plain row renders its values, not their keys: the reader hears «Desde 0:00»
    assert "data-tl-word" in html and "Desde 0:00" in html


def test_a_handle_stays_inside_the_video_and_its_minute(editor_on: None) -> None:
    """Inside its own material (0 … the file's length — past it is «extend», another
    ticket) and never over A9's minute of the video, said in A9's words."""
    state = _measured(200.0)  # 0:00–0:15
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 500.0)
    assert state.clip_cut_end == 60.0
    assert state.clip_cut_error == clip_editor_vm.SOURCE_TOO_LONG
    CreativeState.drop_clip_block.fn(state, _KEY, "start", -4.0)
    assert state.clip_cut_start == 0.0
    small = _measured(20.0)
    CreativeState.drop_clip_block.fn(small, _KEY, "end", 25.0)
    assert small.clip_cut_end == 20.0 and small.clip_cut_error == ""  # the file's end
    # sped up, a piece keeps ½ s of the final video (×5: 2,5 s of the video)
    CreativeState.set_clip_block_speed.fn(small, _KEY, "5")
    CreativeState.drop_clip_block.fn(small, _KEY, "start", 19.0)
    assert small.clip_cut_start == 17.5
    assert small.clip_cut_error == "El pedazo tiene que durar al menos ½ s."


def test_a_shorter_video_cuts_a_text_past_its_end_and_says_so(editor_on: None) -> None:
    state = _measured(20.0)  # 0:00–0:15
    CreativeState.set_clip_overlay_text.fn(state, "2×1")
    CreativeState.commit_clip_overlay_text.fn(state, "")
    state.clip_text_start, state.clip_text_end = 5.0, 14.0
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 8.0)
    assert (state.clip_text_start, state.clip_text_end) == (5.0, -1.0)  # to the new end
    assert state.clip_edit_notice == ("Recortaste el video 1. El texto ahora termina con tu video.")
    # kept so: lengthening the video again does not bring the old end back
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 15.0)
    assert (state.clip_text_start, state.clip_text_end) == (5.0, -1.0)


def test_cortar_is_off_with_eight_blocks(editor_on: None) -> None:
    """The recipe takes 8 stretches in all — the photo and the other video count."""
    state = _timeline_state()  # photo, own, second: 3 blocks
    CreativeState.select_clip_block.fn(state, _KEY)
    for t in (4.0, 6.0, 8.0, 10.0, 12.0):  # five cuts: 8 blocks
        _cut_at(state, t)
    assert len(state.clip_tl_media_rows) == 8
    CreativeState.hear_clip_time.fn(state, 14.0, "pause")
    assert state.clip_cut_here_reason == (
        "Tu video puede tener hasta 8 fotos o videos. Quita uno para cortar de nuevo."
    )
    assert CreativeState.cut_clip_video.fn(state) == []
    assert len(state.clip_tl_media_rows) == 8


def test_no_piece_under_one_second(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.hear_clip_time.fn(state, 2.8, "pause")  # 0.8 s into the video
    assert state.clip_cut_here_reason == clip_editor_vm.CUT_TOO_CLOSE
    _cut_at(state, 5.0)  # 0–3 and 3–15
    second = clip_editor_vm.piece_id(_KEY, 1)
    CreativeState.drop_clip_block.fn(state, second, "start", 14.8)
    assert state.clip_cut_pieces[1] == [14.0, 15.0, 1.0]
    assert state.clip_cut_error == TOO_SHORT


def test_quitar_a_whole_video_or_photo_closes_up_and_says_it(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.select_clip_block.fn(state, _SECOND)
    CreativeState.clip_block_action.fn(state, "Quitar")
    assert [r["id"] for r in state.clip_tl_media_rows] == [_PHOTO, _KEY]
    assert state.clip_tl_total == "17"  # no gap: the track is the sum of its blocks
    assert state.clip_edit_notice == "Quitaste el video 3."
    # a photo too: the video after it moves up to 0:00
    CreativeState.select_clip_block.fn(state, _PHOTO)
    CreativeState.clip_block_action.fn(state, "Quitar")
    assert state.clip_edit_notice == "Quitaste la foto 1."
    assert [(r["id"], r["start"]) for r in state.clip_tl_media_rows] == [(_KEY, "0")]


def test_speed_by_piece_changes_only_that_segment(editor_on: None) -> None:
    """Deivid 2026-11-19 («Por pedazo»): ×10 on piece 2 changes only its
    `SourceSegment.speed`; back to ×1 it is as before."""
    state = _measured(60.0)
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 40.0)  # 0:00–0:40
    CreativeState.select_clip_block.fn(state, _KEY)
    _cut_at(state, 10.0)  # 0–10 and 10–40; the second piece is the chosen one
    second = clip_editor_vm.piece_id(_KEY, 1)
    assert state.clip_edit_block == second and state.clip_tl_speed == "1"
    CreativeState.set_clip_block_speed.fn(state, second, "10")  # 10 + 3 = 13 s
    assert state.clip_cut_pieces == [[0.0, 10.0, 1.0], [10.0, 40.0, 10.0]]
    assert state.clip_effect_ids == []  # each piece says its speed
    assert state.clip_tl_speed == "10"
    assert state.clip_edit_notice == "Pusiste el video 2 ×10."
    segments = state._clip_edit_media()["segments"]
    assert [(s["start_s"], s["end_s"], s["speed"]) for s in segments] == [  # type: ignore[index]
        (0.0, 10.0, 1.0),
        (10.0, 40.0, 10.0),
    ]
    assert state.clip_speed_line == "Tu video durará 13 s."
    rows = state.clip_tl_media_rows
    assert [r["speed_tag"] for r in rows] == ["", "×10"]
    # the first piece is still normal: its own «Velocidad»
    CreativeState.select_clip_block.fn(state, _KEY)
    assert state.clip_tl_speed == "1"
    CreativeState.set_clip_block_speed.fn(state, second, "1")
    assert state.clip_cut_pieces == [[0.0, 10.0, 1.0], [10.0, 40.0, 1.0]]
    assert state.clip_edit_notice == "Volviste el video 2 a la velocidad normal."


def test_a_speed_is_on_for_the_whole_videos_three_to_sixty_seconds(editor_on: None) -> None:
    """A speed of one piece is on only when the whole video — the other blocks as they
    are, this piece at that speed — lasts 3–60 s, and the piece keeps its least."""
    state = _timeline_state()  # photo 2 + own 15 + second 8
    # one stretch at normal speed: judged as sped up, the whole 20 s video
    reasons = state.clip_speed_reasons  # of the own video (nothing chosen: its first piece)
    assert all(reasons[v] == "" for v in ("2", "3", "5", "10", "20"))  # 11 s at ×20
    alone = _measured(20.0)  # 0:00–0:15 alone; sped up, all 20 s
    assert alone.clip_speed_reasons["10"] == "Con ×10 tu video duraría 2 s."
    assert alone.clip_speed_reasons["5"] == ""
    # a piece of 2 s at ×20 is under ½ s of the final video: off
    CreativeState.select_clip_block.fn(state, _KEY)
    _cut_at(state, 4.0)  # 0–2 and 2–15
    CreativeState.select_clip_block.fn(state, _KEY)  # the first piece, 2 s
    assert state.clip_speed_reasons["20"] == clip_editor_vm.piece_too_short_line(20, 0.1)


def test_cortar_and_handles_keep_each_pieces_speed(editor_on: None) -> None:
    state = _measured(60.0)
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 40.0)
    CreativeState.select_clip_block.fn(state, _KEY)
    _cut_at(state, 10.0)
    second = clip_editor_vm.piece_id(_KEY, 1)
    CreativeState.set_clip_block_speed.fn(state, second, "5")  # 10–40 at ×5 = 6 s
    _cut_at(state, 13.0)  # 3 s into the ×5 piece = 15 s of the video
    assert state.clip_cut_pieces == [[0.0, 10.0, 1.0], [10.0, 25.0, 5.0], [25.0, 40.0, 5.0]]
    third = clip_editor_vm.piece_id(_KEY, 2)
    CreativeState.drop_clip_block.fn(state, third, "end", 35.0)
    assert state.clip_cut_pieces[2] == [25.0, 35.0, 5.0]
    # «Quitar» down to one piece: the stretch keeps that piece's speed
    assert state.clip_edit_block == third
    CreativeState.clip_block_action.fn(state, "Quitar")
    CreativeState.select_clip_block.fn(state, second)
    CreativeState.clip_block_action.fn(state, "Quitar")
    assert state.clip_cut_pieces == []
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 10.0)
    assert state.clip_effect_ids == [] and state.clip_tl_speed == "1"


def test_a_piece_over_a_minute_says_a9_in_the_panel_and_before_crear(editor_on: None) -> None:
    """A9 (m-25042483): a piece over a minute of its video — said in the video's panel and
    before «Crear», in A9's words; «Cortar» stays on (it is the way out)."""
    state = _measured(100.0)
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 60.0)  # the most a handle gives
    state.clip_cut_end = 90.0  # e.g. a stretch kept from before A9
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.hear_clip_time.fn(state, 30.0, "pause")
    assert state.clip_source_too_long_line == clip_editor_vm.SOURCE_TOO_LONG
    assert state.clip_cut_here_reason == ""
    assert state._clip_edit_problem() == (clip_editor_vm.SOURCE_TOO_LONG, "warn")
    _cut_at(state, 30.0)  # 0–30 and 30–90: a minute at most each
    assert state.clip_source_too_long_line == ""
    assert state._clip_edit_problem()[0] != clip_editor_vm.SOURCE_TOO_LONG


# -- ED-03 QA (Deivid 2026-11-19): no gap after a speed goes up and back, the trim hint --------


def _gapless(state: CreativeState) -> None:
    """Every block of «Fotos y videos» starts exactly where the one before ends — on the
    timeline (its CSS numbers) and in the preview in sequence (`_clip_sequence`)."""
    rows = state.clip_tl_media_rows
    for before, after in zip(rows, rows[1:], strict=False):
        end = float(before["start"]) + float(before["length"])
        assert end == pytest.approx(float(after["start"]), abs=1e-9), (before, after)
    blocks = state._clip_sequence().blocks
    for before, after in zip(blocks, blocks[1:], strict=False):
        assert before.out_end == after.out_start
    assert float(rows[-1]["start"]) + float(rows[-1]["length"]) == pytest.approx(
        blocks[-1].out_end, abs=0.011
    )


def test_a_piece_sped_up_and_back_leaves_no_gap(editor_on: None) -> None:
    """Deivid 2026-11-19: «aumenté la velocidad de un video y la volví a poner a la
    original y quedó un espacio» — a piece of 3,7 s, ×2 (1,85 s) and back to ×1: the
    blocks were placed on the ½ s grid each on its own (0:03,5 + 0:04 = a gap); now they
    are laid end to end to the hundredth."""
    state = _timeline_state()  # photo 0–2, own 2–17, second 17–25
    CreativeState.select_clip_block.fn(state, _KEY)
    _cut_at(state, 5.7)  # 3,7 s into the own video: 0–3,7 and 3,7–15
    assert state.clip_cut_pieces == [[0.0, 3.7, 1.0], [3.7, 15.0, 1.0]]
    _gapless(state)
    CreativeState.set_clip_block_speed.fn(state, _KEY, "2")
    assert [r["length"] for r in state.clip_tl_media_rows][:2] == ["2", "1.85"]
    _gapless(state)
    CreativeState.set_clip_block_speed.fn(state, _KEY, "1")
    assert state.clip_cut_pieces == [[0.0, 3.7, 1.0], [3.7, 15.0, 1.0]]
    rows = state.clip_tl_media_rows
    assert [(r["start"], r["length"]) for r in rows] == [
        ("0", "2"),
        ("2", "3.7"),
        ("5.7", "11.3"),
        ("17", "8"),
    ]
    _gapless(state)


def test_one_stretch_sped_up_and_back_leaves_no_gap(editor_on: None) -> None:
    """The same with the video not cut, and a length off the ½ s grid (7,33 s: the
    stretch's end is kept on the grid, 7,5, but the block ends at 7,33)."""
    state = _measured(7.33)
    state.clip_images = [{"key": _PHOTO, "name": "foto.jpg", "source": "upload", "role": "product"}]
    state.clip_sequence = [_KEY, _PHOTO]
    CreativeState.set_clip_block_speed.fn(state, _KEY, "2")
    _gapless(state)
    CreativeState.set_clip_block_speed.fn(state, _KEY, "1")
    rows = state.clip_tl_media_rows
    assert [(r["start"], r["length"]) for r in rows] == [("0", "7.33"), ("7.33", "2")]
    _gapless(state)


def test_the_trim_hint_shows_until_the_first_trim(editor_on: None) -> None:
    """Deivid 2026-11-19 («lo de los tiradores no lo entendí»): with a video that has
    handles chosen, `TRIM_HINT` (UX review: «Arrastra las barras de color…») — until the
    first trim; never
    on a photo, never with nothing chosen."""
    state = _timeline_state()
    assert state.clip_trim_hint == ""
    CreativeState.select_clip_block.fn(state, _PHOTO)
    assert state.clip_trim_hint == ""
    CreativeState.select_clip_block.fn(state, _KEY)
    assert state.clip_trim_hint == (
        "Arrastra las barras de color: hacia adentro recortas, hacia afuera alargas."
    )
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 12.0)
    assert state.clip_trim_hint == "" and state.clip_trim_hint_seen


def test_the_editor_has_no_deshacer_button_and_shows_the_hint() -> None:
    from . import clip_editor_view

    rendered = str(clip_editor_view._timeline().render())
    assert "undo_clip_edit" not in rendered and "Deshacer" not in rendered
    assert "clip_trim_hint" in rendered


# -- review ED-03 (2026-11-19) ------------------------------------------------------------------


def test_an_off_speeds_why_stays_with_its_block(editor_on: None) -> None:
    """Review ED-03: ×20 refused on video 2 — choosing video 3 does not carry the note."""
    state = _measured(60.0)
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 40.0)
    CreativeState.select_clip_block.fn(state, _KEY)
    _cut_at(state, 35.0)  # 0–35 and 35–40: the second piece (video 2) chosen
    second = clip_editor_vm.piece_id(_KEY, 1)
    CreativeState.set_clip_block_speed.fn(state, second, "20")  # 5 s at ×20: too short
    assert state.clip_speed_note.startswith("Con ×20")
    CreativeState.select_clip_block.fn(state, _KEY)  # the other piece
    assert state.clip_speed_refused == "" and state.clip_speed_note == ""
    # a trim clears it too
    CreativeState.set_clip_block_speed.fn(state, _KEY, "20")  # 35 s at ×20 = 1,75 s + 5
    CreativeState.set_clip_block_speed.fn(state, second, "20")
    assert state.clip_speed_refused != ""
    CreativeState.drop_clip_block.fn(state, second, "end", 39.0)
    assert state.clip_speed_refused == ""
    # and leaving the editor
    state.clip_speed_refused = "x"
    state._reset_clip_editor()
    assert state.clip_speed_refused == ""


def test_a_texts_and_an_effects_handles_land_on_the_half_second(editor_on: None) -> None:
    """Review ED-03: a text's or an effect's handle dragged is put on the ½ s magnet on
    the server too (as a whole block's «time»): the timeline and the preview agree."""
    state = _timeline_state()  # 25 s
    CreativeState.set_clip_overlay_text.fn(state, "2×1 hoy")
    CreativeState.commit_clip_overlay_text.fn(state, "")
    CreativeState.drop_clip_block.fn(state, "texto-1", "start", 3.3)
    CreativeState.drop_clip_block.fn(state, "texto-1", "end", 12.74)
    assert (state.clip_text_start, state.clip_text_end) == (3.5, 12.5)
    texts = state._clip_sequence().texts
    assert (texts[0].start, texts[0].end) == (3.5, 12.5)
    CreativeState.add_clip_effect.fn(state, "vapor_capa")
    CreativeState.drop_clip_block.fn(state, "efecto-vapor_capa", "start", 4.2)
    CreativeState.drop_clip_block.fn(state, "efecto-vapor_capa", "end", 9.8)
    assert state.clip_effect_times["vapor_capa"] == [4.0, 10.0]
    effects = state._clip_sequence().effects
    assert (effects[0].start, effects[0].end) == (4.0, 10.0)


def test_a_shorter_video_keeps_a_cut_text_on_the_half_second(editor_on: None) -> None:
    """`_clip_fit_overlays` puts a text that starts past the new end on the ½ s too."""
    state = _measured(20.0)  # 0:00–0:15
    CreativeState.set_clip_overlay_text.fn(state, "2×1")
    CreativeState.commit_clip_overlay_text.fn(state, "")
    state.clip_text_start, state.clip_text_end = 12.0, -1.0
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 7.3)  # 7,3 s: the text from 6
    assert state.clip_text_start == 6.0


def test_the_last_trim_wins_over_the_stretch_kept_before_a_speed_up(editor_on: None) -> None:
    """Review ED-03: the whole video sped up, then trimmed, then back to normal — the trim
    stays (it was the stretch from before the speed-up that came back)."""
    state = _measured(20.0)  # 0:00–0:15
    CreativeState.set_clip_block_speed.fn(state, _KEY, "2")  # the whole 20 s
    assert state._clip_fast_before == {"start": 0.0, "end": 15.0}
    CreativeState.drop_clip_block.fn(state, _KEY, "end", 18.0)
    assert state._clip_fast_before == {}
    CreativeState.set_clip_block_speed.fn(state, _KEY, "1")
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 18.0)  # the trim stays
