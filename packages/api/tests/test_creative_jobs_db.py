"""m-24852160 against Postgres: the generation queue of ADR 41 (migration 0096).

Each test runs on a pool of its own (`test:<uuid>`, ten slots inserted by the owner and
deleted afterwards), so the cap is measured without the seeded BytePlus pools nor other
tests. Jobs go through the real doors: the owner's side by `tenant_session`, the worker's
by `creative_worker_session` (role `qualify_creative_worker`, NOBYPASSRLS, column grants).

Pins the acceptance criteria of the ticket and the tests listed in
`docs/seguridad-creative-worker.md` §6.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from psycopg.errors import InsufficientPrivilege
from qualify_shared.db.config import admin_dsn, app_dsn, creative_worker_dsn
from qualify_shared.db.creative_worker import creative_worker_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.creative import job_queue as q

pytestmark = pytest.mark.db

POOL_SIZE = 10
LEASE = timedelta(minutes=2)


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
            {"pool": name, "count": POOL_SIZE},
        )
    try:
        yield name
    finally:
        with owner.begin() as conn:
            conn.execute(text("DELETE FROM vendor_slots WHERE vendor_model = :p"), {"p": name})
            conn.execute(text("DELETE FROM creative_jobs WHERE vendor_model = :p"), {"p": name})


def _draft(tenant_id: UUID) -> UUID:
    """A minimal piece of `tenant_id` (brief + draft), as the owner's app would write it."""
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


def _enqueue(tenant_id: UUID, pool: str, *, draft_id: UUID | None = None, **kw: object) -> UUID:
    draft = draft_id or _draft(tenant_id)
    with tenant_session(tenant_id) as session:
        return q.enqueue_job(
            session,
            tenant_id=tenant_id,
            draft_id=draft,
            kind=str(kw.pop("kind", q.KIND_PREVIEW)),
            revision=1,
            vendor_model=pool,
            lane=q.LANE_IMMEDIATE,
            pricing_version="v7",
            pipeline_version="test",
            **kw,  # type: ignore[arg-type]
        ).job_id


def _claim(pool: str, now: datetime, worker: str = "w1") -> q.ClaimedJob | None:
    with creative_worker_session() as session:
        return q.claim_next(
            session, vendor_model=pool, size=POOL_SIZE, worker_id=worker, lease=LEASE, now=now
        )


def _job(owner: Engine, job_id: UUID) -> dict:
    with owner.connect() as conn:
        return dict(
            conn.execute(text("SELECT * FROM creative_jobs WHERE id = :id"), {"id": job_id})
            .mappings()
            .one()
        )


def _holder_slot(owner: Engine, job_id: UUID) -> int | None:
    with owner.connect() as conn:
        return conn.execute(
            text("SELECT slot_no FROM vendor_slots WHERE holder_job_id = :id"), {"id": job_id}
        ).scalar_one_or_none()


def _now() -> datetime:
    return datetime.now(UTC)


# --- schema -----------------------------------------------------------------------------


def test_vendor_slots_columns_are_pinned_and_it_has_no_rls(owner: Engine) -> None:
    """Security review §4: no `tenant_id`, no draft, no free text — ever."""
    with owner.connect() as conn:
        columns = set(
            conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'vendor_slots'"
                )
            ).scalars()
        )
        rls = conn.execute(
            text("SELECT relrowsecurity FROM pg_class WHERE oid = 'vendor_slots'::regclass")
        ).scalar_one()
    assert columns == {"vendor_model", "slot_no", "holder_job_id", "lease_until", "updated_at"}
    assert rls is False


def test_creative_jobs_has_forced_rls_and_the_worker_policy(owner: Engine) -> None:
    with owner.connect() as conn:
        enabled, forced = conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = 'creative_jobs'::regclass"
            )
        ).one()
        policies = dict(
            conn.execute(
                text("SELECT policyname, qual FROM pg_policies WHERE tablename = 'creative_jobs'")
            ).all()
        )
        worker = conn.execute(
            text("SELECT rolbypassrls, rolsuper FROM pg_roles WHERE rolname = :r"),
            {"r": "qualify_creative_worker"},
        ).one()
    assert enabled and forced
    assert set(policies) == {"tenant_isolation", "creative_worker_claim"}
    assert "NULLIF" in policies["tenant_isolation"]
    assert tuple(worker) == (False, False)


