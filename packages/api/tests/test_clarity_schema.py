"""`db`-marked tests for migration 0006: RLS isolation of the two clarity tables and
the settings upsert. Same discipline as `test_leads_schema` — assertions run as
`qualify_app`, subject to RLS."""

from __future__ import annotations

from uuid import UUID

import pytest

from qualify_api.clarity.repository import PostgresClarityRepository

pytestmark = pytest.mark.db


@pytest.fixture
def configured_a(seeded_ab: tuple[UUID, UUID]) -> tuple[UUID, UUID]:
    tenant_a, tenant_b = seeded_ab
    # Idempotent (ON CONFLICT on the per-tenant unique), so `just test-db` re-runs clean.
    PostgresClarityRepository().upsert_settings(
        tenant_id=tenant_a,
        project_id="proj-a",
        token_ciphertext=b"ciphertext-a",
        token_key_id="dev-1",
    )
    return tenant_a, tenant_b


def test_settings_do_not_leak_across_tenants(configured_a: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = configured_a
    repo = PostgresClarityRepository()
    assert repo.get_settings(tenant_id=tenant_a) is not None
    assert repo.get_settings(tenant_id=tenant_b) is None


def test_settings_upsert_replaces_in_place(configured_a: tuple[UUID, UUID]) -> None:
    tenant_a, _ = configured_a
    repo = PostgresClarityRepository()
    first = repo.upsert_settings(
        tenant_id=tenant_a,
        project_id="proj-a",
        token_ciphertext=b"ciphertext-1",
        token_key_id="dev-1",
    )
    second = repo.upsert_settings(
        tenant_id=tenant_a,
        project_id="proj-a2",
        token_ciphertext=b"ciphertext-2",
        token_key_id="dev-2",
    )
    assert first == second  # same row, updated — the per-tenant unique held
    stored = repo.get_settings(tenant_id=tenant_a)
    assert stored is not None
    assert stored.project_id == "proj-a2"
    assert stored.token_ciphertext == b"ciphertext-2"
    assert stored.token_key_id == "dev-2"


def test_snapshots_are_tenant_scoped(configured_a: tuple[UUID, UUID]) -> None:
    tenant_a, tenant_b = configured_a
    repo = PostgresClarityRepository()
    inserted = repo.insert_snapshot(
        tenant_id=tenant_a,
        num_of_days=1,
        dimensions=["URL"],
        payload=[{"metricName": "Traffic", "information": []}],
    )

    mine = repo.latest_snapshot(tenant_id=tenant_a)
    assert mine is not None
    assert mine.id == inserted.id
    assert mine.dimensions == ["URL"]
    # B's scope sees nothing — the RLS read that matters.
    assert repo.latest_snapshot(tenant_id=tenant_b) is None
    assert repo.fetches_on(tenant_id=tenant_b, day=inserted.fetched_at.date()) == 0
    assert repo.fetches_on(tenant_id=tenant_a, day=inserted.fetched_at.date()) >= 1
