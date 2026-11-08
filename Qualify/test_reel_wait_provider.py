"""UI-2 review (m-24921076): the fleet's 24 h model-call count is reused for 60 s across
polls instead of summed on every tick of every tab. Offline: an in-memory store."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from . import reel_wait_provider as provider

TENANT = uuid4()


class Store:
    def __init__(self) -> None:
        self.fleet_reads = 0

    def model_calls_since(self, tenant_id, since, now) -> int:  # noqa: ANN001
        self.fleet_reads += 1
        return 7


@pytest.fixture(autouse=True)
def fresh_cache(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    clock = [0.0]
    monkeypatch.setattr(provider, "_fleet", provider._FleetCache(clock=lambda: clock[0]))
    return clock


def test_the_fleet_count_is_read_once_a_minute(fresh_cache: list[float]) -> None:
    store = provider._CachedFleetStore(Store())
    now = datetime(2026, 11, 6, tzinfo=UTC)
    assert [store.model_calls_since(TENANT, now, now) for _ in range(5)] == [7] * 5
    assert store._store.fleet_reads == 1
    fresh_cache[0] = provider.FLEET_CACHE_SECONDS + 1
    assert store.model_calls_since(TENANT, now, now) == 7
    assert store._store.fleet_reads == 2


def test_everything_else_is_the_stores_own() -> None:
    inner = Store()
    inner.get = lambda tenant_id, analysis_id: "row"  # type: ignore[attr-defined]
    assert provider._CachedFleetStore(inner).get(TENANT, uuid4()) == "row"


def test_the_status_poll_goes_through_the_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    def get_analysis_status(tenant_id, analysis_id, *, store):  # noqa: ANN001
        seen["store"] = store
        return None

    monkeypatch.setattr(provider.reel_analysis, "default_store", lambda: Store())
    monkeypatch.setattr(provider.reel_analysis, "get_analysis_status", get_analysis_status)
    assert provider.analysis_status(TENANT, uuid4()) is None
    assert isinstance(seen["store"], provider._CachedFleetStore)
