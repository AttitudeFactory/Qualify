"""The growth history (`growth_provider.reads_from_profile`) over a snapshot-5 read
(m-24854324): the web wizard's default read still records Instagram's per-post AI
label; the 1-credit read (the Alta's, `ai_labels=False`) leaves it unknown (`None`),
never "not AI" (`False`). Offline, synthetic payloads in the vendor's raw shape."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from qualify_api.referentes import scrapecreators_client as sc

from . import growth_provider

_DAY = 24 * 3600
_NOW = 1_800_000_000


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_123")
    monkeypatch.setattr(sc.time, "time", lambda: float(_NOW))


def _node(code: str, age_days: float) -> dict[str, Any]:
    return {
        "__typename": "XDTGraphImage",
        "shortcode": code,
        "taken_at_timestamp": int(_NOW - age_days * _DAY),
        "edge_media_preview_like": {"count": 7},
        "comment_count": 1,
    }


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/instagram/profile":
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "user": {
                        "username": "demo.cafe",
                        "edge_followed_by": {"count": 50},
                        "edge_owner_to_timeline_media": {
                            "count": 2,
                            "page_info": {"has_next_page": False},
                            "edges": [
                                {"node": _node("LABELLED", 1)},
                                {"node": _node("PLAIN", 2)},
                            ],
                        },
                    }
                },
            },
        )
    return httpx.Response(
        200,
        json={
            "success": True,
            "items": [
                {
                    "code": "LABELLED",
                    "taken_at": _NOW - _DAY,
                    "like_count": 7,
                    "comment_count": 1,
                    "ai_label_info": {"gen_ai_detection_method": "AI_EDITED"},
                },
                {"code": "PLAIN", "taken_at": _NOW - 2 * _DAY, "like_count": 7},
            ],
            "more_available": False,
        },
    )


def _labels(profile: dict[str, Any]) -> dict[str, tuple[bool | None, str]]:
    _, posts = growth_provider.reads_from_profile("instagram", "demo.cafe", profile)
    return {p.post_id: (p.ai_generated, p.ai_label) for p in posts}


def test_the_wizard_read_records_the_ai_label_as_before() -> None:
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    profile = sc.fetch_profile_and_posts("instagram", "demo.cafe", client=client)

    assert _labels(profile) == {
        "LABELLED": (True, sc.AI_LABEL_DETECTED),
        "PLAIN": (None, ""),
    }


def test_the_one_credit_read_records_unknown_never_not_ai() -> None:
    client = httpx.Client(transport=httpx.MockTransport(_handler))
    profile = sc.fetch_profile_and_posts("instagram", "demo.cafe", client=client, ai_labels=False)

    labels = _labels(profile)
    assert labels == {"LABELLED": (None, ""), "PLAIN": (None, "")}
    assert all(generated is not False for generated, _ in labels.values())
