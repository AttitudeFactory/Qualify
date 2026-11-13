"""m-25017279 (ADR 49 §2 item 1, migration 0164): a stored base photo is an `image_assets`
row with `role='base'` that no ordinary read sees — it never becomes the draft's cover,
never a carousel child, never what the Planificador publishes — while the opt-in reader
(`base_photos_visible`) and `piece_layers.base_asset_id` reach it."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.creative.base_photos import BASE_ROLE, base_photos_visible
from qualify_api.creative.fsm import GENERATED
from qualify_api.creative.media import BasePhoto, MediaWrite
from qualify_api.creative.models import ContentDraft, ImageAsset, PieceLayer
from qualify_api.creative.service import ContentService, PostgresContentRepository
from qualify_api.planner import draft_post_reader

from .test_piece_layers_db import _layer, _piece

pytestmark = pytest.mark.db


def _still(tenant_id: UUID, draft_id: UUID, position: int, *, base: bool = True) -> MediaWrite:
    key = f"t/{tenant_id}/generated/{draft_id}/r1/slide-{position + 1}.jpg"
    base_key = f"t/{tenant_id}/generated/{draft_id}/r1/base/slide-{position + 1}.jpg"
    return MediaWrite(
        position=position,
        media_type="image",
        media_url=key,
        object_key=key,
        width=1080,
        height=1350,
        aspect_ratio="4:5",
        model_id="seedream-test",
        provider="seedream",
        params={"source": "generated", "base_key": base_key} if base else {},
        content_type="image/jpeg",
        ai_generated=True,
        rendered_prompt=f"scene {position}",
        base=BasePhoto(
            key=base_key,
            sha256=f"{position:x}" * 64,
            content_type="image/jpeg",
            model_id="seedream-test",
            provider="seedream",
            rendered_prompt=f"scene {position}",
            prompt_compiler_version=5,
        )
        if base
        else None,
    )


def _generated(tenant_id: UUID, slides: int = 2) -> tuple[UUID, UUID]:
    brand, draft, _ = _piece(tenant_id, version=False)
    PostgresContentRepository().finish_generation(
        tenant_id=tenant_id,
        draft_id=draft,
        brand_id=brand,
        new_status=GENERATED,
        failure_reason=None,
        variants=(),
        usage=(),
        spent_usd=Decimal(0),
        media=tuple(_still(tenant_id, draft, p) for p in range(slides)),
    )
    return brand, draft


def _service() -> ContentService:
    return ContentService(
        router=None,  # type: ignore[arg-type]
        pricing=None,  # type: ignore[arg-type]
        credentials=None,  # type: ignore[arg-type]
        voice_service=None,  # type: ignore[arg-type]
        brand_service=None,  # type: ignore[arg-type]
        repository=PostgresContentRepository(),
    )


def test_a_kept_base_is_stored_as_its_own_hidden_row(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    _, draft = _generated(tenant_a)
    with tenant_session(tenant_a) as session:
        seen = session.scalars(select(ImageAsset).where(ImageAsset.draft_id == draft)).all()
        assert [row.role for row in seen] == ["output", "output"]
        with base_photos_visible(session):
            bases = session.scalars(
                select(ImageAsset)
                .where(ImageAsset.draft_id == draft, ImageAsset.role == BASE_ROLE)
                .order_by(ImageAsset.position)
            ).all()
        assert [b.position for b in bases] == [0, 1]
        assert bases[0].object_key.endswith("/base/slide-1.jpg")
        assert bases[0].rendered_prompt == "scene 0"
        assert bases[0].params["sha256"] == "0" * 64
        assert {b.version_id for b in bases} == {seen[0].version_id}
        # hidden again once the block is over
        assert (
            len(session.scalars(select(ImageAsset).where(ImageAsset.draft_id == draft)).all()) == 2
        )


def test_a_base_is_never_the_cover_nor_a_child_nor_the_preview(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    tenant_a, _ = seeded_ab
    _, draft = _generated(tenant_a)
    service = _service()
    single = service.get_draft(tenant_id=tenant_a, draft_id=draft)
    batch = service.get_drafts(tenant_id=tenant_a, draft_ids=[draft])[draft]
    assert single == batch
    assert single is not None and single.image is not None
    assert single.image.media_url.endswith("/r1/slide-1.jpg")
    assert [m.media_url.rsplit("/", 2)[-2:] for m in single.media] == [
        ["r1", "slide-1.jpg"],
        ["r1", "slide-2.jpg"],
    ]
    with tenant_session(tenant_a) as session:
        preview = session.get(ContentDraft, draft).preview_key
    assert preview is not None and "/base/" not in preview


def test_the_planner_never_reads_a_base(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    _, draft = _generated(tenant_a)
    with tenant_session(tenant_a) as session:
        images = draft_post_reader._images(session, draft)
    assert len(images) == 2
    assert all("/base/" not in (image.object_key or "") for image in images)


def test_a_base_cannot_be_written_or_seen_without_opting_in(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = seeded_ab
    _, draft = _generated(tenant_a)
    with pytest.raises(DBAPIError), tenant_session(tenant_a) as session:
        session.add(
            ImageAsset(
                tenant_id=tenant_a,
                draft_id=draft,
                role=BASE_ROLE,
                media_url="t/x/base.jpg",
                object_key="t/x/base.jpg",
                position=5,
            )
        )
        session.flush()
    # another business sees no base of A, even opting in
    with tenant_session(tenant_b) as session, base_photos_visible(session):
        assert session.scalars(select(ImageAsset).where(ImageAsset.draft_id == draft)).all() == []


def test_one_base_per_slide_and_version(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    _, draft = _generated(tenant_a)
    with tenant_session(tenant_a) as session:
        version = session.scalar(
            select(ImageAsset.version_id).where(ImageAsset.draft_id == draft).limit(1)
        )
    with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
        with base_photos_visible(session):
            session.add(
                ImageAsset(
                    tenant_id=tenant_a,
                    draft_id=draft,
                    version_id=version,
                    role=BASE_ROLE,
                    media_url="t/x/again.jpg",
                    object_key="t/x/again.jpg",
                    position=0,
                )
            )
            session.flush()


def test_a_layer_points_at_its_base(seeded_ab: tuple[UUID, UUID]) -> None:
    """ADR 49 §2.1: `piece_layers.base_asset_id` reaches the hidden row (keys ignore RLS)."""
    tenant_a, _ = seeded_ab
    brand, draft = _generated(tenant_a)
    with tenant_session(tenant_a) as session, base_photos_visible(session):
        base = session.scalars(
            select(ImageAsset).where(
                ImageAsset.draft_id == draft, ImageAsset.role == BASE_ROLE, ImageAsset.position == 0
            )
        ).one()
        version = base.version_id
        base_id = base.id
    with tenant_session(tenant_a) as session:
        layer = _layer(tenant_a, brand, draft, version, base_asset_id=base_id)
        session.add(layer)
        session.flush()
        assert session.get(PieceLayer, layer.id).base_asset_id == base_id
