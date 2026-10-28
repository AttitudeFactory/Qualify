"""Reel replication edits the source instead of producing a new three-shot ad."""

from uuid import uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.adapters import SeedanceVideoAdapter
from qualify_creative.enums import ContentKind

from qualify_api.creative import media as media_module

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, _brief, _kit
from .test_creative_seedance_draft import _finalize, _record
from .test_creative_seedance_video_input import (
    REF,
    VideoInputSeedance,
    _measured,
    _producer,
)


def edit_brief(**overrides):
    return _brief(
        ContentKind.CLIP,
        **{
            "clip_reference_mode": "edit",
            "clip_video_keys": (REF,),
            "clip_image_keys": (f"uploads/{TENANT_ID}/p1.jpg",),
            "duration_seconds": 5,
            **overrides,
        },
    )


def test_reel_edit_preserves_the_source_canvas_and_uses_native_edit_in_draft(monkeypatch):
    _measured(monkeypatch, 5)
    monkeypatch.setattr(media_module, "_video_dimensions", lambda data: (854, 480))
    seedance = VideoInputSeedance()
    outcome = _producer(seedance).produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=edit_brief(),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    params = request.params
    spec = SeedanceVideoAdapter(model=params["model"]).spec(params)
    body = spec.body()
    assert body["omni_reference_task_type"] == "edit"
    assert body["ratio"] == "adaptive" and body["duration"] == -1
    assert body["draft"] is True and body["resolution"] == "480p"
    assert len(params["reference_images"]) == 1
    # the reel's shot structure stays the base (second-plane), and the photo-background
    # safety is kept; the absolute scene-freeze is relaxed elsewhere
    assert "Keep the original shot count" in params["prompt"]
    assert "Do not transfer their background" in params["prompt"]
    assert "Shot 1" not in params["prompt"]
    (video,) = outcome.media
    assert (video.width, video.height) == (854, 480)
    assert video.params["draft"]["status"] == "draft"
    assert video.params["reference_mode"] == "edit"


def test_reel_edit_prompt_carries_the_merged_topic_as_production_instructions():
    """m-24820836: the merged topic (brand identity + scene requests) reaches the video
    as production instructions, the reel's structure stays the base, and brand colors
    apply to the scene — the absolute scene-freeze and the «only replacement branding»
    limit are gone."""
    brief = edit_brief().model_copy(
        update={
            "topic": (
                "Añade humo a la escena y usa los colores de la marca\n\n"
                "— Contexto de replicación (segundo plano) —\nreel de referencia"
            ),
        }
    )
    prompt = media_module.reel_edit_prompt(brief=brief, kit=_kit(), images=1)

    # the merged topic reaches the video prompt as production instructions
    assert "Añade humo a la escena y usa los colores de la marca" in prompt
    assert "Contexto de replicación" in prompt

    # the reel's structure stays the base (second-plane)
    assert "Keep the original shot count" in prompt
    assert "second-plane base" in prompt

    # brand colors apply to the scene's styling; the old restrictive line is gone
    assert "scene's styling and accents" in prompt
    assert "Brand colors apply only to replacement branding" not in prompt

    # the absolute scene freeze is relaxed
    assert "Keep the original background, surface, lighting and composition" not in prompt
    assert "Do not add or remove shots, invent actions, add a CTA scene" not in prompt

    # the operator's explicit scene requests are now allowed (CTA scene ban relaxed)
    assert "add or change shots, actions or elements they asked for" in prompt


def test_approving_an_edit_keeps_its_native_canvas_without_cropping(monkeypatch):
    _measured(monkeypatch, 5)
    monkeypatch.setattr(media_module, "_video_dimensions", lambda data: (854, 480))
    seedance, draft_id = VideoInputSeedance(), uuid4()
    producer, brief = _producer(seedance), edit_brief()
    (draft,) = producer.produce(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    ).media
    outcome = _finalize(producer, brief, _record(draft), draft_id)
    assert outcome.failure is None, outcome.detail
    assert (outcome.media.width, outcome.media.height) == (854, 480)
    body = (
        SeedanceVideoAdapter(model=seedance.requests[-1].params["model"])
        .spec(seedance.requests[-1].params)
        .body()
    )
    assert body["content"] == [{"type": "draft_task", "draft_task": {"id": "cgt-draft"}}]


@pytest.mark.parametrize("seconds", [None, 3, 10])
def test_unusable_edit_source_never_submits_a_paid_video(monkeypatch, seconds):
    _measured(monkeypatch, seconds)
    seedance = VideoInputSeedance()
    outcome = _producer(seedance).produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=edit_brief(),
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is not None
    assert seedance.requests == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"clip_video_keys": ()},
        {"clip_video_keys": (REF, REF + "2")},
        {"clip_image_keys": ()},
        {"clip_first_frame_key": "uploads/first.jpg"},
        {"clip_audio_keys": ("uploads/music.mp3",)},
    ],
)
def test_edit_requires_one_source_and_product_photos_without_frame_or_audio_overrides(overrides):
    with pytest.raises(ValidationError):
        edit_brief(**overrides)
