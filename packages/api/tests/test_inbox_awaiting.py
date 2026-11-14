"""The «Por responder» rule offline (m-25017843, decision (ii) of 2026-11-13; Instagram's
reply-window bound: m-25017859, «Ventana + cerrar chat», 2026-11-13).

`awaits_reply` is the executable specification of `awaiting_reply_sql`;
`test_inbox_unified_db.py` seeds these cases on Postgres and checks both agree."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qualify_api.inbox.awaiting import (
    WINDOW_BOUND_CHANNELS,
    AutomationSend,
    MessageFact,
    ThreadSnapshot,
    awaiting_reply_sql,
    awaits_reply,
    count_awaiting_sql,
    expired_unanswered,
    expired_unanswered_sql,
)
from qualify_api.inbox.channels import UnknownChannel
from qualify_api.whatsapp.outbox import STALE_AFTER
from qualify_api.whatsapp.window import WINDOW

T0 = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
LATER = T0 + timedelta(seconds=5)
EARLIER = T0 - timedelta(minutes=5)
NOW = T0 + timedelta(minutes=1)

IN = MessageFact("inbound", T0)
OWNER = MessageFact("outbound", LATER)
MENU = MessageFact("outbound", LATER, automatic=True)


_SEEDED: object = object()


def _open(
    *messages: MessageFact,
    channel: str = "whatsapp",
    last_inbound_at: datetime | None | object = _SEEDED,
    **kwargs: object,
) -> ThreadSnapshot:
    """An open chat. Unless given, the seeded `threads.last_inbound_at` is what the
    webhook ingestion leaves for these messages: the newest inbound's instant."""
    if last_inbound_at is _SEEDED:
        last_inbound_at = max((m.at for m in messages if m.direction == "inbound"), default=None)
    return ThreadSnapshot(
        status="open",
        channel=channel,
        last_inbound_at=last_inbound_at,  # type: ignore[arg-type]
        messages=messages,
        **kwargs,  # type: ignore[arg-type]
    )


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
        ThreadSnapshot(status="closed", channel="dm", last_inbound_at=T0, messages=(IN,)),
        ThreadSnapshot(status="closed", channel="whatsapp", last_inbound_at=T0, messages=(IN,)),
        ThreadSnapshot(
            status="closed",
            channel="whatsapp",
            last_inbound_at=T0,
            messages=(IN,),
            handed_to_person=True,
        ),
        ThreadSnapshot(
            status="closed",
            channel="whatsapp",
            last_inbound_at=T0,
            messages=(IN,),
            automation_sends=(AutomationSend("failed", LATER),),
        ),
    ],
)
def test_a_closed_chat_never_counts(chat: ThreadSnapshot) -> None:
    assert not awaits_reply(chat, NOW)


def test_the_sql_reads_every_fact_the_rule_needs() -> None:
    sql = " ".join(awaiting_reply_sql("t").split())
    assert sql.startswith("( t.status = 'open' AND t.last_inbound_at IS NOT NULL")
    window = int(WINDOW.total_seconds())
    # Instagram's window, on the `threads` row, before any message is read.
    bound = (
        f"AND (t.channel NOT IN ('dm') OR t.last_inbound_at > now() - "
        f"CAST('{window} seconds' AS interval)) AND EXISTS ("
    )
    assert bound in sql
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


def test_now_can_be_a_bound_parameter_for_both_the_window_and_the_stuck_queue() -> None:
    sql = awaiting_reply_sql("t", now_param="now")
    assert "now()" not in sql
    assert sql.count("CAST(:now AS timestamptz) - CAST(") == 2
    assert "CAST(:now AS timestamptz)" in count_awaiting_sql("dm", now_param="now")
    for bad in ("", "now; drop", ":now"):
        with pytest.raises(ValueError):
            awaiting_reply_sql("t", now_param=bad)


def test_count_awaiting_sql_is_the_counter_drop_in() -> None:
    sql = count_awaiting_sql("whatsapp")
    assert sql.startswith("(SELECT count(*) FROM threads t WHERE t.channel = 'whatsapp' AND (")
    assert awaiting_reply_sql("t") in sql
    for bad in ("comment", "x' OR '1'='1"):
        with pytest.raises(UnknownChannel):
            count_awaiting_sql(bad)


# --- Instagram's reply window (founder, 2026-11-13, «Ventana + cerrar chat») -----------


def test_only_instagram_is_bounded_by_its_window() -> None:
    """WhatsApp can still send an approved message after the window and has «Cerrar
    chat», so it is not bounded; Instagram can send nothing once the window closes."""
    assert WINDOW_BOUND_CHANNELS == frozenset({"dm"})


def test_an_instagram_chat_counts_while_its_window_is_open() -> None:
    chat = _open(IN, channel="dm")
    assert awaits_reply(chat, NOW)
    assert awaits_reply(chat, T0 + WINDOW - timedelta(microseconds=1))


