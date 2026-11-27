"""Catalog carousel ad (m-25113484): card rules, the Meta payload and the shared paused
preparation and activation, offline with the same doubles as the ad from a piece."""

from __future__ import annotations

import asyncio
import io
from dataclasses import replace
from uuid import uuid4

import pytest
from packages.api.tests.test_ad_unpublished import Client, Recipes, form
from PIL import Image
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore

from qualify_api.ads import unpublished_service as module
from qualify_api.ads.activation_repository import MemoryActivationRepository
from qualify_api.ads.carousel import (
    CAROUSEL_PIPELINE,
    CarouselCard,
    CarouselSource,
    carousel_payload,
)
from qualify_api.ads.enhancements import BrandEnhancementSettings
from qualify_api.ads.promotion_repository import MemoryPromotionRepository
from qualify_api.ads.promotions import AccountAccess
from qualify_api.ads.unpublished import ImageSelection, UnpublishedUnavailable
from qualify_api.ads.unpublished_service import (
    CarouselAdService,
    UnpublishedImageService,
    catalog_image_bytes,
)


def card(tenant, name="Shawarma mixto", price="$12.000", link="https://example.org/p"):
    photo = ImageSelection(
        uuid4(), f"t/{tenant}/uploads/catalog/{uuid4()}/photo.jpg", "image/jpeg", 30, 30
    )
    return CarouselCard(uuid4(), name, price, link, photo)


def source(count=3) -> CarouselSource:
    tenant = uuid4()
    return CarouselSource(
        tenant,
        uuid4(),
        uuid4(),
        uuid4(),
        2,
        "12",
        "42",
        "7",
        "COP",
        "America/Bogota",
        tuple(card(tenant, name=f"Producto {i}") for i in range(count)),
    )


class Store:
    def __init__(self):
        self.files = {}

    def read(self, key):
        return self.files[key]

    def write(self, key, data):
        self.files[key] = data


@pytest.mark.parametrize("count", [0, 1, 11])
def test_two_to_ten_cards_or_a_spanish_error(count):
    with pytest.raises(UnpublishedUnavailable, match="entre 2 y 10 productos"):
        source(count).snapshot()


def test_card_rules_before_meta():
    base = source(2)
    first, second = base.cards
    for cards, message in (
        ((first, replace(second, product_id=first.product_id)), "una sola vez"),
        ((first, replace(second, link_url="http://example.org")), "https://"),
        ((first, replace(second, price_label="")), "nombre y precio"),
        ((first, replace(second, name="x" * 120)), "muy largo"),
        (
            (first, replace(second, photo=replace(second.photo, content_type="image/webp"))),
            "JPG o PNG",
        ),
    ):
        with pytest.raises(UnpublishedUnavailable, match=message):
            replace(base, cards=cards).snapshot()
    assert base.snapshot()["pipeline"] == CAROUSEL_PIPELINE
    assert base.draft_id is None


def test_payload_keeps_order_price_links_and_only_server_hashes():
    selected = source(3)
    payload = carousel_payload(selected, form(), ("h1", "h2", "h3"))
    data = payload["object_story_spec"]["link_data"]
    assert payload["object_story_spec"]["page_id"] == "7"
    assert data["multi_share_optimized"] is False and data["multi_share_end_card"] is False
    assert [c["image_hash"] for c in data["child_attachments"]] == ["h1", "h2", "h3"]
    first = data["child_attachments"][0]
    assert first["name"] == "Producto 0 · $12.000" and first["description"] == "$12.000"
    assert first["link"] == first["call_to_action"]["value"]["link"] == "https://example.org/p"
    for hashes in (("h1", "h2"), ("h1", "h2", "not a hash!")):
        with pytest.raises(UnpublishedUnavailable):
            carousel_payload(selected, form(), hashes)


def test_photo_of_another_tenant_is_never_read():
    selected = source(2)
    store = Store()
    foreign = replace(selected.cards[0].photo, object_key=f"t/{uuid4()}/uploads/x/photo.jpg")
    store.files[foreign.object_key] = b"x"
    with pytest.raises(UnpublishedUnavailable):
        catalog_image_bytes(store, selected, foreign)


