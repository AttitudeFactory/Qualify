"""«Tu video completo» — the card's state and view (m-24921084), offline.

The backend is injected: `final_video_card_provider`'s calls are replaced on the module
and the session's identity is stubbed on the CLASS; the background handlers run through
`.fn(state)` (the harness of `test_ice_breakers_state.py`). The card's words come from a
real `FinalVideo` through `provider.card_from` and `final_video_vm`.

Pins:
1. `load` reads once; `refresh` is ONE read, never a loop, and skips another video or
   a busy card; `wants_refresh` is True only while joining.
2. «Aprobar» calls the parts approval with the session's ids, then the toast, the
   menu's count and the «Aprobada» block; it does nothing while disabled or busy.
3. Every typed refusal reaches the owner in words; an unknown error never leaks.
4. «Juntar otra vez», «Crear la parte N otra vez» and «Cambiar una parte».
5. The component compiles with the design system's primitives, without a spinner.
"""

from __future__ import annotations

import ast
import inspect
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.final_video import (
    Blocker,
    FinalVideo,
    JoinState,
    PartCondition,
    PreviewUse,
    RecreateRefused,
    VideoUse,
)
from qualify_api.creative.fsm import InvalidTransition
from qualify_api.creative.part_final import PartFailed, PartsNotReady, StaleJoinedPreview
from qualify_api.creative.parts import PART_SCHEDULED_TEXT, PartChangeRefused
from qualify_api.creative.service import ApprovalBlocked, DraftExpired, UnknownDraft

from . import final_video_card_provider as provider
from . import final_video_card_state as module
from . import final_video_vm as vm
from .creative_vm import videos_short_text
from .final_video_card import final_video_card
from .final_video_card_state import FinalVideoState, refusal_text
from .final_video_vm import JOIN_FAILED_TEXT, JOINING_TEXT
from .part_progress_state import PartProgressState
from .pending_state import PendingState

_HERE = Path(__file__).parent
TENANT = UUID("a0000000-0000-4000-8000-0000000000a1")
USER = UUID("d0000000-0000-4000-8000-0000000000d1")
PARENT = UUID("e0000000-0000-4000-8000-0000000000e1")
OTHER = UUID("e0000000-0000-4000-8000-0000000000e2")
DEADLINE = datetime(2026, 11, 6, 15, 0, tzinfo=UTC)


def _part(index: int, **kw: Any) -> PartCondition:
    base: dict[str, Any] = {
        "index": index,
        "draft_id": UUID(int=index),
        "has_preview": True,
        "failed": False,
        "expired": False,
        "needs_redo": False,
        "expires_at": DEADLINE,
    }
    base.update(kw)
    return PartCondition(**base)


def _final(state: JoinState = JoinState.READY, **kw: Any) -> FinalVideo:
    parts = kw.pop("parts", (_part(1), _part(2)))
    ready = state is JoinState.READY and not any(p.expired or p.failed for p in parts)
    base: dict[str, Any] = {
        "parent_id": PARENT,
        "state": state,
        "seconds": 15,
        "planned": len(parts),
        "parts": parts,
        "can_approve": ready,
        "blocker": None if ready else Blocker.JOINING,
        "video_key": "uploads/joined.mp4",
        "poster_key": "uploads/joined.jpg",
        "expires_at": DEADLINE,
        "video_use": VideoUse(uses=15, quota=40, left=40),
    }
    base.update(kw)
    return FinalVideo(**base)


class Backend:
    """The provider's calls, recorded; each answers what the test set."""

    def __init__(self) -> None:
        self.final: FinalVideo | None = _final()
        self.reads: list[UUID] = []
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fail: dict[str, BaseException] = {}
        self.rejoin_ok = True

    def read_card(self, tenant_id: UUID, parent_id: UUID) -> provider.CardRead | None:
        assert tenant_id == TENANT
        self.reads.append(parent_id)
        if "read" in self.fail:
            raise self.fail["read"]
        return None if self.final is None else provider.card_from(self.final, tenant_id, "UTC")

    def _call(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))
        if name in self.fail:
            raise self.fail[name]

    def approve(self, tenant_id: UUID, parent_id: UUID, user_id: UUID) -> provider.Approval:
        self._call("approve", tenant_id, parent_id, user_id)
        self.final = _final(JoinState.APPROVED, can_approve=False, blocker=Blocker.APPROVED)
        return provider.Approval("success", "Publicación aprobada.", True, "")

    def rejoin(self, tenant_id: UUID, parent_id: UUID) -> bool:
        self._call("rejoin", tenant_id, parent_id)
        return self.rejoin_ok

    def recreate_expired(self, tenant_id: UUID, parent_id: UUID, user_id: UUID) -> tuple:
        self._call("recreate", tenant_id, parent_id, user_id)
        return (2,)

    def create_missing(self, tenant_id: UUID, parent_id: UUID, user_id: UUID) -> list:
        self._call("create", tenant_id, parent_id, user_id)
        return [UUID(int=6)]

    def change_part(
        self, tenant_id: UUID, parent_id: UUID, index: int, text: str, user_id: UUID
    ) -> UUID:
        self._call("change", tenant_id, parent_id, index, text, user_id)
        return UUID(int=index)


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> Iterator[Backend]:
    fake = Backend()

    async def identity(self: FinalVideoState) -> tuple[UUID, UUID]:
        return TENANT, USER

    monkeypatch.setattr(FinalVideoState, "_identity", identity)
    for name in (
        "read_card",
        "approve",
        "rejoin",
        "recreate_expired",
        "change_part",
        "create_missing",
    ):
        monkeypatch.setattr(provider, name, getattr(fake, name))
    yield fake


