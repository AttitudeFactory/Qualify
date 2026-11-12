"""Scoped adapters for custom audiences; the backend owns all authorizations."""

from __future__ import annotations

import asyncio
from uuid import UUID

from qualify_api.ads.custom_audience_service import (
    create_custom_audience,
    list_custom_audiences,
)
from qualify_api.ads.custom_audiences import CustomAudienceRequest, CustomAudienceSummary

from .ad_custom_audiences_vm import CustomAudienceCatalogVM, CustomAudienceVM


def _row(row: CustomAudienceSummary) -> CustomAudienceVM:
    return CustomAudienceVM(
        local_id=str(row.id),
        meta_id=row.meta_audience_id,
        name=row.name,
        kind=row.kind,
        available=row.available,
        notice=row.reason,
    )


def read_custom_audiences(scope: dict[str, UUID]) -> CustomAudienceCatalogVM:
    catalog = asyncio.run(list_custom_audiences(**scope))
    return CustomAudienceCatalogVM(
        loaded=True,
        terms_accepted=catalog.terms_accepted is True,
        creation_available=catalog.creation_available is True,
        notice=catalog.reason,
        audiences=[_row(row) for row in catalog.audiences],
    )


def request_custom_audience(
    scope: dict[str, UUID],
    *,
    name: str,
    kind: str,
    retention_days: int,
    seed_id: str,
    country: str,
    request_key: str,
    confirmed: bool,
) -> CustomAudienceVM:
    request = CustomAudienceRequest(
        name=name.strip(),
        kind=kind,
        retention_days=retention_days,
        seed_id=seed_id,
        country=country,
        ratio=0.01,
    )
    return _row(
        asyncio.run(
            create_custom_audience(
                **scope,
                request=request,
                request_key=UUID(request_key),
                confirmed=confirmed,
            )
        )
    )
