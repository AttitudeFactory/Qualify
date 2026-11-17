"""EF-15 (m-25026575) against Postgres: today's local builds are the business's own
`creation_charges` rows with `request_kind = 'local_video'` (RLS: another business's are
never seen nor counted), the day starts at the business's midnight (`tenants.timezone`,
empty → UTC), a refunded build still counts, and a refusal leaves no draft, charge or job.

No vendor is called: the real router runs a fake copy adapter, the producer is a fake."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.router import CreativeRouter
from qualify_creative.schemas import ContentBrief, MediaInputs, SourceSegment
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.composition import DbBrandKitReader, DbVoiceProfileReader
from qualify_api.creative.creations import PostgresCreationsLedger
from qualify_api.creative.fsm import GENERATED
from qualify_api.creative.local_cap import LOCAL_DAILY_CAP_ENV, LocalDailyCapReached
from qualify_api.creative.queue_dispatch import SWITCH, QueueDispatcher
from qualify_api.creative.service import ContentService

from . import test_content_service as base
from .test_creative_parts import PartsMedia

pytestmark = pytest.mark.db

#: Bogotá's midnight today, 30 minutes before it, and the business's «now» — in SQL, so
#: the test never depends on the machine's clock or zone.
_LOCAL_MIDNIGHT = "(date_trunc('day', now() AT TIME ZONE :zone) AT TIME ZONE :zone)"


def _business(monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, UUID, UUID]:
    monkeypatch.setattr(base, "DB_TENANT", uuid4())
    return base.seed_db_tenant()  # America/Bogota


@pytest.fixture(autouse=True)
def queue_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SWITCH, "queue")
    monkeypatch.delenv(LOCAL_DAILY_CAP_ENV, raising=False)


def _service() -> ContentService:
    copy = base.FakeCopyAdapter()
    pricing = JsonPricingTable("v1")
    service = ContentService(
        router=CreativeRouter({"anthropic": copy}, pricing, base.StaticKeyResolver()),
        pricing=pricing,
        credentials=base.StaticKeyResolver(),
        brand_service=DbBrandKitReader(),
        voice_service=DbVoiceProfileReader(),
        media=PartsMedia(),  # type: ignore[arg-type]
        creations=PostgresCreationsLedger(),
    )
    service.dispatcher = QueueDispatcher(service.repository, pricing_version=pricing.version)
    return service


def _local_clip(tenant: UUID, brand: UUID) -> ContentBrief:
    stretch = SourceSegment(key=f"uploads/{tenant}/mi-cocina.mp4", start_s=0.0, end_s=4.0)
    return base.make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(duration_seconds=5, clip_reference_mode="local", segments=(stretch,)),
    ).model_copy(update={"brand_id": brand})


def _builds(
    tenant: UUID,
    brand: UUID,
    count: int,
    *,
    at: str = "now()",
    zone: str = "America/Bogota",
    kind: str = "local_video",
    status: str = "charged",
) -> None:
    """`count` earlier builds of `kind`, charged `at` (an SQL expression)."""
    with tenant_session(tenant) as session:
        for _ in range(count):
            session.execute(
                text(f"""
                INSERT INTO creation_charges (tenant_id, brand_id, draft_id, revision,
                    request_kind, weight, monthly_quota, weights_version,
                    pricing_table_version, period_month, status, charged_at,
                    refunded_at, refund_reason)
                VALUES (:t, :b, :d, 1, :kind, 0, 30, 'v3', 'v10',
                        date_trunc('month', now())::date, :status, {at},
                        CASE WHEN :status = 'refunded' THEN now() END,
                        CASE WHEN :status = 'refunded' THEN 'failed' END)
                """),
                {
                    "t": tenant,
                    "b": brand,
                    "d": uuid4(),
                    "kind": kind,
                    "status": status,
                    "zone": zone,
                },
            )


def _count(tenant: UUID, sql: str, **params: object) -> int:
    with tenant_session(tenant) as session:
        return int(session.execute(text(sql), params).scalar() or 0)


def _footprint(tenant: UUID) -> tuple[int, int, int, int]:
    return (
        _count(tenant, "SELECT count(*) FROM content_drafts"),
        _count(tenant, "SELECT count(*) FROM content_briefs"),
        _count(tenant, "SELECT count(*) FROM creation_charges"),
        _count(tenant, "SELECT count(*) FROM creative_jobs"),
    )


def test_the_tenth_goes_on_and_the_eleventh_writes_nothing_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, brand, user = _business(monkeypatch)
    service = _service()
    repo = service.repository
    _builds(tenant, brand, 9)
    _builds(tenant, brand, 3, kind="generated_video")  # Seedance clips: never counted
    assert repo.local_builds_today(tenant_id=tenant) == 9  # type: ignore[attr-defined]

    tenth = service.create_draft(
        tenant_id=tenant, brand_id=brand, brief=_local_clip(tenant, brand), user_id=user
    )
    assert repo.local_builds_today(tenant_id=tenant) == 10  # type: ignore[attr-defined]
    assert (
        _count(
            tenant,
            "SELECT count(*) FROM creation_charges WHERE draft_id=:d AND request_kind="
            "'local_video'",
            d=tenth,
        )
        == 1
    )
    assert _count(tenant, "SELECT count(*) FROM creative_jobs WHERE draft_id=:d", d=tenth) == 1

    before = _footprint(tenant)
    with pytest.raises(LocalDailyCapReached) as refused:
        service.create_draft(
            tenant_id=tenant, brand_id=brand, brief=_local_clip(tenant, brand), user_id=user
        )
    assert refused.value.code == "local_daily_cap_reached"
    assert refused.value.text == (
        "Por hoy ya usaste los 10 videos que puedes crear con tus fotos y videos. "
        "Cada parte y cada versión nueva cuenta como uno. Mañana tienes 10 más."
    )
    assert _footprint(tenant) == before  # no draft, brief, charge nor job


def test_another_version_past_the_cap_writes_nothing_db(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant, brand, user = _business(monkeypatch)
    service = _service()
    draft = service.create_draft(
        tenant_id=tenant, brand_id=brand, brief=_local_clip(tenant, brand), user_id=user
    )
    service.run_generation(tenant_id=tenant, draft_id=draft)
    assert service.repository.get_draft(tenant_id=tenant, draft_id=draft).status == GENERATED
    _builds(tenant, brand, 9)  # 10 today with this piece
    before = _footprint(tenant)
    with pytest.raises(LocalDailyCapReached):
        service.reject(
            tenant_id=tenant, draft_id=draft, reason="otra", user_id=user, regenerate=True
        )
    assert _footprint(tenant) == before
    assert _count(tenant, "SELECT revision FROM content_drafts WHERE id=:d", d=draft) == 1


def test_a_refunded_build_still_counts_db(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant, brand, _ = _business(monkeypatch)
    _builds(tenant, brand, 4, status="refunded")  # failed builds spent the CPU too
    _builds(tenant, brand, 2)
    assert _service().repository.local_builds_today(tenant_id=tenant) == 6  # type: ignore[attr-defined]


def test_one_business_at_the_cap_never_touches_another_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, a_brand, a_user = _business(monkeypatch)
    b, b_brand, b_user = _business(monkeypatch)
    service = _service()
    repo = service.repository
    _builds(a, a_brand, 10)
    _builds(b, b_brand, 2)
    assert repo.local_builds_today(tenant_id=a) == 10  # type: ignore[attr-defined]
    assert repo.local_builds_today(tenant_id=b) == 2  # type: ignore[attr-defined]  # A's unseen
    with pytest.raises(LocalDailyCapReached):
        service.create_draft(
            tenant_id=a, brand_id=a_brand, brief=_local_clip(a, a_brand), user_id=a_user
        )
    made = service.create_draft(
        tenant_id=b, brand_id=b_brand, brief=_local_clip(b, b_brand), user_id=b_user
    )
    assert repo.local_builds_today(tenant_id=b) == 3  # type: ignore[attr-defined]
    assert repo.local_builds_today(tenant_id=a) == 10  # type: ignore[attr-defined]
    # B's rows are B's: A never sees them
    assert _count(a, "SELECT count(*) FROM content_drafts WHERE id=:d", d=made) == 0


def test_yesterday_in_the_business_zone_does_not_count_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A business in Bogotá: builds at 23:30 of ITS yesterday are not today's, even when
    UTC already calls that moment today; from its midnight on they count."""
    tenant, brand, user = _business(monkeypatch)
    service = _service()
    repo = service.repository
    _builds(tenant, brand, 10, at=f"{_LOCAL_MIDNIGHT} - interval '30 minutes'")
    assert repo.local_builds_today(tenant_id=tenant) == 0  # type: ignore[attr-defined]
    service.create_draft(
        tenant_id=tenant, brand_id=brand, brief=_local_clip(tenant, brand), user_id=user
    )
    _builds(tenant, brand, 1, at=_LOCAL_MIDNIGHT)  # its very first moment of today
    assert repo.local_builds_today(tenant_id=tenant) == 2  # type: ignore[attr-defined]


