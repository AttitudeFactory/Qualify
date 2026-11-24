"""`db`-marked test for a Seedance 2.5 final (m-24820142) against the real schema: the
draft block is merged into the video's JSONB, and the final replaces the draft IN THE
SAME ROW (every reader keeps reading the piece's one video), with its spend recorded —
also when it failed."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative import models as creative
from qualify_api.creative.draft_mode import (
    DRAFT_FAILED,
    DRAFT_READY,
    DRAFT_RENDERING,
    FINAL_USAGE_DUE,
)
from qualify_api.creative.media import MediaWrite
from qualify_api.creative.service import PostgresContentRepository, UsageWrite
from qualify_api.tenancy.models import Brand

from .test_creative_regenerate_db import _brand, _drafting_draft, _variant

pytestmark = pytest.mark.db

TENANT_F = UUID("c0000000-0000-4000-8000-000000001020")
#: m-25111780: the tests that read a budget get their own tenant (one brand each, with
#: its config row): `_brand` picks ANY brand of a tenant, so none of them sits in TENANT_F.
TENANT_G = UUID("c0000000-0000-4000-8000-000000001021")
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


def _draft_with_video(
    repo: PostgresContentRepository, brand_id: UUID | None = None, tenant_id: UUID = TENANT_F
) -> tuple[UUID, UUID, UUID]:
    brand_id = brand_id or _brand(tenant_id)
    draft_id = _drafting_draft(tenant_id, brand_id)
    repo.finish_generation(
        tenant_id=tenant_id,
        draft_id=draft_id,
        brand_id=brand_id,
        new_status="generated",
        failure_reason=None,
        variants=(_variant("hola"),),
        usage=(),
        spent_usd=Decimal("0"),
        media=(_video(tenant_id, draft_id, "clip.mp4", DRAFT_READY),),
    )
    (asset,) = repo.media_for(tenant_id=tenant_id, draft_id=draft_id)
    return brand_id, draft_id, asset.id


def _usage_rows(draft_id: UUID, tenant_id: UUID = TENANT_F) -> list[creative.CreativeUsageEvent]:
    with tenant_session(tenant_id) as session:
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


def _budgeted_brand() -> UUID:
    """A brand of its own for one test, with its budget config row. The app role may not
    delete `creative_engine_config` rows (by design), so the brand this file shares is
    never given one: a cap on it would outlive the test."""
    _brand(TENANT_G)  # the tenant itself, made once
    with admin_session() as session:
        brand = Brand(tenant_id=TENANT_G, name=f"final-usage-{uuid4().hex[:8]}")
        session.add(brand)
        session.flush()
        brand_id = brand.id
    with tenant_session(TENANT_G) as session:
        session.add(
            creative.CreativeEngineConfig(
                tenant_id=TENANT_G,
                brand_id=brand_id,
                monthly_budget_cap_usd=Decimal("100"),
                budget_spent_usd=Decimal("0"),
            )
        )
    return brand_id


def _budget(brand_id: UUID) -> Decimal:
    """The brand's spent budget (`_budgeted_brand`)."""
    with tenant_session(TENANT_G) as session:
        return Decimal(
            session.scalars(
                select(creative.CreativeEngineConfig.budget_spent_usd).where(
                    creative.CreativeEngineConfig.brand_id == brand_id
                )
            ).one()
        )


def _held_final(draft_id: UUID, raw: dict[str, str], tenant_id: UUID = TENANT_F) -> MediaWrite:
    final = _video(tenant_id, draft_id, "clip-final.mp4", "final")
    block = {**final.params["draft"], "raw_final": raw, FINAL_USAGE_DUE: raw["task_id"]}
    return MediaWrite(**{**final.__dict__, "params": {**final.params, "draft": block}})


def _raw(draft_id: UUID, task: str, tenant_id: UUID = TENANT_F) -> dict[str, str]:
    key = f"t/{tenant_id}/generated/{draft_id}/r1/clip-final-raw-{task}.mp4"
    return {"key": key, "task_id": task, "cost_usd": "2.84"}


def test_a_held_raw_final_spend_is_recorded_once_while_its_task_is_due() -> None:
    """m-25111780: the pass that paid the 1080p lost its lease (its settle rolled back);
    the raw file stayed in the block marked due. The next settle records its spend once
    — event and budget — and clears the mark in the same write; a later settle of the
    same task adds none."""
    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo, _budgeted_brand(), TENANT_G)
    spent = _budget(brand_id)
    raw = _raw(draft_id, "cgt-final", TENANT_G)
    repo.set_video_draft(
        tenant_id=TENANT_G,
        asset_id=asset_id,
        changes={"status": DRAFT_RENDERING, "raw_final": raw, FINAL_USAGE_DUE: "cgt-final"},
    )

    def settle() -> None:
        repo.settle_final(
            tenant_id=TENANT_G,
            draft_id=draft_id,
            brand_id=brand_id,
            asset_id=asset_id,
            media=_held_final(draft_id, raw, TENANT_G),
            error=None,
            usage=(),
            spent_usd=Decimal("0"),
            draft_changes={"raw_final": raw},
            held_usage=(_usage("2.84"),),
            final_task_id="cgt-final",
        )

    settle()
    (asset,) = repo.media_for(tenant_id=TENANT_G, draft_id=draft_id)
    assert asset.params["draft"]["status"] == "final"
    assert FINAL_USAGE_DUE not in asset.params["draft"]
    assert [row.cost_usd for row in _usage_rows(draft_id, TENANT_G)] == [Decimal("2.84")]
    assert _budget(brand_id) - spent == Decimal("2.84")

    settle()  # a slower pass with the same kept file: nothing more
    (asset,) = repo.media_for(tenant_id=TENANT_G, draft_id=draft_id)
    assert FINAL_USAGE_DUE not in asset.params["draft"]
    assert len(_usage_rows(draft_id, TENANT_G)) == 1
    assert _budget(brand_id) - spent == Decimal("2.84")


