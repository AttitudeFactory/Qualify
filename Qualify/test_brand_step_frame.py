"""Tu marca in the step frame (PASOS-4, m-24852243; docs/design-system.md §4.5, N6b).

`/brand`, `/brand/manual` and `/brand/connect`: a way out on every step, the first one
included, for an account and for a guest (H1); «Seguir después» saves and goes to Inicio
(N2); «Paso N de M» counts only the steps the owner walks (H5); `?paso=N` never opens
past a step still unanswered."""

from __future__ import annotations

import json
from typing import Any

import pytest

from . import brand_finish
from . import brand_minimal as minimal
from . import brand_minimal_vm as vm
from . import creative_wizard_pages as wiz
from .auth_state import AuthState
from .brand_minimal import BrandMinimalState
from .creative_state import CreativeState
from .ui.steps_vm import guard_step

_TENANT = "a0000000-0000-4000-8000-000000000001"


def _shown(rendered: str, text: str) -> bool:
    """The compiled page escapes non-ASCII characters."""
    return text in rendered or json.dumps(text)[1:-1] in rendered


# --------------------------------------------------------------------------------------
# the way out (H1)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "page", [minimal.brand_minimal_index, wiz.brand_manual_index, wiz.brand_connect_index]
)
def test_every_page_is_the_step_frame_with_its_way_out(page: Any) -> None:
    rendered = str(page())
    assert "q-step-frame" in rendered and "q-step-head" in rendered
    # «‹ Inicio» for an account, «‹ Tu correo» for a guest — on every step: the head
    # is outside the step's `rx.match`, so no step can lose it
    assert _shown(rendered, wiz.EXIT_LABEL_SESSION) and _shown(rendered, wiz.EXIT_LABEL_GUEST)
    assert _shown(rendered, "Seguir después")
    # a guest keeps «Usar otro correo» on the first step
    assert _shown(rendered, "Usar otro correo")


class _Leaving:
    """A background handler's `self` for `leave_flow`: the lock and `get_state`."""

    def __init__(self, session: str) -> None:
        # a guest is a session without `session_tenant_id` (`leave_flow` reads only it)
        self.auth = AuthState()
        self.auth.session_tenant_id = session

    async def __aenter__(self) -> _Leaving:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def get_state(self, _cls: type) -> Any:
        return self.auth


async def _leave(
    monkeypatch: pytest.MonkeyPatch, state: _Leaving, *, later: bool, fails: bool = False
) -> tuple[list[str], list[str]]:
    saved: list[str] = []

    async def save_progress(_state: object, flow: str) -> None:
        if fails:
            raise RuntimeError("db down")
        saved.append(flow)

    monkeypatch.setattr(brand_finish, "save_progress", save_progress)
    events = [str(e) async for e in wiz.leave_flow(state, vm.MINIMAL_FLOW, later=later)]
    return saved, events


async def test_an_account_leaves_to_inicio_after_saving(monkeypatch: pytest.MonkeyPatch) -> None:
    saved, events = await _leave(monkeypatch, _Leaving(_TENANT), later=False)
    assert saved == [vm.MINIMAL_FLOW]
    assert len(events) == 1 and "_redirect" in events[0] and '"/"' in events[0]


async def test_seguir_despues_saves_and_goes_to_inicio(monkeypatch: pytest.MonkeyPatch) -> None:
    saved, events = await _leave(monkeypatch, _Leaving(_TENANT), later=True)
    assert saved == [vm.MINIMAL_FLOW]
    assert _shown(events[0], wiz.SAVED_FOR_LATER)
    assert "_redirect" in events[1] and '"/"' in events[1]


