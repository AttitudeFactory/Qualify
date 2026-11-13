"""A story with a link button (m-25026350): from Tu semana's historia to the story-only
ad wizard — the paid notice first, no organic story, one 9:16 file and preview."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from . import planner_state, promotion_unpublished_provider
from .planner_drawer import _story_ad_offer
from .planner_state import PlannerState
from .planner_vm import ConnectionChoiceVM, build_post_option
from .promotion_state import PromotionState, _unpublished_defaults
from .promotion_story_ui import story_link, story_review
from .promotion_vm import (
    STORY_AD_NOTICE,
    STORY_STEPS,
    WEBSITE_CTA_LABELS,
    AdMediaVM,
    PromotionDraftVM,
    PromotionSourceVM,
    first_problem,
    step_counter,
    step_keys,
    step_problem,
    step_title,
    story_ad_href,
)
from .test_promotion_wizard import valid_form

ZONE = "America/Bogota"
VERTICAL, COVER = str(uuid4()), str(uuid4())


def story_source(kind: str = "images", files: int = 1) -> PromotionSourceVM:
    video = kind == "videos"
    return PromotionSourceVM(
        str(uuid4()),
        "@negocio",
        "Texto de la pieza",
        media_kind=kind,
        story=True,
        vertical_media=[
            AdMediaVM(VERTICAL if n == 0 else str(uuid4()), media_type=kind[:-1])
            for n in range(files)
        ],
        vertical_covers=[AdMediaVM(COVER)] if video else [],
        default_message="Texto de la pieza",
        default_headline="Yogur helado",
        default_link_url="https://negocio.example/menu",
        default_cta_type="ORDER_NOW",
        default_country="CO",
    )


def story_form(single: bool = True, kind: str = "images") -> PromotionDraftVM:
    return replace(
        valid_form(),
        **_unpublished_defaults(story_source(kind, 1 if single else 2), single),
        source_id="s",
        link_url="https://negocio.example/menu",
        cta_type="ORDER_NOW",
    )


# -- the wizard's steps ----------------------------------------------------------------


def test_a_lone_source_and_file_leave_exactly_link_audience_budget_and_review() -> None:
    form = story_form()
    assert form.story and form.single_source and not form.feed_asset_id
    assert step_keys(form) == ("story_link", "story_audience", "budget")
    assert [step_title(form, n) for n in (1, 2)] == ["¿A dónde lleva el botón?", "¿Quién la ve?"]
    # «Paso N de 4»: the review is the last step, counted exactly
    seen = [step_counter(form, form, n, False) for n in (1, 2, 3)]
    assert seen + [step_counter(form, form, 3, True)] == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert not first_problem(form, ZONE)


def test_several_sources_or_files_are_steps_of_their_own() -> None:
    several = story_form(single=False)
    assert step_keys(several) == STORY_STEPS
    one_source = replace(several, single_source=True)
    assert step_keys(one_source) == ("story_media", "story_link", "story_audience", "budget")
    # without the story flag nothing changes for the two-format ad
    assert "story_link" not in step_keys(replace(several, story=False))


def test_the_button_step_checks_link_button_and_text() -> None:
    form = story_form()
    assert "botón" in step_problem(replace(form, cta_type="CALL_NOW"), 1, ZONE)
    assert "https://" in step_problem(replace(form, link_url="http://x.example"), 1, ZONE)
    assert "título" in step_problem(replace(form, headline=" "), 1, ZONE)
    assert "país" in step_problem(replace(form, country="AR"), 2, ZONE)
    assert "CALL_NOW" not in WEBSITE_CTA_LABELS  # «Llamar» never shown as a button


def test_only_the_vertical_file_and_its_cover_gate_a_story() -> None:
    video = story_form(kind="videos")
    assert not first_problem(video, ZONE)  # no 4:5 file, no feed cover needed
    assert "portada" in first_problem(replace(video, vertical_cover_id=""), ZONE)
    assert "vertical" in first_problem(replace(video, vertical_asset_id=""), ZONE)


def test_review_has_one_sandboxed_preview_and_the_safe_zones() -> None:
    rendered = repr(story_review().render())
    assert rendered.count("sandbox") == 1
    # repr escapes accents: match the plain-ASCII part of each zone label
    for words in ("va tu nombre", "va el bot", "Deja esta zona sin texto."):
        assert words in rendered
    assert "No se publica en tu perfil." in rendered
    assert "Llamar" not in repr(story_link().render())


# -- the story ad source and preparation ------------------------------------------------


def test_preparing_a_story_sends_no_feed_file_and_keeps_the_single_preview(monkeypatch) -> None:
    calls: dict = {}

    class Service:
        async def prepare(self, **kwargs: object) -> SimpleNamespace:
            calls.update(kwargs)
            return SimpleNamespace(
                promotion_id=uuid4(),
                review_id=uuid4(),
                recipe_id=uuid4(),
                feed_html="",
                vertical_html="<iframe src='https://www.facebook.com/ads/api/preview_iframe.php?d=1'>",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )

    monkeypatch.setattr(promotion_unpublished_provider, "_service", Service)
    monkeypatch.setattr(
        "Qualify.promotion_provider.safe_preview_url", lambda html: "https://ok" if html else ""
    )
    start = datetime.now() + timedelta(days=1)
    form = replace(
        story_form(kind="videos"),
        budget="25000",
        start_local=start.strftime("%Y-%m-%dT%H:%M"),
        end_local=(start + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M"),
    )
    source = replace(story_source("videos"), ad_account_id=str(uuid4()))
    review = promotion_unpublished_provider.prepare_unpublished(
        uuid4(), uuid4(), uuid4(), form, source, ZONE, str(uuid4())
    )
    assert calls["feed_asset_id"] is None and calls["feed_thumbnail_asset_id"] is None
    assert calls["vertical_asset_id"] == UUID(VERTICAL)
    assert calls["vertical_thumbnail_asset_id"] == UUID(COVER)
    assert calls["form"].cta_type == "ORDER_NOW"
    assert review.preview_url == review.vertical_preview_url == "https://ok"


def test_the_story_link_keeps_the_way_back_to_the_week() -> None:
    piece = str(uuid4())
    assert story_ad_href(piece) == f"/drafts/{piece}/promote?formato=historia"
    assert story_ad_href(piece, "?desde=semana&semana=2026-11-09") == (
        f"/drafts/{piece}/promote?formato=historia&desde=semana&semana=2026-11-09"
    )


def test_the_wizard_keeps_the_story_format_across_its_steps() -> None:
    context = SimpleNamespace(
        busy=False,
        loading=False,
        sources=[story_source()],
        preparation_blocked=False,
        form=story_form(),
        step=1,
        timezone_name=ZONE,
        error="",
        direction="next",
        _piece_id="p",
        _return_params={"formato": "historia"},
    )
    event = PromotionState.next_step.fn(context)
    assert context.step == 2 and "formato=historia" in repr(event)


# -- Tu semana: the option, its notice, and no organic story ------------------------------

_IG = ConnectionChoiceVM(id="c1", label="@bianki", platform="instagram")


def _planner(*ids: str) -> PlannerState:
    state = PlannerState()
    state.connections = [_IG]
    state.monday_iso = "2026-11-09"
    state.today_iso = "2026-11-13"
    state.now_hhmm = "15:10"
    state.tz_name = ZONE
    state.schedulable = [
        build_post_option(
            post_id=post_id,
            title="Promo",
            caption_excerpt="",
            thumbnail_url="https://cdn.example/s.jpg",
            category="story",
            approval="approved",
            detail_href="/drafts/" + post_id,
            is_publishable=True,
            unpublishable_reason="",
            media_types=("IMAGE",),
            image_size=(1080, 1920),
        )
        for post_id in ids
    ]
    state.open_assign_for_post(ids[0])
    return state


def test_the_option_asks_first_and_continuing_schedules_no_story(monkeypatch) -> None:
    piece = str(uuid4())
    state = _planner(piece)
    assert state.plan_rows[0].destination == "story" and state.story_ad_offered
    monkeypatch.setattr(planner_state, "schedule_post", lambda *a, **k: pytest.fail("story"))
    state.ask_story_ad(piece)
    assert state.story_ad_post == piece and state.form_open  # only the notice, still here
    state.dismiss_story_ad()
    assert state.story_ad_post == "" and len(state.plan_items) == 1  # «Mejor no» keeps it
    state.ask_story_ad(piece)
    event = state.continue_story_ad()
    assert f"/drafts/{piece}/promote?formato=historia" in repr(event)
    assert not state.form_open and state.plan_items == []  # nothing left to «Programar»


def test_the_option_is_not_offered_for_a_bigger_plan_or_another_destination() -> None:
    piece = str(uuid4())
    state = _planner(piece)
    state._update_item(piece, destination="post")
    state.ask_story_ad(piece)
    assert state.story_ad_post == ""
    state.plan_items = [*state.plan_items, replace(state.plan_items[0], post_id=str(uuid4()))]
    assert not state.story_ad_offered
    assert state.continue_story_ad() is None


def test_the_notice_says_it_is_paid_before_the_wizard() -> None:
    rendered = repr(_story_ad_offer(SimpleNamespace(post_id="p")).render())
    assert STORY_AD_NOTICE in rendered and "Mejor no" in rendered and "Continuar" in rendered
