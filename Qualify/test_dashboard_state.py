"""`DashboardState`'s computed vars and query building (QUA-49, QUA-152) — the state is
constructed directly, same technique `test_inbox_state.py` uses: the event handlers need a
live `EventContext` (`self.get_state(AuthState)`) a unit test cannot provide. The paging,
notice and refresh RULES those handlers apply are pure and tested in
`test_mentions_paging.py`; the reads are tested in `test_mentions_provider.py` and, against
Postgres, in `packages/api/tests/test_mentions_paging_db.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from .mentions_paging import ALL_ACCOUNTS, ALL_HISTORY, ALL_ORIGINS, ALL_SENTIMENTS, DEFAULT_PERIOD
from .mentions_provider import MentionVM
from .state import DashboardState, MentionRow, _window_start

assert MentionRow is MentionVM  # the alias `state.py` documents, pinned structurally

CONNECTION = "b0000000-0000-4000-8000-000000000001"


def test_counters_come_from_the_backend_aggregates_not_the_visible_rows() -> None:
    """The counters are fields filled from the backend's counts over the whole filtered
    set; the 12 rows on screen do not feed them."""
    state = DashboardState()
    state.mentions = []
    state.total_mentions = 57
    state.positive_count = 3

    assert state.total_mentions == 57
    assert state.positive_count == 3


def test_states_hint_lists_the_non_polarity_states_separately() -> None:
    state = DashboardState()
    state.pending_count, state.no_text_count, state.error_count = 4, 1, 2

    assert state.states_hint == "4 pendientes de análisis · 3 sin análisis"

    state.pending_count = state.no_text_count = state.error_count = 0
    assert state.states_hint == ""


def test_query_maps_filter_labels_to_backend_codes() -> None:
    state = DashboardState()
    state.accounts = {"@qualifymkt.co": CONNECTION}
    state.account_filter = "@qualifymkt.co"
    state.origin_filter = "Comentario"
    state.sentiment_filter = "Pendiente"
    state.search_query = "@QualifyMkt"

    query = state._query()

    assert query.connection_id == UUID(CONNECTION)
    assert query.origin == "comment"
    assert query.sentiment_state == "PENDING"
    assert query.search_term == "QualifyMkt"


def test_default_filters_query_everything() -> None:
    query = DashboardState()._query()

    assert (query.connection_id, query.origin, query.sentiment_state) == (None, None, None)


def test_an_unknown_account_label_does_not_narrow_the_query() -> None:
    state = DashboardState()
    state.account_filter = "@ya-desconectada"

    assert state._query().connection_id is None


def test_account_options_start_with_all_accounts() -> None:
    state = DashboardState()
    state.accounts = {"@b": "2", "@a": "1"}

    assert state.account_options == [ALL_ACCOUNTS, "@a", "@b"]


def test_has_filters() -> None:
    state = DashboardState()
    assert state.has_filters is False

    state.search_query = "   "
    assert state.has_filters is False

    state.search_query = "hola"
    assert state.has_filters is True

    state.search_query = ""
    state.origin_filter = "Publicación"
    assert state.has_filters is True

    state.origin_filter = ALL_ORIGINS
    state.sentiment_filter = "Pendiente"
    assert state.has_filters is True

    state.sentiment_filter = ALL_SENTIMENTS
    assert state.has_filters is False


def test_empty_state_and_no_results_never_overlap() -> None:
    """Nothing stored -> "Aún no hay menciones"; nothing MATCHING -> "Ninguna mención
    coincide". Loading or an error suppresses both."""
    state = DashboardState()
    assert (state.show_empty_state, state.show_no_results) == (True, False)

    state.origin_filter = "Comentario"
    assert (state.show_empty_state, state.show_no_results) == (False, True)

    state.is_loading_mentions = True
    assert (state.show_empty_state, state.show_no_results) == (False, False)

    state.is_loading_mentions = False
    state.mentions_error = "No se pudieron cargar las menciones."
    assert (state.show_empty_state, state.show_no_results) == (False, False)

    state.mentions_error = ""
    state.filtered_total = 3
    assert (state.show_empty_state, state.show_no_results) == (False, False)


def test_pager_vars() -> None:
    state = DashboardState()
    state.page, state.total_pages = 1, 5
    assert (state.has_prev, state.has_next) == (False, True)
    assert state.page_items == ["1", "2", "3", "4", "5"]

    state.page = 5
    assert (state.has_prev, state.has_next) == (True, False)


def test_new_mentions_notice_reads_from_the_count() -> None:
    state = DashboardState()
    assert state.new_mentions_notice == ""

    state.new_count = 1
    assert state.new_mentions_notice == "1 mención nueva"

    state.new_count = 50
    assert state.new_mentions_notice == "50+ menciones nuevas"


