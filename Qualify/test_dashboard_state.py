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
from qualify_api.mentions.repository import MentionQuery

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

    # The same words as each row's reason (N1): never «análisis».
    assert state.states_hint == "4 por revisar · 1 sin texto para leer · 2 que no pudimos leer"

    state.pending_count, state.error_count = 0, 0
    assert state.states_hint == "1 sin texto para leer"

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


def test_the_dashboard_has_no_new_mention_counter() -> None:
    """A mention is not a message (QUA-152): no counter of new arrivals and no "Nueva"
    mark exist. The only arrival notice is the later page's «Llegaron menciones nuevas.»
    (founder's text 2026-10-23, RESULTADOS-1), tested with the tick below."""
    names = set(DashboardState.get_fields()) | set(DashboardState.computed_vars)
    assert not {"new_count", "new_since"} & names


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
    assert state.refresh_notice == ""  # nothing on the page: the button shows it loading
    assert "Actualizando menciones" in str(result)  # the flow starts with a toast
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
    assert "Menciones actualizadas." in str(emitted[0])


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

    assert state.refresh_notice == ""
    assert state.is_refreshing is False
    assert len(emitted) == 1
    assert "1 ya no está disponible y se quitó." in str(emitted[0])


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

    emitted = await _run(state)

    assert state.refresh_notice == THROTTLED_NOTICE  # what to do, on the page
    assert "1 ya no está disponible y se quitó." in str(emitted[0])  # what changed, a toast


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
    assert state.refresh_notice == THROTTLED_NOTICE


async def test_unread_mentions_are_only_counted_in_the_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch, visible=_report(), scope=_report(in_scope=30, refreshed=27, failed=3))
    state = _running_state()

    emitted = await _run(state)

    assert state.refresh_notice == ""  # nothing to do about it: no on-page notice
    assert len(emitted) == 1
    assert "Se actualizaron 27 de 30 menciones." in str(emitted[0])


async def test_a_failure_in_the_run_unlocks_the_button_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .mentions_paging import REFRESH_FAILED_NOTICE

    _wire(monkeypatch, visible=_report(), scope=RuntimeError("db down"))
    state = _running_state()

    await _run(state)

    assert state.is_refreshing is False
    assert state.refresh_notice == REFRESH_FAILED_NOTICE


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
    assert state.refresh_notice == USAGE_PAUSED_NOTICE
    assert state.is_refreshing is False


async def test_a_session_without_tenant_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _wire(monkeypatch, visible=_report(), scope=_report())

    async def no_tenant(self: DashboardState) -> None:
        return None

    monkeypatch.setattr(DashboardState, "_tenant", no_tenant)
    state = _running_state()

    await _run(state)

    assert "visible" not in seen
    assert state.refresh_notice == "Tu sesión se cerró. Vuelve a entrar para ver tus menciones."
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


# --- a new mention appears, never announced as a message (QUA-152) ----------------------

OLD_SNAPSHOT = "2026-10-14T00:00:00+00:00"
NEW_SNAPSHOT = "2026-10-15T00:00:00+00:00"


def _wire_tick(monkeypatch: pytest.MonkeyPatch, *, broken: bool = False) -> dict:
    """The tick's ONE read, `load_page`: under the old snapshot it holds m1/m2, under a
    new one also the webhook's m3. Records (page, as_of, since). `broken` makes it fail
    once, like a database blip."""
    from . import state as state_module
    from .mentions_provider import MentionCountsVM, MentionPageVM

    seen: dict = {"loads": [], "broken": broken}

    async def fake_tenant(self: DashboardState) -> UUID:
        return UUID("a0000000-0000-4000-8000-000000000001")

    def fake_load_page(
        tenant_id: UUID, *, query: MentionQuery, page: int, as_of: str, **kwargs: object
    ) -> MentionPageVM:
        if seen["broken"]:
            seen["broken"] = False
            raise RuntimeError("db blip")
        seen["loads"].append((page, as_of, query.since))
        ids = ["m1", "m2"] if as_of else ["m3", "m1", "m2"]
        return MentionPageVM(
            rows=[_row(i) for i in ids],
            summary=MentionCountsVM(total=len(ids)),
            filtered_total=len(ids),
            page=page,
            total_pages=2,
            pages_label="",
            as_of=as_of or NEW_SNAPSHOT,
        )

    def fake_list_total_now(tenant_id: UUID, *, query: MentionQuery) -> int:
        seen["counts"].append(query.since)
        seen["count_queries"].append(query)
        if seen.get("count_broken"):
            raise RuntimeError("db blip")
        return seen["now_total"]

    seen.update(counts=[], count_queries=[], now_total=2)
    monkeypatch.setattr(DashboardState, "_tenant", fake_tenant)
    monkeypatch.setattr(state_module, "load_page", fake_load_page)
    monkeypatch.setattr(state_module, "list_total_now", fake_list_total_now)
    return seen


