"""Backend access for «Usar como tu oferta» (m-24945889): thin wrappers over
`qualify_api.whatsapp.promotions` (`WeeklyPromotionService`), all through
`tenant_session` inside the service. Blocking: callers run them off the event loop."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qualify_api.whatsapp.attachments import PostgresAttachmentReads


@dataclass(frozen=True)
class OfferInfo:
    """A piece's brand, and whether it is that business's marked offer."""

    brand_id: UUID | None
    is_offer: bool


@dataclass(frozen=True)
class MarkResult:
    title: str
    previous_id: str = ""
    previous_title: str = ""


def _service():  # noqa: ANN202 — the backend's service, built per call (cheap)
    from qualify_api.whatsapp.promotions import (  # noqa: PLC0415
        production_weekly_promotion_service,
    )

    return production_weekly_promotion_service()


def _piece(tenant_id: UUID, draft_id: UUID):  # noqa: ANN202
    return PostgresAttachmentReads().piece(tenant_id, draft_id)


def offer_info(tenant_id: UUID, draft_id: UUID) -> OfferInfo:
    piece = _piece(tenant_id, draft_id)
    if piece is None:
        return OfferInfo(brand_id=None, is_offer=False)
    marked = _service().get_weekly_promotion(tenant_id=tenant_id, brand_id=piece.brand_id)
    return OfferInfo(
        brand_id=piece.brand_id, is_offer=marked is not None and marked.draft_id == draft_id
    )


def mark_offer(tenant_id: UUID, draft_id: UUID, user_id: UUID | None) -> MarkResult:
    """Mark it (replacing the business's previous one). Raises `PromotionNotAllowed`
    (with the owner's Spanish `.message`) for a piece that may not be an offer."""
    from qualify_api.whatsapp.promotions import PromotionNotAllowed  # noqa: PLC0415

    piece = _piece(tenant_id, draft_id)
    if piece is None:
        raise PromotionNotAllowed("Esa pieza ya no está disponible.")
    service = _service()
    before = service.get_weekly_promotion(tenant_id=tenant_id, brand_id=piece.brand_id)
    previous_id, previous_title = "", ""
    if before is not None and before.draft_id != draft_id:
        previous_id = str(before.draft_id)
        old = _piece(tenant_id, before.draft_id)
        previous_title = (old.title or "") if old is not None else ""
    service.mark_weekly_promotion(
        tenant_id=tenant_id, brand_id=piece.brand_id, draft_id=draft_id, user_id=user_id
    )
    return MarkResult(
        title=piece.title or "", previous_id=previous_id, previous_title=previous_title
    )


def unmark_offer(tenant_id: UUID, brand_id: UUID) -> bool:
    return _service().unmark_weekly_promotion(tenant_id=tenant_id, brand_id=brand_id)