def test_seeded_pools_exist(owner: Engine) -> None:
    with owner.connect() as conn:
        counts = dict(
            conn.execute(
                text(
                    "SELECT vendor_model, count(*) FROM vendor_slots "
                    "WHERE vendor_model NOT LIKE 'test:%' GROUP BY vendor_model"
                )
            ).all()
        )
    assert counts == dict(q.SEEDED_SLOTS)


# --- the cap --------------------------------------------------------------------------------


def test_twenty_concurrent_claims_never_hold_more_than_ten_slots(
    seeded_ab: tuple[UUID, UUID], pool: str, owner: Engine
) -> None:
    tenant_a, tenant_b = seeded_ab
    for i in range(20):
        _enqueue(tenant_a if i % 2 else tenant_b, pool)
    now = _now()
    barrier = threading.Barrier(20)
    results: list[q.ClaimedJob | None] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def claimer(n: int) -> None:
        try:
            barrier.wait(timeout=30)
            claimed = _claim(pool, now, worker=f"w{n}")
            with lock:
                results.append(claimed)
        except BaseException as exc:  # surfaced below
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=claimer, args=(n,)) for n in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == []
    claimed = [r for r in results if r is not None]
    assert len(claimed) <= POOL_SIZE
    assert len({c.job_id for c in claimed}) == len(claimed)
    assert len({c.slot_no for c in claimed}) == len(claimed)
    with creative_worker_session() as session:
        assert q.slots_in_use(session, pool) == len(claimed) <= POOL_SIZE

    # whatever SKIP LOCKED left unclaimed is claimable later, still never past the cap
    while _claim(pool, now) is not None:
        pass
    with creative_worker_session() as session:
        assert q.slots_in_use(session, pool) == POOL_SIZE
    with owner.connect() as conn:
        live = conn.execute(
            text(
                "SELECT count(*) FROM creative_jobs WHERE vendor_model = :p "
                "AND status = 'claimed' AND lease_until > now()"
            ),
            {"p": pool},
        ).scalar_one()
    assert live == POOL_SIZE


# --- recovery ---------------------------------------------------------------------------------


def test_expired_lease_requeues_and_never_resubmits_a_paid_task(
    seeded_ab: tuple[UUID, UUID], pool: str, owner: Engine
) -> None:
    tenant_a, _ = seeded_ab
    paid = _enqueue(tenant_a, pool)
    unsent = _enqueue(tenant_a, pool)
    now = _now()
    first = _claim(pool, now)
    second = _claim(pool, now)
    assert first is not None and second is not None
    by_id = {first.job_id: first, second.job_id: second}
    with tenant_session(tenant_a) as session:
        assert q.record_submission(
            session,
            job_id=paid,
            claim_token=by_id[paid].claim_token,
            vendor_task_id="cgt-paid",
            now=now,
        )
    paid_slot = _holder_slot(owner, paid)

    # the worker dies: both leases run out
    later = now + LEASE + timedelta(seconds=1)
    with creative_worker_session() as session:
        recovery = q.recover_expired(session, now=later)
    assert set(recovery.requeued) == {paid, unsent}
    assert recovery.released_slots == 1 and recovery.kept_slots == 1

    paid_row = _job(owner, paid)
    assert paid_row["status"] == q.QUEUED
    assert paid_row["vendor_task_id"] == "cgt-paid"  # kept: it will be polled, not resent
    assert _holder_slot(owner, paid) == paid_slot  # BytePlus still counts it
    assert _holder_slot(owner, unsent) is None
    assert _job(owner, unsent)["status"] == q.QUEUED

    # the dead holder's token writes nothing any more
    with creative_worker_session() as session:
        assert not q.renew_lease(
            session, job_id=paid, claim_token=by_id[paid].claim_token, lease=LEASE, now=later
        )

    # the next claim takes the paid job first, on its own slot, and cannot resubmit it
    again = _claim(pool, later, worker="w2")
    assert again is not None and again.job_id == paid and again.slot_no == paid_slot
    assert again.claim_token > by_id[paid].claim_token
    with tenant_session(tenant_a) as session:
        assert not q.record_submission(
            session, job_id=paid, claim_token=again.claim_token, vendor_task_id="cgt-2", now=later
        )
    assert _job(owner, paid)["vendor_task_id"] == "cgt-paid"


