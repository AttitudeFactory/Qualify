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


def test_the_brand_typeface_reaches_every_media_prompt_with_the_palette() -> None:
    """§ request 2026-10-21: the Brand Kit's type face goes wherever the palette goes —
    the image, the carousel slide, the avatar's frame, the clip — as a style cue that
    never asks for letters; a kit without them writes the prompts as before."""
    from qualify_creative.enums import AdImageMode

    from qualify_api.creative.media import (
        ad_scene_prompt,
        carousel_motion_prompt,
        carousel_scene_prompt,
        first_frame_prompt,
        motion_prompt,
    )

    def prompts(kit: Any) -> list[str]:
        flyer, avatar, clip = (
            _brief(ContentKind.STATIC_FLYER),
            _brief(ContentKind.STATIC_FLYER),
            _brief(ContentKind.CLIP),
        )
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
                brief=flyer,
                kit=kit,
                brand="Smash",
                scene="",
                ratio="4:5",
                has_product=True,
                has_background=False,
                has_text=True,
            ),
            first_frame_prompt(
                brief=avatar, kit=kit, has_character_image=False, products=1, has_background=False
            ),
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

    # one face (today's Brand Kit), or the headline one of a kit that held two
    for kit in (
        _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Baloo 2"}),
        _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"}),
    ):
        for prompt in prompts(kit):
            assert "The brand's typeface is Baloo 2:" in prompt, prompt[:80]
            assert "without drawing any letters" in prompt and "Nunito" not in prompt
    for prompt in prompts(_kit()):
        assert "typeface" not in prompt
    # the motion prompts read no kit: no palette, no typeface
    flyer = _brief(ContentKind.STATIC_FLYER)  # the motion prompts only read its facts
    for prompt in (carousel_motion_prompt(flyer), motion_prompt(brief=flyer, products=1)):
        assert "typeface" not in prompt
    # a kit stores no cap on a face's name: the prompt does, under the vendor's 3,000
    long = _kit().model_copy(update={"font_heading": "F" * 500})
    for prompt in prompts(long):
        assert "F" * 61 not in prompt and len(prompt) < 3000


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


def test_the_chosen_logo_goes_over_every_frame_and_the_sound_stays() -> None:
    """§ request 2026-10-20: «me hace falta poner mis logos en mis clips» — the logo is
    laid over the generated clip at its own size; its soundtrack is kept."""
    from .test_creative_media_byteplus import FakeFitter

    store, seedance, fitter, draft_id = _clip_store(), FakeSeedance(), FakeFitter(), uuid4()
    store.files[f"uploads/{TENANT_ID}/logo.png"] = _image((200, 10, 10))
    producer = _clip_producer(store, seedance)
    producer._fitter = fitter
    brief = _brief(
        ContentKind.CLIP,
        clip_first_frame_key=f"uploads/{TENANT_ID}/first.jpg",
        brand_logo_key=f"uploads/{TENANT_ID}/logo.png",
    )
    outcome = _produce(producer, brief, draft_id)

    assert outcome.failure is None
    (call,) = fitter.calls
    assert call["data"] == b"mp4-bytes" and call["overlay"][:4] == b"\x89PNG"
    assert call["keep_audio"] is True
    (video,) = outcome.media
    assert call["size"] == (video.width, video.height)  # the clip's own size: no crop
    assert store.files[generated_key(TENANT_ID, draft_id, "clip.mp4")] == b"fitted-mp4-bytes"
    assert video.params["logo"] is True


def test_a_clip_without_a_logo_is_stored_as_seedance_made_it() -> None:
    from .test_creative_media_byteplus import FakeFitter

    store, seedance, fitter, draft_id = _clip_store(), FakeSeedance(), FakeFitter(), uuid4()
    producer = _clip_producer(store, seedance)
    producer._fitter = fitter
    brief = _brief(ContentKind.CLIP, clip_first_frame_key=f"uploads/{TENANT_ID}/first.jpg")
    outcome = _produce(producer, brief, draft_id)

    assert outcome.failure is None and fitter.calls == []
    assert store.files[generated_key(TENANT_ID, draft_id, "clip.mp4")] == b"mp4-bytes"
    assert outcome.media[0].params["logo"] is False


def test_a_logo_with_no_fitter_wired_fails_before_seedance_is_paid() -> None:
    store, seedance = _clip_store(), FakeSeedance()
    store.files[f"uploads/{TENANT_ID}/logo.png"] = _image((200, 10, 10))
    brief = _brief(
        ContentKind.CLIP,
        clip_first_frame_key=f"uploads/{TENANT_ID}/first.jpg",
        brand_logo_key=f"uploads/{TENANT_ID}/logo.png",
    )
    outcome = _produce(_clip_producer(store, seedance), brief, uuid4())

    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert seedance.requests == [] and outcome.usage == ()


class _NoReferenceModel(FakeSeedance):
    """An account without Seedance 2.x: a request naming a model is refused before any
    task exists (ModelArk's `ModelNotOpen`, measured live 2026-10-20)."""

    def generate(self, request: Any, *, api_key: str) -> Any:
        if request.params.get("model"):
            self.requests.append(request)
            raise RuntimeError("ArkAPIError: HTTP 404 ModelNotOpen: not activated")
        return super().generate(request, api_key=api_key)


