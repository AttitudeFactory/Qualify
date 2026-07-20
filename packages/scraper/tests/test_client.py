from __future__ import annotations

from pathlib import Path

from qualify_scraper.client import FixtureScrapingClient, RawHydration


def test_fixture_client_loads_hydration_without_network(fixtures_dir: Path) -> None:
    url = "https://tiktok.example/video"
    client = FixtureScrapingClient({url: fixtures_dir / "tiktok" / "video.json"})
    raw = client.fetch_hydration(url)
    assert isinstance(raw, RawHydration)
    assert raw.url == url
    assert raw.r2_key == "hydration/video.json"
    assert "__DEFAULT_SCOPE__" in raw.hydration
