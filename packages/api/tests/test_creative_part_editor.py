"""UI-4 plan media and source contracts. Offline; no paid calls or durable writes."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.schemas import ContentBrief, PartRef, VideoPartPlan

from qualify_api.creative import part_media
from qualify_api.creative.media import BrandReferenceError, _key_problems
from qualify_api.creative.parts import (
    PartsExtendUnavailable,
    PartsSourceInvalid,
    _child_brief,
    check_split_parts,
    check_split_parts_for_tenant,
    plan_from_analysis,
)
from qualify_api.creative.parts_plan import (
    PLAN_EDIT_UNAVAILABLE,
    PLAN_MERGE_DESCRIPTION,
    PLAN_MERGE_PHOTOS,
    PLAN_MERGE_UNAVAILABLE,
    PLAN_MODE_FORBIDDEN,
    PartsPlanRefused,
    _same_entries,
    check_edited_plan,
    merge_short_part,
)
from qualify_api.referentes.reel_analysis_types import OBSERVED, ReelAnalysis

from .test_creative_media_byteplus import TENANT_ID, _kit, _produce
from .test_creative_part_clip import PHOTO, DraftSeedance, _mp4, _setup
from .test_creative_parts import analysis, parent_brief, shot

VIDEO = f"uploads/{TENANT_ID}/own.mp4"
AUDIO = f"uploads/{TENANT_ID}/own.mp3"


def _parent_with_photo(plan: VideoPartPlan) -> ContentBrief:
    parent = parent_brief(plan, clip_image_keys=(PHOTO,))
    return parent.model_copy(
        update={"media": parent.media.model_copy(update={"product_keys": (PHOTO,)})}
    )


def test_old_plan_defaults_and_new_plan_child_json_roundtrip() -> None:
    old = VideoPartPlan.model_validate({"seconds": 5})
    assert old.clip_image_keys is None and not old.clip_video_keys and not old.clip_audio_keys
    plan = VideoPartPlan(
        seconds=5,
        description="El producto.",
        clip_image_keys=(PHOTO,),
        clip_image_roles=("place",),
        clip_video_keys=(VIDEO,),
        clip_audio_keys=(AUDIO,),
    )
    child = _child_brief(parent_brief(plan), plan, 1, None)
    read = ContentBrief.model_validate_json(child.model_dump_json())
    assert read.media.part == PartRef(index=1, **plan.model_dump())
    assert read.media.clip_image_keys == (PHOTO,) and read.media.clip_image_roles == ("place",)
    assert read.media.clip_video_keys == (VIDEO,) and read.media.clip_audio_keys == (AUDIO,)


def test_none_photos_inherit_and_empty_photos_clear() -> None:
    inherited, cleared = VideoPartPlan(), VideoPartPlan(clip_image_keys=())
    parent = parent_brief(inherited, clip_image_keys=(PHOTO,), clip_image_roles=("style",))
    assert _child_brief(parent, inherited, 1, None).media.clip_image_keys == (PHOTO,)
    assert _child_brief(parent, inherited, 1, None).media.clip_image_roles == ("style",)
    assert _child_brief(parent, cleared, 1, None).media.clip_image_keys == ()


def test_edit_own_video_replaces_public_source_and_unclear_people() -> None:
    plan = VideoPartPlan(
        mode="edit",
        seconds=4,
        clip_video_keys=(VIDEO,),
        notices=("people_unclear",),
    )
    check_edited_plan((plan,), (), None)
    child = _child_brief(_parent_with_photo(plan), plan, 1, "ignored.mp4")
    assert child.media.clip_video_keys == (VIDEO,)
    with pytest.raises(ValidationError):
        VideoPartPlan(mode="edit")
    with pytest.raises(ValidationError):
        VideoPartPlan(mode="edit", clip_video_keys=(VIDEO,), clip_audio_keys=(AUDIO,))
    with pytest.raises(ValidationError):
        VideoPartPlan(clip_image_keys=(PHOTO,), clip_image_roles=("unknown",))


def test_source_identity_only_allows_editor_fields_and_source_free_manual_additions() -> None:
    reel = analysis(shot(0, 0, 5), shot(1, 5, 10))
    saved = plan_from_analysis(reel)
    edited = saved[0].model_copy(
        update={
            "mode": "reference",
            "description": "Un producto distinto.",
            "clip_image_keys": (),
            "clip_video_keys": (VIDEO,),
            "clip_audio_keys": (AUDIO,),
        }
    )
    added = VideoPartPlan(notices=("describe_it",))
    assert _same_entries((edited, saved[1], added), saved, reel, active_count=3)
    assert _same_entries((added, edited, saved[1]), saved, reel, active_count=3)
    assert _same_entries((edited, saved[1], added), saved, reel, active_count=2)
    for change in (
        {"seconds": 6},
        {"shot_indexes": (1,)},
        {"analysis_id": uuid4()},
        {"original_mode": "extend"},
        {"talks_to_camera": True},
    ):
        assert not _same_entries((edited.model_copy(update=change), saved[1]), saved, reel)
    assert not _same_entries((edited,), saved, reel)  # missing saved entries
    assert not _same_entries((edited.model_copy(update={"mode": "extend"}), saved[1]), saved)


def ui_manual_composition(
    reel: ReelAnalysis, saved: Sequence[VideoPartPlan], flow: str
) -> tuple[tuple[VideoPartPlan, ...], tuple[VideoPartPlan, ...]]:
    """UI-4's local payload composed with UI-3, before creation or optional API save."""
    from Qualify import part_editor_vm, reel_parts_vm

    entries = reel_parts_vm.entries_from_plan(reel, saved)
    added = part_editor_vm.new_entry()
    added["plan"] = part_editor_vm.updated_plan(
        added["plan"],
        mode="reference",
        description="Una toma adicional.",
        images=[],
        inherit_images=False,
        videos=[],
        audios=[],
    )
    entries.append(added)  # UI-4 Guardar initially appends to local state only
    removed = []
    if flow == "before":
        entries, before, after = reel_parts_vm.move_part(entries, added["key"], -1)
        assert after < before
    elif flow == "drag":
        entries, _, after = reel_parts_vm.move_unit(
            entries, reel_parts_vm.unit_count(entries) - 1, 0
        )
        assert after == 1
    elif flow in ("removed", "restored"):
        entries, position = reel_parts_vm.remove_part(entries, added["key"])
        assert position == len(saved) + 1
        removed = [added]
        if flow == "restored":
            entries.append(removed.pop())
            entries, _, after = reel_parts_vm.move_unit(
                entries, reel_parts_vm.unit_count(entries) - 1, 0
            )
            assert after == 1
    else:
        raise AssertionError(flow)
    return reel_parts_vm.plans(entries), reel_parts_vm.plans(removed)


