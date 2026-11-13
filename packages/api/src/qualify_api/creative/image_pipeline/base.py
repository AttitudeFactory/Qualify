"""Stage `base` of the image and carousel pipeline (ADR 49 §2.3): the Seedream photograph.

In: the compiled scene prompt (`base_prompt`), the reference images in request order and
the format's ratio. Out: the photograph's bytes, its cost written to `usage` the moment it
is paid for, and — for the image and carousel paths — a `BaseScene` that carries the bytes
together with the exact prompt that produced them to the `compose` stage.

`scene_image` is also how a video's first frame and a presenter's photo are drawn
(`MediaProducer._scene_image` delegates here), so it takes the producer — router, pricing
table — as its first argument rather than owning one.

m-25017278 is a move: what is asked of Seedream, what is paid and what is stored are the
same as before it.

m-25017279 (ADR 49 §2 item 1): the base photograph of the advertising image and of every
GENERATED gallery slide is kept the moment it is paid for, before any composition, as the
vendor made it (after the band fill of compilers ≥ 3: the bytes the composition used), at
`t/{tenant}/generated/{draft_id}/r{revision}/base/…` — inside the piece's folder, so the
retention purge of ADR 39 takes it with the piece. Keeping it is optional: a base that R2
refuses is logged and the paid piece goes on without it (`BaseScene.stored` is None). An
animated slide's first frame is not a base: it is kept, as before, for its own resume.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from qualify_creative.enums import AdImageMode, FailureReason, GenerationTask
from qualify_creative.photo.bands import fill_blank_bands
from qualify_creative.pricing import seedream_image_cost
from qualify_creative.providers import GenerationRequest, RenderedPrompt
from qualify_creative.router import BudgetContext
from qualify_creative.scene_plan import SceneReferencePlan
from qualify_creative.schemas import BrandKit, CarouselSlide, ContentBrief

from qualify_api.creative import trace
from qualify_api.creative.brand_references import (
    BrandReferenceError,
    BrandReferenceImage,
    BrandReferencesSet,
)
from qualify_api.creative.image_pipeline.base_prompt import (
    ad_scene_prompt,
    carousel_scene_prompt,
)
from qualify_api.creative.media import (
    SCENE_SIZES,
    SEEDREAM,
    BasePhoto,
    MediaUsage,
    _data_url,
    _MediaFailed,
    _physical_scene_plan,
    _Saver,
)

if TYPE_CHECKING:
    from qualify_api.creative.media import MediaProducer


@dataclass(frozen=True)
class BaseScene:
    """One base photograph as the `base` stage hands it to `compose`: the vendor's bytes,
    the compiled prompt Seedream was sent for them (provenance of the slide) and, when it
    was kept, where (`stored`)."""

    image: bytes
    prompt: str
    stored: BasePhoto | None = None


def _image_type(data: bytes) -> tuple[str, str]:
    """The MIME type and file extension of a vendor image, by its magic bytes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return "image/jpeg", "jpg"


def keep_base(
    save: _Saver,
    *,
    name: str,
    image: bytes,
    prompt: str,
    usage: Sequence[MediaUsage],
    compiler: int,
) -> BasePhoto | None:
    """Keep one paid base photograph under `base/` and describe it; None when R2 refused
    it (the piece is not failed for its base: it was paid and its slide can still be
    composed). The same bytes under the same name are the same key, so a retry of the
    revision never stores a second copy."""
    content_type, extension = _image_type(image)
    key = save.optional(f"base/{name}.{extension}", image, content_type)
    if key is None:
        return None
    made = usage[-1] if usage else None
    return BasePhoto(
        key=key,
        sha256=hashlib.sha256(image).hexdigest(),
        content_type=content_type,
        model_id=made.model_id if made is not None else SEEDREAM,
        provider=made.provider if made is not None else SEEDREAM,
        rendered_prompt=prompt,
        prompt_compiler_version=compiler,
    )


