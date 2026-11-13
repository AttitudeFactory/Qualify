"""«Buscar de nuevo» and «Mover a» on the Brand Kit editor's «Negocios parecidos al tuyo»
(§ request 2026-11-03): the search run again with nothing reused — no stored phase, no
answer from the shared vendor pool, both still written — and every sorted account movable
between Te inspira, Compite contigo and No va contigo, saved on its own. Fully offline."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any
from uuid import UUID

import pytest

from . import brand_kit_editor as editor
from . import creative_wizard_pages as wiz
from . import creator_discovery as cd
from .creative_wizard_pages import BrandConnectState

IDS = (
    UUID("a0000000-0000-4000-8000-0000000000e1"),
    UUID("b0000000-0000-4000-8000-0000000000e1"),
    None,
)


def _card(handle: str, *, manual: bool = False) -> dict[str, str]:
    card = {"network": "Instagram", "handle": f"@{handle}", "url": "", "followers": "1"}
    if manual:
        card["manual"] = "1"
    return card


def _key(handle: str) -> str:
    return f"Instagram:@{handle}"


# -- «Buscar de nuevo» ------------------------------------------------------------------


class _Runner:
    """`PhasedDiscovery` without the vendor: each phase finds one new account."""

    def __init__(self, seed: Any, **_kw: Any) -> None:
        self.seed = seed
        self.pool: dict[Any, Any] = {}
        self.ran: list[str] = []

    def run(self, key: str) -> cd.PhaseResult:
        self.ran.append(key)
        return cd.PhaseResult(key, f"Fresco {key}", [cd.Candidate("instagram", f"new_{key}")])

    def close(self) -> None:
        return None


@pytest.fixture
def refresh(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A state wired to fakes for every outside call `_discovery` makes; returns the
    state and what each fake saw."""
    state = BrandConnectState()
    seen: dict[str, Any] = {
        "state": state,
        "stored_reads": [],
        "stored_writes": [],
        "cache_reads": [],
        "runners": [],
        "calls": [],
    }

    class _Ctx:
        async def __aenter__(self) -> BrandConnectState:
            return state

        async def __aexit__(self, *_exc: object) -> None:
            return None

    async def ids(_self: Any) -> tuple[UUID, UUID, None]:
        return IDS

    async def stored_phase(_self: Any, _ids: Any, key: str, _seed: Any) -> dict:
        seen["stored_reads"].append(key)
        return {"key": key, "title": f"Guardado {key}", "note": "", "accounts": []}

    async def store_phase(_self: Any, _ids: Any, key: str, *_rest: Any) -> None:
        seen["stored_writes"].append(key)

    async def with_hashtags(_self: Any, _ids: Any, seed: Any, _profile: Any) -> tuple:
        return seed, {}

    async def stored_sort(_self: Any, _ids: Any, _run: int) -> tuple:
        # the owner's sort, as `referentes_provider.load_sort` reads it back: one account
        # the new search found again and one it did not (kept)
        return (
            {_key("new_sector"): "competencia", _key("old"): "referente"},
            [wiz.card_view(_card("old"))],
        )

    async def stored_order(_self: Any, _ids: Any, _cards: list) -> list[str]:
        return [_key("old"), _key("new_sector")]

    def payload_cache(_tenant: Any, *, read: bool = True) -> object:
        seen["cache_reads"].append(read)
        return type("Cache", (), {"hits": 0, "misses": 0})()

    async def flush_labels(_self: Any, _ids: Any) -> None:
        seen["calls"].append("labels")

    async def flush_order(_self: Any, _ids: Any) -> None:
        seen["calls"].append("order")

    def runner(seed: Any, **kw: Any) -> _Runner:
        seen["calls"].append("search")
        made = _Runner(seed, **kw)
        seen["runners"].append(made)
        return made

    monkeypatch.setattr(BrandConnectState, "__aenter__", _Ctx.__aenter__, raising=False)
    monkeypatch.setattr(BrandConnectState, "__aexit__", _Ctx.__aexit__, raising=False)
    monkeypatch.setattr(BrandConnectState, "_referentes_ids", ids)
    monkeypatch.setattr(BrandConnectState, "_stored_phase", stored_phase)
    monkeypatch.setattr(BrandConnectState, "_store_phase", store_phase)
    monkeypatch.setattr(BrandConnectState, "_with_catalog_hashtags", with_hashtags)
    monkeypatch.setattr(BrandConnectState, "_stored_sort", stored_sort)
    monkeypatch.setattr(BrandConnectState, "_stored_order", stored_order)
    monkeypatch.setattr(BrandConnectState, "_flush_labels", flush_labels)
    monkeypatch.setattr(BrandConnectState, "_flush_order", flush_order)
    monkeypatch.setattr(wiz.creator_cache_provider, "cached_snapshot", lambda *_a: None)
    monkeypatch.setattr(
        wiz.discovery_seed,
        "seed_from_profile",
        lambda *_a, **_k: cd.DiscoverySeed("mi.marca", ("food_drink",), country_code="CO"),
    )
    monkeypatch.setattr(wiz.referentes_review, "brand_brief", lambda *_a, **_k: "")
    monkeypatch.setattr(wiz.referentes_review, "make_reviewer", lambda *_a, **_k: None)
    monkeypatch.setattr(wiz.creator_pool_provider, "payload_cache", payload_cache)
    monkeypatch.setattr(wiz.creator_pool_provider, "record_pool", lambda *_a, **_k: (0, 0))
    monkeypatch.setattr(wiz.creator_discovery, "PhasedDiscovery", runner)

    # the editor after `load_saved_details` + `load_saved_referentes`: the seed and an
    # earlier search on screen (so `discovery_ran` is already True)
    state.network = "instagram"
    state.profile_username = "mi.marca"
    state.sector = "food_drink"
    state.country_code = "CO"
    state.sector_accounts = [wiz.card_view(_card("stale"))]
    state.sector_title = "Viejo"
    state.discovery_ran = True
    state.account_buckets = {_key("old"): "referente"}
    return seen


