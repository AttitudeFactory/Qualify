"""Offline scheduler guarantees; the real RLS/discovery/engine paths have DB tests."""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from qualify_api.connections import purge_worker as worker
from qualify_api.connections.purge import ConnectionPurgeBusy


class Repository:
    def __init__(self, tenants: list[UUID], jobs: dict[UUID, list[worker.DueJob]]) -> None:
        self.tenants = tenants
        self.jobs = jobs
        self.discovery: list[UUID | None] = []
        self.attempts: list[UUID] = []

    def discover(self, now: datetime, after: UUID | None) -> list[UUID]:
        self.discovery.append(after)
        return [tid for tid in self.tenants if after is None or tid > after][
            : worker.DISCOVERY_BATCH
        ]

    def due(self, tenant_id: UUID, now: datetime, limit: int) -> list[worker.DueJob]:
        return self.jobs[tenant_id][:limit]

    def mark_attempt(self, tenant_id: UUID, connection_id: UUID, now: datetime) -> None:
        self.attempts.append(connection_id)

    def outstanding(self, tenant_id: UUID, now: datetime) -> tuple[int, int]:
        jobs = self.jobs[tenant_id]
        return len(jobs), sum(job.deadline_at <= now + worker.DEADLINE_WARNING for job in jobs)


def test_failures_do_not_starve_other_jobs_or_tenants_and_never_log_payloads(caplog) -> None:
    tenants = sorted([uuid4(), uuid4()])
    now = datetime.now(UTC)
    jobs = {tid: [worker.DueJob(uuid4(), now + timedelta(days=1))] for tid in tenants}
    jobs[tenants[0]].append(worker.DueJob(uuid4(), now + timedelta(days=1)))
    failed_id = jobs[tenants[0]][0].connection_id
    repository = Repository(tenants, jobs)
    calls: list[UUID] = []

    def purge(*, tenant_id: UUID, connection_id: UUID, **kwargs: object) -> object:
        calls.append(connection_id)
        if connection_id == failed_id:
            raise RuntimeError("vendor response with secret token and personal data")
        jobs[tenant_id] = [job for job in jobs[tenant_id] if job.connection_id != connection_id]
        return SimpleNamespace(status="completed")

    caplog.set_level(logging.INFO)
    report = worker.PurgeRunner(
        tenants=None, execute=True, repository=repository, purge=purge
    ).run_once(now=now)
    assert len(calls) == 3 and report.completed == 2 and report.failed == 1
    assert report.pending == 1 and report.urgent == 0
    assert "error=RuntimeError" in caplog.text
    assert "secret token" not in caplog.text and "personal data" not in caplog.text


def test_discovery_paginates_and_rediscovers_new_tenants_each_pass(monkeypatch) -> None:
    monkeypatch.setattr(worker, "DISCOVERY_BATCH", 1)
    tenants = sorted([uuid4(), uuid4()])
    repository = Repository(tenants[:1], {tid: [] for tid in tenants})
    runner = worker.PurgeRunner(tenants=None, execute=True, repository=repository)
    assert runner.run_once().tenants == 1
    repository.tenants = tenants
    assert runner.run_once().tenants == 2
    assert repository.discovery == [None, tenants[0], None, tenants[0], tenants[1]]


def test_tenant_read_failure_does_not_block_later_tenant() -> None:
    tenants = sorted([uuid4(), uuid4()])
    repository = Repository(tenants, {tenants[1]: []})
    report = worker.PurgeRunner(tenants=tenants, execute=True, repository=repository).run_once()
    assert report.tenants == 2 and report.failed == 1


def test_dry_run_is_read_only_and_deadline_alerts_include_jobs_beyond_batch(caplog) -> None:
    tenant = uuid4()
    now = datetime.now(UTC)
    repository = Repository(
        [tenant],
        {tenant: [worker.DueJob(uuid4(), now + timedelta(days=1)), worker.DueJob(uuid4(), now)]},
    )
    caplog.set_level(logging.INFO)
    report = worker.PurgeRunner(
        tenants=[tenant], execute=False, limit=1, repository=repository
    ).run_once(now=now)
    assert not repository.attempts and report.attempted == 0
    assert report.pending == 2 and report.urgent == 1
    assert "connection_purge.deadline_alert" in caplog.text


def test_busy_is_skipped_and_shutdown_stops_between_jobs() -> None:
    tenant = uuid4()
    now = datetime.now(UTC)
    repository = Repository(
        [tenant], {tenant: [worker.DueJob(uuid4(), now + timedelta(days=1)) for _ in range(2)]}
    )
    stop = threading.Event()

    def purge(**kwargs: object) -> object:
        stop.set()
        raise ConnectionPurgeBusy()

    report = worker.PurgeRunner(
        tenants=[tenant], execute=True, repository=repository, purge=purge
    ).run_once(now=now, should_stop=stop.is_set)
    assert report.attempted == 1 and report.failed == 0


