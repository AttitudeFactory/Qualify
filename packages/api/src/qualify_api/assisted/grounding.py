"""The validated facts an assisted reply may state, with their provenance (m-24789645).

A `Grounding` is what the generator is ALLOWED to say: the business name and the active
products of the brand linked to the connection (`brand_products`, the tenant's own
catalog). Nothing else is a validated source in v1 (founder decision D2): availability,
store, location and hours are in no table a tenant validated, so a reply that needs them
is always «requiere revisión».

## Provenance (why the ids are here)

A reviewer must be able to check every fact a draft relies on. So each `GroundedProduct`
carries the catalog row it came from — `product_id` and that row's `updated_at` — besides
what the model sees (name, price label, category, description). `Grounding.as_record()` is
what a draft stores (JSONB) and includes them; `Grounding.from_record()` reads a stored
record back, tolerating the records written before this change (no `product_id`, no
`updated_at`, no `currency`): they still render, with those fields empty.

`as_prompt()` deliberately does NOT show ids or timestamps to the model: they are for the
person approving, not facts to repeat.

Moved from `conversations/suggest.py`, which re-exports every name, so Conversaciones and
Fase C (followups) are unchanged.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class GroundedProduct:
    """One catalog product as the generator sees it, plus where it came from. The first
    four fields keep their historical positional order (`GroundedProduct("Gorra", "$12")`
    still builds)."""

    name: str
    price_label: str = ""
    category: str = ""
    description: str = ""
    # Provenance — None for a product built by hand (tests) or read from an old record.
    product_id: UUID | None = None
    price_amount: Decimal | None = None
    currency: str = ""
    updated_at: datetime | None = None

    def as_record(self) -> dict[str, Any]:
        return {
            "product_id": str(self.product_id) if self.product_id else None,
            "name": self.name,
            "price": self.price_label,
            "price_amount": str(self.price_amount) if self.price_amount is not None else None,
            "currency": self.currency,
            "category": self.category,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> GroundedProduct:
        """Never raises on a malformed or old record: an unreadable field is empty."""
        return cls(
            name=str(record.get("name") or ""),
            price_label=str(record.get("price") or ""),
            category=str(record.get("category") or ""),
            description=str(record.get("description") or ""),
            product_id=_uuid_or_none(record.get("product_id")),
            price_amount=_decimal_or_none(record.get("price_amount")),
            currency=str(record.get("currency") or ""),
            updated_at=_datetime_or_none(record.get("updated_at")),
        )


@dataclass(frozen=True)
class Grounding:
    """The facts a tenant has validated and the model may state. Serialized onto the
    draft (`as_record`) so a reviewer sees exactly what the model was given."""

    business_name: str | None = None
    products: tuple[GroundedProduct, ...] = ()

    @property
    def has_prices(self) -> bool:
        return any(p.price_label for p in self.products)

    def as_record(self) -> dict[str, Any]:
        return {
            "business_name": self.business_name,
            "products": [p.as_record() for p in self.products],
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any] | None) -> Grounding:
        """A stored record back into a `Grounding` — old (pre-provenance) rows included.
        Extra keys a caller merged in (`unsupported_claims`, `followup_id`) are ignored."""
        if not isinstance(record, Mapping):
            return cls()
        raw_products = record.get("products")
        products = tuple(
            GroundedProduct.from_record(p)
            for p in (raw_products if isinstance(raw_products, list) else [])
            if isinstance(p, Mapping) and str(p.get("name") or "").strip()
        )
        name = record.get("business_name")
        return cls(business_name=str(name) if name else None, products=products)

    def as_prompt(self) -> str:
        lines = [f"Nombre del negocio: {self.business_name or '(no indicado)'}"]
        if self.products:
            lines.append("Productos (nombre — precio — categoría — descripción):")
            for p in self.products:
                price = p.price_label or "precio no indicado"
                desc = p.description.strip()[:160] if p.description else ""
                lines.append(f"- {p.name} — {price} — {p.category or '-'} — {desc or '-'}")
        else:
            lines.append("Productos: ninguno validado (no afirmes nada sobre productos).")
        return "\n".join(lines)


GroundingProvider = Callable[[UUID, UUID], Grounding]
"""`(tenant_id, connection_id) -> Grounding`: resolved per draft, under RLS."""


def grounding_from_products(
    business_name: str | None, products: Sequence[Mapping[str, Any]]
) -> Grounding:
    """Build a `Grounding` from plain product dicts — the shape the composition layer
    gets from the catalog: `name`, `price_label`, `category`, `description`, and the
    provenance keys `product_id`, `price_amount`, `currency`, `updated_at` (all
    optional, so callers that pass only the first four keep working)."""
    return Grounding(
        business_name=(business_name or "").strip() or None,
        products=tuple(
            GroundedProduct(
                name=str(p.get("name", "")).strip(),
                price_label=str(p.get("price_label", "") or ""),
                category=str(p.get("category", "") or ""),
                description=str(p.get("description", "") or ""),
                product_id=_uuid_or_none(p.get("product_id")),
                price_amount=_decimal_or_none(p.get("price_amount")),
                currency=str(p.get("currency", "") or ""),
                updated_at=_datetime_or_none(p.get("updated_at")),
            )
            for p in products
            if str(p.get("name", "")).strip()
        ),
    )


def catalog_grounding_for(tenant_id: UUID, connection_id: UUID) -> Grounding:
    """The validated facts a draft may state: the brand's name and its active products
    (`brand_products`), both read under RLS, each with its id and `updated_at`. A
    connection without a brand grounds on nothing — the generator is told so and must
    not assert products. The `GroundingProvider` every assisted reply uses."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.catalog.models import BrandProduct  # noqa: PLC0415
    from qualify_api.catalog.read import price_label  # noqa: PLC0415
    from qualify_api.connections.models import SocialConnection  # noqa: PLC0415
    from qualify_api.tenancy.models import Brand  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        brand_id = session.execute(
            select(SocialConnection.brand_id).where(SocialConnection.id == connection_id)
        ).scalar_one_or_none()
        if brand_id is None:
            return Grounding()
        name = session.execute(select(Brand.name).where(Brand.id == brand_id)).scalar_one_or_none()
        rows = list(
            session.scalars(
                select(BrandProduct)
                .where(BrandProduct.brand_id == brand_id, BrandProduct.is_active.is_(True))
                .order_by(BrandProduct.position, BrandProduct.name)
            )
        )
        products = [
            {
                "product_id": p.id,
                "name": p.name,
                "price_label": price_label(p.price_amount, p.price_currency or ""),
                "price_amount": p.price_amount,
                "currency": p.price_currency or "",
                "category": p.category or "",
                "description": p.description or "",
                "updated_at": p.updated_at,
            }
            for p in rows
        ]
    return grounding_from_products(name, products)


def _uuid_or_none(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return UUID(value.strip())
        except ValueError:
            return None
    return None


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int | float | str) and str(value).strip():
        try:
            return Decimal(str(value).strip())
        except InvalidOperation:
            return None
    return None


def _datetime_or_none(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


__all__ = [
    "GroundedProduct",
    "Grounding",
    "GroundingProvider",
    "catalog_grounding_for",
    "grounding_from_products",
]
