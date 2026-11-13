"""A story with a link button (m-25026350): from Tu semana's historia to the story-only
ad wizard — the paid notice first, no organic story, one 9:16 file and preview."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from . import planner_state, promotion_state, promotion_unpublished_provider
from .ad_enhancements_vm import BrandEnhancementsVM
from .ad_health_vm import AccountHealthVM
from .planner_drawer import _story_ad_choice, _story_ad_offer
from .planner_state import PlannerState
from .planner_vm import ConnectionChoiceVM, build_post_option
from .promotion_state import PromotionState, _unpublished_defaults
from .promotion_story_ui import story_link, story_review
from .promotion_vm import (
    STORY_AD_OPTION,
    STORY_STEPS,
    UNPUBLISHED_SOURCE_TITLE,
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
from .test_promotion_wizard import PIECE, ActionContext, valid_form

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
    for words in ("va tu nombre", "va el bot", "Instagram las tapa."):
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


def test_preparing_a_story_image_sends_no_cover_at_all(monkeypatch) -> None:
    calls: dict = {}

    class Service:
        async def prepare(self, **kwargs: object) -> SimpleNamespace:
            calls.update(kwargs)
            return SimpleNamespace(
                promotion_id=uuid4(),
                review_id=uuid4(),
                recipe_id=uuid4(),
                feed_html="",
                vertical_html="<iframe>",
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )

    monkeypatch.setattr(promotion_unpublished_provider, "_service", Service)
    monkeypatch.setattr(
        "Qualify.promotion_provider.safe_preview_url", lambda html: "https://ok" if html else ""
    )
    start = datetime.now() + timedelta(days=1)
    form = replace(
        story_form(),
        budget="25000",
        start_local=start.strftime("%Y-%m-%dT%H:%M"),
        end_local=(start + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M"),
    )
    source = replace(story_source(), ad_account_id=str(uuid4()))
    review = promotion_unpublished_provider.prepare_unpublished(
        uuid4(), uuid4(), uuid4(), form, source, ZONE, str(uuid4())
    )
    assert calls["feed_asset_id"] is None and calls["vertical_asset_id"] == UUID(VERTICAL)
    assert calls["feed_thumbnail_asset_id"] is None
    assert calls["vertical_thumbnail_asset_id"] is None
    assert review.preview_url == "https://ok"


def _asset(kind: str, width: int, height: int) -> dict:
    return {
        "id": uuid4(),
        "object_key": "k",
        "content_type": "video/mp4" if kind == "video" else "image/jpeg",
        "media_type": kind,
        "width": width,
        "height": height,
    }


def _fake_piece(monkeypatch, assets: list[dict], accounts: int = 1) -> None:
    piece = {"brand_id": uuid4(), "active_version_id": uuid4(), "ad_copy": None}
    rows = [
        {
            "id": uuid4(),
            "name": "Cuenta",
            "currency": "COP",
            "timezone_name": ZONE,
            "account_label": "@negocio",
        }
        for _ in range(accounts)
    ]
    mod = promotion_unpublished_provider
    monkeypatch.setattr(mod, "_read", lambda *a: (piece, rows, assets))
    monkeypatch.setattr(mod, "load_policy", lambda *a: BrandEnhancementsVM())
    monkeypatch.setattr(mod, "account_health_for", lambda *a: AccountHealthVM())
    monkeypatch.setattr(mod, "issue_view_path", lambda *a: "")


def test_a_story_video_needs_a_vertical_cover_and_never_uses_the_4_5_files(monkeypatch) -> None:
    mod = promotion_unpublished_provider
    video, cover = _asset("video", 1080, 1920), _asset("image", 1080, 1920)
    feed = _asset("image", 1080, 1350)
    _fake_piece(monkeypatch, [video, cover, feed])
    rows = mod.unpublished_sources(uuid4(), uuid4(), story=True)
    assert [row.media_kind for row in rows] == ["videos", "images"]
    assert all(row.story and not row.feed_media and not row.feed_covers for row in rows)
    assert [m.id for m in rows[0].vertical_media] == [str(video["id"])]
    assert [m.id for m in rows[0].vertical_covers] == [str(cover["id"])]
    assert mod.story_ad_ready(uuid4(), uuid4())
    # a 9:16 video with no 9:16 image to cover it: no story ad at all
    _fake_piece(monkeypatch, [video, feed])
    assert mod.unpublished_sources(uuid4(), uuid4(), story=True) == []
    assert not mod.story_ad_ready(uuid4(), uuid4())
    # no ad account: not offered either
    _fake_piece(monkeypatch, [cover], accounts=0)
    assert not mod.story_ad_ready(uuid4(), uuid4())


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cached_story", "params", "wanted"),
    [
        (False, {"paso": "2", "formato": "historia"}, True),  # feed → historia
        (True, {"paso": "2"}, False),  # historia → feed
    ],
)
async def test_a_cached_wizard_is_never_reused_across_formats(
    monkeypatch, cached_story, params, wanted
) -> None:
    context = ActionContext()
    context.sources = [replace(story_source(), story=cached_story)]
    context.draft_id = str(PIECE)
    context.router = SimpleNamespace(url=SimpleNamespace(query_parameters=params))
    context.read_step = lambda: pytest.fail("reused the other format's sources")
    context.choose_source = lambda value: PromotionState.choose_source.fn(context, value)
    seen = []

    def load(*args: object, **kwargs: object) -> tuple[list, str]:
        seen.append(kwargs.get("story"))
        return [], ZONE

    monkeypatch.setattr(promotion_state, "load_sources", load)
    context.read_step = lambda: None
    _ = [event async for event in PromotionState.load.fn(context)]
    assert seen == [wanted] and context.story_entry is wanted


def test_titles_follow_the_story_flow() -> None:
    title = PromotionState.title.fget
    base = dict(preparation_blocked=False, reviewed=False, step=1, loading=False)
    empty = SimpleNamespace(**base, story_entry=True, sources=[], form=PromotionDraftVM())
    assert title(empty) == STORY_AD_OPTION
    one = SimpleNamespace(**base, story_entry=True, sources=[story_source()], form=story_form())
    assert title(one) == "¿A dónde lleva el botón?"  # no source step to name
    several = SimpleNamespace(
        **base, story_entry=True, sources=[story_source(), story_source()], form=PromotionDraftVM()
    )
    assert title(several) == UNPUBLISHED_SOURCE_TITLE
    reviewed = SimpleNamespace(
        **{**base, "reviewed": True}, story_entry=True, sources=[story_source()], form=story_form()
    )
    assert title(reviewed) == "Revisa y aprueba"
    blocked = SimpleNamespace(
        **{**base, "preparation_blocked": True},
        story_entry=True,
        sources=[story_source()],
        form=story_form(),
    )
    assert title(blocked) == "Revisa tu cuenta antes de promocionar"


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
    state._mark_story_ad(piece, True)  # what `check_story_ad` found
    state.ask_story_ad(piece)
    assert state.story_ad_post == piece and state.form_open  # only the notice, still here
    state.dismiss_story_ad()
    assert state.story_ad_post == "" and len(state.plan_items) == 1  # declining keeps it
    state.ask_story_ad(piece)
    events = state._leave_for_story_ad(piece, True)
    rendered = repr(events)
    # the drawer's history entry is closed BEFORE leaving, then the wizard opens
    assert len(events) == 2 and "history" in repr(events[0])
    assert f"/drafts/{piece}/promote?formato=historia" in rendered
    assert not state.form_open and state.plan_items == []  # nothing left to «Programar»


def test_an_ineligible_piece_is_never_offered_and_keeps_its_plan() -> None:
    piece = str(uuid4())
    state = _planner(piece)
    state.ask_story_ad(piece)  # not checked yet: no option, no notice
    assert state.story_ad_post == ""
    state._mark_story_ad(piece, True)
    state.ask_story_ad(piece)
    # it stopped qualifying before «Hacer anuncio pagado» (e.g. published meanwhile)
    assert state._leave_for_story_ad(piece, False) == []
    assert state.story_ad_post == "" and piece not in state.story_ad_ready
    assert state.form_open and len(state.plan_items) == 1  # the historia is still planned


def test_the_option_is_not_offered_for_a_bigger_plan_or_another_destination() -> None:
    piece = str(uuid4())
    state = _planner(piece)
    state._mark_story_ad(piece, True)
    state._update_item(piece, destination="post")
    state.ask_story_ad(piece)
    assert state.story_ad_post == ""
    state.plan_items = [*state.plan_items, replace(state.plan_items[0], post_id=str(uuid4()))]
    assert not state.story_ad_offered
    assert state._leave_for_story_ad(piece, True) == []


def test_a_closed_or_reopened_drawer_never_shows_a_stale_notice() -> None:
    piece = str(uuid4())
    state = _planner(piece)
    state._mark_story_ad(piece, True)
    state.ask_story_ad(piece)
    state.close_form()
    assert state.story_ad_post == ""
    state.ask_story_ad(piece)
    state.open_assign_for_post(piece)  # reopened on the same piece
    assert state.story_ad_post == ""


def test_the_notice_says_it_is_paid_before_the_wizard() -> None:
    rendered = repr(_story_ad_choice(SimpleNamespace(post_id="p"), True).render())
    # repr escapes accents: match the plain-ASCII part of each string
    assert "entre las historias de otras cuentas" in rendered
    assert "Hacer anuncio pagado" in rendered and "Dejar la historia sin bot" in rendered
    assert "Continuar" not in rendered  # never a second «Continuar» next to the drawer's
    offer = _story_ad_offer(SimpleNamespace(post_id="p"))
    assert "check_story_ad" in str(offer.event_triggers["on_mount"])
    assert "story_ad_ready" in repr(offer.render())
