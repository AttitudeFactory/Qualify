"""Running a reel's shared analysis, offline (ADR 44, m-24921056 VE-04a): the queue order,
the lease, the safe download, the remux, the public R2 door, the cost guard, the
injected describe step, R4's `analyze_run_ideas` and the CLI.

Nothing here reaches a network or a bucket: the CDN is an `httpx.MockTransport`, R2 an
in-memory store, the videos are synthetic MP4s made with PyAV, and the describe step
(VE-04c's Haiku) is a fake.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import IO
from uuid import UUID, uuid4

import av
import httpx
import numpy as np
import pytest
from qualify_shared.objects.gate import ObjectNotFound, StoredObject
from qualify_shared.objects.public import PublicObjectGate, reel_source_key

from qualify_api.referentes import reel_analysis_worker as w
from qualify_api.referentes import reel_runs
from qualify_api.referentes.reel_analysis import request_analysis
from qualify_api.referentes.reel_analysis_store import (
    AnalysisRecord,
    DescribeResult,
    InMemoryAnalysisStore,
)
from qualify_api.referentes.reel_analysis_types import (
    ANALYSIS_VERSION,
    ERROR_MODEL_FAILED,
    ERROR_SOURCE_EXPIRED,
    ERROR_SOURCE_TOO_LARGE,
    ERROR_SOURCE_UNAVAILABLE,
    ERROR_SOURCE_UNREADABLE,
    OBSERVED,
    STAGE_DESCRIBING,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_QUEUED,
    STATUS_RUNNING,
    ReelSource,
    ShotAnalysis,
)

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
TENANT, BRAND, RUN = uuid4(), uuid4(), uuid4()


# -- fakes ----------------------------------------------------------------------------------


def mp4(seconds: float = 2.0, fps: int = 30, size: tuple[int, int] = (64, 112), *, audio=False):
    """A synthetic H.264 MP4 (optionally with an AAC track) — no real reel."""
    out = io.BytesIO()
    width, height = size
    with av.open(out, "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=fps, options={"preset": "ultrafast"})
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        track = None
        if audio:
            track = sink.add_stream("aac", rate=44100)
            track.layout = "mono"
        for i in range(int(seconds * fps)):
            pixels = np.full((height, width, 3), (7 * i) % 255, dtype=np.uint8)
            for packet in video.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                sink.mux(packet)
        if track is not None:
            for i in range(int(seconds * 44100 // 1024)):
                frame = av.AudioFrame.from_ndarray(
                    np.zeros((1, 1024), dtype=np.float32), format="fltp", layout="mono"
                )
                frame.sample_rate, frame.pts = 44100, i * 1024
                for packet in track.encode(frame):
                    sink.mux(packet)
        for stream in [video, *([track] if track else [])]:
            for packet in stream.encode():
                sink.mux(packet)
    return out.getvalue()


CLIP = mp4()
IG_URL = "https://scontent-bog1-1.cdninstagram.com/o1/v/t16/clip.mp4?efg=abc"


class Cdn:
    """A MockTransport CDN that counts requests and answers what each test sets."""

    def __init__(self, body: bytes = CLIP) -> None:
        self.calls: list[str] = []
        self.respond: Callable[[httpx.Request], httpx.Response] = lambda _r: httpx.Response(
            200, content=body
        )

    def client(self) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(str(request.url))
            return self.respond(request)

        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


class Bucket:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.fail_puts = False

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        if self.fail_puts:
            raise OSError("R2 down")
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> IO[bytes]:
        return io.BytesIO(self.objects[key][0])

    def size(self, key: str) -> int:
        if key not in self.objects:
            raise ObjectNotFound(key)
        return len(self.objects[key][0])

    def open_range(self, key: str, start: int, end: int) -> IO[bytes]:
        return io.BytesIO(self.objects[key][0][start : end + 1])

    def list_prefix(self, prefix: str) -> list[StoredObject]:
        return [StoredObject(k, len(v[0])) for k, v in self.objects.items() if k.startswith(prefix)]

    def delete_keys(self, keys: list[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)


@dataclass
class FakeDescribe:
    """VE-04c's stand-in: one model call (counted first), two frames, one shot."""

    cost: Decimal = Decimal("0.0055")
    raises: Exception | None = None
    calls_made: int = 0
    before_complete: Callable[[], None] | None = None

    def __call__(self, job: w.DescribeInput) -> DescribeResult:
        assert job.source_path.exists() and job.source_path.stat().st_size > 0
        job.set_stage(STAGE_DESCRIBING)
        job.charge_model_call()
        self.calls_made += 1
        if self.raises is not None:
            raise self.raises
        keys = (job.put_frame(0, 0, b"\xff\xd8jpeg0"), job.put_frame(0, 1, b"\xff\xd8jpeg1"))
        if self.before_complete:
            self.before_complete()
        return DescribeResult(
            shots=(
                ShotAnalysis(
                    0,
                    0.0,
                    job.source.covered_to_s,
                    frame_keys=keys,
                    frame_times_s=(0.3, 1.7),
                    people_presence=OBSERVED,
                ),
            ),
            reel_sheet={"hook": {"status": "unknown"}},
            model_id="claude-haiku-5-5",
            model_revision="rev-1",
            prompt_version="p1",
            schema_version="s1",
            detector_version="d1",
            sampling_version="m1",
            sampling_params={"max_frames": 32},
            input_tokens=40_000,
            output_tokens=3_000,
            cost_usd=self.cost,
        )


