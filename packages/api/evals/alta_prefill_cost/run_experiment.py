"""PB-6 (m-24852200): the real cost of one Alta prefill, measured.

Runs `qualify_api.creative.brand_prefill.prefill_brand_kit` — the exact path the Alta
worker (PB-4) runs, with `propose=True` and the default `CallCaps` — once per account
on a THROWAWAY local tenant, twice:

1. **live** — a fresh tenant, so the profile cache misses and Scrape Creators is read;
2. **cache** — the same tenant again: the profile comes from the tenant's cache (0
   credits). The hashtag catalog's in-process memory is cleared first, so Claude runs
   again as it would in a worker retry in a new process (the realistic cache case).

Per run it records the Scrape Creators requests/credits and endpoints, every Claude run
(model id and revision, prompt version, input/output/cache tokens, cost from
`claude_tools.cost_breakdown`), latency and outcome. The throwaway tenants are deleted at
the end (owner DSN, local only). Nothing is written to a real tenant.

It SPENDS REAL CREDITS AND TOKENS, so it is run by hand, never in CI (pytest does not
collect `run_*.py`). Local stack only: it refuses `QUALIFY_DEPLOY_ENV=production` and
any non-local DSN.

    just eval-precarga --handles cuenta1,cuenta2 --out "$TMPDIR/pb6.json"
    just eval-precarga --cases /ruta/fuera/del/repo/casos.json

`--cases` is a JSON list of {"handle": ..., "label": ...}; the label (e.g. «heladería
pública de Cúcuta») is what goes into the docs — third-party handles never enter the
repo. Results default to a file outside the repo too.

`--alta-usd 0.15` (OL2-0, m-24854322) runs the path the Alta WORKER runs today —
`meegle.prefill.metered_prefill` over `bounded_ports`: a dollar meter of that cap, the
Alta's read (at most 2 credits), the rubro at 1,500 tokens x 2 attempts, the catalog at
3 turns x 1,200 at effort low, no creation run — and records the meter's spend, its
refused and lowered turns and the proposed tags. Without it, the PB-6 path
(`prefill_brand_kit` with the default `CallCaps`, no meter) as measured in PB6-001. The
budget guard stops BEFORE an account whose cap would take the spend over `--max-usd`.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[4]

#: Scrape Creators Freelance plan: $47 = 25,000 credits (scrapecreators.com, 2026-10-25).
#: Free credits cost 0 at the margin; the paid price is the one a cap must cover.
SC_USD_PER_CREDIT = 47 / 25_000
#: The keys the run needs, read from the env file in-process — never printed.
_KEYS = ("QUALIFY_ANTHROPIC_API_KEY", "SCRAPECREATORS_API_KEY")
_OWNER_DSN_DEFAULT = "postgresql+psycopg://qualify_owner:dev_only@localhost:5432/qualify"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def load_keys(env_file: Path) -> None:
    """Only `_KEYS`, only when not already set in the shell."""
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        name = name.strip()
        if sep and name in _KEYS and not os.environ.get(name):
            os.environ[name] = value.strip().strip("\"'")


def assert_local() -> None:
    from qualify_shared.db.config import admin_dsn, app_dsn

    if os.environ.get("QUALIFY_DEPLOY_ENV", "").lower() == "production":
        sys.exit("refused: QUALIFY_DEPLOY_ENV=production — this measurement is local only")
    for dsn in (app_dsn(), admin_dsn(), _owner_dsn()):
        host = urlsplit(dsn.replace("+psycopg", "")).hostname or ""
        if host not in _LOCAL_HOSTS:
            sys.exit(f"refused: non-local database host {host!r}")


def _owner_dsn() -> str:
    return os.environ.get("QUALIFY_MIGRATION_DSN", _OWNER_DSN_DEFAULT)


# --------------------------------------------------------------------------------------
# Throwaway tenants
# --------------------------------------------------------------------------------------


def create_tenant(label: str) -> tuple[uuid.UUID, uuid.UUID]:
    from qualify_shared.db.admin import admin_session
    from sqlalchemy import select

    from qualify_api.tenancy.models import Brand, Tenant

    with admin_session() as session:
        tenant = Tenant(
            name=f"PB-6 medición (borrar) · {label}",
            country="CO",
            timezone="America/Bogota",
            currency="COP",
        )
        session.add(tenant)
        session.flush()
        session.add(Brand(tenant_id=tenant.id, name="PB-6 medición"))
        session.flush()
        brand_id = session.scalar(select(Brand.id).where(Brand.tenant_id == tenant.id))
        return tenant.id, brand_id


def delete_tenant(tenant_id: uuid.UUID) -> list[str]:
    """Every row of the tenant, as the owner (FORCE RLS: the GUC opens the policy).
    Tables are retried until foreign keys stop refusing. Returns what was emptied."""
    from sqlalchemy import create_engine, text

    engine = create_engine(_owner_dsn())
    emptied: list[str] = []
    try:
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
            )
            tables = [
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND column_name = 'tenant_id' "
                        "AND table_name <> 'tenants'"
                    )
                )
            ]
            pending = set(tables)
            for _ in range(len(tables) + 1):
                if not pending:
                    break
                for table in sorted(pending):
                    try:
                        with conn.begin_nested():
                            n = conn.execute(
                                text(f'DELETE FROM "{table}" WHERE tenant_id = :t'),  # noqa: S608
                                {"t": tenant_id},
                            ).rowcount
                        pending.discard(table)
                        if n:
                            emptied.append(f"{table}:{n}")
                    except Exception:  # noqa: BLE001 - FK order: retried next pass
                        continue
            conn.execute(text("DELETE FROM tenants WHERE id = :t"), {"t": tenant_id})
    finally:
        engine.dispose()
    return emptied


# --------------------------------------------------------------------------------------
# One run
# --------------------------------------------------------------------------------------


@dataclass
class RecordingStore:
    """The real `BrandKitStore`, plus what the run wrote under `connect.prefill`."""

    inner: Any
    written: list[Any] = field(default_factory=list)

    def set_document_key(self, **kwargs: Any) -> bool:
        self.written.append(kwargs.get("value"))
        return self.inner.set_document_key(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def run_once(
    tenant_id: uuid.UUID,
    brand_id: uuid.UUID,
    handle: str,
    phase: str,
    alta_usd: Decimal | None = None,
) -> dict:
    from dataclasses import replace

    from qualify_api.claude_tools import cost_breakdown
    from qualify_api.creative import brand_prefill
    from qualify_api.creative.brand_kit_store import BrandKitStore
    from qualify_api.meegle import prefill as alta

    store = RecordingStore(BrandKitStore())
    start = time.perf_counter()
    if alta_usd is None:
        ports = brand_prefill.PrefillPorts(store=store)  # every other port is the real one
        result = brand_prefill.prefill_brand_kit(
            tenant_id,
            brand_id,
            "instagram",
            handle,
            source={"kind": "pb6-measurement", "ticket": "m-24852200"},
            propose=True,
            ports=ports,
        )
    else:  # the Alta worker's own path, with only the store recorded
        result = alta.metered_prefill(
            tenant_id,
            brand_id,
            "instagram",
            handle,
            source={"kind": "ol2-0-measurement", "ticket": "m-24854322"},
            caps=alta.ALTA_CAPS,
            propose=True,
            budget_usd=alta_usd,
            ports=lambda meter: replace(alta.bounded_ports(meter), store=store),
        )
    latency = time.perf_counter() - start
    doc = store.written[-1] if store.written else {}
    provenance = (doc or {}).get("provenance") or {}
    claude_runs = []
    for run in provenance.get("claude") or []:
        parts = cost_breakdown(
            run.get("model_id", ""),
            input_tokens=run.get("input_tokens", 0),
            output_tokens=run.get("output_tokens", 0),
            cache_read_tokens=run.get("cache_read_tokens", 0),
            cache_creation_tokens=run.get("cache_creation_tokens", 0),
        )
        claude_runs.append({**run, "cost_breakdown_usd": parts})
    usage = result.usage.as_document()
    profile = result.profile or {}
    sc_usd = usage["scrapecreators_credits"] * SC_USD_PER_CREDIT
    hashtags = ((result.proposal or {}).get("connect") or {}).get("hashtags") or []
    return {
        "phase": phase,
        "outcome": result.outcome.value,
        "detail": result.detail,
        "latency_s": round(latency, 2),
        "fetched_live": result.fetched_live,
        "posts_read": len(profile.get("recentCaptions") or ()),
        "endpoints": (provenance.get("read") or {}).get("endpoints", []),
        "usage": usage,
        "claude_runs": claude_runs,
        "hashtags_proposed": len(hashtags),
        "hashtags": [{"tag": h.get("tag"), "origin": h.get("origin")} for h in hashtags],
        "rubro_text": ((result.proposal or {}).get("connect") or {}).get("rubro_text", ""),
        "metered_usd": usage.get("metered_usd"),
        "palette": bool((result.proposal or {}).get("palette")),
        "written": result.written,
        "cost_usd": {
            "scrapecreators": round(sc_usd, 6),
            "claude": round(usage["claude_cost_usd"], 6),
            "total": round(sc_usd + usage["claude_cost_usd"], 6),
        },
    }


def clear_catalog_memory() -> None:
    """A worker retry in a new process has no in-memory catalog choice."""
    from qualify_api.hashtags import catalog

    with catalog._choices_lock:  # noqa: SLF001 - measurement only
        catalog._choices.clear()  # noqa: SLF001


def summarize(rows: list[dict]) -> dict:
    out: dict[str, Any] = {}
    for phase in ("live", "cache"):
        totals = [r["cost_usd"]["total"] for r in rows if r["phase"] == phase]
        if totals:
            out[phase] = {
                "n": len(totals),
                "mean_usd": round(statistics.fmean(totals), 6),
                "max_usd": round(max(totals), 6),
                "min_usd": round(min(totals), 6),
            }
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--handles", default="", help="comma-separated Instagram handles")
    parser.add_argument("--cases", type=Path, help='JSON [{"handle", "label"}] (outside repo)')
    parser.add_argument("--env-file", type=Path, default=REPO / ".env")
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "pb6.json")
    parser.add_argument("--max-usd", type=float, default=1.0, help="stop before exceeding")
    parser.add_argument("--skip-cache-run", action="store_true")
    parser.add_argument(
        "--alta-usd", type=Decimal, help="run the Alta worker's metered path with this cap"
    )
    args = parser.parse_args(argv)

    cases: list[dict[str, str]] = []
    if args.cases:
        cases = json.loads(args.cases.read_text(encoding="utf-8"))
    cases += [{"handle": h.strip(), "label": h.strip()} for h in args.handles.split(",") if h]
    if not cases:
        parser.error("no accounts: pass --handles or --cases")

    load_keys(args.env_file)
    assert_local()
    for key in _KEYS:
        if not os.environ.get(key):
            sys.exit(f"missing {key}")

    rows: list[dict] = []
    spent = 0.0
    per_run = float(args.alta_usd) if args.alta_usd is not None else 0.0
    for case in cases:
        if spent >= args.max_usd or spent + per_run > args.max_usd:
            print(f"budget guard: ${spent:.4f} spent, stopping before {case['label']}")
            break
        tenant_id, brand_id = create_tenant(case["label"])
        try:
            phases = ["live"] if args.skip_cache_run else ["live", "cache"]
            for phase in phases:
                if phase == "cache":
                    clear_catalog_memory()
                    if spent + per_run > args.max_usd:
                        print(f"budget guard: ${spent:.4f} spent, no cache run")
                        break
                row = run_once(tenant_id, brand_id, case["handle"], phase, args.alta_usd)
                row |= {"label": case["label"], "handle": case["handle"]}
                rows.append(row)
                spent += row["cost_usd"]["total"]
                print(
                    f"{case['label']:<40} {phase:<5} {row['outcome']:<16} "
                    f"sc={row['usage']['scrapecreators_credits']} "
                    f"claude={row['usage']['claude_calls']} "
                    f"in={row['usage']['claude_input_tokens']} "
                    f"out={row['usage']['claude_output_tokens']} "
                    f"${row['cost_usd']['total']:.4f} {row['latency_s']}s"
                    + (
                        f" metered=${row['metered_usd']} refused={row['usage']['refused_turns']}"
                        f" lowered={row['usage']['lowered_turns']}"
                        if row.get("metered_usd") is not None
                        else ""
                    )
                )
                if spent >= args.max_usd:
                    break
        finally:
            emptied = delete_tenant(tenant_id)
            print(f"  throwaway tenant deleted ({', '.join(emptied) or 'no rows'})")

    report = {
        "ticket": "m-24852200" if args.alta_usd is None else "m-24854322",
        "alta_usd": str(args.alta_usd) if args.alta_usd is not None else None,
        "date": datetime.now(UTC).isoformat(),
        "pipeline_version": __import__(
            "qualify_api.creative.brand_prefill", fromlist=["PREFILL_VERSION"]
        ).PREFILL_VERSION,
        "caps": (
            {"scrapecreators_requests": 6, "claude_calls": 3}
            if args.alta_usd is None
            else {"scrapecreators_requests": 2, "claude_calls": 2}
        ),
        "sc_usd_per_credit": SC_USD_PER_CREDIT,
        "spent_usd": round(spent, 6),
        "summary": summarize(rows),
        "runs": rows,
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"spent ${spent:.4f} — results in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