async def _drain(events: Any) -> list[Any]:
    if hasattr(events, "__aiter__"):
        return [event async for event in events]
    await events
    return []


async def _loaded(parent: UUID = PARENT) -> FinalVideoState:
    state = FinalVideoState()
    await _drain(FinalVideoState.load.fn(state, str(parent)))
    return state


# -- 1. reading, and no poll ----------------------------------------------------------------


async def test_load_reads_once_and_fills_the_card(backend: Backend) -> None:
    state = await _loaded()
    assert backend.reads == [PARENT]
    assert state.loaded and not state.missing and state.error == ""
    assert state.card.header == "Tu video completo · 15 s · Vista previa"
    assert state.card.approve_enabled
    assert state.card.quota_text.startswith("Este video dura 15 s y este mes te quedan 40 s")
    assert state.video_key == "uploads/joined.mp4" and state.video_url == ""  # local key
    assert state.part_options == ["1", "2"]
    assert not state.wants_refresh and state.join_steps == []


async def test_a_parent_that_is_not_a_video_by_parts_renders_nothing(backend: Backend) -> None:
    backend.final = None
    state = await _loaded()
    assert state.loaded and state.missing


async def test_a_failed_first_read_says_what_to_do(backend: Backend) -> None:
    backend.fail["read"] = RuntimeError("db down at 10.0.0.3")
    state = await _loaded()
    assert state.error == module.READ_FAILED_TEXT and "10.0.0.3" not in state.error


@pytest.mark.parametrize("join", [JoinState.JOINING, JoinState.REJOINING])
async def test_wants_refresh_only_while_joining(backend: Backend, join: JoinState) -> None:
    backend.final = _final(join)
    state = await _loaded()
    assert state.wants_refresh
    assert state.card.pill_word == "Juntando" and state.card.pill_tone == "info"
    assert state.join_steps == [{"title": JOINING_TEXT, "status": "running"}]
    backend.final = _final(JoinState.READY)
    await _drain(FinalVideoState.refresh.fn(state, str(PARENT)))
    assert not state.wants_refresh and state.card.show_video


async def test_refresh_is_one_read_and_returns(backend: Backend) -> None:
    state = await _loaded()
    backend.reads.clear()
    assert await _drain(FinalVideoState.refresh.fn(state, str(PARENT))) == []
    assert backend.reads == [PARENT]


async def test_refresh_skips_another_video_and_a_busy_card(backend: Backend) -> None:
    state = await _loaded()
    backend.reads.clear()
    await _drain(FinalVideoState.refresh.fn(state, str(OTHER)))
    await _drain(FinalVideoState.refresh.fn(state, "not-a-uuid"))
    state.busy = module.APPROVE
    await _drain(FinalVideoState.refresh.fn(state, str(PARENT)))
    assert backend.reads == []


def test_the_state_has_no_poll_of_its_own() -> None:
    """UI-7 owns the only poll: no loop, no sleep, no self-chaining here."""
    tree = ast.parse(inspect.getsource(module))
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
    sleeps = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "sleep"]
    assert loops == [] and sleeps == []
    assert "FinalVideoState.refresh" not in inspect.getsource(module)


async def test_load_of_another_video_resets_the_card(backend: Backend) -> None:
    state = await _loaded()
    state.error, state.change_open, state.approved_here = "x", True, True
    await _drain(FinalVideoState.load.fn(state, str(OTHER)))
    assert state.parent_id == str(OTHER)
    assert state.error == "" and not state.change_open and not state.approved_here


@pytest.mark.parametrize("via_reset", [False, True])
async def test_a_stale_read_of_another_video_never_leaves_the_card_loading(
    backend: Backend, monkeypatch: pytest.MonkeyPatch, via_reset: bool
) -> None:
    """Code review: a read of the previous video that lands after the card moved on
    returned without clearing `loading`, and `refresh` then skipped forever."""
    state = await _loaded()
    real = backend.read_card

    def moved_meanwhile(tenant_id: UUID, parent_id: UUID) -> Any:
        if via_reset:
            FinalVideoState._reset(state, str(OTHER))  # what `load(OTHER)` does
        else:
            state.parent_id = str(OTHER)
        return real(tenant_id, parent_id)

    monkeypatch.setattr(provider, "read_card", moved_meanwhile)
    await _drain(FinalVideoState.refresh.fn(state, str(PARENT)))
    assert state.parent_id == str(OTHER) and not state.loading
    monkeypatch.setattr(provider, "read_card", real)
    backend.reads.clear()
    await _drain(FinalVideoState.refresh.fn(state, str(OTHER)))
    assert backend.reads == [OTHER]  # the card still reads


# -- 2. «Aprobar» ----------------------------------------------------------------------------


async def test_approve_goes_on_as_today(backend: Backend) -> None:
    state = await _loaded()
    events = await _drain(FinalVideoState.approve.fn(state))
    assert backend.calls == [("approve", (TENANT, PARENT, USER))]
    assert state.approved_here and state.approved_ready and state.busy == ""
    assert state.join_state == "approved" and not state.card.approve_visible
    assert len(events) == 3 and events[1] == PendingState.refresh_now
    assert "q-final-video-schedule" in str(events[2])  # the focus goes to the next step
    assert state.announce == "Publicación aprobada."


