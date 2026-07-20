"""Instagram parser tests. Fixtures are synthetic but structurally faithful to
IG's `graphql.shortcode_media` payload — see tests/fixtures/README.md. The story
fixture relies on a synthetic `product_type == "story"` discriminator that must
be validated against a real payload before production use."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from qualify_scraper.client import FixtureScrapingClient
from qualify_scraper.parsers.instagram import parse_instagram
from qualify_scraper.schemas import ContentType, MediaKind, Platform, Post


def _parse(fixtures_dir: Path, brand_id: UUID, pipeline_version: str, name: str) -> Post:
    url = f"https://instagram.example/{name}"
    client = FixtureScrapingClient({url: fixtures_dir / "instagram" / f"{name}.json"})
    return parse_instagram(client.fetch_hydration(url), brand_id, pipeline_version)


def test_reel(fixtures_dir: Path, brand_id: UUID, pipeline_version: str) -> None:
    post = _parse(fixtures_dir, brand_id, pipeline_version, "reel")
    assert post.platform == Platform.INSTAGRAM
    assert post.content_type == ContentType.INSTAGRAM_REEL
    assert post.post_id == "CxReel001abc"
    assert post.creator_handle == "trailrunner"
    assert post.metrics.views == 98700
    assert len(post.media) == 1
    assert post.media[0].kind == MediaKind.VIDEO
    assert post.duration_ms == 18400


def test_post(fixtures_dir: Path, brand_id: UUID, pipeline_version: str) -> None:
    post = _parse(fixtures_dir, brand_id, pipeline_version, "post")
    assert post.content_type == ContentType.INSTAGRAM_POST
    assert len(post.media) == 1
    assert post.media[0].kind == MediaKind.IMAGE
    assert post.duration_ms is None
    assert post.metrics.likes == 4100


def test_carousel(fixtures_dir: Path, brand_id: UUID, pipeline_version: str) -> None:
    post = _parse(fixtures_dir, brand_id, pipeline_version, "carousel")
    assert post.content_type == ContentType.INSTAGRAM_CAROUSEL
    assert [m.ordinal for m in post.media] == [0, 1, 2]
    assert [m.kind for m in post.media] == [
        MediaKind.IMAGE,
        MediaKind.VIDEO,
        MediaKind.IMAGE,
    ]
    assert post.media[1].duration_ms == 6200


def test_story(fixtures_dir: Path, brand_id: UUID, pipeline_version: str) -> None:
    post = _parse(fixtures_dir, brand_id, pipeline_version, "story")
    assert post.content_type == ContentType.INSTAGRAM_STORY
    assert len(post.media) == 1
    assert post.media[0].kind == MediaKind.VIDEO
    assert post.caption == ""


def test_provenance_and_natural_key(
    fixtures_dir: Path, brand_id: UUID, pipeline_version: str
) -> None:
    post = _parse(fixtures_dir, brand_id, pipeline_version, "reel")
    assert post.natural_key == (str(brand_id), Platform.INSTAGRAM, "CxReel001abc")
    assert post.hydration_json_r2_key == "hydration/reel.json"
    assert post.pipeline_version == pipeline_version
    assert post.parser_version == "instagram-parser-0.1.0"
