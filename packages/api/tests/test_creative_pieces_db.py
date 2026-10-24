"""`db`-marked tests for the carousel's «De una pieza» reader (§ request 2026-10-09,
`qualify_api.creative.pieces`): it lists — and confirms — only the files of THIS brand's
pieces. A key of a sibling brand of the same tenant passes `owned_by` (the tenant prefix)
but must not pass here; another tenant's never reaches the query (RLS).

Provisioning through `admin_session`; the reader runs through `tenant_session`."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative import models as creative
from qualify_api.creative.pieces import DbPieceFiles
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

TENANT_P = UUID("c0000000-0000-4000-8000-000000001009")
TENANT_Q = UUID("d0000000-0000-4000-8000-000000001009")


def _brands(tenant_id: UUID, count: int) -> list[UUID]:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"pieces-{tenant_id}",
                    country="VE",
                    timezone="America/Caracas",
                    currency="USD",
                )
            )
            session.flush()
        existing = list(session.scalars(select(Brand).where(Brand.tenant_id == tenant_id)).all())
        while len(existing) < count:
            brand = Brand(tenant_id=tenant_id, name=f"brand-{len(existing)}")
            session.add(brand)
            session.flush()
            existing.append(brand)
        return sorted((brand.id for brand in existing), key=str)[:count]


def _piece(tenant_id: UUID, brand_id: UUID, topic: str) -> tuple[str, str]:
    """A generated piece with an image slide and a video slide: their keys."""
    with tenant_session(tenant_id) as session:
        brief = creative.ContentBrief(
            tenant_id=tenant_id,
            brand_id=brand_id,
            objective="sale",
            topic=topic,
            platform="instagram",
            format="feed_4_5",
            intent="organic",
            content_type="promotion",
            image_route="template_only",
        )
        session.add(brief)
        session.flush()
        draft = creative.ContentDraft(
            tenant_id=tenant_id,
            brief_id=brief.id,
            brand_id=brand_id,
            status="generated",
            pipeline_version="test",
        )
        session.add(draft)
        session.flush()
        image = f"t/{tenant_id}/generated/{draft.id}/r1/slide-1.jpg"
        video = f"t/{tenant_id}/generated/{draft.id}/r1/slide-2.mp4"
        poster = f"t/{tenant_id}/generated/{draft.id}/r1/slide-2-poster.jpg"
        for position, (key, kind, params) in enumerate(
            [(image, "image", {}), (video, "video", {"thumbnail_key": poster})]
        ):
            session.add(
                creative.ImageAsset(
                    tenant_id=tenant_id,
                    draft_id=draft.id,
                    media_url=key,
                    object_key=key,
                    content_type="image/jpeg" if kind == "image" else "video/mp4",
                    media_type=kind,
                    position=position,
                    params=params,
                )
            )
        session.flush()
        return image, video


def test_only_this_brands_pieces_are_listed_and_confirmed() -> None:
    mine, sibling = _brands(TENANT_P, 2)
    (other_tenant_brand,) = _brands(TENANT_Q, 1)
    topic = f"Promo {uuid4().hex[:6]}"
    image, video = _piece(TENANT_P, mine, topic)
    sibling_image, _ = _piece(TENANT_P, sibling, "De la otra marca")
    foreign_image, _ = _piece(TENANT_Q, other_tenant_brand, "De otro tenant")
    reader = DbPieceFiles()

    files = reader.files(tenant_id=TENANT_P, brand_id=mine)
    keys = [piece.object_key for piece in files]
    assert image in keys and video in keys
    assert sibling_image not in keys and foreign_image not in keys
    listed = {piece.object_key: piece for piece in files}
    assert listed[video].media_type == "video" and listed[video].poster_key
    assert listed[image].topic == topic

    assert reader.file(tenant_id=TENANT_P, brand_id=mine, object_key=video) is not None
    # the sibling brand's key carries THIS tenant's prefix — `owned_by` would pass it
    assert reader.file(tenant_id=TENANT_P, brand_id=mine, object_key=sibling_image) is None
    assert reader.file(tenant_id=TENANT_P, brand_id=mine, object_key=foreign_image) is None
    assert reader.file(tenant_id=TENANT_P, brand_id=mine, object_key="") is None


def test_a_piece_carries_its_chosen_copys_hook_as_its_title() -> None:
    """§ request 2026-10-14: a picker shows a piece by its title — the hook of its chosen
    copy variant (else its first one) — not by the prompt it was made from."""
    (brand,) = _brands(TENANT_P, 1)
    image, _ = _piece(TENANT_P, brand, "el prompt largo que escribió el operador")
    untitled, _ = _piece(TENANT_P, brand, "otra pieza sin copy")
    with tenant_session(TENANT_P) as session:
        draft_id = session.scalars(
            select(creative.ImageAsset.draft_id).where(creative.ImageAsset.object_key == image)
        ).one()
        variants = []
        for ordinal, hook in enumerate(("Primera opción", "La smash del domingo")):
            variant = creative.CopyVariant(
                tenant_id=TENANT_P,
                draft_id=draft_id,
                ordinal=ordinal,
                copy={"hook": hook, "caption": "", "cta": "", "hashtags": []},
                model_id="test",
            )
            session.add(variant)
            session.flush()
            variants.append(variant)
        draft = session.get(creative.ContentDraft, draft_id)
        draft.selected_variant_id = variants[1].id
    files = DbPieceFiles().files(tenant_id=TENANT_P, brand_id=brand)
    listed = {piece.object_key: piece for piece in files}
    assert listed[image].title == "La smash del domingo"
    assert listed[untitled].title == ""


def test_a_video_still_at_its_480p_draft_is_not_offered() -> None:
    """m-24820142: a carousel reusing a Seedance 2.5 draft video would carry a 480p
    video with no draft block of its own (publishable); its final is offered."""
    (brand,) = _brands(TENANT_P, 1)
    image, video = _piece(TENANT_P, brand, "pieza con borrador")
    reader = DbPieceFiles()

    def set_draft(block: dict | None) -> None:
        with tenant_session(TENANT_P) as session:
            row = session.scalars(
                select(creative.ImageAsset).where(creative.ImageAsset.object_key == video)
            ).one()
            params = {key: value for key, value in (row.params or {}).items() if key != "draft"}
            if block is not None:
                params["draft"] = block
            row.params = params

    for status in ("draft", "rendering", "failed"):
        set_draft({"status": status, "task_id": "cgt-draft"})
        keys = [piece.object_key for piece in reader.files(tenant_id=TENANT_P, brand_id=brand)]
        assert video not in keys and image in keys, status
        assert reader.file(tenant_id=TENANT_P, brand_id=brand, object_key=video) is None

    set_draft({"status": "final", "task_id": "cgt-draft"})
    keys = [piece.object_key for piece in reader.files(tenant_id=TENANT_P, brand_id=brand)]
    assert video in keys
    assert reader.file(tenant_id=TENANT_P, brand_id=brand, object_key=video) is not None