def test_a_slot_is_released_only_when_its_job_is_over(
    seeded_ab: tuple[UUID, UUID], pool: str, owner: Engine
) -> None:
    tenant_a, _ = seeded_ab
    job_id = _enqueue(tenant_a, pool)
    now = _now()
    claimed = _claim(pool, now)
    assert claimed is not None
    with creative_worker_session() as session:
        assert not q.release_slot(session, job_id=job_id, now=now)
    with tenant_session(tenant_a) as session:
        assert q.record_submission(
            session, job_id=job_id, claim_token=claimed.claim_token, vendor_task_id="t", now=now
        )
        assert q.settle_job(
            session, job_id=job_id, claim_token=claimed.claim_token, status=q.SUCCEEDED, now=now
        )
    with creative_worker_session() as session:
        assert q.release_slot(session, job_id=job_id, now=now)
        assert q.slots_in_use(session, pool) == 0
    assert _job(owner, job_id)["finished_at"] is not None


def test_a_full_pool_leaves_the_job_queued(seeded_ab: tuple[UUID, UUID], pool: str) -> None:
    tenant_a, _ = seeded_ab
    for _ in range(POOL_SIZE + 1):
        _enqueue(tenant_a, pool)
    now = _now()
    for _ in range(POOL_SIZE):
        assert _claim(pool, now) is not None
    assert _claim(pool, now) is None


# --- idempotency and isolation -----------------------------------------------------------------


def test_enqueueing_the_same_step_twice_makes_one_job(
    seeded_ab: tuple[UUID, UUID], pool: str, owner: Engine
) -> None:
    tenant_a, _ = seeded_ab
    draft = _draft(tenant_a)
    with tenant_session(tenant_a) as session:
        kwargs = dict(
            tenant_id=tenant_a,
            draft_id=draft,
            kind=q.KIND_FINAL,
            revision=2,
            vendor_model=pool,
            lane=q.LANE_NIGHTLY,
        )
        first = q.enqueue_job(session, **kwargs)  # type: ignore[arg-type]
        second = q.enqueue_job(session, **kwargs)  # type: ignore[arg-type]
    assert first.created and not second.created
    assert first.job_id == second.job_id
    with owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM creative_jobs WHERE draft_id = :d"), {"d": draft}
            ).scalar_one()
            == 1
        )


def test_a_business_cannot_read_nor_cancel_another_businesss_job(
    seeded_ab: tuple[UUID, UUID], pool: str
) -> None:
    tenant_a, tenant_b = seeded_ab
    job_id = _enqueue(tenant_a, pool)
    with tenant_session(tenant_b) as session:
        seen = session.execute(
            text("SELECT count(*) FROM creative_jobs WHERE id = :id"), {"id": job_id}
        ).scalar_one()
        assert seen == 0
        assert not q.cancel_job(session, job_id)
    with tenant_session(tenant_a) as session:
        assert q.cancel_job(session, job_id)


def test_a_job_on_another_businesss_piece_is_rejected(
    seeded_ab: tuple[UUID, UUID], pool: str
) -> None:
    """Threat #2: the composite FK refuses B's job on A's draft at insert."""
    tenant_a, tenant_b = seeded_ab
    draft_of_a = _draft(tenant_a)
    with pytest.raises(IntegrityError):
        _enqueue(tenant_b, pool, draft_id=draft_of_a)


