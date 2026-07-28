"""Dev tenant selection for the CRM — thin adapter over `qualify_shared.dev`.

Sprint 1 has no login (deferred to QUA-66), so the operator picks which tenant they
enter as. The roster is the real `tenants` table, read through
`qualify_shared.dev.dev_available_tenants()`, which goes via `admin_session`
(BYPASSRLS) — the one sanctioned cross-tenant read, kept off the request path.

Two deliberate departures from `qualify_shared.dev`:

- `TenantChoice`, not `qualify_shared.dev.TenantOption`, is what reaches the browser.
  Every Reflex var is serialized to the client, so the DTO is a two-string whitelist.
  `id` carries the tenant uuid as `str` because a Reflex var cannot be a `UUID`;
  `tenant_uuid()` is the single place it is parsed back, immediately before it
  reaches `tenant_session()`.
- `set_dev_tenant` / `get_dev_tenant` are NOT used. They are a process-global, so two
  browser sessions would share one active tenant and the acceptance criterion
  "session A never paints tenant B" would stop being exercisable in the running app.
  The active tenant is custodied per-session in `ConnectionsState` instead — strictly
  narrower than the module global, and the same value ends up in `tenant_session`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qualify_shared.dev import dev_available_tenants


@dataclass(frozen=True)
class TenantChoice:
    """A selectable tenant, projected for the client.

    The real `Tenant` row also carries `timezone` and `currency`; neither is needed to
    pick a tenant, so neither is serialized.
    """

    id: str  # str(tenant uuid)
    label: str  # "PuntoServis (CO)"


def available_tenants() -> list[TenantChoice]:
    """The tenants the operator may enter as. Hits Postgres — call it off the event loop."""
    return [
        TenantChoice(id=str(option.id), label=f"{option.name} ({option.country})")
        for option in dev_available_tenants()
    ]


def tenant_uuid(tenant_id: str) -> UUID | None:
    """Parse a tenant id that arrived from the client.

    Returns None when the value is not a uuid at all, so the caller refuses to query
    rather than handing junk to `tenant_session`. Membership in the roster is checked
    separately by the state; this is only the parse.
    """
    try:
        return UUID(tenant_id)
    except ValueError:
        return None