@pytest.mark.parametrize("flow", ["before", "drag", "removed", "restored"])
def test_ui_add_save_then_ui3_compositions_pass_backend_source_guard(flow) -> None:
    reel = analysis(shot(0, 0, 5), shot(1, 5, 10))
    saved = plan_from_analysis(reel)
    parts, removed = ui_manual_composition(reel, saved, flow)
    check_edited_plan(parts, removed, reel)
    assert _same_entries((*parts, *removed), saved, reel, active_count=len(parts))
    # The same local composition cannot discard an existing public origin.
    missing = tuple(p for p in parts if p.shot_indexes != saved[0].shot_indexes)
    assert not _same_entries((*missing, *removed), saved, reel, active_count=len(missing))


def test_new_manual_can_choose_own_video_edit_but_never_forge_public_source_or_extend() -> None:
    saved = (VideoPartPlan(description="Original."),)
    own_edit = VideoPartPlan(
        mode="edit",
        seconds=4,
        description="Mi video.",
        clip_image_keys=(PHOTO,),
        clip_video_keys=(VIDEO,),
    )
    check_edited_plan((own_edit, *saved), (), None)
    assert _same_entries((own_edit, *saved), saved, active_count=2)
    assert _same_entries((*saved, own_edit), saved, active_count=1)  # local remove before save
    for change in (
        {"original_mode": "edit"},
        {"analysis_id": uuid4()},
        {"shot_indexes": (0,)},
        {"mode": "extend"},
        {"clip_video_keys": ()},
        {"clip_audio_keys": (AUDIO,)},
    ):
        assert not _same_entries(
            (own_edit.model_copy(update=change), *saved), saved, active_count=2
        )


def test_public_edit_uses_authoritative_faces_source_and_window() -> None:
    reel = analysis(shot(0, 0, 5, people=OBSERVED))
    part = VideoPartPlan(mode="edit", seconds=5, analysis_id=reel.id, shot_indexes=(0,))
    with pytest.raises(PartsPlanRefused) as refused:
        check_edited_plan((part,), (), reel)
    assert refused.value.reason == PLAN_EDIT_UNAVAILABLE
    for unavailable in (
        replace(reel, source_available=False),
        replace(reel, width=1080, height=1080),
    ):
        with pytest.raises(PartsPlanRefused):
            check_edited_plan((part,), (), unavailable)
    extension = VideoPartPlan(mode="extend").model_copy(update={"clip_video_keys": (VIDEO,)})
    with pytest.raises(PartsPlanRefused) as refused:
        check_edited_plan((VideoPartPlan(), extension), (), None)
    assert refused.value.reason == PLAN_MODE_FORBIDDEN


