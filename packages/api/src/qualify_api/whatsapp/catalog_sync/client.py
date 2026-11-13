"""The Meta catalog client seam (ADR 48 §2, §7): `items_batch` + `check_batch_request_status`,
and the WABA's `product_catalogs` list the connect CLI checks.

Same discipline as `whatsapp/client.py`, whose `_raise_for_status`/`_json_object` it
reuses: a `Protocol` the worker depends on, one HTTP implementation over an
already-authenticated client (the token never reaches this module), parsers that keep only
ids, counts, statuses and numeric codes. **Meta's `message` strings are never kept** —
they can repeat the owner's product title (§4.3).

Shapes are `[DOC]` (read 2026-11-12, ADR 48 §2) until the live test P1 promotes them.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from qualify_api.connections.resolver import AuthenticatedClient
from qualify_api.whatsapp.client import WhatsAppApiError, _json_object, _raise_for_status

ITEM_TYPE = "PRODUCT_ITEM"
_STATUS_FIELDS = "handle,status,warnings,errors_total_count,ids_of_invalid_requests"


@dataclass(frozen=True)
class BatchAck:
    """`items_batch` answer: the handles (empty = nothing ingested) and the retailer ids
    `validation_status` reported with `errors` (warnings are ignored)."""

    handles: tuple[str, ...]
    rejected_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class BatchStatus:
    """`check_batch_request_status` → `data[0]`: `status` (`finished` is the only value the
    docs show) and the retailer ids Meta found invalid."""

    status: str
    errors_total_count: int = 0
    invalid_ids: frozenset[str] = frozenset()

    @property
    def finished(self) -> bool:
        return self.status == "finished"


class WhatsAppCatalogClient(Protocol):
    async def items_batch(self, requests: Sequence[dict[str, Any]]) -> BatchAck: ...

    async def batch_status(self, handle: str) -> BatchStatus: ...


class WabaCatalogLister(Protocol):
    async def product_catalog_ids(self, waba_id: str) -> list[str]: ...


def _str_ids(values: object) -> frozenset[str]:
    if not isinstance(values, list):
        return frozenset()
    return frozenset(str(v) for v in values if isinstance(v, str | int) and str(v))


def parse_batch_ack(payload: dict[str, Any]) -> BatchAck:
    """[DOC] items_batch: `{"handles": [...], "validation_status": [{"retailer_id",
    "errors": [{"message"}], "warnings": [...]}]}`. Only the ids with errors are kept."""
    handles = payload.get("handles")
    handle_list = (
        tuple(h for h in handles if isinstance(h, str) and h) if isinstance(handles, list) else ()
    )
    rejected: set[str] = set()
    statuses = payload.get("validation_status")
    if isinstance(statuses, list):
        for entry in statuses:
            if not isinstance(entry, dict):
                continue
            retailer_id = entry.get("retailer_id")
            errors = entry.get("errors")
            if isinstance(retailer_id, str | int) and isinstance(errors, list) and errors:
                rejected.add(str(retailer_id))
    return BatchAck(handles=handle_list, rejected_ids=frozenset(rejected))


def parse_batch_status(payload: dict[str, Any]) -> BatchStatus:
    """[DOC] check_batch_request_status: `{"data": [{"handle", "status", "warnings",
    "errors_total_count", "ids_of_invalid_requests"}]}`."""
    data = payload.get("data")
    first = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else None
    if first is None:
        raise WhatsAppApiError("batch status response carried no data[0]")
    status = first.get("status")
    count = first.get("errors_total_count")
    return BatchStatus(
        status=status if isinstance(status, str) else "",
        errors_total_count=count if isinstance(count, int) else 0,
        invalid_ids=_str_ids(first.get("ids_of_invalid_requests")),
    )


class HttpWhatsAppCatalogClient:
    """Real client for ONE catalog, bound at construction (a caller cannot reach another
    tenant's catalog by passing a different id). The `AuthenticatedClient` comes from
    `CredentialResolver.client_for(<the number's connection>, scheme=…)`."""

    def __init__(self, graph_client: AuthenticatedClient, graph_url: str, catalog_id: str) -> None:
        if not catalog_id:
            raise ValueError("catalog_id must not be empty")
        self._graph = graph_client
        self._graph_url = graph_url.rstrip("/")
        self._catalog_id = catalog_id

    async def items_batch(self, requests: Sequence[dict[str, Any]]) -> BatchAck:
        if not requests:
            raise ValueError("items_batch needs at least one request")
        form = {
            "item_type": ITEM_TYPE,
            "allow_upsert": "true",
            "requests": json.dumps(list(requests), separators=(",", ":"), ensure_ascii=False),
        }
        try:
            response = await self._graph.post(
                f"{self._graph_url}/{self._catalog_id}/items_batch", data=form
            )
        except httpx.TransportError as exc:
            raise WhatsAppApiError(
                "transport failure during items_batch", is_transport=True
            ) from exc
        _raise_for_status(response, "items_batch")
        return parse_batch_ack(_json_object(response, "items_batch"))

    async def aclose(self) -> None:
        close = getattr(self._graph, "aclose", None)
        if close is not None:
            await close()

    async def batch_status(self, handle: str) -> BatchStatus:
        try:
            response = await self._graph.get(
                f"{self._graph_url}/{self._catalog_id}/check_batch_request_status",
                params={
                    "handle": handle,
                    "load_ids_of_invalid_requests": "true",
                    "fields": _STATUS_FIELDS,
                },
            )
        except httpx.TransportError as exc:
            raise WhatsAppApiError(
                "transport failure during batch_status", is_transport=True
            ) from exc
        _raise_for_status(response, "batch_status")
        return parse_batch_status(_json_object(response, "batch_status"))


class HttpWabaCatalogLister:
    """`GET /{waba_id}/product_catalogs` → the catalog ids (ADR 48 §9 step 3)."""

    def __init__(self, graph_client: AuthenticatedClient, graph_url: str) -> None:
        self._graph = graph_client
        self._graph_url = graph_url.rstrip("/")

    async def product_catalog_ids(self, waba_id: str) -> list[str]:
        try:
            response = await self._graph.get(
                f"{self._graph_url}/{waba_id}/product_catalogs", params={"fields": "id"}
            )
        except httpx.TransportError as exc:
            raise WhatsAppApiError(
                "transport failure during product_catalogs", is_transport=True
            ) from exc
        _raise_for_status(response, "product_catalogs")
        data = _json_object(response, "product_catalogs").get("data")
        if not isinstance(data, list):
            return []
        return [str(c["id"]) for c in data if isinstance(c, dict) and c.get("id")]


# --- fakes (tests and the UI engineer's local runs; never Meta) ---------------------------


@dataclass
class FakeWhatsAppCatalogClient:
    """In-memory `WhatsAppCatalogClient`. Script the answers: `acks`/`statuses` are popped
    in order (an exception instance is raised instead of returned); with nothing scripted,
    every batch is acked with one handle and every status is `finished` with no invalids."""

    acks: list[BatchAck | Exception] = field(default_factory=list)
    statuses: list[BatchStatus | Exception] = field(default_factory=list)
    sent: list[list[dict[str, Any]]] = field(default_factory=list)
    polled: list[str] = field(default_factory=list)

    async def items_batch(self, requests: Sequence[dict[str, Any]]) -> BatchAck:
        self.sent.append([dict(r) for r in requests])
        if self.acks:
            answer = self.acks.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return BatchAck(handles=(f"handle-{len(self.sent)}",))

    async def batch_status(self, handle: str) -> BatchStatus:
        self.polled.append(handle)
        if self.statuses:
            answer = self.statuses.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer
        return BatchStatus(status="finished")


@dataclass
class FakeWabaCatalogLister:
    catalogs: dict[str, list[str]] = field(default_factory=dict)
    error: Exception | None = None

    async def product_catalog_ids(self, waba_id: str) -> list[str]:
        if self.error is not None:
            raise self.error
        return list(self.catalogs.get(waba_id, []))
