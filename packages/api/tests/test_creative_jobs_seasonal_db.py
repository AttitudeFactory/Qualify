"""m-24976893 against Postgres (migration 0146): a `creative_jobs` row keyed by a
seasonal medium instead of a draft — exactly one subject, `attempt` with it, one job per
(medium, attempt), the tenant-bound FK, the draft natural key untouched, and the worker
still blind to the subject columns (ADR 41)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from packages.api.tests.test_creative_jobs_db import _attempt
from packages.api.tests.test_creative_retention_db import TENANT_A, TENANT_B, _provision
from qualify_shared.db.config import creative_worker_dsn
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.whatsapp.seasonal import (
    MemorySourceReads,
    PostgresSeasonalRepository,
    SeasonalMediaService,
)

pytestmark = pytest.mark.db

_INSERT = text(
    "INSERT INTO creative_jobs (tenant_id, draft_id, seasonal_media_id, attempt, kind, "
    "revision, vendor_model, lane) VALUES (:t, :d, :m, :a, :k, 1, 'test:seasonal', "
    "'immediate') RETURNING id"
)


def _video(tenant: UUID) -> UUID:
    brand, user, _ = _provision(tenant, "A" if tenant == TENANT_A else "B")
    sources = MemorySourceReads()
    sources.logos[(tenant, brand)] = f"t/{tenant}/brand/{brand}/logo.png"
    service = SeasonalMediaService(PostgresSeasonalRepository(), sources)
    rows = service.plan_batch(tenant, brand, f"navidad-{uuid4().hex[:6]}", "Navidad", "free", user)
    return next(r.id for r in rows if r.kind == "video")


def _insert(tenant: UUID, **values) -> UUID:
    params = {"t": tenant, "d": None, "m": None, "a": None, "k": "seasonal_video", **values}
    with tenant_session(tenant) as session:
        return session.execute(_INSERT, params).scalar_one()


def test_one_job_per_medium_attempt() -> None:
    media = _video(TENANT_A)
    _insert(TENANT_A, m=media, a=1)
    with pytest.raises(IntegrityError):
        _insert(TENANT_A, m=media, a=1)
    _insert(TENANT_A, m=media, a=2)  # «Pedir otro»: the next attempt is a new job


@pytest.mark.parametrize(
    "values",
    [
        {"m": None, "a": None},  # no subject
        {"a": None},  # a seasonal job without its attempt
        {"a": 4},  # past the library's cap
        {"k": "final"},  # a seasonal subject on a draft kind
        {"d": "draft"},  # both subjects
    ],
)
def test_the_subject_checks_refuse(values: dict) -> None:
    media = _video(TENANT_A)
    params = {"m": media, "a": 1, **values}
    if params.get("d") == "draft":
        params["d"] = uuid4()
    with pytest.raises(IntegrityError):
        _insert(TENANT_A, **params)


def test_a_draft_kind_cannot_be_seasonal_video_without_its_medium() -> None:
    with pytest.raises(IntegrityError):
        _insert(TENANT_A, d=uuid4(), k="seasonal_video")


def test_another_tenants_medium_is_refused_by_the_fk() -> None:
    foreign = _video(TENANT_B)
    with pytest.raises(IntegrityError):
        _insert(TENANT_A, m=foreign, a=1)


def test_the_worker_sees_the_queue_columns_but_never_the_subject() -> None:
    media = _video(TENANT_A)
    job_id = _insert(TENANT_A, m=media, a=1)
    worker = creative_worker_dsn()
    assert _attempt(worker, "SELECT seasonal_media_id FROM creative_jobs") == "denied"
    assert _attempt(worker, "SELECT attempt FROM creative_jobs") == "denied"
    assert (
        _attempt(
            worker, "SELECT id, kind, status FROM creative_jobs WHERE id = :id", {"id": job_id}
        )
        == "ok"
    )
