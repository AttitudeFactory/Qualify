"""TikTok parser tests. Fixtures are synthetic but structurally faithful to
TikTok's `__UNIVERSAL_DATA_FOR_REHYDRATION__` payload — see tests/fixtures/README.md.
Story and text fixtures rely on a synthetic `contentTypeHint` discriminator that
must be validated against a real payload before production use."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from qualify_scraper.client import FixtureScrapingClient
from qualify_scraper.parsers.tiktok import parse_tiktok
from qualify_scraper.schemas import ContentType, MediaKind, Platform, Post
from qualify_scraper.shared import raw_payload_key


def _parse(fixtures_dir: Path, brand_id: UUID, pipeline_version: str, name: str) -> Post:
    url = f"https://tiktok.example/{name}"
    client = FixtureScrapingClient(
        {url: fixtures_dir / "tiktok" / f"{name}.json"}, platform=Platform.TIKTOK
    )
    # Parser-focused: derive the r2_key with the same fn the store uses (store-free).
    r2_key = raw_payload_key(Platform.TIKTOK, url)
    return parse_tiktok(
        client.fetch_hydration(url),
        r2_key=r2_key,
        brand_id=brand_id,
        pipeline_version=pipeline_version,
    )


def test_video(fixtures_dir: Path, brand_id: UUID, pipeline_version: str) -> None:
    post = _parse(fixtures_dir, brand_id, pipeline_version, "video")
    assert post.platform == Platform.TIKTOK
    assert post.content_type == ContentType.TIKTOK_VIDEO
    assert post.post_id == "7663622615168306462"
    assert post.creator_handle == "trailrunner"
    assert post.metrics.views == 152300
    assert len(post.media) == 1
    assert post.media[0].kind == MediaKind.VIDEO
    assert post.duration_ms == 27000
    assert post.hydration_json_r2_key == raw_payload_key(
        Platform.TIKTOK, "https://tiktok.example/video"
    )


def test_photo_gallery(fixtures_dir: Path, brand_id: UUID, pipeline_version: str) -> None:
    post = _parse(fixtures_dir, brand_id, pipeline_version, "photo_gallery")
    assert post.content_type == ContentType.TIKTOK_PHOTO
    assert [m.ordinal for m in post.media] == [0, 1, 2]
    assert all(m.kind == MediaKind.IMAGE for m in post.media)
    assert post.duration_ms is None


def test_story(fixtures_dir: Path, brand_id: UUID, pipeline_version: str) -> None:
    post = _parse(fixtures_dir, brand_id, pipeline_version, "story")
    assert post.content_type == ContentType.TIKTOK_STORY
    assert len(post.media) == 1
    assert post.media[0].kind == MediaKind.VIDEO
    assert post.duration_ms == 9000


def test_text(fixtures_dir: Path, brand_id: UUID, pipeline_version: str) -> None:
    post = _parse(fixtures_dir, brand_id, pipeline_version, "text")
    assert post.content_type == ContentType.TIKTOK_TEXT
    assert post.media == []
    assert post.caption.startswith("Hot take")
    assert post.metrics.likes == 210


def test_provenance_and_natural_key(
    fixtures_dir: Path, brand_id: UUID, pipeline_version: str
) -> None:
    post = _parse(fixtures_dir, brand_id, pipeline_version, "video")
    assert post.natural_key == (str(brand_id), Platform.TIKTOK, "7663622615168306462")
    assert post.source_url == "https://tiktok.example/video"
    assert post.pipeline_version == pipeline_version
    assert post.parser_version == "tiktok-parser-0.1.0"
