"""m-24852163 against Postgres: `creative-worker` through the real doors.

The fair claim (`PostgresQueueStore.claim_fair`: advisory lock → snapshot → `lanes`
pick → `claim_job`) and the worker's steps run as `qualify_creative_worker` and as
`qualify_app` under `tenant_session`, on a pool of their own (`test:<uuid>`, 10 slots),
with a fake executor in place of BytePlus. Pins: fair share and reserved slots in SQL, a
crash resumed by `vendor_task_id` with one submit, a 429 deferred without failing,
tenant isolation of the worker's tenant-side steps, and the scoped (`--tenant`) run.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from qualify_api.creative import job_queue as q
from qualify_api.creative.worker import lanes, runner
from qualify_api.creative.worker.downloads import DownloadGate
from qualify_api.creative.worker.runner import CreativeWorker, WorkerConfig
from qualify_api.creative.worker.store import PostgresQueueStore

from .test_creative_worker_runner import FakeBytePlus

pytestmark = pytest.mark.db

SIZE = 10


@pytest.fixture(scope="module")
def owner() -> Iterator[Engine]:
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def pool(owner: Engine) -> Iterator[str]:
    name = f"test:{uuid4()}"
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO vendor_slots (vendor_model, slot_no) "
                "SELECT :pool, n FROM generate_series(1, :count) AS n"
            ),
            {"pool": name, "count": SIZE},
        )
    try:
        yield name
    finally:
        with owner.begin() as conn:
            conn.execute(text("DELETE FROM vendor_slots WHERE vendor_model = :p"), {"p": name})
            conn.execute(text("DELETE FROM creative_jobs WHERE vendor_model = :p"), {"p": name})


def _draft(tenant_id: UUID) -> UUID:
    draft_id = uuid4()
    with tenant_session(tenant_id) as session:
        brand_id = session.execute(
            text("SELECT id FROM brands WHERE tenant_id = :t ORDER BY created_at LIMIT 1"),
            {"t": tenant_id},
        ).scalar_one()
        brief_id = session.execute(
            text(
                """
                INSERT INTO content_briefs (tenant_id, brand_id, objective, topic, platform,
                    format, intent, content_type, image_route)
                VALUES (:t, :b, 'o', 't', 'instagram', 'reel', 'i', 'video', 'r')
                RETURNING id
                """
            ),
            {"t": tenant_id, "b": brand_id},
        ).scalar_one()
        session.execute(
            text(
                "INSERT INTO content_drafts (id, tenant_id, brief_id, brand_id, status) "
                "VALUES (:d, :t, :brief, :b, 'drafting')"
            ),
            {"d": draft_id, "t": tenant_id, "brief": brief_id, "b": brand_id},
        )
    return draft_id


def _enqueue(tenant_id: UUID, pool: str, *, kind: str = q.KIND_PREVIEW, **kw: object) -> UUID:
    with tenant_session(tenant_id) as session:
        return q.enqueue_job(
            session,
            tenant_id=tenant_id,
            draft_id=_draft(tenant_id),
            kind=kind,
            revision=1,
            vendor_model=pool,
            lane=str(kw.pop("lane", q.LANE_IMMEDIATE)),
            pricing_version="v7",
            pipeline_version="test",
            **kw,  # type: ignore[arg-type]
        ).job_id


def _job(owner: Engine, job_id: UUID) -> dict:
    with owner.connect() as conn:
        return dict(
            conn.execute(text("SELECT * FROM creative_jobs WHERE id = :id"), {"id": job_id})
            .mappings()
            .one()
        )


def _slot(owner: Engine, job_id: UUID) -> int | None:
    with owner.connect() as conn:
        return conn.execute(
            text("SELECT slot_no FROM vendor_slots WHERE holder_job_id = :id"), {"id": job_id}
        ).scalar_one_or_none()


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC) + timedelta(seconds=1)

    def __call__(self) -> datetime:
        return self.now


def _worker(
    pool: str, vendor: FakeBytePlus, clock: Clock, tenants: list[UUID] | None = None
) -> CreativeWorker:
    return CreativeWorker(
        PostgresQueueStore(),
        {pool: vendor},
        WorkerConfig(pools={pool: SIZE}, tenant_ids=tenants, worker_id=f"w-{uuid4()}"),
        downloads=DownloadGate(2),
        clock=clock,
    )


def _claim(
    store: PostgresQueueStore, pool: str, now: datetime, tenants=None
) -> q.ClaimedJob | None:
    return store.claim_fair(
        vendor_model=pool,
        size=SIZE,
        worker_id="w",
        lease=runner.LEASE,
        now=now,
        tenant_ids=tenants,
    )


# -- fair share and reserved slots, in SQL ---------------------------------------------------


def test_fair_claim_takes_turns_and_caps_two_per_business(
    seeded_ab: tuple[UUID, UUID], pool: str
) -> None:
    tenant_a, tenant_b = seeded_ab
    a_jobs = [_enqueue(tenant_a, pool) for _ in range(5)]
    b_job = _enqueue(tenant_b, pool)
    store, now = PostgresQueueStore(), datetime.now(UTC) + timedelta(seconds=1)

    claimed = []
    while (claim := _claim(store, pool, now)) is not None:
        claimed.append(claim)
    tenants = [c.tenant_id for c in claimed]
    assert tenants[:2] == [tenant_a, tenant_b]  # oldest first, then the other business
    assert tenants.count(tenant_a) == lanes.MAX_PER_TENANT
    assert [c.job_id for c in claimed if c.tenant_id == tenant_b] == [b_job]
    assert {c.job_id for c in claimed if c.tenant_id == tenant_a} <= set(a_jobs)


def test_reserved_slots_keep_three_for_now_and_final(
    seeded_ab: tuple[UUID, UUID], pool: str, owner: Engine
) -> None:
    tenant_a, tenant_b = seeded_ab
    # 7 standard in flight, held through the owner (any business, the cap is the pool's)
    fillers = [_enqueue(tenant_a, pool) for _ in range(7)]
    with owner.begin() as conn:
        for n, job_id in enumerate(fillers, start=1):
            conn.execute(
                text(
                    "UPDATE creative_jobs SET status = 'submitted', vendor_task_id = :t, "
                    "claimed_by = 'other', lease_until = now() + interval '5 min' WHERE id = :id"
                ),
                {"t": f"cgt-fill-{n}", "id": job_id},
            )
            conn.execute(
                text(
                    "UPDATE vendor_slots SET holder_job_id = :id WHERE vendor_model = :p "
                    "AND slot_no = :n"
                ),
                {"id": job_id, "p": pool, "n": n},
            )
    standard = _enqueue(tenant_b, pool)
    store, now = PostgresQueueStore(), datetime.now(UTC) + timedelta(seconds=1)
    assert _claim(store, pool, now) is None  # a standard job waits

    urgent = _enqueue(tenant_b, pool, kind=q.KIND_FINAL)
    claim = _claim(store, pool, now + timedelta(seconds=1))
    assert claim is not None and claim.job_id == urgent
    assert _job(owner, standard)["status"] == q.QUEUED


# -- the worker through the doors ----------------------------------------------------------


def test_crash_mid_job_resumes_by_vendor_task_id_with_one_submit(
    seeded_ab: tuple[UUID, UUID], pool: str, owner: Engine
) -> None:
    tenant_a, _ = seeded_ab
    job_id = _enqueue(tenant_a, pool)
    clock = Clock()
    vendor = FakeBytePlus(crash_on_poll=True)
    first = _worker(pool, vendor, clock)
    (claim,) = first.claim_round(1)
    with pytest.raises(BaseException):  # noqa: B017 — the fake process death
        first.process(claim)
    row = _job(owner, job_id)
    assert (row["status"], row["vendor_task_id"]) == (q.SUBMITTED, "cgt-1")

    clock.now += runner.LEASE + timedelta(seconds=5)
    vendor.crash_on_poll = False
    second = _worker(pool, vendor, clock)
    recovery = second.recover()
    assert job_id in recovery.requeued
    assert _slot(owner, job_id) is not None  # BytePlus still counts the task

    (again,) = second.claim_round(1)
    assert again.job_id == job_id
    assert second.process(again) == runner.SUCCEEDED_OUTCOME
    assert vendor.submits == [job_id]
    row = _job(owner, job_id)
    assert (row["status"], row["vendor_task_id"], row["attempts"]) == (q.SUCCEEDED, "cgt-1", 2)
    assert _slot(owner, job_id) is None


def test_a_429_defers_the_job_without_failing_it(
    seeded_ab: tuple[UUID, UUID], pool: str, owner: Engine
) -> None:
    tenant_a, _ = seeded_ab
    job_id = _enqueue(tenant_a, pool)
    clock = Clock()
    worker = _worker(pool, FakeBytePlus(busy=1), clock)
    (claim,) = worker.claim_round(1)
    assert worker.process(claim) == runner.DEFERRED
    row = _job(owner, job_id)
    assert row["status"] == q.QUEUED and row["last_error"] is None
    assert row["attempts"] == 0 and row["vendor_task_id"] is None
    assert row["not_before"] >= clock.now + timedelta(seconds=59)
    assert row["claimed_by"] is None and row["claim_token"] == claim.claim_token + 1
    assert _slot(owner, job_id) is None
    assert worker.claim_round(1) == []


def test_the_worker_cannot_read_another_business_job(
    seeded_ab: tuple[UUID, UUID], pool: str, owner: Engine
) -> None:
    """Security review threat #1 in SQL: the tenant-side steps of a claim handed the wrong
    business find nothing and write nothing."""
    tenant_a, tenant_b = seeded_ab
    job_id = _enqueue(tenant_a, pool)
    store = PostgresQueueStore()
    claim = _claim(store, pool, datetime.now(UTC) + timedelta(seconds=1))
    assert claim is not None
    forged = q.ClaimedJob(
        job_id=claim.job_id, tenant_id=tenant_b, claim_token=claim.claim_token, slot_no=1
    )
    assert store.load(forged) is None
    assert store.record_submission(forged, vendor_task_id="cgt-x", now=datetime.now(UTC)) is False
    assert store.settle(forged, status=q.FAILED, now=datetime.now(UTC), last_error="x") is False
    assert _job(owner, job_id)["vendor_task_id"] is None

    vendor = FakeBytePlus()
    worker = _worker(pool, vendor, Clock())
    assert worker.process(forged) == runner.MISSING
    assert vendor.submits == []


def test_a_scoped_worker_sees_only_its_tenants(seeded_ab: tuple[UUID, UUID], pool: str) -> None:
    tenant_a, tenant_b = seeded_ab
    _enqueue(tenant_b, pool)
    mine = _enqueue(tenant_a, pool)
    worker = _worker(pool, FakeBytePlus(), Clock(), tenants=[tenant_a])
    claims = worker.claim_round(10)
    assert [c.job_id for c in claims] == [mine]


def test_two_workers_claiming_at_once_never_give_a_business_a_third_slot(
    seeded_ab: tuple[UUID, UUID], pool: str
) -> None:
    """The advisory lock keeps the snapshot true until the claim."""
    tenant_a, _ = seeded_ab
    for _ in range(12):
        _enqueue(tenant_a, pool)
    store, now = PostgresQueueStore(), datetime.now(UTC) + timedelta(seconds=1)
    claims: list[q.ClaimedJob] = []
    lock = threading.Lock()

    def claimer() -> None:
        while (claim := _claim(store, pool, now)) is not None:
            with lock:
                claims.append(claim)

    threads = [threading.Thread(target=claimer) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(claims) == lanes.MAX_PER_TENANT


def test_shutdown_hand_back_keeps_the_slot_of_a_submitted_job(
    seeded_ab: tuple[UUID, UUID], pool: str, owner: Engine
) -> None:
    tenant_a, _ = seeded_ab
    job_id = _enqueue(tenant_a, pool)
    store = PostgresQueueStore()
    now = datetime.now(UTC) + timedelta(seconds=1)
    claim = _claim(store, pool, now)
    assert claim is not None
    assert store.record_submission(claim, vendor_task_id="cgt-keep", now=now)
    assert store.hand_back(claim, now=now)
    row = _job(owner, job_id)
    assert (row["status"], row["vendor_task_id"]) == (q.QUEUED, "cgt-keep")
    assert _slot(owner, job_id) is not None
    # the next claim takes it first and keeps the same slot
    again = _claim(store, pool, now)
    assert again is not None and again.job_id == job_id and again.slot_no == claim.slot_no
