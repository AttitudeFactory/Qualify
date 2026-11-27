"""ED-07 (m-25026638, ADR 50 §13): the «parte con IA» on the Clip's timeline — the state
(`CreativeState`'s AI-part block), what the preview plays and what the brief carries.
Offline: a standalone `CreativeState`, handlers called through `.fn`, the server's own
contract (`validate_brief_recipe`) as the judge. Nothing is created or paid."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.video_pipeline import ai_parts as contract_ai
from qualify_api.creative.video_pipeline import validate_brief_recipe
from qualify_creative.schemas import AI_PART_KIND

from . import ai_block_vm as ai_vm
from . import clip_editor_vm
from . import clip_joins_vm as joins
from . import editor_preview_contract as contract
from .creative_provider import build_brief
from .creative_state import CreativeState
from .ui import timeline_vm

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND = UUID("c0000000-0000-4000-8000-000000000003")
_ONE = f"uploads/{_TENANT}/clip/uno.jpg"
_TWO = f"uploads/{_TENANT}/clip/dos.jpg"


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
    state._clip_session_tenant = str(_TENANT)  # as `remember_clip_tenant` does on mount
    return state


def _kinds(state: CreativeState) -> list[str]:
    return [str(item["kind"]) for item in state._clip_tl_media()]


def _add(state: CreativeState, at_s: float = 0.0) -> str:
    """«Agregar → Parte con IA» with the marker at `at_s`; the new block's id."""
    state.clip_edit_playhead = at_s
    CreativeState.open_clip_flow.fn(state, ai_vm.ADD_KEY)
    return state.clip_edit_block


def _described(state: CreativeState, block: str, words: str = "Una mano acerca el vaso") -> None:
    state.clip_edit_block = block
    CreativeState.set_clip_ai_description.fn(state, block, words)


# -- the switch ----------------------------------------------------------------------------


@pytest.mark.usefixtures("ai_off")
def test_switch_off_nothing_is_new_and_the_clip_is_as_before() -> None:
    before = _state()
    rows_before = before._clip_tl_rows()
    media_before = before._clip_edit_media()

    state = _state()
    assert not state.clip_ai_on
    assert state.clip_ai_add_off
    assert ai_vm.add_options(timeline_vm.ADD_OPTIONS, on=ai_vm.switch_on()) == (
        timeline_vm.ADD_OPTIONS
    )
    assert CreativeState.open_clip_flow.fn(state, ai_vm.ADD_KEY) == []
    assert state.clip_ai_parts == [] and state.clip_edit_block == ""
    # a part left in the state (the switch turned off meanwhile) is never on the timeline
    state.clip_ai_parts = [{"uid": "p1", "plan": ai_vm.new_ai_block(0)[1]}]
    state.clip_sequence = [_ONE, ai_vm.token("p1"), _TWO]
    assert _kinds(state) == ["photo", "photo"]
    assert state._clip_tl_rows() == rows_before
    assert state._clip_edit_media() == media_before
    assert "ai_parts" not in state._clip_edit_media()
    assert state.clip_ai_review_shown is False
    assert state.clip_ai_chosen == {}
    assert state._clip_ai_create_off() == ""
    # the order the Clip keeps reads its files only
    assert state._clip_order_keys() == [_ONE, _TWO]


@pytest.mark.usefixtures("ai_on")
def test_switch_on_offers_parte_con_ia_last_in_agregar() -> None:
    options = ai_vm.add_options(timeline_vm.ADD_OPTIONS, on=ai_vm.switch_on())
    # last: the other options keep their places (and their `--q-orbit-i`) as on main
    assert [key for key, _icon, _text in options] == [
        *(key for key, _icon, _text in timeline_vm.ADD_OPTIONS),
        ai_vm.ADD_KEY,
    ]
    assert (ai_vm.ADD_KEY, "sparkles", "Parte con IA") in options
    assert all(len(text) <= 16 for _key, _icon, text in options)  # the orbit's pill
    assert _state().clip_ai_on


# -- «Agregar → Parte con IA» ----------------------------------------------------------------


