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
from collections.abc import Iterator
from datetime import UTC, datetime
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
    assert state.card.quota_text.startswith("Al aprobar usas 15 de tus 40 segundos")
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
    FinalVideoState.toggle_change.fn(state)
    FinalVideoState.set_change_index.fn(state, "7")  # not a part of this video
    assert state.change_index == ""
    FinalVideoState.set_change_index.fn(state, "2")
    FinalVideoState.set_change_text.fn(state, "Más cerca del producto")
    await _drain(FinalVideoState.change_part.fn(state))
    assert backend.calls == [("change", (TENANT, PARENT, 2, "Más cerca del producto", USER))]
    assert not state.change_open and state.change_text == "" and state.error == ""
    FinalVideoState.toggle_change.fn(state)
    FinalVideoState.set_change_index.fn(state, "1")
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
    for word in ("Elegir d", "parte quieres cambiar", "Crear otra versi"):  # ASCII: escaped
        assert word in rendered
    source = (_HERE / "final_video_card.py").read_text(encoding="utf-8")
    assert "loading_spinner" not in source and "rx.spinner" not in source
    assert final_video_card(str(PARENT)) is not None  # a plain id works too
    assert "q-thumb" in rendered  # each part's tile is the system's `media_thumb`


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
    "use,text",
    [
        (
            VideoUse(uses=20, quota=40, left=35),
            "Te quedan 35 de tus 40 segundos de video del mes. "
            "Al aprobar usas 20 y te quedarían 15 segundos.",
        ),
        (
            VideoUse(uses=20, quota=40, left=21),
            "Te quedan 21 de tus 40 segundos de video del mes. "
            "Al aprobar usas 20 y te quedaría 1 segundo.",
        ),
        (
            VideoUse(uses=1, quota=40, left=1),
            "Te queda 1 de tus 40 segundos de video del mes. "
            "Al aprobar usas 1 y te quedarían 0 segundos.",
        ),
        (
            VideoUse(uses=20, quota=40, left=40),
            "Al aprobar usas 20 de tus 40 segundos de video del mes. Te quedarían 20 segundos.",
        ),
        (VideoUse(uses=20, quota=40, left=40, unlimited=True), ""),
    ],
)
def test_the_seconds_add_up(use: VideoUse, text: str) -> None:
    assert vm.quota_text(use) == text


def test_short_of_seconds_says_what_is_left() -> None:
    said = vm.quota_text(VideoUse(uses=20, quota=40, left=10))
    assert said == videos_short_text(20, 10, 40) and "quedarían" not in said


def test_a_part_approved_before_does_not_count_again() -> None:
    parts = (_part(1, approved=True), _part(2), _part(3))
    card = vm.final_video_card(
        _final(parts=parts, seconds=24, video_use=VideoUse(uses=20, quota=40, left=35))
    )
    assert card.charged_note == "La parte 1 ya está aprobada: no vuelve a contar."
    assert vm.charged_note((1, 2), 24, VideoUse(uses=8, quota=40, left=35)) == (
        "Las partes 1 y 2 ya están aprobadas: no vuelven a contar."
    )
    two = (_part(1, approved=True), _part(2, approved=True), _part(3))
    assert _final(parts=two).approved_parts == (1, 2)
    same = _final(parts=parts, seconds=20, video_use=VideoUse(uses=20, quota=40, left=35))
    assert vm.final_video_card(same).charged_note == ""  # nothing to explain


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
    assert hint == "Disponible cuando la parte 2 tenga su vista previa y cambies la parte 1."


def test_each_part_carries_its_poster(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        provider, "issue_view_path", lambda tenant, key, media_type: f"/r2media/{media_type}"
    )
    parts = (_part(1, poster_key="t/x/part1.jpg"), _part(2), _part(3, draft_id=None))
    read = provider.card_from(_final(parts=parts), TENANT, "UTC")
    assert read.thumbs == (
        {"index": "1", "key": "t/x/part1.jpg", "url": "/r2media/image"},
        {"index": "2", "key": "", "url": ""},  # no poster: the neutral frame
    )


async def test_the_state_keeps_the_tiles(backend: Backend) -> None:
    backend.final = _final(parts=(_part(1, poster_key="uploads/p1.jpg"), _part(2)))
    state = await _loaded()
    assert state.part_thumbs[0] == {"index": "1", "key": "uploads/p1.jpg", "url": ""}
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
    """Deivid, 2026-11-09: [Aprobar] [Cambiar una parte] — or [Aprobar] [Crear otra
    versión] [Cancelar] — as the card's last row, the approve texts right above it."""
    from . import final_video_card as view

    source = inspect.getsource(view._body)
    assert source.index("_approve_texts()") < source.index("_actions()")
    assert source.count("_actions()") == 1 and "_approve_button()" not in source
    actions = inspect.getsource(view._actions)
    assert actions.index("_approve_button()") < actions.index("CHANGE_SUBMIT")
    assert actions.index("_approve_button()") < actions.index("change_part_label")
