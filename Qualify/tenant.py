"""Tenant-id parsing for the CRM states.

This module used to be the dev tenant selector (roster + per-session choice). QUA-66
replaced that with real login: the active tenant is custodied by `AuthState`, set only
by `resolve_login`, and there is no switch (`1 login = 1 tenant = 1 negocio`, founder
ruling 2026-08-16). What remains here is the one function every state still needs:
the single place a tenant id that transited the client (as `str`, because a Reflex var
cannot be a `UUID`) is parsed back, immediately before it reaches `tenant_session()`.
"""

from __future__ import annotations

from uuid import UUID


def tenant_uuid(tenant_id: str) -> UUID | None:
    """Parse a tenant id that arrived from session state.

    Returns None when the value is not a uuid at all, so the caller refuses to query
    rather than handing junk to `tenant_session`.
    """
    try:
        return UUID(tenant_id)
    except ValueError:
        return None
