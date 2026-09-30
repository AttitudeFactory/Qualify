"""The seam between the Canva screens and `qualify_api.canva` — blocking calls (DB and
network): callers on the event loop run them off-thread. Same split as
`creative_provider.py`: plain Python calls, exception types intact.

Not exercised against the live Canva API yet (no integration credentials, § request
2026-09-28); `docs/canva-integracion.md` lists what the first real run must confirm.
"""

from __future__ import annotations

from uuid import UUID

from qualify_api.canva import (
    CanvaNotConfigured,
    CanvaNotConnected,
    ConnectStart,
    NothingToSend,
    SentToCanva,
    UnknownReturn,
    canva_configured,
)
from qualify_api.canva.composition import production_canva_service
from qualify_api.canva.repository import LinkRecord
from qualify_creative.adapters.canva_connect import with_correlation_state

__all__ = [
    "CanvaNotConfigured",
    "CanvaNotConnected",
    "NothingToSend",
    "UnknownReturn",
    "canva_configured",
    "canva_connected",
    "canva_disconnect",
    "canva_finish_connect",
    "canva_links",
    "canva_pull",
    "canva_return",
    "canva_send",
    "canva_start_connect",
]


def canva_connected(tenant_id: UUID, user_id: UUID) -> bool:
    return production_canva_service().is_connected(tenant_id=tenant_id, user_id=user_id)


def canva_start_connect(state: str) -> ConnectStart:
    return production_canva_service().start_connect(state=state)


def canva_finish_connect(tenant_id: UUID, user_id: UUID, code: str, code_verifier: str) -> None:
    production_canva_service().finish_connect(
        tenant_id=tenant_id, user_id=user_id, code=code, code_verifier=code_verifier
    )


def canva_disconnect(tenant_id: UUID, user_id: UUID) -> None:
    production_canva_service().disconnect(tenant_id=tenant_id, user_id=user_id)


def canva_send(tenant_id: UUID, user_id: UUID, draft_id: UUID) -> SentToCanva:
    return production_canva_service().send(tenant_id=tenant_id, user_id=user_id, draft_id=draft_id)


def canva_return(tenant_id: UUID, user_id: UUID, correlation_jwt: str) -> dict[str, str]:
    link = production_canva_service().handle_return(
        tenant_id=tenant_id, user_id=user_id, correlation_jwt=correlation_jwt
    )
    return link_item(link)


def canva_pull(tenant_id: UUID, user_id: UUID, link_id: UUID) -> dict[str, str]:
    link = production_canva_service().pull(tenant_id=tenant_id, user_id=user_id, link_id=link_id)
    return link_item(link)


def canva_links(tenant_id: UUID, draft_id: UUID) -> list[dict[str, str]]:
    links = production_canva_service().links(tenant_id=tenant_id, draft_id=draft_id)
    return [link_item(link) for link in links]


_STATUS_LABELS = {
    "open": "Abierto en Canva",
    "exported": "Edición traída de Canva",
    "failed": "No se pudo traer de Canva",
}


def link_item(link: LinkRecord) -> dict[str, str]:
    """A link as the UI shows it (plain strings, Reflex-serializable)."""
    return {
        "id": str(link.id),
        "draft_id": str(link.draft_id),
        "media_type": link.media_type,
        "status": link.status,
        "status_label": _STATUS_LABELS.get(link.status, link.status),
        # reopening keeps the correlation, so Canva's "Return" still finds this row
        "open_url": with_correlation_state(link.edit_url, link.correlation_state)
        if link.edit_url
        else "",
        "exported_key": link.exported_object_key or "",
        "exported_at": link.exported_at.strftime("%d/%m %H:%M") if link.exported_at else "",
        "error": link.error or "",
    }
