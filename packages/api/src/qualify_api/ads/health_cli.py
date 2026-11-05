"""Daily read-only health tick. No Meta write method is reachable from this module."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from qualify_api.ads.account_health import refresh_daily_account_health


def main() -> None:
    parser = argparse.ArgumentParser(description="Consultar salud de cuentas de anuncios")
    parser.add_argument("--tenant", type=UUID, required=True)
    args = parser.parse_args()
    rows = asyncio.run(refresh_daily_account_health(tenant_id=args.tenant))
    # No account identifiers, payloads, money or credentials in the operational summary.
    print(json.dumps({"checked": len(rows), "blocked": sum(not r.can_promote for r in rows)}))


if __name__ == "__main__":
    main()
