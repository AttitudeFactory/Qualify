"""Reference coverage/identity/output plans are pure and never create media."""

import socket

import pytest
from qualify_creative.enums import AdImageMode, SlideSource
from qualify_creative.scene_plan import (
    ScenePlanError,
    ad_mode_for,
    carousel_scene_plans,
    flyer_scene_plans,
    validate_scene_capacity,
)
from qualify_creative.schemas import CarouselSlide, MediaInputs


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network is forbidden in scene-plan tests")

    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket, "create_connection", fail)


def test_ten_selected_photos_produce_ten_outputs_without_dropping_the_last() -> None:
    media = MediaInputs(product_keys=tuple(f"photo{i}.jpg" for i in range(10)), carousel=True)
    plans = flyer_scene_plans(media, AdImageMode.PRODUCT)
    assert len(plans) == 10
    assert [plan.target_index for plan in plans] == list(range(10))
    assert plans[-1].photo_keys == ("photo9.jpg",)


def test_each_flyer_target_keeps_global_index_role_and_shared_guide() -> None:
    media = MediaInputs(
        product_keys=("guide.jpg", "burger.jpg", "drink.jpg"),
        carousel=True,
        product_image_roles=("composition", "product", "product"),
    )
    plans = flyer_scene_plans(media, AdImageMode.PRODUCT)
    assert len(plans) == 2
    assert [plan.target_index for plan in plans] == [1, 2]
    assert [plan.global_indices for plan in plans] == [(1, 0), (2, 0)]
    assert all(plan.photo_roles == ("product", "composition") for plan in plans)


def test_single_flyer_carries_every_photo_and_background() -> None:
    media = MediaInputs(
        product_keys=("a.jpg", "guide.jpg"),
        background_key="place.jpg",
        product_image_roles=("product", "composition"),
    )
    plan = flyer_scene_plans(media, AdImageMode.BOTH)[0]
    assert plan.global_indices == (0, 1)
    assert plan.background_number == 3 and plan.brand_start_number == 4
    assert plan.numbers_for("composition") == (2,)


def test_guide_target_travels_with_unique_product_identity_without_changing_target() -> None:
    media = MediaInputs(
        product_keys=("guide.jpg", "burger.jpg"),
        product_image_roles=("composition", "product"),
        slides=(CarouselSlide(source=SlideSource.GENERATED, product_index=0),),
    )
    plan = carousel_scene_plans(media)[0]
    assert plan.target_index == 0 and plan.global_indices == (1, 0)
    assert plan.photo_roles == ("product", "composition")


def test_product_targets_never_receive_other_products_as_their_identity() -> None:
    media = MediaInputs(
        product_keys=("guide.jpg", "burger.jpg", "drink.jpg"),
        product_image_roles=("composition", "product", "product"),
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, product_index=0, guide_product_index=1),
            CarouselSlide(source=SlideSource.GENERATED, product_index=1),
            CarouselSlide(source=SlideSource.ANIMATED, product_index=2),
        ),
    )
    plans = carousel_scene_plans(media)
    assert [plan.global_indices for plan in plans[1:]] == [(1,), (2,)]


def test_a_gallery_guide_guides_only_its_own_slide() -> None:
    """Live test 2026-11-03 (draft 320257e3): slide 1's inspiration guide reached slides
    2 and 3 too — 4 references per scene, and Seedream cut slide 3 at ~60 s. Each guide
    now goes with its own slide only; two guides never mix."""
    media = MediaInputs(
        product_keys=("guide-a.jpg", "burger.jpg", "guide-b.jpg", "drink.jpg"),
        product_image_roles=("composition", "product", "composition", "product"),
        background_key="place.jpg",
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, product_index=0, guide_product_index=1),
            CarouselSlide(source=SlideSource.GENERATED, product_index=1),
            CarouselSlide(source=SlideSource.ANIMATED, product_index=2, guide_product_index=3),
            CarouselSlide(source=SlideSource.GENERATED, product_index=3),
        ),
    )
    plans = carousel_scene_plans(media)
    assert [plan.global_indices for plan in plans] == [(1, 0), (1,), (3, 2), (3,)]
    assert [plan.photo_roles for plan in plans] == [
        ("product", "composition"),
        ("product",),
        ("product", "composition"),
        ("product",),
    ]
    assert plans[1].image_count == 2  # its photo and the place, never slide 1's guide