def test_expired_public_edit_tombstone_does_not_block_active_edits_but_restore_rechecks() -> None:
    reel = analysis(shot(0, 0, 5), shot(1, 5, 10))
    original = plan_from_analysis(reel)
    active = original[0].model_copy(update={"mode": "reference", "clip_image_keys": ()})
    expired = replace(reel, source_available=False)
    check_edited_plan((active,), (original[1],), expired)
    with pytest.raises(PartsPlanRefused) as refused:
        check_edited_plan((active, original[1]), (), expired)
    assert refused.value.reason == PLAN_EDIT_UNAVAILABLE


@pytest.mark.parametrize("indexes", [None, (1,), (2,)])
def test_any_active_extend_refuses_new_batch_even_try_first_before_preparation_or_charges(
    indexes, monkeypatch
) -> None:
    from qualify_api.creative.part_request import refusal_of

    from .test_creative_parts import TENANT_ID as service_tenant
    from .test_creative_parts import USER_ID as service_user
    from .test_creative_parts import world

    plan = (
        VideoPartPlan(description="Primera."),
        VideoPartPlan(mode="extend", description="Sigue."),
    )
    parts, content, repo, ledger, dispatcher, _, parent = world(plan=plan)
    before = dict(ledger.rows)
    monkeypatch.setattr(content, "prepare_new_generation", lambda **kw: pytest.fail("not prepared"))
    with pytest.raises(PartsExtendUnavailable) as refused:
        parts.create_parts(
            tenant_id=service_tenant,
            parent_id=parent,
            user_id=service_user,
            part_indexes=indexes,
        )
    assert refusal_of(refused.value) == ("extend_unavailable", None, 0)
    assert ledger.rows == before and not dispatcher.calls
    assert not repo.parts_of(tenant_id=service_tenant, parent_id=parent)


def test_legacy_extend_keeps_reads_idempotent_and_removed_does_not_block() -> None:
    from .test_creative_parts import TENANT_ID as service_tenant
    from .test_creative_parts import USER_ID as service_user
    from .test_creative_parts import world

    plan = (VideoPartPlan(description="Primera."), VideoPartPlan(description="Segunda."))
    parts, _, repo, ledger, dispatcher, _, parent = world(plan=plan)
    ids = parts.create_parts(tenant_id=service_tenant, parent_id=parent, user_id=service_user)
    brief_id = repo.drafts[parent].brief_id
    brief = repo.briefs[brief_id]
    legacy = plan[1].model_copy(update={"mode": "extend"})
    repo.briefs[brief_id] = brief.model_copy(
        update={"media": brief.media.model_copy(update={"parts": (plan[0], legacy)})}
    )
    before, queued = dict(ledger.rows), list(dispatcher.calls)
    assert (
        parts.create_parts(tenant_id=service_tenant, parent_id=parent, user_id=service_user) == ids
    )
    assert ledger.rows == before and dispatcher.calls == queued
    # A removed legacy extend does not prevent creation of another missing active part.
    repo.mark_part_removed(tenant_id=service_tenant, draft_id=ids[1], user_id=service_user)
    repo.drafts.pop(ids[0])
    made = parts.create_parts(tenant_id=service_tenant, parent_id=parent, user_id=service_user)
    assert len(made) == 1


@pytest.mark.parametrize("placement", ["in_place", "before_head", "head_removed", "own_edit"])
def test_converted_born_split_retains_canonical_source_in_any_independent_position(
    placement,
) -> None:
    reel = analysis(shot(0, 0, 12))
    head, tail = plan_from_analysis(reel)
    converted = tail.model_copy(update={"mode": "reference"})
    if placement == "own_edit":
        converted = converted.model_copy(update={"mode": "edit", "clip_video_keys": (VIDEO,)})
    plans = (converted, head) if placement == "before_head" else (head, converted)
    if placement == "head_removed":
        plans = (converted,)
    brief = ContentBrief.model_validate_json(parent_brief(*plans).model_dump_json())
    check_split_parts(brief.media.parts, reel)
    assert converted.original_mode == "extend" and converted.shot_indexes == tail.shot_indexes
    assert (converted.seconds, converted.trim_start_s, converted.trim_end_s) == (
        tail.seconds,
        tail.trim_start_s,
        tail.trim_end_s,
    )
    child = _child_brief(brief, converted, 1, None)
    assert child.media.part.original_mode == "extend"
    with pytest.raises(ValidationError, match="without offsets"):
        VideoPartPlan.model_validate({**tail.model_dump(), "mode": "edit"})


