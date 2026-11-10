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
    join_state = "ready"

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
    final.wants_refresh, final.join_state = True, "joining"

    def joined() -> None:
        if backend.ticks >= 2:
            final.wants_refresh, final.join_state = False, "ready"

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


def test_change_is_never_offered_and_remove_is() -> None:
    failed = shown(FAILED).rows[1]
    assert [b.label for b in failed.buttons] == ["Intentar de nuevo", "Quitar parte"]
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
    for action in ("change", "nonsense"):
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


# -- the real UI-9 state ----------------------------------------------------------------


def test_the_hook_calls_the_real_final_video_refresh() -> None:
    from .final_video_card_state import FinalVideoState

    assert module._final_video_state() is FinalVideoState
    (event,) = module._final_video_refresh(str(PARENT))
    assert event.handler.fn.__name__ == "refresh"
    assert "final_video_state" in event.handler.state_full_name.lower()
    assert module._final_video_refresh("") == []


# -- «Quitar parte» (m-24985192) ---------------------------------------------------------

#: part 2 failed; part 3 «Sigue a la anterior»: removing 2 makes 3 new — asked first
ASKS = progress(
    row(1, PartState.TO_REVIEW, total=3),
    PartProgressRow(
        index=2,
        total=3,
        draft_id=uuid4(),
        mode="reference",
        seconds=4,
        state=PartState.FAILED,
        actions=(PartAction.RETRY, PartAction.REMOVE),
    ),
    PartProgressRow(
        index=3,
        total=3,
        draft_id=uuid4(),
        mode="extend",
        seconds=4,
        state=PartState.QUEUED,
        waiting_for=2,
    ),
)
#: part 2 failed, nothing follows it: removed at once
AT_ONCE = progress(
    row(1, PartState.TO_REVIEW), row(2, PartState.FAILED, PartAction.RETRY, PartAction.REMOVE)
)


def test_a_row_with_a_question_asks_first() -> None:
    state = shown(ASKS)
    assert state.rows[1].remove_confirm.startswith("Si quitas la parte 2")
    assert state.ask_remove(2) == []
    assert state.confirming == 2 and state.rows[1].confirming is True


def test_dejarla_closes_the_question_without_removing(backend) -> None:
    state = shown(ASKS)
    state.ask_remove(2)
    state.cancel_remove()
    assert state.confirming == 0 and state.rows[1].confirming is False
    assert backend.actions == []


async def test_never_removed_without_its_confirmation(backend) -> None:
    state = shown(ASKS)
    assert await tap(state, 2, "remove") == []  # straight to the action: refused
    state.ask_remove(2)
    assert await tap(state, 2, "remove") == []  # question open, no «sí» yet
    assert backend.actions == []


async def test_confirmed_removal_runs_says_so_and_polls(backend) -> None:
    state = shown(ASKS)
    state.ask_remove(2)
    (event,) = state.confirm_remove(2)
    assert state._confirmed == 2
    events = await tap(state, 2, "remove")
    assert [a for a, _ in backend.actions] == ["remove"]
    assert events == [PartProgressState.poll]
    assert state.removed_text == "Quitaste la parte 2. Tu video sigue con 2 partes."
    assert state.announce == state.removed_text and state._confirmed == 0


def test_confirming_another_row_does_nothing() -> None:
    state = shown(ASKS)
    state.ask_remove(2)
    assert state.confirm_remove(1) == []
    assert state._confirmed == 0


async def test_a_row_without_a_question_is_removed_at_once(backend) -> None:
    state = shown(AT_ONCE)
    (event,) = state.ask_remove(2)
    assert state.confirming == 0
    await tap(state, 2, "remove")
    assert [a for a, _ in backend.actions] == ["remove"]
    assert state.removed_text == "Quitaste la parte 2. Tu video sigue con 1 parte."


async def test_a_stale_removal_is_said_on_its_row(backend) -> None:
    backend.action_error = provider.StaleAction("remove")
    state = shown(AT_ONCE)
    await tap(state, 2, "remove")
    assert state.rows[1].error == module.OTHER_STEP_TEXT
    assert state.removed_text == ""


# -- round 6: the join after the last part, removal words, the question -----------------


def _join_script(final: FakeFinalVideoState, states: list[str]) -> Any:
    """Each tick, the card's next read (what `refresh` would have found)."""

    def tick() -> None:
        if states:
            final.join_state = states.pop(0)
            final.wants_refresh = final.join_state in ("joining", "rejoining")

    return tick


