"""Pure FSM tests for the content-draft lifecycle (MC-01, design §2.3): every declared
edge passes, undeclared edges raise, and the two guards (fail-needs-reason,
approve-needs-variant) refuse the lying states."""

from __future__ import annotations

from uuid import UUID

import pytest

from qualify_api.creative.fsm import (
    APPROVED,
    DRAFT_STATUSES,
    DRAFTING,
    FAILED,
    GENERATED,
    PUBLISHED,
    REAP_FAILURE_REASON,
    REJECTED,
    STAGED,
    DraftTrigger,
    GuardUnsatisfied,
    InvalidTransition,
    apply_transition,
)

VARIANT = UUID("44444444-4444-4444-4444-444444444444")

# Every declared edge, with the guard data it needs to pass. This list IS the spec: a new
# edge in `_TRANSITIONS` without a row here should fail the exhaustiveness test below.
DECLARED_EDGES: list[tuple[str, DraftTrigger, str, dict]] = [
    (DRAFTING, DraftTrigger.GENERATE_OK, GENERATED, {}),
    (DRAFTING, DraftTrigger.GENERATE_FAIL, FAILED, {"failure_reason": "provider_error"}),
    (DRAFTING, DraftTrigger.REAP, FAILED, {}),
    (GENERATED, DraftTrigger.APPROVE, APPROVED, {"selected_variant_id": VARIANT}),
    (GENERATED, DraftTrigger.REJECT, REJECTED, {}),
    # 2026-10-22: an approval never scheduled nor published can be undone from Piezas
    (APPROVED, DraftTrigger.REJECT, REJECTED, {}),
    (REJECTED, DraftTrigger.REGENERATE, DRAFTING, {}),
    (APPROVED, DraftTrigger.STAGE, STAGED, {}),
    (APPROVED, DraftTrigger.PUBLISH_OK, PUBLISHED, {}),
    (STAGED, DraftTrigger.PUBLISH_OK, PUBLISHED, {}),
    (STAGED, DraftTrigger.STAGE_EXPIRED, APPROVED, {}),
    # Editing the copy: approved goes back to review; review/rejected stay where they are.
    (GENERATED, DraftTrigger.EDIT, GENERATED, {}),
    (APPROVED, DraftTrigger.EDIT, GENERATED, {}),
    (REJECTED, DraftTrigger.EDIT, REJECTED, {}),
]


@pytest.mark.parametrize(
    ("current", "trigger", "expected", "guard_kwargs"),
    DECLARED_EDGES,
    ids=[f"{c}--{t}->{e}" for c, t, e, _ in DECLARED_EDGES],
)
def test_declared_edge_passes(
    current: str, trigger: DraftTrigger, expected: str, guard_kwargs: dict
) -> None:
    assert apply_transition(current, trigger, **guard_kwargs) == expected


def test_declared_edges_list_is_exhaustive() -> None:
    """The parametrized list above covers exactly the FSM's transition table — no edge
    ships untested, and no test asserts an edge the FSM does not declare."""
    from qualify_api.creative.fsm import _TRANSITIONS

    assert {(c, t) for c, t, _, _ in DECLARED_EDGES} == set(_TRANSITIONS)
    for current, trigger, expected, _ in DECLARED_EDGES:
        assert _TRANSITIONS[(current, trigger)] == expected


# A sample of undeclared edges. Not the full cartesian product (7 statuses x 9 triggers),
# but every status appears and every "tempting shortcut" is pinned closed.
UNDECLARED_EDGES: list[tuple[str, DraftTrigger]] = [
    (DRAFTING, DraftTrigger.APPROVE),  # nothing to approve yet
    (DRAFTING, DraftTrigger.PUBLISH_OK),  # nothing to publish
    (GENERATED, DraftTrigger.PUBLISH_OK),  # publish without approval — the HITL bypass
    (GENERATED, DraftTrigger.STAGE),  # stage without approval
    (GENERATED, DraftTrigger.REGENERATE),  # regenerate is only legal from rejected
    (APPROVED, DraftTrigger.APPROVE),  # double-approve
    (REJECTED, DraftTrigger.APPROVE),  # rejected must regenerate, not flip to approved
    (STAGED, DraftTrigger.STAGE),  # double-stage
    (PUBLISHED, DraftTrigger.PUBLISH_OK),  # published is terminal
    (PUBLISHED, DraftTrigger.REJECT),  # published is terminal
    (FAILED, DraftTrigger.GENERATE_OK),  # failed is terminal
    (FAILED, DraftTrigger.REGENERATE),  # failed is terminal (regenerate ≠ retry)
    (DRAFTING, DraftTrigger.EDIT),  # nothing generated to edit yet
    (STAGED, DraftTrigger.EDIT),  # the platform container already holds the old copy
    (PUBLISHED, DraftTrigger.EDIT),  # it is live; editing would lie about what went out
    (FAILED, DraftTrigger.EDIT),  # terminal
]


