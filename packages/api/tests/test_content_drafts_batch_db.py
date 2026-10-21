"""`db`-marked tests for the batch read of drafts (ticket 24803289, PR 4): what the
«10 variaciones» gallery polls. `ContentService.get_drafts` must equal `get_draft` per
id, stay inside the tenant (RLS), run a CONSTANT number of SQL statements whatever the
number of drafts (measured on the real engine, not on a fake), and reap a draft
orphaned by a dead process first, as listing does.

The root `conftest.py` migrates `qualify_test` to head before any `db` test runs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import event, select
from sqlalchemy.engine import Engine

from qualify_api.creative.fsm import DRAFTING, FAILED, GENERATED
from qualify_api.creative.models import ContentBrief, ContentDraft, CopyVariant, ImageAsset
from qualify_api.creative.service import ContentService, PostgresContentRepository
from qualify_api.tenancy.models import Brand, Tenant, User

pytestmark = pytest.mark.db

# Distinct from the tenants of the other schema-test modules so suites stay independent.
TENANT_A = UUID("a0000000-0000-4000-8000-0000000007a1")
TENANT_B = UUID("b0000000-0000-4000-8000-0000000007b2")


@pytest.fixture
def seeded() -> tuple[UUID, UUID, UUID]:
    """Two tenants with a brand each and a user in A. Returns (brand_a, brand_b, user_a)."""
    with admin_session() as session:
        brands: dict[UUID, UUID] = {}
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"batch-t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
            brand = session.scalar(select(Brand).where(Brand.tenant_id == tid))
            if brand is None:
                brand = Brand(tenant_id=tid, name=f"batch-brand-{name}")
                session.add(brand)
                session.flush()
            brands[tid] = brand.id
        user = User(tenant_id=TENANT_A, email=f"batch-{uuid4()}@a.co", display_name="U")
        session.add(user)
        session.flush()
        user_id = user.id
    return brands[TENANT_A], brands[TENANT_B], user_id


def _draft(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    *,
    status: str = GENERATED,
    variants: int = 2,
    assets: int = 2,
    age: timedelta = timedelta(0),
) -> UUID:
    with tenant_session(tenant_id) as session:
        brief = ContentBrief(
            tenant_id=tenant_id,
            brand_id=brand_id,
            objective="sale",
            topic="shawarma mixto",
            platform="instagram",
            format="feed_4_5",
            intent="organic",
            content_type="product",
            image_route="template_only",
            kind="static_flyer",
            created_by=user_id,
        )
        session.add(brief)
        session.flush()
        draft = ContentDraft(
            tenant_id=tenant_id,
            brand_id=brand_id,
            brief_id=brief.id,
            status=status,
            pipeline_version="creative-v2",
            created_at=datetime.now(UTC) - age,
        )
        session.add(draft)
        session.flush()
        for ordinal in range(variants):
            session.add(
                CopyVariant(
                    tenant_id=tenant_id,
                    draft_id=draft.id,
                    ordinal=ordinal,
                    copy={"hook": f"Gancho {ordinal}", "caption": "c", "cta": "Pide ya"},
                    model_id="claude-opus-5",
                )
            )
        for position in range(assets):
            session.add(
                ImageAsset(
                    tenant_id=tenant_id,
                    draft_id=draft.id,
                    media_url=f"generated/{tenant_id}/{draft.id}/slide-{position}.jpg",
                    object_key=f"generated/{tenant_id}/{draft.id}/slide-{position}.jpg",
                    position=position,
                )
            )
        session.flush()
        return draft.id


@contextmanager
def _statements() -> Iterator[list[str]]:
    """Every SQL statement any engine runs inside the block."""
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", record)


def _service() -> ContentService:
    # only the repository is exercised by get_draft / get_drafts
    return ContentService(
        router=None,  # type: ignore[arg-type]
        pricing=None,  # type: ignore[arg-type]
        credentials=None,  # type: ignore[arg-type]
        voice_service=None,  # type: ignore[arg-type]
        brand_service=None,  # type: ignore[arg-type]
        repository=PostgresContentRepository(),
    )


def test_get_drafts_equals_get_draft_for_every_draft(seeded: tuple[UUID, UUID, UUID]) -> None:
    brand_a, _, user_id = seeded
    service = _service()
    ids = [_draft(TENANT_A, brand_a, user_id), _draft(TENANT_A, brand_a, user_id, assets=0)]
    batch = service.get_drafts(tenant_id=TENANT_A, draft_ids=ids)
    for draft_id in ids:
        assert batch[draft_id] == service.get_draft(tenant_id=TENANT_A, draft_id=draft_id)
    with_media = batch[ids[0]]
    assert len(with_media.variants) == 2 and len(with_media.media) == 2
    assert with_media.image is not None and with_media.kind == "static_flyer"
    assert batch[ids[1]].media == () and batch[ids[1]].image is None


def test_get_drafts_never_crosses_tenants(seeded: tuple[UUID, UUID, UUID]) -> None:
    brand_a, brand_b, user_id = seeded
    service = _service()
    mine = _draft(TENANT_A, brand_a, user_id)
    theirs = _draft(TENANT_B, brand_b, None)
    batch = service.get_drafts(tenant_id=TENANT_A, draft_ids=[mine, theirs, uuid4()])
    assert set(batch) == {mine}


def test_the_batch_runs_a_constant_number_of_statements(seeded: tuple[UUID, UUID, UUID]) -> None:
    brand_a, _, user_id = seeded
    repo = PostgresContentRepository()
    one = [_draft(TENANT_A, brand_a, user_id)]
    ten = [_draft(TENANT_A, brand_a, user_id) for _ in range(10)]
    with _statements() as for_one:
        repo.details_for(tenant_id=TENANT_A, draft_ids=one)
    with _statements() as for_ten:
        bundles = repo.details_for(tenant_id=TENANT_A, draft_ids=ten)
    assert len(bundles) == 10
    # the same statements for 1 draft as for 10 — and few of them (tenant setup + 3 reads)
    assert len(for_ten) == len(for_one) <= 6, for_ten
    # what it replaces: five statements per draft, plus tenant setup each time
    with _statements() as one_by_one:
        for draft_id in ten:
            _service().get_draft(tenant_id=TENANT_A, draft_id=draft_id)
    assert len(one_by_one) > 5 * len(ten)


def test_get_drafts_reaps_a_draft_left_by_a_dead_process(seeded: tuple[UUID, UUID, UUID]) -> None:
    brand_a, _, user_id = seeded
    stale = _draft(
        TENANT_A, brand_a, user_id, status=DRAFTING, variants=0, assets=0, age=timedelta(days=1)
    )
    batch = _service().get_drafts(tenant_id=TENANT_A, draft_ids=[stale])
    assert batch[stale].status == FAILED and batch[stale].failure_reason == "timeout"
