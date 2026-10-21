"""`db`-marked roundtrip of `CatalogService` against the compose Postgres: create a
product, add a normalized photo, promote/remove media, list through the tenant door,
and prove the other tenant sees nothing. Objects go to a temp-dir store."""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from PIL import Image
from qualify_shared.db.admin import admin_session
from sqlalchemy import select

from qualify_api.catalog.service import CatalogError, CatalogService, UnknownProduct
from qualify_api.creative.media import LocalMediaStore
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

TENANT_A = UUID("a0000000-0000-4000-8000-0000000000c1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000000c2")


@pytest.fixture
def seeded() -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"catalog-svc-{name}",
                        country="VE",
                        timezone="America/Caracas",
                        currency="USD",
                    )
                )
                session.flush()
        brands: dict[UUID, UUID] = {}
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            brand = session.scalar(select(Brand).where(Brand.tenant_id == tid))
            if brand is None:
                brand = Brand(tenant_id=tid, name=f"catalog-svc-brand-{name}")
                session.add(brand)
                session.flush()
            brands[tid] = brand.id
        user = User(tenant_id=TENANT_A, email=f"catalog-svc-{uuid4()}@a.co", display_name="U")
        session.add(user)
        session.flush()
        return TENANT_A, brands[TENANT_A], user.id, TENANT_B, brands[TENANT_B]


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1600, 1200), (240, 120, 60)).save(out, format="JPEG")
    return out.getvalue()


def test_catalog_roundtrip_and_isolation(seeded, tmp_path: Path) -> None:
    tenant_a, brand_a, user_a, tenant_b, brand_b = seeded
    service = CatalogService(store=LocalMediaStore(tmp_path))
    # the seeded tenants outlive a run: a fresh name keeps the slug check re-runnable
    run = uuid4().hex[:8]

    product_id = service.create_product(
        tenant_id=tenant_a,
        brand_id=brand_a,
        user_id=user_a,
        name=f"Shawarma mixto {run}",
        price_amount=Decimal("5.00"),
        price_currency="usd",
        category="shawarma",
        tags=("picante", ""),
    )
    twin = service.create_product(
        tenant_id=tenant_a, brand_id=brand_a, user_id=user_a, name=f"Shawarma mixto {run}"
    )
    products = service.list_products(tenant_id=tenant_a, brand_id=brand_a)
    slugs = {p.slug for p in products}
    assert {f"shawarma-mixto-{run}", f"shawarma-mixto-{run}-2"} <= slugs
    first = next(p for p in products if p.id == product_id)
    assert (
        first.price_label == "$5" and first.price_currency == "USD" and first.tags == ("picante",)
    )

    photo = service.add_media(
        tenant_id=tenant_a, product_id=product_id, data=_jpeg(), filename="IMG_1.JPG"
    )
    second = service.add_media(
        tenant_id=tenant_a, product_id=product_id, data=_jpeg(), filename="IMG_2.JPG"
    )
    assert photo.is_primary and not second.is_primary and second.position == 1
    assert (photo.width, photo.height) == (1080, 810)
    assert (tmp_path / photo.object_key).is_file()

    service.set_primary(tenant_id=tenant_a, product_id=product_id, media_id=second.id)
    record = service.get_product(tenant_id=tenant_a, product_id=product_id)
    assert record.primary_photo_key == second.object_key and record.photo_count == 2

    service.remove_media(tenant_id=tenant_a, product_id=product_id, media_id=second.id)
    record = service.get_product(tenant_id=tenant_a, product_id=product_id)
    assert record.photo_count == 1 and record.media[0].is_primary  # primary falls back

    service.update_product(
        tenant_id=tenant_a, product_id=twin, is_active=False, price_amount=Decimal("6")
    )
    active = service.list_products(tenant_id=tenant_a, brand_id=brand_a)
    assert twin not in {p.id for p in active}
    everything = service.list_products(tenant_id=tenant_a, brand_id=brand_a, include_inactive=True)
    assert next(p for p in everything if p.id == twin).price_amount == Decimal("6")

    # RLS: tenant B sees none of A's products, not even by id
    assert service.list_products(tenant_id=tenant_b, brand_id=brand_a) == ()
    with pytest.raises(UnknownProduct):
        service.get_product(tenant_id=tenant_b, product_id=product_id)
    with pytest.raises(CatalogError):
        service.create_product(tenant_id=tenant_a, brand_id=brand_a, user_id=user_a, name="  ")