async def _drain(events: Any) -> list[Any]:
    return [event async for event in events]


def test_buscar_de_nuevo_reuses_nothing_and_writes_everything(refresh: dict[str, Any]) -> None:
    state = refresh["state"]
    asyncio.run(_drain(BrandConnectState.refresh_discovery.fn(state)))
    assert refresh["stored_reads"] == []  # no stored phase reused
    assert refresh["cache_reads"] == [False]  # the pool is write-only
    assert refresh["stored_writes"] == list(cd.PHASES)  # every fresh phase stored
    (runner,) = refresh["runners"]
    assert runner.ran == list(cd.PHASES)
    # the screen was cleared and refilled by the fresh phases
    assert state.sector_title == "Fresco sector"
    assert [a["handle"] for a in state.sector_accounts] == ["@new_sector"]
    assert state.discovering is False and state.discovery_running == ""


def test_the_ordinary_search_still_reuses_stored_phases_and_the_pool(
    refresh: dict[str, Any],
) -> None:
    state = refresh["state"]
    asyncio.run(_drain(BrandConnectState.run_discovery.fn(state)))
    assert refresh["stored_reads"] == list(cd.PHASES)
    assert refresh["runners"] == []  # every phase came from the store: no vendor run


def test_the_owner_s_sort_survives_buscar_de_nuevo(refresh: dict[str, Any]) -> None:
    state = refresh["state"]
    asyncio.run(_drain(BrandConnectState.refresh_discovery.fn(state)))
    assert state.account_buckets == {
        _key("new_sector"): "competencia",
        _key("old"): "referente",
    }
    # the account the new search did not find is kept, in its bucket
    assert [a["handle"] for a in state.kept_accounts] == ["@old"]
    assert _key("old") in {a["key"] for a in state.referente_accounts}
    assert state.influence_order == [_key("old"), _key("new_sector")]


