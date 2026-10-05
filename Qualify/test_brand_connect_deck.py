"""The Referente, competencia o detractor deck after the 2026-09-14 revision: it must
show a card the moment a category's search lands (regression), every card carries the
backend path of its picture, a decision names the zone that flashes, and running out
of accounts to sort moves the deck on by itself."""

from __future__ import annotations

import pytest

from . import creative_wizard_pages as wiz
from .creative_wizard_pages import BrandConnectState


async def _instant_sleep(_seconds: float) -> None:
    """Stands in for `asyncio.sleep` so the auto-advance tests below don't actually
    wait `_STAGE_ADVANCE_DELAY`."""
    return None


def _card(handle: str) -> dict[str, str]:
    return {
        "handle": handle,
        "network": "TikTok",
        "followers": "1K",
        "likes": "",
        "url": "u",
        "blurb": "",
    }


_PHASE_ACCOUNT_VARS = {"sector_accounts", "national_accounts", "local_accounts"}
_PHASE_TITLE_VARS = {"sector_title", "national_title", "local_title"}
_PHASE_NOTE_VARS = {"sector_note", "national_note", "local_note"}


def _deps(var_name: str) -> set[str]:
    """The base vars Reflex will recompute `var_name` for — what the dependency
    tracker reads out of the computed var's bytecode, followed through the computed
    vars it depends on (`current_card` → `stage_pool` → the phase lists)."""
    own = BrandConnectState.get_full_name()
    computed_vars = BrandConnectState.computed_vars
    seen: set[str] = set()
    base: set[str] = set()
    pending = [var_name]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if name not in computed_vars:
            base.add(name)
            continue
        pending.extend(computed_vars[name]._deps(objclass=BrandConnectState).get(own, set()))
    return base


def test_the_deck_recomputes_when_a_category_lands() -> None:
    """Regression (reported 2026-09-14): the step opened EMPTY and only showed cards
    after Siguiente + Anterior. The deck's vars read the phase lists through
    `getattr(self, f"{key}_accounts")`, which Reflex's bytecode-based tracker cannot
    see, so a phase landing (`_apply_phase` → `sector_accounts = […]`) dirtied
    nothing — until `sort_stage` changed and forced a recompute. The readers are
    static now; this pins the dependency set so it cannot silently go back."""
    for var in (
        "discovered_accounts",
        "stage_pool",
        "current_card",
        "has_current_card",
        "stage_remaining",
    ):
        assert _PHASE_ACCOUNT_VARS <= _deps(var), var
    assert _PHASE_TITLE_VARS <= _deps("stage_title")
    assert _PHASE_NOTE_VARS <= _deps("stage_note")
    assert _PHASE_NOTE_VARS <= _deps("stage_failed")
    assert (_PHASE_TITLE_VARS | _PHASE_NOTE_VARS | {"discovering"}) <= _deps("stage_pending")


def test_every_card_gets_the_backend_path_of_its_picture() -> None:
    state = BrandConnectState()
    BrandConnectState._apply_phase(
        state,
        {
            "key": "sector",
            "title": "Referentes del sector",
            "accounts": [
                {
                    "handle": "@a",
                    "network": "TikTok",
                    "avatar": "https://p16.tiktokcdn.com/x.jpeg?s=1",
                },
                {"handle": "@b", "network": "Instagram"},  # a cached result from before pictures
            ],
        },
    )
    assert [a["avatar_src"] for a in state.sector_accounts] == [
        "/avatar/tiktok/a?u=https%3A%2F%2Fp16.tiktokcdn.com%2Fx.jpeg%3Fs%3D1",
        "/avatar/instagram/b",
    ]
    assert (
        state.current_card["avatar_src"]
        == "/avatar/tiktok/a?u=https%3A%2F%2Fp16.tiktokcdn.com%2Fx.jpeg%3Fs%3D1"
    )