async def test_approve_does_nothing_while_disabled_or_busy(backend: Backend) -> None:
    backend.final = _final(JoinState.JOINING)
    state = await _loaded()
    await _drain(FinalVideoState.approve.fn(state))
    backend.final = _final()
    await _drain(FinalVideoState.refresh.fn(state, str(PARENT)))
    state.busy = module.REJOIN  # another action on its way: a double tap does nothing
    await _drain(FinalVideoState.approve.fn(state))
    assert backend.calls == []


async def test_approve_without_enough_seconds_says_so(backend: Backend) -> None:
    backend.fail["approve"] = NotEnoughCreations(
        videos=15, videos_left=10, video_in_seconds=True, video_quota=40
    )
    state = await _loaded()
    events = await _drain(FinalVideoState.approve.fn(state))
    assert events == [] and not state.approved_here and state.busy == ""
    assert state.error == videos_short_text(15, 10, 40)
    assert state.announce == state.error


async def test_an_unknown_failure_never_leaks(backend: Backend) -> None:
    backend.fail["approve"] = RuntimeError("psycopg: relation secret_table")
    state = await _loaded()
    await _drain(FinalVideoState.approve.fn(state))
    assert state.error == module.FAILED_TEXT[module.APPROVE]
    assert "secret" not in state.error


# -- 3. typed refusals -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc,action,text",
    [
        (StaleJoinedPreview(), module.APPROVE, module.STALE_TEXT),
        (PartFailed(), module.APPROVE, module.PART_FAILED_TEXT),
        (PartsNotReady(), module.APPROVE, module.NOT_READY_TEXT),
        (DraftExpired(), module.APPROVE, module.EXPIRED_TEXT),
        (UnknownDraft("x"), module.APPROVE, module.NOT_FOUND_TEXT),
        (ApprovalBlocked("El precio no es el del catálogo."), module.APPROVE, None),
        (RecreateRefused("parts [3] have not all expired"), module.RECREATE, None),
        (PartChangeRefused(PART_SCHEDULED_TEXT), module.CHANGE, PART_SCHEDULED_TEXT),
        (PartChangeRefused("internal: lock held"), module.CHANGE, None),
        (InvalidTransition("drafting -> reject"), module.CHANGE, module.PART_BUSY_TEXT),
        (KeyError("parent"), module.REJOIN, module.FAILED_TEXT[module.REJOIN]),
    ],
)
def test_refusals_are_the_owners_words(exc: BaseException, action: str, text: str | None) -> None:
    said = refusal_text(exc, action)
    if text is not None:
        assert said == text
    assert said
    if isinstance(exc, ApprovalBlocked):
        assert said == "El precio no es el del catálogo."
    if isinstance(exc, RecreateRefused):
        assert said == module.RECREATE_REFUSED_TEXT and "expired" not in said
    if isinstance(exc, PartChangeRefused) and "internal" in str(exc):
        assert said == module.FAILED_TEXT[module.CHANGE]


def test_short_of_previews_names_when_they_come_back() -> None:
    exc = NotEnoughCreations(previews=2, previews_left=0)
    said = refusal_text(exc, module.RECREATE, renews="1 de diciembre", preview_quota=20)
    assert said == "Ya usaste tus 20 vistas previas de este mes. Vuelven el 1 de diciembre."


# -- 4. the other buttons --------------------------------------------------------------------


async def test_rejoin_after_a_failed_join(backend: Backend) -> None:
    backend.final = _final(JoinState.FAILED, can_approve=False, blocker=Blocker.JOIN_FAILED)
    state = await _loaded()
    assert state.card.rejoin_visible and state.card.status_text == JOIN_FAILED_TEXT
    assert state.card.pill_tone == "error"
    backend.final = _final(JoinState.JOINING)
    await _drain(FinalVideoState.rejoin.fn(state))
    assert backend.calls == [("rejoin", (TENANT, PARENT))]
    assert state.wants_refresh and state.error == "" and state.busy == ""
    backend.rejoin_ok = False
    await _drain(FinalVideoState.rejoin.fn(state))
    assert state.error == module.REJOIN_REFUSED_TEXT


async def test_recreate_only_the_expired_parts(backend: Backend) -> None:
    expired = (_part(1), _part(2, expired=True, has_preview=False))
    backend.final = _final(
        JoinState.WAITING,
        parts=expired,
        can_approve=False,
        blocker=Blocker.EXPIRED,
        recreate_use=PreviewUse(uses=1, left=9, quota=20),
    )
    state = await _loaded()
    assert state.card.recreate_label == "Crear la parte 2 otra vez"
    assert state.card.recreate_text == (
        "Crea otra vez la parte 2. Usa 1 vista previa. Te quedan 9 vistas previas."
    )
    await _drain(FinalVideoState.recreate.fn(state))
    assert backend.calls == [("recreate", (TENANT, PARENT, USER))]
    backend.fail["recreate"] = NotEnoughCreations(previews=1, previews_left=0)
    await _drain(FinalVideoState.recreate.fn(state))
    assert state.error.startswith("Ya usaste tus 20 vistas previas de este mes.")


