"""UI-7 (m-24921082): `PartProgressState` — the one poll (stop rule, generation token,
UI-9 hook, live announcements) and the row buttons (only what the row offers, the
session's user, refusals worded per row, only that row waits). The provider is
monkeypatched: no database, no vendor."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.fsm import InvalidTransition
from qualify_api.creative.part_progress import (
    PartAction,
    PartProgress,
    PartProgressRow,
    PartState,
)
from qualify_api.creative.parts import PartChangeRefused
from qualify_api.creative.service import UnknownDraft

from . import part_progress_provider as provider
from . import part_progress_state as module
from .part_progress_state import PartProgressState

TENANT = "00000000-0000-0000-0000-000000000001"
USER = uuid4()
PARENT = uuid4()


def row(index: int, state: PartState, *actions: PartAction, total: int = 2) -> PartProgressRow:
    return PartProgressRow(
        index=index,
        total=total,
        draft_id=uuid4(),
        mode="reference",
        seconds=4,
        state=state,
        actions=tuple(actions),
    )


def progress(*rows: PartProgressRow) -> PartProgress:
    return PartProgress(parent_id=PARENT, parts=tuple(rows))


CREATING = progress(row(1, PartState.TO_REVIEW), row(2, PartState.CREATING))
UNMADE = progress(row(1, PartState.TO_REVIEW), row(2, PartState.UNMADE))
DONE = progress(row(1, PartState.TO_REVIEW), row(2, PartState.READY))
FAILED = progress(
    row(1, PartState.TO_REVIEW),
    row(2, PartState.FAILED, PartAction.RETRY, PartAction.CHANGE, PartAction.REMOVE),
)
#: one row per served action, each offering it
OFFERS = {
    "retry": FAILED,
    "make_new": progress(
        row(1, PartState.TO_REVIEW), row(2, PartState.ORIGINAL_REFUSED, PartAction.MAKE_NEW)
    ),
    "recreate": progress(row(1, PartState.TO_REVIEW), row(2, PartState.REDO, PartAction.RECREATE)),
}


class Proxy:
    """`async with self` / `get_state` over a plain state (as `test_reel_wait_state`)."""

    def __init__(self, state: PartProgressState, auth: SimpleNamespace, final: Any) -> None:
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "auth", auth)
        object.__setattr__(self, "final", final)

    async def __aenter__(self) -> Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_state(self, cls: type) -> Any:
        if cls is module.AuthState:
            return self.auth
        assert cls is FakeFinalVideoState
        return self.final

    def __getattr__(self, name: str) -> Any:
        return getattr(self.state, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self.state, name, value)


class FakeFinalVideoState:
    """UI-9's `FinalVideoState` stand-in: `refresh(parent_id)` and `wants_refresh`."""

    wants_refresh = False

    @staticmethod
    def refresh(parent_id: str) -> tuple[str, str]:
        return ("refresh", parent_id)


