"""The business location «Cerca de mi negocio» starts from (m-25038694, migration 0169).

One point per business, on `tenants`. Saving it is manual input the owner approves, so its
provenance is who saved it and when. Coordinates are never logged.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.audience import AudienceUnavailable

_UNREADABLE = "No pudimos leer la ubicación de tu negocio."


def business_point(latitude: object, longitude: object) -> tuple[float, float]:
    """Two finite, in-range numbers rounded to 6 decimals (what `MapPoint` accepts)."""
    result = []
    for value, limit in ((latitude, 90), (longitude, 180)):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise AudienceUnavailable(_UNREADABLE)
        number = float(value)
        if not math.isfinite(number) or not -limit <= number <= limit:
            raise AudienceUnavailable(_UNREADABLE)
        result.append(round(number, 6) + 0.0)  # + 0.0 turns -0.0 into 0.0
    return result[0], result[1]


def get_business_location(tenant_id: UUID) -> tuple[float, float] | None:
    """The saved (latitude, longitude), or None when the business has none yet."""
    with tenant_session(tenant_id, independent=True) as session:
        row = session.execute(
            text("SELECT business_latitude, business_longitude FROM tenants WHERE id = :id"),
            {"id": tenant_id},
        ).one_or_none()
    if row is None or row[0] is None:
        return None
    return float(row[0]), float(row[1])


def save_business_location(
    tenant_id: UUID, user_id: UUID, latitude: object, longitude: object
) -> tuple[float, float]:
    """Validate, round and save the point (replacing the last one); returns what was stored.

    Raises `AudienceUnavailable` (safe Spanish message) for an impossible point and
    `ValueError` when the user is not of this business."""
    point = business_point(latitude, longitude)
    with tenant_session(tenant_id, independent=True) as session:
        if not session.execute(
            text("SELECT 1 FROM users WHERE id = :id"), {"id": user_id}
        ).scalar():
            raise ValueError("user is outside the tenant")
        updated = session.execute(
            text(
                "UPDATE tenants SET business_latitude = :lat, business_longitude = :lng,"
                " business_location_set_by = :user, business_location_set_at = :at"
                " WHERE id = :id"
            ),
            {
                "lat": point[0],
                "lng": point[1],
                "user": user_id,
                "at": datetime.now(UTC),
                "id": tenant_id,
            },
        ).rowcount
        if updated != 1:
            raise ValueError("tenant not found")
    return point
