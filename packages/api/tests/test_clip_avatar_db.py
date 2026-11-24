"""m-25112920 against Postgres: an avatar block is a child of its Clip in a slot of
migration 0119 (no migration of its own); the store finds the blocks, their kept video
and the stretches that are blocks' videos — never another business's (RLS); and a block
settling opens no `join` on its Clip (only a video by parts joins). No vendor is called."""

from __future__ import annotations

import os
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import ContentBrief, MediaInputs, SourceSegment
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text

from qualify_api.creative import clip_avatar as ca
from qualify_api.creative import models as orm
from qualify_api.creative.parts import mark_parent_dirty
from qualify_api.creative.service import PostgresContentRepository

from . import test_content_service as base

pytestmark = pytest.mark.db


def _business(monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, UUID, UUID]:
    monkeypatch.setattr(base, "DB_TENANT", uuid4())
    return base.seed_db_tenant()


def _clip(brand: UUID, tenant: UUID) -> ContentBrief:
    return ContentBrief.model_validate(
        {
            "brand_id": brand,
            "objective": "sale",
            "topic": "arepa de chócolo",
            "image_route": "from_upload",
            "source_media_key": f"uploads/{tenant}/a.mp4",
            "kind": ContentKind.CLIP,
            "format": ContentFormat.REELS_9_16,
            "variants_requested": 1,
            "media": MediaInputs(
                clip_reference_mode="local",
                segments=(
                    SourceSegment(key=f"uploads/{tenant}/a.mp4", start_s=0, end_s=4, speed=1),
                ),
            ),
        }
    )


def _world(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    tenant, brand, user = _business(monkeypatch)
    repo = PostgresContentRepository()
    clip_brief = _clip(brand, tenant)
    clip = repo.insert_brief_and_draft(
        tenant_id=tenant,
        user_id=user,
        brief=clip_brief,
        voice_profile_version=1,
        pipeline_version="creative-v1",
    )
    request = ca.AvatarBlockRequest(
        kind="presenter", script="Hola, soy Ana.", avatar_prompt="Mujer sonriente"
    )
    block = repo.insert_brief_and_draft(
        tenant_id=tenant,
        user_id=user,
        brief=ca.block_brief(clip_brief, request),
        voice_profile_version=1,
        pipeline_version="creative-v1",
        parent_draft_id=clip,
        part_index=1,
    )
    key = f"t/{tenant}/generated/{block}/r1/video.mp4"
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'generated' WHERE id IN (:c, :b)"),
            {"c": clip, "b": block},
        )
        session.add(
            orm.ImageAsset(
                tenant_id=tenant,
                draft_id=block,
                media_url=key,
                object_key=key,
                media_type="video",
                provider="omnihuman",
                model_id="omnihuman-1.5",
                params={"duration_seconds": 4.2, "model_revision": "omni15"},
            )
        )
    return {"tenant": tenant, "user": user, "clip": clip, "block": block, "key": key}


def test_the_store_finds_the_block_its_video_and_its_stretch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    tenant, clip, block, key = world["tenant"], world["clip"], world["block"], world["key"]
    store = ca.PostgresClipAvatarStore()
    row = store.clip(tenant_id=tenant, clip_id=clip)
    assert row is not None and row.status == "generated" and row.parent_draft_id is None
    (found,) = store.blocks_of(tenant_id=tenant, clip_id=clip)
    assert (found.id, found.slot, found.kind, found.removed) == (block, 1, "presenter", False)
    video = store.block_video(tenant_id=tenant, block_id=block)
    assert video is not None and video.object_key == key and video.seconds == 4.2
    owned = f"uploads/{tenant}/a.mp4"
    sources = store.generated_sources(tenant_id=tenant, keys=[key, owned])
    assert list(sources) == [key]
    source = sources[key]
    assert source.block_id == block and source.clip_id == clip
    assert (source.provider, source.model_id, source.model_revision) == (
        "omnihuman",
        "omnihuman-1.5",
        "omni15",
    )
    # another business sees nothing of it (RLS)
    other = uuid4()
    assert store.clip(tenant_id=other, clip_id=clip) is None
    assert store.blocks_of(tenant_id=other, clip_id=clip) == ()
    assert store.generated_sources(tenant_id=other, keys=[key]) == {}
    assert source.block is True and source.ai_generated is True


