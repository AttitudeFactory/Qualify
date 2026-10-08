"""Register Qualify's own Meta app as the global `platform_apps` row (R1).

The OAuth callback resolves `platform_apps` by `QUALIFY_META_APP_ID`; with no row it raises
`PlatformAppMissing` and the connect flow 500s. `qualify_app` holds only SELECT on the table,
so the request path can never create the row — something with `qualify_admin` has to.

That used to be the dev seed alone, which production never runs (it creates the two test
tenants), so a fresh production database had no row and every connect attempt failed after
Meta's consent screen (2026-10-08). The registration is therefore its own idempotent step:
the seed calls `ensure_platform_app`, and production's `migrate` service runs
`python -m qualify_api.connections.platform_app` right after `bootstrap_db_roles.py` — on
every deploy, so a changed `QUALIFY_META_APP_ID` or `QUALIFY_META_API_VERSION` is picked up
without a manual step.

Only a REFERENCE to the secret is stored (`secret_ref`), never the secret itself.
"""

from __future__ import annotations

import sys

from qualify_shared.db.admin import admin_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.models import PlatformApp

SECRET_REF = "env:QUALIFY_META_APP_SECRET"


def ensure_platform_app(session: Session, settings: MetaOAuthSettings | None = None) -> str:
    """Create or refresh the row for `settings.app_id`; return what happened.

    Returns `"created"`, `"updated"` (api_version moved) or `"unchanged"`.
    """
    settings = settings or MetaOAuthSettings.from_env()
    existing = session.scalar(select(PlatformApp).where(PlatformApp.app_id == settings.app_id))
    if existing is None:
        session.add(
            PlatformApp(
                app_id=settings.app_id,
                secret_ref=SECRET_REF,
                api_version=settings.api_version,
            )
        )
        session.flush()
        return "created"
    if existing.api_version != settings.api_version:
        # Graph versions are deprecated on a calendar; keep the row current so the
        # provenance recorded against new connections is not a stale string.
        existing.api_version = settings.api_version
        session.flush()
        return "updated"
    return "unchanged"


def main() -> int:
    settings = MetaOAuthSettings.from_env()
    with admin_session() as session:
        outcome = ensure_platform_app(session, settings)
    print(f"platform_app: {outcome} app_id={settings.app_id} api_version={settings.api_version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
