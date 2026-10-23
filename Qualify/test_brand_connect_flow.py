"""The Brand Kit connect flow's step structure and navigation (request 2026-09-11):
"Elige tu plan" removed from both flows, "Lo que te proponemos" skipped for a fresh
start, ¿Eres influencer o una marca? moved before ¿Quién es la marca?, and a new Tu
rubro y ubicación step. The walk itself (`BrandConnectState._is_skipped`) runs for real
on a standalone state — every handler exercised here is synchronous and never calls
`get_state`, so no live `EventContext` is needed (see `test_creative_state.py`'s module
docstring for the general limitation)."""

from __future__ import annotations

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


def _without_session(monkeypatch: pytest.MonkeyPatch, tenant: str = "") -> None:
    """`analyze` asks the session for its tenant (to record the read); here there is
    none — or the given one."""
    from .auth_state import AuthState

    auth = AuthState()
    auth.session_tenant_id = tenant

    async def get_state(_self: object, state_cls: type) -> object:
        assert state_cls is AuthState
        return auth

    monkeypatch.setattr(BrandConnectState, "get_state", get_state)


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


def test_account_kind_comes_before_the_rubro_then_the_identity() -> None:
    titles = _titles(wiz.CONNECT_STEPS)
    kind = titles.index("¿Eres influencer o una marca?")
    assert titles[kind + 1] == "Tu rubro y ubicación"
    assert titles[kind + 2] == "¿Quién es la marca?"
    assert kind == wiz._ACCOUNT_KIND_STEP
    assert wiz.CONNECT_STEPS[wiz._IDENTITY_STEP][0] == "¿Quién es la marca?"


def test_the_slimmed_connect_flow() -> None:
    """§ request 2026-10-05: no Lo que te proponemos, no Google Maps pair, the brief
    inside ¿Quién es la marca?, no voice / tone / examples / restrictions screens."""
    titles = _titles(wiz.CONNECT_STEPS)
    assert titles == [
        "Tu cuenta",
        "Esto es lo que vemos",
        "¿Eres influencer o una marca?",
        "Tu rubro y ubicación",
        "¿Quién es la marca?",
        "¿Ya tienes logo?",
        "Tu logo",
        "Tipografía",
        "Paleta de colores",
        "¿Todo correcto?",
        "¿Cómo ves estas cuentas?",
        "Así se ve tu cuenta hoy",
    ]
    for gone in (
        "Lo que te proponemos",
        "¿Tu negocio está en Google Maps?",
        "Súmate a Google Maps",
        "Tu brief de marca",
        "Tu voz",
        "¿Cómo suena?",
        "Enséñale a hablar",
        "Lo que nunca debe decir",
    ):
        assert gone not in titles and gone not in _titles(wiz.STEPS)


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
        assert _next(state) == wiz._TYPOGRAPHY_STEP
        assert _next(state) == wiz._PALETTE_STEP


def test_an_account_without_a_picture_is_asked_about_its_logo_too() -> None:
    """§ request 2026-09-16: "si la cuenta llega sin logo se muestre la pregunta de
    tengo logo" — with no profile picture at all (a fresh start, and an existing
    account whose read carried none), for a brand."""
    fresh = _state(step=wiz._IDENTITY_STEP, started_without_socials=True, account_kind="marca")
    assert fresh.profile_pic == ""
    assert _next(fresh) == wiz._LOGO_QUESTION_STEP

    no_picture = _existing_account(step=wiz._IDENTITY_STEP, profile_pic="", account_kind="ambas")
    assert _next(no_picture) == wiz._LOGO_QUESTION_STEP
    assert _next(no_picture) == wiz._LOGO_UPLOAD_STEP
    # and back from the palette the walk passes through both logo screens again
    no_picture.step = wiz._PALETTE_STEP
    assert _prev(no_picture) == wiz._TYPOGRAPHY_STEP
    assert _prev(no_picture) == wiz._LOGO_UPLOAD_STEP
    assert _prev(no_picture) == wiz._LOGO_QUESTION_STEP


