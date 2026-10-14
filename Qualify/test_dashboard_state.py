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
