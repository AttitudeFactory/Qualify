"""VE-08 (m-24921065) against Postgres: the parts of a video by parts are created and
charged in ONE transaction (`tenant_unit_of_work`), every part's vista previa in
`creation_charges` and its `preview` job in `creative_jobs`; «Crear otra versión» keeps
the earlier version's brief (`piece_versions.brief_id`); a business never touches
another's parts (RLS); the parts never show loose in a listing; the parent's new texts
are capped per day; and a part tells its parent's `join` run to join again.

No vendor is called: the real router runs a fake copy adapter, the producer is a fake."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_creative.creations import CreationPrice
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.router import CreativeRouter
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import job_queue as q
from qualify_api.creative.composition import DbBrandKitReader, DbVoiceProfileReader
from qualify_api.creative.creations import (
    CreationsBalance,
    NotEnoughCreations,
    PostgresCreationsLedger,
)
from qualify_api.creative.fsm import GENERATED
from qualify_api.creative.parts import (
    PARENT_TEXT_DAILY_CAP,
    ParentTextCapReached,
    PartChanges,
    PartsService,
)
from qualify_api.creative.pieces import DbPieceFiles
from qualify_api.creative.queue_dispatch import QueueDispatcher
from qualify_api.creative.read import approved_creative, list_approved
from qualify_api.creative.service import ContentService, UnknownDraft
from qualify_api.home.summary import read_home_counts
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.post_reader import UnpublishableReason

from . import test_content_service as base
from .test_creative_parts import FOUR_PARTS, PartsMedia, parent_brief

pytestmark = pytest.mark.db


def _business(monkeypatch: pytest.MonkeyPatch) -> tuple[UUID, UUID, UUID]:
    monkeypatch.setattr(base, "DB_TENANT", uuid4())
    return base.seed_db_tenant()


def _service() -> tuple[ContentService, PartsService, base.FakeCopyAdapter]:
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
    return service, PartsService(service, require_queue=lambda: True), copy


def _parent(service: ContentService, tenant: UUID, brand: UUID, user: UUID) -> UUID:
    brief = parent_brief(*FOUR_PARTS).model_copy(update={"brand_id": brand})
    parent = service.create_draft(tenant_id=tenant, brand_id=brand, brief=brief, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=parent)
    assert service.repository.get_draft(tenant_id=tenant, draft_id=parent).status == GENERATED
    return parent


def _scalar(tenant: UUID, sql: str, **params: object) -> object:
    with tenant_session(tenant) as session:
        return session.execute(text(sql), params).scalar()


def _use_previews(tenant: UUID, brand: UUID, previews: int) -> None:
    PostgresCreationsLedger().charge(
        tenant_id=tenant,
        brand_id=brand,
        draft_id=uuid4(),
        revision=1,
        price=CreationPrice("generated_video", 0, videos=previews),
    )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    tenant, brand, user = _business(monkeypatch)
    service, parts, copy = _service()
    parent = _parent(service, tenant, brand, user)
    return service, parts, copy, tenant, brand, user, parent


def test_criterion_1_three_free_previews_and_four_parts_make_nothing_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, brand, user, parent = world
    _use_previews(tenant, brand, 17)  # 3 of the month's 20 left
    with pytest.raises(NotEnoughCreations):
        parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    assert (
        _scalar(tenant, "SELECT count(*) FROM content_drafts WHERE parent_draft_id=:p", p=parent)
        == 0
    )
    assert (
        _scalar(
            tenant,
            "SELECT count(*) FROM creation_charges WHERE brand_id=:b AND previews > 0",
            b=brand,
        )
        == 1  # only the 17 used before
    )


def test_a_shortfall_under_the_lock_rolls_every_part_back_db(world, monkeypatch) -> None:  # noqa: ANN001
    """The ledger's own check (under the brand's lock) refusing after the drafts were
    inserted: the unit of work rolls the drafts, briefs and outbox back with it."""
    service, parts, _, tenant, brand, user, parent = world
    ledger = service.creations
    assert ledger is not None
    # the early check (outside the lock) sees a month that can pay
    monkeypatch.setattr(
        type(ledger),
        "balance",
        lambda self, **kw: CreationsBalance(quota=0, used=0, weights_version="x"),
    )
    _use_previews(tenant, brand, 17)
    with pytest.raises(NotEnoughCreations):
        parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    assert (
        _scalar(tenant, "SELECT count(*) FROM content_drafts WHERE parent_draft_id=:p", p=parent)
        == 0
    )
    assert (
        _scalar(
            tenant,
            "SELECT count(*) FROM creative_pipeline_runs r JOIN content_drafts d "
            "ON d.id=r.draft_id WHERE d.parent_draft_id=:p",
            p=parent,
        )
        == 0
    )


def test_an_enqueue_failure_rolls_back_parts_and_charges_db(world, monkeypatch) -> None:  # noqa: ANN001
    service, parts, _, tenant, brand, user, parent = world
    monkeypatch.setattr(q, "enqueue_job", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db")))
    with pytest.raises(RuntimeError):
        parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    assert (
        _scalar(tenant, "SELECT count(*) FROM content_drafts WHERE parent_draft_id=:p", p=parent)
        == 0
    )
    assert (
        _scalar(
            tenant,
            "SELECT count(*) FROM creation_charges WHERE brand_id=:b AND previews>0",
            b=brand,
        )
        == 0
    )


def test_criterion_2_four_parts_four_previews_four_preview_jobs_no_claude_db(world) -> None:  # noqa: ANN001
    service, parts, copy, tenant, brand, user, parent = world
    calls = copy.calls
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    assert len(ids) == 4
    with tenant_session(tenant) as session:
        drafts = session.execute(
            text(
                "SELECT id, part_index, status FROM content_drafts "
                "WHERE parent_draft_id=:p ORDER BY part_index"
            ),
            {"p": parent},
        ).all()
        charges = session.execute(
            text(
                "SELECT draft_id, revision, previews, weight, video_seconds "
                "FROM creation_charges WHERE draft_id = ANY(:ids)"
            ),
            {"ids": ids},
        ).all()
        jobs = session.execute(
            text("SELECT draft_id, kind FROM creative_jobs WHERE draft_id = ANY(:ids)"),
            {"ids": ids},
        ).all()
    assert [(d.id, d.part_index) for d in drafts] == list(zip(ids, [1, 2, 3, 4], strict=True))
    assert sorted((c.draft_id, c.revision, c.previews, c.weight) for c in charges) == sorted(
        (child, 1, 1, 0) for child in ids
    )
    assert all(c.video_seconds == 0 for c in charges)  # seconds wait for approval (VE-10b)
    assert sorted(jobs) == sorted((child, "preview") for child in ids)
    # idempotent: asked again, the same parts, nothing charged or queued twice
    assert parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user) == ids
    assert (
        _scalar(tenant, "SELECT count(*) FROM creation_charges WHERE draft_id=ANY(:i)", i=ids) == 4
    )
    assert _scalar(tenant, "SELECT count(*) FROM creative_jobs WHERE draft_id=ANY(:i)", i=ids) == 4

    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    assert copy.calls == calls  # 0 calls to Claude for the parts
    assert (
        _scalar(
            tenant,
            "SELECT count(*) FROM copy_variants v JOIN content_drafts d ON d.id=v.draft_id "
            "WHERE d.parent_draft_id=:p",
            p=parent,
        )
        == 4
    )


def test_criterion_3_another_version_of_part_2_db(world) -> None:  # noqa: ANN001
    service, parts, copy, tenant, brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    first_brief = _scalar(tenant, "SELECT brief_id FROM content_drafts WHERE id=:d", d=ids[1])
    previews = _scalar(
        tenant, "SELECT sum(previews) FROM creation_charges WHERE brand_id=:b", b=brand
    )

    parts.regenerate_part(
        tenant_id=tenant,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(description="Papas recién fritas."),
        user_id=user,
    )
    service.run_generation(tenant_id=tenant, draft_id=ids[1])

    assert (
        _scalar(tenant, "SELECT sum(previews) FROM creation_charges WHERE brand_id=:b", b=brand)
        == previews + 1
    )
    assert (
        _scalar(
            tenant,
            "SELECT previews FROM creation_charges WHERE draft_id=:d AND revision=2",
            d=ids[1],
        )
        == 1
    )
    for sibling in (ids[0], ids[2], ids[3]):
        assert _scalar(tenant, "SELECT revision FROM content_drafts WHERE id=:d", d=sibling) == 1
    with tenant_session(tenant) as session:
        versions = session.execute(
            text("""
            SELECT v.revision, v.brief_id, b.media->'part'->>'description' AS description
            FROM piece_versions v JOIN content_briefs b ON b.id = v.brief_id
            WHERE v.draft_id = :d ORDER BY v.revision
            """),
            {"d": ids[1]},
        ).all()
    assert [(v.revision, v.description) for v in versions] == [
        (1, "Manos que sirven papas."),
        (2, "Papas recién fritas."),
    ]
    assert versions[0].brief_id == first_brief
    summary = parts.parts(tenant_id=tenant, parent_id=parent)
    assert summary[1].label == "Parte 2 de 4"
    assert summary[1].description == "Papas recién fritas."

    # restoring version 1 brings its brief back
    v1 = _scalar(tenant, "SELECT id FROM piece_versions WHERE draft_id=:d AND revision=1", d=ids[1])
    service.restore_version(tenant_id=tenant, draft_id=ids[1], version_id=v1)  # type: ignore[arg-type]
    assert (
        _scalar(tenant, "SELECT brief_id FROM content_drafts WHERE id=:d", d=ids[1]) == first_brief
    )


def test_criterion_4_a_business_never_touches_anothers_parts_db(world, monkeypatch) -> None:  # noqa: ANN001
    _, parts, _, tenant, _, _, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=world[5])
    other, _, other_user = _business(monkeypatch)
    _, other_parts, _ = _service()
    with pytest.raises(UnknownDraft):
        other_parts.create_parts(tenant_id=other, parent_id=parent, user_id=other_user)
    with pytest.raises(UnknownDraft):
        other_parts.parts(tenant_id=other, parent_id=parent)
    with pytest.raises(UnknownDraft):
        other_parts.regenerate_part(
            tenant_id=other,
            parent_id=parent,
            part_index=2,
            changes=PartChanges(description="Ajeno"),
            user_id=other_user,
        )
    assert _scalar(other, "SELECT count(*) FROM content_drafts WHERE id = ANY(:i)", i=ids) == 0
    assert (
        _scalar(other, "SELECT count(*) FROM content_drafts WHERE parent_draft_id=:p", p=parent)
        == 0
    )
    # and the owner's parts are exactly as they were
    assert (
        _scalar(tenant, "SELECT max(revision) FROM content_drafts WHERE id = ANY(:i)", i=ids) == 1
    )


def test_criterion_5_the_parts_never_show_loose_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, brand, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    assert all(
        _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:d", d=c) == GENERATED
        for c in ids
    )
    # «Por aprobar» / the drafts list
    assert [d.id for d in service.list_drafts(tenant_id=tenant, brand_id=brand)] == [parent]
    # the gallery and the Planificador
    reader = DraftPostReader()
    assert [p.post_id for p in reader.list_for_brand(tenant_id=tenant, brand_id=brand)] == [parent]
    assert all(
        p.post_id not in ids for p in reader.list_schedulable(tenant_id=tenant, brand_id=brand)
    )
    assert set(reader.get_many(tenant_id=tenant, post_ids=[parent, *ids])) == {parent}
    refused = reader.get_publishable(tenant_id=tenant, post_id=ids[0])
    assert getattr(refused, "reason", None) is UnpublishableReason.POST_NOT_FOUND
    # «Tu semana» (Inicio): only the parent waits for approval
    assert read_home_counts(tenant).drafts_to_approve == 1
    # the files of the pieces: the parts' videos are not loose pieces
    assert DbPieceFiles().files(tenant_id=tenant, brand_id=brand) == []
    # an approved part is never an artifact on its own (ads, the read model)
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status='approved', approved_at=now() WHERE id=:d"),
            {"d": ids[0]},
        )
    assert approved_creative(tenant_id=tenant, draft_id=ids[0]) is None
    assert all(a.draft_id not in ids for a in list_approved(tenant_id=tenant, brand_id=brand))
    # the retention warning mail: even if every piece were about to expire, only the
    # parent would be warned about — never a part on its own
    from datetime import UTC, datetime, timedelta

    from qualify_api.creative import retention_mail
    from qualify_api.creative.retention import Retention, RetentionState
    from qualify_api.mail.retention import WarningStage

    now = datetime.now(UTC)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            retention_mail,
            "retention_of",
            lambda session, tenant_id, ids, now: {
                i: Retention(RetentionState.WARNING, deadline=now + timedelta(days=5)) for i in ids
            },
        )
        patch.setattr(retention_mail, "warning_stage", lambda verdict, now: WarningStage.WINDOW_15D)
        with tenant_session(tenant) as session:
            groups, live = retention_mail._live_pieces(session, tenant, now, None)
    assert set(live) == {parent}
    assert all(p.draft_id not in ids for pieces in groups.values() for p in pieces)


def test_criterion_7_the_parents_new_texts_are_counted_and_capped_db(world) -> None:  # noqa: ANN001
    service, _, _, tenant, brand, user, parent = world
    repo = service.repository
    assert repo.parent_texts_regenerated_today(tenant_id=tenant) == 0  # type: ignore[attr-defined]
    service.reject(tenant_id=tenant, draft_id=parent, reason="otro", user_id=user, regenerate=True)
    service.run_generation(tenant_id=tenant, draft_id=parent)
    assert repo.parent_texts_regenerated_today(tenant_id=tenant) == 1  # type: ignore[attr-defined]
    with tenant_session(tenant) as session:
        for revision in range(10, 10 + PARENT_TEXT_DAILY_CAP - 1):
            session.execute(
                text("""
                INSERT INTO creation_charges (tenant_id, brand_id, draft_id, revision,
                    request_kind, weight, monthly_quota, weights_version,
                    pricing_table_version, period_month)
                VALUES (:t, :b, :d, :r, 'shot_video', 0, 30, 'v3', 'v7',
                        date_trunc('month', now())::date)
                """),
                {"t": tenant, "b": brand, "d": uuid4(), "r": revision},
            )
    assert repo.parent_texts_regenerated_today(tenant_id=tenant) == PARENT_TEXT_DAILY_CAP  # type: ignore[attr-defined]
    revision = _scalar(tenant, "SELECT revision FROM content_drafts WHERE id=:d", d=parent)
    with pytest.raises(ParentTextCapReached):
        service.reject(
            tenant_id=tenant, draft_id=parent, reason="otro", user_id=user, regenerate=True
        )
    assert _scalar(tenant, "SELECT revision FROM content_drafts WHERE id=:d", d=parent) == revision
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:d", d=parent) == GENERATED


def test_a_part_marks_its_parents_join_run_dirty_db(world) -> None:  # noqa: ANN001
    service, parts, _, tenant, _, user, parent = world
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    join_run = "SELECT dirty_version FROM creative_pipeline_runs WHERE draft_id=:p AND phase='join'"
    assert _scalar(tenant, join_run, p=parent) is None  # nothing settled yet
    service.run_generation(tenant_id=tenant, draft_id=ids[0])
    # VE-10a: the first part to settle OPENS the parent's `join` run ...
    assert _scalar(tenant, join_run, p=parent) == 1
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    # ... and every later one dirties the same row (one run, never a second)
    assert _scalar(tenant, join_run, p=parent) == 2
    assert (
        _scalar(
            tenant,
            "SELECT count(*) FROM creative_pipeline_runs WHERE draft_id=:p AND phase='join'",
            p=parent,
        )
        == 1
    )


def test_parts_already_made_are_found_under_the_parents_lock_db(world, monkeypatch) -> None:  # noqa: ANN001
    """Review fix: the parts are looked for again inside the unit, under the parent's
    row lock — the parts a concurrent ask made first are returned, nothing is doubled."""
    service, parts, _, tenant, brand, user, parent = world
    first = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    repo = service.repository
    real = repo.parts_of
    looks: list[int] = []

    def parts_of(**kwargs):  # noqa: ANN003, ANN202
        looks.append(1)
        return () if len(looks) == 1 else real(**kwargs)  # the early look misses them

    monkeypatch.setattr(repo, "parts_of", parts_of)
    assert parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user) == first
    assert len(looks) == 2
    assert (
        _scalar(tenant, "SELECT count(*) FROM creation_charges WHERE draft_id=ANY(:i)", i=first)
        == 4
    )
    assert (
        _scalar(tenant, "SELECT count(*) FROM creative_jobs WHERE draft_id=ANY(:i)", i=first) == 4
    )


def test_two_concurrent_asks_make_the_parts_once_db(world) -> None:  # noqa: ANN001
    """Two requests at once (two threads, two connections): one makes the parts, the
    other gets the same ids — no `uq_content_drafts_part` error, nothing charged twice."""
    import threading

    service, parts, _, tenant, brand, user, parent = world
    barrier = threading.Barrier(2)
    results: list[object] = [None, None]

    def ask(slot: int) -> None:
        barrier.wait()
        try:
            results[slot] = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
        except Exception as exc:  # noqa: BLE001 — reported by the assertion below
            results[slot] = exc

    threads = [threading.Thread(target=ask, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    assert all(isinstance(r, list) for r in results), results
    assert results[0] == results[1]
    ids = results[0]
    assert (
        _scalar(tenant, "SELECT count(*) FROM content_drafts WHERE parent_draft_id=:p", p=parent)
        == 4
    )
    assert (
        _scalar(tenant, "SELECT count(*) FROM creation_charges WHERE draft_id=ANY(:i)", i=ids) == 4
    )
    assert _scalar(tenant, "SELECT count(*) FROM creative_jobs WHERE draft_id=ANY(:i)", i=ids) == 4
