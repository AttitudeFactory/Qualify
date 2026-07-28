"""Pure tests for the dev active-tenant helper (no DB). `dev_available_tenants` needs
Postgres and is covered by a `db`-marked test in packages/api."""

from __future__ import annotations

from uuid import UUID

from qualify_shared.dev import get_dev_tenant, set_dev_tenant


def test_set_get_dev_tenant_roundtrip() -> None:
    tenant = UUID("a0000000-0000-4000-8000-000000000001")
    set_dev_tenant(tenant)
    assert get_dev_tenant() == tenant
    other = UUID("b0000000-0000-4000-8000-000000000002")
    set_dev_tenant(other)
    assert get_dev_tenant() == other
