"""Seedance 2.5 draft mode (m-24820142): a 480p draft, then its final from the draft's
task id alone — wire shapes from create-video-generation-task-api (read 2026-10-22)."""

import json
from typing import Any

import pytest

httpx = pytest.importorskip("httpx")

from qualify_creative.adapters import SeedanceVideoAdapter  # noqa: E402
from qualify_creative.adapters.byteplus_ark import (  # noqa: E402
    DRAFT_RESOLUTION,
    estimate_video_tokens,
    output_dimensions,
    seedance_family,
)
from qualify_creative.enums import GenerationTask  # noqa: E402
from qualify_creative.providers import GenerationRequest, RenderedPrompt  # noqa: E402

MODEL = "dreamina-seedance-2-5-260628"
FRAME = "data:image/jpeg;base64,AAAA"


class Recorder:
    def __init__(self, done: dict[str, Any]) -> None:
        self.done = done
        self.posts: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.posts.append(json.loads(request.content))
            return httpx.Response(200, json={"id": self.done["id"]})
        return httpx.Response(200, json=self.done)


def adapter(rec: Recorder) -> SeedanceVideoAdapter:
    return SeedanceVideoAdapter(
        model=MODEL, transport=httpx.MockTransport(rec), sleep=lambda _: None
    )


def request(**params: object) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.SCENE_VIDEO, rendered_prompt=RenderedPrompt("", "", ""), params=params
    )


def done(**extra: Any) -> dict[str, Any]:
    return {
        "id": "cgt-draft",
        "status": "succeeded",
        "model": MODEL,
        "content": {"video_url": "https://ark/d.mp4"},
        "usage": {"completion_tokens": 48000, "total_tokens": 48000},
        "duration": 5,
        "ratio": "9:16",
        "resolution": "480p",
        "seed": 33608,
        "created_at": 1776138520,
        "draft": True,
        "draft_task_id": None,
        **extra,
    }


def test_only_2_5_has_draft_mode() -> None:
    assert seedance_family(MODEL).draft
    assert seedance_family(MODEL).draft_final_resolution == "1080p"
    for other in ("dreamina-seedance-2-0-mini-260615", "seedance-1-0-pro-250528"):
        assert not seedance_family(other).draft
        with pytest.raises(ValueError, match="no draft mode"):
            SeedanceVideoAdapter(model=other).spec({"prompt": "x", "draft": True})


def test_a_draft_is_sent_at_480p_with_draft_true_and_its_id_seed_and_date_come_back() -> None:
    rec = Recorder(done())
    result = adapter(rec).generate(
        request(prompt="A product spins.", draft=True, ratio="9:16", duration_seconds=5),
        api_key="k",
    )
    (body,) = rec.posts
    assert body["draft"] is True
    assert body["resolution"] == DRAFT_RESOLUTION
    assert body["ratio"] == "9:16"
    assert result.payload["task_id"] == "cgt-draft"
    assert result.payload["draft"] is True
    assert result.payload["seed"] == 33608
    assert result.payload["created_at"] == 1776138520
    assert result.usage.output_tokens == 48000


def test_a_draft_refuses_any_other_resolution() -> None:
    with pytest.raises(ValueError, match="480p only"):
        SeedanceVideoAdapter(model=MODEL).spec({"prompt": "x", "draft": True, "resolution": "720p"})


def test_a_non_draft_task_sends_no_draft_flag() -> None:
    rec = Recorder(done(draft=False))
    adapter(rec).generate(request(prompt="x", resolution="720p"), api_key="k")
    assert "draft" not in rec.posts[0]


def test_the_final_sends_only_the_draft_id_the_model_and_1080p() -> None:
    rec = Recorder(done(id="cgt-final", resolution="1080p", draft=False, draft_task_id="cgt-draft"))
    result = adapter(rec).generate(
        # ratio and length ride along for the estimate only
        request(draft_task_id="cgt-draft", ratio="9:16", duration_seconds=5),
        api_key="k",
    )
    (body,) = rec.posts
    assert body == {
        "model": MODEL,
        "content": [{"type": "draft_task", "draft_task": {"id": "cgt-draft"}}],
        "resolution": "1080p",
        "watermark": False,
        "return_last_frame": True,
    }
    # nothing the draft owns is sent again (ModelArk errors even on equal values)
    for inherited in ("ratio", "duration", "seed", "generate_audio", "omni_reference_task_type"):
        assert inherited not in body
    assert result.payload["draft"] is False
    assert result.payload["draft_task_id"] == "cgt-draft"
    assert result.payload["resolution"] == "1080p"


