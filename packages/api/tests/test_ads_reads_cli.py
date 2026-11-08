"""Read worker leases, bounds and failure isolation, without database/network access."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qualify_api.ads import reads_cli


@pytest.mark.asyncio
async def test_busy_lease_never_calls_observation_helpers(monkeypatch):
    @contextmanager
    def lease():
        yield SimpleNamespace(scalar=lambda *args: False)

    async def forbidden(**kwargs):
        pytest.fail("duplicate replica must not read Meta")

    monkeypatch.setattr(reads_cli, "admin_session", lease)
    monkeypatch.setattr(reads_cli, "refresh_daily_account_health", forbidden)
    monkeypatch.setattr(reads_cli, "poll_promotion_results", forbidden)
    assert (await reads_cli.tick(uuid4()))["busy"] == 1


@pytest.mark.asyncio
async def test_tick_releases_lease_and_passes_tenant_limit(monkeypatch):
    tenant = uuid4()
    calls = []

    @contextmanager
    def lease():
        calls.append("enter")
        try:
            yield SimpleNamespace(scalar=lambda *args: True)
        finally:
            calls.append("exit")

    async def health(*, tenant_id):
        assert tenant_id == tenant
        calls.append("health")
        return (SimpleNamespace(can_promote=False),)

    async def results(*, tenant_id, limit):
        assert tenant_id == tenant and limit == 3
        calls.append("results")
        return {"checked": 2, "unavailable": 1}

    monkeypatch.setattr(reads_cli, "admin_session", lease)
    monkeypatch.setattr(reads_cli, "refresh_daily_account_health", health)
    monkeypatch.setattr(reads_cli, "poll_promotion_results", results)
    assert await reads_cli.tick(tenant, limit=3) == {
        "health_checked": 1,
        "health_blocked": 1,
        "checked": 2,
        "unavailable": 1,
        "busy": 0,
    }
    assert calls == ["enter", "health", "results", "exit"]


@pytest.mark.asyncio
async def test_run_isolates_failure_without_printing_exception(monkeypatch, capsys):
    first, second = uuid4(), uuid4()
    calls = []

    async def tick(tenant, *, limit):
        calls.append(tenant)
        if tenant == first:
            raise RuntimeError("secret-provider-token")
        return {"checked": 1}

    monkeypatch.setattr(reads_cli, "tenants", lambda: (first, second))
    monkeypatch.setattr(reads_cli, "tick", tick)
    await reads_cli.run(tenant_id=None, all_tenants=True, once=True, interval=60, limit=3)
    output = capsys.readouterr().out
    assert calls == [first, second]
    assert '"errors": 1' in output and '"checked": 1' in output
    assert "secret-provider-token" not in output


def test_lease_keys_are_stable_separate_signed_int64():
    first, second = uuid4(), uuid4()
    assert reads_cli._lock_key(first) == reads_cli._lock_key(first)
    assert reads_cli._lock_key(first) != reads_cli._lock_key(second)
    assert -(2**63) <= reads_cli._lock_key(first) < 2**63


def test_healthcheck_is_local_fresh_bounded_and_no_network(monkeypatch):
    class LocalPath:
        value = None

        def read_text(self, **kwargs):
            if self.value is None:
                raise FileNotFoundError
            return self.value

        def write_text(self, value, **kwargs):
            self.value = value

        def with_suffix(self, suffix):
            return self

    path = LocalPath()
    monkeypatch.setattr(reads_cli, "heartbeat_path", lambda: path)
    monkeypatch.setattr(reads_cli.os, "replace", lambda *args: None)
    assert not reads_cli.healthy()
    monkeypatch.setattr(reads_cli.time, "time", lambda: 1000)
    reads_cli.heartbeat()
    assert reads_cli.healthy()
    for invalid in ("invalid", "nan", "inf", "0", "1001"):
        path.write_text(invalid)
        assert not reads_cli.healthy()