def test_a_business_without_a_zone_counts_from_utc_midnight_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant, brand, _ = _business(monkeypatch)
    with admin_session() as session:
        session.execute(text("UPDATE tenants SET timezone = '' WHERE id = :t"), {"t": tenant})
    repo = _service().repository
    _builds(tenant, brand, 3, at=f"{_LOCAL_MIDNIGHT} - interval '1 minute'", zone="UTC")
    _builds(tenant, brand, 2, at=_LOCAL_MIDNIGHT, zone="UTC")
    assert repo.local_builds_today(tenant_id=tenant) == 2  # type: ignore[attr-defined]


def test_two_asks_for_the_last_place_at_once_make_exactly_one_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two requests at once (two threads, two connections, two transactions) for the
    last place of the day (9 used, cap 10): the count's per-business transaction lock
    serializes them — the second counts the first's committed row — so exactly one is
    made and the other is refused, whatever order they reach Postgres in."""
    import threading

    tenant, brand, user = _business(monkeypatch)
    service = _service()
    _builds(tenant, brand, 9)
    before = _count(tenant, "SELECT count(*) FROM content_drafts")
    barrier = threading.Barrier(2)
    results: list[object] = [None, None]

    def ask(slot: int) -> None:
        barrier.wait()
        try:
            results[slot] = service.create_draft(
                tenant_id=tenant, brand_id=brand, brief=_local_clip(tenant, brand), user_id=user
            )
        except Exception as exc:  # noqa: BLE001 — reported by the assertions below
            results[slot] = exc

    threads = [threading.Thread(target=ask, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    made = [r for r in results if isinstance(r, UUID)]
    refused = [r for r in results if isinstance(r, LocalDailyCapReached)]
    assert len(made) == 1 and len(refused) == 1, results
    assert refused[0].used == 10
    assert _count(tenant, "SELECT count(*) FROM content_drafts") == before + 1
    assert service.repository.local_builds_today(tenant_id=tenant) == 10  # type: ignore[attr-defined]