@pytest.mark.parametrize("bad", ["short_cut", "excess_repeat", "missing_analysis"])
def test_split_markers_require_real_long_cut_and_canonical_repeat_bound_before_children(
    bad,
) -> None:
    from .test_creative_parts import TENANT_ID as service_tenant
    from .test_creative_parts import USER_ID as service_user
    from .test_creative_parts import world

    reel = analysis(shot(0, 0, 12))
    head, tail = plan_from_analysis(reel)
    converted = tail.model_copy(update={"mode": "reference"})
    plans = (head, converted, converted) if bad == "excess_repeat" else (converted,)
    actual = replace(reel, shots=(shot(0, 0, 5),)) if bad == "short_cut" else reel
    if bad == "missing_analysis":
        actual = None
    with pytest.raises(PartsSourceInvalid):
        check_split_parts(plans, actual)
    if actual is None:
        return
    parts, _, repo, ledger, dispatcher, _, parent = world(plan=plans)
    before = dict(ledger.rows)
    with pytest.raises(PartsSourceInvalid):
        parts.create_parts(
            tenant_id=service_tenant, parent_id=parent, user_id=service_user, analysis=actual
        )
    assert ledger.rows == before and not dispatcher.calls
    assert not repo.parts_of(tenant_id=service_tenant, parent_id=parent)


def test_fresh_split_validation_reads_only_this_tenants_cached_analysis(monkeypatch) -> None:
    from qualify_api.referentes import reel_analysis

    reel = analysis(shot(0, 0, 12))
    head, tail = plan_from_analysis(reel)
    converted = tail.model_copy(update={"mode": "reference"})
    reads = []

    def existing(tenant, analysis_id):
        reads.append((tenant, analysis_id))
        return reel

    monkeypatch.setattr(reel_analysis, "get_analysis", existing)
    check_split_parts_for_tenant(tenant_id=TENANT_ID, parts=(converted, head))
    assert reads == [(TENANT_ID, reel.id)]
    monkeypatch.setattr(reel_analysis, "get_analysis", lambda *a: None)
    with pytest.raises(PartsSourceInvalid):
        check_split_parts_for_tenant(tenant_id=TENANT_ID, parts=(converted, head))


@pytest.mark.parametrize("supplied", [True, False])
def test_removed_split_markers_count_towards_canonical_budget_before_new_work(
    supplied: bool, monkeypatch
) -> None:
    from qualify_api.referentes import reel_analysis

    from .test_creative_parts import TENANT_ID as service_tenant
    from .test_creative_parts import USER_ID as service_user
    from .test_creative_parts import world

    reel = analysis(shot(0, 0, 12))
    head, tail = plan_from_analysis(reel)
    converted = tail.model_copy(update={"mode": "reference"})
    monkeypatch.setattr(reel_analysis, "get_analysis", lambda *a: reel)
    parts, _, repo, ledger, dispatcher, _, parent = world(
        plan=(head,), media={"parts_removed": (converted, converted)}
    )
    before = dict(ledger.rows)
    with pytest.raises(PartsSourceInvalid):
        parts.create_parts(
            tenant_id=service_tenant,
            parent_id=parent,
            user_id=service_user,
            analysis=reel if supplied else None,
        )
    assert ledger.rows == before and not dispatcher.calls
    assert not repo.parts_of(tenant_id=service_tenant, parent_id=parent)


def test_only_removed_split_marker_is_authoritatively_checked_without_execution_requirements(
    monkeypatch,
) -> None:
    from qualify_api.referentes import reel_analysis

    from .test_creative_parts import TENANT_ID as service_tenant
    from .test_creative_parts import USER_ID as service_user
    from .test_creative_parts import world

    reel = analysis(shot(0, 0, 12))
    _, tail = plan_from_analysis(reel)
    removed = tail.model_copy(update={"mode": "reference", "clip_image_keys": ()})
    ordinary = VideoPartPlan(description="Una toma nueva.", clip_image_keys=())
    parts, _, repo, ledger, dispatcher, _, parent = world(
        plan=(ordinary,), media={"parts_removed": (removed,)}
    )
    before = dict(ledger.rows)
    monkeypatch.setattr(reel_analysis, "get_analysis", lambda *a: None)
    with pytest.raises(PartsSourceInvalid):
        parts.create_parts(tenant_id=service_tenant, parent_id=parent, user_id=service_user)
    assert ledger.rows == before and not dispatcher.calls
    assert not repo.parts_of(tenant_id=service_tenant, parent_id=parent)
    # Source expiry and missing photos affect execution, not the validity of a kept
    # tombstone whose authoritative long-cut analysis still exists.
    monkeypatch.setattr(
        reel_analysis, "get_analysis", lambda *a: replace(reel, source_available=False)
    )
    ids = parts.create_parts(tenant_id=service_tenant, parent_id=parent, user_id=service_user)
    assert len(ids) == 1


