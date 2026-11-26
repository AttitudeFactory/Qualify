"""RF-05 (m-25119465) on «Ideas para tus reels»: the competitors panel over RF-02's filter
bar — what opening shows (and that it pays nothing), ticking the 6 for Monday, «Ver sus
reels ahora» (it only queues), the daily cap's words, the «Competidores» filter once their
reels are read, and two businesses on the same screen. Offline: the same world as
`test_reels_discovery.py` (every paid door fails the test if touched)."""

# The fixtures `store` / `world` are imported from `test_reels_discovery` so pytest finds
# them by name; a test's `world` argument is that fixture, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.referentes import competitors as rivals
from qualify_api.referentes.reel_store import (
    STATUS_OK,
    TRIGGER_COMPETITOR_NOW,
    NewVerdict,
    PublicReel,
)
from qualify_api.vendors import usage

from . import reels_competitors_vm
from .test_reels_discovery import (  # noqa: F401 — fixtures: pytest finds them by name
    CLOCK,
    TENANT,
    _filter,
    _key,
    _no_kit,
    _open,
    _screen_state,
    _World,
    store,
    world,
)

OTHER = UUID("b0000000-0000-4000-8000-000000000002")


def _competitors(world: _World, *handles: str) -> None:
    """More `competencia` accounts on Instagram, after the store's @rival (TikTok)."""
    for handle in handles:
        world.repo.set_label(
            tenant_id=TENANT,
            brand_id=world.brand,
            network="instagram",
            handle=handle,
            label="competencia",
            labeled_by=None,
        )


async def _toggle(proxy: Any, key: str) -> None:
    from .discover_reels import DiscoverReelsState

    await DiscoverReelsState.toggle_weekly.fn(proxy, key)


async def _read_now(proxy: Any, key: str) -> None:
    from .discover_reels import DiscoverReelsState

    await DiscoverReelsState.read_competitor.fn(proxy, key)


async def test_opening_shows_the_competitors_and_pays_nothing(world: _World) -> None:
    world.ok_run()
    _competitors(world, *(f"rival{i}" for i in range(7)))
    state, proxy = _screen_state()
    await _open(proxy)
    rows = state.competitor_rows
    assert [r["label"] for r in rows][:2] == ["@rival", "@rival0"]
    assert len(rows) == 8
    # nothing chosen: the first six of the list are read on Monday
    assert sum(bool(r["weekly"]) for r in rows) == 6
    assert state.competitors_count == "6 de 6 marcados"
    assert world.paid == []
    assert world.runs.competitor_runs(TENANT, world.brand) == []


async def test_ticking_saves_the_choice_and_a_seventh_is_refused(world: _World) -> None:
    world.ok_run()
    _competitors(world, *(f"rival{i}" for i in range(7)))
    state, proxy = _screen_state()
    await _open(proxy)
    await _toggle(proxy, "instagram:rival6")  # a seventh
    assert state.competitor_error == reels_competitors_vm.TOO_MANY
    await _toggle(proxy, "tiktok:rival")  # free a place…
    assert state.competitor_error == ""
    await _toggle(proxy, "instagram:rival6")  # …and take it
    picked = {
        lb.handle
        for lb in world.repo.labels(tenant_id=TENANT, brand_id=world.brand)
        if lb.read_weekly
    }
    assert picked == {"rival0", "rival1", "rival2", "rival3", "rival4", "rival6"}
    assert {r["label"] for r in state.competitor_rows if r["weekly"]} == {f"@{h}" for h in picked}
    assert world.paid == []


async def test_read_now_only_queues_and_says_it_is_reading(world: _World) -> None:
    world.ok_run()
    _competitors(world, *(f"rival{i}" for i in range(7)))
    state, proxy = _screen_state()
    await _open(proxy)
    outside = next(r for r in state.competitor_rows if not r["weekly"])
    await _read_now(proxy, outside["key"])
    await _read_now(proxy, outside["key"])  # a double press is the same read
    reads = world.runs.competitor_runs(TENANT, world.brand)
    assert len(reads) == 1 and reads[0].trigger == TRIGGER_COMPETITOR_NOW
    row = next(r for r in state.competitor_rows if r["key"] == outside["key"])
    assert row["state"] == rivals.STATE_READING
    assert row["message"] == rivals.READING_TEXT
    assert state.competitors_reading
    assert world.paid == []  # the reels-worker pays, never the screen


