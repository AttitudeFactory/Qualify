"""N3 (m-25142902): a story ad is seen as one in «Anuncios», and a second story ad of the
same piece needs the owner's choice — on a reload or another phone too (the backend
re-checks under a lock: `packages/api/tests/test_ad_unpublished_db.py`)."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from qualify_api.ads.unpublished import STORY_DUPLICATE, StoryAdExists

from . import ad_results_provider, promotion_state, promotion_unpublished_provider
from .ad_results_page import _ad
from .promotion_entry import card_promotion_link
from .promotion_page import promotion_index
from .promotion_state import PromotionState
from .promotion_story_ui import story_duplicate
from .promotion_vm import (
    STORY_AD_LABEL,
    STORY_CREATE_ANOTHER,
    STORY_HAS_AD,
    STORY_SEE_EXISTING,
    STORY_SEE_PIECE,
    PromotionReviewVM,
)
from .test_ad_results import summary
from .test_promotion_story import ZONE, story_form, story_source
from .test_promotion_story_blocks import _context
from .test_promotion_wizard import ActionContext


def _story_context() -> ActionContext:
    context = ActionContext()
    context.sources = [replace(story_source(), unavailable_reason="")]
    context.form = replace(story_form(), source_id=context.sources[0].id)
    context.review = PromotionReviewVM()
    context.needs_help = context.video_waiting = False
    context.story_existing, context.story_existing_href, context._duplicate_of = "", "", ""
    return context


@pytest.mark.asyncio
async def test_opening_a_historia_that_has_a_story_ad_warns_first(monkeypatch) -> None:
    context = _context({"formato": "historia"})
    monkeypatch.setattr(promotion_state, "story_block_view", lambda *a: ("", "", ""))
    monkeypatch.setattr(promotion_state, "load_sources", lambda *a, **k: ([story_source()], ZONE))
    monkeypatch.setattr(promotion_state, "existing_story_ad", lambda *a: ("r1", "/promotions/p1"))
    _ = [event async for event in PromotionState.load.fn(context)]
    assert (context.story_existing, context.story_existing_href) == ("r1", "/promotions/p1")
    assert context._duplicate_of == ""


@pytest.mark.asyncio
async def test_nothing_is_prepared_until_the_owner_chooses_another(monkeypatch) -> None:
    context = _story_context()
    context.story_existing = "r1"
    calls: list = []

    def prepare(*args: object, **kwargs: object) -> PromotionReviewVM:
        calls.append(kwargs)
        return PromotionReviewVM(recipe_id="r2", review_id="v", preview_url="https://ok")

    monkeypatch.setattr(promotion_state, "prepare_unpublished", prepare)
    await context._remote(confirm=False)
    assert calls == []  # the warning stands: no paused campaign at Meta
    PromotionState.create_another_story_ad.fn(context)
    assert context.story_existing == "" and context._duplicate_of == "r1"
    await context._remote(confirm=False)
    assert calls == [{"duplicate_of": "r1"}]
    # Its own story ad is never a «duplicate» of this session's next preparation.
    assert context._duplicate_of == "r2"


@pytest.mark.asyncio
async def test_another_phone_got_there_first_and_the_warning_names_it(monkeypatch) -> None:
    context = _story_context()
    promotion = uuid4()
    recipe = uuid4()

    def refused(*args: object, **kwargs: object) -> None:
        raise StoryAdExists(recipe, promotion)

    monkeypatch.setattr(promotion_state, "prepare_unpublished", refused)
    await context._remote(confirm=False)
    assert context.error == "" and context.story_existing == str(recipe)
    assert context.story_existing_href == f"/promotions/{promotion}"


def test_the_existing_story_ad_lookup_never_fails_the_wizard(monkeypatch) -> None:
    import qualify_api.ads.unpublished_repository as repository

    piece, recipe, promotion = uuid4(), uuid4(), uuid4()
    monkeypatch.setattr(repository, "story_ads", lambda *a: {piece: (recipe, promotion)})
    assert promotion_unpublished_provider.existing_story_ad(uuid4(), piece) == (
        str(recipe),
        f"/promotions/{promotion}",
    )
    monkeypatch.setattr(repository, "story_ads", lambda *a: {piece: (recipe, None)})
    assert promotion_unpublished_provider.existing_story_ad(uuid4(), piece)[1] == "/promotions"

    def broken(*args: object) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(repository, "story_ads", broken)
    assert promotion_unpublished_provider.existing_story_ad(uuid4(), piece) == ("", "")


def test_the_warning_offers_both_ways_and_blocks_the_preview_button() -> None:
    rendered = repr(story_duplicate().render())
    for text in ("story_existing_href", "create_another_story_ad"):
        assert text in rendered
    assert STORY_SEE_EXISTING.split()[0] in rendered and "Crear otro" in rendered
    assert STORY_CREATE_ANOTHER == "Crear otro anuncio" and "por separado" in STORY_DUPLICATE
    assert "story_existing" in repr(promotion_index().render())


def test_a_story_ad_in_the_list_says_so_with_its_picture_and_its_piece(monkeypatch) -> None:
    piece = uuid4()
    row = replace(
        summary(), caption="", story=True, story_image_key="t/k.png", content_draft_id=piece
    )
    vm = ad_results_provider.summary_vm(row)
    assert vm.story and vm.title == "Anuncio de tu historia" and vm.fix_href == f"/drafts/{piece}"
    assert not ad_results_provider.summary_vm(summary()).story
    monkeypatch.setattr(ad_results_provider, "list_promotion_results", lambda **k: (row,))
    monkeypatch.setattr(ad_results_provider, "story_image", lambda tenant, key: "/r2media/" + key)
    (listed,) = ad_results_provider.load_ads(uuid4())
    assert listed.story_image == "/r2media/t/k.png"
    rendered = repr(_ad(_var_row()).render())
    assert STORY_AD_LABEL in rendered and STORY_SEE_PIECE in rendered
    assert "story_image" in rendered


def _var_row():  # noqa: ANN202 — the list's foreach var
    from .ad_results_state import AdResultsState

    return AdResultsState.ads[0]


def test_a_story_ad_that_cannot_be_shown_has_no_picture_not_an_error() -> None:
    assert ad_results_provider.story_image(uuid4(), "") == ""
    assert ad_results_provider.story_image(uuid4(), "not-an-r2-key") == ""


def test_the_card_says_the_historia_already_has_a_story_ad() -> None:
    from .planner_state import PlannerState

    rendered = repr(card_promotion_link(PlannerState.unscheduled[0]).render())
    assert "story_ad_exists" in rendered and STORY_HAS_AD in rendered
