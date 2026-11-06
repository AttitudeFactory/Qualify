"""VE-10a (m-24921067) against Postgres: the parent of a video by parts joins its parts'
vistas previas in the creative worker's `join` phase.

- 3 parts ready → ONE joined preview on the parent; another version of a part, made or
  restored, → a join with another fingerprint; two parts finishing together → one join
  (the run's lease, `PipelineStore.acquire`).
- The joined preview is not publishable (`draft_pending`; the Planificador refuses it)
  and `_waiting_drafts` never returns it.
- The parent never waits in `drafting`: `reap_stale_drafts` leaves it alone while its
  parts take an hour.
- An unknown phase fails once, never in a loop; another business reads nothing.

The real `PipelinePreparation`, `PipelineStore`, `DbPartJoins` and RLS; the producer is
a fake (no vendor) and the encoder a recording stand-in (the real PyAV join is covered
offline in `test_creative_part_join.py`)."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import part_join
from qualify_api.creative.dispatch import reap_stale_drafts
from qualify_api.creative.draft_mode import draft_pending
from qualify_api.creative.fsm import GENERATED
from qualify_api.creative.media import MediaOutcome, MediaWrite
from qualify_api.creative.part_join import FINISH_JOIN, JOIN_PREVIEW_STATUS, DbPartJoins
from qualify_api.creative.parts import PartChanges
from qualify_api.creative.pipeline import PipelineStore
from qualify_api.creative.service import ContentService
from qualify_api.creative.worker.pipeline import PipelinePreparation
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.post_reader import UnpublishableReason

from . import test_creative_parts_db as parts_db
from .test_creative_part_join import Joiner, Store
from .test_creative_parts import FOUR_PARTS, parent_brief

pytestmark = pytest.mark.db

THREE_PARTS = FOUR_PARTS[:3]


class JoinMedia:
    """The producer double: a parent makes no media; a part makes its 480p vista previa
    (a `draft` block, its part provenance) in the store; the join is the real one over
    the database, with a recording encoder."""

    def __init__(self, store: Store, joiner: Joiner) -> None:
        self.store, self.joiner = store, joiner
        self.joins = DbPartJoins()

    def produce(self, *, tenant_id: UUID, draft_id: UUID, brief, revision: int = 1, **_: Any):  # noqa: ANN001, ANN201
        if brief.kind.is_parts_parent:
            return MediaOutcome()
        part = brief.media.part
        key = f"t/{tenant_id}/generated/{draft_id}/r{revision}/clip.mp4"
        self.store.files[key] = f"clip {draft_id} r{revision}".encode()
        return MediaOutcome(
            media=(
                MediaWrite(
                    position=0,
                    media_type="video",
                    media_url=key,
                    object_key=key,
                    width=480,
                    height=854,
                    aspect_ratio="9:16",
                    model_id="seedance-2-5",
                    provider="byteplus",
                    content_type="video/mp4",
                    ai_generated=True,
                    params={
                        "part": {
                            "index": part.index,
                            "mode": part.mode,
                            "seconds": part.seconds,
                            "generation_seconds": part.generation_seconds,
                            "window": None,
                        },
                        "draft": {
                            "status": "draft",
                            "created_at": time.time(),
                            "model": "seedance-2-5",
                            "finish": "clip",
                        },
                    },
                ),
            )
        )

    def join_preview(self, tenant_id: UUID, parent_id: UUID) -> MediaWrite | None:
        return part_join.join_preview(
            self.store, self.joins, tenant_id, parent_id, joiner=self.joiner
        )

    def save_join_preview(self, tenant_id: UUID, parent_id: UUID, write: MediaWrite) -> bool:
        return self.joins.save(tenant_id=tenant_id, parent_id=parent_id, write=write)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    tenant, brand, user = parts_db._business(monkeypatch)
    service, parts, _ = parts_db._service()
    store, joiner = Store(), Joiner()
    service._media = JoinMedia(store, joiner)  # type: ignore[assignment]
    brief = parent_brief(*THREE_PARTS).model_copy(update={"brand_id": brand})
    parent = service.create_draft(tenant_id=tenant, brand_id=brand, brief=brief, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=parent)
    assert service.repository.get_draft(tenant_id=tenant, draft_id=parent).status == GENERATED
    ids = parts.create_parts(tenant_id=tenant, parent_id=parent, user_id=user)
    return service, parts, store, joiner, tenant, user, parent, ids


def _scalar(tenant: UUID, sql: str, **params: object) -> Any:
    with tenant_session(tenant) as session:
        return session.execute(text(sql), params).scalar()


def _settle_generations(tenant: UUID) -> None:
    """The parts were made by calling `run_generation` here: their own `generation` runs
    are done, so the worker pass below prepares only what this test is about."""
    with tenant_session(tenant) as session:
        session.execute(
            text(
                "UPDATE creative_pipeline_runs SET prepared_version=dirty_version "
                "WHERE phase='generation'"
            )
        )


def _worker_pass(service: ContentService, tenant: UUID) -> None:
    _settle_generations(tenant)
    PipelinePreparation(service, PipelineStore(), (tenant,))()


def _joins(tenant: UUID, parent: UUID) -> list[Any]:
    with tenant_session(tenant) as session:
        return list(
            session.execute(
                text("""
                SELECT id, object_key, params FROM image_assets
                WHERE draft_id=:p AND params->'draft'->>'finish'='join'
                """),
                {"p": parent},
            ).all()
        )


def _join_run(tenant: UUID, parent: UUID) -> Any:
    with tenant_session(tenant) as session:
        return session.execute(
            text("""
            SELECT dirty_version, prepared_version, lease_token FROM creative_pipeline_runs
            WHERE draft_id=:p AND phase='join'
            """),
            {"p": parent},
        ).one()


def test_three_ready_parts_make_one_joined_preview_db(world) -> None:  # noqa: ANN001
    service, _, store, joiner, tenant, _, parent, ids = world
    for child in ids[:2]:
        service.run_generation(tenant_id=tenant, draft_id=child)
    _worker_pass(service, tenant)
    assert joiner.calls == [] and _joins(tenant, parent) == []  # part 3 not ready
    run = _join_run(tenant, parent)
    assert run.prepared_version == run.dirty_version  # done, not retried in a loop

    service.run_generation(tenant_id=tenant, draft_id=ids[2])
    _worker_pass(service, tenant)
    joins = _joins(tenant, parent)
    assert len(joiner.calls) == 1 and len(joins) == 1
    (row,) = joins
    block = row.params["draft"]
    assert block["finish"] == FINISH_JOIN and block["status"] == JOIN_PREVIEW_STATUS
    assert [UUID(child) for child, _ in block["parts"]] == ids
    assert row.object_key == f"t/{tenant}/generated/{parent}/join-{block['fingerprint']}.mp4"
    assert row.object_key in store.files
    assert row.params["join"]["cost_usd"] == "0"
    # cost 0: the parent has no charge row of its own for the join
    assert _scalar(tenant, "SELECT count(*) FROM creation_charges WHERE draft_id=:p", p=parent) <= 1
    # the parent stays `generated` and shows the joined preview
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:p", p=parent) == GENERATED
    assert _scalar(tenant, "SELECT preview_key FROM content_drafts WHERE id=:p", p=parent) in (
        row.params["thumbnail_key"],
        row.object_key,
    )

    # a second pass with nothing new does nothing
    _worker_pass(service, tenant)
    assert len(joiner.calls) == 1 and len(_joins(tenant, parent)) == 1


def test_the_joined_preview_is_not_publishable_nor_a_final_to_ask_for_db(world) -> None:  # noqa: ANN001
    service, _, _, _, tenant, _, parent, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    _worker_pass(service, tenant)
    (row,) = _joins(tenant, parent)
    assert draft_pending(row.params)
    assert service._waiting_drafts(tenant, parent) == ()
    # even approved (VE-10b's path, forced here), the Planificador refuses the 480p join
    variant = _scalar(tenant, "SELECT id FROM copy_variants WHERE draft_id=:p LIMIT 1", p=parent)
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            UPDATE content_drafts SET status='approved', approved_revision=revision,
                selected_variant_id=:v, approved_at=now(), category='reel'
            WHERE id=:p
            """),
            {"p": parent, "v": variant},
        )
    refused = DraftPostReader().get_publishable(tenant_id=tenant, post_id=parent)
    assert getattr(refused, "reason", None) is UnpublishableReason.MEDIA_DRAFT_PENDING


