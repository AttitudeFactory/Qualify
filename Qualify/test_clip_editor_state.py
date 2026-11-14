"""ED-02/03 (m-25026621, m-25026623) and D-E6: the Clip editor's state — the switch
`QUALIFY_CLIP_EDITOR` (off = the Clip exactly as before), the stretch the browser's
length proposes, «Cortar», «Girar», «Cámara rápida», «Deshacer» back to the exact state,
and the recipe the brief carries. A standalone `CreativeState`, handlers called through
`.fn` (`test_creative_state.py` explains why)."""

from __future__ import annotations

from uuid import UUID

import pytest

from . import clip_editor_vm, r2_media
from . import creative_state as creative_state_module
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
    assert state.clip_card_title == "Tu video · 15 s"
    assert state.clip_cut_whole_label == "Usar los primeros 15 s"
    assert state.clip_edit_notice == ""  # the owner changed nothing
    CreativeState.report_clip_source.fn(state, "someone-elses-key", 3.0, 0, 0)
    assert state.clip_source_seconds == 20.0


def test_a_length_off_the_grid_keeps_its_end_reachable(editor_on: None) -> None:
    state = _measured(7.33)
    assert state.clip_cut_max_units == 15  # 7.5 s: ceil, never lost
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 7.5)
    assert state.clip_cut_units == [0, 15]
    assert state.clip_cut_whole_label == "Usar el video entero"
    assert state.clip_cut_check == ["", ""]  # EF-03 cuts 7.5 at 7.33, never refuses it


def test_the_length_is_taken_again_after_a_reset(editor_on: None) -> None:
    state = _measured(20.0)
    state._reset_clip_editor()
    assert not state.clip_cut_ready
    CreativeState.report_clip_source.fn(state, _KEY, 20.0, 1080, 1920)
    assert state.clip_cut_ready


def test_cut_nudge_and_its_error(editor_on: None) -> None:
    state = _measured(20.0)
    CreativeState.commit_clip_cut.fn(state, [8, 24])
    assert (state.clip_cut_start, state.clip_cut_end) == (4.0, 12.0)
    assert state.clip_cut_range_text == "Desde 0:04 · Hasta 0:12"
    assert (state.clip_cut_start_clock, state.clip_cut_end_clock) == ("0:04", "0:12")
    assert state.clip_edit_notice == "Cambiaste el pedazo de tu video."
    CreativeState.commit_clip_cut.fn(state, [8, 10])
    CreativeState.nudge_clip_cut.fn(state, "end", -0.5)
    assert state.clip_cut_error == TOO_SHORT
    assert (state.clip_cut_start, state.clip_cut_end) == (4.0, 5.0)
    CreativeState.nudge_clip_cut.fn(state, "end", 0.5)
    assert state.clip_cut_error == ""
    assert state.clip_cut_end == 5.5


def test_a_video_that_cannot_play_stops_waiting(editor_on: None) -> None:
    state = _state()
    assert "cut" in state.clip_edit_tools
    CreativeState.report_clip_source.fn(state, _KEY, -1.0, 0, 0)
    assert state.clip_source_broken
    assert "cut" not in state.clip_edit_tools
    state.clip_edit_tool = "cut"
    assert state.clip_edit_tool_open == "media"
    CreativeState.report_clip_source.fn(state, _KEY, 9.0, 1080, 1920)
    assert not state.clip_source_broken
    assert "cut" in state.clip_edit_tools


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
    assert "cut" in state.clip_edit_tools


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
    assert "cut" in state.clip_edit_tools


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
    assert "cut" not in state.clip_edit_tools


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


# -- «Cámara rápida» and «Deshacer» ---------------------------------------------------------


def test_fast_motion_proposes_the_whole_video_and_a_five_second_result(editor_on: None) -> None:
    state = _measured(40.0)
    assert state.clip_cut_end == 15.0
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 40.0)  # no 15 s cap
    assert state.clip_speed == 10  # 40 / 10 = 4 s, the closest to 5 s
    assert state.clip_speed_line == "Tu video durará 4 s."
    assert state.clip_fast_warning == ""
    CreativeState.set_clip_speed.fn(state, "20")
    assert state.clip_fast_warning == (
        "Tu video durará 2 s: muy poco para un reel. Elige un pedazo más largo o una "
        "velocidad menor."
    )
    assert state.clip_edit_slower