class Clock:
    def __init__(self, at: datetime = NOW) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[w.Worker, InMemoryAnalysisStore, Bucket, Cdn, Path]]:
    store, bucket, cdn = InMemoryAnalysisStore(), Bucket(), Cdn()
    work = tmp_path / "work"
    work.mkdir()
    with cdn.client() as client:
        worker = w.Worker(
            queue=store,
            gate=PublicObjectGate(bucket),
            describe=None,
            http=client,
            clock=Clock(),
            temp_root=str(work),
            renew_every=0.05,
            fleet_cap=1500,
        )
        yield worker, store, bucket, cdn, work


def source(post_id: str = "DABC1", url: str = IG_URL, **kw: object) -> ReelSource:
    return ReelSource(
        network="instagram",
        post_id=post_id,
        post_url=f"https://www.instagram.com/reel/{post_id}/",
        video_url=url,
        **kw,  # type: ignore[arg-type]
    )


def enqueue(store: InMemoryAnalysisStore, post_id: str = "DABC1", url: str = IG_URL, **kw):
    record, _ = store.ensure(source(post_id, url), ANALYSIS_VERSION, kw.pop("at", NOW))
    if kw:
        record = replace(record, **kw)
        store.put(record)
    return record


# -- order and lease ----------------------------------------------------------------------


def test_an_on_demand_row_goes_before_ten_older_weekly_rows(world) -> None:
    worker, store, *_ = world
    for i in range(10):
        enqueue(store, f"W{i}", at=NOW - timedelta(hours=3, minutes=i))
    ref = request_analysis(TENANT, source("ASKED"), store=store, clock=lambda: NOW)
    claimed = store.claim_next(NOW, w.LEASE, download_only=False, max_attempts=3)
    assert claimed is not None and claimed.record.id == ref.id


def test_a_row_still_to_download_goes_before_one_already_downloaded(world) -> None:
    _, store, *_ = world
    enqueue(store, "DONE", at=NOW - timedelta(days=1), pending_video_url=None, source_key="k")
    fresh = enqueue(store, "NEW", at=NOW)
    claimed = store.claim_next(NOW, w.LEASE, download_only=False, max_attempts=3)
    assert claimed is not None and claimed.record.id == fresh.id


def test_a_live_lease_of_another_process_is_left_alone_and_an_expired_one_is_taken(world):
    worker, store, *_ = world
    row = enqueue(store)
    held = store.claim(row.id, NOW, w.LEASE, max_attempts=3)
    assert held is not None and held.record.attempts == 1
    assert w.run_analysis(row.id, worker).outcome == w.OUTCOME_SKIPPED
    assert w.drain_once(worker) is None
    worker.clock.at = NOW + timedelta(minutes=3)  # the other process died
    outcome = w.run_analysis(row.id, worker)
    assert outcome.outcome == w.OUTCOME_DOWNLOADED
    # The download handed the row back without spending its attempt.
    assert store.get(row.id).attempts == 1