@pytest.mark.parametrize("field,key", [("clip_video_keys", VIDEO), ("clip_audio_keys", AUDIO)])
def test_extend_own_media_is_refused_by_schema_and_actual_creation_before_charges(
    field: str, key: str
) -> None:
    from .test_creative_parts import TENANT_ID as service_tenant
    from .test_creative_parts import USER_ID as service_user
    from .test_creative_parts import world

    with pytest.raises(ValidationError, match="extend part cannot"):
        VideoPartPlan.model_validate({"mode": "extend", field: [key]})
    valid = (VideoPartPlan(), VideoPartPlan(mode="extend"))
    raw = parent_brief(*valid).model_dump(mode="json")
    raw["media"]["parts"][1][field] = [key]
    with pytest.raises(ValidationError, match="extend part cannot"):
        ContentBrief.model_validate(raw)  # actual fresh-parent input boundary
    # Even a programmatically constructed model that bypassed validation cannot
    # create children, spend previews or enqueue work through PartsService.
    parts, _, repo, ledger, dispatcher, _, parent = world(plan=valid)
    draft = repo.drafts[parent]
    before = dict(ledger.rows)
    brief = repo.briefs[draft.brief_id]
    invalid = valid[1].model_copy(update={field: (key,)})
    repo.briefs[draft.brief_id] = brief.model_copy(
        update={"media": brief.media.model_copy(update={"parts": (valid[0], invalid)})}
    )
    with pytest.raises(ValidationError, match="extend part cannot"):
        parts.create_parts(tenant_id=service_tenant, parent_id=parent, user_id=service_user)
    assert ledger.rows == before and not dispatcher.calls
    assert repo.parts_of(tenant_id=service_tenant, parent_id=parent) == ()


def test_short_merge_consumes_exact_adjacent_saved_sources() -> None:
    reel = analysis(shot(0, 0, 2), shot(1, 2, 5))
    first = VideoPartPlan(seconds=2, analysis_id=reel.id, shot_indexes=(0,), description="A.")
    second = VideoPartPlan(seconds=3, analysis_id=reel.id, shot_indexes=(1,), description="B.")
    merged = merge_short_part(first, second, reel)
    assert (merged.seconds, merged.shot_indexes, merged.description) == (5, (0, 1), "A. B.")
    assert merged.mode == merged.original_mode == "edit"
    assert _same_entries((merged,), (first, second), reel, merge_sources=(first, second))
    # Local reorder is allowed: immutable source order, rather than old display order,
    # proves which cuts may be joined.
    assert _same_entries((merged,), (second, first), reel, merge_sources=(second, first))
    with pytest.raises(PartsPlanRefused) as refused:
        merge_short_part(first.model_copy(update={"clip_video_keys": (VIDEO,)}), second, reel)
    assert refused.value.reason == PLAN_MERGE_UNAVAILABLE
    with pytest.raises(PartsPlanRefused) as refused:
        merge_short_part(
            first.model_copy(update={"description": "a" * 500}),
            second.model_copy(update={"description": "b" * 500}),
            reel,
        )
    assert refused.value.reason == PLAN_MERGE_DESCRIPTION


def test_removed_history_can_exceed_six_without_losing_entries() -> None:
    brief = parent_brief(VideoPartPlan(), parts_removed=tuple(VideoPartPlan() for _ in range(10)))
    assert len(ContentBrief.model_validate_json(brief.model_dump_json()).media.parts_removed) == 10
    check_edited_plan(brief.media.parts, brief.media.parts_removed, None)


def test_unsaved_reorder_description_photos_and_explicit_media_clear_can_merge() -> None:
    reel = analysis(shot(0, 0, 2), shot(1, 2, 5), shot(2, 5, 10))
    first = VideoPartPlan(
        seconds=2,
        analysis_id=reel.id,
        shot_indexes=(0,),
        description="a" * 600,
        clip_video_keys=(VIDEO,),
    )
    second = VideoPartPlan(
        seconds=3,
        analysis_id=reel.id,
        shot_indexes=(1,),
        description="b" * 600,
        clip_audio_keys=(AUDIO,),
    )
    third = VideoPartPlan(seconds=5, analysis_id=reel.id, shot_indexes=(2,))
    current = first.model_copy(
        update={
            "description": "Una toma.",
            "clip_video_keys": (),
            "clip_image_keys": (PHOTO,),
        }
    )
    following = second.model_copy(
        update={
            "description": "Otra toma.",
            "clip_audio_keys": (),
            "clip_image_keys": (PHOTO,),
        }
    )
    merged = merge_short_part(current, following, reel)
    saved = (second, third, first)
    assert _same_entries((third, merged), saved, reel, merge_sources=saved, active_count=2)
    assert not _same_entries(
        (third, merged.model_copy(update={"seconds": 6})), saved, reel, merge_sources=saved
    )
    assert not _same_entries(
        (third, merged.model_copy(update={"clip_audio_keys": (AUDIO,)})),
        saved,
        reel,
        merge_sources=saved,
    )


