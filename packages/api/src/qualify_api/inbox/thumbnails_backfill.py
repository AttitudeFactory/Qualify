"""Optional backfill of publication pictures for media monitored before m-24852202.

    just inbox-thumbs-backfill --tenant <uuid> --connection <uuid> [--limit 50]

Reads one `GET /{media}` per `monitored_media` row of that connection that has no stored
picture (the stored URLs would have expired), logged to the 200/hour ledger first and
never past what remains of it, and keeps the picture in R2 under the tenant prefix
(`inbox.thumbnails`). Idempotent: a re-run only reads the rows still without a picture.
Never automatic — a migration cannot call Meta, and this spends the connection's budget.

Prints a JSON line: how many were stored, failed, or left for the next run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from uuid import UUID

DEFAULT_LIMIT = 50


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tenant", type=UUID, required=True)
    parser.add_argument("--connection", type=UUID, required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be at least 1")

    from qualify_api.inbox.composition import backfill_thumbnails  # noqa: PLC0415

    result = asyncio.run(
        backfill_thumbnails(tenant_id=args.tenant, connection_id=args.connection, limit=args.limit)
    )
    sys.stdout.write(json.dumps(asdict(result)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