async def test_change_a_part(backend: Backend) -> None:
    state = await _loaded()
    await _drain(FinalVideoState.change_part.fn(state))  # no part chosen yet
    assert state.error == module.CHOOSE_PART_TEXT and backend.calls == []
    FinalVideoState.choose_part.fn(state, "7")  # not a part of this video
    assert state.change_index == "" and not state.change_open
    FinalVideoState.choose_part.fn(state, "2")  # «Cambiar esta» on part 2
    assert state.change_open and state.change_index == "2" and state.change_number == "2"
    FinalVideoState.set_change_text.fn(state, "Más cerca del producto")
    await _drain(FinalVideoState.change_part.fn(state))
    assert backend.calls == [("change", (TENANT, PARENT, 2, "Más cerca del producto", USER))]
    assert not state.change_open and state.change_text == "" and state.error == ""
    assert state.change_index == ""  # done: nothing stays chosen
    FinalVideoState.choose_part.fn(state, "1")
    backend.fail["change"] = PartChangeRefused(PART_SCHEDULED_TEXT)
    await _drain(FinalVideoState.change_part.fn(state))
    assert state.error == PART_SCHEDULED_TEXT and state.change_open


def test_go_schedule_opens_tu_semana_on_the_video() -> None:
    state = FinalVideoState()
    assert FinalVideoState.go_schedule.fn(state) is None
    state.parent_id = str(PARENT)
    assert f"/planner?post={PARENT}" in str(FinalVideoState.go_schedule.fn(state))


# -- 5. the component ------------------------------------------------------------------------


def test_the_card_compiles_with_the_design_system() -> None:
    rendered = str(final_video_card(FinalVideoState.parent_id).render())
    assert "q-progress-track" in rendered  # the join's wait is the progress panel
    assert "q-rv-media--video" in rendered  # the generator's player frame
    assert "aria-live" in rendered.replace("_", "-") or "ariaLive" in rendered
    assert "q-final-video-approve-why" in rendered
    assert "q-final-video-schedule" in rendered
    # UX review: «Aprobar» off stays focusable (aria-disabled), parts are one-tap buttons
    flat = rendered.replace("_", "-")
    assert "aria-disabled" in flat or "ariaDisabled" in rendered
    assert "aria-pressed" in flat or "ariaPressed" in rendered
    assert "RadixThemesSelect" not in rendered
    for word in ("Elegir d", "le cambiamos?", "Crear otra versi", "Cambiar esta"):
        assert word in rendered  # ASCII: the accents are escaped
    source = (_HERE / "final_video_card.py").read_text(encoding="utf-8")
    assert "loading_spinner" not in source and "rx.spinner" not in source
    assert final_video_card(str(PARENT)) is not None  # a plain id works too
    assert "q-thumb" in rendered  # each part's tile is framed as the system's thumbs
    assert "q-rv-stage" in rendered  # the whole video on its stage (m-25016656)


# -- 6. visual review 2026-11-09 ----------------------------------------------------------


async def test_a_good_read_clears_a_stale_session_error(backend: Backend) -> None:
    """The «Vuelve a iniciar sesión» of a first load before login stayed on screen."""
    state = FinalVideoState()
    state.parent_id, state.error = str(PARENT), module.NO_SESSION_TEXT
    await _drain(FinalVideoState.refresh.fn(state, str(PARENT)))
    assert state.loaded and state.error == ""
    state.error = module.STALE_TEXT  # a refusal of an action is not a read error: it stays
    await _drain(FinalVideoState.refresh.fn(state, str(PARENT)))
    assert state.error == module.STALE_TEXT


@pytest.mark.parametrize(
    "use,seconds,text",
    [
        (  # it fits — Deivid's own example (2026-11-10)
            VideoUse(uses=24, quota=40, left=35),
            24,
            "Este video dura 24 s y este mes te quedan 35 s de video. "
            "Al aprobarlo te quedarían 11 s.",
        ),
        (
            VideoUse(uses=20, quota=40, left=21),
            20,
            "Este video dura 20 s y este mes te quedan 21 s de video. "
            "Al aprobarlo te quedaría 1 s.",
        ),
        (  # it does not fit
            VideoUse(uses=44, quota=40, left=35, renews_on=date(2026, 12, 1)),
            44,
            "Este video dura 44 s y este mes te quedan 35 s de video. Para aprobarlo, quita "
            "partes o espera al 1 de diciembre, cuando vuelven tus 40 segundos.",
        ),
        (  # nothing left
            VideoUse(uses=24, quota=40, left=0, renews_on=date(2026, 12, 1)),
            24,
            "Este video dura 24 s y ya usaste tus 40 segundos de video de este mes. "
            "Para aprobarlo, espera al 1 de diciembre, cuando vuelven.",
        ),
        (  # a part approved before is not charged again: what is left to approve
            VideoUse(uses=20, quota=40, left=35),
            24,
            "Lo que falta aprobar dura 20 s y este mes te quedan 35 s de video. "
            "Al aprobarlo te quedarían 15 s.",
        ),
        (VideoUse(uses=20, quota=40, left=40, unlimited=True), 20, ""),  # unlimited plan
    ],
)
def test_the_seconds_use_deivids_words(use: VideoUse, seconds: int, text: str) -> None:
    assert vm.quota_text(use, seconds) == text


def test_the_card_and_the_plan_step_say_the_same() -> None:
    """One function for both texts (`reel_parts_vm.seconds_line`): they never drift."""
    from .reel_parts_vm import seconds_line

    use = VideoUse(uses=24, quota=40, left=35)
    assert vm.quota_text(use, 24) == seconds_line(24, 24, 35, 40)