def test_the_lease_is_renewed_while_the_row_runs(world) -> None:
    worker, store, *_ = world
    row = enqueue(store)
    claimed = store.claim(row.id, NOW, w.LEASE, max_attempts=3)
    assert claimed is not None
    worker.clock.at = NOW + timedelta(minutes=10)
    with w._Renewer(worker, claimed):  # noqa: SLF001
        import time

        time.sleep(0.2)
    assert store.get(row.id).lease_until == NOW + timedelta(minutes=10) + w.LEASE


# -- the download ---------------------------------------------------------------------------


def test_a_download_stores_a_silent_remux_through_the_public_door(world) -> None:
    worker, store, bucket, cdn, work = world
    body = mp4(3.0, 30, (72, 128), audio=True)
    cdn.respond = lambda _r: httpx.Response(200, content=body)
    row = enqueue(store)
    assert w.drain_once(worker).outcome == w.OUTCOME_DOWNLOADED
    stored = store.get(row.id)
    key = reel_source_key("instagram", "DABC1", row.id)
    assert stored.status == STATUS_QUEUED and stored.source_key == key
    assert stored.pending_video_url is None  # the signed URL is gone once used
    assert stored.source_sha256 == hashlib.sha256(body).hexdigest()
    assert stored.source_purge_after == NOW + timedelta(days=30)
    assert (stored.width, stored.height, stored.fps) == (72, 128, 30.0)
    assert stored.covered_from_s == 0 and 2.9 <= stored.covered_to_s <= 3.05
    assert stored.edit_eligible is True
    data, content_type = bucket.objects[key]
    assert content_type == "video/mp4"
    with av.open(io.BytesIO(data)) as copy:
        assert len(copy.streams.video) == 1 and len(copy.streams.audio) == 0
    assert list(work.iterdir()) == []  # no temp file left behind
    assert len(cdn.calls) == 1


def test_a_long_reel_is_cut_at_60_seconds_and_a_15_fps_one_is_not_edit_eligible(world) -> None:
    worker, store, bucket, cdn, _ = world
    cdn.respond = lambda _r: httpx.Response(200, content=mp4(70.0, 15, (32, 56)))
    row = enqueue(store)
    w.drain_once(worker)
    stored = store.get(row.id)
    assert 69.0 <= stored.source_seconds <= 70.5
    assert 59.0 <= stored.covered_to_s <= 60.0
    assert stored.edit_eligible is False and stored.fps == 15.0
    with av.open(io.BytesIO(bucket.objects[stored.source_key][0])) as copy:
        stream = copy.streams.video[0]
        assert float(stream.duration * stream.time_base) <= 60.1


def test_a_url_older_than_20_hours_fails_without_a_request(world) -> None:
    worker, store, bucket, cdn, work = world
    row = enqueue(store, at=NOW - timedelta(hours=21))
    outcome = w.drain_once(worker)
    assert (outcome.outcome, outcome.error_code) == (w.OUTCOME_FAILED, ERROR_SOURCE_EXPIRED)
    assert store.get(row.id).status == STATUS_FAILED
    assert cdn.calls == [] and bucket.objects == {} and list(work.iterdir()) == []


def test_a_url_past_the_expiry_the_cdn_signed_fails_without_a_request(world) -> None:
    worker, store, _bucket, cdn, _ = world
    expired = IG_URL + "&oe=" + format(int((NOW - timedelta(seconds=1)).timestamp()), "x")
    enqueue(store, url=expired)
    assert w.drain_once(worker).error_code == ERROR_SOURCE_EXPIRED
    assert cdn.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/latest/meta-data/clip.mp4",
        "https://evil.example.com/clip.mp4",
        "https://cdninstagram.com.evil.example/clip.mp4",
        "http://scontent.cdninstagram.com/clip.mp4",
        "https://scontent.cdninstagram.com:8443/clip.mp4",
        "https://v16.tiktokcdn.com/clip.mp4",  # another network's CDN
    ],
)
def test_an_untrusted_url_off_the_cdn_is_never_requested(world, url: str) -> None:
    """0119 lets the screen insert `pending_video_url`: it is input, never followed."""
    worker, store, bucket, cdn, work = world
    enqueue(store, url=url)
    outcome = w.drain_once(worker)
    assert (outcome.outcome, outcome.error_code) == (w.OUTCOME_FAILED, ERROR_SOURCE_UNAVAILABLE)
    assert cdn.calls == [] and bucket.objects == {} and list(work.iterdir()) == []


