"""Tenant-scoped deletion worker door (m-24789547).

The dedicated NOBYPASSRLS role can erase connection-acquired data and credentials,
but cannot read credential ciphertext or modify authored brand assets. Request code
uses tenant_session to enqueue intent; only the purge worker uses this door.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from qualify_shared.db.config import connection_purge_dsn

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(
            connection_purge_dsn(),
            pool_pre_ping=True,
            connect_args={
                "connect_timeout": 10,
                "options": "-c statement_timeout=60000 -c lock_timeout=10000",
            },
        )
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


def discover_due_purge_tenants(*, now: datetime, after: UUID | None, limit: int) -> list[UUID]:
    """Read only due tenant IDs through the restricted discovery function (0108)."""
    with _get_engine().begin() as conn:
        return list(
            conn.scalars(
                text(
                    "SELECT tenant_id FROM public.connection_purge_due_tenants(:now,:after,:limit)"
                ),
                {"now": now, "after": after, "limit": limit},
            )
        )


@contextmanager
def connection_purge_lock(tenant_id: UUID, connection_id: UUID) -> Iterator[bool]:
    """Serialize the entire resumable erasure, including R2, across CLI/worker instances.

    A transaction advisory lock releases on disconnect/crash without a lease to repair.
    Step transactions remain independent so their durable manifest survives a failure.
    """
    with connection_purge_session(tenant_id) as session:
        acquired = session.scalar(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"connection-purge:{tenant_id}:{connection_id}"},
        )
        yield bool(acquired)
