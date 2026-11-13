"""`qualify_api.attention` offline (m-24842990): the store seam, the total, and the SQL's
shape — read-only, and each channel defined as the list it opens filters it."""

from __future__ import annotations

from uuid import UUID, uuid4

from qualify_api.attention import PendingCounts, pending_counts
from qualify_api.attention.counts import _COUNTS_SQL


class _FakeStore:
    def __init__(self, counts: PendingCounts) -> None:
        self.counts = counts
        self.seen: list[UUID] = []

    def read(self, tenant_id: UUID) -> PendingCounts:
        self.seen.append(tenant_id)
        return self.counts


def test_pending_counts_reads_through_the_store_for_the_tenant() -> None:
    tenant = uuid4()
    store = _FakeStore(PendingCounts(messages=2, buyers=1, comments=3, whatsapp=4))
    counts = pending_counts(tenant, store)
    assert store.seen == [tenant]
    assert counts.total == 10


def test_an_empty_tenant_is_all_zero() -> None:
    assert PendingCounts().total == 0


def test_the_query_only_reads() -> None:
    import re

    sql = _COUNTS_SQL.upper()
    assert sql.lstrip().startswith("SELECT")
    for verb in ("INSERT", "UPDATE", "DELETE", "MERGE", "TRUNCATE"):
        assert not re.search(rf"\b{verb}\b", sql), verb


def test_each_channel_uses_its_rule() -> None:
    from qualify_api.inbox.awaiting import awaiting_reply_sql

    sql = " ".join(_COUNTS_SQL.split())
    # Mensajes and WhatsApp = the ONE «Por responder» rule the unified inbox lists by
    # (m-25017843): the very same fragment, once per channel.
    rule = " ".join(awaiting_reply_sql("t").split())
    assert f"t.channel = 'dm' AND {rule}" in sql
    assert f"t.channel = 'whatsapp' AND {rule}" in sql
    # Reading a chat no longer clears it: only a reply does.
    assert "last_read_at" not in sql
    # Quieren comprar = open followups whose comment is still visible.
    assert "f.status = 'open'" in sql and "JOIN messages m ON m.id = f.origin_message_id" in sql
    # Comentarios = the replies waiting for approval.
    assert "d.status = 'proposed'" in sql
    # No hand-written tenant filter: RLS through tenant_session scopes every table.
    assert "tenant_id" not in sql
