"""The generation queue's door to Postgres (ADR 41, m-24852160) — `qualify_creative_worker`,
created by migration 0096.

BytePlus's concurrency cap (10 Seedance 2.5 tasks, 1 OmniHuman task) belongs to the ONE
vendor account, not to a business, so sharing it fairly means seeing the queue of every
business. `tenant_session` sees one. This door is the narrow exception, shaped like
`webhook_worker_session` (0050) but **without BYPASSRLS**
(`docs/seguridad-creative-worker.md` §2):

- `creative_jobs`: a policy for this role alone lets it see every row, but its column
  GRANTs stop at the queue — id, tenant, kind, pool, lane, status, priority, schedule,
  claim and lease, attempts, `vendor_task_id`. Never the piece, the provenance or the
  result. It may UPDATE only `status`, `claimed_by`, `claim_token`, `lease_until` and
  `attempts`: no INSERT (it cannot spend), no DELETE, never `vendor_task_id`.
- `vendor_slots`: SELECT and UPDATE — the semaphore only this role moves.
- Nothing else; a GRANT added by mistake still meets RLS with no `app.tenant_id` set.

The door decides ORDER only. A claimed job leaves this door as `(job_id, tenant_id,
claim_token)`, and everything about its content goes through
`tenant_session(job.tenant_id)`. Only `qualify_api.creative.worker` may import this module
(static test `test_creative_worker_door_sanctity.py`).

The DSN is `QUALIFY_CREATIVE_WORKER_DSN`; the engine is private and lazy — importing this
never opens a socket — and the session never sets `app.tenant_id`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from qualify_shared.db.config import creative_worker_dsn

_engine: Engine | None = None


def _get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(creative_worker_dsn(), pool_pre_ping=True)
    return _engine


@contextmanager
def creative_worker_session() -> Iterator[Session]:
    """Yield a Session on `qualify_creative_worker`. One transaction: commits on clean exit,
    rolls back on error — a claim takes its job and its slot together or not at all."""
    with _get_engine().begin() as conn:
        session = Session(bind=conn)
        try:
            yield session
            session.flush()
        finally:
            session.close()
