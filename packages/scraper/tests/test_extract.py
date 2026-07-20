"""Hydration-extraction tests: raw HTML -> hydration dict -> typed Post, proving
the full in-house parse path (ADR 17) minus the network. HTML fixtures are
synthetic but embed the payloads in the real script shapes
(`__UNIVERSAL_DATA_FOR_REHYDRATION__` / `window._sharedData`)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

from qualify_scraper.extract import (
    HydrationExtractionError,
    extract_instagram_hydration,
    extract_tiktok_hydration,
)
from qualify_scraper.parsers.tiktok import parse_tiktok
from qualify_scraper.shared import Platform, build_envelope, raw_payload_key


def _tiktok_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "html" / "tiktok_video.html").read_text()


def _instagram_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "html" / "instagram_reel.html").read_text()


def test_extract_tiktok_hydration(fixtures_dir: Path) -> None:
    payload = extract_tiktok_hydration(_tiktok_html(fixtures_dir))
    assert "__DEFAULT_SCOPE__" in payload


def test_extract_instagram_hydration(fixtures_dir: Path) -> None:
    payload = extract_instagram_hydration(_instagram_html(fixtures_dir))
    assert payload["graphql"]["shortcode_media"]["shortcode"] == "CxReel001abc"


def test_extract_then_parse_tiktok(
    fixtures_dir: Path, brand_id: UUID, pipeline_version: str
) -> None:
    payload = extract_tiktok_hydration(_tiktok_html(fixtures_dir))
    url = "https://tiktok.example/video"
    envelope = build_envelope(
        platform=Platform.TIKTOK,
        source_url=url,
        hydration=payload,
        fetched_at=datetime.fromtimestamp(0),
    )
    r2_key = raw_payload_key(Platform.TIKTOK, url)
    post = parse_tiktok(
        envelope, r2_key=r2_key, brand_id=brand_id, pipeline_version=pipeline_version
    )
    assert post.post_id == "7663622615168306462"


def test_missing_tiktok_script_raises() -> None:
    with pytest.raises(HydrationExtractionError):
        extract_tiktok_hydration("<html><body>login wall</body></html>")


def test_missing_instagram_shared_data_raises() -> None:
    with pytest.raises(HydrationExtractionError):
        extract_instagram_hydration("<html><body>login wall</body></html>")
