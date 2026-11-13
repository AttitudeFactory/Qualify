"""Product sticker characters against the compose Postgres (m-25017372, migration 0155): the
row and its ONE `creative_jobs` job in one transaction, the pre-POST stamp taken once, the
key CHECKs agree with the gate's key builder, RLS hides another business's rows, and a
character's USD cost is booked once."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from packages.api.tests.test_creative_retention_db import _provision
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.keys import seasonal_media_key
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from qualify_api.creative import job_queue as q
from qualify_api.creative.product_sticker_ai import PostgresCharacterUsageLedger
from qualify_api.creative.product_stickers import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_READY,
    PostgresCharacterRepository,
    StickerCharacter,
)

pytestmark = pytest.mark.db

TENANT = UUID("c0000000-0000-4000-8000-00000025a1d1")
OTHER = UUID("c0000000-0000-4000-8000-00000025a1d2")
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)


def _character(tenant: UUID = TENANT) -> tuple[PostgresCharacterRepository, StickerCharacter]:
    brand, user, _ = _provision(tenant, "stickers")
    repo = PostgresCharacterRepository()
    stored = repo.insert_with_job(
        StickerCharacter(
            id=uuid4(),
            tenant_id=tenant,
            brand_id=brand,
            product_id=None,
            product_name="Shawarma mixto",
            source_media_id=uuid4(),
            quoted_usd=Decimal("0.045"),
            created_by=user,
        )
    )
    return repo, stored


def _jobs(character_id: UUID) -> list[q.JobRow]:
    with tenant_session(TENANT) as session:
        ids = session.execute(
            text("SELECT id FROM creative_jobs WHERE sticker_character_id = :c"),
            {"c": character_id},
        ).scalars()
        return [q.load_job(session, i) for i in ids]  # type: ignore[misc]


def test_one_character_one_job_on_the_seedream_pool() -> None:
    repo, c = _character()
    assert c.status == STATUS_PENDING and c.prompt_version == "kawaii-v3"
    (job,) = _jobs(c.id)
    assert job.kind == q.KIND_STICKER_CHARACTER and job.draft_id is None
    assert job.sticker_character_id == c.id and job.seasonal_media_id is None
    assert job.vendor_model == q.SEEDREAM_PRO_POOL and job.pricing_version == "v9"
    with tenant_session(TENANT) as session:
        again = q.enqueue_character_job(
            session,
            tenant_id=TENANT,
            character_id=c.id,
            pricing_version="v9",
            pipeline_version="kawaii-character-1",
        )
    assert not again.created and again.job_id == job.job_id


def test_the_stamp_is_taken_once_and_cleared_on_busy() -> None:
    repo, c = _character()
    assert repo.start_request(tenant_id=TENANT, character_id=c.id, at=NOW)
    assert not repo.start_request(tenant_id=TENANT, character_id=c.id, at=NOW)
    repo.clear_request(tenant_id=TENANT, character_id=c.id)
    assert repo.start_request(tenant_id=TENANT, character_id=c.id, at=NOW)


def test_the_key_checks_match_the_gate_key_builder() -> None:
    repo, c = _character()
    cut = seasonal_media_key(TENANT, c.brand_id, "personajes", c.id, "webp", 1)
    raw = seasonal_media_key(TENANT, c.brand_id, "personajes", c.id, "webp", 2)
    ready = repo.save(
        replace(c, status=STATUS_READY, object_key=cut, raw_object_key=raw, width=10, height=10),
        expected_status=STATUS_PENDING,
    )
    assert ready.object_key == cut
    _repo, other = _character()
    with pytest.raises(IntegrityError):
        repo.save(
            replace(other, status=STATUS_READY, object_key=raw, raw_object_key=raw),
            expected_status=STATUS_PENDING,
        )


def test_another_business_never_sees_a_character() -> None:
    repo, c = _character()
    _provision(OTHER, "other")
    assert repo.get(tenant_id=OTHER, character_id=c.id) is None
    assert repo.get(tenant_id=TENANT, character_id=c.id) is not None


def test_the_usd_cost_is_booked_once_per_character() -> None:
    repo, c = _character()
    ledger = PostgresCharacterUsageLedger()
    args = dict(
        tenant_id=TENANT,
        brand_id=c.brand_id,
        character_id=c.id,
        model_id="dola-seedream-5-0-pro-260628",
        pieces=1,
        cost_usd=Decimal("0.045"),
        pricing_version="v9",
        occurred_at=NOW,
    )
    assert ledger.record(**args)  # type: ignore[arg-type]
    assert not ledger.record(**args)  # type: ignore[arg-type]
    failed = repo.save(replace(c, status=STATUS_FAILED, fail_reason="x"), expected_status="pending")
    assert failed.status == STATUS_FAILED
