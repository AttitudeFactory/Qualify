"""m-25017278 (ADR 49 §2.1): `piece_layers` — RLS isolation, the composite keys that keep a
layer inside its business, the idempotency key and the provenance checks. The table ships
empty: nothing in the pipeline writes it yet (m-25017283 will)."""

from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.creative.fsm import GENERATED
from qualify_api.creative.media import MediaWrite
from qualify_api.creative.models import ImageAsset, PieceLayer
from qualify_api.creative.service import PostgresContentRepository

pytestmark = pytest.mark.db

SPEC = {"title": "Smash doble", "subtitle": "", "blocks": []}
SPEC_SHA = hashlib.sha256(json.dumps(SPEC, sort_keys=True).encode()).hexdigest()


def _piece(tenant_id: UUID, *, version: bool = True) -> tuple[UUID, UUID, UUID]:
    """A brief, a draft and (unless `version=False`, a piece still drafting) its first
    version, as the app writes them."""
    draft_id, version_id = uuid4(), uuid4()
    with tenant_session(tenant_id) as session:
        brand_id = session.execute(
            text("SELECT id FROM brands WHERE tenant_id = :t ORDER BY created_at LIMIT 1"),
            {"t": tenant_id},
        ).scalar_one()
        brief_id = session.execute(
            text(
                "INSERT INTO content_briefs (tenant_id, brand_id, objective, topic, platform,"
                " format, intent, content_type, image_route)"
                " VALUES (:t, :b, 'o', 't', 'instagram', 'feed', 'i', 'image', 'r') RETURNING id"
            ),
            {"t": tenant_id, "b": brand_id},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO content_drafts (id, tenant_id, brief_id, brand_id, status)"
                " VALUES (:d, :t, :brief, :b, 'drafting')"
            ),
            {"d": draft_id, "t": tenant_id, "brief": brief_id, "b": brand_id},
        )
        if not version:
            return brand_id, draft_id, version_id
        session.execute(
            text(
                "INSERT INTO piece_versions (id, tenant_id, brand_id, draft_id, revision, status)"
                " VALUES (:v, :t, :b, :d, 1, 'active')"
            ),
            {"v": version_id, "t": tenant_id, "b": brand_id, "d": draft_id},
        )
    return brand_id, draft_id, version_id


def _layer(tenant_id: UUID, brand_id: UUID, draft_id: UUID, version_id: UUID, **over) -> PieceLayer:
    values = {
        "tenant_id": tenant_id,
        "brand_id": brand_id,
        "draft_id": draft_id,
        "version_id": version_id,
        "position": 0,
        "layout_id": "headline_top",
        "layout_version": 1,
        "spec": SPEC,
        "spec_sha256": SPEC_SHA,
        "source": "model",
        "model_id": "claude-test",
        "prompt_version": "layer-v1",
        "pipeline_version": "image-pipeline-v1",
    }
    values.update(over)
    return PieceLayer(**values)


def test_a_business_sees_and_writes_only_its_own_layers(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = seeded_ab
    brand_a, draft_a, version_a = _piece(tenant_a)
    brand_b, draft_b, version_b = _piece(tenant_b)
    with tenant_session(tenant_a) as session:
        session.add(_layer(tenant_a, brand_a, draft_a, version_a))
    with tenant_session(tenant_b) as session:
        session.add(_layer(tenant_b, brand_b, draft_b, version_b))

    with tenant_session(tenant_a) as session:
        seen = session.scalars(select(PieceLayer.tenant_id)).all()
    assert set(seen) == {tenant_a}

    # writing a row for another business is refused by the policy's WITH CHECK
    with pytest.raises(DBAPIError), tenant_session(tenant_a) as session:
        session.add(_layer(tenant_b, brand_b, draft_b, version_b, position=1))
        session.flush()

    # no tenant set: nothing visible
    with tenant_session(tenant_a) as session:
        session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        assert session.scalars(select(PieceLayer)).all() == []


def test_a_layer_cannot_point_at_another_business_piece(seeded_ab: tuple[UUID, UUID]) -> None:
    """The composite keys: a row of business A naming B's draft and version (ids a bug could
    carry across) is refused by the foreign keys, which RLS does not hide."""
    tenant_a, tenant_b = seeded_ab
    brand_a, _, _ = _piece(tenant_a)
    _, draft_b, version_b = _piece(tenant_b)
    with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
        session.add(_layer(tenant_a, brand_a, draft_b, version_b))
        session.flush()


def test_one_layer_per_slide_and_version(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    brand, draft, version = _piece(tenant_a)
    with tenant_session(tenant_a) as session:
        session.add(_layer(tenant_a, brand, draft, version))
    with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
        session.add(_layer(tenant_a, brand, draft, version))
        session.flush()


@pytest.mark.parametrize(
    "over",
    [
        {"model_id": None},  # a model's layer without its provenance
        {"source": "owner_edit"},  # an owner's edit without who and from which layer
        {"spec_sha256": "nope"},
        {"position": 10},
        {"base_media_ref": "n:not-a-uuid"},
        {"base_media_ref": f"n:{uuid4()}", "base_asset_id": uuid4()},
    ],
)
def test_the_checks_refuse_a_layer_without_its_provenance(
    seeded_ab: tuple[UUID, UUID], over: dict[str, object]
) -> None:
    tenant_a, _ = seeded_ab
    brand, draft, version = _piece(tenant_a)
    with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
        session.add(_layer(tenant_a, brand, draft, version, **over))
        session.flush()


def test_deleting_the_piece_takes_its_layers(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    brand, draft, version = _piece(tenant_a)
    with tenant_session(tenant_a) as session:
        session.add(_layer(tenant_a, brand, draft, version, base_media_ref=f"n:{uuid4()}"))
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        with engine.begin() as conn:  # the owner: no role of the app deletes a version
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)})
            conn.execute(text("DELETE FROM piece_versions WHERE id = :v"), {"v": version})
            left = conn.scalar(
                text("SELECT count(*) FROM piece_layers WHERE version_id = :v"), {"v": version}
            )
    finally:
        engine.dispose()
    assert left == 0


