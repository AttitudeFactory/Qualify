"""One readonly results tick for an explicitly selected tenant."""

from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from qualify_api.ads.results_service import poll_promotion_results


def main() -> None:
    parser = argparse.ArgumentParser(description="Consultar resultados de promociones en Meta")
    parser.add_argument("--tenant", required=True, type=UUID)
    parser.add_argument("--limit", default=100, type=int)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(poll_promotion_results(tenant_id=args.tenant, limit=args.limit))))


if __name__ == "__main__":
    main()
