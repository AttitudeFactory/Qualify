"""Backend access for «Publicación del mes» (m-25120704). Call inside `acting_login`."""

from __future__ import annotations

from uuid import UUID

from qualify_api.planner.monthly_post import (
    MonthlyPostSetting,
    get_monthly_post_setting,
    set_monthly_post_setting,
)

from .investment_profile_provider import brand_for


def _brand(tenant_id: UUID, cached: str) -> UUID:
    brand = brand_for(tenant_id, cached)
    if brand is None:
        raise LookupError("the business has no brand yet")
    return brand


def read_setting(tenant_id: UUID, cached_brand: str) -> MonthlyPostSetting:
    return get_monthly_post_setting(tenant_id, _brand(tenant_id, cached_brand))


def save_setting(
    tenant_id: UUID, cached_brand: str, enabled: bool, kind: str
) -> MonthlyPostSetting:
    return set_monthly_post_setting(tenant_id, _brand(tenant_id, cached_brand), enabled, kind)
