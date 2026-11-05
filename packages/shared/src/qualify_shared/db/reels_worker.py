"""The shared reel analyses' door to Postgres (ADR 44 F5, m-24921056 VE-04a) —
`qualify_reels_worker`, created by migration 0119.

A reel's analysis is public data, done once for every business (`public_reel_analyses`,
`public_reel_analysis_shots`: no `tenant_id`, no RLS — the signed exception of 0119). The
screen may only enqueue (column grants to `qualify_app`); the RESULT — status, sheet, R2
keys, cost — is written by this role alone, so no business can forge an `ok` every other
business would read. Its reach, all of it granted by 0119: SELECT, INSERT, UPDATE, DELETE
on those two tables. NOBYPASSRLS, so a GRANT added by mistake on a tenant table still
meets RLS with no `app.tenant_id` set — this session never sets it.

Only `qualify_api.referentes.reel_analysis_queue` and `…reel_analysis_worker` may import
this module (static test `test_reel_analysis_door_sanctity.py`). In production the role is
NOLOGIN until R8 (m-24854855) sets `QUALIFY_DB_REELS_WORKER_PASSWORD`.

The DSN is `QUALIFY_REELS_WORKER_DSN`; the engine is private and lazy — importing this
never opens a socket.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from qualify_shared.db.config import reels_worker_dsn

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(reels_worker_dsn(), pool_pre_ping=True)
    return _engine


@contextmanager
def reels_worker_session() -> Iterator[Session]:
    """Yield a Session on `qualify_reels_worker`. One transaction: commits on clean exit,
    rolls back on error — a result and its shots land together or not at all."""
    with _get_engine().begin() as conn:
        session = Session(bind=conn)
        try:
            yield session
            session.flush()
        finally:
            session.close()