def test_a_redirect_is_refused_even_to_another_cdn_host(world) -> None:
    worker, store, bucket, cdn, work = world
    cdn.respond = lambda _r: httpx.Response(
        302, headers={"location": "https://scontent-2.cdninstagram.com/x.mp4"}
    )
    enqueue(store)
    outcome = w.drain_once(worker)
    assert (outcome.outcome, outcome.error_code) == (w.OUTCOME_FAILED, ERROR_SOURCE_UNAVAILABLE)
    assert len(cdn.calls) == 1 and bucket.objects == {} and list(work.iterdir()) == []


def test_over_80_mib_is_refused_declared_or_streamed(world) -> None:
    worker, store, bucket, cdn, work = world
    cdn.respond = lambda _r: httpx.Response(
        200, headers={"content-length": str(81 * 1024 * 1024)}, content=b"x"
    )
    enqueue(store, "DECLARED")
    assert w.drain_once(worker).error_code == ERROR_SOURCE_TOO_LARGE

    def endless() -> Iterator[bytes]:
        chunk = b"\0" * (1024 * 1024)
        for _ in range(82):
            yield chunk

    cdn.respond = lambda _r: httpx.Response(200, content=endless())
    enqueue(store, "STREAMED")
    assert w.drain_once(worker).error_code == ERROR_SOURCE_TOO_LARGE
    assert bucket.objects == {} and list(work.iterdir()) == []


def test_a_body_that_is_not_a_video_is_unreadable(world) -> None:
    worker, store, bucket, cdn, work = world
    cdn.respond = lambda _r: httpx.Response(200, content=b"<html>not a video</html>")
    enqueue(store)
    assert w.drain_once(worker).error_code == ERROR_SOURCE_UNREADABLE
    assert bucket.objects == {} and list(work.iterdir()) == []


def test_a_cdn_5xx_retries_with_backoff_then_fails_on_the_third_attempt(world) -> None:
    worker, store, _bucket, cdn, work = world
    cdn.respond = lambda _r: httpx.Response(503)
    row = enqueue(store)
    first = w.drain_once(worker)
    assert first.outcome == w.OUTCOME_RETRY
    waiting = store.get(row.id)
    assert waiting.status == STATUS_QUEUED and waiting.error_code == ERROR_SOURCE_UNAVAILABLE
    assert w.drain_once(worker) is None  # backing off
    for minutes in (2, 5):
        worker.clock.at = NOW + timedelta(minutes=minutes)
        last = w.drain_once(worker)
    assert last.outcome == w.OUTCOME_FAILED and store.get(row.id).attempts == 3
    assert len(cdn.calls) == 3 and list(work.iterdir()) == []


def test_an_r2_failure_retries_without_marking_the_source(world) -> None:
    worker, store, bucket, *_ = world
    bucket.fail_puts = True
    row = enqueue(store)
    assert w.drain_once(worker).outcome == w.OUTCOME_RETRY
    assert store.get(row.id).source_key is None
    assert store.get(row.id).pending_video_url == IG_URL


# -- describe, guard, result ----------------------------------------------------------------


def test_a_full_run_writes_ok_with_shots_provenance_and_cost(world) -> None:
    worker, store, bucket, *_ = world
    worker.describe = FakeDescribe()
    row = enqueue(store)
    outcome = w.drain_once(worker)
    assert outcome.outcome == w.OUTCOME_OK and outcome.cost_usd == Decimal("0.0055")
    done = store.get(row.id)
    assert done.status == STATUS_OK and done.stage == "done" and done.model_calls == 1
    assert (done.model_id, done.model_revision, done.prompt_version) == (
        "claude-haiku-5-5",
        "rev-1",
        "p1",
    )
    assert (done.input_tokens, done.output_tokens, done.cost_usd) == (
        40_000,
        3_000,
        Decimal("0.0055"),
    )
    assert done.lease_token is None and done.finished_at == NOW
    (shot,) = store.shots(TENANT, row.id)
    assert all(k in bucket.objects for k in shot.frame_keys)