@pytest.mark.usefixtures("ai_on")
def test_agregar_puts_it_at_the_marker_and_opens_its_panel() -> None:
    state = _state()
    block = _add(state, 0.5)  # the marker on the first photo: it goes after it
    assert ai_vm.is_token(block)
    assert _kinds(state) == ["photo", "ai", "photo"]
    (part,) = state.clip_ai_parts
    assert part["plan"]["mode"] == "reference"
    assert part["plan"]["seconds"] == 5
    assert (part["plan"]["mode_rule_version"], part["plan"]["mode_reason"]) == (1, "no_source")
    assert state.clip_edit_notice.startswith(ai_vm.ADDED_LINE)
    row = state.clip_ai_chosen
    assert row["name"] == "Parte con IA 1"
    assert row["full"] == "Nueva, con tu marca"  # no product chosen
    assert row["reason"] == "Nueva, con tu producto."  # EF-09's words for `no_source`
    assert row["seconds_text"] == "5 s"
    assert row["missing"] == "Falta contar qué pasa en la parte con IA 1."
    assert row["try_reason"] == ai_vm.TRY_OFF_LINE  # until PR 2
    # the track's row: the AI block, its badge, its line, no handles
    media_rows = [r for r in state.clip_tl_media_rows if r["kind"] == "ai"]
    (ai_row,) = media_rows
    assert ai_row["label"] == "Parte con IA 1"
    assert ai_row["ai_badge"] == "Nueva"
    assert ai_row["ai_state"] == "plan"
    assert ai_row["ai_secs"] == "5 s"
    assert ai_row["handles"] == ""
    assert ai_row["name"] == "Parte con IA 1, Nueva, de 0:02 a 0:07, sin crear"
    # every row reads the same AI keys (the track's foreach)
    assert all("ai_state" in r for r in state._clip_tl_rows())


@pytest.mark.usefixtures("ai_on")
def test_a_new_part_takes_what_fits_under_60_s_and_8_blocks_say_why() -> None:
    state = _state()
    state.clip_images = [
        {"key": f"uploads/{_TENANT}/clip/{n}.jpg", "name": f"{n}.jpg", "source": "upload"}
        for n in range(8)
    ]
    state.clip_sequence = [i["key"] for i in state.clip_images]
    assert state.clip_ai_add_off
    assert state.clip_tl_add_note == clip_editor_vm.FULL_LINE
    assert CreativeState.open_clip_flow.fn(state, ai_vm.ADD_KEY) == []
    assert state.clip_ai_parts == []


@pytest.mark.usefixtures("ai_on")
def test_six_ai_parts_are_the_most() -> None:
    state = _state()
    state.clip_images = []
    state.clip_sequence = []
    for _ in range(6):
        _add(state, 999.0)
    assert len(state.clip_ai_parts) == 6
    assert state.clip_ai_add_off
    assert state.clip_tl_add_note == ai_vm.FULL_AI_LINE
    # a Clip made only of AI parts is valid (contract §3, Deivid answer 3)
    for item in state._clip_tl_media():
        _described(state, str(item["id"]))
    assert state._clip_ai_problems() == []


# -- the panel ---------------------------------------------------------------------------------


@pytest.mark.usefixtures("ai_on")
def test_the_mode_options_say_why_and_only_nueva_without_a_reel() -> None:
    state = _state()
    block = _add(state, 0.5)
    options = {o["mode"]: o for o in state.clip_ai_options}
    assert options["reference"]["chosen"] == "1" and options["reference"]["reason"] == ""
    assert options["edit"]["reason"] == contract_ai.ai_part_text("edit_needs_reel_window")
    assert options["extend"]["reason"] != ""  # a photo before it, or the switch off
    plan = dict(state.clip_ai_parts[0]["plan"])
    CreativeState.set_clip_ai_mode.fn(state, "edit")  # refused: its reason stays
    assert state.clip_ai_parts[0]["plan"] == plan
    assert state.clip_edit_block == block


