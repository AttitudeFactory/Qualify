"""m-25112920 against Postgres: an avatar block is a child of its Clip in a slot of
migration 0119 (no migration of its own); the store finds the blocks, their kept video
and the stretches that are blocks' videos — never another business's (RLS); and a block
settling opens no `join` on its Clip (only a video by parts joins). No vendor is called."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import ContentBrief, MediaInputs, SourceSegment
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

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
    sources = store.block_sources(tenant_id=tenant, keys=[key, owned])
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
    assert store.block_sources(tenant_id=other, keys=[key]) == {}


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
