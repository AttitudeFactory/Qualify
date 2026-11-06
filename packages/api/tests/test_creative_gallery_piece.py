"""CM-6 (m-24955927): a carousel made from the media the owner chose in Galería — offline.

The `?medios=` grammar, the selection (validation, order, the tenth, short videos), the
segment rule (D2), the sound rule (D1/D3/D6), the brief and its provenance, the quota (D5:
one creation, no video seconds — now or at approval), the producer's own copy of each file
(ADR 39) and its refusal when a medium is gone, all over fakes: no R2, no Claude, no
BytePlus, no FFmpeg.
"""

from __future__ import annotations

import io
from typing import Any
from uuid import UUID, uuid4

import pytest
from PIL import Image
from pydantic import ValidationError
from qualify_creative.creations import REQUEST_CAROUSEL, weight_for
from qualify_creative.enums import (
    BriefObjective,
    ContentFormat,
    ContentKind,
    ImageRoute,
    SlideSource,
    SlideText,
)
from qualify_creative.schemas import CarouselSlide, ContentBrief, MediaInputs
from qualify_creative.video import FittedVideo

from qualify_api.creative.brand_references import BrandReferenceError
from qualify_api.creative.creations import InMemoryCreationsLedger
from qualify_api.creative.gallery_media import (
    GALLERY_ASSEMBLY_VERSION,
    GalleryMedium,
    GalleryRef,
    select_segment,
)
from qualify_api.creative.gallery_piece import (
    DROPPED_TEXT,
    GalleryPieces,
    NotEnoughMedia,
    format_media_query,
    gallery_brief,
    parse_media_query,
    resolve_selection,
)
from qualify_api.creative.media import FailureReason, generated_key
from qualify_api.stock.guard import MISPLACED_TEXT, stock_problems

from .test_creative_media_byteplus import (
    BRAND_ID,
    TENANT_ID,
    FakeSeedance,
    FakeSeedream,
    _produce,
    _producer,
    _store,
)

BUSINESS, PRODUCT = "business", "product"


def _photo(origin: str = BUSINESS, media_id: UUID | None = None) -> GalleryMedium:
    media_id = media_id or uuid4()
    key = (
        f"t/{TENANT_ID}/gallery/{media_id}/photo.jpg"
        if origin == BUSINESS
        else f"uploads/{TENANT_ID}/catalog/{uuid4()}/{media_id}.jpg"
    )
    return GalleryMedium(
        origin=origin,
        media_id=media_id,
        media_type="image",
        object_key=key,
        poster_key=None,
        duration_ms=None,
        has_audio=False,
        product_name="Smash doble" if origin == PRODUCT else "",
    )


def _video(origin: str = BUSINESS, *, ms: int | None = 42_000, audio: bool = True) -> GalleryMedium:
    media_id = uuid4()
    key = (
        f"t/{TENANT_ID}/gallery/{media_id}/video.mp4"
        if origin == BUSINESS
        else f"uploads/{TENANT_ID}/catalog/{uuid4()}/{media_id}.mp4"
    )
    return GalleryMedium(
        origin=origin,
        media_id=media_id,
        media_type="video",
        object_key=key,
        poster_key=f"t/{TENANT_ID}/gallery/{media_id}/poster.jpg" if origin == BUSINESS else None,
        duration_ms=ms,
        has_audio=audio and origin == BUSINESS,
        product_name="Smash doble" if origin == PRODUCT else "",
    )


class FakeReader:
    """The brand's live Galería: only what was put in it, only for BRAND_ID / TENANT_ID."""

    def __init__(self, *media: GalleryMedium) -> None:
        self.live = {m.ref: m for m in media}
        self.asked: list[tuple[UUID, UUID, tuple[GalleryRef, ...]]] = []

    def resolve(
        self, *, tenant_id: UUID, brand_id: UUID, refs: Any
    ) -> dict[GalleryRef, GalleryMedium]:
        self.asked.append((tenant_id, brand_id, tuple(refs)))
        if tenant_id != TENANT_ID or brand_id != BRAND_ID:
            return {}
        return {r: self.live[r] for r in refs if r in self.live}


