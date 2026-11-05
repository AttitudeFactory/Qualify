"""The reels-worker's door to Postgres — `qualify_reels_worker`, created by migration 0119
(ADR 44 F5, VE-04a m-24921056), its R8 reach granted by 0124 (ADR 42 R8, m-24854855).
Built like `creative_worker.py` (ADR 41). NOBYPASSRLS, and this session never sets
`app.tenant_id`: a GRANT added by mistake on a tenant table still meets RLS. Two uses:

- **The shared reel analyses** (0119): SELECT, INSERT, UPDATE, DELETE on the two GLOBAL
  tables `public_reel_analyses` / `public_reel_analysis_shots` (no `tenant_id`, no RLS —
  the signed exception of 0119). The screen may only enqueue (column grants to
  `qualify_app`); the RESULT — status, sheet, R2 keys, cost — is written by this role alone,
  so no business can forge an `ok` every other business reads. The 30-day purge of the
  stored sources (`reel_retention`, through `PostgresAnalysisQueue`) marks its dates here
  too (ADR 44 F9).
- **The weekly scheduling and the run queue** (0124): READ only, through policies for this
  role alone (`reels_worker_read`, `FOR SELECT`) and column grants —
  - `brand_reel_runs`: id, tenant, brand, trigger, run_date, status, queued_at,
    started_at, attempts — never what a run read, cost or concluded;
  - `brand_reel_activity`: tenant, brand, last_opened_at;
  - `tenants`: id and timezone — not the name, the `country` column or the currency (for
    our markets a timezone tells the country, so that is what the role learns).
  It writes no run: a run leaves this door as `(run_id, tenant_id)`, and every read and
  write about a business (enqueue, claim, release, the run itself) goes through
  `tenant_session(tenant_id)`.

Only `qualify_api.referentes.reel_analysis_queue`, `…reel_analysis_worker` and
`…reel_queue` may import this module (static test `test_reel_analysis_door_sanctity.py`).
In production the role is NOLOGIN until `QUALIFY_DB_REELS_WORKER_PASSWORD` is set
(`deploy/bootstrap_db_roles.py`).

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