def test_a_downloaded_row_is_described_later_from_r2(world) -> None:
    """«Download first, analyse later» (§13.3): the slow stages read the stored source."""
    worker, store, *_ = world
    row = enqueue(store)
    assert w.drain_once(worker).outcome == w.OUTCOME_DOWNLOADED
    worker.describe = FakeDescribe()
    assert w.drain_once(worker).outcome == w.OUTCOME_OK
    assert store.get(row.id).status == STATUS_OK


def test_with_two_model_calls_spent_no_call_is_made(world) -> None:
    worker, store, *_ = world
    fake = FakeDescribe()
    worker.describe = fake
    row = enqueue(store, model_calls=2)
    outcome = w.drain_once(worker)
    assert (outcome.outcome, outcome.error_code) == (w.OUTCOME_FAILED, ERROR_MODEL_FAILED)
    assert fake.calls_made == 0 and store.get(row.id).model_calls == 2


def test_the_fleet_cap_pauses_the_row_before_calling(world) -> None:
    worker, store, *_ = world
    fake = FakeDescribe()
    worker.describe, worker.fleet_cap = fake, 3
    enqueue(store, "SPENT", status=STATUS_FAILED, error_code="model_failed", model_calls=2)
    enqueue(store, "SPENT2", status=STATUS_FAILED, error_code="model_failed", model_calls=1)
    row = enqueue(store)
    outcome = w.drain_once(worker)
    assert outcome.outcome == w.OUTCOME_FLEET_PAUSED and fake.calls_made == 0
    paused = store.get(row.id)
    assert paused.status == STATUS_QUEUED and paused.lease_until == NOW + w.FLEET_PAUSE
    assert paused.model_calls == 0


def test_a_failed_model_call_retries_then_fails_and_writes_no_shot(world) -> None:
    worker, store, *_ = world
    worker.describe = FakeDescribe(raises=w.DescribeFailed("cut answer"))
    row = enqueue(store)
    assert w.drain_once(worker).outcome == w.OUTCOME_RETRY
    worker.clock.at = NOW + timedelta(minutes=2)
    second = w.drain_once(worker)
    assert second.outcome == w.OUTCOME_RETRY  # attempt 2 < 3, but the row cap is now spent
    worker.clock.at = NOW + timedelta(minutes=10)
    third = w.drain_once(worker)
    assert (third.outcome, third.error_code) == (w.OUTCOME_FAILED, ERROR_MODEL_FAILED)
    assert store.get(row.id).model_calls == 2 and store.shots(TENANT, row.id) == []


def test_a_result_after_the_lease_was_taken_writes_nothing(world) -> None:
    worker, store, *_ = world
    row = enqueue(store)

    def steal() -> None:
        current = store.get(row.id)
        store.put(replace(current, lease_token=uuid4()))

    worker.describe = FakeDescribe(before_complete=steal)
    assert w.drain_once(worker).outcome == w.OUTCOME_LOST
    assert store.get(row.id).status == STATUS_RUNNING
    assert store.shots(TENANT, row.id) == []


def test_rows_out_of_attempts_are_closed(world) -> None:
    worker, store, *_ = world
    stuck = enqueue(
        store,
        status=STATUS_RUNNING,
        attempts=3,
        lease_token=uuid4(),
        lease_until=NOW - timedelta(minutes=1),
    )
    assert w.drain_once(worker) is None
    closed = store.get(stuck.id)
    assert (closed.status, closed.error_code) == (STATUS_FAILED, ERROR_SOURCE_UNAVAILABLE)


# -- R4's analyze_run_ideas -----------------------------------------------------------------


