"""The reels-worker's door to Postgres (ADR 42 R8, m-24854855) — `qualify_reels_worker`,
created by migration 0119, its R8 reach granted by 0122. Built like
`creative_worker.py` (ADR 41).

The weekly scheduling and the run queue need to see every business: which brands were
opened lately, in which timezone, and which run is next. `tenant_session` sees one
business. This door is the narrow exception, **without BYPASSRLS**: policies for this
role alone (`reels_worker_read`, `FOR SELECT`) and column grants let it READ only

- `brand_reel_runs`: id, tenant, brand, trigger, run_date, status, queued_at,
  started_at, attempts — never what a run read, cost or concluded;
- `brand_reel_activity`: tenant, brand, last_opened_at;
- `tenants`: id and timezone — never the name, the country or the currency;

plus 0119's grants on the two global analysis tables (ADR 44, the analysis lane). It
writes no run: it only DECIDES which brand is due and which run is next. A run leaves
this door as `(run_id, tenant_id)`, and every other read and write — enqueue, claim,
release, the run itself — goes through `tenant_session(tenant_id)`. Only
`qualify_api.referentes.reel_queue` may import this module (static test
`test_reels_worker_door_sanctity.py`).

The DSN is `QUALIFY_REELS_WORKER_DSN`; the engine is private and lazy — importing this
never opens a socket — and the session never sets `app.tenant_id`.
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
    rolls back on error."""
    with _get_engine().begin() as conn:
        session = Session(bind=conn)
        try:
            yield session
            session.flush()
        finally:
            session.close()