def _base(**over: object) -> ContentBrief:
    values: dict[str, object] = {
        "brand_id": BRAND_ID,
        "objective": BriefObjective.SALE,
        "topic": "Así es nuestro local",
        "image_route": ImageRoute.TEMPLATE_ONLY,
    }
    values.update(over)
    return ContentBrief.model_validate(values)


def _query(*media: GalleryMedium) -> str:
    return format_media_query([m.ref for m in media])


def _selection(reader: FakeReader, raw: str):  # noqa: ANN202
    return resolve_selection(
        reader, tenant_id=TENANT_ID, brand_id=BRAND_ID, query=parse_media_query(raw)
    )


# -- the `medios` value --------------------------------------------------------------------


def test_the_media_query_round_trips_in_the_owners_order() -> None:
    a, b, c = _photo(), _video(PRODUCT), _video()
    raw = _query(a, b, c)
    assert raw.startswith(f"n:{a.media_id},p:{b.media_id},n:")
    assert parse_media_query(raw).refs == (a.ref, b.ref, c.ref)
    assert parse_media_query([f"n:{a.media_id}", f"p:{b.media_id}"]).refs == (a.ref, b.ref)


@pytest.mark.parametrize(
    "raw", ["x:" + str(uuid4()), "n:not-a-uuid", "n", ":", f"producto:{uuid4()}", "n:" + "1" * 40]
)
def test_a_malformed_item_is_counted_never_raised(raw: str) -> None:
    parsed = parse_media_query(f"{raw},n:{UUID(int=1)}")
    assert parsed.refs == (GalleryRef(BUSINESS, UUID(int=1)),)
    assert parsed.malformed == 1


def test_an_empty_query_is_an_empty_selection() -> None:
    assert parse_media_query(None).refs == ()
    assert parse_media_query("").refs == ()
    assert not _selection(FakeReader(), "").enough


# -- the selection: validated under RLS, in order, at most 10 ---------------------------------


def test_media_of_another_business_or_removed_are_left_out_without_an_error() -> None:
    """Criterion 1: like `?producto=` (m-24842972) — foreign, removed or malformed is
    dropped silently; /create says so with CM-7's text."""
    mine, also_mine = _photo(), _video()
    foreign, removed = _photo(), _video()  # not in this brand's live Galería
    reader = FakeReader(mine, also_mine)
    selection = _selection(
        reader, ",".join([_query(foreign, mine), "n:bad", _query(removed, also_mine)])
    )
    assert [m.media_id for m in selection.media] == [mine.media_id, also_mine.media_id]
    assert selection.dropped == 3
    assert selection.dropped_text == DROPPED_TEXT
    # every lookup goes through the reader with the caller's tenant and brand
    assert {(t, b) for t, b, _ in reader.asked} == {(TENANT_ID, BRAND_ID)}


def test_a_repeat_is_used_once_and_the_eleventh_is_left_out() -> None:
    media = [_photo() for _ in range(11)]
    reader = FakeReader(*media)
    selection = _selection(reader, _query(media[0], *media))
    assert [m.media_id for m in selection.media] == [m.media_id for m in media[:10]]
    assert selection.dropped == 1  # the eleventh; the repeat is not «gone»


def test_a_video_too_short_for_instagram_is_left_out() -> None:
    short, ok, unknown = _video(ms=2_900), _video(ms=3_000), _video(ms=None)
    selection = _selection(FakeReader(short, ok, unknown), _query(short, ok, unknown))
    assert [m.media_id for m in selection.media] == [ok.media_id, unknown.media_id]
    assert selection.dropped == 1


