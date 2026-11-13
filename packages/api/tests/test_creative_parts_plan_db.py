"""m-24984421 against Postgres: the edited plan of a video by parts is kept on its parent
draft (`save_parts_plan`) and read back (`read_parts_plan`), survives a new session (what
«Seguir después» or a reload needs), numbers the parts made from it, is frozen once they
exist, and another business can neither read nor write it (RLS). No vendor is called."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from qualify_creative.schemas import VideoPartPlan
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.parts import plan_from_analysis
from qualify_api.creative.parts_plan import (
    PLAN_EDIT_UNAVAILABLE,
    PLAN_EXTEND_ORDER,
    PLAN_INVALID,
    PLAN_MEDIA_KEY,
    PLAN_NOT_SAVED,
    PLAN_PARTS_EXIST,
    PLAN_REPEATED_CUT,
    PLAN_TOO_LONG,
    PLAN_UNKNOWN_CUT,
    PartsPlanRefused,
    merge_short_part,
    read_parts_plan,
    save_parts_plan,
)
from qualify_api.creative.service import UnknownDraft

from .test_creative_part_editor import ui_manual_composition
from .test_creative_parts import analysis, parent_brief, shot
from .test_creative_parts_db import _business, _service

pytestmark = pytest.mark.db

REEL = analysis(shot(0, 0.0, 5.0), shot(1, 5.0, 10.0), shot(2, 10.0, 15.0), shot(3, 15.0, 29.0))
PLAN = plan_from_analysis(REEL)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    tenant, brand, user = _business(monkeypatch)
    service, parts, _ = _service()
    brief = parent_brief(*PLAN).model_copy(update={"brand_id": brand})
    parent = service.create_draft(tenant_id=tenant, brand_id=brand, brief=brief, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=parent)
    return service, parts, tenant, brand, user, parent


def _brief_id(tenant: UUID, parent: UUID) -> object:
    with tenant_session(tenant) as session:
        return session.execute(
            text("SELECT brief_id FROM content_drafts WHERE id = :p"), {"p": parent}
        ).scalar()


def test_a_parent_never_edited_reads_its_original_plan_db(world) -> None:  # noqa: ANN001
    _, _, tenant, _, _, parent = world
    saved = read_parts_plan(tenant_id=tenant, parent_id=parent)
    assert saved.parts == PLAN and saved.removed == () and not saved.locked


def test_the_edited_plan_is_kept_and_read_back_in_a_new_session_db(world) -> None:  # noqa: ANN001
    _, _, tenant, _, _, parent = world
    brief_before = _brief_id(tenant, parent)
    kept, removed = (PLAN[3], PLAN[4], PLAN[0], PLAN[2]), (PLAN[1],)
    saved = save_parts_plan(
        tenant_id=tenant, parent_id=parent, parts=kept, removed=removed, analysis=REEL
    )
    assert saved.parts == kept and saved.removed == removed
    again = read_parts_plan(tenant_id=tenant, parent_id=parent)
    assert again == saved
    # in place: the parent keeps its brief (its text versions point at it)
    assert _brief_id(tenant, parent) == brief_before
    # idempotent
    assert (
        save_parts_plan(
            tenant_id=tenant, parent_id=parent, parts=kept, removed=removed, analysis=REEL
        )
        == saved
    )


def test_a_refused_plan_leaves_the_saved_one_untouched_db(world) -> None:  # noqa: ANN001
    _, _, tenant, _, _, parent = world
    kept, removed = (PLAN[0], PLAN[2]), (PLAN[1], PLAN[3], PLAN[4])
    save_parts_plan(tenant_id=tenant, parent_id=parent, parts=kept, removed=removed, analysis=REEL)
    with pytest.raises(PartsPlanRefused) as refused:
        save_parts_plan(
            tenant_id=tenant,
            parent_id=parent,
            parts=(PLAN[4], PLAN[0]),
            removed=(PLAN[1], PLAN[2], PLAN[3]),
            analysis=REEL,
        )
    assert refused.value.reason == PLAN_EXTEND_ORDER
    bogus = PLAN[0].model_copy(update={"shot_indexes": (7,)})
    with pytest.raises(PartsPlanRefused) as refused:
        save_parts_plan(tenant_id=tenant, parent_id=parent, parts=(bogus,), analysis=REEL)
    assert refused.value.reason == PLAN_UNKNOWN_CUT
    assert read_parts_plan(tenant_id=tenant, parent_id=parent).parts == kept


def test_saved_source_identity_survives_edits_reorder_and_restore_db(world) -> None:  # noqa: ANN001
    _, _, tenant, _, _, parent = world

    def save(parts: tuple, removed: tuple) -> object:  # type: ignore[type-arg]
        return save_parts_plan(
            tenant_id=tenant, parent_id=parent, parts=parts, removed=removed, analysis=REEL
        )

    # take the long cut's head out: its «Sigue a la anterior» is made new — allowed
    orphan = PLAN[4].model_copy(update={"mode": "reference"})
    save((orphan, PLAN[0], PLAN[1], PLAN[2]), (PLAN[3],))
    # put the head back before it (the screen returns the tail to «extend») — allowed
    save((PLAN[3], PLAN[4], PLAN[0], PLAN[1], PLAN[2]), ())
    edited = PLAN[0].model_copy(update={"description": "Otra cosa.", "mode": "reference"})
    save((edited, *PLAN[1:]), ())
    refused_plans = [
        # descriptions and modes are editable; source length and provenance are not
        ((PLAN[0].model_copy(update={"seconds": 6}), *PLAN[1:]), ()),
        ((PLAN[0].model_copy(update={"original_mode": "extend"}), *PLAN[1:]), ()),
        # an entry missing (neither kept nor removed)
        (PLAN[:4], ()),
        # an entry the plan never had (a cut of the reel left out of it)
        ((*PLAN[:4], PLAN[2]), (PLAN[4],)),
    ]
    for parts, removed in refused_plans:
        with pytest.raises(PartsPlanRefused) as refused:
            save(parts, removed)
        assert refused.value.reason in (PLAN_NOT_SAVED, PLAN_REPEATED_CUT, PLAN_INVALID)
    saved = read_parts_plan(tenant_id=tenant, parent_id=parent)
    assert saved.parts == (edited, *PLAN[1:]) and saved.removed == ()


def test_only_an_entry_born_extend_becomes_extend_again_db(world, monkeypatch) -> None:  # noqa: ANN001
    _, _, tenant, _, _, parent = world
    # a plan stored before `original_mode` existed: its orphan may be made new, never
    # made «Sigue a la anterior» again
    tenant2, brand2, user2 = _business(monkeypatch)
    service, _, _ = _service()
    legacy = tuple(p.model_copy(update={"original_mode": None}) for p in PLAN)
    brief = parent_brief(*legacy).model_copy(update={"brand_id": brand2})
    old_parent = service.create_draft(
        tenant_id=tenant2, brand_id=brand2, brief=brief, user_id=user2
    )
    orphan = legacy[4].model_copy(update={"mode": "reference"})
    save_parts_plan(
        tenant_id=tenant2,
        parent_id=old_parent,
        parts=(orphan, legacy[0], legacy[1], legacy[2]),
        removed=(legacy[3],),
        analysis=REEL,
    )
    with pytest.raises(PartsPlanRefused) as refused:
        save_parts_plan(tenant_id=tenant2, parent_id=old_parent, parts=legacy, analysis=REEL)
    assert refused.value.reason == PLAN_NOT_SAVED
    # the same move on a plan that records it is allowed
    born = PLAN[4].model_copy(update={"mode": "reference"})
    save_parts_plan(
        tenant_id=tenant,
        parent_id=parent,
        parts=(born, PLAN[0], PLAN[1], PLAN[2]),
        removed=(PLAN[3],),
        analysis=REEL,
    )
    assert (
        save_parts_plan(tenant_id=tenant, parent_id=parent, parts=PLAN, analysis=REEL).parts == PLAN
    )


def test_the_parts_follow_the_saved_order_and_freeze_it_db(world) -> None:  # noqa: ANN001
    service, parts, tenant, _, user, parent = world
    kept = (PLAN[3], PLAN[0], PLAN[2])
    save_parts_plan(
        tenant_id=tenant, parent_id=parent, parts=kept, removed=(PLAN[1], PLAN[4]), analysis=REEL
    )
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user, analysis=REEL)
    assert len(ids) == 3
    children = service.repository.parts_of(tenant_id=tenant, parent_id=parent)
    refs = [
        service.repository.get_brief(tenant_id=tenant, brief_id=c.brief_id).media.part
        for c in children
    ]
    assert [c.part_index for c in children] == [r.index for r in refs] == [1, 2, 3]
    assert [r.shot_indexes for r in refs] == [p.shot_indexes for p in kept]
    assert [r.mode for r in refs] == [p.mode for p in kept]
    assert read_parts_plan(tenant_id=tenant, parent_id=parent).locked
    with pytest.raises(PartsPlanRefused) as refused:
        save_parts_plan(tenant_id=tenant, parent_id=parent, parts=(PLAN[0],), analysis=REEL)
    assert refused.value.reason == PLAN_PARTS_EXIST


def test_each_part_stores_the_images_and_roles_it_received_db(monkeypatch) -> None:  # noqa: ANN001
    tenant, brand, user = _business(monkeypatch)
    service, parts, _ = _service()
    photos = ("uploads/t/burger.jpg", "uploads/t/local.jpg", "uploads/t/mood.jpg")
    made = (PLAN[0].model_copy(update={"mode": "reference"}), PLAN[3])
    brief = parent_brief(
        *made, clip_image_keys=photos, clip_image_roles=("product", "place", "style")
    ).model_copy(update={"brand_id": brand})
    parent = service.create_draft(tenant_id=tenant, brand_id=brand, brief=brief, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=parent)
    parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user, analysis=REEL)
    with tenant_session(tenant) as session:
        rows = session.execute(
            text("""
            SELECT b.media->'part'->>'mode', b.media->'clip_image_keys', b.media->'clip_image_roles'
            FROM content_drafts d JOIN content_briefs b ON b.id = d.brief_id
            WHERE d.parent_draft_id = :p ORDER BY d.part_index
            """),
            {"p": parent},
        ).all()
    assert [tuple(r) for r in rows] == [
        ("reference", list(photos), ["product", "place", "style"]),
        ("edit", list(photos), ["product", "place", "style"]),
    ]


def test_another_business_neither_reads_nor_writes_the_plan_db(world, monkeypatch) -> None:  # noqa: ANN001
    _, _, tenant, _, _, parent = world
    other, _, _ = _business(monkeypatch)
    with pytest.raises(UnknownDraft):
        read_parts_plan(tenant_id=other, parent_id=parent)
    with pytest.raises(UnknownDraft):
        save_parts_plan(tenant_id=other, parent_id=parent, parts=(PLAN[0],), analysis=REEL)
    assert read_parts_plan(tenant_id=tenant, parent_id=parent).parts == PLAN


def test_a_piece_that_is_not_a_video_by_parts_has_no_plan_db(world) -> None:  # noqa: ANN001
    _, _, tenant, _, _, _ = world
    with pytest.raises(UnknownDraft):
        read_parts_plan(tenant_id=tenant, parent_id=uuid4())


def test_editor_media_roundtrip_reaches_children_without_charging_on_save_db(world) -> None:  # noqa: ANN001
    service, parts, tenant, _, user, parent = world
    photo, video, audio = (f"uploads/{tenant}/own.{ext}" for ext in ("jpg", "mp4", "mp3"))
    edited = PLAN[0].model_copy(
        update={
            "mode": "reference",
            "description": "El producto en el local.",
            "clip_image_keys": (photo,),
            "clip_image_roles": ("place",),
            "clip_video_keys": (video,),
            "clip_audio_keys": (audio,),
        }
    )
    appended = VideoPartPlan(description="Una toma final.", clip_image_keys=())
    with tenant_session(tenant) as session:
        before = session.scalar(text("SELECT count(*) FROM creation_charges"))
        jobs_before = session.scalar(text("SELECT count(*) FROM creative_pipeline_runs"))
    saved = save_parts_plan(
        tenant_id=tenant,
        parent_id=parent,
        parts=(edited, *PLAN[1:4], appended),
        removed=(PLAN[4],),
        analysis=REEL,
    )
    assert read_parts_plan(tenant_id=tenant, parent_id=parent) == saved
    with tenant_session(tenant) as session:
        assert session.scalar(text("SELECT count(*) FROM creation_charges")) == before
        assert session.scalar(text("SELECT count(*) FROM creative_pipeline_runs")) == jobs_before
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user, analysis=REEL)
    children = [service.repository.get_draft(tenant_id=tenant, draft_id=i) for i in ids]
    first = service.repository.get_brief(tenant_id=tenant, brief_id=children[0].brief_id)
    last = service.repository.get_brief(tenant_id=tenant, brief_id=children[-1].brief_id)
    assert first.media.part.clip_image_keys == first.media.clip_image_keys == (photo,)
    assert first.media.clip_image_roles == ("place",)
    assert first.media.clip_video_keys == (video,) and first.media.clip_audio_keys == (audio,)
    assert last.media.part.clip_image_keys == last.media.clip_image_keys == ()


def test_editor_foreign_or_malformed_override_never_changes_saved_plan_db(world) -> None:  # noqa: ANN001
    _, _, tenant, _, _, parent = world
    for key in (f"uploads/{uuid4()}/other.jpg", "uploads/../other.jpg"):
        edited = PLAN[0].model_copy(update={"clip_image_keys": (key,)})
        with pytest.raises(PartsPlanRefused) as refused:
            save_parts_plan(
                tenant_id=tenant, parent_id=parent, parts=(edited, *PLAN[1:]), analysis=REEL
            )
        assert refused.value.reason == PLAN_MEDIA_KEY
        assert read_parts_plan(tenant_id=tenant, parent_id=parent).parts == PLAN


def test_six_active_parts_preserve_long_removed_history_and_refuse_restore_db(monkeypatch) -> None:  # noqa: ANN001
    tenant, brand, user = _business(monkeypatch)
    service, _, _ = _service()
    active = tuple(VideoPartPlan(description=f"Activa {i}.") for i in range(6))
    removed = tuple(VideoPartPlan(description=f"Quitada {i}.") for i in range(8))
    brief = parent_brief(*active, parts_removed=removed).model_copy(update={"brand_id": brand})
    parent = service.create_draft(tenant_id=tenant, brand_id=brand, brief=brief, user_id=user)
    saved = save_parts_plan(tenant_id=tenant, parent_id=parent, parts=active, removed=removed)
    with pytest.raises(PartsPlanRefused) as refused:
        save_parts_plan(
            tenant_id=tenant, parent_id=parent, parts=(*active, removed[0]), removed=removed[1:]
        )
    assert refused.value.reason == PLAN_TOO_LONG
    assert read_parts_plan(tenant_id=tenant, parent_id=parent) == saved
    restored = save_parts_plan(
        tenant_id=tenant,
        parent_id=parent,
        parts=(*active[1:], removed[0]),
        removed=(*removed[1:], active[0]),
    )
    assert len(restored.parts) == 6 and len(restored.removed) == 8


def test_short_merge_is_saved_atomically_without_forging_sources_db(monkeypatch) -> None:  # noqa: ANN001
    tenant, brand, user = _business(monkeypatch)
    service, _, _ = _service()
    reel = analysis(shot(0, 0, 2), shot(1, 2, 5))
    first = VideoPartPlan(seconds=2, analysis_id=reel.id, shot_indexes=(0,), description="A.")
    second = VideoPartPlan(seconds=3, analysis_id=reel.id, shot_indexes=(1,), description="B.")
    brief = parent_brief(second, parts_removed=(first,)).model_copy(update={"brand_id": brand})
    parent = service.create_draft(tenant_id=tenant, brand_id=brand, brief=brief, user_id=user)
    merged = merge_short_part(first, second, reel)
    result = save_parts_plan(tenant_id=tenant, parent_id=parent, parts=(merged,), analysis=reel)
    assert read_parts_plan(tenant_id=tenant, parent_id=parent) == result
    assert result.parts[0].shot_indexes == (0, 1) and result.removed == ()


@pytest.mark.parametrize("flow", ["before", "drag", "removed", "restored"])
def test_serialized_manual_ui_compositions_match_optional_save_and_fresh_creation_db(
    world, flow
) -> None:  # noqa: ANN001
    service, _, tenant, brand, user, parent = world
    active, removed = ui_manual_composition(REEL, PLAN, flow)
    # The optional edit API applies the same final-state contract to an existing parent.
    saved = save_parts_plan(
        tenant_id=tenant, parent_id=parent, parts=active, removed=removed, analysis=REEL
    )
    assert read_parts_plan(tenant_id=tenant, parent_id=parent) == saved
    assert saved.parts == active and saved.removed == removed
    # UI-6 currently creates a NEW parent directly; it does not call save_parts_plan.
    fresh_brief = parent_brief(*active, parts_removed=removed).model_copy(
        update={"brand_id": brand}
    )
    fresh = service.create_draft(tenant_id=tenant, brand_id=brand, brief=fresh_brief, user_id=user)
    fresh_read = read_parts_plan(tenant_id=tenant, parent_id=fresh)
    assert fresh_read.parts == active and fresh_read.removed == removed
    assert not fresh_read.locked


def test_new_manual_own_video_edit_can_be_saved_in_local_final_position_db(world) -> None:  # noqa: ANN001
    _, _, tenant, _, _, parent = world
    own = VideoPartPlan(
        mode="edit",
        seconds=4,
        description="El producto en mi video.",
        clip_image_keys=(f"uploads/{tenant}/own.jpg",),
        clip_video_keys=(f"uploads/{tenant}/own.mp4",),
    )
    result = save_parts_plan(tenant_id=tenant, parent_id=parent, parts=(own, *PLAN), analysis=REEL)
    assert result.parts[0] == own
    removed = save_parts_plan(
        tenant_id=tenant, parent_id=parent, parts=PLAN, removed=(own,), analysis=REEL
    )
    assert removed.removed == (own,)


def test_removed_public_edit_expiry_and_cleared_parent_photos_do_not_block_active_save_db(
    world,
) -> None:  # noqa: ANN001
    _, _, tenant, _, _, parent = world
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE content_briefs SET media="
                "jsonb_set(jsonb_set(media, '{product_keys}', '[]'), '{clip_image_keys}', '[]') "
                "WHERE id=(SELECT brief_id FROM content_drafts WHERE id=:p)"
            ),
            {"p": parent},
        )
    active = tuple(p.model_copy(update={"mode": "reference"}) for p in PLAN[1:4])
    removed = (PLAN[0], PLAN[4])
    expired = replace(REEL, source_available=False)
    saved = save_parts_plan(
        tenant_id=tenant, parent_id=parent, parts=active, removed=removed, analysis=expired
    )
    assert read_parts_plan(tenant_id=tenant, parent_id=parent) == saved
    for source in (expired, REEL):
        with pytest.raises(PartsPlanRefused) as refused:
            save_parts_plan(
                tenant_id=tenant,
                parent_id=parent,
                parts=(PLAN[0], *active),
                removed=(PLAN[4],),
                analysis=source,
            )
        assert refused.value.reason == PLAN_EDIT_UNAVAILABLE
    assert read_parts_plan(tenant_id=tenant, parent_id=parent) == saved
