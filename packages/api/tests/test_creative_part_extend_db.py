"""VE-13 (m-24921070) against Postgres: a «Sigue a la anterior» part finds the previous
part's file as the owning business (RLS), waits while that part has no vista previa —
its job stays queued, so the reaper spares it — and is let go (its `generation` run
dirtied) when the previous part settles; a part already made is never run again.

No vendor is called: the parts media is the parts tests' fake."""

from __future__ import annotations

import json
import time
from uuid import UUID, uuid4

import pytest
from qualify_creative.schemas import VideoPartPlan
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.dispatch import reap_stale_drafts
from qualify_api.creative.fsm import DRAFTING, GENERATED
from qualify_api.creative.part_extend import EXTEND_SWITCH, DbPreviousParts
from qualify_api.creative.parts import mark_parent_dirty

from .test_creative_parts import parent_brief
from .test_creative_parts_db import _business, _scalar, _service

pytestmark = pytest.mark.db

PLAN = (
    VideoPartPlan(mode="reference", seconds=5, description="La mano toma el vaso."),
    VideoPartPlan(mode="extend", seconds=5, description="Lo lleva a la mesa."),
)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    tenant, brand, user = _business(monkeypatch)
    service, parts, _copy = _service()
    brief = parent_brief(*PLAN).model_copy(update={"brand_id": brand})
    parent = service.create_draft(tenant_id=tenant, brand_id=brand, brief=brief, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=parent)
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    return service, tenant, parent, ids


def _run_versions(tenant: UUID, draft: UUID) -> tuple[int, int]:
    with tenant_session(tenant) as session:
        row = session.execute(
            text(
                "SELECT dirty_version, prepared_version FROM creative_pipeline_runs "
                "WHERE draft_id=:d AND phase='generation'"
            ),
            {"d": draft},
        ).one()
    return int(row[0]), int(row[1])


def _prepared(tenant: UUID, draft: UUID) -> None:
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE creative_pipeline_runs SET prepared_version=dirty_version "
                "WHERE draft_id=:d AND phase='generation'"
            ),
            {"d": draft},
        )


def _settle(tenant: UUID, child: UUID) -> None:
    with tenant_session(tenant) as session:
        mark_parent_dirty(session, child)


def test_an_extend_part_waits_then_is_let_go_by_the_previous_part_db(world) -> None:  # noqa: ANN001
    service, tenant, _parent, (first, second) = world
    assert DbPreviousParts()(tenant_id=tenant, draft_id=second).state == "waiting"
    _prepared(tenant, second)  # its preparation ran and deferred: nothing to do

    # the reaper spares it: its job is still queued, however old its last stamp
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET updated_at = now() - interval '2 hours' WHERE id=:d"),
            {"d": second},
        )
    reap_stale_drafts(tenant_id=tenant, older_than_minutes=20)
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:d", d=second) == DRAFTING
    assert (
        _scalar(tenant, "SELECT status::text FROM creative_jobs WHERE draft_id=:d", d=second)
        == "queued"
    )

    # the previous part gets its vista previa: the extend part runs again
    service.run_generation(tenant_id=tenant, draft_id=first)
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:d", d=first) == GENERATED
    raw = f"t/{tenant}/generated/{first}/r1/queue-{uuid4()}.bin"
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE image_assets SET media_type='video', params = COALESCE(params,'{}'::jsonb)"
                " || CAST(:p AS jsonb) WHERE draft_id=:d"
            ),
            {
                "d": first,
                "p": json.dumps({"part": {"raw_key": raw}, "draft": {"created_at": time.time()}}),
            },
        )
    dirty, prepared = _run_versions(tenant, second)
    assert dirty > prepared  # let go
    found = DbPreviousParts()(tenant_id=tenant, draft_id=second)
    assert found.state == "ready" and found.source is not None
    assert found.source.key == raw and found.source.draft_id == first


def test_a_made_extend_part_is_never_run_again_db(world) -> None:  # noqa: ANN001
    service, tenant, _parent, (first, second) = world
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status='generated' WHERE id=:d"), {"d": second}
        )
    _prepared(tenant, second)
    _settle(tenant, first)  # the previous part changed: «Hay que rehacerla», not remade
    dirty, prepared = _run_versions(tenant, second)
    assert dirty == prepared


def test_another_business_never_reads_the_previous_part_db(world, monkeypatch) -> None:  # noqa: ANN001
    _service_, _tenant, _parent, (_first, second) = world
    other, _brand, _user = _business(monkeypatch)
    assert DbPreviousParts()(tenant_id=other, draft_id=second).state == "missing"
