"""The 30-day purge of the reels' stored sources and frames (`reel_retention`, ADR 44 F9;
the R8 slice of VE-12 m-24921060), offline: VE-04a's `InMemoryAnalysisStore` and an
in-memory R2 behind the real `PublicObjectGate`.

Pins: day 29 deletes nothing, day 30 deletes `source/` and `frames/` and only then marks
both dates; a second pass does nothing; without `execute` it reports and changes nothing;
an R2 error leaves that row unmarked and the others go on; every due row is reached in
batches; an upload whose `record_source` never landed (no `source_key`, only the date) is
deleted too; a row a live lease holds waits; a row revived meanwhile is purged on its new
date; the worker purges at start and then daily, and only the `--all-tenants` service."""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.objects.gate import StoredObject
from qualify_shared.objects.public import (
    PublicObjectGate,
    reel_analysis_root,
    reel_frame_key,
    reel_source_key,
)

from qualify_api.referentes import reel_retention as rt
from qualify_api.referentes import worker as cli
from qualify_api.referentes.reel_analysis_store import AnalysisRecord, InMemoryAnalysisStore
from qualify_api.referentes.reel_analysis_types import (
    ANALYSIS_VERSION,
    STATUS_QUEUED,
    STATUS_RUNNING,
)
from qualify_api.referentes.reel_queue import MemoryReelQueue
from qualify_api.referentes.reel_store import MemoryReelRunStore
from qualify_api.referentes.reel_worker import ReelsWorker

STORED_AT = datetime(2026, 11, 9, 11, 0, tzinfo=UTC)
DUE = STORED_AT + timedelta(days=30)


class DictStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.broken: set[str] = set()

    def put(self, key: str, fileobj: Any, content_type: str) -> None:
        self.objects[key] = fileobj.read()

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key])

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        for key, data in sorted(self.objects.items()):
            if key.startswith(prefix):
                yield StoredObject(key, len(data))

    def delete_keys(self, keys: Sequence[str]) -> None:
        if any(key.split("/source/")[0].split("/frames/")[0] in self.broken for key in keys):
            raise RuntimeError("R2 refused to delete 1 object(s): InternalError")
        for key in keys:
            self.objects.pop(key, None)


def _stored(
    store: InMemoryAnalysisStore, r2: DictStore, post_id: str, *, recorded: bool = True, **kw
) -> UUID:
    """A reel whose source the analysis stored at `STORED_AT` (plus one frame, VE-04c).
    `recorded=False`: the upload happened but `record_source` never landed — the row only
    has the date `set_purge_date` wrote before the upload."""
    analysis_id = uuid4()
    key = reel_source_key("instagram", post_id, analysis_id)
    kw.setdefault("status", STATUS_QUEUED)
    store.put(
        AnalysisRecord(
            id=analysis_id,
            network="instagram",
            post_id=post_id,
            analysis_version=ANALYSIS_VERSION,
            post_url=f"https://www.instagram.com/reel/{post_id}/",
            created_at=STORED_AT,
            source_key=key if recorded else None,
            source_purge_after=STORED_AT + timedelta(days=30),
            **kw,
        )
    )
    r2.objects[key] = b"mp4" * 10
    r2.objects[reel_frame_key("instagram", post_id, analysis_id, 0, 0)] = b"jpg"
    return analysis_id


@pytest.fixture
def world() -> tuple[InMemoryAnalysisStore, DictStore, PublicObjectGate]:
    r2 = DictStore()
    return InMemoryAnalysisStore(), r2, PublicObjectGate(r2)


def _row(store: InMemoryAnalysisStore, analysis_id: UUID) -> AnalysisRecord:
    return next(r for r in store.rows() if r.id == analysis_id)


def test_day_twenty_nine_nothing_day_thirty_both_folders(world: Any) -> None:
    store, r2, gate = world
    row_id = _stored(store, r2, "C1")
    day29 = rt.purge_reel_sources(gate, STORED_AT + timedelta(days=29), True, store=store)
    assert (day29.due, day29.purged) == (0, 0) and len(r2.objects) == 2

    report = rt.purge_reel_sources(gate, DUE, True, store=store)
    assert (report.due, report.purged, report.objects, report.failed) == (1, 1, 2, 0)
    assert r2.objects == {}
    row = _row(store, row_id)
    assert row.source_purged_at == DUE and row.frames_purged_at == DUE
    assert row.source_key is not None  # the row (and VE-04c's sheet) stays

    again = rt.purge_reel_sources(gate, DUE + timedelta(days=1), True, store=store)
    assert (again.due, again.purged) == (0, 0)


def test_without_execute_it_reports_and_changes_nothing(world: Any) -> None:
    store, r2, gate = world
    row_id = _stored(store, r2, "C1")
    report = rt.purge_reel_sources(gate, DUE + timedelta(days=1), False, store=store)
    assert (report.due, report.purged, report.objects, report.execute) == (1, 0, 2, False)
    assert len(r2.objects) == 2 and _row(store, row_id).source_purged_at is None


