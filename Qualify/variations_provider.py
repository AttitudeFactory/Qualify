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
from collections.abc import Callable, Mapping, Sequence
from functools import cache
from typing import Any
from uuid import UUID

from qualify_api.catalog.service import UnknownProduct
from qualify_api.creative.angle_sets import SET_DRAFTING, AngleSetRecord, AngleSetService
from qualify_api.creative.composition import (
    DEFAULT_RENDER_URL,
    RENDER_URL_ENV,
    production_angle_set_service,
)
from qualify_creative.angles import DEFAULT_ANGLE_COUNT, AnglePreset
from qualify_creative.render.client import RemotionRenderClient
from qualify_creative.render.registry import TemplateRegistry

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

#: (measured at, the `/health` payload or None when unreachable) — one quick call a minute.
_render_health: tuple[float, Mapping[str, Any] | None] | None = None


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
    payload = render_health(clock=clock, client_factory=client_factory)
    return bool(payload and payload.get("ok"))


def render_health(
    *,
    clock: Callable[[], float] = time.monotonic,
    client_factory: Callable[[], RemotionRenderClient] | None = None,
) -> Mapping[str, Any] | None:
    """The render service's `/health` payload (it lists the templates and versions it
    holds), or None when it does not answer — cached like `render_ready`."""
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
    payload: Mapping[str, Any] | None
    try:
        payload = dict(factory().health())
    except Exception as exc:  # noqa: BLE001 — unreachable is an answer: not available
        logger.info("render service not available: %s", type(exc).__name__)
        payload = None
    _render_health = (now, payload)
    return payload


@cache
def _template_registry() -> TemplateRegistry:
    """The app's template manifests, read from disk once per process (they are static
    files shipped with the code)."""
    return TemplateRegistry.from_dir()