def test_missing_password_stays_idle_without_db_attempts_and_warns_once(tmp_path, caplog) -> None:
    class StopAfterThree(threading.Event):
        def __init__(self) -> None:
            super().__init__()
            self.waits = 0

        def wait(self, timeout: float | None = None) -> bool:
            self.waits += 1
            if self.waits == 2:
                self.set()
            return self.is_set()

    class NoDatabase:
        def run_once(self, **kwargs: object) -> object:
            pytest.fail("inactive worker attempted database access")

    path = tmp_path / "heartbeat.json"
    caplog.set_level(logging.INFO)
    assert (
        worker.run_worker(
            NoDatabase(),
            once=False,
            stop=StopAfterThree(),
            heartbeat_path=path,
            is_configured=lambda: False,
        )
        == 0
    )
    assert caplog.text.count("connection_purge.inactive") == 1
    assert json.loads(path.read_text())["status"] == "inactive"
    assert worker.healthcheck(path) == 0
    assert (
        worker.run_worker(NoDatabase(), once=True, heartbeat_path=path, is_configured=lambda: False)
        == 2
    )


@pytest.mark.parametrize("dsn", ["", "invalid", "postgresql+psycopg://role:@postgres/db"])
def test_blank_password_configuration_fails_closed(monkeypatch, dsn: str) -> None:
    monkeypatch.setenv("QUALIFY_CONNECTION_PURGE_DSN", dsn)
    assert not worker.configured()


def test_production_never_falls_back_to_development_dsn(monkeypatch) -> None:
    monkeypatch.setenv("QUALIFY_DEPLOY_ENV", "production")
    monkeypatch.delenv("QUALIFY_CONNECTION_PURGE_DSN", raising=False)
    assert not worker.configured()


def test_healthcheck_records_errors_and_recovers_on_later_success(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"

    class Runner:
        failed = True

        def run_once(self, **kwargs: object) -> worker.TickReport:
            return worker.TickReport(failed=int(self.failed))

    runner = Runner()
    assert (
        worker.run_worker(runner, once=True, heartbeat_path=path, is_configured=lambda: True) == 1
    )
    assert worker.healthcheck(path) == 1
    runner.failed = False
    assert (
        worker.run_worker(runner, once=True, heartbeat_path=path, is_configured=lambda: True) == 0
    )
    assert worker.healthcheck(path) == 0
    beat = json.loads(path.read_text())
    beat["at"] = time.time() - 1201
    path.write_text(json.dumps(beat))
    assert worker.healthcheck(path) == 1


def test_default_heartbeat_uses_platform_temporary_directory() -> None:
    assert worker.HEARTBEAT_PATH.parent == Path(tempfile.gettempdir())
    assert worker.HEARTBEAT_PATH.name == "qualify-connection-purge.json"


def test_discovery_failure_is_unhealthy_and_loop_retries(tmp_path) -> None:
    path = tmp_path / "heartbeat.json"

    class Runner:
        calls = 0

        def run_once(self, **kwargs: object) -> worker.TickReport:
            self.calls += 1
            raise RuntimeError("do not expose this DB connection string")

    runner = Runner()
    assert (
        worker.run_worker(
            runner,
            once=False,
            interval=0,
            max_ticks=2,
            heartbeat_path=path,
            is_configured=lambda: True,
        )
        == 0
    )
    assert runner.calls == 2 and worker.healthcheck(path) == 1


def test_scope_required_and_global_scope_refused_locally(monkeypatch) -> None:
    monkeypatch.delenv("QUALIFY_DEPLOY_ENV", raising=False)
    for args in ([], ["--all-tenants"]):
        with pytest.raises(SystemExit) as exc:
            worker.main(args)
        assert exc.value.code == 2


def test_production_service_defaults_and_dedicated_database_authority() -> None:
    # This is a security contract: default-up scheduling must hold ONLY its dedicated
    # DSN, while all serving services continue to inherit the blank purge authority.
    import yaml

    root = Path(__file__).resolve().parents[3]
    compose = yaml.safe_load((root / "deploy/docker-compose.prod.yml").read_text(encoding="utf-8"))
    service = compose["services"]["connection-purge-worker"]
    assert "profiles" not in service and service["restart"] == "unless-stopped"
    assert "--execute" in service["command"] and "--all-tenants" in service["command"]
    assert service["mem_limit"] == service["memswap_limit"] == "256m"
    for key, value in service["environment"].items():
        if key.endswith("_DSN") and key != "QUALIFY_CONNECTION_PURGE_DSN":
            assert value == ""
    for name in ("api", "reflex", "calendar-worker", "webhook-worker", "creative-worker"):
        assert compose["services"][name]["environment"]["QUALIFY_CONNECTION_PURGE_DSN"] == ""
        assert (
            compose["services"][name]["environment"]["QUALIFY_DB_CONNECTION_PURGE_PASSWORD"] == ""
        )
