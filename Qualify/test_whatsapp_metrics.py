"""Network-free tests for the Conexión metrics block (WA-17, QUA-216 · WA-21, QUA-220).

They pin the VM boundary, the formatting (durations, entries, money), the chart's
geometry (one scale: sent = track as % of the busiest day, delivered = fill as % of its
track), and the provider over `MemoryMetricsRepository` and a fake analytics reader —
including `ReconnectRequired` when Meta rejects the token.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
import reflex as rx
from qualify_api.whatsapp.analytics import (
    AnalyticsPhone,
    MemoryAnalyticsPhoneRepository,
    ReconnectRequired,
    WabaAnalyticsService,
)
from qualify_api.whatsapp.client import (
    MessagingDataPoint,
    PricingAnalytics,
    PricingDataPoint,
    WabaAnalytics,
    WhatsAppApiError,
)
from qualify_api.whatsapp.metrics import (
    ConversationMetricsService,
    MemoryMetricsRepository,
    MessageFact,
    MetricsRows,
    ThreadFact,
)

from . import whatsapp_metrics_block
from .whatsapp_metrics_provider import conversation_metrics, waba_analytics
from .whatsapp_metrics_vm import (
    EMPTY_ANALYTICS,
    EMPTY_METRICS,
    BarVM,
    ConversationMetricsVM,
    CostLineVM,
    EntryVM,
    WabaAnalyticsVM,
    build_analytics_vm,
    entry_label,
    format_duration,
)

_FORBIDDEN = ("token", "credential", "cipher", "secret", "key_id", "password")
TENANT = UUID("00000000-0000-0000-0000-0000000000a4")
CONNECTION = UUID("00000000-0000-0000-0000-0000000000c4")
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def test_whatsapp_metrics_vm_has_no_credential_fields() -> None:
    for vm in (ConversationMetricsVM, EntryVM, WabaAnalyticsVM, BarVM, CostLineVM):
        assert vm.__dataclass_params__.frozen  # type: ignore[attr-defined]
        for f in dataclasses.fields(vm):
            assert not any(bad in f.name.lower() for bad in _FORBIDDEN), (vm, f.name)


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (None, "—"),
        (42, "42 s"),
        (240, "4 min"),
        (4800, "1 h 20 min"),
        (3600, "1 h"),
        (183600, "2 d 3 h"),
    ],
)
def test_durations(seconds: float | None, text: str) -> None:
    assert format_duration(seconds) == text


def test_entry_labels() -> None:
    assert entry_label("directo", None) == "Escribieron directo"
    assert entry_label("command", "menu") == "Comando /menu"
    assert entry_label("keyword", "hola") == "Palabra «hola»"


def test_chart_geometry() -> None:
    day = datetime(2026, 10, 1, tzinfo=UTC)
    vm = build_analytics_vm(
        buckets=[
            (day, 100, 90),
            (day + timedelta(days=1), 50, 50),
            (day + timedelta(days=2), 0, 0),
        ],
        sent_total=150,
        delivered_total=140,
        currency="USD",
        costs=[("MARKETING", 140, 120, Decimal("1.68"))],
        cost_total=Decimal("1.68"),
        cost_available=True,
    )
    assert [(b.sent_pct, b.delivered_pct) for b in vm.bars] == [
        ("100%", "90%"),
        ("50%", "100%"),
        ("0%", "0%"),
    ]
    assert vm.bars[0].tooltip == "1 oct: 100 enviados · 90 entregados"
    assert vm.delivery_rate == "93 %" and vm.has_traffic
    assert vm.costs[0].category == "Promociones" and vm.cost_total == "USD 1,68"


async def test_conversation_metrics_provider() -> None:
    repo = MemoryMetricsRepository()
    thread = uuid4()
    repo.put(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        rows=MetricsRows(
            threads=[
                ThreadFact(
                    thread_id=thread,
                    first_inbound_at=NOW - timedelta(days=1),
                    first_inbound_text="hola",
                )
            ],
            messages=[
                MessageFact(thread_id=thread, direction="inbound", at=NOW - timedelta(days=1)),
                MessageFact(
                    thread_id=thread,
                    direction="outbound",
                    at=NOW - timedelta(days=1) + timedelta(minutes=4),
                    outbox_kind="human_reply",
                ),
            ],
        ),
    )
    service = ConversationMetricsService(repo, clock=lambda: NOW)

    async def no_qr(**_kw: Any) -> None:
        return None

    vm = await conversation_metrics(
        TENANT, CONNECTION, 7, service=service, qr_source=no_qr, now=NOW
    )
    assert vm.threads_opened == "1" and vm.messages_in == "1"
    assert vm.qr_note  # QR codes unreadable → said, not hidden
    assert [e.label for e in vm.entry_counts] == ["Escribieron directo"]


class FakeReader:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail

    async def get_waba_analytics(
        self, waba_id: str, start: datetime, end: datetime, *a: Any
    ) -> WabaAnalytics:
        if self.fail:
            raise self.fail
        return WabaAnalytics(
            granularity="DAY",
            phone_numbers=("573001234567",),
            data_points=(
                MessagingDataPoint(
                    start=start, end=start + timedelta(days=1), sent=10, delivered=9
                ),
            ),
        )

    async def get_pricing_analytics(
        self, waba_id: str, start: datetime, end: datetime, *a: Any
    ) -> PricingAnalytics:
        if self.fail:
            raise self.fail
        return PricingAnalytics(
            currency="USD",
            data_points=(
                PricingDataPoint(
                    start=start,
                    end=end,
                    volume=9,
                    cost=Decimal("0.11"),
                    pricing_category="MARKETING",
                    pricing_type="REGULAR",
                ),
            ),
        )


def _analytics(reader: FakeReader) -> WabaAnalyticsService:
    phones = MemoryAnalyticsPhoneRepository()
    phones.put(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        phone=AnalyticsPhone(waba_id="w", phone_number_id="p", display_phone_number="573001234567"),
    )

    async def factory(**_kw: Any) -> FakeReader:
        return reader

    return WabaAnalyticsService(factory, phones, clock=lambda: NOW)  # type: ignore[arg-type]


async def test_analytics_provider() -> None:
    vm = await waba_analytics(TENANT, CONNECTION, 7, service=_analytics(FakeReader()), now=NOW)
    assert vm.sent_total == "10" and vm.cost_available and vm.cost_total == "USD 0,11"


async def test_analytics_auth_error_asks_to_reconnect() -> None:
    reader = FakeReader(fail=WhatsAppApiError("no", status=401, code=190))
    with pytest.raises(ReconnectRequired):
        await waba_analytics(TENANT, CONNECTION, 7, service=_analytics(reader), now=NOW)


def test_block_renders() -> None:
    component = whatsapp_metrics_block.metrics_block()
    assert isinstance(component, rx.Component)
    rendered = str(component.render())
    for text in ("Conversaciones nuevas", "Pedidos confirmados", "Traspasos a persona"):
        assert text in rendered, text


async def test_a_number_switch_mid_load_loads_the_new_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """m-25143230 (review C1): B is chosen while A's metrics are still loading. B's
    block loads B (it is not turned away by A's load) and A's late answer is dropped."""
    import asyncio

    from . import whatsapp_metrics_state as module
    from .whatsapp_metrics_state import WhatsAppMetricsState

    a, b = str(uuid4()), str(uuid4())
    selected = {"id": a}
    release_a = asyncio.Event()

    class _Lock:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_exc: object) -> None:
            return None

    async def scope(self: WhatsAppMetricsState) -> tuple[str, UUID]:
        return selected["id"], TENANT

    async def metrics(_tenant: UUID, connection: UUID, _days: int) -> object:
        if str(connection) == a:
            await release_a.wait()
        return dataclasses.replace(EMPTY_METRICS, threads_opened=str(connection)[:4])

    async def analytics(_tenant: UUID, _connection: UUID, _days: int) -> object:
        return EMPTY_ANALYTICS

    monkeypatch.setattr(WhatsAppMetricsState, "_scope", scope)
    monkeypatch.setattr(WhatsAppMetricsState, "__aenter__", lambda self: _Lock().__aenter__())
    monkeypatch.setattr(WhatsAppMetricsState, "__aexit__", lambda self, *x: _Lock().__aexit__())
    monkeypatch.setattr(module, "conversation_metrics", metrics)
    monkeypatch.setattr(module, "waba_analytics", analytics)

    state = WhatsAppMetricsState()
    first = asyncio.create_task(state._load(force=False))  # noqa: SLF001
    await asyncio.sleep(0)
    assert state.metrics_loading and state.loaded_key.startswith(a)
    selected["id"] = b  # the owner picks B: its block mounts and asks for B
    await state._load(force=False)  # noqa: SLF001
    assert state.loaded_key.startswith(b)
    assert state.metrics_ready and state.metrics.threads_opened == b[:4]
    release_a.set()
    await first
    assert state.metrics.threads_opened == b[:4]  # A's late answer is dropped
    # The same number and period while it loads is still waited for, not doubled.
    calls: list[str] = []

    async def counted(_tenant: UUID, connection: UUID, _days: int) -> object:
        calls.append(str(connection))
        return EMPTY_METRICS

    monkeypatch.setattr(module, "conversation_metrics", counted)
    state.metrics_loading = True
    await state._load(force=True)  # noqa: SLF001
    assert calls == []
