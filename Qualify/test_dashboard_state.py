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


def test_refresh_now_only_starts_the_run_and_hands_it_to_the_background() -> None:
    """The click handler holds the session for no network call at all: it marks the run
    and returns the background event that does the work (audit finding, QUA-152)."""
    state = DashboardState()
    state.refresh_run = 3

    result = DashboardState.refresh_now.fn(state)

    assert state.is_refreshing is True
    assert state.refresh_run == 4
    assert state.refresh_started_at > 0
    assert state.refresh_tone == "info"
    assert "refresh_scope" in str(result)  # carrying its run token


def test_refresh_now_ignores_a_click_while_a_run_is_in_progress() -> None:
    state = DashboardState()
    state.is_refreshing = True
    state.refresh_run = 7
    state.refresh_notice = "en curso"

    assert DashboardState.refresh_now.fn(state) is None
    assert (state.refresh_run, state.refresh_notice) == (7, "en curso")


class _Proxy:
    """Stands in for Reflex's StateProxy so the background handler can run in a test:
    `async with self` is a no-op lock, every attribute goes to the real state."""

    def __init__(self, state: DashboardState) -> None:
        object.__setattr__(self, "_state", state)

    async def __aenter__(self) -> _Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def __getattr__(self, name: str) -> object:
        return getattr(self._state, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._state, name, value)


def _report(**overrides: object) -> object:
    from qualify_api.mentions.composition import ContentRefreshReport

    values: dict = {
        "in_scope": 2,
        "refreshed": 2,
        "already_fresh": 0,
        "failed": 0,
        "not_attempted": 0,
    }
    values.update(overrides)
    return ContentRefreshReport(**values)


def _wire(monkeypatch: pytest.MonkeyPatch, *, visible: object, scope: object) -> dict:
    from . import state as state_module
    from .mentions_provider import MentionCountsVM, MentionPageVM

    seen: dict = {"reads": 0}
    scope_result = scope

    async def fake_tenant(self: DashboardState) -> UUID:
        return UUID("a0000000-0000-4000-8000-000000000001")

    async def fake_visible(tenant_id: UUID, mention_ids: list[str]) -> object:
        seen["visible"] = mention_ids
        return visible(seen) if callable(visible) else visible

    async def fake_scope(tenant_id: UUID, *, scope: object) -> object:
        seen["scope"] = scope
        if isinstance(scope_result, Exception):
            raise scope_result
        return scope_result

    def fake_load_page(tenant_id: UUID, **kwargs: object) -> MentionPageVM:
        seen["reads"] += 1
        return MentionPageVM(
            rows=[_row("m1"), _row("m2")],
            summary=MentionCountsVM(total=2),
            filtered_total=2,
            page=1,
            total_pages=1,
            pages_label="",
            as_of="2026-10-14T00:00:00+00:00",
        )

    monkeypatch.setattr(DashboardState, "_tenant", fake_tenant)
    monkeypatch.setattr(state_module, "refresh_content", fake_visible)
    monkeypatch.setattr(state_module, "refresh_scope", fake_scope)
    monkeypatch.setattr(state_module, "load_page", fake_load_page)
    return seen


def _running_state() -> DashboardState:
    state = DashboardState()
    state.mentions = [_row("m1"), _row("m2")]
    state.is_refreshing = True
    state.refresh_run = 1
    return state


async def _run(state: DashboardState, run: int = 1) -> list:
    return [item async for item in DashboardState.refresh_scope.fn(_Proxy(state), run)]


async def test_the_background_run_updates_the_visible_page_then_the_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch, visible=_report(), scope=_report(in_scope=30, refreshed=30))
    state = _running_state()

    emitted = await _run(state)

    assert seen["visible"] == ["m1", "m2"]  # the page being looked at, first
    assert seen["scope"] is not None  # then the whole scope
    assert seen["reads"] == 2  # page re-read after each phase
    assert state.is_refreshing is False
    assert state.refresh_notice == ""  # done is a toast, not a notice
    assert len(emitted) == 1


