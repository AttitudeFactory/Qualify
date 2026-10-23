"""Inicio's backend door (m-24842962): the counts through `tenant_session`, as a VM.

Blocking (DB) — the state runs it with `asyncio.to_thread`.
"""

from __future__ import annotations

from uuid import UUID

from qualify_api.home import read_home_counts

from .home_vm import HomeVM, build_home_vm


def load_home(tenant_id: UUID) -> HomeVM:
    return build_home_vm(read_home_counts(tenant_id))


__all__ = ["load_home"]
