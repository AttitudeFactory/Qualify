"""Planificador (QUA-108): the editorial calendar's backend.

POST (QUA-109) → **CalendarEvent (this module)** → PublishAttempt (QUA-111 + publishing).

- `fsm` — the event lifecycle (`scheduled`/`cancelled`, plus the execution states
  QUA-111 will drive).
- `post_reader` — the read-only contract with QUA-109's POST; `draft_post_reader` is the
  temporary adapter over creative drafts until QUA-109 exists.
- `rules` — the execution decision and idempotency key QUA-111 applies.
- `service` — schedule / reschedule / cancel / list week / list unscheduled / list due.
- `composition` — production wiring (the reader swap point).

This module never publishes, never writes content, and never approves.
"""

from qualify_api.planner.fsm import EventStatus, EventTrigger, InvalidTransition, apply_transition
from qualify_api.planner.post_reader import ApprovalStatus, PostReader, PostSummary
from qualify_api.planner.rules import (
    EXECUTION_WINDOW,
    ExecutionDecision,
    decide_execution,
    idempotency_key,
    is_expired,
    is_expired_scheduled,
    is_overdue_unapproved,
)

__all__ = [
    "EXECUTION_WINDOW",
    "ApprovalStatus",
    "EventStatus",
    "EventTrigger",
    "ExecutionDecision",
    "InvalidTransition",
    "PostReader",
    "PostSummary",
    "apply_transition",
    "decide_execution",
    "idempotency_key",
    "is_expired",
    "is_expired_scheduled",
    "is_overdue_unapproved",
]
