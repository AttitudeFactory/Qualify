"""HTTP routes for the Brand Content Engine (design §5, D3) — three routes, each with a
reason to be HTTP rather than an in-process import (the repo's standing posture in
`http/__init__.py`):

- `GET /drafts/{id}/image` — the preview: a browser `<img>` has to load the piece before
  the operator approves/publishes, so a URL must exist. It answers 302 to the provider's
  `media_url` (MVP per §5.1 — nothing lives in R2 yet), and **410 Gone when
  `media_expires_at` has passed**: redirecting a browser to a URL known dead would render
  a broken image where the design demands the words "media expired, regenerate".
- `GET /drafts/{id}` — the second door of the read seam (§4.5), for the day the Ads
  consumer is external to the process. Artifacts only: `read.approved_creative` returns
  `None` for anything no human approved, and that `None` is a 404 here.
- `POST /drafts/{id}/generate` — the operational retry (and the worker hook when Celery
  lands). Idempotent BY STATE, not by guard: it re-dispatches `run_generation`, whose
  first act is to no-op on any draft past `DRAFTING` — so a double-POST accepts twice and
  generates once. See `_TERMINAL_NO_REENTRY` for the one deliberate 409.

**Identity provenance (C1).** Every route takes the tenant from the authenticated
`Principal`, never from the path or body. Every miss — draft absent, draft of another
tenant (RLS makes the two indistinguishable), draft without the thing asked for — is the
SAME 404: a 403 would confirm the resource exists, which is exactly the bit an outsider
is fishing for (§5).

Dependencies are injected through FastAPI's `dependency_overrides` seam
(`connections_routes.get_connect_service` pattern): each `get_*` below raises unless the
app assembly wired it, so an unconfigured deployment fails loudly instead of silently
composing the real Anthropic router.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from qualify_creative.enums import FailureReason
from qualify_creative.schemas import CopyPayload
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative import models as orm
from qualify_api.creative.fsm import FAILED, PUBLISHED
from qualify_api.creative.read import ApprovedCreative
from qualify_api.creative.service import ContentService
from qualify_api.http.deps import Principal, current_principal

router = APIRouter(prefix="/api/creative", tags=["creative"])

#: The two FSM states with no path — through ANY sequence of triggers — back to
#: `drafting`. `FAILED` is settled evidence (recovery is a new draft, or the
#: reject-with-regenerate edge from `generated`, neither of which is this route) and
#: `PUBLISHED` is the terminal happy path. Everything else answers 202: either the draft
#: IS in `drafting` (the retry this route exists for) or `run_generation` will no-op on
#: it by state, which is what "idempotent operational retry" means.
_TERMINAL_NO_REENTRY: frozenset[str] = frozenset({FAILED, PUBLISHED})


# ---------------------------------------------------------------------------
# Dependency seams


def get_content_service() -> ContentService:
    """Overridden in tests and wired at app startup. Raising here keeps an unconfigured
    deployment from silently composing the real Anthropic router."""
    raise NotImplementedError("content service dependency is not configured")


@dataclass(frozen=True)
class DraftImage:
    """What the preview route needs and nothing more: where the image lives and until
    when the provider guarantees it (`None` = no expiry, e.g. fal with a null
    lifecycle)."""

    media_url: str
    media_expires_at: datetime | None


class DraftImageReader(Protocol):
    """`None` when the draft is invisible to this tenant or has no image — the route
    maps both to the same 404."""

    def __call__(self, *, tenant_id: UUID, draft_id: UUID) -> DraftImage | None: ...


def get_draft_image_reader() -> DraftImageReader:
    raise NotImplementedError("draft image reader dependency is not configured")


class ApprovedCreativeReader(Protocol):
    """The shape of `qualify_api.creative.read.approved_creative`, as a seam so the
    route tests run with zero DB."""

    def __call__(self, *, tenant_id: UUID, draft_id: UUID) -> ApprovedCreative | None: ...


def get_approved_creative_reader() -> ApprovedCreativeReader:
    raise NotImplementedError("approved creative reader dependency is not configured")


def read_draft_image(*, tenant_id: UUID, draft_id: UUID) -> DraftImage | None:
    """The production `DraftImageReader`.

    It lives HERE, not in the service/read layer, for two reasons worth writing down:
    no landed read model exposes `media_expires_at` (`ImageRecord` and
    `ApprovedCreative` deliberately carry only what their consumers use), and the
    preview must NOT gate on `approved_creative` — the operator previews a `GENERATED`
    draft at HITL #2, before any approval exists. Same first-image-by-`created_at`
    choice as `PostgresContentRepository.image_for`; RLS on `image_assets` is what makes
    another tenant's draft indistinguishable from a missing one.
    """
    with tenant_session(tenant_id) as session:
        row = session.scalars(
            select(orm.ImageAsset)
            .where(orm.ImageAsset.draft_id == draft_id)
            .order_by(orm.ImageAsset.created_at)
        ).first()
        if row is None:
            return None
        return DraftImage(media_url=row.media_url, media_expires_at=row.media_expires_at)


# ---------------------------------------------------------------------------
# Response models


class ApprovedCreativeResponse(BaseModel):
    """`read.ApprovedCreative` on the wire. Field-for-field on purpose: the artifact IS
    the contract (§4.5), and a slimmer HTTP shape would fork it."""

    draft_id: UUID
    brand_id: UUID
    copy: CopyPayload
    intent: str
    voice_profile_version: int | None
    approved_at: datetime | None
    requires_ai_disclosure: bool
    image_media_url: str | None
    image_object_key: str | None
    image_width: int | None
    image_height: int | None
    aspect_ratio: str | None
    provenance: dict[str, object]


class GenerateAcceptedResponse(BaseModel):
    """202 body: the draft and the status it was in when the retry was accepted —
    `drafting` means work was re-dispatched, anything else means the dispatch will
    settle as a state no-op."""

    draft_id: UUID
    status: str


# ---------------------------------------------------------------------------
# Routes


@router.get("/drafts/{draft_id}/image")
def draft_image(
    draft_id: UUID,
    principal: Principal = Depends(current_principal),
    reader: DraftImageReader = Depends(get_draft_image_reader),
) -> RedirectResponse:
    """302 to the provider's `media_url` — never the bytes (serving binaries through
    this process is waste, §5) and **never a URL known dead**: past
    `media_expires_at` the answer is 410 with the typed reason, because the mitigation
    for the §5.1 debt is the operator being TOLD the piece expired, not a broken
    `<img>`."""
    image = reader(tenant_id=principal.tenant_id, draft_id=draft_id)
    if image is None:
        raise HTTPException(status_code=404, detail="unknown draft or draft has no image")
    if image.media_expires_at is not None and image.media_expires_at < datetime.now(UTC):
        raise HTTPException(
            status_code=410,
            detail={
                "failure_reason": FailureReason.MEDIA_EXPIRED.value,
                "message": "the provider URL for this image has expired; "
                "regenerate the draft to produce a fresh one",
            },
        )
    return RedirectResponse(url=image.media_url, status_code=302)


@router.get("/drafts/{draft_id}", response_model=ApprovedCreativeResponse)
def read_draft(
    draft_id: UUID,
    principal: Principal = Depends(current_principal),
    reader: ApprovedCreativeReader = Depends(get_approved_creative_reader),
) -> ApprovedCreativeResponse:
    """`ApprovedCreative` or 404. One 404 for all three misses — absent, other tenant,
    not an artifact — because `approved_creative` already collapses them into `None`
    and distinguishing them here would leak draft existence."""
    artifact = reader(tenant_id=principal.tenant_id, draft_id=draft_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="unknown draft")
    return ApprovedCreativeResponse(
        draft_id=artifact.draft_id,
        brand_id=artifact.brand_id,
        copy=artifact.copy,
        intent=artifact.intent.value,
        voice_profile_version=artifact.voice_profile_version,
        approved_at=artifact.approved_at,
        requires_ai_disclosure=artifact.requires_ai_disclosure,
        image_media_url=artifact.image_media_url,
        image_object_key=artifact.image_object_key,
        image_width=artifact.image_width,
        image_height=artifact.image_height,
        aspect_ratio=artifact.aspect_ratio,
        provenance=dict(artifact.provenance),
    )


@router.post(
    "/drafts/{draft_id}/generate", response_model=GenerateAcceptedResponse, status_code=202
)
def generate_draft(
    draft_id: UUID,
    principal: Principal = Depends(current_principal),
    service: ContentService = Depends(get_content_service),
) -> GenerateAcceptedResponse:
    """202: the retry is accepted, not finished — generation runs out of band (§7.4)
    through the SAME dispatcher seam `create_draft` uses (`service.dispatcher` is the
    documented public seam; nothing outside a dispatcher may call `run_generation`).

    The documented choice on 409 vs 202: this route retries DRAFTING work, and
    `run_generation` is idempotent by state — it no-ops on any draft past `drafting`.
    So every re-enterable state answers 202 (dispatch is harmless), and 409 is reserved
    for `_TERMINAL_NO_REENTRY` (`failed`, `published`): a `failed` draft is NOT
    re-runnable through this route — the FSM has no `failed → drafting` edge at all,
    and accepting work the FSM forbids would be a 202 that lies. Recovery from
    `failed` is a new draft; re-entry from `rejected` is `ContentService.reject(...,
    regenerate=True)`, a human decision, not an operational retry.
    """
    detail = service.get_draft(tenant_id=principal.tenant_id, draft_id=draft_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="unknown draft")
    if detail.status in _TERMINAL_NO_REENTRY:
        raise HTTPException(
            status_code=409,
            detail=f"draft is {detail.status}: no path back to generation exists; "
            "create a new draft instead",
        )
    if service.dispatcher is None:
        # Assembly bug, not caller error: a 202 with no dispatcher would accept work
        # that provably cannot run.
        raise HTTPException(status_code=503, detail="generation dispatcher is not configured")
    service.dispatcher.dispatch_generation(tenant_id=principal.tenant_id, draft_id=draft_id)
    return GenerateAcceptedResponse(draft_id=draft_id, status=detail.status)
