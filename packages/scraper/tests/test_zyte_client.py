"""ZyteScrapingClient wiring test with a fake transport — no network. Proves the
real client persists the raw payload BEFORE returning it (canonical-artifact
rule) and hands a parseable RawHydration to the parser."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from qualify_scraper.client import ZyteScrapingClient
from qualify_scraper.extract import extract_tiktok_hydration
from qualify_scraper.parsers.tiktok import parse_tiktok
from qualify_scraper.shared import LocalDiskRawPayloadStore, Platform, raw_payload_key


class FakeTransport:
    """Returns canned HTML instead of calling Zyte. Stand-in for ZyteApiTransport
    so the client can be exercised with zero network."""

    def __init__(self, html: str) -> None:
        self._html = html

    def fetch_html(self, url: str) -> str:
        return self._html


def test_client_persists_raw_payload_then_returns_parseable(
    fixtures_dir: Path, brand_id: UUID, pipeline_version: str, tmp_path: Path
) -> None:
    html = (fixtures_dir / "html" / "tiktok_video.html").read_text()
    store = LocalDiskRawPayloadStore(tmp_path)
    client = ZyteScrapingClient(
        transport=FakeTransport(html),
        store=store,
        extractor=extract_tiktok_hydration,
        platform=Platform.TIKTOK,
    )
    url = "https://www.tiktok.com/@trailrunner/video/7663622615168306462"

    raw = client.fetch_hydration(url)

    expected_key = raw_payload_key(Platform.TIKTOK, url)
    assert raw.r2_key == expected_key
    assert (tmp_path / expected_key).exists()

    post = parse_tiktok(raw, brand_id, pipeline_version)
    assert post.post_id == "7663622615168306462"
    assert post.hydration_json_r2_key == expected_key


def test_rescraping_same_url_is_idempotent_at_storage(fixtures_dir: Path, tmp_path: Path) -> None:
    html = (fixtures_dir / "html" / "tiktok_video.html").read_text()
    store = LocalDiskRawPayloadStore(tmp_path)
    client = ZyteScrapingClient(
        transport=FakeTransport(html),
        store=store,
        extractor=extract_tiktok_hydration,
        platform=Platform.TIKTOK,
    )
    url = "https://www.tiktok.com/@trailrunner/video/7663622615168306462"

    first = client.fetch_hydration(url)
    second = client.fetch_hydration(url)

    assert first.r2_key == second.r2_key
