"""m-25017846 (BU-B1) offline: the handler runs each inbound message through ONE
`repo.transaction()`, takes the conversation's lock first, and attributes the ad only
after the commit. The in-memory repository's `transaction()` rolls every table back on
an exception, as Postgres does (`test_whatsapp_menu_atomic_db.py` pins the real thing).
"""

from __future__ import annotations

import logging
from dataclasses import replace
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
from qualify_api.whatsapp.repository import MemoryWhatsAppInboxRepository
from qualify_api.whatsapp.resolve import PhoneResolution, PhoneResolutionOutcome

TENANT = UUID("77777777-7777-4777-8777-000025017846")
CONNECTION = UUID("88888888-8888-4888-8888-000025017846")
PHONE_ROW = UUID("99999999-9999-4999-8999-000025017846")
WA_ID = "584240000001"
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
