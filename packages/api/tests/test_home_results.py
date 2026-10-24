"""`qualify_api.home.results` offline (m-24843003): row mapping, the session door, and the
read-only, RLS-only shape of the query."""

from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from qualify_api.home import WEEK, ResultsCounts, read_results_counts
from qualify_api.home.results import RESULTS_COUNTS_SQL, results_from_row

TENANT = UUID("a0000000-0000-4000-8000-0000000000e2")


def _row(**over: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "messages_week_dm": 1,
        "people_week_dm": 2,
        "comments_week": 3,
        "published_week": 4,
        "messages_week_whatsapp": 5,
        "people_week_whatsapp": 6,
        "mentions_week": 7,
        "instagram_connected": True,
        "whatsapp_connected": False,
    }
    base.update(over)
    return SimpleNamespace(**base)


def test_results_from_row_maps_every_field() -> None:
    assert results_from_row(_row()) == ResultsCounts(1, 2, 3, 4, 5, 6, 7, True, False)


def test_null_counts_read_as_zero() -> None:
    counts = results_from_row(_row(published_week=None, people_week_whatsapp=None))
    assert counts.published_week == 0 and counts.people_week_whatsapp == 0


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
    counts = read_results_counts(TENANT, now=now, session_factory=factory)
    assert seen["tenant"] == TENANT
    assert seen["sql"] is RESULTS_COUNTS_SQL
    assert seen["params"] == {"since": now - WEEK}
    assert counts.comments_week == 3


def test_query_never_filters_by_tenant_by_hand_and_writes_nothing() -> None:
    """RLS is the wall: no tenant predicate that could be forgotten or bypassed."""
    sql = str(RESULTS_COUNTS_SQL).lower()
    assert "tenant_id" not in sql
    for verb in ("insert", "update", "delete"):
        assert not re.search(rf"\b{verb}\b", sql), verb


def test_every_field_is_a_column_of_the_query() -> None:
    sql = str(RESULTS_COUNTS_SQL)
    for name in ResultsCounts.__dataclass_fields__:
        assert f"AS {name}" in sql, name