def test_undo_goes_back_to_the_exact_state(editor_on: None) -> None:
    state = _measured(20.0)
    before = (state.clip_cut_start, state.clip_cut_end, state.clip_rotate, state.clip_speed)
    CreativeState.rotate_clip_video.fn(state)
    assert state.clip_rotate == 90
    assert state.clip_edit_notice == "Giraste tu video."
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert state.clip_speed == 5  # 20 / 5 = 4 s
    CreativeState.set_clip_speed.fn(state, "20")
    CreativeState.undo_clip_edit.fn(state)
    assert state.clip_speed == 5
    assert state.clip_edit_notice == ""
    CreativeState.undo_clip_edit.fn(state)
    assert state.clip_effect_ids == []
    assert (state.clip_cut_end, state.clip_speed) == (15.0, 10)
    CreativeState.undo_clip_edit.fn(state)
    assert (state.clip_cut_start, state.clip_cut_end, state.clip_rotate, state.clip_speed) == (
        before
    )


def test_undo_has_no_timer_and_ends_with_the_step(editor_on: None) -> None:
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
    CreativeState.undo_clip_edit.fn(state)
    assert (state.clip_text_place, state.clip_overlay_text) == ("bottom", "2×1 hoy")
    CreativeState.undo_clip_edit.fn(state)
    assert state.clip_overlay_text == ""


def test_effects_offer_only_what_exists(editor_on: None) -> None:
    state = _measured()
    assert [row["id"] for row in state.clip_edit_effect_rows] == ["camara_rapida"]
    CreativeState.toggle_clip_effect.fn(state, "humo_capa")
    assert state.clip_effect_ids == []  # its loop does not exist yet: never offered
    assert state.clip_edit_effect_srcs == []


def test_photos_only_has_no_cut_nor_fast_motion(editor_on: None) -> None:
    state = _state()
    state.clip_videos = []
    assert state.clip_edit_tools == ["media", "idea", "effects"]
    assert state.clip_edit_effect_rows == []
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert state.clip_effect_ids == []
    state.clip_edit_tool = "cut"
    assert state.clip_edit_tool_open == "media"


def test_the_brief_carries_the_recipe(editor_on: None) -> None:
    state = _measured(20.0)
    CreativeState.commit_clip_cut.fn(state, [8, 24])
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    recipe = state._clip_edit_media()["edit_recipe"]
    assert recipe["segments"] == [  # type: ignore[index]
        {"key": _KEY, "start_s": 0.0, "end_s": 20.0, "speed": 5.0, "rotate": 0}
    ]
    # the speed travels in the stretch only; the effect's params stay empty
    assert recipe["effects"] == [  # type: ignore[index]
        {"effect_id": "camara_rapida", "version": 1, "params": {}, "start_s": None, "end_s": None}
    ]
    assert state._clip_media()["edit_recipe"] == recipe
    state.clip_videos = [{"key": "r", "name": "reel", "source": "reel"}]
    assert state._clip_edit_media() == {}


def test_fast_motion_says_so_and_unmarking_restores_the_stretch(editor_on: None) -> None:
    state = _measured(200.0)
    CreativeState.commit_clip_cut.fn(state, [8, 24])  # 4–12 s
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    # it had its own cut (4–12 s): the line says it comes back
    assert state.clip_edit_notice == (
        "Pusiste cámara rápida: usamos todo tu video a ×20. Si la quitas, vuelve tu pedazo."
    )
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 200.0)
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert state.clip_edit_notice == "Quitaste la cámara rápida de tu video."
    assert (state.clip_cut_start, state.clip_cut_end) == (4.0, 12.0)
    assert state.clip_edit_speed_real == 1.0


def test_unmarking_without_a_kept_stretch_trims_to_fifteen_seconds(editor_on: None) -> None:
    state = _measured(200.0)
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    state._clip_fast_before = {}  # e.g. a stretch from a session before this change
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 15.0)


def test_the_history_does_not_bring_undo_back(editor_on: None) -> None:
    state = _measured()
    CreativeState.rotate_clip_video.fn(state)
    assert state.clip_edit_notice != ""
    CreativeState.reconcile_reel_editor_route.fn(state, "?paso=1")
    assert state.clip_edit_notice == ""


def test_media_inputs_drop_the_edit_recipe_today(editor_on: None) -> None:
    """Pinned before the switch goes on: qualify_creative's real `MediaInputs` accepts the
    brief with `edit_recipe` WITHOUT an error and drops it (extra keys are ignored) —
    nothing reaches the producer until EF-02/EF-06 read `effects`/`text_layer`/`segments`."""
    from qualify_creative.schemas import MediaInputs

    state = _measured(20.0)
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    CreativeState.set_clip_overlay_text.fn(state, "2×1 hoy")
    CreativeState.commit_clip_overlay_text.fn(state, "")
    media = state._clip_media()
    assert "edit_recipe" in media
    inputs = MediaInputs.model_validate(media)
    assert "edit_recipe" not in inputs.model_dump()


