"""The gate's paged reel read and raw profile read for the Creators module
(m-24946121, design §8.1), and reel parser 2 — offline, `httpx.MockTransport`."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import httpx
import pytest

from qualify_api.vendors import scrapecreators as sc


def _load_fake():  # `--import-mode=importlib` puts no test directory on `sys.path`
    if "creators_fake" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "creators_fake", Path(__file__).with_name("creators_fake.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["creators_fake"] = module
        spec.loader.exec_module(module)
    return sys.modules["creators_fake"]


_fake = _load_fake()
HANDLE, FakeVendor, reel_item, reels_page = (
    _fake.HANDLE,
    _fake.FakeVendor,
    _fake.reel_item,
    _fake.reels_page,
)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_123")


def test_parser_2_reads_partnership_coauthors_sound_and_hidden_counts() -> None:
    own = sc._instagram_reel(
        reel_item("A1", days_ago=5, paid=True, coauthors=[HANDLE, "Other.One"]), HANDLE
    )
    assert own is not None
    assert own["paidPartnership"] is True
    # every account on the reel, the read one included: the row is shared (review 2026-11-04)
    assert own["coauthors"] == [HANDLE, "other.one"]
    assert own["soundId"] == "original:a-A1"
    assert own["soundIsOriginal"] is True
    assert own["countsHidden"] is False

    # a reel another account published WITH this one: its owner is the collaborator
    theirs = sc._instagram_reel(
        reel_item("A2", days_ago=5, owner="partner", coauthors=[HANDLE]), HANDLE
    )
    assert theirs is not None and theirs["coauthors"] == [HANDLE, "partner"]
    assert theirs["soundIsOriginal"] is True  # partner's own audio on partner's reel

    reused = sc._instagram_reel(reel_item("A3", days_ago=5, audio_artist="someone"), HANDLE)
    assert reused is not None and reused["soundIsOriginal"] is False

    licensed = sc._instagram_reel(reel_item("A4", days_ago=5, licensed="777"), HANDLE)
    assert licensed is not None
    assert (licensed["soundId"], licensed["soundIsOriginal"]) == ("music:777", False)

    hidden = sc._instagram_reel(reel_item("A5", days_ago=5, hidden=True), HANDLE)
    assert hidden is not None
    assert hidden["countsHidden"] is True and hidden["views"] is None and hidden["likes"] is None
    assert sc.REEL_PARSER_VERSION == 2


def test_a_shared_reel_reads_the_same_through_either_account() -> None:
    item = reel_item("C1", days_ago=5, owner="aaa", coauthors=["bbb"])
    via_a = sc._instagram_reel(item, "aaa")
    via_b = sc._instagram_reel(item, "bbb")
    assert via_a is not None and via_b is not None
    assert via_a["coauthors"] == via_b["coauthors"] == ["aaa", "bbb"]


def test_fetch_reel_pages_hands_each_page_over_before_asking_the_next() -> None:
    vendor = FakeVendor()
    seen: list[tuple[int, int]] = []

    def on_page(page: sc.ReelPage) -> None:
        seen.append((len(vendor.calls), len(page.reels)))

    pages = sc.fetch_reel_pages(
        "instagram",
        f"@{HANDLE.upper()}",
        max_reels=48,
        feature=sc.FEATURE_CREATOR_REELS,
        client=vendor.client(),
        on_page=on_page,
    )
    assert [len(p.reels) for p in pages] == [12, 12, 12, 12]
    # page n was handed over when exactly n calls had been made
    assert seen == [(1, 12), (2, 12), (3, 12), (4, 12)]
    assert pages[0].params == {"handle": HANDLE}
    assert pages[1].params == {"handle": HANDLE, "max_id": "p1"}
    assert pages[0].payload["paging_info"]["max_id"] == "p1"
    assert pages[-1].next_cursor is None


def test_fetch_reel_pages_stops_at_max_reels_and_never_repeats_a_reel() -> None:
    dup = reel_item("R000", days_ago=1)
    vendor = FakeVendor(
        pages=[
            [reel_item(f"R{i:03d}", days_ago=1 + i) for i in range(12)],
            [dup] + [reel_item(f"S{i:03d}", days_ago=30 + i) for i in range(11)],
            [reel_item(f"T{i:03d}", days_ago=60 + i) for i in range(12)],
        ]
    )
    pages = sc.fetch_reel_pages(
        "instagram", HANDLE, max_reels=20, feature=sc.FEATURE_CREATOR_REELS, client=vendor.client()
    )
    ids = [r["id"] for p in pages for r in p.reels]
    assert len(ids) == 20 and len(set(ids)) == 20
    assert vendor.paid_calls == 2  # the walk stopped as soon as 20 were in


def test_fetch_reel_pages_failure_on_page_3_keeps_pages_1_and_2_handed_over() -> None:
    vendor = FakeVendor(fail_page=3)
    handed: list[sc.ReelPage] = []
    with pytest.raises(sc.ScrapeCreatorsError):
        sc.fetch_reel_pages(
            "instagram",
            HANDLE,
            max_reels=48,
            feature=sc.FEATURE_CREATOR_REELS,
            client=vendor.client(),
            on_page=handed.append,
        )
    assert len(handed) == 2


def test_fetch_reel_pages_stops_on_a_repeated_cursor() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=reels_page([reel_item("X1", days_ago=1)], "same"))

    pages = sc.fetch_reel_pages(
        "instagram",
        HANDLE,
        max_reels=48,
        feature=sc.FEATURE_CREATOR_REELS,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert len(pages) == 2  # page 2 brought the same cursor back


def test_fetch_profile_raw_returns_the_raw_answer_and_the_normalized_profile() -> None:
    vendor = FakeVendor()
    raw, profile = sc.fetch_profile_raw(
        "instagram", HANDLE, feature=sc.FEATURE_CREATOR_PROFILE, client=vendor.client()
    )
    assert raw["data"]["user"]["username"] == HANDLE
    assert profile["followers"] == 20000 and profile["isPrivate"] is False
    assert sc.PROFILE_PATHS["instagram"] == "/v1/instagram/profile"


def test_creator_features_are_known_to_the_gate() -> None:
    assert {sc.FEATURE_CREATOR_PROFILE, sc.FEATURE_CREATOR_REELS} <= sc.FEATURES