def test_a_run_analyses_at_most_ten_new_ideas_and_reuse_does_not_count(world) -> None:
    worker, store, *_ = world
    worker.describe = FakeDescribe()
    reused = enqueue(store, "OLD")
    w.drain_once(worker)
    assert store.get(reused.id).status == STATUS_OK
    ideas = [source("OLD")] + [source(f"N{i}") for i in range(11)]
    cost = w.analyze_run_ideas(TENANT, BRAND, RUN, ideas, worker=worker, limit=10)
    assert cost == Decimal("0.0055") * 10
    keys = {r.post_id: r.status for r in store.rows()}
    assert "N10" not in keys  # the 11th new idea is not analysed (nor queued)
    assert sum(1 for p, s in keys.items() if p.startswith("N") and s == STATUS_OK) == 10


def test_a_run_downloads_at_once_without_describe_and_returns_no_cost(world) -> None:
    worker, store, bucket, *_ = world
    cost = w.analyze_run_ideas(TENANT, BRAND, RUN, [source("A"), source("B")], worker=worker)
    assert cost == Decimal("0")
    assert all(r.source_key and r.status == STATUS_QUEUED for r in store.rows())
    assert len(bucket.objects) == 2


def test_a_run_requeues_an_idea_whose_url_had_expired(world) -> None:
    worker, store, *_ = world
    old = enqueue(store, "EXP", at=NOW - timedelta(days=7))
    w.drain_once(worker)
    assert store.get(old.id).error_code == ERROR_SOURCE_EXPIRED
    fresh_url = IG_URL + "&fresh=1"
    w.analyze_run_ideas(TENANT, BRAND, RUN, [source("EXP", fresh_url)], worker=worker)
    again = store.get(old.id)
    assert again.status == STATUS_QUEUED and again.source_key is not None


def test_a_run_gives_a_screen_row_the_url_it_just_read(world) -> None:
    worker, store, _bucket, cdn, _ = world
    stale = IG_URL + "&old=1"
    request_analysis(TENANT, source("S", stale), store=store, clock=lambda: NOW)
    w.analyze_run_ideas(TENANT, BRAND, RUN, [source("S", IG_URL + "&new=1")], worker=worker)
    assert cdn.calls == [IG_URL + "&new=1"]


def test_r4_run_accepts_analyze_run_ideas_as_its_idea_analyzer(world) -> None:
    worker, store, *_ = world
    analyzer: reel_runs.IdeaAnalyzer = lambda t, b, r, s: w.analyze_run_ideas(  # noqa: E731
        t, b, r, s, worker=worker
    )
    ideas = [reel_runs.IdeaSource("instagram", "R4", "https://www.instagram.com/reel/R4/", IG_URL)]
    assert analyzer(TENANT, BRAND, RUN, ideas) == Decimal("0")
    (row,) = store.rows()
    assert row.post_id == "R4" and row.source_key is not None


def test_one_broken_idea_never_stops_the_others(world, monkeypatch) -> None:
    worker, store, *_ = world
    original = store.ensure

    def flaky(src: ReelSource, version: int, now: datetime) -> tuple[AnalysisRecord, bool]:
        if src.post_id == "BAD":
            raise RuntimeError("boom")
        return original(src, version, now)

    monkeypatch.setattr(store, "ensure", flaky)
    w.analyze_run_ideas(TENANT, BRAND, RUN, [source("BAD"), source("GOOD")], worker=worker)
    assert [r.post_id for r in store.rows()] == ["GOOD"]


# -- CLI ------------------------------------------------------------------------------------


def test_the_tick_drains_and_exits(world) -> None:
    worker, store, *_ = world
    enqueue(store, "C1")
    enqueue(store, "C2")
    assert w.main(["--once", "--max", "5"], worker=worker) == 0
    assert all(r.source_key for r in store.rows())


def test_a_bare_worker_has_no_describe_step() -> None:
    """Only `default_worker` plugs VE-04c's Haiku step in (with the key): a bare `Worker`
    never writes an `ok`."""
    assert w.DEFAULT_DESCRIBE is None


def test_concurrency_reads_its_env() -> None:
    assert w.concurrency({}) == 1
    assert w.concurrency({"QUALIFY_REEL_ANALYSIS_CONCURRENCY": "9"}) == 2
    assert w.per_run_limit({}) == 10
    assert w.per_run_limit({"QUALIFY_REEL_ANALYSIS_PER_RUN": "3"}) == 3


def _ids(store: InMemoryAnalysisStore) -> set[UUID]:
    return {r.id for r in store.rows()}