def session(tenant: str = TENANT, user: str = str(USER)) -> SimpleNamespace:
    return SimpleNamespace(session_tenant_id=tenant, _session_user_id=user)


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    seen = SimpleNamespace(
        reads=[], read_calls=0, actions=[], action_error=None, on_tick=None, ticks=0
    )

    def read_progress(tenant_id: UUID, parent_id: UUID) -> PartProgress | None:
        seen.read_calls += 1
        answer = seen.reads.pop(0) if len(seen.reads) > 1 else seen.reads[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def run_action(action: str, **kw: Any) -> UUID:
        seen.actions.append((action, kw))
        if seen.action_error is not None:
            raise seen.action_error
        return uuid4()

    async def sleep(_seconds: float) -> None:
        seen.ticks += 1
        if seen.ticks > 50:
            pytest.fail("the poll never stopped")
        if seen.on_tick is not None:
            seen.on_tick()

    async def to_thread(fn: Any, *args: Any, **kw: Any) -> Any:
        return fn(*args, **kw)

    monkeypatch.setattr(provider, "read_progress", read_progress)
    monkeypatch.setattr(provider, "run_action", run_action)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    monkeypatch.setattr(module.asyncio, "to_thread", to_thread)
    monkeypatch.setattr(module, "_final_video_state", lambda: FakeFinalVideoState)
    return seen


def mounted() -> PartProgressState:
    state = PartProgressState()
    state.watch(str(PARENT))
    return state


def shown(shown_progress: PartProgress) -> PartProgressState:
    state = mounted()
    state._apply(shown_progress)
    return state


async def collect(gen: Any) -> list[Any]:
    return [event async for event in gen]


async def poll(
    state: PartProgressState, *, auth: SimpleNamespace | None = None, final: Any = None
) -> list[Any]:
    proxy = Proxy(state, auth or session(), final or FakeFinalVideoState())
    return await collect(PartProgressState.poll.fn(proxy))


async def tap(
    state: PartProgressState, index: int, action: str, auth: SimpleNamespace | None = None
) -> list[Any]:
    proxy = Proxy(state, auth or session(), FakeFinalVideoState())
    return await collect(PartProgressState.run_part_action.fn(proxy, index, action))


# -- mount ------------------------------------------------------------------------------


def test_mounting_starts_the_poll_and_refreshes_the_whole_video(backend) -> None:
    state = PartProgressState()
    events = state.watch(str(PARENT))
    assert len(events) == 2
    assert ("refresh", str(PARENT)) in events


def test_the_ui9_hook_is_empty_while_its_state_is_not_built() -> None:
    # TODO(UI-9): goes away with the ImportError guard
    try:
        import Qualify.final_video_card_state  # noqa: F401
    except ImportError:
        assert module._final_video_refresh(str(PARENT)) == []


# -- the stop rule ----------------------------------------------------------------------


async def test_the_poll_runs_while_a_part_is_being_created_and_stops_after(backend) -> None:
    backend.reads = [CREATING, CREATING, DONE]
    state = mounted()
    events = await poll(state)
    assert backend.read_calls == 3
    assert state.complete is True and state.value == 100
    # refreshed when the states changed (first read, then done) — not on the idle tick
    assert events == [("refresh", str(PARENT)), ("refresh", str(PARENT))]
    assert [r.word for r in state.rows] == ["Para revisar", "Lista"]
    assert state.title == "Tus partes ya están creadas" and state.step_status == "done"


async def test_an_unmade_part_keeps_the_poll(backend) -> None:
    backend.reads = [UNMADE, UNMADE, CREATING, DONE]
    state = mounted()
    await poll(state)
    assert backend.read_calls == 4


async def test_nothing_in_progress_reads_once_and_stops(backend) -> None:
    backend.reads = [FAILED]
    state = mounted()
    await poll(state)
    assert backend.read_calls == 1 and backend.ticks == 0
    assert state.title == "Falta que decidas qué hacer con una parte"
    assert state.live_text == "Cuando decidas, seguimos con tu video."


async def test_a_join_in_progress_keeps_the_poll_and_refreshes_every_tick(backend) -> None:
    backend.reads = [DONE]
    final = FakeFinalVideoState()
    final.wants_refresh = True

    def joined() -> None:
        if backend.ticks >= 2:
            final.wants_refresh = False

    backend.on_tick = joined
    state = mounted()
    events = await poll(state, final=final)
    assert backend.read_calls == 3
    assert events == [("refresh", str(PARENT))] * 2


async def test_unmounting_stops_the_poll(backend) -> None:
    backend.reads = [CREATING]
    state = mounted()
    backend.on_tick = state.leave
    await poll(state)
    assert backend.read_calls == 1


async def test_a_newer_loop_supersedes_the_older_one(backend) -> None:
    backend.reads = [CREATING]
    state = mounted()

    def another_loop_started() -> None:
        state._poll_token += 1  # what a second `poll` does at its start

    backend.on_tick = another_loop_started
    await poll(state)
    assert backend.read_calls == 1


async def test_another_parent_or_business_stops_the_poll(backend) -> None:
    backend.reads = [CREATING]
    state = mounted()
    backend.on_tick = lambda: state.watch(str(uuid4()))
    await poll(state)
    assert backend.read_calls == 1
    state = mounted()
    backend.on_tick = None
    await poll(state, auth=session(tenant="not-a-uuid"))
    assert backend.read_calls == 1  # nothing read without a business
    assert state.top_error == module.NO_SESSION_TEXT


async def test_failed_reads_keep_what_was_shown_then_say_so(backend) -> None:
    backend.reads = [CREATING, RuntimeError("db"), RuntimeError("db"), RuntimeError("db")]
    state = mounted()
    await poll(state)
    assert state.has_progress and len(state.rows) == 2
    assert state.top_error == module.READ_FAILED_TEXT


async def test_a_parent_without_parts_shows_nothing(backend) -> None:
    backend.reads = [None]
    state = mounted()
    await poll(state)
    assert state.has_progress is False and state.rows == []


# -- the live region --------------------------------------------------------------------


def test_the_first_read_announces_nothing_then_the_last_change() -> None:
    state = shown(CREATING)
    assert state.announce == ""
    state._apply(FAILED)
    assert state.announce == "La parte 2 no salió."
    state._apply(DONE)
    assert state.announce == "Las 2 partes están creadas."


def test_an_unchanged_read_keeps_the_announcement() -> None:
    state = shown(CREATING)
    state._apply(FAILED)
    state._apply(FAILED)
    assert state.announce == "La parte 2 no salió."


# -- the rows ---------------------------------------------------------------------------


def test_change_and_remove_are_never_offered() -> None:
    failed = shown(FAILED).rows[1]
    assert [b.label for b in failed.buttons] == ["Intentar de nuevo"]
    assert failed.buttons[0].aria_label == "Intentar de nuevo la parte 2"
    assert failed.word == "No salió" and failed.tone == "error"


@pytest.mark.parametrize("action", ["retry", "make_new", "recreate"])
async def test_a_tap_runs_its_service_as_the_session_user(backend, action: str) -> None:
    state = shown(OFFERS[action])
    events = await tap(state, 2, action)
    assert backend.actions == [
        (action, {"tenant_id": UUID(TENANT), "parent_id": PARENT, "part_index": 2, "user_id": USER})
    ]
    assert events == [PartProgressState.poll]
    assert state._busy == [] and state.rows[1].error == ""


async def test_a_button_the_row_does_not_show_is_never_run(backend) -> None:
    # «Crearla otra vez» on a part waiting for review would charge a vista previa
    state = shown(progress(row(1, PartState.TO_REVIEW), row(2, PartState.READY)))
    assert await tap(state, 1, "recreate") == []
    assert await tap(state, 3, "retry") == []  # no such row
    assert backend.actions == []


async def test_unserved_actions_are_never_run(backend) -> None:
    state = shown(FAILED)
    for action in ("change", "remove", "nonsense"):
        assert await tap(state, 2, action) == []
    assert backend.actions == []


async def test_without_the_session_user_nothing_runs(backend) -> None:
    state = shown(FAILED)
    assert await tap(state, 2, "retry", auth=session(user="")) == []
    assert backend.actions == []
    assert state.top_error == module.NO_SESSION_TEXT


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (PartChangeRefused("Esta parte ya no necesita otro intento."), "Esta parte ya no necesita"),
        (NotEnoughCreations(previews=1, previews_left=0), "Ya usaste tus vistas previas"),
        (InvalidTransition("x"), "Esta parte ya está en otro paso"),
        (provider.StaleAction("retry"), "Esta parte ya está en otro paso"),
        (UnknownDraft("x"), "No encontramos esta parte"),
        (RuntimeError("boom"), "No pudimos empezar esta parte otra vez"),
    ],
)
async def test_a_refusal_is_said_on_its_row(backend, error: Exception, text: str) -> None:
    backend.action_error = error
    state = shown(FAILED)
    events = await tap(state, 2, "retry")
    assert text in state.rows[1].error
    assert state.rows[0].error == ""
    assert state.rows[1].busy is False
    assert events == [PartProgressState.poll]  # the list catches up


