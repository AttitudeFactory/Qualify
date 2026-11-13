"""Offline tests for the planner's own upload (m-25026384, `creative.own_upload`): the
typed refusals, the category/format rule, the idempotency key, and — through the one
publishability rule (`planner.publishable`) — that the piece it writes is schedulable to
the destinations the acceptance criterion names and publishable at its hour."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind, PostCategory

from qualify_api.creative.own_media import UNTITLED, request_key_for, title_of
from qualify_api.creative.own_upload import (
    REFUSAL_TEXT,
    UNTITLED_IMAGE,
    UNTITLED_VIDEO,
    OwnUpload,
    OwnUploadRefused,
    UploadRefusal,
    check_upload,
    normalized_content_type,
    shape_for,
    upload_request_key,
)
from qualify_api.planner.post_reader import ApprovalStatus, PublishablePost
from qualify_api.planner.publishable import (
    MediaCandidate,
    PostCandidate,
    destination_options,
    evaluate,
)

TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER = UUID("22222222-2222-4222-8222-222222222222")


def _key(tenant: UUID = TENANT, folder: str = "uploads") -> str:
    return f"t/{tenant}/{folder}/{uuid4().hex}_foto.jpg"


def _upload(**overrides: object) -> OwnUpload:
    fields: dict[str, object] = {
        "upload_id": uuid4(),
        "object_key": _key(),
        "media_type": "image",
        "content_type": "image/jpeg",
    }
    fields.update(overrides)
    return OwnUpload(**fields)  # type: ignore[arg-type]


def _refusal(upload: OwnUpload) -> UploadRefusal:
    with pytest.raises(OwnUploadRefused) as caught:
        check_upload(TENANT, upload)
    assert caught.value.text == REFUSAL_TEXT[caught.value.code]
    return caught.value.code


# -- refusals ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"object_key": _key(OTHER)}, UploadRefusal.NOT_THIS_TENANT),
        ({"object_key": f"uploads/{TENANT}/foto.jpg"}, UploadRefusal.NOT_THIS_TENANT),
        ({"object_key": f"t/{TENANT}/uploads/../media/x.jpg"}, UploadRefusal.NOT_THIS_TENANT),
        ({"object_key": ""}, UploadRefusal.NOT_THIS_TENANT),
        ({"object_key": _key(folder="generated")}, UploadRefusal.NOT_AN_UPLOAD),
        ({"object_key": _key(folder="media")}, UploadRefusal.NOT_AN_UPLOAD),
        ({"object_key": f"t/{TENANT}/uploads/"}, UploadRefusal.NOT_AN_UPLOAD),
        ({"media_type": "audio"}, UploadRefusal.UNSUPPORTED_MEDIA_TYPE),
        ({"media_type": "carousel"}, UploadRefusal.UNSUPPORTED_MEDIA_TYPE),
        ({"content_type": "image/png"}, UploadRefusal.UNSUPPORTED_CONTENT_TYPE),
        ({"content_type": "image/heic"}, UploadRefusal.UNSUPPORTED_CONTENT_TYPE),
        ({"content_type": "video/mp4"}, UploadRefusal.UNSUPPORTED_CONTENT_TYPE),
        (
            {"media_type": "video", "content_type": "image/jpeg"},
            UploadRefusal.UNSUPPORTED_CONTENT_TYPE,
        ),
        (
            {"media_type": "video", "content_type": "video/webm"},
            UploadRefusal.UNSUPPORTED_CONTENT_TYPE,
        ),
        ({"width": 0, "height": 100}, UploadRefusal.INVALID_SIZE),
        ({"size_bytes": -1}, UploadRefusal.INVALID_SIZE),
        ({"size_bytes": 8 * 1024 * 1024 + 1}, UploadRefusal.IMAGE_TOO_LARGE),
        ({"poster_object_key": _key()}, UploadRefusal.INVALID_POSTER),  # an image has none
        (
            {
                "media_type": "video",
                "content_type": "video/mp4",
                "poster_object_key": _key(OTHER),
            },
            UploadRefusal.INVALID_POSTER,
        ),
    ],
)
def test_an_upload_the_planner_could_never_publish_is_refused_with_a_stable_code(
    overrides: dict[str, object], code: UploadRefusal
) -> None:
    assert _refusal(_upload(**overrides)) is code


def test_every_refusal_has_plain_spanish_text_for_the_owner() -> None:
    assert set(REFUSAL_TEXT) == set(UploadRefusal)
    for text in REFUSAL_TEXT.values():
        assert text and text.endswith(".")
        for anglicism in ("upload", "post", "file", "Brand Kit", "error"):
            assert anglicism.lower() not in text.lower()


def test_accepted_uploads_are_returned_with_a_normalized_content_type() -> None:
    image = _upload(content_type="image/JPG", size_bytes=8 * 1024 * 1024)
    assert check_upload(TENANT, image).content_type == "image/jpeg"
    video = _upload(
        media_type="video",
        content_type="video/quicktime; codecs=avc1",
        duration_seconds=12.5,
        size_bytes=200 * 1024 * 1024,  # the 8 MB ceiling is the image's only
        poster_object_key=_key(),
    )
    assert check_upload(TENANT, video).content_type == "video/quicktime"
    assert normalized_content_type(" Video/MP4 ") == "video/mp4"


# -- the category/format rule -----------------------------------------------------------


@pytest.mark.parametrize(
    ("media_type", "size", "expected"),
    [
        ("video", None, (PostCategory.REEL, ContentFormat.REELS_9_16)),
        ("video", (1920, 1080), (PostCategory.REEL, ContentFormat.REELS_9_16)),
        ("image", None, (PostCategory.GALERIA, ContentFormat.FEED_4_5)),
        ("image", (1080, 1350), (PostCategory.GALERIA, ContentFormat.FEED_4_5)),
        ("image", (1080, 1080), (PostCategory.GALERIA, ContentFormat.FEED_1_1)),
        ("image", (1910, 1000), (PostCategory.GALERIA, ContentFormat.FEED_4_5)),
        ("image", (1080, 1920), (PostCategory.STORY, ContentFormat.STORY_9_16)),
        ("image", (3000, 1000), (PostCategory.STORY, ContentFormat.STORY_9_16)),
    ],
)
def test_the_shape_of_a_file_never_published(
    media_type: str, size: tuple[int, int] | None, expected: tuple[PostCategory, ContentFormat]
) -> None:
    category, fmt = shape_for(media_type, *(size or (None, None)))
    assert (category, fmt) == expected
    assert fmt in ContentKind.OWN_MEDIA.formats


def test_the_idempotency_key_is_stable_and_disjoint_from_publicar() -> None:
    upload_id = uuid4()
    assert upload_request_key(upload_id) == upload_request_key(upload_id)
    assert upload_request_key(upload_id) != upload_request_key(uuid4())
    assert upload_request_key(upload_id) != request_key_for(upload_id)


def test_the_untitled_titles_are_neutral_and_publicar_keeps_its_own() -> None:
    assert title_of("", UNTITLED_IMAGE) == "Foto subida por ti"
    assert title_of("  \n", UNTITLED_VIDEO) == "Video subido por ti"
    assert title_of("") == UNTITLED  # the publish-now path is unchanged
    assert title_of("¡Hoy 2x1!\nmás", UNTITLED_IMAGE) == "¡Hoy 2x1!"


# -- schedulable and publishable, through the one rule -----------------------------------


def _candidate(upload: OwnUpload, destination: str | None = None) -> PostCandidate:
    """The candidate `DraftPostReader._candidate` builds for the piece `own_upload`
    writes: approved revision 1, the owner's caption, one asset at position 0."""
    checked = check_upload(TENANT, upload)
    category, _fmt = shape_for(checked.media_type, checked.width, checked.height)
    return PostCandidate(
        tenant_id=TENANT,
        post_id=uuid4(),
        brand_id=uuid4(),
        approval=ApprovalStatus.APPROVED,
        revision=1,
        approved_revision=1,
        category=category.value,
        caption=checked.caption,
        media=(
            MediaCandidate(
                object_key=checked.object_key,
                content_type=checked.content_type,
                media_type=checked.media_type,
                position=0,
                width=checked.width,
                height=checked.height,
            ),
        ),
        destination=destination,
    )


