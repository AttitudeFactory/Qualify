"""The clip kind (§ request 2026-10-14): a generated video with no presenter, from an
opening frame (and a closing one), or from references — images, videos, audio — on a
Seedance 2.x model. Same fakes as `test_creative_media_byteplus.py`."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.enums import ContentKind, FailureReason

from qualify_api.creative.media import (
    CLIP_NO_PUBLIC_URL,
    MediaProducer,
    clip_prompt,
    generated_key,
)

from .test_creative_media_byteplus import (
    TENANT_ID,
    FakeSeedance,
    MemoryStore,
    _brief,
    _image,
    _kit,
    _produce,
    _producer,
)

REF_MODEL = "dreamina-seedance-2-0-mini-260615"


def _clip_store() -> MemoryStore:
    return MemoryStore(
        {
            f"uploads/{TENANT_ID}/first.jpg": _image(),
            f"uploads/{TENANT_ID}/last.jpg": _image((10, 200, 10)),
            f"uploads/{TENANT_ID}/product.jpg": _image((10, 10, 200)),
            f"uploads/{TENANT_ID}/ref.mp4": b"mp4-reference",
            f"uploads/{TENANT_ID}/song.mp3": b"mp3-reference",
        }
    )


class RecordingLinks:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, *, tenant_id: Any, key: str, data: bytes, content_type: str) -> str:
        assert tenant_id == TENANT_ID and data
        self.calls.append((key, content_type))
        return f"https://qualify.example/public/media/tok-{len(self.calls)}"


def _clip_producer(
    store: MemoryStore, seedance: FakeSeedance, links: RecordingLinks | None = None
) -> MediaProducer:
    producer = _producer(store, seedance=seedance)
    producer._seedance_reference_model = REF_MODEL
    producer._reference_links = links
    return producer


def test_frames_alone_animate_from_the_opening_to_the_closing_frame() -> None:
    store, seedance, draft_id = _clip_store(), FakeSeedance(), uuid4()
    brief = _brief(
        ContentKind.CLIP,
        clip_first_frame_key=f"uploads/{TENANT_ID}/first.jpg",
        clip_last_frame_key=f"uploads/{TENANT_ID}/last.jpg",
    )
    outcome = _produce(_clip_producer(store, seedance), brief, draft_id)

    assert outcome.failure is None
    (request,) = seedance.requests
    params = request.params
    assert "model" not in params  # the default model takes frames
    assert str(params["first_frame"]).startswith("data:image/jpeg;base64,")
    assert str(params["last_frame"]).startswith("data:image/jpeg;base64,")
    assert "reference_images" not in params
    (video,) = outcome.media
    assert video.media_type == "video" and video.ai_generated
    assert store.files[generated_key(TENANT_ID, draft_id, "clip.mp4")] == b"mp4-bytes"
    assert video.params["thumbnail_key"] == generated_key(TENANT_ID, draft_id, "first-frame.jpg")


def test_references_go_to_the_2x_model_with_the_frames_named_first() -> None:
    store, seedance, links = _clip_store(), FakeSeedance(), RecordingLinks()
    brief = _brief(
        ContentKind.CLIP,
        clip_first_frame_key=f"uploads/{TENANT_ID}/first.jpg",
        clip_image_keys=(f"uploads/{TENANT_ID}/product.jpg",),
        clip_video_keys=(f"uploads/{TENANT_ID}/ref.mp4",),
        clip_audio_keys=(f"uploads/{TENANT_ID}/song.mp3",),
    )
    outcome = _produce(_clip_producer(store, seedance, links), brief, uuid4())

    assert outcome.failure is None
    (request,) = seedance.requests
    params = request.params
    assert params["model"] == REF_MODEL
    assert "first_frame" not in params and "last_frame" not in params
    assert len(params["reference_images"]) == 2  # the opening frame, then the product
    assert params["reference_videos"] == ["https://qualify.example/public/media/tok-1"]
    assert params["reference_audios"] == ["https://qualify.example/public/media/tok-2"]
    assert links.calls == [
        (f"uploads/{TENANT_ID}/ref.mp4", "video/mp4"),
        (f"uploads/{TENANT_ID}/song.mp3", "audio/mpeg"),
    ]
    prompt = str(params["prompt"])
    assert "The opening frame is Image 1." in prompt
    assert "Image 2: the client's real product" in prompt
    assert "camera movement, motion and pacing of Video 1" in prompt
    assert "Use Audio 1 as the soundtrack" in prompt


def test_a_video_reference_without_a_public_url_fails_before_any_spend() -> None:
    store, seedance = _clip_store(), FakeSeedance()
    brief = _brief(ContentKind.CLIP, clip_video_keys=(f"uploads/{TENANT_ID}/ref.mp4",))
    outcome = _produce(_clip_producer(store, seedance, links=None), brief, uuid4())

    assert outcome.failure == FailureReason.INVALID_PARAMETERS.value
    assert outcome.detail == CLIP_NO_PUBLIC_URL
    assert seedance.requests == [] and outcome.usage == ()


def test_a_clip_reference_of_another_tenant_is_refused_before_any_read() -> None:
    store, seedance = _clip_store(), FakeSeedance()
    other = "uploads/00000000-0000-4000-8000-000000000099/ref.mp4"
    brief = _brief(ContentKind.CLIP, clip_video_keys=(other,))
    outcome = _produce(_clip_producer(store, seedance, RecordingLinks()), brief, uuid4())

    assert outcome.failure == FailureReason.ROUTE_BLOCKED_BY_POLICY.value
    assert seedance.requests == []


def test_the_brief_keeps_clip_inputs_to_the_clip() -> None:
    with pytest.raises(ValidationError, match="frames and references are for a clip"):
        _brief(ContentKind.STATIC_FLYER, clip_first_frame_key=f"uploads/{TENANT_ID}/f.jpg")
    with pytest.raises(ValidationError, match="closing frame needs its opening frame"):
        _brief(ContentKind.CLIP, clip_last_frame_key=f"uploads/{TENANT_ID}/l.jpg")
    with pytest.raises(ValidationError, match="at most 9 images"):
        _brief(
            ContentKind.CLIP,
            clip_first_frame_key=f"uploads/{TENANT_ID}/f.jpg",
            clip_image_keys=tuple(f"uploads/{TENANT_ID}/{i}.jpg" for i in range(9)),
        )
    assert _brief(ContentKind.CLIP).requires_ai_disclosure


def test_the_prompt_names_the_product_from_the_catalog() -> None:
    brief = _brief(ContentKind.CLIP).model_copy(update={"product_ref": "Smash doble"})
    prompt = clip_prompt(
        brief=brief,
        kit=_kit(),
        first_frame=True,
        last_frame=False,
        images=0,
        videos=0,
        audios=0,
    )
    assert '"Smash doble"' in prompt and "starts on the opening frame" in prompt


# -- the story, the roles and the facts (§ request 2026-10-14) ---------------------------

FACTS = (("precio", "$18.900"), ("descuento", "20 %"))


def _with_facts(brief: Any) -> Any:
    from qualify_creative.schemas import BriefConstraints

    return brief.model_copy(update={"constraints": BriefConstraints(highlights=FACTS)})


def _copy(**fields: Any) -> Any:
    from qualify_creative.schemas import CopyPayload

    return CopyPayload(hook="¿Doble o nada?", caption="La smash doble.", cta="Pide ya", **fields)


def test_the_clip_tells_its_story_in_three_shots_on_the_hook() -> None:
    """«el clip cuenta una historia … los ganchos ya se tienen, quiero usarlos»: the
    copy's three shots, timed to the clip, opening on its hook."""
    from qualify_creative.schemas import ScriptShot

    brief = _brief(ContentKind.CLIP, duration_seconds=15)
    seconds = brief.media.duration_seconds
    copy = _copy(
        shots=(
            ScriptShot(visual="Una mano duda entre dos hamburguesas", seconds=3),
            ScriptShot(visual="La smash doble chisporrotea en la plancha", seconds=8),
            ScriptShot(visual="La doble, servida, al centro de la mesa", seconds=4),
        )
    )
    prompt = clip_prompt(
        brief=brief,
        kit=_kit(),
        copy=copy,
        first_frame=False,
        last_frame=False,
        images=0,
        videos=0,
        audios=0,
    )
    assert "advertising video" in prompt and "tells a short story" in prompt
    assert '"¿Doble o nada?"' in prompt and "never written" in prompt
    assert 'Shot 1 (0-3 s): "Una mano duda entre dos hamburguesas"' in prompt
    assert f'Shot 3 (11-{seconds} s): "La doble, servida, al centro de la mesa"' in prompt
    # without the copy's shots, the same three beats on its hook and CTA
    plain = clip_prompt(
        brief=brief,
        kit=_kit(),
        copy=_copy(),
        first_frame=True,
        last_frame=True,
        images=0,
        videos=0,
        audios=0,
    )
    assert "Shot 1 (0-3 s): the hook" in plain and "Shot 2 (3-10 s)" in plain
    assert '"Pide ya"' in plain and "the payoff" in plain
    assert "from the opening frame (shot 1) to the closing frame" in plain


