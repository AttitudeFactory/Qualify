"""m-24852203 against Postgres: with `QUALIFY_META_READS=fixture`, the inbox's published
seams work for a connection that has NO credential (the e2e/local case), and a fixture
exported from a connection's own rows re-syncs without adding anything."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from qualify_api.inbox import composition
from qualify_api.inbox import simulator as sim

from .test_sentiment_repository import _seed_connection_only

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _fixture_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sim.META_READS_ENV, "fixture")
    monkeypatch.delenv(sim.DEPLOY_ENV, raising=False)
    monkeypatch.delenv(sim.FIXTURE_PATH_ENV, raising=False)


async def test_list_monitor_and_sync_without_a_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = uuid4()
    connection = _seed_connection_only(tenant)  # active, fake external id, no credential

    candidates = await composition.list_candidate_media(tenant_id=tenant, connection_id=connection)
    assert {c.external_media_id for c in candidates} >= {"17900000000000001"}

    await composition.set_media_monitored(
        tenant_id=tenant,
        connection_id=connection,
        external_media_id="17900000000000001",
        monitored=True,
    )
    summary = await composition.sync_comments(tenant_id=tenant, connection_id=connection)
    assert (summary.media_checked, summary.new_comments) == (1, 4)


async def test_an_exported_fixture_resyncs_without_adding_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tenant = uuid4()
    connection = _seed_connection_only(tenant)
    await composition.set_media_monitored(
        tenant_id=tenant,
        connection_id=connection,
        external_media_id="17900000000000003",
        monitored=True,
    )
    await composition.sync_comments(tenant_id=tenant, connection_id=connection)

    exported = sim.export_tenant_fixture(tenant_id=tenant, connection_id=connection)
    assert [m["id"] for m in exported["media"]] == ["17900000000000003"]
    assert len(exported["comments"]["17900000000000003"]) == 3
    path = tmp_path / "mine.json"
    path.write_text(json.dumps(exported), encoding="utf-8")
    monkeypatch.setenv(sim.FIXTURE_PATH_ENV, str(path))

    again = await composition.sync_comments(tenant_id=tenant, connection_id=connection)
    assert (again.new_comments, again.deleted_comments) == (0, 0)
