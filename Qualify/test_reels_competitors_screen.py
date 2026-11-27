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
    await _filter(proxy, state.toggle_side())  # the competitors' side
    assert [c["key"] for c in state.more_reels] == ["tiktok:C1"]
    assert state.empty_kind == ""
    assert world.paid == []


async def test_no_competitor_marked_keeps_rf02s_message_and_no_panel(world: _World) -> None:
    world.ok_run()
    world.repo.clear_label(tenant_id=TENANT, brand_id=world.brand, network="tiktok", handle="rival")
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.competitor_rows == []
    await _filter(proxy, state.toggle_side())  # the competitors' side
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


def test_the_bar_no_longer_holds_the_panel() -> None:
    """Deivid, 2026-11-27: the bar's «Competidores» switches the side of the reels; the
    panel «Tus competidores» is not in the bar any more (m-25142823 moved it to «Negocios
    parecidos al tuyo»). The reels screen still follows a manual read with its clock."""
    import inspect

    from . import discover_reels

    bar = inspect.getsource(discover_reels._filter_bar)
    desktop, phone = bar.split("class_name=_WIDE_CLASS")
    assert desktop.index("_side_button(chip=False)") < desktop.index("_reset_button()")
    assert "rx.separator" not in bar
    assert phone.index("_filters_button()") < phone.index("_side_button(chip=True)")
    source = inspect.getsource(discover_reels)
    for gone in (
        "scroll_snap",
        "_NO_SCROLLBAR",
        "_with_rivals",
        "_chip_pair",
        "sheet_chip",
        "def _competitors_drawer",
        "def competitors_opener",
        "def _competitor_row(",
    ):
        assert gone not in source, gone
    assert "_competitors_drawer" not in bar and "open_competitors" not in bar
    side = inspect.getsource(discover_reels._side_button)
    assert "on_click=S.toggle_side" in side and "open_competitors" not in side
    reset = inspect.getsource(discover_reels._reset_button)
    assert "DiscoverReelsState.filters_on" in reset  # without a filter it is not drawn
    button = inspect.getsource(discover_reels._filter_button)
    assert "min_width=_CHIP_MIN" in button and 'overflow="hidden"' in button
    ideas = inspect.getsource(discover_reels._ideas)
    assert "_ticker(S.refresh_competitors)" in ideas
    assert STATUS_OK  # the panel never shows a run's status word


def test_the_panel_is_a_section_of_negocios_parecidos() -> None:
    """m-25142823 (Deivid, 2026-11-27): «Tus competidores» is one line under the board of
    «Negocios parecidos al tuyo» — its name, what it does, «3 de 6 marcados» and «Elegir
    competidores», which opens the same panel (the `drawer`, from the bottom on a phone,
    from the right on a wider window). The section reads its rows on mount and follows a
    manual read with the browser clock; the drawer's rows are the reels screen's own state
    (`DiscoverReelsState`), never a copy. Only the system's pieces."""
    import inspect

    from . import brand_kit_editor, competitors_panel

    section = inspect.getsource(brand_kit_editor._referentes_section)
    # on top of the section, before the board (Deivid, 2026-11-27)
    assert "rx.fragment(competitors_section(), _referentes_body())" in section
    panel = inspect.getsource(competitors_panel.competitors_section)
    for needed in (
        "on_mount=[S.load_competitors, rx.call_script(PHONE_MEDIA, callback=S.open_on_arrival)]",
        "_competitors_drawer(bottom=False)",
        "_competitors_drawer(bottom=True)",
        "rx.cond(S.competitors_reading, _ticker(S.refresh_competitors))",
        "competitors_opener()",
        "signal_pill(S.competitors_count",
        "reels_competitors_vm.SECTION_BODY",
        "reels_competitors_vm.SECTION_EMPTY",  # always in view, with no competitor too
        "border_bottom=T.BORDER",
    ):
        assert needed in panel, needed
    assert "rx.cond(S.competitor_rows.length() > 0, line)" not in panel
    drawer_body = inspect.getsource(competitors_panel._competitors_drawer)
    assert "_candidates()" in drawer_body  # mark competitors inside the panel too
    row = inspect.getsource(competitors_panel._competitor_row)
    assert "BrandConnectState.unmark_account(key)" in row  # and unmark them
    candidate = inspect.getsource(competitors_panel._candidate_row)
    assert 'BrandConnectState.move_account(account["key"].to(str), "competencia")' in candidate
    opener = inspect.getsource(competitors_panel.competitors_opener)
    assert "rx.call_script(PHONE_MEDIA, callback=S.open_competitors)" in opener
    assert "id=COMPETITORS_OPENER_ID" in opener and "min_height=_TARGET" in opener
    assert "reels_competitors_vm.OPENER_LABEL" in opener  # its words are its name
    assert "aria_label" not in opener and "title=S.competitors_label" in opener
    assert competitors_panel.COMPETITORS_OPENER_ID in competitors_panel.RIVALS_FOCUS_SCRIPT
    drawer_source = inspect.getsource(competitors_panel._competitors_drawer)
    assert "drawer(" in drawer_source and "on_close_auto_focus" in drawer_source
    assert "reels_filters_vm.DONE_LABEL" in drawer_source
    assert "_ticker" not in drawer_source  # closing it never stops the clock
    row = inspect.getsource(competitors_panel._competitor_row)
    assert 'min_height="44px"' in row  # «Ver sus reels ahora»
    assert 'role="checkbox"' in row and "_option_row(" in row  # the 44 px row, empty box
    assert reels_competitors_vm.OPENER_LABEL == "Elegir competidores"
    assert reels_competitors_vm.SECTION_BODY == (
        "Marca hasta 6 para que cada lunes te traigamos sus reels nuevos."
    )
    rendered = str(brand_kit_editor._referentes_section().render())
    assert competitors_panel.COMPETITORS_OPENER_ID in rendered
    assert rendered.count("q-drawer--bottom") >= 1