def test_each_reference_image_is_told_its_role() -> None:
    prompt = clip_prompt(
        brief=_brief(ContentKind.CLIP),
        kit=_kit(),
        first_frame=True,
        last_frame=False,
        images=4,
        videos=0,
        audios=0,
        image_roles=("product", "place", "style", "product"),
    )
    assert "The opening frame is Image 1." in prompt
    assert "Images 2 and 5: the client's real product" in prompt
    assert "Image 3: the client's real place" in prompt
    assert "Image 4: a style reference" in prompt
    # a brief from before the roles: every image is the product
    old = clip_prompt(
        brief=_brief(ContentKind.CLIP),
        kit=_kit(),
        first_frame=False,
        last_frame=False,
        images=2,
        videos=0,
        audios=0,
    )
    assert "Images 1 and 2: the client's real product" in old


def test_the_roles_reach_the_2x_request() -> None:
    store, seedance, links = _clip_store(), FakeSeedance(), RecordingLinks()
    store.files[f"uploads/{TENANT_ID}/place.jpg"] = _image((90, 60, 30))
    brief = _brief(
        ContentKind.CLIP,
        clip_image_keys=(f"uploads/{TENANT_ID}/product.jpg", f"uploads/{TENANT_ID}/place.jpg"),
        clip_image_roles=("product", "place"),
    )
    outcome = _produce(_clip_producer(store, seedance, links), brief, uuid4())
    assert outcome.failure is None
    prompt = str(seedance.requests[0].params["prompt"])
    assert "Image 1: the client's real product" in prompt
    assert "Image 2: the client's real place" in prompt


