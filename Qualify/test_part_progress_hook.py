"""UI-7 (m-24921082): the result of a video by parts in the generator — the parts' panel
and «Tu video completo» mounted, never the empty video stage, «Revisar y aprobar» held
(with its reason) while parts or the join are missing, and no «lista» toast when only the
parent's text came out."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from . import content_generator as cg
from .creative_state import CreativeState
from .part_progress_vm import PARTS_HEADING_TEXT, PARTS_KIND_LABEL


def test_a_video_by_parts_shows_its_parts_and_whole_video_not_an_empty_stage() -> None:
    js = str(cg._parts_video_result().render())
    assert "part_progress_state" in js  # the panel (its poll mounts with it)
    assert "final_video_state" in js  # «Tu video completo», always mounted
    # one stage only: «Tu video completo»'s own (m-25016656), never a single video's
    assert js.count("q-rv-stage") == 1
    single = str(cg._video_result().render())
    assert "shot_video" in single  # the branch is chosen by the kind


def test_the_result_words_for_a_video_by_parts() -> None:
    source = inspect.getsource(cg._result_view) + inspect.getsource(cg._workspace)
    assert "PARTS_KIND_LABEL" in source and "PARTS_HEADING_TEXT" in source
    assert PARTS_KIND_LABEL == "Video por partes"
    assert PARTS_HEADING_TEXT.startswith("Así va tu video")
    heading = str(cg._parts_hold())
    for needed in ("shot_video", "gen_is_ready", "cancelled", "parts_pending", "join_state"):
        assert needed in heading


def test_a_parent_whose_text_came_out_is_not_announced_ready() -> None:
    source = inspect.getsource(CreativeState.poll_generator.fn)
    branch = source.index('vm.kind == "shot_video"')
    # the ring still drops, the «lista» toast does not
    assert source.index("yield GenerationState.refresh", branch) < source.index(
        "_generation_done_events(outcome)", branch
    )


# -- poll_generator, run: a parent's text is not the video ------------------------------


class _Proxy:
    """`async with self` over a plain `CreativeState` (as the price write-back tests)."""

    def __init__(self, state: CreativeState) -> None:
        object.__setattr__(self, "_state", state)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._state, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._state, name, value)


async def _landed(monkeypatch: pytest.MonkeyPatch, kind: str) -> list[str]:
    from . import creative_state as module

    ids = (uuid4(), uuid4(), uuid4())
    vm = SimpleNamespace(
        kind=kind,
        is_drafting=False,
        is_failed=False,
        can_finish_gallery=False,
        queue=SimpleNamespace(queued=False, cancelled=False),
    )

    async def session_ids(self: object) -> tuple[UUID, UUID, UUID]:
        return ids

    async def to_thread(fn: Any, *args: Any, **kw: Any) -> Any:
        return fn(*args, **kw)

    async def no_price(self: object, tenant_id: UUID, draft_id: str) -> list[Any]:
        return []

    monkeypatch.setattr(CreativeState, "_session_ids", session_ids)
    monkeypatch.setattr(CreativeState, "_sync_catalog_price", no_price)
    monkeypatch.setattr(module, "draft_detail", lambda tenant_id, draft_id: vm)
    monkeypatch.setattr(module.asyncio, "to_thread", to_thread)
    state = CreativeState()
    state.gen_draft_id = str(uuid4())
    proxy = _Proxy(state)
    events: list[str] = []
    async for event in CreativeState.poll_generator.fn(proxy):
        events.append(str(event))
    return events


async def test_a_parts_parent_landing_drops_the_ring_without_a_ready_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = await _landed(monkeypatch, "shot_video")
    assert sum("GenerationState.refresh" in e for e in events) == 2  # start and landing
    assert not any("toast" in e.lower() for e in events)


async def test_any_other_piece_still_says_it_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    events = await _landed(monkeypatch, "clip")
    assert any("toast" in e.lower() for e in events)


# -- the foot: a video by parts is approved only on its card ----------------------------


def _ready_piece(kind: str) -> CreativeState:
    state = CreativeState()
    state.generator_view = "result"
    state.gen_draft_id = str(uuid4())
    state.gen_draft = SimpleNamespace(  # type: ignore[assignment]
        kind=kind,
        is_drafting=False,
        is_failed=False,
        can_finish_gallery=False,
        queue=SimpleNamespace(queued=False, cancelled=False, note=""),
    )
    return state


def test_the_foot_of_a_video_by_parts_has_no_primary() -> None:
    source = inspect.getsource(cg)
    foot = source[source.index("foot=rx.cond(") :]
    foot = foot[: foot.index("step=CreativeState.create_step_n,\n        direction")]
    assert "_approves_on_card()" in foot
    assert "step_foot(\n                    None," in foot  # no primary, «Atrás» stays
    assert "_parts_hold" not in foot  # no held button, no reason
    approves = str(cg._approves_on_card())
    assert "shot_video" in approves and "result" in approves


def test_the_foot_never_sends_a_video_by_parts_to_review() -> None:
    assert _ready_piece("shot_video").create_continue() is None


def test_any_other_piece_still_goes_to_review() -> None:
    assert _ready_piece("clip").create_continue() is not None
