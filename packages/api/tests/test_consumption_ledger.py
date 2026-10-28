"""Tests for the unified consumption ledger, pricing for Anthropic/ScrapeCreators,
and the Meegle sync (m-24823681)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from qualify_creative.pricing import JsonPricingTable
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.consumption import (
    consumption_scope,
    daily_consumption_sync,
    record_consumption,
    summarize_consumption,
    sync_consumption_to_meegle,
)
from qualify_api.consumption.models import ConsumptionLedger

# --- pricing table (offline) ----------------------------------------------------------


def test_pricing_table_anthropic_and_scrapecreators() -> None:
    table = JsonPricingTable("v7")
    # Anthropic token rates (per million tokens)
    assert table.unit_price(model_id="claude-haiku-5-5", unit="per_mtok_in") == Decimal("0.10")
    assert table.unit_price(model_id="claude-haiku-5-5", unit="per_mtok_out") == Decimal("0.50")
    assert table.unit_price(model_id="claude-haiku-4-5", unit="per_mtok_in") == Decimal("1.00")
    assert table.unit_price(model_id="claude-haiku-4-5", unit="per_mtok_out") == Decimal("5.00")
    assert table.unit_price(model_id="claude-sonnet-5", unit="per_mtok_in") == Decimal("2.00")
    assert table.unit_price(model_id="claude-sonnet-5", unit="per_mtok_out") == Decimal("10.00")
    # Cache pricing (provenance for the consumption ledger's cost_usd)
    assert table.unit_price(model_id="claude-haiku-5-5", unit="per_mtok_cache_read") == Decimal(
        "0.01"
    )
    assert table.unit_price(model_id="claude-sonnet-5-5", unit="per_mtok_cache_read") == Decimal(
        "0.10"
    )
    assert table.unit_price(model_id="claude-sonnet-5", unit="per_mtok_cache_read") == Decimal(
        "0.20"
    )
    # ScrapeCreators credits → USD
    assert table.unit_price(model_id="scrapecreators", unit="per_credit") == Decimal("0.0019")


# --- scope persistence + RLS (db) -----------------------------------------------------


def _clear_ledger(tenant_id: object) -> None:
    with admin_session() as session:
        session.query(ConsumptionLedger).filter(ConsumptionLedger.tenant_id == tenant_id).delete()
        session.flush()


@pytest.mark.db
def test_consumption_ledger_persistence_and_rls(seeded_ab: tuple[object, object]) -> None:
    tenant_a, _ = seeded_ab
    _clear_ledger(tenant_a)

    with consumption_scope(tenant_a, meegle_work_item_id=99999, operation="test_op"):
        record_consumption(
            provider="anthropic",
            model_id="claude-haiku-5-5",
            input_tokens=1000,
            output_tokens=200,
            cost_usd=Decimal("0.0002"),
        )
        record_consumption(
            provider="scrapecreators",
            model_id="scrapecreators",
            cost_usd=Decimal("0.0019"),
            metadata={"credits": 1},
        )

    with tenant_session(tenant_a) as session:
        rows = session.scalars(select(ConsumptionLedger)).all()
        assert len(rows) == 2
        total_cost = sum((r.cost_usd for r in rows), Decimal("0"))
        assert total_cost == Decimal("0.0021")
        assert all(r.meegle_work_item_id == 99999 for r in rows)
        assert all(r.operation == "test_op" for r in rows)
        assert all(r.pricing_table_version == "v7" for r in rows)
        sc = next(r for r in rows if r.provider == "scrapecreators")
        assert sc.extra_metadata == {"credits": 1}


@pytest.mark.db
def test_consumption_ledger_tenant_isolation(seeded_ab: tuple[object, object]) -> None:
    tenant_a, tenant_b = seeded_ab
    _clear_ledger(tenant_a)
    _clear_ledger(tenant_b)

    with consumption_scope(tenant_a, operation="iso_a"):
        record_consumption(
            provider="anthropic",
            model_id="claude-haiku-5-5",
            input_tokens=10,
            cost_usd=Decimal("0.000001"),
        )
    with consumption_scope(tenant_b, operation="iso_b"):
        record_consumption(
            provider="anthropic",
            model_id="claude-haiku-5-5",
            input_tokens=10,
            cost_usd=Decimal("0.000001"),
        )

    # Tenant A's session sees only its own rows (RLS).
    with tenant_session(tenant_a) as session:
        ops = {r.operation for r in session.scalars(select(ConsumptionLedger))}
        assert ops == {"iso_a"}
    with tenant_session(tenant_b) as session:
        ops = {r.operation for r in session.scalars(select(ConsumptionLedger))}
        assert ops == {"iso_b"}


# --- summarization (db) ---------------------------------------------------------------


@pytest.mark.db
def test_summarize_consumption(seeded_ab: tuple[object, object]) -> None:
    tenant_a, _ = seeded_ab
    _clear_ledger(tenant_a)

    with consumption_scope(tenant_a, meegle_work_item_id=88888, operation="summary_op"):
        record_consumption(
            provider="anthropic",
            model_id="claude-haiku-5-5",
            input_tokens=2000,
            output_tokens=500,
            cache_read_tokens=300,
            cost_usd=Decimal("0.0005"),
        )
        record_consumption(
            provider="scrapecreators",
            model_id="scrapecreators",
            cost_usd=Decimal("0.0019"),
            metadata={"credits": 1},
        )

    with tenant_session(tenant_a) as session:
        summary = summarize_consumption(session, tenant_id=tenant_a, meegle_work_item_id=88888)
        assert summary["total_cost_usd"] == pytest.approx(0.0024)
        assert summary["anthropic_input_tokens"] == 2000
        assert summary["anthropic_output_tokens"] == 500
        assert summary["anthropic_cache_read_tokens"] == 300
        assert summary["scrapecreators_credits"] == 1
        assert summary["records_count"] == 2
        assert "summary_op" in summary["by_operation"]


# --- Meegle sync (offline, via monkeypatch) -------------------------------------------


def _fake_ledger_row(
    *,
    cost_usd: str = "0.01",
    provider: str = "anthropic",
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> object:
    """A plain object with the attributes `summarize_consumption` reads — not a
    real `ConsumptionLedger` (SQLAlchemy's Mapped descriptors need instance state
    that `__new__` does not set up)."""
    row = type("_Row", (), {})()
    row.cost_usd = Decimal(cost_usd)
    row.provider = provider
    row.input_tokens = input_tokens
    row.output_tokens = output_tokens
    row.cache_read_tokens = 0
    row.cache_creation_tokens = 0
    row.operation = "claude_tools"
    row.extra_metadata = {}
    return row


class _FakeSession:
    """Yields a fixed list of ledger rows (or ids) from `scalars(...)` — the
    result supports both `.all()` (what `summarize_consumption` calls) and direct
    iteration (what `daily_consumption_sync` does over `scalars(...)`)."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self, _stmt: object) -> object:
        rows = self._rows

        class _R:
            def __iter__(self_inner: object) -> object:
                return iter(rows)

            def all(self_inner: object) -> list[object]:
                return rows

        return _R()


