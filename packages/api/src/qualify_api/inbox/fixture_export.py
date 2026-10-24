"""Write a LOCAL Meta-reads fixture from a connection's own rows (m-24852203).

    just inbox-fixture-export --tenant <uuid> --connection <uuid> --out <path>

Then run the app with `QUALIFY_META_READS=fixture QUALIFY_META_READS_FIXTURE=<path>`. The
file holds real data from the local database: keep it out of git. See
`qualify_api.inbox.simulator`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

from qualify_api.inbox.simulator import export_tenant_fixture, is_production


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tenant", type=UUID, required=True)
    parser.add_argument("--connection", type=UUID, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if is_production():
        parser.error("the Meta read simulator is dev-only")
    payload = export_tenant_fixture(tenant_id=args.tenant, connection_id=args.connection)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    sys.stdout.write(
        f"{len(payload['media'])} media, "
        f"{sum(len(c) for c in payload['comments'].values())} comments -> {args.out}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
