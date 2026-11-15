"""m-25017846 (BU-B1) offline: the handler runs each inbound message through ONE
`repo.transaction()`, takes the conversation's lock first, and attributes the ad only
after the commit. The in-memory repository's `transaction()` rolls every table back on
an exception, as Postgres does (`test_whatsapp_menu_atomic_db.py` pins the real thing).
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.webhooks.repository import MAX_ATTEMPTS, ClaimedEvent
from qualify_api.whatsapp.handler import (
    AUTOMATION_ERROR_REASON,
    AUTOMATION_FAILED_EVENT,
    CTX_HANDOFF,
    PublishedMenu,
    whatsapp_messages_handler,
)
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.payment_status import CTX_PAYMENT_RECORD, STATUS_AWAITING
from qualify_api.whatsapp.repository import MemoryWhatsAppInboxRepository, StoredThreadState
from qualify_api.whatsapp.resolve import PhoneResolution, PhoneResolutionOutcome

TENANT = UUID("77777777-7777-4777-8777-000025017846")
CONNECTION = UUID("88888888-8888-4888-8888-000025017846")
PHONE_ROW = UUID("99999999-9999-4999-8999-000025017846")
WA_ID = "584240000001"
NOW = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)
RESOLVED = PhoneResolution(
    outcome=PhoneResolutionOutcome.RESOLVED,
    tenant_id=TENANT,
    connection_id=CONNECTION,
    phone_row_id=PHONE_ROW,
)


class Crash(RuntimeError):
    pass


class CrashingRepo(MemoryWhatsAppInboxRepository):
    """The second outbox row of the first run raises."""

    def __init__(self) -> None:
        super().__init__()
        self.enqueues = 0

    def enqueue_outbox(self, **kwargs: Any) -> UUID:  # type: ignore[override]
        self.enqueues += 1
        if self.enqueues == 2:
            raise Crash
        return super().enqueue_outbox(**kwargs)


def _event(*bodies: str) -> ClaimedEvent:
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="whatsapp_business_account",
        entry_id="waba",
        field="messages",
        value={
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "1555", "phone_number_id": "pn"},
            "contacts": [{"profile": {"name": "Cliente"}, "wa_id": WA_ID}],
            "messages": [
                {
                    "from": WA_ID,
                    "id": f"wamid.offline-{i}",
                    "timestamp": "1791953700",
                    "type": "text",
                    "text": {"body": body},
                }
                for i, body in enumerate(bodies)
            ],
        },
        attempts=1,
    )


def _handler(repo: MemoryWhatsAppInboxRepository, **kwargs: Any) -> Any:
    options: dict[str, Any] = {"menu_loader": lambda _row: PublishedMenu(BIANKI_DEMO_MENU)}
    options.update(kwargs)
    return whatsapp_messages_handler(resolve=lambda _pn: RESOLVED, repo=repo, **options)


async def test_a_crash_mid_outbox_rolls_the_whole_message_back_and_the_retry_replies_once() -> None:
    clean = MemoryWhatsAppInboxRepository()
    await _handler(clean)(_event("Hola"))
    expected = [row["payload"] for row in clean.outbox]
    assert len(expected) >= 2

    repo = CrashingRepo()
    handle = _handler(repo)
    event = _event("Hola")
    with pytest.raises(Crash):
        await handle(event)
    assert repo.messages == {} and repo.states == {} and repo.outbox == []

    assert (await handle(event)).status == "processed"
    assert [row["payload"] for row in repo.outbox] == expected
    assert (await handle(event)).status == "processed"
    assert [row["payload"] for row in repo.outbox] == expected


async def test_every_message_locks_its_conversation_and_two_messages_both_count() -> None:
    repo = MemoryWhatsAppInboxRepository()
    await _handler(repo)(_event("Hola"))
    thread_id = next(iter(repo.threads.values()))["id"]

    await _handler(repo)(_event_with_ids(("zzz uno", "wamid.a"), ("zzz dos", "wamid.b")))

    assert repo.locked_threads == [thread_id, thread_id, thread_id]
    assert repo.states[thread_id][1].attempts == 2


def _event_with_ids(*messages: tuple[str, str]) -> ClaimedEvent:
    event = _event(*(body for body, _ in messages))
    for raw, (_, wamid) in zip(event.value["messages"], messages, strict=True):
        raw["id"] = wamid
    return event


async def test_the_ad_attribution_runs_after_the_message_and_its_reply_are_stored() -> None:
    repo = MemoryWhatsAppInboxRepository()
    seen: list[tuple[int, int]] = []

    def attribute(**kwargs: Any) -> bool:
        seen.append((len(repo.messages), len(repo.outbox)))
        raise RuntimeError("attribution down")

    handle = _handler(repo, attribute_ad=attribute)
    event = _event("Hola")
    with pytest.raises(RuntimeError):
        await handle(event)
    # The menu's reply committed before the attribution failed: the retry (which skips
    # the stored message) can no longer lose it.
    stored = len(repo.outbox)
    assert stored >= 2 and seen == [(1, stored)]
    with pytest.raises(RuntimeError):
        await handle(event)
    assert len(repo.outbox) == stored


# --- the last attempt never loses the message ------------------------------------------


def _attempt(event: ClaimedEvent, attempts: int) -> ClaimedEvent:
    return replace(event, attempts=attempts)


async def test_a_step_that_always_fails_hands_the_stored_message_to_a_person_at_the_end(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken_menu(_row: UUID) -> PublishedMenu:
        raise ValueError("a published menu the Cloud API rejects")

    repo = MemoryWhatsAppInboxRepository()
    handle = _handler(repo, menu_loader=broken_menu)
    event = _event("Hola")

    for attempts in range(1, MAX_ATTEMPTS):
        with pytest.raises(ValueError):
            await handle(_attempt(event, attempts))
        # A retry is still coming: all-or-nothing, nothing landed.
        assert repo.messages == {} and repo.states == {} and repo.outbox == []

    with caplog.at_level(logging.ERROR, logger="qualify_api.whatsapp.handler"):
        outcome = await handle(_attempt(event, MAX_ATTEMPTS))

    assert outcome.status == "processed"  # settled: the change does not loop
    assert (CONNECTION, "wamid.offline-0") in repo.messages
    thread_id = next(iter(repo.threads.values()))["id"]
    _, state = repo.states[thread_id]
    assert state.paused_at is not None  # «Por responder» (inbox/awaiting.py 3a)
    assert state.context[CTX_HANDOFF]["reason"] == AUTOMATION_ERROR_REASON
    assert repo.outbox == []  # nothing sent by itself
    assert AUTOMATION_FAILED_EVENT in caplog.text

    # A reclaim of the same change afterwards writes nothing more.
    assert (await handle(_attempt(event, MAX_ATTEMPTS))).status == "processed"
    assert repo.outbox == [] and len(repo.messages) == 1


async def test_an_error_that_goes_away_on_a_retry_still_gets_the_full_reply_once() -> None:
    clean = MemoryWhatsAppInboxRepository()
    await _handler(clean)(_event("Hola"))
    expected = [row["payload"] for row in clean.outbox]

    failures = {"left": 2}

    def flaky_menu(_row: UUID) -> PublishedMenu:
        if failures["left"]:
            failures["left"] -= 1
            raise ConnectionError("transient")
        return PublishedMenu(BIANKI_DEMO_MENU)

    repo = MemoryWhatsAppInboxRepository()
    handle = _handler(repo, menu_loader=flaky_menu)
    event = _event("Hola")
    for attempts in (1, 2):
        with pytest.raises(ConnectionError):
            await handle(_attempt(event, attempts))
    assert (await handle(_attempt(event, 3))).status == "processed"

    assert [row["payload"] for row in repo.outbox] == expected
    _, state = next(iter(repo.states.values()))
    assert state.paused_at is None and CTX_HANDOFF not in state.context


# --- the last-attempt fallback leaves answered and handed-over chats alone -------------

OTHER_WA_ID = "584240000002"


def _two_customers_event() -> ClaimedEvent:
    """One change, two messages from two customers (A then B)."""
    event = _event("Hola", "Hola")
    event.value["contacts"].append({"profile": {"name": "Otro"}, "wa_id": OTHER_WA_ID})
    event.value["messages"][1]["from"] = OTHER_WA_ID
    return event


class FaultyRepo(MemoryWhatsAppInboxRepository):
    """`fail_outbox_for`: every outbox write after inserting that wamid raises (a step
    that always fails). `fail_insert_once`: the next insert of that wamid raises once (a
    transient blip on a replay). `fail_state_reads`: that many `get_thread_state` calls
    raise first (the main path's read; the fallback's succeeds)."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_outbox_for: set[str] = set()
        self.fail_insert_once: set[str] = set()
        self.fail_state_reads = 0
        self._current: str | None = None

    def insert_inbound_message(self, **kwargs: Any) -> bool:  # type: ignore[override]
        wamid = kwargs["external_message_id"]
        if wamid in self.fail_insert_once:
            self.fail_insert_once.discard(wamid)
            raise ConnectionError("transient")
        self._current = wamid
        return super().insert_inbound_message(**kwargs)

    def enqueue_outbox(self, **kwargs: Any) -> UUID:  # type: ignore[override]
        if self._current in self.fail_outbox_for:
            raise ValueError("always fails")
        return super().enqueue_outbox(**kwargs)

    def get_thread_state(self, thread_id: UUID) -> StoredThreadState | None:
        if self.fail_state_reads:
            self.fail_state_reads -= 1
            raise ConnectionError("transient")
        return super().get_thread_state(thread_id)


