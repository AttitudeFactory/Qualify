"""«Creaciones del mes» weights (CREAR-5, m-24848531): the versioned table and the one
rule that prices a request — the screen's quote and the service's charge read it."""

from __future__ import annotations

import math
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from qualify_creative.creations import (
    CREATIONS_WEIGHTS_VERSION,
    REQUEST_CAROUSEL,
    REQUEST_GENERATED_VIDEO,
    REQUEST_IMAGE,
    REQUEST_IMAGE_REDO,
    REQUEST_PRESENTER,
    REQUEST_SCRIPT,
    REQUEST_TEMPLATE,
    CreationNotOffered,
    load_weights,
    own_script_seconds,
    weight_for,
    weight_for_request,
)
from qualify_creative.enums import (
    AvatarSource,
    BriefObjective,
    ContentFormat,
    ContentKind,
    ImageRoute,
    VideoEngine,
)
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.schemas import ContentBrief, MediaInputs

BRAND_ID = UUID("a3b1c2d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")


V1 = "pesos-creaciones-v1"


def test_the_table_is_versioned_and_names_the_pricing_table_it_derives_from() -> None:
    weights = load_weights()
    assert weights.version == CREATIONS_WEIGHTS_VERSION == "pesos-creaciones-v2"
    assert weights.monthly_quota == 30
    assert weights.usd_per_creation == Decimal("0.15")
    # every charge cites the pricing table in force on main (m-24851828)
    assert weights.pricing_table_version == "v7"
    assert JsonPricingTable(weights.pricing_table_version).version == "v7"
    # v1 is kept as it was, on the table it was measured on
    assert load_weights(V1).pricing_table_version == "v5"
    assert load_weights(V1).video_rates is None


def test_an_unknown_version_is_refused() -> None:
    with pytest.raises(KeyError, match="pesos-creaciones-v0"):
        load_weights("pesos-creaciones-v0")


def test_the_measured_weights_v1_are_kept() -> None:
    """docs/creaciones-del-mes-medicion.md §3, row by row — v1 is never edited."""
    v1 = load_weights(V1)
    assert weight_for_request("static_flyer", weights=v1).weight == 1
    assert [
        weight_for_request("clip", duration_seconds=s, weights=v1).weight for s in (5, 10, 15)
    ] == [3, 5, 6]
    clip = weight_for_request("clip", duration_seconds=5, weights=v1)
    assert clip.final_weight == 0  # v1 had no separate final
    assert weight_for_request("clip", duration_seconds=30, weights=v1).weight == 6
    assert weight_for_request("avatar_video", duration_seconds=5, weights=v1).weight == 13
    assert weight_for_request("avatar_video", duration_seconds=30, weights=v1).weight == 25


def test_the_weights_v2() -> None:
    """docs/creaciones-del-mes-medicion.md §5 (v2), row by row."""
    assert weight_for_request("static_flyer").weight == 1
    assert weight_for_request("static_flyer", redo=True).request_kind == REQUEST_IMAGE_REDO
    assert weight_for_request("static_flyer", redo=True).weight == 1
    assert weight_for_request("template").weight == 1
    assert weight_for_request("creator_script").weight == 1
    assert [weight_for_request("static_flyer", carousel_images=n).weight for n in (3, 5, 9)] == [
        1,
        2,
        3,
    ]
    clips = [weight_for_request("clip", duration_seconds=s) for s in (5, 10, 15)]
    assert [(c.weight, c.preview_weight, c.final_weight) for c in clips] == [
        (23, 4, 19),
        (46, 8, 38),
        (68, 12, 56),
    ]
    presenters = [weight_for_request("avatar_video", duration_seconds=s) for s in (5, 10, 15, 30)]
    assert [p.weight for p in presenters] == [5, 9, 13, 25]
    # OmniHuman has no preview/final: nothing is given back separately
    assert {p.final_weight for p in presenters} == {0}


