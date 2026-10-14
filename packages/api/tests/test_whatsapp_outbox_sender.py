"""WA-08 — `OutboxSender` over the in-memory repository and a scripted fake client.

No DB, no network. What is pinned: every outcome of the table in `outbox.py`'s docstring
(sent / deferred / retry / failed / dead), the window and pacing policies, Meta's `4^X`
backoff, the `MAX_ATTEMPTS` ceiling, auth degradation, stale-lock reclaim and the
outbound `messages` row that `mark_sent` writes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.whatsapp.client import (
    ButtonSpec,
    WhatsAppApiError,
    build_buttons_body,
    build_template_body,
    build_text_body,
)
from qualify_api.whatsapp.optins import MemoryOptInRepository, OptInService
from qualify_api.whatsapp.outbox import (
    ERROR_AUTH,
    ERROR_OPTED_OUT,
    ERROR_STALE_EXHAUSTED,
    ERROR_TRANSPORT,
    ERROR_WINDOW_CLOSED,
    MAX_ATTEMPTS,
    PACING,
    STALE_AFTER,
    MemoryOutboxRepository,
    OutboxSender,
    backoff,
    payload_text,
)

TENANT = UUID("a0000000-0000-4000-8000-0000000000a8")
CONNECTION = UUID("b0000000-0000-4000-8000-0000000000b8")
THREAD = UUID("c0000000-0000-4000-8000-0000000000c8")
USER = UUID("d0000000-0000-4000-8000-0000000000d8")
T0 = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
TO = "+573001234567"
WAMID = "wamid.HBgLNTczMDAxMjM0NTY3FQIAERgSOUFERUJGOEZBNEMzNDI5RTQzAA=="


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class FakeClient:
    """Answers each `send_payload` with the next scripted outcome: a wamid, or an
    exception to raise. Runs out → keeps returning fresh wamids."""

    def __init__(self, *outcomes: str | Exception) -> None:
        self._outcomes = list(outcomes)
        self.payloads: list[dict[str, Any]] = []

    async def send_payload(self, payload: dict[str, Any]) -> str:
        self.payloads.append(payload)
        outcome = self._outcomes.pop(0) if self._outcomes else f"wamid.{uuid4().hex}"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Rig:
    def __init__(self, client: FakeClient | None = None) -> None:
        self.clock = Clock()
        self.repo = MemoryOutboxRepository(clock=self.clock)
        self.client = client or FakeClient(WAMID)
        self.factory_calls: list[UUID] = []
        self.degraded: list[tuple[UUID, UUID]] = []
        # TO holds an active opt-in, so campaign sends to it go out unless a test revokes.
        self.opt_ins = OptInService(MemoryOptInRepository(), clock=self.clock)
        self.opt_ins.record(
            tenant_id=TENANT, phone=TO, source="manual", consent_text="Acepto mensajes"
        )
        self.sender = OutboxSender(
            self.repo,
            self._factory,
            self._degrade,
            worker_id="test:1",
            opt_ins=self.opt_ins,
            clock=self.clock,
        )
        # The window is OPEN by default: the user wrote one hour ago.
        self.repo.threads[THREAD] = T0 - timedelta(hours=1)

    async def _factory(self, *, tenant_id: UUID, connection_id: UUID) -> FakeClient:
        self.factory_calls.append(connection_id)
        return self.client

    def _degrade(self, *, tenant_id: UUID, connection_id: UUID) -> None:
        self.degraded.append((tenant_id, connection_id))

    def enqueue(
        self,
        kind: str = "reply",
        payload: dict[str, Any] | None = None,
        *,
        thread_id: UUID | None = THREAD,
    ) -> UUID:
        return self.repo.enqueue(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            thread_id=thread_id,
            kind=kind,
            payload=payload or build_text_body(TO, "hola", False),
            created_by_user_id=USER,
        )

    async def tick(self):
        return await self.sender.run_once(TENANT)


def _api_error(status: int, code: int | None = None, **kw: Any) -> WhatsAppApiError:
    return WhatsAppApiError(f"HTTP {status}", status=status, code=code, **kw)


# --- happy path --------------------------------------------------------------------------


async def test_a_reply_in_an_open_window_is_sent_and_becomes_an_outbound_message() -> None:
    rig = Rig()
    item_id = rig.enqueue()
    report = await rig.tick()

    assert (report.claimed, report.sent, report.settled) == (1, 1, 1)
    row = rig.repo.rows[item_id]
    assert (row.status, row.wamid, row.sent_at, row.error_code) == ("sent", WAMID, T0, None)
    assert row.locked_by is None and row.locked_at is None
    assert rig.client.payloads == [build_text_body(TO, "hola", False)]
    (message,) = rig.repo.messages
    assert message.thread_id == THREAD and message.connection_id == CONNECTION
    assert message.wamid == WAMID and message.text == "hola"
    assert message.posted_at == T0 and message.delivery_status == "sent"
    assert rig.repo.thread_last_message_at[THREAD] == T0


async def test_an_interactive_body_records_its_body_text() -> None:
    rig = Rig()
    rig.enqueue(
        payload=build_buttons_body(TO, "Que deseas?", [ButtonSpec("m", "Menu")], None, None)
    )
    await rig.tick()
    assert rig.repo.messages[0].text == "Que deseas?"


async def test_one_client_is_built_per_connection_per_batch() -> None:
    rig = Rig()
    rig.enqueue(payload=build_text_body(TO, "1", False))
    rig.enqueue(payload=build_text_body("+573009999999", "2", False))
    await rig.tick()
    assert rig.factory_calls == [CONNECTION]


async def test_an_empty_queue_is_a_quiet_report() -> None:
    rig = Rig()
    report = await rig.tick()
    assert report.claimed == 0 and report.settled == 0 and report.errors == []


# --- the 24 h window ---------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["reply", "automation"])
async def test_free_form_outside_the_window_fails_without_a_request(kind: str) -> None:
    rig = Rig()
    rig.repo.threads[THREAD] = T0 - timedelta(hours=25)
    item_id = rig.enqueue(kind)
    report = await rig.tick()
    assert report.failed == 1
    assert (rig.repo.rows[item_id].status, rig.repo.rows[item_id].error_code) == (
        "failed",
        ERROR_WINDOW_CLOSED,
    )
    assert rig.client.payloads == [] and rig.repo.messages == []


async def test_a_campaign_send_goes_out_with_no_thread_and_no_window() -> None:
    rig = Rig()
    template = build_template_body(TO, "order_ready", "es", None)
    item_id = rig.enqueue("campaign_send", template, thread_id=None)
    report = await rig.tick()
    assert report.sent == 1 and rig.repo.rows[item_id].status == "sent"
    assert rig.client.payloads == [template]
    assert rig.repo.messages == []  # no thread yet: nothing to attach the message to


async def test_a_stop_after_the_campaign_queued_the_row_stops_the_send() -> None:
    """The gap WA-18 left open: the campaign checked the opt-in when it ENQUEUED the row;
    the person said STOP while it waited. The sender re-reads it and never sends."""
    rig = Rig()
    template = build_template_body(TO, "promo_octubre", "es", None)
    item_id = rig.enqueue("campaign_send", template, thread_id=None)
    rig.opt_ins.revoke(tenant_id=TENANT, phone=TO, reason="stop_keyword")

    report = await rig.tick()

    assert (report.failed, report.sent) == (1, 0)
    row = rig.repo.rows[item_id]
    assert (row.status, row.error_code) == ("failed", ERROR_OPTED_OUT)
    assert rig.client.payloads == []
    assert rig.factory_calls == []  # not even a client was built for it


async def test_a_campaign_send_to_a_phone_with_no_opt_in_is_not_sent() -> None:
    rig = Rig()
    stranger = "+573009999999"
    item_id = rig.enqueue(
        "campaign_send", build_template_body(stranger, "promo", "es", None), thread_id=None
    )
    await rig.tick()
    assert rig.repo.rows[item_id].error_code == ERROR_OPTED_OUT
    assert rig.client.payloads == []


async def test_a_digits_only_campaign_recipient_is_matched_as_e164() -> None:
    rig = Rig()
    digits = TO.removeprefix("+")
    item_id = rig.enqueue(
        "campaign_send", build_template_body(digits, "promo", "es", None), thread_id=None
    )
    await rig.tick()
    assert rig.repo.rows[item_id].status == "sent"


async def test_replies_do_not_need_an_opt_in() -> None:
    """Free-form kinds answer inside the person's own window; the opt-in is a campaign
    rule. A revoked opt-in must not silence a person's reply to a STOP-sender's question."""
    rig = Rig()
    rig.opt_ins.revoke(tenant_id=TENANT, phone=TO, reason="stop_keyword")
    item_id = rig.enqueue()
    await rig.tick()
    assert rig.repo.rows[item_id].status == "sent"


async def test_an_opt_in_read_failure_retries_and_never_sends_unchecked() -> None:
    class BrokenOptIns:
        def is_opted_in(self, *, tenant_id: UUID, phone: str) -> bool:
            raise RuntimeError("db down")

    rig = Rig()
    rig.sender = OutboxSender(
        rig.repo,
        rig._factory,
        rig._degrade,
        worker_id="test:1",
        opt_ins=BrokenOptIns(),
        clock=rig.clock,
    )
    item_id = rig.enqueue(
        "campaign_send", build_template_body(TO, "promo", "es", None), thread_id=None
    )
    report = await rig.tick()
    assert report.retried == 1
    assert rig.repo.rows[item_id].status == "pending"
    assert rig.client.payloads == []


async def test_a_meta_window_refusal_is_terminal_not_a_retry() -> None:
    rig = Rig(FakeClient(_api_error(400, 131047)))
    item_id = rig.enqueue()
    report = await rig.tick()
    assert report.failed == 1
    assert (rig.repo.rows[item_id].status, rig.repo.rows[item_id].error_code) == (
        "failed",
        "131047",
    )


# --- pacing: 1 message / 6 s to the same recipient -------------------------------------


async def test_a_second_message_to_the_same_recipient_is_deferred_not_failed() -> None:
    rig = Rig(FakeClient(WAMID, "wamid.second"))
    first = rig.enqueue(payload=build_text_body(TO, "1", False))
    rig.clock.advance(timedelta(milliseconds=1))  # distinct created_at, as real rows have
    second = rig.enqueue(payload=build_text_body("573001234567", "2", False))  # same phone
    rig.clock.now = T0 + PACING  # both are due; the sender runs them in creation order
    report = await rig.tick()

    assert (report.sent, report.deferred) == (1, 1)
    # Creation order decides: the older row goes out, the newer one waits for the pair gap.
    assert [rig.repo.rows[i].status for i in (first, second)] == ["sent", "pending"]
    assert rig.client.payloads == [build_text_body(TO, "1", False)]
    sent_at = rig.repo.rows[first].sent_at
    assert sent_at == T0 + PACING
    deferred = rig.repo.rows[second]
    assert (deferred.status, deferred.attempts, deferred.error_code) == ("pending", 0, None)
    assert deferred.next_attempt_at == sent_at + PACING

    rig.clock.advance(PACING - timedelta(seconds=1))
    assert (await rig.tick()).claimed == 0  # not due yet
    rig.clock.advance(timedelta(seconds=1))
    report = await rig.tick()
    assert report.sent == 1 and rig.repo.rows[second].wamid == "wamid.second"


async def test_different_recipients_are_not_paced_against_each_other() -> None:
    rig = Rig()
    rig.enqueue(payload=build_text_body(TO, "1", False))
    rig.enqueue(payload=build_text_body("+573009999999", "2", False))
    report = await rig.tick()
    assert (report.sent, report.deferred) == (2, 0)


# --- errors ------------------------------------------------------------------------------


async def test_an_auth_error_degrades_the_connection_and_kills_the_batch_for_it() -> None:
    rig = Rig(FakeClient(_api_error(401, 190)))
    first = rig.enqueue(payload=build_text_body(TO, "1", False))
    second = rig.enqueue(payload=build_text_body("+573009999999", "2", False))
    report = await rig.tick()

    assert report.dead == 2 and report.sent == 0
    assert rig.degraded == [(TENANT, CONNECTION)]  # once, not per row
    assert len(rig.client.payloads) == 1  # the second row never hit Meta
    for item_id in (first, second):
        assert (rig.repo.rows[item_id].status, rig.repo.rows[item_id].error_code) == (
            "dead",
            ERROR_AUTH,
        )


async def test_code_190_without_a_401_is_still_an_auth_error() -> None:
    rig = Rig(FakeClient(_api_error(400, 190)))
    item_id = rig.enqueue()
    await rig.tick()
    assert rig.repo.rows[item_id].status == "dead" and rig.degraded


async def test_a_transport_failure_retries_with_metas_backoff_and_counts_the_attempt() -> None:
    rig = Rig(FakeClient(WhatsAppApiError("timeout", is_transport=True)))
    item_id = rig.enqueue()
    report = await rig.tick()
    assert report.retried == 1
    row = rig.repo.rows[item_id]
    assert (row.status, row.attempts, row.error_code) == ("pending", 1, ERROR_TRANSPORT)
    assert row.next_attempt_at == T0 + backoff(1) == T0 + timedelta(seconds=4)


@pytest.mark.parametrize(
    ("status", "code"),
    [(500, None), (503, 2), (429, None), (400, 130429), (400, 131056), (400, 4)],
)
async def test_throttling_and_server_errors_retry(status: int, code: int | None) -> None:
    rig = Rig(FakeClient(_api_error(status, code)))
    item_id = rig.enqueue()
    report = await rig.tick()
    assert report.retried == 1 and rig.repo.rows[item_id].status == "pending"


@pytest.mark.parametrize(
    ("status", "code", "expected"), [(400, 100, "100"), (404, None, "http_404")]
)
async def test_other_client_errors_fail_terminally_with_the_code(
    status: int, code: int | None, expected: str
) -> None:
    rig = Rig(FakeClient(_api_error(status, code)))
    item_id = rig.enqueue()
    report = await rig.tick()
    assert report.failed == 1
    assert (rig.repo.rows[item_id].status, rig.repo.rows[item_id].error_code) == (
        "failed",
        expected,
    )


async def test_the_fifth_failed_attempt_is_dead_and_the_backoff_grew_4x_each_time() -> None:
    rig = Rig(FakeClient(*[_api_error(500)] * MAX_ATTEMPTS))
    item_id = rig.enqueue()
    delays: list[timedelta] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        report = await rig.tick()
        row = rig.repo.rows[item_id]
        assert row.attempts == attempt
        if attempt < MAX_ATTEMPTS:
            assert report.retried == 1 and row.status == "pending"
            delays.append(row.next_attempt_at - rig.clock.now)
            rig.clock.now = row.next_attempt_at
        else:
            assert report.dead == 1 and (row.status, row.error_code) == ("dead", "http_500")
    assert delays == [timedelta(seconds=4**n) for n in range(1, MAX_ATTEMPTS)]
    assert len(rig.client.payloads) == MAX_ATTEMPTS


async def test_an_unexpected_exception_is_a_counted_retry_and_reported() -> None:
    rig = Rig(FakeClient(RuntimeError("boom")))
    item_id = rig.enqueue()
    report = await rig.tick()
    assert report.retried == 1 and report.errors == [f"{item_id}:RuntimeError"]
    row = rig.repo.rows[item_id]
    assert (row.status, row.attempts, row.error_code) == ("pending", 1, "RuntimeError")


# --- claim semantics ---------------------------------------------------------------------


async def test_a_stale_lock_is_reclaimed_and_counts_an_attempt() -> None:
    rig = Rig()
    item_id = rig.enqueue()
    row = rig.repo.rows[item_id]
    row.status, row.locked_by, row.locked_at = "sending", "dead-worker:9", T0 - STALE_AFTER * 2
    report = await rig.tick()
    assert report.sent == 1 and row.status == "sent" and row.attempts == 1


async def test_a_stale_lock_with_no_attempts_left_is_settled_dead_not_resent() -> None:
    rig = Rig()
    item_id = rig.enqueue()
    row = rig.repo.rows[item_id]
    row.status, row.locked_at, row.attempts = "sending", T0 - STALE_AFTER * 2, MAX_ATTEMPTS
    report = await rig.tick()
    assert report.claimed == 0
    assert (row.status, row.error_code) == ("dead", ERROR_STALE_EXHAUSTED)
    assert rig.client.payloads == []


async def test_a_fresh_lock_held_by_another_worker_is_left_alone() -> None:
    rig = Rig()
    item_id = rig.enqueue()
    row = rig.repo.rows[item_id]
    row.status, row.locked_by, row.locked_at = "sending", "other:2", T0 - timedelta(seconds=30)
    assert (await rig.tick()).claimed == 0 and row.status == "sending"


async def test_another_tenants_rows_are_never_claimed() -> None:
    rig = Rig()
    rig.repo.enqueue(
        tenant_id=uuid4(),
        connection_id=CONNECTION,
        thread_id=THREAD,
        kind="reply",
        payload=build_text_body(TO, "ajeno", False),
        created_by_user_id=None,
    )
    assert (await rig.tick()).claimed == 0


async def test_the_batch_limit_is_respected_in_creation_order() -> None:
    rig = Rig()
    ids: list[UUID] = []
    for n in range(3):
        ids.append(rig.enqueue(payload=build_text_body(f"+5730000000{n:02d}", "x", False)))
        rig.clock.advance(timedelta(milliseconds=1))  # distinct created_at, as real rows have
    report = await rig.sender.run_once(TENANT, limit=2)
    assert report.claimed == 2
    assert [rig.repo.rows[i].status for i in ids] == ["sent", "sent", "pending"]


# --- enqueue validation -----------------------------------------------------------------


def test_enqueue_refuses_what_the_sender_could_not_act_on() -> None:
    repo = MemoryOutboxRepository()
    text = build_text_body(TO, "hola", False)
    with pytest.raises(ValueError, match="kind"):
        repo.enqueue(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            thread_id=THREAD,
            kind="broadcast",
            payload=text,
            created_by_user_id=None,
        )
    with pytest.raises(ValueError, match="thread"):
        repo.enqueue(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            thread_id=None,
            kind="reply",
            payload=text,
            created_by_user_id=None,
        )
    with pytest.raises(ValueError, match="'to'"):
        repo.enqueue(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            thread_id=THREAD,
            kind="reply",
            payload={"type": "text"},
            created_by_user_id=None,
        )
    with pytest.raises(ValueError, match="non-empty"):
        repo.enqueue(
            tenant_id=TENANT,
            connection_id=CONNECTION,
            thread_id=THREAD,
            kind="reply",
            payload={},
            created_by_user_id=None,
        )
    assert repo.rows == {}


# --- payload_text ------------------------------------------------------------------------


def test_payload_text_reads_text_and_interactive_bodies_only() -> None:
    assert payload_text(build_text_body(TO, "hola", False)) == "hola"
    assert (
        payload_text(build_buttons_body(TO, "Elige", [ButtonSpec("a", "A")], None, None)) == "Elige"
    )
    assert payload_text(build_template_body(TO, "t", "es", None)) is None
    assert payload_text({"type": "text", "text": {}}) is None
