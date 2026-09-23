"""The Brand Kit connect flow's step structure and navigation (request 2026-09-11):
"Elige tu plan" removed from both flows, "Lo que te proponemos" skipped for a fresh
start, ¿Eres influencer o una marca? moved before ¿Quién es la marca?, and a new Tu
rubro y ubicación step. The walk itself (`BrandConnectState._is_skipped`) runs for real
on a standalone state — every handler exercised here is synchronous and never calls
`get_state`, so no live `EventContext` is needed (see `test_creative_state.py`'s module
docstring for the general limitation)."""

from __future__ import annotations

from pathlib import Path

import pytest

from . import creative_wizard_pages as wiz
from .creative_wizard_pages import BrandConnectState


def _titles(steps: tuple[tuple[str, str], ...]) -> list[str]:
    return [title for title, _ in steps]


def _state(**fields: object) -> BrandConnectState:
    state = BrandConnectState()
    for name, value in fields.items():
        setattr(state, name, value)
    return state


def _existing_account(**fields: object) -> BrandConnectState:
    """A profile read that is not a fresh start: real followers, a picture, the rubro
    detected from the profile."""
    defaults: dict[str, object] = {
        "profile_followers_count": 598_781,
        "profile_pic": "https://example.com/pic.jpg",
        "sector": "technology",
    }
    return _state(**{**defaults, **fields})


def _next(state: BrandConnectState) -> int:
    BrandConnectState.next_step.fn(state)
    return state.step


def _prev(state: BrandConnectState) -> int:
    BrandConnectState.prev_step.fn(state)
    return state.step


# --------------------------------------------------------------------------------------
# structure
# --------------------------------------------------------------------------------------


def test_plan_step_is_gone_from_both_flows() -> None:
    assert "Elige tu plan" not in _titles(wiz.STEPS)
    assert "Elige tu plan" not in _titles(wiz.CONNECT_STEPS)
    assert not hasattr(wiz, "PLANS")
    assert "subscription" not in wiz.BrandWizardState.__fields__


def test_account_kind_comes_before_the_rubro_and_the_maps_pair() -> None:
    titles = _titles(wiz.CONNECT_STEPS)
    kind = titles.index("¿Eres influencer o una marca?")
    assert titles[kind + 1] == "Tu rubro y ubicación"
    assert titles[kind + 2] == "¿Tu negocio está en Google Maps?"
    assert kind == wiz._ACCOUNT_KIND_STEP
    assert wiz.CONNECT_STEPS[wiz._IDENTITY_STEP][0] == "¿Quién es la marca?"
    assert wiz.CONNECT_STEPS[wiz._RECOMMENDATIONS_STEP][0] == "Lo que te proponemos"


def test_the_maps_pair_was_swapped_with_identity() -> None:
    """§ request 2026-09-15: the Google Maps pair runs where ¿Quién es la marca? used
    to. § request 2026-09-16: the logo pair sits right before Paleta de colores."""
    titles = _titles(wiz.CONNECT_STEPS)
    assert titles[wiz._MAPS_QUESTION_STEP : wiz._PALETTE_STEP + 1] == [
        "¿Tu negocio está en Google Maps?",
        "Súmate a Google Maps",
        "¿Quién es la marca?",
        "¿Tienes logo?",
        "Tu logo",
        "Paleta de colores",
    ]


def test_the_logo_pair_is_asked_while_the_profile_picture_has_not_been_taken() -> None:
    """§ request 2026-09-16: merely HAVING a profile picture is not a logo — skipping the
    pair on that made uploading a logo (or asking for one through the brief)
    unreachable. Since 2026-09-21 the pair is skipped only once `analyze` has taken a REAL
    picture as the logo (`logo_from_profile`); until then, and for a default or missing
    picture, it is asked."""
    for kind in ("marca", "ambas"):
        state = _existing_account(step=wiz._IDENTITY_STEP, account_kind=kind)
        assert state.profile_pic != ""
        assert _next(state) == wiz._LOGO_QUESTION_STEP
        assert _next(state) == wiz._LOGO_UPLOAD_STEP
        assert _next(state) == wiz._PALETTE_STEP


