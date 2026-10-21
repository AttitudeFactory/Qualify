"""QUA-111 F2: the publishability rule (`planner.publishable.evaluate`) — pure, no DB.

One candidate in, one verdict out: a `PublishablePost` in the publisher's own shape, or a
`NotPublishable` with the first failing reason of a fixed order.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from qualify_api.planner.post_reader import (
    ApprovalStatus,
    NotPublishable,
    PublishablePost,
    UnpublishableReason,
)
from qualify_api.planner.publishable import (
    REASON_TEXT,
    MediaCandidate,
    PostCandidate,
    compatibility,
    destination_for_product_type,
    destination_options,
    destination_product_type,
    evaluate,
    media_product_type_for,
)
from qualify_api.publishing.client import MEDIA_TYPE_IMAGE, MEDIA_TYPE_REELS, MEDIA_TYPE_STORIES
from qualify_api.publishing.service import MEDIA_TYPE_CAROUSEL

R = UnpublishableReason
TENANT = UUID("f2000000-0000-4000-8000-000000000001")
OTHER_TENANT = UUID("f2000000-0000-4000-8000-000000000002")
CONN = UUID("f2000000-0000-4000-8000-0000000000c1")


def _key(name: str, tenant: UUID = TENANT) -> str:
    return f"t/{tenant}/media/{CONN}/{name}"


def _image(position: int = 0, **kw: object) -> MediaCandidate:
    base = {
        "object_key": _key(f"img{position}"),
        "content_type": "image/jpeg",
        "media_type": "image",
        "position": position,
    }
    return MediaCandidate(**{**base, **kw})  # type: ignore[arg-type]


def _video(position: int = 0, **kw: object) -> MediaCandidate:
    base = {
        "object_key": _key(f"vid{position}"),
        "content_type": "video/mp4",
        "media_type": "video",
        "position": position,
    }
    return MediaCandidate(**{**base, **kw})  # type: ignore[arg-type]


def _post(*media: MediaCandidate, **kw: object) -> PostCandidate:
    base = {
        "tenant_id": TENANT,
        "post_id": uuid4(),
        "brand_id": uuid4(),
        "approval": ApprovalStatus.APPROVED,
        "revision": 1,
        "approved_revision": 1,
        "category": "galeria",
        "caption": "Dos por uno\n\n#promo",
        "media": media if media else (_image(),),
    }
    return PostCandidate(**{**base, **kw})  # type: ignore[arg-type]


def _reason(candidate: PostCandidate) -> UnpublishableReason:
    verdict = evaluate(candidate)
    assert isinstance(verdict, NotPublishable), verdict
    assert verdict.post_id == candidate.post_id
    return verdict.reason


# --- the happy shapes ------------------------------------------------------------


def test_an_approved_single_jpeg_galeria_is_an_image_post() -> None:
    candidate = _post(_image())
    verdict = evaluate(candidate)
    assert isinstance(verdict, PublishablePost)
    assert verdict.media_product_type == "IMAGE"
    assert verdict.caption == "Dos por uno\n\n#promo"
    assert verdict.approved_revision == 1
    assert verdict.tenant_id == TENANT and verdict.post_id == candidate.post_id
    (item,) = verdict.media
    assert (item.object_key, item.content_type, item.media_type, item.position) == (
        _key("img0"),
        "image/jpeg",
        "IMAGE",
        0,
    )


def test_an_mp4_reel_and_an_mp4_story_follow_the_normal_flow() -> None:
    reel = evaluate(_post(_video(), category="reel"))
    story = evaluate(_post(_video(), category="story"))
    assert isinstance(reel, PublishablePost) and reel.media_product_type == "REELS"
    assert isinstance(story, PublishablePost) and story.media_product_type == "STORIES"
    assert reel.media[0].content_type == "video/mp4" and reel.media[0].media_type == "VIDEO"


def test_a_galeria_of_several_items_is_a_carousel_ordered_by_position() -> None:
    verdict = evaluate(_post(_image(2), _video(0), _image(1)))
    assert isinstance(verdict, PublishablePost)
    assert verdict.media_product_type == "CAROUSEL"
    assert [m.position for m in verdict.media] == [0, 1, 2]
    assert [m.media_type for m in verdict.media] == ["VIDEO", "IMAGE", "IMAGE"]


# --- the category x media matrix -------------------------------------------------


@pytest.mark.parametrize(
    ("category", "media_types", "expected"),
    [
        ("galeria", ("IMAGE",), "IMAGE"),
        ("galeria", ("IMAGE", "IMAGE"), "CAROUSEL"),
        ("galeria", ("IMAGE", "VIDEO"), "CAROUSEL"),
        ("galeria", ("IMAGE",) * 10, "CAROUSEL"),
        ("galeria", ("VIDEO",), None),  # a lone video is a reel, not a guess
        ("galeria", ("IMAGE",) * 11, None),
        ("reel", ("VIDEO",), "REELS"),
        ("reel", ("IMAGE",), None),
        ("reel", ("VIDEO", "VIDEO"), None),
        ("story", ("VIDEO",), "STORIES"),
        ("story", ("IMAGE",), "STORIES"),  # image story by category — QUA-118 AC 6
        ("story", ("VIDEO", "IMAGE"), None),
        ("tiktok_video", ("VIDEO",), None),
        ("feed", ("IMAGE",), None),  # the old brief-format label is not a category
        ("unknown", ("VIDEO",), None),
    ],
)
def test_category_media_matrix(
    category: str, media_types: tuple[str, ...], expected: str | None
) -> None:
    assert media_product_type_for(category, media_types) == expected


@pytest.mark.parametrize("category", ["unknown", "feed", "reels", "REEL", "video"])
def test_an_unknown_category_is_never_published_and_never_becomes_a_reel(category: str) -> None:
    candidate = _post(_video(), category=category)
    assert _reason(candidate) is R.CATEGORY_NOT_PUBLISHABLE
    assert media_product_type_for(category, ("VIDEO",)) is None


def test_a_null_category_is_not_publishable() -> None:
    assert _reason(_post(_image(), category=None)) is R.CATEGORY_MISSING
    assert _reason(_post(_image(), category="")) is R.CATEGORY_MISSING


def test_tiktok_video_is_not_publishable() -> None:
    assert _reason(_post(_video(), category="tiktok_video")) is R.CATEGORY_NOT_PUBLISHABLE


def test_story_with_an_image_is_publishable_as_stories() -> None:
    """QUA-118 AC 6: the publisher has published image stories since QUA-113; the
    category contract now says so too (MP-11 had left it to the `story` port)."""
    verdict = evaluate(_post(_image(), category="story"))
    assert isinstance(verdict, PublishablePost) and verdict.media_product_type == "STORIES"
    assert verdict.media[0].media_type == "IMAGE"
    assert _reason(_post(_image(0), _image(1), category="story")) is R.UNSUPPORTED_SHAPE


def test_compatibility_names_the_channel_and_the_shape() -> None:
    """QUA-118: one rule for "can this account take this shape": a typed reason per
    refusal, so the assign flow can disable an account and say why."""
    ok = compatibility("instagram", "story", ("IMAGE",))
    assert ok.ok and ok.media_product_type == "STORIES" and ok.reason is None
    shape = compatibility("instagram", "reel", ("IMAGE",))
    assert not shape.ok and shape.reason is R.UNSUPPORTED_SHAPE
    for platform in ("tiktok", "facebook", ""):
        channel = compatibility(platform, "reel", ("VIDEO",))
        assert not channel.ok and channel.reason is R.CHANNEL_NOT_SUPPORTED
    assert REASON_TEXT[R.CHANNEL_NOT_SUPPORTED]
    # By port the port decides, on Instagram only.
    assert compatibility("instagram", "reel", ("VIDEO",), "reel").media_product_type == "REELS"
    assert compatibility("instagram", "reel", ("IMAGE",), "story").media_product_type == "STORIES"


# --- approval and revision -------------------------------------------------------


@pytest.mark.parametrize(
    "approval", [ApprovalStatus.PENDING, ApprovalStatus.NOT_READY, ApprovalStatus.REJECTED]
)
def test_an_unapproved_post_is_not_publishable(approval: ApprovalStatus) -> None:
    assert _reason(_post(approval=approval)) is R.NOT_APPROVED


def test_approved_without_an_approved_revision_is_not_publishable() -> None:
    assert _reason(_post(approved_revision=None)) is R.NOT_APPROVED


def test_an_edit_after_approval_blocks_the_post() -> None:
    verdict = evaluate(_post(revision=2, approved_revision=1))
    assert isinstance(verdict, NotPublishable)
    assert verdict.reason is R.REVISION_NOT_APPROVED
    assert verdict.detail == "revision 2, approved 1"


def test_an_unreadable_approved_copy_is_not_publishable() -> None:
    assert _reason(_post(caption=None)) is R.APPROVED_COPY_MISSING


def test_an_empty_caption_is_still_publishable() -> None:
    """Meta allows a post without a caption; empty is a value, None is "unreadable"."""
    assert isinstance(evaluate(_post(caption="")), PublishablePost)


# --- media count, order and type -------------------------------------------------


def test_no_media_is_not_publishable() -> None:
    assert _reason(replace(_post(), media=())) is R.NO_MEDIA


def test_more_than_ten_items_is_not_publishable() -> None:
    eleven = tuple(_image(i) for i in range(11))
    assert _reason(_post(*eleven)) is R.TOO_MANY_MEDIA


def test_duplicate_positions_are_ambiguous() -> None:
    assert _reason(_post(_image(0), _image(0))) is R.MEDIA_ORDER_AMBIGUOUS


def test_an_unknown_asset_media_type_is_not_publishable() -> None:
    assert _reason(_post(_image(media_type="audio"))) is R.UNSUPPORTED_MEDIA_TYPE


# --- R2 custody and content type -------------------------------------------------


def test_a_local_generated_key_is_not_in_r2() -> None:
    local = _image(object_key=f"generated/{TENANT}/{uuid4()}/slide-1.png")
    assert _reason(_post(local)) is R.MEDIA_NOT_IN_R2


def test_a_missing_key_is_not_in_r2() -> None:
    assert _reason(_post(_image(object_key=None))) is R.MEDIA_NOT_IN_R2


def test_another_tenants_key_is_not_in_r2() -> None:
    foreign = _image(object_key=_key("img0", OTHER_TENANT))
    assert _reason(_post(foreign)) is R.MEDIA_NOT_IN_R2


def test_a_traversal_key_is_not_in_r2() -> None:
    assert _reason(_post(_image(object_key=f"t/{TENANT}/../x.jpg"))) is R.MEDIA_NOT_IN_R2


def test_a_stock_file_is_never_published_as_is() -> None:
    # stock plan §5.2: an input of a piece, never the piece (both licences)
    stock = _image(object_key=f"t/{TENANT}/stock/pixabay/8434113/abcdef0123456789.jpg")
    assert _reason(_post(stock)) is R.STOCK_NOT_PUBLISHABLE


def test_a_null_content_type_is_not_publishable() -> None:
    assert _reason(_post(_image(content_type=None))) is R.CONTENT_TYPE_MISSING


def test_a_png_is_not_publishable() -> None:
    assert _reason(_post(_image(content_type="image/png"))) is R.UNSUPPORTED_CONTENT_TYPE


def test_a_jpeg_image_and_an_mp4_video_are_valid() -> None:
    assert isinstance(evaluate(_post(_image(content_type="image/jpeg"))), PublishablePost)
    assert isinstance(
        evaluate(_post(_video(content_type="video/mp4"), category="reel")), PublishablePost
    )


def test_a_video_declared_as_an_image_type_is_refused() -> None:
    assert (
        _reason(_post(_video(content_type="image/jpeg"), category="reel"))
        is R.UNSUPPORTED_CONTENT_TYPE
    )


def test_one_bad_item_blocks_the_whole_carousel() -> None:
    carousel = (_image(0), _image(1, content_type="image/png"), _image(2))
    assert _reason(_post(*carousel)) is R.UNSUPPORTED_CONTENT_TYPE


# --- determinism -----------------------------------------------------------------


def test_the_first_failing_rule_in_the_fixed_order_is_the_reason() -> None:
    """Unapproved AND edited AND PNG AND local key: approval is reported, every time."""
    worst = _post(
        _image(object_key="generated/x.png", content_type="image/png"),
        approval=ApprovalStatus.PENDING,
        revision=3,
        category="story",
    )
    assert {_reason(worst) for _ in range(5)} == {R.NOT_APPROVED}


def test_every_reason_has_operator_text() -> None:
    assert set(REASON_TEXT) == set(UnpublishableReason)
    assert all(REASON_TEXT[reason] for reason in UnpublishableReason)


# --- MP-11: one output per event ---------------------------------------------------


def _package(category: str = "reel") -> PostCandidate:
    """A `promo_producto` run: a Reel video, a feed image and a story IMAGE, each on its
    port — the shape the whole-POST rule refuses as `UNSUPPORTED_SHAPE`."""
    return _post(
        _video(0, output_port="reel"),
        _image(1, output_port="feed"),
        _image(2, output_port="story"),
        category=category,
    )


@pytest.mark.parametrize(
    ("port", "media_types", "expected"),
    [
        ("reel", ("VIDEO",), "REELS"),
        ("reel", ("IMAGE",), None),
        ("reel", ("VIDEO", "VIDEO"), None),
        ("feed", ("IMAGE",), "IMAGE"),
        ("feed", ("VIDEO",), None),  # a video in the feed port is never a reel by accident
        ("feed", ("IMAGE", "IMAGE"), None),  # a port is one item; a carousel is a galería
        ("story", ("IMAGE",), "STORIES"),  # image story — QUA-113, the publisher does it
        ("story", ("VIDEO",), "STORIES"),
        ("story", ("IMAGE", "VIDEO"), None),
        ("poster", ("IMAGE",), None),  # an unknown port is never published
    ],
)
def test_port_media_matrix(port: str, media_types: tuple[str, ...], expected: str | None) -> None:
    # The category is irrelevant once a port decides — `reel` here would refuse an image.
    assert media_product_type_for("reel", media_types, port) == expected
    assert media_product_type_for("galeria", media_types, port) == expected


def test_a_package_as_a_whole_is_unsupported_but_each_output_publishes() -> None:
    whole = evaluate(_package())
    assert isinstance(whole, NotPublishable) and whole.reason is R.UNSUPPORTED_SHAPE
    assert whole.output_port is None

    reel = evaluate(replace(_package(), output_port="reel"))
    feed = evaluate(replace(_package(), output_port="feed"))
    story = evaluate(replace(_package(), output_port="story"))
    assert isinstance(reel, PublishablePost) and reel.media_product_type == "REELS"
    assert isinstance(feed, PublishablePost) and feed.media_product_type == "IMAGE"
    assert isinstance(story, PublishablePost) and story.media_product_type == "STORIES"
    # Only the port's asset goes to the publisher, re-numbered from position 0.
    for verdict, key, media_type in (
        (reel, _key("vid0"), "VIDEO"),
        (feed, _key("img1"), "IMAGE"),
        (story, _key("img2"), "IMAGE"),
    ):
        (item,) = verdict.media
        assert (item.object_key, item.media_type, item.position) == (key, media_type, 0)
    assert story.media[0].content_type == "image/jpeg"  # what `is_image_story` keys on
    assert reel.output_port == "reel" and ("output_port", "reel") in reel.provenance


def test_the_port_decides_not_the_category() -> None:
    # A package filed under `galeria` still publishes its Reel as a reel.
    reel = evaluate(replace(_package(category="galeria"), output_port="reel"))
    assert isinstance(reel, PublishablePost) and reel.media_product_type == "REELS"


def test_a_port_the_post_does_not_have_has_no_media() -> None:
    verdict = evaluate(replace(_package(), output_port="poster"))
    assert isinstance(verdict, NotPublishable)
    assert verdict.reason is R.NO_MEDIA and verdict.detail == "port poster"
    assert verdict.output_port == "poster"


def test_a_port_with_the_wrong_media_names_the_port_in_the_detail() -> None:
    swapped = _post(_image(0, output_port="reel"), category="reel", output_port="reel")
    verdict = evaluate(swapped)
    assert isinstance(verdict, NotPublishable) and verdict.reason is R.UNSUPPORTED_SHAPE
    assert verdict.detail == "port reel (reel with IMAGE)"


def test_one_bad_output_does_not_block_the_others() -> None:
    package = _post(
        _video(0, output_port="reel", object_key="generated/local.mp4"),  # not in R2 yet
        _image(1, output_port="feed"),
        category="reel",
    )
    reel = evaluate(replace(package, output_port="reel"))
    feed = evaluate(replace(package, output_port="feed"))
    assert isinstance(reel, NotPublishable) and reel.reason is R.MEDIA_NOT_IN_R2
    assert isinstance(feed, PublishablePost)


def test_without_a_port_assets_with_ports_are_evaluated_as_before() -> None:
    # A single-output run (one `feed` image, category galería) stays publishable whole.
    verdict = evaluate(_post(_image(0, output_port="feed")))
    assert isinstance(verdict, PublishablePost) and verdict.media_product_type == "IMAGE"
    assert verdict.output_port is None


def test_a_generated_pieces_r2_copy_is_publishable() -> None:
    """pendientes-generador-contenido.md §1's closing criterion (§ 2026-10-06): the key the
    generator now writes for a piece's durable copy passes without `media_not_in_r2`."""
    from qualify_api.creative.media import generated_object_key

    draft = uuid4()
    image = _image(object_key=generated_object_key(TENANT, draft, 1, "slide-1.jpg"))
    assert isinstance(evaluate(_post(image)), PublishablePost)
    reel = _video(object_key=generated_object_key(TENANT, draft, 2, "video.mp4"))
    assert isinstance(evaluate(_post(reel, category="reel")), PublishablePost)