def test_buscar_de_nuevo_does_nothing_while_a_search_runs(refresh: dict[str, Any]) -> None:
    state = refresh["state"]
    state.discovering = True
    asyncio.run(_drain(BrandConnectState.refresh_discovery.fn(state)))
    assert refresh["runners"] == [] and refresh["cache_reads"] == []
    assert state.sector_title == "Viejo"  # nothing cleared either


def test_buscar_de_nuevo_without_the_account_says_so_and_spends_nothing(
    refresh: dict[str, Any],
) -> None:
    state = refresh["state"]
    state.profile_username = ""
    state.username = ""
    asyncio.run(_drain(BrandConnectState.refresh_discovery.fn(state)))
    assert refresh["runners"] == []
    assert state.discovering is False
    assert "Instagram o TikTok" in state.discovery_error
    assert state.sector_title == "Viejo"


def test_the_editor_asks_before_searching_again() -> None:
    body = str(editor._referentes_body())
    for text in (editor.REFRESH_TITLE, editor.REFRESH_BODY, "Ahora no", editor.REFRESH_BUTTON):
        assert json.dumps(text)[1:-1] in body
    assert "refresh_discovery" in body and "RefreshCw" in body
    # while it runs: the progress bar (never a spinner) and the error when it fails
    assert "discovery_percent" in body and "discovery_error" in body
    assert "spinner" not in str(editor._refresh_progress()).lower()
    assert "scrape" not in (editor.REFRESH_TITLE + editor.REFRESH_BODY).lower()


# -- «Mover a» ----------------------------------------------------------------------------


def _sorted_state() -> BrandConnectState:
    state = BrandConnectState()
    state.sector_accounts = [wiz.card_view(_card(h)) for h in ("a", "b", "c", "d", "u")]
    state.kept_accounts = [wiz.card_view(_card("k"))]  # sorted before, not found now
    state.account_buckets = {
        _key("a"): "referente",
        _key("b"): "referente",
        _key("c"): "competencia",
        _key("d"): "detractor",
        _key("k"): "detractor",
    }
    state._persisted_buckets = dict(state.account_buckets)
    state.influence_order = [_key("b"), _key("a"), _key("c")]
    return state


def test_moving_to_another_list_puts_it_last_there_and_saves_on_its_own() -> None:
    state = _sorted_state()
    fired = BrandConnectState.move_account.fn(state, _key("b"), "competencia")
    assert fired is not None and "sync_sort" in str(fired)
    assert state.account_buckets[_key("b")] == "competencia"
    assert [a["key"] for a in state.ranked_referentes] == [_key("a")]
    # last in its new list, after the ones the owner already ranked
    assert [a["key"] for a in state.ranked_competencia] == [_key("c"), _key("b")]
    assert state.influence_order == [_key("a"), _key("c"), _key("b")]
    # what `sync_labels` / `sync_sort` will write: exactly the move
    assert wiz.referentes_provider.label_changes(
        state._persisted_buckets, state.account_buckets
    ) == {_key("b"): "competencia"}


def test_a_detractor_and_a_kept_account_can_come_back_to_the_ranking() -> None:
    state = _sorted_state()
    BrandConnectState.move_account.fn(state, _key("k"), "referente")
    assert [a["key"] for a in state.ranked_referentes] == [_key("b"), _key("a"), _key("k")]
    BrandConnectState.move_account.fn(state, _key("d"), "competencia")
    assert [a["key"] for a in state.ranked_competencia] == [_key("c"), _key("d")]
    assert {a["key"] for a in state.detractor_accounts} == set()


def test_moving_to_no_va_contigo_takes_it_out_of_the_ranking() -> None:
    state = _sorted_state()
    BrandConnectState.move_account.fn(state, _key("a"), "detractor")
    assert [a["key"] for a in state.ranked_referentes] == [_key("b")]
    assert _key("a") not in state.influence_order
    assert _key("a") in {a["key"] for a in state.detractor_accounts}


