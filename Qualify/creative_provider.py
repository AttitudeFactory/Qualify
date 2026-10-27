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

import dataclasses
import logging
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from qualify_api.creative import models as orm
from qualify_api.creative.brand_service import BrandKitService
from qualify_api.creative.composition import media_root, production_content_service
from qualify_api.creative.context_ai import ContextInput, ContextProposal, enhance_context
from qualify_api.creative.creations import CreationsBalance
from qualify_api.creative.draft_mode import (
    FINAL_STALE_SECONDS,
    draft_expires_at,
    draft_rendering,
    draft_state,
    draft_summary,
)
from qualify_api.creative.media import LocalMediaStore, R2ReadingMediaStore
from qualify_api.creative.piece_export import (
    archive_name,
    build_archive,
    piece_copy,
    piece_files,
    piece_text,
    slug,
)
from qualify_api.creative.queue_visibility import cancel_queued, queue_status
from qualify_api.creative.readiness import readiness
from qualify_api.creative.retention import Retention, retention_of
from qualify_api.creative.service import DraftDetail
from qualify_api.creative.voice_service import VoiceProfileService
from qualify_api.stock.keys import is_stock_key
from qualify_api.tenancy.models import Brand
from qualify_creative.enums import (
    BriefIntent,
    BriefObjective,
    ContentFormat,
    ContentKind,
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
    MediaInputs,
    ToneAxes,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select

from .connections_provider import acting_user_id
from .creative_vm import (
    VIDEO_DRAFT,
    VIDEO_FAILED,
    CopyVariantVM,
    DraftSummaryVM,
    DraftVM,
    KitFormVM,
    MediaVM,
    PieceVersionVM,
    QueueVM,
    ReadinessVM,
    RecipeOptionVM,
    RouteOptionVM,
    VideoDraftVM,
    VoiceProposalVM,
    build_draft_summary_vm,
    build_draft_vm,
    build_media_vms,
    build_readiness_vm,
    build_recipe_options,
    build_route_options,
    build_variant_vm,
    build_voice_proposal_vm,
    draft_expiry_text,
    draft_kind_label,
    failure_label,
    purged_label,
    recreate_use_text,
    renewal_day_label,
    retention_notice,
    video_draft_vm,
)
from .piece_download import issue_download_path
from .r2_media import is_r2_key, issue_view_path

logger = logging.getLogger(__name__)

__all__ = [
    "acting_user_id",
    "approval_videos",
    "creations_balance",
    "recreate_draft",
    "recreate_note",
    "regeneration_creations",
    "approve_draft",
    "approve_voice",
    "brand_clone_voice",
    "brand_readiness",
    "catalog_products",
    "default_brand_id",
    "draft_detail",
    "edit_variant",
    "piece_archive",
    "list_drafts",
    "load_kit_form",
    "load_voice_screen",
    "propose_voice",
    "recipe_options",
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
        font_heading=kit.font_heading,
        font_body=kit.font_body,
        has_logo=kit.logo_asset_key is not None,
        has_template=kit.template_asset_key is not None,
    )


def save_kit(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID,
    form: KitFormVM,
    *,
    adopt_voice: bool = True,
) -> None:
    """Parse the form back into the pydantic kit and upsert it through the service.

    The image policy, logo/template/reference keys are preserved from the stored kit —
    this form does not edit them, and an upsert must not erase what it does not model.
    Raises pydantic `ValidationError` when the form values do not make a legal kit.
    `adopt_voice=False` is the wizard's save-as-you-go (§ 2026-10-02): a half-written
    kit is kept, but no voice version is minted per step — finishing adopts it.
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
        "font_heading": form.font_heading.strip(),
        "font_body": form.font_body.strip(),
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
    if not adopt_voice:
        return
    # § 2026-09-30 (founder: no approval step): saving the kit adopts the voice — the
    # next version goes ACTIVE when the kit's voice fields changed, so the generator is
    # never blocked on an approval and never reads a voice older than the kit.
    VoiceProfileService().adopt_from_kit(tenant_id=tenant_id, brand_id=brand_id, user_id=user_id)


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


def build_brief(
    brand_id: UUID,
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
    highlights: Sequence[Sequence[str]] = (),
    variants_requested: int = 3,
    kind: str = "static_flyer",
    media: Mapping[str, object] | None = None,
    content_format: str = "",
) -> ContentBrief:
    """The frozen `ContentBrief` of a form — shared by `submit_brief` and
    `preview_brief_prompt`, so the preview is the brief Generar sends.

    `kind` / `media` are the generator's content kind and its inputs (`ContentKind`,
    `MediaInputs`, § request 2026-09-25). The image route is derived from them rather
    than asked: the operator's own images are placed untouched (`FROM_UPLOAD`, keyed on
    the first of them) and a piece with none is `TEMPLATE_ONLY`. Raises
    `ValidationError` for an inexecutable brief.
    """
    content_kind = ContentKind(kind)
    inputs = MediaInputs.model_validate(dict(media or {}))
    # an «Inspiración» (stock) file is never the route's source: the licence guard keeps
    # stock out of `source_media_key` (a from-upload source is published as it is), and
    # stock is not the operator's own image — a piece with only stock has none
    own_images = [
        key
        for key in (*inputs.product_keys, inputs.background_key)
        if key and not is_stock_key(key)
    ]
    if content_kind is not ContentKind.STATIC_FLYER or image_route == "":
        image_route = ImageRoute.FROM_UPLOAD.value if own_images else ImageRoute.TEMPLATE_ONLY.value
        source_media_key = own_images[0] if own_images else ""
    return ContentBrief(
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
            highlights=tuple((str(name), str(fact)) for name, fact in highlights),
        ),
        variants_requested=variants_requested,
        kind=content_kind,
        media=inputs,
        # the format the operator picked, else the kind's default
        format=ContentFormat(content_format) if content_format else content_kind.default_format,
    )


def submit_brief(tenant_id: UUID, brand_id: UUID, user_id: UUID, **form: Any) -> UUID:
    """Build the brief (`build_brief`) and create the draft through the composed
    service. Returns the new draft id; generation runs out of band (§7.4).

    Raises `ValidationError` (an inexecutable brief, e.g. an upload route without a
    photo, or a kind missing its inputs), `BrandNotReady` and `RouteBlockedByPolicy` —
    the state translates each.
    """
    brief = build_brief(brand_id, **form)
    return production_content_service().create_draft(
        tenant_id=tenant_id, brand_id=brand_id, brief=brief, user_id=user_id
    )


def preview_brief_prompt(tenant_id: UUID, brand_id: UUID, **form: Any) -> bool:
    """Print to the console the copy prompt this form would send (§ request 2026-10-06),
    without creating a draft or calling a vendor. False when it could not render."""
    brief = build_brief(brand_id, **form)
    return production_content_service().preview_prompt(
        tenant_id=tenant_id, brand_id=brand_id, brief=brief
    )


def brand_character(tenant_id: UUID, brand_id: UUID) -> dict[str, str]:
    """The «Avatar animado»'s character, from the Brand Kit (§ request 2026-10-20: no
    picker any more): the brand's own drawn avatar when the kit has a ready one (an image
    Qualify made for the brand, so its rights are the brand's), else a mascot described
    from the kit — name, business, colours, tone. `{}` without a kit.

    `{source: "image", key, name}` or `{source: "ai", prompt, name}`."""
    from qualify_api.creative.brand_avatar import (
        AvatarStatus,
        describe_character,
        load_avatar_inputs,
        load_brand_avatar,
    )

    avatar = load_brand_avatar(tenant_id, brand_id)
    if avatar is not None and avatar.status is AvatarStatus.READY and avatar.object_key:
        return {"source": "image", "key": avatar.object_key, "name": "El avatar de tu marca"}
    inputs = load_avatar_inputs(tenant_id, brand_id)
    if inputs is None:
        return {}
    return {
        "source": "ai",
        "prompt": describe_character(inputs),
        "name": "La mascota de tu marca, creada con tu Brand Kit",
    }


def enhance_generator_context(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    text: str,
    piece: str,
    scene: bool,
    product: str,
    highlights: Sequence[Sequence[str]],
    must_mention: str,
    must_avoid: str,
) -> ContextProposal:
    """«Potenciar con IA» (§ request 2026-10-20): the context the operator wrote,
    rewritten with the brand's kit and the piece's «Datos clave» — no new facts
    (`qualify_api.creative.context_ai`). Nothing is created or stored."""
    kit = BrandKitService().get_kit(tenant_id=tenant_id, brand_id=brand_id)
    data = ContextInput(
        text=text,
        piece=piece,
        scene=scene,
        product=product,
        highlights=tuple((str(name), str(fact)) for name, fact in highlights),
        must_mention=must_mention,
        must_avoid=must_avoid,
    )
    return enhance_context(data, kit)


# ---------------------------------------------------------------------------
# The template kind (plan-mvp-plantillas-remotion.md): the catalog picker and the recipes


def catalog_products(tenant_id: UUID, brand_id: UUID) -> tuple[dict[str, str], ...]:
    """The brand's products for the generator's picker, as flat string rows (a Reflex var
    cannot carry the catalog's dataclasses): `{id, name, photo_key,
    photo_count, video_count}`. Read through the catalog's own door."""
    from .catalog_provider import list_products

    return tuple(
        {
            "id": product.product_id,
            "name": product.name,
            "photo_key": product.primary_photo_key,
            "photo_count": str(product.photo_count),
            "video_count": str(product.video_count),
            "counts_label": product.counts_label,
            "photo_keys": "\n".join(m.key for m in product.media if m.media_type == "image"),
            "video_keys": "\n".join(m.key for m in product.media if m.media_type == "video"),
        }
        for product in list_products(tenant_id, brand_id)
    )


def recipe_options(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    content_type: str,
    product_ref: str,
    product_keys: Sequence[str],
    source_media_key: str,
) -> tuple[RecipeOptionVM, ...]:
    """The three options of «¿Cómo la hacemos?» (MP-09/MP-10): the router's rules over
    what THIS Post has — the photos the operator uploaded for the piece plus the catalog
    product's own (deduplicated), the catalog's clips (or a video the operator staged),
    and the angle — against the templates published in the repo. `has_avatar` is False
    until the tenant's presenter is a stored fact, so the talking presenter (OmniHuman)
    is offered as the alternative it is, never as the suggestion."""
    from qualify_api.catalog.read import DbProductCatalog
    from qualify_creative.render import PostFacts, TemplateRegistry, suggest_recipes
    from qualify_creative.video import is_video_filename

    registry = TemplateRegistry.from_dir()
    products = DbProductCatalog().products_for(
        tenant_id=tenant_id, brand_id=brand_id, product_ref=product_ref or None
    )
    photo_keys = set(product_keys) | {key for p in products for key in p.photo_keys}
    video_keys = {key for p in products for key in p.video_keys}
    if source_media_key and is_video_filename(source_media_key):
        video_keys.add(source_media_key)
    try:
        angle = ContentType(content_type)
    except ValueError:
        angle = ContentType.PRODUCT
    facts = PostFacts(
        angle=angle,
        photo_count=len(photo_keys),
        video_count=len(video_keys),
        product_count=max(len(products), 1),
        has_avatar=False,
        niche=None,
    )
    return build_recipe_options(suggest_recipes(facts, registry))


#: The Brand Kit's files the generator can place in a piece: raster images only (a
#: Pillow composition and the image models take nothing else) — never the fonts.
_BRAND_MEDIA_TYPES = {
    "image/png": (".png",),
    "image/jpeg": (".jpg", ".jpeg"),
    "image/webp": (".webp",),
}


def _brand_media_type(content_type: str, key: str) -> str:
    """The image's MIME type, from the row or, for a row saved without one, the key."""
    if content_type in _BRAND_MEDIA_TYPES:
        return content_type
    lower = key.lower()
    return next((mime for mime, exts in _BRAND_MEDIA_TYPES.items() if lower.endswith(exts)), "")


def brand_media(tenant_id: UUID, brand_id: UUID) -> tuple[dict[str, str], ...]:
    """The images already saved in the Brand Kit — the logo, its versions and the
    brandboard's elements (§ request 2026-10-06: "usar los assets ya cargados en el
    brandkit como media") — as `{key, label, view}` rows for the generator's picker.
    `key` is the R2 key the media pipeline reads (`R2ReadingMediaStore`); `view` a
    short-lived `/r2media` path for the thumbnail ("" when none could be issued)."""
    from qualify_api.creative.brand_kit_store import EXTRA, FONT, LOGO, BrandKitStore

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for asset in BrandKitStore().list_assets(tenant_id=tenant_id, brand_id=brand_id):
        content_type = _brand_media_type(asset.content_type, asset.object_key)
        if asset.kind == FONT or not content_type or asset.object_key in seen:
            continue
        seen.add(asset.object_key)
        if asset.kind == LOGO:
            label = "Logo"
        elif asset.kind == EXTRA:
            label = asset.label.strip() or "Elemento"
        else:  # a logo version: its slot is the version's name
            label = (asset.label.strip() or asset.slot.replace("_", " ")).capitalize()
        try:
            view = issue_view_path(tenant_id, asset.object_key, "image", content_type)
        except Exception as exc:  # noqa: BLE001 — a thumbnail is not worth failing the step
            logger.warning("brand media view not issued: %s", type(exc).__name__)
            view = ""
        rows.append(
            {
                "key": asset.object_key,
                "label": label,
                "view": view,
                # a logo takes the brand mark's place; an element is used as its note says
                "kind": "element" if asset.kind == EXTRA else "logo",
                "usage": " ".join(asset.context.split()),
            }
        )
    return tuple(rows)


_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")


def _piece_label(title: str, media_type: str, created_at: object) -> str:
    """A piece by its title (§ request 2026-10-14: «el título del video, no lo del
    prompt») — its copy's hook — else by what it is and when it was made."""
    title = " ".join(title.split())
    if title:
        return title[:40] + "…" if len(title) > 40 else title
    what = "Video" if media_type == "video" else "Imagen"
    day = getattr(created_at, "day", None)
    month = getattr(created_at, "month", None)
    return f"{what} del {day} {_MONTHS[month - 1]}" if day and month else what


def brand_pieces(tenant_id: UUID, brand_id: UUID) -> tuple[dict[str, str], ...]:
    """The images and videos of the brand's own pieces, the most recent first — what a
    carousel's «De una pieza» slide picks from (§ request 2026-10-09). `view` is a
    short-lived `/r2media` path of the thumbnail (a video's poster frame), "" when the
    file is not in R2 or has no poster; `label` says which piece it came from."""
    from qualify_api.creative.pieces import DbPieceFiles

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for piece in DbPieceFiles().files(tenant_id=tenant_id, brand_id=brand_id):
        if piece.object_key in seen:
            continue
        seen.add(piece.object_key)
        thumb = piece.object_key if piece.media_type == "image" else piece.poster_key
        try:
            view = issue_view_path(tenant_id, thumb, "image") if thumb else ""
        except Exception as exc:  # noqa: BLE001 — a thumbnail is not worth failing the list
            logger.warning("piece view not issued: %s", type(exc).__name__)
            view = ""
        rows.append(
            {
                "key": piece.object_key,
                "media_type": piece.media_type,
                "label": _piece_label(piece.title, piece.media_type, piece.created_at),
                "view": view,
            }
        )
    return tuple(rows)


def template_blocker(
    tenant_id: UUID,
    brand_id: UUID,
    *,
    content_type: str,
    product_ref: str,
    product_keys: Sequence[str],
    source_media_key: str,
    content_format: str,
) -> str:
    """Why the template this Post would get cannot be made ("" when it can) — checked
    on «¿Todo listo?» since «¿Cómo la hacemos?», which used to say it, left the wizard
    (§ 2026-10-06): too few photos for the router's template, or no output of the
    chosen format. The same router `MediaProducer` runs, so Generar cannot disagree."""
    from qualify_api.creative.media import template_port
    from qualify_creative.render import TemplateRegistry

    options = recipe_options(
        tenant_id,
        brand_id,
        content_type=content_type,
        product_ref=product_ref,
        product_keys=product_keys,
        source_media_key=source_media_key,
    )
    remotion = next((o for o in options if o.key == "remotion"), None)
    if remotion is None or not remotion.template_id:
        return "ninguna plantilla publicada sirve a esta pieza"
    if not remotion.available:
        return remotion.reason
    manifest = TemplateRegistry.from_dir().get(remotion.template_id, remotion.template_version)
    if template_port(manifest, ContentFormat(content_format)) is None:
        return f"la plantilla «{manifest.name}» no tiene ese formato"
    return ""


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
    retention = _retention(tenant_id, detail.id)
    purged = retention is not None and retention.is_purged
    # m-24828907: a purged piece's keys point at nothing in R2 — no view tokens for them.
    media = (
        ()
        if purged
        else _with_r2_urls(
            tenant_id,
            build_media_vms(
                [
                    # R2-only media has no provider URL: its object key is what the screen
                    # resolves (`_with_r2_urls` mints the backend URL for it).
                    (
                        item.media_url or item.object_key or "",
                        item.media_type,
                        item.position,
                        item.params,
                    )
                    for item in detail.media
                ]
            ),
        )
    )
    vm = build_draft_vm(
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
        kind=detail.kind,
        media=media,
        failure_detail=detail.failure_detail,
        warnings=tuple(warning.detail for warning in detail.warnings),
        waiting_vendor=bool(getattr(detail, "waiting_vendor", False)),
    )
    active_id = str(getattr(detail, "active_version_id", None) or "")
    viewed_id = str(getattr(detail, "viewed_version_id", None) or active_id)
    preview = bool(getattr(detail, "is_version_preview", False))
    vm = dataclasses.replace(
        vm,
        versions=tuple(
            PieceVersionVM(
                version_id=str(version.id),
                label=f"Versi\u00f3n {version.revision}",
                created_label=_format_dt(version.created_at),
                available=version.status == "active",
                current=str(version.id) == active_id,
            )
            for version in getattr(detail, "versions", ())
        ),
        active_version_id=active_id,
        viewed_version_id=viewed_id,
        viewing_previous_version=preview,
        can_restore_version=bool(getattr(detail, "can_restore_version", False)) and not purged,
    )
    if preview:
        vm = dataclasses.replace(
            vm,
            can_approve=vm.can_approve and vm.can_restore_version,
            can_reject=False,
            can_regenerate=False,
            can_edit=False,
            download_path="",
            download_name="",
        )
    # m-24820142: the Seedance 2.5 draft videos' state (badge, final, retry)
    video_params = [item.params for item in detail.media]
    approved = detail.status == "approved"
    vm = dataclasses.replace(
        vm,
        video_draft=_with_expiry(
            tenant_id,
            video_draft_vm(
                # approved with a video still at its draft: its final was never ordered
                *draft_summary(video_params, approved=approved),
                still_rendering=draft_rendering(video_params),
                approved=approved,
            ),
            video_params,
            approved=approved,
        ),
    )
    if purged:
        assert retention is not None
        when = retention.purged_at.isoformat() if retention.purged_at else None
        return dataclasses.replace(vm, media_purged=True, purged_label=purged_label(when))
    if retention is not None:
        vm = dataclasses.replace(
            vm,
            retention_notice=retention_notice(
                retention.state.value,
                retention.deadline.isoformat() if retention.deadline else None,
                retention.days_left(datetime.now(UTC)),
            ),
        )
    if (
        detail.revision > 1
        and detail.status in {"drafting", "generated", "rejected"}
        and any(draft_state(item.params) for item in detail.media)
    ):
        from .final_review_provider import pending_version_note

        vm = dataclasses.replace(
            vm, other_version_pending=pending_version_note(tenant_id, detail.id)
        )
    return vm if preview else _with_download(tenant_id, detail, vm)


def _retention(tenant_id: UUID, draft_id: UUID) -> Retention | None:
    """The piece's retention verdict (m-24828907); None when it has no R2 files, or when
    it cannot be read — a warning is not worth failing the page."""
    try:
        with tenant_session(tenant_id) as session:
            return retention_of(session, tenant_id, [draft_id], datetime.now(UTC)).get(draft_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("piece retention unreadable: %s", type(exc).__name__)
        return None


def _with_download(tenant_id: UUID, detail: DraftDetail, vm: DraftVM) -> DraftVM:
    """«Descargar todo» (m-24828908): the piece's `.zip` path, minted only once there is
    something to download — never on every poll of a draft still generating. A token that
    cannot be minted (Redis down) only costs the button."""
    if vm.is_drafting or not (detail.variants or detail.media):
        return vm
    try:
        path = issue_download_path(tenant_id, detail.id)
    except Exception as exc:  # noqa: BLE001 — a download link is not worth failing the page
        logger.warning("piece download token not issued: %s", type(exc).__name__)
        return vm
    return dataclasses.replace(
        vm, download_path=path, download_name=archive_name(_brand_name(tenant_id), detail.title)
    )


def _brand_name(tenant_id: UUID) -> str:
    """The tenant's brand name, "" when it cannot be read (the archive is still named)."""
    try:
        with tenant_session(tenant_id) as session:
            return session.scalar(select(Brand.name).order_by(Brand.created_at)) or ""
    except Exception as exc:  # noqa: BLE001 — a file name is not worth failing the page
        logger.warning("brand name unreadable: %s", type(exc).__name__)
        return ""


def piece_archive(tenant_id: UUID, draft_id: UUID) -> tuple[str, bytes] | None:
    """The piece as a `.zip` — its files and `texto.txt`, never the prompt (`piece_export`).
    Read through RLS: a draft of another tenant is None. Blocking (R2 reads)."""
    detail = production_content_service().get_draft(tenant_id=tenant_id, draft_id=draft_id)
    if detail is None:
        return None
    retention = _retention(tenant_id, draft_id)
    if retention is not None and retention.is_purged:
        return None  # m-24828907: nothing left to download (a link minted before the purge)
    store = R2ReadingMediaStore(LocalMediaStore(media_root()))
    kind_label = draft_kind_label(
        detail.kind, has_video=any(item.media_type == "video" for item in detail.media)
    )
    # inside the archive the files are named by what they are («clip-1.mp4»): a POST's
    # title is often its whole context, too long for a file name — that goes on the .zip
    files, missing = piece_files(detail, store.read, stem=slug(kind_label) or "pieza")
    text = piece_text(title=detail.title, kind_label=kind_label, copy=piece_copy(detail))
    return archive_name(_brand_name(tenant_id), detail.title), build_archive(files, text, missing)


def _with_r2_urls(tenant_id: UUID, media: tuple[MediaVM, ...]) -> tuple[MediaVM, ...]:
    """Media that lives only in R2 gets a short-lived backend URL (`r2_media`); the rest
    keeps resolving through the local upload store. A token that cannot be minted (e.g.
    Redis down) only costs the preview — the draft itself still loads."""

    def view(key: str, media_type: str) -> str:
        if not is_r2_key(key):
            return ""
        try:
            return issue_view_path(tenant_id, key, media_type)
        except Exception as exc:  # noqa: BLE001 — a preview is not worth failing the page
            logger.warning("r2 media token not issued: %s", type(exc).__name__)
            return ""

    return tuple(
        dataclasses.replace(
            item,
            url=view(item.key, item.media_type),
            poster_url=view(item.poster_key, "image") if item.poster_key else "",
        )
        for item in media
    )


def preview_draft_version(tenant_id: UUID, draft_id: UUID, version_id: UUID) -> DraftVM:
    detail = production_content_service().preview_version(
        tenant_id=tenant_id, draft_id=draft_id, version_id=version_id
    )
    return _detail_to_vm(tenant_id, detail)


def restore_draft_version(tenant_id: UUID, draft_id: UUID, version_id: UUID) -> DraftVM:
    detail = production_content_service().restore_version(
        tenant_id=tenant_id, draft_id=draft_id, version_id=version_id
    )
    return _detail_to_vm(tenant_id, detail)


def draft_detail(tenant_id: UUID, draft_id: UUID) -> DraftVM | None:
    """One draft with variants, image and cost line; None when missing or not visible
    to this tenant (RLS makes the two indistinguishable, on purpose)."""
    detail = production_content_service().get_draft(tenant_id=tenant_id, draft_id=draft_id)
    if detail is None:
        return None
    vm = _detail_to_vm(tenant_id, detail)
    queue = draft_queue(tenant_id, draft_id)
    if queue.cancelled:
        vm = dataclasses.replace(
            vm, video_draft=dataclasses.replace(vm.video_draft, can_retry=False)
        )
    return dataclasses.replace(vm, queue=queue)


def draft_queue(tenant_id: UUID, draft_id: UUID) -> QueueVM:
    from .creative_vm import queue_vm  # noqa: PLC0415

    if os.environ.get("QUALIFY_CREATIVE_DISPATCHER", "inline").strip().lower() != "queue":
        return queue_vm()
    status = queue_status(tenant_id=tenant_id, draft_id=draft_id)
    return queue_vm(
        queued=status.queued,
        can_cancel=status.can_cancel,
        cancelled=status.cancelled,
        estimated_minutes=status.estimated_minutes,
    )


def cancel_draft_queue(tenant_id: UUID, draft_id: UUID) -> None:
    cancel_queued(tenant_id=tenant_id, draft_id=draft_id)


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
    script: str | None = None,
) -> tuple[str, ...]:
    """Re-run layer 1 over the operator's edit through the service; returns the hard
    failures as display strings ("regla: detalle"), empty when the edit was stored.

    A malformed edit (hook over 60 chars, etc.) comes back as a blocking message too —
    pydantic rejecting the payload and layer 1 rejecting a claim both mean "the approve
    button stays blocked WITH the reason", per §6.5.
    """
    service = production_content_service()
    # Merged over the stored copy: what the editor does not show (the ads slots, the
    # script's shot list) survives the edit.
    base = service.variant_copy(tenant_id=tenant_id, variant_id=variant_id)
    changes: dict[str, object] = {
        "hook": hook.strip(),
        "caption": caption,
        "hashtags": tuple(tag.lstrip("#") for tag in hashtags.split() if tag.strip("#")),
        "cta": cta.strip(),
    }
    if script is not None:
        changes["script"] = script.strip()
    try:
        payload = CopyPayload.model_validate({**base.model_dump(), **changes})
    except ValidationError as exc:
        return tuple(_field_error(err) for err in exc.errors())
    failures = service.edit_variant(
        tenant_id=tenant_id, variant_id=variant_id, copy=payload, user_id=user_id
    )
    return tuple(failure_label(f.rule, f.detail) for f in failures)


_FIELD_LABELS = {
    "hook": "El gancho",
    "caption": "El caption",
    "cta": "El CTA",
    "script": "El guion",
}


def _field_error(err: Mapping[str, object]) -> str:
    """A malformed edit in the operator's words: "El gancho admite como máximo 60
    caracteres." rather than pydantic's "hook: String should have at most 60 characters"."""
    loc = err.get("loc") or ()
    field = str(loc[0]) if loc else ""
    label = _FIELD_LABELS.get(field, f"El campo «{field}»")
    ctx = err.get("ctx") or {}
    kind = str(err.get("type", ""))
    if kind == "string_too_long" and isinstance(ctx, Mapping):
        return f"{label} admite como máximo {ctx.get('max_length')} caracteres."
    if kind == "string_too_short" and isinstance(ctx, Mapping):
        return f"{label} necesita al menos {ctx.get('min_length')} caracteres."
    return f"{label} no es válido: {err.get('msg', '')}"


def approve_draft(tenant_id: UUID, draft_id: UUID, variant_id: UUID, user_id: UUID) -> DraftVM:
    """HITL #2 approval through the FSM's guarded edge (a variant must be picked)."""
    detail = production_content_service().approve(
        tenant_id=tenant_id, draft_id=draft_id, variant_id=variant_id, user_id=user_id
    )
    return _detail_to_vm(tenant_id, detail)


def approve_draft_version(
    tenant_id: UUID, draft_id: UUID, variant_id: UUID, user_id: UUID, version_id: UUID
) -> DraftVM:
    """Activate and approve exactly the selected historical variant, atomically."""
    detail = production_content_service().approve_version(
        tenant_id=tenant_id,
        draft_id=draft_id,
        version_id=version_id,
        variant_id=variant_id,
        user_id=user_id,
    )
    return _detail_to_vm(tenant_id, detail)


def creations_balance(
    tenant_id: UUID, brand_id: UUID
) -> tuple[int, int, str, int, int, int, int, tuple[int, str, int, str, int, str]] | None:
    """«Creaciones del mes» (CREAR-5): (left, quota, renews, videos_left, video_quota,
    previews_left, preview_quota, extras) — `renews` the day the quota renews as the owner
    reads it («1 de noviembre», "" when unknown); the videos and vistas previas are the
    month's (founder, 2026-10-24); `extras` what the live 90-day packs still bring and
    when the first of them expires, per counter (m-24852129: (creations, «22 de enero»,
    videos, …, vistas previas, …)) — or None when no quota is wired: the screens then say
    nothing about creations."""
    balance = production_content_service().creations_balance(tenant_id=tenant_id, brand_id=brand_id)
    if balance is None:
        return None
    return (
        balance.left,
        balance.quota,
        renewal_day_label(balance.renews_on),
        balance.videos_left,
        balance.video_quota,
        balance.previews_left,
        balance.preview_quota,
        balance_extras(balance),
    )


def balance_extras(balance: CreationsBalance) -> tuple[int, str, int, str, int, str]:
    """The extras of a balance as the owner reads them (expiry «22 de enero»)."""
    return (
        balance.extra_left,
        renewal_day_label(balance.extra_expires_on),
        balance.extra_videos_left,
        renewal_day_label(balance.extra_videos_expires_on),
        balance.extra_previews_left,
        renewal_day_label(balance.extra_previews_expires_on),
    )


def approval_videos(
    tenant_id: UUID, draft_id: UUID, version_id: UUID | None = None
) -> tuple[int, int, int, str] | None:
    """What approving a piece uses of the month's videos (founder, 2026-10-24):
    (videos, videos_left, video_quota, renews), or None when it makes no video, is not
    waiting for approval, or no quota is wired."""
    quote = production_content_service().approval_videos(
        tenant_id=tenant_id,
        draft_id=draft_id,
        **({"version_id": version_id} if version_id is not None else {}),
    )
    if quote is None:
        return None
    videos, balance = quote
    return videos, balance.videos_left, balance.video_quota, renewal_day_label(balance.renews_on)


def recreate_note(tenant_id: UUID, brand_id: UUID, draft_id: UUID) -> str:
    """The line under «Crearla otra vez» (founder, 2026-10-24): «Usa 1 de tus vistas
    previas. Te quedan {p}.» — "" without a quota or a price."""
    service = production_content_service()
    price = service.recreate_price(tenant_id=tenant_id, draft_id=draft_id)
    balance = service.creations_balance(tenant_id=tenant_id, brand_id=brand_id)
    if price is None or balance is None:
        return ""
    return recreate_use_text(
        price.weight, price.videos, balance.previews_left, balance.preview_quota
    )


def recreate_draft(tenant_id: UUID, draft_id: UUID, user_id: UUID) -> str:
    """«Crearla otra vez»: a new piece from an expired one's request (one vista previa
    per video). Raises `NotEnoughCreations` when the month cannot pay it."""
    new_id = production_content_service().recreate(
        tenant_id=tenant_id, draft_id=draft_id, user_id=user_id
    )
    return str(new_id)


def regeneration_creations(
    tenant_id: UUID, brand_id: UUID, draft_id: UUID
) -> tuple[int, int, int, str, int, int, int] | None:
    """What «Pedir otra versión» of a draft uses: (weight, left, quota, renews, previews,
    previews_left, preview_quota) — a video's new version is a new vista previa per
    video, never a video (those are counted at approval) — or None."""
    service = production_content_service()
    price = service.regeneration_price(tenant_id=tenant_id, draft_id=draft_id)
    balance = service.creations_balance(tenant_id=tenant_id, brand_id=brand_id)
    if price is None or balance is None:
        return None
    return (
        price.weight,
        balance.left,
        balance.quota,
        renewal_day_label(balance.renews_on),
        price.videos if balance.preview_quota > 0 else 0,
        balance.previews_left,
        balance.preview_quota,
    )


def retry_final(tenant_id: UUID, draft_id: UUID) -> DraftVM:
    """Order again the 1080p finals that failed (m-24820142)."""
    detail = production_content_service().retry_final(tenant_id=tenant_id, draft_id=draft_id)
    return _detail_to_vm(tenant_id, detail)


#: How long the piece's page watches a 1080p final (m-24820142): until the final is in
#: place, fails, or — a dead process left it — turns retryable (`FINAL_STALE_SECONDS`
#: after its work last started, the one source of truth), plus a margin for the order
#: to be claimed; the last look then shows «Reintentar» without a reload.
FINAL_POLL_WINDOW_SECONDS = FINAL_STALE_SECONDS + 2 * 60


def final_video_state(tenant_id: UUID, draft_id: UUID) -> VideoDraftVM | None:
    """The piece's draft videos as the screen shows them — what the final poll reads
    every few seconds: the draft row and its draft videos only, never the whole piece
    (`ContentService.video_drafts_state`). None when the draft is gone."""
    state = production_content_service().video_drafts_state(tenant_id=tenant_id, draft_id=draft_id)
    if state is None:
        return None
    status, params = state
    approved = status == "approved"
    return _with_expiry(
        tenant_id,
        video_draft_vm(
            *draft_summary(list(params), approved=approved),
            still_rendering=draft_rendering(list(params)),
            approved=approved,
        ),
        list(params),
        approved=approved,
    )


def _with_expiry(
    tenant_id: UUID,
    video: VideoDraftVM,
    params: list[Mapping[str, object] | None],
    *,
    approved: bool,
) -> VideoDraftVM:
    """A vista previa still waiting for approval says until when (founder, 2026-10-24):
    «Apruébala antes del jueves 30 de octubre para tener el video final.», in the
    business's zone. Nothing once approved, expired, or without a date."""
    if video.state == "rendering" and any(
        (draft_state(param) or {}).get("final_nightly") for param in params
    ):
        from .final_review_vm import FINAL_NIGHT_RUNNING_NOTE, FINAL_SCHEDULED_NOTE
        from .inbox_provider import tenant_zone

        local = datetime.now(UTC).astimezone(tenant_zone(tenant_id))
        return dataclasses.replace(
            video,
            badge="Video final mañana",
            tone="neutral",
            note=(FINAL_NIGHT_RUNNING_NOTE if local.hour < 6 else FINAL_SCHEDULED_NOTE),
        )
    if approved or video.state not in (VIDEO_DRAFT, VIDEO_FAILED):
        return video
    ends = draft_expires_at(params)
    if ends is None:
        return video
    from .inbox_provider import tenant_zone  # noqa: PLC0415 — keeps the import graph flat

    when = datetime.fromtimestamp(ends, tz=UTC).astimezone(tenant_zone(tenant_id))
    return dataclasses.replace(video, expiry_note=draft_expiry_text(when), expires_at=ends)


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


# ---------------------------------------------------------------------------
# The avatar kinds' video engine (/create, § request 2026-10-07; ByteDance 2026-10-16)

#: Which vendor renders the two avatar kinds. HeyGen is retired (2026-10-16): the
#: talking presenter is OmniHuman (photo + Seed Speech voice, lips in sync), the scene
#: video Seedance. Read per call, like the keys: an env change, nothing else.
VIDEO_ENGINE_ENV = "QUALIFY_VIDEO_ENGINE"
VIDEO_ENGINES = ("omnihuman", "seedance")
#: The two keys the talking presenter needs (Seed Speech reads, OmniHuman animates).
PRESENTER_KEY_ENVS = ("QUALIFY_BYTEPLUS_SPEECH_API_KEY", "QUALIFY_BYTEPLUS_CV_API_KEY")
GENDERS = ("female", "male")


def presenter_keys_ready() -> bool:
    import os

    return all(os.environ.get(name, "").strip() for name in PRESENTER_KEY_ENVS)


def configured_video_engine() -> str:
    """`QUALIFY_VIDEO_ENGINE` when it names a live engine; otherwise OmniHuman once both
    of its keys are set (§ request 2026-10-16: «dejar todo preparado para cuando tenga
    las api key»), Seedance until then. A stale `heygen` falls through the same way."""
    import os

    value = (os.environ.get(VIDEO_ENGINE_ENV) or "").strip().lower()
    if value in VIDEO_ENGINES:
        return value
    if not presenter_keys_ready():
        return "seedance"
    # OmniHuman downloads the photo and the voice: without a public URL (a local run, no
    # tunnel) every presenter would fail after its frame and voice were paid for
    from qualify_api.creative.composition import public_media_ready

    return "omnihuman" if public_media_ready() else "seedance"


# ---------------------------------------------------------------------------
# The voices of the talking presenter (/create)


def brand_clone_voice(tenant_id: UUID, brand_id: UUID) -> dict[str, str] | None:
    """The brand's own cloned voice (Seed Speech, `voice_lab`) as a voice of the /create
    picker, once ready — None otherwise. Its id is `"brand"`, never the clone's id: the
    producer resolves it server-side (`voice_access`). `own` keeps it listed whatever
    gender the picker shows."""
    from qualify_api.creative.voice_access import BRAND_VOICE
    from qualify_api.creative.voice_clone import VoiceCloneService

    clone = VoiceCloneService().current(tenant_id=tenant_id, brand_id=brand_id)
    if clone is None or not clone.is_ready:
        return None
    return {"id": BRAND_VOICE, "name": f"Tu voz · {clone.name}", "gender": clone.gender, "own": "1"}


def public_voices() -> list[dict[str, str]]:
    """The public Spanish voices the presenter may read with — a closed list, the same
    one the producer accepts (`byteplus_speech.PUBLIC_SPANISH_VOICES`)."""
    from qualify_creative.adapters.byteplus_speech import PUBLIC_SPANISH_VOICES

    return [
        {"id": v["id"], "name": f"{v['name']} · {v['style']}", "gender": v["gender"]}
        for v in PUBLIC_SPANISH_VOICES
    ]


def voice_options(tenant_id: UUID | None, brand_id: UUID | None) -> list[dict[str, str]]:
    """The brand's own voice first (when ready), then the public ones. A clone that
    cannot be read only leaves the list without it."""
    own = None
    if tenant_id is not None and brand_id is not None:
        try:
            own = brand_clone_voice(tenant_id, brand_id)
        except Exception as exc:  # noqa: BLE001 — the public voices still serve
            logger.warning("brand voice clone unreadable: %s", type(exc).__name__)
    return [own, *public_voices()] if own else public_voices()