def test_a_part_approved_before_does_not_count_again() -> None:
    parts = (_part(1, approved=True), _part(2), _part(3))
    card = vm.final_video_card(
        _final(parts=parts, seconds=24, video_use=VideoUse(uses=20, quota=40, left=35))
    )
    assert card.charged_note == "La parte 1 ya está aprobada y no gasta tus segundos otra vez."
    assert vm.charged_note((1, 2), 24, VideoUse(uses=8, quota=40, left=35)) == (
        "Las partes 1 y 2 ya están aprobadas y no gastan tus segundos otra vez."
    )
    two = (_part(1, approved=True), _part(2, approved=True), _part(3))
    assert _final(parts=two).approved_parts == (1, 2)
    nobody = _final(seconds=24, video_use=VideoUse(uses=24, quota=40, left=35))
    assert vm.final_video_card(nobody).charged_note == ""  # no part approved before
    unlimited = VideoUse(uses=20, quota=40, left=35, unlimited=True)
    assert vm.charged_note((1,), 24, unlimited) == ""


@pytest.mark.parametrize(
    "use,head",
    [
        (VideoUse(uses=20, quota=40, left=35), "Al aprobarlo te quedarían 15 s."),  # fits
        (  # does not fit
            VideoUse(uses=20, quota=40, left=10, renews_on=date(2026, 12, 1)),
            "Para aprobarlo, quita partes o espera al 1 de diciembre",
        ),
        (  # nothing left
            VideoUse(uses=20, quota=40, left=0, renews_on=date(2026, 12, 1)),
            "Para aprobarlo, espera al 1 de diciembre, cuando vuelven.",
        ),
    ],
)
def test_approved_parts_are_explained_in_every_case(use: VideoUse, head: str) -> None:
    parts = (_part(1, approved=True), _part(2), _part(3))
    card = vm.final_video_card(_final(parts=parts, seconds=24, video_use=use))
    assert card.quota_text.startswith("Lo que falta aprobar dura 20 s")
    assert head in card.quota_text
    assert card.charged_note == "La parte 1 ya está aprobada y no gasta tus segundos otra vez."


def test_a_part_being_made_is_named_with_every_other_reason() -> None:
    parts = (
        _part(1, approved=True),
        _part(2),
        _part(3),
        _part(4, expired=True, has_preview=False),
        _part(5, has_preview=False, creating=True),
    )
    final = _final(JoinState.WAITING, parts=parts, can_approve=False, blocker=Blocker.EXPIRED)
    card = vm.final_video_card(final)
    assert final.creating_parts == (5,)
    assert card.approve_hint == (
        "Disponible cuando la parte 5 tenga su vista previa y crees otra vez la parte 4."
    )
    assert card.creating_text == "La parte 5 todavía se está creando."
    assert vm.creating_text((3, 5)) == "Las partes 3 y 5 todavía se están creando."
    failed = (_part(1, failed=True, has_preview=False), _part(2, creating=True))
    hint = vm.approve_hint(
        _final(JoinState.WAITING, parts=failed, can_approve=False, blocker=Blocker.PART_FAILED)
    )
    assert (
        hint
        == "Disponible cuando la parte 2 tenga su vista previa y decidas qué hacer con la parte 1."
    )


def test_each_part_carries_its_poster(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        provider, "issue_view_path", lambda tenant, key, media_type: f"/r2media/{media_type}"
    )
    parts = (_part(1, poster_key="t/x/part1.jpg"), _part(2), _part(3, draft_id=None))
    read = provider.card_from(_final(parts=parts), TENANT, "UTC")
    assert read.thumbs == (
        {"index": "1", "number": "1", "key": "t/x/part1.jpg", "url": "/r2media/image"},
        {"index": "2", "number": "2", "key": "", "url": ""},  # no poster: the neutral frame
    )


async def test_the_state_keeps_the_tiles(backend: Backend) -> None:
    backend.final = _final(parts=(_part(1, poster_key="uploads/p1.jpg"), _part(2)))
    state = await _loaded()
    assert state.part_thumbs[0] == {"index": "1", "number": "1", "key": "uploads/p1.jpg", "url": ""}
    assert [t["index"] for t in state.part_thumbs] == state.part_options == ["1", "2"]


# -- 7. a part never created is not «being made» (visual review 2026-11-09) ---------------


def _plan_with_unmade(*unmade: int) -> FinalVideo:
    parts = [
        _part(1, approved=True),
        _part(2),
        _part(3),
        _part(4, expired=True, has_preview=False),
        _part(5, has_preview=False, creating=True),
    ]
    for index in unmade:
        parts.append(_part(index, draft_id=None, has_preview=False, expires_at=None, unmade=True))
    return _final(JoinState.WAITING, parts=tuple(parts), can_approve=False, blocker=Blocker.EXPIRED)


def test_a_part_never_created_is_told_apart_from_one_being_made() -> None:
    final = _plan_with_unmade(6)
    assert final.creating_parts == (5,) and final.unmade_parts == (6,)
    card = vm.final_video_card(final)
    assert card.creating_text == "La parte 5 todavía se está creando."
    assert card.unmade_text == "La parte 6 todavía no se creó."
    assert card.approve_hint == (
        "Disponible cuando la parte 5 tenga su vista previa, crees la parte 6 y "
        "crees otra vez la parte 4."
    )
    assert card.create_visible and card.create_label == "Crear la parte 6"
    assert card.create_text == "Crea la parte 6. Usa 1 vista previa."
    many = vm.final_video_card(_plan_with_unmade(6, 7))
    assert many.unmade_text == "Las partes 6 y 7 todavía no se crearon."
    assert many.create_label == "Crear las que faltan"
    assert many.create_text == "Crea las partes 6 y 7. Usan 2 vistas previas."