def test_an_r2_error_leaves_that_row_unmarked_and_the_others_go_on(world: Any) -> None:
    store, r2, gate = world
    broken = _stored(store, r2, "C1")
    fine = _stored(store, r2, "C2")
    r2.broken.add(reel_analysis_root("instagram", "C1", broken).rstrip("/"))
    report = rt.purge_reel_sources(gate, DUE, True, store=store)
    assert (report.due, report.purged, report.failed) == (2, 1, 1)
    assert _row(store, broken).source_purged_at is None
    assert _row(store, fine).source_purged_at is not None


def test_every_due_row_is_reached_in_batches(world: Any) -> None:
    store, r2, gate = world
    for n in range(5):
        _stored(store, r2, f"C{n}")
    dry = rt.purge_reel_sources(gate, DUE, False, store=store, batch=2)
    assert dry.due == 5 and dry.purged == 0  # a dry run pages too, not 2 forever
    done = rt.purge_reel_sources(gate, DUE, True, store=store, batch=2)
    assert (done.due, done.purged) == (5, 5) and r2.objects == {}


def test_an_upload_whose_record_never_landed_is_deleted_by_its_date(world: Any) -> None:
    """N2: the folders come from the row's identity, never from `source_key`."""
    store, r2, gate = world
    orphan = _stored(store, r2, "C1", recorded=False)
    report = rt.purge_reel_sources(gate, DUE, True, store=store)
    assert (report.due, report.purged, report.objects) == (1, 1, 2)
    assert r2.objects == {} and _row(store, orphan).source_purged_at == DUE


def test_a_row_a_live_lease_holds_waits_for_the_next_day(world: Any) -> None:
    store, r2, gate = world
    held = _stored(
        store,
        r2,
        "C1",
        status=STATUS_RUNNING,
        lease_token=uuid4(),
        lease_until=DUE + timedelta(minutes=2),
    )
    report = rt.purge_reel_sources(gate, DUE, True, store=store)
    assert report.due == 0 and len(r2.objects) == 2
    later = rt.purge_reel_sources(gate, DUE + timedelta(minutes=3), True, store=store)
    assert later.purged == 1 and _row(store, held).source_purged_at is not None


def test_a_row_revived_after_a_purge_is_purged_again(world: Any) -> None:
    """A failed download that a new URL brings back writes a new date before its upload,
    which clears the purged marks (`set_purge_date`)."""
    store, r2, gate = world
    row_id = _stored(store, r2, "C1", recorded=False)
    rt.purge_reel_sources(gate, DUE, True, store=store)
    revived = DUE + timedelta(days=5)
    claimed = store.claim(row_id, revived, timedelta(minutes=2), max_attempts=3)
    assert claimed is not None
    assert store.set_purge_date(row_id, claimed.token, revived + timedelta(days=30))
    assert _row(store, row_id).source_purged_at is None
    r2.objects[reel_source_key("instagram", "C1", row_id)] = b"mp4"
    store.release(row_id, claimed.token)

    assert rt.purge_reel_sources(gate, revived + timedelta(days=29), True, store=store).due == 0
    report = rt.purge_reel_sources(gate, revived + timedelta(days=30), True, store=store)
    assert report.purged == 1 and r2.objects == {}


def test_a_row_whose_date_moved_meanwhile_is_not_marked(world: Any) -> None:
    store, r2, gate = world
    row_id = _stored(store, r2, "C1")
    seen = _row(store, row_id).source_purge_after
    store.put(replace(_row(store, row_id), source_purge_after=DUE + timedelta(days=30)))
    assert store.mark_purged(row_id, seen, DUE) is False
    assert _row(store, row_id).source_purged_at is None


def test_after_the_purge_the_screen_is_told_the_source_is_gone(world: Any) -> None:
    """Criterion 1: `get_analysis_status` says `source_available = false` (and VE-04d
    answers `source_purged`, `reel_analysis_window._check_analysis`)."""
    from qualify_api.referentes.reel_analysis import get_analysis_status

    store, r2, gate = world
    row_id = _stored(store, r2, "C1")
    tenant = uuid4()
    before = get_analysis_status(tenant, row_id, store=store, clock=lambda: DUE)
    assert before is not None and before.source_available
    rt.purge_reel_sources(gate, DUE, True, store=store)
    after = get_analysis_status(tenant, row_id, store=store, clock=lambda: DUE)
    assert after is not None and not after.source_available


class _LockedStore(DictStore):
    """The production bucket if its lock rule refuses deletes as it refuses overwrites."""

    def __init__(self) -> None:
        super().__init__()
        self.delete_calls = 0

    def delete_keys(self, keys: Sequence[str]) -> None:
        from qualify_shared.objects.gate import DeleteRefused

        self.delete_calls += 1
        raise DeleteRefused(len(keys), ("ObjectLockedByBucketPolicy",))


