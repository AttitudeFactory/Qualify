"""m-25017279 (ADR 49 §2 item 1, migration 0164): a base photo lives in its own table,
`piece_base_photos` — never in `image_assets` — so it can never become the draft's cover,
a carousel child, the preview or what the Planificador publishes. A base R2 did not keep is
a `missing` row. `piece_layers.base_asset_id` points at it."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from qualify_api.creative.fsm import GENERATED
from qualify_api.creative.media import BasePhoto, MediaWrite
from qualify_api.creative.models import ContentDraft, ImageAsset, PieceBasePhoto, PieceLayer
from qualify_api.creative.service import ContentService, PostgresContentRepository
from qualify_api.planner import draft_post_reader

from .test_piece_layers_db import _layer, _piece

pytestmark = pytest.mark.db


def _still(tenant_id: UUID, draft_id: UUID, position: int, *, kept: bool = True) -> MediaWrite:
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
        params={"source": "generated", "base_key": base_key} if kept else {"base_missing": True},
        content_type="image/jpeg",
        ai_generated=True,
        rendered_prompt=f"scene {position}",
        base=BasePhoto(
            key=base_key if kept else None,
            sha256=f"{position:x}" * 64,
            content_type="image/jpeg",
            model_id="seedream-test",
            provider="seedream",
            rendered_prompt=f"scene {position}",
            prompt_compiler_version=5,
            width=1280,
            height=1600,
            missing_reason=None if kept else "R2 did not keep the base photo",
        ),
    )


def _generated(tenant_id: UUID, *, kept: bool = True) -> tuple[UUID, UUID]:
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
        media=tuple(_still(tenant_id, draft, p, kept=kept) for p in range(2)),
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


def _bases(tenant_id: UUID, draft: UUID) -> list[PieceBasePhoto]:
    with tenant_session(tenant_id) as session:
        return list(
            session.scalars(
                select(PieceBasePhoto)
                .where(PieceBasePhoto.draft_id == draft)
                .order_by(PieceBasePhoto.position)
            )
        )


def test_each_still_base_gets_its_own_row(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    _, draft = _generated(tenant_a)
    bases = _bases(tenant_a, draft)
    assert [(b.position, b.state) for b in bases] == [(0, "stored"), (1, "stored")]
    assert bases[0].object_key.endswith("/r1/base/slide-1.jpg")
    assert bases[0].sha256 == "0" * 64
    assert (bases[0].width, bases[0].height) == (1280, 1600)
    assert bases[0].rendered_prompt == "scene 0" and bases[0].prompt_compiler_version == 5
    with tenant_session(tenant_a) as session:
        outputs = session.scalars(select(ImageAsset).where(ImageAsset.draft_id == draft)).all()
    assert len(outputs) == 2 and all("/base/" not in o.object_key for o in outputs)
    assert {b.version_id for b in bases} == {outputs[0].version_id}


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
    assert [m.media_url.rsplit("/", 1)[1] for m in single.media] == ["slide-1.jpg", "slide-2.jpg"]
    assert all("/base/" not in m.media_url for m in single.media)
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


def test_a_base_r2_did_not_keep_is_recorded_as_missing(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    _, draft = _generated(tenant_a, kept=False)
    bases = _bases(tenant_a, draft)
    assert [b.state for b in bases] == ["missing", "missing"]
    assert all(b.object_key is None and b.missing_reason for b in bases)


def test_another_business_sees_no_base(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = seeded_ab
    _, draft = _generated(tenant_a)
    assert _bases(tenant_b, draft) == []


def test_one_base_per_slide_and_version(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    brand, draft = _generated(tenant_a)
    first = _bases(tenant_a, draft)[0]
    with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
        session.add(
            PieceBasePhoto(
                tenant_id=tenant_a,
                brand_id=brand,
                draft_id=draft,
                version_id=first.version_id,
                position=0,
                state="missing",
                rendered_prompt="again",
                model_id="m",
                provider="seedream",
                prompt_compiler_version=5,
                pipeline_version="t",
                missing_reason="test",
            )
        )
        session.flush()


def test_a_stored_base_lives_in_its_own_piece_folder(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = seeded_ab
    brand, draft = _generated(tenant_a)
    first = _bases(tenant_a, draft)[0]
    with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
        session.add(
            PieceBasePhoto(
                tenant_id=tenant_a,
                brand_id=brand,
                draft_id=draft,
                version_id=first.version_id,
                position=3,
                state="stored",
                object_key=f"t/{tenant_b}/generated/{draft}/r1/base/slide-4.jpg",
                sha256="a" * 64,
                content_type="image/jpeg",
                rendered_prompt="x",
                model_id="m",
                provider="seedream",
                prompt_compiler_version=5,
                pipeline_version="t",
            )
        )
        session.flush()


def test_a_layer_points_at_its_base(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    """ADR 49 §2.1: `piece_layers.base_asset_id` → `piece_base_photos (id, tenant_id)`."""
    tenant_a, _ = seeded_ab
    brand, draft = _generated(tenant_a)
    base = _bases(tenant_a, draft)[0]
    with tenant_session(tenant_a) as session:
        layer = _layer(tenant_a, brand, draft, base.version_id, base_asset_id=base.id)
        session.add(layer)
        session.flush()
        layer_id = layer.id
    with tenant_session(tenant_a) as session:
        assert session.get(PieceLayer, layer_id).base_asset_id == base.id


def test_a_layer_cannot_point_at_an_output_or_another_business_base(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = seeded_ab
    brand, draft = _generated(tenant_a)
    version = _bases(tenant_a, draft)[0].version_id
    with tenant_session(tenant_a) as session:
        output = session.scalar(select(ImageAsset.id).where(ImageAsset.draft_id == draft).limit(1))
    _, their_draft = _generated(tenant_b)
    theirs = _bases(tenant_b, their_draft)[0].id
    for target in (output, theirs):
        with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
            session.add(_layer(tenant_a, brand, draft, version, base_asset_id=target))
            session.flush()
