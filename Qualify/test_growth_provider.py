"""The creator history's Reflex side (2026-10-01): what a profile read and a search
phase become as rows, and that a session-less or failing write never reaches the UI."""

from __future__ import annotations

from uuid import UUID

from qualify_api.growth import MemoryGrowthRepository

from . import growth_provider
from .creator_discovery import Candidate

TENANT = UUID("a0000000-0000-4000-8000-0000000000c1")


def test_a_phase_s_accounts_become_discovery_rows_only_when_their_size_was_read() -> None:
    repo = MemoryGrowthRepository()
    accounts = [
        Candidate("tiktok", "midudev", followers=405_000, total_likes=9_000_000),
        Candidate("instagram", "midu.dev", followers=611_000),
        Candidate("tiktok", "unread"),  # never read: no size, no row
        Candidate("tiktok", " "),
    ]
    assert growth_provider.record_discovered(TENANT, accounts, repository=repo, now=1.0) == 2
    assert [p.followers for p in repo.follower_series(TENANT, "tiktok", "midudev")] == [405_000]
    assert repo.reads[TENANT][0].source == "discovery"
    assert repo.reads[TENANT][0].total_likes == 9_000_000
    assert [p.followers for p in repo.follower_series(TENANT, "instagram", "midu.dev")] == [611_000]
    assert growth_provider.record_discovered(TENANT, [], repository=repo) == 0


def test_a_profile_without_a_fetched_at_is_recorded_now() -> None:
    repo = MemoryGrowthRepository()
    written = growth_provider.record_profile_read(
        TENANT, "instagram", "@Brand", {"followers": 10, "recentPosts": None}, repository=repo
    )
    assert written == 0
    series = repo.follower_series(TENANT, "instagram", "brand")
    assert len(series) == 1 and series[0].followers == 10