def test_the_backend_marks_a_plan_entry_without_a_row_as_unmade() -> None:
    from qualify_api.creative.final_video import part_conditions
    from qualify_api.creative.part_join import PartPreview, PartsToJoin

    drafting = PartPreview(
        draft_id=UUID(int=1), part_index=1, status="drafting", revision=1,
        version_id=None, object_key=None,
    )  # fmt: skip
    snapshot = PartsToJoin(parent_id=PARENT, revision=1, planned=2, parts=(drafting,))
    first, second = part_conditions(snapshot, TENANT, 0.0)
    assert first.creating and not first.unmade
    assert second.unmade and not second.creating and second.draft_id is None


async def test_create_the_missing_parts(backend: Backend) -> None:
    backend.final = _plan_with_unmade(6)
    state = await _loaded()
    await _drain(FinalVideoState.create_missing.fn(state))
    assert backend.calls == [("create", (TENANT, PARENT, USER))]
    assert state.busy == "" and state.announce == module.DONE_TEXT[module.CREATE]
    from qualify_api.creative.parts import PartNeedsPrevious, PartsPlanBusy

    backend.fail["create"] = PartNeedsPrevious(6)
    await _drain(FinalVideoState.create_missing.fn(state))
    assert state.error == "La parte 6 sigue a la parte 5: crea primero la parte 5."
    assert refusal_text(PartsPlanBusy(), module.CREATE) == module.PLAN_BUSY_TEXT
    assert refusal_text(RuntimeError("boom"), module.CREATE) == module.FAILED_TEXT["create"]


async def test_nothing_to_create_does_nothing(backend: Backend) -> None:
    state = await _loaded()
    await _drain(FinalVideoState.create_missing.fn(state))
    assert backend.calls == []


def test_aprobar_is_first_in_the_last_row() -> None:
    """Deivid, 2026-11-09: [Aprobar] — or, with a part chosen, [Aprobar] [Crear otra
    versión] [Cancelar] — as the card's last row, the approve texts right above it."""
    from . import final_video_card as view

    rendered = str(view._decisions(view.COLUMNS).render())
    why = rendered.index(view.APPROVE_WHY_ID)  # the texts' block
    approve = rendered.index(view.APPROVE_WHY_ID, why + 1)  # «Aprobar», described by it
    submit = rendered.index("final_video_state.change_part")
    assert why < approve < submit
    assert rendered.index("final_video_state.cancel_change") > submit
    # no «Cambiar una parte» any more: a part is chosen on its own tile
    assert "Cambiar una parte" not in rendered and "toggle_change" not in rendered


# -- 8. live test 2026-11-10: only the parts that can change now --------------------------


def test_change_offers_only_parts_that_can_change_now() -> None:
    parts = (
        _part(1, approved=True, poster_key="uploads/p1.jpg"),
        _part(2, failed=True, has_preview=False),  # changing it is how it gets fixed
        _part(3, has_preview=False, creating=True),  # «En fila»
        _part(4, has_preview=False, creating=True),  # being made
        _part(5, purged=True),
        _part(6, draft_id=None, has_preview=False, expires_at=None, unmade=True),
    )
    final = _final(JoinState.WAITING, parts=parts, can_approve=False, blocker=Blocker.NOT_READY)
    assert [p.index for p in final.changeable_parts] == [1, 2]
    read = provider.card_from(final, TENANT, "UTC")
    assert read.parts == (1, 2)
    assert [t["index"] for t in read.thumbs] == ["1", "2"]
    assert read.thumbs[0]["key"] == "uploads/p1.jpg" and read.vm.change_part_visible


def test_the_tile_reads_the_shown_number_and_acts_on_the_plan_index() -> None:
    parts = (_part(1), _part(3, number=2))  # part 2 was removed: no gap on screen
    read = provider.card_from(_final(parts=parts), TENANT, "UTC")
    assert read.thumbs[1]["index"] == "3" and read.thumbs[1]["number"] == "2"


def test_no_part_to_change_hides_the_button() -> None:
    parts = (
        _part(1, has_preview=False, creating=True),
        _part(2, has_preview=False, creating=True),
    )
    final = _final(JoinState.WAITING, parts=parts, can_approve=False, blocker=Blocker.NOT_READY)
    read = provider.card_from(final, TENANT, "UTC")
    assert read.parts == () and not read.vm.change_part_visible


async def test_ready_is_announced_once_on_the_transition(backend: Backend) -> None:
    backend.final = _final(JoinState.JOINING)
    state = await _loaded()
    assert state.announce == ""
    backend.final = _final(JoinState.READY)
    await _drain(FinalVideoState.refresh.fn(state, str(PARENT)))
    assert state.announce == module.READY_ANNOUNCE
    state.announce = ""
    await _drain(FinalVideoState.refresh.fn(state, str(PARENT)))
    assert state.announce == ""  # still ready: nothing new to hear


async def test_a_first_read_already_ready_announces_nothing(backend: Backend) -> None:
    state = await _loaded()
    assert state.join_state == "ready" and state.announce == ""


def test_a_chosen_tile_says_so_with_more_than_colour() -> None:
    from . import final_video_card as view

    tile = str(view._part_card(PartProgressState.part_tiles[0]).render())
    assert "aria-pressed" in tile.replace("_", "-") or "ariaPressed" in tile
    assert view.CHOOSE_LABEL == "Cambiar esta" and view.CHOSEN_LABEL == "Elegida"
    assert "LucideCheck" in tile  # the tick beside «Elegida»
    assert '"listitem"' in tile


# -- 9. an action that sets work going restarts UI-7's parts poll -------------------------


def test_the_poll_name_is_part_progress_states_own() -> None:
    from .part_progress_state import PartProgressState

    assert module.PART_PROGRESS_POLL == PartProgressState.get_full_name() + ".poll"
    assert callable(getattr(PartProgressState, "poll", None))


