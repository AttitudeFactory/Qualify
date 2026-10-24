"""The hashtag pills on Tu rubro y ubicación (§ request 2026-09-25): typed or suggested,
removable, capped — and, when there are any, THE hashtags the referentes search runs
with (`DiscoverySeed.chosen_hashtags`), so changing them re-runs the search."""

from __future__ import annotations

from qualify_api.hashtags import catalog as hashtag_catalog

from . import creative_wizard_pages as wiz
from . import creator_discovery as cd
from .creative_wizard_pages import (
    BrandConnectState,
    add_pills,
    merge_suggestions,
    seed_with_pills,
)


def _state() -> BrandConnectState:
    state = BrandConnectState()
    state.account_kind = "marca"
    state.rubro_text = "hamburguesería"
    state.country_code = "VE"
    state.city = "Caracas"
    return state


def _type(state: BrandConnectState, text: str) -> None:
    state.new_hashtag = text
    BrandConnectState.add_hashtag.fn(state)


def test_a_typed_hashtag_is_normalised_and_never_repeated() -> None:
    state = _state()
    _type(state, "  #SmashBurger ")
    _type(state, "smashburger")
    assert state.rubro_hashtags == [
        {"tag": "smashburger", "origin": "manual", "reason": "", "model": ""}
    ]
    assert state.new_hashtag == ""


def test_a_hashtag_is_one_word() -> None:
    state = _state()
    _type(state, "comida rapida")
    assert state.rubro_hashtags == []
    assert "una sola palabra" in state.hashtag_note


def test_pills_stop_at_the_cap_and_say_why() -> None:
    pills, note = add_pills(
        [], [{"tag": f"tag{i}", "origin": "manual"} for i in range(cd.CHOSEN_HASHTAGS + 2)]
    )
    assert len(pills) == cd.CHOSEN_HASHTAGS
    assert str(cd.CHOSEN_HASHTAGS) in note


def test_a_pill_can_be_removed() -> None:
    state = _state()
    _type(state, "burger")
    _type(state, "smashburger")
    BrandConnectState.remove_hashtag.fn(state, "burger")
    assert [p["tag"] for p in state.rubro_hashtags] == ["smashburger"]


def test_new_suggestions_replace_old_ones_but_keep_what_the_operator_typed() -> None:
    pills, _ = add_pills(
        [],
        [
            {"tag": "burgerlovers", "origin": "manual"},
            {"tag": "viejo", "origin": "ai", "reason": "antes", "model": "m"},
        ],
    )
    choice = hashtag_catalog.HashtagChoice(
        tags=("hamburguesas", "burgerlovers"),
        by="ai",
        picks={"hamburguesas": {"model": "claude-sonnet-5", "fit": "alta", "reason": "producto"}},
    )
    pills, note = merge_suggestions(pills, choice)
    assert [(p["tag"], p["origin"]) for p in pills] == [
        ("burgerlovers", "manual"),
        ("hamburguesas", "ai"),
    ]
    assert pills[1]["reason"] == "producto" and pills[1]["model"] == "claude-sonnet-5"
    assert note == ""


def test_an_empty_suggestion_says_so_and_a_rule_suggestion_is_marked() -> None:
    _, note = merge_suggestions([], hashtag_catalog.HashtagChoice((), "ai"))
    assert "Agrega las tuyas" in note
    pills, _ = merge_suggestions([], hashtag_catalog.HashtagChoice(("foodie",), "rule"))
    assert pills[0]["origin"] == "catalog"


def test_the_pills_become_the_seed_hashtags_with_their_provenance() -> None:
    pills, _ = add_pills(
        [],
        [
            {"tag": "hamburguesas", "origin": "ai", "reason": "producto", "model": "sonnet"},
            {"tag": "foodie", "origin": "catalog"},
            {"tag": "burgerlovers", "origin": "manual"},
        ],
    )
    seed, picks = seed_with_pills(cd.DiscoverySeed("smash", ("food_drink",)), pills)
    assert seed.chosen_hashtags == ("hamburguesas", "foodie", "burgerlovers")
    assert picks == {
        "hamburguesas": {"suggested_by": "sonnet", "reason": "producto"},
        "foodie": {"suggested_by": "catalogo"},
        "burgerlovers": {},
    }


def test_changing_the_pills_restarts_the_search_on_leaving_the_step() -> None:
    state = _state()
    state.step = wiz._RUBRO_STEP
    state.discovery_answers = state._answers()
    _type(state, "smashburger")
    assert state._answers() != state.discovery_answers
    assert BrandConnectState.next_step.fn(state) == BrandConnectState.run_discovery


def test_a_restart_forgets_the_pills() -> None:
    state = _state()
    _type(state, "smashburger")
    state.hashtag_note = "x"
    state._reset_fields()
    assert (state.rubro_hashtags, state.hashtag_note, state.new_hashtag) == ([], "", "")