# --- QUA-118 v2: the event's destination ------------------------------------------------
#
# Rules verified against Meta's IG User Media reference (2026-10-06): a feed image only
# inside 4:5…1.91:1; a feed video IS a reel (no feed VIDEO since 2023-11-09); a story is
# one image or one video (≤ 60 s, not checkable here); a carousel is never a story nor a
# reel.


def _options(media_types: tuple[str, ...], size: tuple[int, int] | None = None) -> dict:
    return {o.destination: (o.offered, o.available) for o in destination_options(media_types, size)}


def test_destination_options_follow_instagram() -> None:
    assert _options(("IMAGE",), (1080, 1350)) == {
        "post": (True, True),
        "reel": (True, False),
        "story": (True, True),
    }
    assert _options(("IMAGE",), (1080, 1920))["post"] == (True, False)  # 9:16 is too tall
    assert _options(("VIDEO",)) == {
        "post": (False, False),  # not offered: it would be a reel anyway
        "reel": (True, True),
        "story": (True, True),
    }
    assert _options(("IMAGE", "VIDEO")) == {
        "post": (True, True),
        "reel": (True, False),
        "story": (True, False),
    }
    story = next(o for o in destination_options(("VIDEO",)) if o.destination == "story")
    assert "60 segundos" in story.warning


