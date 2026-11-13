"""Actual service orchestration through explicit offline account, object and ledger doubles."""

from __future__ import annotations

import asyncio
import io
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore

from qualify_api.ads import unpublished_service as module
from qualify_api.ads.activation_repository import MemoryActivationRepository
from qualify_api.ads.client import MarketingClient, MarketingPage
from qualify_api.ads.enhancements import BrandEnhancementSettings
from qualify_api.ads.errors import MarketingError
from qualify_api.ads.fake import FakeMarketingClient
from qualify_api.ads.promotion_repository import MemoryPromotionRepository
from qualify_api.ads.promotions import AccountAccess
from qualify_api.ads.unpublished import (
    ImageAdForm,
    ImageSelection,
    ImageSource,
    UnpublishedUnavailable,
    creative_payload,
)
from qualify_api.ads.unpublished_service import UnpublishedImageService, image_bytes


def source() -> ImageSource:
    tenant = uuid4()

    def asset(width, height):
        return ImageSelection(
            uuid4(), f"t/{tenant}/generated/{uuid4()}.png", "image/png", width, height
        )

    return ImageSource(
        tenant,
        uuid4(),
        uuid4(),
        uuid4(),
        3,
        uuid4(),
        uuid4(),
        2,
        "12",
        "42",
        "7",
        "COP",
        "America/Bogota",
        asset(40, 50),
        asset(90, 160),
    )


def form() -> ImageAdForm:
    now = datetime.now(UTC)
    return ImageAdForm(
        "Prueba",
        "Título",
        "https://example.org",
        100_00,
        now + timedelta(days=1),
        now + timedelta(days=2),
        "CO",
    )


class Recipes:
    def __init__(self):
        self.rows, self.uploads = {}, {}

    def approve(self, source, form, actor, key):
        row = self.rows.setdefault(
            key,
            {
                "id": key,
                "source": source.snapshot(),
                "form": form.snapshot(),
                "approved_by": actor,
                "ad_account_id": source.account_id,
                "approved_at": datetime.now(UTC),
                "promotion_id": None,
            },
        )
        return deepcopy(row)

    def recipe(self, tenant, key):
        return deepcopy(self.rows[key])

    def link(self, tenant, key, promotion):
        self.rows[key]["promotion_id"] = promotion

    def claim_upload(self, source, asset, digest):
        key = asset.asset_id, digest
        if key in self.uploads:
            return deepcopy(self.uploads[key]), False
        row = {"id": uuid4(), "state": "creating", "image_hash": None}
        self.uploads[key] = row
        return deepcopy(row), True

    def finish_upload(self, tenant, upload, value):
        row = next(row for row in self.uploads.values() if row["id"] == upload)
        row.update(state="created" if value else "unknown", image_hash=value)


class Client(FakeMarketingClient):
    def __init__(self):
        super().__init__(account_id="12")
        self.upload_calls, self.updates, self.previews, self.validations = 0, [], [], []
        self.upload_failure = False
        self.update_failure = False
        self.mutate = None
        self.read_lock = asyncio.Lock()

    async def upload_image(self, data, *, before_write):
        before_write()
        self.upload_calls += 1
        if self.upload_failure:
            raise MarketingError("unknown", outcome_unknown=True)
        return f"hash{self.upload_calls}"

    async def validate(self, resource, *, params):
        self.validations.append((resource, deepcopy(params)))

    async def create(self, resource, *, params, before_write=None):
        value = await super().create(resource, params=params, before_write=before_write)
        self.objects[value]["account_id"] = "12"
        if resource == "ads":
            self.objects[value]["creative"] = {"id": params["creative"]["creative_id"]}
            parent = self.objects[params["adset_id"]]
            self.objects[value]["campaign_id"] = parent["campaign_id"]
        return value

    async def read_object(self, identifier, *, fields):
        # Like Graph, only the requested fields come back (FakeMarketingClient honours them).
        async with self.read_lock:
            return await FakeMarketingClient._request(self, "GET", identifier, {"fields": fields})

    async def children(self, parent, *, resource):
        field = "campaign_id" if resource == "adsets" else "adset_id"
        return tuple(
            row
            for row in self.objects.values()
            if row.get("_resource") == resource and row.get(field) == parent
        )

    async def adpreviews(self, ad, *, params):
        self.previews.append(params["ad_format"])
        return MarketingPage(({"body": f"preview:{params['ad_format']}"},))

    async def update(self, identifier, *, params, before_write=None):
        # Simulate the real account lock: read operations in its callback must use
        # another client, not re-enter a held lock.
        async with self.read_lock:
            if before_write:
                await before_write()
            self.updates.append(identifier)
            if self.update_failure:
                raise MarketingError("unknown", outcome_unknown=True)
            self.objects[identifier].update(params)

    async def aclose(self):
        pass


