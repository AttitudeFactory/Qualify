"""Fresh member/brand checks and compare-and-swap settings; no calls to Meta."""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.enhancements import (
    BrandEnhancementSettings,
    EnhancementsUnavailable,
    normalize,
)
from qualify_api.tenancy.acting import current_acting_login, require_acting_member


def _member(tenant_id: UUID) -> UUID:
    login = current_acting_login()
    if login is None:
        raise EnhancementsUnavailable("Vuelve a iniciar sesiÃ³n para revisar tu marca.")
    require_acting_member(tenant_id)
    return login


def read_policy(session: object, tenant_id: UUID, brand_id: UUID) -> BrandEnhancementSettings:
    """Internal approval path shares its transaction and brand lock with the caller."""
    brand = session.execute(
        text("SELECT id FROM brands WHERE id=:id FOR SHARE"), {"id": brand_id}
    ).scalar_one_or_none()
    if brand is None:
        raise EnhancementsUnavailable("Esta marca ya no estÃ¡ disponible en este negocio.")
    row = (
        session.execute(
            text(
                "SELECT version,feature_flags,updated_at FROM ad_brand_enhancements "
                "WHERE brand_id=:id"
            ),
            {"id": brand_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return BrandEnhancementSettings(tenant_id, brand_id)
    return BrandEnhancementSettings(
        tenant_id, brand_id, row["version"], normalize(row["feature_flags"]), row["updated_at"]
    )


def load_brand_enhancements(*, tenant_id: UUID, brand_id: UUID) -> BrandEnhancementSettings:
    _member(tenant_id)
    with tenant_session(tenant_id, independent=True) as session:
        result = read_policy(session, tenant_id, brand_id)
    _member(tenant_id)
    return result


def save_brand_enhancements(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    values: dict[str, bool],
    expected_version: int,
) -> BrandEnhancementSettings:
    actor = _member(tenant_id)
    values = normalize(values)
    if type(expected_version) is not int or expected_version < 0:
        raise EnhancementsUnavailable("Vuelve a cargar los permisos antes de guardarlos.")
    with tenant_session(tenant_id, independent=True) as session:
        # Serialize first saves and updates against approval's shared brand lock.
        brand = session.execute(
            text("SELECT id FROM brands WHERE id=:id FOR UPDATE"), {"id": brand_id}
        ).scalar_one_or_none()
        if brand is None:
            raise EnhancementsUnavailable("Esta marca ya no estÃ¡ disponible en este negocio.")
        current = read_policy(session, tenant_id, brand_id)
        if current.version != expected_version:
            raise EnhancementsUnavailable(
                "Otra persona cambiÃ³ estos permisos. Vuelve a cargarlos antes de guardar."
            )
        if current.values == values:
            return current
        _member(tenant_id)
        row = session.execute(
            text("""
            INSERT INTO ad_brand_enhancements
                (tenant_id,brand_id,version,feature_flags,updated_by,pipeline_version)
            VALUES (:tenant,:brand,:version,CAST(:values AS jsonb),:actor,'ad-enhancements-v1')
            ON CONFLICT (brand_id) DO UPDATE SET version=EXCLUDED.version,
                feature_flags=EXCLUDED.feature_flags,updated_by=EXCLUDED.updated_by,updated_at=now()
            RETURNING updated_at
        """),
            {
                "tenant": tenant_id,
                "brand": brand_id,
                "version": current.version + 1,
                "values": json.dumps(values),
                "actor": actor,
            },
        ).scalar_one()
        return replace(current, version=current.version + 1, values=values, updated_at=row)
