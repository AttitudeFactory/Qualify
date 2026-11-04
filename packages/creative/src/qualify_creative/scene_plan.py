"""Pure reference/output planning for new versioned creative consumers.

No IO, provider, renderer or image processing belongs here. Preflight, request builders
and output/cost estimates consume this same plan instead of slicing photos separately.
"""

from __future__ import annotations

from dataclasses import dataclass

from qualify_creative.enums import AdImageMode, SlideSource
from qualify_creative.schemas import MediaInputs


class ScenePlanError(ValueError):
    """The chosen inputs cannot all be used without changing the operator's target."""


@dataclass(frozen=True)
class ScenePhoto:
    global_index: int
    key: str
    role: str


@dataclass(frozen=True)
class SceneReferencePlan:
    output_index: int
    target_index: int | None
    photos: tuple[ScenePhoto, ...]
    background_key: str | None = None

    @property
    def photo_keys(self) -> tuple[str, ...]:
        return tuple(photo.key for photo in self.photos)

    @property
    def photo_roles(self) -> tuple[str, ...]:
        return tuple(photo.role for photo in self.photos)

    @property
    def global_indices(self) -> tuple[int, ...]:
        return tuple(photo.global_index for photo in self.photos)

    @property
    def image_count(self) -> int:
        return len(self.photos) + int(bool(self.background_key))

    @property
    def background_number(self) -> int | None:
        return len(self.photos) + 1 if self.background_key else None

    @property
    def brand_start_number(self) -> int:
        return self.image_count + 1

    def provenance(self) -> dict[str, object]:
        return {
            "version": 1,
            "output_index": self.output_index,
            "target_photo_index": self.target_index,
            "photo_indices": list(self.global_indices),
            "photo_keys": list(self.photo_keys),
            "photo_roles": list(self.photo_roles),
            "background_key": self.background_key,
            "background_number": self.background_number,
            "brand_start_number": self.brand_start_number,
        }

    def numbers_for(self, role: str, *, start: int = 1) -> tuple[int, ...]:
        return tuple(start + i for i, photo in enumerate(self.photos) if photo.role == role)


def product_photos(media: MediaInputs) -> tuple[ScenePhoto, ...]:
    roles = media.product_image_roles
    if roles and (
        len(roles) != len(media.product_keys)
        or any(role not in {"product", "composition"} for role in roles)
    ):
        raise ScenePlanError(
            "Cambiaste tus fotos mientras preparábamos la pieza. Revísalas y toca «Crear» otra vez."
        )
    return tuple(
        ScenePhoto(i, key, roles[i] if roles else "composition" if "/stock/" in key else "product")
        for i, key in enumerate(media.product_keys)
    )


def _target_photos(
    photos: tuple[ScenePhoto, ...],
    target: int,
    product: int | None = None,
    *,
    shared_guides: bool = True,
) -> tuple[ScenePhoto, ...]:
    """The photos one output is generated from. `product`: the identity the owner chose
    for a GUIDE target (`CarouselSlide.guide_product_index`); None keeps the rule every
    earlier brief was planned with.

    `shared_guides`: every composition guide travels with every output — a flyer
    gallery, where a guide has no output of its own and so guides them all. A
    «Galería» (`carousel_scene_plans`) passes False: each guide is a slide of its own
    and guides ONLY that slide (live test 2026-11-03, draft 320257e3: slide 1's guide
    went to slides 2 and 3 too — 4 references per scene and a Seedream cut at ~60 s)."""
    if not 0 <= target < len(photos):
        raise ScenePlanError("Una diapositiva apunta a una foto que ya no está. Vuelve a elegirla.")
    selected = photos[target]
    guides = (
        tuple(photo for photo in photos if photo.role == "composition")
        if shared_guides
        else ((selected,) if selected.role == "composition" else ())
    )
    identities = tuple(photo for photo in photos if photo.role == "product")
    if selected.role == "product":
        return (selected, *guides)
    if product is not None:
        if not 0 <= product < len(photos) or photos[product].role != "product":
            raise ScenePlanError(
                "La foto del producto que elegiste para esa diapositiva ya no está. "
                "Vuelve a elegirla."
            )
        return (photos[product], *guides)
    if len(identities) > 1:
        raise ScenePlanError(
            "Esta guía tiene varias fotos de producto posibles. "
            "Elige la foto del producto que debe aparecer en esa diapositiva."
        )
    # A guide cannot masquerade as the real product. When an identity exists, it
    # travels alongside the guide. Multiple identities require an explicit target.
    return (*identities, *guides)


def ad_mode_for(media: MediaInputs) -> AdImageMode:
    return media.ad_mode or (
        AdImageMode.BOTH
        if media.product_keys and media.background_key
        else AdImageMode.BACKGROUND
        if media.background_key
        else AdImageMode.PRODUCT
        if media.product_keys
        else AdImageMode.SCENE
    )


def flyer_scene_plans(media: MediaInputs, mode: AdImageMode) -> tuple[SceneReferencePlan, ...]:
    photos = product_photos(media)
    identities = tuple(photo for photo in photos if photo.role == "product")
    if identities and not mode.needs_product:
        raise ScenePlanError(
            "Esta opción no usa fotos de producto. "
            "Quítalas o elige una opción que muestre tu producto."
        )
    if media.background_key and not mode.needs_background:
        raise ScenePlanError("Esta opción no usa fondo. Quítalo o elige una opción con fondo.")
    background = media.background_key if mode.needs_background else None
    if media.carousel and identities:
        return tuple(
            SceneReferencePlan(
                i, photo.global_index, _target_photos(photos, photo.global_index), background
            )
            for i, photo in enumerate(identities)
        )
    return (SceneReferencePlan(0, None, photos, background),)


def flyer_output_count(media: MediaInputs) -> int:
    """Physical output count for a new creation/quote; never stamps a UI/client version."""
    return len(flyer_scene_plans(media, ad_mode_for(media)))


def carousel_scene_plans(media: MediaInputs) -> tuple[SceneReferencePlan, ...]:
    """One plan per generated/animated slide. A guide (inspiration photo) is its own
    slide and guides only that slide; a product slide is made from its own photo alone
    (founder, 2026-11-03)."""
    photos = product_photos(media)
    plans = []
    for i, slide in enumerate(media.slides):
        if slide.source not in {SlideSource.GENERATED, SlideSource.ANIMATED}:
            continue
        plans.append(
            SceneReferencePlan(
                i,
                slide.product_index,
                _target_photos(
                    photos, slide.product_index, slide.guide_product_index, shared_guides=False
                )
                if slide.product_index is not None
                else (),
                media.background_key if slide.use_background else None,
            )
        )
    used = {photo.global_index for plan in plans for photo in plan.photos}
    missing = set(range(len(photos))) - used
    if missing:
        numbers = ", ".join(str(i + 1) for i in sorted(missing))
        raise ScenePlanError(
            f"Las fotos {numbers} no aparecen en ninguna diapositiva. Ponlas en una o quítalas."
        )
    if media.background_key and not any(plan.background_key for plan in plans):
        raise ScenePlanError(
            "Ninguna escena usa el fondo que elegiste. Actívalo en una diapositiva generada "
            "o quítalo de la selección."
        )
    return tuple(plans)


def validate_scene_capacity(
    plan: SceneReferencePlan, *, brand_images: int, maximum: int, prefix_images: int = 0
) -> None:
    total = plan.image_count + brand_images + prefix_images
    if total > maximum:
        raise ScenePlanError(
            f"Elegiste más fotos de las que caben ({total} de {maximum}). "
            "Quita algunas o reparte tus fotos en dos publicaciones."
        )