# -- review fixes (lease before R2 writes, post id shape) ------------------------------------


def test_a_lease_lost_during_the_download_stores_nothing_in_r2(world) -> None:
    worker, store, bucket, cdn, work = world
    row = enqueue(store)

    def steal_then_serve(_r: httpx.Request) -> httpx.Response:
        store.put(replace(store.get(row.id), lease_token=uuid4()))  # another process took it
        return httpx.Response(200, content=CLIP)

    cdn.respond = steal_then_serve
    assert w.drain_once(worker).outcome == w.OUTCOME_LOST
    assert bucket.objects == {} and list(work.iterdir()) == []
    assert store.get(row.id).source_key is None


def test_a_lease_lost_before_a_frame_writes_no_frame(world) -> None:
    worker, store, bucket, *_ = world
    row = enqueue(store)
    assert w.drain_once(worker).outcome == w.OUTCOME_DOWNLOADED

    class Steal(FakeDescribe):
        def __call__(self, job: w.DescribeInput) -> DescribeResult:
            store.put(replace(store.get(row.id), lease_token=uuid4()))
            return super().__call__(job)

    worker.describe = Steal()
    source_only = dict(bucket.objects)
    assert w.drain_once(worker).outcome == w.OUTCOME_LOST
    assert bucket.objects == source_only  # no frame written
    assert store.shots(TENANT, row.id) == []


@pytest.mark.parametrize("bad", ["../x", "a/b", "a.b", "a b", "x" * 65])
def test_a_malformed_post_id_is_never_enqueued_nor_downloaded(world, bad: str) -> None:
    worker, store, _bucket, cdn, _ = world
    with pytest.raises(ValueError):
        store.ensure(source(bad), ANALYSIS_VERSION, NOW)
    with pytest.raises(ValueError):
        request_analysis(TENANT, source(bad), store=store, clock=lambda: NOW)
    assert w.analyze_run_ideas(TENANT, BRAND, RUN, [source(bad)], worker=worker) == 0
    assert store.rows() == [] and cdn.calls == []


# -- VE-12: no object in R2 without a purge date (R8 re-review, N2) ----------------------


def test_the_purge_date_is_on_the_row_before_the_upload_and_outlives_a_lost_record(
    world,
) -> None:
    """The process that uploaded loses its lease before `record_source`: the object is in
    R2 and no row names it — but the row already had its date, so the 30-day purge (which
    derives the folders from the row, never from `source_key`) deletes it all the same."""
    from qualify_api.referentes import reel_retention

    worker, store, bucket, _cdn, _ = world
    record = enqueue(store)
    dates_at_put: list[datetime | None] = []
    real_put = bucket.put

    def put(key: str, fileobj: IO[bytes], content_type: str) -> None:
        dates_at_put.append(store.get(record.id).source_purge_after)
        real_put(key, fileobj, content_type)

    bucket.put = put  # type: ignore[method-assign]
    store.record_source = lambda *_a, **_k: False  # type: ignore[method-assign]

    assert w.drain_once(worker).outcome == w.OUTCOME_LOST
    due = NOW + w.SOURCE_RETENTION
    assert dates_at_put == [due]  # written BEFORE the PUT
    key = reel_source_key(record.network, record.post_id, record.id)
    row = store.get(record.id)
    assert key in bucket.objects and row.source_key is None and row.source_purge_after == due

    early = reel_retention.purge_reel_sources(
        worker.gate, due - timedelta(days=1), True, store=store
    )
    assert early.due == 0 and key in bucket.objects
    report = reel_retention.purge_reel_sources(worker.gate, due, True, store=store)
    assert (report.due, report.purged) == (1, 1) and bucket.objects == {}
    assert store.get(record.id).source_purged_at == due


def test_a_lease_lost_before_the_purge_date_uploads_nothing(world) -> None:
    worker, store, bucket, *_ = world
    record = enqueue(store)
    store.set_purge_date = lambda *_a, **_k: False  # type: ignore[method-assign]
    assert w.drain_once(worker).outcome == w.OUTCOME_LOST
    assert bucket.objects == {} and store.get(record.id).source_purge_after is None
