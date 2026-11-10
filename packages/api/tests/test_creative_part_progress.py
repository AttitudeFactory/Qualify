"""m-24921082 (UI-7): the nine states of a part on its video's result screen, derived from
what is stored, and the owner's actions on a part that did not come out. Offline: pure
rules, and the actions over the in-memory world of `test_creative_parts`. The read under
RLS is in `test_creative_part_progress_db.py`."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from qualify_creative.creations import weight_for

from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.fsm import (
    APPROVED,
    DRAFTING,
    FAILED,
    GENERATED,
    PUBLISHED,
    DraftTrigger,
    apply_transition,
)
from qualify_api.creative.part_actions import (
    PART_ALREADY_NEW_TEXT,
    PART_BEING_MADE_TEXT,
    PART_NOT_FAILED_TEXT,
    PART_ONLY_NEW_TEXT,
    PART_RETRY_AS_IS_TEXT,
    PART_SAME_PHOTOS_TEXT,
    PartRecovery,
)
from qualify_api.creative.part_progress import (
    SERVED_ACTIONS,
    PartAction,
    PartFacts,
    PartState,
    derive_progress,
    derive_state,
)
from qualify_api.creative.parts import PartChangeRefused, PartChanges

from .test_content_service import BRAND_ID, TENANT_ID, USER_ID
from .test_creative_parts import _children, world

NOW = 1_800_000_000.0
DAY = 24 * 3600.0
PARENT = UUID("7a7a0000-0000-4000-8000-000000000001")


def facts(index: int = 1, **kw: object) -> PartFacts:
    base: dict[str, object] = {"index": index, "mode": "reference", "seconds": 4}
    if kw.get("status") in (GENERATED, APPROVED, "rejected"):
        base.update(
            draft_id=uuid4(), has_video=True, preview={"status": "draft", "created_at": NOW - 60}
        )
    elif "status" in kw:
        base["draft_id"] = uuid4()
    base.update(kw)
    return PartFacts(**base)  # type: ignore[arg-type]


def state(f: PartFacts, previous: PartFacts | None = None, **kw: object) -> PartState:
    return derive_state(f, previous, now=NOW, **kw).state  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# the nine states


def test_unmade_a_planned_part_without_child() -> None:
    row = derive_state(facts(), None, now=NOW)
    assert row.state is PartState.UNMADE and not row.has_preview
    # m-24921081: «Crear esta parte»
    assert row.actions == (PartAction.CREATE,) and PartAction.CREATE not in SERVED_ACTIONS


def test_an_unmade_extend_is_not_created_alone_nor_under_a_purged_video() -> None:
    made = facts(1, status=GENERATED)
    alone = derive_state(facts(2, mode="extend"), facts(1), now=NOW)
    after = derive_state(facts(2, mode="extend"), made, now=NOW)
    purged = derive_state(facts(1), None, now=NOW, parent_purged=True)
    assert alone.state is PartState.UNMADE and alone.actions == ()
    assert after.actions == (PartAction.CREATE,)
    assert purged.state is PartState.UNMADE and purged.actions == ()


def test_the_owners_ask_rides_with_the_progress() -> None:
    from qualify_creative.schemas import PartsRequest

    asked = PartsRequest(scope="first", refused="not_enough_previews", missing=1)
    progress = derive_progress(PARENT, [facts(1), facts(2)], now=NOW, request=asked)
    assert progress.request == asked
    assert derive_progress(PARENT, [facts(1)], now=NOW).request is None


def test_queued_while_every_job_waits() -> None:
    assert state(facts(status=DRAFTING, jobs=("queued",))) is PartState.QUEUED


def test_creating_once_a_job_is_taken_or_without_queue() -> None:
    assert state(facts(status=DRAFTING, jobs=("claimed",))) is PartState.CREATING
    assert state(facts(status=DRAFTING, jobs=("submitted",))) is PartState.CREATING
    assert state(facts(status=DRAFTING)) is PartState.CREATING  # threads: no job row


def test_an_extend_in_line_waits_for_the_previous_part() -> None:
    previous = facts(1, status=DRAFTING, jobs=("claimed",))
    waiting = facts(2, mode="extend", status=DRAFTING, jobs=("queued",))
    row = derive_state(waiting, previous, now=NOW)
    assert row.state is PartState.QUEUED and row.waiting_for == 1


def test_an_extend_taken_by_the_vendor_is_creating_not_waiting() -> None:
    previous = facts(1, status=DRAFTING)
    taken = facts(2, mode="extend", status=DRAFTING, jobs=("claimed",))
    assert state(taken, previous) is PartState.CREATING


def test_an_extend_whose_previous_is_ready_is_only_queued() -> None:
    row = derive_state(
        facts(2, mode="extend", status=DRAFTING, jobs=("queued",)),
        facts(1, status=GENERATED),
        now=NOW,
    )
    assert row.state is PartState.QUEUED and row.waiting_for is None


def test_to_review_with_a_live_preview() -> None:
    row = derive_state(facts(status=GENERATED), None, now=NOW)
    assert row.state is PartState.TO_REVIEW and row.has_preview and row.actions == ()


def test_ready_once_approved_with_the_whole_video() -> None:
    row = derive_state(facts(status=APPROVED), None, now=NOW)
    assert row.state is PartState.READY and row.has_preview


def test_failed_offers_retry_change_remove() -> None:
    row = derive_state(facts(status=FAILED, failure_reason="provider_error"), None, now=NOW)
    assert row.state is PartState.FAILED
    assert row.actions == (PartAction.RETRY, PartAction.CHANGE, PartAction.REMOVE)


def test_a_new_part_refused_for_its_photos_is_not_retried_as_is() -> None:
    row = derive_state(facts(status=FAILED, failure_reason="refused_face"), None, now=NOW)
    assert row.state is PartState.FAILED
    assert row.actions == (PartAction.CHANGE, PartAction.REMOVE)


@pytest.mark.parametrize(
    "reason",
    [
        "refused_face",
        "source_purged",
        "not_edit_eligible",
        "analysis_not_ready",
        "window_unavailable",
    ],
)
def test_original_refused_on_an_edit_part(reason: str) -> None:
    row = derive_state(facts(mode="edit", status=FAILED, failure_reason=reason), None, now=NOW)
    assert row.state is PartState.ORIGINAL_REFUSED
    assert row.actions == (PartAction.MAKE_NEW, PartAction.REMOVE)


def test_an_edit_part_that_failed_for_our_reason_keeps_its_form() -> None:
    row = derive_state(
        facts(mode="edit", status=FAILED, failure_reason="part_failed"), None, now=NOW
    )
    assert row.state is PartState.FAILED and PartAction.MAKE_NEW not in row.actions


def test_redo_when_the_previous_part_changed_after_this_one() -> None:
    previous = facts(1, status=GENERATED, preview={"status": "draft", "created_at": NOW - 10})
    mine = facts(
        2, mode="extend", status=GENERATED, preview={"status": "draft", "created_at": NOW - 100}
    )
    row = derive_state(mine, previous, now=NOW)
    assert row.state is PartState.REDO and row.changed_part == 1
    assert row.actions == (PartAction.RECREATE,) and row.has_preview


def test_an_extend_made_after_its_previous_is_fine() -> None:
    previous = facts(1, status=GENERATED, preview={"status": "draft", "created_at": NOW - 100})
    mine = facts(
        2, mode="extend", status=GENERATED, preview={"status": "draft", "created_at": NOW - 10}
    )
    assert state(mine, previous) is PartState.TO_REVIEW


def test_expired_after_seven_days() -> None:
    old = facts(status=GENERATED, preview={"status": "draft", "created_at": NOW - 8 * DAY})
    row = derive_state(old, None, now=NOW)
    assert row.state is PartState.EXPIRED and row.actions == (PartAction.RECREATE,)
    assert not row.purged and not row.has_preview


def test_a_kept_final_never_expires() -> None:
    kept = facts(
        status=APPROVED,
        preview={"status": "part_final", "created_at": NOW - 30 * DAY, "raw_final": {"key": "k"}},
    )
    assert state(kept) is PartState.READY


def test_purged_files_read_as_expired_without_action() -> None:
    row = derive_state(facts(status=GENERATED, purged=True), None, now=NOW)
    assert row.state is PartState.EXPIRED and row.purged and row.actions == ()
    parent_purged = derive_state(facts(status=GENERATED), None, now=NOW, parent_purged=True)
    assert parent_purged.state is PartState.EXPIRED and parent_purged.purged


def test_every_state_is_reachable() -> None:
    previous = facts(1, status=GENERATED, preview={"status": "draft", "created_at": NOW - 10})
    seen = {
        state(facts()),
        state(facts(status=DRAFTING, jobs=("queued",))),
        state(facts(status=DRAFTING)),
        state(facts(status=GENERATED)),
        state(facts(status=APPROVED)),
        state(facts(status=FAILED, failure_reason="timeout")),
        state(facts(mode="edit", status=FAILED, failure_reason="refused_face")),
        state(
            facts(
                2,
                mode="extend",
                status=GENERATED,
                preview={"status": "draft", "created_at": NOW - 99},
            ),
            previous,
        ),
        state(facts(status=GENERATED, preview={"status": "draft", "created_at": 0})),
    }
    assert seen == set(PartState)


def test_progress_counts_the_parts_with_a_preview() -> None:
    progress = derive_progress(
        PARENT,
        [
            facts(3, status=DRAFTING),
            facts(1, status=GENERATED),
            facts(2, status=APPROVED),
            facts(4, status=FAILED, failure_reason="timeout"),
        ],
        now=NOW,
    )
    assert [p.index for p in progress.parts] == [1, 2, 3, 4]
    assert {p.total for p in progress.parts} == {4}
    assert (progress.with_preview, progress.total) == (2, 4)


def test_remove_has_no_service_yet() -> None:
    assert PartAction.REMOVE not in SERVED_ACTIONS


# ---------------------------------------------------------------------------
# the actions (in memory)


def _failed_world(reason: str = "provider_error", *, previews_used: int = 0):  # noqa: ANN202
    parts, content, repo, ledger, dispatcher, router, parent = world(previews_used=previews_used)
    ids = parts.create_parts(tenant_id=TENANT_ID, parent_id=parent, user_id=USER_ID)
    for child in ids:
        content.run_generation(tenant_id=TENANT_ID, draft_id=child)
    failed = ids[1]
    repo.drafts[failed] = replace(repo.drafts[failed], status=FAILED, failure_reason=reason)
    dispatcher.calls.clear()
    return PartRecovery(parts), content, repo, ledger, dispatcher, router, parent, ids


def _previews(ledger) -> int:  # noqa: ANN001
    return ledger.balance(tenant_id=TENANT_ID, brand_id=BRAND_ID).previews_used


def test_retry_makes_the_same_part_again_charged_as_creating_it() -> None:
    recovery, _content, repo, ledger, dispatcher, router, parent, ids = _failed_world()
    child = repo.drafts[ids[1]]
    brief = repo.briefs[child.brief_id]
    before = _previews(ledger)

    made = recovery.retry_part(tenant_id=TENANT_ID, parent_id=parent, part_index=2, user_id=USER_ID)

    after = repo.drafts[made]
    assert made == ids[1] and after.status == DRAFTING and after.failure_reason is None
    assert after.revision == child.revision + 1 and after.brief_id == child.brief_id
    assert _previews(ledger) == before + 1
    assert ledger.rows[(made, after.revision)].price == weight_for(brief)  # as at creation
    assert dispatcher.calls == [(TENANT_ID, made)]
    assert len(router.requests) == 1  # no Claude for a part


def test_change_rewrites_description_and_photos_never_the_mode() -> None:
    recovery, _content, repo, _ledger, _dispatcher, _router, parent, ids = _failed_world()
    mode = repo.briefs[repo.drafts[ids[1]].brief_id].media.part.mode  # type: ignore[union-attr]

    recovery.retry_part(
        tenant_id=TENANT_ID,
        parent_id=parent,
        part_index=2,
        user_id=USER_ID,
        changes=PartChanges(description="Papas recién fritas.", photo_keys=("uploads/t/p.jpg",)),
    )

    new = repo.briefs[repo.drafts[ids[1]].brief_id]
    assert new.media.part is not None and new.media.part.mode == mode
    assert new.media.part.description == "Papas recién fritas."
    assert new.media.clip_image_keys == ("uploads/t/p.jpg",)


def test_retry_without_previews_left_writes_nothing() -> None:
    recovery, _content, repo, ledger, dispatcher, _router, parent, ids = _failed_world(
        previews_used=16
    )
    rows = dict(ledger.rows)
    before = repo.drafts[ids[1]]
    with pytest.raises(NotEnoughCreations):
        recovery.retry_part(tenant_id=TENANT_ID, parent_id=parent, part_index=2, user_id=USER_ID)
    assert ledger.rows == rows and repo.drafts[ids[1]] == before and dispatcher.calls == []


def test_only_a_failed_part_is_retried() -> None:
    recovery, _content, repo, ledger, _dispatcher, _router, parent, ids = _failed_world()
    rows = dict(ledger.rows)
    with pytest.raises(PartChangeRefused, match=PART_NOT_FAILED_TEXT):
        recovery.retry_part(tenant_id=TENANT_ID, parent_id=parent, part_index=1, user_id=USER_ID)
    assert ledger.rows == rows and repo.drafts[ids[0]].status == GENERATED


def test_a_published_video_refuses_a_retry() -> None:
    recovery, _content, repo, ledger, _dispatcher, _router, parent, ids = _failed_world()
    repo.drafts[parent] = replace(repo.drafts[parent], status=PUBLISHED)
    rows = dict(ledger.rows)
    with pytest.raises(PartChangeRefused):
        recovery.retry_part(tenant_id=TENANT_ID, parent_id=parent, part_index=2, user_id=USER_ID)
    assert ledger.rows == rows and repo.drafts[ids[1]].status == FAILED


def test_make_new_is_only_for_an_original_part() -> None:
    recovery, _content, _repo, ledger, _dispatcher, _router, parent, _ids = _failed_world(
        "refused_face"
    )
    rows = dict(ledger.rows)
    with pytest.raises(PartChangeRefused, match=PART_ALREADY_NEW_TEXT):
        recovery.make_part_new(tenant_id=TENANT_ID, parent_id=parent, part_index=2, user_id=USER_ID)
    assert ledger.rows == rows


def test_make_new_turns_an_original_part_into_a_new_one(monkeypatch: pytest.MonkeyPatch) -> None:
    recovery, _content, repo, ledger, dispatcher, _router, parent, ids = _failed_world(
        "refused_face"
    )
    child = repo.drafts[ids[1]]
    old = repo.briefs[child.brief_id]
    # an «Igual al original» part, as a reel's plan makes it (with its window of the reel)
    part = old.media.part.model_copy(update={"mode": "edit", "analysis_id": uuid4()})  # type: ignore[union-attr]
    edit = old.model_copy(
        update={
            "media": old.media.model_copy(
                update={
                    "part": part,
                    "clip_reference_mode": "edit",
                    "clip_video_keys": ("t/x/generated/w.mp4",),
                }
            )
        }
    )
    repo.briefs[child.brief_id] = edit
    before = _previews(ledger)

    made = recovery.make_part_new(
        tenant_id=TENANT_ID, parent_id=parent, part_index=2, user_id=USER_ID
    )

    after = repo.drafts[made]
    new = repo.briefs[after.brief_id]
    assert after.brief_id != child.brief_id and after.status == DRAFTING
    assert new.media.part is not None and new.media.part.mode == "reference"
    assert new.media.part.description == part.description
    assert new.media.clip_reference_mode == "motion" and new.media.clip_video_keys == ()
    assert new.media.clip_image_keys == old.media.clip_image_keys
    assert _previews(ledger) == before + 1
    assert dispatcher.calls == [(TENANT_ID, made)]
    assert repo.briefs[child.brief_id].media.part.mode == "edit"  # the old version keeps it  # type: ignore[union-attr]


def test_the_retry_edge_is_only_from_failed() -> None:
    assert apply_transition(FAILED, DraftTrigger.PART_RETRY) == DRAFTING
    for other in (DRAFTING, GENERATED, APPROVED):
        with pytest.raises(Exception):  # noqa: B017
            apply_transition(other, DraftTrigger.PART_RETRY)


def test_a_retry_leaves_the_other_parts_alone() -> None:
    recovery, _c, repo, _l, _d, _r, parent, ids = _failed_world()
    before = {c.id: c for c in _children(repo, parent)}
    recovery.retry_part(tenant_id=TENANT_ID, parent_id=parent, part_index=2, user_id=USER_ID)
    after = {c.id: c for c in _children(repo, parent)}
    for sibling in (ids[0], ids[2], ids[3]):
        assert after[sibling] == before[sibling]


def _as_edit(repo, child_id: UUID) -> None:  # noqa: ANN001
    """Make a part «Igual al original», as a reel's plan makes it."""
    child = repo.drafts[child_id]
    old = repo.briefs[child.brief_id]
    part = old.media.part.model_copy(update={"mode": "edit", "analysis_id": uuid4()})
    repo.briefs[child.brief_id] = old.model_copy(
        update={"media": old.media.model_copy(update={"part": part, "clip_reference_mode": "edit"})}
    )


