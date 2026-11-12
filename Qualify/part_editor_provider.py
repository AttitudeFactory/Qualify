"""Read-only, tenant-scoped metadata for the part editor."""

from __future__ import annotations

from typing import Any
from uuid import UUID


def video_seconds(tenant_id: UUID, key: str) -> float | None:
    """The API validates ownership before opening the object. Called off the event loop."""
    from qualify_api.creative.part_media import part_video_seconds

    return part_video_seconds(tenant_id=tenant_id, key=key)


def merge_entries(
    tenant_id: UUID, current: dict[str, Any], following: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, str]:
    """Reuse the authoritative cut and face rules; never invent a union in the UI."""
    from qualify_api.creative.parts_plan import PartsPlanRefused, merge_short_part
    from qualify_api.referentes import reel_analysis
    from qualify_creative.schemas import VideoPartPlan

    from .part_editor_vm import merge_refusal_text
    from .reel_wait_provider import part_stretch

    if following is None:
        return None, "Esta parte no tiene una siguiente. Hazla nueva."
    aid = current["plan"].get("analysis_id")
    analysis = reel_analysis.get_analysis(tenant_id, UUID(str(aid))) if aid else None
    try:
        plan = merge_short_part(
            VideoPartPlan.model_validate(current["plan"]),
            VideoPartPlan.model_validate(following["plan"]),
            analysis,
        )
    except PartsPlanRefused as exc:
        return None, merge_refusal_text(exc.reason)
    stretch = part_stretch(analysis, plan.shot_indexes) if analysis is not None else None
    return {
        **current,
        "plan": plan.model_dump(mode="json"),
        "reason": "",
        "start_s": stretch[0] if stretch else 0,
        "end_s": stretch[1] if stretch else 0,
    }, ""