async def test_only_the_tapped_row_waits_in_words(backend, monkeypatch: pytest.MonkeyPatch) -> None:
    state = shown(FAILED)
    seen: list[Any] = []

    def run_action(action: str, **kw: Any) -> UUID:
        seen.append(([r.busy for r in state.rows], state.rows[1].buttons[0].label))
        return uuid4()

    monkeypatch.setattr(provider, "run_action", run_action)
    await tap(state, 2, "retry")
    assert seen == [([False, True], "Un momento…")]
    assert state.rows[1].buttons[0].label == "Intentar de nuevo"


async def test_a_row_already_busy_ignores_a_second_tap(backend) -> None:
    state = shown(FAILED)
    state._busy = [2]
    assert await tap(state, 2, "retry") == []
    assert backend.actions == []


def test_a_moved_row_drops_its_old_error() -> None:
    state = shown(FAILED)
    state._row_errors = {2: "No pudimos empezar esta parte otra vez."}
    state._rebuild_rows()
    state._apply(CREATING)
    assert state.rows[1].error == ""


async def test_an_empty_plan_paints_nothing_and_stops(backend) -> None:
    backend.reads = [progress()]
    state = mounted()
    events = await poll(state)
    assert state.has_progress is False and state.rows == []
    assert backend.read_calls == 1 and events == []


