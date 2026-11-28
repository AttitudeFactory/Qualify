"""m-25143223 (PR B): «Ver qué quedó fuera» in «Hacer uno parecido» — the words and rows
(`left_out_vm`), the reads (`left_out_provider`, over the server's real contract) and the
editor's flow (`CreativeState`): the card's button, the tab, the shortcut, the swap that
keeps texts, joins and references, a join that no longer fits, the refusals, the switch
off. Offline: the analysis read is faked, the network is closed — nothing paid."""

from __future__ import annotations

import socket
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.left_out import (
    LEFT_OUT_REASON_TEXTS,
    SPAN_EXTEND_ORDER,
    SPAN_TEXTS,
    SPAN_UNKNOWN,
    LeftOutSpan,
)
from qualify_api.creative.part_extend import EXTEND_SWITCH
from qualify_api.creative.video_pipeline import ai_parts as contract_ai
from qualify_api.referentes import reel_analysis
from qualify_api.referentes.reel_analysis_types import AnalysisStatus, ReelAnalysis
from qualify_creative.effects import RecipeProblem
from qualify_creative.schemas import VideoPartPlan
from qualify_shared.objects.public import reel_frame_key

from . import ai_block_vm as ai_vm
from . import clip_editor_vm, left_out_provider
from . import clip_joins_vm as joins
from . import clip_refs_vm as refs_vm
from . import creative_state as module
from . import left_out_vm as vm
from .creative_state import CreativeState
from .test_editor_idea import _CARD, _IMPORTED, _TENANT, _Proxy
from .test_reel_parts_vm import ANALYSIS_ID, analysis, shot

#: Nine cuts of 5-8 s (none joinable under 10 s): the plan keeps the first six, 44 s of 63.
_ENDS = [8, 15, 22, 29, 36, 44, 51, 58, 63]
_REF = f"uploads/{_TENANT}/ref/a.png"


def _reel(**changes: Any) -> ReelAnalysis:
    starts = [0, *_ENDS[:-1]]
    cuts = [shot(i, a, b) for i, (a, b) in enumerate(zip(starts, _ENDS, strict=True))]
    return replace(analysis(*cuts), **changes)


def _framed(reel: ReelAnalysis, index: int) -> ReelAnalysis:
    """`reel` with two stored frames of cut `index`."""
    cuts = []
    for cut in reel.shots:
        if cut.shot_index == index:
            keys = tuple(reel_frame_key("instagram", "p1", ANALYSIS_ID, index, n) for n in (0, 1))
            cut = replace(cut, frame_keys=keys, frame_times_s=(cut.start_s + 1, cut.start_s + 3))
        cuts.append(cut)
    return replace(reel, shots=tuple(cuts))


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing here may reach a vendor (nothing paid): any connection off this machine
    fails (the event loop's own loopback pair stays)."""
    connect = socket.socket.connect

    def refuse(sock: socket.socket, address: Any) -> None:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError("no network: «Ver qué quedó fuera» pays for nothing")
        connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", refuse)


@pytest.fixture
def ai_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)
    monkeypatch.setenv(contract_ai.CLIP_AI_PARTS_SWITCH, "on")
    monkeypatch.setenv(joins.JOINS_SWITCH, "on")
    monkeypatch.delenv(EXTEND_SWITCH, raising=False)


