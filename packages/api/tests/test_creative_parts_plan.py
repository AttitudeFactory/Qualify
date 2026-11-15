"""m-24984421: the plan of a video by parts as the owner edited it in «Orden del clip» —
what is refused before anything is written (pure), the `extend` rules a reorder can now
break, and that the parts are numbered by the edited order. Offline; saving and reading
on Postgres (and between businesses) is `test_creative_parts_plan_db.py`."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest
from pydantic import ValidationError
from qualify_creative.schemas import (
    CLIP_MAX_IMAGES,
    PARTS_MAX,
    PARTS_REMOVED_MAX,
    MediaInputs,
    VideoPartPlan,
)

from qualify_api.creative.parts import (
    ExtendOutOfOrder,
    ExtendTooShort,
    PartChanges,
    PartsPlanBusy,
    PartsUnavailable,
    check_extend_parts,
    part_images,
    plan_from_analysis,
)
from qualify_api.creative.parts_plan import (
    MERGED_PARTS_REASON,
    PLAN_EDIT_UNAVAILABLE,
    PLAN_EMPTY,
    PLAN_EXTEND_ORDER,
    PLAN_OTHER_REEL,
    PLAN_REPEATED_CUT,
    PLAN_TOO_LONG,
    PLAN_UNKNOWN_CUT,
    PartsPlanRefused,
    _same_entries,
    check_edited_plan,
    mark_owner_mode_changes,
    merge_short_part,
    save_parts_plan,
)
from qualify_api.referentes.reel_analysis_types import NOT_OBSERVED, OBSERVED, UNKNOWN

from .test_content_service import TENANT_ID, USER_ID
from .test_creative_parts import ANALYSIS_ID, _children, analysis, shot, world

OTHER_REEL = UUID("5e1f0000-0000-4000-8000-0000000000b9")


def _part(*cuts: int, mode: str = "reference", seconds: int = 5, reel: UUID = ANALYSIS_ID):
    return VideoPartPlan(mode=mode, seconds=seconds, analysis_id=reel, shot_indexes=cuts)  # type: ignore[arg-type]


#: Cuts 0-2 of 5 s and cut 3 of 14 s (split by the analysis into a part and its extend).
REEL = analysis(shot(0, 0.0, 5.0), shot(1, 5.0, 10.0), shot(2, 10.0, 15.0), shot(3, 15.0, 29.0))
LONG_HEAD = _part(3, seconds=7)
LONG_TAIL = _part(3, mode="extend", seconds=7)


# ---------------------------------------------------------------------------
# check_extend_parts: what a reorder can break


def test_an_extend_cannot_be_the_first_part_with_or_without_cuts() -> None:
    with pytest.raises(ExtendOutOfOrder):
        check_extend_parts((LONG_TAIL, _part(0)), REEL)
    with pytest.raises(ExtendOutOfOrder):
        check_extend_parts((VideoPartPlan(mode="extend", seconds=5),), None)


def test_an_extend_torn_from_the_part_it_continues_is_refused() -> None:
    # moved after another part: its first cut is no longer the previous part's last
    with pytest.raises(ExtendOutOfOrder):
        check_extend_parts((LONG_HEAD, _part(0), LONG_TAIL), REEL)
    # after a part without cuts (no reel)
    with pytest.raises(ExtendOutOfOrder):
        check_extend_parts((VideoPartPlan(seconds=5), LONG_TAIL), REEL)


def test_an_order_problem_is_not_a_short_cut() -> None:
    assert not issubclass(ExtendOutOfOrder, ExtendTooShort)
    assert not issubclass(ExtendTooShort, ExtendOutOfOrder)


@pytest.mark.parametrize(
    "kept", [(LONG_TAIL, _part(0)), (LONG_HEAD, _part(0), LONG_TAIL)], ids=["first", "torn"]
)
def test_the_edited_plan_says_extend_order(kept: tuple[VideoPartPlan, ...]) -> None:
    with pytest.raises(PartsPlanRefused) as refused:
        check_edited_plan(kept, (), REEL)
    assert refused.value.reason == PLAN_EXTEND_ORDER


def test_a_short_shared_cut_is_a_repeated_cut_not_an_order_problem() -> None:
    """A cut of 10 s or less is never split: two parts on it are a duplicate in the
    edited plan (`check_extend_parts` alone says `ExtendTooShort`, see test_creative_parts)."""
    reel = analysis(shot(0, 0.0, 8.0))
    plan = (_part(0, seconds=4), _part(0, mode="extend", seconds=4))
    with pytest.raises(PartsPlanRefused) as refused:
        check_edited_plan(plan, (), reel)
    assert refused.value.reason == PLAN_REPEATED_CUT
    with pytest.raises(ExtendTooShort):
        check_extend_parts(plan, reel)


def test_an_extend_right_after_its_part_on_a_long_cut_passes() -> None:
    check_extend_parts((_part(0), LONG_HEAD, LONG_TAIL), REEL)


# ---------------------------------------------------------------------------
# check_edited_plan (pure)


@pytest.mark.parametrize("extend_on", [True, False])
def test_the_analysis_plan_reordered_with_a_part_taken_out_passes(extend_on: bool) -> None:
    plan = plan_from_analysis(REEL, extend_on=extend_on)
    # the 14 s cut is split: its tail is born `extend`, made `extend` only with the switch
    assert plan[-1].original_mode == "extend"
    assert plan[-1].mode == ("extend" if extend_on else "reference")
    kept = (plan[2], plan[0], plan[3], plan[4])
    check_edited_plan(kept, (plan[1],), REEL)


def test_an_orphan_extend_made_new_keeps_its_cut() -> None:
    """The screen turns an extend whose part was taken out into «Nueva, inspirada en el
    original»: it still covers the long cut, which the removed part covers too."""
    orphan = LONG_TAIL.model_copy(update={"mode": "reference"})
    check_edited_plan((orphan, _part(0)), (LONG_HEAD,), REEL)


def test_an_empty_plan_is_refused() -> None:
    with pytest.raises(PartsPlanRefused) as refused:
        check_edited_plan((), (_part(0),), REEL)
    assert refused.value.reason == PLAN_EMPTY


def test_only_active_parts_count_towards_the_limit() -> None:
    kept = tuple(VideoPartPlan(seconds=5) for _ in range(PARTS_MAX))
    check_edited_plan(kept, tuple(VideoPartPlan(seconds=5) for _ in range(9)), None)
    with pytest.raises(PartsPlanRefused) as refused:
        check_edited_plan((*kept, VideoPartPlan(seconds=5)), (), None)
    assert refused.value.reason == PLAN_TOO_LONG


def _manual(n: int) -> tuple[VideoPartPlan, ...]:
    """`n` parts added by hand («Añadir parte»): source-free `reference` entries."""
    return tuple(VideoPartPlan(seconds=5, description=f"Parte {i}.") for i in range(n))


def test_the_removed_history_is_bounded() -> None:
    # UI-4: removed parts take no active place, but add-and-remove cannot grow the
    # kept history without limit
    kept = (VideoPartPlan(seconds=5),)
    check_edited_plan(kept, _manual(PARTS_REMOVED_MAX), None)
    with pytest.raises(PartsPlanRefused) as refused:
        check_edited_plan(kept, _manual(PARTS_REMOVED_MAX + 1), None)
    assert refused.value.reason == PLAN_TOO_LONG


def test_the_parent_schema_refuses_an_unbounded_removed_history() -> None:
    # the door `submit_parts_brief(removed_parts=…)` goes through (`build_brief`)
    assert (
        len(MediaInputs(parts_removed=_manual(PARTS_REMOVED_MAX)).parts_removed)
        == PARTS_REMOVED_MAX
    )
    with pytest.raises(ValidationError, match="parts_removed"):
        MediaInputs(parts_removed=_manual(PARTS_REMOVED_MAX + 1))


def test_saving_an_unbounded_removed_history_is_refused_before_the_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.creative import parts_plan

    monkeypatch.setattr(parts_plan, "tenant_session", lambda *a: pytest.fail("no session"))
    with pytest.raises(PartsPlanRefused) as refused:
        save_parts_plan(
            tenant_id=TENANT_ID,
            parent_id=TENANT_ID,
            parts=(VideoPartPlan(seconds=5),),
            removed=_manual(PARTS_REMOVED_MAX + 1),
        )
    assert refused.value.reason == PLAN_TOO_LONG


def test_a_cut_the_analysis_does_not_have_is_refused() -> None:
    with pytest.raises(PartsPlanRefused) as refused:
        check_edited_plan((_part(0), _part(9)), (), REEL)
    assert refused.value.reason == PLAN_UNKNOWN_CUT


@pytest.mark.parametrize(
    ("kept", "removed"),
    [
        ((_part(0), _part(0)), ()),  # the same part twice
        ((_part(0),), (_part(0),)),  # kept and taken out at once
        ((LONG_HEAD, LONG_TAIL, _part(3, mode="extend", seconds=7)), ()),  # 14 s → 2 parts
    ],
)
def test_a_cut_in_more_parts_than_the_analysis_makes_of_it_is_refused(
    kept: tuple[VideoPartPlan, ...], removed: tuple[VideoPartPlan, ...]
) -> None:
    with pytest.raises(PartsPlanRefused) as refused:
        check_edited_plan(kept, removed, REEL)
    assert refused.value.reason == PLAN_REPEATED_CUT


def test_parts_of_another_reel_or_without_the_analysis_are_refused() -> None:
    for reel in (None, replace(analysis(shot(0, 0.0, 5.0)), id=OTHER_REEL)):
        with pytest.raises(PartsPlanRefused) as refused:
            check_edited_plan((_part(0),), (), reel)
        assert refused.value.reason == PLAN_OTHER_REEL


def test_a_plan_without_a_reel_needs_no_analysis() -> None:
    check_edited_plan((VideoPartPlan(seconds=5), VideoPartPlan(seconds=4)), (), None)


def test_parts_removed_belong_to_a_video_by_parts_only() -> None:
    from .test_content_service import make_brief

    with pytest.raises(ValueError, match="plan of parts"):
        make_brief(media=MediaInputs(parts_removed=(VideoPartPlan(seconds=5),)))


# ---------------------------------------------------------------------------
# PartRef.index = the place in the EDITED order


def test_the_parts_are_numbered_by_the_edited_order() -> None:
    plan = plan_from_analysis(REEL)
    edited = (plan[3], plan[0], plan[2])  # long head first; unavailable extend stays removed
    check_edited_plan(edited, (plan[1], plan[4]), REEL)
    parts, _, repo, *_, parent = world(plan=edited)
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, analysis=REEL)
    children = _children(repo, parent)
    assert [c.id for c in children] == ids
    assert [c.part_index for c in children] == [1, 2, 3]
    refs = [repo.get_brief(tenant_id=TENANT_ID, brief_id=c.brief_id).media.part for c in children]
    assert [r.index for r in refs] == [1, 2, 3]
    assert [(r.mode, r.shot_indexes) for r in refs] == [(p.mode, p.shot_indexes) for p in edited]
    assert [s.index for s in parts.parts(tenant_id=TENANT_ID, parent_id=parent)] == [1, 2, 3]


# ---------------------------------------------------------------------------
# The parent's images reach each part with their real role

PHOTOS = {
    "clip_image_keys": ("uploads/t/burger.jpg", "uploads/t/local.jpg", "uploads/t/mood.jpg"),
    "clip_image_roles": ("product", "place", "style"),
}


def _media(**fields: object) -> MediaInputs:
    return MediaInputs(product_keys=("uploads/t/burger.jpg",), **fields)  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", ["reference", "extend", "edit"])
def test_every_part_takes_every_image_with_its_role(mode: str) -> None:
    """Deivid, 2026-11-09: an «Igual al original» part too gets product, place and style."""
    keys, roles = part_images(_media(**PHOTOS), mode)
    assert keys == PHOTOS["clip_image_keys"] and roles == PHOTOS["clip_image_roles"]


def test_a_parent_without_roles_or_images_gives_its_products() -> None:
    no_roles = _media(clip_image_keys=("uploads/t/a.jpg", "uploads/t/b.jpg"))
    assert part_images(no_roles, "reference")[1] == ("product", "product")
    assert part_images(_media(), "reference") == (("uploads/t/burger.jpg",), ("product",))


def test_the_images_stay_within_clip_max_images_and_once_each() -> None:
    # a parent from before m-24984421: up to 10 product photos, a part takes 9
    many = tuple(f"uploads/t/{i}.jpg" for i in range(CLIP_MAX_IMAGES + 1))
    keys, roles = part_images(MediaInputs(product_keys=many), "reference")
    assert keys == many[:CLIP_MAX_IMAGES] and roles == ("product",) * CLIP_MAX_IMAGES
    twice = _media(clip_image_keys=("uploads/t/a.jpg", "uploads/t/a.jpg"))
    assert part_images(twice, "reference")[0] == ("uploads/t/a.jpg",)


def test_each_part_records_the_images_and_roles_it_received() -> None:
    plan = plan_from_analysis(REEL)
    made = (plan[0].model_copy(update={"mode": "reference"}), plan[3])
    assert [p.mode for p in made] == ["reference", "edit"]
    parts, _, repo, *_, parent = world(plan=made, media=PHOTOS)
    parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, analysis=REEL)
    received = []
    for child in _children(repo, parent):
        media = repo.get_brief(tenant_id=TENANT_ID, brief_id=child.brief_id).media
        received.append((media.part.mode, media.clip_image_keys, media.clip_image_roles))
    assert received == [
        ("reference", PHOTOS["clip_image_keys"], PHOTOS["clip_image_roles"]),
        ("edit", PHOTOS["clip_image_keys"], PHOTOS["clip_image_roles"]),
    ]


def test_another_version_of_a_part_keeps_the_roles_of_its_photos() -> None:
    parts, content, repo, *_, parent = world(media=PHOTOS)
    for child_id in parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID):
        content.run_generation(tenant_id=TENANT_ID, draft_id=child_id)
    parts.regenerate_part(
        tenant_id=TENANT_ID,
        parent_id=parent,
        part_index=1,
        changes=PartChanges(photo_keys=("uploads/t/local.jpg", "uploads/t/nuevo.jpg")),
        user_id=USER_ID,
    )
    child = _children(repo, parent)[0]
    media = repo.get_brief(tenant_id=TENANT_ID, brief_id=child.brief_id).media
    assert media.clip_image_keys == ("uploads/t/local.jpg", "uploads/t/nuevo.jpg")
    assert media.clip_image_roles == ("place", "product")


def test_an_edit_part_keeps_a_place_or_style_photo_in_another_version() -> None:
    plan = plan_from_analysis(REEL)
    assert plan[0].mode == "edit"
    parts, content, repo, *_, parent = world(plan=(plan[0],), media=PHOTOS)
    for child_id in parts.create_parts(
        tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, analysis=REEL
    ):
        content.run_generation(tenant_id=TENANT_ID, draft_id=child_id)
    parts.regenerate_part(
        tenant_id=TENANT_ID,
        parent_id=parent,
        part_index=1,
        changes=PartChanges(
            photo_keys=("uploads/t/local.jpg", "uploads/t/burger.jpg", "uploads/t/mood.jpg")
        ),
        user_id=USER_ID,
    )
    child = _children(repo, parent)[0]
    media = repo.get_brief(tenant_id=TENANT_ID, brief_id=child.brief_id).media
    assert media.clip_image_keys == (
        "uploads/t/local.jpg",
        "uploads/t/burger.jpg",
        "uploads/t/mood.jpg",
    )
    assert media.clip_image_roles == ("place", "product", "style")


def test_the_analysis_plan_records_each_entrys_original_mode() -> None:
    plan = plan_from_analysis(REEL, extend_on=True)
    assert [p.original_mode for p in plan] == [p.mode for p in plan]
    assert plan[-1].original_mode == "extend"
    # EF-09: switched off, only the split tail differs — born `extend`, made `reference`
    off = plan_from_analysis(REEL, extend_on=False)
    assert [p.original_mode for p in off] == [p.original_mode for p in plan]
    assert [p.mode for p in off] == [*(p.mode for p in plan[:-1]), "reference"]
    assert VideoPartPlan(seconds=5).original_mode is None  # stored before, or no reel


@pytest.mark.parametrize(
    ("born", "allowed"), [("extend", True), ("reference", False), (None, False)]
)
def test_a_reference_becomes_extend_only_when_born_extend(born: str | None, allowed: bool) -> None:
    saved = _part(3, seconds=7).model_copy(update={"original_mode": born})
    back = saved.model_copy(update={"mode": "extend"})
    assert _same_entries((back,), (saved,)) is allowed
    # the other way (an orphan made new) is always allowed
    assert _same_entries((saved,), (back,))


# ---------------------------------------------------------------------------
# create_parts reads the plan again under the parent's lock


def test_a_plan_saved_between_the_read_and_the_lock_is_the_one_made() -> None:
    """A save landing after `create_parts`' first read: the children follow the plan
    the parent keeps, never the one read before (the join counts `media.parts`)."""
    plan = plan_from_analysis(REEL)
    first, second = (plan[0], plan[1], plan[2]), (plan[2], plan[0])
    parts, _, repo, *_, parent = world(plan=first)
    brief_id = repo.drafts[parent].brief_id
    calls = {"n": 0}
    original = repo.parts_of

    def parts_of(**kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] == 2:  # the check under the lock, on the first attempt
            old = repo.briefs[brief_id]
            media = old.media.model_copy(update={"parts": second, "parts_removed": (plan[1],)})
            repo.briefs[brief_id] = old.model_copy(update={"media": media})
        return original(**kwargs)  # type: ignore[arg-type]

    repo.parts_of = parts_of  # type: ignore[method-assign]
    parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, analysis=REEL)
    children = _children(repo, parent)
    made = [repo.get_brief(tenant_id=TENANT_ID, brief_id=c.brief_id).media.part for c in children]
    assert [(p.shot_indexes, p.index) for p in made] == [((2,), 1), ((0,), 2)]
    assert calls["n"] >= 4  # it started again after the save


def test_a_plan_saved_on_every_attempt_is_plan_busy_not_a_queue_off() -> None:
    plan = plan_from_analysis(REEL)
    plans = ((plan[0], plan[1], plan[2]), (plan[2], plan[0], plan[1]))
    parts, _, repo, ledger, dispatcher, _, parent = world(plan=plans[0])
    brief_id = repo.drafts[parent].brief_id
    calls = {"n": 0}
    original = repo.parts_of

    def parts_of(**kwargs: object) -> object:
        calls["n"] += 1
        if calls["n"] % 2 == 0:  # a save before every lock
            old = repo.briefs[brief_id]
            media = old.media.model_copy(update={"parts": plans[calls["n"] // 2 % 2]})
            repo.briefs[brief_id] = old.model_copy(update={"media": media})
        return original(**kwargs)  # type: ignore[arg-type]

    repo.parts_of = parts_of  # type: ignore[method-assign]
    rows = dict(ledger.rows)
    with pytest.raises(PartsPlanBusy) as busy:
        parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID, analysis=REEL)
    assert busy.value.reason == "plan_busy"
    assert not isinstance(busy.value, PartsUnavailable)
    assert _children(repo, parent) == [] and ledger.rows == rows and dispatcher.calls == []


# ---------------------------------------------------------------------------
# EF-09: the owner changes the mode the rule proposed (`mode_changed_by_owner`)

OWN_VIDEO = f"uploads/{TENANT_ID}/own.mp4"


def test_the_owner_changing_the_rules_mode_is_marked_and_going_back_clears_it() -> None:
    plan = plan_from_analysis(REEL, extend_on=False)
    clean = plan[0]
    assert (clean.mode, clean.mode_reason, clean.mode_rule_version) == (
        "edit",
        "reel_no_people",
        1,
    )
    made_new = clean.model_copy(update={"mode": "reference"})
    check_edited_plan((made_new, *plan[1:]), (), REEL)
    (marked,) = mark_owner_mode_changes((made_new,))
    assert marked.mode_changed_by_owner is True
    # the proposal's provenance is kept as it was
    assert (marked.mode_reason, marked.mode_rule_version) == ("reel_no_people", 1)
    # back to what the rule proposed: not an owner's change any more
    (back,) = mark_owner_mode_changes((marked.model_copy(update={"mode": "edit"}),))
    assert back.mode_changed_by_owner is False
    assert back == clean


def test_a_clean_part_the_rule_made_new_turned_into_edit_is_marked() -> None:
    """reference → edit on a clean part: the split tail the rule made `reference` while
    «Sigue a la anterior» is off (`extend_unavailable`), turned «Igual al original» with
    the owner's own video (a converted tail cannot edit the public source)."""
    plan = plan_from_analysis(REEL, extend_on=False)
    tail = plan[-1]
    assert (tail.mode, tail.original_mode, tail.mode_reason) == (
        "reference",
        "extend",
        "extend_unavailable",
    )
    edited = tail.model_copy(update={"mode": "edit", "clip_video_keys": (OWN_VIDEO,)})
    check_edited_plan((*plan[:-1], edited), (), REEL)
    (marked,) = mark_owner_mode_changes((edited,))
    assert marked.mode_changed_by_owner is True
    assert (marked.mode_reason, marked.mode_rule_version) == ("extend_unavailable", 1)
    # the tail put back to «Sigue a la anterior» (born `extend`) is the owner's too
    (extended,) = mark_owner_mode_changes((tail.model_copy(update={"mode": "extend"}),))
    assert extended.mode_changed_by_owner is True