def test_a_generated_slide_prompt_reaches_image_assets(seeded_ab: tuple[UUID, UUID]) -> None:
    """m-25017278: `MediaWrite.rendered_prompt` is persisted as `image_assets.rendered_prompt`
    by the same transaction that saves the piece."""
    tenant_a, _ = seeded_ab
    brand, draft, _ = _piece(tenant_a, version=False)
    key = f"t/{tenant_a}/generated/{draft}/slide-1.jpg"
    PostgresContentRepository().finish_generation(
        tenant_id=tenant_a,
        draft_id=draft,
        brand_id=brand,
        new_status=GENERATED,
        failure_reason=None,
        variants=(),
        usage=(),
        spent_usd=Decimal(0),
        media=(
            MediaWrite(
                position=0,
                media_type="image",
                media_url=key,
                object_key=key,
                width=1080,
                height=1350,
                aspect_ratio="4:5",
                model_id="seedream-test",
                provider="seedream",
                content_type="image/jpeg",
                ai_generated=True,
                rendered_prompt="Create one professional advertising photograph",
            ),
        ),
    )
    with tenant_session(tenant_a) as session:
        stored = session.scalars(
            select(ImageAsset.rendered_prompt).where(ImageAsset.draft_id == draft)
        ).all()
    assert stored == ["Create one professional advertising photograph"]


def _asset(tenant_id: UUID, draft_id: UUID, version_id: UUID) -> UUID:
    asset_id = uuid4()
    with tenant_session(tenant_id) as session:
        session.execute(
            text(
                "INSERT INTO image_assets (id, tenant_id, draft_id, version_id, media_url,"
                " object_key, content_type, media_type)"
                " VALUES (:id, :t, :d, :v, 'unused', :key, 'image/jpeg', 'image')"
            ),
            {
                "id": asset_id,
                "t": tenant_id,
                "d": draft_id,
                "v": version_id,
                "key": f"t/{tenant_id}/generated/{draft_id}/base/{asset_id}.jpg",
            },
        )
    return asset_id


def _add(tenant_id: UUID, piece: tuple[UUID, UUID, UUID], **over: object) -> UUID:
    layer = _layer(tenant_id, *piece, **over)
    with tenant_session(tenant_id) as session:
        session.add(layer)
        session.flush()
        return layer.id


def test_a_layer_cannot_use_another_business_base_photo(seeded_ab: tuple[UUID, UUID]) -> None:
    """Review of m-25017278: keys are checked without RLS, so the asset key carries
    `tenant_id` — A can neither point at nor probe B's stored photo."""
    tenant_a, tenant_b = seeded_ab
    piece_a = _piece(tenant_a)
    piece_b = _piece(tenant_b)
    theirs = _asset(tenant_b, piece_b[1], piece_b[2])
    with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
        session.add(_layer(tenant_a, *piece_a, base_asset_id=theirs))
        session.flush()
    # its own photo is fine, and deleting that photo clears only the reference
    mine = _asset(tenant_a, piece_a[1], piece_a[2])
    layer = _add(tenant_a, piece_a, base_asset_id=mine)
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)})
            conn.execute(text("DELETE FROM image_assets WHERE id = :a"), {"a": mine})
    finally:
        engine.dispose()
    with tenant_session(tenant_a) as session:
        row = session.get(PieceLayer, layer)
        assert row is not None and row.base_asset_id is None and row.tenant_id == tenant_a


def test_a_layer_cannot_derive_from_another_business_layer(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = seeded_ab
    piece_a = _piece(tenant_a)
    theirs = _add(tenant_b, _piece(tenant_b))
    with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
        session.add(_layer(tenant_a, *piece_a, parent_layer_id=theirs))
        session.flush()


def test_one_correction_per_layer_at_the_same_slide(seeded_ab: tuple[UUID, UUID]) -> None:
    """ADR 49 §2.3: the visual check writes its corrected layer as a new row at the same
    version and position; one per parent, and a second root stays refused."""
    tenant_a, _ = seeded_ab
    piece = _piece(tenant_a)
    root = _add(tenant_a, piece)
    with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
        session.add(_layer(tenant_a, *piece))  # a second root at position 0
        session.flush()
    fixed = _add(tenant_a, piece, parent_layer_id=root)  # the one correction
    assert fixed != root
    with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
        session.add(_layer(tenant_a, *piece, parent_layer_id=root))  # a second one
        session.flush()
    assert _add(tenant_a, piece, parent_layer_id=fixed)  # a further change derives from it