async def test_read_now_with_the_daily_cap_spent_says_so(world: _World) -> None:
    world.ok_run()
    _competitors(world, "rival0")
    ledger = usage.InMemoryUsageStore()
    usage.configure_store(ledger)  # the conftest puts the default back after the test
    ledger.events.append(
        usage.UsageEvent(
            tenant_id=TENANT,
            brand_id=None,
            vendor=usage.SCRAPECREATORS,
            feature="reels_list",
            credits=usage.DAILY_CAP,
            usd_estimate=Decimal("0"),
            pricing_table_version=usage.PRICING_TABLE_VERSION,
            request_key=f"seed:{uuid4()}",
            created_at=CLOCK,
        )
    )
    state, proxy = _screen_state()
    await _open(proxy)
    # with two competitors, both are in the Monday six: the button needs a seventh
    _competitors(world, *(f"rival{i}" for i in range(1, 7)))
    await _open(proxy)
    outside = next(r for r in state.competitor_rows if not r["weekly"])
    await _read_now(proxy, outside["key"])
    assert world.runs.competitor_runs(TENANT, world.brand) == []  # nothing queued
    row = next(r for r in state.competitor_rows if r["key"] == outside["key"])
    assert row["state"] == rivals.STATE_LIMIT and row["tone"] == "warn"
    assert row["message"] == (
        "Hoy ya se alcanzó el límite de lecturas de tu negocio. Inténtalo mañana."
    )
    assert world.paid == []


def _finish(world: _World, key: str, status: str) -> None:
    """What the reels-worker leaves: today's manual read of `key` ended `status`."""
    (run,) = [
        r
        for r in world.runs.competitor_runs(TENANT, world.brand)
        if f"{r.account_network}:{r.account_handle}" == key
    ]
    claimed = world.runs.claim(TENANT, run.id, now=CLOCK)
    assert claimed is not None and claimed.started_at is not None
    world.runs.finish(
        TENANT,
        run.id,
        status=status,
        now=CLOCK,
        credits=0,
        cost_usd=Decimal("0"),
        brief_hash="b",
        started_at=claimed.started_at,
    )


async def test_a_read_that_ends_refreshes_the_panel_and_the_lists(world: _World) -> None:
    from .discover_reels import DiscoverReelsState

    world.ok_run()
    _competitors(world, *(f"rival{i}" for i in range(7)))
    state, proxy = _screen_state()
    await _open(proxy)
    outside = next(r for r in state.competitor_rows if not r["weekly"])
    await _read_now(proxy, outside["key"])
    # still reading: the clock reads the rows again and asks for nothing else
    assert await DiscoverReelsState.refresh_competitors.fn(proxy) is None
    _finish(world, outside["key"], STATUS_OK)
    follow = await DiscoverReelsState.refresh_competitors.fn(proxy)
    assert follow[0] is DiscoverReelsState.refilter  # the new reels reach the lists
    row = next(r for r in state.competitor_rows if r["key"] == outside["key"])
    assert row["state"] == rivals.STATE_DONE and row["message"] == rivals.DONE_TEXT
    assert not state.competitors_reading
    assert world.paid == []


async def test_a_press_the_cap_refuses_says_so_even_after_a_failed_read(
    world: _World,
) -> None:
    world.ok_run()
    _competitors(world, *(f"rival{i}" for i in range(7)))
    state, proxy = _screen_state()
    await _open(proxy)
    outside = next(r for r in state.competitor_rows if not r["weekly"])
    await _read_now(proxy, outside["key"])
    _finish(world, outside["key"], "error")  # today's read failed
    ledger = usage.InMemoryUsageStore()
    usage.configure_store(ledger)  # the conftest puts the default back after the test
    ledger.events.append(
        usage.UsageEvent(
            tenant_id=TENANT,
            brand_id=None,
            vendor=usage.SCRAPECREATORS,
            feature="reels_list",
            credits=usage.DAILY_CAP,
            usd_estimate=Decimal("0"),
            pricing_table_version=usage.PRICING_TABLE_VERSION,
            request_key=f"seed:{uuid4()}",
            created_at=CLOCK,
        )
    )
    await _read_now(proxy, outside["key"])
    row = next(r for r in state.competitor_rows if r["key"] == outside["key"])
    assert row["state"] == rivals.STATE_LIMIT
    assert row["message"] == rivals.DAILY_LIMIT_TEXT


async def test_the_competitors_filter_shows_their_reels_once_read(world: _World) -> None:
    world.ok_run()
    world.runs.upsert_reels(
        TENANT,
        [
            PublicReel(
                network="tiktok",
                reel_id="C1",
                handle="rival",
                taken_at=CLOCK,
                metrics_at=CLOCK,
                parser_version=1,
                caption="Nuestra burger",
                views=5_000,
            )
        ],
    )
    world.runs.save_verdicts(
        TENANT,
        world.brand,
        [
            NewVerdict(
                network="tiktok",
                reel_id="C1",
                brief_hash="b",
                input_hash="iC1",
                fits=True,
                model_id="claude",
                prompt_version="p",
                affinity="producto",
            )
        ],
    )
    state, proxy = _screen_state()
    await _open(proxy)
    await _filter(proxy, state.set_filter("kind", "competencia"))
    assert [c["key"] for c in state.more_reels] == ["tiktok:C1"]
    assert state.empty_kind == ""
    assert world.paid == []


