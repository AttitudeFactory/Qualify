"""UI-4: isolated drafts, stable identity, truthful availability and step history."""

from __future__ import annotations

import copy
import json
import types
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from reflex.istate.data import ReflexURL, RouterData, SessionData

from . import part_editor_provider
from . import part_editor_vm as vm
from .creative_state import CreativeState
from .test_reel_parts_state import planned

PHOTO = {"key": "t/a/photo.jpg", "name": "Producto", "role": "product"}
VIDEO = {"key": "t/a/own.mp4", "name": "Mi video"}
_LOAD_TENANT = "00000000-0000-0000-0000-000000000001"
_LOAD_BRAND = "00000000-0000-0000-0000-000000000002"


def close_load_state() -> CreativeState:
    state = editor(1)
    state._brand_id = _LOAD_BRAND
    state.router = RouterData(
        session=SessionData(session_id="mounted-socket"),
        url=ReflexURL("http://localhost/create?paso=2&parte=1"),
    )
    state.create_entered = True
    state._create_loaded_identity = (_LOAD_TENANT, _LOAD_BRAND, "mounted-socket")
    state._arm_editor_close_load()
    assert state._reel_editor_load_context
    return state


def close_url(
    state: CreativeState, path: str = "/create?paso=2", sid: str = "mounted-socket"
) -> None:
    state.router = RouterData(
        session=SessionData(session_id=sid), url=ReflexURL("http://localhost" + path)
    )


@pytest.mark.parametrize("action", ["save", "cancel", "back"])
def test_only_the_armed_editor_close_can_suppress_one_loading_remount(action: str) -> None:
    state = close_load_state()
    if action == "save":
        state.save_reel_part({"description": "Acercamos el producto"})
    elif action == "cancel":
        state.set_reel_edit_open(False)
    close_url(state)
    # Both route callbacks can precede the close-autofocus event and page loader.
    state.reconcile_reel_editor_route("?paso=2")
    state.reconcile_reel_editor_route("?paso=2")
    assert state._consume_editor_close_load(_LOAD_TENANT)
    assert not state._consume_editor_close_load(_LOAD_TENANT)
    state.edit_reel_part(state._reel_plan[0]["key"])
    assert state._reel_editor_load_context  # another explicit opening arms its own close


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selected_product_id", "another-product"),
        ("product_source", "stock"),
        ("gen_category", "script"),
        ("brief_kind", "script"),
        ("gen_mode", "discover"),
        ("parts_piece", 99),
        ("reel_analysis_id", "another-analysis"),
        ("gen_draft_id", "created-parent"),
        ("_brand_id", "another-brand"),
    ],
)
def test_editor_close_loading_guard_never_crosses_a_changed_context(field: str, value: Any) -> None:
    state = close_load_state()
    close_url(state)
    setattr(state, field, value)
    assert not state._consume_editor_close_load(_LOAD_TENANT)
    assert not state._reel_editor_load_context


@pytest.mark.parametrize(
    ("path", "sid", "tenant"),
    [
        ("/create?paso=2", "new-cold-or-reconnected-socket", _LOAD_TENANT),
        ("/create?paso=2", "", _LOAD_TENANT),
        ("/create?paso=2", "mounted-socket", "another-tenant"),
        ("/create?paso=3", "mounted-socket", _LOAD_TENANT),
        ("/create?paso=2&producto=another", "mounted-socket", _LOAD_TENANT),
        ("/create?paso=2&parte=1", "mounted-socket", _LOAD_TENANT),
        ("/create?paso=2&modo=variaciones", "mounted-socket", _LOAD_TENANT),
        ("/catalog?paso=2", "mounted-socket", _LOAD_TENANT),
    ],
)
def test_cold_session_real_navigation_or_extra_query_keeps_normal_loading(
    path: str, sid: str, tenant: str
) -> None:
    state = close_load_state()
    close_url(state, path, sid)
    assert not state._consume_editor_close_load(tenant)


def test_leaving_and_returning_to_the_same_piece_does_not_reuse_a_close_guard() -> None:
    state = close_load_state()
    state.leave_create_frame()
    close_url(state)
    state.create_entered = True
    assert not state._consume_editor_close_load(_LOAD_TENANT)
    state = close_load_state()
    state.create_entered = False
    close_url(state)
    assert not state._consume_editor_close_load(_LOAD_TENANT)