def test_vendor_task_id_is_write_once(seeded_ab: tuple[UUID, UUID], pool: str) -> None:
    tenant_a, _ = seeded_ab
    job_id = _enqueue(tenant_a, pool)
    claimed = _claim(pool, _now())
    assert claimed is not None
    with tenant_session(tenant_a) as session:
        assert q.record_submission(
            session,
            job_id=job_id,
            claim_token=claimed.claim_token,
            vendor_task_id="cgt-1",
            now=_now(),
        )
    for value in ("cgt-other", None):
        with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
            session.execute(
                text("UPDATE creative_jobs SET vendor_task_id = :v WHERE id = :id"),
                {"v": value, "id": job_id},
            )


# --- the worker's reach (security review §6) ----------------------------------------------------


def _attempt(dsn: str, sql: str, params: dict | None = None) -> str:
    """'ok' or 'denied' — always rolled back."""
    engine = create_engine(dsn)
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                conn.execute(text(sql), params or {})
                return "ok"
            except DBAPIError as exc:
                if isinstance(exc.orig, InsufficientPrivilege):
                    return "denied"
                raise
            finally:
                trans.rollback()
    finally:
        engine.dispose()


def test_the_worker_role_cannot_spend_erase_nor_read_content(
    seeded_ab: tuple[UUID, UUID], pool: str
) -> None:
    tenant_a, _ = seeded_ab
    job_id = _enqueue(tenant_a, pool)
    worker = creative_worker_dsn()
    insert = (
        "INSERT INTO creative_jobs (tenant_id, draft_id, kind, revision, vendor_model, lane) "
        "VALUES (:t, gen_random_uuid(), 'preview', 1, :p, 'immediate')"
    )
    assert _attempt(worker, insert, {"t": tenant_a, "p": pool}) == "denied"
    assert _attempt(worker, "DELETE FROM creative_jobs WHERE id = :id", {"id": job_id}) == "denied"
    assert (
        _attempt(
            worker, "UPDATE creative_jobs SET vendor_task_id = 'x' WHERE id = :id", {"id": job_id}
        )
        == "denied"
    )
    assert _attempt(worker, "SELECT draft_id FROM creative_jobs") == "denied"
    assert _attempt(worker, "SELECT pipeline_version FROM creative_jobs") == "denied"
    assert _attempt(worker, "SELECT id FROM content_drafts") == "denied"
    assert _attempt(worker, "SELECT id FROM tenants") == "denied"
    assert _attempt(worker, "INSERT INTO vendor_slots (vendor_model, slot_no) VALUES ('x', 1)") == (
        "denied"
    )
    # it does see the queue of every business (the one cross-tenant permission)
    with creative_worker_session() as session:
        seen = session.execute(
            text("SELECT tenant_id FROM creative_jobs WHERE id = :id"), {"id": job_id}
        ).scalar_one()
    assert seen == tenant_a


def test_only_the_worker_touches_vendor_slots() -> None:
    for dsn in (app_dsn(), admin_dsn()):
        assert _attempt(dsn, "SELECT count(*) FROM vendor_slots") == "denied"
        assert _attempt(dsn, "UPDATE vendor_slots SET lease_until = now()") == "denied"


def test_a_mistaken_grant_still_meets_rls(seeded_ab: tuple[UUID, UUID], owner: Engine) -> None:
    """NOBYPASSRLS: even granted SELECT on content_drafts by mistake, the worker reads 0."""
    tenant_a, _ = seeded_ab
    _draft(tenant_a)
    with owner.begin() as conn:
        conn.execute(text("GRANT SELECT ON content_drafts TO qualify_creative_worker"))
    try:
        engine = create_engine(creative_worker_dsn())
        try:
            with engine.connect() as conn:
                count = conn.execute(text("SELECT count(*) FROM content_drafts")).scalar_one()
        finally:
            engine.dispose()
        assert count == 0
    finally:
        with owner.begin() as conn:
            conn.execute(text("REVOKE SELECT ON content_drafts FROM qualify_creative_worker"))