def test_an_instagram_chat_stops_counting_once_its_window_has_closed() -> None:
    chat = _open(IN, channel="dm")
    assert not awaits_reply(chat, T0 + WINDOW)  # closed AT the boundary (`window_state`)
    assert not awaits_reply(chat, T0 + timedelta(days=30))


def test_a_new_inbound_after_a_closed_window_reopens_it_and_counts_again() -> None:
    again = MessageFact("inbound", T0 + timedelta(days=3))
    chat = _open(IN, OWNER, again, channel="dm")
    assert awaits_reply(chat, again.at + timedelta(hours=1))
    assert not awaits_reply(chat, again.at + WINDOW)


def test_the_window_rests_on_last_inbound_at_hidden_messages_included() -> None:
    """A hidden newest inbound does not make the chat wait, but it did open Meta's window:
    an older visible unanswered message still counts while that window is open."""
    hidden = MessageFact("inbound", T0 + timedelta(days=2), hidden=True)
    chat = _open(IN, hidden, channel="dm")
    assert awaits_reply(chat, hidden.at + timedelta(hours=1))
    explicit = _open(IN, channel="dm", last_inbound_at=hidden.at)
    assert awaits_reply(explicit, hidden.at + timedelta(hours=1))
    assert not awaits_reply(explicit, hidden.at + WINDOW)


def test_the_twin_reads_the_column_not_the_messages() -> None:
    """Ingestion does not always move `threads.last_inbound_at` with a message: an unsent
    one is left out of it (`_RECOMPUTE_THREAD`), one the re-sync stored without
    `posted_at` is not bumped. The twin reads the column as stored, like the SQL."""
    two_days_ago = MessageFact("inbound", NOW - timedelta(days=2))
    unsent = MessageFact("inbound", NOW - timedelta(minutes=5), hidden=True)
    assert not awaits_reply(
        _open(two_days_ago, unsent, channel="dm", last_inbound_at=two_days_ago.at), NOW
    )
    # The column was never set (only an un-dated re-synced inbound): no channel counts it.
    for channel in ("dm", "whatsapp"):
        assert not awaits_reply(_open(IN, channel=channel, last_inbound_at=None), NOW)


def test_whatsapp_keeps_counting_after_its_window() -> None:
    assert awaits_reply(_open(IN), T0 + timedelta(days=30))


@pytest.mark.parametrize("alias", ["", "t.x", "aw_t", "t; drop"])
def test_the_alias_is_a_plain_identifier(alias: str) -> None:
    with pytest.raises(ValueError):
        awaiting_reply_sql(alias)


# --------------------------------------------------------------------------------------
# Expired without an answer (m-25017859)
# --------------------------------------------------------------------------------------


def test_an_instagram_chat_whose_window_closed_unanswered_is_expired_not_waiting() -> None:
    chat = _open(IN, channel="dm")
    closed = T0 + WINDOW
    assert expired_unanswered(chat, closed) and not awaits_reply(chat, closed)
    just_before = closed - timedelta(microseconds=1)
    assert not expired_unanswered(chat, just_before) and awaits_reply(chat, just_before)


def test_an_answered_closed_or_whatsapp_chat_is_never_expired() -> None:
    late = T0 + timedelta(days=3)
    assert not expired_unanswered(_open(IN, OWNER, channel="dm"), late)
    closed = ThreadSnapshot(status="closed", channel="dm", last_inbound_at=T0, messages=(IN,))
    assert not expired_unanswered(closed, late)
    assert not expired_unanswered(_open(IN), late)  # WhatsApp: no window bound
    assert not expired_unanswered(
        _open(MessageFact("inbound", T0, hidden=True), channel="dm"), late
    )
    assert not expired_unanswered(_open(channel="dm", last_inbound_at=None), late)


def test_a_later_inbound_reopens_the_window_and_clears_expired() -> None:
    again = T0 + timedelta(days=2)
    chat = _open(IN, OWNER, MessageFact("inbound", again), channel="dm")
    assert awaits_reply(chat, again + timedelta(hours=1))
    assert not expired_unanswered(chat, again + timedelta(hours=1))
    assert expired_unanswered(chat, again + WINDOW)


def test_expired_sql_is_false_off_the_bound_channels_and_shares_the_facts() -> None:
    sql = " ".join(expired_unanswered_sql("t", now_param="now").split())
    assert "t.channel IN ('dm')" in sql
    assert "t.last_inbound_at <= CAST(:now AS timestamptz) - CAST('86400 seconds'" in sql
    assert "aw_f.last_in > COALESCE(aw_f.last_person_out" in sql
    assert "now()" in " ".join(expired_unanswered_sql("t").split())
    with pytest.raises(ValueError):
        expired_unanswered_sql("aw_t")
