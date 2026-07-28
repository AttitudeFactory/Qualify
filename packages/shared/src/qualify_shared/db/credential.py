"""The third sanctioned door to Postgres — `qualify_credential`, the ONLY role granted
`oauth_credentials.ciphertext`/`key_id` (R3).

This exists so the `CredentialResolver` can decrypt in memory without `qualify_app` ever
holding the privilege to read a token at all. The separation is structural, not
disciplinary: `qualify_app`'s column grant deliberately excludes those two columns, so an
application query for `ciphertext` gets `permission denied` from Postgres rather than a
code-review comment.

Two properties make this narrow door safe rather than a hole in the wall:

- `qualify_credential` is `NOSUPERUSER NOBYPASSRLS` and is not the tables' owner, so it is
  fully subject to RLS. It can only ever decrypt within the tenant whose GUC is set — the
  same isolation `tenant_session` gets, on a role that can read strictly less.
- The GUC is fixed per transaction exactly as in `tenant_session`, via the parameterizable
  `set_config(..., is_local => true)` rather than `SET LOCAL` (which cannot bind
  parameters, so it would force interpolating the tenant id into SQL).

Nothing here returns credential material. It hands out a Session; the only sanctioned
consumer is `qualify_api.connections.credential_reader`, which reads the ciphertext and
passes it straight to the resolver's in-memory decrypt.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from qualify_shared.db.config import credential_dsn

# Private to the module, built lazily — importing this never opens a socket.
_credential_engine: Engine | None = None


def _get_credential_engine() -> Engine:
    global _credential_engine
    if _credential_engine is None:
        _credential_engine = create_engine(credential_dsn(), pool_pre_ping=True)
    return _credential_engine


@contextmanager
def credential_session(tenant_id: UUID) -> Iterator[Session]:
    """Yield an RLS-scoped Session on the `qualify_credential` role.

    Same transactional GUC discipline as `tenant_session`, and the same fail-closed
    behavior: the policies wrap the GUC read in `NULLIF(..., '')`, so a reused pooled
    connection whose GUC has reverted to the empty string filters to zero rows instead of
    raising on the uuid cast.
    """
    with _get_credential_engine().begin() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        session = Session(bind=conn)
        try:
            yield session
        finally:
            session.close()