def test_restored_source_can_merge_once_while_other_history_survives() -> None:
    reel = analysis(shot(0, 0, 2), shot(1, 2, 5), shot(2, 5, 10))
    restored = VideoPartPlan(seconds=2, analysis_id=reel.id, shot_indexes=(0,))
    active = VideoPartPlan(seconds=3, analysis_id=reel.id, shot_indexes=(1,))
    other = VideoPartPlan(seconds=5, analysis_id=reel.id, shot_indexes=(2,))
    history = VideoPartPlan(description="Se queda quitada.")
    saved = (active, other, restored, history)
    merged = merge_short_part(restored, active, reel)
    assert _same_entries((merged, other, history), saved, reel, merge_sources=saved, active_count=2)
    assert not _same_entries(
        (merged, other, restored, history), saved, reel, merge_sources=saved, active_count=2
    )
    assert not _same_entries(
        (other, merged, history), saved, reel, merge_sources=saved, active_count=1
    )


def test_nested_foreign_and_malformed_refs_are_refused_before_media_read() -> None:
    foreign = f"uploads/{uuid4()}/foreign.jpg"
    plan = VideoPartPlan(clip_image_keys=(foreign,), clip_audio_keys=("../../bad.mp3",))
    malformed, other = _key_problems(TENANT_ID, parent_brief(plan), _kit())
    assert "../../bad.mp3" in malformed and foreign in other


def test_own_reference_video_and_audio_reach_provider_without_reel_cutter() -> None:
    producer, store, seedance, windows, _ = _setup()
    store.files[VIDEO], store.files[AUDIO] = _mp4(4), b"audio"
    plan = VideoPartPlan(seconds=4, clip_video_keys=(VIDEO,), clip_audio_keys=(AUDIO,))
    child = _child_brief(_parent_with_photo(plan), plan, 1, None)
    result = _produce(producer, child, uuid4())
    assert result.failure is None, result.detail
    request = seedance.requests[0]
    assert request.params["reference_videos"] and request.params["reference_audios"]
    assert "camera movement, motion and pacing of Video 1" in request.params["prompt"]
    assert "Use Audio 1 as the soundtrack" in request.params["prompt"]
    assert result.media[0].params["part_prompt_version"] == 2
    assert not windows.calls


def test_own_edit_length_is_checked_before_copy_or_provider() -> None:
    producer, store, seedance, windows, _ = _setup()
    store.files[VIDEO] = _mp4(5)
    plan = VideoPartPlan(mode="edit", seconds=4, clip_video_keys=(VIDEO,))
    child = _child_brief(_parent_with_photo(plan), plan, 1, None)
    with pytest.raises(BrandReferenceError, match="4 segundos"):
        producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=uuid4(), brief=child)
    assert not seedance.requests and not windows.calls
    store.files[VIDEO] = _mp4(4)
    result = _produce(producer, child, uuid4())
    assert result.failure is None, result.detail
    assert not windows.calls and len(seedance.requests) == 1


