"""`db`-marked: the Alta prefill queue (`alta_prefill_jobs`, migration 0092; PB-4,
m-24852198) against the real Postgres — idempotency key, claim/settle compare-and-set,
tenant isolation, and the proposal surviving the signup that adopts the reserved draft."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from qualify_api.auth import FakeAuthProvider, create_invite, register_business, service
from qualify_api.creative.brand_kit_store import PREFILL_DOCUMENT, PREFILL_KEY, BrandKitStore
from qualify_api.creative.brand_prefill import (
    DEFAULT_CAPS,
    CallCaps,
    PrefillOutcome,
    PrefillResult,
    PrefillUsage,
)
from qualify_api.meegle.prefill import (
    COMMENT_OK,
    ENABLED_ENV,
    MAX_USD_ENV,
    PIPELINE_VERSION,
    AltaPrefillRunner,
    AltaPrefillScheduler,
    AltaPrefillSettings,
)
from qualify_api.meegle.prefill_jobs import STALE_AFTER, NewPrefillJob, PostgresPrefillJobs

pytestmark = pytest.mark.db


def _now() -> datetime:
    """Just after the database's own `now()` (the column default of `next_attempt_at`)."""
    return datetime.now(UTC) + timedelta(seconds=2)


@pytest.fixture(autouse=True)
def _no_meegle_write_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "notify_meegle_registered", lambda item, tenant: None)


def _item() -> int:
    return uuid4().int % 10**12


def _email() -> str:
    return f"hlrd1993+pb4-{uuid4().hex[:8]}@gmail.com"


def _new(tenant_id: UUID, brand_id: UUID, item: int, handle: str = "bianki.ve") -> NewPrefillJob:
    return NewPrefillJob(
        tenant_id=tenant_id,
        brand_id=brand_id,
        meegle_work_item_id=item,
        network="instagram",
        handle=handle,
        max_usd=Decimal("0.5"),
        pipeline_version=PIPELINE_VERSION,
    )


def _brand(tenant_id: UUID) -> UUID:
    with tenant_session(tenant_id) as session:
        return session.execute(
            text("SELECT id FROM brands WHERE tenant_id = :t LIMIT 1"), {"t": tenant_id}
        ).scalar_one()


def _rows(tenant_id: UUID, item: int) -> list[Any]:
    with tenant_session(tenant_id) as session:
        return session.execute(
            text(
                "SELECT status, attempts, comment_attempts, outcome, spent_usd, runs, "
                "comment_posted_at, finished_at FROM alta_prefill_jobs "
                "WHERE meegle_work_item_id = :i"
            ),
            {"i": item},
        ).all()