def test_an_approved_draft_that_is_edited_can_be_approved_again() -> None:
    """The dead end this edge removes: approved → edit → (approve again) → approved."""
    back_in_review = apply_transition(APPROVED, DraftTrigger.EDIT)
    assert back_in_review == GENERATED
    assert apply_transition(back_in_review, DraftTrigger.APPROVE, selected_variant_id=VARIANT) == (
        APPROVED
    )


def test_editable_statuses_come_from_the_table() -> None:
    from qualify_api.creative.fsm import EDITABLE_STATUSES

    assert EDITABLE_STATUSES == {GENERATED, APPROVED, REJECTED}


@pytest.mark.parametrize(
    ("current", "trigger"), UNDECLARED_EDGES, ids=[f"{c}--{t}" for c, t in UNDECLARED_EDGES]
)
def test_undeclared_edge_raises(current: str, trigger: DraftTrigger) -> None:
    with pytest.raises(InvalidTransition):
        apply_transition(current, trigger, selected_variant_id=VARIANT, failure_reason="x")


def test_unknown_status_raises() -> None:
    with pytest.raises(InvalidTransition):
        apply_transition("exported", DraftTrigger.PUBLISH_OK)  # pre-amendment status


def test_approve_without_variant_raises() -> None:
    # Design §2.3 hard rule: APPROVED with no selected variant is a state that lies.
    with pytest.raises(GuardUnsatisfied):
        apply_transition(GENERATED, DraftTrigger.APPROVE)


def test_generate_fail_without_reason_raises() -> None:
    with pytest.raises(GuardUnsatisfied):
        apply_transition(DRAFTING, DraftTrigger.GENERATE_FAIL)
    with pytest.raises(GuardUnsatisfied):
        apply_transition(DRAFTING, DraftTrigger.GENERATE_FAIL, failure_reason="")


def test_guard_error_is_an_invalid_transition() -> None:
    # Callers that only catch InvalidTransition still catch guard refusals.
    assert issubclass(GuardUnsatisfied, InvalidTransition)


def test_reap_reason_is_timeout() -> None:
    # The reaper's reason is forced by contract, matching FailureReason.TIMEOUT.
    assert REAP_FAILURE_REASON == "timeout"
    assert apply_transition(DRAFTING, DraftTrigger.REAP) == FAILED


def test_status_vocabulary_is_the_contract() -> None:
    """The plain-string statuses must match `qualify_creative.enums.DraftStatus` values.
    That package is not importable from this venv yet, so pin the values themselves."""
    assert DRAFT_STATUSES == {
        "drafting",
        "generated",
        "approved",
        "rejected",
        "staged",
        "published",
        "failed",
    }


def test_full_happy_path_via_staging() -> None:
    status = DRAFTING
    status = apply_transition(status, DraftTrigger.GENERATE_OK)
    status = apply_transition(status, DraftTrigger.APPROVE, selected_variant_id=VARIANT)
    status = apply_transition(status, DraftTrigger.STAGE)
    status = apply_transition(status, DraftTrigger.PUBLISH_OK)
    assert status == PUBLISHED


def test_reject_regenerate_loops_back_to_drafting() -> None:
    status = apply_transition(GENERATED, DraftTrigger.REJECT)
    assert status == REJECTED
    assert apply_transition(status, DraftTrigger.REGENERATE) == DRAFTING


def test_stage_expiry_returns_to_approved_and_can_restage() -> None:
    status = apply_transition(STAGED, DraftTrigger.STAGE_EXPIRED)
    assert status == APPROVED
    assert apply_transition(status, DraftTrigger.STAGE) == STAGED
