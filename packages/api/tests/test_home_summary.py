"""`qualify_api.home.summary` offline (m-24842962): the row mapping and the session door."""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from qualify_creative.adapters.byteplus_ark import DRAFT_TTL_SECONDS

from qualify_api.home import WEEK, HomeCounts, read_home_counts
from qualify_api.home.summary import EXPIRING_SOON, HOME_COUNTS_SQL, counts_from_row

TENANT = UUID("a0000000-0000-4000-8000-0000000000e1")


def _row(**over: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "people_waiting": 1,
        "drafts_to_approve": 2,
        "comments_unanswered": 3,
        "messages_week_dm": 4,
        "messages_week_whatsapp": 5,
        "comments_week": 6,
        "mentions_week": 7,
        "instagram_connected": True,
        "has_publication": False,
        "videos_expiring_soon": 8,
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_counts_from_row_maps_every_field() -> None:
    counts = counts_from_row(_row())
    assert counts == HomeCounts(1, 2, 3, 4, 5, 6, 7, True, False, videos_expiring_soon=8)
    assert counts.messages_week == 9


def test_null_counts_read_as_zero() -> None:
    counts = counts_from_row(_row(people_waiting=None, mentions_week=None))
    assert counts.people_waiting == 0 and counts.mentions_week == 0


def test_read_goes_through_the_tenant_session_with_a_week_window() -> None:
    seen: dict[str, object] = {}

    class _Session:
        def execute(self, statement, params):
            seen["sql"] = statement
            seen["params"] = params
            return SimpleNamespace(one=lambda: _row())

    @contextmanager
    def factory(tenant_id: UUID):
        seen["tenant"] = tenant_id
        yield _Session()

    now = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    counts = read_home_counts(TENANT, now=now, session_factory=factory)
    assert seen["tenant"] == TENANT
    assert seen["sql"] is HOME_COUNTS_SQL
    assert seen["params"] == {
        "since": now - WEEK,
        "now": now,
        "draft_ttl": DRAFT_TTL_SECONDS,
        "expiring_soon": EXPIRING_SOON.total_seconds(),
    }
    assert counts.drafts_to_approve == 2


def test_query_never_filters_by_tenant_by_hand() -> None:
    """RLS is the wall: the SQL carries no tenant predicate that could be forgotten or
    bypassed, and writes nothing."""
    sql = str(HOME_COUNTS_SQL).lower()
    assert "tenant_id" not in sql
    for verb in ("insert", "update", "delete"):
        assert not re.search(rf"\b{verb}\b", sql), verb
