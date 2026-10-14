"""WA-21 — WABA analytics: the client's two Graph reads and the summary service.

The client half drives the REAL `HttpWhatsAppClient` through an `httpx.MockTransport`
behind a real `_InjectedAuthClient` (as `test_whatsapp_client.py` does), answering with
the doc-derived fixtures `waba_analytics_response.json` / `pricing_analytics_response.json`.
The service half uses a fake reader and the in-memory phone repository.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
import pytest

from qualify_api.connections.credential_reader import CredentialNotFound
from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.whatsapp.analytics import (
    AnalyticsPhone,
    MemoryAnalyticsPhoneRepository,
    ReconnectRequired,
    WabaAnalyticsService,
    summarize_pricing,
)
from qualify_api.whatsapp.client import (
    HttpWhatsAppClient,
    MessagingDataPoint,
    PricingAnalytics,
    PricingDataPoint,
    WabaAnalytics,
    WhatsAppApiError,
    build_analytics_fields,
    build_pricing_analytics_fields,
)
from qualify_api.whatsapp.metrics import ConnectionNotFound, InvalidRange

FIXTURES = Path(__file__).parent / "fixtures" / "whatsapp"
TOKEN = "SUPER_SECRET_WA_SYSTEM_USER_TOKEN"
GRAPH = "https://graph.facebook.com/v21.0"
WABA = "2338576026889338"
START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 10, 8, tzinfo=UTC)
TENANT = UUID("a1000000-0000-4000-8000-00000000000a")
CONN = UUID("a4000000-0000-4000-8000-00000000000a")
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def _fixture(name: str) -> dict[str, Any]:
    payload = json.loads((FIXTURES / name).read_text())
    assert "DOC-DERIVED" in payload.pop("_fixture_note")
    return payload


class _Recorder:
    def __init__(self, payload: dict[str, Any], status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.payload)

    @property
    def fields(self) -> str:
        assert len(self.requests) == 1
        return parse_qs(urlsplit(str(self.requests[0].url)).query)["fields"][0]


def _client(recorder: _Recorder) -> HttpWhatsAppClient:
    return HttpWhatsAppClient(
        graph_client=_InjectedAuthClient(
            TOKEN, scheme="Bearer", transport=httpx.MockTransport(recorder)
        ),
        graph_url=GRAPH,
        phone_number_id="1393787420477981",
    )


# ======================================================================================
# Request builders
# ======================================================================================


def test_analytics_fields_follow_the_doc_example() -> None:
    assert build_analytics_fields(START, END, "DAY") == (
        "analytics.start(1790812800).end(1791417600).granularity(DAY)"
    )
    assert build_analytics_fields(START, END, "MONTH", ["+57 300 000 0017"]) == (
        "analytics.start(1790812800).end(1791417600).granularity(MONTH)"
        '.phone_numbers(["573000000017"])'
    )


def test_pricing_fields_translate_granularity_and_ask_currency() -> None:
    assert build_pricing_analytics_fields(START, END, "DAY", ["15550001234"]) == (
        "currency,pricing_analytics.start(1790812800).end(1791417600).granularity(DAILY)"
        '.phone_numbers(["15550001234"]).dimensions(PRICING_CATEGORY,PRICING_TYPE)'
    )
    assert ".granularity(MONTHLY)" in build_pricing_analytics_fields(START, END, "MONTH")


def test_naive_instants_are_utc_and_empty_phone_lists_mean_all() -> None:
    naive = build_analytics_fields(START.replace(tzinfo=None), END.replace(tzinfo=None), "DAY")
    assert naive == build_analytics_fields(START, END, "DAY")
    assert "phone_numbers" not in build_analytics_fields(START, END, "DAY", ["", "+"])


# ======================================================================================
# Client — waba analytics
# ======================================================================================


async def test_get_waba_analytics_request_and_parse() -> None:
    recorder = _Recorder(_fixture("waba_analytics_response.json"))
    result = await _client(recorder).get_waba_analytics(
        WABA, START, END, "DAY", ["+1 650-555-0111"]
    )
    request = recorder.requests[0]
    assert request.method == "GET"
    assert str(request.url).startswith(f"{GRAPH}/{WABA}?")
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url)
    assert recorder.fields == build_analytics_fields(START, END, "DAY", ["16505550111"])

    assert result.granularity == "DAY"
    assert result.phone_numbers == ("16505550111", "16505550112", "16505550113")
    # Sorted by start, whatever order Meta sent them in.
    assert result.data_points[0] == MessagingDataPoint(
        start=datetime.fromtimestamp(1543543200, tz=UTC),
        end=datetime.fromtimestamp(1543629600, tz=UTC),
        sent=196093,
        delivered=179715,
    )
    assert [p.sent for p in result.data_points] == [196093, 147649, 61988, 132465]


async def test_waba_analytics_without_the_field_is_empty() -> None:
    result = await _client(_Recorder({"id": WABA})).get_waba_analytics(WABA, START, END, "DAY")
    assert result == WabaAnalytics(granularity=None, phone_numbers=(), data_points=())


async def test_waba_analytics_skips_malformed_points() -> None:
    payload = {
        "analytics": {
            "data_points": [
                {"start": "x", "end": 1, "sent": 1},
                "junk",
                {"start": 1543543200, "end": 1543629600},
            ]
        }
    }
    result = await _client(_Recorder(payload)).get_waba_analytics(WABA, START, END, "DAY")
    assert len(result.data_points) == 1
    assert result.data_points[0].sent == 0


@pytest.mark.parametrize(
    ("waba", "start", "end", "granularity"),
    [("", START, END, "DAY"), (WABA, END, START, "DAY"), (WABA, START, END, "HALF_HOUR")],
)
async def test_analytics_validation_raises_before_any_request(
    waba: str, start: datetime, end: datetime, granularity: Any
) -> None:
    recorder = _Recorder({})
    with pytest.raises(ValueError):
        await _client(recorder).get_waba_analytics(waba, start, end, granularity)
    with pytest.raises(ValueError):
        await _client(recorder).get_pricing_analytics(waba, start, end, granularity)
    assert recorder.requests == []


async def test_analytics_graph_errors_carry_codes_not_bodies() -> None:
    auth = _fixture("error_auth_190.json")
    with pytest.raises(WhatsAppApiError) as info:
        await _client(_Recorder(auth, status=401)).get_waba_analytics(WABA, START, END, "DAY")
    assert info.value.is_auth_error
    assert TOKEN not in str(info.value)

    other = {"error": {"message": "Unsupported get request", "code": 100, "error_subcode": 33}}
    with pytest.raises(WhatsAppApiError) as info:
        await _client(_Recorder(other, status=400)).get_pricing_analytics(WABA, START, END, "DAY")
    assert not info.value.is_auth_error
    assert (info.value.status, info.value.code) == (400, 100)


# ======================================================================================
# Client — pricing analytics
# ======================================================================================


async def test_get_pricing_analytics_request_and_parse() -> None:
    recorder = _Recorder(_fixture("pricing_analytics_response.json"))
    result = await _client(recorder).get_pricing_analytics(
        WABA, START, END, "MONTH", ["16505550111"]
    )
    assert recorder.fields == build_pricing_analytics_fields(START, END, "MONTH", ["16505550111"])
    assert result.currency == "USD"
    assert len(result.data_points) == 8
    first = result.data_points[0]
    assert first.start == datetime.fromtimestamp(1748761200, tz=UTC)
    # The earliest AUTHENTICATION_INTERNATIONAL point (1748847600) costs 2.3 — a float in
    # the JSON, an exact Decimal here (no binary noise).
    auth = next(
        p for p in result.data_points if p.pricing_category == "AUTHENTICATION_INTERNATIONAL"
    )
    assert (auth.cost, auth.tier, auth.country) == (Decimal("2.3"), "0:750000", "IN")
    free = [p for p in result.data_points if p.pricing_type != "REGULAR"]
    assert len(free) == 3
    assert all(p.tier is None and p.cost == Decimal("0") for p in free)


async def test_pricing_without_cost_is_cost_unavailable() -> None:
    payload = {
        "pricing_analytics": {
            "data": [
                {
                    "data_points": [
                        {
                            "start": 1748761200,
                            "end": 1748847600,
                            "pricing_type": "REGULAR",
                            "pricing_category": "MARKETING",
                            "volume": 3,
                        }
                    ]
                }
            ]
        }
    }
    result = await _client(_Recorder(payload)).get_pricing_analytics(WABA, START, END, "DAY")
    assert result.currency is None
    assert result.data_points[0].cost is None
    categories, available = summarize_pricing(result)
    assert not available
    assert categories[0].cost is None and categories[0].volume == 3


# ======================================================================================
# Service
# ======================================================================================


class FakeReader:
    def __init__(
        self,
        messaging: WabaAnalytics | None = None,
        pricing: PricingAnalytics | None = None,
        error: WhatsAppApiError | None = None,
    ) -> None:
        self.messaging = messaging or WabaAnalytics(None, (), ())
        self.pricing = pricing or PricingAnalytics(None, ())
        self.error = error
        self.calls: list[tuple[str, str, datetime, datetime, str, list[str] | None]] = []

    async def get_waba_analytics(self, waba_id, start, end, granularity, phone_numbers=None):  # noqa: ANN001, ANN201
        self.calls.append(("analytics", waba_id, start, end, granularity, list(phone_numbers)))
        if self.error:
            raise self.error
        return self.messaging

    async def get_pricing_analytics(self, waba_id, start, end, granularity, phone_numbers=None):  # noqa: ANN001, ANN201
        self.calls.append(("pricing", waba_id, start, end, granularity, list(phone_numbers)))
        if self.error:
            raise self.error
        return self.pricing


def _service(reader: FakeReader) -> tuple[WabaAnalyticsService, list[tuple[UUID, UUID]]]:
    phones = MemoryAnalyticsPhoneRepository()
    phones.put(
        tenant_id=TENANT,
        connection_id=CONN,
        phone=AnalyticsPhone(waba_id=WABA, phone_number_id="pn-1", display_phone_number="+57 300"),
    )
    built: list[tuple[UUID, UUID]] = []

    async def factory(*, tenant_id: UUID, connection_id: UUID) -> FakeReader:
        built.append((tenant_id, connection_id))
        return reader

    return WabaAnalyticsService(factory, phones, clock=lambda: NOW), built


def _point(day: int, category: str, ptype: str, volume: int, cost: str | None) -> PricingDataPoint:
    start = datetime(2026, 10, day, 7, tzinfo=UTC)
    return PricingDataPoint(
        start=start,
        end=start + timedelta(days=1),
        volume=volume,
        cost=Decimal(cost) if cost is not None else None,
        pricing_category=category,
        pricing_type=ptype,
    )


async def test_summary_folds_days_and_categories() -> None:
    day = datetime(2026, 10, 2, 7, tzinfo=UTC)
    reader = FakeReader(
        messaging=WabaAnalytics(
            "DAY",
            ("57300",),
            (
                MessagingDataPoint(day, day + timedelta(days=1), sent=10, delivered=9),
                MessagingDataPoint(
                    day + timedelta(days=1), day + timedelta(days=2), sent=5, delivered=5
                ),
            ),
        ),
        pricing=PricingAnalytics(
            "COP",
            (
                _point(2, "MARKETING", "REGULAR", 4, "1200.50"),
                _point(3, "MARKETING", "REGULAR", 2, "600.25"),
                _point(2, "SERVICE", "FREE_CUSTOMER_SERVICE", 7, "0"),
                _point(2, "UTILITY", "FREE_CUSTOMER_SERVICE", 1, "0"),
                _point(3, "UTILITY", "REGULAR", 3, "90"),
                PricingDataPoint(day, day, volume=1, cost=None),
            ),
        ),
    )
    service, built = _service(reader)
    result = await service.summary(TENANT, CONN)

    assert built == [(TENANT, CONN)]
    # Default range: the last 7 days, both reads filtered to the connection's number.
    assert {c[0] for c in reader.calls} == {"analytics", "pricing"}
    for call in reader.calls:
        assert call[1:] == (WABA, NOW - timedelta(days=7), NOW, "DAY", ["+57 300"])

    assert result.phone_number == "+57 300"
    assert result.currency == "COP"
    assert (result.sent_total, result.delivered_total) == (15, 14)
    assert [b.sent for b in result.messages] == [10, 5]
    assert [(c.category, c.volume, c.billable_volume, c.cost) for c in result.cost_by_category] == [
        ("MARKETING", 6, 6, Decimal("1800.75")),
        ("UTILITY", 4, 3, Decimal("90")),
        ("SERVICE", 7, 0, Decimal("0")),
        ("UNKNOWN", 1, 0, None),
    ]
    assert result.cost_total == Decimal("1890.75")
    assert result.cost_available
    assert result.campaign_reconciliation is None


async def test_summary_without_any_cost() -> None:
    reader = FakeReader(
        pricing=PricingAnalytics(None, (_point(2, "MARKETING", "REGULAR", 2, None),))
    )
    service, _ = _service(reader)
    result = await service.summary(TENANT, CONN, since=START, until=END, granularity="MONTH")
    assert not result.cost_available
    assert result.cost_total is None
    assert result.granularity == "MONTH"


async def test_summary_unknown_connection_never_builds_a_client() -> None:
    reader = FakeReader()
    service, built = _service(reader)
    with pytest.raises(ConnectionNotFound):
        await service.summary(TENANT, UUID(int=1))
    with pytest.raises(InvalidRange):
        await service.summary(TENANT, CONN, since=END, until=START)
    assert built == []


@pytest.mark.parametrize(
    "error",
    [
        WhatsAppApiError("x", status=401, code=None),
        WhatsAppApiError("x", status=400, code=190),
    ],
)
async def test_graph_auth_errors_become_reconnect_required(error: WhatsAppApiError) -> None:
    service, _ = _service(FakeReader(error=error))
    with pytest.raises(ReconnectRequired):
        await service.summary(TENANT, CONN)


async def test_other_graph_errors_propagate() -> None:
    service, _ = _service(FakeReader(error=WhatsAppApiError("x", status=400, code=100)))
    with pytest.raises(WhatsAppApiError) as info:
        await service.summary(TENANT, CONN)
    assert info.value.code == 100


async def test_missing_credential_becomes_reconnect_required() -> None:
    phones = MemoryAnalyticsPhoneRepository()
    phones.put(
        tenant_id=TENANT,
        connection_id=CONN,
        phone=AnalyticsPhone(waba_id=WABA, phone_number_id="pn-1", display_phone_number="1"),
    )

    async def factory(*, tenant_id: UUID, connection_id: UUID) -> FakeReader:
        raise CredentialNotFound("none")

    service = WabaAnalyticsService(factory, phones, clock=lambda: NOW)
    with pytest.raises(ReconnectRequired):
        await service.summary(TENANT, CONN)


def test_reconcile_with_campaigns_is_a_placeholder() -> None:
    service, _ = _service(FakeReader())
    assert service.reconcile_with_campaigns(TENANT, CONN, START, END) is None