def test_another_version_of_a_part_made_or_restored_joins_again_db(world) -> None:  # noqa: ANN001
    service, parts, store, joiner, tenant, user, parent, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    _worker_pass(service, tenant)
    (first,) = _joins(tenant, parent)
    first_print = first.params["draft"]["fingerprint"]

    parts.regenerate_part(
        tenant_id=tenant,
        parent_id=parent,
        part_index=2,
        changes=PartChanges(description="Papas recién fritas."),
        user_id=user,
    )
    _worker_pass(service, tenant)  # part 2 is being made again: nothing to join
    assert len(joiner.calls) == 1
    service.run_generation(tenant_id=tenant, draft_id=ids[1])
    _worker_pass(service, tenant)
    (second,) = _joins(tenant, parent)  # the same row, another file
    second_print = second.params["draft"]["fingerprint"]
    assert second_print != first_print and second.object_key != first.object_key
    assert len(joiner.calls) == 2
    assert first.object_key in store.files  # the earlier join stays in the store

    # restoring part 2's version 1 joins those parts again: another fingerprint than the
    # current one — the very first, whose file is already kept and reused, not encoded
    v1 = _scalar(tenant, "SELECT id FROM piece_versions WHERE draft_id=:d AND revision=1", d=ids[1])
    service.restore_version(tenant_id=tenant, draft_id=ids[1], version_id=v1)  # type: ignore[arg-type]
    _worker_pass(service, tenant)
    (third,) = _joins(tenant, parent)
    assert third.params["draft"]["fingerprint"] == first_print != second_print
    assert third.object_key == first.object_key
    assert len(joiner.calls) == 2