def test_the_key_is_item_network_and_username(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    jobs, item, brand = PostgresPrefillJobs(), _item(), _brand(tenant_a)
    assert jobs.enqueue(_new(tenant_a, brand, item)) is True
    assert jobs.enqueue(_new(tenant_a, brand, item)) is False
    assert jobs.enqueue(_new(tenant_a, brand, item, "bianki.oficial")) is True
    assert len(_rows(tenant_a, item)) == 2


def test_jobs_are_invisible_to_other_tenants(
    seeded_ab: tuple[UUID, UUID], app_engine: Engine
) -> None:
    tenant_a, tenant_b = seeded_ab
    NOW = _now()  # noqa: N806
    jobs, item = PostgresPrefillJobs(), _item()
    jobs.enqueue(_new(tenant_a, _brand(tenant_a), item))
    assert _rows(tenant_b, item) == []
    with app_engine.connect() as conn:  # no app.tenant_id: fail closed
        assert (
            conn.execute(
                text("SELECT count(*) FROM alta_prefill_jobs WHERE meegle_work_item_id = :i"),
                {"i": item},
            ).scalar_one()
            == 0
        )
    claimed_by_b = jobs.claim(tenant_b, now=NOW, worker_id="w", limit=50)
    assert all(j.meegle_work_item_id != item for j in claimed_by_b)
    assert tenant_a in jobs.due_tenants(now=NOW)
    with pytest.raises(DBAPIError), tenant_session(tenant_b) as session:
        session.execute(  # WITH CHECK: B cannot write a row for A
            text(
                "INSERT INTO alta_prefill_jobs (tenant_id, brand_id, meegle_work_item_id, "
                "network, handle, max_usd, pipeline_version) "
                "VALUES (:t, :b, :i, 'instagram', 'x', 1, 'v')"
            ),
            {"t": tenant_a, "b": _brand(tenant_a), "i": _item()},
        )


def test_claim_retry_finish_and_comment_compare_and_set(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    NOW = _now()  # noqa: N806
    jobs, item = PostgresPrefillJobs(), _item()
    jobs.enqueue(_new(tenant_a, _brand(tenant_a), item))
    (job,) = [
        j
        for j in jobs.claim(tenant_a, now=NOW, worker_id="w1", limit=50)
        if j.meegle_work_item_id == item
    ]
    assert job.attempts == 1 and job.needs_prefill
    assert (
        jobs.retry(job, worker_id="other", now=NOW, next_at=NOW, spent_usd=Decimal(0), run={})
        is False
    )  # not its lock
    assert jobs.retry(
        job,
        worker_id="w1",
        now=NOW,
        next_at=NOW + timedelta(minutes=5),
        spent_usd=Decimal("0.01"),
        run={"attempt": 1, "outcome": "read_failed"},
    )
    later = NOW + timedelta(minutes=6)
    (job,) = [
        j for j in jobs.claim(tenant_a, now=later, worker_id="w1", limit=50) if j.id == job.id
    ]
    assert job.attempts == 2 and job.spent_usd == Decimal("0.01")
    assert jobs.finish_prefill(
        job,
        worker_id="w1",
        now=later,
        outcome="ok",
        written=True,
        spent_usd=Decimal("0.05"),
        run={"attempt": 2, "outcome": "ok"},
        comment=True,
    )
    (job,) = [
        j
        for j in jobs.claim(tenant_a, now=later + timedelta(seconds=1), worker_id="w1", limit=50)
        if j.id == job.id
    ]
    assert job.comment_attempts == 1 and job.attempts == 2 and not job.needs_prefill
    assert jobs.comment_posted(job, worker_id="w1", now=later)
    ((status, attempts, comments, outcome, spent, runs, posted, finished),) = _rows(tenant_a, item)
    assert (status, attempts, comments, outcome) == ("done", 2, 1, "ok")
    assert spent == Decimal("0.05") and [r["outcome"] for r in runs] == ["read_failed", "ok"]
    assert posted is not None and finished is not None


def test_the_proposal_survives_the_signup_that_adopts_the_draft() -> None:
    """Datos completed → reserved draft + job → the runner writes the proposal (here a fake
    `prefill_brand_kit` writing through the real store) → the signup with the Alta's
    invite adopts the draft and the proposal is in the account."""
    item, email = _item(), _email()
    settings = AltaPrefillSettings.from_env({ENABLED_ENV: "1", MAX_USD_ENV: "1"})
    comments: list[tuple[int, str]] = []
    jobs = PostgresPrefillJobs()
    scheduler = AltaPrefillScheduler(
        jobs, lambda i, t: comments.append((i, t)), settings=lambda: settings
    )
    assert scheduler.schedule(item, email=email, handle="bianki.ve") == "enqueued"
    assert scheduler.schedule(item, email=email, handle="bianki.ve") == "duplicate"

    calls: list[dict[str, Any]] = []

    def fake_prefill(
        tenant_id: UUID,
        brand_id: UUID,
        network: str,
        handle: str,
        *,
        source: dict[str, Any] | None = None,
        caps: CallCaps = DEFAULT_CAPS,
        propose: bool = True,
        budget_usd: Any = None,
    ) -> PrefillResult:
        calls.append({"tenant_id": tenant_id, "source": source})
        proposal = {"connect": {"username": handle, "sector": "comida"}, "palette": None}
        BrandKitStore().set_document_key(
            tenant_id=tenant_id,
            brand_id=brand_id,
            document=PREFILL_DOCUMENT,
            key=PREFILL_KEY,
            value={
                "status": "ok",
                "state": "proposed",
                "proposal": proposal,
                "provenance": {"source": source},
            },
        )
        return PrefillResult(
            PrefillOutcome.OK,
            network,
            handle,
            proposal=proposal,
            written=True,
            usage=PrefillUsage(scrapecreators_credits=2, claude_calls=2, claude_cost_usd=0.02),
        )

    runner = AltaPrefillRunner(
        jobs,
        lambda i, t: comments.append((i, t)),
        worker_id="w1",
        settings=lambda: settings,
        prefill=fake_prefill,
    )
    runner.run_once(limit=50)  # drains every due job — other tests' too
    assert [c for c in comments if c[0] == item] == [(item, COMMENT_OK)]
    (call,) = [c for c in calls if c["source"]["meegle_work_item_id"] == item]
    draft_tenant = call["tenant_id"]
    assert call["source"] == {"kind": "alta", "meegle_work_item_id": item}

    invite = create_invite(email, meegle_work_item_id=item)
    registered = register_business(
        FakeAuthProvider(),
        business_name="Bianki",
        email=email,
        password="correct-horse-9",
        country="CO",
        timezone="America/Bogota",
        currency="COP",
        invite_id=invite.id,
    )
    assert registered.tenant_id == draft_tenant
    details = BrandKitStore().load_details(
        tenant_id=registered.tenant_id, brand_id=_brand(registered.tenant_id)
    )
    prefill = details.connect[PREFILL_KEY]
    assert prefill["state"] == "proposed"
    assert prefill["proposal"]["connect"]["username"] == "bianki.ve"
    assert prefill["provenance"]["source"]["meegle_work_item_id"] == item
    ((status, *_rest),) = _rows(draft_tenant, item)
    assert status == "done"


def test_a_stale_running_job_comes_back_flagged_reclaimed(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    jobs, item = PostgresPrefillJobs(), _item()
    jobs.enqueue(_new(tenant_a, _brand(tenant_a), item))
    now = _now()
    first = [j for j in jobs.claim(tenant_a, now=now, worker_id="w1", limit=50) if j.id]
    (job,) = [j for j in first if j.meegle_work_item_id == item]
    assert job.reclaimed is False
    later = now + STALE_AFTER + timedelta(minutes=1)
    (again,) = [
        j
        for j in jobs.claim(tenant_a, now=later, worker_id="w2", limit=50)
        if j.meegle_work_item_id == item
    ]
    assert again.reclaimed is True and again.attempts == 2
    # the first worker lost its lock: its late settlement writes nothing
    assert not jobs.comment_posted(job, worker_id="w1", now=later)


def test_an_alta_without_an_account_is_one_comment_job_per_item(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    tenant_a, _ = seeded_ab
    jobs, item, brand = PostgresPrefillJobs(), _item(), _brand(tenant_a)
    no_handle = replace(_new(tenant_a, brand, item, ""), outcome="no_handle")
    assert jobs.enqueue(no_handle) is True
    assert jobs.enqueue(no_handle) is False
    ((status, attempts, comments, outcome, *_rest),) = _rows(tenant_a, item)
    assert (status, attempts, comments, outcome) == ("commenting", 0, 0, "no_handle")