def test_destination_product_type_and_its_inverse() -> None:
    assert destination_product_type("post", ("IMAGE",)) == MEDIA_TYPE_IMAGE
    assert destination_product_type("post", ("IMAGE", "VIDEO")) == MEDIA_TYPE_CAROUSEL
    assert destination_product_type("post", ("VIDEO",)) is None
    assert destination_product_type("reel", ("VIDEO",)) == MEDIA_TYPE_REELS
    assert destination_product_type("reel", ("IMAGE",)) is None
    assert destination_product_type("story", ("IMAGE",)) == MEDIA_TYPE_STORIES
    assert destination_product_type("story", ("VIDEO",)) == MEDIA_TYPE_STORIES
    assert destination_product_type("story", ("IMAGE", "IMAGE")) is None
    for product, destination in (
        (MEDIA_TYPE_IMAGE, "post"),
        (MEDIA_TYPE_CAROUSEL, "post"),
        (MEDIA_TYPE_REELS, "reel"),
        (MEDIA_TYPE_STORIES, "story"),
        (None, None),
    ):
        assert destination_for_product_type(product) == destination


def test_the_events_destination_decides_what_meta_receives() -> None:
    # The same reel POST, as a Reel and as a Historia: the category is only the origin.
    reel = _post(_video(), category="reel")
    assert evaluate(replace(reel, destination="reel")).media_product_type == MEDIA_TYPE_REELS
    as_story = evaluate(replace(reel, destination="story"))
    assert as_story.media_product_type == MEDIA_TYPE_STORIES
    assert ("destination", "story") in as_story.provenance
    # A galería image as a Historia, a carousel only as a post.
    image = _post(_image(width=1080, height=1350))
    assert evaluate(replace(image, destination="story")).media_product_type == MEDIA_TYPE_STORIES
    carousel = _post(_image(0), _video(1))
    assert _reason(replace(carousel, destination="story")) is R.DESTINATION_NOT_SUPPORTED
    assert _reason(replace(reel, destination="post")) is R.DESTINATION_NOT_SUPPORTED
    # No destination (an event the backfill could not derive) keeps the category rule.
    assert evaluate(reel).media_product_type == MEDIA_TYPE_REELS


