"""m-25017283 (ADR 49 §2.1, §2.3 amendment 2026-11-14, migration 0168): the layer's
persistence — the cap of one base regeneration per slide is a unique key, a generation
writes the ROOT layer of each still pointing at its stored base, and every derived layer
derives from the current leaf of the same draft, version and position."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from uuid import UUID

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative.fsm import GENERATED
from qualify_api.creative.layer_store import (
    LayerWriteRefused,
    append_layer,
    claim_base_regeneration,
    leaf_of,
)
from qualify_api.creative.media import LayerWrite
from qualify_api.creative.models import PieceBasePhoto, PieceLayer
from qualify_api.creative.service import PostgresContentRepository

from .test_base_photos_db import _still
from .test_piece_layers_db import _piece

pytestmark = pytest.mark.db

SPEC = {"layout_id": "plate", "title": "Tu shawarma, recién hecho"}


def _layer(title: str = "Tu shawarma, recién hecho") -> LayerWrite:
    return LayerWrite(
        spec={**SPEC, "title": title},
        spec_sha256=(title.encode().hex() * 64)[:64],
        layout_id="plate",
        layout_version=1,
        model_id="claude-sonnet-5-5",
        prompt_version="capa-v1",
    )


def _claim(tenant: UUID, brand: UUID, draft: UUID, position: int = 0) -> bool:
    return claim_base_regeneration(
        tenant_id=tenant,
        brand_id=brand,
        draft_id=draft,
        revision=1,
        position=position,
        reason="base_has_invented_text",
        model_id="claude-sonnet-5-5",
        prompt_version="capa-v1",
    )


def test_a_slide_s_base_is_regenerated_at_most_once(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = seeded_ab
    brand, draft, _ = _piece(tenant_a, version=False)
    assert _claim(tenant_a, brand, draft) is True
    assert _claim(tenant_a, brand, draft) is False  # the key is the cap
    assert _claim(tenant_a, brand, draft, position=1) is True  # another slide
    with pytest.raises(Exception):  # noqa: B017 - another business cannot claim A's draft
        _claim(tenant_b, brand, draft, position=2)


def _generated_with_layers(tenant: UUID) -> tuple[UUID, UUID, UUID]:
    brand, draft, _ = _piece(tenant, version=False)
    media = tuple(replace(_still(tenant, draft, p), layer=_layer()) for p in range(2))
    PostgresContentRepository().finish_generation(
        tenant_id=tenant,
        draft_id=draft,
        brand_id=brand,
        new_status=GENERATED,
        failure_reason=None,
        variants=(),
        usage=(),
        spent_usd=Decimal(0),
        media=media,
    )
    with tenant_session(tenant) as session:
        version = session.scalar(
            select(PieceLayer.version_id).where(PieceLayer.draft_id == draft).limit(1)
        )
    return brand, draft, version


def test_a_generation_writes_each_still_s_root_layer_on_its_base(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    tenant_a, _ = seeded_ab
    _, draft, version = _generated_with_layers(tenant_a)
    with tenant_session(tenant_a) as session:
        layers = session.scalars(
            select(PieceLayer).where(PieceLayer.draft_id == draft).order_by(PieceLayer.position)
        ).all()
        bases = dict(
            session.execute(
                select(PieceBasePhoto.position, PieceBasePhoto.id).where(
                    PieceBasePhoto.draft_id == draft
                )
            ).all()
        )
        assert [(row.position, row.parent_layer_id) for row in layers] == [(0, None), (1, None)]
        assert all(row.base_asset_id == bases[row.position] for row in layers)
        assert {row.source for row in layers} == {"model"}
        assert layers[0].model_id == "claude-sonnet-5-5" and layers[0].prompt_version == "capa-v1"
        assert layers[0].pipeline_version == "image-pipeline-layer-v1"
        assert layers[0].version_id == version


def test_edits_chain_from_the_leaf_in_the_same_version(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    _, draft, version = _generated_with_layers(tenant_a)
    with tenant_session(tenant_a) as session:
        root = leaf_of(session, version_id=version, position=0)
        assert root is not None and root.parent_layer_id is None
        edit = append_layer(
            session, parent=root, layer=_layer("Tu shawarma de hoy"), source="model"
        )
        assert edit.version_id == version and edit.position == 0 and edit.draft_id == draft
        assert leaf_of(session, version_id=version, position=0).id == edit.id
        with pytest.raises(LayerWriteRefused):  # the old root is no longer the leaf
            append_layer(session, parent=root, layer=_layer("Otra"), source="model")
        other = leaf_of(session, version_id=version, position=1)
        assert other is not None and other.parent_layer_id is None  # its own chain


def test_a_derived_layer_comes_from_the_model_or_the_owner(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    _, _, version = _generated_with_layers(tenant_a)
    with tenant_session(tenant_a) as session:
        root = leaf_of(session, version_id=version, position=0)
        with pytest.raises(LayerWriteRefused):
            append_layer(session, parent=root, layer=_layer(), source="owner_photo")
        mismatch = replace(_layer(), layout_id="band")
        with pytest.raises(LayerWriteRefused):
            append_layer(session, parent=root, layer=mismatch, source="model")