@pytest.mark.parametrize("entry", ["warm-close", "forward-open", "changed-context", "cold"])
async def test_close_and_forward_loads_revalidate_and_arm_only_the_ready_editor(
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
) -> None:
    from . import creative_state as module

    state = close_load_state()
    if entry == "warm-close":
        state.set_reel_edit_open(False)
        close_url(state)
    elif entry == "cold":
        state._clear_reel_edit()
        state.leave_create_frame()
        close_url(state)
    expected_loading = entry != "warm-close"
    calls: list[str] = []

    async def ids(self: object) -> tuple[UUID, UUID, UUID]:
        calls.append("session")
        assert state.create_loading is expected_loading
        return UUID(_LOAD_TENANT), UUID(_LOAD_BRAND), UUID(_LOAD_TENANT)

    async def voice(tenant: UUID, brand: UUID) -> bool:
        calls.append("voice")
        return False

    async def creations(self: object, tenant: UUID, brand: UUID) -> None:
        calls.append("creations")

    def read(name: str, result: Any):
        def inner(*args: object) -> Any:
            calls.append(name)
            assert state.create_loading is expected_loading
            if name == "routes" and entry == "changed-context":
                state._product_changed()  # while the normal Forward read was in flight
            return result

        return inner

    monkeypatch.setattr(CreativeState, "_session_ids", ids)
    monkeypatch.setattr(CreativeState, "_kit_voice_missing", staticmethod(voice))
    monkeypatch.setattr(CreativeState, "_refresh_creations", creations)
    monkeypatch.setattr(module, "brand_readiness", read("readiness", None))
    monkeypatch.setattr(module, "route_options_for", read("routes", ()))
    monkeypatch.setattr(module, "brand_media", read("media", []))
    monkeypatch.setattr(module, "brand_campaign_options", read("campaigns", []))
    monkeypatch.setattr(module, "brand_cta_patterns", read("phrases", ()))
    await CreativeState.load_create.fn(EditorProxy(state))
    assert set(calls) == {
        "session",
        "readiness",
        "routes",
        "voice",
        "media",
        "campaigns",
        "phrases",
        "creations",
    }
    assert not state.create_loading
    if entry == "forward-open":
        assert state.reel_edit_open and state._reel_editor_load_context
        state.set_reel_edit_open(False)
        close_url(state)
        assert state._consume_editor_close_load(_LOAD_TENANT)
    else:
        assert not state._reel_editor_load_context


def editor(index: int = 1) -> CreativeState:
    state = planned()
    state.clip_images = [PHOTO]
    state.edit_reel_part(state.reel_part_rows[index - 1]["key"])
    return state


def test_cancel_discards_text_mode_and_media_without_touching_plan() -> None:
    state = editor()
    before = copy.deepcopy(state._reel_plan)
    state.set_reel_edit_text("Mi descripción")
    state.set_reel_edit_mode("reference")
    state.remove_part_media("image", PHOTO["key"])
    assert state._reel_plan == before
    state.set_reel_edit_open(False)
    assert state._reel_plan == before and not state.reel_edit_open


def test_save_uses_exact_submitted_description_and_stable_key_after_reorder() -> None:
    state = editor(2)
    key = state.reel_edit_key
    state.move_reel_part_up(key)
    state.save_reel_part({"description": "Lo último escrito antes de tocar Guardar"})
    assert state._reel_plan[0]["key"] == key
    assert state._reel_plan[0]["plan"]["description"] == "Lo último escrito antes de tocar Guardar"
    assert not state.reel_edit_open


def test_inherited_photos_and_explicit_empty_are_different_and_parent_matches() -> None:
    state = editor(2)
    assert state.reel_edit_images == [PHOTO]
    state.save_reel_part()
    assert state._reel_plan[1]["plan"]["clip_image_keys"] is None
    assert state._media_inputs()["clip_image_keys"] == [PHOTO["key"]]
    state.edit_reel_part(state._reel_plan[1]["key"])
    state.remove_part_media("image", PHOTO["key"])
    state.save_reel_part()
    assert state._reel_plan[1]["plan"]["clip_image_keys"] == []
    state.edit_reel_part(state._reel_plan[1]["key"])
    assert state.reel_edit_images == [] and not state.reel_edit_inherit_images


def test_parent_keeps_opening_frame_as_part_photo() -> None:
    state = editor(2)
    state.clip_first_frame_key = PHOTO["key"]
    assert state._clip_reference_items() == []
    assert state._media_inputs()["clip_image_keys"] == [PHOTO["key"]]