def test_an_unsorted_account_can_be_sorted_from_the_editor() -> None:
    state = _sorted_state()
    assert [a["key"] for a in state.unsorted_accounts] == [_key("u")]
    BrandConnectState.move_account.fn(state, _key("u"), "referente")
    assert state.unsorted_accounts == []
    assert state.ranked_referentes[-1]["key"] == _key("u")


def test_a_move_that_changes_nothing_does_nothing() -> None:
    state = _sorted_state()
    before = (dict(state.account_buckets), list(state.influence_order))
    assert BrandConnectState.move_account.fn(state, _key("a"), "referente") is None
    assert BrandConnectState.move_account.fn(state, _key("zz"), "referente") is None
    assert BrandConnectState.move_account.fn(state, _key("a"), "") is None
    assert BrandConnectState.move_account.fn(state, _key("a"), "nope") is None
    assert (state.account_buckets, state.influence_order) == before


def test_sync_sort_writes_the_labels_before_the_order(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _sorted_state()
    BrandConnectState.move_account.fn(state, _key("b"), "competencia")
    writes: list[tuple[str, Any]] = []

    class _Ctx:
        async def __aenter__(self) -> BrandConnectState:
            return state

        async def __aexit__(self, *_exc: object) -> None:
            return None

    async def ids(_self: Any) -> tuple[UUID, UUID, None]:
        return IDS

    monkeypatch.setattr(BrandConnectState, "__aenter__", _Ctx.__aenter__, raising=False)
    monkeypatch.setattr(BrandConnectState, "__aexit__", _Ctx.__aexit__, raising=False)
    monkeypatch.setattr(BrandConnectState, "_referentes_ids", ids)
    monkeypatch.setattr(
        wiz.referentes_provider,
        "write_labels",
        lambda _t, _b, _u, changes: writes.append(("labels", dict(changes))),
    )
    monkeypatch.setattr(
        wiz.referentes_provider,
        "write_order",
        lambda _t, _b, order: writes.append(("order", list(order))),
    )
    asyncio.run(BrandConnectState.sync_sort.fn(state))
    assert writes == [
        ("labels", {_key("b"): "competencia"}),
        ("order", [_key("a"), _key("c"), _key("b")]),
    ]
    assert state._persisted_buckets == state.account_buckets


def test_every_sorted_card_in_the_editor_can_be_moved() -> None:
    body = str(editor._referentes_body())
    assert "move_account" in body and json.dumps(wiz.MOVE_LABEL)[1:-1] in body
    for _bucket, title, label in wiz.BOARD_LISTS:
        assert json.dumps(title)[1:-1] in body and json.dumps(label)[1:-1] in body
    # the columns take a card from another column; the phone shows one list at a time
    assert "data-rank-column" in body and "drop_on_column" in body
    assert "set_sort_tab" in body and "SegmentedControl" in body
    for hint in (wiz.BOARD_HINT, wiz.BOARD_HINT_PHONE):
        assert json.dumps(hint)[1:-1] in body
        assert "card" not in hint
    # the wizard's ranking stays as it was: no «Mover a», no columns there
    ranking = str(wiz._ranking_panel())
    assert "move_account" not in ranking and "data-rank-column" not in ranking
    assert "una card" not in ranking


# -- Cross-column drops on the editor's board ---------------------------------------------


def test_a_card_dropped_on_another_column_lands_last_there() -> None:
    state = _sorted_state()
    BrandConnectState.rank_pick.fn(state, _key("b"))
    fired = BrandConnectState.drop_on_column.fn(state, "competencia")
    assert fired is not None and "sync_sort" in str(fired)
    assert state.rank_dragging == ""
    assert [a["key"] for a in state.ranked_competencia] == [_key("c"), _key("b")]
    assert [a["key"] for a in state.ranked_referentes] == [_key("a")]


def test_a_card_dropped_on_no_va_contigo_leaves_the_ranking_and_can_come_back() -> None:
    state = _sorted_state()
    BrandConnectState.rank_pick.fn(state, _key("a"))
    BrandConnectState.drop_on_column.fn(state, "detractor")
    assert _key("a") not in state.influence_order
    assert _key("a") in {a["key"] for a in state.ranked_detractors}
    # out of No va contigo again: last in Compite contigo
    BrandConnectState.rank_pick.fn(state, _key("d"))
    BrandConnectState.drop_on_column.fn(state, "competencia")
    assert [a["key"] for a in state.ranked_competencia] == [_key("c"), _key("d")]
    assert state.influence_order[-1] == _key("d")


def test_a_reorder_bubbling_up_to_its_own_column_changes_nothing_more() -> None:
    """`rank-drag.js` drops on a card inside the same column: `rank_drop` reorders and
    clears the lifted card, so the column's own `drop` (the event bubbles) is a no-op."""
    state = _sorted_state()
    BrandConnectState.rank_pick.fn(state, _key("a"))
    BrandConnectState.rank_drop.fn(state, _key("b"))
    order = list(state.influence_order)
    assert BrandConnectState.drop_on_column.fn(state, "referente") is None
    assert state.influence_order == order
    # and a lifted card dropped back on its own column does nothing either
    BrandConnectState.rank_pick.fn(state, _key("c"))
    assert BrandConnectState.drop_on_column.fn(state, "competencia") is None
    assert state.account_buckets[_key("c")] == "competencia"


def test_no_va_contigo_has_no_ranking_order() -> None:
    state = _sorted_state()
    rows = state.ranked_detractors
    assert [a["key"] for a in rows] == [_key("d"), _key("k")]  # as found, kept last
    BrandConnectState.rank_pick.fn(state, _key("k"))
    assert BrandConnectState.rank_drop.fn(state, _key("d")) is None  # never reordered


def test_the_phone_tab_only_takes_a_list() -> None:
    state = BrandConnectState()
    BrandConnectState.set_sort_tab.fn(state, "detractor")
    assert state.sort_tab == "detractor"
    BrandConnectState.set_sort_tab.fn(state, ["competencia"])
    assert state.sort_tab == "competencia"
    BrandConnectState.set_sort_tab.fn(state, "nope")
    assert state.sort_tab == "competencia"


# -- The editor's deck for the accounts not sorted yet ------------------------------------


def _pending_state() -> BrandConnectState:
    state = _sorted_state()
    state.national_accounts = [wiz.card_view(_card(h)) for h in ("p1", "p2")]
    state.sort_stage = 0
    return state


def test_the_editor_deck_deals_every_category_at_once_and_closes_when_done() -> None:
    state = _pending_state()
    # «u» is in the sector, «p1»/«p2» in the country: one pile, not a category at a time
    assert state.pending_count == 3
    BrandConnectState.open_sorting.fn(state)
    assert state.sorting_open is True and state.pending_card["key"] == _key("u")
    BrandConnectState.skip_pending.fn(state)
    assert state.pending_card["key"] == _key("p1")
    fired = BrandConnectState.classify_pending.fn(state, "referente")
    assert fired is not None and "sync_sort" in str(fired)
    assert "advance_stage" not in str(fired)
    assert state.account_buckets[_key("p1")] == "referente"
    assert state.fly_direction == "left" and state.hit_bucket == "referente"
    assert state.ranked_referentes[-1]["key"] == _key("p1")  # last in its new list
    BrandConnectState.drop_pending.fn(state, "detractor")
    assert state.fly_direction == ""  # a drop already showed it landing
    assert state.sorting_open is True
    BrandConnectState.classify_pending.fn(state, "competencia")
    assert state.pending_count == 0 and state.pending_card == {}
    assert state.sorting_open is False  # nothing left: the deck goes away
    assert state.sort_stage == 0 and state.step == 0  # never a category or step jump


def test_the_editor_deck_does_nothing_without_a_card_or_with_a_wrong_bucket() -> None:
    state = _sorted_state()
    state.sector_accounts = [a for a in state.sector_accounts if a["handle"] != "@u"]
    assert BrandConnectState.classify_pending.fn(state, "referente") is None
    state = _pending_state()
    assert BrandConnectState.classify_pending.fn(state, "nope") is None
    assert state.pending_count == 3


def test_the_editor_deck_reuses_the_wizard_deck_with_its_own_decision() -> None:
    from . import creative_wizard_pages as module

    deck = str(module._editor_deck())
    assert "q-deck-card" in deck and "q-deck-zone" in deck  # the wizard's deck + zones
    assert "classify_pending" in deck and "drop_pending" in deck
    assert "send_current" not in deck and "drop_into" not in deck
    task = str(module._sorting_task())
    assert json.dumps(module.SORT_NOW)[1:-1] in task
    assert "cuentas por clasificar" in task
    # the wizard's own sort step still decides through `assign`
    step = str(module._connect_step_sort())
    assert "send_current" in step and "classify_pending" not in step


# -- While classifying: only the deck; a move is seen travelling --------------------------


def test_the_open_deck_hides_the_board_until_it_closes() -> None:
    state = _pending_state()
    assert state.board_visible is True
    BrandConnectState.open_sorting.fn(state)
    assert state.board_visible is False
    BrandConnectState.close_sorting.fn(state)  # «Seguir después»
    assert state.board_visible is True
    BrandConnectState.open_sorting.fn(state)
    for bucket in ("referente", "competencia", "detractor"):
        BrandConnectState.classify_pending.fn(state, bucket)
    assert state.sorting_open is False and state.board_visible is True  # the last one
    assert BrandConnectState().board_visible is False  # nothing sorted: no board


def test_the_open_deck_hides_the_board_and_buscar_de_nuevo_on_screen() -> None:
    body = str(editor._referentes_body())
    assert "board_visible" in body
    # «Buscar de nuevo» sits behind the deck flag too
    row = body.index(json.dumps(editor.REFRESH_BUTTON)[1:-1])
    assert "sorting_open" in body[:row]
    panel = str(wiz._sorted_panel())
    assert "q-settle" in panel  # the board settles back in when the deck closes


def test_a_move_carries_what_the_animation_needs() -> None:
    board = str(wiz._sorted_board())
    # the script is sent when the board mounts
    assert "__qRankFlip" in wiz._RANK_FLIP_JS
    assert "_RANK_FLIP_JS" in inspect.getsource(wiz._sorted_board)
    for attr in ("data-rank-board", "data-move-key", "data-move-to", "data-move-board"):
        assert attr in board
    assert "data-rank-count" in board and "data-sort-tab" in board
    flip = (wiz.Path(wiz.__file__).parent.parent / "assets" / "rank-flip.js").read_text(
        encoding="utf-8"
    )
    assert "prefers-reduced-motion" in flip and "MutationObserver" in flip
    drag = (wiz.Path(wiz.__file__).parent.parent / "assets" / "rank-drag.js").read_text(
        encoding="utf-8"
    )
    assert "__qRankFlip.drop" in drag


# -- Review round: paid-call guard, sort flushed first, deck opens after a refresh ---------


def test_the_sort_not_stored_yet_is_written_before_the_screen_is_cleared(
    refresh: dict[str, Any],
) -> None:
    asyncio.run(_drain(BrandConnectState.refresh_discovery.fn(refresh["state"])))
    assert refresh["calls"][:3] == ["labels", "order", "search"]


def test_one_refresh_per_brand_at_a_time(refresh: dict[str, Any]) -> None:
    state = refresh["state"]
    wiz._REFRESHING.add(IDS[1])  # another tab of the same brand is searching
    try:
        asyncio.run(_drain(BrandConnectState.refresh_discovery.fn(state)))
    finally:
        wiz._REFRESHING.discard(IDS[1])
    assert refresh["runners"] == [] and refresh["calls"] == []
    assert state.discovering is False
    assert state.discovery_error == wiz.REFRESH_RUNNING_NOTE
    assert state.sector_title == "Viejo"  # nothing cleared
    # and a run that ends lets the next one through
    asyncio.run(_drain(BrandConnectState.refresh_discovery.fn(state)))
    assert len(refresh["runners"]) == 1 and IDS[1] not in wiz._REFRESHING


def test_buscar_de_nuevo_opens_the_deck_when_there_is_something_to_sort(
    refresh: dict[str, Any],
) -> None:
    state = refresh["state"]
    asyncio.run(_drain(BrandConnectState.refresh_discovery.fn(state)))
    # new_national / new_local came back unsorted (new_sector was sorted before)
    assert state.sorting_open is True and state.board_visible is False
    assert state.pending_count == 2


def test_buscar_de_nuevo_shows_the_board_when_nothing_is_pending(
    refresh: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def all_sorted(_self: Any, _ids: Any, _run: int) -> tuple:
        return ({_key(f"new_{k}"): "referente" for k in cd.PHASES}, [])

    monkeypatch.setattr(BrandConnectState, "_stored_sort", all_sorted)
    state = refresh["state"]
    asyncio.run(_drain(BrandConnectState.refresh_discovery.fn(state)))
    assert state.sorting_open is False and state.board_visible is True


def test_a_failed_or_superseded_refresh_does_not_open_the_deck(
    refresh: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    state = refresh["state"]

    def failing(self: Any, key: str) -> cd.PhaseResult:
        raise wiz.scrapecreators_client.ScrapeCreatorsError("down")

    monkeypatch.setattr(_Runner, "run", failing)
    asyncio.run(_drain(BrandConnectState.refresh_discovery.fn(state)))
    assert state.discovery_error and state.sorting_open is False

    def superseded(self: Any, key: str) -> cd.PhaseResult:
        state.discovery_run_id += 1  # another search started meanwhile
        return cd.PhaseResult(key, "x", [cd.Candidate("instagram", f"late_{key}")])

    monkeypatch.setattr(_Runner, "run", superseded)
    asyncio.run(_drain(BrandConnectState.refresh_discovery.fn(state)))
    assert state.sorting_open is False


def test_the_wizard_search_never_opens_the_editor_deck(refresh: dict[str, Any]) -> None:
    state = refresh["state"]
    state.sector_accounts = []
    state.sector_title = ""
    asyncio.run(_drain(BrandConnectState.run_discovery.fn(state)))
    assert state.sorting_open is False


def test_the_last_account_sorted_says_so_and_moves_the_focus() -> None:
    state = _pending_state()
    BrandConnectState.open_sorting.fn(state)
    BrandConnectState.classify_pending.fn(state, "referente")
    assert state.sorting_done_note == ""
    BrandConnectState.classify_pending.fn(state, "referente")
    fired = BrandConnectState.drop_pending.fn(state, "detractor")
    assert state.sorting_done_note == wiz.SORTING_DONE_NOTE
    assert "sync_sort" in str(fired) and wiz.BOARD_HEADING_ID in str(fired)
    BrandConnectState.open_sorting.fn(state)
    assert state.sorting_done_note == ""
    panel = str(wiz._sorted_panel())
    assert "sorting_done_note" in panel and "polite" in panel
    assert wiz.BOARD_HEADING_ID in str(wiz._sorted_board())


def test_board_cards_are_drag_surfaces_with_the_handle_as_the_link() -> None:
    row = wiz.BrandConnectState.ranked_referentes[0]
    card = str(wiz._rank_card(row, "referente", board="cols"))
    assert 'role:"link"' not in card and "Ver perfil de" in card
    wizard_card = str(wiz._rank_card(row, "referente"))
    assert 'role:"link"' in wizard_card  # the wizard's ranking stays as it was
    board = str(wiz._sorted_board())
    for text in (wiz.EMPTY_TAB, wiz.EMPTY_COLUMN, wiz.BOARD_HINT_PHONE):
        assert json.dumps(text)[1:-1] in board
    assert "Tócala para ver su perfil" in wiz.BOARD_HINT_PHONE


def test_the_missing_account_error_says_where_to_write_it() -> None:
    assert "«Tu cuenta»" in wiz.MISSING_HANDLE_ERROR
