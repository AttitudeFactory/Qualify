"""Authenticated backend settings projected as display-only brand permissions."""

from __future__ import annotations

from uuid import UUID

from .ad_enhancements_vm import FEATURES, BrandEnhancementsVM


def _view(settings: object, tenant_id: UUID, brand_id: UUID) -> BrandEnhancementsVM:
    values = getattr(settings, "values")
    version = getattr(settings, "version")
    if (
        getattr(settings, "tenant_id") != tenant_id
        or getattr(settings, "brand_id") != brand_id
        or type(version) is not int
        or version < 0
        or set(values) != set(FEATURES)
        or any(type(value) is not bool for value in values.values())
    ):
        raise ValueError("invalid enhancement settings")
    return BrandEnhancementsVM(
        brand_id=str(getattr(settings, "brand_id")),
        version=version,
        values=dict(values),
        loaded=True,
    )


def load_policy(tenant_id: UUID, brand_id: UUID) -> BrandEnhancementsVM:
    from qualify_api.ads.enhancements_service import load_brand_enhancements

    return _view(
        load_brand_enhancements(tenant_id=tenant_id, brand_id=brand_id), tenant_id, brand_id
    )


def save_policy(
    tenant_id: UUID, brand_id: UUID, values: dict[str, bool], version: int
) -> BrandEnhancementsVM:
    from qualify_api.ads.enhancements_service import save_brand_enhancements

    return _view(
        save_brand_enhancements(
            tenant_id=tenant_id, brand_id=brand_id, values=values, expected_version=version
        ),
        tenant_id,
        brand_id,
    )