STALE_WINDOW = (datetime.now(UTC) - timedelta(days=20)).isoformat()


def _listing_state(page: int = 1) -> DashboardState:
    """A listing opened long ago: its window start is 20 days back by now."""
    state = DashboardState()
    state.mentions = [_row("m1"), _row("m2")]
    state.as_of = OLD_SNAPSHOT
    state.snapshot_total = 2
    state.page = page
    state.total_pages = 2
    state.since = STALE_WINDOW
    return state


def _days_back(since: datetime | None) -> float:
    assert since is not None
    return (datetime.now(UTC) - since).total_seconds() / 86400


async def test_a_new_mention_appears_on_the_first_page_without_any_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire_tick(monkeypatch)
    state = _listing_state()

    await DashboardState.refresh_tick.fn(state)

    assert [row.id for row in state.mentions] == ["m3", "m1", "m2"]
    assert [(page, as_of) for page, as_of, _ in seen["loads"]] == [(1, "")]  # ONE read
    assert (state.as_of, state.snapshot_total) == (NEW_SNAPSHOT, 3)
    # Nothing presents it as a message that arrived, nor as "the list changed".
    assert (state.refresh_notice, state.list_changed, state.refresh_error) == ("", False, "")


async def test_the_first_page_tick_keeps_the_period_window_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review finding: a dashboard left open on page 1 must keep showing the selected
    period (the last 14 days by default, or the chosen one), not a window that grows."""
    seen = _wire_tick(monkeypatch)
    state = _listing_state()  # opened when its window started 20 days ago

    await DashboardState.refresh_tick.fn(state)

    since = seen["loads"][0][2]
    assert 13.99 < _days_back(since) < 14.01  # the default period, recomputed
    assert state.since == since.isoformat()

    state.period_filter = "Últimos 7 días"
    await DashboardState.refresh_tick.fn(state)
    assert 6.99 < _days_back(seen["loads"][1][2]) < 7.01

    state.period_filter = ALL_HISTORY
    await DashboardState.refresh_tick.fn(state)
    assert seen["loads"][2][2] is None


async def test_a_later_page_keeps_its_snapshot_and_window(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _wire_tick(monkeypatch)
    state = _listing_state(page=2)

    await DashboardState.refresh_tick.fn(state)

    page, as_of, since = seen["loads"][0]
    assert (page, as_of) == (2, OLD_SNAPSHOT)  # same snapshot: paging stays exact
    assert since == datetime.fromisoformat(STALE_WINDOW)  # same listing, same window
    assert (state.refresh_notice, state.list_changed) == ("", False)


async def test_a_mention_committed_late_on_page_one_shows_without_the_change_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review finding: on page 1 a set that changed under the old snapshot (a mention
    committed late) now simply shows too — never "La lista cambió"."""
    _wire_tick(monkeypatch)
    state = _listing_state()
    state.snapshot_total = 1  # the old snapshot missed a row that committed late

    await DashboardState.refresh_tick.fn(state)

    assert state.list_changed is False
    assert state.snapshot_total == 3


async def test_a_later_page_whose_set_changed_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_tick(monkeypatch)
    state = _listing_state(page=2)
    state.snapshot_total = 5  # the same snapshot now holds a different set

    await DashboardState.refresh_tick.fn(state)

    assert state.list_changed is True
    assert [row.id for row in state.mentions] == ["m1", "m2"]  # rows never swapped silently


