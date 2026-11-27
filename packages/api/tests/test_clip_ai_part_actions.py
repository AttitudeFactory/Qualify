"""m-25129407 (ADR 50 §13.3, PR 3 «después de crear»): the owner's actions on a Clip's
«parte con IA» blocks.

Acceptance criteria pinned here:

1. every action checks its rules, today's local cap and the month BEFORE anything is
   written or paid (nothing written, nothing charged, nothing dispatched on a refusal);
2. reordering, cutting or changing a join never asks a part again (the parts' rows,
   revisions and charges stay; the Clip plays the same files);
3. an assembly the owner's tap causes counts in today's local cap; the automatic one
   (the Clip waking up when its part is made) does not.

Plus §11's wait brought back: a failed part keeps the Clip waiting for the owner's
choice (retry, change, make new, another mode, remove) for 72 h.

Offline only: no BytePlus, Seedance or Claude is called — the database is a set of dicts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.schemas import EffectUse, SourceSegment, VideoTextLayer

from qualify_api.creative import clip_ai_part_actions as act
from qualify_api.creative import clip_ai_parts as cap
from qualify_api.creative import clip_avatar as ca
from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED
from qualify_api.creative.local_cap import LocalDailyCapReached, local_daily_cap
from qualify_api.creative.part_extend import EXTEND_SWITCH
from qualify_api.creative.parts import PartChanges
from qualify_api.creative.video_pipeline.ai_parts import CLIP_AI_PARTS_SWITCH

from .test_clip_ai_parts import (
    OTHER,
    World,
    _block,
    _brief_of,
    _charged,
    _clip,
    _create,
    _entry,
    _made,
    _own,
    _switches,
    _world,
    assemble_at_the_sources_size,
    assembly_files,
    no_normalize_jobs,
    queue_on,
)
from .test_clip_avatar import OWN_VIDEO
from .test_content_service import BRAND_ID, TENANT_ID, USER_ID

__all__ = [  # fixtures used by name, or autouse
    "_switches",
    "assemble_at_the_sources_size",
    "assembly_files",
    "no_normalize_jobs",
    "queue_on",
]


# ---------------------------------------------------------------------------
# helpers


def _actions(world: World) -> act.ClipAiPartActions:
    return act.ClipAiPartActions(world.content, parts_store=world.store, store=object(), env={})


def _fail(world: World, part_id: UUID, reason: str = "provider_error") -> None:
    """The part failed, as its generation fails it: `failed`, its vista previa given back
    at its revision (`_refund_if_not_delivered`), its row written now."""
    draft = replace(world.repo.drafts[part_id], status=FAILED, failure_reason=reason)
    world.repo.drafts[part_id] = draft
    world.store.changed[part_id] = world.clock[0]
    if world.ledger is not None:
        world.ledger.refund(
            tenant_id=TENANT_ID, draft_id=part_id, revision=draft.revision, reason=reason
        )


def _made_again(world: World, part_id: UUID, seconds: float = 5.0) -> str:
    """The part's NEW version came out: its old file is an older version's now."""
    old = world.store.videos[part_id]
    world.store.old_keys[old.object_key] = part_id
    revision = world.repo.drafts[part_id].revision
    key = f"t/{TENANT_ID}/generated/{part_id}/r{revision}/video.mp4"
    world.repo.drafts[part_id] = replace(world.repo.drafts[part_id], status=GENERATED)
    world.store.videos[part_id] = replace(old, asset_id=uuid4(), object_key=key, seconds=seconds)
    return key


def _waiting_with_a_failed_part(world: World) -> cap.ClipWithAiParts:
    made = _create(world)
    _fail(world, made.part_ids[0])
    _made(world, made.part_ids[1])
    with pytest.raises(ca.ClipBlocksWait):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    return made


def _made_clip(world: World) -> tuple[cap.ClipWithAiParts, list[str]]:
    made = _create(world)
    keys = [_made(world, made.part_ids[0], 5.0), _made(world, made.part_ids[1], 4.0)]
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    return made, keys


class _Snapshot:
    """Everything an action could write: the rows, the briefs, the ledger, the jobs."""

    def __init__(self, world: World) -> None:
        self.drafts = dict(world.repo.drafts)
        self.briefs = len(world.repo.briefs)
        self.removed = set(world.repo.removed)
        self.rows = dict(world.ledger.rows) if world.ledger else {}
        self.calls = list(world.dispatcher.calls)

    def same(self, world: World) -> bool:
        return (
            self.drafts == world.repo.drafts
            and self.briefs == len(world.repo.briefs)
            and self.removed == world.repo.removed
            and self.rows == (dict(world.ledger.rows) if world.ledger else {})
            and self.calls == world.dispatcher.calls
        )


def _spend_the_local_cap(world: World) -> None:
    from qualify_creative.creations import weight_for

    assert world.ledger is not None
    price = weight_for(_brief_of(world, next(iter(world.repo.drafts))), redo=True)
    local = next(
        p for p in (price, weight_for(_clip((_own(4.0),), ()))) if p.request_kind == "local_video"
    )
    while world.repo.local_builds_today(tenant_id=TENANT_ID) < local_daily_cap():
        world.ledger.charge(
            tenant_id=TENANT_ID, brand_id=BRAND_ID, draft_id=uuid4(), revision=1, price=local
        )


def _use_every_preview(world: World) -> None:
    from qualify_creative.creations import load_weights

    assert world.ledger is not None
    world.ledger._opening_previews = load_weights().monthly_preview_quota  # noqa: SLF001


# ---------------------------------------------------------------------------
# §11's wait: a failed part waits for its owner


def test_a_failed_part_keeps_the_clip_waiting_with_the_owners_deadline() -> None:
    world = _world()
    made = _waiting_with_a_failed_part(world)
    view = _actions(world).parts_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view is not None and view.waiting and view.needs_attention
    assert view.wait_until == world.clock[0] + cap.CLIP_AI_PART_OWNER_WAIT
    first, second = view.parts
    assert first.state == "failed" and first.owner_text == act.PART_FAILED_TEXT
    assert first.actions == ("retry", "change", "change_mode", "remove")
    assert second.state == "ready" and second.actions == ()
    assert world.repo.drafts[made.clip_id].status == DRAFTING


def test_retry_makes_the_part_again_charges_one_preview_and_the_clip_goes_on() -> None:
    world = _world()
    made = _waiting_with_a_failed_part(world)
    part = made.part_ids[0]
    clip_brief = world.repo.drafts[made.clip_id].brief_id
    used = world.repo.local_builds_today(tenant_id=TENANT_ID)
    calls = len(world.dispatcher.calls)
    assert (
        _actions(world).retry_part(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=part
        )
        == part
    )
    child = world.repo.drafts[part]
    assert (child.status, child.revision) == (DRAFTING, 2)
    assert world.ledger is not None
    assert world.ledger.rows[(part, 2)].price.videos == 1  # one vista previa
    # the Clip's brief is written again (its pass that read before cannot fail it)
    assert world.repo.drafts[made.clip_id].brief_id != clip_brief
    assert _brief_of(world, made.clip_id).media.ai_parts  # still the owner's blocks
    assert world.dispatcher.calls[calls:] == [(TENANT_ID, part)]
    # a retry while the Clip waits for its FIRST assembly is no new local build
    assert world.repo.local_builds_today(tenant_id=TENANT_ID) == used
    with pytest.raises(ca.ClipBlocksWait, match="creating"):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    _made(world, part)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    # the automatic assembly counts nothing either
    assert world.repo.local_builds_today(tenant_id=TENANT_ID) == used


def test_a_double_tap_makes_one_attempt() -> None:
    world = _world()
    made = _waiting_with_a_failed_part(world)
    actions = _actions(world)
    args = {"tenant_id": TENANT_ID, "user_id": USER_ID, "clip_id": made.clip_id}
    actions.retry_part(part_id=made.part_ids[0], **args)
    snap = _Snapshot(world)
    assert actions.retry_part(part_id=made.part_ids[0], **args) == made.part_ids[0]
    assert snap.same(world)


def test_change_writes_the_new_description_before_making_it_again() -> None:
    world = _world()
    made = _waiting_with_a_failed_part(world)
    part = made.part_ids[0]
    _actions(world).retry_part(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=made.clip_id,
        part_id=part,
        changes=PartChanges(description="La arepa servida en un plato blanco"),
    )
    child = _brief_of(world, part).media.part
    assert child is not None and child.description == "La arepa servida en un plato blanco"
    assert child.mode == "reference" and world.repo.drafts[part].status == DRAFTING


def test_a_photo_of_another_business_is_refused_before_anything() -> None:
    world = _world()
    made = _waiting_with_a_failed_part(world)
    snap = _Snapshot(world)
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        _actions(world).retry_part(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            clip_id=made.clip_id,
            part_id=made.part_ids[0],
            changes=PartChanges(photo_keys=(f"uploads/{uuid4()}/ajena.jpg",)),
        )
    assert refused.value.code == "ai_part_file_not_owned"
    assert snap.same(world)


def test_a_new_part_refused_for_its_photos_is_never_asked_again_with_them() -> None:
    world = _world()
    made = _create(world)
    _fail(world, made.part_ids[0], reason="refused_face")
    snap = _Snapshot(world)
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        _actions(world).retry_part(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=made.part_ids[0]
        )
    assert refused.value.code == "part_action_refused"
    assert snap.same(world)


def test_a_part_that_did_not_fail_is_not_tried_again() -> None:
    world = _world()
    made = _waiting_with_a_failed_part(world)
    snap = _Snapshot(world)
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        _actions(world).retry_part(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=made.part_ids[1]
        )
    assert refused.value.code == "part_not_failed"
    assert snap.same(world)


# ---------------------------------------------------------------------------
# criterion 1: rules, cap and month before anything is written or paid


def test_retry_without_a_vista_previa_left_writes_nothing() -> None:
    world = _world()
    made = _waiting_with_a_failed_part(world)
    _use_every_preview(world)
    snap = _Snapshot(world)
    with pytest.raises(NotEnoughCreations):
        _actions(world).retry_part(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=made.part_ids[0]
        )
    assert snap.same(world)


def test_redo_without_a_vista_previa_left_writes_nothing() -> None:
    world = _world()
    made, _ = _made_clip(world)
    _use_every_preview(world)
    snap = _Snapshot(world)
    with pytest.raises(NotEnoughCreations):
        _actions(world).redo_part(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=made.part_ids[0]
        )
    assert snap.same(world)


def test_redo_with_todays_local_cap_spent_writes_nothing() -> None:
    world = _world()
    made, _ = _made_clip(world)
    _spend_the_local_cap(world)
    snap = _Snapshot(world)
    with pytest.raises(LocalDailyCapReached):
        _actions(world).redo_part(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=made.part_ids[0]
        )
    assert snap.same(world)


def test_rearrange_with_todays_local_cap_spent_writes_nothing() -> None:
    world = _world()
    made, keys = _made_clip(world)
    _spend_the_local_cap(world)
    segments = tuple(reversed(_brief_of(world, made.clip_id).media.segments))
    snap = _Snapshot(world)
    with pytest.raises(LocalDailyCapReached):
        _actions(world).rearrange(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            clip_id=made.clip_id,
            segments=tuple(s.model_copy(update={"transition_in": None}) for s in segments),
        )
    assert snap.same(world)


@pytest.mark.parametrize("action", ["retry", "redo", "rearrange", "mode"])
def test_with_the_switch_off_nothing_is_made_again(
    action: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = _world()
    if action == "retry":
        made = _waiting_with_a_failed_part(world)
    else:
        made, _ = _made_clip(world)
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "off")
    snap = _Snapshot(world)
    actions = _actions(world)
    args: dict[str, Any] = {"tenant_id": TENANT_ID, "user_id": USER_ID, "clip_id": made.clip_id}
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        if action == "retry":
            actions.retry_part(part_id=made.part_ids[0], **args)
        elif action == "redo":
            actions.redo_part(part_id=made.part_ids[0], **args)
        elif action == "mode":
            actions.change_part_mode(part_id=made.part_ids[0], mode="edit", **args)
        else:
            actions.rearrange(segments=_brief_of(world, made.clip_id).media.segments, **args)
    assert refused.value.code == "switched_off"
    assert refused.value.owner_message == act.SWITCHED_OFF_TEXT
    assert snap.same(world)


def test_a_mode_the_part_cannot_take_is_refused_before_anything() -> None:
    world = _world()
    made, _ = _made_clip(world)
    snap = _Snapshot(world)
    actions = _actions(world)
    args: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "user_id": USER_ID,
        "clip_id": made.clip_id,
        "part_id": made.part_ids[0],
    }
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        actions.change_part_mode(mode="edit", **args)
    assert refused.value.code == "edit_needs_reel_window"
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        actions.change_part_mode(mode="reference", **args)
    assert refused.value.code == "mode_unchanged"
    assert snap.same(world)


def test_over_the_businesss_dollar_cap_nothing_is_written() -> None:
    from decimal import Decimal

    from qualify_api.creative.parts import PartsOverBudget
    from qualify_api.creative.service import BudgetState

    world = _world()
    made, _ = _made_clip(world)
    world.repo.budget = BudgetState(remaining_usd=Decimal("0.01"), hard_stop=True)
    snap = _Snapshot(world)
    with pytest.raises(PartsOverBudget):
        _actions(world).redo_part(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=made.part_ids[0]
        )
    assert snap.same(world)


# ---------------------------------------------------------------------------
# criterion 2: order, cuts and joins reuse every part


def test_reordering_and_cutting_never_ask_a_part_again(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative.video_pipeline.recipe import CLIP_BLOCK_TRANSITIONS_SWITCH

    monkeypatch.setenv(CLIP_BLOCK_TRANSITIONS_SWITCH, "on")
    world = _world()
    made, keys = _made_clip(world)
    parts = {p: world.repo.drafts[p] for p in made.part_ids}
    part_rows = {k: r for k, r in (world.ledger.rows if world.ledger else {}).items()}
    calls = len(world.dispatcher.calls)
    first, part_one, other, part_two = _brief_of(world, made.clip_id).media.segments
    # the second part first, the first one cut to 3 s, a fade into the owner's video
    fade = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5})
    segments = (
        part_two,
        part_one.model_copy(update={"end_s": part_one.start_s + 3.0}),
        first.model_copy(update={"transition_in": fade}),
        other,
    )
    _actions(world).rearrange(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=made.clip_id,
        segments=segments,
        text_layers=(VideoTextLayer(text="Pide la tuya", start_s=1.0, end_s=3.0),),
    )
    clip = world.repo.drafts[made.clip_id]
    assert clip.status == DRAFTING and clip.revision == 2
    # the Clip only: no part dispatched, made again or charged
    assert world.dispatcher.calls[calls:] == [(TENANT_ID, made.clip_id)]
    assert {p: world.repo.drafts[p] for p in made.part_ids} == parts
    assert world.ledger is not None
    new_rows = {k for k in world.ledger.rows if k not in part_rows}
    assert new_rows == {(made.clip_id, 2)}
    assert world.ledger.rows[(made.clip_id, 2)].price.request_kind == "local_video"
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    brief = _brief_of(world, made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    assert [s.key for s in brief.media.segments] == [keys[1], keys[0], OWN_VIDEO, OTHER]
    assert brief.media.segments[1].end_s == 3.0
    assert {p: world.repo.drafts[p].revision for p in made.part_ids} == {
        p: 1 for p in made.part_ids
    }


def test_a_generated_file_of_another_clip_is_refused() -> None:
    world = _world()
    made, _ = _made_clip(world)
    stranger = SourceSegment(
        key=f"t/{TENANT_ID}/generated/{uuid4()}/r1/video.mp4", start_s=0, end_s=3, speed=1
    )
    segments = (*_brief_of(world, made.clip_id).media.segments, stranger)
    snap = _Snapshot(world)
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        _actions(world).rearrange(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, segments=segments
        )
    assert refused.value.code == "stretch_not_of_clip"
    assert snap.same(world)


def test_a_new_ai_block_after_the_clip_is_made_is_refused() -> None:
    world = _world()
    made, _ = _made_clip(world)
    segments = (*_brief_of(world, made.clip_id).media.segments, _block(0))
    snap = _Snapshot(world)
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        _actions(world).rearrange(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, segments=segments
        )
    assert refused.value.code == "ai_part_added"
    assert snap.same(world)


# ---------------------------------------------------------------------------
# criterion 3: the owner's assembly counts, the automatic one does not


def test_rehacer_charges_one_preview_counts_once_and_the_clip_plays_the_new_file() -> None:
    world = _world()
    made, keys = _made_clip(world)
    part = made.part_ids[0]
    used = world.repo.local_builds_today(tenant_id=TENANT_ID)
    calls = len(world.dispatcher.calls)
    _actions(world).redo_part(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=made.clip_id,
        part_id=part,
        changes=PartChanges(description="La arepa abierta con queso"),
    )
    assert world.ledger is not None
    assert world.ledger.rows[(part, 2)].price.videos == 1
    assert world.repo.drafts[part].status == DRAFTING
    clip = world.repo.drafts[made.clip_id]
    assert (clip.status, clip.revision) == (DRAFTING, 2)
    # the owner's tap: one local build
    assert world.repo.local_builds_today(tenant_id=TENANT_ID) == used + 1
    assert world.dispatcher.calls[calls:] == [(TENANT_ID, part), (TENANT_ID, made.clip_id)]
    with pytest.raises(ca.ClipBlocksWait, match="creating"):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    new_key = _made_again(world, part)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    brief = _brief_of(world, made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    assert [s.key for s in brief.media.segments] == [OWN_VIDEO, new_key, OTHER, keys[1]]
    # the automatic assembly after the part came out counts nothing more
    assert world.repo.local_builds_today(tenant_id=TENANT_ID) == used + 1


def test_a_redo_that_did_not_come_out_keeps_the_previous_part() -> None:
    """The part's failed version keeps the one it had (the generation's rule): the Clip
    is assembled with the old file, never without its part."""
    world = _world()
    made, keys = _made_clip(world)
    part = made.part_ids[0]
    _actions(world).redo_part(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=part
    )
    world.repo.drafts[part] = replace(world.repo.drafts[part], status=GENERATED)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    brief = _brief_of(world, made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    assert [s.key for s in brief.media.segments] == [OWN_VIDEO, keys[0], OTHER, keys[1]]


def test_another_mode_on_a_made_clip_counts_and_is_the_owners_choice() -> None:
    world = _world()
    made = _create(world, _edit_clip(_edit_analysis()))
    _made(world, made.part_ids[0], 4.0)
    _made(world, made.part_ids[1], 4.0)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    used = world.repo.local_builds_today(tenant_id=TENANT_ID)
    edit_part = made.part_ids[0]
    _actions(world).change_part_mode(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=made.clip_id,
        part_id=edit_part,
        mode="reference",
    )
    part = _brief_of(world, edit_part).media.part
    assert part is not None and part.mode == "reference" and part.mode_changed_by_owner
    assert part.index == 1
    assert world.repo.local_builds_today(tenant_id=TENANT_ID) == used + 1
    clip = world.repo.drafts[made.clip_id]
    assert (clip.status, clip.revision) == (DRAFTING, 2)


def test_sigue_a_la_anterior_for_a_part_split_from_the_same_take(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    _split_cuts_checked(monkeypatch)
    world = _world()
    brief = _split_clip()
    entries = brief.media.ai_parts
    # the second part made «Nueva» at «Crear»: the owner asks it back as «Sigue a la anterior»
    brief = _clip(
        brief.media.segments, (entries[0], entries[1].model_copy(update={"mode": "reference"}))
    )
    made = _create(world, brief)
    first, second = made.part_ids
    _fail(world, second)
    _made(world, first)
    _actions(world).change_part_mode(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=second, mode="extend"
    )
    part = _brief_of(world, second).media.part
    assert part is not None and part.mode == "extend" and part.index == 2
    assert _brief_of(world, second).media.clip_reference_mode == "extend"


# ---------------------------------------------------------------------------
# fixtures of a reel


def _edit_analysis() -> UUID:
    return uuid4()


PHOTO = f"uploads/{TENANT_ID}/arepa.jpg"


def _edit_clip(analysis: UUID) -> Any:
    """Own video, an «Igual al original» part (first on the timeline), own video, a
    «Nueva» part — with a product photo (an edit takes one)."""
    return _clip(
        entries=(
            _entry(4),
            _entry(4, mode="edit", analysis_id=analysis, shot_indexes=(1,), original_mode="edit"),
        ),
        segments=(_own(4.0), _block(1, 4), _own(3.0, OTHER), _block(0, 4)),
        clip_image_keys=(PHOTO,),
        clip_image_roles=("product",),
    )


def _split_clip() -> Any:
    """Own video, a part, then «Sigue a la anterior» split from the same take."""
    analysis = uuid4()
    return _clip(
        (_own(4.0), _block(0), _block(1)),
        (
            _entry(5, analysis_id=analysis, shot_indexes=(0, 1)),
            _entry(
                5, mode="extend", analysis_id=analysis, shot_indexes=(1,), original_mode="extend"
            ),
        ),
    )


def _split_cuts_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reel's split cuts are read from the database: offline, they pass."""
    from qualify_api.creative import parts

    monkeypatch.setattr(parts, "check_split_parts_for_tenant", lambda **_: None)


