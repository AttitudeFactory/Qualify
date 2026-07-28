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
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from qualify_shared.db.config import app_dsn

# Private to the module. Built lazily so importing this module never opens a socket
# (tests that don't touch the DB, tooling, etc. import it freely).
_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(app_dsn(), pool_pre_ping=True)
    return _engine


@contextmanager
def tenant_session(tenant_id: UUID) -> Iterator[Session]:
    """Yield a Session bound to a transaction with `app.tenant_id` set to `tenant_id`.

    Everything read or written inside is RLS-scoped to that tenant. The transaction
    commits on clean exit and rolls back on exception (via `Engine.begin`). Re-running
    the same work under the same tenant is safe; a write for another tenant is rejected
    by the policies' `WITH CHECK`.
    """
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