def test_edit_own_source_requires_known_matching_duration_photos_and_no_audio() -> None:
    state = editor(2)  # original contains a person; own source is distinct
    assert state.reel_edit_options[0]["reason"].startswith("Aquí aparece una persona")
    state.reel_edit_videos = [VIDEO]
    assert "comprobar" in state.reel_edit_options[0]["reason"]
    state._reel_video_seconds = {VIDEO["key"]: 4.0}
    assert state.reel_edit_options[0]["reason"] == ""
    assert state.reel_edit_options[0]["label"] == "Tu video, con tu marca"
    state.set_reel_edit_mode("edit")
    state._reel_video_seconds = {VIDEO["key"]: 5.0}
    assert "debe durar 4 s" in state.reel_edit_save_reason
    state._reel_video_seconds = {VIDEO["key"]: 4.0}
    state.reel_edit_audios = [{"key": "audio", "name": "Audio"}]
    assert "quita el audio" in state.reel_edit_save_reason
    assert state.save_reel_part() is None and state.reel_edit_open
    state.set_reel_edit_mode("reference")
    state.save_reel_part()
    assert state._reel_plan[1]["plan"]["clip_audio_keys"] == ["audio"]
    assert state._reel_plan[0]["plan"].get("clip_audio_keys", []) == []


def test_new_extend_disabled_but_existing_extend_preserved_when_saving_description() -> None:
    state = editor(2)
    state.set_reel_edit_mode("extend")
    assert state.reel_edit_mode == "reference"
    assert state.reel_edit_options[2]["reason"]
    state = editor(4)
    assert state.reel_edit_mode == "extend" and state.reel_edit_save_reason == ""
    state.save_reel_part({"description": "Sigue el movimiento"})
    assert state._reel_plan[3]["plan"]["mode"] == "extend"


def test_old_extend_cannot_edit_public_cut_head_but_can_edit_distinct_own_video() -> None:
    state = editor(4)
    assert "Hazla nueva" in state.reel_edit_options[0]["reason"]
    state.reel_edit_videos = [VIDEO]
    state._reel_video_seconds = {VIDEO["key"]: 6.0}
    assert state.reel_edit_options[0]["reason"] == ""
    state.set_reel_edit_mode("edit")
    state.save_reel_part()
    assert state._reel_plan[3]["plan"]["mode"] == "edit"


def test_radio_tab_stop_follows_selection_or_first_enabled_without_changing_mode() -> None:
    state = editor(2)
    assert state.reel_edit_tab_mode == "reference"
    state.reel_edit_videos = [VIDEO]
    state._reel_video_seconds = {VIDEO["key"]: 4.0}
    state.set_reel_edit_mode("edit")
    assert state.reel_edit_tab_mode == "edit"
    state.set_reel_edit_mode("reference")
    assert state.reel_edit_tab_mode == "reference"
    state = editor(4)
    assert state.reel_edit_tab_mode == "reference" and state.reel_edit_mode == "extend"


def test_append_is_transactional_and_limit_counts_active_parts_only() -> None:
    state = editor(2)
    state.set_reel_edit_open(False)
    old = copy.deepcopy(state._reel_plan)
    state.add_reel_part()
    assert state._reel_plan == old and state.reel_edit_new and state.reel_edit_mode == "reference"
    assert state.reel_edit_title == "Parte 5 de 5"
    assert state.reel_edit_save_reason == vm.DESCRIPTION_REQUIRED
    state.save_reel_part({"description": "Cerramos mostrando el producto"})
    assert state.reel_parts_count == 5
    state.add_reel_part()
    state.save_reel_part({"description": "Otra parte"})
    assert state.reel_parts_count == 6 and state.reel_add_reason == vm.MAX_PARTS_TEXT
    assert state.add_reel_part() is None and state.reel_parts_notice == vm.MAX_PARTS_TEXT


def test_removal_history_survives_append_and_restore_at_six_refuses() -> None:
    state = editor(2)
    state.set_reel_edit_open(False)
    state.remove_reel_part(state._reel_plan[0]["key"])
    for n in range(3):
        state.add_reel_part()
        state.save_reel_part({"description": f"Parte nueva {n}"})
    assert state.reel_parts_count == 6 and len(state._reel_plan_before) == 7
    state.undo_reel_part()
    assert state.reel_parts_count == 6 and len(state._reel_plan_before) == 7
    assert state.reel_parts_notice == vm.MAX_PARTS_TEXT


def test_step_five_description_action_opens_correct_part_and_second_step() -> None:
    state = editor(2)
    state.set_reel_edit_open(False)
    key = state._reel_plan[2]["key"]
    state._reel_plan[2]["plan"].update(description="", notices=["describe_it"])
    state.gen_step = 3
    state.describe_reel_part()
    assert state.gen_step == 0 and state.reel_edit_key == key
    state.save_reel_part({"description": "Muestra el vaso"})
    assert not state.reel_missing_description


