"""View-models for the metrics block of `/whatsapp` → Conexión (WA-17 conversation metrics,
QUA-216 · WA-21 WABA analytics, QUA-220).

Two sources, two VMs, both frozen and pre-formatted:

- `ConversationMetricsVM` — from `qualify_api.whatsapp.metrics.ConversationMetrics`
  (our own tables: threads, orders, handoffs, first human response, messages);
- `WabaAnalyticsVM` — from `qualify_api.whatsapp.analytics.AnalyticsSummary` (read from
  Meta: messages sent/delivered per day, approximate cost per pricing category).

Every definition (what counts as a "conversación nueva", how the median is taken) lives
in those modules' docstrings; this one only formats. The chart is the dataviz
"emphasis" form: one bar per day, sent as the gray track and delivered as the accent
fill inside it — one scale, no second axis; the exact numbers are in the tooltip.

Pure module: no Reflex, network or database import.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from .whatsapp_campaigns_vm import format_count, format_money

PERIODS: tuple[tuple[str, str], ...] = (("7", "7 días"), ("30", "30 días"))
PERIOD_KEYS: frozenset[str] = frozenset(key for key, _ in PERIODS)
DEFAULT_PERIOD = "7"

NO_VALUE = "—"

_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

_PRICING_CATEGORY: dict[str, str] = {
    "MARKETING": "Marketing",
    "UTILITY": "Utilidad",
    "AUTHENTICATION": "Autenticación",
    "AUTHENTICATION_INTERNATIONAL": "Autenticación internacional",
    "SERVICE": "Servicio",
    "MARKETING_LITE": "Marketing (lite)",
    "UNKNOWN": "Sin categoría",
}


def format_duration(seconds: float | None) -> str:
    """«45 s», «4 min», «1 h 20 min», «2 d 3 h»; «—» when there is no data."""
    if seconds is None:
        return NO_VALUE
    total = round(seconds)
    if total < 60:
        return f"{total} s"
    minutes = round(total / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    days, hours = divmod(hours, 24)
    return f"{days} d {hours} h" if hours else f"{days} d"


def short_day(value: datetime) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]}"


# --------------------------------------------------------------------------------------
# Conversation metrics (WA-17)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryVM:
    label: str
    count: str


@dataclass(frozen=True)
class ConversationMetricsVM:
    threads_opened: str
    orders_confirmed: str
    orders_total: str  # «COP 50.000,00 · USD 12,00», «Sin ventas» when none
    handoffs: str
    awaiting_human: str  # «2 esperan respuesta», "" when 0
    median_first_response: str
    p90_first_response: str
    messages_in: str
    messages_out: str
    messages_out_detail: str  # «12 automáticos · 30 de personas · 5 de campañas»
    entry_counts: list[EntryVM]
    qr_note: str  # "" when the QR codes could be read from Meta


EMPTY_METRICS = ConversationMetricsVM(
    threads_opened="0",
    orders_confirmed="0",
    orders_total="",
    handoffs="0",
    awaiting_human="",
    median_first_response=NO_VALUE,
    p90_first_response=NO_VALUE,
    messages_in="0",
    messages_out="0",
    messages_out_detail="",
    entry_counts=[],
    qr_note="",
)


def entry_label(kind: str, key: str | None) -> str:
    if kind == "directo":
        return "Escribieron directo"
    if kind == "qr":
        return f"QR {key}" if key else "Código QR"
    if kind == "command":
        return f"Comando /{key}" if key else "Comando"
    if kind == "ice_breaker":
        return f"Atajo «{key}»" if key else "Atajo"
    if kind == "keyword":
        return f"Palabra «{key}»" if key else "Palabra clave"
    return key or kind


def build_metrics_vm(
    *,
    threads_opened: int,
    entries: Sequence[tuple[str, str | None, int]],
    orders_confirmed: int,
    orders_total: Mapping[str, Decimal],
    handoffs: int,
    awaiting_human_response: int,
    median_first_human_response_seconds: float | None,
    p90_first_human_response_seconds: float | None,
    messages_in: int,
    messages_out_automation: int,
    messages_out_human: int,
    messages_out_campaign: int,
    messages_out_other: int,
    qr_codes_available: bool,
) -> ConversationMetricsVM:
    out_total = (
        messages_out_automation + messages_out_human + messages_out_campaign + messages_out_other
    )
    detail = [
        f"{format_count(messages_out_automation)} automáticos",
        f"{format_count(messages_out_human)} de personas",
    ]
    if messages_out_campaign:
        detail.append(f"{format_count(messages_out_campaign)} de campañas")
    totals = [
        format_money(amount, currency)
        for currency, amount in sorted(orders_total.items())
        if currency != "XXX"
    ]
    ranked = sorted(entries, key=lambda e: (-e[2], entry_label(e[0], e[1])))
    return ConversationMetricsVM(
        threads_opened=format_count(threads_opened),
        orders_confirmed=format_count(orders_confirmed),
        orders_total=" · ".join(totals) if totals else "Sin ventas registradas",
        handoffs=format_count(handoffs),
        awaiting_human=(
            f"{format_count(awaiting_human_response)} aún esperan respuesta"
            if awaiting_human_response
            else ""
        ),
        median_first_response=format_duration(median_first_human_response_seconds),
        p90_first_response=format_duration(p90_first_human_response_seconds),
        messages_in=format_count(messages_in),
        messages_out=format_count(out_total),
        messages_out_detail=" · ".join(detail),
        entry_counts=[
            EntryVM(label=entry_label(kind, key), count=format_count(n))
            for kind, key, n in ranked
            if n
        ],
        qr_note=(
            ""
            if qr_codes_available
            else "No pudimos leer tus códigos QR en Meta: lo que llegó por QR cuenta como "
            "palabra clave o directo."
        ),
    )


# --------------------------------------------------------------------------------------
# WABA analytics (WA-21)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BarVM:
    label: str  # «14 oct»
    sent_pct: str  # track height, % of the busiest day — "0%" … "100%"
    delivered_pct: str  # fill height, % of the track
    tooltip: str  # «14 oct: 120 enviados · 118 entregados»
    show_label: bool  # first, last and (on 30 days) every 7th label only


@dataclass(frozen=True)
class CostLineVM:
    category: str
    volume: str
    billable: str
    cost: str


@dataclass(frozen=True)
class WabaAnalyticsVM:
    bars: list[BarVM]
    has_traffic: bool
    sent_total: str
    delivered_total: str
    delivery_rate: str  # «98 %», «—» without sends
    costs: list[CostLineVM]
    cost_total: str
    cost_available: bool


EMPTY_ANALYTICS = WabaAnalyticsVM(
    bars=[],
    has_traffic=False,
    sent_total="0",
    delivered_total="0",
    delivery_rate=NO_VALUE,
    costs=[],
    cost_total=NO_VALUE,
    cost_available=False,
)


def _pct(part: int, whole: int) -> str:
    if whole <= 0:
        return "0%"
    return f"{min(100, round(100 * part / whole))}%"


def build_analytics_vm(
    *,
    buckets: Sequence[tuple[datetime, int, int]],
    sent_total: int,
    delivered_total: int,
    currency: str | None,
    costs: Sequence[tuple[str, int, int, Decimal | None]],
    cost_total: Decimal | None,
    cost_available: bool,
) -> WabaAnalyticsVM:
    busiest = max((sent for _start, sent, _d in buckets), default=0)
    last = len(buckets) - 1
    step = 7 if len(buckets) > 10 else 1
    bars = [
        BarVM(
            label=short_day(start),
            sent_pct=_pct(sent, busiest),
            delivered_pct=_pct(delivered, sent),
            tooltip=(
                f"{short_day(start)}: {format_count(sent)} enviados · "
                f"{format_count(delivered)} entregados"
            ),
            show_label=index in (0, last) or (index % step == 0 and last - index >= step // 2),
        )
        for index, (start, sent, delivered) in enumerate(buckets)
    ]
    cur = currency or ""
    return WabaAnalyticsVM(
        bars=bars,
        has_traffic=sent_total > 0,
        sent_total=format_count(sent_total),
        delivered_total=format_count(delivered_total),
        delivery_rate=_pct(delivered_total, sent_total).replace("%", " %")
        if sent_total
        else NO_VALUE,
        costs=[
            CostLineVM(
                category=_PRICING_CATEGORY.get(category.upper(), category),
                volume=format_count(volume),
                billable=format_count(billable),
                cost=format_money(cost, cur) if cost is not None and cur else NO_VALUE,
            )
            for category, volume, billable, cost in costs
        ],
        cost_total=format_money(cost_total, cur) if cost_total is not None and cur else NO_VALUE,
        cost_available=cost_available,
    )