def test_two_parts_finishing_together_make_one_join_db(world) -> None:  # noqa: ANN001
    service, _, _, joiner, tenant, _, parent, ids = world
    service.run_generation(tenant_id=tenant, draft_id=ids[0])
    done = [
        threading.Thread(target=service.run_generation, kwargs={"tenant_id": tenant, "draft_id": c})
        for c in ids[1:]
    ]
    for thread in done:
        thread.start()
    for thread in done:
        thread.join()
    assert _join_run(tenant, parent).dirty_version == 3  # one row, bumped by each part
    _settle_generations(tenant)

    started = threading.Event()

    def slow(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        started.set()
        time.sleep(1.0)  # the other worker tries while this one holds the lease
        return joiner(*args, **kwargs)

    service._media.joiner = slow  # type: ignore[attr-defined]
    acquired: list[Any] = []
    store = PipelineStore()
    first = threading.Thread(target=PipelinePreparation(service, store, (tenant,)))
    first.start()
    started.wait(10)
    acquired.append(store.acquire(tenant, parent, 1, "join"))  # a second worker, now
    second = threading.Thread(target=PipelinePreparation(service, PipelineStore(), (tenant,)))
    second.start()
    first.join()
    second.join()
    assert acquired == [None]  # the lease: the second worker never joins concurrently
    assert len(joiner.calls) == 1 and len(_joins(tenant, parent)) == 1
    # whatever was dirtied meanwhile re-checks and finds the same parts: still one join
    PipelinePreparation(service, PipelineStore(), (tenant,))()
    assert len(joiner.calls) == 1 and len(_joins(tenant, parent)) == 1


def test_the_reaper_leaves_the_parent_alone_while_its_parts_take_an_hour_db(world) -> None:  # noqa: ANN001
    service, _, _, _, tenant, _, parent, ids = world
    hour_ago = datetime.now(UTC) - timedelta(hours=1, minutes=5)
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET updated_at=:t WHERE id=:p OR parent_draft_id=:p"),
            {"t": hour_ago, "p": parent},
        )
    reap_stale_drafts(tenant_id=tenant)
    # the parent made its text and is `generated`, never `drafting` waiting for its parts
    assert _scalar(tenant, "SELECT status FROM content_drafts WHERE id=:p", p=parent) == GENERATED
    assert (
        _scalar(tenant, "SELECT failure_reason FROM content_drafts WHERE id=:p", p=parent) is None
    )
    # its parts still wait on their queued jobs, so the reaper leaves them alone too
    statuses = _scalar(
        tenant,
        "SELECT array_agg(DISTINCT status) FROM content_drafts WHERE parent_draft_id=:p",
        p=parent,
    )
    assert statuses == ["drafting"]
    # and once they are made, the join comes as if nothing happened
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    _worker_pass(service, tenant)
    assert len(_joins(tenant, parent)) == 1


