"""The open business's logo for the sidebar's top row (alternative B, m-24976899).

Reads the main logo of the tenant's Brand Kit (`brand_kits.logo_asset_key`, chosen by
`MAIN_LOGO_ORDER` when the kit is saved) through `tenant_session` (inside
`BrandKitService`) and mints its short-lived `/r2media/<token>` path. Read-only: it
never writes or deletes anything in R2. Blocking — call it through `asyncio.to_thread`.

Only the CURRENT business: the «Cambiar de negocio» list shows the store icon for the
others (no cross-tenant read here).
"""

from __future__ import annotations

import logging
from uuid import UUID

logger = logging.getLogger(__name__)


def business_logo_path(tenant_id: UUID) -> str:
    """`/r2media/<token>` of the business's main logo, or "" when it has none (or the
    logo is not an R2 object of this tenant, or the token store is down) — the sidebar
    then shows the store icon."""
    # Lazy: the creative stack is heavy and imports AuthState's module itself.
    from qualify_api.creative.brand_service import BrandKitService  # noqa: PLC0415

    from .brand_finish import content_type_of  # noqa: PLC0415
    from .creative_provider import default_brand_id  # noqa: PLC0415
    from .r2_media import issue_view_path  # noqa: PLC0415

    brand_id = default_brand_id(tenant_id)
    if brand_id is None:
        return ""
    kit = BrandKitService().get_kit(tenant_id=tenant_id, brand_id=brand_id)
    key = getattr(kit, "logo_asset_key", None) if kit is not None else None
    if not key:
        return ""
    try:
        return issue_view_path(tenant_id, key, "image", content_type_of(key, "image/png"))
    except Exception as exc:  # Redis down: the store icon stands in
        logger.warning("business logo path not issued: %s", type(exc).__name__)
        return ""


__all__ = ["business_logo_path"]