def _thread_of(repo: MemoryWhatsAppInboxRepository, wa_id: str) -> UUID:
    return repo.threads[(CONNECTION, "whatsapp", wa_id)]["id"]


async def test_the_fallback_never_pauses_a_chat_whose_message_the_menu_already_answered() -> None:
    repo = FaultyRepo()
    handle = _handler(repo)
    event = _two_customers_event()
    first, second = (m["id"] for m in event.value["messages"])
    repo.fail_outbox_for = {second}

    with pytest.raises(ValueError):
        await handle(_attempt(event, 1))  # A committed with its reply; B failed
    thread_a = _thread_of(repo, WA_ID)
    _, answered = repo.states[thread_a]
    replies_a = [row for row in repo.outbox if row["thread_id"] == thread_a]
    assert replies_a and answered.paused_at is None

    repo.fail_insert_once = {first}  # A's replay hits a blip on the last attempt
    assert (await handle(_attempt(event, MAX_ATTEMPTS))).status == "processed"

    # A: already answered — untouched (not paused, no handoff, no new row).
    _, after = repo.states[thread_a]
    assert after == answered
    assert [row for row in repo.outbox if row["thread_id"] == thread_a] == replies_a
    # B: stored and handed to a person.
    _, handed = repo.states[_thread_of(repo, OTHER_WA_ID)]
    assert handed.paused_at is not None
    assert handed.context[CTX_HANDOFF]["reason"] == AUTOMATION_ERROR_REASON


