"""The 30-day purge of the reel videos the weekly run copied (`reel_retention`, ADR 44 F9;
the R8 slice of VE-12 m-24921060), offline: the in-memory analysis store and an in-memory
R2 behind the real `PublicObjectGate`.

Pins: day 29 deletes nothing, day 30 deletes `source/` and `frames/` and only then marks
both dates; a second pass does nothing; without `execute` it reports and changes nothing;
an R2 error leaves that row unmarked and the others go on; every due row is reached in
batches; the worker purges at start and then daily, and only the `--all-tenants` service."""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_shared.objects import (
    PublicObjectGate,
    StoredObject,
    public_analysis_prefix,
    public_source_key,
)

from qualify_api.referentes import reel_analysis as ra
from qualify_api.referentes import reel_retention as rt
from qualify_api.referentes import worker as cli
from qualify_api.referentes.reel_queue import MemoryReelQueue
from qualify_api.referentes.reel_store import MemoryReelRunStore
from qualify_api.referentes.reel_worker import ReelsWorker

STORED_AT = datetime(2026, 11, 9, 11, 0, tzinfo=UTC)


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
        if any(key.split("/source/")[0] in self.broken for key in keys):
            raise RuntimeError("R2 refused to delete 1 object(s): InternalError")
        for key in keys:
            self.objects.pop(key, None)


def _stored(store: ra.MemoryAnalysisStore, r2: DictStore, post_id: str) -> UUID:
    """A reel whose video the run copied at `STORED_AT` (plus one frame, for VE-04c)."""
    row = store.upsert("instagram", post_id, post_url="https://x/", video_url="https://y/")
    token = uuid4()
    assert store.claim(row.id, token=token, now=STORED_AT) is not None
    key = public_source_key("instagram", post_id, row.id)
    source = ra.StoredSource(key, "0" * 64, 12.0, 720, 1280, 30.0, True)
    assert store.stored(row.id, token=token, source=source, now=STORED_AT)
    prefix = public_analysis_prefix("instagram", post_id, row.id)
    r2.objects[key] = b"mp4" * 10
    r2.objects[prefix + "frames/00-0.jpg"] = b"jpg"
    return row.id


@pytest.fixture
def world() -> tuple[ra.MemoryAnalysisStore, DictStore, PublicObjectGate]:
    r2 = DictStore()
    return ra.MemoryAnalysisStore(), r2, PublicObjectGate(r2)


def test_day_twenty_nine_nothing_day_thirty_both_folders(world: Any) -> None:
    store, r2, gate = world
    row_id = _stored(store, r2, "C1")
    day29 = rt.purge_reel_sources(gate, STORED_AT + timedelta(days=29), True, store=store)
    assert (day29.due, day29.purged) == (0, 0) and len(r2.objects) == 2

    day30 = STORED_AT + timedelta(days=30)
    report = rt.purge_reel_sources(gate, day30, True, store=store)
    assert (report.due, report.purged, report.objects, report.failed) == (1, 1, 2, 0)
    assert r2.objects == {}
    item = store.rows[row_id]
    assert item.row.source_purged_at == day30 and item.values["frames_purged_at"] == day30
    assert item.row.source_key is not None  # the row (and VE-04c's sheet) stays

    again = rt.purge_reel_sources(gate, day30 + timedelta(days=1), True, store=store)
    assert (again.due, again.purged) == (0, 0)


def test_without_execute_it_reports_and_changes_nothing(world: Any) -> None:
    store, r2, gate = world
    row_id = _stored(store, r2, "C1")
    report = rt.purge_reel_sources(gate, STORED_AT + timedelta(days=31), False, store=store)
    assert (report.due, report.purged, report.objects, report.execute) == (1, 0, 2, False)
    assert len(r2.objects) == 2 and store.rows[row_id].row.source_purged_at is None


def test_an_r2_error_leaves_that_row_unmarked_and_the_others_go_on(world: Any) -> None:
    store, r2, gate = world
    broken = _stored(store, r2, "C1")
    fine = _stored(store, r2, "C2")
    r2.broken.add(public_analysis_prefix("instagram", "C1", broken).rstrip("/"))
    report = rt.purge_reel_sources(gate, STORED_AT + timedelta(days=30), True, store=store)
    assert (report.due, report.purged, report.failed) == (2, 1, 1)
    assert store.rows[broken].row.source_purged_at is None
    assert store.rows[fine].row.source_purged_at is not None


def test_every_due_row_is_reached_in_batches(world: Any) -> None:
    store, r2, gate = world
    for n in range(5):
        _stored(store, r2, f"C{n}")
    when = STORED_AT + timedelta(days=30)
    dry = rt.purge_reel_sources(gate, when, False, store=store, batch=2)
    assert dry.due == 5 and dry.purged == 0  # a dry run pages too, not 2 forever
    done = rt.purge_reel_sources(gate, when, True, store=store, batch=2)
    assert (done.due, done.purged) == (5, 5) and r2.objects == {}


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


def test_only_the_all_tenants_service_purges() -> None:
    every = cli.production_worker(
        None, batch=1, schedule_every=timedelta(minutes=15), should_stop=lambda: False
    )
    scoped = cli.production_worker(
        [uuid4()], batch=1, schedule_every=timedelta(minutes=15), should_stop=lambda: False
    )
    assert every._purge is not None and scoped._purge is None
