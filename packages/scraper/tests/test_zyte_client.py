"""ZyteScrapingClient wiring test with a fake transport — no network. Proves the
capture -> persist -> parse seam (ADR 18): the client mints a signed envelope, the
raw is persisted by `persist_envelope` BEFORE parsing, and the persisted key is the
only thing that satisfies `Post.hydration_json_r2_key` (raw-before-parse rule,
enforced structurally by type dependency)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from qualify_scraper.client import ZyteScrapingClient
from qualify_scraper.extract import extract_tiktok_hydration
from qualify_scraper.parsers.tiktok import parse_tiktok
from qualify_scraper.shared import (
    LocalDiskRawPayloadStore,
    Platform,
    persist_envelope,
    raw_payload_key,
)


class FakeTransport:
    """Returns canned HTML instead of calling Zyte. Stand-in for ZyteApiTransport
    so the client can be exercised with zero network."""

    def __init__(self, html: str) -> None:
        self._html = html

    def fetch_html(self, url: str) -> str:
        return self._html


def _client(html: str) -> ZyteScrapingClient:
    return ZyteScrapingClient(
        transport=FakeTransport(html),
        extractor=extract_tiktok_hydration,
        platform=Platform.TIKTOK,
    )


def test_capture_persist_parse_seam(
    fixtures_dir: Path, brand_id: UUID, pipeline_version: str, tmp_path: Path
) -> None:
    html = (fixtures_dir / "html" / "tiktok_video.html").read_text()
    store = LocalDiskRawPayloadStore(tmp_path)
    client = _client(html)
    url = "https://www.tiktok.com/@trailrunner/video/7663622615168306462"

    # Capture is pure: the client does NOT persist.
    envelope = client.fetch_hydration(url)
    expected_key = raw_payload_key(envelope)
    assert expected_key.startswith("scrape/tiktok/")
    assert not (tmp_path / expected_key).exists()

    # Commit the raw BEFORE parsing; only persist yields the key a Post requires.
    r2_key = persist_envelope(store, envelope)
    assert r2_key == expected_key
    assert (tmp_path / expected_key).exists()

    post = parse_tiktok(
        envelope, r2_key=r2_key, brand_id=brand_id, pipeline_version=pipeline_version
    )
    assert post.post_id == "7663622615168306462"
    # Structural proof of raw-before-parse: the parsed row points at the persisted key.
    assert post.hydration_json_r2_key == expected_key
    # And it carries the exact content version it was derived from.
    assert post.content_signature == envelope.content_signature


def test_rescraping_same_url_is_idempotent_at_storage(fixtures_dir: Path, tmp_path: Path) -> None:
    html = (fixtures_dir / "html" / "tiktok_video.html").read_text()
    store = LocalDiskRawPayloadStore(tmp_path)
    client = _client(html)
    url = "https://www.tiktok.com/@trailrunner/video/7663622615168306462"

    first = persist_envelope(store, client.fetch_hydration(url))
    second = persist_envelope(store, client.fetch_hydration(url))

    assert first == second
