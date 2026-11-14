"""ADR 48 §2, §7: the catalog client drives `items_batch` and `check_batch_request_status`
through an `httpx.MockTransport` behind the real `_InjectedAuthClient` — never Meta. Also
the pure error classification and backoff tables the worker uses."""

from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import parse_qs

import httpx
import pytest

from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.whatsapp.catalog_sync.client import (
    BatchAck,
    BatchStatus,
    FakeWhatsAppCatalogClient,
    HttpWabaCatalogLister,
    HttpWhatsAppCatalogClient,
    parse_batch_ack,
    parse_batch_status,
)
from qualify_api.whatsapp.catalog_sync.worker import (
    classify,
    poll_error_wait,
    poll_wait,
    transient_wait,
)
from qualify_api.whatsapp.client import WhatsAppApiError

TOKEN = "SUPER_SECRET_WA_SYSTEM_USER_TOKEN"
GRAPH = "https://graph.facebook.com/v21.0"
CATALOG_ID = "987654321"


class _Recorder:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.payload)


def _client(handler: object) -> HttpWhatsAppCatalogClient:
    graph = _InjectedAuthClient(TOKEN, scheme="Bearer", transport=httpx.MockTransport(handler))
    return HttpWhatsAppCatalogClient(graph, GRAPH, CATALOG_ID)


async def test_items_batch_posts_the_documented_form_fields() -> None:
    recorder = _Recorder({"handles": ["h1"], "validation_status": []})
    requests = [
        {"method": "UPDATE", "data": {"id": "p1", "image": [{"url": "https://x/1.jpg"}]}},
        {"method": "DELETE", "data": {"id": "p2"}},
    ]
    ack = await _client(recorder).items_batch(requests)
    assert ack == BatchAck(handles=("h1",))
    request = recorder.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{GRAPH}/{CATALOG_ID}/items_batch"
    form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
    assert form["item_type"] == "PRODUCT_ITEM"
    assert form["allow_upsert"] == "true"
    assert json.loads(form["requests"]) == requests
    assert request.headers["authorization"] == f"Bearer {TOKEN}"


async def test_validation_errors_are_kept_as_ids_only() -> None:
    payload = {
        "handles": ["h1"],
        "validation_status": [
            {"retailer_id": "p1", "errors": [{"message": "Título del dueño inválido"}]},
            {"retailer_id": "p2", "errors": [], "warnings": [{"message": "w"}]},
        ],
    }
    ack = await _client(_Recorder(payload)).items_batch(
        [{"method": "DELETE", "data": {"id": "p1"}}]
    )
    assert ack.rejected_ids == frozenset({"p1"})
    assert "Título" not in repr(ack)


def test_empty_handles_parse_as_nothing_ingested() -> None:
    assert parse_batch_ack({"handles": []}).handles == ()
    assert parse_batch_ack({}).handles == ()


async def test_batch_status_asks_for_the_invalid_ids() -> None:
    recorder = _Recorder(
        {
            "data": [
                {
                    "handle": "h1",
                    "status": "finished",
                    "errors_total_count": 1,
                    "ids_of_invalid_requests": ["p2"],
                }
            ]
        }
    )
    status = await _client(recorder).batch_status("h1")
    assert status == BatchStatus("finished", 1, frozenset({"p2"}))
    params = recorder.requests[0].url.params
    assert params["handle"] == "h1"
    assert params["load_ids_of_invalid_requests"] == "true"
    assert "ids_of_invalid_requests" in params["fields"]


def test_batch_status_without_data_is_an_api_error() -> None:
    with pytest.raises(WhatsAppApiError):
        parse_batch_status({"data": []})
    assert not parse_batch_status({"data": [{"status": "in_progress"}]}).finished


async def test_meta_errors_carry_codes_not_messages() -> None:
    recorder = _Recorder(
        {"error": {"code": 80014, "message": "Demasiadas llamadas: «Shawarma mixto»"}},
        status=400,
    )
    with pytest.raises(WhatsAppApiError) as caught:
        await _client(recorder).items_batch([{"method": "DELETE", "data": {"id": "p"}}])
    assert caught.value.code == 80014
    assert "Shawarma" not in str(caught.value)
    assert classify(caught.value) == "rate_limited"


async def test_transport_failures_are_marked_transport() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(WhatsAppApiError) as caught:
        await _client(boom).batch_status("h")
    assert caught.value.is_transport
    assert classify(caught.value) == "transient"


async def test_waba_lister_reads_the_catalog_ids() -> None:
    recorder = _Recorder({"data": [{"id": "111"}, {"id": "222"}]})
    graph = _InjectedAuthClient(TOKEN, scheme="Bearer", transport=httpx.MockTransport(recorder))
    assert await HttpWabaCatalogLister(graph, GRAPH).product_catalog_ids("waba1") == ["111", "222"]
    assert str(recorder.requests[0].url).startswith(f"{GRAPH}/waba1/product_catalogs")


async def test_fake_client_scripts_answers_and_records_requests() -> None:
    fake = FakeWhatsAppCatalogClient(acks=[WhatsAppApiError("x", status=500)])
    with pytest.raises(WhatsAppApiError):
        await fake.items_batch([{"method": "DELETE", "data": {"id": "a"}}])
    assert (await fake.items_batch([{"method": "DELETE", "data": {"id": "b"}}])).handles == (
        "handle-2",
    )
    assert (await fake.batch_status("handle-2")).finished
    assert len(fake.sent) == 2 and fake.polled == ["handle-2"]


# --- classification and backoff (§7) ------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (WhatsAppApiError("x", status=400, code=80014), "rate_limited"),
        (WhatsAppApiError("x", status=400, code=80009), "rate_limited"),
        (WhatsAppApiError("x", status=400, code=4), "rate_limited"),
        (WhatsAppApiError("x", status=400, code=17), "rate_limited"),
        (WhatsAppApiError("x", status=400, code=32), "rate_limited"),
        (WhatsAppApiError("x", status=400, code=613), "rate_limited"),
        (WhatsAppApiError("x", status=401), "auth_error"),
        (WhatsAppApiError("x", status=400, code=190), "auth_error"),
        (WhatsAppApiError("x", status=403, code=200), "missing_permission"),
        (WhatsAppApiError("x", status=403, code=10), "missing_permission"),
        (WhatsAppApiError("x", status=503), "transient"),
        (WhatsAppApiError("x", is_transport=True), "transient"),
        (WhatsAppApiError("x", status=400, code=100), "rejected"),
        (RuntimeError("resolver"), "transient"),
    ],
)
def test_classify(error: BaseException, kind: str) -> None:
    assert classify(error) == kind


def test_backoff_tables() -> None:
    assert [transient_wait(n) for n in (1, 2, 3, 4, 9)] == [
        timedelta(minutes=1),
        timedelta(minutes=5),
        timedelta(minutes=15),
        timedelta(minutes=60),
        timedelta(minutes=60),
    ]
    assert poll_wait(timedelta(seconds=10)) == timedelta(seconds=30)
    assert poll_wait(timedelta(minutes=2)) == timedelta(minutes=1)
    assert poll_wait(timedelta(minutes=4)) == timedelta(minutes=2)
    assert poll_wait(timedelta(minutes=10)) == timedelta(minutes=5)
    assert poll_wait(timedelta(hours=3)) == timedelta(minutes=10)
    assert poll_error_wait(timedelta(seconds=31)) == timedelta(seconds=30)
    assert poll_error_wait(timedelta(minutes=40)) == timedelta(minutes=20)
    assert poll_error_wait(timedelta(hours=5)) == timedelta(minutes=60)
