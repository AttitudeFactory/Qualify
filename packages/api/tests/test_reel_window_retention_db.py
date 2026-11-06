"""`db` test for VE-12 RA5 (m-24921060, `referentes.reel_window_retention`) against the
live schema: the production discovery (`all_tenant_ids`, `admin_session`) returns every
business id and nothing but ids. The purge itself reads no draft row — each business's
`reel-windows/{tenant}/` root is listed by the cut's own age — so nothing else of the
database is in play (offline tests in `test_reel_window_retention.py`)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session

from qualify_api.referentes import reel_window_retention as wr
from qualify_api.tenancy.models import Tenant

pytestmark = pytest.mark.db


def _tenant() -> UUID:
    tenant = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name="VE-12 windows",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
    return tenant


def test_discovery_returns_every_business_id_and_only_ids() -> None:
    a, b = _tenant(), _tenant()
    found = wr.all_tenant_ids(datetime.now(UTC))
    assert all(isinstance(t, UUID) for t in found)
    assert {a, b} <= set(found)
    assert len(found) == len(set(found))
