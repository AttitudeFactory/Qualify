"""UI-2 (m-24921076): step 2's wait for the reel's analysis in `CreativeState` — the poll's
guards (business, id, step, one loop at a time), «Siguiente» held while waiting, and the
ways forward. The backend reads are monkeypatched: no database, no network, no vendor."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.referentes.reel_analysis_types import AnalysisStatus
from qualify_creative.schemas import VideoPartPlan

from . import creative_state as module
from . import reel_wait_vm as vm
from .creative_state import CreativeState

TENANT = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"
CARD = {
    "key": "instagram:A",
    "network": "instagram",
    "id": "A",
    "url": "https://www.instagram.com/reel/A/",
    "handle": "smash_hiro",
}
IMPORTED = {"key": f"uploads/{TENANT}/referencia-reel.mp4", "name": "Reel · 5 s"}


def status(state: str, analysis_id: UUID, **kw: Any) -> AnalysisStatus:
    base: dict[str, Any] = {
        "stage": None,
        "error_code": None,
        "retryable": False,
        "queued_for_s": 5.0,
        "queue_ahead": 0,
        "shots_found": 0,
        "covered_to_s": None,
        "source_seconds": None,
        "source_available": True,
    }
    base.update(kw)
    return AnalysisStatus(analysis_id=analysis_id, status=state, **base)


class Proxy:
    """`async with self` / `get_state` over a plain `CreativeState` (as in
    `test_reel_replication.Proxy`)."""

    def __init__(self, state: CreativeState, auth: SimpleNamespace) -> None:
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "auth", auth)

    async def __aenter__(self) -> Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_state(self, cls: type) -> Any:
        assert cls is module.AuthState
        return self.auth

    def __getattr__(self, name: str) -> Any:
        return getattr(self.state, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.state, name, value)


def replica(outcome: str = "queued", analysis_id: str | None = None) -> CreativeState:
    """A piece opened by «Hacer uno parecido», on step 2 («Qué mostrar»)."""
    state = CreativeState()
    state.selected_product_id = "burger"
    state.brief_product_ref = "Smash doble"
    state.product_confirmed = True
    aid = str(uuid4()) if analysis_id is None else analysis_id
    state._apply_reel_reference(CARD, IMPORTED, aid, outcome)
    return state


def fake_entries(n: int) -> list[dict[str, Any]]:
    """`n` parts as the provider's entries (UI-3), without an analysis behind them."""
    plan = VideoPartPlan(mode="reference", seconds=4).model_dump(mode="json")
    return [
        {"key": f"k{i}", "plan": dict(plan), "person": False, "reason": "added"} for i in range(n)
    ]


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The provider's two reads, scripted per test; `sleep` runs `on_tick` instead of
    waiting (the test's chance to change the session between two ticks)."""
    seen = SimpleNamespace(
        statuses=[], status_calls=[], plan_calls=[], parts=3, on_tick=None, ticks=0
    )

    def analysis_status(tenant_id: UUID, analysis_id: UUID) -> AnalysisStatus | None:
        seen.status_calls.append((tenant_id, analysis_id))
        answer = seen.statuses.pop(0) if len(seen.statuses) > 1 else seen.statuses[0]
        if isinstance(answer, Exception):
            raise answer
        return answer(analysis_id) if callable(answer) else answer

    def reel_plan(
        tenant_id: UUID, analysis_id: UUID, products: tuple[str, ...]
    ) -> list[dict[str, Any]] | None:
        seen.plan_calls.append((tenant_id, analysis_id, tuple(products)))
        if seen.parts is None:
            return None
        return fake_entries(seen.parts)

    async def sleep(_seconds: float) -> None:
        seen.ticks += 1
        if seen.ticks > 50:
            pytest.fail("the poll never stopped")
        if seen.on_tick is not None:
            seen.on_tick()

    monkeypatch.setattr(module.reel_wait_provider, "analysis_status", analysis_status)
    monkeypatch.setattr(module.reel_wait_provider, "reel_plan", reel_plan)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    return seen


async def poll(state: CreativeState, auth: SimpleNamespace | None = None) -> None:
    proxy = Proxy(state, auth or SimpleNamespace(session_tenant_id=TENANT))
    await CreativeState.poll_reel_analysis.fn(proxy)


def queued(aid: UUID) -> AnalysisStatus:
    return status("queued", aid)


def ok(aid: UUID) -> AnalysisStatus:
    return status("ok", aid)


# -- what «Hacer uno parecido» leaves on step 2 ---------------------------------------


def test_a_pending_analysis_holds_next_with_the_reason() -> None:
    state = replica("queued")
    assert state.reel_wait_shown and state.reel_wait_pending
    assert state.gen_step_key == "show"
    assert state.create_primary_disabled
    assert state.create_reason == "Disponible cuando terminemos de mirar el reel."
    assert state.next_view() is None and state.gen_step_key == "show"
    assert state.go_to_view("2") is None and state.gen_step_key == "show"


@pytest.mark.parametrize(
    ("outcome", "title"),
    [
        ("no_video", "No pudimos bajar el video de este reel."),
        ("daily_limit", "Por hoy no podemos mirar más reels para tu negocio."),
        (vm.OUTCOME_UNASKED, "No pudimos mirar este reel."),
    ],
)
def test_an_outcome_without_an_id_is_kept_and_says_why(outcome: str, title: str) -> None:
    state = replica(outcome, analysis_id="")
    assert state.reel_analysis_id == "" and state.reel_analysis_status == outcome
    assert state.reel_wait_phase == vm.PHASE_ERROR and state.reel_wait_error_title == title
    assert state.reel_wait_without and state.reel_wait_shown and not state.reel_wait_pending


def test_a_normal_clip_has_no_wait_and_nothing_held() -> None:
    state = CreativeState()
    state.selected_product_id = "burger"
    state.product_confirmed = True
    state.gen_mode = "create"
    assert not state.reel_wait_shown and not state.create_primary_disabled
    assert state.create_reason == ""


def test_going_without_the_reel_forgets_the_analysis_and_keeps_the_piece() -> None:
    state = replica("queued")
    state.reel_go_without()
    assert state.reel_analysis_id == "" and state.reel_analysis_status == ""
    assert not state.reel_wait_shown and not state.create_primary_disabled
    assert state.from_reel_ideas and state.create_back_label == "Ideas para tus reels"
    assert state.clip_videos and state.clip_videos[0]["source"] == "reel"
    assert state.next_view() is not None and state.gen_step_key != "show"


def test_picking_another_reel_goes_back_to_the_ideas_and_forgets_it() -> None:
    state = replica("no_video", analysis_id="")
    state.exit_create()
    assert not state.from_reel_ideas and state.reel_analysis_status == ""
    assert not state.reel_wait_shown


# -- the poll -------------------------------------------------------------------------


async def test_the_poll_follows_the_stages_until_the_plan_is_counted(backend) -> None:
    state = replica("queued")
    aid = UUID(state.reel_analysis_id)
    backend.statuses = [
        queued,
        lambda a: status("running", a, stage="downloading"),
        lambda a: status("running", a, stage="describing"),
        ok,
    ]
    shown: list[str] = []
    backend.on_tick = lambda: shown.append(state.reel_wait_stage)
    await poll(state)
    assert shown == [
        "Estamos mirando este reel…",
        "Bajando el video",
        "Revisando si aparece alguien",
    ]
    assert state.reel_wait_phase == vm.PHASE_READY
    assert state.reel_wait_stage == "Encontramos 3 partes" and state.reel_parts_count == 3
    assert not state.create_primary_disabled and state.create_reason == ""
    assert all(call == (UUID(TENANT), aid) for call in backend.status_calls)
    assert backend.plan_calls == [(UUID(TENANT), aid, ("Smash doble",))]
    assert not state._reel_poll_live


async def test_an_already_analysed_reel_goes_straight_to_its_parts(backend) -> None:
    state = replica("ok")
    assert state.reel_wait_stage == "Armando tu propuesta" and state.reel_wait_pending
    backend.statuses, backend.parts = [ok], 1
    await poll(state)
    assert backend.ticks == 0  # one read, no wait
    assert state.reel_single_part and state.reel_wait_stage == "Encontramos 1 parte"
    assert not state.create_primary_disabled


@pytest.mark.parametrize(
    ("answer", "title", "pick_other"),
    [
        (
            lambda a: status("failed", a, error_code="source_expired"),
            "No pudimos bajar el video de este reel.",
            True,
        ),
        (
            lambda a: status("failed", a, error_code="model_failed"),
            "No pudimos mirar este reel.",
            True,
        ),
        (None, "No pudimos mirar este reel.", True),
    ],
)
async def test_a_terminal_failure_stops_with_a_way_forward(
    backend, answer: Any, title: str, pick_other: bool
) -> None:
    state = replica("queued")
    backend.statuses = [answer]
    await poll(state)
    assert backend.ticks == 0 and len(backend.status_calls) == 1
    assert state.reel_wait_phase == vm.PHASE_ERROR and state.reel_wait_error_title == title
    assert state.reel_wait_pick_other is pick_other and state.reel_wait_without
    assert not state._reel_poll_live


async def test_a_long_wait_offers_going_without_and_keeps_polling(backend) -> None:
    state = replica("queued")
    backend.statuses = [lambda a: status("queued", a, queued_for_s=400.0), ok]
    slow: list[bool] = []
    backend.on_tick = lambda: slow.append(state.reel_wait_slow and state.reel_wait_without)
    await poll(state)
    assert slow == [True] and state.reel_wait_phase == vm.PHASE_READY


def _changes(state: CreativeState, auth: SimpleNamespace) -> dict[str, Callable[[], None]]:
    def other_tenant() -> None:
        auth.session_tenant_id = OTHER

    def other_id() -> None:
        state.reel_analysis_id = str(uuid4())

    def left_step() -> None:
        state.gen_step = 1

    def left_create() -> None:
        state.gen_mode = "discover"

    def without() -> None:
        state.reel_go_without()

    def unmounted() -> None:
        state.leave_reel_wait()

    return {
        "tenant": other_tenant,
        "id": other_id,
        "step": left_step,
        "mode": left_create,
        "without": without,
        "unmount": unmounted,
    }


@pytest.mark.parametrize("change", ["tenant", "id", "step", "mode", "without", "unmount"])
async def test_the_poll_stops_when_the_session_moves_on(backend, change: str) -> None:
    state = replica("queued")
    auth = SimpleNamespace(session_tenant_id=TENANT)
    backend.statuses = [queued, ok]
    backend.on_tick = _changes(state, auth)[change]
    before = state.reel_wait_phase if change not in ("without",) else vm.PHASE_IDLE
    await poll(state, auth)
    # nothing is read for a session that moved on, nor applied to it
    assert backend.ticks == 1 and len(backend.status_calls) == 1
    assert backend.plan_calls == []
    assert state.reel_wait_phase == before and state.reel_parts_count == 0


async def test_the_poll_seals_the_business_and_the_id_from_the_session(backend) -> None:
    state = replica("queued")
    backend.statuses = [ok]
    await poll(state)
    assert backend.status_calls == [(UUID(TENANT), UUID(state.reel_analysis_id))]


async def test_no_session_business_no_poll(backend) -> None:
    state = replica("queued")
    backend.statuses = [ok]
    await poll(state, SimpleNamespace(session_tenant_id=""))
    assert backend.status_calls == [] and state.reel_wait_pending


async def test_one_loop_at_a_time(backend) -> None:
    state = replica("queued")
    state._reel_poll_live = True  # another loop of this process is running, and ticking
    state._reel_poll_owner = module._PROCESS_ID
    state._reel_poll_beat = module.time.time()
    backend.statuses = [ok]
    await poll(state)
    assert backend.status_calls == []


async def test_a_loop_that_died_with_the_server_does_not_block_a_new_one(backend) -> None:
    state = replica("queued")
    state._reel_poll_live = True  # the mark outlived its loop
    state._reel_poll_beat = module.time.time() - 120
    backend.statuses = [ok]
    await poll(state)
    assert len(backend.status_calls) == 1 and state.reel_wait_phase == vm.PHASE_READY


async def test_nothing_to_poll_for_a_normal_clip_or_a_terminal_state(backend) -> None:
    backend.statuses = [ok]
    plain = CreativeState()
    await poll(plain)
    done = replica("no_video", analysis_id="")
    await poll(done)
    assert backend.status_calls == []


async def test_an_unreadable_id_fails_closed_without_reading(backend) -> None:
    state = replica("queued", analysis_id="not-a-uuid")
    backend.statuses = [ok]
    await poll(state)
    assert backend.status_calls == [] and state.reel_wait_phase == vm.PHASE_ERROR
    assert state.reel_wait_without


async def test_a_new_replica_stops_the_previous_poll(backend) -> None:
    state = replica("queued")
    backend.statuses = [queued, ok]
    backend.on_tick = lambda: state._apply_reel_reference(CARD, IMPORTED, str(uuid4()), "queued")
    await poll(state)
    assert backend.ticks == 1 and len(backend.status_calls) == 1 and backend.plan_calls == []
    assert state.reel_wait_phase == vm.PHASE_WAITING and not state._reel_poll_live


# -- review fixes: transient reads, a tab that is gone, a restart ---------------------


async def test_a_failed_read_keeps_the_wait_and_retries(backend) -> None:
    state = replica("queued")
    backend.statuses = [
        lambda a: status("running", a, stage="detecting"),
        RuntimeError("pool timeout"),
        RuntimeError("pool timeout"),
        ok,
    ]
    shown: list[str] = []
    backend.on_tick = lambda: shown.append(state.reel_wait_stage)
    await poll(state)
    # two blips in a row keep «Mirando qué pasa» on screen; the next good read goes on
    assert shown == ["Mirando qué pasa"] * 3
    assert state.reel_wait_phase == vm.PHASE_READY


async def test_three_failed_reads_in_a_row_give_up_with_a_way_forward(backend) -> None:
    state = replica("queued")
    backend.statuses = [queued, RuntimeError("down"), RuntimeError("down"), RuntimeError("down")]
    await poll(state)
    assert len(backend.status_calls) == 4
    assert state.reel_wait_error_title == "No pudimos mirar este reel."
    assert state.reel_wait_without and not state.reel_poll_live


async def test_a_good_read_resets_the_failure_count(backend) -> None:
    state = replica("queued")
    blip = RuntimeError("blip")
    backend.statuses = [blip, blip, queued, blip, blip, ok]
    await poll(state)
    assert state.reel_wait_phase == vm.PHASE_READY


async def test_a_gone_row_fails_at_once(backend) -> None:
    state = replica("queued")
    backend.statuses = [None]
    await poll(state)
    assert backend.ticks == 0 and state.reel_wait_phase == vm.PHASE_ERROR


async def test_the_poll_stops_when_the_tab_stops_saying_it_is_there(backend) -> None:
    state = replica("queued")
    backend.statuses = [queued]

    def tab_gone() -> None:
        state._reel_seen_at = module.time.time() - module._REEL_CLIENT_GONE_SECONDS - 1

    backend.on_tick = tab_gone
    await poll(state)
    assert backend.ticks == 1 and len(backend.status_calls) == 1
    assert not state.reel_poll_live and not state._reel_poll_live


async def test_the_heartbeat_keeps_a_long_wait_polling(backend) -> None:
    state = replica("queued")
    backend.statuses = [queued, queued, queued, ok]

    def heartbeat_late() -> None:
        # time passes past the gone-limit, but the mounted view keeps beating
        state._reel_seen_at = module.time.time()

    backend.on_tick = heartbeat_late
    await poll(state)
    assert state.reel_wait_phase == vm.PHASE_READY


def test_the_heartbeat_restarts_a_poll_no_loop_runs() -> None:
    state = replica("queued")
    state.reel_poll_live = True  # persisted from a process that restarted
    state._reel_poll_live = True
    state._reel_poll_owner = "another-process"
    state._reel_poll_beat = module.time.time()
    events = state.reel_wait_heartbeat()
    assert "poll_reel_analysis" in str(events)
    assert not state.reel_poll_live  # «Armar sin el reel» shows until it is back


def test_the_heartbeat_leaves_a_running_poll_alone() -> None:
    state = replica("queued")
    state._reel_poll_live = state.reel_poll_live = True
    state._reel_poll_owner = module._PROCESS_ID
    state._reel_poll_beat = module.time.time()
    assert state.reel_wait_heartbeat() == [] and state.reel_poll_live


def test_nothing_to_resume_for_a_finished_wait_or_a_normal_clip() -> None:
    assert replica("no_video", analysis_id="").reel_wait_heartbeat() == []
    assert CreativeState().reel_wait_heartbeat() == []


async def test_a_mark_from_another_process_does_not_block_a_new_poll(backend) -> None:
    state = replica("queued")
    state._reel_poll_live = True
    state._reel_poll_owner = "another-process"
    state._reel_poll_beat = module.time.time()  # fresh, but not ours
    backend.statuses = [ok]
    await poll(state)
    assert len(backend.status_calls) == 1 and state.reel_wait_phase == vm.PHASE_READY


def test_the_page_load_resumes_a_pending_wait() -> None:
    from reflex.istate.data import ReflexURL, RouterData

    state = replica("queued")
    state.router = RouterData(url=ReflexURL("http://localhost:3000/create?paso=2"))
    events = state.enter_create_step()
    assert "__qStepEntry" in str(events) and "poll_reel_analysis" in str(events)
    plain = CreativeState()
    plain.router = RouterData(url=ReflexURL("http://localhost:3000/create?paso=2"))
    assert "poll_reel_analysis" not in str(plain.enter_create_step())


def test_a_live_poll_flag_is_what_hides_the_way_out() -> None:
    state = replica("queued")
    assert not state.reel_poll_live  # no loop yet: the view offers «Armar sin el reel»
    state.leave_reel_wait()
    assert not state.reel_poll_live


# -- Deivid 2026-11-07: the wait is the whole step; 3 failed reads; a paused fleet ----


def test_the_wait_takes_the_whole_step_while_looking_and_on_error() -> None:
    assert replica("queued").reel_wait_takes_step  # pending
    assert replica("ok").reel_wait_takes_step  # planning: still being looked at
    assert replica("no_video", analysis_id="").reel_wait_takes_step  # error


def test_the_usual_step_is_back_once_ok_or_without_the_reel() -> None:
    ready = replica("queued")
    ready._show_reel_wait(vm.ready(3))
    assert not ready.reel_wait_takes_step and ready.reel_wait_shown
    gone = replica("queued")
    gone.reel_go_without()
    assert not gone.reel_wait_takes_step and not gone.reel_wait_shown


def test_a_normal_clip_keeps_its_step() -> None:
    state = CreativeState()
    state.gen_mode = "create"
    assert not state.reel_wait_takes_step


def test_the_view_hides_the_usual_step_behind_the_wait() -> None:
    from .content_generator import _step_show

    rendered = str(_step_show())
    assert "reel_wait_takes_step" in rendered


def test_the_wait_gives_up_after_exactly_three_failed_reads() -> None:
    assert module._REEL_POLL_MAX_FAILURES == 3


async def test_two_failed_reads_are_not_enough(backend) -> None:
    state = replica("queued")
    blip = RuntimeError("blip")
    backend.statuses = [blip, blip, queued]
    states: list[str] = []

    def stop_after_third() -> None:
        states.append(state.reel_wait_phase)
        if len(states) == 3:
            state.leave_reel_wait()

    backend.on_tick = stop_after_third
    await poll(state)
    assert states == [vm.PHASE_WAITING] * 3 and len(backend.status_calls) == 3


async def test_a_paused_fleet_says_so_keeps_next_held_and_keeps_polling(backend) -> None:
    state = replica("queued")
    backend.statuses = [lambda a: status("queued", a, fleet_paused=True, queued_for_s=900.0), ok]
    seen: list[tuple[str, bool, str]] = []
    backend.on_tick = lambda: seen.append(
        (state.reel_wait_notice, state.create_primary_disabled, state.create_reason)
    )
    await poll(state)
    assert seen == [(vm.PAUSED_TEXT, True, "Disponible cuando terminemos de mirar el reel.")]
    assert state.reel_wait_phase == vm.PHASE_READY and state.reel_wait_notice == ""
