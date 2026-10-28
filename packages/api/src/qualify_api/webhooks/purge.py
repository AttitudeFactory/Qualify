"""Explicit deletion's scoped raw-webhook step (m-24789547)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from qualify_shared.db.connection_purge import connection_purge_session
from sqlalchemy import text


def purge_connection_webhooks(
    *, tenant_id: UUID, connection_id: UUID, now: datetime | None = None
) -> bool:
    """Erase proven ownership; False means legacy has not reached original expiry.

    No platform identifiers leave the database or survive in a deletion audit.
    The core retains identifiers and retries until this step returns True.
    """
    with connection_purge_session(tenant_id) as session:
        return bool(
            session.scalar(
                text("SELECT purge_connection_meta_webhooks(:cid,:now)"),
                {"cid": connection_id, "now": now or datetime.now(UTC)},
            )
        )