def test_the_mark_is_the_servers_never_the_entrys() -> None:
    plan = plan_from_analysis(REEL, extend_on=False)
    forged = plan[0].model_copy(update={"mode_changed_by_owner": True})
    assert mark_owner_mode_changes((forged,)) == (plan[0],)
    # no proposal (before the rule, added by hand): never marked
    legacy = VideoPartPlan(mode="edit", seconds=5, clip_video_keys=(OWN_VIDEO,))
    flagged = legacy.model_copy(update={"mode_changed_by_owner": True})
    assert mark_owner_mode_changes((flagged,)) == (legacy,)


@pytest.mark.parametrize(
    ("people", "faces"), [(OBSERVED, OBSERVED), (OBSERVED, NOT_OBSERVED), (UNKNOWN, UNKNOWN)]
)
def test_edit_where_someone_is_or_may_be_seen_is_still_refused(people: str, faces: str) -> None:
    reel = analysis(shot(0, 0.0, 5.0, people=people, faces=faces), shot(1, 5.0, 10.0))
    plan = plan_from_analysis(reel, extend_on=False)
    assert plan[0].mode == "reference"
    assert plan[0].mode_reason in ("reel_people", "people_unclear")
    values = {**plan[0].model_dump(), "mode": "edit"}
    if "people_unclear" in plan[0].notices:
        # the schema itself refuses it (`save_parts_plan` answers `invalid`)
        with pytest.raises(ValidationError):
            VideoPartPlan.model_validate(values)
        values["notices"] = ()
    with pytest.raises(PartsPlanRefused) as refused:
        check_edited_plan((VideoPartPlan.model_validate(values), *plan[1:]), (), reel)
    assert refused.value.reason == PLAN_EDIT_UNAVAILABLE


