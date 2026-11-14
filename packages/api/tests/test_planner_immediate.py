"""Offline tests for «Publicar» → «Tu semana» (m-25019217): which attempts become a
piece + a `published` calendar event, and in what shape (`planner.immediate`), the
owner's copy (`creative.own_media`), the publishability of the piece it makes, the tick's
sweep hook and the attempt recording its staged object. The SQL (idempotency, RLS,
`list_week`, retention) is in `test_planner_immediate_db.py`."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind, PostCategory, ReuseType

from qualify_api.creative.own_media import (
    OwnMediaItem,
    OwnMediaPiece,
    own_copy,
    request_key_for,
    title_of,
)
from qualify_api.planner.gallery import GalleryState, gallery_state
from qualify_api.planner.immediate import (
    AttemptFacts,
    ChildFacts,
    Outcome,
    PublicationPlan,
    RecordResult,
    Skip,
    eligibility,
    plan_publication,
)
from qualify_api.planner.post_reader import ApprovalStatus, PostSummary, PublishablePost
from qualify_api.planner.publishable import MediaCandidate, PostCandidate, evaluate
from qualify_api.planner.tick import TickRunner

TENANT = UUID("a0000000-0000-4000-8000-0000000025a1")
SETTLED = datetime(2026, 11, 13, 15, 4, 5, tzinfo=UTC)
CAPTION = "Shawarma mixto 🌯\n\n¡Hoy 2x1!\n\n#shawarma #sancristobal"


def _attempt(
    *,
    product: str = "IMAGE",
    key: str = "web:abc",
    status: str = "published",
    settled_at: datetime | None = SETTLED,
    caption: str | None = CAPTION,
    object_key: str | None = None,
    content_type: str | None = "image/jpeg",
) -> AttemptFacts:
    return AttemptFacts(
        id=uuid4(),
        idempotency_key=key,
        status=status,
        settled_at=settled_at,
        caption=caption,
        media_product_type=product,
        media_object_key=(
            object_key if object_key is not None else f"t/{TENANT}/media/{uuid4()}/{uuid4()}"
        ),
        media_content_type=content_type,
    )


# -- eligibility: only what Instagram accepted from «Publicar» --------------------------


@pytest.mark.parametrize(
    ("changes", "skip"),
    [
        ({"status": "failed"}, Skip.NOT_PUBLISHED),
        ({"status": "unknown"}, Skip.NOT_PUBLISHED),
        ({"status": "processing", "settled_at": None}, Skip.NOT_SETTLED),
        ({"key": f"cal:{uuid4()}:1"}, Skip.CALENDAR_ATTEMPT),
        # the executor's attempt is never ours, even settled published
        ({"key": f"cal:{uuid4()}:3", "status": "published"}, Skip.CALENDAR_ATTEMPT),
    ],
)
def test_a_failed_unsettled_or_calendar_attempt_creates_nothing(
    changes: dict[str, object], skip: Skip
) -> None:
    attempt = _attempt(**changes)  # type: ignore[arg-type]
    assert eligibility(attempt) is skip
    assert plan_publication(attempt) is skip


def test_a_published_attempt_from_publicar_is_recorded_at_its_settled_time() -> None:
    attempt = _attempt()
    plan = plan_publication(attempt)
    assert isinstance(plan, PublicationPlan)
    assert plan.published_at == SETTLED
    assert plan.caption == CAPTION
    assert (plan.category, plan.format, plan.destination) == (
        PostCategory.GALERIA,
        ContentFormat.FEED_4_5,
        "post",
    )
    assert plan.items == (OwnMediaItem(attempt.media_object_key or "", "image/jpeg", "image", 0),)


@pytest.mark.parametrize(
    ("product", "content_type", "shape"),
    [
        ("REELS", "video/mp4", (PostCategory.REEL, ContentFormat.REELS_9_16, "reel", "video")),
        (
            "VIDEO",
            "video/quicktime",
            (PostCategory.REEL, ContentFormat.REELS_9_16, "reel", "video"),
        ),
        ("STORIES", "image/jpeg", (PostCategory.STORY, ContentFormat.STORY_9_16, "story", "image")),
        ("STORIES", "video/mp4", (PostCategory.STORY, ContentFormat.STORY_9_16, "story", "video")),
        # an image's type is JPEG by construction («Publicar» stages only JPEG)
        ("IMAGE", None, (PostCategory.GALERIA, ContentFormat.FEED_4_5, "post", "image")),
    ],
)
def test_each_single_publication_maps_to_its_shape(
    product: str, content_type: str | None, shape: tuple[object, ...]
) -> None:
    plan = plan_publication(_attempt(product=product, content_type=content_type))
    assert isinstance(plan, PublicationPlan)
    category, fmt, destination, media_type = shape
    assert (plan.category, plan.format, plan.destination) == (category, fmt, destination)
    assert [item.media_type for item in plan.items] == [media_type]


def test_a_single_attempt_without_its_staged_object_writes_nothing() -> None:
    # attempts written before 0159 never recorded the object (the backfill reads Meta)
    assert plan_publication(_attempt(object_key="")) is Skip.NO_MEDIA
    assert plan_publication(_attempt(product="REELS", content_type=None)) is Skip.NO_MEDIA
    assert plan_publication(_attempt(product="REELS", content_type="image/jpeg")) is (
        Skip.UNSUPPORTED_TYPE
    )
    assert plan_publication(_attempt(product="SOMETHING")) is Skip.UNSUPPORTED_TYPE


def test_a_carousel_is_one_piece_with_its_items_in_order() -> None:
    attempt = _attempt(product="CAROUSEL", object_key="", content_type=None)
    keys = [f"t/{TENANT}/media/c/{n}" for n in range(3)]
    children = (
        ChildFacts(2, keys[2], "video/mp4", "VIDEO"),
        ChildFacts(0, keys[0], "image/jpeg", "IMAGE"),
        ChildFacts(1, keys[1], "image/jpeg", "IMAGE"),
    )
    plan = plan_publication(attempt, children)
    assert isinstance(plan, PublicationPlan)
    assert [(i.object_key, i.media_type, i.position) for i in plan.items] == [
        (keys[0], "image", 0),
        (keys[1], "image", 1),
        (keys[2], "video", 2),
    ]
    assert (plan.category, plan.destination) == (PostCategory.GALERIA, "post")
    assert plan_publication(attempt, ()) is Skip.NO_MEDIA


def test_n_single_attempts_make_n_pieces() -> None:
    """«Una por una» = N attempts = N pieces: each attempt is its own source."""
    attempts = [_attempt() for _ in range(4)]
    plans = [plan_publication(a) for a in attempts]
    assert all(isinstance(p, PublicationPlan) and len(p.items) == 1 for p in plans)
    keys = {request_key_for(a.id) for a in attempts}
    assert len(keys) == 4
    assert request_key_for(attempts[0].id) == request_key_for(attempts[0].id)


# -- the piece: its caption, and that it can be planned again ----------------------------


@pytest.mark.parametrize(
    "caption", [CAPTION, "", "  espacios al borde  ", "una línea", "#solo #hashtags"]
)
def test_the_rendered_caption_equals_the_published_one(caption: str) -> None:
    assert own_copy(caption).rendered_caption() == caption


def test_the_title_is_the_first_line_or_a_fallback() -> None:
    assert title_of(CAPTION) == "Shawarma mixto 🌯"
    assert title_of("") == "Publicación desde Publicar"
    assert len(title_of("x" * 300)) == 80


def _candidate(plan: PublicationPlan, destination: str | None = None) -> PostCandidate:
    """What `DraftPostReader._candidate` builds from the rows `create_own_media_piece`
    writes (approved, revision 1, the variant's rendered caption, the assets)."""
    return PostCandidate(
        tenant_id=TENANT,
        post_id=uuid4(),
        brand_id=uuid4(),
        approval=ApprovalStatus.APPROVED,
        revision=1,
        approved_revision=1,
        category=plan.category.value,
        caption=own_copy(plan.caption).rendered_caption(),
        media=tuple(
            MediaCandidate(
                object_key=item.object_key,
                content_type=item.content_type,
                media_type=item.media_type,
                position=item.position,
            )
            for item in plan.items
        ),
        destination=destination,
    )


@pytest.mark.parametrize(
    ("product", "content_type", "expected"),
    [
        ("IMAGE", "image/jpeg", "IMAGE"),
        ("REELS", "video/mp4", "REELS"),
        ("STORIES", "image/jpeg", "STORIES"),
        ("STORIES", "video/mp4", "STORIES"),
    ],
)
def test_the_piece_passes_evaluate_and_can_be_scheduled_again(
    product: str, content_type: str, expected: str
) -> None:
    plan = plan_publication(_attempt(product=product, content_type=content_type))
    assert isinstance(plan, PublicationPlan)
    for destination in (None, plan.destination):
        verdict = evaluate(_candidate(plan, destination))
        assert isinstance(verdict, PublishablePost), verdict
        assert verdict.media_product_type == expected
        assert verdict.caption == plan.caption


def test_a_carousel_piece_passes_evaluate_as_a_carousel() -> None:
    attempt = _attempt(product="CAROUSEL", object_key="", content_type=None)
    children = tuple(
        ChildFacts(n, f"t/{TENANT}/media/c/{n}", "image/jpeg", "IMAGE") for n in range(3)
    )
    plan = plan_publication(attempt, children)
    assert isinstance(plan, PublicationPlan)
    verdict = evaluate(_candidate(plan, plan.destination))
    assert isinstance(verdict, PublishablePost)
    assert verdict.media_product_type == "CAROUSEL"
    assert [m.object_key for m in verdict.media] == [c.media_object_key for c in children]


def test_a_recurring_piece_stays_offered_in_the_gallery_after_publishing() -> None:
    """`reuse_type = recurrente`: a published one-shot piece would read USED and never be
    offered again (`planner.gallery`)."""
    summary = PostSummary(
        post_id=uuid4(),
        brand_id=uuid4(),
        title="x",
        caption_excerpt="x",
        approval=ApprovalStatus.APPROVED,
        lifecycle_status="approved",
        is_publishable=True,
        reuse_type=ReuseType.RECURRENTE.value,
        times_published=1,
        has_live_event=False,
    )
    assert gallery_state(summary) is GalleryState.SCHEDULABLE


def test_the_piece_validates_its_own_shape() -> None:
    item = OwnMediaItem(f"t/{TENANT}/media/c/1", "image/jpeg", "image", 0)
    common = {
        "brand_id": uuid4(),
        "user_id": uuid4(),
        "caption": "",
        "category": PostCategory.GALERIA,
        "format": ContentFormat.FEED_4_5,
        "approved_at": SETTLED,
        "request_key": uuid4(),
    }
    OwnMediaPiece(items=(item,), **common)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OwnMediaPiece(items=(), **common)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        OwnMediaPiece(items=(item, item), **common)  # type: ignore[arg-type]


def test_own_media_is_a_kind_never_offered_to_create() -> None:
    assert ContentKind.OWN_MEDIA.value == "own_media"
    assert not ContentKind.OWN_MEDIA.is_offered
    assert not ContentKind.SHOT_VIDEO.is_offered
    assert ContentKind.OWN_MEDIA.is_own_media
    assert not ContentKind.OWN_MEDIA.requires_ai_disclosure
    assert [k.value for k in ContentKind if k.is_offered] == [
        "creator_script",
        "avatar_video",
        "animated_avatar_video",
        "static_flyer",
        "template",
        "carousel",
        "clip",
    ]


# -- the tick's sweep hook ---------------------------------------------------------------


class _NoEvents:
    def list_in_flight(self, *, tenant_id: UUID, limit: int = 100) -> list[object]:
        return []

    def list_due(self, *, tenant_id: UUID, now: datetime, limit: int = 100) -> list[object]:
        return []


class _Tenants:
    def tenants(self, *, now: datetime) -> list[UUID]:
        return [TENANT]


async def test_the_tick_runs_the_sweep_per_tenant_and_counts_what_it_recorded() -> None:
    calls: list[tuple[UUID, datetime]] = []
    attempt = uuid4()

    def sweep(*, tenant_id: UUID, now: datetime) -> list[RecordResult]:
        calls.append((tenant_id, now))
        return [
            RecordResult(attempt, Outcome.RECORDED, draft_id=uuid4(), event_id=uuid4()),
            RecordResult(uuid4(), Outcome.SKIPPED, skip=Skip.NO_BRAND),
        ]

    runner = TickRunner(
        tenants=_Tenants(),
        repository=_NoEvents(),  # type: ignore[arg-type]
        executor=object(),  # type: ignore[arg-type]
        clock=lambda: SETTLED,
        immediate=sweep,
    )
    report = await runner.run_once()
    assert calls == [(TENANT, SETTLED)]
    assert report.tenants[0].operations == 1
    assert report.tenants[0].errors == []


async def test_a_failing_sweep_is_recorded_and_never_stops_the_tick() -> None:
    def sweep(*, tenant_id: UUID, now: datetime) -> list[RecordResult]:
        raise RuntimeError("db down")

    runner = TickRunner(
        tenants=_Tenants(),
        repository=_NoEvents(),  # type: ignore[arg-type]
        executor=object(),  # type: ignore[arg-type]
        clock=lambda: SETTLED,
        immediate=sweep,
    )
    report = await runner.run_once()
    assert report.tenants[0].errors == ["sweep:RuntimeError"]


async def test_without_a_sweep_the_tick_is_unchanged() -> None:
    runner = TickRunner(
        tenants=_Tenants(),
        repository=_NoEvents(),  # type: ignore[arg-type]
        executor=object(),  # type: ignore[arg-type]
        clock=lambda: SETTLED,
    )
    report = await runner.run_once()
    assert report.tenants[0].recorded == []
    assert report.tenants[0].operations == 0


@pytest.mark.parametrize(
    ("product", "children", "category", "destination", "evaluated_as"),
    [
        # one photo: category `galeria` (as a generated single image), «Publicación»
        ("IMAGE", 0, PostCategory.GALERIA, "post", "IMAGE"),
        ("CAROUSEL", 3, PostCategory.GALERIA, "post", "CAROUSEL"),
        ("REELS", 0, PostCategory.REEL, "reel", "REELS"),
        ("STORIES", 0, PostCategory.STORY, "story", "STORIES"),
    ],
)
def test_the_four_shapes_map_to_their_category_and_destination(
    product: str, children: int, category: PostCategory, destination: str, evaluated_as: str
) -> None:
    content_type = "video/mp4" if product == "REELS" else "image/jpeg"
    kids = tuple(
        ChildFacts(n, f"t/{TENANT}/media/c/{n}", "image/jpeg", "IMAGE") for n in range(children)
    )
    plan = plan_publication(_attempt(product=product, content_type=content_type), kids)
    assert isinstance(plan, PublicationPlan)
    assert (plan.category, plan.destination) == (category, destination)
    verdict = evaluate(_candidate(plan, plan.destination))
    assert isinstance(verdict, PublishablePost) and verdict.media_product_type == evaluated_as