def test_a_gallery_guide_without_a_slide_of_its_own_is_refused() -> None:
    """A guide reaches a scene only through its own slide: one no slide uses is an
    unused photo, refused before anything is paid (it no longer rides on the others)."""
    media = MediaInputs(
        product_keys=("guide.jpg", "burger.jpg"),
        product_image_roles=("composition", "product"),
        slides=(CarouselSlide(source=SlideSource.GENERATED, product_index=1),),
    )
    with pytest.raises(ScenePlanError, match="no aparecen en ninguna diapositiva"):
        carousel_scene_plans(media)


def test_ambiguous_guide_target_is_rejected_instead_of_picking_a_different_product() -> None:
    media = MediaInputs(
        product_keys=("guide.jpg", "burger.jpg", "drink.jpg"),
        product_image_roles=("composition", "product", "product"),
        slides=(CarouselSlide(source=SlideSource.GENERATED, product_index=0),),
    )
    with pytest.raises(ScenePlanError, match="varias fotos de producto"):
        carousel_scene_plans(media)


def test_the_owners_product_choice_resolves_a_guide_among_several_products() -> None:
    """Live test 2026-11-03: slide 1 an inspiration guide, slides 2 and 3 two catalog
    photos — the guide slide shows the product the owner picked for it."""
    media = MediaInputs(
        product_keys=("guide.jpg", "burger.jpg", "drink.jpg"),
        product_image_roles=("composition", "product", "product"),
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, product_index=0, guide_product_index=2),
            CarouselSlide(source=SlideSource.GENERATED, product_index=1),
            CarouselSlide(source=SlideSource.GENERATED, product_index=2),
        ),
    )
    plans = carousel_scene_plans(media)
    assert plans[0].target_index == 0
    assert plans[0].global_indices == (2, 0)
    assert plans[0].photo_roles == ("product", "composition")
    assert [plan.global_indices for plan in plans[1:]] == [(1,), (2,)]  # the guide is slide 1's


def test_a_guide_choice_must_be_a_product_photo() -> None:
    media = MediaInputs(
        product_keys=("guide.jpg", "other-guide.jpg", "burger.jpg"),
        product_image_roles=("composition", "composition", "product"),
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, product_index=0, guide_product_index=1),
            CarouselSlide(source=SlideSource.GENERATED, product_index=2),
        ),
    )
    with pytest.raises(ScenePlanError, match="ya no está"):
        carousel_scene_plans(media)


def test_an_animated_guide_slide_works_like_an_image_one() -> None:
    """Founder 2026-11-03: «Video animado» with (a) a guide and a chosen product, or (b)
    only a guide — with one product photo in the piece, that one; with several, the
    owner's choice."""
    one = MediaInputs(
        product_keys=("t/x/stock/pixabay/1/g.jpg", "uploads/t/a.jpg"),
        slides=(
            CarouselSlide(source=SlideSource.ANIMATED, product_index=0),
            CarouselSlide(source=SlideSource.GENERATED, product_index=1),
        ),
    )
    assert carousel_scene_plans(one)[0].global_indices == (1, 0)
    several = MediaInputs(
        product_keys=("t/x/stock/pixabay/1/g.jpg", "uploads/t/a.jpg", "uploads/t/b.jpg"),
        slides=(
            CarouselSlide(source=SlideSource.ANIMATED, product_index=0, guide_product_index=1),
            CarouselSlide(source=SlideSource.GENERATED, product_index=1),
            CarouselSlide(source=SlideSource.GENERATED, product_index=2),
        ),
    )
    assert carousel_scene_plans(several)[0].global_indices == (1, 0)