def test_the_sound_switch_is_offered_only_for_a_business_video_with_sound() -> None:
    silent, product_clip, photo = _video(audio=False), _video(PRODUCT), _photo()
    assert not _selection(
        FakeReader(silent, product_clip, photo), _query(silent, product_clip, photo)
    ).offers_sound
    loud = _video(audio=True)
    assert _selection(FakeReader(loud, photo), _query(loud, photo)).offers_sound


# -- the segment (D2) ----------------------------------------------------------------------


def test_the_segment_rule_is_the_whole_video_or_the_stretch_from_zero() -> None:
    assert select_segment(42_000) == (0, 42_000)  # a carousel plays it whole
    assert select_segment(60_000) == (0, 60_000)
    assert select_segment(42_000, 15_000) == (0, 15_000)  # a shorter format: from 0
    assert select_segment(None) == (0, 60_000)  # unknown: at most what the format asks
    with pytest.raises(ValueError):
        select_segment(10_000, 0)


# -- the brief -----------------------------------------------------------------------------


def test_the_brief_is_a_carousel_of_the_chosen_media_in_order_with_provenance() -> None:
    photo, video, clip = _photo(), _video(ms=42_400), _video(PRODUCT, ms=9_000)
    reader = FakeReader(photo, video, clip)
    selection = _selection(reader, _query(video, photo, clip))
    brief = gallery_brief(_base(format=ContentFormat.REELS_9_16), selection)

    assert brief.kind is ContentKind.CAROUSEL
    assert brief.format is ContentFormat.FEED_4_5  # a carousel has no 9:16: its default
    assert brief.image_route is ImageRoute.FROM_UPLOAD
    assert brief.source_media_key == video.object_key
    assert brief.topic == "Así es nuestro local"
    assert brief.product_ref == "Smash doble"  # the one product among the chosen
    assert not brief.requires_ai_disclosure  # nothing generated
    media = brief.media
    assert media.gallery_assembly_version == GALLERY_ASSEMBLY_VERSION
    assert media.gallery_audio is False  # D6: off unless the owner turns it on
    assert not media.closing_slide
    assert [s.source for s in media.slides] == [SlideSource.GALLERY] * 3
    assert [(s.gallery_origin, s.gallery_media_id, s.object_key) for s in media.slides] == [
        (BUSINESS, video.media_id, video.object_key),
        (BUSINESS, photo.media_id, photo.object_key),
        (PRODUCT, clip.media_id, clip.object_key),
    ]
    first, second, third = media.slides
    assert (first.segment_start_ms, first.segment_end_ms, first.audio) == (0, 42_400, False)
    assert (second.segment_start_ms, second.segment_end_ms, second.audio) == (None, None, False)
    assert (third.segment_start_ms, third.segment_end_ms) == (0, 9_000)
    assert all(s.text is SlideText.NONE and not s.scene_prompt for s in media.slides)
    assert stock_problems(brief) is None


def test_with_the_sound_on_only_a_business_video_with_sound_keeps_it() -> None:
    """D1/D3: the owner's switch applies to their business videos; a product's video and a
    business video saved without sound stay silent."""
    loud, silent, clip, photo = _video(), _video(audio=False), _video(PRODUCT), _photo()
    selection = _selection(FakeReader(loud, silent, clip, photo), _query(loud, silent, clip, photo))
    brief = gallery_brief(_base(), selection, use_audio=True)
    assert brief.media.gallery_audio is True
    assert [s.audio for s in brief.media.slides] == [True, False, False, False]


def test_fewer_than_two_usable_media_is_not_a_carousel() -> None:
    only = _photo()
    selection = _selection(FakeReader(only), _query(only, _photo()))
    with pytest.raises(NotEnoughMedia) as refused:
        gallery_brief(_base(), selection)
    assert refused.value.usable_count == 1 and refused.value.dropped == 1
    assert "al menos 2 fotos o videos" in str(refused.value)


