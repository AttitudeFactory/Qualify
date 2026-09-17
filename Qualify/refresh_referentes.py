"""Recompute stored referentes that an older algorithm computed — `just refresh-referentes`.

When `creator_discovery.PHASED_PLAN_VERSION` goes up (the algorithm improved), every
stored phase from an older version stops being reused. The wizard recomputes a brand's
phases the next time its operator walks the flow; this command does it for every brand
at once, from the seed each phase stored, without anyone walking the wizard.

    just refresh-referentes --dry-run            # what would run, and its estimated cost
    just refresh-referentes --max-credits 40     # run, stopping before the budget is hit
    just refresh-referentes --tenant <uuid> --brand <uuid>

It spends Scrape Creators credits (the searches ARE the algorithm), so `--dry-run` first
and `--max-credits` always apply. The estimate of a brand is what its stored phases cost
last time. Labels (referente/competencia/detractor) are never touched: they belong to the
account, and an account the new algorithm drops still shows in its bucket.

An operator tool, never imported by the app: `admin_session` (BYPASSRLS) is used ONLY to
list tenant ids — every read and write of referentes goes through `tenant_session`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from uuid import UUID

from . import creator_discovery, referentes_provider
from .referentes_provider import BrandRefresh, PhaseRunner

DEFAULT_MAX_CREDITS = 50


def all_tenant_ids() -> list[UUID]:
    from qualify_api.tenancy.models import Tenant
    from qualify_shared.db.admin import admin_session
    from sqlalchemy import select

    with admin_session() as session:
        return list(session.scalars(select(Tenant.id).order_by(Tenant.created_at)))


def _describe(plan: BrandRefresh) -> str:
    versions = ", ".join(f"v{v}" for v in plan.from_versions)
    return (
        f"tenant {plan.tenant_id} · marca {plan.brand_id} · fases {', '.join(plan.keys)} · "
        f"{versions} -> v{creator_discovery.PHASED_PLAN_VERSION} · "
        f"~{plan.estimated_credits} créditos"
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    tenants: Callable[[], list[UUID]] = all_tenant_ids,
    run: PhaseRunner = referentes_provider.run_phases,
    out: Callable[[str], None] = print,
) -> int:
    parser = argparse.ArgumentParser(
        prog="refresh-referentes",
        description="Recompute referentes stored by an older algorithm version.",
    )
    parser.add_argument("--dry-run", action="store_true", help="list what would run; spend nothing")
    parser.add_argument("--max-credits", type=int, default=DEFAULT_MAX_CREDITS)
    parser.add_argument("--tenant", type=UUID, default=None)
    parser.add_argument("--brand", type=UUID, default=None)
    args = parser.parse_args(argv)

    tenant_ids = [args.tenant] if args.tenant else tenants()
    plans = [
        plan
        for tenant_id in tenant_ids
        for plan in referentes_provider.plan_refresh(tenant_id, brand_id=args.brand)
    ]
    version = creator_discovery.PHASED_PLAN_VERSION
    if not plans:
        out(f"Todo al día: ningún referente guardado con una versión anterior a v{version}.")
        return 0

    estimate = sum(p.estimated_credits for p in plans)
    out(f"{len(plans)} marca(s) con referentes de una versión anterior a v{version}:")
    for plan in plans:
        out(f"  - {_describe(plan)}")
    out(f"Estimado total: ~{estimate} créditos (tope: {args.max_credits}).")
    if args.dry_run:
        out("--dry-run: no se gastó nada.")
        return 0

    creator_discovery._load_dotenv()
    spent = 0
    skipped = 0
    for plan in plans:
        if spent + plan.estimated_credits > args.max_credits:
            skipped += 1
            out(f"  omitida (tope de créditos): {_describe(plan)}")
            continue
        try:
            used, not_stored = referentes_provider.execute_refresh(plan, run)
        except creator_discovery.ScrapeCreatorsError as exc:
            skipped += 1
            out(f"  error del vendor, se reintentará en la próxima corrida: {plan.brand_id}: {exc}")
            continue
        spent += used
        note = f" (sin guardar, se reintentará: {', '.join(not_stored)})" if not_stored else ""
        out(f"  actualizada: marca {plan.brand_id} · {used} créditos{note}")
    out(f"Listo: {spent} créditos gastados, {skipped} marca(s) pendientes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
