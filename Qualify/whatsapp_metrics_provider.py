"""The seam between the Conexión metrics block (WA-17 / WA-21) and the real backend.

In-process calls to the same services `GET /api/whatsapp/metrics` and `/analytics` wrap
(`http/whatsapp_routes.py`), with the same order of operations:

- **metrics** — `ConversationMetricsService.ensure_connection` first (an unknown id costs
  no Graph call), then the number's QR codes from Meta (`production_qr_prefix_source`,
  which never fails: `None` when Meta cannot be read), then `compute` over our own tables;
- **analytics** — `WabaAnalyticsService.summary`, read from Meta through WA-08's
  resolver-built client (no token here). It raises `ReconnectRequired` when the credential
  is missing or Meta rejects it, and the Graph error otherwise; the state turns those into
  the reconnect hint or the Meta code.

Everything is injectable so `test_whatsapp_metrics.py` runs on Memory repositories and
fakes — no network, no database.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from qualify_api.whatsapp.analytics import WabaAnalyticsService
from qualify_api.whatsapp.metrics import ConversationMetricsService

from .whatsapp_metrics_vm import (
    ConversationMetricsVM,
    WabaAnalyticsVM,
    build_analytics_vm,
    build_metrics_vm,
)


def _range(days: int, now: datetime | None = None) -> tuple[datetime, datetime]:
    until = now or datetime.now(UTC)
    return until - timedelta(days=days), until


def production_metrics() -> tuple[ConversationMetricsService, Any]:
    from qualify_api.whatsapp.metrics import (  # noqa: PLC0415
        production_metrics_service,
        production_qr_prefix_source,
    )

    return production_metrics_service(), production_qr_prefix_source()


def production_analytics() -> WabaAnalyticsService:
    from qualify_api.whatsapp.analytics import production_analytics_service  # noqa: PLC0415

    return production_analytics_service()


async def conversation_metrics(
    tenant_id: UUID,
    connection_id: UUID,
    days: int,
    *,
    service: ConversationMetricsService | None = None,
    qr_source: Any = None,
    now: datetime | None = None,
) -> ConversationMetricsVM:
    """Raises `ConnectionNotFound` / `InvalidRange` like the route."""
    if service is None or qr_source is None:
        default_service, default_source = production_metrics()
        service = service or default_service
        qr_source = qr_source or default_source
    since, until = _range(days, now)
    await asyncio.to_thread(service.ensure_connection, tenant_id, connection_id)
    prefixes = await qr_source(tenant_id=tenant_id, connection_id=connection_id)
    m = await asyncio.to_thread(
        service.compute, tenant_id, connection_id, since, until, prefixes or {}
    )
    return build_metrics_vm(
        threads_opened=m.threads_opened,
        entries=[(e.kind, e.key, e.threads) for e in m.threads_opened_by_entry],
        orders_confirmed=m.orders_confirmed,
        orders_total=m.orders_total,
        handoffs=m.handoffs,
        awaiting_human_response=m.awaiting_human_response,
        median_first_human_response_seconds=m.median_first_human_response_seconds,
        p90_first_human_response_seconds=m.p90_first_human_response_seconds,
        messages_in=m.messages_in,
        messages_out_automation=m.messages_out_automation,
        messages_out_human=m.messages_out_human,
        messages_out_campaign=m.messages_out_campaign,
        messages_out_other=m.messages_out_other,
        qr_codes_available=prefixes is not None,
    )


async def waba_analytics(
    tenant_id: UUID,
    connection_id: UUID,
    days: int,
    *,
    service: WabaAnalyticsService | None = None,
    now: datetime | None = None,
) -> WabaAnalyticsVM:
    """Raises `ReconnectRequired`, `ConnectionNotFound`, `InvalidRange` or the client's
    non-auth `WhatsAppApiError`."""
    svc = service or production_analytics()
    since, until = _range(days, now)
    s = await svc.summary(tenant_id, connection_id, since, until, "DAY")
    return build_analytics_vm(
        buckets=[(b.start, b.sent, b.delivered) for b in s.messages],
        sent_total=s.sent_total,
        delivered_total=s.delivered_total,
        currency=s.currency,
        costs=[(c.category, c.volume, c.billable_volume, c.cost) for c in s.cost_by_category],
        cost_total=s.cost_total,
        cost_available=s.cost_available,
    )
