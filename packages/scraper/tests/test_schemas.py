from datetime import datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from qualify_scraper.schemas import (
    ContentType,
    MediaItem,
    MediaKind,
    Platform,
    Post,
)


def _minimal_post(**overrides: object) -> Post:
    base: dict[str, object] = dict(
        brand_id=UUID("11111111-1111-1111-1111-111111111111"),
        platform=Platform.TIKTOK,
        post_id="abc123",
        content_type=ContentType.TIKTOK_VIDEO,
        creator_handle="handle",
        creator_id="creator_1",
        post_url="https://tiktok.example/@handle/video/abc123",
        posted_at=datetime.fromtimestamp(1710460800),
        hydration_json_r2_key="hydration/video.json",
        content_signature="sha256:" + "0" * 64,
        source_url="https://tiktok.example/@handle/video/abc123",
        scraped_at=datetime.fromtimestamp(0),
        parser_version="tiktok-parser-0.1.0",
        pipeline_version="0.1.0",
    )
    base.update(overrides)
    return Post(**base)


def test_natural_key_is_brand_platform_post() -> None:
    post = _minimal_post()
    assert post.natural_key == (
        "11111111-1111-1111-1111-111111111111",
        Platform.TIKTOK,
        "abc123",
    )


def test_provenance_is_mandatory() -> None:
    with pytest.raises(ValidationError):
        Post(
            brand_id=UUID("11111111-1111-1111-1111-111111111111"),
            platform=Platform.TIKTOK,
            post_id="abc123",
            content_type=ContentType.TIKTOK_VIDEO,
            creator_handle="handle",
            creator_id="creator_1",
            post_url="https://tiktok.example/@handle/video/abc123",
            posted_at=datetime.fromtimestamp(1710460800),
        )  # type: ignore[call-arg]


def test_media_items_ordered_by_ordinal() -> None:
    post = _minimal_post(
        content_type=ContentType.TIKTOK_PHOTO,
        media=[
            MediaItem(kind=MediaKind.IMAGE, url="https://x/1.jpg", ordinal=0),
            MediaItem(kind=MediaKind.IMAGE, url="https://x/2.jpg", ordinal=1),
        ],
    )
    assert [m.ordinal for m in post.media] == [0, 1]


def test_content_type_must_match_platform() -> None:
    with pytest.raises(ValidationError):
        _minimal_post(platform=Platform.INSTAGRAM, content_type=ContentType.TIKTOK_VIDEO)


def test_parser_version_distinct_from_pipeline_version() -> None:
    post = _minimal_post(parser_version="tiktok-parser-9.9.9", pipeline_version="0.1.0")
    assert post.parser_version == "tiktok-parser-9.9.9"
    assert post.pipeline_version == "0.1.0"
