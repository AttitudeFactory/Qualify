from __future__ import annotations

from pathlib import Path

from qualify_scraper.client import FixtureScrapingClient
from qualify_scraper.shared import Platform, RawPayloadEnvelope, content_signature


def test_fixture_client_returns_signed_envelope_without_network(fixtures_dir: Path) -> None:
    url = "https://tiktok.example/video"
    client = FixtureScrapingClient(
        {url: fixtures_dir / "tiktok" / "video.json"}, platform=Platform.TIKTOK
    )
    envelope = client.fetch_hydration(url)
    assert isinstance(envelope, RawPayloadEnvelope)
    assert envelope.platform == Platform.TIKTOK
    assert envelope.source_url == url
    assert envelope.payload_schema_version == 2
    assert "__DEFAULT_SCOPE__" in envelope.hydration
    # The envelope is self-describing: its signature matches its own hydration.
    assert envelope.content_signature == content_signature(envelope.hydration)
    assert envelope.content_signature.startswith("sha256:")
