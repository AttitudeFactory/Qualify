from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from qualify_scraper.schemas import (
    ContentType,
    MediaItem,
    MediaKind,
    Platform,
    Post,
    PostMetrics,
)
from qualify_scraper.shared import RawHydration

PARSER_VERSION = "tiktok-parser-0.1.0"


def _item_struct(hydration: dict[str, Any]) -> dict[str, Any]:
    """Navigate TikTok's `__UNIVERSAL_DATA_FOR_REHYDRATION__` payload down to the
    `itemStruct` that describes a single post."""
    scope = hydration["__DEFAULT_SCOPE__"]
    detail = scope["webapp.video-detail"]
    return detail["itemInfo"]["itemStruct"]


def _detect_content_type(item: dict[str, Any]) -> ContentType:
    """Pick the native format from the signals present in the payload.

    Priority is data-driven: a photo gallery (`imagePost`) and a real video
    (`video.playAddr`) are unambiguous in real hydration JSON. Story and text
    lack a stable public discriminator, so they fall back to an explicit
    `contentTypeHint` — synthetic in our fixtures and flagged as needing
    validation against a real payload once one is available."""
    hint = item.get("contentTypeHint")
    if hint == "story":
        return ContentType.TIKTOK_STORY
    if hint == "text":
        return ContentType.TIKTOK_TEXT
    if item.get("imagePost"):
        return ContentType.TIKTOK_PHOTO
    video = item.get("video") or {}
    if video.get("playAddr"):
        return ContentType.TIKTOK_VIDEO
    return ContentType.TIKTOK_TEXT


def _extract_media(
    item: dict[str, Any], content_type: ContentType
) -> tuple[list[MediaItem], int | None]:
    if content_type == ContentType.TIKTOK_PHOTO:
        images = item["imagePost"]["images"]
        media = [
            MediaItem(
                kind=MediaKind.IMAGE,
                url=image["imageURL"]["urlList"][0],
                ordinal=index,
            )
            for index, image in enumerate(images)
        ]
        return media, None
    if content_type in (ContentType.TIKTOK_VIDEO, ContentType.TIKTOK_STORY):
        video = item.get("video") or {}
        play_addr = video.get("playAddr")
        if not play_addr:
            return [], None
        duration_ms = int(video.get("duration", 0)) * 1000 or None
        media = [MediaItem(kind=MediaKind.VIDEO, url=play_addr, duration_ms=duration_ms)]
        return media, duration_ms
    return [], None


def parse_tiktok(raw: RawHydration, brand_id: UUID, pipeline_version: str) -> Post:
    """Convert a saved TikTok hydration payload into a typed Post.

    Provenance (`hydration_json_r2_key`, `source_url`, `scraped_at`) comes from
    the RawHydration wrapper, so every parsed post keeps a reference back to the
    raw JSON it was built from."""
    item = _item_struct(raw.hydration)
    content_type = _detect_content_type(item)
    media, duration_ms = _extract_media(item, content_type)

    author = item.get("author") or {}
    stats = item.get("stats") or {}

    return Post(
        brand_id=brand_id,
        platform=Platform.TIKTOK,
        post_id=str(item["id"]),
        content_type=content_type,
        creator_handle=author.get("uniqueId", ""),
        creator_id=str(author.get("id", "")),
        post_url=raw.url,
        caption=item.get("desc", ""),
        posted_at=datetime.fromtimestamp(int(item["createTime"])),
        metrics=PostMetrics(
            views=int(stats.get("playCount", 0)),
            likes=int(stats.get("diggCount", 0)),
            comments_count=int(stats.get("commentCount", 0)),
            shares=int(stats.get("shareCount", 0)),
        ),
        media=media,
        duration_ms=duration_ms,
        hydration_json_r2_key=raw.r2_key,
        source_url=raw.url,
        scraped_at=raw.fetched_at,
        parser_version=PARSER_VERSION,
        pipeline_version=pipeline_version,
    )
