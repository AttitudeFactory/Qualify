"""Read seam of the product catalog (migration 0038) for the template engine: the
products a brief names, as `ProductFacts` the props builder understands — store keys,
primary photo first, a formatted price label. Read-only, through the tenant door.

`product_ref` matching is forgiving on purpose: the brief's field is free text the
operator typed ("Shawarma mixto"), so it matches a product's slug, its exact name or a
case-insensitive name prefix. No match → no products, and the template runs on the
brief's own uploads alone (the photos the operator attached to THIS piece).
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from qualify_creative.render.props import ProductFacts
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.catalog.models import (
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    BrandProduct,
    ProductMedia,
)


def price_label(amount: Decimal | None, currency: str) -> str:
    if amount is None:
        return ""
    text = f"{amount:.2f}".rstrip("0").rstrip(".")
    symbol = {"USD": "$", "VES": "Bs.", "COP": "$", "UYU": "$", "EUR": "€"}.get(
        currency.upper(), ""
    )
    return f"{symbol}{text}" if symbol else f"{text} {currency}".strip()


class DbProductCatalog:
    def products_for(
        self, *, tenant_id: UUID, brand_id: UUID, product_ref: str | None
    ) -> tuple[ProductFacts, ...]:
        if not product_ref or not product_ref.strip():
            return ()
        ref = product_ref.strip()
        with tenant_session(tenant_id) as session:
            rows = list(
                session.scalars(
                    select(BrandProduct)
                    .where(BrandProduct.brand_id == brand_id, BrandProduct.is_active.is_(True))
                    .order_by(BrandProduct.position, BrandProduct.name)
                )
            )
            matches = _match(rows, ref)
            if not matches:
                return ()
            media = list(
                session.scalars(
                    select(ProductMedia)
                    .where(ProductMedia.product_id.in_([p.id for p in matches]))
                    .order_by(ProductMedia.is_primary.desc(), ProductMedia.position)
                )
            )
        by_product: dict[UUID, list[ProductMedia]] = {}
        for m in media:
            by_product.setdefault(m.product_id, []).append(m)
        return tuple(
            ProductFacts(
                name=p.name,
                price_label=price_label(p.price_amount, p.price_currency or ""),
                photo_keys=tuple(
                    m.object_key
                    for m in by_product.get(p.id, [])
                    if m.media_type == MEDIA_TYPE_IMAGE
                ),
                video_keys=tuple(
                    m.object_key
                    for m in by_product.get(p.id, [])
                    if m.media_type == MEDIA_TYPE_VIDEO
                ),
                extra={"id": str(p.id), "slug": p.slug, "category": p.category},
            )
            for p in matches
        )


def _match(rows: list[BrandProduct], ref: str) -> list[BrandProduct]:
    lowered = ref.lower()
    exact = [p for p in rows if p.slug == lowered or p.name.lower() == lowered]
    if exact:
        return exact
    return [p for p in rows if p.name.lower().startswith(lowered)]
