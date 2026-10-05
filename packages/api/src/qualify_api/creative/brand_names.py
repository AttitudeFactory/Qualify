"""The brand's display name for a composition (`props.brand.name`, CONTRACT §2) — read
through the tenant door, nothing else. Kept apart from `BrandKitService` because the kit
deliberately carries no name (the kit is voice and look; the name is tenancy's)."""

from __future__ import annotations

from uuid import UUID

from qualify_shared.db.session import tenant_session

from qualify_api.tenancy.models import Brand


class DbBrandNames:
    def __call__(self, *, tenant_id: UUID, brand_id: UUID) -> str:
        with tenant_session(tenant_id) as session:
            brand = session.get(Brand, brand_id)
            return str(brand.name) if brand is not None and brand.name else ""