# -- Deivid's review: the result must not call the video ready too soon ------------------

REDO_LEFT = progress(row(1, PartState.TO_REVIEW), row(2, PartState.REDO, PartAction.RECREATE))


def test_parts_pending_until_every_part_is_made_and_none_waits() -> None:
    state = mounted()
    assert state.parts_pending is True  # before the first read
    state._apply(CREATING)
    assert state.parts_pending is True
    state._apply(REDO_LEFT)
    assert state.complete is True and state.parts_pending is True
    state._apply(DONE)
    assert state.parts_pending is False
    state._apply(None)
    assert state.parts_pending is True


async def test_a_decision_title_does_not_stop_the_poll_while_parts_move(backend) -> None:
    decision_and_moving = progress(
        row(1, PartState.FAILED, PartAction.RETRY), row(2, PartState.CREATING)
    )
    backend.reads = [decision_and_moving, decision_and_moving, FAILED]
    state = mounted()
    await poll(state)
    assert backend.read_calls == 3  # ruled by the rows in progress, not by the title
    assert state.title == "Falta que decidas qué hacer con una parte"


# -- round 4 -----------------------------------------------------------------------------


def test_unmounting_keeps_the_video_pending() -> None:
    state = shown(DONE)
    assert state.parts_pending is False
    state.leave()
    assert state.parts_pending is True


def test_the_hold_reason_follows_the_read() -> None:
    state = shown(FAILED)
    assert state.hold_reason == "Primero decide qué hacer con las partes que no salieron."
    state._apply(CREATING)
    assert state.hold_reason == "Podrás revisarlo cuando todas sus partes estén creadas."


async def test_past_the_budget_it_reads_slower_until_two_hours(
    backend, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"now": 0.0}
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        clock["now"] += seconds
        if len(slept) > 2000:
            pytest.fail("the poll never stopped")

    monkeypatch.setattr(module.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    backend.reads = [CREATING]  # never moves on
    state = mounted()
    await poll(state)
    assert set(slept) == {module.POLL_SECONDS, module.POLL_SLOW_SECONDS}
    fast = [s for s in slept if s == module.POLL_SECONDS]
    assert len(fast) == int(module.POLL_BUDGET_SECONDS / module.POLL_SECONDS) + 1
    assert clock["now"] > module.POLL_MAX_SECONDS
    assert clock["now"] <= module.POLL_MAX_SECONDS + module.POLL_SLOW_SECONDS
