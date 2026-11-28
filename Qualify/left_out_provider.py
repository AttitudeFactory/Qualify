"""m-25143223 (PR B): the backend reads behind «Ver qué quedó fuera». Blocking: callers
run them in `asyncio.to_thread`.

One database read each — the reel's analysis through `reel_analysis.get_analysis`
(`tenant_session`, the current `ANALYSIS_VERSION` only) — then the server's pure contract
(`qualify_api.creative.left_out`). Never a vendor, a model, a download nor anything
paid: a stretch's picture is a frame the analysis already stored, signed here and read
by the browser from the frames' route (`avatar_proxy.part_thumbnail_path`).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID

from qualify_api.creative.left_out import (
    SPAN_UNKNOWN,
    SpanRefused,
    left_out_spans,
    span_entry,
)
from qualify_api.creative.plan_blocks import ClipBlocks
from qualify_api.referentes import reel_analysis
from qualify_creative.schemas import VideoPartPlan

from . import left_out_vm
from .avatar_proxy import part_thumbnail_path

logger = logging.getLogger(__name__)

Used = ClipBlocks | Sequence[VideoPartPlan] | Iterable[int]


def _named(products: Sequence[str]) -> tuple[str, ...]:
    return tuple(p for p in products if p)


def left_out_rows(
    tenant_id: UUID, analysis_id: UUID, used: Used, products: Sequence[str] = ()
) -> list[dict[str, Any]] | None:
    """Every stretch of the reel the Clip does not use NOW (`used`: its blocks, else its
    AI entries), in reel order, as `left_out_vm.span_dict` — each with its picture's
    signed path when the analysis kept a frame of it. None when the analysis is not `ok`
    (any more)."""
    analysis = reel_analysis.get_analysis(tenant_id, analysis_id)
    if analysis is None:
        return None
    found = left_out_spans(analysis, used, products=_named(products))
    return [
        left_out_vm.span_dict(
            span,
            # «de 0:44 a 0:51»'s picture: a stored frame of its cuts, else the placeholder
            thumb=part_thumbnail_path(analysis, span.shot_indexes)
            if span.thumbnail_key and span.shot_indexes
            else "",
        )
        for span in found.spans
    ]


def swap_entry(
    tenant_id: UUID,
    analysis_id: UUID,
    span_id: str,
    used: Sequence[VideoPartPlan],
    products: Sequence[str] = (),
) -> tuple[dict[str, Any] | None, str]:
    """The part of stretch `span_id` (`span_entry`: «Igual al original» or new, as the
    plan would have proposed it, checked against v1) as JSON, and "" — or (None, the
    owner's words) when the contract refuses it (`span_unknown`, `span_in_clip`,
    `extend_order`) or the analysis is gone. `used`: the Clip WITHOUT the part being
    replaced."""
    analysis = reel_analysis.get_analysis(tenant_id, analysis_id)
    if analysis is None:
        return None, left_out_vm.REFUSAL_TEXTS[SPAN_UNKNOWN]
    try:
        entry = span_entry(analysis, span_id, products=_named(products), used=used)
    except SpanRefused as exc:
        logger.info("left-out stretch refused: %s", exc.reason)
        return None, exc.text
    return entry.model_dump(mode="json"), ""


__all__ = ["left_out_rows", "swap_entry"]
