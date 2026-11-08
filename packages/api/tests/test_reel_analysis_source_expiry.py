"""The expiry a CDN signs into its own link (m-24975868): TikTok's sits in the PATH as
8 hex chars of unix seconds; only a value close to now counts, so another hex segment
(an object id, a hash) is never mistaken for it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from qualify_api.referentes.reel_analysis_source import url_expires_at, url_is_stale

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
CDN = "https://v16m.tiktokcdn.com"


def _hex(moment: datetime) -> str:
    return format(int(moment.timestamp()), "08x")


def test_tiktok_path_expiry_is_parsed() -> None:
    expires = NOW + timedelta(hours=23)
    url = f"{CDN}/0123456789abcdef0123456789abcdef/{_hex(expires)}/video/tos/x.mp4"
    assert url_expires_at(url, NOW) == expires


def test_the_observed_sample_segment_decodes_to_a_unix_time() -> None:
    # `/6af12bc8/` from the 2026-11-08 diagnosis, read against a `now` before it
    expires = datetime.fromtimestamp(0x6AF12BC8, UTC)
    url = "https://v16m.tiktokcdn-us.com/abc/6af12bc8/video/tos/clip.mp4"
    assert url_expires_at(url, expires - timedelta(hours=20)) == expires


@pytest.mark.parametrize(
    "segment",
    [
        "deadbeef",  # 8 hex chars, but 2088: not a plausible expiry
        "00c0ffee",  # 8 hex chars, 1970
        "6af12bc",  # 7 chars
        "6af12bc8a",  # 9 chars
        "6af12bcz",  # not hex
    ],
)
def test_other_hex_segments_are_ignored(segment: str) -> None:
    assert url_expires_at(f"{CDN}/{segment}/video/tos/x.mp4", NOW) is None


def test_a_far_segment_is_skipped_for_the_plausible_one() -> None:
    expires = NOW + timedelta(hours=10)
    assert url_expires_at(f"{CDN}/deadbeef/{_hex(expires)}/x.mp4", NOW) == expires


def test_path_hex_is_only_read_on_tiktok_hosts() -> None:
    url = f"https://scontent.cdninstagram.com/{_hex(NOW + timedelta(hours=3))}/x.mp4"
    assert url_expires_at(url, NOW) is None


def test_query_params_still_win() -> None:
    soon = NOW + timedelta(hours=2)
    path = _hex(NOW + timedelta(hours=20))
    url = f"{CDN}/{path}/x.mp4?x-expires={int(soon.timestamp())}"
    assert url_expires_at(url, NOW) == soon
    ig = f"https://cdn.fbcdn.net/x.mp4?oe={int(soon.timestamp()):X}"
    assert url_expires_at(ig, NOW) == soon


def test_an_expired_path_makes_the_link_stale() -> None:
    gone = f"{CDN}/{_hex(NOW - timedelta(minutes=5))}/x.mp4"
    assert url_is_stale(gone, NOW - timedelta(hours=1), NOW)
    fresh = f"{CDN}/{_hex(NOW + timedelta(hours=20))}/x.mp4"
    assert not url_is_stale(fresh, NOW - timedelta(hours=1), NOW)
