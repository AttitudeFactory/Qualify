"""Backend access of «Por responder» (m-24842990): the pending counts per channel, read
in process through `qualify_api.attention` (`tenant_session`, RLS). Blocking — the state
calls it through `asyncio.to_thread`."""

from __future__ import annotations

from uuid import UUID

from qualify_api.attention import PendingCounts, pending_counts


def counts_for(tenant_id: UUID) -> PendingCounts:
    return pending_counts(tenant_id)