def test_route_reconciles_back_forward_and_invalid_part_without_changing_wrong_part() -> None:
    state = editor(2)
    key = state.reel_edit_key
    state.reconcile_reel_editor_route("?paso=2")
    assert not state.reel_edit_open and state.create_step_n == 2
    state.reconcile_reel_editor_route("?paso=2&parte=2")
    assert state.reel_edit_key == key and state.reel_edit_open
    state.reconcile_reel_editor_route("?paso=2&parte=99")
    assert not state.reel_edit_open
    state.reconcile_reel_editor_route("?paso=3&parte=2")
    assert state.create_step_n == 3 and not state.reel_edit_open


@pytest.mark.parametrize("raw", ["-1", "0", "1.0", "٢", "x", "7", ""])
def test_invalid_query_never_resolves_a_part(raw: str) -> None:
    assert vm.position(raw, 6) == 0


def test_existing_frontend_factory_renders_a_real_accessible_form() -> None:
    from .content_generator import _clip_parts_block

    rendered = str(_clip_parts_block())
    assert "q-part-editor-form" in rendered and "radiogroup" in rendered
    assert "aria-disabled" in rendered and "aria-describedby" in rendered
    assert "Juntar con la siguiente" in rendered


def test_parent_creation_freezes_an_open_draft_without_losing_owner_edits() -> None:
    state = editor(2)
    before = copy.deepcopy(state._reel_plan)
    state.set_reel_edit_text("Mi cambio todavía abierto")
    state.gen_draft_id = "created-in-another-event"
    assert state.save_reel_part() is None
    assert state._reel_plan == before and state.reel_edit_open
    assert state.reel_edit_text == "Mi cambio todavía abierto"
    assert state.reel_edit_error == state.reel_plan_edit_reason
    state.set_reel_edit_open(False)
    assert state.edit_reel_part(before[0]["key"]) is None
    assert state.add_reel_part() is None


@pytest.mark.parametrize("kind", ["video", "audio"])
def test_preserved_extend_cannot_accept_own_media_until_explicitly_made_new(kind: str) -> None:
    state = editor(4)
    before = copy.deepcopy(state._reel_plan)
    setattr(
        state,
        "reel_edit_videos" if kind == "video" else "reel_edit_audios",
        [{"key": "my-file", "name": "Mi archivo"}],
    )
    assert "elige hacer esta parte nueva" in state.reel_edit_save_reason
    assert state.save_reel_part() is None and state._reel_plan == before
    assert state.reel_edit_mode == "extend"
    state.set_reel_edit_mode("reference")
    state.save_reel_part()
    assert state._reel_plan[3]["plan"]["mode"] == "reference"


def test_a_new_manual_part_can_edit_own_video_before_first_generation() -> None:
    state = editor(2)
    state.set_reel_edit_open(False)
    state.add_reel_part()
    state.reel_edit_videos = [VIDEO]
    state._reel_video_seconds = {VIDEO["key"]: 5.0}
    state.set_reel_edit_mode("edit")
    assert state.reel_edit_mode == "edit"
    state.save_reel_part({"description": "Mi video con el vaso"})
    assert state._reel_plan[-1]["plan"]["analysis_id"] is None
    assert state._reel_plan[-1]["plan"]["clip_video_keys"] == [VIDEO["key"]]
    state.move_reel_part_up(state._reel_plan[-1]["key"])
    assert state._reel_plan[2]["plan"]["mode"] == "edit"


def test_full_removed_history_survives_reorder_and_undo_restores_only_last_removal() -> None:
    state = editor(2)
    state.set_reel_edit_open(False)
    first, second = [e["key"] for e in state._reel_plan[:2]]
    state.remove_reel_part(first)
    state.remove_reel_part(second)
    assert [e["key"] for e in state._reel_removed] == [first, second]
    state.undo_reel_part()
    assert [e["key"] for e in state._reel_removed] == [first]
    state.move_reel_part_down(second)
    assert [e["key"] for e in state._reel_removed] == [first]


class EditorProxy:
    """The state's lock and authenticated tenant, without a Reflex server."""

    def __init__(self, state: CreativeState) -> None:
        object.__setattr__(self, "state", state)

    async def __aenter__(self) -> EditorProxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_state(self, cls: type) -> SimpleNamespace:
        return SimpleNamespace(session_tenant_id="00000000-0000-0000-0000-000000000001")

    def __getattr__(self, name: str) -> Any:
        if name == "_read_part_merge":
            return types.MethodType(CreativeState._read_part_merge, self)
        return getattr(self.state, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self.state, name, value)