def test_the_screen_opens_on_the_last_14_days() -> None:
    state = DashboardState()

    assert state.period_filter == DEFAULT_PERIOD == "Últimos 14 días"
    assert state.is_windowed is True


def test_the_window_start_follows_the_period_and_feeds_the_query() -> None:
    before = datetime.now(UTC)
    start = datetime.fromisoformat(_window_start("Últimos 7 días"))

    assert timedelta(days=7) - timedelta(seconds=5) < before - start < timedelta(days=7, seconds=5)
    assert _window_start(ALL_HISTORY) == ""

    state = DashboardState()
    state.since = start.isoformat()
    assert state._query().since == start
    state.since = ""
    assert state._query().since is None


def test_whole_history_is_not_a_window() -> None:
    state = DashboardState()
    state.period_filter = ALL_HISTORY

    assert state.is_windowed is False


def test_the_account_filter_shows_only_with_several_accounts() -> None:
    state = DashboardState()
    state.accounts = {"@a": "1"}
    assert state.show_account_filter is False

    state.accounts = {"@a": "1", "@b": "2"}
    assert state.show_account_filter is True


# --- "Actualizar menciones" (QUA-152 D1) -----------------------------------------------


def _row(mention_id: str) -> MentionVM:
    return MentionVM(
        id=mention_id,
        is_new=False,
        platform="instagram",
        kind="post",
        kind_label="Publicación",
        author="@autora",
        author_note="",
        text="hola",
        text_unavailable=False,
        date="13 oct 2026, 10:00",
        day="13 oct 2026",
        time="10:00",
        sentiment_state="POS",
        likes="1",
        likes_note="",
        permalink="",
    )


def test_the_refresh_scope_is_account_and_period_never_origin_sentiment_or_search() -> None:
    state = DashboardState()
    state.accounts = {"@marca": CONNECTION}
    state.account_filter = "@marca"
    state.since = "2026-10-01T00:00:00+00:00"
    state.origin_filter = "Comentario"
    state.sentiment_filter = "Negativa"
    state.search_query = "promo"

    scope = state._scope_query()

    assert scope.connection_id == UUID(CONNECTION)
    assert scope.since == datetime(2026, 10, 1, tzinfo=UTC)
    assert (scope.origin, scope.sentiment_state, scope.search) == (None, None, "")


async def test_refresh_now_updates_the_visible_page_then_hands_the_scope_to_the_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import state as state_module
    from .mentions_provider import MentionCountsVM, MentionPageVM

    tenant = UUID("a0000000-0000-4000-8000-000000000001")
    seen: dict = {}

    async def fake_tenant(self: DashboardState) -> UUID:
        return tenant

    async def fake_refresh(tenant_id: UUID, mention_ids: list[str]) -> None:
        seen["refreshed"] = (tenant_id, mention_ids)

    def fake_load_page(tenant_id: UUID, **kwargs: object) -> MentionPageVM:
        seen["reload"] = kwargs
        return MentionPageVM(
            rows=[_row("m1"), _row("m2")],
            summary=MentionCountsVM(total=2, positive=2),
            filtered_total=2,
            page=1,
            total_pages=1,
            pages_label="Total de 1 página",
            as_of="2026-10-14T00:00:00+00:00",
        )

    monkeypatch.setattr(DashboardState, "_tenant", fake_tenant)
    monkeypatch.setattr(state_module, "refresh_content", fake_refresh)
    monkeypatch.setattr(state_module, "load_page", fake_load_page)
    state = DashboardState()
    state.mentions = [_row("m1"), _row("m2")]
    state.as_of = "2026-10-13T00:00:00+00:00"

    emitted = [item async for item in DashboardState.refresh_now.fn(state)]

    assert seen["refreshed"] == (tenant, ["m1", "m2"])  # the visible page, right away
    assert seen["reload"]["as_of"] == ""  # then a new snapshot of the same page
    assert state.is_refreshing is True  # still running: the scope is next
    assert state.refresh_tone == "info"
    assert emitted[-1] is not None
    assert "refresh_scope" in str(emitted[-1])  # the rest of the scope, in the background


async def test_refresh_now_ignores_a_click_while_a_run_is_in_progress() -> None:
    state = DashboardState()
    state.is_refreshing = True
    state.refresh_notice = "en curso"

    emitted = [item async for item in DashboardState.refresh_now.fn(state)]

    assert emitted == []
    assert state.refresh_notice == "en curso"


def test_the_background_run_reports_through_the_pure_outcome_rule() -> None:
    """`refresh_scope` needs a live StateProxy (`async with self`), so its wiring is pinned
    structurally: it reports with `refresh_outcome` and never claims done while pending."""
    import inspect

    source = inspect.getsource(DashboardState.refresh_scope.fn)
    assert "refresh_outcome(" in source
    assert "self.is_refreshing = False" in source
    assert 'pending = outcome.tone == "warn"' in source