def test_an_unknown_phase_fails_once_without_a_loop_db(world, monkeypatch) -> None:  # noqa: ANN001
    service, _, _, joiner, tenant, _, parent, _ = world
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            INSERT INTO creative_pipeline_runs (tenant_id, draft_id, revision, phase,
                pipeline_version)
            SELECT tenant_id, id, revision, 'joinfinal', pipeline_version
            FROM content_drafts WHERE id=:p
            """),
            {"p": parent},
        )
    called: list[str] = []
    monkeypatch.setattr(service, "run_generation", lambda **_: called.append("generation"))
    monkeypatch.setattr(service, "run_queued_final", lambda **_: called.append("final"))
    _worker_pass(service, tenant)
    _worker_pass(service, tenant)
    assert called == [] and joiner.calls == []
    with tenant_session(tenant) as session:
        run = session.execute(
            text("""
            SELECT dirty_version, prepared_version FROM creative_pipeline_runs
            WHERE draft_id=:p AND phase='joinfinal'
            """),
            {"p": parent},
        ).one()
    assert run.prepared_version == run.dirty_version  # marked done once


def test_another_business_reads_no_part_and_joins_nothing_db(world, monkeypatch) -> None:  # noqa: ANN001
    service, _, _, joiner, tenant, _, parent, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    other, _, _ = parts_db._business(monkeypatch)
    assert DbPartJoins().read(tenant_id=other, parent_id=parent) is None
    assert service._media.join_preview(other, parent) is None
    assert joiner.calls == []
    assert DbPartJoins().read(tenant_id=tenant, parent_id=parent) is not None


def test_a_join_lost_with_its_lease_writes_nothing_db(world) -> None:  # noqa: ANN001
    """The save is fenced by the run's lease: a worker that lost it never writes."""
    service, _, _, _, tenant, _, parent, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    write = service._media.join_preview(tenant, parent)
    assert write is not None
    store = PipelineStore()
    run = store.acquire(tenant, parent, 1, "join")
    assert run is not None
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE creative_pipeline_runs SET lease_token=:t WHERE draft_id=:p"),
            {"t": uuid4(), "p": parent},
        )
    from qualify_api.creative.pipeline import preparing
    from qualify_api.creative.queue_dispatch import CheckpointError

    with preparing(run), pytest.raises(CheckpointError):
        service._media.save_join_preview(tenant, parent, write)
    assert _joins(tenant, parent) == []


def test_a_new_text_of_the_parent_gets_its_parts_joined_again_db(world) -> None:  # noqa: ANN001
    """The joined preview lives on the parent's ACTIVE version: another text (a new
    revision) opens the `join` run there, and the same parts' file is reused."""
    service, _, _, joiner, tenant, user, parent, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    _worker_pass(service, tenant)
    (first,) = _joins(tenant, parent)
    service.reject(
        tenant_id=tenant, draft_id=parent, reason="otro texto", user_id=user, regenerate=True
    )
    service.run_generation(tenant_id=tenant, draft_id=parent)
    assert _scalar(tenant, "SELECT revision FROM content_drafts WHERE id=:p", p=parent) == 2
    _worker_pass(service, tenant)
    with tenant_session(tenant) as session:
        rows = session.execute(
            text("""
            SELECT a.object_key, a.version_id = d.active_version_id AS active
            FROM image_assets a JOIN content_drafts d ON d.id = a.draft_id
            WHERE a.draft_id=:p AND a.params->'draft'->>'finish'='join'
            ORDER BY a.created_at
            """),
            {"p": parent},
        ).all()
    assert [r.active for r in rows] == [False, True]  # one per version, the new one shown
    assert rows[1].object_key == first.object_key  # the same parts: the file is reused
    assert len(joiner.calls) == 1