def test_a_late_settle_that_lost_its_claim_records_its_raw_spend_once() -> None:
    """Review of 4160220e: run A paid T1 and lost its claim to a new order. If A settles
    while T1 is still due, A records it and clears the mark; if the new run recorded T1
    first (no mark, `raw_final` naming T1), A records nothing more."""
    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo, _budgeted_brand(), TENANT_G)
    spent = _budget(brand_id)
    raw = _raw(draft_id, "cgt-a", TENANT_G)

    def late_a() -> None:
        repo.settle_final(
            tenant_id=TENANT_G,
            draft_id=draft_id,
            brand_id=brand_id,
            asset_id=asset_id,
            media=_held_final(draft_id, raw, TENANT_G),
            error=None,
            usage=(),
            spent_usd=Decimal("2.84"),
            claim="claim-a",
            draft_changes={"raw_final": raw},
            final_task_id="cgt-a",
            raw_usage=(_usage("2.84"),),
        )

    # ordered again: claim gone, T1 still due — A records it and clears the mark
    repo.set_video_draft(
        tenant_id=TENANT_G,
        asset_id=asset_id,
        changes={
            "status": DRAFT_RENDERING,
            "claim": None,
            "raw_final": raw,
            FINAL_USAGE_DUE: "cgt-a",
        },
    )
    late_a()
    (asset,) = repo.media_for(tenant_id=TENANT_G, draft_id=draft_id)
    assert asset.params["draft"]["status"] == DRAFT_RENDERING  # not A's to write
    assert FINAL_USAGE_DUE not in asset.params["draft"]
    assert len(_usage_rows(draft_id, TENANT_G)) == 1 and _budget(brand_id) - spent == Decimal(
        "2.84"
    )

    # A again, as if the new run had recorded T1 first: nothing more, budget unchanged
    late_a()
    assert len(_usage_rows(draft_id, TENANT_G)) == 1 and _budget(brand_id) - spent == Decimal(
        "2.84"
    )


def test_a_mark_naming_another_task_is_kept() -> None:
    """The settle of task T2 never touches a mark naming another task."""
    repo = PostgresContentRepository()
    brand_id, draft_id, asset_id = _draft_with_video(repo)
    repo.set_video_draft(
        tenant_id=TENANT_F,
        asset_id=asset_id,
        changes={"status": DRAFT_RENDERING, FINAL_USAGE_DUE: "cgt-other"},
    )
    raw = _raw(draft_id, "cgt-two")
    repo.settle_final(
        tenant_id=TENANT_F,
        draft_id=draft_id,
        brand_id=brand_id,
        asset_id=asset_id,
        media=None,
        error="No se pudo recodificar.",
        usage=(),
        spent_usd=Decimal("0"),
        draft_changes={"raw_final": raw},
        held_usage=(_usage("2.84"),),
        final_task_id="cgt-two",
    )
    (asset,) = repo.media_for(tenant_id=TENANT_F, draft_id=draft_id)
    assert asset.params["draft"][FINAL_USAGE_DUE] == "cgt-other"
    assert asset.params["draft"]["raw_final"] == raw
    assert _usage_rows(draft_id) == []


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
    """The final remains gated until an approver confirms the exact viewed object."""
    from uuid import uuid4

    from qualify_shared.db.admin import admin_session

    from qualify_api.creative.final_review import confirm_final, review_manifest
    from qualify_api.creative.read import approved_creative, list_approved
    from qualify_api.tenancy.models import TenantMember, User

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

    # A legacy final with no human confirmation is still withheld from every consumer.
    assert approved_creative(tenant_id=TENANT_F, draft_id=draft_id) is None
    assert draft_id not in {
        item.draft_id for item in list_approved(tenant_id=TENANT_F, brand_id=brand_id)
    }
    owner = uuid4()
    with admin_session() as session:
        session.add(
            User(
                id=owner,
                tenant_id=TENANT_F,
                email=f"final-review-{owner}@example.invalid",
                display_name="Test",
            )
        )
        session.flush()
        session.add(TenantMember(tenant_id=TENANT_F, user_id=owner, role="owner"))
    manifest = review_manifest(
        tenant_id=TENANT_F,
        draft_id=draft_id,
        user_id=owner,
        read_object=lambda key: b"exact final fixture bytes",
    )
    assert approved_creative(tenant_id=TENANT_F, draft_id=draft_id) is None
    confirm_final(tenant_id=TENANT_F, draft_id=draft_id, user_id=owner, expected=manifest)

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