def test_an_account_without_a_picture_is_asked_about_its_logo_too() -> None:
    """§ request 2026-09-16: "si la cuenta llega sin logo se muestre la pregunta de
    tengo logo" — with no profile picture at all (a fresh start, and an existing
    account whose read carried none), both as a brand and as a creator."""
    fresh = _state(step=wiz._IDENTITY_STEP, started_without_socials=True, account_kind="marca")
    assert fresh.profile_pic == ""
    assert _next(fresh) == wiz._LOGO_QUESTION_STEP

    for kind in ("ambas", "influencer"):
        no_picture = _existing_account(step=wiz._IDENTITY_STEP, profile_pic="", account_kind=kind)
        assert _next(no_picture) == wiz._LOGO_QUESTION_STEP
        assert _next(no_picture) == wiz._LOGO_UPLOAD_STEP
        # and back from the palette the walk passes through both logo screens again
        no_picture.step = wiz._PALETTE_STEP
        assert _prev(no_picture) == wiz._LOGO_UPLOAD_STEP
        assert _prev(no_picture) == wiz._LOGO_QUESTION_STEP


def test_an_influencer_with_a_real_picture_is_not_asked_about_a_logo() -> None:
    """§ request 2026-09-21: a creator whose real profile picture was detected already has
    their logo — neither ¿Tienes logo? nor Tu logo is walked, forwards or backwards."""
    state = _existing_account(
        step=wiz._IDENTITY_STEP, account_kind="influencer", logo_from_profile=True
    )
    assert _next(state) == wiz._PALETTE_STEP
    assert _prev(state) == wiz._IDENTITY_STEP


@pytest.mark.parametrize("profile_pic", ["https://example.com/default.jpg", ""])
def test_an_influencer_without_a_real_picture_is_asked_about_a_logo(profile_pic: str) -> None:
    """§ request 2026-09-21 ("solo la pregunta en influencer cuando detecte que no tiene
    logo"): no picture at all, or the network's default silhouette — the detection then
    takes nothing (`logo_from_profile` stays False) and the question is asked."""
    state = _existing_account(
        step=wiz._IDENTITY_STEP,
        profile_pic=profile_pic,
        account_kind="influencer",
        profile_pic_is_real=False,
        logo_from_profile=False,
    )
    assert _next(state) == wiz._LOGO_QUESTION_STEP
    assert _next(state) == wiz._LOGO_UPLOAD_STEP
    assert _next(state) == wiz._PALETTE_STEP


def test_account_kind_offers_both_as_a_third_answer() -> None:
    assert [key for key, _, _ in wiz.ACCOUNT_KINDS] == ["marca", "influencer", "ambas"]


# --------------------------------------------------------------------------------------
# fresh start ("No, todavía no" or a brand-new account)
# --------------------------------------------------------------------------------------


def test_start_without_socials_resets_and_flags_a_fresh_walk() -> None:
    state = _existing_account(step=9, account_kind="marca")
    BrandConnectState.start_without_socials.fn(state)
    assert state.started_without_socials is True
    assert state.step == 0 and state.account_kind == "" and state.sector == ""

    BrandConnectState.clear_entry.fn(state)
    assert state.started_without_socials is False


def test_fresh_start_skips_recommendations_and_always_asks_the_rubro() -> None:
    state = _existing_account(step=wiz._PROFILE_STEP, started_without_socials=True)
    assert state.shows_cancel is True  # Esto es lo que vemos is the last preview screen

    assert _next(state) == wiz._ACCOUNT_KIND_STEP
    # the rubro was detected, but a fresh start is still asked
    BrandConnectState.answer_account_kind.fn(state, "influencer")
    assert state.step == wiz._RUBRO_STEP
    assert _prev(state) == wiz._ACCOUNT_KIND_STEP
    assert _prev(state) == wiz._PROFILE_STEP


def test_a_brand_new_account_counts_as_a_fresh_start_too() -> None:
    state = _state(step=wiz._PROFILE_STEP, profile_followers_count=12)
    assert state.is_fresh_start is True
    assert _next(state) == wiz._ACCOUNT_KIND_STEP


# --------------------------------------------------------------------------------------
# existing account
# --------------------------------------------------------------------------------------


