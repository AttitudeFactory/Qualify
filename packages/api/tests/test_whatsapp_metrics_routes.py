"""WA-17 / WA-21 — the HTTP contract of `GET /api/whatsapp/metrics` and
`GET /api/whatsapp/analytics`.

Fully offline: the metrics service over `MemoryMetricsRepository`, the analytics service
over a fake Graph reader and the in-memory phone repository, a frozen clock, and the dev
principal resolver fed from `QUALIFY_DEV_PRINCIPALS` (the real 401 road). The services'
rules are `test_whatsapp_metrics.py` / `test_whatsapp_analytics.py`; this file pins the
response field names the UI codes against and the error mapping.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from qualify_api.connections.credential_reader import CredentialNotFound
from qualify_api.http import deps, whatsapp_routes
from qualify_api.http.app import create_app
from qualify_api.whatsapp.analytics import (
    AnalyticsPhone,
    MemoryAnalyticsPhoneRepository,
    WabaAnalyticsService,
)
from qualify_api.whatsapp.client import (
    MessagingDataPoint,
    PricingAnalytics,
    PricingDataPoint,
    WabaAnalytics,
    WhatsAppApiError,
)
from qualify_api.whatsapp.menus.schema import EntryConfig
from qualify_api.whatsapp.metrics import (
    CTX_HANDOFF,
    ConversationMetricsService,
    MemoryMetricsRepository,
    MessageFact,
    MetricsRows,
    ThreadFact,
)

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
TENANT_A = UUID("a1000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("b1000000-0000-4000-8000-00000000000b")
USER_A = UUID("a2000000-0000-4000-8000-00000000000a")
USER_B = UUID("b2000000-0000-4000-8000-00000000000b")
CONN_A = UUID("a4000000-0000-4000-8000-00000000000a")
CONN_B = UUID("b4000000-0000-4000-8000-00000000000b")
T1 = UUID("c1000000-0000-4000-8000-00000000000c")
T2 = UUID("c2000000-0000-4000-8000-00000000000c")
WABA = "2338576026889338"

AUTH_A = {"Authorization": "Bearer token-a"}
AUTH_B = {"Authorization": "Bearer token-b"}

METRICS_FIELDS = {
    "connection_id",
    "since",
    "until",
    "threads_opened",
    "threads_opened_by_entry",
    "orders_confirmed",
    "orders_total",
    "handoffs",
    "handoffs_by_reason",
    "first_human_responses",
    "awaiting_human_response",
    "median_first_human_response_seconds",
    "p90_first_human_response_seconds",
    "messages_in",
    "messages_out_automation",
    "messages_out_human",
    "messages_out_campaign",
    "messages_out_other",
    "delivery_failed",
    "send_failed",
    "qr_codes_available",
}
ANALYTICS_FIELDS = {
    "connection_id",
    "waba_id",
    "phone_number",
    "since",
    "until",
    "granularity",
    "currency",
    "messages",
    "sent_total",
    "delivered_total",
    "cost_by_category",
    "cost_total",
    "cost_available",
    "campaign_reconciliation",
}


class QrSource:
    def __init__(self, prefixes: Mapping[str, str] | None) -> None:
        self.prefixes = prefixes
        self.calls: list[tuple[UUID, UUID]] = []

    async def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> Mapping[str, str] | None:
        self.calls.append((tenant_id, connection_id))
        return self.prefixes


class Reader:
    def __init__(self) -> None:
        self.error: Exception | None = None
        self.factory_error: Exception | None = None
        day = datetime(2026, 10, 13, 7, tzinfo=UTC)
        self.messaging = WabaAnalytics(
            "DAY", ("573000000017",), (MessagingDataPoint(day, day + timedelta(days=1), 12, 11),)
        )
        self.pricing = PricingAnalytics(
            "COP",
            (
                PricingDataPoint(
                    day,
                    day + timedelta(days=1),
                    volume=3,
                    cost=Decimal("1350.75"),
                    pricing_category="MARKETING",
                    pricing_type="REGULAR",
                ),
                PricingDataPoint(
                    day,
                    day + timedelta(days=1),
                    volume=8,
                    cost=Decimal("0"),
                    pricing_category="SERVICE",
                    pricing_type="FREE_CUSTOMER_SERVICE",
                ),
            ),
        )
        self.calls: list[tuple[Any, ...]] = []

    async def get_waba_analytics(self, *args: Any) -> WabaAnalytics:
        self.calls.append(("analytics", *args))
        if self.error:
            raise self.error
        return self.messaging

    async def get_pricing_analytics(self, *args: Any) -> PricingAnalytics:
        self.calls.append(("pricing", *args))
        if self.error:
            raise self.error
        return self.pricing


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "QUALIFY_DEV_PRINCIPALS",
            f"token-a:{TENANT_A}:{USER_A},token-b:{TENANT_B}:{USER_B}",
        )
        self.metrics_repo = MemoryMetricsRepository()
        self.qr = QrSource({"ABCDEFGH": "Hola, vengo del mostrador"})
        self.reader = Reader()
        phones = MemoryAnalyticsPhoneRepository()
        phones.put(
            tenant_id=TENANT_A,
            connection_id=CONN_A,
            phone=AnalyticsPhone(WABA, "1393787420477981", "+57 300 000 0017"),
        )
        phones.put(
            tenant_id=TENANT_B,
            connection_id=CONN_B,
            phone=AnalyticsPhone("waba-b", "pn-b", "+1 555"),
        )
        self.clients_built: list[tuple[UUID, UUID]] = []

        async def factory(*, tenant_id: UUID, connection_id: UUID) -> Reader:
            if self.reader.factory_error is not None:
                raise self.reader.factory_error
            self.clients_built.append((tenant_id, connection_id))
            return self.reader

        metrics = ConversationMetricsService(self.metrics_repo, clock=lambda: NOW)
        analytics = WabaAnalyticsService(factory, phones, clock=lambda: NOW)
        app = create_app(configure_production=False)
        app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
        app.dependency_overrides[whatsapp_routes.get_metrics_service] = lambda: metrics
        app.dependency_overrides[whatsapp_routes.get_qr_prefix_source] = lambda: self.qr
        app.dependency_overrides[whatsapp_routes.get_analytics_service] = lambda: analytics
        self.http = TestClient(app)

    def seed(self) -> None:
        day = NOW - timedelta(days=1)
        self.metrics_repo.put(
            tenant_id=TENANT_A,
            connection_id=CONN_A,
            rows=MetricsRows(
                threads=[
                    ThreadFact(T1, day, "Hola, vengo del mostrador"),
                    ThreadFact(
                        T2,
                        day,
                        "menu",
                        context={
                            CTX_HANDOFF: {"reason": "human_requested", "at": day.isoformat()},
                            "_order": {
                                "items": [{"product_id": "p", "name": "C", "qty": 1}],
                                "total": "35000.50",
                                "currency": "COP",
                                "confirmed_at": day.isoformat(),
                            },
                        },
                        automated=True,
                    ),
                ],
                messages=[
                    MessageFact(T1, "inbound", day),
                    MessageFact(T1, "outbound", day + timedelta(minutes=5), "reply", "read"),
                    MessageFact(T2, "inbound", day),
                    MessageFact(T2, "outbound", day + timedelta(seconds=1), "automation"),
                ],
                send_failed=1,
                entry=EntryConfig(keywords={"menu": "home"}),
            ),
        )
        self.metrics_repo.put(
            tenant_id=TENANT_B, connection_id=CONN_B, rows=MetricsRows(threads=[], messages=[])
        )


@pytest.fixture
def h(monkeypatch: pytest.MonkeyPatch) -> Harness:
    harness = Harness(monkeypatch)
    harness.seed()
    return harness


# ======================================================================================
# Metrics
# ======================================================================================


def test_metrics_response_shape_and_values(h: Harness) -> None:
    r = h.http.get("/api/whatsapp/metrics", params={"connection_id": str(CONN_A)}, headers=AUTH_A)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == METRICS_FIELDS
    assert body["since"] == (NOW - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    assert body["threads_opened"] == 2
    assert body["threads_opened_by_entry"] == [
        {"kind": "keyword", "key": "menu", "threads": 1},
        {"kind": "qr", "key": "ABCDEFGH", "threads": 1},
    ]
    assert body["orders_confirmed"] == 1
    assert body["orders_total"] == {"COP": "35000.50"}
    assert body["handoffs_by_reason"] == {"human_requested": 1}
    assert body["median_first_human_response_seconds"] == 300.0
    assert body["awaiting_human_response"] == 1  # T2 handed off, nobody answered yet
    assert body["messages_out_human"] == 1
    assert body["messages_out_automation"] == 1
    assert body["send_failed"] == 1
    assert body["qr_codes_available"] is True
    assert h.qr.calls == [(TENANT_A, CONN_A)]


def test_metrics_without_qr_codes_still_answers(h: Harness) -> None:
    h.qr.prefixes = None
    r = h.http.get("/api/whatsapp/metrics", params={"connection_id": str(CONN_A)}, headers=AUTH_A)
    body = r.json()
    assert body["qr_codes_available"] is False
    assert {"kind": "directo", "key": None, "threads": 1} in body["threads_opened_by_entry"]


def test_metrics_explicit_range(h: Harness) -> None:
    r = h.http.get(
        "/api/whatsapp/metrics",
        params={
            "connection_id": str(CONN_A),
            "since": "2026-09-01T00:00:00Z",
            "until": "2026-09-08T00:00:00Z",
        },
        headers=AUTH_A,
    )
    assert r.status_code == 200
    assert r.json()["threads_opened"] == 0


def test_metrics_other_tenants_connection_is_404_and_costs_no_graph_call(h: Harness) -> None:
    r = h.http.get("/api/whatsapp/metrics", params={"connection_id": str(CONN_B)}, headers=AUTH_A)
    assert r.status_code == 404
    assert r.json()["detail"] == {"code": "connection_not_found"}
    assert h.qr.calls == []


@pytest.mark.parametrize(
    "params",
    [
        {"since": "2026-10-10T00:00:00Z", "until": "2026-10-01T00:00:00Z"},
        {"since": "2025-01-01T00:00:00Z", "until": "2026-10-01T00:00:00Z"},
    ],
)
def test_metrics_invalid_range_is_422(h: Harness, params: dict[str, str]) -> None:
    r = h.http.get(
        "/api/whatsapp/metrics", params={"connection_id": str(CONN_A), **params}, headers=AUTH_A
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_range"


def test_metrics_requires_connection_id_and_auth(h: Harness) -> None:
    assert h.http.get("/api/whatsapp/metrics", headers=AUTH_A).status_code == 422
    r = h.http.get("/api/whatsapp/metrics", params={"connection_id": str(CONN_A)})
    assert r.status_code == 401


# ======================================================================================
# Analytics
# ======================================================================================


def test_analytics_response_shape_and_values(h: Harness) -> None:
    r = h.http.get("/api/whatsapp/analytics", params={"connection_id": str(CONN_A)}, headers=AUTH_A)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == ANALYTICS_FIELDS
    assert body["waba_id"] == WABA
    assert body["phone_number"] == "+57 300 000 0017"
    assert body["granularity"] == "DAY"
    assert body["currency"] == "COP"
    assert body["messages"] == [
        {
            "start": "2026-10-13T07:00:00Z",
            "end": "2026-10-14T07:00:00Z",
            "sent": 12,
            "delivered": 11,
        }
    ]
    assert (body["sent_total"], body["delivered_total"]) == (12, 11)
    assert body["cost_by_category"] == [
        {"category": "MARKETING", "volume": 3, "billable_volume": 3, "cost": "1350.75"},
        {"category": "SERVICE", "volume": 8, "billable_volume": 0, "cost": "0"},
    ]
    assert body["cost_total"] == "1350.75"
    assert body["cost_available"] is True
    assert body["campaign_reconciliation"] is None
    assert h.clients_built == [(TENANT_A, CONN_A)]
    # Both reads: this WABA, the default range, the connection's display number.
    for call in h.reader.calls:
        assert call[1:] == (WABA, NOW - timedelta(days=7), NOW, "DAY", ["+57 300 000 0017"])


def test_analytics_month_granularity(h: Harness) -> None:
    r = h.http.get(
        "/api/whatsapp/analytics",
        params={"connection_id": str(CONN_A), "granularity": "MONTH"},
        headers=AUTH_A,
    )
    assert r.status_code == 200
    assert {c[4] for c in h.reader.calls} == {"MONTH"}
    bad = h.http.get(
        "/api/whatsapp/analytics",
        params={"connection_id": str(CONN_A), "granularity": "HALF_HOUR"},
        headers=AUTH_A,
    )
    assert bad.status_code == 422


@pytest.mark.parametrize(
    ("error", "factory_error"),
    [
        (WhatsAppApiError("x", status=401, code=190), None),
        (WhatsAppApiError("x", status=400, code=190), None),
        (None, CredentialNotFound("none")),
    ],
)
def test_analytics_reconnect_required_is_409(
    h: Harness, error: Exception | None, factory_error: Exception | None
) -> None:
    h.reader.error = error
    h.reader.factory_error = factory_error
    r = h.http.get("/api/whatsapp/analytics", params={"connection_id": str(CONN_A)}, headers=AUTH_A)
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "reconnect_required"}


def test_analytics_other_graph_error_is_502_with_code_only(h: Harness) -> None:
    h.reader.error = WhatsAppApiError(
        "get_waba_analytics failed with HTTP 400 (code=100, subcode=33)",
        status=400,
        code=100,
        subcode=33,
        error_data_details="Unsupported get request for object 2338576026889338",
    )
    r = h.http.get("/api/whatsapp/analytics", params={"connection_id": str(CONN_A)}, headers=AUTH_A)
    assert r.status_code == 502
    assert r.json()["detail"] == {"code": "graph_error", "meta_error_code": 100}
    assert "Unsupported" not in r.text


def test_analytics_other_tenants_connection_is_404(h: Harness) -> None:
    r = h.http.get("/api/whatsapp/analytics", params={"connection_id": str(CONN_B)}, headers=AUTH_A)
    assert r.status_code == 404
    assert r.json()["detail"] == {"code": "connection_not_found"}
    assert h.clients_built == []
    # Tenant B sees its own.
    ok = h.http.get(
        "/api/whatsapp/analytics", params={"connection_id": str(CONN_B)}, headers=AUTH_B
    )
    assert ok.status_code == 200
    assert ok.json()["waba_id"] == "waba-b"


def test_analytics_invalid_range_is_422(h: Harness) -> None:
    r = h.http.get(
        "/api/whatsapp/analytics",
        params={
            "connection_id": str(CONN_A),
            "since": "2026-10-10T00:00:00Z",
            "until": "2026-10-10T00:00:00Z",
        },
        headers=AUTH_A,
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "invalid_range"
    assert h.clients_built == []


def test_production_wiring_registers_the_three_dependencies() -> None:
    app = create_app(configure_production=True)
    for dep in (
        whatsapp_routes.get_metrics_service,
        whatsapp_routes.get_qr_prefix_source,
        whatsapp_routes.get_analytics_service,
    ):
        assert dep in app.dependency_overrides