@pytest.mark.parametrize(
    ("profile_pic", "is_real"),
    [("https://example.com/me.jpg", True), ("https://example.com/default.jpg", False), ("", False)],
)
def test_an_influencer_goes_straight_from_identity_to_the_review(
    profile_pic: str, is_real: bool
) -> None:
    """§ request 2026-09-29: whatever the profile picture, a creator walks neither
    ¿Tienes logo?, Tu logo, Tipografía nor Paleta de colores — forwards or backwards.
    Since the voice screens left the wizard (2026-10-05) the next one is ¿Todo
    correcto?."""
    state = _existing_account(
        step=wiz._IDENTITY_STEP,
        profile_pic=profile_pic,
        account_kind="influencer",
        profile_pic_is_real=is_real,
        logo_from_profile=is_real,
    )
    assert _next(state) == wiz._CONNECT_CONFIRM_STEP
    assert _prev(state) == wiz._IDENTITY_STEP


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
    # Esto es lo que vemos is the last preview screen for everyone since Lo que te
    # proponemos left the flow (§ request 2026-10-05)
    assert state.shows_cancel is True
    assert _next(state) == wiz._ACCOUNT_KIND_STEP
    assert state.shows_cancel is False

    BrandConnectState.answer_account_kind.fn(state, "influencer")
    # the rubro step is always shown now (§ request 2026-09-11), prefilled
    assert state.step == wiz._RUBRO_STEP
    assert state.is_influencer is True and state.rubro_complete is True
    # straight to ¿Quién es la marca?, which carries the brief (§ 2026-10-05)
    assert _next(state) == wiz._IDENTITY_STEP

    # logo, typography and palette skipped (influencer): straight to the review
    assert _next(state) == wiz._CONNECT_CONFIRM_STEP
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
    assert _next(state) == wiz._IDENTITY_STEP
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
    state.step = wiz._LOGO_QUESTION_STEP
    assert BrandConnectState.next_step.fn(state) is None


def test_both_behaves_as_a_brand_for_location() -> None:
    state = _existing_account(
        step=wiz._RUBRO_STEP, account_kind="ambas", country_code="CO", city="Cúcuta"
    )
    assert state.needs_location is True
    # no Google Maps pair any more (§ 2026-10-05): the rubro leads to the identity, and
    # a brand (or both) walks the logo screens after it
    assert _next(state) == wiz._IDENTITY_STEP
    assert _next(state) == wiz._LOGO_QUESTION_STEP


def test_arriving_at_the_rubro_creates_the_hashtags_once() -> None:
    """§ 2026-10-05: the hashtags are created on their own when Tu rubro opens with no
    suggestion yet — not again once there are suggested pills."""
    state = _existing_account(step=wiz._ACCOUNT_KIND_STEP, account_kind="marca")
    fired = BrandConnectState.next_step.fn(state)
    assert state.step == wiz._RUBRO_STEP and "suggest_hashtags" in str(fired)
    state.step = wiz._ACCOUNT_KIND_STEP
    state.rubro_hashtags = [{"tag": "smashburger", "origin": "ai", "reason": "", "model": ""}]
    assert BrandConnectState.next_step.fn(state) is None


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
    assert titles[wiz._SORT_STEP] == "¿Cómo ves estas cuentas?"
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
    # `_apply_phase` adds the backend path of the card's picture (2026-09-14) and the
    # keys the AI review writes, empty for a card stored before it (2026-09-25)
    assert state.local_accounts == [
        {**wiz._CARD_DEFAULTS, **card, "avatar_src": "/avatar/tiktok/x"}
    ]

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


def test_a_detected_profile_picture_preanswers_the_question_and_skips_only_tu_logo() -> None:
    """§ request 2026-09-21: a brand or "ambas" is ALWAYS asked ¿Tienes logo? — a real
    profile picture arrives as the selected answer ("Mi foto de perfil es mi logo"), and
    only Tu logo, which has nothing left to ask, is skipped."""
    for kind in ("marca", "ambas"):
        state = _existing_account(
            step=wiz._IDENTITY_STEP, account_kind=kind, logo_from_profile=True
        )
        assert _next(state) == wiz._LOGO_QUESTION_STEP
        assert _next(state) == wiz._TYPOGRAPHY_STEP  # Tipografía is asked either way
        assert _prev(state) == wiz._LOGO_QUESTION_STEP
        assert _prev(state) == wiz._IDENTITY_STEP