def test_existing_influencer_is_still_asked_the_rubro_then_walks_to_identity() -> None:
    state = _existing_account(step=wiz._PROFILE_STEP)
    assert state.shows_cancel is False
    assert _next(state) == wiz._RECOMMENDATIONS_STEP
    assert state.shows_cancel is True
    assert _next(state) == wiz._ACCOUNT_KIND_STEP

    BrandConnectState.answer_account_kind.fn(state, "influencer")
    # the rubro step is always shown now (§ request 2026-09-11), prefilled
    assert state.step == wiz._RUBRO_STEP
    assert state.is_influencer is True and state.rubro_complete is True
    assert _next(state) == wiz._IDENTITY_STEP

    # Maps pair skipped (influencer); the logo pair is asked while no real profile picture
    # was taken as the logo (`test_an_influencer_with_a_real_picture_is_not_asked_...`)
    assert _next(state) == wiz._LOGO_QUESTION_STEP
    assert _next(state) == wiz._LOGO_UPLOAD_STEP
    assert _next(state) == wiz._PALETTE_STEP
    assert _prev(state) == wiz._LOGO_UPLOAD_STEP
    assert _prev(state) == wiz._LOGO_QUESTION_STEP
    assert _prev(state) == wiz._IDENTITY_STEP
    assert _prev(state) == wiz._RUBRO_STEP
    assert _prev(state) == wiz._ACCOUNT_KIND_STEP


def test_a_brand_without_location_is_asked_and_can_go_back_to_the_rubro() -> None:
    state = _existing_account(step=wiz._ACCOUNT_KIND_STEP)
    BrandConnectState.answer_account_kind.fn(state, "marca")
    assert state.step == wiz._RUBRO_STEP
    assert state.rubro_complete is False

    BrandConnectState.set_country_code.fn(state, "CO")
    BrandConnectState.set_city.fn(state, "Cúcuta")
    assert state.rubro_complete is True
    assert _next(state) == wiz._MAPS_QUESTION_STEP
    assert _prev(state) == wiz._RUBRO_STEP


def test_leaving_the_rubro_step_restarts_the_search_only_when_the_seed_changed() -> None:
    state = _existing_account(step=wiz._RUBRO_STEP, account_kind="influencer")
    # the search that started at the profile read was seeded with these answers
    state.discovery_answers = state._answers()
    assert BrandConnectState.next_step.fn(state) is None  # nothing changed → no restart
    assert state.step == wiz._IDENTITY_STEP

    state = _existing_account(step=wiz._RUBRO_STEP, account_kind="influencer")
    state.discovery_answers = state._answers()
    BrandConnectState.set_sector.fn(state, "food_drink")
    fired = BrandConnectState.next_step.fn(state)
    assert fired is not None and "run_discovery" in str(fired)
    # any other step never fires it
    state.step = wiz._IDENTITY_STEP
    assert BrandConnectState.next_step.fn(state) is None


def test_both_behaves_as_a_brand_for_location_and_maps() -> None:
    state = _existing_account(
        step=wiz._RUBRO_STEP, account_kind="ambas", country_code="CO", city="Cúcuta"
    )
    assert state.needs_location is True
    assert _next(state) == wiz._MAPS_QUESTION_STEP

    # "sí" skips Súmate a Google Maps, so the walk lands on ¿Quién es la marca?
    BrandConnectState.answer_has_maps.fn(state, "si")
    assert state.step == wiz._IDENTITY_STEP
    assert _prev(state) == wiz._MAPS_QUESTION_STEP


def test_free_text_rubro_completes_the_step_for_a_brand_but_a_creator_needs_a_category() -> None:
    brand = _existing_account(account_kind="marca", sector="", country_code="CO", city="Cúcuta")
    assert brand.rubro_complete is False
    BrandConnectState.set_rubro_text.fn(brand, "peluquería canina")
    assert brand.rubro_complete is True and brand._rubro_complete() is True

    creator = _existing_account(account_kind="influencer", sector="", rubro_text="peluquería")
    assert creator.rubro_complete is False  # § request: "solo la categoría y la ubicación"
    BrandConnectState.set_sector.fn(creator, "fashion_beauty")
    assert creator.rubro_complete is True


def test_a_creator_does_not_need_a_location() -> None:
    state = _existing_account(account_kind="influencer", sector="food_drink")
    assert state.needs_location is False
    assert state.rubro_complete is True
    assert _existing_account(account_kind="influencer", sector="").rubro_complete is False


def test_the_sort_step_sits_between_confirm_and_insights() -> None:
    titles = _titles(wiz.CONNECT_STEPS)
    assert titles[wiz._CONNECT_CONFIRM_STEP] == "¿Todo correcto?"
    assert titles[wiz._SORT_STEP] == "Referente, competencia o detractor"
    assert wiz._SORT_STEP == wiz.CONNECT_LAST - 1
    state = _existing_account(step=wiz._CONNECT_CONFIRM_STEP, account_kind="influencer")
    assert _next(state) == wiz._SORT_STEP
    assert _next(state) == wiz.CONNECT_LAST


