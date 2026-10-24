"""Resultados' backend door (m-24843003): the week's counts through `tenant_session`, as
a VM. Blocking (DB) — the state runs it with `asyncio.to_thread`."""

from __future__ import annotations

from uuid import UUID

from qualify_api.home import read_results_counts

from .results_vm import ResultsVM, build_results_vm


def load_results(tenant_id: UUID) -> ResultsVM:
    return build_results_vm(read_results_counts(tenant_id))


__all__ = ["load_results"]
