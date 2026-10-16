"""`qualify_api.mail.handlers` driven through the real `Processor` with an in-memory queue,
a fake invite marker and a fake Meegle notifier — offline. What each event does to the
row, when Meegle is written, idempotency on repeats, and the engine's delivery methods
against a fake Meegle API served by `httpx.MockTransport`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.auth.invites import DeliveryMark
from qualify_api.mail.handlers import (
    BOUNCED_HANDLER_KEY,
    CONTRACT_VIOLATION,
    DELIVERED_HANDLER_KEY,
    IGNORED_REPEAT,
    IGNORED_UNKNOWN_EMAIL,
    MEEGLE_FAILED_PREFIX,
    OPENED_HANDLER_KEY,
    ResendEvent,
    production_resend_handlers,
    resend_handlers,
)
from qualify_api.meegle.client import MeegleClient
from qualify_api.meegle.onboarding import OnboardingEngine
from qualify_api.meegle.schema import SchemaResolver
from qualify_api.meegle.settings import MeegleNames, MeegleSettings
from qualify_api.webhooks.processor import Processor
from qualify_api.webhooks.repository import MAX_ATTEMPTS, ClaimedEvent

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
EMAIL_ID = "11111111-1111-4111-8111-111111111111"
INVITE_ID = UUID("22222222-2222-4222-8222-222222222222")
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


class FakeInvites:
    """`mark_delivery` over an in-memory row: the three columns, first-time semantics."""

    def __init__(self, *, work_item: int | None = ITEM, known: bool = True) -> None:
        self.work_item = work_item
        self.known = known
        self.columns: dict[str, datetime | None] = {
            "delivered": None,
            "opened": None,
            "bounced": None,
        }
        self.calls: list[tuple[str, str, datetime | None]] = []
        self.raises: Exception | None = None

    def mark(self, email_id: str, *, kind: str, at: datetime | None = None) -> DeliveryMark | None:
        if self.raises is not None:
            raise self.raises
        self.calls.append((email_id, kind, at))
        if not self.known or email_id != EMAIL_ID:
            return None
        first = self.columns[kind] is None
        if first:
            self.columns[kind] = at or NOW
        return DeliveryMark(
            invite_id=INVITE_ID,
            meegle_work_item_id=self.work_item,
            first=first,
            delivered_at=self.columns["delivered"],
            opened_at=self.columns["opened"],
            bounced_at=self.columns["bounced"],
        )


class FakeNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int, Any]] = []
        self.raises: Exception | None = None

    def mark_delivered(self, work_item_id: int, *, already_opened: bool = False) -> None:
        if self.raises is not None:
            raise self.raises
        self.calls.append(("delivered", work_item_id, already_opened))

    def mark_opened(self, work_item_id: int) -> None:
        if self.raises is not None:
            raise self.raises
        self.calls.append(("opened", work_item_id, None))

    def mark_bounced(self, work_item_id: int, reason: str) -> None:
        if self.raises is not None:
            raise self.raises
        self.calls.append(("bounced", work_item_id, reason))


def value(event_type: str = "email.delivered", **data: object) -> dict:
    return {
        "type": event_type,
        "created_at": "2026-10-16T12:00:00.000Z",
        "data": {
            "created_at": "2026-10-16T11:59:59.500+00:00",
            "email_id": EMAIL_ID,
            "from": "Qualify <no-reply@send.example.test>",
            "to": ["maria@example.test"],
            "subject": "Invitación",
            **data,
        },
    }


def _event(val: Any, *, field: str = "email.delivered", attempts: int = 1) -> ClaimedEvent:
    email_id = val.get("data", {}).get("email_id", "-") if isinstance(val, dict) else "-"
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="resend",
        entry_id=email_id,
        field=field,
        value=val,
        attempts=attempts,
    )


async def _run(
    *events: ClaimedEvent, invites: FakeInvites | None = None, notifier: FakeNotifier | None = None
) -> tuple[FakeQueue, FakeInvites, FakeNotifier | None]:
    invites = invites or FakeInvites()
    queue = FakeQueue(list(events))
    processor = Processor(
        queue=queue,
        handlers=resend_handlers(notifier, marker=invites.mark),
        worker_id="w1",
        clock=lambda: NOW,
    )
    await processor.run_once()
    return queue, invites, notifier


def test_handler_keys_are_object_qualified() -> None:
    assert DELIVERED_HANDLER_KEY == "resend:email.delivered"
    assert OPENED_HANDLER_KEY == "resend:email.opened"
    assert BOUNCED_HANDLER_KEY == "resend:email.bounced"


async def test_delivered_marks_the_row_and_completes_invitada() -> None:
    notifier = FakeNotifier()
    event = _event(value())
    queue, invites, _ = await _run(event, notifier=notifier)
    assert queue.settled[event.id] == ("processed", None)
    assert invites.calls == [(EMAIL_ID, "delivered", NOW)]
    assert invites.columns["delivered"] == NOW
    assert notifier.calls == [("delivered", ITEM, False)]


async def test_opened_and_bounced_write_their_status() -> None:
    notifier = FakeNotifier()
    opened = _event(value("email.opened"), field="email.opened")
    bounced = _event(
        value(
            "email.bounced",
            bounce={"message": "Mailbox does not exist", "type": "Permanent", "subType": "General"},
        ),
        field="email.bounced",
    )
    queue, invites, _ = await _run(opened, bounced, notifier=notifier)
    assert queue.settled[opened.id] == ("processed", None)
    assert queue.settled[bounced.id] == ("processed", None)
    assert invites.columns["opened"] == NOW and invites.columns["bounced"] == NOW
    assert notifier.calls == [
        ("opened", ITEM, None),
        ("bounced", ITEM, "Mailbox does not exist (Permanent / General)"),
    ]


async def test_a_delivery_after_an_open_keeps_the_later_status() -> None:
    notifier = FakeNotifier()
    opened = _event(value("email.opened"), field="email.opened")
    delivered = _event(value())
    await _run(opened, delivered, notifier=notifier)
    assert notifier.calls == [("opened", ITEM, None), ("delivered", ITEM, True)]


async def test_a_repeated_event_changes_nothing_and_does_not_write_meegle_again() -> None:
    notifier = FakeNotifier()
    first = _event(value())
    again = _event(value())
    queue, invites, _ = await _run(first, again, notifier=notifier)
    assert queue.settled[first.id] == ("processed", None)
    assert queue.settled[again.id] == ("processed", IGNORED_REPEAT)
    assert len(invites.calls) == 2 and notifier.calls == [("delivered", ITEM, False)]


async def test_an_unknown_email_id_is_ignored() -> None:
    notifier = FakeNotifier()
    event = _event(value())
    queue, _, _ = await _run(event, invites=FakeInvites(known=False), notifier=notifier)
    assert queue.settled[event.id] == ("processed", IGNORED_UNKNOWN_EMAIL)
    assert notifier.calls == []


async def test_an_invite_without_a_meegle_item_or_without_meegle_never_calls_meegle() -> None:
    notifier = FakeNotifier()
    plain = _event(value())
    queue, _, _ = await _run(plain, invites=FakeInvites(work_item=None), notifier=notifier)
    assert queue.settled[plain.id] == ("processed", None) and notifier.calls == []
    off = _event(value())
    queue, invites, _ = await _run(off, notifier=None)
    assert queue.settled[off.id] == ("processed", None)
    assert invites.columns["delivered"] == NOW


async def test_a_meegle_failure_is_best_effort_and_settled() -> None:
    notifier = FakeNotifier()
    notifier.raises = RuntimeError("meegle down")
    event = _event(value())
    queue, invites, _ = await _run(event, notifier=notifier)
    assert queue.settled[event.id] == ("processed", f"{MEEGLE_FAILED_PREFIX}RuntimeError")
    assert invites.columns["delivered"] == NOW  # the row is the record
    assert queue.failed == {}


async def test_a_database_failure_is_retried() -> None:
    invites = FakeInvites()
    invites.raises = ConnectionError("pg down")
    event = _event(value(), attempts=1)
    queue, _, _ = await _run(event, invites=invites, notifier=FakeNotifier())
    assert queue.failed[event.id] == (1, "ConnectionError")
    assert event.id not in queue.settled


async def test_off_contract_values_are_dead() -> None:
    bad_shape = _event({"type": "email.delivered", "data": {}})
    renamed = _event(value("email.clicked"))  # a key registered by mistake
    queue, invites, _ = await _run(bad_shape, renamed, notifier=FakeNotifier())
    assert queue.settled[bad_shape.id] == ("dead", CONTRACT_VIOLATION)
    assert queue.settled[renamed.id] == ("dead", CONTRACT_VIOLATION)
    assert invites.calls == []


def test_the_bounce_reason_tolerates_every_shape() -> None:
    assert ResendEvent.model_validate(value("email.bounced")).bounce_reason() == (
        "sin detalle del proveedor"
    )
    assert ResendEvent.model_validate(value("email.bounced", bounce={})).bounce_reason() == (
        "sin detalle del proveedor"
    )
    assert (
        ResendEvent.model_validate(
            value("email.bounced", bounce={"message": "Nope"})
        ).bounce_reason()
        == "Nope"
    )
    assert (
        ResendEvent.model_validate(
            value("email.bounced", bounce={"type": "Transient"})
        ).bounce_reason()
        == "Transient"
    )
    event = ResendEvent.model_validate(value())
    assert event.happened_at() == NOW
    no_time = ResendEvent.model_validate({"type": "email.delivered", "data": {"email_id": "x"}})
    assert no_time.happened_at() is None


def test_production_handlers_register_the_three_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "QUALIFY_MEEGLE_PLUGIN_ID",
        "QUALIFY_MEEGLE_PLUGIN_SECRET",
        "QUALIFY_MEEGLE_CALLBACK_TOKEN",
        "QUALIFY_MEEGLE_PROJECT_KEY",
        "QUALIFY_MEEGLE_WORK_ITEM_TYPE",
        "QUALIFY_MEEGLE_USER_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    # Meegle off: the handlers exist all the same (the row is always written).
    assert set(production_resend_handlers()) == {
        DELIVERED_HANDLER_KEY,
        OPENED_HANDLER_KEY,
        BOUNCED_HANDLER_KEY,
    }


# --------------------------------------------------------------------------------------
# The engine's delivery methods against a fake Meegle Open API (httpx.MockTransport)
# --------------------------------------------------------------------------------------


class FakeMeegleApi:
    """Answers the token, `field/all`, `workflow/query`, `update_fields`, `operate` and
    `comment` calls, recording every write."""

    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.operations: list[tuple[str, dict]] = []
        self.comments: list[str] = []
        self.refuse_confirm: bool = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        payload = json.loads(request.content or b"{}")
        if path == "/open_api/authen/plugin_token":
            return httpx.Response(
                200, json={"data": {"token": "tok", "expire_time": 7200}, "error": {"code": 0}}
            )
        assert request.headers["X-Plugin-Token"] == "tok"
        if path.endswith("/field/all"):
            return httpx.Response(
                200,
                json={
                    "err_code": 0,
                    "data": [
                        {
                            "field_key": "f_status",
                            "field_name": "Estado Qualify",
                            "field_type_key": "select",
                            "options": [
                                {"label": label, "value": f"opt_{i}"}
                                for i, label in enumerate(
                                    ("pendiente", "invitada", "entregada", "abierta", "rebotó")
                                )
                            ],
                        },
                        {"field_key": "f_mail", "field_name": "Correo", "field_type_key": "text"},
                    ],
                },
            )
        if path.endswith("/workflow/query"):
            return httpx.Response(
                200,
                json={
                    "err_code": 0,
                    "data": {
                        "workflow_nodes": [
                            {"id": "started", "state_key": "started", "name": "Datos"},
                            {"id": "state_0", "state_key": "state_0", "name": "Invitada"},
                        ]
                    },
                },
            )
        if "/node/" in path and path.endswith("/operate"):
            node = path.split("/node/")[1].split("/")[0]
            self.operations.append((node, payload))
            if self.refuse_confirm:
                return httpx.Response(
                    200, json={"err_code": 10001, "err_msg": "node already completed"}
                )
            return httpx.Response(200, json={"err_code": 0, "data": None})
        if path.endswith("/comment/create"):
            self.comments.append(payload["content"])
            return httpx.Response(200, json={"err_code": 0, "data": 42})
        if request.method == "PUT":
            self.updates.append(
                {pair["field_key"]: pair["field_value"] for pair in payload["update_fields"]}
            )
            return httpx.Response(200, json={"err_code": 0, "data": None})
        raise AssertionError(f"unexpected call {request.method} {path}")


@pytest.fixture
def engine() -> tuple[OnboardingEngine, FakeMeegleApi]:
    api = FakeMeegleApi()
    settings = MeegleSettings(
        base_url="https://meegle.test",
        plugin_id="MII_TEST",
        plugin_secret="s3cret",
        callback_token="tok",
        project_key="proj-test",
        work_item_type="alta_cliente",
        user_key="1",
    )
    client = MeegleClient(settings, transport=httpx.MockTransport(api))
    names = MeegleNames()
    return OnboardingEngine(client, SchemaResolver(client, names), names=names), api


def test_mark_delivered_sets_entregada_and_completes_invitada(engine) -> None:  # noqa: ANN001
    eng, api = engine
    eng.mark_delivered(ITEM)
    assert api.updates == [{"f_status": "opt_2"}]
    assert api.operations == [("state_0", {"action": "confirm"})]
    # The open arrived first: the status stays `abierta`, the node is still completed.
    eng.mark_delivered(ITEM, already_opened=True)
    assert api.updates == [{"f_status": "opt_2"}]
    assert len(api.operations) == 2


def test_mark_delivered_tolerates_an_already_completed_node(engine) -> None:  # noqa: ANN001
    eng, api = engine
    api.refuse_confirm = True
    eng.mark_delivered(ITEM)  # no raise
    assert api.updates == [{"f_status": "opt_2"}] and len(api.operations) == 1


def test_mark_opened_and_bounced(engine) -> None:  # noqa: ANN001
    eng, api = engine
    eng.mark_opened(ITEM)
    assert api.updates == [{"f_status": "opt_3"}] and api.operations == []
    eng.mark_bounced(ITEM, "Mailbox   does not\nexist (Permanent)")
    assert api.updates[-1] == {"f_status": "opt_4"}
    (comment,) = api.comments
    assert comment.startswith("El correo de invitación rebotó: Mailbox does not exist (Permanent)")
    assert "«Correo»" in comment and "«Datos»" in comment
    eng.mark_bounced(ITEM, "   ")
    assert api.comments[-1].startswith("El correo de invitación rebotó: sin detalle del proveedor")
