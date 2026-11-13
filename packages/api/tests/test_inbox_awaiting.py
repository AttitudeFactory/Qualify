"""The «Por responder» rule offline (m-25017843, decision (ii) of 2026-11-13).

`awaits_reply` is the executable specification of `awaiting_reply_sql`;
`test_inbox_awaiting_db.py` proves on Postgres that both agree on these same cases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qualify_api.inbox.awaiting import ThreadReplyFacts, awaiting_reply_sql, awaits_reply

T0 = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
LATER = T0 + timedelta(seconds=5)
EARLIER = T0 - timedelta(minutes=5)


def test_an_unanswered_inbound_counts() -> None:
    assert awaits_reply(ThreadReplyFacts(status="open", last_inbound_at=T0))


def test_answered_by_the_owner_does_not_count() -> None:
    facts = ThreadReplyFacts(
        status="open", last_inbound_at=T0, last_person_outbound_at=LATER, last_outbound_at=LATER
    )
    assert not awaits_reply(facts)


def test_answered_only_by_the_menu_does_not_count() -> None:
    facts = ThreadReplyFacts(status="open", last_inbound_at=T0, last_outbound_at=LATER)
    assert not awaits_reply(facts)


def test_a_menu_reply_still_queued_is_the_menu_answering() -> None:
    facts = ThreadReplyFacts(
        status="open", last_inbound_at=T0, automation_queued_since_inbound=True
    )
    assert not awaits_reply(facts)


def test_handed_to_a_person_counts_even_after_the_menus_message() -> None:
    # «Hablar con alguien»: the menu says it hands over (an outbound after the inbound).
    facts = ThreadReplyFacts(
        status="open", last_inbound_at=T0, last_outbound_at=LATER, handed_to_person=True
    )
    assert awaits_reply(facts)


def test_handed_to_a_person_and_then_answered_by_the_owner_does_not_count() -> None:
    facts = ThreadReplyFacts(
        status="open",
        last_inbound_at=T0,
        last_person_outbound_at=LATER,
        last_outbound_at=LATER,
        handed_to_person=True,
    )
    assert not awaits_reply(facts)


def test_owner_answered_and_the_customer_wrote_again_counts() -> None:
    facts = ThreadReplyFacts(
        status="open",
        last_inbound_at=T0,
        last_person_outbound_at=EARLIER,
        last_outbound_at=EARLIER,
    )
    assert awaits_reply(facts)


def test_a_failed_automatic_send_counts() -> None:
    facts = ThreadReplyFacts(
        status="open", last_inbound_at=T0, automation_failed_since_inbound=True
    )
    assert awaits_reply(facts)


def test_a_failed_automatic_send_after_the_owner_answered_does_not_count() -> None:
    facts = ThreadReplyFacts(
        status="open",
        last_inbound_at=T0,
        last_person_outbound_at=LATER,
        last_outbound_at=LATER,
        automation_failed_since_inbound=True,
    )
    assert not awaits_reply(facts)


@pytest.mark.parametrize(
    "facts",
    [
        ThreadReplyFacts(status="closed", last_inbound_at=T0),
        ThreadReplyFacts(status="closed", last_inbound_at=T0, handed_to_person=True),
        ThreadReplyFacts(status="closed", last_inbound_at=T0, automation_failed_since_inbound=True),
    ],
)
def test_a_closed_chat_never_counts(facts: ThreadReplyFacts) -> None:
    assert not awaits_reply(facts)


def test_a_chat_the_customer_never_wrote_in_does_not_count() -> None:
    facts = ThreadReplyFacts(
        status="open", last_inbound_at=None, last_outbound_at=T0, handed_to_person=True
    )
    assert not awaits_reply(facts)


def test_the_sql_reads_every_fact_the_rule_needs() -> None:
    sql = " ".join(awaiting_reply_sql("t").split())
    assert sql.startswith("( t.status = 'open'")
    assert "aw_ob.kind = 'automation'" in sql  # menu messages are not a person's reply
    assert "aw_s.automation_paused_at IS NOT NULL" in sql  # handed to a person
    assert "aw_x.status IN ('failed', 'dead')" in sql  # failed automatic send
    assert "aw_xm.delivery_status = 'failed'" in sql  # Meta reported it failed
    assert "aw_q.status IN ('pending', 'sending')" in sql  # menu still answering
    assert "deleted_at IS NULL" in sql
    # Read-only and no hand-written tenant filter: RLS scopes it.
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert verb not in sql.upper().split()
    assert "tenant_id" not in sql


@pytest.mark.parametrize("alias", ["", "t.x", "aw_t", "t; drop"])
def test_the_alias_is_a_plain_identifier(alias: str) -> None:
    with pytest.raises(ValueError):
        awaiting_reply_sql(alias)