async def test_a_failed_tick_keeps_the_rows_and_the_next_tick_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review finding (QUA-152): a database blip during a tick must never become the
    screen's load error, which also stopped every later tick."""
    seen = _wire_tick(monkeypatch, broken=True)
    state = _listing_state()

    await DashboardState.refresh_tick.fn(state)

    assert [row.id for row in state.mentions] == ["m1", "m2"]  # kept
    assert state.mentions_error == ""  # the screen is not broken
    assert state.refresh_error != ""  # a soft notice says it
    assert (state.as_of, state.since) == (OLD_SNAPSHOT, STALE_WINDOW)  # nothing half-applied

    await DashboardState.refresh_tick.fn(state)  # the next tick works

    assert [row.id for row in state.mentions] == ["m3", "m1", "m2"]
    assert state.refresh_error == ""
    assert len(seen["loads"]) == 1


@pytest.mark.parametrize("how", ["go_to_page", "prev_page"])
async def test_going_back_to_page_one_shows_what_arrived_at_once(
    monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    seen = _wire_tick(monkeypatch)
    state = _listing_state(page=2)

    if how == "go_to_page":
        await DashboardState.go_to_page.fn(state, "1")
    else:
        await DashboardState.prev_page.fn(state)

    assert [(page, as_of) for page, as_of, _ in seen["loads"]] == [(1, "")]
    assert [row.id for row in state.mentions] == ["m3", "m1", "m2"]
    assert 13.99 < _days_back(seen["loads"][0][2]) < 14.01  # window recomputed too


async def test_moving_between_later_pages_keeps_the_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire_tick(monkeypatch)
    state = _listing_state(page=1)

    await DashboardState.go_to_page.fn(state, "2")

    assert [(page, as_of) for page, as_of, _ in seen["loads"]] == [(2, OLD_SNAPSHOT)]


def test_the_list_changed_button_goes_to_page_one_through_the_one_handler() -> None:
    """Review finding: "Actualizar" and going to page 1 were two identical handlers."""
    from .components import notices

    assert not hasattr(DashboardState, "refresh_list")
    assert "go_to_page" in str(notices())


def test_the_notices_announce_new_mentions_only_through_the_founders_text() -> None:
    """RESULTADOS-1 (QUA-152, founder 2026-10-23): «Llegaron menciones nuevas.» with
    «Verlas» to page 1 — never a counter, a bell or «Ver nuevas»."""
    from .components import notices

    rendered = str(notices())

    for announcement in ("Ver nuevas", "bell", "new_count"):
        assert announcement not in rendered
    assert "new_mentions_notice" in rendered and "Verlas" in rendered
    # The legitimate refresh outcomes are still there.
    assert "list_changed" in rendered and "refresh_notice" in rendered


# --- «Llegaron menciones nuevas.» on a later page (RESULTADOS-1, QUA-152) ----------------


async def test_a_later_page_says_new_mentions_arrived(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _wire_tick(monkeypatch)
    seen["now_total"] = 3  # the webhook stored m3 after the snapshot
    state = _listing_state(page=2)

    await DashboardState.refresh_tick.fn(state)

    assert state.new_mentions_notice == "Llegaron menciones nuevas."
    assert [row.id for row in state.mentions] == ["m1", "m2"]  # the page never shifts
    assert seen["counts"] == [datetime.fromisoformat(STALE_WINDOW)]  # same window


async def test_the_arrivals_count_uses_the_lists_own_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UX review: on page 2 of «Negativas», a new positive mention must not announce
    itself — the count is the list's (sentiment included) against the list's total."""
    seen = _wire_tick(monkeypatch)
    state = _listing_state(page=2)
    state.sentiment_filter = "Negativa"
    state.total_mentions = 40  # the scope holds far more than the filtered list
    seen["now_total"] = 2  # nothing new among the negatives

    await DashboardState.refresh_tick.fn(state)

    assert seen["count_queries"][0].sentiment_state == "NEG"
    assert state.new_mentions_notice == ""


async def test_verlas_goes_to_page_one_and_clears_the_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire_tick(monkeypatch)
    seen["now_total"] = 3
    state = _listing_state(page=2)
    await DashboardState.refresh_tick.fn(state)

    await DashboardState.go_to_page.fn(state, "1")

    assert state.new_mentions_notice == ""
    assert [row.id for row in state.mentions] == ["m3", "m1", "m2"]


async def test_page_one_never_counts_nor_announces_arrivals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire_tick(monkeypatch)
    seen["now_total"] = 9
    state = _listing_state()

    await DashboardState.refresh_tick.fn(state)

    assert seen["counts"] == []  # ONE read on page 1, as before
    assert state.new_mentions_notice == ""


async def test_a_failed_arrivals_count_only_skips_the_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire_tick(monkeypatch)
    seen["count_broken"] = True
    state = _listing_state(page=2)

    await DashboardState.refresh_tick.fn(state)

    assert (state.new_mentions_notice, state.refresh_error, state.mentions_error) == ("", "", "")


# --- one tap to the bad ones, «Más filtros» (RESULTADOS-1) --------------------------------


def _wire_restart(monkeypatch: pytest.MonkeyPatch) -> list[MentionQuery]:
    queries: list[MentionQuery] = []

    async def fake_read(self: DashboardState, *, page: int, new_snapshot: bool) -> None:
        queries.append(self._query())

    monkeypatch.setattr(DashboardState, "_read", fake_read)
    return queries


async def test_tapping_negativas_filters_the_list_and_a_second_tap_shows_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queries = _wire_restart(monkeypatch)
    state = DashboardState()

    await DashboardState.pick_sentiment.fn(state, "Negativa")
    assert state.sentiment_filter == "Negativa"
    assert queries[-1].sentiment_state == "NEG"

    await DashboardState.pick_sentiment.fn(state, "Negativa")
    assert state.sentiment_filter == ALL_SENTIMENTS
    assert queries[-1].sentiment_state is None


async def test_the_total_card_shows_every_sentiment(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_restart(monkeypatch)
    state = DashboardState()
    state.sentiment_filter = "Positiva"

    await DashboardState.pick_sentiment.fn(state, ALL_SENTIMENTS)

    assert state.sentiment_filter == ALL_SENTIMENTS


def test_each_summary_card_is_a_real_button() -> None:
    """Enter/Space and `aria-pressed` for free: the cards sit in native buttons."""
    from .components import stats_row

    rendered = str(stats_row())

    assert rendered.count('type:"button"') == 4 and "aria-pressed" in rendered


def test_more_filters_counts_what_it_hides() -> None:
    state = DashboardState()
    assert state.more_filters_label == "Más filtros"

    state.origin_filter, state.sentiment_filter = "Comentario", "Negativa"
    assert state.more_filters_label == "Más filtros (2)"


async def test_quitar_filtros_keeps_the_period(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire_restart(monkeypatch)
    state = DashboardState()
    state.period_filter = "Últimos 30 días"
    state.origin_filter, state.sentiment_filter = "Comentario", "Negativa"

    await DashboardState.clear_more_filters.fn(state)

    assert (state.origin_filter, state.sentiment_filter) == (ALL_ORIGINS, ALL_SENTIMENTS)
    assert state.period_filter == "Últimos 30 días"


def test_ver_mas_opens_and_closes_one_mention() -> None:
    state = DashboardState()

    DashboardState.toggle_expanded.fn(state, "m1")
    DashboardState.toggle_expanded.fn(state, "m2")
    DashboardState.toggle_expanded.fn(state, "m1")

    assert state.expanded_ids == ["m2"]


def test_the_screen_has_no_hover_only_information() -> None:
    """N12: no tooltip and no hover card anywhere on the mentions screen."""
    from .components import filter_bar, mentions_body, stats_row

    rendered = str(stats_row()) + str(filter_bar()) + str(mentions_body())

    assert "Tooltip" not in rendered
    assert "HoverCard" not in rendered