# ---------------------------------------------------------------------------
# «Hacerla nueva» and «Quitar»


def test_make_new_turns_a_failed_igual_al_original_into_nueva() -> None:
    world = _world()
    analysis = _edit_analysis()
    made = _create(world, _edit_clip(analysis))
    edit_part = made.part_ids[0]  # entry 1 is first on the timeline
    assert _brief_of(world, edit_part).media.part.mode == "edit"  # type: ignore[union-attr]
    _fail(world, edit_part, reason="refused_face")
    _actions(world).make_part_new(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=edit_part
    )
    part = _brief_of(world, edit_part).media.part
    assert part is not None and part.mode == "reference" and part.analysis_id == analysis
    assert _brief_of(world, edit_part).media.clip_reference_mode == "motion"
    assert world.repo.drafts[edit_part].status == DRAFTING


def test_remove_drops_the_block_and_the_clip_is_assembled_without_it() -> None:
    world = _world()
    made = _waiting_with_a_failed_part(world)
    rows = dict(world.ledger.rows) if world.ledger else {}
    calls = len(world.dispatcher.calls)
    assert _actions(world).remove_part(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=made.part_ids[0]
    )
    assert made.part_ids[0] in world.repo.removed
    assert world.dispatcher.calls[calls:] == []  # nothing made, nothing charged
    assert world.ledger is not None and world.ledger.rows == rows
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    brief = _brief_of(world, made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    second = world.store.videos[made.part_ids[1]].object_key
    assert [s.key for s in brief.media.segments] == [OWN_VIDEO, OTHER, second]
    # again: removed already
    assert not _actions(world).remove_part(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=made.part_ids[0]
    )


def test_the_only_block_left_is_not_removed() -> None:
    world = _world()
    made = _create(world, _clip((_block(0),), (_entry(5),)))
    _fail(world, made.part_ids[0])
    snap = _Snapshot(world)
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        _actions(world).remove_part(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=made.part_ids[0]
        )
    assert refused.value.code == "last_block"
    assert snap.same(world)


def test_a_sigue_a_la_anterior_after_a_removed_part_becomes_nueva(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    _split_cuts_checked(monkeypatch)
    world = _world()
    made = _create(world, _split_clip())
    first, follower = made.part_ids
    _fail(world, first)
    _fail(world, follower, reason="part_failed")
    _actions(world).remove_part(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=first
    )
    part = _brief_of(world, follower).media.part
    assert part is not None and part.mode == "reference"


def test_the_expired_wait_gives_back_the_preview_of_a_part_tried_again() -> None:
    world = _world()
    made = _waiting_with_a_failed_part(world)
    part = made.part_ids[0]
    _actions(world).retry_part(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=part
    )
    _fail(world, part)
    world.clock[0] += cap.CLIP_AI_PART_OWNER_WAIT
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].failure_reason == cap.AI_PART_EXPIRED
    assert not any(_charged(world, d) for d in (made.clip_id, *made.part_ids))


def test_mode_change_rules() -> None:
    from qualify_creative.schemas import VideoPartPlan

    analysis = uuid4()
    plain = VideoPartPlan(mode="reference", seconds=5, description="x")
    split = VideoPartPlan(
        mode="reference",
        seconds=5,
        description="x",
        analysis_id=analysis,
        shot_indexes=(1,),
        original_mode="extend",
    )
    before = VideoPartPlan(
        mode="reference", seconds=5, description="x", analysis_id=analysis, shot_indexes=(0, 1)
    )

    def code(part: VideoPartPlan, mode: str, previous: VideoPartPlan | None) -> str | None:
        found = act.mode_change_problem(part, mode, previous=previous)
        return None if found is None else found[0]

    assert code(plain, "reference", before) == "mode_unchanged"
    assert code(plain, "edit", before) == "edit_needs_reel_window"
    assert code(plain, "extend", before) == "extend_not_same_moment"
    assert code(split, "extend", None) == "extend_needs_block_before"
    # the same take: this part's first cut is the last of the part before
    assert code(split, "extend", before) is None
    other_take = before.model_copy(update={"shot_indexes": (3,)})
    assert code(split, "extend", other_take) == "extend_not_same_moment"
    with pytest.raises(ValueError, match="mode"):
        act.mode_change_problem(plain, "local", previous=before)


# ---------------------------------------------------------------------------
# review of m-25129407


def test_sigue_a_la_anterior_needs_the_part_right_before_on_the_timeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An own video between the two parts leaves nothing to continue: refused as «Crear»
    refuses it, even when both parts come from the same take."""
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    _split_cuts_checked(monkeypatch)
    world = _world()
    first, second = _split_clip().media.ai_parts
    brief = _clip(
        (_own(4.0), _block(0), _own(3.0, OTHER), _block(1)),
        (first, second.model_copy(update={"mode": "reference"})),
    )
    made = _create(world, brief)
    _made(world, made.part_ids[0])
    _fail(world, made.part_ids[1])
    snap = _Snapshot(world)
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        _actions(world).change_part_mode(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            clip_id=made.clip_id,
            part_id=made.part_ids[1],
            mode="extend",
        )
    assert refused.value.code == "extend_needs_block_before"
    assert snap.same(world)


def test_a_made_clip_offers_redo_only_on_the_parts_it_plays() -> None:
    world = _world()
    made, _ = _made_clip(world)
    first, part_one, other, _part_two = _brief_of(world, made.clip_id).media.segments
    _actions(world).rearrange(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=made.clip_id,
        segments=(first, part_one, other),  # the second part taken out
    )
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    view = _actions(world).parts_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view is not None and not view.waiting
    assert [p.actions for p in view.parts] == [("redo", "change_mode"), ()]
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        _actions(world).redo_part(
            tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=made.part_ids[1]
        )
    assert refused.value.code == "part_not_in_video"


def test_a_redo_left_failed_can_be_made_again() -> None:
    """A version made again that ended failed (the reaper keeps no previous version) is
    not a dead end: its previous file is still in the video and it can be redone."""
    world = _world()
    made, _ = _made_clip(world)
    part = made.part_ids[0]
    args: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "user_id": USER_ID,
        "clip_id": made.clip_id,
        "part_id": part,
    }
    _actions(world).redo_part(**args)
    _fail(world, part)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    view = _actions(world).parts_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view is not None and view.parts[0].actions == ("redo", "change_mode")
    _actions(world).redo_part(**args)
    assert (world.repo.drafts[part].status, world.repo.drafts[part].revision) == (DRAFTING, 3)


def test_a_redo_refused_for_its_photos_is_not_sent_again_with_them() -> None:
    """Re-review: a «Nueva» part whose redo was refused for its photos would fail again
    with them — a paid call for nothing. Only «Cambiar» (new photos) or another mode."""
    world = _world()
    made, _ = _made_clip(world)
    part = made.part_ids[0]
    args: dict[str, Any] = {
        "tenant_id": TENANT_ID,
        "user_id": USER_ID,
        "clip_id": made.clip_id,
        "part_id": part,
    }
    _actions(world).redo_part(**args)
    _fail(world, part, reason="refused_face")
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    view = _actions(world).parts_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view is not None and view.parts[0].actions == ("change_mode",)
    snap = _Snapshot(world)
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        _actions(world).redo_part(**args)
    assert refused.value.code == "part_action_refused"
    assert snap.same(world)
    photo = f"uploads/{TENANT_ID}/otra.jpg"
    _actions(world).redo_part(changes=PartChanges(photo_keys=(photo,)), **args)
    assert world.repo.drafts[part].status == DRAFTING


def test_a_refreshed_stretch_keeps_its_cut_speed_and_join() -> None:
    fade = EffectUse(effect_id="fundido", version=2, params={"duration_s": 0.5})
    old_key = f"t/{TENANT_ID}/generated/{uuid4()}/r1/video.mp4"
    old = SourceSegment(key=old_key, start_s=1.0, end_s=4.0, speed=2, transition_in=fade)
    brief = _clip((_own(4.0), old), ())
    new = cap.AiPartVideo(
        asset_id=uuid4(),
        object_key=f"t/{TENANT_ID}/generated/{uuid4()}/r2/video.mp4",
        seconds=5.0,
        params={"duration_seconds": 5.0, "part": {"seconds": 5, "generation_seconds": 5}},
    )
    (_, stretch) = cap.refresh(brief, {old_key: new}).brief.media.segments
    assert (stretch.key, stretch.start_s, stretch.end_s) == (new.object_key, 1.0, 4.0)
    assert stretch.speed == 2 and stretch.transition_in == fade