@pytest.mark.parametrize("extend_on", [True, False])
def test_reordering_or_removing_never_marks(extend_on: bool) -> None:
    plan = plan_from_analysis(REEL, extend_on=extend_on)
    kept, removed = (plan[2], plan[0], plan[3], plan[4]), (plan[1],)
    check_edited_plan(kept, removed, REEL)
    assert mark_owner_mode_changes(kept) == kept
    assert mark_owner_mode_changes(removed) == removed


def test_joining_two_parts_is_not_an_owners_change_of_mode() -> None:
    """«Juntar con la siguiente» forces `edit` with `merged_parts` and no rule version
    (EF-02): never marked, even when the owner had changed one of the two."""
    reel = analysis(shot(0, 0.0, 2.0), shot(1, 2.0, 5.0))
    common = {"analysis_id": reel.id, "mode_rule_version": 1, "mode_reason": "reel_no_people"}
    first = VideoPartPlan(mode="reference", seconds=2, shot_indexes=(0,), **common)
    second = VideoPartPlan(mode="edit", seconds=3, shot_indexes=(1,), **common)
    first, second = mark_owner_mode_changes((first, second))
    assert first.mode_changed_by_owner and not second.mode_changed_by_owner
    merged = merge_short_part(first, second, reel)
    assert (merged.mode, merged.mode_reason, merged.mode_rule_version) == (
        "edit",
        MERGED_PARTS_REASON,
        0,
    )
    assert mark_owner_mode_changes((merged,)) == (merged,)
    assert merged.mode_changed_by_owner is False


