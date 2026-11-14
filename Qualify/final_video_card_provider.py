"""Backend access of «Tu video completo» (m-24921084, `docs/ux-video-por-planos.md` §3e).

Plain, blocking Python over the production content service — the state runs every call
with `asyncio.to_thread`. Every read and write goes through the backend's own doors
(`FinalVideoReader`, `rejoin`, `ContentService.approve_parts`,
`PartsService.regenerate_part`), which open `tenant_session` / `tenant_unit_of_work`
themselves: RLS scopes every row to the tenant, nothing here filters by hand.

Exception types reach the caller intact; `final_video_card_state.refusal_text` turns
them into the owner's words.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from qualify_api.creative.composition import production_content_service
from qualify_api.creative.final_video import FinalVideo, FinalVideoReader
from qualify_api.creative.final_video import rejoin as backend_rejoin
from qualify_api.creative.parts import PartChanges, PartsService
from qualify_api.planner.composition import tenant_timezone

from .creative_vm import (
    APPROVED_NOT_READY_TOAST,
    APPROVED_TOAST,
    approval_notice,
    renewal_day_label,
)
from .final_video_vm import FinalVideoCardVM, final_video_card
from .r2_media import is_r2_key, issue_view_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CardRead:
    """One read of the card: its view model plus what the view needs around it."""

    vm: FinalVideoCardVM
    state: str
    video_key: str = ""
    video_url: str = ""  # `/r2media/<token>` when the joined preview lives in R2
    poster_key: str = ""
    poster_url: str = ""
    parts: tuple[int, ...] = ()  # the parts «Cambiar una parte» may change (made ones)
    #: each of those parts as «Cambiar una parte» draws it: index, poster key and URL
    thumbs: tuple[dict[str, str], ...] = ()
    renews: str = ""  # «1 de diciembre»: when the month's video/vistas previas renew
    preview_quota: int = 0


@dataclass(frozen=True)
class Approval:
    """What approving left behind, for the toast and the «Aprobada» card — the same
    words the piece's own page uses (`creative_vm.approval_notice`)."""

    kind: str  # rx.toast kind: success / info / warning
    text: str
    ready: bool  # Tu semana can plan it now («Elegir día y hora»)
    note: str  # why not, in the evaluator's words ("" when ready)


def _view(tenant_id: UUID, key: str | None, media_type: str) -> str:
    """A short-lived `/r2media` path for an R2 key ("" otherwise, or when no token can
    be minted: the preview is not worth failing the card)."""
    if not key or not is_r2_key(key):
        return ""
    try:
        return issue_view_path(tenant_id, key, media_type)
    except Exception as exc:  # noqa: BLE001 — a missing preview must not break the card
        logger.warning("final video token not issued: %s", type(exc).__name__)
        return ""


def _zone(tenant_id: UUID) -> str:
    try:
        return tenant_timezone(tenant_id)
    except Exception as exc:  # noqa: BLE001 — the deadline falls back to UTC
        logger.warning("tenant zone unreadable: %s", type(exc).__name__)
        return "UTC"


def card_from(final: FinalVideo, tenant_id: UUID, zone: str) -> CardRead:
    """The card of one `FinalVideo` read. Pure but for minting the media tokens."""
    use = final.video_use
    previews = final.recreate_use
    renews_on = (use.renews_on if use else None) or (previews.renews_on if previews else None)
    return CardRead(
        vm=final_video_card(final, zone=zone),
        state=str(final.state),
        video_key=final.video_key or "",
        video_url=_view(tenant_id, final.video_key, "video"),
        poster_key=final.poster_key or "",
        poster_url=_view(tenant_id, final.poster_key, "image"),
        # only the parts that can change NOW (`FinalVideo.changeable_parts`): never one
        # «En fila», being made, never created or purged (live test 2026-11-10)
        parts=tuple(p.index for p in final.changeable_parts),
        thumbs=tuple(
            {
                "index": str(p.index),  # what `regenerate_part` takes
                "number": str(p.shown),  # what the owner reads (no gap after a removal)
                "key": p.poster_key or "",
                "url": _view(tenant_id, p.poster_key, "image"),
            }
            for p in final.changeable_parts
        ),
        renews=renewal_day_label(renews_on),
        preview_quota=previews.quota if previews else 0,
    )


def read_card(tenant_id: UUID, parent_id: UUID) -> CardRead | None:
    """«Tu video completo» of `parent_id`, or None when it is not a video by parts of
    this business (another business's reads as missing, RLS)."""
    final = FinalVideoReader(production_content_service()).read(
        tenant_id=tenant_id, parent_id=parent_id
    )
    if final is None:
        return None
    return card_from(final, tenant_id, _zone(tenant_id))