def test_sorting_accounts_by_tap_and_by_drop() -> None:
    a = {
        "handle": "@a",
        "network": "TikTok",
        "followers": "1K",
        "likes": "",
        "url": "u",
        "blurb": "",
    }
    b = {
        "handle": "@b",
        "network": "Instagram",
        "followers": "2K",
        "likes": "",
        "url": "u",
        "blurb": "",
    }
    state = _state(sector_accounts=[a, b], national_accounts=[a])  # `a` found twice → once
    assert [x["key"] for x in state.discovered_accounts] == ["TikTok:@a", "Instagram:@b"]
    assert len(state.unsorted_accounts) == 2 and state.has_sorted is False

    BrandConnectState.assign.fn(state, "TikTok:@a", "referente")
    assert [x["handle"] for x in state.referente_accounts] == ["@a"]
    assert [x["handle"] for x in state.unsorted_accounts] == ["@b"]

    BrandConnectState.start_drag.fn(state, "Instagram:@b")
    BrandConnectState.drop_into.fn(state, "detractor")
    assert state.dragging == ""
    assert [x["handle"] for x in state.detractor_accounts] == ["@b"]
    assert state.unsorted_accounts == [] and state.has_sorted is True

    # moving between buckets, and back to the pool
    BrandConnectState.assign.fn(state, "Instagram:@b", "competencia")
    assert [x["handle"] for x in state.competencia_accounts] == ["@b"]
    BrandConnectState.assign.fn(state, "Instagram:@b", "")
    assert [x["handle"] for x in state.unsorted_accounts] == ["@b"]
    # a nonsense bucket is a "quitar" too, never a new bucket
    BrandConnectState.assign.fn(state, "TikTok:@a", "loquesea")
    assert state.account_buckets == {}

    # a drop with nothing picked up takes the card in the middle (the pointer drag of
    # 2026-09-14 never calls `start_drag`): the pool is [@a, @b], so @a goes
    BrandConnectState.drop_into.fn(state, "referente")
    assert state.account_buckets == {"TikTok:@a": "referente"}
    # …and with the middle empty it is a no-op
    BrandConnectState.assign.fn(state, "Instagram:@b", "competencia")
    BrandConnectState.drop_into.fn(state, "detractor")
    assert state.account_buckets == {"TikTok:@a": "referente", "Instagram:@b": "competencia"}


def test_a_new_search_clears_the_buckets() -> None:
    state = _state(account_buckets={"TikTok:@a": "referente"}, dragging="x")
    state._clear_discovery()
    assert state.account_buckets == {} and state.dragging == ""


def test_the_walk_never_leaves_the_flow() -> None:
    state = _existing_account(step=wiz.CONNECT_LAST)
    assert _next(state) == wiz.CONNECT_LAST
    state = _existing_account(step=1)
    assert _prev(state) == 0


# --------------------------------------------------------------------------------------
# discovery results into state
# --------------------------------------------------------------------------------------


def test_apply_phase_fills_the_phase_and_explains_a_failed_empty_one() -> None:
    state = _state()
    card = {"handle": "@x", "network": "TikTok", "followers": "12K", "likes": "", "url": "u"}
    state._apply_phase({"key": "local", "title": "Referentes en Cúcuta", "accounts": [card]})
    assert state.local_title == "Referentes en Cúcuta"
    # `_apply_phase` adds the backend path of the card's picture (2026-09-14)
    assert state.local_accounts == [{**card, "avatar_src": "/avatar/tiktok/x"}]

    state._apply_phase({"key": "sector", "title": "t", "accounts": [], "errors": ["402"]})
    assert state.sector_accounts == []
    assert "No pudimos" in state.sector_note

    state._apply_phase({"key": "nope", "title": "ignored"})
    assert state.national_title == ""