async def test_metadata_programming_error_is_not_masked(monkeypatch: pytest.MonkeyPatch) -> None:
    state = editor(2)
    state.reel_edit_videos = [VIDEO]

    def broken(*args: object) -> None:
        raise TypeError("a programming mistake")

    monkeypatch.setattr(part_editor_provider, "video_seconds", broken)
    with pytest.raises(TypeError):
        await CreativeState.inspect_part_videos.fn(EditorProxy(state))


async def test_pending_merge_cannot_overwrite_newer_owner_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = editor(1)
    state._reel_edit_draft["plan"]["seconds"] = 2

    def delayed(
        tenant: UUID, current: dict[str, Any], following: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        merged = copy.deepcopy(current)
        merged["plan"]["seconds"] = 9
        state.set_reel_edit_text("Texto que escribí mientras comprobabas")
        return merged, ""

    monkeypatch.setattr(part_editor_provider, "merge_entries", delayed)
    await CreativeState.merge_reel_part.fn(EditorProxy(state))
    assert state.reel_edit_text == "Texto que escribí mientras comprobabas"
    assert state._reel_edit_draft["plan"]["seconds"] == 2
    assert not state._reel_edit_merge_key


async def test_product_change_invalidates_pending_merge_and_every_new_drawer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = editor(1)
    state._reel_edit_draft["plan"]["seconds"] = 2
    old_epoch = state._reel_edit_epoch

    def delayed(
        tenant: UUID, current: dict[str, Any], following: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        state._product_changed()  # same reel plan remains; the editing context changes
        return current, ""

    monkeypatch.setattr(part_editor_provider, "merge_entries", delayed)
    await CreativeState.merge_reel_part.fn(EditorProxy(state))
    assert state._reel_edit_epoch > old_epoch and not state.reel_edit_open
    assert not state._reel_edit_draft and not state._reel_edit_merge_key
    state.add_reel_part()
    assert state.reel_edit_open and state.reel_edit_new
    state._forget_reel_analysis()
    assert not state.reel_edit_open and not state._reel_edit_draft


async def test_old_probe_cannot_apply_after_same_key_reopens_for_another_product(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = editor(2)
    key = state.reel_edit_key
    state.reel_edit_videos = [VIDEO]

    def delayed(tenant: UUID, video: str) -> float:
        state._product_changed()
        state.edit_reel_part(key)
        state.reel_edit_videos = [VIDEO]
        return 4.0

    monkeypatch.setattr(part_editor_provider, "video_seconds", delayed)
    await CreativeState.inspect_part_videos.fn(EditorProxy(state))
    assert state.reel_edit_open and state.reel_edit_key == key
    assert VIDEO["key"] not in state._reel_video_seconds


# -- UX review 2026-11-12 ----------------------------------------------------------------


def test_extend_reason_says_only_what_applies_to_the_part() -> None:
    entry = vm.new_entry()
    first, later = (
        vm.options(entry, at, images=[PHOTO], videos=[], audios=[], durations={})[2]["reason"]
        for at in (1, 2)
    )
    assert first == "La primera parte no tiene una anterior."
    assert later == "Por ahora no está disponible. Hazla nueva."


def test_own_media_section_opens_by_itself_only_without_an_original_video() -> None:
    state = editor(1)  # a reel's analysed part: keeping its original needs no own video
    assert state._reel_edit_draft["plan"].get("analysis_id")
    assert not state.reel_edit_more
    state.set_reel_edit_open(False)
    state.add_reel_part()  # no original: an own video is the one way to keep a video
    assert state.reel_edit_more
    assert vm.MORE_LABEL == "Video o audio tuyo"
    assert "Agrega un video tuyo en «Video o audio tuyo», más abajo." == vm.edit_reason(
        state._reel_edit_draft, images=[PHOTO], videos=[], audios=[], durations={}
    )


def test_media_limits_name_the_count_and_the_way_out() -> None:
    assert vm.media_limit_text("image") == (
        "Ya tienes 9 fotos, el máximo. Quita una para agregar otra."
    )
    assert vm.media_limit_text("video") == (
        "Ya tienes 3 videos, el máximo. Quita uno para agregar otro."
    )
    assert vm.media_limit_text("audio") == (
        "Ya tienes 3 audios, el máximo. Quita uno para agregar otro."
    )


def test_a_click_on_the_aria_disabled_guardar_is_ignored() -> None:
    state = editor(1)
    before = copy.deepcopy(state._reel_plan)
    state.set_reel_edit_text("")
    assert state.reel_edit_save_reason == vm.DESCRIPTION_REQUIRED
    assert state.save_reel_part() is None
    assert state._reel_plan == before and state.reel_edit_open
    assert state.reel_edit_error == ""  # the reason is already shown under «Guardar»


def test_sheet_view_copy_and_guardar_stays_focusable() -> None:
    from .content_generator import _clip_parts_block

    rendered = str(_clip_parts_block())
    assert vm.SHEET_HELP == "Cambia solo esta parte; las demás quedan igual."

    def js(text: str) -> str:  # the compiled JSX escapes every non-ASCII letter
        return json.dumps(text)[1:-1]

    assert js(vm.SHEET_HELP) in rendered
    assert f'"{vm.MORE_LABEL}"' in rendered and js('"Más opciones"') not in rendered
    guardar = rendered[: rendered.index('"Guardar")')]
    guardar = guardar[guardar.rindex("RadixThemesButton") :]
    assert '"aria-disabled"' in guardar and "disabled:" not in guardar
    assert '"aria-describedby":"q-part-save-reason"' in guardar
    assert js("Mover antes") not in rendered and js("Mover después") not in rendered
    # each «Quitar» names its file after its visible label (WCAG 2.5.3)
    assert all(f'"Quitar {kind} "' in rendered for kind in ("foto", "video", "audio"))


async def test_joining_with_the_next_part_confirms_in_info_tone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = editor(1)
    state._reel_edit_draft["plan"]["seconds"] = 2

    def merged(
        tenant: UUID, current: dict[str, Any], following: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        joined = copy.deepcopy(current)
        joined["plan"]["seconds"] = 6
        return joined, ""

    monkeypatch.setattr(part_editor_provider, "merge_entries", merged)
    await CreativeState.merge_reel_part.fn(EditorProxy(state))
    assert state.reel_edit_notice == "Listo: las partes 1 y 2 quedan juntas al guardar."
    assert state.reel_edit_error == ""
    state.set_reel_edit_open(False)
    assert state.reel_edit_notice == ""


def test_quitar_stops_at_the_removed_history_cap_with_a_clear_way_out() -> None:
    """The parent keeps at most `PARTS_REMOVED_MAX` removed parts (`too_many` beyond):
    «Quitar» says so and points to «Cambiar» instead of failing at «Crear»."""
    state = planned()
    keep = copy.deepcopy(state._reel_plan)
    state._reel_removed = [copy.deepcopy(keep[0]) for _ in range(vm.MAX_REMOVED)]
    assert state.remove_reel_part(keep[1]["key"]) is None
    assert state._reel_plan == keep and len(state._reel_removed) == vm.MAX_REMOVED
    assert state.reel_parts_notice == (
        "Ya no puedes quitar más partes de este video. "
        "Toca «Cambiar» para hacer esta parte de otra forma."
    )
    state._reel_removed = state._reel_removed[1:]  # one below the cap: «Quitar» works
    assert state.remove_reel_part(keep[1]["key"]) is not None
    assert len(state._reel_removed) == vm.MAX_REMOVED


def test_a_part_without_an_original_names_the_edit_form_after_the_owners_video() -> None:
    entry = vm.new_entry()  # no analysed original: «Igual al original» would be untrue
    (edit,) = [
        o
        for o in vm.options(entry, 2, images=[PHOTO], videos=[], audios=[], durations={})
        if o["mode"] == "edit"
    ]
    assert edit["label"] == "Tu video, con tu marca"
    assert edit["reason"] == "Agrega un video tuyo en «Video o audio tuyo», más abajo."
    state = editor(2)  # a reel's part keeps its original's name
    assert state.reel_edit_options[0]["label"] != "Tu video, con tu marca"


def test_the_way_out_buttons_name_the_part() -> None:
    assert vm.describe_action([2]) == "Escribir qué pasa en la parte 2"
    assert vm.describe_action([2, 4]) == "Escribir qué pasa"
    assert vm.change_action([3, 5]) == "Cambiar la parte 3"
    assert vm.MAX_PARTS_TEXT == (
        "Tu video ya tiene 6 partes, el máximo. Quita o junta una para añadir otra."
    )
    from . import reel_parts_vm

    assert reel_parts_vm.FOOT_UNSUPPORTED == (
        "Hay partes que siguen a la anterior. Hazlas nuevas para crear tu video."
    )
    from .test_reel_parts_state import planned as plan_state

    state = plan_state()
    state._reel_plan[1]["plan"]["mode"] = "extend"
    assert state.reel_change_label == "Cambiar la parte 2"


@pytest.mark.parametrize(
    ("reason", "text"),
    [
        ("merge_photos", "Usa las mismas fotos en las dos partes para juntarlas."),
        ("merge_description", vm.MERGE_DESCRIPTION_TEXT),
        ("merge_unavailable", vm.MERGE_UNAVAILABLE_TEXT),
        ("anything_else", vm.MERGE_UNAVAILABLE_TEXT),
    ],
)
def test_each_merge_refusal_has_its_own_words(reason: str, text: str) -> None:
    assert vm.merge_refusal_text(reason) == text


def test_merging_parts_with_different_photos_says_to_use_the_same_ones(monkeypatch) -> None:
    from qualify_api.referentes import reel_analysis

    reel = types.SimpleNamespace(id=UUID(int=7))
    monkeypatch.setattr(reel_analysis, "get_analysis", lambda *a: reel)
    current = {
        "plan": {
            "seconds": 2,
            "analysis_id": str(reel.id),
            "shot_indexes": [0],
            "clip_image_keys": [PHOTO["key"]],
        }
    }
    following = {"plan": {"seconds": 3, "analysis_id": str(reel.id), "shot_indexes": [1]}}
    merged, reason = part_editor_provider.merge_entries(UUID(_LOAD_TENANT), current, following)
    assert merged is None
    assert reason == vm.MERGE_PHOTOS_TEXT


@pytest.mark.parametrize(
    ("kind", "field", "label"),
    [
        ("image", "reel_edit_images", "Quitar foto "),
        ("video", "reel_edit_videos", "Quitar video "),
        ("audio", "reel_edit_audios", "Quitar audio "),
    ],
)
def test_every_held_file_uploaded_or_from_the_gallery_can_be_removed(
    kind: str, field: str, label: str
) -> None:
    """Each kind's list draws a «Quitar foto/video/audio <nombre>» per held file, whatever
    its source (an upload from «Subir» or a pick from Galería), and the one handler
    takes either out without touching the plan."""
    from .content_generator import _part_media_editor

    rendered = str(_part_media_editor(kind))
    assert f'"aria-label":("{label}"+' in rendered and "remove_part_media" in rendered
    state = editor(1)
    before = copy.deepcopy(state._reel_plan)
    uploaded = {"key": f"t/a/subido.{kind}", "name": "subido", "source": "upload"}
    picked = {"key": f"t/a/galeria.{kind}", "name": "galeria", "source": "brandcat"}
    setattr(state, field, [uploaded, picked])
    state.remove_part_media(kind, uploaded["key"])
    assert getattr(state, field) == [picked]
    state.remove_part_media(kind, picked["key"])
    assert getattr(state, field) == []
    assert state._reel_plan == before


def test_disabled_forms_dim_and_cambiar_sits_at_the_card_foot() -> None:
    """The quiet look of an aria-disabled form and «Cambiar» at the foot are CSS hooks:
    the view sets them, the stylesheet targets them (opacity, not the reason)."""
    from pathlib import Path

    from .content_generator import _clip_parts_block, _part_item

    assert "q-choice-reason" in str(_clip_parts_block())
    card = str(_part_item(CreativeState.reel_part_rows[0]))
    assert '"q-part-change"' in card and '["marginTop"] : "auto"' in card
    css = (Path(__file__).parent.parent / "assets" / "qualify.css").read_text(encoding="utf-8")
    dim = '[aria-disabled="true"] :is(svg, .rt-Text:not(.q-choice-reason))'
    # only the sheet's cards: `ui.choice_card(disabled=True)` already fades as a whole
    assert ".q-part-choice" + dim in css and ".q-choice-card" + dim not in css
    assert '.q-choice-card[aria-disabled="true"] .q-choice-reason' not in css
    assert "q-part-choice" in str(_clip_parts_block())
    assert ".q-part-card > .q-part-change {\n  margin-top: auto;" in css


# -- «Quitar» on every kind and every origin (Deivid's live test, 2026-11-12) ------------

_FIELDS = {"image": "reel_edit_images", "video": "reel_edit_videos", "audio": "reel_edit_audios"}
_SAVED = {"image": "clip_image_keys", "video": "clip_video_keys", "audio": "clip_audio_keys"}
_TARGET = {"image": "part_images", "video": "part_videos"}


def _rendered_remove_payload(kind: str, file: dict[str, str]) -> tuple[str, str]:
    """What the rendered «Quitar» sends: its compiled event names `kind` as a literal and
    `key` as the list item's own `key` — read from the render, not assumed."""
    from .content_generator import _part_media_editor

    rendered = str(_part_media_editor(kind))
    sent = '.remove_part_media", ({ ["kind"] : "' + kind + '", ["key"] : file_rx_state_?.["key"] })'
    assert sent in rendered
    return kind, file["key"]


async def _add_from(state: CreativeState, kind: str, origin: str, monkeypatch: Any) -> str:
    """Put one file of `kind` in the open sheet the way the screen does it."""
    key = f"t/a/{origin}-{kind}.bin"
    if origin == "subir":

        async def saved(self: CreativeState, files: list[Any]) -> list[tuple[str, str]]:
            return [(key, f"slide-1.{kind}")]

        async def signed_in(self: CreativeState, cls: type) -> SimpleNamespace:
            return SimpleNamespace(session_tenant_id=_LOAD_TENANT)

        monkeypatch.setattr(CreativeState, "_save_uploads", saved)
        monkeypatch.setattr(CreativeState, "get_state", signed_in)
        monkeypatch.setattr(part_editor_provider, "video_seconds", lambda tenant, k: 5.0)
        handler = {
            "image": CreativeState.handle_part_image_uploads,
            "video": CreativeState.handle_part_video_uploads,
            "audio": CreativeState.handle_part_audio_uploads,
        }[kind]
        assert await handler.fn(state, [object()]) is None  # nothing chained (see state)
        return key
    if origin == "galeria":  # the chosen product's files («De la Galería»)
        if kind == "image":
            state._selected_product_photo_keys = [key]
        else:
            state._selected_product_video_keys = [key]
        state.pick_media(_TARGET[kind], "catalog", key)
    elif origin == "galeria-marca":  # the brand's Galería tab
        field = "photo_keys" if kind == "image" else "video_keys"
        state.catalog_items = [{"name": "Vaso", field: key}]
        state.pick_media(_TARGET[kind], "brandcat", key)
    elif origin == "publicaciones":
        state.piece_items = [{"key": key, "label": "Publicación", "media_type": kind}]
        state.pick_media(_TARGET[kind], "pieces", key)
    return key


_CASES = [
    *((kind, "subir") for kind in ("image", "video", "audio")),
    *(
        (kind, origin)
        for kind in ("image", "video")
        for origin in ("galeria", "galeria-marca", "publicaciones")
    ),
]


@pytest.mark.parametrize(("kind", "origin"), _CASES)
async def test_quitar_takes_out_every_kind_from_every_origin(
    kind: str, origin: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fotos, videos y audios — from «Subir», Galería (product or brand) or
    Publicaciones (audio has only «Subir») — go with the payload the rendered «Quitar»
    sends: out of the sheet's list and out of the part Guardar keeps."""
    state = editor(2)
    field = _FIELDS[kind]
    key = await _add_from(state, kind, origin, monkeypatch)
    if (kind, origin) == ("video", "subir"):  # its length is read in the upload itself
        assert state._reel_video_seconds[key] == 5.0
    held = getattr(state, field)
    file = next(item for item in held if item["key"] == key)
    state.remove_part_media(*_rendered_remove_payload(kind, file))
    assert all(item["key"] != key for item in getattr(state, field))
    target = state.reel_edit_key
    state.set_reel_edit_mode("reference")
    state.save_reel_part({"description": "Muestra el vaso"})
    saved = next(e for e in state._reel_plan if e["key"] == target)["plan"]
    assert key not in (saved.get(_SAVED[kind]) or [])


def test_the_inherited_product_photos_can_be_taken_out_too() -> None:
    """The «Foto de la Galería» the sheet starts with (the clip's photos) is removable
    like an added one, and Guardar keeps the cleared list, not the inherited one."""
    state = editor(2)
    assert state.reel_edit_inherit_images and state.reel_edit_images[0]["key"] == PHOTO["key"]
    state.remove_part_media(*_rendered_remove_payload("image", state.reel_edit_images[0]))
    assert state.reel_edit_images == [] and not state.reel_edit_inherit_images
    target = state.reel_edit_key
    state.set_reel_edit_mode("reference")
    state.save_reel_part({"description": "Muestra el vaso"})
    saved = next(e for e in state._reel_plan if e["key"] == target)["plan"]
    assert saved["clip_image_keys"] == []


async def test_an_upload_clears_an_old_merge_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    state = editor(1)
    state._reel_edit_draft["plan"]["seconds"] = 2
    assert state.reel_merge_shown
    state.reel_merge_reason = "No pudimos comprobar estas partes."

    async def saved(self: CreativeState, files: list[Any]) -> list[tuple[str, str]]:
        return [("t/a/subida.jpg", "subida.jpg")]

    monkeypatch.setattr(CreativeState, "_save_uploads", saved)
    assert await CreativeState.handle_part_image_uploads.fn(state, [object()]) is None
    assert state.reel_merge_reason == ""
