"""«Creaciones del mes» weights (CREAR-5, m-24848531): the versioned table and the one
rule that prices a request — the screen's quote and the service's charge read it."""

from __future__ import annotations

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


def test_the_table_is_versioned_and_names_the_pricing_table_it_derives_from() -> None:
    weights = load_weights()
    assert weights.version == CREATIONS_WEIGHTS_VERSION == "pesos-creaciones-v1"
    assert weights.monthly_quota == 30
    assert weights.usd_per_creation == Decimal("0.15")
    # the pricing table it was measured on exists and is the one named
    assert JsonPricingTable(weights.pricing_table_version).version == "v5"


def test_an_unknown_version_is_refused() -> None:
    with pytest.raises(KeyError, match="pesos-creaciones-v0"):
        load_weights("pesos-creaciones-v0")


def test_the_measured_weights_v1() -> None:
    """docs/creaciones-del-mes-medicion.md §3, row by row."""
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
    assert [weight_for_request("clip", duration_seconds=s).weight for s in (5, 10, 15)] == [
        3,
        5,
        6,
    ]
    assert weight_for_request("avatar_video", duration_seconds=15).weight == 13
    assert weight_for_request("avatar_video", duration_seconds=30).weight == 25


def test_a_clip_longer_than_the_vendor_allows_is_priced_at_its_longest_row() -> None:
    # every Seedance family the app calls caps at 12-15 s
    assert weight_for_request("clip", duration_seconds=30).weight == 6


def test_a_presenter_longer_than_the_table_is_not_offered() -> None:
    with pytest.raises(CreationNotOffered):
        weight_for_request("avatar_video", duration_seconds=45)


def test_the_operators_own_script_is_priced_by_how_long_it_reads() -> None:
    assert own_script_seconds(150) == 10
    short = weight_for_request("animated_avatar_video", own_script_chars=150)
    assert (short.request_kind, short.weight, short.presenter_seconds) == (
        REQUEST_PRESENTER,
        13,
        15,
    )
    assert weight_for_request("avatar_video", own_script_chars=300).weight == 25
    with pytest.raises(CreationNotOffered):
        weight_for_request("avatar_video", own_script_chars=600)


def test_an_avatar_on_seedance_is_a_generated_video_not_a_presenter() -> None:
    price = weight_for_request(
        "avatar_video", duration_seconds=15, video_engine=VideoEngine.SEEDANCE.value
    )
    assert (price.request_kind, price.weight) == (REQUEST_GENERATED_VIDEO, 6)


def test_a_gallery_pays_its_stills_and_each_animated_slide() -> None:
    assert weight_for_request("carousel", generated_slides=3).weight == 1
    # two stills (1) + one animated 5 s slide (3)
    price = weight_for_request("carousel", generated_slides=2, animated_slide_seconds=(5,))
    assert (price.request_kind, price.weight) == (REQUEST_CAROUSEL, 4)
    # only reused pieces: still the copy, never free
    assert weight_for_request("carousel").weight == 1


def test_the_shortest_presenter_is_what_a_short_balance_is_offered() -> None:
    assert load_weights().shortest_presenter == (15, 13)
    assert load_weights().presenter_max_seconds == 30


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


def test_the_data_file_matches_the_measurement_doc_name() -> None:
    data = Path(__file__).parents[1] / "src/qualify_creative/creations_data"
    assert (data / f"{CREATIONS_WEIGHTS_VERSION}.json").is_file()