def test_a_closing_slide_never_makes_an_eleventh_item() -> None:
    ten = [_photo() for _ in range(10)]
    brief = gallery_brief(_base(), _selection(FakeReader(*ten), _query(*ten)), closing_slide=True)
    assert len(brief.media.slides) == 10 and not brief.media.closing_slide
    two = ten[:2]
    brief = gallery_brief(_base(), _selection(FakeReader(*two), _query(*two)), closing_slide=True)
    assert brief.media.closing_slide


@pytest.mark.parametrize(
    "fields",
    [
        {},  # no origin, no id
        {"gallery_origin": "elsewhere", "gallery_media_id": uuid4()},
        {"gallery_origin": BUSINESS, "gallery_media_id": uuid4(), "text": SlideText.HOOK},
        {"gallery_origin": BUSINESS, "gallery_media_id": uuid4(), "segment_end_ms": 5_000},
        {
            "gallery_origin": BUSINESS,
            "gallery_media_id": uuid4(),
            "segment_start_ms": 0,
            "segment_end_ms": 61_000,
        },
        {"gallery_origin": PRODUCT, "gallery_media_id": uuid4(), "audio": True},
    ],
)
def test_a_gallery_slide_is_the_medium_as_it_is(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CarouselSlide(source=SlideSource.GALLERY, object_key="t/x/gallery/a/v.mp4", **fields)


def test_only_a_gallery_slide_names_a_gallery_medium() -> None:
    with pytest.raises(ValidationError):
        CarouselSlide(source=SlideSource.GENERATED, gallery_media_id=uuid4())


def test_a_stock_file_as_a_gallery_slide_is_refused() -> None:
    stock = f"t/{TENANT_ID}/stock/pixabay/video-1/abcdef0123456789.mp4"
    slides = (
        CarouselSlide(
            source=SlideSource.GALLERY,
            object_key=stock,
            gallery_origin=BUSINESS,
            gallery_media_id=uuid4(),
        ),
        CarouselSlide(source=SlideSource.GENERATED),
    )
    brief = _base(kind=ContentKind.CAROUSEL, media=MediaInputs(slides=slides))
    assert stock_problems(brief) == MISPLACED_TEXT


# -- the quota (D5) ------------------------------------------------------------------------


def test_a_carousel_of_own_media_is_one_creation_and_no_video_seconds() -> None:
    """D5: one creation of the month, like any other piece, and no video seconds
    (m-24921139) — however many videos it carries, and at approval too."""
    media = [_video(ms=60_000) for _ in range(6)] + [_photo() for _ in range(4)]
    brief = gallery_brief(_base(), _selection(FakeReader(*media), _query(*media)))
    price = weight_for(brief)
    assert price.request_kind == REQUEST_CAROUSEL
    assert (price.weight, price.videos, price.video_seconds) == (1, 0, 0)
    assert weight_for(brief, redo=True).video_seconds == 0


def test_creating_from_galeria_charges_one_creation_and_dispatches_the_draft() -> None:
    from .test_creations_ledger import _service

    ledger = InMemoryCreationsLedger()
    service, repo, dispatcher = _service(ledger)
    photo, video = _photo(), _video()
    pieces = GalleryPieces(content=service, reader=FakeReader(photo, video))
    created = pieces.create(
        tenant_id=TENANT_ID,
        brand_id=BRAND_ID,
        user_id=uuid4(),
        brief=_base(),
        medios=_query(photo, video) + f",n:{uuid4()}",
        use_audio=True,
    )
    assert created.dropped == 1
    (row,) = ledger.rows.values()
    assert (row.price.weight, row.price.videos, row.price.video_seconds) == (1, 0, 0)
    assert ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).left == 29
    assert dispatcher.calls  # generated out of band, like any piece
    record = repo.get_draft(tenant_id=TENANT_ID, draft_id=created.draft_id)
    stored = repo.get_brief(tenant_id=TENANT_ID, brief_id=record.brief_id)
    assert stored.kind is ContentKind.CAROUSEL and stored.media.gallery_audio
    assert [s.gallery_media_id for s in stored.media.slides] == [photo.media_id, video.media_id]
    # approving it uses no video seconds (only animated slides would)
    assert service.video_seconds_of(tenant_id=TENANT_ID, draft_id=created.draft_id) == 0
    assert service._videos_of(TENANT_ID, record) == (0, 0)