@pytest.fixture
def service(monkeypatch):
    selected, actor = source(3), uuid4()
    store = Store()
    for asset in selected.assets:
        data = io.BytesIO()
        Image.new("RGB", (asset.width, asset.height)).save(data, format="JPEG")
        store.files[asset.object_key] = data.getvalue()
    client = Client()
    obj = CarouselAdService(ObjectGate(MemoryObjectStore(locked=False)), store)
    obj.recipes, obj.promotions, obj.reviews = (
        Recipes(),
        MemoryPromotionRepository(),
        MemoryActivationRepository(),
    )
    loads = []

    def load(tenant, account, cards):
        loads.append(cards)
        return selected

    monkeypatch.setattr(module, "load_carousel_source", load)
    monkeypatch.setattr(module, "guard_source", lambda s: None)
    monkeypatch.setattr(module, "authorize_actor", lambda tenant, who: None)
    monkeypatch.setattr(
        module,
        "load_brand_enhancements",
        lambda **kw: BrandEnhancementSettings(selected.tenant_id, selected.brand_id),
    )
    calls = []

    async def account(s, a):
        calls.append(1)
        observed = client
        if len(calls) > 2:
            observed = Client()
            observed.objects = client.objects
        return AccountAccess(s.tenant_id, s.brand_id, s.meta_account_id, s.currency, observed)

    async def observe(*args):
        pass

    monkeypatch.setattr(obj, "_account", account)
    monkeypatch.setattr(obj, "_observe", observe)
    return obj, selected, actor, client, loads


async def prepare(obj, selected, actor, key, ad_form=None):
    return await obj.prepare(
        tenant_id=selected.tenant_id,
        ad_account_id=selected.account_id,
        products=tuple((c.product_id, "") for c in selected.cards),
        form=ad_form or form(),
        actor=actor,
        request_key=key,
        confirm_preparation=True,
    )


@pytest.mark.asyncio
async def test_carousel_is_prepared_paused_then_activated_once(service):
    obj, selected, actor, client, loads = service
    key, ad_form = uuid4(), form()
    preview = await prepare(obj, selected, actor, key, ad_form)
    # An empty card link takes the ad's link; the owner never passes keys or hashes.
    assert loads[0] == tuple((c.product_id, "https://example.org") for c in selected.cards)
    assert client.upload_calls == 3 and len(client.objects) == 4
    assert client.previews == ["INSTAGRAM_STANDARD"]
    assert preview.feed_html == "preview:INSTAGRAM_STANDARD" and preview.vertical_html == ""
    assert all(
        row.get("status") == "PAUSED"
        for row in client.objects.values()
        if row["_resource"] != "adcreatives"
    )
    promotion = obj.promotions.get(selected.tenant_id, preview.promotion_id)
    assert promotion.request["content_draft_id"] is None
    assert promotion.request["source_media_id"] == f"catalog-carousel:{preview.recipe_id}"
    assert promotion.request["targeting"]["instagram_positions"] == ["stream"]
    cards = promotion.request["creative"]["object_story_spec"]["link_data"]["child_attachments"]
    assert [c["image_hash"] for c in cards] == ["hash1", "hash2", "hash3"]
    review = obj.reviews.get(selected.tenant_id, preview.review_id)
    assert review.checks_snapshot["kind"] == "unpublished-carousel"

    # The same request again reuses the recorded uploads: nothing is sent twice.
    await prepare(obj, selected, actor, key, ad_form)
    assert client.upload_calls == 3

    result = await asyncio.wait_for(
        obj.confirm(
            tenant_id=selected.tenant_id,
            recipe_id=preview.recipe_id,
            review_id=preview.review_id,
            actor=actor,
            confirm_charge=True,
        ),
        3,
    )
    assert result == "active"
    # The write went through a later account client that shares the same Meta objects.
    assert all(
        client.objects[promotion.ids[k]]["status"] == "ACTIVE"
        for k in ("ads", "adsets", "campaigns")
    )


@pytest.mark.asyncio
async def test_piece_service_refuses_a_carousel_approval(service):
    obj, selected, actor, *_ = service
    preview = await prepare(obj, selected, actor, uuid4())
    piece = UnpublishedImageService(obj.gate)
    piece.recipes, piece.promotions, piece.reviews = obj.recipes, obj.promotions, obj.reviews
    with pytest.raises(UnpublishedUnavailable, match="cambió"):
        await piece.confirm(
            tenant_id=selected.tenant_id,
            recipe_id=preview.recipe_id,
            review_id=preview.review_id,
            actor=actor,
            confirm_charge=True,
        )