def test_a_seedance_piece_reads_as_ai_and_an_own_composition_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The label's evidence as Postgres keeps it: a Seedance clip's asset is AI by its
    provider; our composition of the owner's photos (provider `qualify`, a draft that
    needs no disclosure) is not; neither is a block."""
    world = _world(monkeypatch)
    tenant, user = world["tenant"], world["user"]
    repo = PostgresContentRepository()
    made: dict[str, str] = {}
    for name, provider in (("seedance", "seedance"), ("own", "qualify")):
        draft = repo.insert_brief_and_draft(
            tenant_id=tenant,
            user_id=user,
            brief=_clip(_brand_of(tenant, world["clip"]), tenant),
            voice_profile_version=1,
            pipeline_version="creative-v1",
        )
        key = f"t/{tenant}/generated/{draft}/r1/video.mp4"
        with tenant_session(tenant) as session:
            session.execute(
                text("UPDATE content_drafts SET requires_ai_disclosure = false WHERE id = :d"),
                {"d": draft},
            )
            session.add(
                orm.ImageAsset(
                    tenant_id=tenant,
                    draft_id=draft,
                    media_url=key,
                    object_key=key,
                    media_type="video",
                    provider=provider,
                    model_id=f"{provider}-model",
                    params={"duration_seconds": 4.0},
                )
            )
        made[name] = key
    sources = ca.PostgresClipAvatarStore().generated_sources(
        tenant_id=tenant, keys=list(made.values())
    )
    seedance, own = sources[made["seedance"]], sources[made["own"]]
    assert (seedance.ai_generated, seedance.block) == (True, False)
    assert (own.ai_generated, own.block) == (False, False)


def _brand_of(tenant: UUID, draft: UUID) -> UUID:
    with tenant_session(tenant) as session:
        return session.scalar(
            text("SELECT brand_id FROM content_drafts WHERE id = :d"), {"d": draft}
        )


def test_the_slot_is_unique_under_the_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import IntegrityError

    world = _world(monkeypatch)
    repo = PostgresContentRepository()
    with tenant_session(world["tenant"]) as session:
        brief_id = session.scalar(
            text("SELECT brief_id FROM content_drafts WHERE id = :b"), {"b": world["block"]}
        )
    brief = repo.get_brief(tenant_id=world["tenant"], brief_id=brief_id)
    assert brief is not None and brief.media.clip_avatar_block
    with pytest.raises(IntegrityError):
        repo.insert_brief_and_draft(
            tenant_id=world["tenant"],
            user_id=world["user"],
            brief=brief,
            voice_profile_version=1,
            pipeline_version="creative-v1",
            parent_draft_id=world["clip"],
            part_index=1,
        )


def test_a_block_settling_opens_no_join_on_its_clip(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(monkeypatch)
    with tenant_session(world["tenant"]) as session:
        mark_parent_dirty(session, world["block"])
        runs = session.scalar(
            text("SELECT count(*) FROM creative_pipeline_runs WHERE draft_id = :c"),
            {"c": world["clip"]},
        )
    assert runs == 0


# ---------------------------------------------------------------------------
# review of 9ffa7eee: the queue finds the block's reservation; Deivid 2026-11-24: the
# daily cap of 3 blocks per business, counted by Postgres


def _service(env: dict[str, str]) -> tuple[ca.ClipAvatarService, Any]:
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.router import CreativeRouter

    from qualify_api.creative.composition import DbBrandKitReader, DbVoiceProfileReader
    from qualify_api.creative.creations import PostgresCreationsLedger
    from qualify_api.creative.queue_dispatch import QueueDispatcher
    from qualify_api.creative.service import ContentService

    pricing = JsonPricingTable("v1")
    content = ContentService(
        router=CreativeRouter(
            {"anthropic": base.FakeCopyAdapter()}, pricing, base.StaticKeyResolver()
        ),
        pricing=pricing,
        credentials=base.StaticKeyResolver(),
        brand_service=DbBrandKitReader(),
        voice_service=DbVoiceProfileReader(),
        creations=PostgresCreationsLedger(),
    )
    content.dispatcher = QueueDispatcher(content.repository, pricing_version=pricing.version)
    return ca.ClipAvatarService(content, env=env), content


def _request() -> ca.AvatarBlockRequest:
    return ca.AvatarBlockRequest(
        kind="presenter", script="Hola, soy Ana.", avatar_prompt="Mujer sonriente"
    )


def test_the_queue_finds_a_blocks_reservation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of 9ffa7eee (blocking): without its charge row the queue refused every
    block («generation reservation is no longer active») after Seedream and Seed Speech
    were paid. The job is claimed as the worker claims it and goes through the real
    `PipelineExecutor._validate_reservation`. No vendor is called."""
    from qualify_api.creative.worker.executor import JobContext
    from qualify_api.creative.worker.pipeline import PipelineExecutor

    world = _world(monkeypatch)
    tenant = world["tenant"]
    service, content = _service({ca.PRESENTER_SWITCH: "on"})
    block = service.create_block(
        tenant_id=tenant, user_id=world["user"], clip_id=world["clip"], request=_request()
    )
    # claimed as the worker claims it (setup only: the table's owner, as the queue tests)
    owner = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    with owner.begin() as connection:
        job = connection.execute(
            text("""
            UPDATE creative_jobs SET status = 'claimed', claim_token = 7,
                claimed_by = 'test-worker', lease_until = now() + interval '5 minutes'
            WHERE draft_id = :b RETURNING id, kind, revision, position, vendor_model, charge_id
        """),
            {"b": block},
        ).one()
    owner.dispose()
    with tenant_session(tenant) as session:
        charge = session.execute(
            text("SELECT status, request_kind, weight FROM creation_charges WHERE id = :c"),
            {"c": job.charge_id},
        ).one()
    assert (charge.status, charge.request_kind, charge.weight) == (
        "charged",
        "clip_avatar_block",
        0,
    )
    context = JobContext(
        job_id=job.id,
        tenant_id=tenant,
        draft_id=block,
        kind=job.kind,
        revision=job.revision,
        position=job.position,
        vendor_model=job.vendor_model,
        lane="now",
        vendor_priority=0,
        deadline=None,
        claim_token=7,
    )
    executor = PipelineExecutor(content, None, None, "omnihuman")
    executor._validate_reservation(context)
    # the control: what 9ffa7eee left (no charge row) is refused by the same check
    owner = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    with owner.begin() as connection:
        connection.execute(
            text("UPDATE creative_jobs SET charge_id = NULL WHERE id = :j"), {"j": job.id}
        )
    owner.dispose()
    with pytest.raises(ValueError, match="reservation is no longer active"):
        executor._validate_reservation(context)


