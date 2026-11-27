"""ED-06 (m-25026636, PR 7 of the one editor): «Idea» inside «Arma tu video» and the video
in 3 steps — the pure words and fits (`editor_idea_vm`), the steps and their old
addresses, the general panel's fields reaching the copy as before, «Hacer uno parecido»
laying the reel's plan as blocks and «Agregar → Pedir una idea» adding Claude's parts at
the end. Offline: standalone states, the backend reads and the proposal faked — no
database, no Claude, no vendor, nothing paid."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.creative.parts import plan_from_analysis
from qualify_api.creative.parts_ai import (
    PROPOSE_RETRY_TEXT,
    STORY_MAX,
    PartsProposal,
    parse_parts,
)
from qualify_api.creative.plan_blocks import ClipBlocks, blocks_from_analysis, blocks_from_plan
from qualify_api.creative.video_pipeline import ai_parts as contract_ai
from qualify_api.referentes.reel_analysis_types import AnalysisStatus
from qualify_creative.schemas import (
    AI_PART_KIND,
    EffectUse,
    PartsProvenance,
    SourceSegment,
    VideoPartPlan,
    ai_part_key,
)

from . import ai_block_vm as ai_vm
from . import clip_editor_vm, reel_wait_provider, reel_wait_vm
from . import clip_joins_vm as joins
from . import creative_state as module
from . import editor_idea_vm as vm
from . import parts_start_provider as start_provider
from . import parts_start_state as start_state
from . import parts_start_vm as start_vm
from .creative_provider import build_brief
from .creative_state import (
    CONTEXT_FIELD_ID,
    CreativeState,
    generator_step_of,
    generator_steps,
)
from .parts_start_state import PartsStartState
from .test_reel_parts_vm import ANALYSIS_ID, analysis, shot

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND = UUID("c0000000-0000-4000-8000-000000000003")
_ONE = f"uploads/{_TENANT}/clip/uno.jpg"
_TWO = f"uploads/{_TENANT}/clip/dos.jpg"
_VIDEO = f"uploads/{_TENANT}/clip/v.mp4"
_CARD = {
    "key": "instagram:A",
    "network": "instagram",
    "id": "A",
    "url": "https://www.instagram.com/reel/A/",
    "handle": "smash_hiro",
}
_IMPORTED = {"key": f"uploads/{_TENANT}/referencia-reel.mp4", "name": "Reel · 5 s"}


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)


@pytest.fixture
def ai_on(monkeypatch: pytest.MonkeyPatch, editor_on: None) -> None:
    monkeypatch.setenv(contract_ai.CLIP_AI_PARTS_SWITCH, "on")
    monkeypatch.setenv(joins.JOINS_SWITCH, "on")


@pytest.fixture
def ai_off(monkeypatch: pytest.MonkeyPatch, editor_on: None) -> None:
    monkeypatch.delenv(contract_ai.CLIP_AI_PARTS_SWITCH, raising=False)


def _plan(seconds: int = 5, words: str = "Una mano acerca el vaso") -> VideoPartPlan:
    return VideoPartPlan(mode="reference", seconds=seconds, description=words)


def _ai_track(n: int) -> ClipBlocks:
    """A track of `n` AI parts of 5 s each (the editor's `after`)."""
    return ClipBlocks(
        segments=tuple(
            SourceSegment(key=ai_part_key(i), kind=AI_PART_KIND, start_s=0, end_s=5)
            for i in range(n)
        ),
        ai_parts=tuple(_plan() for _ in range(n)),
    )


def _photo_track(n: int) -> ClipBlocks:
    """A track of `n` own photos of 2 s each."""
    return ClipBlocks(
        segments=tuple(
            SourceSegment(key=f"uploads/{_TENANT}/clip/f{i}.jpg", kind="photo", start_s=0, end_s=2)
            for i in range(n)
        )
    )


# -- the words (`editor_idea_vm`) -------------------------------------------------------------


def test_the_new_words_read_literally() -> None:
    # the ticket (m-25026636) and the signed design (D6, D20, D21, 03C)
    assert vm.TOPIC_QUESTION == "¿De qué trata tu video?"
    assert vm.TOPIC_HELP == "Esto guía el texto de todo el video."
    assert vm.TOPIC_EXAMPLE == "Ej.: «Promoción de 2×1 los martes»."
    assert vm.WHOLE_TITLE == "Todo el video"
    assert vm.WHOLE_RULE == (
        "Esto guía el texto y el tono de todo el video. Lo que escribas abajo dice qué se ve "
        "en esta parte."
    )
    assert vm.CHANGE_LABEL == "Cambiar"
    assert vm.INSPIRATION_TITLE == "Video de inspiración"
    assert vm.GO_TO_VIDEO == "Ir al video"
    assert vm.PROPOSE_LABEL == "Proponerme las partes"
    assert vm.PROPOSE_NOTE == (
        "Proponer es gratis. Las partes se suman al final de tu video y las revisas antes "
        "de crear nada."
    )
    # «bloque» stays where it already is; nothing new says it (contract §3.3)
    for words in (vm.WHOLE_RULE, vm.WHOLE_EMPTY, vm.PROPOSE_NOTE, vm.reel_line(3, 2)):
        assert "bloque" not in words
    # the general panel's field is step 2's (`Mejorar mi texto` scrolls to it)
    assert vm.TOPIC_FIELD_ID == CONTEXT_FIELD_ID


def test_todo_el_video_quotes_the_context_or_asks_for_it() -> None:
    assert vm.whole_value("  Promoción de 2×1\n los martes ") == "«Promoción de 2×1 los martes»"
    assert vm.whole_value("") == vm.WHOLE_EMPTY == "Cuenta de qué trata tu video: guía el texto."


def test_the_folded_row_says_the_context_or_invites_to_write_it() -> None:
    """Design D21: one row with nothing chosen — «Cambiar» or «Escribir»."""
    assert vm.row_text(" 2×1 los\n martes ") == "Tu video trata de: «2×1 los martes»"
    assert vm.row_text("") == "Cuenta de qué trata tu video: guía el texto."
    assert (vm.CHANGE_LABEL, vm.WRITE_LABEL) == ("Cambiar", "Escribir")
    assert vm.CHANGE_ARIA == "Cambiar de qué trata tu video"
    assert vm.WRITE_ARIA == "Escribir de qué trata tu video"
    assert vm.MORE_LABEL == "Más opciones (a quién le habla, precio, descuento…)"
    assert vm.PANEL_TITLE == "De qué trata tu video"
    assert vm.GO_TO_VIDEO_ARIA == "Ir al video de inspiración (se abre en otra pestaña)"


def test_the_reel_line_counts_ai_parts_and_own_ones() -> None:
    assert vm.reel_line(3, 2) == (
        "Te armamos tu video como el reel: 3 partes con IA y 2 tuyas. Revisa cada una; "
        "hasta «Crear» no gastas nada."
    )
    assert vm.reel_line(1, 0) == (
        "Te armamos tu video como el reel: 1 parte con IA. Revísala; hasta «Crear» no gastas nada."
    )
    assert vm.reel_line(0, 2).startswith("Te armamos tu video como el reel: 2 partes tuyas. ")
    assert "1 parte con IA y 1 tuya. Revisa cada una" in vm.reel_line(1, 1)
    assert vm.REEL_FALLBACK_LINE == (
        "No pudimos armarlo como el reel: agregamos el paso «Qué decir»."
    )


def test_the_idea_line_says_how_many_went_in_and_why_not_the_rest() -> None:
    assert vm.idea_line(4, 4) == "Te propusimos 4 partes. Revísalas: hasta «Crear» no gastas nada."
    assert vm.idea_line(1, 1) == "Te propusimos 1 parte. Revísala: hasta «Crear» no gastas nada."
    # UX review: the fact, never the order «Quita una…»
    assert vm.idea_line(4, 2, "too_many_blocks") == (
        "Te propusimos 4 partes y pusimos 2: tu video llegó a 8 fotos o videos, el máximo. "
        "Revísalas: hasta «Crear» no gastas nada."
    )
    assert vm.idea_line(4, 2, "too_many_ai_children") == (
        "Te propusimos 4 partes y pusimos 2: tu video llegó a 6 partes con IA, el máximo. "
        "Revísalas: hasta «Crear» no gastas nada."
    )
    assert vm.idea_line(3, 1, "too_long") == (
        "Te propusimos 3 partes y pusimos 1: con las demás, tu video pasaría de 60 s. "
        "Revísala: hasta «Crear» no gastas nada."
    )
    for reason in ("too_many_blocks", "too_many_ai_children", "too_long"):
        assert "Quita" not in vm.idea_line(3, 1, reason)
    # none went in: the cap's words of today
    assert vm.idea_line(3, 0, "too_many_blocks") == clip_editor_vm.FULL_LINE


def test_the_caps_speak_in_the_signed_words() -> None:
    assert vm.cap_text("too_many_blocks") == clip_editor_vm.FULL_LINE
    assert vm.cap_text("too_many_ai_children") == ai_vm.FULL_AI_LINE
    assert vm.cap_text("too_long") == ai_vm.FULL_SECONDS_LINE
    assert vm.cap_text("too_many_texts").startswith("Tu video puede tener hasta 3 textos")
    assert vm.cap_text("") == ""


# -- how much of a proposal fits (`fit_proposal`, the server's `blocks_from_plan`) -----------


def test_a_proposal_goes_whole_on_an_empty_track() -> None:
    blocks, placed, reason = vm.fit_proposal([_plan(), _plan(), _plan()], ClipBlocks())
    assert blocks is not None and placed == 3 and reason == ""
    assert [s.key for s in blocks.segments] == [ai_part_key(0), ai_part_key(1), ai_part_key(2)]


def test_a_proposal_goes_at_the_end_and_keeps_what_was_there() -> None:
    after = _photo_track(2)
    blocks, placed, _ = vm.fit_proposal([_plan(), _plan()], after)
    assert blocks is not None and placed == 2
    assert blocks.segments[:2] == after.segments  # nothing moved, nothing deleted
    ops = vm.editor_ops(blocks, start=len(after.segments))
    assert [op["kind"] for op in ops] == ["ai", "ai"]


@pytest.mark.parametrize(
    ("after", "plan", "placed", "reason"),
    [
        (_photo_track(7), [_plan(), _plan(), _plan()], 1, "too_many_blocks"),
        (_ai_track(5), [_plan(), _plan(), _plan()], 1, "too_many_ai_children"),
        (_ai_track(5), [_plan(5), _plan(6)], 1, "too_many_ai_children"),
        (_ai_track(5), [_plan(10)], 1, ""),  # 25 s + 10 s fit in 60 s: all of it
    ],
)
def test_only_what_fits_goes_in_and_the_first_cap_is_said(
    after: ClipBlocks, plan: list[VideoPartPlan], placed: int, reason: str
) -> None:
    blocks, count, code = vm.fit_proposal(plan, after)
    assert count == placed and code == reason
    assert blocks is not None and len(blocks.segments) == len(after.segments) + placed


def test_past_60_seconds_nothing_more_goes_in() -> None:
    after = ClipBlocks(
        segments=tuple(
            SourceSegment(key=f"uploads/{_TENANT}/clip/v{i}.mp4", kind="video", start_s=0, end_s=14)
            for i in range(4)
        )
    )  # 56 s of own videos
    blocks, placed, reason = vm.fit_proposal([_plan(5), _plan(3)], after)
    assert placed == 0 and blocks is None and reason == "too_long"
    blocks, placed, reason = vm.fit_proposal([_plan(3), _plan(5)], after)
    assert placed == 1 and reason == "too_long"


def test_the_ops_carry_ai_parts_own_blocks_and_their_joins() -> None:
    fade = EffectUse(effect_id=joins.FADE, version=1, params={"duration_s": 0.5})
    plan = (
        VideoPartPlan(
            mode="local",
            seconds=2,
            segments=(
                SourceSegment(key=_ONE, kind="photo", start_s=0, end_s=3, rotate=90),
                SourceSegment(key=_VIDEO, kind="video", start_s=0, end_s=4),
            ),
        ),
        VideoPartPlan(mode="reference", seconds=4, description="Sale humo", transition_in=fade),
    )
    blocks = blocks_from_plan(plan)
    ops = vm.editor_ops(blocks)
    assert [op["kind"] for op in ops] == ["photo", "video", "ai"]
    assert ops[0]["seconds"] == 3.0 and ops[0]["rotate"] == 90
    assert ops[2]["plan"]["description"] == "Sale humo"
    assert ops[2]["join"] == {"kind": joins.FADE, "seconds": 0.5, "direction": ""}
    # the AI part's entry has no recipe of its own: its join is the block's
    assert ops[2]["plan"]["transition_in"] is None


@pytest.mark.parametrize(
    "video",
    [
        SourceSegment(key=_VIDEO, kind="video", start_s=2, end_s=6),  # a stretch
        SourceSegment(key=_VIDEO, kind="video", start_s=0, end_s=12, speed=3),  # a speed
    ],
)
def test_a_local_video_the_editor_cannot_hold_is_never_lost_in_silence(
    video: SourceSegment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review: an own video with a stretch or a speed would come in whole and at ×1 —
    the whole plan goes back to today's way instead (the list, or «no pudimos»)."""
    plan = (
        VideoPartPlan(mode="local", seconds=4, segments=(video,)),
        VideoPartPlan(mode="reference", seconds=4, description="Sale humo"),
    )
    blocks = blocks_from_plan(plan)
    assert vm.editor_ops(blocks) is None
    # «Hacer uno parecido»: the provider says «no blocks», so the list follows
    reel = analysis(shot(0, 0, 5), shot(1, 5, 9))
    monkeypatch.setattr(reel_wait_provider.reel_analysis, "get_analysis", lambda *_a: reel)
    monkeypatch.setattr(reel_wait_provider, "blocks_from_plan", lambda *_a, **_k: blocks)
    assert reel_wait_provider.reel_blocks(_TENANT, ANALYSIS_ID) is None


def test_the_plans_texts_and_effects_are_not_put_until_the_editor_takes_them() -> None:
    """TODO(PR 5 follow-up): `editor_ops` does not put a plan's texts or effects yet — no
    plan brings them today. This FAILS the day `plan_from_analysis` or `propose_parts`
    does, so the editor learns to put them before an owner loses one."""
    reel = analysis(shot(0, 0, 5), shot(1, 5, 9), shot(2, 9, 21))
    from_reel = blocks_from_analysis(reel, products=("smash doble",))
    rows = [
        {"description": "Una mano acerca el vaso de yogur a la cámara.", "seconds": 5},
        {"description": "El local lleno a la hora del almuerzo.", "seconds": 6},
        {"description": "Una cuchara toma yogur con fresas del vaso.", "seconds": 5},
    ]
    parts, problems = parse_parts({"parts": rows})
    assert problems == ()
    from_idea, placed, _ = vm.fit_proposal(parts, ClipBlocks())
    assert placed == 3 and from_idea is not None
    for blocks in (from_reel, from_idea):
        assert blocks.text_layers == () and blocks.effects == ()
    # … and if one ever does, nothing is put half-way
    smoke = EffectUse(effect_id="humo_capa", version=1)
    with_effect = VideoPartPlan(mode="reference", seconds=4, description="x", effects=(smoke,))
    assert vm.editor_ops(blocks_from_plan((with_effect,))) is None


# -- 3 steps for a video, 4 for the rest --------------------------------------------------------


def test_generator_steps_skip_que_decir_only_for_the_video_in_the_editor() -> None:
    assert [s for s, _ in generator_steps("clip", "clip", editor=True)] == [
        "show",
        "how",
        "review",
    ]
    assert generator_steps("clip", "clip", editor=True)[0] == (
        "show",
        ["reference", "topic", "rules"],
    )
    assert generator_step_of("clip", "clip", "topic", editor=True) == 0
    assert generator_step_of("clip", "clip", "rules", editor=True) == 0
    # without the editor (production today) the Clip keeps its 4 steps
    assert [s for s, _ in generator_steps("clip", "clip")] == ["show", "say", "how", "review"]
    # Imagen, Carrusel and Avatar keep 4, whatever the flag says
    for category, kind in (
        ("image", "static_flyer"),
        ("carousel", "carousel"),
        ("video", "avatar_video"),
        ("video", "animated_avatar_video"),
    ):
        for editor in (False, True):
            steps = [s for s, _ in generator_steps(category, kind, editor=editor)]
            assert steps == ["show", "say", "how", "review"], (category, kind, editor)


@pytest.mark.usefixtures("editor_on")
def test_a_clip_on_the_editor_walks_three_steps() -> None:
    state = CreativeState()
    state.choose_category("clip")
    assert state.create_step_m == 3 and state.gen_step_count == "Paso 1 de 3"
    assert [s["label"] for s in state.gen_view_steps] == [
        "Arma tu video",
        "Cómo la quieres",
        "Revisa y crea",
    ]
    state.next_view()
    assert state.gen_step_key == "how" and state.gen_step_count == "Paso 2 de 3"
    for category in ("image", "carousel", "video"):
        other = CreativeState()
        other.choose_category(category)
        assert other.create_step_m == 4, category


def test_with_the_editor_off_a_clip_keeps_four_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", False)
    monkeypatch.setenv(contract_ai.CLIP_AI_PARTS_SWITCH, "on")
    state = CreativeState()
    state.choose_category("clip")
    assert state.gen_step_count == "Paso 1 de 4"
    assert [s["label"] for s in state.gen_view_steps][1] == "Qué decir"


@pytest.mark.usefixtures("editor_on")
def test_an_old_paso_of_a_saved_video_lands_on_its_step_without_error() -> None:
    """A video kept with `?paso=2` (its «Qué decir» of before) or `?paso=4`: the address
    is read against the 3 steps — never past the last, never an error."""
    state = CreativeState()
    state.choose_category("clip")
    state.brief_topic = "Promoción de 2×1 los martes"
    state._show_create_step(2)
    assert state.gen_step_key == "how" and state.create_step_n == 2
    assert state.create_error == "" and state.generator_view == "form"
    state._show_create_step(4)  # «Revisa y crea» was the 4th
    assert state.gen_step_key == "review" and state.create_step_n == 3
    # a step kept in the session from before (index 1, «Qué decir») shows a real step
    state.gen_step = 1
    assert state.gen_step_key == "how" and state.gen_view == "channel"
    state.gen_step = 3
    assert state.gen_step_key == "review" and state.gen_is_last_view


@pytest.mark.usefixtures("editor_on")
def test_editar_the_context_goes_to_the_editors_general_panel() -> None:
    state = CreativeState()
    state.choose_category("clip")
    state.next_view()
    state.next_view()
    assert state.gen_step_key == "review"
    rows = {row["label"]: row for row in state.gen_summary}
    # UX review: «Contexto» is named after the general panel with the editor on
    assert vm.PANEL_TITLE in rows and "Contexto" not in rows
    events = state.edit_view(rows[vm.PANEL_TITLE]["view"])
    assert state.gen_step_key == "show" and state.clip_edit_block == ""
    assert state.clip_general_open and not state.rules_open
    assert vm.TOPIC_FIELD_ID in str(events)
    # «Datos clave»: the panel open on its first field, «Más opciones» unfolded
    state.clip_general_open = False
    state.next_view()
    events = state.edit_view("rules")
    assert state.gen_step_key == "show" and state.clip_general_open and state.rules_open
    assert vm.RULES_FIELD_IDS[0] in str(events)
    # «A quién le habla»: its own selector, «Más opciones» unfolded
    state.rules_open = state.clip_general_open = False
    state.brief_audience = "problem_aware"
    state.go_to_view("2")
    rows = {row["label"]: row for row in state.gen_summary}
    found = [r for r in rows.values() if r["view"] == "topic:more"]
    assert found, [(r["label"], r["view"]) for r in rows.values()]
    audience = found[0]
    events = state.edit_view(audience["view"])
    assert state.clip_general_open and state.rules_open
    assert vm.AUDIENCE_FIELD_ID in str(events)


@pytest.mark.usefixtures("editor_on")
def test_editar_from_another_step_touches_no_block_history() -> None:
    """Review: a block chosen before «Siguiente» left a `qBloque` entry; «Editar» must
    not walk it back (that left the owner on step 2) nor push `?bloque=de-que-trata` —
    the step's own address is the way back."""
    state = _clip()
    CreativeState.select_clip_block.fn(state, _ONE)
    assert state.clip_edit_block == _ONE
    state.next_view()
    state.next_view()
    assert state.gen_step_key == "review"
    for view in ("topic", "rules", vm.MENTION_VIEW, vm.AVOID_VIEW):
        events = state.edit_view(view)
        said = str(events)
        # no `block_url_script` at all (it is the only script that reads `qBloque`);
        # the step's own `go_to_step` is the one history change
        assert "qBloque" not in said, view
        assert vm.GENERAL_SLUG not in said, view
        assert state.gen_step_key == "show" and state.clip_edit_block == ""
        assert state.clip_general_open
        state.go_to_view("2")


@pytest.mark.usefixtures("editor_on")
def test_listo_after_editar_never_leaves_the_step() -> None:
    """Final review, the exact flow: the panel opened on step 1 (its own address), two
    «Siguiente», «Editar» on «De qué trata», then «Listo» — no `history.back()`."""
    state = CreativeState()
    state.choose_category("clip")
    CreativeState.edit_clip_general.fn(state)
    assert state.clip_general_open and state._clip_general_addressed
    events = str(state.next_view())
    # the panel closes and its word is dropped with `replaceState` BEFORE the step's entry
    assert not state.clip_general_open
    assert events.index("delete st.qBloque") < events.index("/create?paso=2")
    state.next_view()
    assert state.gen_step_key == "review"
    rows = {row["label"]: row for row in state.gen_summary}
    state.edit_view(rows[vm.PANEL_TITLE]["view"])
    assert state.clip_general_open and not state._clip_general_addressed
    events = str(CreativeState.close_clip_general.fn(state))
    assert "history.back" not in events and "replaceState" in events
    assert not state.clip_general_open
    # opened on its own step, «Listo» walks its own entry back, as a block's
    CreativeState.edit_clip_general.fn(state)
    assert "history.back" in str(CreativeState.close_clip_general.fn(state))


@pytest.mark.usefixtures("editor_on")
def test_fallback_fields_take_the_focus_when_the_first_one_is_not_there() -> None:
    state = CreativeState()
    state.choose_category("clip")
    state.brief_audience = "problem_aware"
    state.brief_must_mention = "envío gratis"
    state.go_to_view("2")
    rows = {row["label"]: row for row in state.gen_summary}
    audience = next(r for r in rows.values() if r["view"] == "topic:more")
    events = str(state.edit_view(audience["view"]))
    # the answer already given shows as a closed line: its «Cambiar» takes the focus
    assert all(field in events for field in vm.AUDIENCE_FIELD_IDS)
    state.go_to_view("2")
    events = str(state.edit_view(rows["Debe mencionar"]["view"]))
    # 12 phrases turn the field off: its help takes the focus
    assert vm.MENTION_FIELD_ID in events and vm.MENTION_HELP_ID in events
    assert "!e.disabled" in vm.focus_script(vm.MENTION_FIELD_ID)


@pytest.mark.usefixtures("editor_on")
def test_each_rules_row_focuses_its_own_field() -> None:
    state = CreativeState()
    state.choose_category("clip")
    state.brief_must_mention = "envío gratis"
    state.brief_must_avoid = "barato"
    state.go_to_view("2")
    views = {row["label"]: row["view"] for row in state.gen_summary}
    assert views["Debe mencionar"] == vm.MENTION_VIEW
    assert views["Debe evitar"] == vm.AVOID_VIEW
    assert views["Datos clave"] == "rules"
    events = str(state.edit_view(views["Debe mencionar"]))
    assert vm.MENTION_FIELD_ID in events and state.rules_open
    state.go_to_view("2")
    events = str(state.edit_view(views["Debe evitar"]))
    assert vm.AVOID_FIELD_ID in events
    state.go_to_view("2")
    # «Datos clave» with no row yet: «Agregar dato» takes the focus
    events = str(state.edit_view("rules"))
    assert all(field in events for field in vm.RULES_FIELD_IDS)
    assert vm.RULES_FIELD_IDS[-1] == vm.RULES_ADD_ID


def test_rules_rows_without_the_editor_open_step_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", False)
    state = CreativeState()
    state.choose_category("clip")
    state.brief_must_mention = "envío gratis"
    state.go_to_view("3")
    views = {row["label"]: row for row in state.gen_summary}
    assert views["Debe mencionar"]["index"] == "1"  # «Qué decir»
    state.edit_view(views["Debe mencionar"]["view"])
    assert state.gen_step_key == "say" and state.rules_open


@pytest.mark.usefixtures("editor_on")
def test_the_general_panel_opens_from_its_row_and_closes_with_listo() -> None:
    state = CreativeState()
    state.choose_category("clip")
    assert not state.clip_topic_said and state.clip_topic_row == vm.ROW_EMPTY
    events = CreativeState.edit_clip_general.fn(state)
    assert state.clip_general_open and vm.TOPIC_FIELD_ID in str(events)
    events = CreativeState.close_clip_general.fn(state)
    assert not state.clip_general_open and vm.ROW_BUTTON_ID in str(events)
    state.brief_topic = "Promo"
    assert state.clip_topic_said and state.clip_topic_row == "Tu video trata de: «Promo»"
    # UX review P1: it has its own address — pushed open, walked back with «Listo» …
    events = CreativeState.edit_clip_general.fn(state)
    assert f'"{vm.GENERAL_SLUG}"' in str(events)
    events = CreativeState.close_clip_general.fn(state)
    assert "history.back" in str(events) and not state.clip_general_open
    # … and the phone's «atrás» (the address without it) closes it, the focus on its row
    CreativeState.edit_clip_general.fn(state)
    events = CreativeState.reconcile_reel_editor_route.fn(state, "?paso=1")
    assert not state.clip_general_open and vm.ROW_BUTTON_ID in str(events)
    # «adelante» (or a reload) on its address opens it again
    CreativeState.reconcile_reel_editor_route.fn(state, f"?paso=1&bloque={vm.GENERAL_SLUG}")
    assert state.clip_general_open and state.clip_edit_block == ""
    # choosing anything else closes it: one thing under the timeline at a time
    CreativeState.edit_clip_general.fn(state)
    CreativeState.open_clip_flow.fn(state, clip_editor_vm.FLOW_IDEA)
    assert not state.clip_general_open


def test_the_context_and_the_key_facts_reach_the_copy_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`topic` and `rules` («Datos clave») go into the brief exactly as from «Qué decir»."""

    def form(editor: bool) -> dict[str, object]:
        monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", editor)
        state = CreativeState()
        state.choose_category("clip")
        state.brief_topic = "Promoción de 2×1 los martes"
        state.brief_must_mention = "solo los martes"
        state.brief_must_avoid = "precios viejos"
        state.brief_highlights = [{"key": "Precio", "value": "18.900", "source": ""}]
        assert state._clip_idea_in_editor() is editor
        return state._generator_form()

    before, after = form(False), form(True)
    for field in ("topic", "must_mention", "must_avoid", "highlights", "objective"):
        assert after[field] == before[field], field
    assert after["topic"] == "Promoción de 2×1 los martes"
    assert ("Precio", "18.900") in [tuple(p) for p in after["highlights"]]  # type: ignore[union-attr]


# -- the general panel and «Todo el video» ----------------------------------------------------


def _clip(**extra: Any) -> CreativeState:
    """Two photos of 2 s each on «Arma tu video»."""
    state = CreativeState()
    state.choose_category("clip")
    state.brief_topic = "Promoción de 2×1 los martes"
    state.clip_images = [
        {"key": _ONE, "name": "uno.jpg", "source": "upload", "role": "product"},
        {"key": _TWO, "name": "dos.jpg", "source": "upload", "role": "product"},
    ]
    state.clip_sequence = [_ONE, _TWO]
    state._clip_session_tenant = str(_TENANT)
    state._brand_id = str(_BRAND)
    for name, value in extra.items():
        setattr(state, name, value)
    return state


@pytest.mark.usefixtures("ai_on")
def test_cambiar_in_todo_el_video_goes_back_to_the_general_panel() -> None:
    state = _clip()
    state.clip_edit_playhead = 4.0
    CreativeState.open_clip_flow.fn(state, ai_vm.ADD_KEY)
    assert ai_vm.is_token(state.clip_edit_block)
    assert state.clip_topic_whole == "«Promoción de 2×1 los martes»"
    events = CreativeState.edit_clip_general.fn(state)
    assert state.clip_edit_block == "" and state.gen_step_key == "show"
    assert state.clip_general_open  # the general panel, not another sheet
    assert vm.TOPIC_FIELD_ID in str(events)
    state.brief_topic = ""
    assert state.clip_topic_whole == vm.WHOLE_EMPTY


# -- «Hacer uno parecido» -------------------------------------------------------------------


class _Proxy:
    """`async with self` / `get_state` over plain states (as in `test_reel_wait_state`)."""

    def __init__(self, state: Any, **others: Any) -> None:
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "others", others)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_state(self, cls: type) -> Any:
        return self.others[cls.__name__]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.state, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.state, name, value)


def _replica() -> CreativeState:
    state = CreativeState()
    state.selected_product_id = "burger"
    state.brief_product_ref = "Smash doble"
    state._apply_reel_reference(_CARD, _IMPORTED, str(uuid4()), "queued")
    return state


def _reel_ops() -> list[dict[str, Any]]:
    new = VideoPartPlan(mode="reference", seconds=4, description="Una mano acerca el vaso")
    return [
        {"kind": "ai", "plan": new.model_dump(mode="json"), "join": None},
        {
            "kind": "ai",
            "plan": new.model_copy(update={"seconds": 5}).model_dump(mode="json"),
            "join": {"kind": joins.FADE, "seconds": 0.5, "direction": ""},
        },
    ]


@pytest.fixture
def reel_backend(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    seen = SimpleNamespace(blocks_calls=0)

    def analysis_status(tenant_id: UUID, analysis_id: UUID) -> AnalysisStatus:
        return AnalysisStatus(
            analysis_id=analysis_id,
            status="ok",
            stage=None,
            error_code=None,
            retryable=False,
            queued_for_s=5.0,
            queue_ahead=0,
            shots_found=2,
            covered_to_s=None,
            source_seconds=None,
            source_available=True,
        )

    def reel_plan(tenant_id: UUID, analysis_id: UUID, products: Any) -> list[dict[str, Any]]:
        plan = VideoPartPlan(mode="reference", seconds=4).model_dump(mode="json")
        return [{"key": f"k{i}", "plan": dict(plan), "person": False, "reason": ""} for i in (1, 2)]

    def reel_blocks(tenant_id: UUID, analysis_id: UUID, products: Any) -> list[dict[str, Any]]:
        seen.blocks_calls += 1
        return _reel_ops()

    async def sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(module.reel_wait_provider, "analysis_status", analysis_status)
    monkeypatch.setattr(module.reel_wait_provider, "reel_plan", reel_plan)
    monkeypatch.setattr(module.reel_wait_provider, "reel_blocks", reel_blocks)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    return seen


async def _poll(state: CreativeState) -> None:
    auth = SimpleNamespace(session_tenant_id=str(_TENANT))
    await CreativeState.poll_reel_analysis.fn(_Proxy(state, AuthState=auth))


@pytest.mark.usefixtures("ai_on")
async def test_hacer_uno_parecido_opens_the_editor_with_the_blocks_laid(
    reel_backend: SimpleNamespace,
) -> None:
    state = _replica()
    assert state.reel_wait_pending
    assert state.gen_step_count == "Paso 1 de 3"  # the editor is on its way
    await _poll(state)
    assert reel_backend.blocks_calls == 1
    assert state.reel_wait_phase == reel_wait_vm.PHASE_READY
    assert state.clip_reel_blocks and state.clip_editor_shown
    assert not state._reel_plan_open() and state.reel_part_rows == []
    # the reel is the «Video de inspiración», never a block of the track
    assert not any(v.get("source") == "reel" for v in state.clip_videos)
    assert [m["kind"] for m in state._clip_tl_media()] == ["ai", "ai"]
    assert state.clip_edit_notice == vm.reel_line(2, 0)
    assert state.gen_step_count == "Paso 1 de 3"
    assert state.reel_based_on_text == "Basado en un reel de smash_hiro"
    # the join of the plan is on its block; nothing is created or paid before «Crear»
    second = state._clip_tl_media()[1]["id"]
    assert state.clip_block_joins == {second: joins.FADE}
    media = state._clip_edit_media()
    assert media["clip_reference_mode"] == "local"
    assert [s["kind"] for s in media["segments"]] == [AI_PART_KIND, AI_PART_KIND]  # type: ignore[index]
    assert media["segments"][1]["transition_in"]["effect_id"] == joins.FADE  # type: ignore[index]
    assert len(media["ai_parts"]) == 2  # type: ignore[arg-type]
    assert state._clip_ai_create_off() != ""  # «Crear» waits for PR 2 (m-25129406)


@pytest.mark.usefixtures("ai_off")
async def test_with_the_switch_off_hacer_uno_parecido_is_as_today(
    reel_backend: SimpleNamespace,
) -> None:
    state = _replica()
    assert state.gen_step_count == "Paso 1 de 4"
    await _poll(state)
    assert reel_backend.blocks_calls == 0
    assert not state.clip_reel_blocks and not state.clip_editor_shown
    assert state._reel_plan_open() and state.reel_parts_count == 2
    assert state.clip_videos[0]["source"] == "reel"
    assert state.clip_ai_parts == [] and state.gen_step_count == "Paso 1 de 4"


@pytest.mark.usefixtures("ai_on")
async def test_a_plan_that_does_not_fit_as_blocks_is_listed_as_today(
    reel_backend: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(module.reel_wait_provider, "reel_blocks", lambda *_a: None)
    state = _replica()
    assert state.gen_step_count == "Paso 1 de 3"
    await _poll(state)
    assert not state.clip_reel_blocks and state._reel_plan_open()
    assert state.reel_parts_count == 2 and state.gen_step_count == "Paso 1 de 4"
    # review: the owner stays on the same step by its name, and the list says why
    assert state.gen_step_key == "show"
    assert state.reel_parts_notice == vm.REEL_FALLBACK_LINE


@pytest.mark.usefixtures("ai_on")
async def test_blocks_that_cannot_be_read_fall_back_to_the_list_without_a_failure(
    reel_backend: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review: `reel_blocks` failing (any exception) is never a failed wait: the
    list of always, at once."""

    def broken(*_a: Any) -> list[dict[str, Any]]:
        raise RuntimeError("database blip")

    monkeypatch.setattr(module.reel_wait_provider, "reel_blocks", broken)
    state = _replica()
    await _poll(state)
    assert state.reel_wait_phase == reel_wait_vm.PHASE_READY
    assert not state.clip_reel_blocks and state._reel_plan_open()
    assert state.reel_parts_count == 2


@pytest.mark.usefixtures("ai_on")
def test_falling_back_keeps_the_step_by_its_name() -> None:
    state = _replica()
    state.clip_reel_blocks = True  # 3 steps: «Cómo la quieres» is the 2nd
    state.gen_step = 1
    assert state.gen_step_key == "how"
    state.clip_reel_blocks = False
    state._show_reel_wait(reel_wait_vm.ready(2))  # 4 steps now: index 1 is «Qué decir»
    state._reel_blocks_fell_back("how")
    assert state.gen_step_key == "how" and state.gen_step_count == "Paso 3 de 4"


def test_the_provider_turns_the_reels_plan_into_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    reel = analysis(shot(0, 0, 5), shot(1, 5, 9))
    monkeypatch.setattr(reel_wait_provider.reel_analysis, "get_analysis", lambda *_a: reel)
    ops = reel_wait_provider.reel_blocks(_TENANT, ANALYSIS_ID, ("smash doble",))
    assert ops is not None and [op["kind"] for op in ops] == ["ai", "ai"]
    assert [op["plan"]["mode"] for op in ops] == ["edit", "edit"]  # «Igual al original»
    assert all(op["plan"]["analysis_id"] == str(ANALYSIS_ID) for op in ops)
    assert all(op["plan"]["transition_in"] is None for op in ops)
    monkeypatch.setattr(reel_wait_provider.reel_analysis, "get_analysis", lambda *_a: None)
    assert reel_wait_provider.reel_blocks(_TENANT, ANALYSIS_ID) is None


def test_a_reels_plan_past_60_seconds_falls_back_to_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review: a plan longer than the Clip's 60 s is never laid cut short: the list."""
    reel = analysis(shot(0, 0, 5), shot(1, 5, 9))
    monkeypatch.setattr(reel_wait_provider.reel_analysis, "get_analysis", lambda *_a: reel)
    long = ClipBlocks(
        segments=tuple(
            SourceSegment(key=ai_part_key(i), kind=AI_PART_KIND, start_s=0, end_s=10)
            for i in range(6)
        )
        + (SourceSegment(key=_VIDEO, kind="video", start_s=0, end_s=5),),
        ai_parts=tuple(_plan(10) for _ in range(6)),
    )
    assert long.seconds > clip_editor_vm.LOCAL_MAX_SECONDS
    monkeypatch.setattr(reel_wait_provider, "blocks_from_plan", lambda *_a, **_k: long)
    assert reel_wait_provider.reel_blocks(_TENANT, ANALYSIS_ID) is None


def test_a_reels_plan_the_server_refuses_as_blocks_falls_back_to_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 3 s «Igual al original» cut: `plan_from_analysis` proposes it, `blocks_from_plan`
    refuses it (`edit_unavailable`) — the screen lists the parts as today, never fails."""
    reel = analysis(shot(0, 0, 3), shot(1, 3, 7, people="observed", faces="observed"))
    monkeypatch.setattr(reel_wait_provider.reel_analysis, "get_analysis", lambda *_a: reel)
    assert reel_wait_provider.reel_blocks(_TENANT, ANALYSIS_ID, ("smash doble",)) is None


# -- m-25143223: a reel's plan that stops before the reel's end says so ----------------------


def test_the_reel_line_and_the_card_say_how_much_of_the_reel_a_cut_plan_uses() -> None:
    capped = vm.ReelCut(used_s=44, reel_s=63, capped=True)
    assert vm.reel_line(6, 0, capped) == (
        "Te armamos tu video como el reel: 6 partes con IA (el máximo por video), con 44 s "
        "de los 63 del reel. Revisa cada una; hasta «Crear» no gastas nada."
    )
    assert vm.reel_cut_card(capped) == "Usamos 44 s de los 63 del reel."
    # own parts among them: the plan's cap was of parts, not of AI parts — no bracket
    assert vm.reel_line(4, 2, capped) == (
        "Te armamos tu video como el reel: 4 partes con IA y 2 tuyas, con 44 s de los 63 "
        "del reel. Revisa cada una; hasta «Crear» no gastas nada."
    )
    # one part, stopped by something else than the cap: no bracket, «Revísala»
    one = vm.ReelCut(used_s=8, reel_s=20)
    assert vm.reel_line(1, 0, one) == (
        "Te armamos tu video como el reel: 1 parte con IA, con 8 s de los 20 del reel. "
        "Revísala; hasta «Crear» no gastas nada."
    )
    # a plan that covers the reel: nothing changes
    assert vm.reel_line(3, 2, None) == vm.reel_line(3, 2)
    assert vm.reel_cut_card(None) == ""


def test_the_provider_says_a_plan_cut_at_six_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    # nine cuts of 5-8 s (none joinable under 10 s): the plan keeps the first six, 44 s
    ends = [8, 15, 22, 29, 36, 44, 51, 58, 63]
    starts = [0, *ends[:-1]]
    reel = analysis(*(shot(i, a, b) for i, (a, b) in enumerate(zip(starts, ends, strict=True))))
    monkeypatch.setattr(reel_wait_provider.reel_analysis, "get_analysis", lambda *_a: reel)
    ops = reel_wait_provider.reel_blocks(_TENANT, ANALYSIS_ID, ("smash doble",))
    assert isinstance(ops, vm.ReelOps) and len(ops) == 6
    assert ops.cut == vm.ReelCut(used_s=44, reel_s=63, capped=True)


def test_six_natural_cuts_of_a_reel_read_short_are_not_capped() -> None:
    """Review: six cuts, all in the plan, of an analysis that stopped at 44 s of a 63 s
    reel — nothing was left out at the cap, so no bracket."""
    ends = [8, 15, 22, 29, 36, 44]
    starts = [0, *ends[:-1]]
    six = analysis(*(shot(i, a, b) for i, (a, b) in enumerate(zip(starts, ends, strict=True))))
    reel = replace(six, source_seconds=63.0)
    plan = plan_from_analysis(reel)
    assert len(plan) == 6
    assert reel_wait_provider.reel_cut(reel, plan) == vm.ReelCut(used_s=44, reel_s=63)


def test_the_provider_says_nothing_when_the_plan_covers_the_reel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reel = analysis(shot(0, 0, 5), shot(1, 5, 9))
    monkeypatch.setattr(reel_wait_provider.reel_analysis, "get_analysis", lambda *_a: reel)
    ops = reel_wait_provider.reel_blocks(_TENANT, ANALYSIS_ID, ("smash doble",))
    assert isinstance(ops, vm.ReelOps) and ops.cut is None
    # the shot detector's last half second is not a cut the owner should hear of
    close = replace(reel, source_seconds=9.6)
    assert reel_wait_provider.reel_cut(close, plan_from_analysis(close)) is None


def test_the_provider_says_how_much_one_part_uses_of_a_longer_reel() -> None:
    """One part of an analysis that read 8 s of a 20 s reel: «8 s de los 20», no cap."""
    reel = replace(analysis(shot(0, 0, 8)), source_seconds=20.2)
    plan = plan_from_analysis(reel)
    assert len(plan) == 1
    assert reel_wait_provider.reel_cut(reel, plan) == vm.ReelCut(used_s=8, reel_s=20)


def test_a_long_cut_split_in_parts_counts_only_the_parts_kept() -> None:
    """Review (the real case): cuts of 8, 7, 7, 7 s and one of 40 s split in 10 s parts —
    the plan keeps 8 + 7 + 7 + 7 + 10 + 10: 49 s of the 69, two parts of the long cut left
    out at the cap."""
    reel = analysis(shot(0, 0, 8), shot(1, 8, 15), shot(2, 15, 22), shot(3, 22, 29),
                    shot(4, 29, 69))  # fmt: skip
    plan = plan_from_analysis(reel)
    assert [p.seconds for p in plan] == [8, 7, 7, 7, 10, 10]
    assert reel_wait_provider.reel_cut(reel, plan) == vm.ReelCut(used_s=49, reel_s=69, capped=True)


@pytest.mark.usefixtures("ai_on")
async def test_a_cut_reel_plan_is_said_on_the_line_and_the_card(
    reel_backend: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    cut = vm.ReelCut(used_s=9, reel_s=20)
    monkeypatch.setattr(
        module.reel_wait_provider,
        "reel_blocks",
        lambda *_a: vm.ReelOps(_reel_ops(), cut=cut),
    )
    state = _replica()
    await _poll(state)
    assert state.clip_reel_blocks
    assert state.clip_edit_notice == vm.reel_line(2, 0, cut)
    assert state.clip_reel_cut == "Usamos 9 s de los 20 del reel."
    # the plan goes with its analysis: the card's line too
    state._apply_reel_reference(_CARD, _IMPORTED, str(uuid4()), "queued")
    assert state.clip_reel_cut == ""


@pytest.mark.usefixtures("ai_on")
async def test_a_whole_reel_plan_keeps_the_card_without_a_cut_line(
    reel_backend: SimpleNamespace,
) -> None:
    state = _replica()
    await _poll(state)
    assert state.clip_reel_blocks and state.clip_reel_cut == ""
    assert state.clip_edit_notice == vm.reel_line(2, 0)


# -- «Agregar → Pedir una idea» ------------------------------------------------------------


def _proposal(n: int) -> PartsProposal:
    return PartsProposal(
        parts=tuple(
            VideoPartPlan(mode="reference", seconds=5, description=f"Parte {i} del yogur.")
            for i in range(1, n + 1)
        ),
        provenance=PartsProvenance(model_id="fake-model", prompt_version="fake-v1", turns=1),
    )


@pytest.fixture
def fake_claude(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The proposal seam faked: no Claude call, nothing paid; records what it was asked.
    `during` runs while the «call» is out (the owner keeps working meanwhile); `outcome`
    replaces the answer."""
    seen: dict[str, Any] = {"calls": [], "n": 3, "during": None, "outcome": None}
    monkeypatch.setattr(start_vm, "STAGE_SECONDS", 0.01)

    def propose(tenant_id: UUID, brand_id: UUID, **kw: Any) -> start_provider.ProposalOutcome:
        seen["calls"].append(kw)
        if seen["during"] is not None:
            seen["during"]()
        if seen["outcome"] is not None:
            return seen["outcome"]
        proposal = _proposal(seen["n"])
        return start_provider.ProposalOutcome(
            entries=start_vm.entries_from_proposal(proposal),
            provenance=start_vm.provenance_json(proposal),
        )

    monkeypatch.setattr(start_state.provider, "propose", propose)
    return seen


async def _ask_idea(
    creative: CreativeState, typed: str | None, auth: SimpleNamespace | None = None
) -> tuple[PartsStartState, list]:
    card = PartsStartState()
    auth = auth or SimpleNamespace(session_tenant_id=str(_TENANT))
    proxy = _Proxy(card, CreativeState=creative, AuthState=auth)
    events = [event async for event in PartsStartState.propose_idea.fn(proxy, typed)]
    return card, events


def _fill(creative: CreativeState, n: int) -> None:
    """`n` AI parts of 5 s more, at the end of the track."""
    for _ in range(n):
        creative.clip_edit_playhead = 999.0
        CreativeState.open_clip_flow.fn(creative, ai_vm.ADD_KEY)
        creative.clip_edit_block = ""


@pytest.mark.usefixtures("ai_on")
async def test_pedir_una_idea_adds_the_parts_at_the_end_for_free(
    fake_claude: dict[str, Any],
) -> None:
    creative = _clip()
    CreativeState.open_clip_flow.fn(creative, clip_editor_vm.FLOW_IDEA)
    card, events = await _ask_idea(creative, "Promoción de 2×1 los martes en yogur")
    (asked,) = fake_claude["calls"]
    assert asked["story"] == "Promoción de 2×1 los martes en yogur"
    assert creative.brief_topic == "Promoción de 2×1 los martes en yogur"
    # the photos stay first, untouched; the 3 parts go after them
    media = creative._clip_tl_media()
    assert [m["kind"] for m in media] == ["photo", "photo", "ai", "ai", "ai"]
    assert [m["key"] for m in media[:2]] == [_ONE, _TWO]
    assert creative.clip_edit_notice.startswith("Te propusimos 3 partes. Revísalas")
    assert card.phase == start_vm.PHASE_READY and card.editor and card.error == ""
    # TODO(PR 2, m-25129406): kept here until the Clip's brief can carry it
    assert creative._clip_idea_provenance == start_vm.provenance_json(_proposal(1))
    assert "finish_clip_idea" in str(events)
    # the panel closes by itself
    CreativeState.finish_clip_idea.fn(creative)
    assert creative.clip_edit_block == "" and creative.clip_tl_flow == ""
    # nothing created: «Crear» still waits for PR 2, and the brief carries the parts
    assert creative._clip_ai_create_off() != ""
    brief = build_brief(_BRAND, **creative._generator_form())  # type: ignore[arg-type]
    assert brief.media.clip_reference_mode == "local"
    assert len(brief.media.ai_parts) == 3
    assert brief.media.parts_provenance is None  # PR 2 carries it (contract gap)


@pytest.mark.usefixtures("ai_on")
async def test_pedir_una_idea_puts_only_what_fits_and_says_why(
    fake_claude: dict[str, Any],
) -> None:
    creative = _clip()
    _fill(creative, 5)  # 2 photos + 5 AI parts = 7 blocks
    _card, _events = await _ask_idea(creative, None)
    assert [m["kind"] for m in creative._clip_tl_media()].count("ai") == 6
    assert creative.clip_edit_notice == (
        "Te propusimos 3 partes y pusimos 1: tu video llegó a 8 fotos o videos, el máximo. "
        "Revísala: hasta «Crear» no gastas nada."
    )


@pytest.mark.usefixtures("ai_on")
async def test_pedir_una_idea_does_not_ask_claude_when_nothing_fits(
    fake_claude: dict[str, Any],
) -> None:
    creative = _clip()
    _fill(creative, 6)
    assert creative.clip_idea_off == clip_editor_vm.FULL_LINE
    card, events = await _ask_idea(creative, None)
    assert fake_claude["calls"] == [] and events == []
    # review: the reason is said once, under the button — never a second time here
    assert card.error == "" and card.phase == start_vm.PHASE_IDLE


@pytest.mark.usefixtures("ai_on")
async def test_a_long_context_is_kept_whole_and_only_claude_reads_it_cut(
    fake_claude: dict[str, Any],
) -> None:
    """Review: the owner's context is never cut nor its «Mejorar mi texto» versions lost;
    only the sentence sent to Claude is (`STORY_MAX`)."""
    creative = _clip()
    versions = [{"text": "Una versión", "approach": "x"}]
    creative.context_versions = versions
    long = "Promoción de 2×1 los martes en yogur con fresas. " * 20
    assert len(long) > STORY_MAX
    await _ask_idea(creative, long)
    assert creative.brief_topic == long
    assert creative.context_versions == versions
    (asked,) = fake_claude["calls"]
    assert len(asked["story"]) <= STORY_MAX and long.startswith(asked["story"])


@pytest.mark.usefixtures("ai_on")
async def test_a_video_still_being_read_is_said_before_asking_claude(
    fake_claude: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    creative = _clip()

    def not_ready(_self: Any) -> ClipBlocks:
        # an own video with no length yet: its stretch is not a valid segment
        return ClipBlocks(segments=(SourceSegment(key=_VIDEO, start_s=0, end_s=0),))

    monkeypatch.setattr(CreativeState, "_clip_idea_track", not_ready)
    assert creative.clip_idea_off == vm.TRACK_NOT_READY
    card, _events = await _ask_idea(creative, None)
    assert fake_claude["calls"] == [] and card.error == ""
    # … and if it happens after the call, nothing is put and nothing was spent
    entries = start_vm.entries_from_proposal(_proposal(2))
    assert creative._clip_add_idea(entries, None) == (False, vm.TRACK_NOT_READY_AFTER)


@pytest.mark.usefixtures("ai_on")
async def test_a_failed_proposal_says_why_until_the_owner_types_or_reopens(
    fake_claude: dict[str, Any],
) -> None:
    fake_claude["outcome"] = start_provider.ProposalOutcome(error=PROPOSE_RETRY_TEXT)
    creative = _clip()
    CreativeState.open_clip_flow.fn(creative, clip_editor_vm.FLOW_IDEA)
    card, events = await _ask_idea(creative, None)
    assert card.phase == start_vm.PHASE_ERROR and card.error == PROPOSE_RETRY_TEXT
    assert card.error_epoch == creative.clip_idea_epoch  # shown
    assert events == [] and [m["kind"] for m in creative._clip_tl_media()] == ["photo"] * 2
    CreativeState.set_brief_topic.fn(creative, "Otro texto")
    assert card.error_epoch != creative.clip_idea_epoch  # typing takes it away
    card.error_epoch = creative.clip_idea_epoch
    CreativeState.done_clip_block.fn(creative)
    CreativeState.open_clip_flow.fn(creative, clip_editor_vm.FLOW_IDEA)
    assert card.error_epoch != creative.clip_idea_epoch  # … and so does reopening


@pytest.mark.usefixtures("ai_on")
@pytest.mark.parametrize(
    "outcome",
    [
        start_provider.ProposalOutcome(entries=[], provenance=None),  # `ok`, no parts
        start_provider.ProposalOutcome(  # a plan Claude sent malformed
            entries=[{"key": "k", "plan": {"mode": "reference", "seconds": 99}}],
            provenance=None,
        ),
    ],
)
async def test_an_empty_or_malformed_answer_puts_nothing(
    fake_claude: dict[str, Any], outcome: start_provider.ProposalOutcome
) -> None:
    fake_claude["outcome"] = outcome
    creative = _clip()
    card, events = await _ask_idea(creative, None)
    assert card.error == vm.NOT_PLACED and events == []
    assert [m["kind"] for m in creative._clip_tl_media()] == ["photo", "photo"]


@pytest.mark.usefixtures("ai_on")
async def test_another_business_meanwhile_puts_nothing(fake_claude: dict[str, Any]) -> None:
    creative = _clip()
    auth = SimpleNamespace(session_tenant_id=str(_TENANT))

    def switch() -> None:
        auth.session_tenant_id = "00000000-0000-0000-0000-0000000000ff"

    fake_claude["during"] = switch
    card, events = await _ask_idea(creative, None, auth)
    assert events == [] and card.phase == start_vm.PHASE_IDLE and card.error == ""
    assert [m["kind"] for m in creative._clip_tl_media()] == ["photo", "photo"]


@pytest.mark.usefixtures("ai_on")
async def test_another_piece_meanwhile_puts_nothing(fake_claude: dict[str, Any]) -> None:
    creative = _clip()

    def new_piece() -> None:
        creative.parts_piece += 1

    fake_claude["during"] = new_piece
    card, events = await _ask_idea(creative, None)
    assert events == [] and card.error == ""
    assert [m["kind"] for m in creative._clip_tl_media()] == ["photo", "photo"]


@pytest.mark.usefixtures("ai_on")
async def test_a_track_filled_meanwhile_puts_what_still_fits_or_says_why(
    fake_claude: dict[str, Any],
) -> None:
    creative = _clip()
    fake_claude["during"] = lambda: _fill(creative, 5)  # 7 blocks once Claude answers
    await _ask_idea(creative, None)
    assert [m["kind"] for m in creative._clip_tl_media()].count("ai") == 6
    assert "y pusimos 1: tu video llegó a 8 fotos o videos" in creative.clip_edit_notice
    full = _clip()
    fake_claude["during"] = lambda: _fill(full, 6)  # full once Claude answers
    card, events = await _ask_idea(full, None)
    assert events == [] and card.error == clip_editor_vm.FULL_LINE
    assert len(full._clip_tl_media()) == 8


@pytest.mark.usefixtures("ai_on")
async def test_pedir_una_idea_without_a_context_is_off_and_asks_for_it(
    fake_claude: dict[str, Any],
) -> None:
    """m-25026636: with nothing written the button is off with «Escribe de qué trata tu
    video, arriba en «¿De qué trata tu video?»…» as its reason (like the caps and a video
    being read), and a tap never asks Claude."""
    creative = _clip(brief_topic="")
    assert creative.clip_idea_off == vm.STORY_MISSING
    CreativeState.set_brief_topic.fn(creative, "   ")
    assert creative.clip_idea_off == vm.STORY_MISSING  # blanks are not a context
    card, events = await _ask_idea(creative, "   ")
    assert fake_claude["calls"] == [] and events == []
    # said once, under the button — never a second time on the card
    assert card.error == "" and card.phase == start_vm.PHASE_IDLE
    CreativeState.set_brief_topic.fn(creative, "Promoción de 2×1")
    assert creative.clip_idea_off == ""


@pytest.mark.usefixtures("ai_on")
async def test_what_is_typed_at_the_tap_turns_the_idea_on(
    fake_claude: dict[str, Any],
) -> None:
    """The field is debounced: the state may still hold "" when the owner taps right after
    typing. What the field holds at the tap counts, so the proposal goes ahead."""
    creative = _clip(brief_topic="")
    _card, _events = await _ask_idea(creative, "Promoción de 2×1 los martes")
    (asked,) = fake_claude["calls"]
    assert asked["story"] == "Promoción de 2×1 los martes"


def test_the_idea_reason_follows_the_context() -> None:
    """`clip_idea_off` recomputes when the context changes (a dependency Reflex sees)."""
    deps = CreativeState.computed_vars["clip_idea_off"]._deps(objclass=CreativeState)
    assert any("brief_topic" in names for names in deps.values())


@pytest.mark.usefixtures("ai_off")
def test_with_the_switch_off_an_idea_puts_nothing() -> None:
    creative = _clip()
    entries = start_vm.entries_from_proposal(_proposal(2))
    assert creative._clip_add_idea(entries, None) == (False, "")
    assert [m["kind"] for m in creative._clip_tl_media()] == ["photo", "photo"]
    assert creative.clip_idea_off == "" and not creative.clip_ai_on