@pytest.mark.parametrize(
    "key",
    [
        "uploads/t/foto.jpg",  # «Subir»
        "t/x/catalog/p/1.jpg",  # the catalog
        "t/x/generated/d/r1/a.png",  # «Publicaciones»
    ],
)
def test_only_stock_keys_default_to_a_guide(key: str) -> None:
    """Uploaded, catalog and pieces' photos are product identities (role «product»);
    only an inspiration (`/stock/`) key defaults to «composition»."""
    from qualify_creative.scene_plan import product_photos

    media = MediaInputs(product_keys=(key, "t/x/stock/pixabay/1/g.jpg"))
    assert [p.role for p in product_photos(media)] == ["product", "composition"]
    two = MediaInputs(
        product_keys=(key, "uploads/t/b.jpg"),
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, product_index=0),
            CarouselSlide(source=SlideSource.ANIMATED, product_index=1),
        ),
    )
    assert [plan.global_indices for plan in carousel_scene_plans(two)] == [(0,), (1,)]


def test_a_choice_on_a_product_target_changes_nothing() -> None:
    media = MediaInputs(
        product_keys=("burger.jpg", "drink.jpg"),
        product_image_roles=("product", "product"),
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, product_index=0, guide_product_index=1),
            CarouselSlide(source=SlideSource.GENERATED, product_index=1),
        ),
    )
    assert carousel_scene_plans(media)[0].global_indices == (0,)


@pytest.mark.parametrize("unused", ["photo", "background"])
def test_selected_inputs_without_a_consuming_scene_fail_early(unused: str) -> None:
    media = MediaInputs(
        product_keys=("burger.jpg", "drink.jpg") if unused == "photo" else (),
        background_key="place.jpg" if unused == "background" else None,
        slides=(
            CarouselSlide(
                source=SlideSource.GENERATED,
                product_index=0 if unused == "photo" else None,
                use_background=False,
            ),
        ),
    )
    with pytest.raises(ScenePlanError):
        carousel_scene_plans(media)


def test_capacity_includes_actual_photos_guides_background_brand_and_character() -> None:
    media = MediaInputs(
        product_keys=("burger.jpg", "guide.jpg"),
        background_key="place.jpg",
        product_image_roles=("product", "composition"),
    )
    plan = flyer_scene_plans(media, AdImageMode.BOTH)[0]
    validate_scene_capacity(plan, brand_images=2, prefix_images=1, maximum=6)
    with pytest.raises(ScenePlanError, match=r"\(6 de 5\)"):
        validate_scene_capacity(plan, brand_images=2, prefix_images=1, maximum=5)


@pytest.mark.parametrize("mode", [AdImageMode.BACKGROUND, AdImageMode.PRODUCT])
def test_mode_cannot_silently_ignore_selected_product_or_background(mode: AdImageMode) -> None:
    media = MediaInputs(product_keys=("burger.jpg",), background_key="place.jpg")
    with pytest.raises(ScenePlanError):
        flyer_scene_plans(media, mode)


def test_v9_price_uses_same_output_plan_while_legacy_keeps_photo_count():
    from qualify_creative.creations import weight_for, weight_for_request
    from qualify_creative.enums import ContentKind

    from .test_creative_media_byteplus import _brief

    brief = _brief(
        ContentKind.STATIC_FLYER,
        carousel=True,
        product_keys=("guide.jpg", "burger.jpg", "drink.jpg"),
        product_image_roles=("composition", "product", "product"),
        brand_application_version=2,
    )
    plans = flyer_scene_plans(brief.media, ad_mode_for(brief.media))
    assert len(plans) == 2
    assert weight_for(brief) == weight_for_request(brief.kind.value, carousel_images=len(plans))
    old = brief.model_copy(
        update={"media": brief.media.model_copy(update={"brand_application_version": 1})}
    )
    assert weight_for(old) == weight_for_request(brief.kind.value, carousel_images=3)
