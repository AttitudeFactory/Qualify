"""The two Meta-webhook doors to Postgres (QUA-147) — `qualify_webhook` and
`qualify_webhook_worker`, both created by migration 0050.

The intake tables (`meta_webhook_deliveries`, `meta_webhook_events`) carry no `tenant_id`:
when Meta delivers an event nobody yet knows which tenant owns it. So they cannot be
reached through `tenant_session`, and isolation is by GRANT instead of by policy. Two
roles split the work so that neither holds more than its half:

- `webhook_session()` — the RECEIVER (the public, unauthenticated `POST
  /api/mentions/webhook`). `qualify_webhook` may only INSERT into the two intake tables:
  no SELECT (so no `RETURNING` and no `ON CONFLICT` target), no UPDATE, no DELETE, and no
  privilege on any other table. A compromised receiver can append, never read back.
- `webhook_worker_session()` — the PROCESSOR and the purge (`qualify_api.webhooks.worker`,
  never the request path). `qualify_webhook_worker` reads and settles the queue (the
  queue columns only — never `raw_body`/`signature_header`), deletes for retention, and
  reads five columns of `social_connections` across tenants to resolve `entry[].id`.
  It has BYPASSRLS for that one read; BYPASSRLS does not bypass GRANTs, so it can touch
  nothing else.

Neither door sets `app.tenant_id`: both are tenant-blind by design. Anything that writes
tenant data after a resolution goes back through `tenant_session(tenant_id)`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from qualify_shared.db.config import webhook_dsn, webhook_worker_dsn

# Private to the module, built lazily — importing this never opens a socket.
_webhook_engine: Engine | None = None
_webhook_worker_engine: Engine | None = None


def _get_webhook_engine() -> Engine:
    global _webhook_engine
    if _webhook_engine is None:
        _webhook_engine = create_engine(webhook_dsn(), pool_pre_ping=True)
    return _webhook_engine


def _get_webhook_worker_engine() -> Engine:
    global _webhook_worker_engine
    if _webhook_worker_engine is None:
        _webhook_worker_engine = create_engine(webhook_worker_dsn(), pool_pre_ping=True)
    return _webhook_worker_engine


@contextmanager
def webhook_session() -> Iterator[Session]:
    """Yield an INSERT-only Session on `qualify_webhook`. One transaction: commits on
    clean exit, rolls back on error — so a delivery and its changes land together or not
    at all."""
    with _get_webhook_engine().begin() as conn:
        session = Session(bind=conn)
        try:
            yield session
            session.flush()
        finally:
            session.close()


@contextmanager
def webhook_worker_session() -> Iterator[Session]:
    """Yield a Session on `qualify_webhook_worker` (queue, purge, cross-tenant resolution).
    Commits on clean exit, rolls back on error."""
    with _get_webhook_worker_engine().begin() as conn:
        session = Session(bind=conn)
        try:
            yield session
            session.flush()
        finally:
            session.close()