def scene_image(
    producer: MediaProducer,
    *,
    tenant_id: UUID,
    draft_id: UUID,
    brand_id: UUID,
    prompt: str,
    references: list[bytes],
    ratio: str,
    budget: BudgetContext,
    usage: list[MediaUsage],
    what: str,
    reference_plan: dict[str, object] | None = None,
    fill_bands: bool = False,
) -> bytes:
    """One Seedream image (the ad's scene, or a video's first frame), its cost
    recorded the moment it is paid for. `fill_bands`: a gallery slide's scene at
    compiler 3 only (review #5) — every other image comes back exactly as made."""
    request = GenerationRequest(
        task=GenerationTask.PRODUCT_IMAGE,
        rendered_prompt=RenderedPrompt("", "", ""),
        params={
            "prompt": prompt,
            "images": [_data_url(image) for image in references],
            "size": SCENE_SIZES[ratio],
            **({"reference_plan": reference_plan} if reference_plan is not None else {}),
        },
    )
    if reference_plan is not None and "references" in reference_plan:
        sources = reference_plan["references"]
        if not isinstance(sources, list) or len(sources) != len(references):
            raise BrandReferenceError(
                "Cambiaron las fotos que elegiste mientras preparábamos la pieza. "
                "Revísalas y toca «Crear» otra vez."
            )
        request.params["reference_manifest"] = [
            {**source, "sha256": hashlib.sha256(data).hexdigest()}
            for source, data in zip(sources, references, strict=True)
        ]
    trace.media_request(
        draft_id=draft_id,
        provider="Seedream",
        what=what,
        fields={
            "prompt": prompt,
            "imágenes de referencia": len(references),
            "tamaño": SCENE_SIZES[ratio],
        },
    )
    result = producer._run(
        tenant_id=tenant_id,
        brand_id=brand_id,
        link=SEEDREAM,
        request=request,
        budget=budget,
        usage=usage,
    )
    pieces = max(result.usage.pieces, 1)
    from qualify_creative.adapters.byteplus_ark import seedream_size

    payload = result.payload if isinstance(result.payload, dict) else {}
    sizes = payload.get("sizes") or ()
    requested_size = seedream_size(SCENE_SIZES[ratio], result.model_id)
    billed_size = str(sizes[0]) if sizes and sizes[0] else requested_size
    cost = seedream_image_cost(
        producer._pricing,
        model_id=result.model_id,
        size=billed_size,
        references=len(references),
        pieces=pieces,
    )
    usage.append(
        MediaUsage(
            provider=result.provider,
            model_id=result.model_id,
            unit="piece",
            quantity=pieces,
            cost_usd=cost,
        )
    )
    images = payload.get("images") or ()
    if not images:
        raise _MediaFailed(
            FailureReason.PROVIDER_ERROR.value,
            "No se pudo generar la imagen. Inténtalo de nuevo.",
            raw=f"{result.model_id} returned no image",
        )
    # draft 97f35052: a flat empty band the vendor left at the top or bottom of a
    # gallery slide is cropped and the frame covered again — never shown, nor darkened
    # into grey by the scrim. Never on a flyer, a first frame or a presenter's photo,
    # where the crop could cut a head or a product (review #5).
    image = bytes(images[0])
    return fill_blank_bands(image) if fill_bands else image


