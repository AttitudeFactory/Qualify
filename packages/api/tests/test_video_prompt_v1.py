"""Seedance video prompts at compiler 1, round 7b (m-24820842, 2026-11-02): the exact
repetitions removed (the text rule's label/lettering sentence the typefaces line already
says; identical «@ImageN» lines in the replica), the talking video's preflight ranked with
the other combinations, the trace counting brand resources apart. Offline, on the
anonymized real case; not model quality."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.adapters.byteplus_ark import prompt_words
from qualify_creative.enums import AvatarSource, ContentKind, VideoEngine
from qualify_creative.schemas import ContentBrief, CopyPayload, ScriptShot

from qualify_api.creative import media as media_module
from qualify_api.creative.brand_references import BrandReferenceError
from qualify_api.creative.media import (
    _LABELS_AND_LETTERING,
    _talking_room_problem,
    carousel_motion_prompt,
    clip_prompt,
    motion_prompt,
)

from .prompt_quality import assert_prompt_keeps_intent, assert_video_prompt_keeps_intent
from .test_creative_media_byteplus import BUDGET, COPY
from .test_creative_media_byteplus import TENANT_ID as TEST_TENANT
from .test_creative_media_byteplus import _kit as _test_kit
from .test_creative_reel_edit import edit_brief
from .test_creative_seedance_video_input import VideoInputSeedance, _measured
from .test_creative_seedance_video_input import _producer as _edit_producer
from .test_prompt_budget_v1 import (
    SEEDANCE_25,
    TENANT,
    Selector,
    _chosen,
    _fixture_producer,
    _kit,
    _prepare,
    _real,
    _with_brand_text,
)

LABELS = _LABELS_AND_LETTERING.strip()
PRODUCT = "producto XY"
MANDATORY = "Every selected brand resource is mandatory"
SHOTS = CopyPayload(
    hook="La que te llama",
    caption="Texto",
    cta="Pide ya",
    shots=(
        ScriptShot(visual="Primer plano de la carne sobre la plancha caliente.", seconds=2),
        ScriptShot(visual="El queso se derrite sobre la doble carne.", seconds=2),
        ScriptShot(visual="La hamburguesa servida con papas en la bandeja.", seconds=1),
    ),
)


def _motion(version: int = 1) -> ContentBrief:
    brief = _real(
        version=version,
        clip_reference_mode="motion",
        source_reel=None,
        clip_image_keys=("a", "b"),
        clip_image_roles=("product", "product"),
    )
    return brief.model_copy(update={"topic": brief.topic.split("\n\n")[0]})


def _talking(version: int = 1) -> ContentBrief:
    brief = _real(
        version=version,
        video_engine=VideoEngine.SEEDANCE,
        avatar_source=AvatarSource.AI,
        avatar_prompt="Mujer de unos 30 años",
        product_keys=(f"uploads/{TENANT}/p1.jpg",),
        clip_reference_mode="motion",
        source_reel=None,
        clip_image_keys=(),
        clip_image_roles=(),
        clip_video_keys=(),
    )
    return brief.model_copy(update={"kind": ContentKind.AVATAR_VIDEO, "topic": "Hola."})


def _clip(brief: ContentBrief, refs: list[Any], copy: CopyPayload | None = SHOTS) -> str:
    return clip_prompt(
        brief=brief,
        kit=_kit(),
        first_frame=False,
        last_frame=False,
        images=2,
        videos=1,
        audios=0,
        image_roles=("product", "product"),
        brand_refs=refs,
        copy=copy,
        model=SEEDANCE_25,
    )


@pytest.mark.parametrize("combo", [(0,), (1,), (2,), (0, 1, 2)])
def test_motion_clip_says_the_label_rule_once(combo: tuple[int, ...]) -> None:
    refs = _chosen(combo)
    before, after = _clip(_motion(0), refs), _clip(_motion(), refs)
    assert before.count(LABELS) == 1 and after.count(LABELS) == 0
    old_product = (
        "It shows the client's real product, "
        + f'"{PRODUCT}"'
        + ", exactly as it is: shape, colors, label. "
    )
    old_photo = "the client's real product — keep it exactly as it is (shape, colors, label)"
    new_photo = media_module._PRODUCT_PHOTO_LINE.format(product=PRODUCT)
    merge = len(old_product) - (len(new_photo) - len(old_photo))
    assert len(before) - len(after) == len(_LABELS_AND_LETTERING) + merge
    assert "Preserve authentic product labels in their original typeface." in after
    assert old_product.strip() in before and "It shows the client's real product" not in after
    assert f"Images 1 and 2: {new_photo}." in after
    assert_video_prompt_keeps_intent(
        after,
        brief=_motion(),
        kit=_kit(),
        refs=refs,
        base_index=2,
        texts=(_motion().topic, *(shot.visual for shot in SHOTS.shots)),
        product=PRODUCT,
    )


@pytest.mark.parametrize("roles", [(), ("place",), ("style", "place")])
def test_without_a_product_photo_the_product_keeps_its_own_line(roles: tuple[str, ...]) -> None:
    prompt = clip_prompt(
        brief=_motion(),
        kit=_kit(),
        first_frame=False,
        last_frame=False,
        images=len(roles),
        videos=1,
        audios=0,
        image_roles=roles,
        brand_refs=_chosen((0,)),
        copy=SHOTS,
        model=SEEDANCE_25,
    )
    assert "It shows the client's real product, " + f'"{PRODUCT}"' in prompt


@pytest.mark.parametrize("numbered", [False, True])
def test_animated_slide_says_the_label_rule_once(numbered: bool) -> None:
    refs = _chosen((0, 1, 2))

    def slide(version: int) -> str:
        motion = carousel_motion_prompt(
            _motion(version), refs, numbered=numbered, kit=_kit(), uncapped=version >= 1
        )
        if numbered:
            motion = media_module._carousel_reference_motion(
                motion, strict=True, uncapped=version >= 1
            )
        return motion

    before, after = slide(0), slide(1)
    assert before.count(LABELS) == 1 and after.count(LABELS) == 0
    assert_video_prompt_keeps_intent(
        after, brief=_motion(), kit=_kit(), refs=refs, base_index=1, numbered=numbered
    )


def test_talking_video_says_the_label_rule_once() -> None:
    refs = _chosen((0,))  # one logo: the full (not the compact multi-logo) wording

    def talk(version: int) -> str:
        return motion_prompt(
            brief=_talking(version), products=1, budget=None, brand_refs=refs, kit=_kit()
        )

    assert talk(0).count(LABELS) == 1 and talk(1).count(LABELS) == 0
    assert_video_prompt_keeps_intent(
        talk(1),
        brief=_talking(),
        kit=_kit(),
        refs=refs,
        base_index=1,
        numbered=False,
        resources_mandatory=True,
    )


@pytest.mark.parametrize("reference_mode", [False, True])
@pytest.mark.parametrize("combo", [(0,), (1,), (2,), (0, 1, 2)])
def test_talking_video_keeps_every_unit_of_the_mandatory_sentence(
    combo: tuple[int, ...], reference_mode: bool
) -> None:
    refs = _chosen(combo)

    def talk(version: int) -> str:
        return motion_prompt(
            brief=_talking(version),
            products=1,
            budget=None,
            brand_refs=refs,
            kit=_kit(),
            reference_mode=reference_mode,
        )

    before, after = talk(0), talk(1)
    assert MANDATORY in before and MANDATORY not in after
    assert media_module._TALKING_PRESENCE_LINE in after
    assert_video_prompt_keeps_intent(
        after,
        brief=_talking(),
        kit=_kit(),
        refs=refs,
        base_index=1,
        numbered=reference_mode,
        resources_mandatory=True,
    )


@pytest.mark.parametrize("on", [False, True])
def test_replica_names_photos_of_one_role_together(on: bool) -> None:
    kit = _kit(cta_patterns=("¡Pide la tuya hoy!",))
    brief = _with_brand_text(
        _real(clip_image_keys=("a", "b"), clip_image_roles=("product", "product")), on
    )
    refs = _chosen((0,))
    prompt = clip_prompt(
        brief=brief,
        kit=kit,
        first_frame=False,
        last_frame=False,
        images=2,
        videos=1,
        audios=0,
        image_roles=("product", "product"),
        brand_refs=refs,
        model=SEEDANCE_25,
    )
    line = "@Image1, @Image2: real product identity/ingredients/labels, not its photo"
    assert line in prompt and "@Image2: real product" not in prompt.replace(line, "")
    assert_prompt_keeps_intent(prompt, brief=brief, kit=kit, refs=refs, images=2, budget=None)


def test_talking_preflight_reports_the_worst_combination() -> None:
    producer, selector = _fixture_producer(Selector())
    producer._seedance_model = SEEDANCE_25
    own = _talking(0).model_copy(
        update={"media": _talking(0).media.model_copy(update={"own_script": "a " * 990})}
    )
    brief = producer.prepare_new_brief(own, _kit())
    overs = [
        _talking_room_problem(
            brief,
            prompt_words(
                motion_prompt(
                    brief=brief,
                    products=1,
                    budget=None,
                    brand_refs=_chosen(combo),
                    kit=_kit(),
                )
            ),
        )
        for combo in [(0,), (1,), (2,), (0, 1, 2)]
    ]
    assert len(set(overs)) > 1  # the combinations differ: the first is not the worst
    with pytest.raises(BrandReferenceError) as caught:
        _prepare(producer, brief)
    assert caught.value.detail.startswith(
        f"Tu guion es muy largo para este video: sobran {max(overs)} palabras."
    )
    assert selector.requests == []


def test_the_trace_counts_brand_resources_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(media_module.trace, "media_request", lambda **k: seen.append(k))
    _measured(monkeypatch, 5)
    monkeypatch.setattr(media_module, "_video_dimensions", lambda data: (854, 480))
    brief = edit_brief()
    brief = brief.model_copy(
        update={"media": brief.media.model_copy(update={"prompt_compiler_version": 1})}
    )
    outcome = _edit_producer(VideoInputSeedance()).produce(
        tenant_id=TEST_TENANT,
        draft_id=uuid4(),
        brief=brief,
        kit=_test_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None, outcome.detail
    (clip,) = [k for k in seen if k["what"] == "clip"]
    assert clip["fields"]["referencias"] == "1 foto + 0 recursos de marca · 1 video · 0 audios"
