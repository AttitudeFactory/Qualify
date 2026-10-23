"""`HumanApproval` — who approved this exact text, and when (ADR 21c).

Moved here from `conversations/outbox.py` (m-24789645) so the public comment reply
(`replies.ReplyService.send`) demands the very same object the private outbox does.
`conversations.outbox` re-exports both names; `isinstance` checks keep working because it
is one class, not a copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class ApprovalRequired(PermissionError):
    """A send was requested without a human approval. There is no code path around it."""


@dataclass(frozen=True)
class HumanApproval:
    """Who approved this exact text, and when. `draft_id` links back to the assisted
    draft when the text came from one (E4); a hand-written reply has none."""

    user_id: UUID
    approved_at: datetime
    draft_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, UUID):
            raise ApprovalRequired("an approval needs the approving user's id")
        if not isinstance(self.approved_at, datetime):
            raise ApprovalRequired("an approval needs the instant it was given")


__all__ = ["ApprovalRequired", "HumanApproval"]
