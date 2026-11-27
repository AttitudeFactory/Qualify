"""m-25142982: a NEW «parte con IA» added to a Clip that is already made and not approved
(«Por aprobar») — ONE child made, 1 vista previa, the Clip assembled again with every
other part reused.

Acceptance criteria pinned here:

1. only that child is created (1 vista previa, all or nothing with the Clip's own row,
   before any write); the Clip is assembled again once it is made, its other parts
   reused untouched; idempotent with `request_key`;
2. the caps: 6 AI children (scenes included), 8 blocks, 60 s;
3. refused on an approved Clip and while anything of it is being made;
4. placed at the owner's position; «Sigue a la anterior» only right after the AI part it
   continues (the rules of «Rehacer», m-25129407).

Offline only: no BytePlus, Seedance or Claude is called — the database is a set of dicts."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from qualify_creative.schemas import (
    SourceSegment,
    VideoPartPlan,
    VideoTextLayer,
)

from qualify_api.creative import clip_ai_part_actions as act
from qualify_api.creative import clip_ai_parts as cap
from qualify_api.creative import clip_avatar as ca
from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.fsm import APPROVED, DRAFTING, GENERATED, REJECTED
from qualify_api.creative.local_cap import LocalDailyCapReached
from qualify_api.creative.part_extend import EXTEND_SWITCH
from qualify_api.creative.video_pipeline.ai_parts import CLIP_AI_PARTS_SWITCH
from qualify_api.creative.video_pipeline.recipe import RecipeRefused

from .test_clip_ai_part_actions import (
    _actions,
    _fail,
    _made_clip,
    _Snapshot,
    _spend_the_local_cap,
    _split_cuts_checked,
    _use_every_preview,
)
from .test_clip_ai_parts import (
    OTHER,
    World,
    _brief_of,
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
from .test_content_service import TENANT_ID, USER_ID

__all__ = [  # fixtures used by name, or autouse
    "_switches",
    "assemble_at_the_sources_size",
    "assembly_files",
    "no_normalize_jobs",
    "queue_on",
]


def _add(world: World, clip_id: UUID, entry: VideoPartPlan | None = None, **kw: object) -> UUID:
    position = kw.pop("position", None)
    if position is None:
        position = len(_brief_of(world, clip_id).media.segments)
    return _actions(world).add_part(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=clip_id,
        entry=entry or _entry(5, description="La arepa servida en la mesa"),
        position=position,  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


def _refused(world: World, clip_id: UUID, **kw: object) -> str:
    snap = _Snapshot(world)
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        _add(world, clip_id, **kw)  # type: ignore[arg-type]
    assert snap.same(world), "a refusal writes, charges and dispatches nothing"
    return refused.value.code


# ---------------------------------------------------------------------------
# criterion 1: one child, 1 vista previa, the Clip again with the others reused


def test_a_new_part_is_one_child_one_preview_and_the_clip_plays_it_with_the_others() -> None:
    world = _world()
    made, keys = _made_clip(world)
    first, second = made.part_ids
    before = {
        p: (world.repo.drafts[p].revision, world.repo.drafts[p].brief_id) for p in made.part_ids
    }
    used = world.repo.local_builds_today(tenant_id=TENANT_ID)
    calls = len(world.dispatcher.calls)
    view = _actions(world).parts_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view is not None and view.can_add_part  # «Agregar → Parte con IA» offered

    new = _add(world, made.clip_id)
    view = _actions(world).parts_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view is not None and not view.can_add_part  # busy while it is made

    child = world.repo.drafts[new]
    assert (child.status, child.revision) == (DRAFTING, 1)
    assert world.repo.parents[new] == (made.clip_id, 3)  # the place after every child
    part = _brief_of(world, new).media.part
    assert part is not None and part.index == 3 and part.description.startswith("La arepa")
    assert world.ledger is not None
    assert world.ledger.rows[(new, 1)].price.videos == 1  # one vista previa
    clip = world.repo.drafts[made.clip_id]
    assert (clip.status, clip.revision) == (DRAFTING, 2)
    assert (made.clip_id, 2) in world.ledger.rows  # the Clip's own row, 0 creations
    # the owner's tap assembles the Clip again: one local build of today
    assert world.repo.local_builds_today(tenant_id=TENANT_ID) == used + 1
    assert world.dispatcher.calls[calls:] == [(TENANT_ID, new), (TENANT_ID, made.clip_id)]
    # nothing of the other parts moved: not asked again, not charged again
    assert {
        p: (world.repo.drafts[p].revision, world.repo.drafts[p].brief_id) for p in made.part_ids
    } == before
    assert (first, 2) not in world.ledger.rows and (second, 2) not in world.ledger.rows

    with pytest.raises(ca.ClipBlocksWait, match="creating"):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    new_key = _made(world, new, 5.0)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    brief = _brief_of(world, made.clip_id)
    assert [s.key for s in brief.media.segments] == [OWN_VIDEO, keys[0], OTHER, keys[1], new_key]
    assert brief.media.ai_parts == () and brief.media.derived_from_brief_id is not None
    # the automatic assembly after the part came out counts nothing more
    assert world.repo.local_builds_today(tenant_id=TENANT_ID) == used + 1
    view = _actions(world).parts_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view is not None and [p.part_id for p in view.parts] == [first, second, new]
    assert view.parts[2].actions == ("redo", "change_mode")


def test_a_part_in_the_middle_moves_what_comes_after_it() -> None:
    world = _world()
    made, keys = _made_clip(world)
    current = _brief_of(world, made.clip_id)
    texts = (
        VideoTextLayer(text="Antes", start_s=1.0, end_s=3.0),
        VideoTextLayer(text="Cruza", start_s=8.0, end_s=10.0),
        VideoTextLayer(text="Después", start_s=12.0, end_s=14.0),
    )
    world.repo.briefs[world.repo.drafts[made.clip_id].brief_id] = current.model_copy(
        update={"media": current.media.model_copy(update={"text_layers": texts})}
    )
    # after the owner's video and the first part: 4 s + 5 s = second 9
    new = _add(world, made.clip_id, _entry(4, description="Las manos amasando"), position=2)
    brief = _brief_of(world, made.clip_id)
    assert [s.kind for s in brief.media.segments] == ["video", "video", "ai_part", "video", "video"]
    assert brief.media.ai_parts[0].seconds == 4
    assert [(t.start_s, t.end_s) for t in brief.media.text_layers] == [
        (1.0, 3.0),
        (8.0, 14.0),
        (16.0, 18.0),
    ]
    new_key = _made(world, new, 4.0)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    segments = _brief_of(world, made.clip_id).media.segments
    assert [s.key for s in segments] == [OWN_VIDEO, keys[0], new_key, OTHER, keys[1]]


def test_the_same_tap_twice_adds_one_part_and_dispatches_once() -> None:
    world = _world()
    made, _ = _made_clip(world)
    key = uuid4()
    new = _add(world, made.clip_id, request_key=key)
    snap = _Snapshot(world)
    assert _add(world, made.clip_id, request_key=key) == new
    assert snap.same(world)


def test_a_plain_clip_without_ai_parts_takes_its_first_one() -> None:
    world = _world()
    plain = _plain_draft(world)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=plain)
    assert world.repo.drafts[plain].status == GENERATED
    assert _actions(world).parts_view(tenant_id=TENANT_ID, clip_id=plain) is None
    assert _actions(world).can_add_part(tenant_id=TENANT_ID, clip_id=plain)
    new = _add(world, plain, position=1)
    assert world.repo.parents[new] == (plain, 1)
    new_key = _made(world, new, 5.0)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=plain)
    segments = _brief_of(world, plain).media.segments
    assert [s.key for s in segments] == [OWN_VIDEO, new_key, OTHER]
    # a Clip with an AI part waits for PR 4 to be approved, as any other
    with pytest.raises(cap.ClipAiPartsRefused, match=cap.APPROVE_UNAVAILABLE_CODE):
        cap.refuse_ai_parts_approval(world.store, tenant_id=TENANT_ID, clip_id=plain)


def _plain_draft(world: World) -> UUID:
    return world.content.create_draft(
        tenant_id=TENANT_ID,
        brand_id=_clip().brand_id,
        user_id=USER_ID,
        brief=_clip((_own(4.0), _own(3.0, OTHER)), ()),
    )


# ---------------------------------------------------------------------------
# what a new part that does not come out leaves


def test_a_new_part_that_failed_waits_for_the_owner_who_can_retry_it() -> None:
    world = _world()
    made, _ = _made_clip(world)
    new = _add(world, made.clip_id)
    _fail(world, new)
    with pytest.raises(ca.ClipBlocksWait, match="part_failed"):
        world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    view = _actions(world).parts_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view is not None and view.waiting and view.needs_attention
    failed = next(p for p in view.parts if p.part_id == new)
    assert failed.actions == ("retry", "change", "change_mode", "remove")
    assert not _actions(world).can_add_part(tenant_id=TENANT_ID, clip_id=made.clip_id)
    _actions(world).retry_part(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=new
    )
    assert world.repo.drafts[new].status == DRAFTING
    _made(world, new)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED


def test_removing_the_failed_new_part_gives_back_the_video_as_it_was() -> None:
    world = _world()
    made, keys = _made_clip(world)
    new = _add(world, made.clip_id, position=1)
    _fail(world, new)
    assert _actions(world).remove_part(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=new
    )
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    segments = _brief_of(world, made.clip_id).media.segments
    assert [s.key for s in segments] == [OWN_VIDEO, keys[0], OTHER, keys[1]]


def test_when_the_owners_time_runs_out_the_clip_keeps_its_video_and_nothing_else_returns() -> None:
    """A made Clip never fails for a part added to it: it is assembled without it, and
    the vistas previas of its other parts (spent on the video the owner has) stay spent."""
    world = _world()
    made, keys = _made_clip(world)
    new = _add(world, made.clip_id)
    _fail(world, new)
    assert world.ledger is not None
    kept = {p: world.ledger.rows[(p, 1)] for p in made.part_ids}
    world.clock[0] += cap.CLIP_AI_PART_OWNER_WAIT + timedelta(minutes=1)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    segments = _brief_of(world, made.clip_id).media.segments
    assert [s.key for s in segments] == [OWN_VIDEO, keys[0], OTHER, keys[1]]
    assert {p: world.ledger.rows[(p, 1)] for p in made.part_ids} == kept


def test_the_gate_places_the_added_part_after_every_child() -> None:
    rows = (
        cap.AiPartRow(id=uuid4(), slot=1, status=GENERATED),
        cap.AiPartRow(id=uuid4(), slot=2, status=GENERATED, removed=True),
        cap.AiPartRow(id=uuid4(), slot=3, status=DRAFTING),
    )
    current = _clip((_own(4.0),), ())
    added = act.with_block_added(current, _entry(5), 1, origin=uuid4())
    assert cap.is_added_part_brief(added)
    assert cap.entry_slots(added, rows) == {0: 3}
    # «Crear» brief: its blocks in timeline order, as before
    assert not cap.is_added_part_brief(_clip())
    assert cap.entry_slots(_clip(), rows) == {1: 1, 0: 2}


# ---------------------------------------------------------------------------
# criteria 2 and 3: the caps and the Clip's state, all before any write


def test_with_the_switch_off_nothing_is_added(monkeypatch: pytest.MonkeyPatch) -> None:
    world = _world()
    made, _ = _made_clip(world)
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "off")
    assert _refused(world, made.clip_id) == "switched_off"
    assert not _actions(world).can_add_part(tenant_id=TENANT_ID, clip_id=made.clip_id)


def test_an_approved_clip_takes_no_new_part() -> None:
    world = _world()
    made, _ = _made_clip(world)
    world.repo.drafts[made.clip_id] = replace(world.repo.drafts[made.clip_id], status=APPROVED)
    assert _refused(world, made.clip_id) == "clip_approved"
    assert not _actions(world).can_add_part(tenant_id=TENANT_ID, clip_id=made.clip_id)


def test_a_rejected_clip_still_waiting_for_approval_takes_one() -> None:
    world = _world()
    made, _ = _made_clip(world)
    world.repo.drafts[made.clip_id] = replace(world.repo.drafts[made.clip_id], status=REJECTED)
    _add(world, made.clip_id)
    assert world.repo.drafts[made.clip_id].status == DRAFTING


def test_nothing_is_added_while_the_clip_or_a_part_is_being_made() -> None:
    world = _world()
    waiting = _create(world)
    assert _refused(world, waiting.clip_id) == "clip_not_made"
    made, _ = _made_clip(world)
    _actions(world).redo_part(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=made.part_ids[0]
    )
    assert _refused(world, made.clip_id) == "clip_busy"
    # the Clip made, a part (or a final) still being made: busy too
    world.repo.drafts[made.clip_id] = replace(world.repo.drafts[made.clip_id], status=GENERATED)
    assert _refused(world, made.clip_id) == "clip_busy"
    assert not _actions(world).can_add_part(tenant_id=TENANT_ID, clip_id=made.clip_id)


def test_six_ai_children_or_every_place_taken_refuse() -> None:
    world = _world()
    made, _ = _made_clip(world)
    for slot in (3, 4, 5, 6):
        # other children of the Clip (a scene's place, say): not AI parts, same places
        other = uuid4()
        world.repo.drafts[other] = replace(
            world.repo.drafts[made.clip_id], id=other, parent_draft_id=made.clip_id
        )
        world.repo.parents[other] = (made.clip_id, slot)
    assert _refused(world, made.clip_id) == "too_many_ai_children"
    # a removed part keeps its place: 5 kept children, but no place 7
    removed = next(d for d, (c, s) in world.repo.parents.items() if c == made.clip_id and s == 6)
    world.repo.removed.add(removed)
    assert _refused(world, made.clip_id) == "no_place_left"
    assert not _actions(world).can_add_part(tenant_id=TENANT_ID, clip_id=made.clip_id)


def test_more_than_eight_blocks_or_sixty_seconds_are_refused() -> None:
    world = _world()
    made, _ = _made_clip(world)
    current = _brief_of(world, made.clip_id)
    many = (*current.media.segments, *(_own(2.0) for _ in range(4)))  # 8 blocks
    world.repo.briefs[world.repo.drafts[made.clip_id].brief_id] = current.model_copy(
        update={"media": current.media.model_copy(update={"segments": many})}
    )
    assert not _actions(world).can_add_part(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert _refused(world, made.clip_id) == "too_many_blocks"

    world = _world()
    made, _ = _made_clip(world)
    current = _brief_of(world, made.clip_id)
    long = (*current.media.segments, _own(40.0))  # 16 s + 40 s, then a part of 5 s
    world.repo.briefs[world.repo.drafts[made.clip_id].brief_id] = current.model_copy(
        update={"media": current.media.model_copy(update={"segments": long})}
    )
    snap = _Snapshot(world)
    with pytest.raises(RecipeRefused) as refused:
        _add(world, made.clip_id)
    assert "local_length_out_of_range" in {p.code for p in refused.value.problems}
    assert snap.same(world)


def test_a_part_with_nothing_to_make_it_from_or_a_foreign_photo_is_refused() -> None:
    world = _world()
    made, _ = _made_clip(world)
    assert _refused(world, made.clip_id, entry=_entry(5, description=" ")) == (
        "ai_part_needs_description"
    )
    foreign = _entry(5, clip_image_keys=(f"uploads/{uuid4()}/ajena.jpg",))
    assert _refused(world, made.clip_id, entry=foreign) == "ai_part_file_not_owned"


def test_todays_local_cap_and_the_month_are_checked_before_anything() -> None:
    world = _world()
    made, _ = _made_clip(world)
    _spend_the_local_cap(world)
    snap = _Snapshot(world)
    with pytest.raises(LocalDailyCapReached):
        _add(world, made.clip_id)
    assert snap.same(world)

    world = _world()
    made, _ = _made_clip(world)
    _use_every_preview(world)
    snap = _Snapshot(world)
    with pytest.raises(NotEnoughCreations):
        _add(world, made.clip_id)
    assert snap.same(world)


# ---------------------------------------------------------------------------
# criterion 4: «Sigue a la anterior» right after the part it continues


def _split_made(world: World) -> tuple[cap.ClipWithAiParts, UUID]:
    """A made Clip: own video, then a part split from a take of the reel."""
    analysis = uuid4()
    made = _create(
        world,
        _clip((_own(4.0), _block_at(0)), (_entry(5, analysis_id=analysis, shot_indexes=(0, 1)),)),
    )
    _made(world, made.part_ids[0], 5.0)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    return made, analysis


def _block_at(n: int, seconds: int = 5) -> SourceSegment:
    from .test_clip_ai_parts import _block

    return _block(n, seconds)


def _follower(analysis: UUID, shot: int = 1) -> VideoPartPlan:
    return _entry(
        5,
        mode="extend",
        analysis_id=analysis,
        shot_indexes=(shot,),
        original_mode="extend",
    )


def test_sigue_a_la_anterior_right_after_the_part_it_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    _split_cuts_checked(monkeypatch)
    world = _world()
    made, analysis = _split_made(world)
    new = _add(world, made.clip_id, _follower(analysis), position=2)
    part = _brief_of(world, new).media.part
    assert part is not None and part.mode == "extend" and part.index == 2
    assert part.extend_own is None  # it continues the part, never the stretch playing it


def test_sigue_a_la_anterior_without_the_part_right_before_or_from_another_moment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    _split_cuts_checked(monkeypatch)
    world = _world()
    made, analysis = _split_made(world)
    # right after the owner's own video, before the part
    assert (
        _refused(world, made.clip_id, entry=_follower(analysis), position=1)
        == "extend_needs_block_before"
    )
    # at the very start
    assert (
        _refused(world, made.clip_id, entry=_follower(analysis), position=0)
        == "extend_needs_block_before"
    )
    # right after the part, but from another moment of the reel
    assert (
        _refused(world, made.clip_id, entry=_follower(analysis, shot=3), position=2)
        == "extend_not_same_moment"
    )


def test_sigue_a_la_anterior_after_a_part_whose_redo_failed_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review of m-25142982: its old file still plays, but the producer only continues a
    made part — a follower would wait for ever."""
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    _split_cuts_checked(monkeypatch)
    world = _world()
    made, analysis = _split_made(world)
    part = made.part_ids[0]
    _actions(world).redo_part(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=part
    )
    _fail(world, part)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    assert (
        _refused(world, made.clip_id, entry=_follower(analysis), position=2)
        == "extend_needs_block_before"
    )


