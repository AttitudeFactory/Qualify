"""Seedance 2.5 priced with video input (pricing v7, m-24820142): the with-video rate,
the final priced by its draft, and the estimate counting the input video — measured on
live drafts 2026-10-23 (docs/modelos-generativos/seedance-2-5.md)."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

httpx = pytest.importorskip("httpx")

from qualify_creative.adapters import SeedanceVideoAdapter  # noqa: E402
from qualify_creative.adapters.byteplus_ark import (  # noqa: E402
    MAX_REFERENCE_VIDEO_SECONDS,
    estimate_video_tokens,
    video_cost_usd,
)
from qualify_creative.enums import GenerationTask  # noqa: E402
from qualify_creative.pricing import JsonPricingTable  # noqa: E402
from qualify_creative.providers import GenerationRequest, RenderedPrompt  # noqa: E402

MODEL = "dreamina-seedance-2-5-260628"
V7 = JsonPricingTable("v7")
CLIP = "https://media.example/clip.mp4"


def request(**params: object) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.SCENE_VIDEO, rendered_prompt=RenderedPrompt("", "", ""), params=params
    )


def test_v7_keeps_v6_and_adds_only_the_with_video_rates() -> None:
    for older in ("v5", "v6"):
        table = JsonPricingTable(older)
        assert table.unit_price(model_id=MODEL, unit="per_mtok_video_480p") == Decimal("10.70")
        with pytest.raises(KeyError):
            table.unit_price(model_id=MODEL, unit="per_mtok_video_480p_with_video")
    assert V7.unit_price(model_id=MODEL, unit="per_mtok_video_480p_with_video") == Decimal("6.40")
    assert V7.unit_price(model_id=MODEL, unit="per_mtok_video_720p_with_video") == Decimal("6.40")
    assert V7.unit_price(model_id=MODEL, unit="per_mtok_video_1080p_with_video") == Decimal("7.00")


def test_v7_is_v6_plus_only_the_three_with_video_units() -> None:
    data = Path(__file__).resolve().parents[1] / "src" / "qualify_creative" / "pricing_data"
    v6 = json.loads((data / "v6.json").read_text(encoding="utf-8"))
    v7 = json.loads((data / "v7.json").read_text(encoding="utf-8"))
    assert v7["version"] == "v7"
    added = {f"per_mtok_video_{res}_with_video" for res in ("480p", "720p", "1080p")}
    assert v7["entries"].keys() == v6["entries"].keys()
    for model_id, units in v7["entries"].items():
        extra = units.keys() - v6["entries"][model_id].keys()
        assert extra == (added if model_id == MODEL else set()), model_id
        for unit, price in v6["entries"][model_id].items():
            assert units[unit] == price, (model_id, unit)


@pytest.mark.parametrize(
    ("resolution", "video_input", "expected"),
    [
        # the live draft cgt-20261024063856-4djtl: 115,690 tokens at 480p
        ("480p", False, "1.237883"),
        ("480p", True, "0.740416"),
        ("1080p", False, "1.353573"),
        ("1080p", True, "0.809830"),
    ],
)
def test_cost_with_and_without_video_input(
    resolution: str, video_input: bool, expected: str
) -> None:
    cost = video_cost_usd(V7, MODEL, resolution, 115_690, video_input=video_input)
    assert cost == Decimal(expected)


def test_a_family_without_a_with_video_rate_is_priced_at_its_higher_rate() -> None:
    # 2.0 carries no with-video rate yet: never zero, never a crash — the higher one
    model = "dreamina-seedance-2-0-260128"
    assert video_cost_usd(V7, model, "720p", 1_000_000, video_input=True) == Decimal("7.000000")


def test_the_estimate_counts_the_input_video_like_the_live_drafts() -> None:
    out_only = estimate_video_tokens(MODEL, "480p", "9:16", 5)
    with_input = estimate_video_tokens(MODEL, "480p", "9:16", 5, 7.33)
    two_videos = estimate_video_tokens(MODEL, "480p", "9:16", 5, 22)
    assert 47_000 < out_only < 50_000  # the no-video draft billed 49,673
    assert 113_000 < with_input < 124_000  # billed 115,690 and 118,851
    assert 255_000 < two_videos < 265_000  # billed 259,802


def test_a_task_with_a_reference_video_estimates_its_seconds_at_the_with_video_rate() -> None:
    adapter = SeedanceVideoAdapter(model=MODEL)
    params = {
        "prompt": "x",
        "draft": True,
        "ratio": "9:16",
        "duration_seconds": 5,
        "reference_images": ["data:image/jpeg;base64,AAAA"],
        "reference_videos": [CLIP],
        "reference_video_seconds": 7.33,
    }
    tokens = estimate_video_tokens(MODEL, "480p", "9:16", 5, 7.33)
    expected = video_cost_usd(V7, MODEL, "480p", tokens, video_input=True)
    assert adapter.estimate_cost_usd(request(**params), V7) == expected
    without = {k: v for k, v in params.items() if k not in ("reference_videos",)}
    assert adapter.estimate_cost_usd(request(**without), V7) == video_cost_usd(
        V7, MODEL, "480p", estimate_video_tokens(MODEL, "480p", "9:16", 5)
    )


def test_an_unmeasured_reference_video_is_priced_at_the_cap() -> None:
    adapter = SeedanceVideoAdapter(model=MODEL)
    params = {"prompt": "x", "ratio": "9:16", "duration_seconds": 5, "reference_videos": [CLIP]}
    tokens = estimate_video_tokens(MODEL, "720p", "9:16", 5, MAX_REFERENCE_VIDEO_SECONDS)
    assert adapter.estimate_cost_usd(request(**params), V7) == video_cost_usd(
        V7, MODEL, "720p", tokens, video_input=True
    )


def test_reference_video_seconds_must_be_a_number() -> None:
    adapter = SeedanceVideoAdapter(model=MODEL)
    with pytest.raises(ValueError, match="reference_video_seconds"):
        adapter.spec({"prompt": "x", "reference_videos": [CLIP], "reference_video_seconds": "7"})
    with pytest.raises(ValueError, match="video_input"):
        adapter.spec({"draft_task_id": "cgt-1", "video_input": "yes"})


def test_the_final_is_estimated_by_its_drafts_video_input() -> None:
    adapter = SeedanceVideoAdapter(model=MODEL)
    final = {"draft_task_id": "cgt-1", "ratio": "9:16", "duration_seconds": 5}
    plain = adapter.estimate_cost_usd(request(**final), V7)
    assert plain == video_cost_usd(
        V7, MODEL, "1080p", estimate_video_tokens(MODEL, "1080p", "9:16", 5)
    )
    with_video = {**final, "video_input": True, "reference_video_seconds": 7.33}
    tokens = estimate_video_tokens(MODEL, "1080p", "9:16", 5, 7.33)
    assert adapter.estimate_cost_usd(request(**with_video), V7) == video_cost_usd(
        V7, MODEL, "1080p", tokens, video_input=True
    )


class _Recorder:
    def __init__(self, done: dict[str, Any]) -> None:
        self.done = done
        self.posts: list[dict[str, Any]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            self.posts.append(json.loads(req.content))
            return httpx.Response(200, json={"id": self.done["id"]})
        return httpx.Response(200, json=self.done)


def _done(**extra: Any) -> dict[str, Any]:
    return {
        "id": "cgt-x",
        "status": "succeeded",
        "model": MODEL,
        "content": {"video_url": "https://ark/x.mp4"},
        "usage": {"completion_tokens": 115_690},
        "duration": 5,
        "ratio": "9:16",
        "resolution": "480p",
        **extra,
    }


def test_the_payload_says_video_input_and_neither_field_is_sent() -> None:
    rec = _Recorder(_done(draft=True))
    adapter = SeedanceVideoAdapter(
        model=MODEL, transport=httpx.MockTransport(rec), sleep=lambda _: None
    )
    result = adapter.generate(
        request(
            prompt="x",
            draft=True,
            reference_images=["data:image/jpeg;base64,AAAA"],
            reference_videos=[CLIP],
            reference_video_seconds=7.33,
        ),
        api_key="k",
    )
    assert result.payload["video_input"] is True
    assert result.payload["reference_video_seconds"] == 7.33
    assert "reference_video_seconds" not in rec.posts[0]

    rec = _Recorder(_done(id="cgt-f", resolution="1080p", draft_task_id="cgt-x"))
    adapter = SeedanceVideoAdapter(
        model=MODEL, transport=httpx.MockTransport(rec), sleep=lambda _: None
    )
    result = adapter.generate(request(draft_task_id="cgt-x", video_input=True), api_key="k")
    assert result.payload["video_input"] is True  # the draft's, for the final's rate
    assert "video_input" not in rec.posts[0]