def test_a_clip_of_images_only_falls_back_to_its_frames_without_the_2x_model() -> None:
    """§ request 2026-10-20: «si le estoy pasando solo imágenes» — three images make the
    middle one a reference (2.x only); without 2.x on the account the clip is made from
    its opening and closing images on the default model, not refused."""
    store, seedance, draft_id = _clip_store(), _NoReferenceModel(), uuid4()
    brief = _brief(
        ContentKind.CLIP,
        clip_first_frame_key=f"uploads/{TENANT_ID}/first.jpg",
        clip_last_frame_key=f"uploads/{TENANT_ID}/last.jpg",
        clip_image_keys=(f"uploads/{TENANT_ID}/product.jpg",),
        clip_image_roles=("product",),
    )
    outcome = _produce(_clip_producer(store, seedance, RecordingLinks()), brief, draft_id)

    assert outcome.failure is None
    refused, made = seedance.requests
    assert refused.params["model"] == REF_MODEL
    assert "model" not in made.params and "reference_images" not in made.params
    assert str(made.params["first_frame"]).startswith("data:image/")
    assert str(made.params["last_frame"]).startswith("data:image/")
    (video,) = outcome.media
    assert video.params["references_dropped"] == {"images": 1, "videos": 0}
    assert video.params["references"]["images"] == 0
    assert len(outcome.usage) == 1  # only the clip that was made is paid


def test_a_reference_video_without_the_2x_model_still_says_so() -> None:
    store, seedance = _clip_store(), _NoReferenceModel()
    brief = _brief(
        ContentKind.CLIP,
        clip_first_frame_key=f"uploads/{TENANT_ID}/first.jpg",
        clip_video_keys=(f"uploads/{TENANT_ID}/ref.mp4",),
    )
    outcome = _produce(_clip_producer(store, seedance, RecordingLinks()), brief, uuid4())

    assert outcome.failure == FailureReason.PROVIDER_ERROR.value
    assert "no está activado" in (outcome.detail or "")
    assert len(seedance.requests) == 1  # no frames-only retry: the video would be lost


class _BrokenFitter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def fit(self, data: bytes, **kwargs: Any) -> Any:
        self.calls.append({"data": data, **kwargs})
        raise ValueError("an H.264 slide needs even dimensions")


def test_a_logo_that_cannot_be_laid_keeps_the_paid_clip() -> None:
    """Review 2026-10-20: the clip is billed before the logo goes on it — a failure to
    lay the logo leaves the clip as Seedance made it, never a failed piece."""
    store, seedance, fitter, draft_id = _clip_store(), FakeSeedance(), _BrokenFitter(), uuid4()
    store.files[f"uploads/{TENANT_ID}/logo.png"] = _image((200, 10, 10))
    producer = _clip_producer(store, seedance)
    producer._fitter = fitter
    brief = _brief(
        ContentKind.CLIP,
        clip_first_frame_key=f"uploads/{TENANT_ID}/first.jpg",
        brand_logo_key=f"uploads/{TENANT_ID}/logo.png",
    )
    outcome = _produce(producer, brief, draft_id)

    assert outcome.failure is None and len(fitter.calls) == 1
    assert store.files[generated_key(TENANT_ID, draft_id, "clip.mp4")] == b"mp4-bytes"
    assert outcome.media[0].params["logo"] is False


def test_a_video_that_closes_the_clip_falls_back_to_its_frame_without_2x() -> None:
    """Review 2026-10-20: a video is a motion reference even when it closes the clip;
    without Seedance 2.x the clip is still made, ending on that video's last frame."""
    store, seedance, draft_id = _clip_store(), _NoReferenceModel(), uuid4()
    store.files[f"uploads/{TENANT_ID}/ref.mp4"] = _tiny_mp4()
    brief = _brief(
        ContentKind.CLIP,
        clip_first_frame_key=f"uploads/{TENANT_ID}/first.jpg",
        clip_last_frame_key=f"uploads/{TENANT_ID}/ref.mp4",
        clip_video_keys=(f"uploads/{TENANT_ID}/ref.mp4",),
    )
    outcome = _produce(_clip_producer(store, seedance, RecordingLinks()), brief, draft_id)

    assert outcome.failure is None
    refused, made = seedance.requests
    assert refused.params["reference_videos"] and "model" not in made.params
    assert str(made.params["last_frame"]).startswith("data:image/")
    assert outcome.media[0].params["references_dropped"] == {"images": 0, "videos": 1}


def test_without_a_public_url_a_frame_video_clip_is_still_made() -> None:
    store, seedance, draft_id = _clip_store(), FakeSeedance(), uuid4()
    store.files[f"uploads/{TENANT_ID}/ref.mp4"] = _tiny_mp4()
    brief = _brief(
        ContentKind.CLIP,
        clip_first_frame_key=f"uploads/{TENANT_ID}/ref.mp4",
        clip_video_keys=(f"uploads/{TENANT_ID}/ref.mp4",),
    )
    outcome = _produce(_clip_producer(store, seedance, links=None), brief, draft_id)

    assert outcome.failure is None
    (made,) = seedance.requests
    assert "model" not in made.params and "first_frame" in made.params


def _tiny_mp4() -> bytes:
    """A real 1 s clip: a frame video's first/last frame is extracted locally."""
    import io

    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=12)
        stream.width, stream.height, stream.pix_fmt = 64, 112, "yuv420p"
        for i in range(12):
            pixels = np.full((112, 64, 3), 20 * i, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return out.getvalue()