def test_sorting_goes_category_by_category_and_a_failed_one_never_blocks() -> None:
    a = {
        "handle": "@a",
        "network": "TikTok",
        "followers": "1K",
        "likes": "",
        "url": "u",
        "blurb": "",
    }
    b = {
        "handle": "@b",
        "network": "TikTok",
        "followers": "1K",
        "likes": "",
        "url": "u",
        "blurb": "",
    }
    state = _state(
        sector_accounts=[a],
        national_note="No pudimos completar esta búsqueda ahora. Inténtalo más tarde.",
        local_accounts=[b],
        local_title="Referentes en Cúcuta",
    )
    assert state.stage_key == "sector" and state.stage_label == "Categoría 1 de 3"
    assert [x["handle"] for x in state.stage_pool] == ["@a"]
    assert state.is_first_stage and not state.is_last_stage

    BrandConnectState.assign.fn(state, "TikTok:@a", "referente")
    assert [x["handle"] for x in state.stage_referente] == ["@a"] and state.stage_pool == []

    BrandConnectState.next_sort_stage.fn(state)
    assert state.stage_key == "national" and state.stage_failed is True
    assert state.stage_pool == [] and state.stage_referente == []  # the sector's card stays there

    BrandConnectState.next_sort_stage.fn(state)
    assert state.stage_key == "local" and state.is_last_stage
    assert state.stage_title == "Referentes en Cúcuta"
    assert [x["handle"] for x in state.stage_pool] == ["@b"]
    BrandConnectState.next_sort_stage.fn(state)  # clamped
    assert state.sort_stage == 2
    BrandConnectState.prev_sort_stage.fn(state)
    assert state.stage_key == "national"

    # still searching → pending, not failed
    state = _state(discovering=True)
    assert state.stage_pending is True and state.stage_failed is False
    state._clear_discovery()
    assert state.sort_stage == 0


def test_the_deck_shows_one_account_and_moves_on_after_each_decision() -> None:
    cards = [
        {
            "handle": f"@{n}",
            "network": "TikTok",
            "followers": "1K",
            "likes": "",
            "url": "u",
            "blurb": "",
        }
        for n in ("a", "b", "c")
    ]
    state = _state(sector_accounts=cards)
    assert state.current_card["handle"] == "@a" and state.stage_remaining == 3

    BrandConnectState.skip_card.fn(state)
    assert state.current_card["handle"] == "@b"
    BrandConnectState.send_current.fn(state, "referente")
    assert [x["handle"] for x in state.stage_referente] == ["@b"]
    # the cursor stayed inside the shrunken pool: next up is @c
    assert state.current_card["handle"] == "@c" and state.stage_remaining == 2

    assert state.can_undo is True
    BrandConnectState.undo_last.fn(state)
    assert state.stage_referente == [] and state.stage_remaining == 3 and state.can_undo is False

    BrandConnectState.start_drag.fn(state, "TikTok:@c")
    BrandConnectState.drop_into.fn(state, "detractor")
    assert [x["handle"] for x in state.stage_detractor] == ["@c"]
    BrandConnectState.send_current.fn(state, "competencia")
    BrandConnectState.send_current.fn(state, "referente")
    assert state.has_current_card is False and state.current_card == {}
    BrandConnectState.send_current.fn(state, "referente")  # nothing left: a no-op
    BrandConnectState.skip_card.fn(state)
    # after the undo the deck was back on @b; @c left by drag, so @b went next, then @a
    assert state.account_buckets == {
        "TikTok:@c": "detractor",
        "TikTok:@b": "competencia",
        "TikTok:@a": "referente",
    }
    # changing category starts its deck from the top
    state.stage_cursor = 2
    BrandConnectState.next_sort_stage.fn(state)
    assert state.stage_cursor == 0


def test_a_decision_launches_a_ghost_of_the_card_the_way_it_went() -> None:
    a = {
        "handle": "@a",
        "network": "TikTok",
        "followers": "1K",
        "likes": "",
        "url": "u",
        "blurb": "",
    }
    state = _state(sector_accounts=[a])
    assert state.fly_direction == "" and state.is_dragging is False

    # a tap launches the ghost the way the card went…
    BrandConnectState.send_current.fn(state, "referente")
    assert state.fly_direction == "left" and state.fly_card["handle"] == "@a"
    assert state.fly_token == 1
    BrandConnectState.undo_last.fn(state)

    # …a pointer drop does not (the operator just watched the real card land there),
    # but the decision still counts (`fly_token`) so the panel flashes
    BrandConnectState.start_drag.fn(state, "TikTok:@a")
    assert state.is_dragging is True
    BrandConnectState.drop_into.fn(state, "referente")
    assert state.fly_direction == "" and state.hit_bucket == "referente"
    assert state.fly_token == 2 and state.is_dragging is False
    assert [x["handle"] for x in state.stage_referente] == ["@a"]

    BrandConnectState.undo_last.fn(state)
    assert state.fly_direction == ""  # coming back is not a flight
    BrandConnectState.send_current.fn(state, "detractor")
    assert state.fly_direction == "down" and state.fly_token == 3
    state._clear_discovery()
    assert state.fly_card == {} and state.fly_direction == ""


