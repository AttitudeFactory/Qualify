"""An unpublished piece is another source of the same promotion wizard (m-24828982)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from qualify_api.ads.unpublished import (
    UPLOAD_UNCERTAIN,
    VIDEO_PROCESSING,
    UnpublishedUnavailable,
)
from qualify_api.ads.unpublished_service import VIDEO_WAIT

from . import promotion_state as state_module
from .promotion_page import promotion_index
from .promotion_state import PromotionState
from .promotion_unpublished_ui import unpublished_review
from .promotion_vm import (
    IMAGE_STEPS,
    PUBLISHED_STEPS,
    VIDEO_STEPS,
    AdMediaVM,
    PromotionDraftVM,
    PromotionSourceVM,
    first_problem,
    step_count,
    step_counter,
    step_keys,
    step_problem,
    step_title,
    video_outcome,
    zone_label,
)
from .test_promotion_wizard import SOURCE, ActionContext, review, valid_form

FEED, VERTICAL, FEED_COVER, VERTICAL_COVER = "f1", "v1", "fc1", "vc1"


def video_source() -> PromotionSourceVM:
    return PromotionSourceVM(
        str(SOURCE),
        "@negocio",
        "Texto de la pieza",
        media_kind="videos",
        feed_media=[AdMediaVM(FEED, media_type="video"), AdMediaVM("f2", media_type="video")],
        vertical_media=[AdMediaVM(VERTICAL, media_type="video")],
        feed_covers=[AdMediaVM(FEED_COVER)],
        vertical_covers=[AdMediaVM(VERTICAL_COVER)],
        default_message="Texto de la pieza",
        default_headline="Yogur helado",
        default_link_url="https://negocio.example",
        default_country="CO",
    )


def video_form() -> PromotionDraftVM:
    return replace(
        valid_form(),
        media_kind="videos",
        feed_asset_id=FEED,
        vertical_asset_id=VERTICAL,
        feed_cover_id=FEED_COVER,
        vertical_cover_id=VERTICAL_COVER,
        message="Texto",
        headline="Título",
        country="CO",
    )


def unpublished_context() -> ActionContext:
    context = ActionContext()
    context.sources = [video_source()]
    context.form = video_form()
    context.step = len(VIDEO_STEPS)
    context.needs_help = False
    context.video_waiting = False
    return context


def test_steps_follow_the_source_kind_and_published_flow_is_unchanged() -> None:
    assert step_count(valid_form()) == len(PUBLISHED_STEPS) == 4
    assert step_count(replace(valid_form(), media_kind="images")) == len(IMAGE_STEPS)
    form = video_form()
    assert [step_title(form, n) for n in (2, 3)] == [
        "Video para el perfil",
        "Video vertical de pantalla completa",
    ]
    assert not first_problem(form, "America/Bogota")


def test_a_single_file_of_a_format_is_not_a_step() -> None:
    form = replace(video_form(), single_feed=True)
    assert "feed_video" not in step_keys(form) and "vertical_video" in step_keys(form)
    both = replace(video_form(), media_kind="images", single_feed=True, single_vertical=True)
    assert step_keys(both) == ("source", "text", "country", "budget")
    # skipped or not, the pair and the covers still gate the preparation
    assert "portada" in first_problem(replace(form, feed_cover_id=""), "America/Bogota")
    assert "dos archivos" in first_problem(replace(form, feed_asset_id=""), "America/Bogota")


@pytest.mark.parametrize(
    ("change", "step", "fragment"),
    [
        ({"headline": "x" * 101}, 4, "100 caracteres"),
        ({"message": " "}, 4, "texto"),
        ({"link_url": "http://negocio.example"}, 4, "https://"),
        ({"country": "AR"}, 5, "país"),
    ],
)
def test_each_unpublished_step_names_what_is_missing(change, step, fragment) -> None:
    form = replace(video_form(), **change)
    assert fragment in step_problem(form, step, "America/Bogota")
    assert first_problem(form, "America/Bogota") == step_problem(form, step, "America/Bogota")


def test_video_refusals_switch_on_the_typed_reason_not_the_wording() -> None:
    waiting = UnpublishedUnavailable("cualquier texto", reason=VIDEO_PROCESSING)
    assert video_outcome(waiting) == "waiting"
    assert video_outcome(UnpublishedUnavailable("x", reason=UPLOAD_UNCERTAIN)) == "help"
    # the same wording without a reason is an ordinary, fixable refusal
    assert video_outcome(UnpublishedUnavailable(VIDEO_WAIT["processing"])) == ""
    assert video_outcome(ValueError("Pide ayuda")) == ""


def test_choosing_the_source_prefills_the_pieces_pair_and_skips_audience() -> None:
    context = unpublished_context()
    context.form = PromotionDraftVM()
    context._reset_custom_audiences = lambda: None
    context.place_query = context.interest_query = ""
    event = PromotionState.choose_source.fn(context, str(SOURCE))
    assert event is None  # no audience search for this source
    form = context.form
    assert (form.media_kind, form.feed_asset_id, form.vertical_asset_id) == (
        "videos",
        FEED,
        VERTICAL,
    )
    assert (form.feed_cover_id, form.vertical_cover_id) == (FEED_COVER, VERTICAL_COVER)
    assert (form.headline, form.country, form.link_url) == (
        "Yogur helado",
        "CO",
        "https://negocio.example",
    )


def test_media_choice_only_accepts_the_pieces_own_files() -> None:
    context = unpublished_context()
    context.selected_source = context.sources[0]
    PromotionState.choose_media.fn(context, "feed_asset_id", "not-in-piece")
    assert context.form.feed_asset_id == FEED
    PromotionState.choose_media.fn(context, "feed_asset_id", "f2")
    assert context.form.feed_asset_id == "f2"
    assert not context.review.review_id  # a new file discards the prepared preview


def test_changing_a_cover_from_the_summary_stays_on_the_summary() -> None:
    context = unpublished_context()
    context.sources[0] = replace(
        context.sources[0], feed_covers=[AdMediaVM(FEED_COVER), AdMediaVM("fc2")]
    )
    context.selected_source = context.sources[0]
    context.reviewed = True
    PromotionState.choose_media.fn(context, "feed_cover_id", "fc2")
    assert context.form.feed_cover_id == "fc2"
    assert context.reviewed and not context.review.review_id
    PromotionState.choose_media.fn(context, "feed_asset_id", "f2")
    assert not context.reviewed  # a new video still sends the owner back to the steps


@pytest.mark.asyncio
async def test_processing_video_waits_and_repeats_with_the_same_key(monkeypatch) -> None:
    context = unpublished_context()
    context.review = type(review())()
    keys = []

    def processing(*args: object) -> None:
        keys.append(args[-1])
        raise UnpublishedUnavailable(VIDEO_WAIT["processing"], reason=VIDEO_PROCESSING)

    monkeypatch.setattr(state_module, "prepare_unpublished", processing)
    await context._remote(confirm=False)
    await context._remote(confirm=False)
    assert context.video_waiting and not context.error and not context.needs_help
    assert keys == ["one-approved-draft", "one-approved-draft"]


@pytest.mark.asyncio
async def test_uncertain_upload_asks_for_help_and_never_retries(monkeypatch) -> None:
    context = unpublished_context()
    context.review = type(review())()
    calls = []

    def unknown(*args: object) -> None:
        calls.append(args)
        raise UnpublishedUnavailable(
            "No pudimos confirmar la carga del video en Meta. "
            "Pide ayuda para revisarla antes de continuar.",
            reason=UPLOAD_UNCERTAIN,
        )

    monkeypatch.setattr(state_module, "prepare_unpublished", unknown)
    await context._remote(confirm=False)
    await context._remote(confirm=False)
    assert len(calls) == 1 and context.needs_help and "Pide ayuda" in context.error


@pytest.mark.asyncio
async def test_confirmation_goes_to_the_unpublished_service_only_with_consent(
    monkeypatch,
) -> None:
    context = unpublished_context()
    calls = []
    monkeypatch.setattr(state_module, "confirm_unpublished", lambda *a: calls.append(a))
    monkeypatch.setattr(state_module, "confirm_review", lambda *a: pytest.fail("published"))
    await context._remote(confirm=True)
    assert not calls and "acepta" in context.error
    context.confirm_charge = True
    context.error = ""
    monkeypatch.setattr(
        state_module,
        "confirm_unpublished",
        lambda *a: calls.append(a) or state_module.PromotionResultVM("p", "active", "ok"),
    )
    await context._remote(confirm=True)
    assert len(calls) == 1 and context.result.status == "active"


def test_tree_has_both_sandboxed_previews_and_the_wait_copy() -> None:
    rendered = repr(unpublished_review().render())
    assert rendered.count("sandbox") >= 2
    assert "preparando tu video" in rendered
    assert "dangerouslySetInnerHTML" not in rendered
    assert "Revisar ahora" in repr(promotion_index().render())


@pytest.mark.parametrize(
    ("form", "expected"),
    [
        # video: 6 steps + the review as the 7th
        (video_form(), [(n, 7) for n in range(1, 7)] + [(7, 7)]),
        # one video of each format: both video steps skipped, still exact
        (
            replace(video_form(), single_feed=True, single_vertical=True),
            [(n, 5) for n in range(1, 5)] + [(5, 5)],
        ),
        # images: 5 steps + review
        (replace(video_form(), media_kind="images"), [(n, 6) for n in range(1, 6)] + [(6, 6)]),
        # published: unchanged, «4 de 4» on budget and review as before
        (valid_form(), [(n, 4) for n in range(1, 5)] + [(4, 4)]),
    ],
)
def test_step_counter_is_right_on_every_step(form, expected) -> None:
    last = step_count(form)
    seen = [step_counter(form, form, n, False) for n in range(1, last + 1)]
    seen.append(step_counter(form, form, last, True))
    assert seen == expected


def test_counter_before_the_choice_uses_what_the_first_source_would_prefill() -> None:
    offered = replace(PromotionDraftVM(), media_kind="videos", single_feed=True)
    assert step_counter(PromotionDraftVM(), offered, 1, False) == (1, 6)
    assert step_counter(PromotionDraftVM(), PromotionDraftVM(), 1, False) == (1, 4)


def test_zone_is_said_in_plain_spanish() -> None:
    assert zone_label("America/Bogota") == "hora de Colombia"
    assert zone_label("America/Caracas") == "hora de Venezuela"
    assert zone_label("America/Montevideo") == "hora de Uruguay"
    assert zone_label("Europe/Madrid") == zone_label("") == "la hora de tu negocio"
