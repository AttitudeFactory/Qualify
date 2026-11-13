"""The unified inbox read offline (m-25017843): argument checks, the cursor, the seam, and
the shape of the one statement. Postgres behaviour lives in `test_inbox_unified_db.py`."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.inbox.awaiting import awaiting_reply_sql, expired_unanswered_sql
from qualify_api.inbox.channels import UnknownChannel
from qualify_api.inbox.unified import (
    EXPIRED_UNANSWERED_WITHIN,
    INBOX_FILTERS,
    InboxCounts,
    InboxCursor,
    InboxFilter,
    InboxPage,
    InboxRow,
    InvalidCursor,
    _count_sql,
    _counts_sql,
    _filter_sql,
    _list_sql,
    count_expired_unanswered,
    count_inbox,
    inbox_counts,
    list_inbox,
)
from qualify_api.whatsapp.window import WINDOW

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


class _FakeReader:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.expired_since: list[datetime] = []

    def list_page(
        self,
        tenant_id: UUID,
        *,
        filter: InboxFilter,
        channels: Sequence[str],
        cursor: InboxCursor | None,
        limit: int,
        now: datetime,
        expired_since: datetime,
    ) -> InboxPage:
        self.calls.append(
            {"tenant": tenant_id, "filter": filter, "channels": tuple(channels), "cursor": cursor}
        )
        self.expired_since.append(expired_since)
        return InboxPage(rows=(), next_cursor=None)

    def count(
        self,
        tenant_id: UUID,
        *,
        filter: InboxFilter,
        channels: Sequence[str],
        now: datetime,
        expired_since: datetime,
    ) -> int:
        self.calls.append(
            {"tenant": tenant_id, "filter": filter, "channels": tuple(channels), "now": now}
        )
        self.expired_since.append(expired_since)
        return 7

    def counts(
        self, tenant_id: UUID, *, channels: Sequence[str], now: datetime, expired_since: datetime
    ) -> InboxCounts:
        self.calls.append({"tenant": tenant_id, "channels": tuple(channels), "now": now})
        self.expired_since.append(expired_since)
        return InboxCounts(
            by_channel={
                "dm": {f: 1 for f in INBOX_FILTERS},
                "whatsapp": {f: 2 for f in INBOX_FILTERS},
            }
        )


def test_defaults_read_por_responder_over_every_chat_channel() -> None:
    reader = _FakeReader()
    tenant = uuid4()
    list_inbox(tenant, reader=reader, now=NOW)
    assert reader.calls == [
        {
            "tenant": tenant,
            "filter": "por_responder",
            "channels": ("dm", "whatsapp"),
            "cursor": None,
        }
    ]


def test_a_channel_filter_narrows_and_an_unknown_one_is_refused() -> None:
    reader = _FakeReader()
    list_inbox(uuid4(), channel="whatsapp", filter="cerrados", reader=reader, now=NOW)
    assert reader.calls[0]["channels"] == ("whatsapp",)
    for bad in ("comment", "tiktok_dm"):
        with pytest.raises(UnknownChannel):
            list_inbox(uuid4(), channel=bad, reader=reader)
        with pytest.raises(UnknownChannel):
            count_inbox(uuid4(), channel=bad, reader=reader)


def test_unknown_filter_and_bad_limits_are_refused() -> None:
    reader = _FakeReader()
    with pytest.raises(ValueError):
        list_inbox(uuid4(), filter="leidas", reader=reader)  # type: ignore[arg-type]
    for limit in (0, 101):
        with pytest.raises(ValueError):
            list_inbox(uuid4(), limit=limit, reader=reader)
    assert reader.calls == []


def test_a_naive_now_is_refused() -> None:
    reader = _FakeReader()
    naive = NOW.replace(tzinfo=None)
    with pytest.raises(ValueError, match="timezone-aware"):
        list_inbox(uuid4(), now=naive, reader=reader)
    with pytest.raises(ValueError, match="timezone-aware"):
        count_inbox(uuid4(), now=naive, reader=reader)
    assert reader.calls == []


def test_count_goes_through_the_reader() -> None:
    reader = _FakeReader()
    assert count_inbox(uuid4(), reader=reader, now=NOW) == 7
    assert reader.calls[0]["now"] == NOW
    count_inbox(uuid4(), reader=reader)
    assert reader.calls[1]["now"].tzinfo is not None  # the wall clock, aware


@pytest.mark.parametrize("at", [NOW, None])
def test_the_cursor_round_trips_as_a_token(at: datetime | None) -> None:
    cursor = InboxCursor(last_message_at=at, thread_id=uuid4())
    token = cursor.encode()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", token)
    assert InboxCursor.decode(token) == cursor
    reader = _FakeReader()
    list_inbox(uuid4(), cursor=token, reader=reader, now=NOW)
    assert reader.calls[0]["cursor"] == cursor


@pytest.mark.parametrize("token", ["", "nope", "!!!", "MjAyNi0xMS0xM1QxMjowMDowMHxub3Bl"])
def test_a_foreign_cursor_is_refused(token: str) -> None:
    with pytest.raises(InvalidCursor):
        InboxCursor.decode(token)


def test_the_list_is_one_read_only_statement_with_the_shared_rule() -> None:
    sql = " ".join(_list_sql("por_responder", None).split())
    assert sql.startswith("WITH page AS MATERIALIZED (")
    for verb in ("INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE"):
        assert not re.search(rf"\b{verb}\b", sql.upper()), verb
    rule = " ".join(awaiting_reply_sql("t", now_param="now").split())
    # The rule filters both branches of the page, and is not evaluated again per row.
    assert sql.count(rule) == 2 and "TRUE AS awaiting_reply" in sql
    assert "t.channel = ANY(:channels)" in sql
    assert "UNION ALL" in sql
    assert "FROM page t LEFT JOIN whatsapp_thread_state s" in sql  # no join back
    assert "LEFT JOIN LATERAL" in sql and "LEFT JOIN whatsapp_thread_state s" in sql
    assert sql.endswith("ORDER BY t.last_message_at DESC NULLS LAST, t.id DESC LIMIT :limit")
    assert "tenant_id" not in sql
    assert "now()" not in sql  # the rule judges the bound `:now`, like the rows' window


def test_other_filters_compute_the_rule_only_for_the_page() -> None:
    sql = " ".join(_list_sql("todos", None).split())
    rule = " ".join(awaiting_reply_sql("t", now_param="now").split())
    expired = " ".join(expired_unanswered_sql("t", now_param="now").split())
    assert sql.count(rule) == 1 and f"{rule} AS awaiting_reply," in sql
    assert sql.count(expired) == 1
    assert f"{expired} AS window_expired_unanswered FROM page t" in sql


def test_a_filter_that_decides_a_verdict_does_not_compute_it_again() -> None:
    waiting = " ".join(_list_sql("por_responder", None).split())
    assert "TRUE AS awaiting_reply, FALSE AS window_expired_unanswered" in waiting
    expired = " ".join(_list_sql("ventana_vencida", None).split())
    assert "FALSE AS awaiting_reply, TRUE AS window_expired_unanswered" in expired
    assert expired.count("CAST(:expired_since AS timestamptz)") == 2  # both page branches


def test_the_new_filters_read_only_the_thread_and_correlated_subqueries() -> None:
    payment = " ".join(_filter_sql("pago_por_revisar").split())
    assert "t.channel = 'whatsapp' AND t.status = 'open'" in payment
    assert "ps.context->'_payment'->>'status' = 'review'" in payment
    expired = " ".join(_filter_sql("ventana_vencida").split())
    assert "t.channel IN ('dm')" in expired and "t.status = 'open'" in expired
    for f in INBOX_FILTERS:
        assert "tenant_id" not in _filter_sql(f)


def test_counts_are_one_statement_with_every_filter_verbatim() -> None:
    sql = _counts_sql()
    assert sql.count("UNION ALL") == len(INBOX_FILTERS) - 1
    assert sql.count("GROUP BY t.channel") == len(INBOX_FILTERS)
    for f in INBOX_FILTERS:
        # Each branch is `count_inbox`'s own WHERE, so both are planned alike.
        branch = f"SELECT '{f}' AS filter, t.channel, count(*) AS n FROM threads t"
        assert branch in " ".join(sql.split())
        assert f"t.channel = ANY(:channels) AND {_filter_sql(f)}" in sql
        assert _filter_sql(f) in _count_sql(f)
    for verb in ("INSERT", "UPDATE", "DELETE"):
        assert not re.search(rf"\b{verb}\b", sql.upper()), verb


def test_inbox_counts_sum_per_filter_and_channel() -> None:
    reader = _FakeReader()
    counts = inbox_counts(uuid4(), now=NOW, reader=reader)
    assert reader.calls[0]["channels"] == ("dm", "whatsapp")
    assert reader.expired_since == [NOW - EXPIRED_UNANSWERED_WITHIN - WINDOW]
    assert counts.count("por_responder") == counts.por_responder == 3
    assert counts.count("cerrados", "whatsapp") == 2
    assert (counts.expired_unanswered, counts.payment_review) == (3, 3)
    with pytest.raises(ValueError):
        counts.count("leidas")  # type: ignore[arg-type]
    with pytest.raises(UnknownChannel):
        counts.count("todos", "comment")


def test_the_expired_count_takes_its_period() -> None:
    reader = _FakeReader()
    assert count_expired_unanswered(uuid4(), now=NOW, reader=reader) == 7
    count_expired_unanswered(uuid4(), within=timedelta(days=2), now=NOW, reader=reader)
    assert [c["filter"] for c in reader.calls] == ["ventana_vencida"] * 2
    assert reader.expired_since == [
        NOW - EXPIRED_UNANSWERED_WITHIN - WINDOW,
        NOW - timedelta(days=2) - WINDOW,
    ]
    assert EXPIRED_UNANSWERED_WITHIN == timedelta(days=7)
    with pytest.raises(ValueError):
        count_expired_unanswered(uuid4(), within=timedelta(0), now=NOW, reader=reader)


def test_a_row_built_by_hand_needs_none_of_the_new_fields() -> None:
    row = InboxRow(
        thread_id=uuid4(),
        channel="whatsapp",
        connection_id=uuid4(),
        status="open",
        counterpart_name=None,
        counterpart_username=None,
        counterpart_avatar_url=None,
        counterpart_phone="573000000000",
        last_message_at=NOW,
        last_inbound_at=NOW,
        last_message_text="Hola",
        last_message_kind=None,
        last_message_direction="inbound",
        awaiting_reply=True,
        unread=None,
        window_open=True,
        window_closes_at=NOW + WINDOW,
        automation_paused=False,
        payment_status="review",
    )
    assert (row.assigned_agent_id, row.window_expired_unanswered, row.window_expired_at) == (
        None,
        False,
        None,
    )
    assert (row.payment_review, row.payment_awaiting, row.is_closed) == (True, False, False)


def test_filters_and_cursor_shape_the_page() -> None:
    assert "AND t.status = 'open'" in _list_sql("todos", None)
    assert "AND t.status = 'closed'" in _list_sql("cerrados", None)
    page = " ".join(_list_sql("todos", None).split())
    assert "t.last_message_at IS NOT NULL" in page and "t.last_message_at IS NULL" in page
    assert "ORDER BY t.last_message_at DESC, t.id DESC LIMIT :limit" in page
    assert "ORDER BY t.id DESC LIMIT :limit" in page
    dated = " ".join(_list_sql("todos", InboxCursor(NOW, uuid4())).split())
    assert "(t.last_message_at < :at OR (t.last_message_at = :at AND t.id < :id))" in dated
    assert "UNION ALL" in dated  # every undated chat still follows a dated cursor
    undated = " ".join(_list_sql("todos", InboxCursor(None, uuid4())).split())
    assert "UNION ALL" not in undated and ":at" not in undated
    assert "t.last_message_at IS NULL AND t.status = 'open' AND t.id < :id" in undated
    count = " ".join(_count_sql("por_responder").split())
    assert count.startswith("SELECT count(*) FROM threads t WHERE t.channel = ANY(:channels)")
    assert " ".join(awaiting_reply_sql("t", now_param="now").split()) in count