def test_a_new_part_refused_for_its_photos_is_not_retried_with_them() -> None:
    recovery, _c, repo, ledger, dispatcher, _r, parent, ids = _failed_world("refused_face")
    rows = dict(ledger.rows)
    with pytest.raises(PartChangeRefused, match=PART_SAME_PHOTOS_TEXT):
        recovery.retry_part(tenant_id=TENANT_ID, parent_id=parent, part_index=2, user_id=USER_ID)
    assert ledger.rows == rows and repo.drafts[ids[1]].status == FAILED
    assert dispatcher.calls == []
    # «Cambiar» (other photos) is what the screen offers: it goes through
    recovery.retry_part(
        tenant_id=TENANT_ID,
        parent_id=parent,
        part_index=2,
        user_id=USER_ID,
        changes=PartChanges(photo_keys=("uploads/t/otra.jpg",)),
    )
    assert repo.drafts[ids[1]].status == DRAFTING


@pytest.mark.parametrize("reason", ["refused_face", "source_purged", "analysis_not_ready"])
def test_an_original_part_refused_is_only_made_new(reason: str) -> None:
    recovery, _c, repo, ledger, _d, _r, parent, ids = _failed_world(reason)
    _as_edit(repo, ids[1])
    rows = dict(ledger.rows)
    for changes in (None, PartChanges(description="Otra cosa.")):
        with pytest.raises(PartChangeRefused, match=PART_ONLY_NEW_TEXT):
            recovery.retry_part(
                tenant_id=TENANT_ID,
                parent_id=parent,
                part_index=2,
                user_id=USER_ID,
                changes=changes,
            )
    assert ledger.rows == rows and repo.drafts[ids[1]].status == FAILED


def test_an_original_part_that_failed_for_another_reason_is_not_made_new() -> None:
    recovery, _c, repo, ledger, _d, _r, parent, ids = _failed_world("provider_error")
    _as_edit(repo, ids[1])
    rows = dict(ledger.rows)
    with pytest.raises(PartChangeRefused, match=PART_RETRY_AS_IS_TEXT):
        recovery.make_part_new(tenant_id=TENANT_ID, parent_id=parent, part_index=2, user_id=USER_ID)
    assert ledger.rows == rows and repo.drafts[ids[1]].status == FAILED


def test_a_part_being_made_says_so() -> None:
    recovery, _c, repo, _l, _d, _r, parent, ids = _failed_world()
    repo.drafts[ids[1]] = replace(repo.drafts[ids[1]], status=DRAFTING, failure_reason=None)
    with pytest.raises(PartChangeRefused, match=PART_BEING_MADE_TEXT):
        recovery.retry_part(tenant_id=TENANT_ID, parent_id=parent, part_index=2, user_id=USER_ID)