def test_a_part_left_out_offers_nothing_and_holds_no_part_of_the_six() -> None:
    """Review of m-25142982: an added part whose owner's time ran out is not in the video.
    While a second added part is awaited, only that one can be retried or removed — never
    a vista previa for the one left out — and it does not count in the 6."""
    world = _world()
    made, _ = _made_clip(world)
    left_out = _add(world, made.clip_id)
    _fail(world, left_out)
    world.clock[0] += cap.CLIP_AI_PART_OWNER_WAIT + timedelta(minutes=1)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    view = _actions(world).parts_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view is not None and view.can_add_part
    assert next(p for p in view.parts if p.part_id == left_out).actions == ()
    second = _add(world, made.clip_id)
    assert world.repo.parents[second] == (made.clip_id, 4)
    _fail(world, second)
    view = _actions(world).parts_view(tenant_id=TENANT_ID, clip_id=made.clip_id)
    assert view is not None and view.needs_attention
    actions = {p.part_id: p.actions for p in view.parts}
    assert actions[left_out] == () and "retry" in actions[second]
    for act_on in (_actions(world).retry_part, _actions(world).remove_part):
        snap = _Snapshot(world)
        with pytest.raises(cap.ClipAiPartsRefused) as refused:
            act_on(tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=left_out)
        assert refused.value.code == "part_not_in_video"
        assert snap.same(world)


def test_no_place_left_says_why_for_a_part_removed_or_left_out() -> None:
    """Review N1 of m-25142982: the place of a part that did not come out is lost too —
    the owner reads both causes, never only «las que quitaste»."""
    places = tuple((slot, slot == 2) for slot in range(1, 7))  # place 2 removed
    left_out = frozenset({5})  # an added part whose owner's time ran out
    problem = act.ClipAiPartActions._place_problem(places, left_out)  # noqa: SLF001
    assert problem == ("no_place_left", act.NO_PLACE_LEFT_TEXT)
    assert "quitaste" in act.NO_PLACE_LEFT_TEXT and "no salieron" in act.NO_PLACE_LEFT_TEXT


def test_a_position_off_the_timeline_is_a_moved_clip() -> None:
    world = _world()
    made, _ = _made_clip(world)
    assert _refused(world, made.clip_id, position=9) == "clip_moved"