async def test_the_last_part_done_keeps_reading_until_the_join_is_ready(backend) -> None:
    # the tick everything is made, the card still holds its old «waiting»
    backend.reads = [CREATING, DONE]
    final = FakeFinalVideoState()
    final.join_state = "waiting"
    backend.on_tick = _join_script(final, ["waiting", "joining", "joining", "ready"])
    state = mounted()
    events = await poll(state, final=final)
    assert state.parts_pending is False
    assert backend.read_calls == 5  # waiting, waiting, joining, joining, ready: stops
    # the card reads on every tick until the join settles (not on the settled one)
    assert events.count(("refresh", str(PARENT))) == 4


async def test_a_failed_join_stops_the_poll(backend) -> None:
    backend.reads = [DONE]
    final = FakeFinalVideoState()
    final.join_state = ""  # the card not read yet: open
    backend.on_tick = _join_script(final, ["joining", "failed"])
    state = mounted()
    await poll(state, final=final)
    assert backend.read_calls == 3


async def test_parts_waiting_for_the_owner_do_not_wait_for_the_join(backend) -> None:
    backend.reads = [FAILED]
    final = FakeFinalVideoState()
    final.join_state = "waiting"
    state = mounted()
    await poll(state, final=final)
    assert backend.read_calls == 1  # nothing moves until the owner decides


def test_the_removal_words_survive_the_next_read() -> None:
    three = progress(
        row(1, PartState.TO_REVIEW, total=3),
        row(2, PartState.FAILED, PartAction.REMOVE, total=3),
        row(3, PartState.CREATING, total=3),
    )
    state = shown(three)
    state.removed_text = state.announce = "Quitaste la parte 2. Tu video sigue con 2 partes."
    after = PartProgress(
        parent_id=PARENT,
        parts=(
            row(1, PartState.TO_REVIEW),
            PartProgressRow(
                index=3,
                total=2,
                draft_id=uuid4(),
                mode="reference",
                seconds=4,
                state=PartState.CREATING,
                number=2,
            ),
        ),
    )
    state._apply(after)  # the row is gone, nothing else changed: nothing new to say
    assert state.announce == "Quitaste la parte 2. Tu video sigue con 2 partes."


def test_an_open_question_closes_when_the_row_no_longer_asks() -> None:
    state = shown(ASKS)
    state.ask_remove(2)
    assert state.confirming == 2
    state._apply(CREATING)  # part 2 is being made again: nothing to remove
    assert state.confirming == 0 and state._confirmed == 0
    assert not any(r.confirming for r in state.rows)


async def test_a_part_removed_elsewhere_is_said_on_top_not_on_its_row(backend) -> None:
    from qualify_api.creative.parts import PartRemoved

    backend.action_error = PartRemoved(2)
    state = shown(AT_ONCE)
    await tap(state, 2, "remove")
    assert state.removed_text == "Esa parte ya la habías quitado de tu video."
    assert state.rows[1].error == ""


def test_an_unmade_row_points_to_the_card() -> None:
    state = shown(UNMADE)
    assert state.rows[1].detail == "Créala desde Tu video completo, más abajo."


# -- the fold (Deivid, «Sí, plegarlas») -------------------------------------------------


def test_rows_fold_by_default_without_decisions() -> None:
    state = shown(CREATING)
    assert state.rows_open is False and state.rows_forced is False
    assert state.rows_toggle == "Ver las 2 partes"
    state.toggle_rows()
    assert state.rows_open is True and state.rows_toggle == "Ocultar las partes"


def test_a_decision_opens_the_rows_and_hides_the_toggle() -> None:
    state = shown(FAILED)
    assert state.rows_open is True and state.rows_forced is True
    state.toggle_rows()  # no toggle while a part waits for the owner
    assert state.rows_open is True


def test_a_new_decision_opens_folded_rows_on_the_next_read() -> None:
    state = shown(CREATING)
    assert state.rows_open is False
    state._apply(FAILED)
    assert state.rows_open is True


def test_open_rows_never_fold_by_themselves() -> None:
    state = shown(FAILED)
    state._apply(CREATING)  # the decision was made: the part is being made again
    assert state.rows_open is True and state.rows_forced is False
    state._apply(DONE)
    assert state.rows_open is True
    state.toggle_rows()  # only the owner folds them
    assert state.rows_open is False


def test_another_video_starts_from_the_rule() -> None:
    state = shown(CREATING)
    state.toggle_rows()
    state.watch(str(uuid4()))
    assert state.rows_open is False and state.rows_forced is False


def test_one_part_left_says_it_in_the_singular() -> None:
    state = shown(progress(row(1, PartState.CREATING, total=1)))
    assert state.rows_toggle == "Ver la parte"
