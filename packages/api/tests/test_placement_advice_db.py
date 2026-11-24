"""`db`-marked tests of EF-20 phase 2 (m-25026599) against the compose Postgres: the
reservations in `creative_usage_events` (per-video cap, the fleet cap under the advisory
lock across connections, the settle), the brand's dollar cap untouched, the advice kept in
the `upload_preview` job and RLS keeping it to its own business.

Every test makes its own tenant, brand and source key (`uuid4()`): no deletes, no shared
state. No model is called."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, update

from qualify_api.catalog.business_media_models import (
    JOB_UPLOAD_PREVIEW,
    STATUS_DONE,
    GalleryJob,
)
from qualify_api.creative import models as orm
from qualify_api.creative import placement_advice as adv
from qualify_api.creative import placement_ai as pa
from qualify_api.creative.upload_previews import preview_job_key, preview_key, request_preview
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db


def _business() -> tuple[UUID, UUID]:
    tenant = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name=f"m25026599-{tenant.hex[:6]}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        brand = Brand(tenant_id=tenant, name=f"m25026599-{tenant.hex[:6]}")
        session.add(brand)
        session.flush()
        return tenant, brand.id


def _source(tenant: UUID) -> str:
    return f"t/{tenant}/uploads/{uuid4().hex}_hamburguesa.mp4"


def _ledger() -> adv.PostgresPlacementLedger:
    return adv.PostgresPlacementLedger(adv.AdminFleetCounter())


def _reserve(
    tenant: UUID, brand: UUID, source: str, cap: int = 1_000_000, ledger: object = None
) -> UUID:
    return (ledger or _ledger()).reserve(  # type: ignore[attr-defined]
        tenant_id=tenant,
        brand_id=brand,
        source_key=source,
        now=datetime.now(UTC),
        fleet_cap=cap,
    )


def _event(tenant: UUID, event_id: UUID) -> orm.CreativeUsageEvent | None:
    with tenant_session(tenant) as session:
        row = session.get(orm.CreativeUsageEvent, event_id)
        if row is not None:
            session.expunge(row)
        return row


def _advice(source: str) -> adv.PlacementAdvice:
    return adv.PlacementAdvice(
        source_key=source,
        subject_bands=("middle", "bottom"),
        recommended_text_band="top",
        recommended_logo_band="top",
        reason_es="El producto se ve en el centro y abajo. Pon el texto arriba para no taparlo.",
        model=pa.MODEL_ID,
        prompt_version=pa.PLACEMENT_PROMPT_VERSION,
        frames=({"at_s": 1.0, "width": 270, "height": 480, "sha256": "ab" * 8},),
        cost_usd=Decimal("0.000812"),
        made_at=datetime.now(UTC),
    )


def _preview_job(tenant: UUID, brand: UUID, source: str, status: str = STATUS_DONE) -> UUID:
    request_preview(tenant, brand, source)
    with tenant_session(tenant) as session:
        session.execute(
            update(GalleryJob)
            .where(GalleryJob.idempotency_key == preview_job_key(source))
            .values(status=status, result={"preview_key": preview_key(tenant, source)})
        )
        return session.scalar(
            select(GalleryJob.id).where(GalleryJob.idempotency_key == preview_job_key(source))
        )


# 1 --------------------------------------------------------------------------------------


def test_two_reservations_per_video_then_piece_cap() -> None:
    tenant, brand = _business()
    source = _source(tenant)
    first, second = _reserve(tenant, brand, source), _reserve(tenant, brand, source)
    assert first == adv.usage_event_id(tenant, source, 1)
    assert second == adv.usage_event_id(tenant, source, 2)
    with pytest.raises(pa.PlacementRefused) as refused:
        _reserve(tenant, brand, source)
    assert refused.value.reason == "piece_cap"
    row = _event(tenant, first)
    assert row is not None
    assert row.unit == adv.PLACEMENT_USAGE_UNIT and row.provider == adv.PROVIDER
    assert row.model_id == pa.MODEL_ID and row.draft_id is None and row.brand_id == brand
    assert Decimal(row.cost_usd) == pa.MAX_REQUEST_USD and row.paid_by == "platform"
    # another video of the same business has its own two calls
    assert _reserve(tenant, brand, _source(tenant)) is not None


# 2 --------------------------------------------------------------------------------------


def test_concurrent_reservations_respect_the_fleet_cap() -> None:
    tenant, brand = _business()
    other_tenant, other_brand = _business()
    counter = adv.AdminFleetCounter()
    cap = counter.calls_since(datetime.now(UTC) - timedelta(hours=24)) + 1
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def run(t: UUID, b: UUID) -> None:
        barrier.wait()
        try:
            _reserve(t, b, _source(t), cap=cap)
            result = "ok"
        except pa.PlacementRefused as refused:
            result = refused.reason
        with lock:
            outcomes.append(result)

    threads = [
        threading.Thread(target=run, args=(tenant, brand)),
        threading.Thread(target=run, args=(other_tenant, other_brand)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(outcomes) == ["fleet_cap", "ok"]


# 3 and 4 --------------------------------------------------------------------------------


def test_settle_twice_leaves_what_was_billed_and_the_brand_cap_untouched() -> None:
    tenant, brand = _business()
    with tenant_session(tenant) as session:
        session.add(
            orm.CreativeEngineConfig(
                tenant_id=tenant,
                brand_id=brand,
                monthly_budget_cap_usd=Decimal("10.00"),
                budget_spent_usd=Decimal("1.25"),
            )
        )
    source = _source(tenant)
    ledger = _ledger()
    event_id = _reserve(tenant, brand, source, ledger=ledger)
    for _ in range(2):
        ledger.settle(
            tenant_id=tenant,
            brand_id=brand,
            event_id=event_id,
            cost_usd=Decimal("0.000812"),
            input_tokens=5_200,
            output_tokens=400,
        )
    row = _event(tenant, event_id)
    assert row is not None
    assert Decimal(row.cost_usd) == Decimal("0.000812")
    assert row.input_tokens == 5_200 and row.output_tokens == 400
    with tenant_session(tenant) as session:
        spent = session.scalar(
            select(orm.CreativeEngineConfig.budget_spent_usd).where(
                orm.CreativeEngineConfig.brand_id == brand
            )
        )
    assert Decimal(spent) == Decimal("1.25")


# 5 --------------------------------------------------------------------------------------


def test_keep_writes_only_into_a_done_preview_job_without_advice() -> None:
    tenant, brand = _business()
    store = adv.GalleryJobAdviceStore()
    queued_source = _source(tenant)
    queued = _preview_job(tenant, brand, queued_source, status="queued")
    assert store.keep(tenant, queued, _advice(queued_source)) is False
    assert store.kept(tenant, queued_source) is None

    source = _source(tenant)
    done = _preview_job(tenant, brand, source)
    first = _advice(source)
    assert store.keep(tenant, done, first) is True
    assert store.kept(tenant, source) == first
    # a second advice never overwrites the first
    second = replace(_advice(source), recommended_text_band="bottom")
    assert store.keep(tenant, done, second) is False
    assert store.kept(tenant, source) == first
    with tenant_session(tenant) as session:
        row = session.get(GalleryJob, done)
        assert row is not None and row.kind == JOB_UPLOAD_PREVIEW
        assert row.result["preview_key"] == preview_key(tenant, source)  # the rest kept
        assert row.result[adv.ADVICE_FIELD]["recommended_text_band"] == "top"


# 6 --------------------------------------------------------------------------------------


def test_another_business_never_sees_the_advice() -> None:
    tenant_a, brand_a = _business()
    tenant_b, _brand_b = _business()
    source = _source(tenant_a)
    job = _preview_job(tenant_a, brand_a, source)
    assert adv.GalleryJobAdviceStore().keep(tenant_a, job, _advice(source)) is True
    assert adv.placement_advice_for(tenant_a, [source]).keys() == {source}
    # B passing A's key: refused before any query, and RLS hides the row anyway
    assert adv.placement_advice_for(tenant_b, [source]) == {}
    assert adv.GalleryJobAdviceStore().keep(tenant_b, job, _advice(source)) is False
    with tenant_session(tenant_b) as session:
        assert session.get(GalleryJob, job) is None


# 7 --------------------------------------------------------------------------------------


def test_the_fleet_counter_answers_one_integer() -> None:
    tenant, brand = _business()
    since = datetime.now(UTC) - timedelta(hours=24)
    before = adv.AdminFleetCounter().calls_since(since)
    _reserve(tenant, brand, _source(tenant))
    after = adv.AdminFleetCounter().calls_since(since)
    assert type(before) is int and type(after) is int
    assert after >= before + 1
