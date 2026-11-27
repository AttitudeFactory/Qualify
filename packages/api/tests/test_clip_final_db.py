"""m-25129408 against Postgres: approving a Clip with a character scene charges the
scene's seconds once on its own row, marks the Clip's video pending, orders the scene's
final and opens the Clip's `clip_final` run — under the Clip's row lock, never twice; the
store saves the final only while the Clip still waits for it, and only for its business
(RLS). No vendor is called."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import character_scene as cs
from qualify_api.creative import clip_final as cf
from qualify_api.creative.media import MediaWrite
from qualify_api.creative.service import PostgresContentRepository, VariantWrite

from . import test_character_scene_db as scenes_db
from . import test_content_service as base

pytestmark = pytest.mark.db


class Dispatcher:
    def __init__(self) -> None:
        self.finals: list[UUID] = []
        self.generations: list[UUID] = []

    def dispatch_generation(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        self.generations.append(draft_id)

    def dispatch_finalize(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        self.finals.append(draft_id)


def _variant() -> VariantWrite:
    return VariantWrite(
        ordinal=0,
        copy={"hook": "", "caption": "Pruébala hoy", "script": ""},
        fidelity={"passed": True, "hard_failures": []},
        model_id="none",
        model_revision=None,
    )


def _video(key: str, params: dict[str, Any]) -> MediaWrite:
    return MediaWrite(
        position=0,
        media_type="video",
        media_url=key,
        object_key=key,
        width=480,
        height=854,
        aspect_ratio="9:16",
        model_id="m",
        provider="seedance",
        ai_generated=True,
        params=params,
    )


def _made(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A Clip with ONE scene, both made: the scene's 480p draft and the Clip's video
    that laid it."""
    tenant, brand, user = scenes_db._business(monkeypatch)
    repo = PostgresContentRepository()
    item = scenes_db._item(tenant, 0.0, 6)
    clip_brief = scenes_db._clip(brand, tenant, item)
    clip = repo.insert_brief_and_draft(
        tenant_id=tenant,
        user_id=user,
        brief=clip_brief,
        voice_profile_version=1,
        pipeline_version="creative-v1",
    )
    scene = repo.insert_brief_and_draft(
        tenant_id=tenant,
        user_id=user,
        brief=cs.scene_brief(clip_brief, item),
        voice_profile_version=1,
        pipeline_version="creative-v1",
        parent_draft_id=clip,
        part_index=1,
    )
    scene_key = f"t/{tenant}/generated/{scene}/r1/scene.mp4"
    draft = {
        "status": "draft",
        "task_id": "cgt-draft",
        "created_at": time.time(),
        "model": cs.SCENE_MODEL,
        "duration_seconds": 6,
        "finish": "video",
    }
    repo.finish_generation(
        tenant_id=tenant,
        draft_id=scene,
        brand_id=brand,
        new_status="generated",
        failure_reason=None,
        variants=(_variant(),),
        usage=(),
        spent_usd=Decimal(0),
        media=(_video(scene_key, {"draft": draft}),),
    )
    (scene_asset,) = repo.draft_videos_for(tenant_id=tenant, draft_id=scene)
    clip_key = f"t/{tenant}/generated/{clip}/r1/local.mp4"
    laid = {"character_scenes": [{"draft_id": str(scene), "asset_id": str(scene_asset.id)}]}
    repo.finish_generation(
        tenant_id=tenant,
        draft_id=clip,
        brand_id=brand,
        new_status="generated",
        failure_reason=None,
        variants=(_variant(),),
        usage=(),
        spent_usd=Decimal(0),
        media=(_video(clip_key, {"local": laid}),),
    )
    return {
        "tenant": tenant,
        "brand": brand,
        "user": user,
        "clip": clip,
        "scene": scene,
        "scene_asset": scene_asset.id,
        "clip_key": clip_key,
        "repo": repo,
    }


def _service(dispatcher: Dispatcher) -> Any:
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.router import CreativeRouter

    from qualify_api.creative.composition import DbBrandKitReader, DbVoiceProfileReader
    from qualify_api.creative.creations import PostgresCreationsLedger
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
    content.dispatcher = dispatcher
    return content


def _charges(tenant: UUID, draft: UUID) -> list[Any]:
    with tenant_session(tenant) as session:
        return list(
            session.execute(
                text("""
                SELECT revision, videos, video_seconds, videos_charged_at
                FROM creation_charges WHERE draft_id = :d ORDER BY revision
            """),
                {"d": draft},
            ).all()
        )


def _runs(tenant: UUID, clip: UUID) -> list[Any]:
    with tenant_session(tenant) as session:
        return list(
            session.execute(
                text("""
                SELECT phase, revision, dirty_version FROM creative_pipeline_runs
                WHERE draft_id = :c ORDER BY phase
            """),
                {"c": clip},
            ).all()
        )