@pytest.mark.usefixtures("ai_on")
def test_seconds_are_whole_from_1_to_10() -> None:
    state = _state()
    block = _add(state, 0.5)
    for _ in range(7):
        CreativeState.step_clip_ai_seconds.fn(state, 1)
    assert state.clip_ai_parts[0]["plan"]["seconds"] == 10
    assert state.clip_ai_chosen["plus_reason"] == ai_vm.PLUS_OFF_MAX
    assert state.clip_edit_notice == "La parte con IA 1 ahora dura 10 s."
    media = state._clip_tl_media()
    assert media[1]["src_end"] == 10.0
    for _ in range(12):
        CreativeState.step_clip_ai_seconds.fn(state, -1)
    assert state.clip_ai_parts[0]["plan"]["seconds"] == 1
    assert state.clip_ai_chosen["minus_reason"] == ai_vm.MINUS_OFF
    assert state.clip_ai_chosen["seconds_note"].startswith("Se crea de 4 s")
    assert state.clip_edit_block == block


@pytest.mark.usefixtures("ai_on")
def test_description_and_photos_are_kept_at_once() -> None:
    state = _state()
    block = _add(state, 0.5)
    _described(state, block, "  Una mano acerca el vaso  ")
    assert ai_vm.plans(state.clip_ai_parts)[0]["description"] == "Una mano acerca el vaso"
    assert state.clip_ai_chosen["missing"] == ""
    assert [p["on"] for p in state.clip_ai_photos] == ["1", "1"]  # none chosen = the Clip's
    CreativeState.toggle_clip_ai_photo.fn(state, _TWO)
    assert state.clip_ai_parts[0]["plan"]["clip_image_keys"] == [_ONE]
    assert [p["on"] for p in state.clip_ai_photos] == ["1", ""]
    CreativeState.toggle_clip_ai_photo.fn(state, "uploads/otro/negocio.jpg")  # not the Clip's
    assert state.clip_ai_parts[0]["plan"]["clip_image_keys"] == [_ONE]


@pytest.mark.usefixtures("ai_on")
def test_leaving_nueva_drops_the_guide() -> None:
    state = _state()
    block = _add(state, 0.5)
    plan, why = ai_vm.with_guide(state.clip_ai_parts[0]["plan"], f"uploads/{_TENANT}/baile.mp4")
    assert why == ""
    state._clip_ai_put(block, plan)
    assert [g["kind"] for g in state.clip_ai_guides] == ["video"]
    plan = ai_vm.with_owner_mode(state.clip_ai_parts[0]["plan"], "extend")
    assert (plan["clip_video_keys"], plan["clip_audio_keys"]) == ([], [])
    _wrong, why = ai_vm.with_guide(plan, f"uploads/{_TENANT}/baile.webm")
    assert why == ai_vm.GUIDE_NEEDS_NEW
    _wrong, why = ai_vm.with_guide(state.clip_ai_parts[0]["plan"], "x/baile.webm")
    assert why == contract_ai.ai_part_text("ai_part_guide_type")


# -- move, remove ------------------------------------------------------------------------------


@pytest.mark.usefixtures("ai_on")
def test_it_moves_by_dragging_and_its_place_is_kept() -> None:
    state = _state()
    block = _add(state, 0.5)
    state._clip_move_media(block, 0)
    assert _kinds(state) == ["ai", "photo", "photo"]
    assert state.clip_edit_notice == "Moviste la parte con IA 1."
    # a photo added later never moves it
    state.clip_images = [
        *state.clip_images,
        {"key": f"uploads/{_TENANT}/clip/tres.jpg", "name": "tres.jpg", "source": "upload"},
    ]
    CreativeState._sync_clip_frames(state)
    assert _kinds(state)[0] == "ai"
    assert state._clip_order_keys()[0] == block


@pytest.mark.usefixtures("ai_on")
def test_quitar_takes_the_part_and_its_entry() -> None:
    state = _state()
    first = _add(state, 0.5)
    second = _add(state, 999.0)
    state.clip_edit_block = first
    CreativeState.clip_block_action.fn(state, clip_editor_vm.REMOVE)
    assert [p["uid"] for p in state.clip_ai_parts] == [ai_vm.uid_of(second)]
    assert first not in state.clip_sequence
    assert _kinds(state) == ["photo", "photo", "ai"]
    assert state.clip_edit_notice == "Quitaste la parte con IA 1."
    # the one left points at entry 0 now
    media = state._clip_edit_media()
    assert [s.get("key") for s in media["segments"]][-1] == "ai_part:0"  # type: ignore[index]


# -- the preview, the recipe and the brief ----------------------------------------------------


