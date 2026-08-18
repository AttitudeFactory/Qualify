"""Content-draft lifecycle FSM (MC-01, design §2.3): drafting → generated → approved /
rejected → staged → published, with `failed` as the terminal error state.

Replica of the `connections/fsm.py` pattern: explicit transitions, a table, and no status
mutation anywhere outside `apply_transition`. Two edges carry guards that make lying
states unrepresentable: a draft cannot fail without a machine-readable reason, and a
draft cannot be approved without the human having picked a variant (design §2.3 hard
rules — "aprobar sin elegir variante es un estado que miente").

The status strings below ARE the contract with `qualify_creative.enums.DraftStatus`:
`qualify_creative` is not an installed dependency of `qualify_api` (yet), so this module
speaks the wire values rather than importing the enum. If either side renames a value,
the other must follow — the DB `status` column stores exactly these strings.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

# Draft statuses — plain strings, values contract-matched to
# `qualify_creative.enums.DraftStatus` (see module docstring).
DRAFTING = "drafting"  # row created, generation work enqueued/in flight
GENERATED = "generated"  # variants exist, waiting for the human gate (HITL #2)
APPROVED = "approved"  # human approved; visible to downstream modules
REJECTED = "rejected"  # human rejected; may be regenerated
STAGED = "staged"  # media container created on the platform, not yet published
PUBLISHED = "published"  # live on the platform; terminal happy path
FAILED = "failed"  # terminal; `failure_reason` says what to do about it

DRAFT_STATUSES: frozenset[str] = frozenset(
    {DRAFTING, GENERATED, APPROVED, REJECTED, STAGED, PUBLISHED, FAILED}
)

# The failure reason `reap` stamps — contract-matched to
# `qualify_creative.enums.FailureReason.TIMEOUT`. The reaper fails drafts stuck in
# `drafting` past their deadline; the reason is forced, not caller-supplied.
REAP_FAILURE_REASON = "timeout"


class DraftTrigger(StrEnum):
    """Trigger vocabulary — this module's own, so a real `StrEnum` (unlike the statuses
    above, which mirror a foreign enum this package cannot import yet)."""

    GENERATE_OK = "generate_ok"  # generation pipeline produced variants
    GENERATE_FAIL = "generate_fail"  # pipeline failed; requires a typed failure_reason
    APPROVE = "approve"  # human approved; requires selected_variant_id
    REJECT = "reject"  # human rejected the generated variants
    REGENERATE = "regenerate"  # re-enqueue a rejected draft (config caps how many times)
    STAGE = "stage"  # platform media container created (pre-publish)
    PUBLISH_OK = "publish_ok"  # platform confirmed the publish
    STAGE_EXPIRED = "stage_expired"  # container expired; service must clear container cols
    REAP = "reap"  # stuck in drafting past deadline; reason forced to TIMEOUT


class InvalidTransition(Exception):
    """Raised when a (status, trigger) pair is not a legal edge of the FSM."""


class GuardUnsatisfied(InvalidTransition):
    """A legal edge whose guard data is missing: `generate_fail` without a
    `failure_reason`, or `approve` without a `selected_variant_id`."""


# (current status, trigger) -> next status
_TRANSITIONS: dict[tuple[str, str], str] = {
    (DRAFTING, DraftTrigger.GENERATE_OK): GENERATED,
    (DRAFTING, DraftTrigger.GENERATE_FAIL): FAILED,
    # The reaper edge: a draft stuck in `drafting` (worker died, process restarted) is
    # failed with reason TIMEOUT rather than left lying about work that is not running.
    (DRAFTING, DraftTrigger.REAP): FAILED,
    (GENERATED, DraftTrigger.APPROVE): APPROVED,
    (GENERATED, DraftTrigger.REJECT): REJECTED,
    (REJECTED, DraftTrigger.REGENERATE): DRAFTING,
    (APPROVED, DraftTrigger.STAGE): STAGED,
    # Publish is legal from both sides of staging: a direct publish never staged, and a
    # staged container being published.
    (APPROVED, DraftTrigger.PUBLISH_OK): PUBLISHED,
    (STAGED, DraftTrigger.PUBLISH_OK): PUBLISHED,
    # An expired container drops the draft back to `approved`; the service that applies
    # this edge must also clear `staged_container_id`/`staged_expires_at` — a status of
    # `approved` with a container id would be a row lying about its own state.
    (STAGED, DraftTrigger.STAGE_EXPIRED): APPROVED,
}


def apply_transition(
    current: str,
    trigger: str,
    *,
    failure_reason: str | None = None,
    selected_variant_id: UUID | None = None,
) -> str:
    """Pure lookup of the FSM edge — no DB, no side effects. Returns the next status.

    Raises `InvalidTransition` for an illegal (status, trigger) pair and
    `GuardUnsatisfied` (a subclass) when a legal edge is missing its guard data.
    """
    try:
        new_status = _TRANSITIONS[(current, trigger)]
    except KeyError:
        raise InvalidTransition(f"no transition from {current!r} on {trigger!r}") from None
    if trigger == DraftTrigger.GENERATE_FAIL and not failure_reason:
        raise GuardUnsatisfied("generate_fail requires a failure_reason")
    if trigger == DraftTrigger.APPROVE and selected_variant_id is None:
        raise GuardUnsatisfied("approve requires a selected_variant_id")
    return new_status
