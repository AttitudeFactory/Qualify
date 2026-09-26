"""`just classify-hashtags` — classify, with Claude, the catalog hashtags the rules left
open (`unknown`, or a topic with no niche). The wizard already does one batch after each
search (`hashtag_catalog.classify_pending`); this drains the backlog in one go.

    just classify-hashtags --dry-run          # how many are pending, and which
    just classify-hashtags --max-batches 10   # spends ~$0.005 per batch of 80 (Haiku 4.5)

The catalog is shared and carries no tenant: a tenant id is needed only as the key to the
sanctioned DB door (`tenant_session`), so the first tenant is used unless `--tenant` says
otherwise. Reads `QUALIFY_ANTHROPIC_API_KEY` from the environment or `.env`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID

from qualify_api.hashtags import ai as hashtag_ai

from . import hashtag_catalog
from .refresh_referentes import all_tenant_ids

DEFAULT_MAX_BATCHES = 10


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)


def main(
    argv: Sequence[str] | None = None,
    *,
    tenants: Callable[[], list[UUID]] = all_tenant_ids,
    out: Callable[[str], None] = print,
) -> int:
    parser = argparse.ArgumentParser(
        prog="classify-hashtags",
        description="Classify the hashtag catalog's pending tags with Claude.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list what is pending; spend nothing"
    )
    parser.add_argument("--max-batches", type=int, default=DEFAULT_MAX_BATCHES)
    parser.add_argument("--tenant", type=UUID, default=None)
    args = parser.parse_args(argv)

    tenant_ids = [args.tenant] if args.tenant else tenants()
    if not tenant_ids:
        out("No hay ningún tenant: nada que usar como sesión.")
        return 1
    tenant_id = tenant_ids[0]
    repo = hashtag_catalog.REPOSITORY
    pending = repo.needs_classification(tenant_id, limit=100_000)
    batch = hashtag_ai.CLASSIFY_BATCH
    out(f"{len(pending)} hashtag(s) pendientes de clasificar ({-(-len(pending) // batch)} lotes).")
    if args.dry_run:
        out(
            "  " + " ".join(f"#{t.tag}" for t in pending[:40]) + (" …" if len(pending) > 40 else "")
        )
        out("--dry-run: no se gastó nada.")
        return 0

    _load_dotenv()
    changed = 0
    cost = 0.0
    for _ in range(args.max_batches):
        summary = hashtag_catalog.classify_pending(tenant_id, repository=repo)
        if summary.asked == 0:
            break
        changed += summary.changed
        cost += summary.cost_usd
        out(f"  lote: {summary.changed}/{summary.asked} clasificados · ${summary.cost_usd:.4f}")
        if summary.changed == 0:
            out("  el último lote no cambió nada (¿falta la API key o falló la llamada?).")
            break
    left = len(repo.needs_classification(tenant_id, limit=100_000))
    out(f"Listo: {changed} clasificados · ${cost:.4f} · quedan {left} pendientes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
