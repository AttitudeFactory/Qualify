"""A carousel ad of Catálogo products in the promotion wizard (m-25113484)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from . import promotion_unpublished_provider as provider
from .ad_enhancements_vm import BrandEnhancementsVM
from .ad_health_vm import AccountHealthVM
from .catalog_vm import ProductVM
from .promotion_page import promotion_index
from .promotion_state import PromotionState
from .promotion_unpublished_ui import unpublished_products, unpublished_review
from .promotion_vm import (
    CAROUSEL_COUNT,
    CAROUSEL_FULL,
    CAROUSEL_STEPS,
    CarouselProductVM,
    PromotionDraftVM,
    PromotionSourceVM,
    carousel_choices,
    carousel_count_label,
    first_problem,
    step_keys,
    step_problem,
    toggle_carousel_product,
)
from .test_promotion_wizard import SOURCE, ZONE, ActionContext, valid_form

IDS = [str(uuid4()) for _ in range(11)]
PRODUCTS = [CarouselProductVM(i, f"Producto {n}", "$10.000", f"k{n}") for n, i in enumerate(IDS)]


def carousel_source() -> PromotionSourceVM:
    return PromotionSourceVM(
        str(SOURCE),
        "@negocio",
        "Texto de la pieza",
        media_kind="carousel",
        ad_account_id=str(uuid4()),
        products=PRODUCTS,
        default_message="Texto de la pieza",
        default_link_url="https://negocio.example",
        default_country="CO",
    )


def carousel_form(cards: int = 2) -> PromotionDraftVM:
    return replace(
        valid_form(),
        media_kind="carousel",
        product_ids=IDS[:cards],
        message="Texto",
        country="CO",
    )


def test_steps_ask_for_products_and_never_for_a_title() -> None:
    form = carousel_form()
    assert step_keys(form) == CAROUSEL_STEPS
    assert not first_problem(form, ZONE)  # no headline, no piece files: still complete
    for cards in (0, 1, 11):
        assert step_problem(carousel_form(cards), 2, ZONE) == CAROUSEL_COUNT
    assert first_problem(carousel_form(1), ZONE) == CAROUSEL_COUNT


def test_taps_keep_the_order_and_stop_at_ten() -> None:
    chosen = toggle_carousel_product(toggle_carousel_product([], IDS[3]), IDS[1])
    assert chosen == [IDS[3], IDS[1]]
    assert [row.order for row in carousel_choices(PRODUCTS[:4], chosen)] == [0, 2, 0, 1]
    assert toggle_carousel_product(chosen, IDS[3]) == [IDS[1]]
    assert toggle_carousel_product(IDS[:10], IDS[10]) == IDS[:10]


def test_counter_says_the_limit_and_when_it_is_full() -> None:
    assert carousel_count_label(0) == CAROUSEL_COUNT == "Elige de 2 a 10 productos de tu Catálogo."
    assert "al menos 1 más" in carousel_count_label(1)
    assert carousel_count_label(3) == "3 de 10 elegidos"
    assert carousel_count_label(10) == CAROUSEL_FULL


def test_eleventh_tap_sets_no_top_error_and_review_numbers_cards() -> None:
    context = ActionContext()
    context.sources = [carousel_source()]
    context.selected_source = context.sources[0]
    context.form = carousel_form(10)
    context.error = ""
    PromotionState.toggle_product.fn(context, IDS[10])
    assert context.form.product_ids == IDS[:10] and context.error == ""
    context.form = carousel_form(2)
    assert PromotionState.carousel_names.fget(context) == "1. Producto 0 · 2. Producto 1"


def test_toggle_event_only_accepts_the_brands_products() -> None:
    context = ActionContext()
    context.sources = [carousel_source()]
    context.selected_source = context.sources[0]
    context.form = carousel_form(0)
    PromotionState.toggle_product.fn(context, "not-a-product")
    assert context.form.product_ids == []
    PromotionState.toggle_product.fn(context, IDS[0])
    assert context.form.product_ids == [IDS[0]]
    assert not context.review.review_id  # a new card discards the prepared preview


class FakeCarouselService:
    calls: list[tuple[str, dict]] = []

    async def prepare(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(("prepare", kwargs))
        return SimpleNamespace(
            promotion_id=uuid4(),
            review_id=uuid4(),
            recipe_id=uuid4(),
            feed_html='<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?d=1">',
            vertical_html="",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def confirm(self, **kwargs: object) -> str:
        self.calls.append(("confirm", kwargs))
        return "active"


def test_provider_sends_products_in_order_to_the_carousel_service(monkeypatch) -> None:
    FakeCarouselService.calls = []
    kinds: list[bool] = []
    monkeypatch.setattr(
        provider, "_service", lambda carousel=False: kinds.append(carousel) or FakeCarouselService()
    )
    form = replace(carousel_form(3), product_ids=[IDS[2], IDS[0], IDS[1]])
    review = provider.prepare_unpublished(
        uuid4(), uuid4(), uuid4(), form, carousel_source(), ZONE, str(uuid4())
    )
    ((_, sent),) = FakeCarouselService.calls
    assert sent["products"] == tuple((UUID(i), "") for i in (IDS[2], IDS[0], IDS[1]))
    assert sent["form"].headline == "Producto 2"  # required, unused by Meta: first card
    assert sent["confirm_preparation"] is True
    assert review.preview_url and review.vertical_preview_url == ""
    provider.confirm_unpublished(uuid4(), uuid4(), review, True)
    assert kinds == [True, True] and FakeCarouselService.calls[-1][0] == "confirm"


def test_sources_offer_the_carousel_only_with_two_products(monkeypatch) -> None:
    piece = {"brand_id": uuid4(), "active_version_id": uuid4(), "ad_copy": None}
    account = {
        "id": uuid4(),
        "name": "Cuenta",
        "currency": "COP",
        "timezone_name": ZONE,
        "account_label": "@negocio",
    }
    image = {"content_type": "image/jpeg", "media_type": "image", "object_key": "k"}
    assets = [
        image | {"id": uuid4(), "width": 1080, "height": 1350},
        image | {"id": uuid4(), "width": 1080, "height": 1920},
    ]
    monkeypatch.setattr(provider, "_read", lambda *a: (piece, [account], assets))
    monkeypatch.setattr(provider, "load_policy", lambda *a: BrandEnhancementsVM())
    monkeypatch.setattr(provider, "account_health_for", lambda *a: AccountHealthVM())
    monkeypatch.setattr(provider, "issue_view_path", lambda *a: "")

    def product(name: str, photo: str, price: str) -> ProductVM:
        return ProductVM(str(uuid4()), name, "", "", price, "", "", "", photo, 1, 0, "")

    catalog = [product("Mixto", "a.jpg", "$1"), product("Sin foto", "", "$1")]
    monkeypatch.setattr(provider, "list_products", lambda *a: tuple(catalog))
    assert [row.media_kind for row in provider.unpublished_sources(uuid4(), uuid4())] == ["images"]
    catalog.append(product("Falafel", "b.jpg", "$2"))
    rows = provider.unpublished_sources(uuid4(), uuid4())
    assert [row.media_kind for row in rows] == ["images", "carousel"]
    assert [p.name for p in rows[1].products] == ["Mixto", "Falafel"]
    assert not rows[1].feed_media and not rows[1].vertical_media
    # a story never offers a carousel
    assert "carousel" not in [
        r.media_kind for r in provider.unpublished_sources(uuid4(), uuid4(), story=True)
    ]


def test_tree_has_the_picker_and_a_single_preview() -> None:
    picker = repr(unpublished_products().render())
    assert "Elige de 2 a 10" not in picker  # the counter is state, not a literal
    assert "checkbox" in picker and "orden en que quieres" in picker
    review = repr(unpublished_review().render())
    assert "En el inicio de Instagram" in review and "Productos, en este orden" in review
    assert "Varios productos (carrusel)" in repr(promotion_index().render())


@pytest.mark.parametrize("cards", [2, 10])
def test_limits_are_inclusive(cards: int) -> None:
    assert not step_problem(carousel_form(cards), 2, ZONE)
