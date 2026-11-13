"""What to send, and what the screen shows, computed in memory (ADR 48 §4.2, §6). Pure: the
service and the view load rows, these functions decide.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from qualify_api.whatsapp.catalog_sync.mapping import (
    MappingContext,
    ProductSnapshot,
    ineligibility,
    product_hash,
)
from qualify_api.whatsapp.catalog_sync.media_url import CatalogMediaUnavailable

IN_FLIGHT = frozenset({"queued", "uploading"})
SYNCABLE = frozenset({"synced", "error"})

ProductState = Literal[
    "queued", "uploading", "error", "not_eligible", "not_uploaded", "out_of_date", "synced"
]
DecisionKind = Literal["new", "changed", "delete"]


@dataclass(frozen=True)
class ItemSnapshot:
    """The parts of a `whatsapp_catalog_items` row the decisions read."""

    id: UUID
    product_id: UUID | None
    retailer_id: str
    state: str
    last_pushed_hash: str | None
    error_code: str | None
    sync_version: int = 0


@dataclass(frozen=True)
class Decision:
    """One request to enqueue. `item_id` is None for a product never sent (its row is
    created at enqueue time); `content_hash` is None for a delete."""

    kind: DecisionKind
    retailer_id: str
    product_id: UUID | None
    item_id: UUID | None
    content_hash: str | None
    sync_version: int

    @property
    def op(self) -> Literal["upsert", "delete"]:
        return "delete" if self.kind == "delete" else "upsert"


@dataclass(frozen=True)
class Plan:
    decisions: tuple[Decision, ...]
    unchanged: int
    in_flight: int
    not_eligible: Mapping[str, int] = field(default_factory=dict)
    plan_key: str = ""

    def count(self, kind: DecisionKind) -> int:
        return sum(1 for d in self.decisions if d.kind == kind)


def decide_product(
    product: ProductSnapshot, item: ItemSnapshot | None, ctx: MappingContext
) -> Decision | Literal["unchanged", "in_flight"] | str:
    """One product against its item. Returns a `Decision`, `"unchanged"`, `"in_flight"`,
    or an ineligibility reason (a plain string from `INELIGIBLE_REASONS`)."""
    if item is not None and item.state in IN_FLIGHT:
        return "in_flight"
    live = item is not None and item.state in SYNCABLE
    reason = ineligibility(product)
    if reason is not None:
        if live and not product.is_active:
            assert item is not None
            return Decision(
                "delete", item.retailer_id, product.id, item.id, None, item.sync_version
            )
        return reason
    retailer_id = item.retailer_id if item is not None else str(product.id)
    digest = product_hash(product, retailer_id=retailer_id, ctx=ctx)
    if not live:
        return Decision(
            "new",
            retailer_id,
            product.id,
            item.id if item is not None else None,
            digest,
            item.sync_version if item is not None else 0,
        )
    assert item is not None
    if item.state == "error" or item.last_pushed_hash != digest:
        return Decision("changed", retailer_id, product.id, item.id, digest, item.sync_version)
    return "unchanged"


def plan_key(catalog_row_id: UUID, decisions: Iterable[Decision]) -> str:
    """What the person confirmed: the catalog and every (target, op, hash, version)."""
    body = sorted(
        [
            d.kind,
            str(d.item_id or d.product_id),
            d.content_hash or "",
            d.sync_version,
        ]
        for d in decisions
    )
    canonical = json.dumps([str(catalog_row_id), body], separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def compute_plan(
    *,
    catalog_row_id: UUID,
    products: Mapping[UUID, ProductSnapshot],
    items: Iterable[ItemSnapshot],
    ctx: MappingContext,
) -> Plan:
    """«Cargar o sincronizar todos»: new + changed eligible products, deletes of live items
    whose product is inactive or gone; equal ones and in-flight ones are only counted."""
    by_product: dict[UUID, ItemSnapshot] = {}
    orphans: list[ItemSnapshot] = []
    for item in items:
        if item.product_id is not None and item.product_id in products:
            by_product[item.product_id] = item
        else:
            orphans.append(item)

    decisions: list[Decision] = []
    unchanged = 0
    in_flight = 0
    not_eligible: Counter[str] = Counter()
    for product_id in sorted(products, key=str):
        outcome = decide_product(products[product_id], by_product.get(product_id), ctx)
        if isinstance(outcome, Decision):
            decisions.append(outcome)
        elif outcome == "unchanged":
            unchanged += 1
        elif outcome == "in_flight":
            in_flight += 1
        else:
            not_eligible[outcome] += 1
    for item in sorted(orphans, key=lambda i: str(i.id)):
        if item.state in IN_FLIGHT:
            in_flight += 1
        elif item.state in SYNCABLE:
            decisions.append(
                Decision("delete", item.retailer_id, None, item.id, None, item.sync_version)
            )
    return Plan(
        decisions=tuple(decisions),
        unchanged=unchanged,
        in_flight=in_flight,
        not_eligible=dict(not_eligible),
        plan_key=plan_key(catalog_row_id, decisions),
    )


def request_key(
    catalog_row_id: UUID, trigger: str, entries: Iterable[tuple[UUID, str, str, int]]
) -> str:
    """`sha256(catalog_row_id ‖ trigger ‖ sorted((item_id, op, hash, sync_version)))` — the
    ADR's key plus the item's `sync_version`, so retrying an item whose content did not
    change (after an error) is a NEW request, while a double click is the same one."""
    body = sorted([str(item_id), op, digest, version] for item_id, op, digest, version in entries)
    canonical = json.dumps([str(catalog_row_id), trigger, body], separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class ProductSyncState:
    """What the Galería screen shows for one product: `state` and, for `not_eligible` an
    ineligibility reason, for `error` the item's `error_code`."""

    state: ProductState
    reason: str | None = None


def product_state(
    product: ProductSnapshot,
    item: ItemSnapshot | None,
    ctx: MappingContext | None,
) -> ProductSyncState:
    """§4.2, in order. `ctx` None means the photo URL cannot be built in this process
    (`CatalogMediaUnavailable`): a synced item is then shown `synced` (nothing to compare
    against) — the actions themselves refuse to enqueue in that case.

    One refinement over the ADR's table: a synced item whose product is still active but
    no longer eligible (its photo or price removed) is `not_eligible` with the reason,
    since a resync could not send it."""
    if item is not None and item.state in IN_FLIGHT:
        return ProductSyncState(item.state)  # type: ignore[arg-type]
    if item is not None and item.state == "error":
        return ProductSyncState("error", item.error_code)
    reason = ineligibility(product)
    if item is None or item.state != "synced":
        if reason is not None:
            return ProductSyncState("not_eligible", reason)
        return ProductSyncState("not_uploaded")
    if not product.is_active:
        return ProductSyncState("out_of_date")
    if reason is not None:
        return ProductSyncState("not_eligible", reason)
    if ctx is None:
        return ProductSyncState("synced")
    try:
        digest = product_hash(product, retailer_id=item.retailer_id, ctx=ctx)
    except CatalogMediaUnavailable:
        return ProductSyncState("synced")
    if digest != item.last_pushed_hash:
        return ProductSyncState("out_of_date")
    return ProductSyncState("synced")
