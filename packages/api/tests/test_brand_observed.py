"""Review evidence is bounded, private and deterministic, with no vendor calls."""

from __future__ import annotations

import json
from typing import Any

import pytest

from qualify_api.creative.brand_observed import observed_from

NOW = 1_793_318_400


def _post(identity: str, days: float, likes: int, comments: int = 0, **kw: Any) -> dict:
    return {
        "postId": identity,
        "kind": "image",
        "takenAt": NOW - days * 86400,
        "likes": likes,
        "comments": comments,
        "views": None,
        "caption": "Postres de la casa",
        "isOwner": True,
        "location": "",
        **kw,
    }


def _profile(**kw: Any) -> dict:
    return {
        "stable_id": "573001234548",
        "isProfessionalAccount": True,
        "fetchedAt": NOW,
        "category": "Ice Cream Shop",
        "bio": "Helados en Cúcuta, Colombia",
        "postsCount": 90,
        "totalLikes": 1500,
        "topHashtags": ["helados"],
        "recentMedia": [_post("one", 1, 15), _post("two", 3, 10, 12)],
        **kw,
    }


def test_owner_ranking_and_frequency_are_based_on_the_bounded_snapshot() -> None:
    result = observed_from(
        _profile(
            recentMedia=[
                _post("collab", 0, 1000, isOwner=False),
                _post("one", 1, 15),
                _post("two", 3, 10, 12),
                _post("old", 90, 2),
                _post("two", 3, 10, 12),
            ]
        ),
        network="instagram",
    )
    assert result["top_media_ids"] == ["two"]
    assert result["top_media_basis"] == "últimas 12"
    assert result["posted_last_30d"] is True
    assert result["posts_per_week"] == 3.5
    assert result["stable_id"] == "573001234548"  # identifiers aren't phones
    assert result["total_likes"] is None
    assert result["category_es"] == "Heladería"
    assert result["place_hint"] == {"city": "Cúcuta", "country_code": "CO", "source": "bio"}


@pytest.mark.parametrize(
    "posts",
    [
        [],
        [_post("old", 31, 10)],
        [_post("future", -1, 10)],
        [_post("collab", 1, 10, isOwner=False)],
    ],
)
def test_no_recent_owned_activity_suppresses_frequency_and_ranking(posts: list) -> None:
    result = observed_from(_profile(recentMedia=posts), network="instagram")
    assert result["posted_last_30d"] is False
    assert result["posts_per_week"] is None
    assert result["top_media_ids"] is None
    assert result["top_media_basis"] is None


def test_privacy_bounds_and_unknown_category() -> None:
    profile = _profile(
        bio="",
        category="An unknown category",
        recentMedia=[
            _post(str(i), 1, 4, caption="WhatsApp +57 300 123 4548 " + "x" * 500) for i in range(15)
        ],
        bioLinks=[
            {
                "title": "WhatsApp +57 300 123 4548",
                "url": "https://wa.me/573001234548",
                "kind": "whatsapp",
            }
        ],
    )
    result = observed_from(profile, network="instagram")
    assert len(result["recent_media"]) == 12
    assert len(result["recent_media"][0]["caption"]) == 280
    assert "300 123 4548" not in json.dumps(result)
    assert "573001234548" not in result["links"][0]["url"]
    assert "••" in result["links"][0]["url"]
    assert "thumbnailUrl" not in json.dumps(result)
    assert result["category_es"] is None
    assert result["place_hint"] is None
    assert profile["bioLinks"][0]["url"] == "https://wa.me/573001234548"  # no mutation


@pytest.mark.parametrize("professional", [False, None])
def test_personal_or_unknown_account_carries_no_whatsapp_links(professional: Any) -> None:
    result = observed_from(
        _profile(
            isProfessionalAccount=professional,
            bioLinks=[
                {"url": "https://wa.me/573001234548", "kind": "whatsapp"},
                {"url": "https://example.com", "title": "Pedidos", "kind": "web"},
            ],
        ),
        network="instagram",
    )
    assert [link["kind"] for link in result["links"]] == ["web"]


def test_place_source_is_a_post_location_only_when_bio_has_no_place() -> None:
    result = observed_from(
        _profile(
            bio="Helados hechos aquí",
            recentMedia=[
                _post("one", 1, 5, location="Cúcuta, Colombia"),
            ],
        ),
        network="instagram",
    )
    assert result["place_hint"] == {"city": "Cúcuta", "country_code": "CO", "source": "tag"}


def test_missing_snapshot_fields_remain_unknown() -> None:
    result = observed_from({}, network="instagram")
    assert result["stable_id"] == ""
    assert result["posts_count"] is None
    assert result["posted_last_30d"] is False
    assert result["recent_media"] == []


@pytest.mark.parametrize("kind", ["photo", "video", "carousel"])
def test_media_kind_preserves_the_normalized_snapshot(kind: str) -> None:
    result = observed_from(
        _profile(recentMedia=[_post("one", 1, 2, kind=kind)]), network="instagram"
    )
    assert result["recent_media"][0]["kind"] == kind


def test_frequency_uses_the_observed_intervals_rather_than_assuming_a_full_month() -> None:
    weekly = observed_from(
        _profile(recentMedia=[_post(str(i), i / 2, 2) for i in range(12)]), network="instagram"
    )
    monthly = observed_from(
        _profile(recentMedia=[_post(str(i), i * 2.5, 2) for i in range(12)]), network="instagram"
    )
    assert weekly["posts_per_week"] == 14
    assert monthly["posts_per_week"] == 2.8


@pytest.mark.parametrize("posts", [[_post("only", 1, 2)], [_post("one", 1, 2), _post("two", 1, 3)]])
def test_insufficient_dates_leave_frequency_unknown(posts: list) -> None:
    result = observed_from(_profile(recentMedia=posts), network="instagram")
    assert result["posted_last_30d"] is True
    assert result["posts_per_week"] is None


@pytest.mark.parametrize("missing", [{"likes": None}, {"comments": None}])
def test_hidden_interactions_make_the_winner_unknown(missing: dict) -> None:
    result = observed_from(
        _profile(recentMedia=[_post("visible", 1, 100), _post("hidden", 2, 2) | missing]),
        network="instagram",
    )
    assert result["top_media_ids"] is None
    assert result["top_media_basis"] is None