def test_the_hashtag_input_only_shows_after_its_plus() -> None:
    """§ request 2026-09-30: the pills end in a "+"; the input appears only after it,
    and adding a hashtag, Escape or leaving it empty puts the "+" back."""
    state = _state()
    assert state.adding_hashtag is False
    BrandConnectState.open_hashtag_input.fn(state)
    assert state.adding_hashtag is True
    BrandConnectState.set_new_hashtag.fn(state, "#StreetFood")
    BrandConnectState.add_hashtag.fn(state)
    assert [p["tag"] for p in state.rubro_hashtags] == ["streetfood"]
    assert state.adding_hashtag is False

    BrandConnectState.open_hashtag_input.fn(state)
    BrandConnectState.hashtag_input_blur.fn(state, "  ")
    assert state.adding_hashtag is False

    # leaving the input with something typed adds it, like Enter
    BrandConnectState.open_hashtag_input.fn(state)
    BrandConnectState.set_new_hashtag.fn(state, "#Tacos")
    BrandConnectState.hashtag_input_blur.fn(state, "#Tacos")
    assert [p["tag"] for p in state.rubro_hashtags] == ["streetfood", "tacos"]
    assert state.adding_hashtag is False and state.new_hashtag == ""

    # a typed value that is not a hashtag stays in the open input, with the reason
    BrandConnectState.open_hashtag_input.fn(state)
    BrandConnectState.set_new_hashtag.fn(state, "dos palabras")
    BrandConnectState.hashtag_input_blur.fn(state, "dos palabras")
    assert state.adding_hashtag is True and state.new_hashtag == "dos palabras"
    assert "una sola palabra" in state.hashtag_note

    BrandConnectState.hashtag_input_key.fn(state, "Escape")
    assert state.adding_hashtag is False and state.new_hashtag == ""


async def test_a_live_profile_read_is_recorded_in_the_creator_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ 2026-10-01: Analizar's live read becomes a row of the creator history (the
    series the organic growth estimate needs); a cached read is not recorded again."""
    from uuid import UUID

    from . import growth_provider

    profile = {
        "username": "nibbles",
        "fullName": "Nibbles",
        "bio": "",
        "category": "",
        "followers": 1_500,
        "following": 10,
        "postsCount": 40,
        "profilePicUrl": "",
        "fetchedAt": 1_790_000_000.0,
        "recentPosts": [
            {
                "postId": "v1",
                "takenAt": 1_789_900_000,
                "likes": 50,
                "comments": 2,
                "views": 900,
                "shares": 3,
                "aiGenerated": True,
                "aiLabel": "detected",
                "aiSource": "Sora",
            },
            {"takenAt": 1_789_900_001, "likes": 1, "comments": 0, "views": 2},  # no id: no row
        ],
    }
    recorded: list[tuple[UUID, str, str, int]] = []

    def record(tenant_id: UUID, network: str, handle: str, read: dict[str, object]) -> int:
        assert read is profile
        recorded.append((tenant_id, network, handle, len(read["recentPosts"])))
        return 1

    monkeypatch.setattr(growth_provider, "record_profile_read", record)
    from . import creator_cache_provider as cache

    cached: dict[tuple[UUID, str, str], dict[str, object]] = {}
    monkeypatch.setattr(cache, "cached_snapshot", lambda t, n, h: cached.get((t, n, h)))
    monkeypatch.setattr(
        cache, "remember_snapshot", lambda t, n, h, p: cached.__setitem__((t, n, h), p)
    )
    monkeypatch.setattr(wiz.scrapecreators_client, "fetch_profile_and_posts", lambda n, h: profile)
    brand = UUID("b0000000-0000-4000-8000-0000000000a1")
    monkeypatch.setattr(wiz.account_claims_provider, "claim", lambda _t, _n, _h: (brand, True))
    monkeypatch.setattr(wiz.account_claims_provider, "keep_only", lambda *_a: None)
    tenant = "a0000000-0000-4000-8000-0000000000a1"
    _without_session(monkeypatch, tenant)

    state = BrandConnectState()
    state.network = "tiktok"
    state.username = "@Nibbles"
    async for _ in BrandConnectState.analyze.fn(state):
        pass
    assert recorded == [(UUID(tenant), "tiktok", "@Nibbles", 2)]
    assert state.profile_username == "nibbles"
    # § 2026-10-01: remembered per tenant in Postgres (no JSON), with a time to live
    assert cached == {(UUID(tenant), "tiktok", "@Nibbles"): profile}

    # the same handle again, now served from the tenant's cache: no read, no new row
    monkeypatch.setattr(
        wiz.scrapecreators_client,
        "fetch_profile_and_posts",
        lambda n, h: (_ for _ in ()).throw(AssertionError("no read expected")),
    )
    async for _ in BrandConnectState.analyze.fn(state):
        pass
    assert len(recorded) == 1 and state.profile_username == "nibbles"

    # the rows the provider would write from that read
    read, posts = growth_provider.reads_from_profile("tiktok", "@Nibbles", profile)
    assert (read.handle, read.followers, read.posts_count) == ("nibbles", 1_500, 40)
    assert [(p.post_id, p.shares, p.ai_generated, p.ai_source) for p in posts] == [
        ("v1", 3, True, "Sora")
    ]