@pytest.fixture
def service(monkeypatch):
    selected, actor = source(), uuid4()
    store = MemoryObjectStore(locked=False)
    for asset in (selected.feed, selected.vertical):
        data = io.BytesIO()
        Image.new("RGB", (asset.width, asset.height)).save(data, format="PNG")
        store.put(asset.object_key, io.BytesIO(data.getvalue()), "image/png")
    client = Client()
    obj = UnpublishedImageService(ObjectGate(store))
    obj.recipes, obj.promotions, obj.reviews = (
        Recipes(),
        MemoryPromotionRepository(),
        MemoryActivationRepository(),
    )
    monkeypatch.setattr(module, "load_image_source", lambda *args: selected)
    monkeypatch.setattr(module, "guard_source", lambda s: None)
    monkeypatch.setattr(module, "authorize_actor", lambda tenant, who: None)
    monkeypatch.setattr(
        module,
        "load_brand_enhancements",
        lambda **kw: BrandEnhancementSettings(selected.tenant_id, selected.brand_id),
    )
    account_calls = []

    async def account(s, a):
        obj._guard(s, a)
        account_calls.append(1)
        observed = client
        if len(account_calls) > 2:
            observed = Client()
            observed.objects = client.objects
        return AccountAccess(s.tenant_id, s.brand_id, s.meta_account_id, s.currency, observed)

    async def observe(*args):
        obj._guard(selected, actor)

    monkeypatch.setattr(obj, "_account", account)
    monkeypatch.setattr(obj, "_observe", observe)
    return obj, selected, actor, client, store


async def prepare(bundle):
    obj, selected, actor, *_ = bundle
    return await obj.prepare(
        tenant_id=selected.tenant_id,
        draft_id=selected.draft_id,
        ad_account_id=selected.account_id,
        feed_asset_id=selected.feed.asset_id,
        vertical_asset_id=selected.vertical.asset_id,
        form=form(),
        actor=actor,
        request_key=uuid4(),
        confirm_preparation=True,
    )


@pytest.mark.asyncio
async def test_production_service_prepares_four_paused_objects_and_two_bound_previews(service):
    obj, selected, actor, client, _ = service
    preview = await prepare(service)
    assert client.upload_calls == 2 and len(client.objects) == 4
    assert client.previews == ["INSTAGRAM_STANDARD", "INSTAGRAM_STORY"]
    assert not client.updates
    assert all(
        row.get("status") == "PAUSED"
        for row in client.objects.values()
        if row["_resource"] != "adcreatives"
    )
    promotion = obj.promotions.get(selected.tenant_id, preview.promotion_id)
    assert promotion.request["source_media_id"] is None
    assert promotion.request["publish_attempt_id"] is None
    assert promotion.request["creative"]["asset_feed_spec"]["link_urls"] == [
        {"website_url": "https://example.org"}
    ]
    with pytest.raises(UnpublishedUnavailable, match="Confirma"):
        await obj.confirm(
            tenant_id=selected.tenant_id,
            recipe_id=preview.recipe_id,
            review_id=preview.review_id,
            actor=actor,
            confirm_charge=False,
        )
    assert not client.updates
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
    assert client.updates == [promotion.ids[key] for key in ("ads", "adsets", "campaigns")]


@pytest.mark.asyncio
async def test_uncertain_upload_is_durable_and_never_posted_again(service):
    obj, selected, actor, client, _ = service
    client.upload_failure = True
    with pytest.raises(UnpublishedUnavailable):
        await prepare(service)
    assert client.upload_calls == 1
    assert next(iter(obj.recipes.uploads.values()))["state"] == "unknown"
    with pytest.raises(UnpublishedUnavailable, match="Pide ayuda"):
        await prepare(service)
    assert client.upload_calls == 1 and not client.objects