def test_too_few_media_create_nothing_and_charge_nothing() -> None:
    from .test_creations_ledger import _service

    ledger = InMemoryCreationsLedger()
    service, _, dispatcher = _service(ledger)
    photo = _photo()
    pieces = GalleryPieces(content=service, reader=FakeReader(photo))
    with pytest.raises(NotEnoughMedia):
        pieces.create(
            tenant_id=TENANT_ID,
            brand_id=BRAND_ID,
            user_id=uuid4(),
            brief=_base(),
            medios=_query(photo, _photo()),
        )
    assert ledger.rows == {} and not dispatcher.calls


# -- the producer: the piece's own copy, and a medium gone ----------------------------------


class RecordingFitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def fit(
        self,
        data: bytes,
        *,
        size: tuple[int, int],
        overlay: bytes | None = None,
        max_seconds: float = 60.0,
        keep_audio: bool = False,
        x264: Any = None,
    ) -> FittedVideo:
        self.calls.append(
            {"data": data, "size": size, "max_seconds": max_seconds, "keep_audio": keep_audio}
        )
        out = io.BytesIO()
        Image.new("RGB", size, (1, 2, 3)).save(out, format="PNG")
        return FittedVideo(
            data=b"fitted-" + data,
            width=size[0],
            height=size[1],
            duration_sec=min(max_seconds, 42.4),
            poster=out.getvalue(),
        )


def _jpeg(size: tuple[int, int] = (1080, 1440)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (200, 80, 40)).save(out, format="JPEG")
    return out.getvalue()


def _gallery_producer(reader: FakeReader, store: Any, fitter: RecordingFitter) -> Any:
    seedream, seedance = FakeSeedream(), FakeSeedance()
    producer = _producer(store, seedream=seedream, seedance=seedance)
    producer._gallery = reader
    producer._fitter = fitter
    return producer, seedream, seedance


def test_the_carousel_copies_each_medium_into_the_draft_as_it_is() -> None:
    """Copia propia (ADR 39): each file is read from Galería, fitted to the format and
    stored in THIS draft's folder; the video keeps its sound only as the slide says; no
    vendor is called; every asset carries its provenance."""
    photo, loud, clip = _photo(), _video(ms=42_400), _video(PRODUCT, ms=9_000)
    reader = FakeReader(photo, loud, clip)
    store, fitter = _store(), RecordingFitter()
    store.files[photo.object_key] = _jpeg()
    store.files[loud.object_key] = b"business-video"
    store.files[clip.object_key] = b"product-clip"
    brief = gallery_brief(_base(), _selection(reader, _query(photo, loud, clip)), use_audio=True)
    producer, seedream, seedance = _gallery_producer(reader, store, fitter)
    draft_id = uuid4()
    outcome = _produce(producer, brief, draft_id)

    assert outcome.failure is None, outcome.detail
    assert seedream.requests == [] and seedance.requests == []
    assert [(m.position, m.media_type) for m in outcome.media] == [
        (0, "image"),
        (1, "video"),
        (2, "video"),
    ]
    assert outcome.media[0].object_key == generated_key(TENANT_ID, draft_id, "slide-1.jpg")
    for asset, medium in zip(outcome.media, (photo, loud, clip), strict=True):
        assert asset.object_key != medium.object_key and str(draft_id) in asset.object_key
        assert (asset.width, asset.height) == (1080, 1350)
        assert asset.provider == "qualify" and not asset.ai_generated
        assert asset.params["source"] == "gallery"
        assert asset.params["media_id"] == str(medium.media_id)
        assert asset.params["origin"] == medium.origin
        assert asset.params["from_key"] == medium.object_key
        assert asset.params["assembly_version"] == GALLERY_ASSEMBLY_VERSION
    assert Image.open(io.BytesIO(store.files[outcome.media[0].object_key])).size == (1080, 1350)
    business_call, product_call = fitter.calls
    assert business_call["data"] == b"business-video" and business_call["keep_audio"] is True
    assert business_call["max_seconds"] == pytest.approx(42.4)
    assert product_call["data"] == b"product-clip" and product_call["keep_audio"] is False
    assert outcome.media[1].params["audio"] is True
    assert outcome.media[1].params["segment_start_ms"] == 0
    assert outcome.media[1].params["segment_end_ms"] == 42_400
    assert outcome.media[1].params["thumbnail_key"]
    assert outcome.media[2].params["audio"] is False
    # the Galería originals are untouched: removing them later breaks nothing
    assert store.files[loud.object_key] == b"business-video"


