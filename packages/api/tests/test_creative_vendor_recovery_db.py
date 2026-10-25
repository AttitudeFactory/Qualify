"""m-24852492 against Postgres: the worker recovers a billed video with no screen read.

The real recovery store (reaper, waiting drafts, atomic claim), the real
`ContentService.run_generation` and the real task store; BytePlus's answers by id are a
fake and the media producer is the scripted one of `test_creative_vendor_tasks_db.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED
from qualify_api.creative.vendor_recovery import (
    PendingTask,
    PostgresRecoveryStore,
    discover_tenants,
    recover_once,
)

from .test_content_service import FakeCopyAdapter
from .test_creative_vendor_tasks_db import (
    Ledger,
    ScriptedMedia,
    _age,
    _draft,
    _service,
    _tasks,
    _usage,
)

pytestmark = pytest.mark.db


@pytest.fixture
def db_seeded() -> tuple[UUID, UUID, UUID]:
    from . import test_content_service as base

    return base.seed_db_tenant()


class Vendor:
    """BytePlus's state by task id (`get_task`)."""

    def __init__(self, state: str) -> None:
        self.state = state
        self.asked: list[str] = []

    def status(self, task: PendingTask, *, tenant_id: UUID, brand_id: UUID) -> str:
        self.asked.append(task.vendor_task_id)
        return self.state


def _waiting_draft(seeded: tuple[UUID, UUID, UUID], media: ScriptedMedia, ledger: Ledger):
    """A video draft whose wait ran out (task `cgt-1` pending) and whose thread has
    been silent for 10 min."""
    tenant_id = seeded[0]
    service = _service(media, ledger, FakeCopyAdapter())
    draft_id = _draft(service, seeded)
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)
    _age(tenant_id, draft_id, quiet=timedelta(minutes=10), task_age=timedelta(minutes=12))
    return service, draft_id


def _pass(service, tenant_id: UUID, vendor: Vendor):
    return recover_once(
        tenants=lambda _now: [tenant_id],
        store=PostgresRecoveryStore(),
        statuses=vendor,
        resume=lambda t, d: service.run_generation(tenant_id=t, draft_id=d),
    )


def _updated_at(tenant_id: UUID, draft_id: UUID) -> datetime:
    from qualify_shared.db.session import tenant_session

    from qualify_api.creative import models as orm

    with tenant_session(tenant_id) as session:
        return session.get(orm.ContentDraft, draft_id).updated_at


def test_the_worker_lands_a_succeeded_video_and_its_cost_without_a_screen_read(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id = db_seeded[0]
    media, ledger = ScriptedMedia(), Ledger()
    service, draft_id = _waiting_draft(db_seeded, media, ledger)
    vendor = Vendor("succeeded")

    report = _pass(service, tenant_id, vendor)

    assert draft_id in report.resumed and "cgt-1" in vendor.asked
    detail = service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert detail.status == GENERATED
    assert [m.media_type for m in detail.media] == ["video"]
    assert _usage(tenant_id, draft_id) == ["anthropic", "seedance"]
    assert [t[2] for t in _tasks(tenant_id, draft_id)] == ["succeeded"]
    # (the shared test tenant may hold other suites' waiting drafts: only ours counted)
    assert report.resumed.count(draft_id) == 1
    assert draft_id not in [r["draft_id"] for r in ledger.refunds]


def test_twice_and_beside_a_screen_read_nothing_is_duplicated(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id = db_seeded[0]
    media, ledger = ScriptedMedia(), Ledger()
    service, draft_id = _waiting_draft(db_seeded, media, ledger)
    vendor = Vendor("succeeded")

    # a screen read claims it first (stamps it and hands it to its dispatcher)
    service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert service.dispatcher.generations.count(draft_id) == 2
    report = _pass(service, tenant_id, vendor)
    assert draft_id not in report.resumed  # no longer quiet: the worker backs off

    # quiet again: the worker resumes it once; further passes and reads change nothing
    _age(tenant_id, draft_id, quiet=timedelta(minutes=10), task_age=timedelta(minutes=30))
    assert draft_id in _pass(service, tenant_id, vendor).resumed
    assert draft_id not in _pass(service, tenant_id, vendor).resumed
    service.get_draft(tenant_id=tenant_id, draft_id=draft_id)
    assert service.dispatcher.generations.count(draft_id) == 2
    service.run_generation(tenant_id=tenant_id, draft_id=draft_id)  # a late screen run
    assert _usage(tenant_id, draft_id) == ["anthropic", "seedance"]
    assert [t[2] for t in _tasks(tenant_id, draft_id)] == ["succeeded"]
    assert draft_id not in [r["draft_id"] for r in ledger.refunds]


@pytest.mark.parametrize("state", ["failed", "expired", "unknown"])
def test_a_failed_expired_or_unknown_task_fails_the_piece_unpaid_and_refunded(
    db_seeded: tuple[UUID, UUID, UUID], state: str
) -> None:
    tenant_id = db_seeded[0]
    # the resumed run hears BytePlus's verdict through the media producer
    media, ledger = ScriptedMedia(verdict="failed"), Ledger()
    service, draft_id = _waiting_draft(db_seeded, media, ledger)

    report = _pass(service, tenant_id, Vendor(state))

    assert draft_id in report.resumed
    assert service.get_draft(tenant_id=tenant_id, draft_id=draft_id).status == FAILED
    assert _usage(tenant_id, draft_id) == ["anthropic"]
    assert [r["draft_id"] for r in ledger.refunds].count(draft_id) == 1


def test_a_task_still_running_is_neither_claimed_nor_resumed(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id = db_seeded[0]
    service, draft_id = _waiting_draft(db_seeded, ScriptedMedia(), Ledger())
    before = _updated_at(tenant_id, draft_id)

    report = _pass(service, tenant_id, Vendor("running"))

    assert draft_id in report.still_running and draft_id not in report.resumed
    assert _updated_at(tenant_id, draft_id) == before
    assert service.get_draft(tenant_id=tenant_id, draft_id=draft_id).status == DRAFTING


def test_another_business_never_sees_claims_or_resumes_the_draft(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id = db_seeded[0]
    service, draft_id = _waiting_draft(db_seeded, ScriptedMedia(), Ledger())
    store, other = PostgresRecoveryStore(), uuid4()

    assert store.waiting(tenant_id=other, now=datetime.now(UTC)) == []
    assert store.claim(tenant_id=other, draft_id=draft_id) is False
    report = _pass(service, other, Vendor("succeeded"))
    assert report.resumed == []
    # still waiting, untouched, for its own business (checked before a screen read
    # would claim it)
    mine = store.waiting(tenant_id=tenant_id, now=datetime.now(UTC))
    assert any(w.draft_id == draft_id for w in mine)
    assert service.get_draft(tenant_id=tenant_id, draft_id=draft_id).status == DRAFTING


def test_production_discovery_lists_the_tenant_of_a_quiet_draft(
    db_seeded: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id = db_seeded[0]
    _waiting_draft(db_seeded, ScriptedMedia(), Ledger())
    assert tenant_id in discover_tenants(datetime.now(UTC))