def test_a_5_second_clip_is_priced_as_5_seconds_not_15() -> None:
    """UX review 2026-10-24 §Pesos 1: the clip's own length, never the presenter's."""
    five = weight_for_request("clip", duration_seconds=5)
    fifteen = weight_for_request("clip", duration_seconds=15)
    assert five.weight == 23 and fifteen.weight == 68


def test_the_v2_video_rates_come_from_pricing_table_v7() -> None:
    """Tokens per second (480p / 1080p, the largest ratio) × the v7 per-million rates."""
    rates = load_weights().video_rates
    assert rates is not None
    v7 = JsonPricingTable("v7")
    model = "dreamina-seedance-2-5-260628"
    assert rates.model_id == model
    million = Decimal(1_000_000)

    def rate(unit: str) -> Decimal:
        return v7.unit_price(model_id=model, unit=unit)

    assert rates.preview_usd_per_second == 9870 * rate("per_mtok_video_480p") / million
    assert rates.final_usd_per_second == 48672 * rate("per_mtok_video_1080p") / million
    assert rates.preview_usd_per_second_with_video == (
        9870 * rate("per_mtok_video_480p_with_video") / million
    )
    assert rates.final_usd_per_second_with_video == (
        48672 * rate("per_mtok_video_1080p_with_video") / million
    )
    # the presenter rows: script p95 0.033 + OmniHuman 1.5 per second + the voice
    omni = v7.unit_price(model_id="omnihuman-1-5", unit="per_second_720p")
    voice = v7.unit_price(model_id="seed-icl-2.0", unit="per_mchar")
    for step in load_weights().presenter_by_seconds:
        usd = Decimal("0.033") + omni * step.up_to + voice * 15 * step.up_to / million
        assert step.weight == math.ceil(usd / Decimal("0.15"))


def test_a_reference_video_is_priced_with_its_input_seconds() -> None:
    """docs/modelos-generativos/seedance-2-5.md: the input video's seconds are billed at
    the with-video rate; an unknown length is priced at the most a task takes (30 s)."""
    measured = weight_for_request(
        "clip", duration_seconds=5, reference_videos=1, reference_video_seconds=7.33
    )
    assert (measured.weight, measured.final_weight) == (34, 28)
    unknown = weight_for_request("clip", duration_seconds=5, reference_videos=1)
    assert unknown.weight == 95
    short = weight_for_request(
        "clip", duration_seconds=5, reference_videos=1, reference_video_seconds=3
    )
    assert short.weight == 22  # the cheaper with-video rate, plus 3 s of input


def test_the_sound_does_not_change_the_weight() -> None:
    """v7 has one rate with or without «Con audio» and SD25-001 billed no extra tokens."""
    for seconds in (5, 10, 15):
        loud = weight_for_request("clip", duration_seconds=seconds, audio=True)
        silent = weight_for_request("clip", duration_seconds=seconds, audio=False)
        assert loud == silent


def test_a_clip_longer_than_the_table_prices_is_priced_at_its_longest() -> None:
    assert weight_for_request("clip", duration_seconds=30).weight == 68


def test_a_presenter_of_45_or_60_seconds_is_not_offered() -> None:
    """Founder 2026-10-24: 5, 10, 15 and 30 s only — 45 and 60 s have no row."""
    weights = load_weights()
    assert [step.up_to for step in weights.presenter_by_seconds] == [5, 10, 15, 30]
    for seconds in (45, 60):
        with pytest.raises(CreationNotOffered):
            weight_for_request("avatar_video", duration_seconds=seconds)


def test_the_operators_own_script_is_priced_by_how_long_it_reads() -> None:
    assert own_script_seconds(150) == 10
    short = weight_for_request("animated_avatar_video", own_script_chars=150)
    assert (short.request_kind, short.weight, short.presenter_seconds) == (
        REQUEST_PRESENTER,
        9,
        10,
    )
    # a 20 s script is a 30 s presenter
    assert weight_for_request("avatar_video", own_script_chars=300).weight == 25
    with pytest.raises(CreationNotOffered):
        weight_for_request("avatar_video", own_script_chars=600)