def _polls(events: list[Any]) -> list[Any]:
    return [e for e in events if getattr(e, "name", None) == module.PART_PROGRESS_POLL]


async def _run(state: FinalVideoState, action: str) -> list[Any]:
    if action == "change_part":
        FinalVideoState.set_change_index.fn(state, "1")
    return await _drain(getattr(FinalVideoState, action).fn(state))


_ACTIONS = {  # event -> (backend call name, the card that offers it)
    "rejoin": "rejoin",
    "recreate": "recreate",
    "create_missing": "create",
    "change_part": "change",
}


def _offering(action: str) -> FinalVideo:
    if action == "create_missing":
        return _plan_with_unmade(6)
    if action == "rejoin":
        return _final(JoinState.FAILED, can_approve=False, blocker=Blocker.JOIN_FAILED)
    return _final()


@pytest.mark.parametrize("action", sorted(_ACTIONS))
async def test_a_successful_action_restarts_the_parts_poll(backend: Backend, action: str) -> None:
    backend.final = _offering(action)
    state = await _loaded()
    events = await _run(state, action)
    assert len(_polls(events)) == 1


@pytest.mark.parametrize("action", sorted(_ACTIONS))
async def test_a_refused_action_does_not(backend: Backend, action: str) -> None:
    backend.final = _offering(action)
    state = await _loaded()
    backend.fail[_ACTIONS[action]] = RuntimeError("down")
    assert _polls(await _run(state, action)) == []


async def test_a_rejoin_that_could_not_start_does_not(backend: Backend) -> None:
    backend.final = _offering("rejoin")
    state = await _loaded()
    backend.rejoin_ok = False
    assert _polls(await _run(state, "rejoin")) == []


# -- 10. m-25016656: «Tus partes» — every part a tile that plays in place ----------------


def test_choosing_the_chosen_part_again_lets_it_go() -> None:
    state = FinalVideoState()
    state.part_options = ["1", "2"]
    FinalVideoState.choose_part.fn(state, "2")
    FinalVideoState.set_change_text.fn(state, "más luz")
    FinalVideoState.choose_part.fn(state, "1")  # another part: the choice moves
    assert state.change_index == "1" and state.change_open
    assert state.change_text == ""  # the words were for part 2, never carried to part 1
    FinalVideoState.set_change_text.fn(state, "más cerca")
    FinalVideoState.choose_part.fn(state, "1")  # «✓ Elegida» again: let go
    assert state.change_index == "" and not state.change_open and state.change_text == ""
    FinalVideoState.choose_part.fn(state, "2")
    FinalVideoState.cancel_change.fn(state)
    assert state.change_index == "" and not state.change_open


def test_the_change_words_name_the_chosen_part() -> None:
    state = FinalVideoState()
    state.part_options = ["1", "3"]
    state.part_thumbs = [{"index": "1", "number": "1"}, {"index": "3", "number": "2"}]
    FinalVideoState.choose_part.fn(state, "3")  # plan part 3 reads «Parte 2»
    assert state.change_number == "2"
    from . import final_video_card as view

    assert view.CHANGE_TEXT_LABEL == ": ¿qué le cambiamos? (opcional)"
    panel = str(view._change_panel().render())
    assert "final_video_state.change_number" in panel


def test_each_tile_plays_its_own_part() -> None:
    from . import final_video_card as view

    tile = str(view._part_card(PartProgressState.part_tiles[0]).render())
    assert "q-clip q-thumb" in tile and '"aspectRatio"] : "9 / 16"' in tile
    assert '"data-clip-renew":""' in tile  # an expired address is renewed first
    for field in ("preview_url", "poster_url", "play_label", "pause_label", "key"):
        assert f'?.["{field}"]' in tile, field
    # no clip yet: the word of its state, never a dead ▶
    assert '?.["word"]' in tile and "LucideFilm" in tile
    # «Cambiar esta» only for a part that can change now, and never on an approved video
    assert "final_video_state.part_options" in tile
    assert "change_part_visible" in tile
    # the ▶ is the big one (≥ 44 px), not the small one of the panel's rows
    assert "q-clip__play--sm" not in tile


def test_the_strip_and_its_hint() -> None:
    from . import final_video_card as view

    strip = str(view._parts_strip(view.COLUMNS).render())
    assert "part_progress_state.part_tiles" in strip and '"list"' in strip
    for text in (view.PARTS_TITLE, view.PARTS_HINT_CHANGE, view.PARTS_HINT_WATCH):
        forms = (text, json.dumps(text)[1:-1], json.dumps(json.dumps(text)[1:-1])[1:-1])
        assert any(form in strip for form in forms), text
    assert view.PARTS_HINT_WATCH == "Toca ▶ para ver cada parte."
    # a phone: one row that slides sideways; the desktop column: it wraps
    assert "nowrap" in strip and "wrap" in strip and "overflowX" in strip


def test_the_layouts() -> None:
    from . import final_video_card as view

    columns = str(view._body(view.COLUMNS).render())
    stacked = str(view._body(view.STACKED).render())
    assert "20rem minmax(0, 1fr)" in columns and "24rem minmax(0, 1fr)" in columns
    assert "minmax" not in stacked
    for rendered in (columns, stacked):
        assert "q-rv-stage" in rendered and "q-rv-media-empty" in rendered
    with pytest.raises(ValueError):
        view.final_video_card("x", layout="wide")


