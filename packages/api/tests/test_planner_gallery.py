"""QUA-118: the POST's gallery state (`planner.gallery`) — pure, no DB.

Five states + the «Usado» badge, derived from the three existing layers (lifecycle,
approval, publishability) and the POST's event history. Nothing persisted.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from qualify_api.planner.gallery import GalleryState, gallery_state, is_reusable, is_used
from qualify_api.planner.post_reader import ApprovalStatus, PostSummary


def _post(
    approval: ApprovalStatus = ApprovalStatus.APPROVED,
    *,
    lifecycle: str = "approved",
    publishable: bool = True,
    times_published: int = 0,
    live: bool = False,
    reuse_type: str | None = None,
) -> PostSummary:
    return PostSummary(
        post_id=uuid4(),
        brand_id=uuid4(),
        title="Promo",
        approval=approval,
        lifecycle_status=lifecycle,
        is_publishable=publishable,
        times_published=times_published,
        has_live_event=live,
        reuse_type=reuse_type,
    )


@pytest.mark.parametrize(
    ("post", "expected"),
    [
        # Draft: still being produced.
        (_post(ApprovalStatus.NOT_READY, lifecycle="drafting", publishable=False), "draft"),
        # Discarded: rejected by the human, or generation failed.
        (_post(ApprovalStatus.REJECTED, lifecycle="rejected", publishable=False), "discarded"),
        (_post(ApprovalStatus.NOT_READY, lifecycle="failed", publishable=False), "discarded"),
        # Needs action: in review, or approved with a red evaluation.
        (_post(ApprovalStatus.PENDING, lifecycle="generated", publishable=False), "needs_action"),
        (_post(ApprovalStatus.PENDING, lifecycle="generated", publishable=True), "needs_action"),
        (_post(publishable=False), "needs_action"),
        # Schedulable: approved and green.
        (_post(), "schedulable"),
        # Used: a one-shot POST that was published or is live on the calendar.
        (_post(times_published=1), "used"),
        (_post(live=True), "used"),
        (_post(times_published=2, reuse_type="promocional"), "used"),
        # D2: a recurrente POST stays schedulable however often it was used.
        (_post(times_published=3, reuse_type="recurrente"), "schedulable"),
        (_post(live=True, reuse_type="recurrente"), "schedulable"),
        # History never rescues a POST that is not plannable.
        (_post(ApprovalStatus.REJECTED, lifecycle="rejected", times_published=2), "discarded"),
        (_post(ApprovalStatus.PENDING, lifecycle="generated", times_published=2), "needs_action"),
    ],
)
def test_gallery_state_table(post: PostSummary, expected: str) -> None:
    assert gallery_state(post) is GalleryState(expected)


def test_used_is_a_badge_that_coexists_with_schedulable_for_a_recurrente_post() -> None:
    post = _post(times_published=3, reuse_type="recurrente")
    assert is_used(post) and is_reusable(post)
    assert gallery_state(post) is GalleryState.SCHEDULABLE
    assert post.times_published == 3  # «Usado ×3»


def test_only_recurrente_is_reusable() -> None:
    assert is_reusable(_post(reuse_type="recurrente"))
    assert not is_reusable(_post(reuse_type="promocional"))
    assert not is_reusable(_post(reuse_type=None))


def test_the_five_states_are_exactly_five() -> None:
    assert {s.value for s in GalleryState} == {
        "draft",
        "needs_action",
        "schedulable",
        "used",
        "discarded",
    }
