"""The source window of an «Igual al original» part (ADR 44, m-24921059 VE-04d).

Offline: a synthetic MP4 stored under the public door of an in-memory bucket, the
in-memory analysis store, and a fake draft-ownership check standing in for RLS.
"""

from __future__ import annotations

import io
import math
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any
from uuid import UUID, uuid4

import av
import numpy as np
import pytest
from qualify_creative.video.cut import cut_window
from qualify_shared.objects.gate import ObjectGate, ObjectNotFound
from qualify_shared.objects.keys import TenantPrefixViolation
from qualify_shared.objects.public import PublicObjectGate, reel_source_key

from qualify_api.creative.process import mark_worker_process, unmark_worker_process
from qualify_api.creative.worker import __main__ as main_module
from qualify_api.referentes import reel_analysis_window as rw
from qualify_api.referentes.reel_analysis_store import AnalysisRecord, InMemoryAnalysisStore
from qualify_api.referentes.reel_analysis_types import STATUS_OK, STATUS_RUNNING
from qualify_api.referentes.reel_analysis_window import (
    WINDOW_ANALYSIS_NOT_READY,
    WINDOW_BAD,
    WINDOW_NOT_EDIT_ELIGIBLE,
    WINDOW_SOURCE_PURGED,
    WINDOW_UNAVAILABLE,
    WINDOW_WRONG_PROCESS,
    ForeignDraft,
    SourceWindowRefused,
    SourceWindows,
    window_key,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
TENANT, OTHER, DRAFT, FOREIGN_DRAFT = uuid4(), uuid4(), uuid4(), uuid4()
FPS = 30


def mp4(seconds: float = 10.0, fps: int = FPS, size: tuple[int, int] = (64, 112)) -> bytes:
    """A synthetic H.264 MP4: each frame a different grey, no real reel."""
    out = io.BytesIO()
    width, height = size
    with av.open(out, "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=fps, options={"preset": "ultrafast"})
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        for i in range(int(seconds * fps)):
            pixels = np.full((height, width, 3), (7 * i) % 255, dtype=np.uint8)
            for packet in video.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return out.getvalue()


SOURCE = mp4()


class Bucket:
    """An in-memory R2 that counts reads and answers a missing key like R2 does."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.reads: list[str] = []

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def _get(self, key: str) -> bytes:
        self.reads.append(key)
        if key not in self.objects:
            raise ObjectNotFound(key)
        return self.objects[key][0]

    def open(self, key: str) -> IO[bytes]:
        return io.BytesIO(self._get(key))

    def size(self, key: str) -> int:
        return len(self._get(key))

    def open_range(self, key: str, start: int, end: int) -> IO[bytes]:
        return io.BytesIO(self._get(key)[start : end + 1])


@dataclass
class Drafts:
    """RLS on `content_drafts`: a business sees only its own drafts."""

    owned: dict[UUID, set[UUID]] = field(default_factory=lambda: {TENANT: {DRAFT}})
    calls: int = 0

    def owns(self, tenant_id: UUID, draft_id: UUID) -> bool:
        self.calls += 1
        return draft_id in self.owned.get(tenant_id, set())


@dataclass
class CountingRequests:
    store: InMemoryAnalysisStore
    gets: int = 0

    def get(self, tenant_id: UUID, analysis_id: UUID) -> AnalysisRecord | None:
        self.gets += 1
        return self.store.get(tenant_id, analysis_id)


@dataclass
class World:
    windows: SourceWindows
    store: InMemoryAnalysisStore
    requests: CountingRequests
    bucket: Bucket
    cuts: list[tuple[float, float]]
    analysis_id: UUID
    source_key: str
    temp: Path


def analysis(**kw: Any) -> AnalysisRecord:
    analysis_id = kw.pop("id", uuid4())
    values: dict[str, Any] = {
        "id": analysis_id,
        "network": "instagram",
        "post_id": "DABC1",
        "analysis_version": 1,
        "status": STATUS_OK,
        "post_url": "https://www.instagram.com/reel/DABC1/",
        "created_at": NOW,
        "source_key": reel_source_key("instagram", "DABC1", analysis_id),
        "source_seconds": 10.0,
        "fps": float(FPS),
        "edit_eligible": True,
        "finished_at": NOW,
    }
    values.update(kw)
    return AnalysisRecord(**values)


@pytest.fixture
def worker_process() -> Iterator[None]:
    """This test process plays the creative worker (its entry point marks it)."""
    mark_worker_process()
    yield
    unmark_worker_process()


@pytest.fixture
def world(tmp_path: Path, worker_process: None) -> World:
    store = InMemoryAnalysisStore()
    row = analysis()
    store.put(row)
    bucket = Bucket()
    bucket.objects[row.source_key] = (SOURCE, "video/mp4")
    cuts: list[tuple[float, float]] = []

    def spy(source: Any, start_s: float, end_s: float, **kw: Any) -> Any:
        cuts.append((start_s, end_s))
        return cut_window(source, start_s, end_s, **kw)

    requests = CountingRequests(store)
    temp = tmp_path / "work"
    temp.mkdir()
    windows = SourceWindows(
        requests=requests,
        drafts=Drafts(),
        gate=ObjectGate(bucket),
        public=PublicObjectGate(bucket),
        temp_root=str(temp),
        cut=spy,
    )
    return World(windows, store, requests, bucket, cuts, row.id, row.source_key, temp)


def frames_of(data: bytes) -> tuple[int, float]:
    with av.open(io.BytesIO(data)) as container:
        stream = container.streams.video[0]
        count = sum(1 for _ in container.decode(stream))
        return count, float(stream.average_rate)


def cut(world: World, start_s: Any = 3, end_s: Any = 7, **kw: Any) -> str:
    return world.windows.source_window(
        kw.pop("tenant_id", TENANT),
        kw.pop("analysis_id", world.analysis_id),
        draft_id=kw.pop("draft_id", DRAFT),
        start_s=start_s,
        end_s=end_s,
    )


def test_a_3_to_7_window_lasts_4_seconds_in_the_pieces_folder(world: World) -> None:
    key = cut(world)

    aid = world.analysis_id
    assert key == f"t/{TENANT}/generated/{DRAFT}/source-window-{aid}-3-7.mp4"
    assert key == window_key(TENANT, DRAFT, aid, 3, 7)
    data, content_type = world.bucket.objects[key]
    assert content_type == "video/mp4"
    frames, rate = frames_of(data)
    assert rate == FPS
    assert abs(frames - 4 * FPS) <= 1  # 4 s ± 1 frame
    assert world.cuts == [(3.0, 7.0)]
    # nothing written under `public/`, and the temp folder is gone
    assert [k for k in world.bucket.objects if k.startswith("public/")] == [world.source_key]
    assert list(world.temp.iterdir()) == []


def test_a_second_identical_call_does_not_cut_again(world: World) -> None:
    first = cut(world)
    source_reads = world.bucket.reads.count(world.source_key)

    assert cut(world) == first
    assert world.cuts == [(3.0, 7.0)]
    assert world.bucket.reads.count(world.source_key) == source_reads
    # another window of the same piece is another object
    assert cut(world, 0, 10) == window_key(TENANT, DRAFT, world.analysis_id, 0, 10)
    assert len(world.cuts) == 2


def test_a_part_whose_reference_reel_changes_never_reuses_the_old_cut(world: World) -> None:
    old = cut(world)
    other = analysis(post_id="DXYZ9")
    world.store.put(other)
    world.bucket.objects[other.source_key] = (SOURCE, "video/mp4")

    new = cut(world, analysis_id=other.id)

    assert new != old and str(other.id) in new
    assert len(world.cuts) == 2


def test_at_most_one_cut_runs_per_process_at_a_time(world: World) -> None:
    """Two drafts cut at once: the second waits for the first (the encode peaks ~295 MiB)."""
    second_draft = uuid4()
    world.windows.drafts.owned[TENANT].add(second_draft)  # type: ignore[attr-defined]
    inside, peak, gate = [0], [0], threading.Lock()
    real = world.windows.cut

    def slow(source: Any, start_s: float, end_s: float, **kw: Any) -> Any:
        with gate:
            inside[0] += 1
            peak[0] = max(peak[0], inside[0])
        time.sleep(0.2)
        try:
            return real(source, start_s, end_s, **kw)
        finally:
            with gate:
                inside[0] -= 1

    world.windows.cut = slow
    threads = [
        threading.Thread(target=cut, args=(world,), kwargs={"draft_id": d})
        for d in (DRAFT, second_draft)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak[0] == 1
    assert len(world.cuts) == 2


@pytest.mark.parametrize(
    ("start_s", "end_s"),
    [
        (2.5, 6.5),
        (2.5, 7),
        (0, 12),
        (3, 6),
        (3, 3),
        (-1, 4),
        (True, 5),
        ("3", "7"),
        (math.nan, 7),
        (3, math.inf),
        (-math.inf, 4),
    ],
)
def test_a_window_that_is_not_4_to_10_whole_seconds_is_refused_before_any_read(
    world: World, start_s: Any, end_s: Any
) -> None:
    with pytest.raises(SourceWindowRefused) as refused:
        cut(world, start_s, end_s)

    assert refused.value.code == WINDOW_BAD
    assert not refused.value.falls_back
    assert world.requests.gets == 0 and world.bucket.reads == [] and world.cuts == []


def test_a_purged_source_is_refused_without_opening_r2(world: World) -> None:
    world.store.put(analysis(id=world.analysis_id, source_purged_at=NOW))

    with pytest.raises(SourceWindowRefused) as refused:
        cut(world)

    assert refused.value.code == WINDOW_SOURCE_PURGED
    assert refused.value.falls_back
    assert world.bucket.reads == [] and world.cuts == []


def test_a_source_missing_from_r2_is_also_source_purged(world: World) -> None:
    del world.bucket.objects[world.source_key]

    with pytest.raises(SourceWindowRefused) as refused:
        cut(world)

    assert refused.value.code == WINDOW_SOURCE_PURGED
    assert world.cuts == [] and list(world.temp.iterdir()) == []


def test_a_draft_of_another_business_is_refused_before_reading_the_source(world: World) -> None:
    with pytest.raises(TenantPrefixViolation) as refused:
        cut(world, draft_id=FOREIGN_DRAFT)
    assert isinstance(refused.value, ForeignDraft)

    # the same draft asked for by another business: also refused
    with pytest.raises(ForeignDraft):
        cut(world, tenant_id=OTHER)

    assert world.requests.gets == 0 and world.bucket.reads == [] and world.cuts == []
    assert not any(k.startswith(f"t/{OTHER}/") for k in world.bucket.objects)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"edit_eligible": False}, WINDOW_NOT_EDIT_ELIGIBLE),
        ({"edit_eligible": None}, WINDOW_NOT_EDIT_ELIGIBLE),
        ({"status": STATUS_RUNNING}, WINDOW_ANALYSIS_NOT_READY),
        ({"source_key": None}, WINDOW_ANALYSIS_NOT_READY),
        ({"source_seconds": 6.0}, WINDOW_UNAVAILABLE),
    ],
)
def test_a_row_that_cannot_give_the_window_falls_back_to_reference(
    world: World, changes: dict[str, Any], code: str
) -> None:
    world.store.put(analysis(id=world.analysis_id, **changes))

    with pytest.raises(SourceWindowRefused) as refused:
        cut(world)

    assert refused.value.code == code
    assert refused.value.falls_back
    assert world.bucket.reads == [] and world.cuts == []


def test_an_unknown_analysis_is_not_ready(world: World) -> None:
    with pytest.raises(SourceWindowRefused) as refused:
        cut(world, analysis_id=uuid4())

    assert refused.value.code == WINDOW_ANALYSIS_NOT_READY


def test_a_source_shorter_than_its_row_says_is_window_unavailable(world: World) -> None:
    world.bucket.objects[world.source_key] = (mp4(seconds=5.0), "video/mp4")

    with pytest.raises(SourceWindowRefused) as refused:
        cut(world)

    assert refused.value.code == WINDOW_UNAVAILABLE
    assert refused.value.falls_back
    assert not any(k.startswith(f"t/{TENANT}/") for k in world.bucket.objects)
    assert list(world.temp.iterdir()) == []


def test_outside_the_marked_worker_it_refuses_before_any_read(world: World) -> None:
    """The Reflex process never marks itself, whatever `.env.prod` says."""
    unmark_worker_process()

    with pytest.raises(SourceWindowRefused) as refused:
        cut(world)

    assert refused.value.code == WINDOW_WRONG_PROCESS
    assert not refused.value.falls_back
    assert world.requests.gets == 0 and world.bucket.reads == [] and world.cuts == []


def test_the_environment_switch_does_not_open_it(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    unmark_worker_process()
    monkeypatch.setenv("QUALIFY_CREATIVE_DISPATCHER", "queue")

    with pytest.raises(SourceWindowRefused) as refused:
        cut(world)

    assert refused.value.code == WINDOW_WRONG_PROCESS


def test_the_creative_worker_entry_point_marks_its_process() -> None:
    import ast

    source = Path(main_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    main = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)]
    called = {n.func.id for n in calls if isinstance(n.func, ast.Name)}
    assert "mark_worker_process" in called


def test_a_cut_already_stored_returns_without_waiting_for_the_lock(world: World) -> None:
    key = cut(world)
    assert rw._CUT_LOCK.acquire(timeout=1)
    try:
        assert cut(world) == key  # checked before the lock: no wait, no cut
    finally:
        rw._CUT_LOCK.release()
    assert len(world.cuts) == 1


def test_a_lock_held_past_the_timeout_falls_back(world: World) -> None:
    world.windows.lock_timeout_s = 0.05
    assert rw._CUT_LOCK.acquire(timeout=1)
    try:
        with pytest.raises(SourceWindowRefused) as refused:
            cut(world)
    finally:
        rw._CUT_LOCK.release()

    assert refused.value.code == WINDOW_UNAVAILABLE
    assert refused.value.falls_back
    assert world.cuts == []