def test_a_tail_the_screen_orphaned_is_not_the_owners_change() -> None:
    """With «Sigue a la anterior» on, taking out the head of a long cut makes the screen
    turn its tail «Nueva, inspirada en el original» (`reel_parts_vm._settle`): the owner
    did not choose that mode, so it is not marked — as the same removal is not with the
    switch off. A tail still right after its head turned `reference` by hand is."""
    plan = plan_from_analysis(REEL, extend_on=True)
    head, tail = plan[-2], plan[-1]
    assert (tail.mode, tail.mode_reason) == ("extend", "split_cut_continues")
    orphan = tail.model_copy(update={"mode": "reference"})
    kept, removed = (*plan[:-2], orphan), (head,)
    check_edited_plan(kept, removed, REEL)
    assert mark_owner_mode_changes(kept) == kept
    assert mark_owner_mode_changes(removed, removed=True) == removed
    # moved away from its head (another part in between): the screen's too
    moved = (head, plan[0], orphan, *plan[1:-2])
    assert mark_owner_mode_changes(moved)[2].mode_changed_by_owner is False
    # the orphan later taken out as well: never marked among the removed
    assert mark_owner_mode_changes((head, orphan), removed=True) == (head, orphan)
    # still attached to its head and made new by hand: the owner's change
    attached = (*plan[:-1], orphan)
    check_edited_plan(attached, (), REEL)
    *_, marked = mark_owner_mode_changes(attached)
    assert marked.mode_changed_by_owner is True
    assert (marked.mode_reason, marked.mode_rule_version) == ("split_cut_continues", 1)