async def test_analyze_never_seeds_from_a_concurrent_tenants_profile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The cross-tenant race this regression-guards: `analyze()` used to save its own
    read to the one global, non-tenant-keyed snapshot file and then blindly re-read
    THAT FILE (`scrapecreators_client.load_profile_snapshot`, no network/handle check)
    instead of just using the profile it had already fetched. In a real multi-session
    backend, another tenant's own `save_profile_snapshot` landing in that window handed
    this session someone else's real business profile — reproduced directly against
    `scrapecreators_client` before this fix (two interleaved saves, then a blind
    re-read, returned the SECOND tenant's profile to the FIRST caller).

    Simulates the worst case directly: `save_profile_snapshot` here does the real save
    AND THEN a second tenant's save on top of it, in the same call — the exact
    interleaving a concurrent session could produce. `analyze()` must still end up with
    tenant A's own profile, because it no longer reads the shared file back at all."""
    monkeypatch.setattr(wiz.scrapecreators_client, "load_cached_profile", lambda *a, **k: None)

    tenant_a_profile = {
        "username": "tenant_a_real_business",
        "fullName": "Tenant A Real Business",
        "bio": "",
        "category": "",
        "followers": 111,
        "profilePicUrl": "",
    }
    snapshot_path = tmp_path / "shared_snapshot.json"
    real_save = wiz.scrapecreators_client.save_profile_snapshot  # before it gets patched below

    def _fetch(_network: str, _handle: str) -> dict[str, object]:
        return tenant_a_profile

    def _save_then_another_tenant_interleaves(
        network: str, handle: str, profile: dict[str, object]
    ) -> None:
        real_save(network, handle, profile, path=snapshot_path)
        # A DIFFERENT session's own save, landing in the same window a blind re-read
        # (the code this test guards against reintroducing) would have been exposed to.
        real_save(
            "instagram",
            "tenant_b_handle",
            {"username": "tenant_b_real_business", "followers": 222},
            path=snapshot_path,
        )

    monkeypatch.setattr(wiz.scrapecreators_client, "fetch_profile_and_posts", _fetch)
    monkeypatch.setattr(
        wiz.scrapecreators_client, "save_profile_snapshot", _save_then_another_tenant_interleaves
    )
    monkeypatch.setattr(
        wiz.creator_discovery,
        "seed_from_profile",
        lambda _profile: wiz.creator_discovery.DiscoverySeed(
            handle="tenant_a_real_business", niches=()
        ),
    )

    state = BrandConnectState()
    state.network = "instagram"
    state.username = "tenant_a_handle"

    async for _ in BrandConnectState.analyze.fn(state):
        pass

    # Sanity check the race actually happened on the shared file (proves this test
    # exercises the real interleaving, not a no-op):
    assert (
        wiz.scrapecreators_client.load_profile_snapshot(path=snapshot_path)["username"]
        == "tenant_b_real_business"
    )
    # ...yet tenant A's own session must never have picked that up.
    assert state.profile_username == "tenant_a_real_business"
    assert state.profile_fullname == "Tenant A Real Business"
    assert state.error == ""


def test_a_detected_profile_picture_preanswers_the_question_and_skips_only_tu_logo() -> None:
    """§ request 2026-09-21: a brand or "ambas" is ALWAYS asked ¿Tienes logo? — a real
    profile picture arrives as the selected answer ("Mi foto de perfil es mi logo"), and
    only Tu logo, which has nothing left to ask, is skipped."""
    for kind in ("marca", "ambas"):
        state = _existing_account(
            step=wiz._IDENTITY_STEP, account_kind=kind, logo_from_profile=True
        )
        assert _next(state) == wiz._LOGO_QUESTION_STEP
        assert _next(state) == wiz._PALETTE_STEP
        assert _prev(state) == wiz._LOGO_QUESTION_STEP
        assert _prev(state) == wiz._IDENTITY_STEP