def _slow(world, seconds: float) -> None:  # noqa: ANN001
    service, _, _, joiner, *_ = world

    def slow(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        time.sleep(seconds)
        return joiner(*args, **kwargs)

    service._media.joiner = slow  # type: ignore[attr-defined]


def test_a_join_longer_than_the_lease_is_saved_once_db(world, monkeypatch) -> None:  # noqa: ANN001
    """arm64 under QEMU (2026-11-06): a join that outlasts `LEASE` kept losing it before
    its save (`CheckpointError`). The heartbeat keeps it: one pass, one join."""
    from qualify_api.creative import pipeline

    service, _, _, joiner, tenant, _, parent, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    monkeypatch.setattr(pipeline, "LEASE", timedelta(seconds=2))
    _slow(world, 5)  # 2.5 leases
    _worker_pass(service, tenant)
    assert len(joiner.calls) == 1 and len(_joins(tenant, parent)) == 1
    run = _join_run(tenant, parent)
    assert run.prepared_version == run.dirty_version and run.lease_token is None


def test_a_join_that_lost_its_lease_is_reused_not_made_again_db(world, monkeypatch) -> None:  # noqa: ANN001
    """Without the heartbeat (what failed): the save is refused, nothing is written, and
    the next pass reuses the file already in R2 — no second encode, no duplicate."""
    from contextlib import nullcontext

    from qualify_api.creative import pipeline
    from qualify_api.creative.worker import pipeline as worker_pipeline

    service, _, _, joiner, tenant, _, parent, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    monkeypatch.setattr(pipeline, "LEASE", timedelta(seconds=1))
    monkeypatch.setattr(worker_pipeline, "lease_kept", lambda *a, **k: nullcontext())
    _slow(world, 2.5)
    _worker_pass(service, tenant)
    assert len(joiner.calls) == 1 and _joins(tenant, parent) == []
    run = _join_run(tenant, parent)
    assert run.prepared_version < run.dirty_version  # not done: it comes back
    _worker_pass(service, tenant)
    assert len(joiner.calls) == 1 and len(_joins(tenant, parent)) == 1
    PipelinePreparation(service, PipelineStore(), (tenant,))()
    assert len(joiner.calls) == 1 and len(_joins(tenant, parent)) == 1


def test_the_worker_joins_in_the_background_one_at_a_time_db(world) -> None:  # noqa: ANN001
    """Review fix 1: the loop's preparation hands the join to its own thread and comes
    back at once; the run stays leased by that thread, so no second join starts."""
    service, _, _, joiner, tenant, _, parent, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    _slow(world, 2)
    _settle_generations(tenant)
    preparation = PipelinePreparation(service, PipelineStore(), (tenant,), background_joins=True)
    began = time.monotonic()
    preparation()
    assert time.monotonic() - began < 1.5  # did not wait for the encode
    assert preparation.joins is not None and preparation.joins.busy()
    with tenant_session(tenant) as session:  # the parent is dirtied again meanwhile
        session.execute(
            text("UPDATE creative_pipeline_runs SET dirty_version=dirty_version+1 "
                 "WHERE draft_id=:p AND phase='join'"),
            {"p": parent},
        )  # fmt: skip
    preparation()  # busy: the join run is left for a later pass
    assert preparation.shutdown(None)
    assert len(joiner.calls) == 1 and len(_joins(tenant, parent)) == 1
    preparation()  # the later pass: same parts, same fingerprint — nothing new
    assert preparation.shutdown(None)
    assert len(joiner.calls) == 1 and len(_joins(tenant, parent)) == 1
    run = _join_run(tenant, parent)
    assert run.prepared_version == run.dirty_version and run.lease_token is None


def test_an_unknown_phase_is_logged_at_error_db(world, caplog) -> None:  # noqa: ANN001
    import logging

    service, _, _, _, tenant, _, parent, _ = world
    with tenant_session(tenant) as session:
        session.execute(
            text("""
            INSERT INTO creative_pipeline_runs (tenant_id, draft_id, revision, phase,
                pipeline_version)
            SELECT tenant_id, id, revision, 'mystery', pipeline_version
            FROM content_drafts WHERE id=:p
            """),
            {"p": parent},
        )
    with caplog.at_level(logging.ERROR, logger="qualify_api.creative.worker.pipeline"):
        _worker_pass(service, tenant)
    (record,) = [r for r in caplog.records if "unknown_phase" in r.getMessage()]
    assert record.levelno == logging.ERROR and "mystery" in record.getMessage()


def test_a_new_text_keeps_the_parents_picture_db(world) -> None:  # noqa: ANN001
    """Review fix 4: the parent's picture is its join's poster, and a new text never
    leaves it empty while its parts are joined again."""
    service, _, _, _, tenant, user, parent, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant, draft_id=child)
    _worker_pass(service, tenant)
    (first,) = _joins(tenant, parent)
    poster = first.params["thumbnail_key"]
    picture = "SELECT preview_key FROM content_drafts WHERE id=:p"
    assert poster and _scalar(tenant, picture, p=parent) == poster
    service.reject(
        tenant_id=tenant, draft_id=parent, reason="otro texto", user_id=user, regenerate=True
    )
    service.run_generation(tenant_id=tenant, draft_id=parent)
    assert _scalar(tenant, picture, p=parent) == poster  # before the worker joins again
    _worker_pass(service, tenant)
    assert _scalar(tenant, picture, p=parent) == poster
    # restoring the first version shows its join's poster, not the joined video
    v1 = _scalar(tenant, "SELECT id FROM piece_versions WHERE draft_id=:p AND revision=1", p=parent)
    service.restore_version(tenant_id=tenant, draft_id=parent, version_id=v1)  # type: ignore[arg-type]
    assert _scalar(tenant, picture, p=parent) == poster