@pytest.fixture
def reads(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The one database read (`reel_analysis.get_analysis`) answered by `seen.reel`,
    counted; the wait's status `ok`; no sleeping."""
    seen = SimpleNamespace(reel=_reel(), reads=0)

    def get_analysis(tenant_id: UUID, analysis_id: UUID) -> ReelAnalysis | None:
        assert tenant_id == _TENANT
        seen.reads += 1
        return seen.reel if analysis_id == ANALYSIS_ID else None

    def analysis_status(tenant_id: UUID, analysis_id: UUID) -> AnalysisStatus:
        return AnalysisStatus(
            analysis_id=analysis_id,
            status="ok",
            stage=None,
            error_code=None,
            retryable=False,
            queued_for_s=5.0,
            queue_ahead=0,
            shots_found=len(seen.reel.shots),
            covered_to_s=None,
            source_seconds=None,
            source_available=True,
        )

    async def sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(reel_analysis, "get_analysis", get_analysis)
    monkeypatch.setattr(module.reel_wait_provider, "analysis_status", analysis_status)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    return seen


def _proxy(state: CreativeState) -> _Proxy:
    return _Proxy(state, AuthState=SimpleNamespace(session_tenant_id=str(_TENANT)))


async def _laid() -> CreativeState:
    """«Hacer uno parecido» of the nine-cut reel: its six parts laid as blocks, cut."""
    state = CreativeState()
    state.selected_product_id = "burger"
    state.brief_product_ref = "Smash doble"
    state._apply_reel_reference(_CARD, _IMPORTED, str(ANALYSIS_ID), "queued")
    state._clip_session_tenant = str(_TENANT)
    await CreativeState.poll_reel_analysis.fn(_proxy(state))
    assert state.clip_reel_blocks
    assert state.clip_reel_cut == "Usamos 44 s de los 63 del reel."
    return state


def _ai_ids(state: CreativeState) -> list[str]:
    return [str(m["id"]) for m in state._clip_tl_media() if m["kind"] == ai_vm.TL_KIND]


def _span(span_id: str, start: float, end: float, reason: str = "parts_cap", **kw: Any) -> Any:
    return LeftOutSpan(
        id=span_id,
        start_s=start,
        end_s=end,
        seconds=round(end - start),
        description=kw.get("description", "Una mano acerca el vaso"),
        reason=reason,  # type: ignore[arg-type]
        mode_hint=None if reason == "not_analyzed" else "edit",
        thumbnail_key=kw.get("thumbnail_key"),
        shot_indexes=kw.get("shot_indexes", ()),
    )


# -- the words and the rows (`left_out_vm`) ---------------------------------------------------


def test_the_signed_words_read_literally() -> None:
    assert vm.OPEN_LABEL == "Ver qué quedó fuera"
    assert vm.TITLE == "Lo que quedó fuera del reel" == clip_editor_vm.FLOW_QUESTIONS[vm.FLOW]
    assert vm.SHORTCUT_LABEL == "Cambiar por otro tramo del reel"
    assert vm.CHOOSE_FIRST == "Elige primero la parte con IA que quieres cambiar."
    assert vm.swapped_line(2, 44.0, 51.2) == (
        "Cambiaste la parte con IA 2 por el tramo de 0:44 a 0:51 del reel. "
        "No gastas nada hasta «Crear»."
    )
    assert vm.span_range(58.4, 63.0) == "de 0:58 a 1:03"
    assert vm.span_range(3.1, 3.4) == "de 0:03 a 0:04"  # never «de 0:03 a 0:03»
    assert vm.head_line(0) == vm.CHOOSE_FIRST
    assert vm.head_line(3) == "Toca el tramo que quieres poner en vez de la parte con IA 3."


def test_the_rows_say_each_stretch_and_offer_the_swap_only_when_it_can_be_made() -> None:
    spans = [
        vm.span_dict(_span("cut:6", 44.0, 51.0, shot_indexes=(6,)), thumb="/avatar/frame/x"),
        vm.span_dict(_span("cut:7", 51.0, 58.0, shot_indexes=(7,))),
        vm.span_dict(_span("uncovered:end", 63.0, 70.0, "not_analyzed", description="")),
    ]
    aimed = vm.rows(spans, 2)
    assert [r["range"] for r in aimed] == ["de 0:44 a 0:51", "de 0:51 a 0:58", "de 1:03 a 1:10"]
    assert [r["thumb"] for r in aimed] == ["/avatar/frame/x", "", ""]  # the placeholder
    assert aimed[0]["use_label"] == "Usar en vez de la parte con IA 2"
    assert aimed[0]["use"] == aimed[1]["use"] == "1"
    assert aimed[0]["reason"] == LEFT_OUT_REASON_TEXTS["parts_cap"]
    # the end the analysis did not cover: information only
    assert aimed[2]["use"] == aimed[2]["swappable"] == "" and aimed[2]["use_label"] == ""
    assert aimed[2]["reason"] == LEFT_OUT_REASON_TEXTS["not_analyzed"]
    assert vm.INFO_ONLY_ARIA in aimed[2]["aria"]
    # no AI part chosen: every row is information only
    assert all(r["use"] == "" for r in vm.rows(spans, 0))


def test_the_problems_after_a_swap_speak_in_the_contracts_words() -> None:
    texts = vm.problem_texts(
        [
            RecipeProblem(code="local_length_out_of_range", duration_s=64.0),
            RecipeProblem(code="transitions_longer_than_block", field="segments[1]"),
            RecipeProblem(code="local_length_out_of_range", duration_s=64.0),
        ],
        64.0,
    )
    assert len(texts) == 2  # once each
    assert texts[0] == clip_editor_vm.length_out_of_range_line(64.0)
    assert "2" in texts[1]


# -- the reads (`left_out_provider`, the server's real contract) -------------------------------


def test_the_list_has_stretches_with_and_without_a_picture_and_the_end_not_read(
    reads: SimpleNamespace,
) -> None:
    reads.reel = _framed(_reel(source_seconds=70.0), 6)
    plan = [
        VideoPartPlan(mode="edit", seconds=s, analysis_id=ANALYSIS_ID, shot_indexes=(i,))
        for i, s in enumerate((8, 7, 7, 7, 7, 8))
    ]
    rows = left_out_provider.left_out_rows(_TENANT, ANALYSIS_ID, plan, ("Smash doble",))
    assert rows is not None
    assert [r["id"] for r in rows] == ["cut:6", "cut:7", "cut:8", "uncovered:end"]
    assert rows[0]["thumb"].startswith("/avatar/frame/instagram/p1/")  # signed, stored
    assert rows[1]["thumb"] == "" and rows[3]["thumb"] == ""
    assert [r["swappable"] for r in rows] == [True, True, True, False]
    assert reads.reads == 1
    reads.reel = None
    assert left_out_provider.left_out_rows(_TENANT, ANALYSIS_ID, plan) is None


def test_an_unknown_stretch_and_a_tail_without_its_head_are_refused_in_the_contracts_words(
    reads: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, said = left_out_provider.swap_entry(_TENANT, ANALYSIS_ID, "cut:99", [])
    assert plan is None and said == SPAN_TEXTS[SPAN_UNKNOWN]
    plan, said = left_out_provider.swap_entry(_TENANT, ANALYSIS_ID, "uncovered:end", [])
    assert plan is None and said == SPAN_TEXTS[SPAN_UNKNOWN]  # never swappable
    # «Sigue a la anterior» on: a cut of 25 s is a head and its tails; a tail needs its head
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    reads.reel = analysis(shot(0, 0, 25))
    plan, said = left_out_provider.swap_entry(_TENANT, ANALYSIS_ID, "cut:0.1", [])
    assert plan is None and said == SPAN_TEXTS[SPAN_EXTEND_ORDER]
    # the stretch's own part, «Igual al original» with its reel window, as JSON
    reads.reel = _reel()
    plan, said = left_out_provider.swap_entry(_TENANT, ANALYSIS_ID, "cut:6", [])
    assert said == "" and plan is not None
    assert plan["mode"] == "edit" and plan["shot_indexes"] == [6]
    assert plan["analysis_id"] == str(ANALYSIS_ID) and plan["transition_in"] is None


# -- the editor (`CreativeState`) ---------------------------------------------------------------


@pytest.mark.usefixtures("ai_on")
async def test_the_card_opens_the_list_and_without_a_part_chosen_asks_to_choose_one(
    reads: SimpleNamespace,
) -> None:
    state = await _laid()
    assert state.clip_left_out_on
    assert vm.TAB[0] == clip_editor_vm.FLOW_LEFT_OUT
    assert state.clip_edit_block == ""
    events = CreativeState.open_clip_left_out.fn(state)
    assert state.clip_tl_flow == clip_editor_vm.FLOW_LEFT_OUT and state.clip_flow_drawer_open
    assert CreativeState.load_clip_left_out in events
    assert state.clip_left_out_phase == "loading"
    await CreativeState.load_clip_left_out.fn(_proxy(state))
    assert state.clip_left_out_phase == "ready"
    assert [r["id"] for r in state.clip_left_out_rows] == ["cut:6", "cut:7", "cut:8"]
    assert state.clip_left_out_head == vm.CHOOSE_FIRST
    assert all(r["use"] == "" for r in state.clip_left_out_rows)
    # a swap asked without a part does nothing
    parts = [dict(p) for p in state.clip_ai_parts]
    await CreativeState.swap_clip_left_out.fn(_proxy(state), "cut:6")
    assert state.clip_ai_parts == parts


@pytest.mark.usefixtures("ai_on")
async def test_the_parts_shortcut_opens_the_list_aimed_at_it(reads: SimpleNamespace) -> None:
    state = await _laid()
    second = _ai_ids(state)[1]
    CreativeState.select_clip_block.fn(state, second)
    assert state.clip_left_out_shortcut
    CreativeState.open_clip_left_out_for_part.fn(state)
    assert state.clip_tl_flow == clip_editor_vm.FLOW_LEFT_OUT
    await CreativeState.load_clip_left_out.fn(_proxy(state))
    assert state.clip_left_out_head == vm.head_line(2)
    assert state.clip_left_out_rows[0]["use_label"] == "Usar en vez de la parte con IA 2"
    # the card's button, with that part chosen, aims at it too
    CreativeState.done_clip_block.fn(state)
    CreativeState.select_clip_block.fn(state, second)
    CreativeState.open_clip_left_out.fn(state)
    assert state._clip_left_out_target == second
    # the tab bar walks back to it with the same aim
    CreativeState.switch_clip_flow.fn(state, clip_editor_vm.FLOW_TEXT)
    CreativeState.switch_clip_flow.fn(state, clip_editor_vm.FLOW_LEFT_OUT)
    assert state._clip_left_out_target == second


@pytest.mark.usefixtures("ai_on")
async def test_a_swap_keeps_the_place_texts_joins_and_references_and_asks_again(
    reads: SimpleNamespace,
) -> None:
    state = await _laid()
    ids = _ai_ids(state)
    second = ids[1]
    span = next(sp for sp in state._clip_ai_spans() if sp["id"] == second)
    state._clip_refs_store([refs_vm.new_item([], "photo", [_REF], span["start"], span["end"])])
    state._clip_keep_joins({second: joins.FADE})
    text = {
        "uid": "t1",
        "text": "2×1 hoy",
        "place": "top",
        "start": float(span["start"]) + 0.5,
        "end": float(span["start"]) + 3.0,
        "blocks": [],
        "fade": 0.5,
    }
    state.clip_text_uses = [dict(text)]
    uid = state.clip_ai_parts[1]["uid"]
    CreativeState.select_clip_block.fn(state, second)
    CreativeState.open_clip_left_out_for_part.fn(state)
    await CreativeState.load_clip_left_out.fn(_proxy(state))
    reads.reads = 0
    await CreativeState.swap_clip_left_out.fn(_proxy(state), "cut:8")  # 58-63 s, 5 s
    assert reads.reads == 2  # the part, then the list again — one read each, nothing paid
    # the same block, in the same place, with the stretch's part
    assert _ai_ids(state) == ids and state.clip_ai_parts[1]["uid"] == uid
    plan = state.clip_ai_parts[1]["plan"]
    assert plan["mode"] == "edit" and plan["shot_indexes"] == [8] and plan["seconds"] == 5
    assert state.clip_ai_parts[1]["desc_rev"] == 1  # the panel shows the new words
    moved = next(sp for sp in state._clip_ai_spans() if sp["id"] == second)
    assert round(float(moved["end"]) - float(moved["start"]), 2) == 5.0
    # the text, the fade (it still fits) and the reference stay with the part
    assert [t["text"] for t in state.clip_text_uses] == ["2×1 hoy"]
    assert state.clip_block_joins == {second: joins.FADE}
    assert len(state.clip_refs) == 1
    assert float(state.clip_refs[0]["start"]) == pytest.approx(float(moved["start"]))
    assert state.clip_edit_notice.startswith(vm.swapped_line(2, 58.0, 63.0))
    assert state.clip_left_out_said == state.clip_edit_notice
    assert state.clip_left_out_problems == []
    # the list was asked again: the stretch went in, the part it replaced is out
    assert state.clip_left_out_phase == "ready"
    listed = [r["id"] for r in state.clip_left_out_rows]
    assert "cut:8" not in listed and "cut:1" in listed


@pytest.mark.usefixtures("ai_on")
async def test_a_join_that_no_longer_fits_goes_back_to_corte_and_the_line_says_it(
    reads: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = await _laid()
    second = _ai_ids(state)[1]
    state._clip_keep_joins({second: joins.FADE})
    CreativeState.select_clip_block.fn(state, second)
    CreativeState.open_clip_left_out_for_part.fn(state)
    await CreativeState.load_clip_left_out.fn(_proxy(state))
    # the server's room check says the swapped block is now too short for its fade
    monkeypatch.setattr(
        module.clip_joins_vm,
        "room_problems",
        lambda _segments: {1: "x"} if second in state.clip_block_joins else {},
    )
    await CreativeState.swap_clip_left_out.fn(_proxy(state), "cut:6")
    assert state.clip_block_joins == {}
    assert vm.JOIN_DROPPED["before"] in state.clip_edit_notice
    assert state.clip_edit_notice.startswith(vm.swapped_line(2, 44.0, 51.0))


@pytest.mark.usefixtures("ai_on")
async def test_a_refused_stretch_says_why_and_changes_nothing(
    reads: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = await _laid()
    second = _ai_ids(state)[1]
    CreativeState.select_clip_block.fn(state, second)
    CreativeState.open_clip_left_out_for_part.fn(state)
    await CreativeState.load_clip_left_out.fn(_proxy(state))
    parts = [dict(p) for p in state.clip_ai_parts]
    monkeypatch.setattr(
        module.left_out_provider,
        "swap_entry",
        lambda *_a: (None, SPAN_TEXTS[SPAN_EXTEND_ORDER]),
    )
    await CreativeState.swap_clip_left_out.fn(_proxy(state), "cut:7")
    assert state.clip_left_out_error == SPAN_TEXTS[SPAN_EXTEND_ORDER]
    assert state.clip_ai_parts == parts
    assert state.clip_left_out_phase == "ready"  # the list was asked again
    # an id no longer listed is never sent
    calls: list[str] = []
    monkeypatch.setattr(
        module.left_out_provider, "swap_entry", lambda *a: calls.append(a[2]) or (None, "")
    )
    await CreativeState.swap_clip_left_out.fn(_proxy(state), "cut:42")
    assert calls == []


@pytest.mark.usefixtures("ai_on")
async def test_a_failed_read_offers_to_try_again(
    reads: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = await _laid()
    CreativeState.open_clip_left_out.fn(state)

    def broken(*_a: Any) -> None:
        raise RuntimeError("database blip")

    monkeypatch.setattr(module.left_out_provider, "left_out_rows", broken)
    await CreativeState.load_clip_left_out.fn(_proxy(state))
    assert state.clip_left_out_phase == "error" and state.clip_left_out_rows == []
    assert CreativeState.retry_clip_left_out.fn(state) is CreativeState.load_clip_left_out


@pytest.mark.usefixtures("ai_on")
async def test_a_reel_that_was_not_cut_shows_nothing(reads: SimpleNamespace) -> None:
    reads.reel = analysis(shot(0, 0, 5), shot(1, 5, 9))
    state = CreativeState()
    state._apply_reel_reference(_CARD, _IMPORTED, str(ANALYSIS_ID), "queued")
    await CreativeState.poll_reel_analysis.fn(_proxy(state))
    assert state.clip_reel_blocks and state.clip_reel_cut == ""
    assert not state.clip_left_out_on
    assert CreativeState.open_clip_left_out.fn(state) == []
    assert state.clip_tl_flow == ""


@pytest.mark.usefixtures("ai_on")
async def test_with_the_switch_off_nothing_of_it_shows(
    reads: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = await _laid()
    second = _ai_ids(state)[1]
    CreativeState.select_clip_block.fn(state, second)
    monkeypatch.delenv(contract_ai.CLIP_AI_PARTS_SWITCH)
    assert not state.clip_left_out_on and not state.clip_left_out_shortcut
    assert state.clip_left_out_rows == [] and state.clip_left_out_head == ""
    assert CreativeState.open_clip_left_out.fn(state) == []
    assert CreativeState.open_clip_left_out_for_part.fn(state) == []
    assert CreativeState.open_clip_flow.fn(state, clip_editor_vm.FLOW_LEFT_OUT) == []
    reads.reads = 0
    await CreativeState.load_clip_left_out.fn(_proxy(state))
    assert reads.reads == 0


@pytest.mark.usefixtures("ai_on")
async def test_a_new_reel_lets_the_list_go(reads: SimpleNamespace) -> None:
    state = await _laid()
    CreativeState.open_clip_left_out.fn(state)
    await CreativeState.load_clip_left_out.fn(_proxy(state))
    assert state._clip_left_out_spans
    state._apply_reel_reference(_CARD, _IMPORTED, str(ANALYSIS_ID), "queued")
    assert state._clip_left_out_spans == [] and state.clip_left_out_phase == ""
