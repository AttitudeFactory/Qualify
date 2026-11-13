"""ADR 48 against the compose Postgres (migration 0156): RLS with two tenants and the
grants, the three actions and their idempotency, `CatalogSyncTick` driven end to end with
the FAKE catalog client (never Meta), the screen's read, and the photo route's lookup.
Nothing here touches R2: the route's store is never built."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from psycopg.errors import InsufficientPrivilege
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

from qualify_api.catalog.models import BrandProduct, ProductMedia
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.http.public_catalog_media_routes import lookup_catalog_media
from qualify_api.tenancy.models import Brand, Tenant, User
from qualify_api.whatsapp.catalog_sync import media_url, service
from qualify_api.whatsapp.catalog_sync.client import (
    BatchAck,
    BatchStatus,
    FakeWhatsAppCatalogClient,
)
from qualify_api.whatsapp.catalog_sync.connect import (
    CatalogConflict,
    CatalogRegistration,
    PostgresCatalogRegistry,
)
from qualify_api.whatsapp.catalog_sync.worker import CatalogSyncTick
from qualify_api.whatsapp.client import WhatsAppApiError
from qualify_api.whatsapp.models import (
    WhatsAppCatalog,
    WhatsAppCatalogItem,
    WhatsAppCatalogSyncRun,
    WhatsAppPhoneNumber,
)
from qualify_api.whatsapp.worker import ScopedTenants

pytestmark = pytest.mark.db

# Fresh tenants per test (set by the `ids` fixture): the tick claims ANY due run of its
# tenant, so a run left over by another test or an earlier `just test-db` must not exist
# in the tenant a test drives.
TENANT = UUID(int=0)
OTHER_TENANT = UUID(int=0)


@pytest.fixture(autouse=True)
def _signing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(media_url.SECRET_ENV, "c" * 40)
    monkeypatch.setenv(media_url.BASE_URL_ENV, "https://qualify.example")


def _tenant(session, tenant_id: UUID, name: str) -> None:  # noqa: ANN001
    if session.get(Tenant, tenant_id) is None:
        session.add(
            Tenant(
                id=tenant_id,
                name=name,
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()


def _setup(tenant_id: UUID) -> dict[str, UUID]:
    """A fresh brand with a connected number and a registered catalog."""
    with admin_session() as session:
        _tenant(session, tenant_id, f"t-{tenant_id.hex[-4:]}")
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@adr48.co", display_name="U")
        brand = Brand(tenant_id=tenant_id, name="Bianki")
        session.add_all([app, user, brand])
        session.flush()
        ids = {"app": app.id, "user": user.id, "brand": brand.id}
    waba = f"waba-{uuid4()}"
    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=ids["app"],
            platform="whatsapp",
            account_type="waba_phone_number",
            external_account_id=f"wa-{uuid4()}",
            linked_page_id=None,
            granted_scopes=["whatsapp_business_messaging"],
            status="pending",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=ids["user"],
        )
        session.add(conn)
        session.flush()
        phone = WhatsAppPhoneNumber(
            tenant_id=tenant_id,
            brand_id=ids["brand"],
            connection_id=conn.id,
            waba_id=waba,
            phone_number_id=f"pn-{uuid4()}",
            display_phone_number="+57 300 000 0048",
        )
        session.add(phone)
        session.flush()
        ids["connection"] = conn.id
        ids["phone"] = phone.id
    outcome = PostgresCatalogRegistry().register(
        CatalogRegistration(
            tenant_id=tenant_id,
            brand_id=ids["brand"],
            phone=PostgresCatalogRegistry().phone_for_brand(tenant_id, ids["brand"]),  # type: ignore[arg-type]
            catalog_id=f"cat-{uuid4()}",
            link_url="https://bianki.example",
            user_id=ids["user"],
            now=datetime.now(UTC),
        )
    )
    ids["catalog"] = outcome.catalog_row_id
    return ids


def _product(
    tenant_id: UUID,
    brand_id: UUID,
    name: str,
    *,
    price: str | None = "12500",
    active: bool = True,
    photo: tuple[int, int, str] | None = (800, 800, "image/jpeg"),
) -> tuple[UUID, UUID | None]:
    with tenant_session(tenant_id) as session:
        product = BrandProduct(
            tenant_id=tenant_id,
            brand_id=brand_id,
            name=name,
            slug=f"{name.lower()}-{uuid4().hex[:8]}",
            price_amount=Decimal(price) if price is not None else None,
            price_currency="COP",
            is_active=active,
        )
        session.add(product)
        session.flush()
        media_id = None
        if photo is not None:
            media = ProductMedia(
                tenant_id=tenant_id,
                brand_id=brand_id,
                product_id=product.id,
                media_type="image",
                object_key=f"t/{tenant_id}/catalog/{uuid4()}.jpg",
                content_type=photo[2],
                width=photo[0],
                height=photo[1],
                is_primary=True,
            )
            session.add(media)
            session.flush()
            media_id = media.id
        return product.id, media_id


def _item(tenant_id: UUID, catalog: UUID, product_id: UUID) -> WhatsAppCatalogItem:
    with tenant_session(tenant_id) as session:
        item = session.scalar(
            select(WhatsAppCatalogItem).where(
                WhatsAppCatalogItem.catalog_row_id == catalog,
                WhatsAppCatalogItem.product_id == product_id,
            )
        )
        assert item is not None
        session.expunge(item)
        return item


def _run(tenant_id: UUID, run_id: UUID) -> WhatsAppCatalogSyncRun:
    with tenant_session(tenant_id) as session:
        run = session.get(WhatsAppCatalogSyncRun, run_id)
        assert run is not None
        session.expunge(run)
        return run


def _runs(tenant_id: UUID, catalog: UUID) -> int:
    with tenant_session(tenant_id) as session:
        return len(
            list(
                session.scalars(
                    select(WhatsAppCatalogSyncRun.id).where(
                        WhatsAppCatalogSyncRun.catalog_row_id == catalog
                    )
                )
            )
        )


class _Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC) + timedelta(seconds=1)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def _tick(tenant_id: UUID, fake: FakeWhatsAppCatalogClient, clock: _Clock) -> CatalogSyncTick:
    async def factory(
        *, tenant_id: UUID, connection_id: UUID, catalog_id: str
    ) -> FakeWhatsAppCatalogClient:
        return fake

    return CatalogSyncTick(
        tenants=ScopedTenants([tenant_id]), clients=factory, worker_id="test:1", clock=clock
    )


@pytest.fixture
def ids() -> Iterator[dict[str, UUID]]:
    global TENANT, OTHER_TENANT
    TENANT, OTHER_TENANT = uuid4(), uuid4()
    yield _setup(TENANT)


def _upload(ids: dict[str, UUID], product_id: UUID) -> service.EnqueueResult:
    return service.upload_product(
        tenant_id=TENANT, brand_id=ids["brand"], product_id=product_id, requested_by=ids["user"]
    )


def _resync(ids: dict[str, UUID], product_id: UUID) -> service.EnqueueResult:
    return service.resync_product(
        tenant_id=TENANT, brand_id=ids["brand"], product_id=product_id, requested_by=ids["user"]
    )


# --- RLS and grants -----------------------------------------------------------------------


def test_another_tenant_sees_nothing(ids: dict[str, UUID]) -> None:
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    _upload(ids, product_id)
    _setup(OTHER_TENANT)
    with tenant_session(OTHER_TENANT) as session:
        for model in (WhatsAppCatalog, WhatsAppCatalogItem, WhatsAppCatalogSyncRun):
            rows = session.scalars(select(model).where(model.tenant_id == TENANT)).all()
            assert rows == []
    view = service.catalog_sync_view(tenant_id=OTHER_TENANT, brand_id=ids["brand"])
    assert view.connection == "none" and dict(view.products) == {}


def _denied(sql: str) -> bool:
    with pytest.raises(DBAPIError) as caught, tenant_session(TENANT) as session:
        session.execute(text(sql))
    return isinstance(caught.value.orig, InsufficientPrivilege)


def test_retailer_id_and_identity_are_not_updatable_and_runs_not_deletable(
    ids: dict[str, UUID],
) -> None:
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    _upload(ids, product_id)
    assert _denied("UPDATE whatsapp_catalog_items SET retailer_id = 'x'")
    assert _denied("UPDATE whatsapp_catalog_items SET catalog_row_id = catalog_row_id")
    assert _denied("UPDATE whatsapp_catalog_items SET tenant_id = tenant_id")
    assert _denied("DELETE FROM whatsapp_catalog_sync_runs WHERE false")
    with tenant_session(TENANT) as session:
        session.execute(text("UPDATE whatsapp_catalog_items SET state = state"))


# --- the actions --------------------------------------------------------------------------


async def test_upload_send_poll_synced_then_idempotent(ids: dict[str, UUID]) -> None:
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    first = _upload(ids, product_id)
    assert (len(first.run_ids), first.upserts) == (1, 1)
    again = _upload(ids, product_id)
    assert again.run_ids == () and again.in_flight == 1
    assert _runs(TENANT, ids["catalog"]) == 1
    item = _item(TENANT, ids["catalog"], product_id)
    assert (item.state, item.retailer_id) == ("queued", str(product_id))

    fake = FakeWhatsAppCatalogClient()
    clock = _Clock()
    tick = _tick(TENANT, fake, clock)
    await tick.run_once()
    run = _run(TENANT, first.run_ids[0])
    assert (run.status, run.handle, run.attempts) == ("sent", "handle-1", 1)
    [[request]] = fake.sent
    assert request["method"] == "UPDATE"
    assert request["data"]["price"] == "12500.00 COP"
    assert request["data"]["link"] == "https://bianki.example"
    assert _item(TENANT, ids["catalog"], product_id).state == "uploading"

    clock.advance(seconds=31)
    await tick.run_once()
    run = _run(TENANT, first.run_ids[0])
    assert (run.status, run.items_failed) == ("finished", 0)
    item = _item(TENANT, ids["catalog"], product_id)
    assert item.state == "synced" and item.last_pushed_hash and item.pending_hash is None
    assert item.pipeline_version == "wa-catalog-map-v1" and item.last_run_id == run.id

    unchanged = _resync(ids, product_id)
    assert unchanged.run_ids == () and unchanged.unchanged == 1
    view = service.catalog_sync_view(tenant_id=TENANT, brand_id=ids["brand"])
    assert view.connection == "connected"
    assert view.products[product_id].state == "synced"
    assert view.last_run is not None and view.last_run.status == "finished"

    with tenant_session(TENANT) as session:
        session.execute(
            update(BrandProduct)
            .where(BrandProduct.id == product_id)
            .values(price_amount=Decimal("13000"))
        )
    view = service.catalog_sync_view(tenant_id=TENANT, brand_id=ids["brand"])
    assert view.products[product_id].state == "out_of_date"
    changed = _resync(ids, product_id)
    assert len(changed.run_ids) == 1 and changed.upserts == 1
    assert _runs(TENANT, ids["catalog"]) == 2


def test_refusals_are_typed(ids: dict[str, UUID]) -> None:
    small, _ = _product(TENANT, ids["brand"], "Pequeño", photo=(300, 300, "image/jpeg"))
    with pytest.raises(service.ProductNotEligible) as caught:
        _upload(ids, small)
    assert caught.value.reason == "photo_too_small"
    webp, _ = _product(TENANT, ids["brand"], "Webp", photo=(900, 900, "image/webp"))
    with pytest.raises(service.ProductNotEligible):
        _upload(ids, webp)
    fresh, _ = _product(TENANT, ids["brand"], "Nuevo")
    with pytest.raises(service.ItemNotUploaded):
        _resync(ids, fresh)
    with pytest.raises(service.ProductNotFound):
        _upload(ids, uuid4())
    with pytest.raises(service.CatalogNotConnected):
        service.plan_catalog_sync(tenant_id=TENANT, brand_id=uuid4())
    with tenant_session(TENANT) as session:
        session.execute(
            update(WhatsAppCatalog)
            .where(WhatsAppCatalog.id == ids["catalog"])
            .values(access_state="missing_permission")
        )
    with pytest.raises(service.CatalogPermissionMissing):
        _upload(ids, fresh)


def test_upload_refuses_without_a_signing_secret(
    ids: dict[str, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    monkeypatch.setenv(media_url.SECRET_ENV, "short")
    with pytest.raises(media_url.CatalogMediaUnavailable):
        _upload(ids, product_id)
    assert _runs(TENANT, ids["catalog"]) == 0


async def test_sync_all_plan_then_confirm_and_plan_changed(ids: dict[str, UUID]) -> None:
    a, _ = _product(TENANT, ids["brand"], "A")
    b, _ = _product(TENANT, ids["brand"], "B")
    _product(TENANT, ids["brand"], "SinFoto", photo=None)
    _product(TENANT, ids["brand"], "Inactivo", active=False)
    plan = service.plan_catalog_sync(tenant_id=TENANT, brand_id=ids["brand"])
    assert (plan.new, plan.changed, plan.deletes, plan.unchanged) == (2, 0, 0, 0)
    assert plan.not_eligible == {"no_photo": 1, "inactive": 1}
    with pytest.raises(service.PlanChanged):
        service.sync_all(
            tenant_id=TENANT, brand_id=ids["brand"], requested_by=ids["user"], plan_key="stale"
        )
    result = service.sync_all(
        tenant_id=TENANT, brand_id=ids["brand"], requested_by=ids["user"], plan_key=plan.plan_key
    )
    assert (len(result.run_ids), result.upserts) == (1, 2)
    again = service.plan_catalog_sync(tenant_id=TENANT, brand_id=ids["brand"])
    assert (again.new, again.in_flight) == (0, 2)
    assert {_item(TENANT, ids["catalog"], p).state for p in (a, b)} == {"queued"}


async def test_inactive_product_item_is_deleted_and_reupload_reuses_the_row(
    ids: dict[str, UUID],
) -> None:
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    _upload(ids, product_id)
    fake = FakeWhatsAppCatalogClient()
    clock = _Clock()
    tick = _tick(TENANT, fake, clock)
    await tick.run_once()
    clock.advance(seconds=31)
    await tick.run_once()
    first = _item(TENANT, ids["catalog"], product_id)
    assert first.state == "synced"

    with tenant_session(TENANT) as session:
        session.execute(
            update(BrandProduct).where(BrandProduct.id == product_id).values(is_active=False)
        )
    deletion = _resync(ids, product_id)
    assert deletion.deletes == 1
    clock.advance(seconds=1)
    await tick.run_once()
    assert fake.sent[-1] == [{"method": "DELETE", "data": {"id": str(product_id)}}]
    clock.advance(seconds=31)
    await tick.run_once()
    assert _item(TENANT, ids["catalog"], product_id).state == "deleted"

    with tenant_session(TENANT) as session:
        session.execute(
            update(BrandProduct).where(BrandProduct.id == product_id).values(is_active=True)
        )
    _upload(ids, product_id)
    again = _item(TENANT, ids["catalog"], product_id)
    assert (again.id, again.retailer_id, again.state) == (first.id, first.retailer_id, "queued")


# --- the tick against the fake client -----------------------------------------------------


async def _sent_run(ids: dict[str, UUID], fake: FakeWhatsAppCatalogClient, clock: _Clock) -> UUID:
    product_id, _ = _product(TENANT, ids["brand"], f"P{uuid4().hex[:4]}")
    result = _upload(ids, product_id)
    await _tick(TENANT, fake, clock).run_once()
    return result.run_ids[0]


async def test_finished_with_invalid_ids_is_partial(ids: dict[str, UUID]) -> None:
    a, _ = _product(TENANT, ids["brand"], "A")
    b, _ = _product(TENANT, ids["brand"], "B")
    plan = service.plan_catalog_sync(tenant_id=TENANT, brand_id=ids["brand"])
    result = service.sync_all(
        tenant_id=TENANT, brand_id=ids["brand"], requested_by=ids["user"], plan_key=plan.plan_key
    )
    fake = FakeWhatsAppCatalogClient(statuses=[BatchStatus("finished", 1, frozenset({str(b)}))])
    clock = _Clock()
    tick = _tick(TENANT, fake, clock)
    await tick.run_once()
    clock.advance(seconds=31)
    await tick.run_once()
    run = _run(TENANT, result.run_ids[0])
    assert (run.status, run.items_failed) == ("partial", 1)
    assert _item(TENANT, ids["catalog"], a).state == "synced"
    rejected = _item(TENANT, ids["catalog"], b)
    assert (rejected.state, rejected.error_code) == ("error", "meta_rejected")
    view = service.catalog_sync_view(tenant_id=TENANT, brand_id=ids["brand"])
    assert (view.products[b].state, view.products[b].reason) == ("error", "meta_rejected")


async def test_validation_errors_at_ack_mark_items_rejected(ids: dict[str, UUID]) -> None:
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    result = _upload(ids, product_id)
    fake = FakeWhatsAppCatalogClient(
        acks=[BatchAck(handles=("h",), rejected_ids=frozenset({str(product_id)}))]
    )
    await _tick(TENANT, fake, _Clock()).run_once()
    assert _run(TENANT, result.run_ids[0]).status == "sent"
    item = _item(TENANT, ids["catalog"], product_id)
    assert (item.state, item.error_code) == ("error", "meta_rejected")


async def test_empty_handles_fail_the_run(ids: dict[str, UUID]) -> None:
    fake = FakeWhatsAppCatalogClient(acks=[BatchAck(handles=())])
    run_id = await _sent_run(ids, fake, _Clock())
    run = _run(TENANT, run_id)
    assert (run.status, run.error_code) == ("failed", "nothing_ingested")


async def test_not_finished_waits_then_unconfirmed_at_24h(ids: dict[str, UUID]) -> None:
    fake = FakeWhatsAppCatalogClient(
        statuses=[BatchStatus("in_progress"), BatchStatus("in_progress")]
    )
    clock = _Clock()
    run_id = await _sent_run(ids, fake, clock)
    clock.advance(seconds=31)
    await _tick(TENANT, fake, clock).run_once()
    run = _run(TENANT, run_id)
    assert run.status == "sent" and run.next_attempt_at > clock.now
    clock.advance(hours=25)
    await _tick(TENANT, fake, clock).run_once()
    run = _run(TENANT, run_id)
    assert (run.status, run.error_code) == ("failed", "meta_unconfirmed")


async def test_rate_limit_puts_the_run_back_for_fifteen_minutes(ids: dict[str, UUID]) -> None:
    fake = FakeWhatsAppCatalogClient(acks=[WhatsAppApiError("x", status=400, code=80014)])
    clock = _Clock()
    run_id = await _sent_run(ids, fake, clock)
    run = _run(TENANT, run_id)
    assert (run.status, run.attempts, run.meta_error_code) == ("pending", 0, 80014)
    assert run.next_attempt_at >= clock.now + timedelta(minutes=15)


async def test_transport_errors_retry_then_send_failed(ids: dict[str, UUID]) -> None:
    errors = [WhatsAppApiError("x", is_transport=True) for _ in range(5)]
    fake = FakeWhatsAppCatalogClient(acks=list(errors))
    clock = _Clock()
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    run_id = _upload(ids, product_id).run_ids[0]
    tick = _tick(TENANT, fake, clock)
    for _ in range(5):
        await tick.run_once()
        clock.advance(hours=2)
    run = _run(TENANT, run_id)
    assert (run.status, run.attempts, run.error_code) == ("failed", 5, "send_failed")
    item = _item(TENANT, ids["catalog"], product_id)
    assert (item.state, item.error_code) == ("error", "send_failed")


async def test_auth_error_sets_access_state(ids: dict[str, UUID]) -> None:
    fake = FakeWhatsAppCatalogClient(acks=[WhatsAppApiError("x", status=403, code=200)])
    run_id = await _sent_run(ids, fake, _Clock())
    run = _run(TENANT, run_id)
    assert (run.status, run.error_code) == ("failed", "missing_permission")
    with tenant_session(TENANT) as session:
        catalog = session.get(WhatsAppCatalog, ids["catalog"])
        assert catalog is not None and catalog.access_state == "missing_permission"
    view = service.catalog_sync_view(tenant_id=TENANT, brand_id=ids["brand"])
    assert view.connection == "missing_permission"


async def test_hourly_cap_defers_the_eleventh_send(ids: dict[str, UUID]) -> None:
    clock = _Clock()
    with tenant_session(TENANT) as session:
        for n in range(10):
            session.add(
                WhatsAppCatalogSyncRun(
                    tenant_id=TENANT,
                    catalog_row_id=ids["catalog"],
                    request_key=f"past-{uuid4()}-{n}",
                    trigger="upload_one",
                    status="finished",
                    item_ids=[uuid4()],
                    upserts=1,
                    deletes=0,
                    requested_by=ids["user"],
                    sent_at=clock.now - timedelta(minutes=5),
                    pipeline_version="wa-catalog-map-v1",
                )
            )
    fake = FakeWhatsAppCatalogClient()
    run_id = await _sent_run(ids, fake, clock)
    run = _run(TENANT, run_id)
    assert run.status == "pending" and fake.sent == []
    assert run.next_attempt_at > clock.now + timedelta(minutes=50)


# --- the connect registry and the photo route's lookup ------------------------------------


def test_registry_refuses_switching_a_catalog_with_live_items(ids: dict[str, UUID]) -> None:
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    _upload(ids, product_id)
    registry = PostgresCatalogRegistry()
    phone = registry.phone_for_brand(TENANT, ids["brand"])
    assert phone is not None
    registration = CatalogRegistration(
        tenant_id=TENANT,
        brand_id=ids["brand"],
        phone=phone,
        catalog_id="another-catalog",
        link_url=None,
        user_id=ids["user"],
        now=datetime.now(UTC),
    )
    with pytest.raises(CatalogConflict):
        registry.register(registration)


def test_photo_lookup_only_for_live_items_of_the_tenant(ids: dict[str, UUID]) -> None:
    product_id, media_id = _product(TENANT, ids["brand"], "Shawarma")
    assert media_id is not None
    assert lookup_catalog_media(TENANT, media_id) is None  # not in the catalog yet
    _upload(ids, product_id)
    target = lookup_catalog_media(TENANT, media_id)
    assert target is not None and target.content_type == "image/jpeg"
    assert lookup_catalog_media(OTHER_TENANT, media_id) is None
    with tenant_session(TENANT) as session:
        session.execute(
            update(WhatsAppCatalogItem)
            .where(WhatsAppCatalogItem.product_id == product_id)
            .values(state="deleted")
        )
    assert lookup_catalog_media(TENANT, media_id) is None


# --- review fixes: bounded retries, stale reclaim, lost claim -----------------------------


def _set_run(run_id: UUID, **values: object) -> None:
    with tenant_session(TENANT) as session:
        session.execute(
            update(WhatsAppCatalogSyncRun)
            .where(WhatsAppCatalogSyncRun.id == run_id)
            .values(**values)
        )


async def test_a_rejected_status_poll_fails_the_run_at_once(ids: dict[str, UUID]) -> None:
    fake = FakeWhatsAppCatalogClient(statuses=[WhatsAppApiError("x", status=400, code=100)])
    clock = _Clock()
    run_id = await _sent_run(ids, fake, clock)
    clock.advance(seconds=31)
    await _tick(TENANT, fake, clock).run_once()
    run = _run(TENANT, run_id)
    assert (run.status, run.error_code, run.meta_error_code) == ("failed", "meta_error", 100)
    with tenant_session(TENANT) as session:
        item = session.scalar(
            select(WhatsAppCatalogItem).where(WhatsAppCatalogItem.last_run_id == run_id)
        )
        assert item is not None
        assert (item.state, item.error_code) == ("error", "meta_unconfirmed")


async def test_transient_poll_errors_back_off(ids: dict[str, UUID]) -> None:
    fake = FakeWhatsAppCatalogClient(statuses=[WhatsAppApiError("x", status=503)])
    clock = _Clock()
    run_id = await _sent_run(ids, fake, clock)
    clock.advance(hours=2)
    await _tick(TENANT, fake, clock).run_once()
    run = _run(TENANT, run_id)
    assert run.status == "sent"
    assert run.next_attempt_at >= clock.now + timedelta(minutes=60)


async def test_a_throttle_code_is_waited_out_not_failed(ids: dict[str, UUID]) -> None:
    fake = FakeWhatsAppCatalogClient(acks=[WhatsAppApiError("x", status=400, code=613)])
    run_id = await _sent_run(ids, fake, _Clock())
    assert _run(TENANT, run_id).status == "pending"


async def test_rate_limits_stop_after_a_day(ids: dict[str, UUID]) -> None:
    clock = _Clock()
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    run_id = _upload(ids, product_id).run_ids[0]
    _set_run(run_id, requested_at=clock.now - timedelta(hours=23, minutes=50))
    fake = FakeWhatsAppCatalogClient(acks=[WhatsAppApiError("x", status=400, code=80014)])
    await _tick(TENANT, fake, clock).run_once()
    run = _run(TENANT, run_id)
    assert (run.status, run.error_code) == ("failed", "rate_limited")
    item = _item(TENANT, ids["catalog"], product_id)
    assert (item.state, item.error_code) == ("error", "send_failed")
    # The person can act on it again.
    assert len(_resync(ids, product_id).run_ids) == 1


async def test_a_run_older_than_a_day_is_never_sent(ids: dict[str, UUID]) -> None:
    clock = _Clock()
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    run_id = _upload(ids, product_id).run_ids[0]
    _set_run(run_id, requested_at=clock.now - timedelta(hours=25))
    fake = FakeWhatsAppCatalogClient()
    await _tick(TENANT, fake, clock).run_once()
    assert (_run(TENANT, run_id).status, fake.sent) == ("failed", [])


def _crash_mid_send(run_id: UUID, product_id: UUID, clock: _Clock, attempts: int) -> None:
    """What a worker that died after its claim committed leaves behind."""
    _set_run(
        run_id,
        status="sending",
        attempts=attempts,
        locked_by="dead:1",
        locked_at=clock.now - timedelta(minutes=11),
    )
    with tenant_session(TENANT) as session:
        session.execute(
            update(WhatsAppCatalogItem)
            .where(WhatsAppCatalogItem.product_id == product_id)
            .values(state="uploading", pending_op="upsert")
        )


async def test_a_stale_sending_claim_is_re_sent(ids: dict[str, UUID]) -> None:
    clock = _Clock()
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    run_id = _upload(ids, product_id).run_ids[0]
    _crash_mid_send(run_id, product_id, clock, attempts=1)
    fake = FakeWhatsAppCatalogClient()
    await _tick(TENANT, fake, clock).run_once()
    run = _run(TENANT, run_id)
    assert (run.status, run.attempts, run.locked_by) == ("sent", 2, None)
    assert len(fake.sent) == 1


async def test_a_stale_reclaim_respects_the_attempt_cap(ids: dict[str, UUID]) -> None:
    clock = _Clock()
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    run_id = _upload(ids, product_id).run_ids[0]
    _crash_mid_send(run_id, product_id, clock, attempts=5)
    fake = FakeWhatsAppCatalogClient()
    await _tick(TENANT, fake, clock).run_once()
    run = _run(TENANT, run_id)
    assert (run.status, run.error_code, fake.sent) == ("failed", "send_failed", [])
    item = _item(TENANT, ids["catalog"], product_id)
    assert (item.state, item.error_code) == ("error", "send_failed")


class _StealingClient(FakeWhatsAppCatalogClient):
    """Another worker re-claims the run while this one waits on Meta."""

    async def items_batch(self, requests):  # noqa: ANN001, ANN201
        with tenant_session(TENANT) as session:
            session.execute(
                update(WhatsAppCatalogSyncRun)
                .where(WhatsAppCatalogSyncRun.status == "sending")
                .values(locked_by="other:2")
            )
        return await super().items_batch(requests)


async def test_a_lost_claim_is_never_settled(ids: dict[str, UUID]) -> None:
    clock = _Clock()
    product_id, _ = _product(TENANT, ids["brand"], "Shawarma")
    run_id = _upload(ids, product_id).run_ids[0]
    await _tick(TENANT, _StealingClient(), clock).run_once()
    run = _run(TENANT, run_id)
    assert (run.status, run.locked_by, run.handle) == ("sending", "other:2", None)