def test_the_final_needs_a_draft_capable_model_and_an_id() -> None:
    with pytest.raises(ValueError, match="no draft mode"):
        SeedanceVideoAdapter().spec({"draft_task_id": "cgt-1"})
    with pytest.raises(ValueError, match="draft_task_id"):
        SeedanceVideoAdapter(model=MODEL).spec({"draft_task_id": "  "})


def test_2_5_sends_adaptive_ratio_for_an_opening_frame() -> None:
    body = (
        SeedanceVideoAdapter(model=MODEL)
        .spec({"prompt": "x", "first_frame": FRAME, "ratio": "9:16"})
        .body()
    )
    assert body["ratio"] == "adaptive"
    # without frames the named ratio still goes
    assert (
        SeedanceVideoAdapter(model=MODEL).spec({"prompt": "x", "ratio": "9:16"}).body()["ratio"]
        == "9:16"
    )
    # 2.0 keeps the named ratio for a frame
    mini = SeedanceVideoAdapter(model="dreamina-seedance-2-0-mini-260615")
    assert (
        mini.spec({"prompt": "x", "first_frame": FRAME, "ratio": "9:16"}).body()["ratio"] == "9:16"
    )


def test_2_5_draft_size_is_its_own_480p() -> None:
    assert output_dimensions(MODEL, "480p", "9:16") == (480, 854)
    assert output_dimensions(MODEL, "1080p", "9:16") == (1080, 1920)
    # the final costs far more tokens than the draft
    assert estimate_video_tokens(MODEL, "1080p", "9:16", 5) > 4 * estimate_video_tokens(
        MODEL, "480p", "9:16", 5
    )


def test_the_final_parses_ratio_and_length_like_the_draft() -> None:
    """Review fix: one parser for both specs, so the final prices what the draft made."""
    adapter = SeedanceVideoAdapter(model=MODEL)
    for extra in (
        {"ratio": "adaptive", "duration_seconds": -1},
        {"ratio": "16:9", "duration_seconds": 99},
        {"ratio": "1:1", "duration_seconds": 1},
    ):
        draft = adapter.spec({"prompt": "x", "draft": True, **extra})
        final = adapter.spec({"draft_task_id": "cgt-draft", **extra})
        assert (final.ratio, final.seconds) == (draft.ratio, draft.seconds)
        assert (final.estimate_ratio, final.estimate_seconds) == (
            draft.estimate_ratio,
            draft.estimate_seconds,
        )
    with pytest.raises(ValueError, match="ratio"):
        adapter.spec({"draft_task_id": "cgt-draft", "ratio": "2:1"})
    with pytest.raises(ValueError, match="duration_seconds"):
        adapter.spec({"draft_task_id": "cgt-draft", "duration_seconds": "5"})


@pytest.mark.parametrize(("sent", "recorded"), [(False, False), (True, True), (None, True)])
def test_the_finals_payload_says_the_drafts_own_sound_and_never_sends_it(
    sent: bool | None, recorded: bool
) -> None:
    """Review round 4: a silent draft's final said `generate_audio: True` (the family's
    default) in its payload and provenance. The draft's own setting rides along for the
    payload only; a draft that does not say is taken as the family's default."""
    rec = Recorder(done(id="cgt-final", resolution="1080p", draft=False, draft_task_id="cgt-d"))
    params: dict[str, object] = {"draft_task_id": "cgt-d"}
    if sent is not None:
        params["generate_audio"] = sent
    result = adapter(rec).generate(request(**params), api_key="k")
    assert result.payload["generate_audio"] is recorded
    assert "generate_audio" not in rec.posts[0]