async def test_the_section_reads_its_rows_for_the_session_business(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`load_competitors` reads the rows of the logged-in business's brand — even when the
    reels screen was never opened — and opening the panel reads them again; another
    business never sees this one's rows; nothing is paid."""
    from . import discover_reels
    from .discover_reels import DiscoverReelsState

    world.ok_run()
    state, proxy = _screen_state()
    assert state.competitor_rows == []
    await DiscoverReelsState.load_competitors.fn(proxy)
    assert [r["key"] for r in state.competitor_rows] == ["tiktok:rival"]
    assert state._brand_id == str(world.brand)
    assert state.open_competitors(False) is DiscoverReelsState.load_competitors
    assert state.competitors_open and not state.competitors_bottom
    other_brand = uuid4()
    world.repo.add_brand(tenant_id=OTHER, brand_id=other_brand)
    monkeypatch.setattr(
        discover_reels,
        "default_brand_id",
        lambda tenant: world.brand if tenant == TENANT else other_brand,
    )
    proxy.auth.session_tenant_id = str(OTHER)
    await DiscoverReelsState.load_competitors.fn(proxy)
    assert state.competitor_rows == [] and not state.competitors_open
    assert world.paid == []


async def test_unmarking_every_competitor_keeps_the_panel_open(world: _World) -> None:
    """Open, and every competitor unmarked: the panel stays open (it offers the board's
    accounts to mark again, and its opener is always in view)."""
    from .discover_reels import DiscoverReelsState

    world.ok_run()
    state, proxy = _screen_state()
    await DiscoverReelsState.load_competitors.fn(proxy)
    state.open_competitors(True)
    assert state.competitors_open
    world.repo.clear_label(tenant_id=TENANT, brand_id=world.brand, network="tiktok", handle="rival")
    await DiscoverReelsState.load_competitors.fn(proxy)
    assert state.competitor_rows == [] and state.competitors_open


async def test_a_read_for_a_session_that_changed_meanwhile_never_paints(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rows were read for A, and B logged in before they landed: A's rows never show."""
    from . import discover_reels
    from .discover_reels import DiscoverReelsState

    world.ok_run()
    state, proxy = _screen_state()
    real = discover_reels._competitor_rows

    async def rows_then_switch(tenant: UUID, brand: UUID) -> Any:
        found = await real(tenant, brand)
        proxy.auth.session_tenant_id = str(OTHER)  # another business, same tab
        return found

    monkeypatch.setattr(discover_reels, "_competitor_rows", rows_then_switch)
    await DiscoverReelsState.load_competitors.fn(proxy)
    assert state.competitor_rows == [] and state._brand_id == ""
    proxy.auth.session_tenant_id = ""  # no session: nothing is read
    monkeypatch.setattr(discover_reels, "_competitor_rows", real)
    await DiscoverReelsState.load_competitors.fn(proxy)
    assert state.competitor_rows == []


def test_storing_the_sort_reads_the_competitors_again() -> None:
    """m-25142823: a «Compite contigo» added or taken out on the board shows at once in
    «Tus competidores» just under it — both ways the sort is stored chain the free read."""
    import inspect

    from . import creative_wizard_pages as wiz
    from .discover_reels import DiscoverReelsState

    for event in (wiz.BrandConnectState.sync_labels, wiz.BrandConnectState.sync_sort):
        assert "return _competitors_reread()" in inspect.getsource(event.fn)
    assert wiz._competitors_reread() is DiscoverReelsState.load_competitors


def test_the_brand_page_never_refilters_lists_it_never_painted() -> None:
    """A manual read that ends while the owner is on the brand page reads the reels list
    again only when the reels screen painted one (`screen != ""`)."""
    import inspect

    from .discover_reels import DiscoverReelsState

    source = inspect.getsource(DiscoverReelsState.refresh_competitors.fn)
    assert 'lists = self.screen != ""' in source
    assert "[DiscoverReelsState.refilter] if lists else []" in source


async def test_the_drawer_opens_and_closes_and_needs_competitors(world: _World) -> None:
    world.ok_run()
    state, proxy = _screen_state()
    await _open(proxy)
    assert state.competitor_rows
    state.open_competitors(True)  # a phone's window: from the bottom
    assert state.competitors_open and state.competitors_bottom
    state.competitors_changed(False)  # Esc / backdrop / «Cerrar»
    assert not state.competitors_open
    state.open_competitors(False)  # a wider window: from the right
    assert state.competitors_open and not state.competitors_bottom
    state.close_competitors()  # «Listo»
    assert not state.competitors_open
    assert state.competitors_label == "Tus competidores: 1 de 6 los revisamos cada lunes"
    # no competitor marked: the panel still opens — it offers the board's accounts to mark
    world.repo.clear_label(tenant_id=TENANT, brand_id=world.brand, network="tiktok", handle="rival")
    await _open(proxy)
    assert state.competitor_rows == []
    state.open_competitors(False)
    assert state.competitors_open  # Deivid, 2026-11-27: always reachable
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


# --------------------------------------------------------------------------------------
# Deivid's live test of 2026-11-27: always reachable, mark / unmark, from the reels too
# --------------------------------------------------------------------------------------


def test_unmark_takes_the_account_back_to_the_board_and_saves() -> None:
    """«Quitar»: the account leaves «Compite contigo» for the board's «sin clasificar» (its
    label cleared, out of the ranking) and the board saves it (`sync_sort`)."""
    from . import creative_wizard_pages as wiz

    # the board keys its cards by their LABELS (`creator_discovery.account_card`: «TikTok»,
    # «@Rival»); the panel's row keys are the stored identity («tiktok:rival»)
    from . import reels_competitors_vm as rc
    from .creative_wizard_pages import _account_key

    rival = _account_key({"network": "TikTok", "handle": "@Rival"})
    foodie = _account_key({"network": "Instagram", "handle": "@foodie"})
    assert rival == "TikTok:@Rival"
    board = wiz.BrandConnectState()
    board.account_buckets = {rival: "competencia", foodie: "referente"}
    board.influence_order = [foodie, rival]
    from qualify_api.referentes.reels import CompetitorAccount

    stored = CompetitorAccount(network="tiktok", handle="rival", picked=True, weekly=True)
    row_key = rc.rows([stored])[0]["key"]
    assert row_key == "tiktok:rival"
    assert board.unmark_account(row_key) is wiz.BrandConnectState.sync_sort
    assert board.account_buckets == {foodie: "referente"}
    assert board.influence_order == [foodie]
    assert board.unmark_account("tiktok:nobody") is None  # not on the board: nothing saved
    assert board.unmark_account("bad") is None


def test_the_copy_of_the_panel_is_plain_spanish() -> None:
    assert reels_competitors_vm.SECTION_EMPTY == (
        "Aún no tienes competidores. Márcalos abajo con «Compite contigo» o elígelos aquí."
    )
    assert (reels_competitors_vm.REMOVE_LABEL, reels_competitors_vm.ADD_TITLE) == (
        "Quitar",
        "Agregar competidores",
    )
    assert reels_competitors_vm.ADD_BUTTON == "Compite contigo"  # the board's own words
    assert reels_competitors_vm.BUCKET_WORDS == {
        "": "Sin clasificar",
        "referente": "Te inspira",
        "detractor": "No va contigo",
    }


def test_cambiar_competidores_leads_to_the_open_panel_and_back_to_this_side() -> None:
    """On the reels' competitors side, one line over the list says what is on screen and
    offers «Cambiar competidores»: «Negocios parecidos al tuyo» with «Tus competidores»
    open (`abrir=competidores`), and its way back is the reels on the competitors' side
    (`lado=competidores`, still «‹ Ideas de videos»)."""
    import inspect
    from urllib.parse import parse_qs, urlsplit

    from . import discover_reels, reels_filters_vm
    from .catalog_vm import return_label_for, return_path_from_query

    href = urlsplit(discover_reels.CHANGE_COMPETITORS_HREF)
    query = parse_qs(href.query)
    assert href.path == "/brand/kit" and query["seccion"] == ["referentes"]
    assert query["abrir"] == ["competidores"]
    back = return_path_from_query({"volver": query["volver"][0]})
    assert parse_qs(urlsplit(back).query)["lado"] == ["competidores"]
    assert return_label_for(back) == "Ideas de videos"
    ideas = inspect.getsource(discover_reels._ideas)
    assert "rx.cond(S.on_competitors, _change_competitors_line())" in ideas
    line = inspect.getsource(discover_reels._change_competitors_line)
    assert "reels_filters_vm.COMPETITORS_NOTE" in line and "CHANGE_COMPETITORS_HREF" in line
    assert "min_height=_TARGET" in line
    bar = inspect.getsource(discover_reels._filter_bar)
    assert "_change_competitors_line" not in bar  # never a chip of the bar
    assert reels_filters_vm.CHANGE_COMPETITORS == "Cambiar competidores"


async def test_the_reels_come_back_on_the_competitors_side_once(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`?lado=competidores` (the way back from «Cambiar competidores») opens the reels on
    the competitors' side — once for that URL: the owner can switch back to inspirations
    and a later read keeps their choice."""
    from types import SimpleNamespace

    from .discover_reels import DiscoverReelsState

    world.ok_run()
    state, proxy = _screen_state()
    url = SimpleNamespace(
        query_parameters={"modo": "ideas", "lado": "competidores"},
        __str__=lambda self: "/create?modo=ideas&lado=competidores",
    )
    monkeypatch.setattr(
        DiscoverReelsState, "router", property(lambda self: SimpleNamespace(url=url))
    )
    await _open(proxy)
    assert state.filter_kind == "competencia" and state.on_competitors
    await _filter(proxy, state.toggle_side())
    assert state.filter_kind == "referente"
    await _open(proxy)  # «Ver si ya están», same URL: the owner's side stays
    assert state.filter_kind == "referente"
    assert world.paid == []


def test_the_panel_opens_on_arrival_only_when_asked_and_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from .discover_reels import DiscoverReelsState

    state = DiscoverReelsState()
    url = SimpleNamespace(query_parameters={"seccion": "referentes"}, __str__=lambda s: "/a")
    monkeypatch.setattr(
        DiscoverReelsState, "router", property(lambda self: SimpleNamespace(url=url))
    )
    assert state.open_on_arrival(True) is None and not state.competitors_open
    url.query_parameters = {"seccion": "referentes", "abrir": "competidores"}
    assert state.open_on_arrival(True) is DiscoverReelsState.load_competitors
    assert state.competitors_open and state.competitors_bottom
    state.competitors_changed(False)
    assert state.open_on_arrival(False) is None and not state.competitors_open  # once
    # a new round trip always leaves the reels first: `leave` starts the «once» over
    state.leave()
    assert state.open_on_arrival(False) is DiscoverReelsState.load_competitors
    assert state.competitors_open


async def test_two_round_trips_through_cambiar_competidores(
    world: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Independent review: «Cambiar competidores» twice in one session — each time the
    reels come back on the competitors' side (the reels screen was left in between)."""
    from types import SimpleNamespace

    from .discover_reels import DiscoverReelsState

    world.ok_run()
    state, proxy = _screen_state()
    url = SimpleNamespace(query_parameters={"modo": "ideas", "lado": "competidores"})
    monkeypatch.setattr(
        DiscoverReelsState, "router", property(lambda self: SimpleNamespace(url=url))
    )
    for _ in range(2):
        await _open(proxy)  # back from the brand page, `?lado=competidores`
        assert state.filter_kind == "competencia"
        state.leave()  # «Cambiar competidores» leaves the reels again
        assert state.filter_kind == "referente"
    assert world.paid == []


def test_a_drawers_column_is_bounded_so_its_body_scrolls() -> None:
    """Deivid's live test (2026-11-27, 375 px, «Filtros» open): the sheet's column grew to
    its content, so `.q-drawer-body` never scrolled and the foot left the screen. The
    shared rule bounds the primitive's column inside every drawer (bottom and right), the
    body flexes and may shrink, head and foot never shrink."""
    import inspect
    import re
    from pathlib import Path

    from .ui import primitives

    css = (Path(__file__).resolve().parent.parent / "assets" / "qualify.css").read_text(
        encoding="utf-8"
    )
    rule = re.search(r"\.rt-DialogContent\.q-drawer > \.rt-Flex \{(.*?)\}", css, re.S)
    assert rule, "the drawer's column must be bounded"
    for needed in ("flex: 1 1 auto;", "min-height: 0;"):
        assert needed in rule.group(1), needed
    assert ".q-drawer-head, .q-drawer-foot { flex-shrink: 0; }" in css
    source = inspect.getsource(primitives.drawer)
    # the body is the one that scrolls: it flexes and may shrink below its content
    assert 'class_name="q-drawer-body"' in source
    assert 'flex="1"' in source and 'min_height="0"' in source and 'overflow_y="auto"' in source
    assert 'rx.flex(*parts, direction="column"' in source  # the column the rule bounds