def test_fast_motion_past_sixty_seconds_says_so(editor_on: None) -> None:
    state = _measured(1300.0)
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert state.clip_speed == 20  # 65 s, still the closest to 5 s
    assert state.clip_speed_line == ""
    assert state.clip_fast_warning == (
        "Con esa velocidad tu video duraría 65 s: muy largo para un reel. Elige una "
        "velocidad mayor o corta un pedazo más corto."
    )


def test_inspiration_stock_stays_a_reference(editor_on: None) -> None:
    """Deivid 2026-11-14: Inspiración stock is a reference for the AI only — the editor
    never cuts it and it never becomes a stretch of the recipe."""
    state = _state()
    stock = {"key": f"t/{_TENANT}/stock/v.mp4", "name": "Inspiración", "source": "stock"}
    state.clip_videos = [stock]
    assert "cut" not in state.clip_edit_tools
    assert state._clip_edit_media() == {} or not state._clip_edit_media().get("segments")
    state.clip_videos = [stock, {"key": _KEY, "name": "video.mp4", "source": "upload"}]
    CreativeState.report_clip_source.fn(state, _KEY, 20.0, 1080, 1920)
    segments = state._clip_edit_media()["edit_recipe"]["segments"]  # type: ignore[index]
    assert [segment["key"] for segment in segments] == [_KEY]


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
    assert state.clip_edit_video_playable and "cut" in state.clip_edit_tools
    # a publication's video kept in the upload store plays at once, no token
    CreativeState.pick_media.fn(state, "clip_videos", "pieces", r2_key)  # takes it out
    CreativeState.pick_media.fn(state, "clip_videos", "pieces", local_key)
    assert state.clip_edit_video_key == local_key
    assert not state.clip_edit_r2_pending
    assert state.clip_edit_video_playable and "cut" in state.clip_edit_tools


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
    assert state.clip_cut_end == 12.5 and state.clip_cut_max_units == 25
    assert state.clip_cut_end_shown == 12.04
    assert state.clip_card_title == "Tu video · 12 s"
    assert state.clip_cut_usage_text == "Usas 12 s de tu video."
    assert state.clip_cut_range_text == "Desde 0:00 · Hasta 0:12"
    assert state.clip_cut_end_clock == "0:12"
    recipe = state._clip_edit_media()["edit_recipe"]
    assert recipe["segments"][0]["end_s"] == 12.04  # type: ignore[index]


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
    assert "cut" not in state.clip_edit_tools


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
    assert "cut" not in state.clip_edit_tools
    assert not state.clip_cut_ready


def test_fast_motion_is_off_on_a_video_under_fifteen_seconds(editor_on: None) -> None:
    state = _measured(12.0)
    row = next(r for r in state.clip_edit_effect_rows if r["id"] == "camara_rapida")
    assert row["off"] == "true"
    assert row["reason"] == "Para usar cámara rápida tu video tiene que durar al menos 15 s."
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert state.clip_effect_ids == []
    state = _measured(15.0)
    row = next(r for r in state.clip_edit_effect_rows if r["id"] == "camara_rapida")
    assert row["off"] == "" and row["reason"] == ""


def test_fast_motion_that_cannot_reach_three_seconds_stays_out_of_the_recipe(
    editor_on: None,
) -> None:
    """Even the whole video at ×5 under 3 s (a marked fast motion on a video whose real
    length came in shorter): the line says so and `camara_rapida` leaves the recipe."""
    state = _measured(20.0)
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    CreativeState.report_clip_source.fn(state, _KEY, 12.0, 1080, 1920)  # measured again
    assert state.clip_fast_warning == (
        "Tu video duraría 2,4 s: muy poco para un reel. Quita la cámara rápida o usa un "
        "video más largo."
    )
    recipe = state._clip_edit_media()["edit_recipe"]
    assert [e["effect_id"] for e in recipe["effects"]] == []  # type: ignore[index]


def test_marking_fast_motion_says_what_it_did(editor_on: None) -> None:
    state = _measured(40.0)  # the whole proposal: 0–15, no cut of the owner's
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    assert state.clip_edit_notice == "Pusiste cámara rápida: usamos todo tu video a ×10."


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
