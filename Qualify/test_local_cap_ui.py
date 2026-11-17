"""EF-15 (m-25026575): when today's videos made with the owner's photos and videos are
spent, «Crear» and «Pedir otra versión» say so in the cap's own words
(`LocalDailyCapReached.text`), never the generic line, and give the button back."""

from __future__ import annotations

from uuid import uuid4

import pytest
from qualify_api.creative.local_cap import LocalDailyCapReached

from . import creative_state as module
from .creative_state import _BRIEF_INVALID, CreativeState
from .test_create_busy_button import _last_step, _press_crear, _session
from .test_generator_campaign import _Proxy


def _cap() -> LocalDailyCapReached:
    return LocalDailyCapReached(used=10, cap=10)


async def test_crear_at_the_cap_says_the_cap_not_the_generic_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session(monkeypatch)

    def refuse(*args: object, **kwargs: object) -> None:
        raise _cap()

    monkeypatch.setattr(module, "submit_brief", refuse)
    state = _last_step()
    await _press_crear(state)
    assert state.create_error == _cap().text != _BRIEF_INVALID
    assert not state.is_submitting and state.create_primary_label == "Crear"
    assert state.generator_view != "result"


async def test_another_version_at_the_cap_says_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    _session(monkeypatch)
    draft = uuid4()
    monkeypatch.setattr(CreativeState, "_route_draft_id", lambda self: draft)

    def refuse(*args: object, **kwargs: object) -> None:
        raise _cap()

    monkeypatch.setattr(module, "reject_draft", refuse)
    state = CreativeState()
    events = [e async for e in CreativeState.reject_current.fn(_Proxy(state), True)]
    assert events == []  # nothing refreshed: the piece stays as it was
    assert state.action_error == _cap().text