def _parent_with_parts(service, parts_service, tenant, brand, user):  # noqa: ANN001, ANN202
    brief = parent_brief(*THREE_PARTS).model_copy(update={"brand_id": brand})
    parent = service.create_draft(tenant_id=tenant, brand_id=brand, brief=brief, user_id=user)
    service.run_generation(tenant_id=tenant, draft_id=parent)
    for child in parts_service.create_parts(tenant_id=tenant, parent_id=parent, user_id=user):
        service.run_generation(tenant_id=tenant, draft_id=child)
    return parent


def test_two_businesses_joined_back_to_back_each_under_its_own_db(world, monkeypatch) -> None:  # noqa: ANN001
    """Re-review fix 1: the background join binds its tenant from the RUN. The loop moves
    on to the next business before the thread starts; the join still reads as its own."""
    from contextlib import contextmanager

    from qualify_api.creative.worker import pipeline as worker_pipeline

    service, parts, _, joiner, tenant_a, _, parent_a, ids = world
    for child in ids:
        service.run_generation(tenant_id=tenant_a, draft_id=child)
    tenant_b, brand_b, user_b = parts_db._business(monkeypatch)
    parent_b = _parent_with_parts(service, parts, tenant_b, brand_b, user_b)
    for tenant in (tenant_a, tenant_b):
        _settle_generations(tenant)
    seen: list[UUID] = []
    real_join = service._media.join_preview

    def join_preview(tenant_id, parent_id):  # noqa: ANN001, ANN202
        seen.append(tenant_id)
        return real_join(tenant_id, parent_id)

    service._media.join_preview = join_preview  # type: ignore[method-assign]
    real_preparing = worker_pipeline.preparing

    @contextmanager
    def late(run):  # noqa: ANN001, ANN202 — the thread starts after the loop moved on
        time.sleep(0.5)
        with real_preparing(run):
            yield

    monkeypatch.setattr(worker_pipeline, "preparing", late)
    preparation = PipelinePreparation(
        service, PipelineStore(), (tenant_a, tenant_b), background_joins=True
    )
    for _ in range(2):  # one join at a time: A in this pass, B in the next
        preparation()
        assert preparation.shutdown(None)
        preparation.joins = worker_pipeline.BackgroundJoins(preparation.store)
    assert sorted(map(str, seen)) == sorted(map(str, (tenant_a, tenant_b)))
    assert len(_joins(tenant_a, parent_a)) == 1 and len(_joins(tenant_b, parent_b)) == 1
    for tenant, parent in ((tenant_a, parent_a), (tenant_b, parent_b)):
        run = _join_run(tenant, parent)
        assert run.prepared_version == run.dirty_version
