"""Backend access for «Publicación del mes» (m-25120704). Call inside `acting_login`."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from qualify_api.creative.creations import quota_for
from qualify_api.planner.monthly_post import (
    MonthlyPostSetting,
    get_monthly_post_setting,
    set_monthly_post_setting,
)
from qualify_creative.creations import load_weights

from .catalog_provider import list_products
from .investment_profile_provider import brand_for
from .monthly_post_vm import product_rows
from .settings_provider import read_plan


def _brand(tenant_id: UUID, cached: str) -> UUID:
    brand = brand_for(tenant_id, cached)
    if brand is None:
        raise LookupError("the business has no brand yet")
    return brand


def read_setting(tenant_id: UUID, cached_brand: str) -> MonthlyPostSetting:
    return get_monthly_post_setting(tenant_id, _brand(tenant_id, cached_brand))


def template_products(tenant_id: UUID, cached_brand: str) -> list[dict[str, str]]:
    """The brand's active products with a photo, for «Con plantilla»'s picker."""
    return product_rows(list_products(tenant_id, _brand(tenant_id, cached_brand)))


def save_setting(
    tenant_id: UUID, cached_brand: str, enabled: bool, kind: str, product_id: str = ""
) -> MonthlyPostSetting:
    brand = _brand(tenant_id, cached_brand)
    return set_monthly_post_setting(tenant_id, brand, enabled, kind, product_id or None)


def monthly_creations(tenant_id: UUID, cached_brand: str) -> int:
    """The month's creations of the business's plan (`quota_for`, the one place the
    quota is decided); 0 for a plan with no monthly limit."""
    quota = quota_for(
        tenant_id=tenant_id,
        brand_id=_brand(tenant_id, cached_brand),
        period=date.today(),  # quota_for ignores it: the plan already is this month's
        weights=load_weights(),
        plan=read_plan(tenant_id),
    )
    return 0 if quota.unlimited else quota.creations
