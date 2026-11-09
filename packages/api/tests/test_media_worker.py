"""`media-worker`'s CLI and loop, offline (m-24955918): scope is mandatory, the
reconciler runs at start and every 24 h, deterministic ids are stable."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from qualify_api.catalog import media_worker
from qualify_api.catalog.media_worker import (
    RECONCILE_EVERY_SECONDS,
    ScopedTenants,
    build_parser,
    cut_part_media_id,
    ingest_media_id,
    run_loop,
)

TENANT = UUID("a0000000-0000-4000-8000-00000000cb01")


def test_scope_is_mandatory() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--tenant", str(TENANT), "--all-tenants"])
    with pytest.raises(ValueError):
        ScopedTenants([])
    args = build_parser().parse_args(["--tenant", str(TENANT), "--once"])
    assert args.tenants == [TENANT] and args.once


def test_deterministic_ids() -> None:
    job = UUID("12345678-1234-5678-1234-567812345678")
    assert ingest_media_id(job) == ingest_media_id(job) != cut_part_media_id(job, 0)
    assert cut_part_media_id(job, 0) != cut_part_media_id(job, 1)


class _Runner:
    def __init__(self) -> None:
        self.reconciled = 0
        self.jobs = 0

    def reconcile_tenant(self, tenant_id: UUID) -> Any:
        self.reconciled += 1
        return media_worker.ReconcileReport(tenant_id=tenant_id)

    def run_tenant(self, tenant_id: UUID, *, limit: int) -> list[Any]:
        self.jobs += 1
        return []


def test_loop_reconciles_at_start_and_every_day() -> None:
    runner = _Runner()
    now = {"t": 0.0}

    def sleep(seconds: float) -> None:
        now["t"] += RECONCILE_EVERY_SECONDS / 2

    run_loop(
        runner,  # type: ignore[arg-type]
        ScopedTenants([TENANT]),
        interval=5,
        limit=1,
        sleep=sleep,
        clock=lambda: now["t"],
        max_ticks=5,
    )
    assert runner.jobs == 5 and runner.reconciled == 3  # t = 0, 1 day, 2 days


def test_once_runs_one_jobs_pass_with_the_given_runner() -> None:
    runner = _Runner()
    code = media_worker.main(
        ["--tenant", str(TENANT), "--once"],
        make_runner=lambda: runner,  # type: ignore[arg-type,return-value]
    )
    assert code == 0 and runner.jobs == 1 and runner.reconciled == 0