def test_with_the_sound_off_the_business_video_goes_silent() -> None:
    loud, photo = _video(), _photo()
    reader = FakeReader(loud, photo)
    store, fitter = _store(), RecordingFitter()
    store.files[loud.object_key] = b"v"
    store.files[photo.object_key] = _jpeg()
    brief = gallery_brief(_base(), _selection(reader, _query(loud, photo)))
    producer, *_ = _gallery_producer(reader, store, fitter)
    outcome = _produce(producer, brief, uuid4())
    assert outcome.failure is None
    assert fitter.calls[0]["keep_audio"] is False
    assert outcome.media[0].params["audio"] is False


def test_a_medium_removed_after_the_choice_fails_before_any_file_is_read() -> None:
    """§4.2 rule 4: removed from Galería between the choice and the run — the carousel
    refuses (nothing paid, nothing read), saying which one, and the previous version of
    any piece is untouched (the draft just fails)."""
    photo, video = _photo(), _video()
    reader = FakeReader(photo, video)
    brief = gallery_brief(_base(), _selection(reader, _query(photo, video)))
    del reader.live[video.ref]  # «Quitar» in Galería
    store, fitter = _store(), RecordingFitter()
    store.files[photo.object_key] = _jpeg()
    producer, *_ = _gallery_producer(reader, store, fitter)
    outcome = _produce(producer, brief, uuid4())
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert "La foto o video 2 ya no está en tu Galería" in (outcome.detail or "")
    assert fitter.calls == [] and outcome.media == ()


def test_a_medium_whose_file_changed_is_refused() -> None:
    photo, other = _photo(), _photo()
    reader = FakeReader(photo, other)
    brief = gallery_brief(_base(), _selection(reader, _query(photo, other)))
    reader.live[photo.ref] = GalleryMedium(
        **{**photo.__dict__, "object_key": f"t/{TENANT_ID}/gallery/{uuid4()}/photo.jpg"}
    )
    store = _store()
    store.files[other.object_key] = _jpeg()
    producer, *_ = _gallery_producer(reader, store, RecordingFitter())
    outcome = _produce(producer, brief, uuid4())
    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value


def test_a_producer_without_galeria_takes_no_gallery_slide() -> None:
    photo, other = _photo(), _photo()
    reader = FakeReader(photo, other)
    brief = gallery_brief(_base(), _selection(reader, _query(photo, other)))
    producer = _producer(_store())
    assert producer._gallery is None
    assert _produce(producer, brief, uuid4()).failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value


def test_the_check_before_the_copy_refuses_a_removed_medium() -> None:
    """The copy (Claude, paid) runs after `prepare_reference_videos`: a medium removed
    since the choice refuses the piece there, before any paid call."""
    photo, video = _photo(), _video()
    reader = FakeReader(photo, video)
    brief = gallery_brief(_base(), _selection(reader, _query(photo, video)))
    producer, *_ = _gallery_producer(reader, _store(), RecordingFitter())
    producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief)
    del reader.live[photo.ref]
    with pytest.raises(BrandReferenceError) as refused:
        producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief)
    assert "La foto o video 1 ya no está en tu Galería" in refused.value.detail
