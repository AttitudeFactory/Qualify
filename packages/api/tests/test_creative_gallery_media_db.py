"""`db`-marked tests of CM-6's Galería reader (m-24955927) against the compose Postgres:
`DbGalleryMedia.resolve` through the tenant door — RLS hides another tenant's media, and the
brand / liveness filters hide another brand's, a tombstoned one, a video being cut and the
media of an inactive product. No R2: rows only, nothing is read or written in a bucket."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text

from qualify_api.catalog.business_media_models import (
    INGEST_PIPELINE_VERSION,
    JOB_CUT,
    STATUS_DONE,
    STATUS_RUNNING,
    BusinessMedia,
    GalleryJob,
)
from qualify_api.catalog.models import BrandProduct, ProductMedia
from qualify_api.creative.gallery_media import DbGalleryMedia, GalleryRef
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

TENANT_A = UUID("a0000000-0000-4000-8000-0000000006c1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000006c2")
BUSINESS, PRODUCT = "business", "product"


def _brand(session, tenant: UUID, name: str) -> UUID:  # noqa: ANN001
    brand = session.scalar(select(Brand).where(Brand.tenant_id == tenant, Brand.name == name))
    if brand is None:
        brand = Brand(tenant_id=tenant, name=name)
        session.add(brand)
        session.flush()
    return brand.id


@pytest.fixture
def brands() -> dict[str, UUID]:
    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"cm6-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        out = {
            "a": _brand(session, TENANT_A, "cm6-brand-a"),
            "a2": _brand(session, TENANT_A, "cm6-brand-a2"),
            "b": _brand(session, TENANT_B, "cm6-brand-b"),
        }
    for tid in (TENANT_A, TENANT_B):
        with tenant_session(tid) as session:
            for table in ("gallery_jobs", "business_media", "product_media", "brand_products"):
                session.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t"), {"t": tid})
    return out


def _business(tenant: UUID, brand: UUID, *, photo: bool = False, **over: object) -> UUID:
    media_id = uuid4()
    if photo:
        over = {
            "media_type": "image",
            "object_key": f"gallery/{tenant}/{media_id}/photo.jpg",
            "poster_key": None,
            "content_type": "image/jpeg",
            "duration_ms": None,
            "has_audio": False,
            **over,
        }
    values: dict[str, object] = dict(
        id=media_id,
        tenant_id=tenant,
        brand_id=brand,
        media_type="video",
        object_key=f"gallery/{tenant}/{media_id}/video.mp4",
        poster_key=f"gallery/{tenant}/{media_id}/poster.jpg",
        content_type="video/mp4",
        width=1080,
        height=1920,
        duration_ms=42_000,
        has_audio=True,
        pipeline_version=INGEST_PIPELINE_VERSION,
    )
    values.update(over)
    with tenant_session(tenant) as session:
        session.add(BusinessMedia(**values))
    return media_id


def _product_media(tenant: UUID, brand: UUID, *, active: bool = True) -> tuple[UUID, str]:
    product_id, media_id = uuid4(), uuid4()
    name = f"Smash {product_id.hex[:6]}"
    with tenant_session(tenant) as session:
        session.add(
            BrandProduct(
                id=product_id,
                tenant_id=tenant,
                brand_id=brand,
                name=name,
                slug=f"smash-{product_id.hex[:8]}",
                is_active=active,
            )
        )
        session.flush()
        session.add(
            ProductMedia(
                id=media_id,
                tenant_id=tenant,
                brand_id=brand,
                product_id=product_id,
                media_type="video",
                object_key=f"uploads/{tenant}/catalog/{product_id}/{media_id}.mp4",
                content_type="video/mp4",
                duration_sec=Decimal("9.50"),
            )
        )
    return media_id, name


def test_resolve_returns_only_this_brands_live_media(brands: dict[str, UUID]) -> None:
    a, a2, b = brands["a"], brands["a2"], brands["b"]
    photo = _business(TENANT_A, a, photo=True)
    video = _business(TENANT_A, a)
    removed = _business(TENANT_A, a, deleted_at=text("now()"))
    being_cut = _business(TENANT_A, a)
    cut_before = _business(TENANT_A, a)
    other_brand = _business(TENANT_A, a2)
    other_tenant = _business(TENANT_B, b)
    clip, clip_name = _product_media(TENANT_A, a)
    inactive, _ = _product_media(TENANT_A, a, active=False)
    foreign_clip, _ = _product_media(TENANT_B, b)
    with tenant_session(TENANT_A) as session:
        for source, status in ((being_cut, STATUS_RUNNING), (cut_before, STATUS_DONE)):
            session.add(
                GalleryJob(
                    tenant_id=TENANT_A,
                    brand_id=a,
                    kind=JOB_CUT,
                    status=status,
                    idempotency_key=f"cut:{source}:x",
                    source_media_id=source,
                    segments=[[0, 20_000]],
                    pipeline_version="gallery-cut-v1",
                )
            )

    refs = [
        GalleryRef(BUSINESS, m)
        for m in (photo, video, removed, being_cut, cut_before, other_brand, other_tenant)
    ] + [GalleryRef(PRODUCT, m) for m in (clip, inactive, foreign_clip)]
    # a product id asked as a business medium (and the reverse) is not found either
    refs += [GalleryRef(BUSINESS, clip), GalleryRef(PRODUCT, video)]
    found = DbGalleryMedia().resolve(tenant_id=TENANT_A, brand_id=a, refs=refs)

    assert set(found) == {
        GalleryRef(BUSINESS, photo),
        GalleryRef(BUSINESS, video),
        GalleryRef(BUSINESS, cut_before),  # its cut finished: it is a medium like any other
        GalleryRef(PRODUCT, clip),
    }
    business_video = found[GalleryRef(BUSINESS, video)]
    assert business_video.is_video and business_video.has_audio and business_video.keeps_sound
    assert business_video.duration_ms == 42_000
    assert business_video.thumbnail_key.endswith("poster.jpg")
    product_clip = found[GalleryRef(PRODUCT, clip)]
    assert product_clip.duration_ms == 9_500 and not product_clip.keeps_sound
    assert product_clip.product_name == clip_name
    assert found[GalleryRef(BUSINESS, photo)].duration_ms is None

    # tenant B, asking for tenant A's ids under its own session, sees nothing of A's
    seen_by_b = DbGalleryMedia().resolve(tenant_id=TENANT_B, brand_id=b, refs=refs)
    assert set(seen_by_b) == {GalleryRef(BUSINESS, other_tenant), GalleryRef(PRODUCT, foreign_clip)}
    # and a brand of tenant B named under tenant A's session is not a key to B's rows
    assert DbGalleryMedia().resolve(tenant_id=TENANT_A, brand_id=b, refs=refs) == {}


def test_resolve_with_nothing_asked_reads_nothing() -> None:
    assert DbGalleryMedia().resolve(tenant_id=TENANT_A, brand_id=uuid4(), refs=()) == {}
