"""`db`-marked test for the dev tenant picker source: `dev_available_tenants` must list
every tenant (a legitimate cross-tenant read via the admin door)."""

from __future__ import annotations

from uuid import UUID

import pytest
from qualify_shared.dev import dev_available_tenants

pytestmark = pytest.mark.db


def test_dev_available_tenants_lists_all(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = seeded_ab
    listed = {option.id for option in dev_available_tenants()}
    assert {tenant_a, tenant_b} <= listed
