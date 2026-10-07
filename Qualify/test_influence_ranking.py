"""The influence ranking on Resultados e insights (§ request 2026-09-29): the sorted
referentes and competencia as cards in influence order, the accounts added by hand
pinned first, a card only moving inside its own list and group, and the order stored
as `brand_account_labels.position`. Fully offline."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_api.referentes import MemoryReferentesRepository

from . import creative_wizard_pages as wiz
from . import referentes_provider as rp
from .creative_wizard_pages import BrandConnectState

TENANT = UUID("5e5e0000-0000-4000-8000-0000000000c1")


def _card(handle: str, *, manual: bool = False) -> dict[str, str]:
    card = {"network": "Instagram", "handle": f"@{handle}", "url": "", "followers": "1"}
    if manual:
        card["manual"] = "1"
    return card


def _key(handle: str) -> str:
    return f"Instagram:@{handle}"


# -- ranking rules ------------------------------------------------------------------------


def test_pinned_first_then_the_order_then_the_search_order() -> None:
    accounts = [
        {**_card("a"), "key": _key("a")},
        {**_card("b"), "key": _key("b")},
        {**_card("m1", manual=True), "key": _key("m1")},
        {**_card("c"), "key": _key("c")},
        {**_card("m2", manual=True), "key": _key("m2")},
    ]
    ranked = wiz._rank(accounts, [_key("c"), _key("m2")])
    assert [a["key"] for a in ranked] == [
        _key("m2"),  # pinned, ordered
        _key("m1"),  # pinned, never ordered
        _key("c"),  # ordered
        _key("a"),  # never ordered: the order the search found them
        _key("b"),
    ]
    assert [a["group"] for a in ranked] == ["pinned", "pinned", "rest", "rest", "rest"]
    assert [a["rank"] for a in ranked] == ["1", "2", "3", "4", "5"]


def test_a_move_never_crosses_between_pinned_and_the_rest() -> None:
    ranked = wiz._rank(
        [
            {**_card("m1", manual=True), "key": _key("m1")},
            {**_card("m2", manual=True), "key": _key("m2")},
            {**_card("a"), "key": _key("a")},
            {**_card("b"), "key": _key("b")},
        ],
        [],
    )
    assert wiz._move_in_ranking(ranked, _key("m2"), 0) == [
        _key("m2"),
        _key("m1"),
        _key("a"),
        _key("b"),
    ]
    assert wiz._move_in_ranking(ranked, _key("b"), 2) == [
        _key("m1"),
        _key("m2"),
        _key("b"),
        _key("a"),
    ]
    assert wiz._move_in_ranking(ranked, _key("a"), 1) is None  # into the pinned
    assert wiz._move_in_ranking(ranked, _key("m1"), 3) is None  # out of the pinned
    assert wiz._move_in_ranking(ranked, _key("zz"), 0) is None
    assert wiz._move_in_ranking(ranked, _key("a"), 9) is None


def _state() -> BrandConnectState:
    state = BrandConnectState()
    state.sector_accounts = [
        wiz.card_view(_card("a")),
        wiz.card_view(_card("b")),
        wiz.card_view(_card("c")),
    ]
    state.kept_accounts = [wiz.card_view(_card("m1", manual=True))]
    state.account_buckets = {
        _key("a"): "referente",
        _key("b"): "referente",
        _key("c"): "competencia",
        _key("m1"): "referente",
    }
    return state


def test_the_state_ranks_each_bucket_on_its_own() -> None:
    state = _state()
    assert [a["key"] for a in state.ranked_referentes] == [_key("m1"), _key("a"), _key("b")]
    assert [a["key"] for a in state.ranked_competencia] == [_key("c")]


def test_dragging_a_card_onto_another_takes_its_place() -> None:
    state = _state()
    BrandConnectState.rank_pick.fn(state, _key("b"))
    fired = BrandConnectState.rank_drop.fn(state, _key("a"))
    assert fired is not None and "sync_order" in str(fired)
    assert [a["key"] for a in state.ranked_referentes] == [_key("m1"), _key("b"), _key("a")]
    # both buckets end up in the stored order, one after the other
    assert state.influence_order == [_key("m1"), _key("b"), _key("a"), _key("c")]
    assert state.rank_dragging == ""


def test_a_drop_across_groups_or_lists_does_nothing() -> None:
    state = _state()
    BrandConnectState.rank_pick.fn(state, _key("a"))
    assert BrandConnectState.rank_drop.fn(state, _key("m1")) is None  # onto a pinned one
    BrandConnectState.rank_pick.fn(state, _key("a"))
    assert BrandConnectState.rank_drop.fn(state, _key("c")) is None  # onto the competencia
    assert BrandConnectState.rank_drop.fn(state, _key("b")) is None  # nothing lifted
    assert state.influence_order == []


def test_with_only_one_kind_sorted_its_ranking_still_reorders() -> None:
    """§ request 2026-10-06: "si por casualidad solo hay referentes o competencia igual
    quiero que se pueda mutar la lista" — the other grid is simply not there."""
    for only, ranked in (("referente", "ranked_referentes"), ("competencia", "ranked_competencia")):
        state = BrandConnectState()
        state.sector_accounts = [wiz.card_view(_card(h)) for h in ("a", "b", "c")]
        state.account_buckets = {_key(h): only for h in ("a", "b", "c")}
        assert state.has_ranking
        BrandConnectState.rank_pick.fn(state, _key("c"))
        assert BrandConnectState.rank_drop.fn(state, _key("a")) is not None
        assert [a["key"] for a in getattr(state, ranked)] == [_key("c"), _key("a"), _key("b")]


