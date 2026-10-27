"""The single sanctioned door to Postgres for tenant-scoped code (C-01.4).

`tenant_session(tenant_id)` is the ONLY public way to obtain a Session that touches
tenant data. It fixes the `app.tenant_id` GUC per transaction, so Row Level Security
isolates the tenant even if a query forgets its `WHERE tenant_id = ...`. The
application `Engine` (the `qualify_app` role) is private to this module — there is no
exported `get_engine`/`SessionLocal`, and a static test (C-01) fails if any repository
constructs its own Session or engine outside this module.

Why `set_config(..., is_local => true)` and not `SET LOCAL app.tenant_id = ...`:
`SET LOCAL` cannot bind parameters, which would force interpolating the tenant id into
SQL (an injection surface). `set_config(key, value, is_local => true)` is the
parameterizable equivalent and is scoped to the transaction — so when the pooled
connection is reused by the next transaction the tenant's value is already gone.

Precisely what "gone" means (R7): the value reverts, but it reverts to the placeholder's
*reset value* — the EMPTY STRING, not "undefined" — because a custom GUC stays defined
for the rest of the session once it has been set. That is exactly why the RLS policies
wrap the read in `NULLIF(current_setting('app.tenant_id', true), '')`: without it, the
`::uuid` cast of `''` raises instead of failing closed. The fail-closed guarantee lives
in the policy shape, NOT in this module resetting anything on scope exit — an explicit
reset here was considered and rejected as a redundant round-trip that would move the
guarantee away from where it is actually enforced.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from qualify_shared.db.config import app_dsn

# Private to the module. Built lazily so importing this module never opens a socket
# (tests that don't touch the DB, tooling, etc. import it freely).
_engine: Engine | None = None
_unit: ContextVar[tuple[UUID, Session] | None] = ContextVar("tenant_unit", default=None)


@contextmanager
def tenant_unit_of_work(tenant_id: UUID) -> Iterator[Session]:
    """Opt in to one transaction across repository calls (transactional outbox).

    Normal sessions remain independent. Only the owning request's context inherits
    this transaction; a different tenant is rejected before executing SQL.
    """
    with tenant_session(tenant_id) as session:
        token = _unit.set((tenant_id, session))
        try:
            yield session
        finally:
            _unit.reset(token)


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(app_dsn(), pool_pre_ping=True)
    return _engine


@contextmanager
def tenant_session(tenant_id: UUID, *, independent: bool = False) -> Iterator[Session]:
    """Yield a Session bound to a transaction with `app.tenant_id` set to `tenant_id`.

    Everything read or written inside is RLS-scoped to that tenant. The transaction
    commits on clean exit and rolls back on exception (via `Engine.begin`). Re-running
    the same work under the same tenant is safe; a write for another tenant is rejected
    by the policies' `WITH CHECK`.

    `independent=True` is reserved for runtime connection-health reports: commit that
    diagnosis even if the surrounding business operation rolls back, and publish its
    event only after this transaction commits. It uses the same tenant role and RLS.
    Call after releasing any outer row lock on that connection to avoid self-deadlock.
    """
    active = _unit.get()
    if active is not None:
        if active[0] != tenant_id:
            raise ValueError("a tenant unit of work cannot change tenant")
        if not independent:
            yield active[1]
            active[1].flush()
            return
    with _get_engine().begin() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        session = Session(bind=conn)
        try:
            yield session
            session.flush()
        finally:
            session.close()