def test_a_decision_names_the_zone_that_flashes_and_undo_clears_it() -> None:
    state = BrandConnectState()
    state.sector_accounts = [
        {
            "handle": "@a",
            "network": "TikTok",
            "followers": "1K",
            "likes": "",
            "url": "u",
            "blurb": "",
        }
    ]
    assert state.hit_bucket == ""
    BrandConnectState.send_current.fn(state, "competencia")
    assert state.hit_bucket == "competencia" and state.fly_direction == "right"
    BrandConnectState.undo_last.fn(state)
    assert state.hit_bucket == "" and state.fly_direction == ""
    # the pointer drag never calls `start_drag`: `drop_into` takes the card in the middle
    BrandConnectState.drop_into.fn(state, "detractor")
    assert state.hit_bucket == "detractor" and state.fly_direction == ""
    assert state.account_buckets == {"TikTok:@a": "detractor"}
    BrandConnectState.drop_into.fn(state, "referente")  # nothing left in the middle: no-op
    assert state.account_buckets == {"TikTok:@a": "detractor"}
    BrandConnectState._clear_discovery(state)
    assert state.hit_bucket == ""


def test_the_zones_are_the_tap_targets_and_the_button_row_is_gone() -> None:
    assert not hasattr(wiz, "_deck_button")
    assert not hasattr(wiz, "_DragCard")  # the pointer script drags a plain box
    assert [bucket for bucket, *_ in wiz._DECK_ZONES] == ["referente", "competencia", "detractor"]
    assert {area for *_, area in wiz._DECK_ZONES} == {"left", "right", "down"}
    assert issubclass(wiz._DropZone, wiz.rx.el.Button)


def test_the_deck_card_opens_the_profile_and_drops_the_ver_perfil_link() -> None:
    """§ request 2026-09-14: "dandole click se pueda ir a ver el perfil" — the whole
    card is now the profile link (via `assets/deck-drag.js`'s `data-profile-url`),
    so the separate `rx.link` row `_deck_face` used to render is gone. Checked
    against the source directly (not a rendered tree) — consistent with the rest of
    this test suite, which stays off live component rendering."""
    import inspect

    assert "data-profile-url" in inspect.getsource(wiz._deck_card)
    face_source = inspect.getsource(wiz._deck_face)
    assert "rx.link" not in face_source and "Ver perfil" not in face_source
    assert "Toca para ver el perfil" in face_source
    assert "Mantén presionado para arrastrar" in face_source


def test_the_zone_labels_are_wrapped_for_the_pop_animation() -> None:
    """§ request 2026-09-14: "quites el fondo de las opciones… que las letras y
    flecha sufran un scale" — the title + blurb are grouped under `q-deck-label` so
    they scale together as one block (`assets/qualify.css`'s `.q-deck-zone[data-
    over]`/`[data-hit]` rules target `.q-deck-arrow`/`.q-deck-label`, not the panel
    itself)."""
    import inspect

    source = inspect.getsource(wiz._deck_zone)
    assert "q-deck-label" in source and "q-deck-arrow" in source


# --------------------------------------------------------------------------------------
# running out of accounts moves the deck on by itself (§ request 2026-09-14: "que
# cuando se acaben los referentes pase a la siguiente categoria y si no hay
# categorias que vaya a la otra view")
# --------------------------------------------------------------------------------------


def test_assign_chains_advance_stage_exactly_when_the_pool_empties() -> None:
    state = BrandConnectState()
    state.sector_accounts = [_card("@a"), _card("@b")]

    # one card left after this: nothing to chain yet
    assert BrandConnectState.assign.fn(state, "TikTok:@a", "referente") is None
    # the last one: chains the auto-advance
    assert (
        BrandConnectState.assign.fn(state, "TikTok:@b", "competencia")
        is BrandConnectState.advance_stage_if_exhausted
    )
    # reverting never chains, even with an empty pool right before it
    assert BrandConnectState.assign.fn(state, "TikTok:@b", "") is None


def test_send_current_and_drop_into_propagate_the_chained_event() -> None:
    tap_state = BrandConnectState()
    tap_state.sector_accounts = [_card("@a")]
    assert (
        BrandConnectState.send_current.fn(tap_state, "referente")
        is BrandConnectState.advance_stage_if_exhausted
    )

    drop_state = BrandConnectState()
    drop_state.sector_accounts = [_card("@a")]
    assert (
        BrandConnectState.drop_into.fn(drop_state, "detractor")
        is BrandConnectState.advance_stage_if_exhausted
    )