@pytest.mark.asyncio
async def test_changed_r2_bytes_and_source_never_activate(service, monkeypatch):
    obj, selected, actor, client, store = service
    preview = await prepare(service)
    data = io.BytesIO()
    Image.new("RGB", (selected.feed.width, selected.feed.height), color="red").save(
        data, format="PNG"
    )
    store.objects[selected.feed.object_key] = data.getvalue()
    with pytest.raises(UnpublishedUnavailable, match="cambiaron"):
        await obj.confirm(
            tenant_id=selected.tenant_id,
            recipe_id=preview.recipe_id,
            review_id=preview.review_id,
            actor=actor,
            confirm_charge=True,
        )
    assert not client.updates
    monkeypatch.setattr(
        module, "guard_source", lambda s: (_ for _ in ()).throw(UnpublishedUnavailable("changed"))
    )
    with pytest.raises(UnpublishedUnavailable, match="changed"):
        await prepare(service)


@pytest.mark.asyncio
async def test_unknown_activation_cannot_be_retried(service):
    obj, selected, actor, client, _ = service
    preview = await prepare(service)
    client.update_failure = True
    with pytest.raises(MarketingError):
        await obj.confirm(
            tenant_id=selected.tenant_id,
            recipe_id=preview.recipe_id,
            review_id=preview.review_id,
            actor=actor,
            confirm_charge=True,
        )
    assert obj.reviews.get(selected.tenant_id, preview.review_id).state == "unknown"
    assert (
        await obj.confirm(
            tenant_id=selected.tenant_id,
            recipe_id=preview.recipe_id,
            review_id=preview.review_id,
            actor=actor,
            confirm_charge=True,
        )
        == "unknown"
    )
    assert len(client.updates) == 1


@pytest.mark.parametrize(
    "url", ["https://a b", "https://[", "https://example.org:bad", "http://example.org"]
)
def test_malformed_link_is_owner_error(url):
    with pytest.raises(UnpublishedUnavailable):
        replace(form(), link_url=url).validate(datetime.now(UTC))


def test_raw_bytes_type_dimensions_and_ratio_checked(service):
    obj, selected, _, _, store = service
    damaged = bytearray(store.objects[selected.feed.object_key])
    damaged[damaged.index(b"IDAT") + 4] ^= 1
    store.objects[selected.feed.object_key] = bytes(damaged)
    with pytest.raises(UnpublishedUnavailable):
        image_bytes(obj.gate, selected, selected.feed)
    store.objects[selected.feed.object_key] = b"not an image"
    with pytest.raises(UnpublishedUnavailable):
        image_bytes(obj.gate, selected, selected.feed)
    with pytest.raises(UnpublishedUnavailable):
        replace(selected, feed=replace(selected.feed, width=50)).snapshot()
    with pytest.raises(UnpublishedUnavailable):
        creative_payload(selected, form(), ("one",))
    del store.objects[selected.feed.object_key]
    with pytest.raises(UnpublishedUnavailable) as error:
        image_bytes(obj.gate, selected, selected.feed)
    assert selected.feed.object_key not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{"images": {"fixture": {"hash": "abc-imagehash"}}}, {"id": "77"}]
)
async def test_real_http_image_transport_accepts_hash_not_numeric_id_and_never_retries(payload):
    import base64
    from urllib.parse import parse_qs

    calls, fences = [], []

    def respond(request):
        calls.append(request)
        assert request.url.path == "/v26.0/act_12/adimages" and request.method == "POST"
        assert base64.b64decode(parse_qs(request.content.decode())["bytes"][0]) == b"image-bytes"
        assert fences == [True]
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = MarketingClient(client=http, account_id="12")
        if "images" in payload:
            assert (
                await client.upload_image(b"image-bytes", before_write=lambda: fences.append(True))
                == "abc-imagehash"
            )
        else:
            with pytest.raises(MarketingError) as error:
                await client.upload_image(b"image-bytes", before_write=lambda: fences.append(True))
            assert error.value.outcome_unknown
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_concurrent_confirmation_dispatches_one_activation_only(service, monkeypatch):
    obj, selected, actor, client, _ = service
    preview = await prepare(service)

    async def observe(*args):
        await asyncio.sleep(0)

    monkeypatch.setattr(obj, "_observe", observe)

    async def confirm():
        return await obj.confirm(
            tenant_id=selected.tenant_id,
            recipe_id=preview.recipe_id,
            review_id=preview.review_id,
            actor=actor,
            confirm_charge=True,
        )

    outcomes = await asyncio.gather(confirm(), confirm())
    assert "active" in outcomes
    assert len(client.updates) == 3
