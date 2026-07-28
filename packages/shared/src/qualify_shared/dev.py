"""Development-only active-tenant selection for the CRM (C-01), used until real auth
lands. The Reflex UI reads `dev_available_tenants()` to render a picker, calls
`set_dev_tenant(id)` when the operator chooses one, and threads that id through
`tenant_session(...)`. The active tenant NEVER comes from a URL parameter.

This is a dev crutch, not production auth: the selection is process-local (a module
global), so it is unsuitable for a real multi-user server. Real session-derived tenancy
replaces `get_dev_tenant` when authentication exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text

from qualify_shared.db.admin import admin_session


@dataclass(frozen=True)
class TenantOption:
    """Minimal tenant descriptor for the dev picker. Carries no credential-ish data —
    just enough to identify and label a tenant."""

    id: UUID
    name: str
    country: str


# Process-local active tenant. Not thread/session safe by design (dev only).
_dev_tenant: UUID | None = None


def dev_available_tenants() -> list[TenantOption]:
    """List all tenants for the dev picker. Inherently cross-tenant, so it reads
    through `admin_session` (BYPASSRLS) — the one legitimate cross-tenant read, kept off
    the request path."""
    with admin_session() as session:
        rows = session.execute(text("SELECT id, name, country FROM tenants ORDER BY name")).all()
    return [TenantOption(id=row.id, name=row.name, country=row.country) for row in rows]


def set_dev_tenant(tenant_id: UUID) -> None:
    """Set the active dev tenant (what the CRM's `session_tenant_id` will point at)."""
    global _dev_tenant
    _dev_tenant = tenant_id


def get_dev_tenant() -> UUID | None:
    """Return the active dev tenant, or None if none has been selected yet."""
    return _dev_tenant