def test_assign_does_not_chain_while_the_category_is_pending_or_failed() -> None:
    pending = BrandConnectState()
    pending.sector_accounts = [_card("@a")]
    pending.discovering = True
    assert BrandConnectState.assign.fn(pending, "TikTok:@a", "referente") is None

    failed = BrandConnectState()
    failed.sector_accounts = [_card("@a")]
    failed.sector_note = "No pudimos completar esta búsqueda ahora. Inténtalo más tarde."
    assert BrandConnectState.assign.fn(failed, "TikTok:@a", "referente") is None


async def test_advance_stage_if_exhausted_moves_to_the_next_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiz.asyncio, "sleep", _instant_sleep)
    state = BrandConnectState()
    state.sort_stage = 0  # "sector" — not the last of the three
    # sector already sorted; national has something left (an EMPTY next category would
    # be skipped — § 2026-09-30, `test_finishing_a_category_jumps_over_an_empty_one`)
    state.sector_accounts = [_card("@s")]
    state.account_buckets = {"TikTok:@s": "referente"}
    state.national_accounts = [_card("@n")]
    state.stage_cursor = 2
    async for _ in BrandConnectState.advance_stage_if_exhausted.fn(state):
        pass
    assert state.sort_stage == 1 and state.stage_cursor == 0


async def test_the_last_category_done_stays_put_until_continuar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ request 2026-10-05 ("no quiero que se vaya a la otra view directamente, quiero
    que eso sea manual"): on the last category `advance_stage_if_exhausted` neither
    changes the stage nor chains `advance_to_insights` — the deck says "Todas
    clasificadas" and Continuar is the only way to Resultados e insights (that path is
    covered in `test_brand_connect_flow.py`)."""
    monkeypatch.setattr(wiz.asyncio, "sleep", _instant_sleep)
    state = BrandConnectState()
    last = len(wiz.creator_discovery.PHASES) - 1  # "local"
    state.sort_stage = last
    state.step = wiz._SORT_STEP
    yielded = [event async for event in BrandConnectState.advance_stage_if_exhausted.fn(state)]
    assert BrandConnectState.advance_to_insights not in yielded
    assert state.sort_stage == last and state.step == wiz._SORT_STEP
    rendered = str(wiz._connect_step_sort())
    assert "Pulsa Continuar para ver tus resultados" in rendered


async def test_advance_stage_if_exhausted_cancels_when_the_stage_changed_meanwhile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `Reintentar`, or more cards landing, between the decision and the delayed
    check must cancel the auto-advance — it must never yank the deck out from under
    a category that turned out to still have something in it."""
    state = BrandConnectState()
    state.sort_stage = 0

    async def sleep_then_refill(_seconds: float) -> None:
        state.sector_accounts = [_card("@z")]

    monkeypatch.setattr(wiz.asyncio, "sleep", sleep_then_refill)
    async for _ in BrandConnectState.advance_stage_if_exhausted.fn(state):
        pass
    assert state.sort_stage == 0  # a card showed up in the meantime: stayed put


# --------------------------------------------------------------------------------------
# the loading screen in front of the sort step (§ request 2026-09-14: "una pantalla de
# carga antes de Referente, competencia o detractor para obligar al usuario a esperar")
# --------------------------------------------------------------------------------------


def test_the_sort_step_waits_while_the_search_runs() -> None:
    state = BrandConnectState()
    state.step = wiz._SORT_STEP
    state.discovering = True
    assert state.waiting_for_referentes is True
    state.discovering = False
    assert state.waiting_for_referentes is False
    # any other step never shows it, even mid-search
    state.step = wiz._SORT_STEP - 1
    state.discovering = True
    assert state.waiting_for_referentes is False
    assert {"step", "discovering"} <= _deps("waiting_for_referentes")


def test_the_loading_screen_lists_each_category_as_it_lands() -> None:
    state = BrandConnectState()
    state.discovering = True
    state.discovery_running = "Referentes del sector"
    assert [(r["title"], r["status"]) for r in state.discovery_progress] == [
        ("Referentes del sector", "running"),
        ("Referentes nacionales", "pending"),
        ("Referentes locales", "pending"),
    ]
    state.sector_title = "Referentes del sector"
    state.discovery_running = "Referentes en Venezuela"
    assert [(r["title"], r["status"]) for r in state.discovery_progress] == [
        ("Referentes del sector", "done"),
        ("Referentes en Venezuela", "running"),
        ("Referentes locales", "pending"),
    ]
    # a category that failed or found nothing still counts as done
    state.national_note = "No pudimos completar esta búsqueda ahora. Inténtalo más tarde."
    assert [r["status"] for r in state.discovery_progress] == ["done", "done", "running"]
    assert (_PHASE_TITLE_VARS | _PHASE_NOTE_VARS | {"discovering"}) <= _deps("discovery_progress")