def test_the_daily_cap_is_three_blocks_of_the_business_own_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)  # its block was made today: it counts
    tenant, user, clip = world["tenant"], world["user"], world["clip"]
    service, _ = _service({ca.PRESENTER_SWITCH: "on"})
    store = ca.PostgresClipAvatarStore()
    assert store.blocks_made_today(tenant_id=tenant) == 1
    for _ in range(ca.AVATAR_DAILY_CAP - 1):
        service.create_block(tenant_id=tenant, user_id=user, clip_id=clip, request=_request())
    with tenant_session(tenant) as session:
        jobs_before = session.scalar(text("SELECT count(*) FROM creative_jobs"))
    with pytest.raises(ca.AvatarDailyCapReached):
        service.create_block(tenant_id=tenant, user_id=user, clip_id=clip, request=_request())
    with tenant_session(tenant) as session:
        assert session.scalar(text("SELECT count(*) FROM creative_jobs")) == jobs_before
        # one that failed before anything was paid (no usage with a cost) frees its place
        session.execute(
            text("UPDATE content_drafts SET status = 'failed' WHERE id = :b"),
            {"b": world["block"]},
        )
    assert store.blocks_made_today(tenant_id=tenant) == ca.AVATAR_DAILY_CAP - 1
    service.create_block(tenant_id=tenant, user_id=user, clip_id=clip, request=_request())
    assert store.blocks_made_today(tenant_id=tenant) == ca.AVATAR_DAILY_CAP
    # another business is not affected
    other_world = _world(monkeypatch)
    assert store.blocks_made_today(tenant_id=other_world["tenant"]) == 1
    # the business's next day frees the cap
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE content_drafts SET created_at = created_at - interval '1 day' "
                "WHERE parent_draft_id = :c"
            ),
            {"c": clip},
        )
    assert store.blocks_made_today(tenant_id=tenant) == 0


def test_pending_seconds_are_the_brands_uncharged_live_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    store = ca.PostgresClipAvatarStore()
    with tenant_session(world["tenant"]) as session:
        brand = session.scalar(
            text("SELECT brand_id FROM content_drafts WHERE id = :c"), {"c": world["clip"]}
        )
    assert store.pending_block_seconds(tenant_id=world["tenant"], brand_id=brand) == (
        1,
        ca.script_seconds("Hola, soy Ana."),
    )
    with tenant_session(world["tenant"]) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'failed' WHERE id = :b"),
            {"b": world["block"]},
        )
    assert store.pending_block_seconds(tenant_id=world["tenant"], brand_id=brand) == (0, 0)