def _offered(media_type: str, size: tuple[int, int] | None = None) -> dict[str, bool]:
    publisher = {"image": "IMAGE", "video": "VIDEO"}[media_type]
    return {
        option.destination: option.available
        for option in destination_options((publisher,), size)
        if option.offered
    }


def test_an_image_offers_publicacion_and_historia_and_publishes_as_either() -> None:
    upload = _upload(caption="Shawarma mixto", width=1080, height=1350)
    assert _offered("image", (1080, 1350)) == {"post": True, "reel": False, "story": True}
    whole = evaluate(_candidate(upload))
    assert isinstance(whole, PublishablePost) and whole.media_product_type == "IMAGE"
    for destination, product in (("post", "IMAGE"), ("story", "STORIES")):
        verdict = evaluate(_candidate(upload, destination))
        assert isinstance(verdict, PublishablePost), verdict
        assert verdict.media_product_type == product
        assert verdict.media[0].object_key == upload.object_key
        assert verdict.media[0].content_type == "image/jpeg"
        assert verdict.caption == "Shawarma mixto"


def test_a_tall_image_is_a_story_and_publicacion_is_off_with_its_reason() -> None:
    upload = _upload(width=1080, height=1920)
    assert _offered("image", (1080, 1920)) == {"post": False, "reel": False, "story": True}
    whole = evaluate(_candidate(upload))
    assert isinstance(whole, PublishablePost) and whole.media_product_type == "STORIES"
    assert not isinstance(evaluate(_candidate(upload, "post")), PublishablePost)


def test_a_video_offers_reel_and_historia_and_publishes_as_either() -> None:
    upload = _upload(object_key=_key(), media_type="video", content_type="video/mp4")
    assert _offered("video") == {"reel": True, "story": True}
    whole = evaluate(_candidate(upload))
    assert isinstance(whole, PublishablePost) and whole.media_product_type == "REELS"
    for destination, product in (("reel", "REELS"), ("story", "STORIES")):
        verdict = evaluate(_candidate(upload, destination))
        assert isinstance(verdict, PublishablePost), verdict
        assert verdict.media_product_type == product
        assert verdict.media[0].media_type == "VIDEO"


def test_a_png_would_never_publish_which_is_why_it_is_refused_up_front() -> None:
    """The planner's rule refuses a PNG at its hour (`UNSUPPORTED_CONTENT_TYPE`), so the
    upload refuses it before any piece exists: the app converts to JPEG first."""
    candidate = _candidate(_upload())
    png = PostCandidate(
        **{
            **candidate.__dict__,
            "media": (MediaCandidate(_key(), "image/png", "image", 0),),
        }
    )
    assert not isinstance(evaluate(png), PublishablePost)
    assert _refusal(_upload(content_type="image/png")) is UploadRefusal.UNSUPPORTED_CONTENT_TYPE