# EF-09: the mode rule's provenance is the server's — a save that rewrites it is
# `not_in_plan` (`_same_entries` false → `PLAN_NOT_SAVED` in `save_parts_plan`)


@pytest.mark.parametrize(
    "forged",
    [
        {"mode_reason": "reel_people"},  # another known reason: decides the mark
        {"mode_reason": "extend_unavailable", "mode": "edit"},
        {"mode_rule_version": 0},  # «before the rule»: never marked
        {"mode_rule_version": 2},
    ],
)
def test_a_forged_mode_provenance_is_not_the_saved_plan(forged: dict[str, object]) -> None:
    saved = plan_from_analysis(REEL, extend_on=False)
    assert saved[0].mode_rule_version == 1 and saved[0].mode_reason == "reel_no_people"
    entry = saved[0].model_copy(update=forged)
    assert not _same_entries((entry, *saved[1:]), saved, REEL, active_count=len(saved))
    # changing only the mode, the provenance as saved, still matches
    made_new = saved[0].model_copy(update={"mode": "reference"})
    assert _same_entries((made_new, *saved[1:]), saved, REEL, active_count=len(saved))


@pytest.mark.parametrize(
    "provenance",
    [
        {"mode_rule_version": 1, "mode_reason": "reel_no_people"},
        {"mode_rule_version": 1},
        {"mode_reason": "no_source"},
    ],
)
def test_a_part_added_by_hand_cannot_claim_the_rule_proposed_it(
    provenance: dict[str, object],
) -> None:
    added = VideoPartPlan(mode="reference", seconds=5, notices=("describe_it",))
    assert _same_entries((added,), ())
    forged = added.model_copy(update=provenance)
    assert not _same_entries((forged,), ())


def test_joining_still_matches_its_candidate_and_its_provenance_is_held() -> None:
    reel = analysis(shot(0, 0.0, 2.0), shot(1, 2.0, 5.0))
    common = {"analysis_id": reel.id, "mode_rule_version": 1, "mode_reason": "reel_no_people"}
    saved = (
        VideoPartPlan(mode="edit", seconds=2, shot_indexes=(0,), **common),
        VideoPartPlan(mode="edit", seconds=3, shot_indexes=(1,), **common),
    )
    merged = merge_short_part(*saved, reel)
    kw = {"merge_sources": saved, "active_count": 1}
    assert _same_entries((merged,), saved, reel, **kw)
    for forged in ({"mode_reason": "reel_no_people"}, {"mode_rule_version": 1}):
        assert not _same_entries((merged.model_copy(update=forged),), saved, reel, **kw)