async def test_a_mention_deleted_on_the_network_never_leaves_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case of the 2026-10-15 report: the visible pass finds one mention deleted, the
    scope run then sees only the rest. The run is done — no "no se pudo leer" warning."""
    _wire(
        monkeypatch,
        visible=_report(in_scope=2, refreshed=1, removed=1),
        scope=_report(in_scope=1, refreshed=0, already_fresh=1),
    )
    state = _running_state()

    emitted = await _run(state)

    assert (state.refresh_notice, state.refresh_tone) == ("", "")
    assert state.is_refreshing is False
    assert len(emitted) == 1


async def test_removals_are_announced_when_the_run_stops_early(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .mentions_paging import THROTTLED_NOTICE

    _wire(
        monkeypatch,
        visible=_report(in_scope=2, refreshed=0, removed=1, rate_limited=True),
        scope=_report(),
    )
    state = _running_state()

    await _run(state)

    assert state.refresh_tone == "warn"
    assert state.refresh_notice.startswith("1 mención ya no está disponible en la red social")
    assert state.refresh_notice.endswith(THROTTLED_NOTICE)


async def test_a_throttled_visible_pass_stops_the_run_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .mentions_paging import THROTTLED_NOTICE

    seen = _wire(
        monkeypatch, visible=_report(refreshed=0, not_attempted=2, rate_limited=True), scope=None
    )
    state = _running_state()

    await _run(state)

    assert "scope" not in seen  # never asked for the rest
    assert state.is_refreshing is False
    assert (state.refresh_notice, state.refresh_tone) == (THROTTLED_NOTICE, "warn")


async def test_a_pending_scope_stays_on_screen_as_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch, visible=_report(), scope=_report(in_scope=30, refreshed=27, failed=3))
    state = _running_state()

    emitted = await _run(state)

    assert state.refresh_tone == "warn"
    assert state.refresh_notice.startswith("Se actualizaron 27 de 30 menciones.")
    assert emitted == []


async def test_a_failure_in_the_run_unlocks_the_button_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .mentions_paging import REFRESH_FAILED_NOTICE

    _wire(monkeypatch, visible=_report(), scope=RuntimeError("db down"))
    state = _running_state()

    await _run(state)

    assert state.is_refreshing is False
    assert (state.refresh_notice, state.refresh_tone) == (REFRESH_FAILED_NOTICE, "warn")


async def test_a_superseded_run_never_writes_over_the_newer_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _running_state()

    def reopened_meanwhile(seen: dict) -> object:
        state.refresh_run = 2  # the screen was reopened / a newer run started
        state.refresh_notice = "la ejecución nueva"
        return _report()

    seen = _wire(monkeypatch, visible=reopened_meanwhile, scope=_report())

    await _run(state)

    assert "scope" not in seen
    assert state.is_refreshing is True  # owned by the newer run
    assert state.refresh_notice == "la ejecución nueva"


def test_opening_the_screen_decides_through_the_liveness_rule() -> None:
    import inspect

    source = inspect.getsource(DashboardState.load_mentions.fn)
    assert "refresh_still_running(" in source
    assert "self.is_refreshing = False" in source
    assert "self.refresh_run += 1" in source  # a dead run is superseded if it resumes


async def test_a_run_superseded_during_the_scope_pass_never_writes_its_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _running_state()
    seen = _wire(monkeypatch, visible=_report(), scope=_report())
    from . import state as state_module

    async def scope_then_reopened(tenant_id: UUID, *, scope: object) -> object:
        seen["scope"] = scope
        state.refresh_run = 2  # a newer run started while this one was reading
        state.refresh_notice = "la ejecución nueva"
        return _report(in_scope=30, refreshed=30)

    monkeypatch.setattr(state_module, "refresh_scope", scope_then_reopened)

    emitted = await _run(state)

    assert emitted == []  # no toast for a run nobody owns
    assert state.is_refreshing is True
    assert state.refresh_notice == "la ejecución nueva"


async def test_a_run_whose_token_is_stale_before_starting_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch, visible=_report(), scope=_report())
    state = _running_state()
    state.refresh_run = 5  # the screen was reopened after the click

    await _run(state, run=4)

    assert "visible" not in seen and "scope" not in seen
    assert state.refresh_alive_run == 0


async def test_a_usage_pause_in_the_visible_pass_stops_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .mentions_paging import USAGE_PAUSED_NOTICE

    seen = _wire(monkeypatch, visible=_report(usage_paused=True), scope=None)
    state = _running_state()

    await _run(state)

    assert "scope" not in seen
    assert (state.refresh_notice, state.refresh_tone) == (USAGE_PAUSED_NOTICE, "warn")
    assert state.is_refreshing is False


async def test_a_session_without_tenant_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _wire(monkeypatch, visible=_report(), scope=_report())

    async def no_tenant(self: DashboardState) -> None:
        return None

    monkeypatch.setattr(DashboardState, "_tenant", no_tenant)
    state = _running_state()

    await _run(state)

    assert "visible" not in seen
    assert (state.refresh_notice, state.refresh_tone) == ("No hay una sesión activa.", "warn")
    assert state.is_refreshing is False


async def test_the_background_run_marks_itself_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, visible=_report(), scope=_report())
    state = _running_state()

    await _run(state)

    assert state.refresh_alive_run == 1


async def test_a_run_superseded_after_the_visible_pass_skips_the_scope_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import state as state_module

    state = _running_state()
    seen = _wire(monkeypatch, visible=_report(), scope=_report())
    real_load_page = state_module.load_page

    def reload_then_reopened(tenant_id: UUID, **kwargs: object) -> object:
        page = real_load_page(tenant_id, **kwargs)
        state.refresh_run = 2  # reopened right after the visible page was re-read
        return page

    monkeypatch.setattr(state_module, "load_page", reload_then_reopened)

    await _run(state)

    assert "visible" in seen
    assert "scope" not in seen  # the scope's reads are never spent for nobody


async def test_a_failing_visible_pass_still_reloads_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(seen: dict) -> object:
        raise RuntimeError("network down")

    seen = _wire(monkeypatch, visible=broken, scope=_report(in_scope=30, refreshed=30))
    state = _running_state()

    await _run(state)

    assert seen["reads"] == 2  # the page is re-read anyway
    assert "scope" in seen  # and the scope still runs
    assert state.is_refreshing is False
