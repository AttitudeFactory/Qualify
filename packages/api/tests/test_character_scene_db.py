"""m-25128784 against Postgres: a character scene is a child draft of its Clip of kind
`character_scene` (migration 0188 widens `ck_content_briefs_kind`), it counts in the
business's daily cap with the avatar blocks, and the store finds the Clip's scenes and
the seconds still owed — never another business's (RLS). No vendor is called."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import (
    CharacterSceneBackground,
    CharacterSceneItem,
    CharacterSceneProduct,
    ContentBrief,
    MediaInputs,
    SourceSegment,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import character_scene as cs
from qualify_api.creative.clip_avatar import PostgresClipAvatarStore
from qualify_api.creative.service import PostgresContentRepository

from . import test_content_service as base

pytestmark = pytest.mark.db


def _business(monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, UUID, UUID]:
    monkeypatch.setattr(base, "DB_TENANT", uuid4())
    return base.seed_db_tenant()


def _item(tenant: UUID, start: float, duration: int = 5) -> CharacterSceneItem:
    return CharacterSceneItem(
        character_id=uuid4(),
        product=CharacterSceneProduct(product_id=uuid4(), photo_key=f"uploads/{tenant}/p.jpg"),
        background=CharacterSceneBackground(key=f"uploads/{tenant}/l.jpg"),
        line="¡Mira esto!",
        start=start,
        duration=duration,
    )


def _clip(brand: UUID, tenant: UUID, *scenes: CharacterSceneItem) -> ContentBrief:
    return ContentBrief.model_validate(
        {
            "brand_id": brand,
            "objective": "sale",
            "topic": "super smash",
            "image_route": "from_upload",
            "source_media_key": f"uploads/{tenant}/a.mp4",
            "kind": ContentKind.CLIP,
            "format": ContentFormat.REELS_9_16,
            "variants_requested": 1,
            "media": MediaInputs(
                clip_reference_mode="local",
                segments=(
                    SourceSegment(key=f"uploads/{tenant}/a.mp4", start_s=0, end_s=20, speed=1),
                ),
                character_scenes=scenes,
            ),
        }
    )


def _world(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    tenant, brand, user = _business(monkeypatch)
    repo = PostgresContentRepository()
    scenes = (_item(tenant, 0.0), _item(tenant, 10.0, 8))
    clip_brief = _clip(brand, tenant, *scenes)
    clip = repo.insert_brief_and_draft(
        tenant_id=tenant,
        user_id=user,
        brief=clip_brief,
        voice_profile_version=1,
        pipeline_version="creative-v1",
    )
    made = [
        repo.insert_brief_and_draft(
            tenant_id=tenant,
            user_id=user,
            brief=cs.scene_brief(clip_brief, item),
            voice_profile_version=1,
            pipeline_version="creative-v1",
            parent_draft_id=clip,
            part_index=slot,
        )
        for slot, item in enumerate(scenes, 1)
    ]
    return {"tenant": tenant, "brand": brand, "clip": clip, "scenes": made}


def test_a_scene_is_a_child_of_its_clip_of_its_own_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world(monkeypatch)
    tenant = world["tenant"]
    with tenant_session(tenant) as session:
        kinds = session.execute(
            text(
                "SELECT b.kind, d.part_index FROM content_drafts d "
                "JOIN content_briefs b ON b.id = d.brief_id "
                "WHERE d.parent_draft_id = :c ORDER BY d.part_index"
            ),
            {"c": world["clip"]},
        ).all()
    assert [(row.kind, row.part_index) for row in kinds] == [
        ("character_scene", 1),
        ("character_scene", 2),
    ]
    store = cs.PostgresCharacterSceneStore()
    assert store.scenes_of(tenant_id=tenant, clip_id=world["clip"]) == tuple(world["scenes"])


def test_scenes_count_in_the_daily_cap_and_owe_their_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    tenant, brand = world["tenant"], world["brand"]
    store = cs.PostgresCharacterSceneStore()
    assert store.scenes_made_today(tenant_id=tenant) == 2
    assert PostgresClipAvatarStore().blocks_made_today(tenant_id=tenant) == 2
    # both are owed (5 + 8 s) while their Clip is not approved
    assert store.pending_scene_seconds(tenant_id=tenant, brand_id=brand) == (2, 13)
    # P6: a FAILED Clip's scenes owe nothing
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'failed' WHERE id = :c"),
            {"c": world["clip"]},
        )
    assert store.pending_scene_seconds(tenant_id=tenant, brand_id=brand) == (0, 0)
    # another business sees none of them (RLS)
    other = _world(monkeypatch)
    assert store.scenes_made_today(tenant_id=other["tenant"]) == 2
    assert store.scenes_of(tenant_id=other["tenant"], clip_id=world["clip"]) == ()


def test_the_stored_brief_names_the_character_where_the_in_use_check_reads_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """m-25129385's `PostgresCharacterUsage` JSON path, verbatim."""
    world = _world(monkeypatch)
    with tenant_session(world["tenant"]) as session:
        named = session.execute(
            text(
                "SELECT b.media->'character_scenes'->0->>'character_id' "
                "FROM content_drafts d JOIN content_briefs b ON b.id = d.brief_id "
                "WHERE d.id = :c"
            ),
            {"c": world["clip"]},
        ).scalar_one()
        found = session.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM content_drafts d "
                "JOIN content_briefs b ON b.id = d.brief_id WHERE d.id = :c AND "
                "jsonb_path_exists(b.media, '$.character_scenes[*] ? (@.character_id == $id)', "
                "jsonb_build_object('id', CAST(:character AS text))))"
            ),
            {"c": world["clip"], "character": named},
        ).scalar_one()
    assert named and found is True
