"""The seam between the creative screens and the Brand Content Engine backend.

Same split as `connections_provider.py`:

- **Reads this module owns** go straight through `tenant_session(tenant_id)` — the one
  sanctioned door — so RLS scopes every row to the tenant even where the query carries
  no `WHERE tenant_id`. That covers the brand lookup, the proposed-voice listing (the
  services expose no "latest proposed" read), the per-draft usage-cost sum and the
  brief-topic join for the drafts list.
- **Writes delegate to the real services in-process**: `BrandKitService`,
  `VoiceProfileService` and the composed `ContentService`
  (`production_content_service`) — plain Python calls, exception types intact. The UI
  never drives the FSM itself.

Identity is always explicit (`tenant_id`, `user_id` arguments, never ambient), and the
acting user is the same dev crutch the connections screen uses
(`connections_provider.acting_user_id`) until real per-user sessions exist.

Every function here is a blocking DB (and possibly network) call — callers on the event
loop must run them off-thread.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError
from qualify_api.creative import models as orm
from qualify_api.creative.brand_service import BrandKitService
from qualify_api.creative.composition import production_content_service
from qualify_api.creative.readiness import readiness
from qualify_api.creative.service import DraftDetail
from qualify_api.creative.voice_service import VoiceProfileService
from qualify_api.tenancy.models import Brand
from qualify_creative.enums import (
    BriefIntent,
    BriefObjective,
    ContentType,
    ImageRoute,
    VoiceProfileStatus,
)
from qualify_creative.schemas import (
    BrandKit,
    BriefConstraints,
    ContentBrief,
    CopyPayload,
    ImagePolicy,
    ToneAxes,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select

from .connections_provider import acting_user_id
from .creative_vm import (
    CopyVariantVM,
    DraftSummaryVM,
    DraftVM,
    KitFormVM,
    ReadinessVM,
    RouteOptionVM,
    VoiceProposalVM,
    build_draft_summary_vm,
    build_draft_vm,
    build_readiness_vm,
    build_route_options,
    build_variant_vm,
    build_voice_proposal_vm,
)

__all__ = [
    "acting_user_id",
    "approve_draft",
    "approve_voice",
    "brand_readiness",
    "default_brand_id",
    "draft_detail",
    "edit_variant",
    "list_drafts",
    "load_kit_form",
    "load_voice_screen",
    "propose_voice",
    "reject_draft",
    "route_options_for",
    "save_kit",
    "submit_brief",
]


def _format_dt(value: datetime | None) -> str:
    """Pre-format server-side — the frontend never receives a raw datetime var."""
    if value is None:
        return ""
    return value.strftime("%d %b %Y, %H:%M")


# ---------------------------------------------------------------------------
# Brand resolution (D14 / §6: 1 login = 1 tenant = 1 negocio → one brand, no picker)


def default_brand_id(tenant_id: UUID) -> UUID | None:
    """The tenant's brand — the eldest row, deterministic. One brand per tenant is the
    signed model; if a second row ever appears the eldest is still the business the
    tenant was provisioned with, not an arbitrary one."""
    with tenant_session(tenant_id) as session:
        return session.scalar(select(Brand.id).order_by(Brand.created_at))


# ---------------------------------------------------------------------------
# Readiness + brand kit


def brand_readiness(tenant_id: UUID, brand_id: UUID) -> ReadinessVM:
    verdict = readiness(tenant_id=tenant_id, brand_id=brand_id)
    return build_readiness_vm(
        has_kit=verdict.has_kit,
        kit_completeness=verdict.kit_completeness,
        has_active_voice=verdict.has_active_voice,
        can_distill=verdict.can_distill,
        can_generate=verdict.can_generate,
        missing=verdict.missing,
    )


def _split_lines(text: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in text.splitlines() if line.strip())


def _split_commas(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(",") if part.strip())


def load_kit_form(tenant_id: UUID, brand_id: UUID) -> KitFormVM | None:
    """The stored kit flattened into form values; None when the brand has none yet."""
    kit = BrandKitService().get_kit(tenant_id=tenant_id, brand_id=brand_id)
    if kit is None:
        return None
    return KitFormVM(
        positioning=kit.positioning,
        audience=kit.audience,
        regional_variant=kit.regional_variant,
        tone_formal_casual=kit.tone_axes.formal_casual,
        tone_sober_enthusiastic=kit.tone_axes.sober_enthusiastic,
        tone_technical_plain=kit.tone_axes.technical_plain,
        tone_brief_elaborate=kit.tone_axes.brief_elaborate,
        do_examples="\n".join(kit.do_examples),
        dont_examples="\n".join(kit.dont_examples),
        banned_words="\n".join(kit.banned_words),
        forbidden_claims="\n".join(kit.forbidden_claims),
        cta_patterns="\n".join(kit.cta_patterns),
        palette_rgb=", ".join(kit.palette_rgb),
        has_logo=kit.logo_asset_key is not None,
        has_template=kit.template_asset_key is not None,
    )


def save_kit(tenant_id: UUID, brand_id: UUID, user_id: UUID, form: KitFormVM) -> None:
    """Parse the form back into the pydantic kit and upsert it through the service.

    The image policy, logo/template/reference keys are preserved from the stored kit —
    this form does not edit them, and an upsert must not erase what it does not model.
    Raises pydantic `ValidationError` when the form values do not make a legal kit.
    """
    service = BrandKitService()
    current = service.get_kit(tenant_id=tenant_id, brand_id=brand_id)
    data: dict[str, object] = {
        "brand_id": brand_id,
        "positioning": form.positioning.strip(),
        "audience": form.audience.strip(),
        "regional_variant": form.regional_variant,
        "tone_axes": ToneAxes(
            formal_casual=form.tone_formal_casual,
            sober_enthusiastic=form.tone_sober_enthusiastic,
            technical_plain=form.tone_technical_plain,
            brief_elaborate=form.tone_brief_elaborate,
        ),
        "do_examples": _split_lines(form.do_examples),
        "dont_examples": _split_lines(form.dont_examples),
        "banned_words": _split_lines(form.banned_words),
        "forbidden_claims": _split_lines(form.forbidden_claims),
        "cta_patterns": _split_lines(form.cta_patterns),
        "palette_rgb": _split_commas(form.palette_rgb),
    }
    if current is not None:
        # Fields this form does not edit keep their stored values.
        data.update(
            language=current.language,
            emoji_policy=current.emoji_policy,
            hashtag_policy=current.hashtag_policy,
            length_targets=current.length_targets,
            logo_asset_key=current.logo_asset_key,
            template_asset_key=current.template_asset_key,
            reference_image_keys=current.reference_image_keys,
            image_policy=current.image_policy,
        )
    kit = BrandKit.model_validate(data)
    service.upsert_kit(tenant_id=tenant_id, brand_id=brand_id, kit=kit, user_id=user_id)


# ---------------------------------------------------------------------------
# Voice (HITL #0)


def _proposal_vm(row: orm.BrandVoiceProfile, kit_axes: dict[str, int] | None) -> VoiceProposalVM:
    profile: dict = dict(row.profile or {})
    sources_raw = row.sources or []
    if isinstance(sources_raw, dict):
        sources_raw = sources_raw.get("sources", [])
    return build_voice_proposal_vm(
        version=row.version,
        status=row.status,
        tone_axes=profile.get("tone_axes", {}),
        kit_tone_axes=kit_axes,
        lexicon=profile.get("lexicon", ()),
        avoid_lexicon=profile.get("avoid_lexicon", ()),
        signature_moves=profile.get("signature_moves", ()),
        sources=[s for s in sources_raw if isinstance(s, dict)],
    )


def load_voice_screen(
    tenant_id: UUID, brand_id: UUID
) -> tuple[VoiceProposalVM | None, VoiceProposalVM | None]:
    """(latest PROPOSED profile, current ACTIVE profile) for the HITL #0 screen.

    Read directly (RLS-scoped): the services expose `active_profile` but no "latest
    proposed" — and the screen needs both side by side. The kit's tone axes ride along
    as the "del kit" comparison column.
    """
    kit = BrandKitService().get_kit(tenant_id=tenant_id, brand_id=brand_id)
    kit_axes = kit.tone_axes.model_dump() if kit is not None else None
    with tenant_session(tenant_id) as session:
        proposed = session.scalar(
            select(orm.BrandVoiceProfile)
            .where(
                orm.BrandVoiceProfile.brand_id == brand_id,
                orm.BrandVoiceProfile.status == VoiceProfileStatus.PROPOSED.value,
            )
            .order_by(orm.BrandVoiceProfile.version.desc())
        )
        active = session.scalar(
            select(orm.BrandVoiceProfile).where(
                orm.BrandVoiceProfile.brand_id == brand_id,
                orm.BrandVoiceProfile.status == VoiceProfileStatus.ACTIVE.value,
            )
        )
        return (
            _proposal_vm(proposed, kit_axes) if proposed is not None else None,
            _proposal_vm(active, kit_axes) if active is not None else None,
        )


def propose_voice(tenant_id: UUID, brand_id: UUID, user_id: UUID) -> int:
    """S1 distillation: propose the next voice profile from the kit; returns the new
    version. Raises `UnknownBrandKit` when there is no kit to propose from."""
    return VoiceProfileService().propose_from_kit(
        tenant_id=tenant_id, brand_id=brand_id, user_id=user_id
    )


def approve_voice(tenant_id: UUID, brand_id: UUID, version: int, user_id: UUID) -> None:
    """HITL #0 approval — promotes PROPOSED to ACTIVE inside the service's single
    transaction. Raises `UnknownVersion` / `NotProposed` on a stale screen."""
    VoiceProfileService().approve(
        tenant_id=tenant_id, brand_id=brand_id, version=version, user_id=user_id
    )


# ---------------------------------------------------------------------------
# The brief (/create)


def route_options_for(
    tenant_id: UUID, brand_id: UUID, content_type: str
) -> tuple[RouteOptionVM, ...]:
    """The image accordion for this brand and content type. Falls back to the default
    (conservative) `ImagePolicy` when the brand has no kit yet — the readiness gate
    keeps /create closed in that case anyway."""
    kit = BrandKitService().get_kit(tenant_id=tenant_id, brand_id=brand_id)
    policy = kit.image_policy if kit is not None else ImagePolicy()
    return build_route_options(policy=policy, content_type=ContentType(content_type))


def submit_brief(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID,
    *,
    objective: str,
    content_type: str,
    topic: str,
    product_ref: str,
    intent: str,
    image_route: str,
    source_media_key: str,
    must_mention: str,
    must_avoid: str,
    variants_requested: int = 3,
) -> UUID:
    """Build the frozen `ContentBrief` and create the draft through the composed
    service. Returns the new draft id; generation runs out of band (§7.4).

    Raises `ValidationError` (an inexecutable brief, e.g. an upload route without a
    photo), `BrandNotReady` and `RouteBlockedByPolicy` — the state translates each.
    """
    brief = ContentBrief(
        brand_id=brand_id,
        objective=BriefObjective(objective),
        content_type=ContentType(content_type),
        topic=topic.strip(),
        product_ref=product_ref.strip() or None,
        intent=BriefIntent(intent),
        image_route=ImageRoute(image_route),
        source_media_key=source_media_key or None,
        constraints=BriefConstraints(
            must_mention=_split_commas(must_mention),
            must_avoid=_split_commas(must_avoid),
        ),
        variants_requested=variants_requested,
    )
    return production_content_service().create_draft(
        tenant_id=tenant_id, brand_id=brand_id, brief=brief, user_id=user_id
    )


# ---------------------------------------------------------------------------
# Drafts (list + detail)


def list_drafts(tenant_id: UUID, brand_id: UUID) -> tuple[DraftSummaryVM, ...]:
    """The brand's drafts, newest first, THROUGH the service (its listing runs the
    reaper first — §7.4 — so an orphaned draft shows as failed/timeout, never as an
    eternal spinner). Topics come from one RLS-scoped read over the briefs."""
    records = production_content_service().list_drafts(tenant_id=tenant_id, brand_id=brand_id)
    topics: dict[UUID, str] = {}
    brief_ids = [record.brief_id for record in records]
    if brief_ids:
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(orm.ContentBrief.id, orm.ContentBrief.topic).where(
                    orm.ContentBrief.id.in_(brief_ids)
                )
            ).all()
            topics = {row[0]: row[1] for row in rows}
    return tuple(
        build_draft_summary_vm(
            draft_id=str(record.id),
            topic=topics.get(record.brief_id, ""),
            status=record.status,
            created_label=_format_dt(record.created_at),
            failure_reason=record.failure_reason,
        )
        for record in records
    )


def _draft_costs(tenant_id: UUID, draft_id: UUID) -> tuple[Decimal | None, tuple[str, ...]]:
    """(total cost, distinct model ids) from the draft's usage events — cost provenance
    over facts (§6.5: the cost is shown always)."""
    with tenant_session(tenant_id) as session:
        total = session.scalar(
            select(func.sum(orm.CreativeUsageEvent.cost_usd)).where(
                orm.CreativeUsageEvent.draft_id == draft_id
            )
        )
        models = session.scalars(
            select(orm.CreativeUsageEvent.model_id)
            .where(orm.CreativeUsageEvent.draft_id == draft_id)
            .distinct()
            .order_by(orm.CreativeUsageEvent.model_id)
        ).all()
        return (Decimal(total) if total is not None else None, tuple(models))


def _detail_to_vm(tenant_id: UUID, detail: DraftDetail) -> DraftVM:
    variants: list[CopyVariantVM] = [
        build_variant_vm(
            variant_id=str(v.id),
            ordinal=v.ordinal,
            copy=v.copy,
            edited_copy=v.edited_copy,
            fidelity=v.fidelity,
        )
        for v in detail.variants
    ]
    total, model_ids = _draft_costs(tenant_id, detail.id)
    return build_draft_vm(
        draft_id=str(detail.id),
        status=detail.status,
        failure_reason=detail.failure_reason,
        variants=variants,
        image_url=detail.image.media_url if detail.image is not None else None,
        total_cost_usd=total,
        voice_profile_version=detail.voice_profile_version,
        model_ids=model_ids,
        requires_ai_disclosure=detail.requires_ai_disclosure,
        created_label=_format_dt(detail.created_at),
    )


def draft_detail(tenant_id: UUID, draft_id: UUID) -> DraftVM | None:
    """One draft with variants, image and cost line; None when missing or not visible
    to this tenant (RLS makes the two indistinguishable, on purpose)."""
    detail = production_content_service().get_draft(tenant_id=tenant_id, draft_id=draft_id)
    if detail is None:
        return None
    return _detail_to_vm(tenant_id, detail)


# ---------------------------------------------------------------------------
# HITL #2


def edit_variant(
    tenant_id: UUID,
    variant_id: UUID,
    user_id: UUID,
    *,
    hook: str,
    caption: str,
    hashtags: str,
    cta: str,
) -> tuple[str, ...]:
    """Re-run layer 1 over the operator's edit through the service; returns the hard
    failures as display strings ("regla: detalle"), empty when the edit was stored.

    A malformed edit (hook over 60 chars, etc.) comes back as a blocking message too —
    pydantic rejecting the payload and layer 1 rejecting a claim both mean "the approve
    button stays blocked WITH the reason", per §6.5.
    """
    try:
        payload = CopyPayload(
            hook=hook.strip(),
            caption=caption,
            hashtags=tuple(tag.lstrip("#") for tag in hashtags.split() if tag.strip("#")),
            cta=cta.strip(),
        )
    except ValidationError as exc:
        return tuple(
            f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
    failures = production_content_service().edit_variant(
        tenant_id=tenant_id, variant_id=variant_id, copy=payload, user_id=user_id
    )
    return tuple(f"{f.rule}: {f.detail}" for f in failures)


def approve_draft(tenant_id: UUID, draft_id: UUID, variant_id: UUID, user_id: UUID) -> DraftVM:
    """HITL #2 approval through the FSM's guarded edge (a variant must be picked)."""
    detail = production_content_service().approve(
        tenant_id=tenant_id, draft_id=draft_id, variant_id=variant_id, user_id=user_id
    )
    return _detail_to_vm(tenant_id, detail)


def reject_draft(
    tenant_id: UUID, draft_id: UUID, user_id: UUID, *, reason: str, regenerate: bool
) -> DraftVM:
    """Reject (optionally re-entering DRAFTING for another generation round)."""
    detail = production_content_service().reject(
        tenant_id=tenant_id,
        draft_id=draft_id,
        reason=reason,
        user_id=user_id,
        regenerate=regenerate,
    )
    return _detail_to_vm(tenant_id, detail)