def test_a_bucket_that_refuses_deletes_stops_the_pass_marks_nothing_logs_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The risk of 2026-11-05: if the lock refuses deletes, the purge must neither crash,
    nor try every row, nor mark anything; one ERROR line, and tomorrow tries again."""
    store, r2 = InMemoryAnalysisStore(), _LockedStore()
    gate = PublicObjectGate(r2)
    ids = [_stored(store, r2, f"C{n}") for n in range(5)]
    with caplog.at_level("ERROR", logger=rt.logger.name):
        report = rt.purge_reel_sources(gate, DUE, True, store=store, batch=2)
    assert report.refused == ("ObjectLockedByBucketPolicy",)
    assert (report.due, report.purged, report.failed) == (1, 0, 1)
    assert r2.delete_calls == 1 and len(r2.objects) == 10
    assert all(_row(store, i).source_purged_at is None for i in ids)
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(errors) == 1 and "ObjectLockedByBucketPolicy" in errors[0].getMessage()
    # The next day the same rows are still due: nothing was lost or marked.
    assert rt.purge_reel_sources(gate, DUE, False, store=store).due == 5


def test_a_delete_that_answers_ok_but_leaves_objects_is_not_marked(world: Any) -> None:
    """If R2 answered OK but kept the objects (a lock rule that does not report), the row
    is not marked: the purge lists again before marking."""
    store, r2, gate = world

    class _Sticky(DictStore):
        def delete_keys(self, keys: Sequence[str]) -> None:
            return None

    sticky = _Sticky()
    row_id = _stored(store, sticky, "C1")
    report = rt.purge_reel_sources(PublicObjectGate(sticky), DUE, True, store=store)
    assert (report.purged, report.failed) == (0, 1)
    assert _row(store, row_id).source_purged_at is None


def test_the_switch_reads_the_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(rt.EXECUTE_ENV, raising=False)
    assert rt.execute_from_env() is False
    monkeypatch.setenv(rt.EXECUTE_ENV, "1")
    assert rt.execute_from_env() is True


# --------------------------------------------------------------------------------------
# in the worker
# --------------------------------------------------------------------------------------


def test_the_worker_purges_at_start_and_then_daily() -> None:
    calls: list[datetime] = []
    now = {"t": STORED_AT}
    store = MemoryReelRunStore()
    worker = ReelsWorker(
        MemoryReelQueue(store),
        store,
        run=lambda tenant, run_id: None,  # type: ignore[arg-type,return-value]
        ready=lambda tenant, brand: True,
        clock=lambda: now["t"],
        purge=lambda moment: calls.append(moment) or rt.PurgeReport(execute=True),
    )
    worker.pass_once()
    now["t"] += timedelta(hours=23)
    worker.pass_once()
    now["t"] += timedelta(hours=1)
    worker.pass_once()
    assert calls == [STORED_AT, STORED_AT + timedelta(hours=24)]


def test_only_the_all_tenants_service_purges_and_drains() -> None:
    """The stored sources and the analysis queue belong to no business: a `--tenant`
    worker (local) never deletes nor downloads them."""
    every = cli.production_worker(
        None, batch=1, schedule_every=timedelta(minutes=15), should_stop=lambda: False
    )
    scoped = cli.production_worker(
        [uuid4()], batch=1, schedule_every=timedelta(minutes=15), should_stop=lambda: False
    )
    assert every._purge is not None and scoped._purge is None
    assert every._drain is not None and scoped._drain is None


def test_a_row_whose_stored_source_was_purged_is_never_claimed(world: Any) -> None:
    """FN3: a row purged while still `queued` (its source stored, never described) is taken
    by no lane — not the download one (it needs a pending URL), not VE-04c's describe one
    (m-24921058: describing it would read an object that is gone), not a claim by id —
    while a stored source not purged yet is described as usual."""
    from qualify_api.referentes import reel_analysis_worker as w

    store, r2, gate = world
    purged = _stored(store, r2, "C1")  # queued, source stored, no pending URL
    rt.purge_reel_sources(gate, DUE, True, store=store)
    assert _row(store, purged).source_purged_at == DUE
    later = DUE + timedelta(minutes=1)
    lease = w.LEASE
    assert store.claim_next(later, lease, download_only=True, max_attempts=3) is None
    assert store.claim_next(later, lease, download_only=False, max_attempts=3) is None
    assert store.claim(purged, later, lease, max_attempts=3) is None

    described: list[str] = []

    def describe(job: w.DescribeInput) -> Any:
        described.append(job.record.post_id)
        raise w.DescribeFailed("not expected in this test")

    worker = w.Worker(queue=store, gate=gate, describe=describe, clock=lambda: later)
    assert w.drain_once(worker) is None and described == []
    # control: a stored source still in R2 is the describe lane's
    kept = _stored(store, r2, "C2")
    claimed = store.claim_next(later, lease, download_only=False, max_attempts=3)
    assert claimed is not None and claimed.record.id == kept
