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
    PLAN_EMPTY,
    PLAN_EXTEND_ORDER,
    PLAN_OTHER_REEL,
    PLAN_REPEATED_CUT,
    PLAN_TOO_LONG,
    PLAN_UNKNOWN_CUT,
    PartsPlanRefused,
    _same_entries,
    check_edited_plan,
    save_parts_plan,
)

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


def test_the_analysis_plan_reordered_with_a_part_taken_out_passes() -> None:
    plan = plan_from_analysis(REEL)
    assert [p.mode for p in plan][-1] == "extend"  # the 14 s cut is split
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
    plan = plan_from_analysis(REEL)
    assert [p.original_mode for p in plan] == [p.mode for p in plan]
    assert plan[-1].original_mode == "extend"
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
