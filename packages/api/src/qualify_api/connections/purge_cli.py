"""Scoped deletion operations; dry-run unless --execute (m-24789547).

Run the due-job command every fifteen minutes for each configured tenant. The
29-day grace/legacy expiry leaves one day for retries before the 30-day deadline.
Never run this against production without the documented operations approval.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.connections.purge import (
    PurgeBlocked,
    purge_connection,
    request_connection_purge,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", required=True, type=UUID)
    parser.add_argument("--connection", type=UUID)
    parser.add_argument("--request", action="store_true", help="queue an explicit manual request")
    parser.add_argument("--execute", action="store_true", help="persist intent and erase due data")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    if args.request and args.connection is None:
        parser.error("--request requires --connection")
    if not 1 <= args.limit <= 1000:
        parser.error("--limit must be between 1 and 1000")
    now = datetime.now(UTC)
    if args.request:
        if not args.execute:
            print(f"dry_run manual_request connection={args.connection}")
            return 0
        request_connection_purge(tenant_id=args.tenant, connection_id=args.connection, now=now)
    with tenant_session(args.tenant) as session:
        due_filter = "AND due_at <= :now" if args.execute else ""
        rows = session.execute(
            text(f"""SELECT connection_id,status,due_at,deadline_at,last_error_code
            FROM connection_purge_requests WHERE tenant_id=:tid
              AND status IN ('scheduled','running')
              AND (CAST(:cid AS uuid) IS NULL OR connection_id=CAST(:cid AS uuid))
              {due_filter}
            ORDER BY deadline_at,connection_id LIMIT :limit"""),
            {
                "tid": args.tenant,
                "cid": str(args.connection) if args.connection else None,
                "limit": args.limit,
                "now": now,
            },
        ).all()
    failures = 0
    for row in rows:
        if not args.execute or row.due_at > now:
            print(
                f"{'dry_run' if not args.execute else 'not_due'} connection={row.connection_id} "
                f"status={row.status} due={row.due_at.isoformat()} "
                f"deadline={row.deadline_at.isoformat()} error={row.last_error_code or '-'}"
            )
            continue
        try:
            result = purge_connection(
                tenant_id=args.tenant, connection_id=row.connection_id, now=now
            )
            print(f"connection={row.connection_id} status={result.status}")
        except Exception as exc:
            code = str(exc) if isinstance(exc, PurgeBlocked) else type(exc).__name__
            print(f"connection={row.connection_id} status=retry error={code}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