def test_a_feed_image_outside_metas_range_is_refused_only_as_a_post() -> None:
    tall = _post(_image(width=1080, height=1920), category="story")
    assert _reason(replace(tall, destination="post")) is R.IMAGE_RATIO_NOT_ALLOWED
    assert evaluate(replace(tall, destination="story")).media_product_type == MEDIA_TYPE_STORIES
    unknown = _post(_image())  # no recorded size: Meta is the one to say
    assert evaluate(replace(unknown, destination="post")).media_product_type == MEDIA_TYPE_IMAGE
    assert REASON_TEXT[R.IMAGE_RATIO_NOT_ALLOWED] and REASON_TEXT[R.DESTINATION_NOT_SUPPORTED]


@pytest.mark.parametrize(
    ("port", "media_type", "expected"),
    [
        ("square", "IMAGE", "IMAGE"),
        ("feed-video", "VIDEO", "REELS"),
        ("square-video", "VIDEO", "REELS"),
        ("feed-video", "IMAGE", None),
    ],
)
def test_the_template_v2_ports_publish_as_their_shape(
    port: str, media_type: str, expected: str | None
) -> None:
    """promo_producto v2 (2026-10-13): the 1:1 still is a feed post, the 4:5 / 1:1 videos
    are Reels — never an unknown port the planner refuses."""
    from qualify_api.planner.publishable import _shape_product_type

    assert _shape_product_type("plantilla", (media_type,), port) == expected