def _between_two_photos(monkeypatch: pytest.MonkeyPatch) -> tuple[CreativeState, str]:
    """Deivid's case: an AI part between two photos, with a text and «Humo» over it and
    «Fundido» as it comes in."""
    monkeypatch.setenv(joins.JOINS_SWITCH, "on")
    state = _state()
    block = _add(state, 0.5)
    _described(state, block)
    CreativeState.open_clip_join.fn(state, block)
    CreativeState.set_clip_join.fn(state, joins.FADE)
    # over the AI part (its seconds of the final video, after the fade: 1.5-6.5 s)
    state.clip_text_uses = [
        {
            "uid": "t1",
            "text": "2×1 hoy",
            "place": "top",
            "start": 2.0,
            "end": 6.0,
            "blocks": [],
            "fade": 0.5,
        }
    ]
    state.clip_effect_uses = [
        {"uid": "u1", "effect_id": "humo_capa", "start": 2.0, "end": 6.0, "lane": 0, "blocks": []}
    ]
    return state, block


@pytest.mark.usefixtures("ai_on")
def test_the_preview_shows_it_with_its_mark_text_humo_and_fundido(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _block = _between_two_photos(monkeypatch)
    sequence = state._clip_sequence()
    assert [b.kind for b in sequence.blocks] == ["photo", "ai", "photo"]
    ai = sequence.blocks[1]
    assert ai.url == ""  # nothing to play before it is made: its poster or its card
    assert ai.label == "Parte con IA 1"
    assert ai.mark == ai_vm.PREVIEW_MARK.format(n=1) == "Parte con IA 1 · se crea al tocar «Crear»"
    assert ai.join == "fade" and ai.join_s > 0
    assert ai.poster.endswith(clip_editor_vm.upload_path(_ONE))  # the Clip's first photo
    assert [t.text for t in sequence.texts] == ["2×1 hoy"]
    assert [e.effect_id for e in sequence.effects] == ["humo_capa"]
    (text,) = sequence.texts
    assert ai.out_start <= text.start and text.end <= ai.out_end


@pytest.mark.usefixtures("ai_on")
def test_the_clip_keeps_it_in_its_recipe_and_the_servers_validator_takes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deivid (2026-11-26, ED-07 criterion): the brief carries the `ai_part` block with
    its `transition_in`, the text and the effect over its seconds, and passes the
    server's own `validate_brief_recipe` with the switch on — its entry with a guide of
    the business and a catalog photo, so the guide's checks run too."""
    state, block_id = _between_two_photos(monkeypatch)
    guide = f"uploads/{_TENANT}/clip/baile.mp4"
    photo = f"uploads/{_TENANT}/catalog/arepa.jpg"
    plan, why = ai_vm.with_guide(state.clip_ai_parts[0]["plan"], guide)
    assert why == ""
    state._clip_ai_put(block_id, ai_vm.with_photos(plan, [photo]))
    media = state._clip_edit_media()
    segments: list[dict[str, Any]] = media["segments"]  # type: ignore[assignment]
    assert [s.get("kind", "video") for s in segments] == ["photo", AI_PART_KIND, "photo"]
    ai = segments[1]
    assert ai["key"] == "ai_part:0" and ai["start_s"] == 0 and ai["end_s"] == 5
    assert (ai["speed"], ai["rotate"]) == (1, 0)
    assert ai["transition_in"]["effect_id"] == joins.FADE
    assert len(media["ai_parts"]) == 1  # type: ignore[arg-type]

    brief = build_brief(_BRAND, **state._generator_form())  # type: ignore[arg-type]
    assert brief.media.clip_reference_mode == "local"
    (entry,) = brief.media.ai_parts
    assert entry.mode == "reference" and entry.seconds == 5
    assert entry.description == "Una mano acerca el vaso"
    assert entry.clip_video_keys == (guide,) and entry.clip_image_keys == (photo,)
    # no recipe of its own: its texts, effects and join are the Clip's (contract §2)
    assert not (entry.effects or entry.text_layers or entry.segments or entry.transition_in)
    block = brief.media.segments[1]
    assert block.kind == AI_PART_KIND and block.ai_part_at == 0
    assert (block.speed, block.rotate) == (1, 0)
    assert block.transition_in is not None and block.transition_in.effect_id == joins.FADE
    (layer,) = brief.media.text_layers
    assert (layer.text, layer.start_s, layer.end_s) == ("2×1 hoy", 2.0, 6.0)
    (effect,) = brief.media.effects
    assert (effect.effect_id, effect.start_s, effect.end_s) == ("humo_capa", 2.0, 6.0)
    assert validate_brief_recipe(brief, tenant_id=_TENANT) == ()


@pytest.mark.usefixtures("ai_on")
def test_crear_stays_off_with_ai_parts_until_pr2(monkeypatch: pytest.MonkeyPatch) -> None:
    state, _block = _between_two_photos(monkeypatch)
    assert not ai_vm.AI_CREATE_BUILT
    assert state.clip_edit_problem == [ai_vm.CREATE_OFF_LINE, "info"]
    assert state._form_problem() == ai_vm.CREATE_OFF_LINE  # «Crear» refuses too
    review = state.clip_ai_review
    assert review["now"].startswith("Ahora, al crear: 1 vista previa, la de tu parte con IA.")
    assert review["later"].startswith("Después, al aprobar: 5 s de video")
    assert review["off"] == ai_vm.CREATE_OFF_LINE
    assert "try_reason" not in review  # «Probar esta parte» is in each part's panel
    state.gen_step = len(state._gen_steps()) - 1  # «Revisa y crea»
    assert state.gen_is_last_view
    assert state.create_primary_disabled
    assert state.create_reason == ai_vm.CREATE_OFF_SHORT  # the long words once, above


@pytest.mark.usefixtures("ai_on")
def test_siguiente_waits_for_the_description() -> None:
    state = _state()
    assert state.clip_editor_on_screen
    block = _add(state, 0.5)
    assert state._clip_ai_missing() == "Falta contar qué pasa en la parte con IA 1."
    _described(state, block)
    assert state._clip_ai_missing() == ""


@pytest.mark.usefixtures("ai_on")
def test_the_contracts_refusals_show_before_crear() -> None:
    state = _state()
    state.clip_images = []
    state.clip_sequence = []
    block = _add(state, 0.0)
    _described(state, block)
    # «Sigue a la anterior» first on the track: the contract's words, under the timeline
    state._clip_ai_put(block, {**state.clip_ai_parts[0]["plan"], "mode": "extend"})
    problem = state.clip_edit_problem
    assert problem == [contract_ai.ai_part_text("extend_needs_block_before"), "warn"]
    assert state.clip_ai_chosen["problem"] == problem[0]


@pytest.mark.usefixtures("ai_on")
def test_a_guide_of_another_business_is_said_before_crear() -> None:
    """Review: the session's business goes to the contract (`foreign_key`)."""
    state = _state()
    block = _add(state, 0.5)
    _described(state, block)
    other = "uploads/b0000000-0000-4000-8000-000000000009/clip/baile.mp4"
    plan, _why = ai_vm.with_guide(state.clip_ai_parts[0]["plan"], other)
    state._clip_ai_put(block, plan)
    # no business known yet: never skipped in silence
    state._clip_session_tenant = ""
    assert [p["code"] for p in state._clip_ai_problems()] == ["ai_parts_mismatch"]
    assert state.clip_edit_problem == [ai_vm.refusal_text("ai_parts_mismatch"), "warn"]
    state._clip_session_tenant = str(_TENANT)
    assert [p["code"] for p in state._clip_ai_problems()] == ["foreign_key"]
    assert state.clip_edit_problem == [ai_vm.refusal_text("foreign_key"), "warn"]
    mine, _why = ai_vm.with_guide(
        ai_vm.without_guide(plan, other), f"uploads/{_TENANT}/clip/baile.mp4"
    )
    state._clip_ai_put(block, mine)
    assert state._clip_ai_problems() == []


@pytest.mark.usefixtures("ai_on")
def test_late_words_never_land_on_another_part() -> None:
    """Review: the field flushes its debounced words on unmount — after another part was
    chosen. Each event names its own part."""
    state = _state()
    first = _add(state, 0.5)
    second = _add(state, 999.0)
    assert state.clip_edit_block == second
    CreativeState.set_clip_ai_description.fn(state, first, "Una mano acerca el vaso")
    assert state.clip_ai_parts[0]["plan"]["description"] == "Una mano acerca el vaso"
    assert state.clip_ai_parts[1]["plan"]["description"] == ""
    # a part no longer there: ignored
    CreativeState.set_clip_ai_description.fn(state, ai_vm.token("gone"), "x")
    assert [p["plan"]["description"] for p in state.clip_ai_parts] == [
        "Una mano acerca el vaso",
        "",
    ]


@pytest.mark.usefixtures("ai_on")
def test_after_a_join_the_field_shows_the_joined_words() -> None:
    """Review: the field is uncontrolled; a join keeps the part's id and changes its
    words, so its revision goes up and the field's key with it."""
    state = _state()
    first = _add(state, 0.5)
    second = _add(state, 2.5)  # right after the first one
    state.clip_edit_block = first
    _described(state, first, "Una mano acerca el vaso")
    assert state.clip_ai_chosen["desc_key"] == f"{first}-0"
    joined = {**state.clip_ai_parts[0]["plan"], "description": "Una mano acerca el vaso. Brinda."}
    joined["seconds"] = 8
    state._clip_ai_apply_merge(first, second, joined)
    assert [p["uid"] for p in state.clip_ai_parts] == [ai_vm.uid_of(first)]
    row = state.clip_ai_chosen
    assert row["desc_key"] == f"{first}-1"
    assert row["description"] == "Una mano acerca el vaso. Brinda."
    assert state.clip_edit_notice == "Juntaste las partes con IA 1 y 2: ahora son una de 8 s."
    # the owner's own typing never moves the revision
    _described(state, first, "Otra cosa")
    assert state.clip_ai_chosen["desc_key"] == f"{first}-1"


@pytest.mark.usefixtures("ai_on")
def test_moving_says_the_new_number() -> None:
    state = _state()
    first = _add(state, 0.5)  # after photo 1
    _add(state, 999.0)  # last
    state._clip_move_media(first, 4)  # to the end: it is the second AI part now
    assert state.clip_edit_notice == "Moviste la parte con IA 1: ahora es la parte con IA 2."


@pytest.mark.usefixtures("ai_on")
def test_the_guide_upload_keeps_only_a_guides_types(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio  # noqa: PLC0415

    stored: list[str] = []

    async def save(self: CreativeState, files: list[Any]) -> list[tuple[str, str]]:
        stored.extend(f.name for f in files)
        return [(f"uploads/{_TENANT}/clip/{f.name}", f.name) for f in files]

    monkeypatch.setattr(CreativeState, "_save_uploads", save)

    class _File:
        def __init__(self, name: str) -> None:
            self.name = name

    state = _state()
    _add(state, 0.5)
    files = [_File("baile.mp4"), _File("nota.txt"), _File("ritmo.mp3")]
    asyncio.run(CreativeState.handle_clip_ai_guide_uploads.fn(state, files))
    assert stored == ["baile.mp4", "ritmo.mp3"]  # the .txt is never stored
    assert [g["kind"] for g in state.clip_ai_guides] == ["video", "audio"]
    assert state.clip_edit_notice == contract_ai.ai_part_text("ai_part_guide_type")


def test_the_screen_contract_names_the_ai_block_as_the_server() -> None:
    from typing import get_args  # noqa: PLC0415

    from qualify_creative import schemas  # noqa: PLC0415

    assert get_args(contract.SegmentKind) == get_args(schemas.SegmentKind)
    assert contract.AI_PART_KIND == schemas.AI_PART_KIND
    assert contract.SEGMENT_KINDS == schemas.SEGMENT_KINDS  # own material, as before
    segment = contract.SourceSegment("ai_part:2", 0.0, 5.0, kind=contract.AI_PART_KIND)
    assert segment.ai_part_at == 2
    assert contract.segment_problems(segment) == []
    assert contract.segment_problems(
        contract.SourceSegment("ai_part:2", 0.0, 5.0, speed=2.0, kind="ai_part")
    ) == ["ai_part_with_speed"]
    assert "bad_kind" in contract.segment_problems(
        contract.SourceSegment("t/x.mp4", 0.0, 5.0, kind="ai_part")
    )
    assert contract.used_seconds([segment]) == 0.0