async def test_no_competitor_marked_keeps_rf02s_message_and_no_panel(world: _World) -> None:
    world.ok_run()
    world.repo.clear_label(tenant_id=TENANT, brand_id=world.brand, network="tiktok", handle="rival")
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.competitor_rows == []
    await _filter(proxy, state.set_filter("kind", "competencia"))
    from . import reels_filters_vm

    assert state.empty_kind == reels_filters_vm.EMPTY_NO_COMPETITORS


async def test_another_business_never_sees_the_panel_of_this_one(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from . import discover_reels

    world.ok_run()
    _competitors(world, *(f"rival{i}" for i in range(7)))
    other_brand = uuid4()
    world.repo.add_brand(tenant_id=OTHER, brand_id=other_brand)
    monkeypatch.setattr(
        discover_reels,
        "default_brand_id",
        lambda tenant: world.brand if tenant == TENANT else other_brand,
    )
    state, proxy = _screen_state()
    await _open(proxy)
    outside = next(r for r in state.competitor_rows if not r["weekly"])
    await _read_now(proxy, outside["key"])
    assert state.competitor_rows
    proxy.auth.session_tenant_id = str(OTHER)  # another business logs in, same tab
    await _open(proxy)
    assert state.competitor_rows == [] and state.competitor_busy == ""
    await _read_now(proxy, outside["key"])  # a stale press of A's row does nothing
    await _toggle(proxy, outside["key"])
    assert world.runs.competitor_runs(OTHER, other_brand) == []
    assert len(world.runs.competitor_runs(TENANT, world.brand)) == 1
    assert world.paid == []


def test_the_panel_is_a_drawer_from_the_bar_with_its_clock_outside() -> None:
    """Option A (Deivid, 2026-11-25): «Tus competidores» ends the bar and opens the
    system's drawer; the clock that follows a read lives outside it."""
    import inspect

    from . import discover_reels

    bar = inspect.getsource(discover_reels._filter_bar)
    desktop, phone = bar.split("display=_WIDE")
    # Deivid 2026-11-26, desktop: «Tus competidores» flows with the filters, paired with
    # «Duración» so it is never alone on a row; «Restablecer filtros» comes last
    assert "_with_rivals(_dropdown(AXIS_DURATION, shrink=True), chip=False)" in desktop
    assert desktop.index("_with_rivals(") < desktop.index("_reset_button()")
    assert "rx.separator" not in bar
    pair = inspect.getsource(discover_reels._with_rivals)
    assert 'wrap="nowrap"' in pair and "_rivals_button(chip=chip, shrink=True)" in pair
    # in the pair, «Duración» gives way first, the button's label last
    rivals = inspect.getsource(discover_reels._rivals_button)
    assert 'flex_shrink="1" if shrink else "0"' in rivals and "**_ELLIPSIS" in rivals
    assert int(discover_reels._SHRINK_FIRST) > 1
    # the phone (Deivid 2026-11-26): the chips wrap onto CENTRED lines — no sideways
    # scroll, no chip seen cut off; with a filter on, «Restablecer filtros» goes FIRST
    assert "_with_rivals" not in phone
    order = [
        phone.index("_reset_button(chip=True)"),
        phone.index("_rivals_button(chip=True)"),
        phone.index("_chip_pair(AXIS_NETWORK, AXIS_KIND)"),
        phone.index("_chip_pair(AXIS_ACCOUNT, AXIS_DURATION)"),
    ]
    assert order == sorted(order)
    assert phone.count("_reset_button(") == 1
    for needed in ('wrap="wrap"', 'justify="center"', 'min_width="0"'):
        assert needed in phone, needed
    for gone in ("overflow_x", "scroll_snap", "nowrap"):
        assert gone not in phone, gone
    source = inspect.getsource(discover_reels)
    assert "scroll_snap" not in source and "_NO_SCROLLBAR" not in source
    reset = inspect.getsource(discover_reels._reset_button)
    assert "DiscoverReelsState.filters_on" in reset  # without a filter it is not drawn
    # never wider than the panel: every chip may sit below its content and ellipsize
    button = inspect.getsource(discover_reels._filter_button)
    assert 'max_width="100%"' in button and 'min_width="0"' in button
    assert 'min_width="0"' in rivals and 'overflow="hidden"' in rivals
    assert '"overflow": "hidden"' in button  # the shrinking «Duración» of the pair
    assert "_competitors_drawer(bottom=False)" in bar and "_competitors_drawer(bottom=True)" in bar
    button = inspect.getsource(discover_reels._rivals_button)
    # RF-13: a Radix button of the skin, like the filters beside it — no class of its own
    for needed in ('"users"', "aria_haspopup", "aria_expanded", "rx.button(", "min_height=_TARGET"):
        assert needed in button, needed
    assert "class_name" not in button
    assert "loading_spinner" in button and "competitors_label" in button
    drawer_source = inspect.getsource(discover_reels._competitors_drawer)
    assert "drawer(" in drawer_source and "on_close_auto_focus" in drawer_source
    assert "reels_filters_vm.DONE_LABEL" in drawer_source
    assert "_ticker" not in drawer_source  # closing it never stops the clock
    ideas = inspect.getsource(discover_reels._ideas)
    assert "_ticker(S.refresh_competitors)" in ideas
    row = inspect.getsource(discover_reels._competitor_row)
    assert 'min_height="44px"' in row  # «Ver sus reels ahora»
    assert 'role="checkbox"' in row and "_option_row(" in row  # the 44 px row, empty box
    assert STATUS_OK  # the panel never shows a run's status word


async def test_the_drawer_opens_and_closes_and_needs_competitors(world: _World) -> None:
    world.ok_run()
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.competitor_rows
    state.open_competitors(True)  # the phone's chip: from the bottom
    assert state.competitors_open and state.competitors_bottom
    state.competitors_changed(False)  # Esc / backdrop / «Cerrar»
    assert not state.competitors_open
    state.open_competitors(False)  # the desktop button: from the right
    assert state.competitors_open and not state.competitors_bottom
    state.close_competitors()  # «Listo»
    assert not state.competitors_open
    assert state.competitors_label == "Tus competidores: 1 de 6 los revisamos cada lunes"
    # no competitor marked: no button, no drawer
    world.repo.clear_label(tenant_id=TENANT, brand_id=world.brand, network="tiktok", handle="rival")
    await _open(proxy)
    assert state.competitor_rows == []
    state.open_competitors(False)
    assert not state.competitors_open
    assert world.paid == []


async def test_a_read_that_ends_with_the_drawer_closed_says_so_in_a_toast(
    world: _World,
) -> None:
    from .discover_reels import DiscoverReelsState

    world.ok_run()
    _competitors(world, *(f"rival{i}" for i in range(7)))
    state, proxy = _screen_state()
    await _open(proxy)
    outside = next(r for r in state.competitor_rows if not r["weekly"])
    await _read_now(proxy, outside["key"])
    assert state.competitors_label == "Tus competidores: estamos leyendo sus reels"
    assert not state.competitors_open  # the clock lives outside the drawer
    _finish(world, outside["key"], STATUS_OK)
    events = await DiscoverReelsState.refresh_competitors.fn(proxy)
    assert events[0] is DiscoverReelsState.refilter and len(events) == 2
    toast = str(events[1])
    assert reels_competitors_vm.TOAST_DONE.format(account=outside["label"]) in toast


async def test_a_failed_read_with_the_drawer_closed_toasts_the_failure(world: _World) -> None:
    from .discover_reels import DiscoverReelsState

    world.ok_run()
    _competitors(world, *(f"rival{i}" for i in range(7)))
    state, proxy = _screen_state()
    await _open(proxy)
    outside = next(r for r in state.competitor_rows if not r["weekly"])
    await _read_now(proxy, outside["key"])
    _finish(world, outside["key"], "error")
    events = await DiscoverReelsState.refresh_competitors.fn(proxy)
    assert reels_competitors_vm.TOAST_FAILED.format(account=outside["label"]) in str(events[1])


async def test_with_the_drawer_open_the_row_says_it_and_no_toast(world: _World) -> None:
    from .discover_reels import DiscoverReelsState

    world.ok_run()
    _competitors(world, *(f"rival{i}" for i in range(7)))
    state, proxy = _screen_state()
    await _open(proxy)
    state.open_competitors(False)
    outside = next(r for r in state.competitor_rows if not r["weekly"])
    await _read_now(proxy, outside["key"])
    _finish(world, outside["key"], STATUS_OK)
    events = await DiscoverReelsState.refresh_competitors.fn(proxy)
    assert events == [DiscoverReelsState.refilter]
    row = next(r for r in state.competitor_rows if r["key"] == outside["key"])
    assert row["message"] == rivals.DONE_TEXT