def test_arriving_at_the_sort_step_starts_a_search_that_never_ran() -> None:
    def at_confirm() -> BrandConnectState:
        state = BrandConnectState()
        state.profile_followers_count = 598_781
        state.profile_pic = "https://example.com/pic.jpg"
        state.sector = "technology"
        state.account_kind = "influencer"
        state.step = wiz._CONNECT_CONFIRM_STEP
        return state

    never_ran = at_confirm()
    assert BrandConnectState.next_step.fn(never_ran) is BrandConnectState.run_discovery
    assert never_ran.step == wiz._SORT_STEP

    already_ran = at_confirm()
    already_ran.discovery_ran = True
    assert BrandConnectState.next_step.fn(already_ran) is None
    assert already_ran.step == wiz._SORT_STEP


# -- empty categories are skipped (§ request 2026-09-30) ---------------------------------


def test_the_shown_category_follows_every_phase_it_may_skip() -> None:
    """The category on screen is derived from ALL three phases (an empty one is jumped
    over), so a phase landing, failing or finishing must recompute it."""
    everything = _PHASE_ACCOUNT_VARS | _PHASE_TITLE_VARS | _PHASE_NOTE_VARS
    for var in ("stage_key", "stage_label", "is_first_stage", "is_last_stage"):
        assert everything | {"discovering", "sort_stage"} <= _deps(var), var
    assert everything | {"discovering"} <= _deps("nothing_to_sort")


def test_an_empty_category_is_skipped_both_ways() -> None:
    state = BrandConnectState()
    state.national_accounts = [_card("@n")]
    # the deck opens on the first category with something in it
    assert state.stage_key == "national" and state.stage_label == "Categoría 2 de 3"
    assert state.is_first_stage and state.is_last_stage
    assert state.nothing_to_sort is False

    state.local_accounts = [_card("@l")]
    assert not state.is_last_stage
    BrandConnectState.next_sort_stage.fn(state)
    assert state.stage_key == "local"
    BrandConnectState.prev_sort_stage.fn(state)
    assert state.stage_key == "national"  # the empty sector is not a stop
    BrandConnectState.prev_sort_stage.fn(state)
    assert state.stage_key == "national"


def test_a_failed_or_loading_category_is_not_skipped() -> None:
    state = BrandConnectState()
    state.sector_note = "No pudimos completar esta búsqueda ahora. Inténtalo más tarde."
    state.local_accounts = [_card("@l")]
    assert state.stage_key == "sector" and state.stage_failed  # its Reintentar stays

    state = BrandConnectState()
    state.discovering = True
    assert state.stage_key == "sector" and state.stage_pending
    assert state.nothing_to_sort is False


def test_nothing_to_sort_when_every_category_came_back_empty() -> None:
    state = BrandConnectState()
    assert state.nothing_to_sort is True
    assert state.stage_key == "sector" and not state.has_current_card
    state.local_accounts = [_card("@l")]
    assert state.nothing_to_sort is False and state.stage_key == "local"


async def test_finishing_a_category_jumps_over_an_empty_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(wiz.asyncio, "sleep", _instant_sleep)
    state = BrandConnectState()
    state.sector_accounts = [_card("@s")]
    state.local_accounts = [_card("@l")]
    # sorting the sector's last card chains the auto-advance…
    assert BrandConnectState.assign.fn(state, "TikTok:@s", "referente") == (
        BrandConnectState.advance_stage_if_exhausted
    )
    async for _ in BrandConnectState.advance_stage_if_exhausted.fn(state):
        pass
    # …which jumps over the empty national category
    assert state.stage_key == "local" and state.has_current_card


def test_the_referentes_progress_bar_moves_one_category_at_a_time() -> None:
    state = BrandConnectState()
    state.discovering = True
    assert state.discovery_percent == 12  # the first category is being searched
    state.sector_title = "Referentes del sector"
    assert state.discovery_percent == 45
    state.national_title = "Nacionales"
    state.local_title = "Locales"
    state.discovering = False
    assert state.discovery_percent == 100
