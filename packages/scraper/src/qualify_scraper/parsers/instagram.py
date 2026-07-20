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
from qualify_scraper.shared import RawPayloadEnvelope

PARSER_VERSION = "instagram-parser-0.1.0"


def _shortcode_media(hydration: dict[str, Any]) -> dict[str, Any]:
    """Navigate Instagram's embedded page data down to the `shortcode_media`
    node that describes a single post."""
    return hydration["graphql"]["shortcode_media"]


def _caption(media: dict[str, Any]) -> str:
    edges = media.get("edge_media_to_caption", {}).get("edges", [])
    if edges:
        return edges[0]["node"].get("text", "")
    return ""


def _detect_content_type(media: dict[str, Any]) -> ContentType:
    """Pick the native IG format.

    Carousels (`edge_sidecar_to_children`) and reels (`product_type == "clips"`)
    are unambiguous in real page data. Stories are not served on the shortcode
    page, so they fall back to an explicit `product_type == "story"` marker —
    synthetic in our fixtures and flagged as needing validation against a real
    story payload once one is available."""
    product_type = media.get("product_type")
    if product_type == "story":
        return ContentType.INSTAGRAM_STORY
    if media.get("edge_sidecar_to_children"):
        return ContentType.INSTAGRAM_CAROUSEL
    if product_type == "clips":
        return ContentType.INSTAGRAM_REEL
    return ContentType.INSTAGRAM_POST


def _media_item(node: dict[str, Any], ordinal: int) -> MediaItem:
    if node.get("is_video"):
        duration = node.get("video_duration")
        return MediaItem(
            kind=MediaKind.VIDEO,
            url=node["video_url"],
            ordinal=ordinal,
            duration_ms=int(duration * 1000) if duration is not None else None,
        )
    return MediaItem(kind=MediaKind.IMAGE, url=node["display_url"], ordinal=ordinal)


def _extract_media(
    media: dict[str, Any], content_type: ContentType
) -> tuple[list[MediaItem], int | None]:
    if content_type == ContentType.INSTAGRAM_CAROUSEL:
        edges = media["edge_sidecar_to_children"]["edges"]
        items = [_media_item(edge["node"], index) for index, edge in enumerate(edges)]
        return items, None
    item = _media_item(media, 0)
    duration_ms = item.duration_ms if item.kind == MediaKind.VIDEO else None
    return [item], duration_ms


def parse_instagram(
    envelope: RawPayloadEnvelope,
    *,
    r2_key: str,
    brand_id: UUID,
    pipeline_version: str,
) -> Post:
    """Convert a captured Instagram envelope into a typed Post.

    `source_url`, `scraped_at`, and `content_signature` come from the envelope;
    `hydration_json_r2_key` is the caller-threaded `r2_key` — `persist_envelope`'s
    return — so a Post cannot be built without the raw having been persisted first
    (raw-before-parse rule). `r2_key`, `brand_id`, and `pipeline_version` are
    keyword-only: `r2_key`/`pipeline_version` are both `str`, so keyword-only removes
    a silent positional-swap footgun. `parser_version` is a parser-internal constant
    (not a caller arg) — the code-that-reads-the-hydration axis."""
    media = _shortcode_media(envelope.hydration)
    content_type = _detect_content_type(media)
    media_items, duration_ms = _extract_media(media, content_type)

    owner = media.get("owner") or {}

    return Post(
        brand_id=brand_id,
        platform=Platform.INSTAGRAM,
        post_id=str(media.get("shortcode") or media["id"]),
        content_type=content_type,
        creator_handle=owner.get("username", ""),
        creator_id=str(owner.get("id", "")),
        post_url=envelope.source_url,
        caption=_caption(media),
        posted_at=datetime.fromtimestamp(int(media["taken_at_timestamp"])),
        metrics=PostMetrics(
            views=int(media.get("video_view_count", 0)),
            likes=int(media.get("edge_media_preview_like", {}).get("count", 0)),
            comments_count=int(media.get("edge_media_to_comment", {}).get("count", 0)),
            shares=0,
        ),
        media=media_items,
        duration_ms=duration_ms,
        hydration_json_r2_key=r2_key,
        content_signature=envelope.content_signature,
        source_url=envelope.source_url,
        scraped_at=envelope.fetched_at,
        parser_version=PARSER_VERSION,
        pipeline_version=pipeline_version,
    )
