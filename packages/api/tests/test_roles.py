"""C-01 structural role test (QUA-13 finding): FORCE ROW LEVEL SECURITY does NOT subject
a superuser or a BYPASSRLS role, so the isolation guarantee rests entirely on
`qualify_app` being neither. Without this test a stray role-attribute change (grant
BYPASSRLS, make it superuser) would silently void isolation and no functional test would
catch it."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.db


def test_qualify_app_is_not_superuser_and_not_bypassrls(app_engine: Engine) -> None:
    with app_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'qualify_app'")
        ).one()
    assert row.rolsuper is False, "qualify_app must not be superuser (would bypass RLS)"
    assert row.rolbypassrls is False, "qualify_app must not have BYPASSRLS"


def test_qualify_admin_has_bypassrls(app_engine: Engine) -> None:
    # The provisioning/seed role is deliberately cross-tenant.
    with app_engine.connect() as conn:
        row = conn.execute(
            text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'qualify_admin'")
        ).one()
    assert row.rolbypassrls is True
    assert row.rolsuper is False
