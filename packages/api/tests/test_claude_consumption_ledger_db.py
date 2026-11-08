"""m-24955649 against Postgres: the Claude interceptor's row in `consumption_ledger` —
its shape, the tenant door it is written through (RLS), and that a scope of another
business around the call cannot misfile it."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import delete, select

from qualify_api import claude_tools
from qualify_api.claude_tools import Attribution, ClaudeConsumption
from qualify_api.consumption import consumption_scope
from qualify_api.consumption.models import ConsumptionLedger
from qualify_api.tenancy.models import Brand

pytestmark = pytest.mark.db


def _brand_of(tenant_id: UUID) -> UUID:
    with admin_session() as session:
        return session.scalar(select(Brand.id).where(Brand.tenant_id == tenant_id))


def _record(attribution: Attribution) -> ClaudeConsumption:
    return ClaudeConsumption(
        attribution=attribution,
        model_id="claude-haiku-5-5",
        model_revision="claude-haiku-5-5-20261008",
        input_tokens=1_000,
        output_tokens=200,
        cache_read_tokens=3_000,
        cache_creation_tokens=500,
        cost_usd=Decimal("0.0002925"),
        priced=True,
    )


def _rows(tenant_id: UUID, feature: str) -> list[ConsumptionLedger]:
    with tenant_session(tenant_id) as session:
        return list(
            session.scalars(select(ConsumptionLedger).where(ConsumptionLedger.operation == feature))
        )


def _forget(feature: str) -> None:
    with admin_session() as session:
        session.execute(delete(ConsumptionLedger).where(ConsumptionLedger.operation == feature))


def test_a_booked_call_is_one_row_of_its_business_with_full_provenance(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = seeded_ab
    brand = _brand_of(tenant_a)
    feature = f"test-{uuid4().hex[:8]}"
    try:
        paid = Attribution(
            tenant_id=tenant_a, brand_id=brand, feature=feature, prompt_version="wa-suggest-1"
        )
        claude_tools.ledger_sink(_record(paid))
        (row,) = _rows(tenant_a, feature)
        assert row.tenant_id == tenant_a and row.brand_id == brand
        assert row.provider == "anthropic" and row.model_id == "claude-haiku-5-5"
        assert (row.input_tokens, row.output_tokens) == (1_000, 200)
        assert (row.cache_read_tokens, row.cache_creation_tokens) == (3_000, 500)
        assert row.cost_usd == Decimal("0.000293")  # Numeric(12, 6)
        assert row.pricing_table_version == "v7"
        assert row.extra_metadata == {
            "model_revision": "claude-haiku-5-5-20261008",
            "prompt_version": "wa-suggest-1",
        }
        assert row.idempotency_key is None and row.meegle_work_item_id is None
        # RLS: the other business never sees it
        assert _rows(tenant_b, feature) == []
    finally:
        _forget(feature)


def test_a_scope_of_another_business_cannot_misfile_the_row(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = seeded_ab
    feature = f"test-{uuid4().hex[:8]}"
    try:
        with consumption_scope(tenant_b, operation="someone-else") as scope:
            claude_tools.ledger_sink(_record(Attribution(tenant_id=tenant_a, feature=feature)))
            assert scope.records == []  # written now, under its own tenant
        assert len(_rows(tenant_a, feature)) == 1
        assert _rows(tenant_b, feature) == []
    finally:
        _forget(feature)


def test_sin_negocio_writes_no_row(seeded_ab: tuple[UUID, UUID]) -> None:
    del seeded_ab  # the tenants exist; none of them is charged
    feature = f"test-{uuid4().hex[:8]}"
    claude_tools.ledger_sink(_record(Attribution.no_business(feature)))
    with admin_session() as session:
        found = session.scalars(
            select(ConsumptionLedger).where(ConsumptionLedger.operation == feature)
        ).all()
    assert found == []