def _variant_of(service: object, tenant_id: UUID, parent_id: UUID) -> UUID:
    """The parent's text to approve with: the one picked before, else its first."""
    from qualify_api.creative.service import UnknownVariant  # noqa: PLC0415

    repo = service.repository  # type: ignore[attr-defined]
    record = repo.get_draft(tenant_id=tenant_id, draft_id=parent_id)
    variants = repo.variants_for(tenant_id=tenant_id, draft_id=parent_id)
    if not variants:
        raise UnknownVariant(str(parent_id))
    chosen = getattr(record, "selected_variant_id", None)
    if chosen is not None and any(v.id == chosen for v in variants):
        return chosen
    return min(variants, key=lambda v: v.ordinal).id


def _readiness(tenant_id: UUID, parent_id: UUID) -> tuple[bool, str]:
    """m-24842978: «Elegir día y hora» only for a publication Tu semana can plan — the
    same reader the piece's page uses after approving. Unreadable: offered anyway, Tu
    semana is the real gate."""
    from .gallery_state import schedule_readiness  # noqa: PLC0415
    from .planner_provider import load_gallery  # noqa: PLC0415

    try:
        gallery = load_gallery(tenant_id)
        return schedule_readiness(list(gallery.posts), str(parent_id))
    except Exception as exc:  # noqa: BLE001 — the approval already stands
        logger.warning("readiness after approve failed: %s", type(exc).__name__)
        return True, ""


def approve(tenant_id: UUID, parent_id: UUID, user_id: UUID) -> Approval:
    """«Aprobar» the whole video once (`ContentService.approve_parts`, ADR 44 F8): every
    part's seconds charged together, all or nothing, and one final per part ordered.
    Then what the piece's page says after any approval (`approval_notice`)."""
    from .creative_provider import draft_detail  # noqa: PLC0415

    service = production_content_service()
    service.approve_parts(
        tenant_id=tenant_id,
        parent_id=parent_id,
        variant_id=_variant_of(service, tenant_id, parent_id),
        user_id=user_id,
    )
    ready, note = _readiness(tenant_id, parent_id)
    try:
        vm = draft_detail(tenant_id, parent_id)
    except Exception as exc:  # noqa: BLE001 — the approval already stands
        logger.warning("draft unreadable after approve: %s", type(exc).__name__)
        vm = None
    if vm is None:  # approved, then unreadable: the approval stands, the words are generic
        kind, text = ("success", APPROVED_TOAST) if ready else ("info", APPROVED_NOT_READY_TOAST)
    else:
        notice = approval_notice(vm.video_draft, ready=ready)
        kind, text = notice.kind, notice.text
    return Approval(kind=kind, text=text, ready=ready, note=note)


def rejoin(tenant_id: UUID, parent_id: UUID) -> bool:
    """«Juntar otra vez»: ours, 0 USD, nothing charged. False when it cannot."""
    return backend_rejoin(tenant_id=tenant_id, parent_id=parent_id)


def recreate_expired(tenant_id: UUID, parent_id: UUID, user_id: UUID) -> tuple[int, ...]:
    """«Crear la parte N otra vez»: only the expired parts, all or nothing."""
    return FinalVideoReader(production_content_service()).recreate_expired_parts(
        tenant_id=tenant_id, parent_id=parent_id, user_id=user_id
    )


def create_missing(tenant_id: UUID, parent_id: UUID, user_id: UUID) -> list[UUID]:
    """«Crear la parte 6» / «Crear las que faltan»: every part of the plan not created
    yet, all or nothing (`PartsRequests.request_parts`, m-24921081). 1 vista previa
    each; a refusal reaches the caller typed."""
    from qualify_api.creative.part_request import PartsRequests  # noqa: PLC0415

    return PartsRequests(production_content_service()).request_parts(
        tenant_id=tenant_id, parent_id=parent_id, user_id=user_id
    )


def change_part(
    tenant_id: UUID,
    parent_id: UUID,
    part_index: int,
    description: str,
    user_id: UUID,
    photo_keys: Sequence[str] | None = None,
) -> UUID:
    """«Crear otra versión» of ONE part (VE-10b; m-24921083): `description` is the WHOLE
    description of the part as the owner left it in «¿Qué pasa en esta parte?» (filled
    in with what it had) — never a change written on top of it; empty keeps what it had.
    `photo_keys`: the photos chosen in «Fotos de tu producto» (None keeps them). The
    mode never changes (`PartChanges`). 1 vista previa."""
    text = description.strip()
    photos = None if photo_keys is None else tuple(dict.fromkeys(k for k in photo_keys if k))
    return PartsService(production_content_service()).regenerate_part(
        tenant_id=tenant_id,
        parent_id=parent_id,
        part_index=part_index,
        changes=PartChanges(description=text or None, photo_keys=photos),
        user_id=user_id,
    )


__all__ = [
    "Approval",
    "CardRead",
    "approve",
    "card_from",
    "change_part",
    "read_card",
    "recreate_expired",
    "rejoin",
]
