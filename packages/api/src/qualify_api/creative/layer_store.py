"""Persistence of the text layer (m-25017283, ADR 49 §2.1 and the §2.3 amendment of
2026-11-14): what the layer stage reads (the business's saved data, the piece's catalog
products), the cap of one base regeneration per slide (0168), the ROOT `piece_layers` rows a
generation writes, and the one writer of every derived layer (`append_layer`).

Everything goes through `tenant_session`. Like the base photos, writing a generation's
layers never costs the owner their paid piece: it runs in a SAVEPOINT and a refusal is
logged, the piece is committed without its layer.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import exists, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, aliased

from qualify_api.creative import models as orm
from qualify_api.creative.image_pipeline.layer import (
    LAYER_PIPELINE_VERSION,
    BusinessFacts,
    CatalogProduct,
)
from qualify_api.creative.media import LayerWrite, MediaWrite

logger = logging.getLogger(__name__)

MODEL_SOURCE = "model"
OWNER_EDIT = "owner_edit"
OWNER_PHOTO = "owner_photo"

#: catalog §1.5: payment methods shown, at most, and how they are joined.
_PAYMENT_MAX = 4
_PRODUCTS_MAX = 3


class LayerWriteRefused(ValueError):
    """A derived layer that breaks a rule the schema cannot state (ADR 49 §2.1)."""


# -- what the layer stage reads -----------------------------------------------------------


def load_business_facts(tenant_id: UUID, brand_id: UUID) -> BusinessFacts:
    """The business's saved data an info block may show. Today: the address and the
    number of its connected WhatsApp line and its active payment methods; opening hours are
    not stored yet (m-25017300), so an `hours` block is never offered."""
    from qualify_api.whatsapp.models import BrandPaymentMethod, WhatsAppPhoneNumber  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        line = session.scalars(
            select(WhatsAppPhoneNumber)
            .where(WhatsAppPhoneNumber.brand_id == brand_id)
            .order_by(WhatsAppPhoneNumber.created_at)
            .limit(1)
        ).first()
        methods = session.scalars(
            select(BrandPaymentMethod.name)
            .where(BrandPaymentMethod.brand_id == brand_id, BrandPaymentMethod.active.is_(True))
            .order_by(BrandPaymentMethod.position)
            .limit(_PAYMENT_MAX)
        ).all()
    return BusinessFacts(
        location=getattr(line, "location_address", None) if line is not None else None,
        contact=getattr(line, "display_phone_number", None) if line is not None else None,
        payment=" · ".join(m for m in methods if m) or None,
    )


def load_catalog_products(
    tenant_id: UUID, brand_id: UUID, product_ref: str | None
) -> tuple[CatalogProduct, ...]:
    """The catalog products the brief names (`catalog.read._match`), each with whether
    its price prints whole (`price_label`, the price guard's rule: whole or not at all)."""
    from qualify_api.catalog.models import BrandProduct  # noqa: PLC0415
    from qualify_api.catalog.read import _match, price_label  # noqa: PLC0415

    if not product_ref or not product_ref.strip():
        return ()
    with tenant_session(tenant_id) as session:
        rows = list(
            session.scalars(
                select(BrandProduct)
                .where(BrandProduct.brand_id == brand_id, BrandProduct.is_active.is_(True))
                .order_by(BrandProduct.position, BrandProduct.name)
            )
        )
        matches = _match(rows, product_ref.strip())
        return tuple(
            CatalogProduct(
                product_id=p.id,
                name=p.name,
                has_price=bool(price_label(p.price_amount, p.price_currency or "")),
            )
            for p in matches[:_PRODUCTS_MAX]
        )


# -- the regeneration cap (0168) ----------------------------------------------------------


def claim_base_regeneration(
    *,
    tenant_id: UUID,
    brand_id: UUID,
    draft_id: UUID,
    revision: int,
    position: int,
    reason: str,
    model_id: str,
    prompt_version: str,
) -> bool:
    """True when THIS caller may regenerate the slide's base: the row is new. False when it
    was already claimed — by an earlier attempt, a resumed run, anyone: the unique key
    `uq_piece_base_regenerations_slide` is the cap, not this function."""
    with tenant_session(tenant_id) as session:
        claimed = session.execute(
            pg_insert(orm.PieceBaseRegeneration)
            .values(
                tenant_id=tenant_id,
                brand_id=brand_id,
                draft_id=draft_id,
                revision=revision,
                position=position,
                reason=reason[:200] or "base_has_invented_text",
                model_id=model_id,
                prompt_version=prompt_version,
            )
            .on_conflict_do_nothing(constraint="uq_piece_base_regenerations_slide")
            .returning(orm.PieceBaseRegeneration.id)
        ).first()
    return claimed is not None


# -- the generation's root layers ---------------------------------------------------------


def _root_rows(
    session: Session,
    *,
    tenant_id: UUID,
    brand_id: UUID,
    draft_id: UUID,
    version_id: UUID,
    media: Sequence[MediaWrite],
) -> list[dict[str, Any]]:
    bases = dict(
        session.execute(
            select(orm.PieceBasePhoto.position, orm.PieceBasePhoto.id).where(
                orm.PieceBasePhoto.version_id == version_id,
                orm.PieceBasePhoto.state == "stored",
            )
        ).all()
    )
    return [
        {
            "tenant_id": tenant_id,
            "brand_id": brand_id,
            "draft_id": draft_id,
            "version_id": version_id,
            "position": item.position,
            "layout_id": item.layer.layout_id,
            "layout_version": item.layer.layout_version,
            "spec": item.layer.spec,
            "spec_sha256": item.layer.spec_sha256,
            "base_asset_id": bases.get(item.position),
            "source": MODEL_SOURCE,
            "model_id": item.layer.model_id,
            "prompt_version": item.layer.prompt_version,
            "pipeline_version": LAYER_PIPELINE_VERSION,
        }
        for item in media
        if item.layer is not None
    ]


def record_layers(
    session: Session,
    *,
    tenant_id: UUID,
    brand_id: UUID,
    draft_id: UUID,
    version_id: UUID,
    media: Sequence[MediaWrite],
) -> int:
    """The ROOT layer of each file that carries one, at its version and position, its base
    the `piece_base_photos` row of the same position. Never raises: a refusal rolls back
    its savepoint only, and the piece is committed without its layers."""
    if not any(item.layer is not None for item in media):
        return 0
    session.flush()  # unrelated pending writes fail as themselves, outside the savepoint
    try:
        with session.begin_nested():
            rows = _root_rows(
                session,
                tenant_id=tenant_id,
                brand_id=brand_id,
                draft_id=draft_id,
                version_id=version_id,
                media=media,
            )
            if rows:
                session.execute(insert(orm.PieceLayer), rows)
            return len(rows)
    except Exception as exc:  # noqa: BLE001 - a layer never fails the paid piece
        logger.warning("layers of draft %s not written: %s", draft_id, exc)
        return 0


# -- every derived layer ------------------------------------------------------------------


def leaf_of(session: Session, *, version_id: UUID, position: int) -> orm.PieceLayer | None:
    """The current layer of a version and position: the one with no child in it."""
    child = aliased(orm.PieceLayer)
    return session.scalars(
        select(orm.PieceLayer)
        .where(orm.PieceLayer.version_id == version_id, orm.PieceLayer.position == position)
        .where(
            ~exists().where(
                child.parent_layer_id == orm.PieceLayer.id,
                child.version_id == orm.PieceLayer.version_id,
            )
        )
    ).first()


def append_layer(
    session: Session,
    *,
    parent: orm.PieceLayer,
    layer: LayerWrite,
    source: str,
    created_by: UUID | None = None,
) -> orm.PieceLayer:
    """A derived layer (an owner's edit, the visual check's correction, «Deshacer»): a
    child of `parent` in the SAME version and position (ADR 49 §2.3). Refused unless the
    parent is the current leaf of its version and position — the rules the schema cannot
    state (`LayerWriteRefused`). The approval and the schedule are the caller's to void in
    the same transaction (m-25017288)."""
    if source not in (MODEL_SOURCE, OWNER_EDIT):
        raise LayerWriteRefused(f"a derived layer comes from the model or the owner, not {source}")
    leaf = leaf_of(session, version_id=parent.version_id, position=parent.position)
    if leaf is None or leaf.id != parent.id:
        raise LayerWriteRefused("a new layer derives from the current leaf of its slide only")
    if layer.spec.get("layout_id") != layer.layout_id:
        raise LayerWriteRefused("the layer's layout_id and its spec disagree")
    # built from the row just read and checked, never from the caller's object
    row = orm.PieceLayer(
        tenant_id=leaf.tenant_id,
        brand_id=leaf.brand_id,
        draft_id=leaf.draft_id,  # same draft, by construction
        version_id=leaf.version_id,  # same version
        position=leaf.position,  # same position
        layout_id=layer.layout_id,
        layout_version=layer.layout_version,
        spec=layer.spec,
        spec_sha256=layer.spec_sha256,
        base_asset_id=leaf.base_asset_id,
        base_media_ref=leaf.base_media_ref,
        source=source,
        parent_layer_id=leaf.id,
        created_by=created_by,
        model_id=layer.model_id if source == MODEL_SOURCE else None,
        prompt_version=layer.prompt_version if source == MODEL_SOURCE else None,
        pipeline_version=LAYER_PIPELINE_VERSION,
    )
    session.add(row)
    session.flush()
    return row
