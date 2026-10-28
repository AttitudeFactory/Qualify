"""Consumption ledger: contextvar scope, summary, and Meegle sync (m-24823681).

A unified ledger of what an «Alta de cliente» cost — the Anthropic tokens,
BytePlus generation and ScrapeCreators credits — one tenant-scoped row per
billable operation, with `pricing_table_version` as the provenance marker so a
`cost_usd` stays reproducible against the price sheet that produced it.

The capture mechanism is a contextvar scope: `record_consumption` appends a row
to the active `consumption_scope`, and the rows are persisted in one
`tenant_session` when the scope exits. **No Meegle call happens here** — the
scope exists to persist the ledger, not to write to Meegle. The Meegle summary
is written explicitly, by `sync_consumption_to_meegle`, on «Kit de marca listo»
node completion (wired in `qualify_api.meegle.handlers`) and by the daily
catch-up `daily_consumption_sync()` (`qualify_api.consumption.worker`).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.consumption.models import ConsumptionLedger

logger = logging.getLogger("qualify_api.consumption")

#: The providers the ledger distinguishes (`provider` column values).
ANTHROPIC = "anthropic"
SCRAPECREATORS = "scrapecreators"

#: The default price-sheet provenance marker the capture points record against
#: (the creative `JsonPricingTable`, `pricing_data/<version>.json`). `v7` is the
#: version that carries the Anthropic token and ScrapeCreators credit rates.
DEFAULT_PRICING_TABLE_VERSION = "v7"


@dataclass
class ConsumptionContext:
    tenant_id: UUID
    brand_id: UUID | None = None
    meegle_work_item_id: int | None = None
    operation: str = ""
    pricing_table_version: str = DEFAULT_PRICING_TABLE_VERSION
    records: list[dict[str, Any]] = field(default_factory=list)


_active_consumption: ContextVar[ConsumptionContext | None] = ContextVar(
    "active_consumption", default=None
)


def summarize_consumption(
    session: Session,
    *,
    tenant_id: UUID | None = None,
    meegle_work_item_id: int | None = None,
) -> dict[str, Any]:
    """Summarize ledger rows grouped by provider, operation, and totals.

    The session respects RLS: a `tenant_session` reads only its own tenant's
    rows; an `admin_session` (BYPASSRLS) reads every row the ledger has — the
    worker/daily-tick path. Filter by `tenant_id` and/or `meegle_work_item_id`
    to scope a slice.
    """
    stmt = select(ConsumptionLedger)
    if tenant_id is not None:
        stmt = stmt.where(ConsumptionLedger.tenant_id == tenant_id)
    if meegle_work_item_id is not None:
        stmt = stmt.where(ConsumptionLedger.meegle_work_item_id == meegle_work_item_id)
    rows = session.scalars(stmt).all()

    total_cost = sum((r.cost_usd for r in rows), Decimal("0"))
    anthropic_in = sum((r.input_tokens for r in rows if r.provider == ANTHROPIC), 0)
    anthropic_out = sum((r.output_tokens for r in rows if r.provider == ANTHROPIC), 0)
    anthropic_cache_read = sum((r.cache_read_tokens for r in rows if r.provider == ANTHROPIC), 0)
    anthropic_cache_creation = sum(
        (r.cache_creation_tokens for r in rows if r.provider == ANTHROPIC), 0
    )
    scrape_credits = sum(
        (r.extra_metadata.get("credits", 0) for r in rows if r.provider == SCRAPECREATORS),
        0,
    )

    by_operation: dict[str, dict[str, Any]] = {}
    for r in rows:
        op = r.operation or "default"
        if op not in by_operation:
            by_operation[op] = {"cost_usd": Decimal("0"), "tokens": 0, "calls": 0}
        by_operation[op]["cost_usd"] += r.cost_usd
        by_operation[op]["tokens"] += r.input_tokens + r.output_tokens
        by_operation[op]["calls"] += 1

    return {
        "total_cost_usd": float(total_cost),
        "anthropic_input_tokens": anthropic_in,
        "anthropic_output_tokens": anthropic_out,
        "anthropic_cache_read_tokens": anthropic_cache_read,
        "anthropic_cache_creation_tokens": anthropic_cache_creation,
        "scrapecreators_credits": scrape_credits,
        "records_count": len(rows),
        "by_operation": by_operation,
    }


def _render_summary(work_item_id: int, summary: dict[str, Any]) -> str:
    """A Meegle comment body: the totals a person reads in one glance."""
    return (
        f"**Consumo registrado (Alta #{work_item_id}):**\n"
        f"- Costo total: ${summary['total_cost_usd']:.4f} USD\n"
        f"- Tokens Anthropic (In/Out): {summary['anthropic_input_tokens']} / "
        f"{summary['anthropic_output_tokens']}\n"
        f"- Tokens Cache (Read/Create): {summary['anthropic_cache_read_tokens']} / "
        f"{summary['anthropic_cache_creation_tokens']}\n"
        f"- Créditos ScrapeCreators: {summary['scrapecreators_credits']}\n"
        f"- Registros de consumo: {summary['records_count']}"
    )


def sync_consumption_to_meegle(work_item_id: int) -> str:
    """Post a consumption summary comment to the Meegle «Alta de cliente» item.

    Best-effort: returns a short label (`synced`, `empty`, `meegle_off`,
    `meegle_failed`) and never raises. Reads the ledger cross-tenant via the
    `admin_session` (BYPASSRLS) — the worker/handler context has no current
    tenant, and a work item's rows belong to one tenant anyway. No comment is
    posted when the item has no consumption (`empty`) or the Meegle engine is
    off (`meegle_off`); a Meegle refusal or transport failure is logged and
    returns `meegle_failed` (the ledger rows are the record, so a retry is safe).

    Idempotency: Meegle accepts a repeated comment. The node-completion wiring is
    the primary trigger (one summary per «Kit de marca listo»); the daily tick is
    a catch-up that re-posts — run it weekly, not hourly, once node-completion is
    the norm.
    """
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415 — see module docstring

    with admin_session() as session:
        summary = summarize_consumption(session, meegle_work_item_id=work_item_id)
    if summary["records_count"] == 0:
        return "empty"
    # The meegle package owns the client (the plugin secret lives there); this
    # module owns the ledger read and the summary text. Routed through
    # `post_consumption_comment` so this module never imports the raw client
    # (the `meegle.client` sanctity guard).
    try:
        from qualify_api.meegle.handlers import post_consumption_comment  # noqa: PLC0415

        return post_consumption_comment(work_item_id, _render_summary(work_item_id, summary))
    except Exception as exc:  # noqa: BLE001 — the ledger rows are the record
        logger.warning("consumption sync to meegle item %s failed: %s", work_item_id, exc)
        return "meegle_failed"
    return "synced"


def daily_consumption_sync() -> dict[str, int]:
    """Sync the consumption summary of every «Alta de cliente» with ledger rows
    back to Meegle, one pass per item. The node-completion sync is the primary
    trigger; this is the catch-up for items completed before the wiring or that
    accrued consumption after it.

    Returns a report `{synced, empty, meegle_off, meegle_failed}` count.
    """
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415

    with admin_session() as session:
        ids = [
            wid
            for wid in session.scalars(
                select(ConsumptionLedger.meegle_work_item_id)
                .where(ConsumptionLedger.meegle_work_item_id.is_not(None))
                .distinct()
            )
            if wid is not None
        ]
    report: dict[str, int] = {"synced": 0, "empty": 0, "meegle_off": 0, "meegle_failed": 0}
    for wid in ids:
        result = sync_consumption_to_meegle(wid)
        report[result] = report.get(result, 0) + 1
    logger.info("consumption daily sync: %s", report)
    return report


@contextmanager
def consumption_scope(
    tenant_id: UUID,
    *,
    brand_id: UUID | None = None,
    meegle_work_item_id: int | None = None,
    operation: str = "",
    pricing_table_version: str = DEFAULT_PRICING_TABLE_VERSION,
) -> Iterator[ConsumptionContext]:
    """Capture consumption within a scope and persist it on exit.

    `record_consumption` appends a row to the active scope; on exit the rows are
    written in one `tenant_session` under the tenant's RLS policy. The
    `meegle_work_item_id` links the rows back to the «Alta de cliente» item.
    **No Meegle call happens here** — the scope persists the ledger; the Meegle
    summary is written on node completion and by the daily tick.
    """
    ctx = ConsumptionContext(
        tenant_id=tenant_id,
        brand_id=brand_id,
        meegle_work_item_id=meegle_work_item_id,
        operation=operation,
        pricing_table_version=pricing_table_version,
    )
    token = _active_consumption.set(ctx)
    try:
        yield ctx
    finally:
        _active_consumption.reset(token)
        if not ctx.records:
            return
        with tenant_session(tenant_id) as session:
            for r in ctx.records:
                session.add(ConsumptionLedger(**r))
            session.flush()


def record_consumption(
    *,
    tenant_id: UUID | None = None,
    brand_id: UUID | None = None,
    meegle_work_item_id: int | None = None,
    operation: str | None = None,
    provider: str,
    model_id: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cost_usd: Decimal | float = Decimal("0"),
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    pricing_table_version: str | None = None,
) -> None:
    """Record one billable operation into the ledger.

    Inside an active `consumption_scope` (the common case) the row is appended to
    `ctx.records` and written when the scope exits. Outside a scope, `tenant_id`
    opens a `tenant_session` on the spot. Nothing is written when there is no
    tenant (no scope, no explicit `tenant_id`): a capture point called outside
    any scope is a no-op.

    `cost_usd` is the caller's — the capture point already priced the operation
    (`claude_tools` via `cost_breakdown`, ScrapeCreators at the per-credit rate).
    `pricing_table_version` (default `v7`) is the provenance marker that makes a
    ledger row reproducible against the price sheet; `metadata` carries the rest
    (ScrapeCreators records `{"credits": 1}` per call).
    """
    ctx = _active_consumption.get()
    tid = tenant_id or (ctx.tenant_id if ctx else None)
    if not tid:
        return
    b_id = brand_id or (ctx.brand_id if ctx else None)
    mw_id = (
        meegle_work_item_id
        if meegle_work_item_id is not None
        else (ctx.meegle_work_item_id if ctx else None)
    )
    op = operation or (ctx.operation if ctx else "") or ""
    version = pricing_table_version or (ctx.pricing_table_version if ctx else None)

    record_data: dict[str, Any] = {
        "tenant_id": tid,
        "brand_id": b_id,
        "meegle_work_item_id": mw_id,
        "operation": op,
        "provider": provider,
        "model_id": model_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_creation_tokens": cache_creation_tokens,
        "cost_usd": Decimal(str(cost_usd)),
        "idempotency_key": idempotency_key,
        "extra_metadata": metadata or {},
        "pricing_table_version": version,
    }

    if ctx is not None:
        ctx.records.append(record_data)
    else:
        with tenant_session(tid) as session:
            session.add(ConsumptionLedger(**record_data))
            session.flush()