async def test_the_fallback_keeps_the_handoff_of_a_chat_already_with_a_person() -> None:
    repo = FaultyRepo()
    thread_id = repo.upsert_thread(
        tenant_id=TENANT, connection_id=CONNECTION, wa_id=WA_ID, inbound_at=NOW
    ).thread_id
    handoff = {"reason": "customer_request", "summary": {"node": "x"}, "at": NOW.isoformat()}
    repo.save_thread_state(
        thread_id=thread_id,
        tenant_id=TENANT,
        state=StoredThreadState(node_id=None, context={CTX_HANDOFF: handoff}, paused_at=NOW),
    )
    repo.fail_state_reads = 1  # the main path fails; the fallback runs

    assert (await _handler(repo)(_attempt(_event("Hola"), MAX_ATTEMPTS))).status == "processed"

    assert (CONNECTION, "wamid.offline-0") in repo.messages
    _, state = repo.states[thread_id]
    assert state.context[CTX_HANDOFF] == handoff and state.paused_at == NOW
    assert repo.outbox == []


async def test_a_media_proof_stored_by_the_fallback_still_moves_the_payment_to_review() -> None:
    repo = FaultyRepo()
    thread_id = repo.upsert_thread(
        tenant_id=TENANT, connection_id=CONNECTION, wa_id=WA_ID, inbound_at=NOW
    ).thread_id
    repo.save_thread_state(
        thread_id=thread_id,
        tenant_id=TENANT,
        state=StoredThreadState(
            node_id=None,
            context={CTX_PAYMENT_RECORD: {"choice": "method", "status": STATUS_AWAITING}},
        ),
    )
    repo.fail_state_reads = 1
    event = _event("x")
    event.value["messages"][0].update(type="image", image={"id": "media-1"})
    del event.value["messages"][0]["text"]

    assert (await _handler(repo)(_attempt(event, MAX_ATTEMPTS))).status == "processed"

    _, state = repo.states[thread_id]
    assert state.context[CTX_PAYMENT_RECORD]["status"] == "review"
    assert state.context[CTX_PAYMENT_RECORD]["review_message_id"] == "wamid.offline-0"
    assert state.paused_at is not None
    assert state.context[CTX_HANDOFF]["reason"] == AUTOMATION_ERROR_REASON
    assert repo.outbox == []