def test_no_chooser_left_behind() -> None:
    from . import final_video_card as view

    for gone in ("_part_choice", "_chosen_preview", "CHANGE_PREVIEW_ID", "CHANGE_PICK_LABEL"):
        assert not hasattr(view, gone), gone
    assert not hasattr(FinalVideoState, "toggle_change")


# -- 11. m-25016656, final UX review ----------------------------------------------------------


def test_the_empty_frame_says_what_it_waits_for() -> None:
    from . import final_video_card as view

    assert view.JOINING_STAGE_TEXT == "Estamos juntando tus partes. En un momento lo ves aquí."
    stage = str(view._player(view.COLUMNS).render())
    for text in (view.EMPTY_STAGE_TEXT, view.JOINING_STAGE_TEXT):
        forms = (text, json.dumps(text)[1:-1], json.dumps(json.dumps(text)[1:-1])[1:-1])
        assert any(form in stage for form in forms), text
    assert "wants_refresh" in stage  # joining: its own words
    # failed or purged: the film glyph alone (the notice on the right says why)
    assert '=== "failed"' in stage and '=== "purged"' in stage and "LucideFilm" in stage


def test_the_card_keeps_one_live_region() -> None:
    from . import final_video_card as view

    rendered = str(view._decisions(view.COLUMNS).render())
    assert 'role:"status"' not in rendered and 'role:"alert"' not in rendered
    assert 'role:"note"' in rendered


def test_a_tile_names_itself_with_its_visible_words() -> None:
    from . import final_video_card as view

    tile = str(view._part_card(PartProgressState.part_tiles[0]).render())
    assert '": parte "' in tile and "Cambiar esta" in tile and "Elegida" in tile
    assert view.CHOOSE_ID_PREFIX == module.CHOOSE_ID_PREFIX == "q-part-choose-"
    assert '"q-part-choose-"' in tile  # a stable id per part, for «Cancelar»
    # «Aprobar» is the card's one filled button: a chosen tile is `soft`
    assert '"solid"' not in tile and '"soft"' in tile


def test_cancelar_takes_the_keyboard_back_to_its_part() -> None:
    state = FinalVideoState()
    state.part_options = ["1", "2"]
    FinalVideoState.choose_part.fn(state, "2")
    event = FinalVideoState.cancel_change.fn(state)
    assert "q-part-choose-2" in str(event) and state.change_index == ""
    assert FinalVideoState.cancel_change.fn(state) is None  # nothing chosen: no focus move


async def test_crear_otra_version_takes_the_keyboard_to_the_status_line(
    backend: Backend,
) -> None:
    from .part_progress_state import STATUS_ID

    assert module.PARTS_STATUS_ID == STATUS_ID
    state = await _loaded()
    FinalVideoState.choose_part.fn(state, "2")
    events = await _drain(FinalVideoState.change_part.fn(state))
    assert STATUS_ID in str(events[0]) and events[-1].name == module.PART_PROGRESS_POLL


async def test_a_part_that_can_no_longer_change_closes_its_words(backend: Backend) -> None:
    """Review: a read that drops the chosen part (it is being made again) closes the form
    and its words — never a form about a part that cannot change."""
    state = await _loaded()
    FinalVideoState.choose_part.fn(state, "2")
    FinalVideoState.set_change_text.fn(state, "más luz")
    backend.final = _final(parts=(_part(1), _part(2, has_preview=False, creating=True)))
    await _drain(FinalVideoState.refresh.fn(state, str(PARENT)))
    assert state.part_options == ["1"]
    assert state.change_index == "" and not state.change_open and state.change_text == ""


# -- 12. m-25016656 final review: an approved video is only to watch -----------------------


@pytest.mark.parametrize(
    ("join", "closed"),
    [("approved", True), ("purged", True), ("ready", False), ("waiting", False), ("", False)],
)
def test_closed_is_approved_or_purged(join: str, closed: bool) -> None:
    """A part of an approved video turns «Venció» after 7 days in the backend
    (`part_progress.derive_state`: APPROVED + `draft_expired`, no action) — on a screen
    that is only to watch, that must not ask for a decision."""
    state = FinalVideoState()
    state.join_state = join
    assert state.closed is closed


def test_an_approved_video_asks_for_no_decision() -> None:
    from . import final_video_card as view
    from .part_progress_panel import _content, _status
    from .part_progress_vm import STATUS_CLOSED_MANY, STATUS_CLOSED_ONE

    assert (STATUS_CLOSED_ONE, STATUS_CLOSED_MANY) == ("Tu parte", "Tus {total} partes")
    line = _status("p").render()["children"][0]
    # the line: «Tus 3 partes» while closed, the usual line otherwise
    assert "final_video_state.closed" in str(line)
    rows = str(_content("p").render())
    # the rows waiting for a decision are not drawn on a closed video
    cond = rows[rows.index("decision_rows_rx_state_.length") :][:400]
    assert "final_video_state.closed" in cond
    # nor does a part's tile show its decision word there
    tile = str(view._part_card(PartProgressState.part_tiles[0]).render())
    word = tile[tile.index('?.["word"]?.valueOf?.() === ""') :][:300]
    assert "final_video_state.closed" in word


def test_another_video_is_never_closed_by_the_previous_one() -> None:
    """Review: an approved video A, then another video B — `closed` starts over."""
    state = FinalVideoState()
    state.parent_id = str(PARENT)
    state.join_state = "approved"
    assert state.closed
    FinalVideoState._reset(state, str(OTHER))
    assert state.parent_id == str(OTHER) and not state.closed
