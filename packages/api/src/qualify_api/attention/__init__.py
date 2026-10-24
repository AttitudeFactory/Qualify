"""Who is waiting for an answer, counted per channel (m-24842990, ATENDER-1).

A read-only aggregation over tables other modules own (`threads`, `messages`,
`interaction_followups`, `comment_reply_drafts`): it writes nothing, opens no vendor
call and adds no table. See `counts.py` for each channel's definition.
"""

from .counts import PendingCounts, PendingCountsStore, PostgresPendingCounts, pending_counts

__all__ = ["PendingCounts", "PendingCountsStore", "PostgresPendingCounts", "pending_counts"]