class _FakeAdminCM:
    """`with admin_session() as session:` → yields a `_FakeSession`."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def __enter__(self) -> _FakeSession:
        return self._session

    def __exit__(self, *args: object) -> None:
        return None


def _patch_admin_session(monkeypatch: pytest.MonkeyPatch, rows: list[object]) -> None:
    monkeypatch.setattr(
        "qualify_shared.db.admin.admin_session",
        lambda: _FakeAdminCM(_FakeSession(rows)),
        raising=True,
    )


def test_sync_consumption_to_meegle_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ledger rows → `empty`, no Meegle call."""
    _patch_admin_session(monkeypatch, [])
    assert sync_consumption_to_meegle(12345) == "empty"


def test_sync_consumption_to_meegle_meegle_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ledger has rows but the Meegle engine is off → `meegle_off`."""
    _patch_admin_session(monkeypatch, [_fake_ledger_row()])

    def _off(_wid: int, _md: str) -> str:
        return "meegle_off"

    monkeypatch.setattr("qualify_api.meegle.handlers.post_consumption_comment", _off, raising=True)
    assert sync_consumption_to_meegle(1) == "meegle_off"


def test_sync_consumption_to_meegle_posts_comment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ledger has rows and Meegle is on → a comment is posted, returns `synced`."""
    posted: list[tuple[int, str]] = []

    def _post(wid: int, md: str) -> str:
        posted.append((wid, md))
        return "synced"

    _patch_admin_session(monkeypatch, [_fake_ledger_row(input_tokens=100, output_tokens=50)])
    monkeypatch.setattr("qualify_api.meegle.handlers.post_consumption_comment", _post, raising=True)

    result = sync_consumption_to_meegle(777)
    assert result == "synced"
    assert len(posted) == 1
    assert posted[0][0] == 777
    assert "Consumo registrado" in posted[0][1]
    assert "100 / 50" in posted[0][1]


def test_sync_consumption_to_meegle_meegle_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Meegle transport failure → `meegle_failed`, never raises."""

    def _fails(_wid: int, _md: str) -> str:
        raise RuntimeError("meegle down")

    _patch_admin_session(monkeypatch, [_fake_ledger_row()])
    monkeypatch.setattr(
        "qualify_api.meegle.handlers.post_consumption_comment", _fails, raising=True
    )

    assert sync_consumption_to_meegle(1) == "meegle_failed"


# --- daily sync (offline) -------------------------------------------------------------


def test_daily_consumption_sync_aggregates(monkeypatch: pytest.MonkeyPatch) -> None:
    """The daily sync calls `sync_consumption_to_meegle` once per distinct work item."""
    calls: list[int] = []
    _patch_admin_session(monkeypatch, [10, 20, 30])
    monkeypatch.setattr(
        "qualify_api.consumption.sync_consumption_to_meegle",
        lambda wid: calls.append(wid) or "synced",
    )

    report = daily_consumption_sync()
    assert calls == [10, 20, 30]
    assert report == {"synced": 3, "empty": 0, "meegle_off": 0, "meegle_failed": 0}
