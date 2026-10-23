"""`db`-marked test for a Seedance 2.5 final (m-24820142) against the real schema: the
draft block is merged into the video's JSONB, and the final replaces the draft IN THE
SAME ROW (every reader keeps reading the piece's one video), with its spend recorded —
also when it failed."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative import models as creative
from qualify_api.creative.draft_mode import DRAFT_FAILED, DRAFT_READY, DRAFT_RENDERING
from qualify_api.creative.media import MediaWrite
from qualify_api.creative.service import PostgresContentRepository, UsageWrite

from .test_creative_regenerate_db import _brand, _drafting_draft, _variant

pytestmark = pytest.mark.db

TENANT_F = UUID("c0000000-0000-4000-8000-000000001020")
MODEL = "dreamina-seedance-2-5-260628"


def _video(tenant_id: UUID, draft_id: UUID, name: str, status: str) -> MediaWrite:
    key = f"t/{tenant_id}/generated/{draft_id}/r1/{name}"
    return MediaWrite(
        position=0,
        media_type="video",
        media_url=key,
        object_key=key,
        width=480,
        height=854,
        aspect_ratio="9:16",
        model_id=MODEL,
        provider="seedance",
        content_type="video/mp4",
        params={"resolution": "480p", "draft": {"status": status, "task_id": "cgt-draft"}},
    )


def _usage(cost: str) -> UsageWrite:
    return UsageWrite(
        provider="seedance",
        model_id=MODEL,
        unit="second",
        input_tokens=0,
        output_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        cost_usd=Decimal(cost),
        paid_by="platform",
        pricing_table_version="v5",
        pieces=5,
    )


def _draft_with_video(repo: PostgresContentRepository) -> tuple[UUID, UUID, UUID]:
    brand_id = _brand(TENANT_F)
    draft_id = _drafting_draft(TENANT_F, brand_id)
    repo.finish_generation(
        tenant_id=TENANT_F,
        draft_id=draft_id,
        brand_id=brand_id,
        new_status="generated",
        failure_reason=None,
        variants=(_variant("hola"),),
        usage=(),
        spent_usd=Decimal("0"),
        media=(_video(TENANT_F, draft_id, "clip.mp4", DRAFT_READY),),
    )
    (asset,) = repo.media_for(tenant_id=TENANT_F, draft_id=draft_id)
    return brand_id, draft_id, asset.id


def _usage_rows(draft_id: UUID) -> list[creative.CreativeUsageEvent]:
    with tenant_session(TENANT_F) as session:
        return list(
            session.scalars(
                select(creative.CreativeUsageEvent).where(
                    creative.CreativeUsageEvent.draft_id == draft_id
                )
            )
        )


def test_the_final_replaces_the_draft_in_the_same_row() -> None:
    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo)

    repo.set_video_draft(tenant_id=TENANT_F, asset_id=asset_id, changes={"status": DRAFT_RENDERING})
    (asset,) = repo.media_for(tenant_id=TENANT_F, draft_id=draft_id)
    assert asset.params["draft"] == {"status": DRAFT_RENDERING, "task_id": "cgt-draft"}

    final = _video(TENANT_F, draft_id, "clip-final.mp4", "final")
    final = MediaWrite(**{**final.__dict__, "width": 1080, "height": 1920})
    repo.settle_final(
        tenant_id=TENANT_F,
        draft_id=draft_id,
        brand_id=brand_id,
        asset_id=asset_id,
        media=final,
        error=None,
        usage=(_usage("2.84"),),
        spent_usd=Decimal("2.84"),
    )

    (asset,) = repo.media_for(tenant_id=TENANT_F, draft_id=draft_id)
    assert asset.id == asset_id
    assert asset.object_key.endswith("clip-final.mp4")
    assert (asset.width, asset.height) == (1080, 1920)
    assert asset.params["draft"]["status"] == "final"
    assert [row.cost_usd for row in _usage_rows(draft_id)] == [Decimal("2.84")]
    with tenant_session(TENANT_F) as session:
        draft = session.get(creative.ContentDraft, draft_id)
        assert draft is not None and draft.preview_key == asset.object_key


def test_a_failed_final_keeps_the_draft_and_records_its_spend() -> None:
    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo)

    repo.settle_final(
        tenant_id=TENANT_F,
        draft_id=draft_id,
        brand_id=brand_id,
        asset_id=asset_id,
        media=None,
        error="ModelArk falló.",
        usage=(_usage("0.10"),),
        spent_usd=Decimal("0.10"),
    )

    (asset,) = repo.media_for(tenant_id=TENANT_F, draft_id=draft_id)
    assert asset.object_key.endswith("/clip.mp4")
    assert asset.params["draft"]["status"] == DRAFT_FAILED
    assert asset.params["draft"]["error"] == "ModelArk falló."
    assert len(_usage_rows(draft_id)) == 1


def test_a_final_is_claimed_once_per_order_and_settled_only_by_its_claim() -> None:
    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo)
    repo.set_video_draft(
        tenant_id=TENANT_F,
        asset_id=asset_id,
        changes={"status": DRAFT_RENDERING, "attempt": "a1", "claim": None},
    )

    assert not repo.claim_final(tenant_id=TENANT_F, asset_id=asset_id, attempt="a0", claim="x")
    assert repo.claim_final(tenant_id=TENANT_F, asset_id=asset_id, attempt="a1", claim="c1")
    assert not repo.claim_final(tenant_id=TENANT_F, asset_id=asset_id, attempt="a1", claim="c2")

    # ordered again meanwhile: the old claim's settle records its spend, writes nothing
    repo.set_video_draft(
        tenant_id=TENANT_F, asset_id=asset_id, changes={"attempt": "a2", "claim": None}
    )
    repo.settle_final(
        tenant_id=TENANT_F,
        draft_id=draft_id,
        brand_id=brand_id,
        asset_id=asset_id,
        media=None,
        error="tarde",
        usage=(_usage("2.84"),),
        spent_usd=Decimal("2.84"),
        claim="c1",
    )
    repo.fail_final(tenant_id=TENANT_F, asset_id=asset_id, claim="c1", error="tarde")
    (asset,) = repo.media_for(tenant_id=TENANT_F, draft_id=draft_id)
    assert asset.params["draft"]["status"] == DRAFT_RENDERING
    assert len(_usage_rows(draft_id)) == 1

    assert repo.claim_final(tenant_id=TENANT_F, asset_id=asset_id, attempt="a2", claim="c3")
    repo.fail_final(tenant_id=TENANT_F, asset_id=asset_id, claim="c3", error="ModelArk falló.")
    (asset,) = repo.media_for(tenant_id=TENANT_F, draft_id=draft_id)
    assert asset.params["draft"]["status"] == DRAFT_FAILED


def test_only_the_draft_videos_are_read_and_a_failure_keeps_the_raw_final() -> None:
    """Review 2026-10-23: approving reads the draft videos alone (`params ? 'draft'`),
    and a failed final keeps the paid raw file its retry reuses."""
    repo = PostgresContentRepository()
    brand_id = _brand(TENANT_F)
    draft_id = _drafting_draft(TENANT_F, brand_id)
    video = _video(TENANT_F, draft_id, "clip.mp4", DRAFT_READY)
    still = MediaWrite(
        **{
            **video.__dict__,
            "position": 1,
            "media_type": "image",
            "media_url": f"t/{TENANT_F}/generated/{draft_id}/r1/still.jpg",
            "object_key": f"t/{TENANT_F}/generated/{draft_id}/r1/still.jpg",
            "content_type": "image/jpeg",
            "params": {"resolution": "1080p"},
        }
    )
    repo.finish_generation(
        tenant_id=TENANT_F,
        draft_id=draft_id,
        brand_id=brand_id,
        new_status="generated",
        failure_reason=None,
        variants=(_variant("hola"),),
        usage=(),
        spent_usd=Decimal("0"),
        media=(video, still),
    )
    assert len(repo.media_for(tenant_id=TENANT_F, draft_id=draft_id)) == 2
    (asset,) = repo.draft_videos_for(tenant_id=TENANT_F, draft_id=draft_id)
    assert asset.object_key.endswith("/clip.mp4")

    raw = {"key": f"t/{TENANT_F}/generated/{draft_id}/r1/clip-final-raw.mp4", "cost_usd": "2.84"}
    repo.settle_final(
        tenant_id=TENANT_F,
        draft_id=draft_id,
        brand_id=brand_id,
        asset_id=asset.id,
        media=None,
        error="No se pudo recodificar.",
        usage=(_usage("2.84"),),
        spent_usd=Decimal("2.84"),
        draft_changes={"raw_final": raw},
    )
    (asset,) = repo.draft_videos_for(tenant_id=TENANT_F, draft_id=draft_id)
    assert asset.params["draft"]["status"] == DRAFT_FAILED
    assert asset.params["draft"]["raw_final"] == raw


# -- review round 4 (m-24820142) --------------------------------------------------------


def _approve(draft_id: UUID) -> None:
    """The draft approved with its one variant (the FSM's edge, written directly)."""
    from datetime import UTC, datetime

    with tenant_session(TENANT_F) as session:
        draft = session.get(creative.ContentDraft, draft_id)
        variant = session.scalars(
            select(creative.CopyVariant).where(creative.CopyVariant.draft_id == draft_id)
        ).one()
        assert draft is not None
        draft.status = "approved"
        draft.selected_variant_id = variant.id
        draft.approved_at = datetime.now(UTC)
        draft.approved_revision = draft.revision


def test_the_read_seam_holds_back_an_approved_piece_until_its_final_is_in_place() -> None:
    """Downstream modules read the Planificador's rule: a video still at its 480p draft
    is not the piece that will be published."""
    from qualify_api.creative.read import approved_creative, list_approved

    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo)
    _approve(draft_id)

    assert approved_creative(tenant_id=TENANT_F, draft_id=draft_id) is None
    listed = list_approved(tenant_id=TENANT_F, brand_id=brand_id)
    assert draft_id not in {a.draft_id for a in listed}

    final = _video(TENANT_F, draft_id, "clip-final.mp4", "final")
    repo.settle_final(
        tenant_id=TENANT_F,
        draft_id=draft_id,
        brand_id=brand_id,
        asset_id=asset_id,
        media=MediaWrite(**{**final.__dict__, "width": 1080, "height": 1920}),
        error=None,
        usage=(),
        spent_usd=Decimal("0"),
    )

    artifact = approved_creative(tenant_id=TENANT_F, draft_id=draft_id)
    assert artifact is not None and str(artifact.image_object_key).endswith("clip-final.mp4")
    listed = list_approved(tenant_id=TENANT_F, brand_id=brand_id)
    assert draft_id in {a.draft_id for a in listed}