def test_a_clip_image_role_is_checked() -> None:
    with pytest.raises(ValidationError, match="one each"):
        _brief(
            ContentKind.CLIP,
            clip_image_keys=(f"uploads/{TENANT_ID}/a.jpg",),
            clip_image_roles=("product", "place"),
        )
    with pytest.raises(ValidationError, match="role is one of"):
        _brief(
            ContentKind.CLIP,
            clip_image_keys=(f"uploads/{TENANT_ID}/a.jpg",),
            clip_image_roles=("hero",),
        )


def test_datos_clave_reach_every_media_prompt() -> None:
    """«quiero añadir los datos claves a los prompts (todos)»: the image, the carousel
    slide and its motion, the avatar's frame and motion, the clip — each as JSON, each
    told not to write them."""
    from qualify_creative.enums import AdImageMode

    from qualify_api.creative.media import (
        ad_scene_prompt,
        carousel_motion_prompt,
        carousel_scene_prompt,
        first_frame_prompt,
        motion_prompt,
    )

    kit = _kit()
    facts = '{"precio": "$18.900", "descuento": "20 %"}'

    def prompts(flyer: Any, carousel: Any, avatar: Any, clip: Any) -> list[str]:
        return [
            ad_scene_prompt(
                brief=flyer,
                kit=kit,
                brand="Smash",
                mode=AdImageMode.PRODUCT,
                products=1,
                has_background=False,
            ),
            carousel_scene_prompt(
                brief=carousel,
                kit=kit,
                brand="Smash",
                scene="",
                ratio="4:5",
                has_product=True,
                has_background=False,
                has_text=True,
            ),
            carousel_motion_prompt(carousel),
            first_frame_prompt(
                brief=avatar, kit=kit, has_character_image=False, products=1, has_background=False
            ),
            motion_prompt(brief=avatar, products=1),
            clip_prompt(
                brief=clip,
                kit=kit,
                copy=_copy(),
                first_frame=False,
                last_frame=False,
                images=0,
                videos=0,
                audios=0,
            ),
        ]

    briefs = (
        _brief(ContentKind.STATIC_FLYER),
        _brief(ContentKind.STATIC_FLYER),  # the slide's prompts only read the brief
        _brief(ContentKind.STATIC_FLYER),  # the avatar's frame and motion too
        _brief(ContentKind.CLIP),
    )
    for prompt in prompts(*(_with_facts(brief) for brief in briefs)):
        assert facts in prompt, prompt[:80]
        assert len(prompt) < 3000
    for prompt in prompts(*briefs):
        assert "Key facts" not in prompt