def template_problem(
    preset: AnglePreset,
    health: Mapping[str, Any] | None,
    registry: TemplateRegistry | None = None,
) -> str | None:
    """Why this template preset cannot be used NOW, checked before anything is paid
    (2026-10-22: a render image with only promo_producto v1 let three pieces pay Claude
    and Seedream, then fail): the service must hold the exact version the app asks for."""
    if not preset.needs_render_service or not preset.template_id:
        return None
    if not health or not health.get("ok"):
        return (
            f"«{preset.name}» necesita el servicio de plantillas, que no está disponible "
            "en este entorno."
        )
    try:
        wanted = (registry or _template_registry()).get(preset.template_id).version
    except Exception as exc:  # noqa: BLE001 — a manifest the app cannot read is a problem
        logger.warning("template manifest unavailable: %s", type(exc).__name__)
        return f"La app no encuentra la plantilla «{preset.template_id}» en este entorno."
    held = {
        (str(t.get("id")), int(t.get("version", 0)))
        for t in health.get("templates", [])
        if isinstance(t, Mapping)
    }
    if (preset.template_id, wanted) in held:
        return None
    have = sorted(v for tid, v in held if tid == preset.template_id)
    have_text = f"la v{have[-1]}" if have else "ninguna versión"
    return (
        f"El servicio de plantillas de este entorno tiene {have_text} de "
        f"«{preset.template_id}» y la app necesita la v{wanted}: hay que reconstruir su imagen."
    )


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
    health = render_health() if needs_render else None
    checked = [(preset, problem or template_problem(preset, health)) for preset, problem in choices]
    return build_product_check_vm(facts), build_preset_vms(
        checked, render_ready=bool(health and health.get("ok")) if needs_render else True
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


def worth_listing(record: AngleSetRecord) -> bool:
    """A group with nothing standing — every angle deleted, or none ever proposed — is
    not kept on the list (request 2026-10-22: «si fallaron no guardes nada»). One still
    proposing (no rows yet) is."""
    return record.open_count != 0 or record.status == SET_DRAFTING


def list_variation_sets(tenant_id: UUID, brand_id: UUID) -> tuple[SetSummaryVM, ...]:
    return tuple(
        build_set_summary_vm(record)
        for record in _service().list_sets(tenant_id=tenant_id, brand_id=brand_id)
        if worth_listing(record)
    )


def variation_set_detail(tenant_id: UUID, set_id: str) -> SetVM:
    """The set and its angles — what the gallery polls. The drafts of every angle are
    read in one batch (`ContentService.get_drafts`)."""
    detail = _service().detail(tenant_id=tenant_id, set_id=UUID(set_id))
    return build_set_vm(detail, _preview_url(tenant_id))


# -- the angles --------------------------------------------------------------------------


def discard_variation_angle(tenant_id: UUID, angle_id: str, user_id: UUID) -> None:
    """Before or after its piece: one waiting for review is rejected with it."""
    _service().discard_angle(tenant_id=tenant_id, angle_id=UUID(angle_id), user_id=user_id)


def discard_variation_angles(tenant_id: UUID, angle_ids: Sequence[str], user_id: UUID) -> int:
    """Discard several angles in one gesture (request 2026-10-22: «elijo 2 o 3 y las demás
    no las quiero»): one service call per angle, so a refusal on one never undoes the
    others. Returns how many went through."""
    done = 0
    for angle_id in angle_ids:
        try:
            discard_variation_angle(tenant_id, angle_id, user_id)
        except Exception as exc:  # noqa: BLE001 — the rest still go; the count says it
            logger.warning("variations: discard skipped one angle: %s", type(exc).__name__)
            continue
        done += 1
    return done


def archive_variation_set(tenant_id: UUID, set_id: str, user_id: UUID) -> int:
    """«Eliminar grupo»: off the list for good; its open angles discarded."""
    return _service().archive_set(tenant_id=tenant_id, set_id=UUID(set_id), user_id=user_id)


def save_variation_angle(tenant_id: UUID, angle_id: str, saved: bool) -> None:
    """«Guardar para después» (True) or take the angle up again (False)."""
    _service().save_angle(tenant_id=tenant_id, angle_id=UUID(angle_id), saved=saved)


def save_variation_angles(tenant_id: UUID, angle_ids: Sequence[str]) -> int:
    """Put several aside in one gesture; a refusal on one never undoes the others."""
    done = 0
    for angle_id in angle_ids:
        try:
            save_variation_angle(tenant_id, angle_id, True)
        except Exception as exc:  # noqa: BLE001 — the rest still go; the count says it
            logger.warning("variations: save skipped one angle: %s", type(exc).__name__)
            continue
        done += 1
    return done


def restore_variation_angle(tenant_id: UUID, angle_id: str) -> None:
    _service().restore_angle(tenant_id=tenant_id, angle_id=UUID(angle_id))


def edit_variation_angle(
    tenant_id: UUID,
    angle_id: str,
    scene: str,
    composition: str,
    *,
    title: str | None = None,
    hook: str | None = None,
    cta: str | None = None,
    rationale: str | None = None,
) -> None:
    _service().edit_angle(
        tenant_id=tenant_id,
        angle_id=UUID(angle_id),
        scene=scene,
        composition=composition,
        title=title,
        hook=hook,
        cta=cta,
        rationale=rationale,
    )


def regenerate_variation_angle(tenant_id: UUID, angle_id: str, user_id: UUID) -> str:
    """Another take of a piece that did not convince — a paid image, the old draft
    rejected. Returns the new draft id."""
    draft_id = _service().regenerate_angle(
        tenant_id=tenant_id, angle_id=UUID(angle_id), user_id=user_id
    )
    return str(draft_id)


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
    "archive_variation_set",
    "catalog_product_id",
    "create_variation_set",
    "discard_variation_angle",
    "edit_variation_angle",
    "generate_variation_pieces",
    "list_variation_sets",
    "regenerate_variation_angle",
    "render_ready",
    "restore_variation_angle",
    "save_variation_angle",
    "save_variation_angles",
    "retry_variation_angle",
    "variation_plan",
    "variation_presets",
    "variation_set_detail",
]
