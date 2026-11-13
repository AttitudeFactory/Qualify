"""Backend access of the menu's «creating your publication» ring (m-24973458).

One read-only EXISTS through `tenant_session`, in `qualify_api.creative.in_flight`.
Blocking — the state calls it with `asyncio.to_thread`.
"""

from __future__ import annotations

from uuid import UUID

from qualify_api.creative.in_flight import generation_in_flight


def read_in_flight(tenant_id: UUID) -> bool:
    return generation_in_flight(tenant_id)


__all__ = ["read_in_flight"]
