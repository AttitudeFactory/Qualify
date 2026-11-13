"""The unified inbox read offline (m-25017843): argument checks, the cursor, the seam, and
the shape of the one statement. Postgres behaviour lives in `test_inbox_unified_db.py`."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qualify_api.inbox.awaiting import awaiting_reply_sql
from qualify_api.inbox.channels import UnknownChannel
from qualify_api.inbox.unified import (
    InboxCursor,
    InboxFilter,
    InboxPage,
    InvalidCursor,
    _count_sql,
    _list_sql,
    count_inbox,
    list_inbox,
)

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


class _FakeReader:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def list_page(
        self,
        tenant_id: UUID,
        *,
        filter: InboxFilter,
        channels: Sequence[str],
        cursor: InboxCursor | None,
        limit: int,
        now: datetime,
    ) -> InboxPage:
        self.calls.append(
            {"tenant": tenant_id, "filter": filter, "channels": tuple(channels), "cursor": cursor}
        )
        return InboxPage(rows=(), next_cursor=None)

    def count(self, tenant_id: UUID, *, filter: InboxFilter, channels: Sequence[str]) -> int:
        self.calls.append({"tenant": tenant_id, "filter": filter, "channels": tuple(channels)})
        return 7


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


def test_count_goes_through_the_reader() -> None:
    reader = _FakeReader()
    assert count_inbox(uuid4(), reader=reader) == 7


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
    rule = " ".join(awaiting_reply_sql("t").split())
    # The rule filters both branches of the page, and is not evaluated again per row.
    assert sql.count(rule) == 2 and "TRUE AS awaiting_reply" in sql
    assert "t.channel = ANY(:channels)" in sql
    assert "UNION ALL" in sql
    assert "FROM page t LEFT JOIN whatsapp_thread_state s" in sql  # no join back
    assert "LEFT JOIN LATERAL" in sql and "LEFT JOIN whatsapp_thread_state s" in sql
    assert sql.endswith("ORDER BY t.last_message_at DESC NULLS LAST, t.id DESC LIMIT :limit")
    assert "tenant_id" not in sql


def test_other_filters_compute_the_rule_only_for_the_page() -> None:
    sql = " ".join(_list_sql("todos", None).split())
    rule = " ".join(awaiting_reply_sql("t").split())
    assert sql.count(rule) == 1 and f"{rule} AS awaiting_reply FROM page t" in sql


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
    assert " ".join(awaiting_reply_sql("t").split()) in count
