"""Stage `compose` of the image and carousel pipeline (ADR 49 §2.3): the finished stills.

In: the base photographs of stage `base` (`BaseScene`), the copy and the brand's text
style. Out: the `MediaWrite`s of the piece — `slide-N.jpg`, JPEG, the format's exact size,
positions 0..N-1 — that `MediaProducer` returns for `image_assets`.

- `ad_image` — `ContentKind.STATIC_FLYER` with Seedream wired: the scenes, with the hook
  and the real logo set on top (`qualify_creative.compose.render_ad_slides`); a 9:16 Reel
  gets the composed still pushed in (`MediaProducer._ad_reel`, a video path that stays in
  `media.py`).
- `carousel` — `ContentKind.CAROUSEL`: the operator's slides in order, then the closing
  slide. Slides that are not a generated still — an existing piece, a Galería medium, a
  stock video, an animated slide — are made by the producer's own methods, which stay in
  `media.py` with the video code they share. The resume of a half-finished gallery
  («Crear las que faltan»: `kept_slides`, `_resumed_gallery_slides`, `_keep_made`) is the
  same as before m-25017278.

Composition is still Pillow's here, exactly as before: replacing it with Remotion is
m-25017285 / m-25017293, not this move.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any
from uuid import UUID

from qualify_creative.compose import (
    FlyerText,
    TextStyle,
    render_ad_slides,
    render_carousel_slide,
    render_closing_slide,
    text_layer,
)
from qualify_creative.enums import (
    AdImageMode,
    ContentFormat,
    FailureReason,
    SlideSource,
    SlideText,
)
from qualify_creative.photo.normalize import to_meta_jpeg
from qualify_creative.router import BudgetContext
from qualify_creative.scene_plan import carousel_scene_plans, flyer_scene_plans
from qualify_creative.schemas import BrandKit, ContentBrief, CopyPayload

from qualify_api.creative.brand_references import BrandReferencesSet
from qualify_api.creative.image_pipeline.base import carousel_slide_scene, flyer_scenes
from qualify_api.creative.media import (
    _TASK_RUN,
    COMPOSE_MODEL,
    GALLERY_CONTEXT,
    JPEG,
    SEEDANCE,
    SEEDANCE_RATIOS,
    SEEDREAM,
    MediaUsage,
    MediaWrite,
    _keep_made,
    _media_write_json,
    _MediaFailed,
    _MediaPending,
    _physical_scene_plan,
    _printed_words,
    _resumed_gallery_slides,
    _resumed_scene_key,
    _Saver,
)
from qualify_api.creative.pipeline import current_preparation
from qualify_api.creative.queue_dispatch import CheckpointError, GenerationDeferred

if TYPE_CHECKING:
    from qualify_api.creative.media import MediaProducer


def ad_image(
    producer: MediaProducer,
    tenant_id: UUID,
    draft_id: UUID,
    brief: ContentBrief,
    kit: BrandKit,
    copy: CopyPayload,
    budget: BudgetContext,
    usage: list[MediaUsage],
    save: _Saver,
    style: TextStyle,
    brand_refs: BrandReferencesSet,
) -> list[MediaWrite]:
    """The advertising image: Seedream generates the photograph with the operator's
    own product and/or background as references (one per carousel slide) — or from
    the described scene alone when they uploaded none (§ 2026-10-12) — and the
    words and the real logo are set on top locally."""
    media = brief.media
    mode = media.ad_mode or (
        AdImageMode.BOTH
        if media.product_keys and media.background_key
        else AdImageMode.BACKGROUND
        if media.background_key
        else AdImageMode.PRODUCT
        if media.product_keys
        else AdImageMode.SCENE
    )
    current = media.brand_application_version >= 2 or brand_refs.block_version >= 9
    plans = flyer_scene_plans(media, mode) if current else None
    if plans is not None and brief.format is ContentFormat.REELS_9_16 and len(plans) != 1:
        raise _MediaFailed(
            FailureReason.INVALID_PARAMETERS.value,
            "Este video admite una sola escena. Usa un carrusel para tus fotos.",
        )
    products = producer._products(brief) if mode.needs_product or current else []
    background = producer._read(media.background_key) if mode.needs_background else None
    ratio = brief.format.aspect_ratio
    brand = producer._brand_name(tenant_id, brief.brand_id)
    brand_images = producer._brand_reference_images(brand_refs)
    # one scene with every product, or — a carousel — one scene per product
    groups = (
        [[products[photo.global_index] for photo in plan.photos] for plan in plans]
        if plans is not None
        else [[p] for p in products[:9]]
        if media.carousel and products
        else [products]
    )
    based = flyer_scenes(
        producer,
        tenant_id=tenant_id,
        draft_id=draft_id,
        brief=brief,
        kit=kit,
        brand=brand,
        mode=mode,
        groups=groups,
        plans=plans,
        background=background,
        brand_images=brand_images,
        brand_refs=brand_refs,
        ratio=ratio,
        budget=budget,
        usage=usage,
    )
    scenes = [scene.image for scene in based]
    scene_prompts = [scene.prompt for scene in based]
    slides = render_ad_slides(
        scenes=scenes,
        text=FlyerText(hook=copy.hook, cta=copy.cta, price=media.price_line),
        palette=kit.palette_rgb,
        logo=producer._logo(kit, media.brand_logo_key),
        carousel=media.carousel,
        size=brief.format.dimensions,
        style=style,
    )
    width, height = brief.format.dimensions
    model_id = usage[-1].model_id if usage else SEEDREAM
    if brief.format is ContentFormat.REELS_9_16:
        # § 2026-10-13: Instagram publishes only a video as a Reel — the composed
        # image (words and logo on it) gets a slow push-in; nothing is generated twice
        return [
            producer._ad_reel(
                slides[0],
                brief=brief,
                model_id=model_id,
                params={
                    "ad_mode": mode.value,
                    "scene_prompt": media.scene_prompt,
                    "generation_prompts": scene_prompts,
                    "scene_reference_plans": [p.provenance() for p in plans] if plans else [],
                    "planned_output_count": len(plans) if plans else len(groups),
                    "generated_scenes": len(scenes),
                    "products": len(products),
                    "background": background is not None,
                    "printed": _printed_words(hook=copy.hook),
                },
                save=save,
            )
        ]
    out: list[MediaWrite] = []
    for position, png in enumerate(slides):
        key = save(f"slide-{position + 1}.jpg", to_meta_jpeg(png), JPEG)
        out.append(
            MediaWrite(
                position=position,
                media_type="image",
                media_url=key,
                object_key=key,
                width=width,
                height=height,
                aspect_ratio=brief.format.aspect_ratio,
                model_id=model_id,
                provider=SEEDREAM,
                content_type=JPEG,
                ai_generated=True,
                params={
                    "ad_mode": mode.value,
                    "scene_prompt": media.scene_prompt,
                    "generation_prompts": scene_prompts,
                    "scene_reference_plans": [p.provenance() for p in plans] if plans else [],
                    "planned_output_count": len(plans) if plans else len(groups),
                    "carousel": media.carousel,
                    "slides": len(slides),
                    "generated_scenes": len(scenes),
                    "products": len(products),
                    "background": background is not None,
                    "printed": _printed_words(
                        hook=copy.hook if position == 0 else "",
                        # a gallery's closing slide prints `cta or hook` centred
                        cta=(copy.cta or copy.hook)
                        if media.carousel and position == len(slides) - 1
                        else "",
                    ),
                },
            )
        )
    return out


def carousel(
    producer: MediaProducer,
    tenant_id: UUID,
    draft_id: UUID,
    brief: ContentBrief,
    kit: BrandKit,
    copy: CopyPayload,
    budget: BudgetContext,
    usage: list[MediaUsage],
    save: _Saver,
    style: TextStyle,
    brand_refs: BrandReferencesSet,
    kept_slides: Mapping[int, MediaWrite] | None = None,
) -> list[MediaWrite]:
    """The operator's slides in order, then the closing slide when asked for. Every
    slide is fitted to the format's exact size: Instagram crops a carousel to its
    first item, and a reused Reel or a Seedance 3:4 would otherwise be cut there.

    m-24820842 (live test 2026-11-03, draft 320257e3): `kept_slides` are generated
    or animated slides an earlier, failed attempt of this gallery already made and
    paid for (by position) — reused as they are, never asked of a vendor again. When
    a slide fails, the slides made so far ride on the exception (`_keep_made`) so
    the failed outcome still carries them."""
    kept = dict(kept_slides or {})
    # m-24820842 (draft 9968b10c, 2026-11-03): a run resuming this revision's vendor
    # task reuses the slides the earlier run finished before it (kept with the task)
    # and the Seedance slots they took — never asked of a vendor, nor saved, again
    run = _TASK_RUN.get() if current_preparation() is None else None
    resumed, resumed_slots = _resumed_gallery_slides(run)
    kept.update(resumed)
    slots_taken: dict[int, int] = {}
    media = brief.media
    current = media.brand_application_version >= 2 or brand_refs.block_version >= 9
    scene_plans = {p.output_index: p for p in carousel_scene_plans(media)} if current else {}
    size = brief.format.dimensions
    total = len(media.slides) + int(media.closing_slide)
    products = producer._products(brief)
    background = producer._read(media.background_key)
    logo = producer._logo(kit, media.brand_logo_key)
    brand = producer._brand_name(tenant_id, brief.brand_id)
    # every reused piece is resolved BEFORE the first paid call (PR #100 review): a
    # piece gone from slide 4 must not cost slides 1-3 first
    pieces = producer._existing_pieces(tenant_id, brief)
    # the same for every stock video: read up front, before anything is paid
    stock_videos = producer._stock_videos(brief)
    # CM-6: and every Galería medium — still live and this brand's — before any slide
    gallery = producer._gallery_media(tenant_id, brief)
    brand_images = producer._brand_reference_images(brand_refs)
    out: list[MediaWrite] = []
    deferred = False
    scene_failure = None
    for position, slide in enumerate(media.slides):
        number = position + 1
        reused = kept.get(position)
        if reused is not None:
            # made and paid by an earlier attempt of this gallery: never again
            out.append(reused)
            if run is not None:
                for _ in range(resumed_slots.get(position, 0)):
                    run.next_slot(SEEDANCE)
            slots_taken[position] = resumed_slots.get(position, 0)
            continue
        try:
            if slide.source is SlideSource.EXISTING:
                out.append(producer._existing_slide(brief, pieces[position], position, save))
                continue
            if slide.source is SlideSource.GALLERY:
                out.append(producer._gallery_slide(brief, slide, gallery[position], position, save))
                continue
            if slide.source is SlideSource.STOCK:
                out.append(
                    producer._stock_slide(
                        brief,
                        kit,
                        copy,
                        slide,
                        stock_videos[position],
                        position,
                        logo,
                        save,
                        style,
                    )
                )
                continue
            hook = copy.hook if slide.text is SlideText.HOOK else ""
            cta = copy.cta if slide.text is SlideText.CTA else ""
            product = products[slide.product_index] if slide.product_index is not None else None
            place = background if slide.use_background else None
            animated = slide.source is SlideSource.ANIMATED
            # a video's first frame is drawn at the ratio Seedance renders (it has no 4:5)
            ratio = SEEDANCE_RATIOS[brief.format] if animated else brief.format.aspect_ratio
            plan = scene_plans.get(position)
            base = (
                [
                    *(products[p.global_index] for p in plan.photos),
                    *([place] if place is not None else []),
                ]
                if plan is not None
                else [image for image in (product, place) if image is not None]
            )
            # m-24820842: brand references appended AFTER the existing references
            references = [*base, *(img.image for img in brand_images)]
            if plan is not None:
                background_index = plan.background_number
            elif place is not None and product is not None:
                background_index = 2
            elif place is not None:
                background_index = 1
            else:
                background_index = None
            resumed_scene = (
                _resumed_scene_key(run, position) if animated and run is not None else None
            )
            scene = (
                producer._store.read(resumed_scene)
                if resumed_scene
                else carousel_slide_scene(
                    producer,
                    tenant_id=tenant_id,
                    draft_id=draft_id,
                    brief=brief,
                    kit=kit,
                    brand=brand,
                    slide=slide,
                    number=number,
                    total=total,
                    ratio=ratio,
                    has_product=product is not None,
                    has_background=place is not None,
                    plan=plan,
                    references=references,
                    background_index=background_index,
                    brand_refs=brand_refs,
                    hook=hook,
                    cta=cta,
                    animated=animated,
                    budget=budget,
                    usage=usage,
                ).image
            )
            still = render_carousel_slide(
                scene=scene,
                hook=hook,
                cta=cta,
                palette=kit.palette_rgb,
                logo=logo,
                size=size,
                style=style,
            )
            params: dict[str, Any] = {
                "slide": number,
                "slides": total,
                "source": slide.source.value,
                "text": slide.text.value,
                "printed": _printed_words(hook=hook, cta=cta),
                "scene_prompt": slide.scene_prompt,
                # m-24820842: provenance, and what «Crear las que faltan» compiles
                # the missing slides with (the gallery's own compiler, not today's)
                "prompt_compiler_version": brief.media.prompt_compiler_version,
                **(
                    {"reference_plan": _physical_scene_plan(plan, brand_refs.refs)}
                    if plan is not None
                    else {}
                ),
            }
            if not animated:
                key = save(f"slide-{number}.jpg", to_meta_jpeg(still), JPEG)
                out.append(
                    MediaWrite(
                        position=position,
                        media_type="image",
                        media_url=key,
                        object_key=key,
                        width=size[0],
                        height=size[1],
                        aspect_ratio=brief.format.aspect_ratio,
                        model_id=usage[-1].model_id,
                        provider=SEEDREAM,
                        content_type=JPEG,
                        ai_generated=True,
                        params=params,
                    )
                )
                continue
            overlay = (
                text_layer(
                    size=size,
                    hook=hook,
                    cta=cta,
                    palette=kit.palette_rgb,
                    logo=logo,
                    style=style,
                )
                if hook or cta or (current and logo is not None)
                else None
            )
            if run is not None and not resumed_scene:
                # what a resumed run needs to land this slide's video without paying
                # its scene, nor the slides before it, again (draft 9968b10c)
                scene_key = save(f"slide-{number}-scene.jpg", to_meta_jpeg(scene), JPEG)
                run.shared[GALLERY_CONTEXT] = {
                    "position": position,
                    "scene_key": scene_key,
                    "slides": [
                        _media_write_json(made, slots_taken.get(made.position, 0)) for made in out
                    ],
                }
            calls_before = run.calls.get(SEEDANCE, 0) if run is not None else 0
            try:
                out.append(
                    producer._animated_slide(
                        tenant_id=tenant_id,
                        draft_id=draft_id,
                        brief=brief,
                        scene=scene,
                        still=still,
                        kit=kit,
                        overlay=overlay,
                        seconds=slide.seconds,
                        reference_video_key=slide.reference_video_key,
                        audio=slide.audio,
                        position=position,
                        total=total,
                        params=params,
                        budget=budget,
                        usage=usage,
                        save=save,
                        brand_refs=brand_refs,
                    )
                )
            except GenerationDeferred:
                deferred = True
            except _MediaFailed as exc:
                exc.detail = f"Diapositiva {number}: {exc.detail}"
                scene_failure = scene_failure or exc
            finally:
                if run is not None:
                    slots_taken[position] = run.calls.get(SEEDANCE, 0) - calls_before
                    run.shared.pop(GALLERY_CONTEXT, None)
        except (GenerationDeferred, _MediaPending, CheckpointError):
            raise
        except Exception as exc:
            _keep_made(exc, number, out)
            raise
    if media.closing_slide:
        closing = render_closing_slide(
            line=copy.cta or copy.hook,
            palette=kit.palette_rgb,
            logo=logo,
            size=size,
            style=style,
        )
        key = save(f"slide-{total}.jpg", to_meta_jpeg(closing), JPEG)
        out.append(
            MediaWrite(
                position=total - 1,
                media_type="image",
                media_url=key,
                object_key=key,
                width=size[0],
                height=size[1],
                aspect_ratio=brief.format.aspect_ratio,
                model_id=COMPOSE_MODEL,
                provider="qualify",
                content_type=JPEG,
                params={
                    "slide": total,
                    "slides": total,
                    "source": "closing",
                    "printed": _printed_words(cta=copy.cta or copy.hook),
                },
            )
        )
    if deferred:
        raise GenerationDeferred()
    if scene_failure is not None:
        _keep_made(scene_failure, None, out)
        raise scene_failure
    return out