async def test_a_guest_saves_and_stays_or_leaves_to_the_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Inicio before the login: «Seguir después» saves and says how to come back;
    «‹ Tu correo» saves and asks for an email again (the draft stays under its own)."""
    saved, events = await _leave(monkeypatch, _Leaving(""), later=True)
    assert saved == [vm.MINIMAL_FLOW] and len(events) == 1
    assert _shown(events[0], wiz.SAVED_FOR_LATER_GUEST) and "_redirect" not in events[0]
    saved, events = await _leave(monkeypatch, _Leaving(""), later=False)
    assert saved == [vm.MINIMAL_FLOW] and len(events) == 1
    assert "leave_brand_draft" in events[0]


async def test_a_failed_save_never_leaves(monkeypatch: pytest.MonkeyPatch) -> None:
    _saved, events = await _leave(monkeypatch, _Leaving(_TENANT), later=True, fails=True)
    assert len(events) == 1 and _shown(events[0], wiz.SAVE_LATER_FAILED)
    assert "_redirect" not in events[0]


def test_all_three_flows_leave_through_the_same_door() -> None:
    import inspect

    for state in (BrandMinimalState, wiz.BrandWizardState, wiz.BrandConnectState):
        for handler in (state.save_for_later, state.leave):
            assert "leave_flow(" in inspect.getsource(handler.fn), state.__name__


def test_the_exit_copy_is_plain_spanish() -> None:
    for text in (
        wiz.SAVED_FOR_LATER,
        wiz.SAVED_FOR_LATER_GUEST,
        wiz.SAVE_LATER_FAILED,
        wiz.EXIT_LABEL_GUEST,
    ):
        assert "brand kit" not in text.lower() and "draft" not in text.lower()


# --------------------------------------------------------------------------------------
# «Paso N de M» with the real M (H5)
# --------------------------------------------------------------------------------------


def _walk(state: wiz.BrandConnectState) -> list[tuple[int, int]]:
    """(N, M) on every step `next_step` lands on, from the first to the last."""
    seen = [(state.step_n, state.step_m)]
    while state.step != wiz.CONNECT_LAST:
        wiz.BrandConnectState.next_step.fn(state)
        seen.append((state.step_n, state.step_m))
    return seen


@pytest.mark.parametrize(
    ("kind", "total"),
    [("marca", len(wiz.CONNECT_STEPS)), ("influencer", len(wiz.CONNECT_STEPS) - 4)],
)
def test_the_counter_walks_consecutively_for_a_brand_and_a_creator(kind: str, total: int) -> None:
    """A creator skips the logo block: «5 de 8» → «6 de 8», never «5 de 12» → «10 de 12»."""
    state = wiz.BrandConnectState()
    state.account_kind = kind
    state.discovery_ran = True  # the sort step would otherwise start the search
    state.suggesting_hashtags = True  # nor create hashtags on arrival
    seen = _walk(state)
    assert seen == [(n, total) for n in range(1, total + 1)]


def test_the_profile_picture_as_logo_drops_tu_logo_from_the_count() -> None:
    assert wiz.connect_position(wiz.CONNECT_LAST, "marca", True) == (11, 11)
    assert wiz.connect_position(wiz._PALETTE_STEP, "marca", True) == (8, 11)
    assert wiz.connect_position(wiz._CONNECT_CONFIRM_STEP, "influencer", False) == (6, 8)


def test_the_skip_rule_is_the_one_the_walk_uses() -> None:
    state = wiz.BrandConnectState()
    for kind in ("marca", "influencer", "ambas"):
        for from_profile in (False, True):
            state.account_kind, state.logo_from_profile = kind, from_profile
            skipped = wiz.connect_skipped(kind, from_profile)
            for index in range(len(wiz.CONNECT_STEPS)):
                assert state._is_skipped(index) == (index in skipped)


def test_the_five_steps_and_the_manual_flow_count_every_step() -> None:
    state = BrandMinimalState()
    state.step = vm.STEP_COLOURS
    assert (state.n, vm.TOTAL_STEPS) == (4, 5)
    manual = wiz.BrandWizardState()
    manual.step = wiz.LAST_STEP
    assert (manual.step_n, len(wiz.STEPS)) == (7, 7)


# --------------------------------------------------------------------------------------
# `?paso=N`: never past an unanswered step
# --------------------------------------------------------------------------------------


def test_guard_step_lands_on_the_first_unanswered_step() -> None:
    assert guard_step(4, [True, False, True, True, True]) == 2
    assert guard_step(4, [True, True, True, False, False]) == 4  # the step itself may be open
    assert guard_step(9, [True, True, True]) == 3
    assert guard_step(0, [False, False]) == 1
    assert guard_step(2, []) == 1


def test_the_five_steps_say_which_are_answered() -> None:
    facts = vm.KitFacts(socials_answered=True, rubro="Shawarma", positioning="x", audience="y")
    assert vm.step_completes(facts) == [True, True, False, False, False]
    assert guard_step(5, vm.step_completes(facts)) == 3
    assert vm.logo_answered("perfil", has_files=False, brief="", from_profile="perfil")
    assert vm.logo_answered("si", has_files=True, brief="", from_profile="perfil")
    assert not vm.logo_answered("si", has_files=False, brief="algo", from_profile="perfil")
    assert vm.logo_answered("no", has_files=False, brief="moderno", from_profile="perfil")
    assert not vm.logo_answered("", has_files=True, brief="x", from_profile="perfil")


class _States:
    def __init__(self) -> None:
        self.instances: dict[type, Any] = {}

    def __call__(self, cls: type) -> Any:
        if cls not in self.instances:
            self.instances[cls] = cls()
        return self.instances[cls]


@pytest.fixture
def states(monkeypatch: pytest.MonkeyPatch) -> _States:
    holder = _States()

    async def get_state(_self: object, cls: type) -> Any:
        return holder(cls)

    for cls in (BrandMinimalState, wiz.BrandWizardState, wiz.BrandConnectState):
        monkeypatch.setattr(cls, "get_state", get_state)
    return holder


async def test_a_deep_link_to_cómo_hablas_opens_the_first_gap(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    """«Atrás»/«adelante» of the browser on /brand: `?paso=5` with Tu logo unanswered
    opens Tu logo; with everything answered, Cómo hablas."""
    connect = states(wiz.BrandConnectState)
    connect.started_without_socials = True
    connect.rubro_text = "Shawarma"
    creative = states(CreativeState)
    creative.kit_positioning, creative.kit_audience = "Al momento", "Oficinistas"
    state = BrandMinimalState()
    states.instances[BrandMinimalState] = state
    state.entered = True
    monkeypatch.setattr(minimal, "step_param", lambda _s: "5")
    await BrandMinimalState.pop_step.fn(state)
    assert state.step == vm.STEP_LOGO
    states(wiz.BrandWizardState).has_logo = "no"
    states(wiz.BrandWizardState).logo_brief_1 = "Moderno"
    creative.kit_palette = "#0A3D2E"
    await BrandMinimalState.pop_step.fn(state)
    assert state.step == vm.STEP_VOICE
    # going back is always allowed, and says so to the entrance animation
    monkeypatch.setattr(minimal, "step_param", lambda _s: "2")
    await BrandMinimalState.pop_step.fn(state)
    assert state.step == vm.STEP_BUSINESS and state.direction == "back"


async def test_the_browser_back_waits_for_the_entry(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = BrandMinimalState()
    state.step = vm.STEP_LOGO
    monkeypatch.setattr(minimal, "step_param", lambda _s: "1")
    await BrandMinimalState.pop_step.fn(state)  # `enter` has not decided yet
    assert state.step == vm.STEP_LOGO


async def test_a_deep_link_into_the_manual_flow_is_guarded(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    creative = states(CreativeState)
    creative.kit_positioning, creative.kit_audience = "Al momento", "Oficinistas"
    state = wiz.BrandWizardState()
    states.instances[wiz.BrandWizardState] = state
    monkeypatch.setattr(wiz, "step_param", lambda _s: "6")
    await wiz.BrandWizardState.resume.fn(state)
    assert state.step == wiz._M_HAS_LOGO_STEP and state.steps_ready
    state.has_logo, state.logo_brief_1 = "no", "Moderno"
    creative.kit_palette = "#0A3D2E"
    await wiz.BrandWizardState.pop_step.fn(state)
    assert state.step == 5  # «¿Todo correcto?», step 6 of 7


async def test_a_deep_link_into_the_connect_flow_counts_visible_steps(
    states: _States, monkeypatch: pytest.MonkeyPatch
) -> None:
    """For a creator `?paso=6` is ¿Todo correcto? (the sixth step they walk), and a
    link past an unanswered rubro lands on the rubro."""
    state = wiz.BrandConnectState()
    states.instances[wiz.BrandConnectState] = state
    state.profile_username = "nibbles"
    state.account_kind = "influencer"
    state.sector = "food"
    creative = states(CreativeState)
    creative.kit_positioning, creative.kit_audience = "Al momento", "Oficinistas"
    monkeypatch.setattr(wiz, "step_param", lambda _s: "6")
    await state._apply_step_param()
    assert state.step == wiz._CONNECT_CONFIRM_STEP and state.step_n == 6
    state.sector = ""
    await state._apply_step_param()
    assert state.step == wiz._RUBRO_STEP


def test_no_paso_keeps_the_usual_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without `?paso=` the flows open where they always did (the saved step or the
    first gap): `step_param` says there is none."""

    class Router:
        class url:  # noqa: N801 — mirrors `router.url`
            query_parameters: dict[str, str] = {}

    class Holder:
        router = Router()

    assert wiz.step_param(Holder()) is None
    Router.url.query_parameters = {"paso": "3"}
    assert wiz.step_param(Holder()) == "3"
