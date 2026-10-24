"""Seedance 2.5's `omni_reference_task_type` (read 2026-10-22): the hint is sent as given
and checked the way ModelArk checks it at creation, so a bad edit or extension fails the
pre-flight instead of a queued task; 2.5 takes more references than 2.0."""

import pytest

from qualify_creative.adapters import SeedanceVideoAdapter
from qualify_creative.enums import GenerationTask
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, RenderedPrompt

V25 = SeedanceVideoAdapter(model="dreamina-seedance-2-5-260628")
MINI = SeedanceVideoAdapter(model="dreamina-seedance-2-0-mini-260615")
VIDEO = "https://qualify.example/public/media/tok-1"
IMAGE = "data:image/jpeg;base64,AAAA"


def _params(**kw: object) -> dict[str, object]:
    return {"prompt": "Video edit: remove the logo in @Video1.", "reference_videos": [VIDEO], **kw}


def test_an_edit_is_sent_adaptive_with_the_models_own_length() -> None:
    body = V25.spec(
        _params(omni_reference_task_type="edit", ratio="adaptive", duration_seconds=-1)
    ).body()
    assert body["omni_reference_task_type"] == "edit"
    assert body["ratio"] == "adaptive" and body["duration"] == -1
    assert body["content"][1] == {
        "type": "video_url",
        "video_url": {"url": VIDEO},
        "role": "reference_video",
    }


def test_an_edit_or_extension_refuses_what_modelark_would() -> None:
    with pytest.raises(ValueError, match="ratio 'adaptive'"):
        V25.spec(_params(omni_reference_task_type="edit", duration_seconds=-1))
    with pytest.raises(ValueError, match="duration -1"):
        V25.spec(_params(omni_reference_task_type="edit", ratio="adaptive", duration_seconds=5))
    with pytest.raises(ValueError, match="needs a reference video"):
        V25.spec(
            {
                "prompt": "Extend it.",
                "reference_images": [IMAGE],
                "omni_reference_task_type": "extend",
                "ratio": "adaptive",
            }
        )
    # an extension takes a length of its own
    body = V25.spec(
        _params(omni_reference_task_type="extend", ratio="adaptive", duration_seconds=11)
    ).body()
    assert body["duration"] == 11 and body["omni_reference_task_type"] == "extend"


def test_reference_needs_references_and_takes_any_ratio() -> None:
    body = V25.spec(
        {"prompt": "x", "reference_images": [IMAGE], "omni_reference_task_type": "reference"}
    ).body()
    assert body["omni_reference_task_type"] == "reference" and body["ratio"] == "9:16"
    with pytest.raises(ValueError, match="task with references"):
        V25.spec({"prompt": "x", "omni_reference_task_type": "reference"})


def test_the_hint_is_2_5_only_and_from_a_known_set() -> None:
    with pytest.raises(ValueError, match="use Seedance 2.5"):
        MINI.spec(_params(omni_reference_task_type="reference"))
    with pytest.raises(ValueError, match="must be one of"):
        V25.spec(_params(omni_reference_task_type="remix"))
    # omitted: nothing sent, the API's `auto`
    assert "omni_reference_task_type" not in V25.spec(_params()).body()


def test_2_5_takes_more_references_than_2_0() -> None:
    images = [IMAGE] * 12
    assert len(V25.spec({"prompt": "x", "reference_images": images}).reference_images) == 12
    with pytest.raises(ValueError, match="at most 9 reference images"):
        MINI.spec({"prompt": "x", "reference_images": images})
    videos = [VIDEO] * 10
    assert len(V25.spec({"prompt": "x", "reference_videos": videos}).reference_videos) == 10
    with pytest.raises(ValueError, match="at most 10 reference videos"):
        V25.spec({"prompt": "x", "reference_videos": [VIDEO] * 11})


def test_adaptive_and_auto_length_are_2x_values_and_are_estimated() -> None:
    with pytest.raises(ValueError, match="no adaptive ratio"):
        SeedanceVideoAdapter().spec({"prompt": "x", "ratio": "adaptive"})
    # 1.0 has no -1: it is clamped into its range, as any length was
    assert SeedanceVideoAdapter().spec({"prompt": "x", "duration_seconds": -1}).seconds == 2
    request = GenerationRequest(
        task=GenerationTask.SCENE_VIDEO,
        rendered_prompt=RenderedPrompt("", "", ""),
        params=_params(omni_reference_task_type="edit", ratio="adaptive", duration_seconds=-1),
    )
    # an unknown length is priced at the model's longest, an unknown ratio as 9:16
    cost = V25.estimate_cost_usd(request, JsonPricingTable("v5"))
    longest = V25.estimate_cost_usd(
        GenerationRequest(
            task=GenerationTask.SCENE_VIDEO,
            rendered_prompt=RenderedPrompt("", "", ""),
            params=_params(ratio="9:16", duration_seconds=30),
        ),
        JsonPricingTable("v5"),
    )
    assert cost == longest > 0