def test_an_avatar_on_seedance_is_a_generated_video_not_a_presenter() -> None:
    price = weight_for_request(
        "avatar_video", duration_seconds=15, video_engine=VideoEngine.SEEDANCE.value
    )
    assert (price.request_kind, price.weight, price.final_weight) == (
        REQUEST_GENERATED_VIDEO,
        68,
        56,
    )


def test_a_gallery_pays_its_stills_and_each_animated_slide() -> None:
    assert weight_for_request("carousel", generated_slides=3).weight == 1
    # two stills (1) + one animated 5 s slide (23, of which 19 pay its final)
    price = weight_for_request("carousel", generated_slides=2, animated_slide_seconds=(5,))
    assert (price.request_kind, price.weight, price.final_weight) == (REQUEST_CAROUSEL, 24, 19)
    # an animated slide that follows a reference video of unknown length
    referenced = weight_for_request(
        "carousel",
        generated_slides=2,
        animated_slide_seconds=(5,),
        animated_slide_references=(True,),
    )
    assert referenced.weight == 1 + 95
    # only reused pieces: still the copy, never free
    assert weight_for_request("carousel").weight == 1


def test_a_short_balance_is_offered_the_longest_presenter_it_pays_for() -> None:
    weights = load_weights()
    assert weights.shortest_presenter == (5, 5)
    assert weights.presenter_max_seconds == 30
    assert weights.longest_presenter_within(30) == (30, 25)
    assert weights.longest_presenter_within(20) == (15, 13)
    assert weights.longest_presenter_within(12) == (10, 9)
    assert weights.longest_presenter_within(8) == (5, 5)
    assert weights.longest_presenter_within(4) is None


def _brief(kind: ContentKind, fmt: ContentFormat = ContentFormat.FEED_4_5, **media: object):
    return ContentBrief(
        brand_id=BRAND_ID,
        objective=BriefObjective.SALE,
        topic="Smash burger doble",
        image_route=ImageRoute.TEMPLATE_ONLY,
        kind=kind,
        format=fmt,
        media=MediaInputs(**media),  # type: ignore[arg-type]
    )


def test_the_charge_reads_the_same_rule_off_the_stored_brief() -> None:
    assert weight_for(_brief(ContentKind.STATIC_FLYER)).request_kind == REQUEST_IMAGE
    flyer = _brief(
        ContentKind.STATIC_FLYER,
        carousel=True,
        product_keys=tuple(f"uploads/t/{n}.jpg" for n in range(5)),
    )
    assert weight_for(flyer).weight == 2
    template = _brief(ContentKind.TEMPLATE, product_keys=("uploads/t/a.jpg",))
    assert weight_for(template).request_kind == REQUEST_TEMPLATE
    script = _brief(ContentKind.CREATOR_SCRIPT, fmt=ContentFormat.REELS_9_16)
    assert weight_for(script).request_kind == REQUEST_SCRIPT
    presenter = _brief(
        ContentKind.AVATAR_VIDEO,
        fmt=ContentFormat.REELS_9_16,
        video_engine=VideoEngine.OMNIHUMAN,
        avatar_source=AvatarSource.AI,
        avatar_prompt="Una mujer joven, sonriente",
        duration_seconds=30,
    )
    assert weight_for(presenter).weight == 25
    clip = _brief(ContentKind.CLIP, fmt=ContentFormat.REELS_9_16, duration_seconds=5)
    assert (weight_for(clip).weight, weight_for(clip).final_weight) == (23, 19)
    referenced = _brief(
        ContentKind.CLIP,
        fmt=ContentFormat.REELS_9_16,
        duration_seconds=5,
        clip_video_keys=("uploads/t/ref.mp4",),
    )
    # the brief carries no length for the reference video: the most a task takes
    assert weight_for(referenced).weight == 95


def test_the_data_file_matches_the_measurement_doc_name() -> None:
    data = Path(__file__).parents[1] / "src/qualify_creative/creations_data"
    assert (data / f"{CREATIONS_WEIGHTS_VERSION}.json").is_file()