def test_approving_charges_the_scene_once_and_opens_the_clips_final(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _made(monkeypatch)
    tenant, clip, scene = world["tenant"], world["clip"], world["scene"]
    dispatcher = Dispatcher()
    content = _service(dispatcher)
    (variant,) = world["repo"].variants_for(tenant_id=tenant, draft_id=clip)
    content.approve(tenant_id=tenant, draft_id=clip, variant_id=variant.id, user_id=world["user"])
    repo = world["repo"]
    assert repo.get_draft(tenant_id=tenant, draft_id=clip).status == "approved"
    assert repo.get_draft(tenant_id=tenant, draft_id=scene).status == "approved"
    (charged,) = [row for row in _charges(tenant, scene) if row.videos > 0]
    assert charged.revision == 1 and charged.videos == 1
    (asset,) = repo.draft_videos_for(tenant_id=tenant, draft_id=scene)
    assert asset.params["draft"]["status"] in ("rendering", "final_scheduled")
    assert asset.params["draft"]["charge_revision"] == 1
    assert dispatcher.finals == [scene]
    (video,) = [
        m for m in repo.media_for(tenant_id=tenant, draft_id=clip) if m.media_type == "video"
    ]
    assert video.params["draft"]["status"] == cf.CLIP_FINAL_PENDING
    assert [(r.phase, r.revision) for r in _runs(tenant, clip)] == [(cf.CLIP_FINAL_PHASE, 1)]
    # twice: nothing more charged nor ordered
    content.approve(tenant_id=tenant, draft_id=clip, variant_id=variant.id, user_id=world["user"])
    assert [row for row in _charges(tenant, scene) if row.videos > 0] == [charged]
    assert dispatcher.finals == [scene]


def test_a_childs_kept_final_reopens_its_clips_run(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _made(monkeypatch)
    tenant, clip, scene = world["tenant"], world["clip"], world["scene"]
    content = _service(Dispatcher())
    (variant,) = world["repo"].variants_for(tenant_id=tenant, draft_id=clip)
    content.approve(tenant_id=tenant, draft_id=clip, variant_id=variant.id, user_id=world["user"])
    (before,) = _runs(tenant, clip)
    with tenant_session(tenant) as session:
        assert cf.clip_parent_of(session, scene) == clip
        assert cf.clip_parent_of(session, clip) is None
        assert cf.open_clip_final(session, clip) is True
    (after,) = _runs(tenant, clip)
    assert after.dirty_version == before.dirty_version + 1
    # another business sees nothing of it (RLS)
    other, _, _ = scenes_db._business(monkeypatch)
    with tenant_session(other) as session:
        assert cf.clip_parent_of(session, scene) is None
        assert cf.open_clip_final(session, clip) is False


def test_the_store_saves_the_final_only_while_the_clip_waits_for_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _made(monkeypatch)
    tenant, clip = world["tenant"], world["clip"]
    content = _service(Dispatcher())
    (variant,) = world["repo"].variants_for(tenant_id=tenant, draft_id=clip)
    content.approve(tenant_id=tenant, draft_id=clip, variant_id=variant.id, user_id=world["user"])
    repo = world["repo"]
    (video,) = [
        m for m in repo.media_for(tenant_id=tenant, draft_id=clip) if m.media_type == "video"
    ]
    final_key = f"t/{tenant}/generated/{clip}/r1/final-local.mp4"
    write = cf.final_write(
        _video(final_key, {"local": {}}),
        block=video.params["draft"],
        preview=video,
        revision=1,
        digest="a" * 64,
        finals=(),
    )
    store = cf.PostgresClipFinalStore()
    # another revision: never
    assert not store.save(
        tenant_id=tenant, clip_id=clip, asset_id=video.id, revision=2, write=write
    )
    assert store.save(tenant_id=tenant, clip_id=clip, asset_id=video.id, revision=1, write=write)
    (saved,) = [
        m for m in repo.media_for(tenant_id=tenant, draft_id=clip) if m.media_type == "video"
    ]
    assert saved.object_key == final_key
    assert saved.params["draft"]["status"] == "final_ready"
    assert saved.params["clip_final"]["preview_object_key"] == world["clip_key"]
    # once: the block no longer waits
    assert not store.save(
        tenant_id=tenant, clip_id=clip, asset_id=video.id, revision=1, write=write
    )
    assert not store.fail(tenant_id=tenant, clip_id=clip, asset_id=video.id, error="x")


def test_a_failed_assembly_is_marked_and_the_preview_stays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _made(monkeypatch)
    tenant, clip = world["tenant"], world["clip"]
    content = _service(Dispatcher())
    (variant,) = world["repo"].variants_for(tenant_id=tenant, draft_id=clip)
    content.approve(tenant_id=tenant, draft_id=clip, variant_id=variant.id, user_id=world["user"])
    repo = world["repo"]
    (video,) = [
        m for m in repo.media_for(tenant_id=tenant, draft_id=clip) if m.media_type == "video"
    ]
    store = cf.PostgresClipFinalStore()
    assert store.fail(
        tenant_id=tenant, clip_id=clip, asset_id=video.id, error=cf.CLIP_FINAL_FAILED_TEXT
    )
    (after,) = [
        m for m in repo.media_for(tenant_id=tenant, draft_id=clip) if m.media_type == "video"
    ]
    assert after.object_key == world["clip_key"]
    assert after.params["draft"]["status"] == cf.CLIP_FINAL_FAILED
    assert after.params["draft"]["error"] == cf.CLIP_FINAL_FAILED_TEXT