def test_a_draft_merge_waits_for_a_concurrent_one_and_never_loses_it() -> None:
    """A stale run's raw-final record (`set_video_draft`) racing a new order: the merge
    takes the row lock, so it lands over the order's `attempt` instead of over a read
    taken before the order committed."""
    import threading
    import time

    repo = PostgresContentRepository()
    _, draft_id, asset_id = _draft_with_video(repo)
    locked, recorded = threading.Event(), threading.Event()

    def order() -> None:
        with tenant_session(TENANT_F) as session:
            row = session.get(creative.ImageAsset, asset_id, with_for_update=True)
            assert row is not None
            params = dict(row.params or {})
            params["draft"] = {**params["draft"], "status": DRAFT_RENDERING, "attempt": "a2"}
            row.params = params
            session.flush()
            locked.set()
            # hold the lock while the other merge starts; it must wait for this commit
            recorded.wait(timeout=1.0)
            time.sleep(0.3)

    thread = threading.Thread(target=order)
    thread.start()
    assert locked.wait(timeout=10)
    writer = threading.Thread(
        target=lambda: repo.set_video_draft(
            tenant_id=TENANT_F, asset_id=asset_id, changes={"raw_final": {"key": "k"}}
        )
    )
    writer.start()
    recorded.set()
    thread.join(timeout=10)
    writer.join(timeout=10)

    (asset,) = repo.media_for(tenant_id=TENANT_F, draft_id=draft_id)
    block = asset.params["draft"]
    assert block["status"] == DRAFT_RENDERING and block["attempt"] == "a2"
    assert block["raw_final"] == {"key": "k"}