def flyer_scenes(
    producer: MediaProducer,
    *,
    tenant_id: UUID,
    draft_id: UUID,
    brief: ContentBrief,
    kit: BrandKit,
    brand: str,
    mode: AdImageMode,
    groups: Sequence[Sequence[bytes]],
    plans: Sequence[SceneReferencePlan] | None,
    background: bytes | None,
    brand_images: Sequence[BrandReferenceImage],
    brand_refs: BrandReferencesSet,
    ratio: str,
    budget: BudgetContext,
    usage: list[MediaUsage],
    save: _Saver | None = None,
) -> list[BaseScene]:
    """The advertising image's base photographs: one Seedream scene per group of product
    photos (one group, or one per slide of the old gallery inside `STATIC_FLYER`), each
    with the background and then the brand references after the group's photos."""
    scenes: list[BaseScene] = []
    for index, group in enumerate(groups):
        # brand references come AFTER the existing references, preserving their indices
        references = [
            *group,
            *([background] if background is not None else []),
            *(img.image for img in brand_images),
        ]
        background_index = len(group) + 1 if background is not None else None
        prompt = ad_scene_prompt(
            brief=brief,
            kit=kit,
            brand=brand,
            mode=mode,
            products=len(group),
            has_background=background is not None,
            background_index=background_index if brand_refs.refs else None,
            brand_refs=brand_refs.refs,
            scene_plan=plans[index] if plans is not None else None,
        )
        image = scene_image(
            producer,
            tenant_id=tenant_id,
            draft_id=draft_id,
            brand_id=brief.brand_id,
            prompt=prompt,
            references=references,
            ratio=ratio,
            budget=budget,
            usage=usage,
            what=f"escena de la imagen publicitaria {index + 1}/{len(groups)}",
            reference_plan=_physical_scene_plan(plans[index], brand_refs.refs)
            if plans is not None
            else None,
        )
        stored = (
            keep_base(
                save,
                name=f"flyer-{index + 1}",
                image=image,
                prompt=prompt,
                usage=usage,
                compiler=brief.media.prompt_compiler_version,
            )
            if save is not None
            else None
        )
        scenes.append(BaseScene(image=image, prompt=prompt, stored=stored))
    return scenes


def carousel_slide_scene(
    producer: MediaProducer,
    *,
    tenant_id: UUID,
    draft_id: UUID,
    brief: ContentBrief,
    kit: BrandKit,
    brand: str,
    slide: CarouselSlide,
    number: int,
    total: int,
    ratio: str,
    has_product: bool,
    has_background: bool,
    plan: SceneReferencePlan | None,
    references: list[bytes],
    background_index: int | None,
    brand_refs: BrandReferencesSet,
    hook: str,
    cta: str,
    animated: bool,
    budget: BudgetContext,
    usage: list[MediaUsage],
    save: _Saver | None = None,
) -> BaseScene:
    """One gallery slide's base photograph (a generated slide, or an animated slide's
    first frame), compiled under the gallery's own compiler."""
    media = brief.media
    prompt = carousel_scene_prompt(
        brief=brief,
        kit=kit,
        brand=brand,
        scene=slide.scene_prompt,
        ratio=ratio,
        has_product=has_product,
        product_role=(
            media.product_image_roles[slide.product_index]
            if media.brand_application_version
            and slide.product_index is not None
            and slide.product_index < len(media.product_image_roles)
            else "product"
        ),
        has_background=has_background,
        has_text=bool(hook or cta),
        background_index=background_index if brand_refs.refs else None,
        brand_refs=brand_refs.refs,
        scene_plan=plan,
        hook=bool(hook),
        cta=bool(cta),
        slide_number=number,
        slides=total,
        animated=animated,
    )
    image = scene_image(
        producer,
        tenant_id=tenant_id,
        draft_id=draft_id,
        brand_id=brief.brand_id,
        prompt=prompt,
        references=references,
        ratio=ratio,
        budget=budget,
        usage=usage,
        what=f"escena de la diapositiva {number}/{total}",
        reference_plan=_physical_scene_plan(plan, brand_refs.refs) if plan is not None else None,
        fill_bands=media.prompt_compiler_version >= 3,
    )
    # an animated slide's frame is not a base: it is kept for its own resume, as before
    stored = (
        keep_base(
            save,
            name=f"slide-{number}",
            image=image,
            prompt=prompt,
            usage=usage,
            compiler=media.prompt_compiler_version,
        )
        if save is not None and not animated
        else None
    )
    return BaseScene(image=image, prompt=prompt, stored=stored)