def test_only_detractores_sorted_is_no_ranking() -> None:
    state = BrandConnectState()
    state.sector_accounts = [wiz.card_view(_card("a"))]
    state.account_buckets = {_key("a"): "detractor"}
    assert not state.has_ranking


# -- storage ------------------------------------------------------------------------------


@pytest.fixture
def brand(monkeypatch: pytest.MonkeyPatch) -> UUID:
    memory = MemoryReferentesRepository()
    monkeypatch.setattr(rp, "REPOSITORY", memory)
    brand_id = uuid4()
    memory.add_brand(tenant_id=TENANT, brand_id=brand_id)
    return brand_id


def test_the_order_round_trips_through_the_labels(brand: UUID) -> None:
    cards = [_card("a"), _card("b"), _card("c")]
    rp.write_labels(
        TENANT,
        brand,
        None,
        {_key("a"): "referente", _key("b"): "referente", _key("c"): "competencia"},
    )
    assert rp.load_order(TENANT, brand, cards) == []  # labeled, never ordered

    rp.write_order(TENANT, brand, [_key("b"), _key("a"), _key("c")])
    assert rp.load_order(TENANT, brand, cards) == [_key("b"), _key("a"), _key("c")]

    # re-labeling keeps the position; an unlabeled account is never given one
    rp.write_labels(TENANT, brand, None, {_key("a"): "competencia"})
    rp.write_order(TENANT, brand, [_key("zz")])
    assert rp.load_order(TENANT, brand, cards) == [_key("b"), _key("a"), _key("c")]


def test_a_negative_position_is_refused(brand: UUID) -> None:
    with pytest.raises(ValueError):
        rp.REPOSITORY.set_positions(
            tenant_id=TENANT, brand_id=brand, positions={("instagram", "a"): -1}
        )


def test_the_card_is_the_control_and_the_grid_sizes_itself() -> None:
    """§ request 2026-09-29: no arrows, no link icon and no 2/3 switch — a click opens
    the profile (`data-profile-url`), a long press drags, and the width picks 3, 2 or 1
    columns."""
    rendered = str(wiz._ranking_panel())
    assert "q-rank-card" in rendered and "data-rank-group" in rendered
    assert "data-profile-url" in rendered
    for gone in ("chevron-left", "chevron-right", "external-link", "segmented", "columns-3"):
        assert gone not in rendered.lower()
    assert not hasattr(BrandConnectState, "rank_move")


def test_the_read_account_picture_goes_through_the_proxy() -> None:
    """§ request 2026-09-29: never the vendor's signed URL straight in an `<img>`."""
    state = BrandConnectState()
    state.network = "instagram"
    state.profile_username = "leomarisreyes.dev"
    state.profile_pic = "https://scontent.cdninstagram.com/v/pic.jpg?oe=1"
    assert state.profile_avatar_src.startswith("/avatar/instagram/leomarisreyes.dev?u=")
