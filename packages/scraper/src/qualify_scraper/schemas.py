from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, model_validator

from qualify_scraper.shared import Platform, ScrapeProvenance, make_natural_key

__all__ = [
    "ContentType",
    "MediaItem",
    "MediaKind",
    "Platform",
    "Post",
    "PostMetrics",
    "ScrapeProvenance",
]


class ContentType(StrEnum):
    """Platform-native post formats in scope for Fase 1 Parte 2.

    Values are platform-prefixed so the discriminator is unambiguous across
    platforms (a TikTok photo gallery and an IG carousel are both multi-image
    but are distinct native formats).
    """

    TIKTOK_VIDEO = "tiktok_video"
    TIKTOK_PHOTO = "tiktok_photo"
    TIKTOK_STORY = "tiktok_story"
    TIKTOK_TEXT = "tiktok_text"
    INSTAGRAM_REEL = "instagram_reel"
    INSTAGRAM_POST = "instagram_post"
    INSTAGRAM_CAROUSEL = "instagram_carousel"
    INSTAGRAM_STORY = "instagram_story"


class MediaKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class MediaItem(BaseModel):
    """A single media element of a post.

    Isolated submodel: single-video posts carry one VIDEO item, galleries /
    carousels carry many IMAGE items, text-only posts carry none. Kept separate
    so the media shape can evolve without touching the Post top level.
    """

    kind: MediaKind
    url: str
    ordinal: int = 0
    duration_ms: int | None = None
    r2_key: str = ""


class PostMetrics(BaseModel):
    """Normalized engagement metrics. Nested to keep the Post top level stable
    while the exact metric set is still provisional (pending architect sign-off)."""

    views: int = 0
    likes: int = 0
    comments_count: int = 0
    shares: int = 0


class Post(ScrapeProvenance):
    """Typed post, shaped after ingestion.posts (plan-ingesta-social.md §3.2)
    and extended to cover multi-media and text-only formats via `content_type`
    + `media`. Provisional until architect signs off — it constrains the
    eventual ClickHouse DDL."""

    brand_id: UUID
    platform: Platform
    post_id: str
    content_type: ContentType
    creator_handle: str
    creator_id: str
    post_url: str
    caption: str = ""
    posted_at: datetime
    metrics: PostMetrics = PostMetrics()
    media: list[MediaItem] = []
    duration_ms: int | None = None

    @model_validator(mode="after")
    def _content_type_matches_platform(self) -> Post:
        """content_type is denormalized against platform; assert the prefix
        matches so a parser mislabeling a post is caught at construction."""
        if not self.content_type.value.startswith(self.platform.value):
            raise ValueError(
                f"content_type {self.content_type.value!r} does not match "
                f"platform {self.platform.value!r}"
            )
        return self

    @property
    def natural_key(self) -> tuple[str, Platform, str]:
        """Idempotency key (brand_id, platform, post_id) — checkable from the
        schema alone so dedup does not depend on the storage layer."""
        return make_natural_key(self.brand_id, self.platform, self.post_id)
