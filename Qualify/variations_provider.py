"""The seam between the «Variaciones» screens and `AngleSetService` (ticket 24803289).

Every function wraps one service call and returns `variations_vm` shapes; the service's
own exceptions pass through unchanged and the screen turns them into words with
`variations_vm.variation_error_message`. Identity is always explicit (`tenant_id`,
`brand_id`, `user_id`), never ambient.

Every function here is a blocking call — the database, and `create_variation_set` a
Claude call of several seconds — so callers on the event loop run them off-thread
(`await asyncio.to_thread(...)` inside a background event handler, as «Generar» does).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Sequence
from uuid import UUID

from qualify_api.catalog.service import UnknownProduct
from qualify_api.creative.angle_sets import AngleSetService
from qualify_api.creative.composition import (
    DEFAULT_RENDER_URL,
    RENDER_URL_ENV,
    production_angle_set_service,
)
from qualify_creative.angles import DEFAULT_ANGLE_COUNT
from qualify_creative.render.client import RemotionRenderClient

from .r2_media import is_r2_key, issue_view_path
from .variations_vm import (
    OutcomeVM,
    PlanVM,
    PresetVM,
    ProductCheckVM,
    SetSummaryVM,
    SetVM,
    build_outcome_vm,
    build_plan_vm,
    build_preset_vms,
    build_product_check_vm,
    build_set_summary_vm,
    build_set_vm,
)

logger = logging.getLogger(__name__)

#: How long one answer of the render service's health check is trusted, and how long
#: the check may take before the template preset is shown as unavailable.
RENDER_HEALTH_TTL_SECONDS = 60.0
RENDER_HEALTH_TIMEOUT_SECONDS = 2.0

_render_health: tuple[float, bool] | None = None


def _service() -> AngleSetService:
    return production_angle_set_service()


def catalog_product_id(raw: str) -> UUID:
    """The id of a CATALOG product (requirement 1), refused before any call when it is
    not one. A stock pick («Inspiración») is never a UUID — the generator keeps it as
    `stock:…` or a `t/<tenant>/stock/…` key — so parsing alone keeps it out."""
    value = (raw or "").strip()
    try:
        return UUID(value)
    except ValueError:
        raise UnknownProduct(value) from None


def render_ready(
    *,
    clock: Callable[[], float] = time.monotonic,
    client_factory: Callable[[], RemotionRenderClient] | None = None,
) -> bool:
    """Whether the render service answers its health check — cached for
    `RENDER_HEALTH_TTL_SECONDS`, with a short timeout, so a missing service (production
    does not publish it) costs one quick failed call a minute, never a hung screen."""
    global _render_health
    now = clock()
    if _render_health is not None and now - _render_health[0] < RENDER_HEALTH_TTL_SECONDS:
        return _render_health[1]
    factory = client_factory or (
        lambda: RemotionRenderClient(
            os.environ.get(RENDER_URL_ENV) or DEFAULT_RENDER_URL,
            timeout_seconds=RENDER_HEALTH_TIMEOUT_SECONDS,
        )
    )
    try:
        ready = bool(factory().health().get("ok"))
    except Exception as exc:  # noqa: BLE001 — unreachable is an answer: not available
        logger.info("render service not available: %s", type(exc).__name__)
        ready = False
    _render_health = (now, ready)
    return ready


def _preview_url(tenant_id: UUID) -> Callable[[str], str]:
    """An R2 key → its short-lived view URL; a local key → "" (the screen uses
    `rx.get_upload_url`). A token that cannot be issued only costs the preview."""

    def view(key: str) -> str:
        if not is_r2_key(key):
            return ""
        try:
            return issue_view_path(tenant_id, key, "image")
        except Exception as exc:  # noqa: BLE001 — a preview is not worth failing the page
            logger.warning("r2 media token not issued: %s", type(exc).__name__)
            return ""

    return view


# -- before the set ----------------------------------------------------------------------


def variation_presets(
    tenant_id: UUID, brand_id: UUID, product_id: str
) -> tuple[ProductCheckVM, tuple[PresetVM, ...]]:
    """The chosen product as the set will see it (photos, the price it will print or the
    «no price» note) and every preset with whether it can be used now."""
    facts, choices = _service().product_presets(
        tenant_id=tenant_id, brand_id=brand_id, product_id=catalog_product_id(product_id)
    )
    needs_render = any(preset.needs_render_service for preset, _ in choices)
    return build_product_check_vm(facts), build_preset_vms(
        choices, render_ready=render_ready() if needs_render else True
    )


def variation_plan(count: int = DEFAULT_ANGLE_COUNT) -> PlanVM:
    return build_plan_vm(_service().plan(count))


# -- the set -----------------------------------------------------------------------------


def create_variation_set(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID,
    product_id: str,
    preset_key: str,
    count: int = DEFAULT_ANGLE_COUNT,
) -> str:
    """Ask Claude for the angles of a catalog product and store them; returns the set id.
    One paid Claude call — the screen must have shown `variation_plan` first."""
    set_id = _service().create_set(
        tenant_id=tenant_id,
        brand_id=brand_id,
        user_id=user_id,
        product_id=catalog_product_id(product_id),
        preset_key=preset_key,
        count=count,
    )
    return str(set_id)


def list_variation_sets(tenant_id: UUID, brand_id: UUID) -> tuple[SetSummaryVM, ...]:
    return tuple(
        build_set_summary_vm(record)
        for record in _service().list_sets(tenant_id=tenant_id, brand_id=brand_id)
    )


def variation_set_detail(tenant_id: UUID, set_id: str) -> SetVM:
    """The set and its angles — what the gallery polls. The drafts of every angle are
    read in one batch (`ContentService.get_drafts`)."""
    detail = _service().detail(tenant_id=tenant_id, set_id=UUID(set_id))
    return build_set_vm(detail, _preview_url(tenant_id))


# -- the angles --------------------------------------------------------------------------


def discard_variation_angle(tenant_id: UUID, angle_id: str) -> None:
    _service().discard_angle(tenant_id=tenant_id, angle_id=UUID(angle_id))


def restore_variation_angle(tenant_id: UUID, angle_id: str) -> None:
    _service().restore_angle(tenant_id=tenant_id, angle_id=UUID(angle_id))


def generate_variation_pieces(
    tenant_id: UUID,
    set_id: str,
    user_id: UUID,
    angle_ids: Sequence[str] | None = None,
) -> OutcomeVM:
    """One piece per proposed angle (or per `angle_ids`): each is a paid image
    generation, dispatched out of band; a double click creates no second piece."""
    outcome = _service().generate_pieces(
        tenant_id=tenant_id,
        set_id=UUID(set_id),
        user_id=user_id,
        angle_ids=[UUID(a) for a in angle_ids] if angle_ids is not None else None,
    )
    return build_outcome_vm(outcome)


def retry_variation_angle(tenant_id: UUID, angle_id: str, user_id: UUID) -> str:
    draft_id = _service().retry_angle(tenant_id=tenant_id, angle_id=UUID(angle_id), user_id=user_id)
    return str(draft_id)


def approve_variation_angle(tenant_id: UUID, angle_id: str, user_id: UUID) -> None:
    _service().approve_angle(tenant_id=tenant_id, angle_id=UUID(angle_id), user_id=user_id)


__all__ = [
    "approve_variation_angle",
    "catalog_product_id",
    "create_variation_set",
    "discard_variation_angle",
    "generate_variation_pieces",
    "list_variation_sets",
    "render_ready",
    "restore_variation_angle",
    "retry_variation_angle",
    "variation_plan",
    "variation_presets",
    "variation_set_detail",
]
