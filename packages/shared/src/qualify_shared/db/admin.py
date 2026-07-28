"""The privileged, cross-tenant door to Postgres — `qualify_admin` (BYPASSRLS).

Used ONLY by tenant provisioning and the seed: creating a `tenants` row happens when
there is no "current tenant" yet, so it is inherently cross-tenant and cannot go
through `tenant_session`. Keeping it a separate, clearly named door (never imported by
the request path) makes "create a tenant" an explicit, privileged operation rather than
a path a request handler could take by accident.

Because `qualify_admin` has BYPASSRLS, code here can read/write any tenant's rows — so
nothing on the request path may import it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from qualify_shared.db.config import admin_dsn

_admin_engine: Engine | None = None


def _get_admin_engine() -> Engine:
    global _admin_engine
    if _admin_engine is None:
        _admin_engine = create_engine(admin_dsn(), pool_pre_ping=True)
    return _admin_engine


@contextmanager
def admin_session() -> Iterator[Session]:
    """Yield a BYPASSRLS Session for provisioning/seed. No `app.tenant_id` is set —
    this door is deliberately tenant-blind. Commits on clean exit, rolls back on error.
    """
    with _get_admin_engine().begin() as conn:
        session = Session(bind=conn)
        try:
            yield session
            session.flush()
        finally:
            session.close()