def test_duration_hint_checks_ownership_before_database_or_reads(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(part_media, "_saved_seconds", lambda *a: calls.append("metadata") or 4.0)
    monkeypatch.setattr(part_media, "_probe_bytes", lambda *a: calls.append("read") or _mp4(4))
    assert (
        part_media.part_video_seconds(tenant_id=TENANT_ID, key=f"uploads/{uuid4()}/x.mp4") is None
    )
    assert part_media.part_video_seconds(tenant_id=TENANT_ID, key="../../x.mp4") is None
    assert not calls
    assert part_media.part_video_seconds(tenant_id=TENANT_ID, key=VIDEO) == 4.0
    assert calls == ["metadata"]


def test_selected_own_media_is_not_dropped_when_model_refuses() -> None:
    producer, store, seedance, windows, _ = _setup(
        seedance=DraftSeedance(refuse="ArkAPIError: HTTP 403 AccessDenied: not activated")
    )
    store.files[VIDEO], store.files[AUDIO] = _mp4(4), b"audio"
    plan = VideoPartPlan(seconds=4, clip_video_keys=(VIDEO,), clip_audio_keys=(AUDIO,))
    result = _produce(producer, _child_brief(_parent_with_photo(plan), plan, 1, None), uuid4())
    assert result.failure == "provider_error" and not result.media
    assert len(seedance.requests) == 1 and not windows.calls
    assert seedance.requests[0].params["reference_videos"]
    assert seedance.requests[0].params["reference_audios"]


def test_duration_probe_refuses_large_objects_before_downloading(monkeypatch) -> None:
    from qualify_api.creative import owner_uploads, purged_media

    class Gate:
        def object_size(self, *args):
            return part_media._MAX_PROBE_BYTES + 1

        def open_object(self, *args):
            pytest.fail("an oversized object must not be downloaded")

    monkeypatch.setattr(owner_uploads, "default_gate", lambda: Gate())
    monkeypatch.setattr(purged_media, "refuse_if_purged", lambda *a: None)
    assert part_media._probe_bytes(TENANT_ID, f"t/{TENANT_ID}/uploads/large.mp4") is None


def test_duration_hint_logs_expected_failure_without_payload_and_exposes_programming_errors(
    monkeypatch, caplog
) -> None:
    from sqlalchemy.exc import OperationalError

    def database_unavailable(*args):
        raise OperationalError("secret-query", {}, RuntimeError("secret-password"))

    def read_unavailable(*args):
        raise OSError("secret-object-key")

    monkeypatch.setattr(part_media, "_saved_seconds", database_unavailable)
    monkeypatch.setattr(part_media, "_probe_bytes", read_unavailable)
    assert part_media.part_video_seconds(tenant_id=TENANT_ID, key=VIDEO) is None
    assert "OperationalError" in caplog.text and "OSError" in caplog.text
    assert "secret-" not in caplog.text

    def broken_metadata(*args):
        raise TypeError("programming defect")

    monkeypatch.setattr(part_media, "_saved_seconds", broken_metadata)
    with pytest.raises(TypeError, match="programming defect"):
        part_media.part_video_seconds(tenant_id=TENANT_ID, key=VIDEO)


@pytest.mark.parametrize("error_kind", ["client", "transport", "programming"])
def test_duration_probe_uses_sanctioned_storage_errors_and_preserves_programming_failures(
    error_kind, monkeypatch, caplog
) -> None:
    from botocore.exceptions import BotoCoreError, ClientError

    from qualify_api.creative import owner_uploads, purged_media

    errors = {
        "client": ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "secret-object-token"}}, "HeadObject"
        ),
        "transport": BotoCoreError(),
        "programming": TypeError("programming defect"),
    }

    class Gate:
        def object_size(self, *args):
            raise errors[error_kind]

    monkeypatch.setattr(part_media, "_saved_seconds", lambda *a: None)
    monkeypatch.setattr(owner_uploads, "default_gate", lambda: Gate())
    monkeypatch.setattr(purged_media, "refuse_if_purged", lambda *a: None)
    key = f"t/{TENANT_ID}/uploads/probe.mp4"
    if error_kind == "programming":
        with pytest.raises(TypeError, match="programming defect"):
            part_media.part_video_seconds(tenant_id=TENANT_ID, key=key)
    else:
        assert part_media.part_video_seconds(tenant_id=TENANT_ID, key=key) is None
        assert "ObjectReadUnavailable" in caplog.text and "secret-" not in caplog.text


def test_duration_probe_preserves_successful_bounded_read(monkeypatch) -> None:
    import io

    from qualify_api.creative import owner_uploads, purged_media

    payload = _mp4(4)
    calls = []

    class Gate:
        def object_size(self, *args):
            calls.append("size")
            return len(payload)

        def open_object(self, *args):
            calls.append("read")
            return io.BytesIO(payload)

    monkeypatch.setattr(part_media, "_saved_seconds", lambda *a: None)
    monkeypatch.setattr(owner_uploads, "default_gate", lambda: Gate())
    monkeypatch.setattr(purged_media, "refuse_if_purged", lambda *a: None)
    assert (
        part_media.part_video_seconds(tenant_id=TENANT_ID, key=f"t/{TENANT_ID}/uploads/probe.mp4")
        == 4.0
    )
    assert calls == ["size", "read"]


def test_an_extend_already_made_does_not_block_creating_a_missing_part() -> None:
    from .test_creative_parts import TENANT_ID as service_tenant
    from .test_creative_parts import USER_ID as service_user
    from .test_creative_parts import world

    plan = (VideoPartPlan(description="Primera."), VideoPartPlan(description="Segunda."))
    parts, _, repo, *_, parent = world(plan=plan)
    ids = parts.create_parts(tenant_id=service_tenant, parent_id=parent, user_id=service_user)
    brief_id = repo.drafts[parent].brief_id
    brief = repo.briefs[brief_id]
    legacy = plan[1].model_copy(update={"mode": "extend"})  # its child exists (made before)
    repo.briefs[brief_id] = brief.model_copy(
        update={"media": brief.media.model_copy(update={"parts": (plan[0], legacy)})}
    )
    repo.drafts.pop(ids[0])  # part 1 is missing again
    made = parts.create_parts(tenant_id=service_tenant, parent_id=parent, user_id=service_user)
    assert len(made) == 2 and made[1] == ids[1] and made[0] != ids[0]
    # never turned into `reference` behind the owner's back
    assert repo.briefs[brief_id].media.parts[1].mode == "extend"


