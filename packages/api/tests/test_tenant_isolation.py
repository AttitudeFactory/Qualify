"""C-01.5 isolation tests — they assert "tenant A cannot read/write tenant B", not
merely "a policy exists". They run as `qualify_app` (subject to RLS); running as owner
or admin would bypass RLS and make the assertions vacuous."""

from __future__ import annotations

from uuid import UUID

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.engine import Engine

from qualify_api.tenancy.models import Brand

pytestmark = pytest.mark.db


def test_tenant_a_cannot_read_tenant_b(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = seeded_ab
    with tenant_session(tenant_a) as session:
        # No explicit WHERE — RLS is the only thing scoping this.
        seen = {brand.tenant_id for brand in session.scalars(select(Brand)).all()}
    assert seen == {tenant_a}  # positive guarantee
    assert tenant_b not in seen  # the guarantee that matters: zero rows of B


def test_unset_guc_reads_zero_rows(seeded_ab: tuple[UUID, UUID], app_engine: Engine) -> None:
    # Fail-closed on a PRISTINE connection: the GUC has never been set, so
    # current_setting(..., true) is NULL → tenant_id = NULL is NULL → every row filtered.
    with app_engine.begin() as conn:
        count = conn.execute(text("SELECT count(*) FROM brands")).scalar_one()
    assert count == 0


def test_guc_does_not_bleed_across_pooled_transactions(
    seeded_ab: tuple[UUID, UUID], app_engine: Engine
) -> None:
    tenant_a, _ = seeded_ab
    # Reuse a SINGLE physical connection across two transactions. set_config(is_local=>
    # true) is transaction-scoped, so the second transaction must NOT inherit tenant A.
    with app_engine.connect() as conn:
        with conn.begin():
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_a)},
            )
            scoped = conn.execute(text("SELECT count(*) FROM brands")).scalar_one()
        with conn.begin():
            leaked = conn.execute(text("SELECT count(*) FROM brands")).scalar_one()
    # Other DB tests can add brands to this shared tenant. The scoped transaction
    # must see its brands; the next transaction must see none of them.
    assert scoped > 0
    assert leaked == 0  # GUC gone on reuse → fail-closed, no bleed


def test_reset_guc_is_empty_string_not_null(
    seeded_ab: tuple[UUID, UUID], app_engine: Engine
) -> None:
    """Pin the Postgres behavior the whole `NULLIF` fix rests on (R7).

    A custom GUC stays DEFINED for the rest of the session once set; ending the
    transaction reverts it to the placeholder's *reset value*, which is `''` — NOT
    "undefined". This is the permanent regime for any pooled connection, and it is why
    the policies cannot cast `current_setting(...)` straight to uuid. Asserted directly so
    a future Postgres version that changes it breaks HERE, loudly, instead of silently
    making the policies' NULLIF look like dead weight someone later removes.
    """
    tenant_a, _ = seeded_ab
    with app_engine.connect() as conn:
        with conn.begin():
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_a)},
            )
        with conn.begin():
            after = conn.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar_one()
    assert after == "", f"expected the reset value to be the empty string, got {after!r}"


def test_cannot_write_other_tenant(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = seeded_ab
    # WITH CHECK blocks inserting a row for another tenant under tenant A's GUC.
    with pytest.raises(Exception):  # noqa: B017 - RLS raises a DB error subclass
        with tenant_session(tenant_a) as session:
            session.add(Brand(tenant_id=tenant_b, name="smuggled"))
            session.flush()
