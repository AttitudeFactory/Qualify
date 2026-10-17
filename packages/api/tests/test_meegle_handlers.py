"""`qualify_api.meegle.handlers` driven through the real `Processor` with an in-memory
queue and a fake engine — offline. Pins the prelude (openapi, other type, contract) and
the per-event outcomes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.meegle.handlers import (
    IGNORED_OPENAPI,
    IGNORED_ROLLBACK,
    NODE_COMPLETED_HANDLER_KEY,
    NODE_ROLLED_BACK_HANDLER_KEY,
    OTHER_WORK_ITEM_TYPE,
    WORK_ITEM_NOT_FOUND,
    WORK_ITEM_TERMINATED_HANDLER_KEY,
    meegle_handlers,
    production_meegle_handlers,
)
from qualify_api.meegle.onboarding import InvitationResult, WorkItemNotFound
from qualify_api.meegle.settings import MeegleNames
from qualify_api.webhooks.processor import Processor
from qualify_api.webhooks.repository import MAX_ATTEMPTS, ClaimedEvent

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
ITEM = 5390584662


class FakeQueue:
    def __init__(self, events: list[ClaimedEvent]) -> None:
        self.events = events
        self.settled: dict[UUID, tuple[str, str | None]] = {}
        self.failed: dict[UUID, tuple[int, str]] = {}

    def claim(self, *, worker_id: str, now: datetime, limit: int) -> list[ClaimedEvent]:
        batch, self.events = self.events[:limit], self.events[limit:]
        return batch

    def settle(self, *, event_id, worker_id, now, status, error=None) -> bool:  # noqa: ANN001
        self.settled[event_id] = (status, error)
        return True

    def fail(self, *, event_id, worker_id, now, attempts, error) -> str | None:  # noqa: ANN001
        self.failed[event_id] = (attempts, error)
        return "dead" if attempts >= MAX_ATTEMPTS else "failed"


class FakeEngine:
    def __init__(self) -> None:
        self.nodes = {"started": "Datos", "state_0": "Invitada", "state_1": "Registrada"}
        self.started: list[int] = []
        self.expired: list[int] = []
        self.result = InvitationResult(ok=True, invite_id=uuid4())
        self.raises: Exception | None = None

    def node_name(self, work_item_id: int, key: str) -> str | None:
        if self.raises is not None:
            raise self.raises
        return self.nodes.get(key)

    def start_invitation(self, work_item_id: int) -> InvitationResult:
        if self.raises is not None:
            raise self.raises
        self.started.append(work_item_id)
        return self.result

    def expire_for_terminated(self, work_item_id: int) -> int:
        self.expired.append(work_item_id)
        return 2


def _event(value: Any, *, field: str = "2001", attempts: int = 1) -> ClaimedEvent:
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="meegle",
        entry_id=str(ITEM),
        field=field,
        value=value,
        attempts=attempts,
    )


async def _run(engine: FakeEngine, *events: ClaimedEvent) -> FakeQueue:
    queue = FakeQueue(list(events))
    processor = Processor(
        queue=queue,
        handlers=meegle_handlers(engine, work_item_type="alta_cliente", names=MeegleNames()),  # type: ignore[arg-type]
        worker_id="w1",
        clock=lambda: NOW,
    )
    await processor.run_once()
    return queue


def test_handler_keys_are_object_qualified() -> None:
    assert NODE_COMPLETED_HANDLER_KEY == "meegle:2001"
    assert WORK_ITEM_TERMINATED_HANDLER_KEY == "meegle:1005"
    assert NODE_ROLLED_BACK_HANDLER_KEY == "meegle:2004"


async def test_datos_completed_starts_the_invitation(meegle_events) -> None:  # noqa: ANN001
    engine = FakeEngine()
    event = _event(meegle_events.value(nodes=["started"]))
    queue = await _run(engine, event)
    assert queue.settled[event.id] == ("processed", None)
    assert engine.started == [ITEM]


async def test_an_invitation_the_person_must_fix_is_settled_not_retried(meegle_events) -> None:  # noqa: ANN001
    engine = FakeEngine()
    engine.result = InvitationResult(ok=False, reason="invalid_input")
    event = _event(meegle_events.value(nodes=["started"]))
    queue = await _run(engine, event)
    assert queue.settled[event.id] == ("processed", "invite_failed:invalid_input")
    assert queue.failed == {}


async def test_other_nodes_are_ignored(meegle_events) -> None:  # noqa: ANN001
    engine = FakeEngine()
    event = _event(meegle_events.value(nodes=["state_1"]))
    none = _event(meegle_events.value(nodes=[]))
    queue = await _run(engine, event, none)
    assert queue.settled[event.id] == ("processed", "ignored:node=Registrada")
    assert queue.settled[none.id] == ("processed", "ignored:node=?")
    assert engine.started == []


async def test_qualifys_own_writes_never_trigger_anything(meegle_events) -> None:  # noqa: ANN001
    engine = FakeEngine()
    events = [
        _event(meegle_events.value(source="openapi", nodes=["started"])),
        _event(meegle_events.value(source="openapi", event_type=1005), field="1005"),
        _event(meegle_events.value(source="openapi", event_type=2004), field="2004"),
    ]
    queue = await _run(engine, *events)
    for event in events:
        assert queue.settled[event.id] == ("processed", IGNORED_OPENAPI)
    assert engine.started == [] and engine.expired == []


async def test_another_work_item_type_is_unsupported_and_kept(meegle_events) -> None:  # noqa: ANN001
    engine = FakeEngine()
    event = _event(meegle_events.value(nodes=["started"], work_item_type="story"))
    queue = await _run(engine, event)
    assert queue.settled[event.id] == ("unsupported", OTHER_WORK_ITEM_TYPE)
    assert engine.started == []


async def test_off_contract_values_are_dead(meegle_events) -> None:  # noqa: ANN001
    engine = FakeEngine()
    bad = [
        _event({"source": "normal"}),  # no data
        _event({"source": "normal", "data": {"event_type": "x", "idempotent_key": "k"}}),
        _event(meegle_events.value(nodes=["started"], work_item_id=None)),  # no item
        _event(None),
    ]
    queue = await _run(engine, *bad)
    for event in bad:
        assert queue.settled[event.id] == ("dead", "contract_violation")


async def test_a_vanished_item_is_dead_not_retried(meegle_events) -> None:  # noqa: ANN001
    engine = FakeEngine()
    engine.raises = WorkItemNotFound("5390584662")
    event = _event(meegle_events.value(nodes=["started"]))
    queue = await _run(engine, event)
    assert queue.settled[event.id] == ("dead", WORK_ITEM_NOT_FOUND)


async def test_an_infrastructure_failure_is_retried(meegle_events) -> None:  # noqa: ANN001
    engine = FakeEngine()
    engine.raises = ConnectionError("meegle down")
    event = _event(meegle_events.value(nodes=["started"]), attempts=2)
    queue = await _run(engine, event)
    assert event.id not in queue.settled
    assert queue.failed[event.id] == (2, "ConnectionError")


async def test_terminated_expires_the_invites(meegle_events) -> None:  # noqa: ANN001
    engine = FakeEngine()
    event = _event(meegle_events.value(event_type=1005), field="1005")
    queue = await _run(engine, event)
    assert queue.settled[event.id] == ("processed", "expired=2")
    assert engine.expired == [ITEM]


async def test_rollback_is_ignored(meegle_events) -> None:  # noqa: ANN001
    engine = FakeEngine()
    event = _event(meegle_events.value(event_type=2004, nodes=["started"]), field="2004")
    queue = await _run(engine, event)
    assert queue.settled[event.id] == ("processed", IGNORED_ROLLBACK)
    assert engine.started == []


def test_production_handlers_are_empty_when_the_engine_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "QUALIFY_MEEGLE_PLUGIN_ID",
        "QUALIFY_MEEGLE_PLUGIN_SECRET",
        "QUALIFY_MEEGLE_CALLBACK_TOKEN",
        "QUALIFY_MEEGLE_PROJECT_KEY",
        "QUALIFY_MEEGLE_WORK_ITEM_TYPE",
        "QUALIFY_MEEGLE_USER_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    assert dict(production_meegle_handlers()) == {}
