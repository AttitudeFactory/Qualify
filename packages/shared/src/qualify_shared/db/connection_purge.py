"""Tenant-scoped deletion worker door (m-24789547).

The dedicated NOBYPASSRLS role can erase connection-acquired data and credentials,
but cannot read credential ciphertext or modify authored brand assets. Request code
uses tenant_session to enqueue intent; only the purge worker uses this door.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from qualify_shared.db.config import connection_purge_dsn

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(connection_purge_dsn(), pool_pre_ping=True)
    return _engine


@contextmanager
def connection_purge_session(tenant_id: UUID) -> Iterator[Session]:
    """Commit one deletion step, always under the supplied tenant's forced RLS."""
    with _get_engine().begin() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        session = Session(bind=conn)
        try:
            yield session
            session.flush()
        finally:
            session.close()