def test_a_created_parent_whose_extend_has_no_child_stays_refused() -> None:
    """Residual case (documented, not decided here): a parent created before the guard
    whose active `extend` part was never made. Creating it would be new extend work, so
    `create_parts` refuses with nothing charged; the plan is not converted silently, and
    `save_parts_plan` refuses `parts_exist` once a child exists."""
    from qualify_api.creative.part_request import refusal_of

    from .test_creative_parts import TENANT_ID as service_tenant
    from .test_creative_parts import USER_ID as service_user
    from .test_creative_parts import world

    plan = (VideoPartPlan(description="Primera."), VideoPartPlan(description="Segunda."))
    parts, _, repo, ledger, dispatcher, _, parent = world(plan=plan)
    first = parts.create_parts(
        tenant_id=service_tenant, parent_id=parent, user_id=service_user, part_indexes=(1,)
    )
    brief_id = repo.drafts[parent].brief_id
    brief = repo.briefs[brief_id]
    legacy = plan[1].model_copy(update={"mode": "extend"})
    repo.briefs[brief_id] = brief.model_copy(
        update={"media": brief.media.model_copy(update={"parts": (plan[0], legacy)})}
    )
    before, queued = dict(ledger.rows), list(dispatcher.calls)
    for indexes in (None, (2,)):
        with pytest.raises(PartsExtendUnavailable) as refused:
            parts.create_parts(
                tenant_id=service_tenant,
                parent_id=parent,
                user_id=service_user,
                part_indexes=indexes,
            )
        assert refusal_of(refused.value) == ("extend_unavailable", None, 0)
    assert ledger.rows == before and dispatcher.calls == queued
    assert [c.id for c in repo.parts_of(tenant_id=service_tenant, parent_id=parent)] == first
    assert repo.briefs[brief_id].media.parts[1].mode == "extend"


def test_a_merge_the_part_schema_refuses_is_merge_unavailable_not_a_raw_error() -> None:
    reel = analysis(shot(0, 0, 2), shot(1, 2, 5))
    # client notices say someone of the original may show: the merged `edit` is invalid
    first = VideoPartPlan(
        seconds=2,
        analysis_id=reel.id,
        shot_indexes=(0,),
        description="A.",
        notices=("people_unclear",),
    )
    second = VideoPartPlan(seconds=3, analysis_id=reel.id, shot_indexes=(1,), description="B.")
    with pytest.raises(PartsPlanRefused) as refused:
        merge_short_part(first, second, reel)
    assert refused.value.reason == PLAN_MERGE_UNAVAILABLE
    assert isinstance(refused.value.__cause__, ValidationError)


@pytest.mark.parametrize(
    ("current", "following"),
    [
        ({"clip_image_keys": (PHOTO,)}, {}),  # own photos, the next inherits the video's
        ({}, {"clip_image_keys": (PHOTO,)}),
        ({"clip_image_keys": (PHOTO,)}, {"clip_image_keys": ()}),  # different selections
        (
            {"clip_image_keys": (PHOTO,), "clip_image_roles": ("product",)},
            {"clip_image_keys": (PHOTO,), "clip_image_roles": ("place",)},
        ),
    ],
)
def test_parts_with_different_photos_say_merge_photos(current: dict, following: dict) -> None:
    reel = analysis(shot(0, 0, 2), shot(1, 2, 5))
    first = VideoPartPlan(seconds=2, analysis_id=reel.id, shot_indexes=(0,), **current)
    second = VideoPartPlan(seconds=3, analysis_id=reel.id, shot_indexes=(1,), **following)
    with pytest.raises(PartsPlanRefused) as refused:
        merge_short_part(first, second, reel)
    assert refused.value.reason == PLAN_MERGE_PHOTOS
    same = {"clip_image_keys": (PHOTO,), "clip_image_roles": ()}
    merged = merge_short_part(first.model_copy(update=same), second.model_copy(update=same), reel)
    assert merged.clip_image_keys == (PHOTO,)


def test_duration_probe_refuses_a_purged_local_file_before_reading(monkeypatch, tmp_path) -> None:
    from pathlib import Path

    from qualify_api.creative import composition, purged_media

    local = tmp_path / VIDEO
    local.parent.mkdir(parents=True)
    local.write_bytes(_mp4(4))
    monkeypatch.setattr(composition, "media_root", lambda: tmp_path)
    monkeypatch.setattr(part_media, "_saved_seconds", lambda *a: None)
    monkeypatch.setattr(purged_media, "is_purged_object", lambda tenant, key: key == VIDEO)

    def no_read(self: Path) -> bytes:
        raise AssertionError("a purged file must not be read")

    monkeypatch.setattr(Path, "read_bytes", no_read)
    assert part_media.part_video_seconds(tenant_id=TENANT_ID, key=VIDEO) is None
    monkeypatch.undo()  # not purged: the same local file is read and measured
    monkeypatch.setattr(composition, "media_root", lambda: tmp_path)
    monkeypatch.setattr(part_media, "_saved_seconds", lambda *a: None)
    monkeypatch.setattr(purged_media, "is_purged_object", lambda tenant, key: False)
    assert part_media.part_video_seconds(tenant_id=TENANT_ID, key=VIDEO) == pytest.approx(4, 0.1)
