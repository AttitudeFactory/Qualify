"""Structural tests over `pg_policies` (R7/R8): the SHAPE of every isolation policy, not
its behavior on any one table.

Why this exists as a separate, structural test: migrations 0001 and 0002 carry INDEPENDENT
copies of the same policy SQL (`_enable_rls` and `_enable_tenant_rls`). A functional test
proves the tables that exist today isolate correctly; nothing stops a future table from
being born with the old, pre-`NULLIF` spelling and failing open only on a reused pooled
connection — the exact defect R7 fixes. So this enumerates the live catalog and asserts the
invariant holds for EVERY tenant-scoped table, including ones added after this was written.

Same spirit as R6's role-attribute test: catch the silent structural regression that no
behavioral assertion covers.
"""

from __future__ import annotations

import pytest
from qualify_shared.db.admin import admin_session
from sqlalchemy import text

pytestmark = pytest.mark.db

# The only table that is tenant-scoped without owning a `tenant_id` column: its PK IS the
# tenant id, so its policy compares against `id`.
_TENANTS_TABLE = "tenants"

# R1: `platform_apps` registers Qualify's OWN Meta apps — global reference data that every
# tenant connects through. It must have no policy at all; forcing RLS on it would break the
# connect flow rather than isolate anything.
_GLOBAL_TABLES = frozenset({"platform_apps"})

# ADR 41 (m-24852160, `docs/seguridad-creative-worker.md` §2): the ONE deliberate
# cross-tenant policy. `creative_jobs` keeps its `tenant_isolation` and gains a permissive
# policy scoped to the generation worker's role alone (NOBYPASSRLS, column grants). Any
# other extra policy, or this one granted to another role, fails below.
_ROLE_SCOPED_EXTRAS = {"creative_jobs": {"creative_worker_claim": "{qualify_creative_worker}"}}


def _tenant_scoped_tables() -> set[str]:
    """Every public table carrying a `tenant_id` column, plus `tenants` itself."""
    with admin_session() as session:
        rows = session.execute(
            text(
                "SELECT table_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'tenant_id'"
            )
        ).all()
    return {row.table_name for row in rows} | {_TENANTS_TABLE}


def _policies() -> dict[str, list[tuple[str, str | None, str | None]]]:
    """table -> [(policyname, qual, with_check)] for the public schema."""
    with admin_session() as session:
        rows = session.execute(
            text(
                "SELECT tablename, policyname, qual, with_check FROM pg_policies "
                "WHERE schemaname = 'public'"
            )
        ).all()
    by_table: dict[str, list[tuple[str, str | None, str | None]]] = {}
    for row in rows:
        by_table.setdefault(row.tablename, []).append((row.policyname, row.qual, row.with_check))
    return by_table


def test_every_tenant_scoped_table_has_exactly_one_isolation_policy() -> None:
    policies = _policies()
    missing: list[str] = []
    for table in sorted(_tenant_scoped_tables()):
        entries = policies.get(table, [])
        extras = _ROLE_SCOPED_EXTRAS.get(table, {})
        names = [name for name, _, _ in entries if name not in extras]
        if names != ["tenant_isolation"]:
            missing.append(f"{table}: expected exactly ['tenant_isolation'], got {names}")
    assert not missing, "policy inventory drifted:\n" + "\n".join(missing)


def test_every_isolation_policy_uses_the_nullif_form() -> None:
    """Both `USING` and `WITH CHECK` must NULLIF the GUC before casting to uuid.

    Without it, a reused pooled connection reads `''` (the placeholder's reset value, not
    "undefined") and `''::uuid` RAISES instead of filtering to zero rows — failing loud and
    open-ended rather than closed.
    """
    offenders: list[str] = []
    policies = _policies()
    for table in sorted(_tenant_scoped_tables()):
        for name, qual, with_check in policies.get(table, []):
            if name in _ROLE_SCOPED_EXTRAS.get(table, {}):
                continue  # role-scoped, pinned by the test below
            for clause_name, clause in (("USING", qual), ("WITH CHECK", with_check)):
                if clause is None:
                    offenders.append(f"{table}.{name}: {clause_name} is absent")
                elif "NULLIF" not in clause.upper():
                    offenders.append(f"{table}.{name}: {clause_name} lacks NULLIF -> {clause}")
    assert not offenders, "pre-R7 policy shape found:\n" + "\n".join(offenders)


def test_tenant_scoped_tables_have_rls_enabled_and_forced() -> None:
    """ENABLE alone leaves the table OWNER exempt; FORCE closes that. (Neither subjects a
    superuser or a BYPASSRLS role — that is what the role-attribute test of R6 covers.)"""
    with admin_session() as session:
        rows = session.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r'"
            )
        ).all()
    flags = {row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in rows}
    offenders = [
        f"{table}: rowsecurity={flags.get(table)}"
        for table in sorted(_tenant_scoped_tables())
        if flags.get(table) != (True, True)
    ]
    assert not offenders, "RLS not enabled+forced:\n" + "\n".join(offenders)


def test_global_tables_have_no_policies() -> None:
    """R1 pinned structurally: `platform_apps` is global reference data, not tenant data."""
    policies = _policies()
    for table in sorted(_GLOBAL_TABLES):
        assert table not in policies, (
            f"{table} is global (R1) but carries policies {policies[table]} — "
            "RLS here would break the connect flow, not isolate anything"
        )


def test_role_scoped_extra_policies_reach_only_their_role() -> None:
    """The worker's cross-tenant policy exists, and is `TO qualify_creative_worker` only —
    never PUBLIC, never `qualify_app`."""
    with admin_session() as session:
        rows = session.execute(
            text(
                "SELECT tablename, policyname, roles::text AS roles FROM pg_policies "
                "WHERE schemaname = 'public'"
            )
        ).all()
    found = {(row.tablename, row.policyname): row.roles for row in rows}
    for table, extras in _ROLE_SCOPED_EXTRAS.items():
        for name, roles in extras.items():
            assert found.get((table, name)) == roles, f"{table}.{name}: {found.get((table, name))}"
