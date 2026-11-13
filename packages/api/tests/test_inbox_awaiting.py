"""The «Por responder» rule offline (m-25017843, decision (ii) of 2026-11-13).

`awaits_reply` is the executable specification of `awaiting_reply_sql`;
`test_inbox_unified_db.py` seeds these cases on Postgres and checks both agree."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qualify_api.inbox.awaiting import (
    AutomationSend,
    MessageFact,
    ThreadSnapshot,
    awaiting_reply_sql,
    awaits_reply,
    count_awaiting_sql,
)
from qualify_api.inbox.channels import UnknownChannel
from qualify_api.whatsapp.outbox import STALE_AFTER

T0 = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
LATER = T0 + timedelta(seconds=5)
EARLIER = T0 - timedelta(minutes=5)
NOW = T0 + timedelta(minutes=1)

IN = MessageFact("inbound", T0)
OWNER = MessageFact("outbound", LATER)
MENU = MessageFact("outbound", LATER, automatic=True)


def _open(*messages: MessageFact, **kwargs: object) -> ThreadSnapshot:
    return ThreadSnapshot(status="open", messages=messages, **kwargs)  # type: ignore[arg-type]


def test_an_unanswered_inbound_counts() -> None:
    assert awaits_reply(_open(IN), NOW)


def test_answered_by_the_owner_does_not_count() -> None:
    assert not awaits_reply(_open(IN, OWNER), NOW)


def test_answered_only_by_the_menu_does_not_count() -> None:
    assert not awaits_reply(_open(IN, MENU), NOW)


def test_a_fresh_queued_menu_reply_is_the_menu_answering() -> None:
    chat = _open(IN, automation_sends=(AutomationSend("pending", LATER),))
    assert not awaits_reply(chat, NOW)


def test_a_queued_menu_reply_older_than_stale_after_no_longer_hides_the_chat() -> None:
    chat = _open(IN, automation_sends=(AutomationSend("sending", LATER),))
    assert awaits_reply(chat, LATER + STALE_AFTER)
    assert not awaits_reply(chat, LATER + STALE_AFTER - timedelta(seconds=1))


def test_a_queued_or_failed_send_older_than_the_inbound_is_ignored() -> None:
    old = (AutomationSend("pending", EARLIER), AutomationSend("failed", EARLIER))
    assert awaits_reply(_open(IN, automation_sends=old[:1]), NOW)  # unanswered anyway
    assert not awaits_reply(_open(MessageFact("inbound", T0), MENU, automation_sends=old[1:]), NOW)


def test_handed_to_a_person_counts_even_after_the_menus_message() -> None:
    assert awaits_reply(_open(IN, MENU, handed_to_person=True), NOW)


def test_a_resumed_hand_off_is_the_menu_again() -> None:
    assert not awaits_reply(_open(IN, MENU, handed_to_person=False), NOW)


def test_handed_to_a_person_and_then_answered_by_the_owner_does_not_count() -> None:
    assert not awaits_reply(_open(IN, OWNER, handed_to_person=True), NOW)


def test_owner_answered_and_the_customer_wrote_again_counts() -> None:
    assert awaits_reply(_open(MessageFact("outbound", EARLIER), IN), NOW)


def test_a_failed_automatic_send_counts() -> None:
    assert awaits_reply(_open(IN, automation_sends=(AutomationSend("dead", LATER),)), NOW)
    delivered_failed = AutomationSend("sent", LATER, delivery_failed=True)
    assert awaits_reply(_open(IN, MENU, automation_sends=(delivered_failed,)), NOW)


def test_a_failed_automatic_send_after_the_owner_answered_does_not_count() -> None:
    chat = _open(IN, OWNER, automation_sends=(AutomationSend("failed", LATER),))
    assert not awaits_reply(chat, NOW)


def test_a_hidden_owner_reply_still_answers_the_chat() -> None:
    assert not awaits_reply(_open(IN, MessageFact("outbound", LATER, hidden=True)), NOW)


def test_a_hidden_customer_message_does_not_keep_the_chat_waiting() -> None:
    hidden_last = MessageFact("inbound", LATER + timedelta(seconds=1), hidden=True)
    assert not awaits_reply(_open(IN, OWNER, hidden_last), NOW)
    assert not awaits_reply(_open(MessageFact("inbound", T0, hidden=True)), NOW)


def test_outbound_first_and_empty_chats() -> None:
    assert not awaits_reply(_open(MessageFact("outbound", EARLIER)), NOW)
    assert awaits_reply(_open(MessageFact("outbound", EARLIER), IN), NOW)
    assert not awaits_reply(_open(), NOW)


@pytest.mark.parametrize(
    "chat",
    [
        ThreadSnapshot(status="closed", messages=(IN,)),
        ThreadSnapshot(status="closed", messages=(IN,), handed_to_person=True),
        ThreadSnapshot(
            status="closed", messages=(IN,), automation_sends=(AutomationSend("failed", LATER),)
        ),
    ],
)
def test_a_closed_chat_never_counts(chat: ThreadSnapshot) -> None:
    assert not awaits_reply(chat, NOW)


def test_the_sql_reads_every_fact_the_rule_needs() -> None:
    sql = " ".join(awaiting_reply_sql("t").split())
    assert sql.startswith("( t.status = 'open' AND t.last_inbound_at IS NOT NULL")
    assert "aw_ob.kind = 'automation'" in sql  # menu messages are not a person's reply
    assert "aw_m.direction = 'inbound' AND aw_m.deleted_at IS NULL" in sql  # hidden inbound
    assert "WHERE aw_m.thread_id = t.id )" in sql  # hidden outbound still counts
    assert "aw_s.automation_paused_at IS NOT NULL" in sql  # handed to a person
    assert "aw_x.status IN ('failed', 'dead')" in sql  # failed automatic send
    assert "aw_xm.delivery_status = 'failed'" in sql  # Meta reported it failed
    assert "aw_q.status IN ('pending', 'sending')" in sql  # menu still answering
    stale = int(STALE_AFTER.total_seconds())
    assert f"now() - CAST('{stale} seconds' AS interval)" in sql
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert verb not in sql.upper().split()
    assert "tenant_id" not in sql


def test_count_awaiting_sql_is_the_counter_drop_in() -> None:
    sql = count_awaiting_sql("whatsapp")
    assert sql.startswith("(SELECT count(*) FROM threads t WHERE t.channel = 'whatsapp' AND (")
    assert awaiting_reply_sql("t") in sql
    for bad in ("comment", "x' OR '1'='1"):
        with pytest.raises(UnknownChannel):
            count_awaiting_sql(bad)


@pytest.mark.parametrize("alias", ["", "t.x", "aw_t", "t; drop"])
def test_the_alias_is_a_plain_identifier(alias: str) -> None:
    with pytest.raises(ValueError):
        awaiting_reply_sql(alias)
