"""m-25042483 («Bajarlos a 4K 8 bits»): the local assembly only ever decodes a source of
at most 3840×2160 at 8 bits. A bigger or 10-bit video stretch waits — silently, at cost 0
— for its normalized copy from the media-worker (`normalize_local`), and is then read as
that copy, its provenance recorded per stretch. Offline: PyAV-encoded tiny sources, a dict
store, the jobs door in memory, and a header double that says which file is «5K 10-bit»."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.schemas import SourceSegment
from qualify_creative.video import prepare
from qualify_creative.video.local_normalize import NORMALIZE_LOCAL_VERSION
from qualify_creative.video.source_limits import SourceHeader, read_header

from qualify_api.creative import heavy_video
from qualify_api.creative.queue_dispatch import CheckpointError
from qualify_api.creative.video_pipeline import local, local_sources
from qualify_api.creative.video_pipeline.local_sources import (
    InMemoryLocalSourceJobs,
    LocalSourceNormalizing,
    NormalizeJob,
    normalize_job_key,
    normalized_key,
)
from qualify_api.creative.worker import pipeline as worker_pipeline
from qualify_api.creative.worker.pipeline import PipelinePreparation

from . import test_video_pipeline_local as base
from .test_creative_heavy_video import LeaseStore, _Rows
from .test_creative_media import BUDGET, COPY, _kit
from .test_video_pipeline_local import (
    PHOTO_KEY,
    TENANT_ID,
    VIDEO_KEY,
    ExplodingByteplus,
    ReadingStore,
    _local_clip,
    _photo,
    _producer,
    _stamped,
    _video_bytes,
)

# the EF-06 module's fixtures, used here by name (the two autouse ones apply here too)
assemble_at_the_sources_size = base.assemble_at_the_sources_size
no_normalize_jobs = base.no_normalize_jobs
queue_on = base.queue_on
sources = base.sources

BIG_KEY = f"t/{TENANT_ID}/uploads/{uuid4()}/iphone-5k.mov"
OTHER_BIG_KEY = f"t/{TENANT_ID}/uploads/{uuid4()}/otro-5k.mov"
GALLERY_KEY = f"gallery/{TENANT_ID}/{uuid4()}/video.mp4"
FIVE_K_10_BIT = SourceHeader(width=5120, height=2880, pix_fmt="yuv420p10le")


@pytest.fixture(scope="module")
def big_bytes() -> bytes:
    """A real tiny video the header double calls «5K 10-bit» (its bytes tell it apart)."""
    return _video_bytes(4.0, colour=(20, 40, 200))


@pytest.fixture
def headers(monkeypatch: pytest.MonkeyPatch, big_bytes: bytes) -> list[Path]:
    """The header reader: «5K 10-bit» for `big_bytes`, the real header otherwise. Records
    every file whose header was read."""
    seen: list[Path] = []

    def header(path: Path) -> SourceHeader:
        seen.append(path)
        if path.read_bytes() == big_bytes:
            return FIVE_K_10_BIT
        return read_header(path)

    monkeypatch.setattr(local_sources, "_read_header", header)
    return seen


@pytest.fixture
def no_decode(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`prepare` records what it decodes (and still decodes it)."""
    decoded: list[str] = []
    real = prepare.read_source

    def spy(source: Any) -> Any:
        decoded.append(str(source))
        return real(source)

    monkeypatch.setattr(prepare, "read_source", spy)
    return decoded


def _clip(*segments: SourceSegment) -> Any:
    return _stamped(_local_clip(*segments))


def _big(key: str = BIG_KEY) -> SourceSegment:
    return SourceSegment(key=key, start_s=0.0, end_s=4.0, speed=2.0)


def _produce(store: ReadingStore, brief: Any) -> Any:
    return _producer(store, ExplodingByteplus()).produce(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit(), copy=COPY, budget=BUDGET
    )


def test_a_5k_10_bit_stretch_waits_for_one_job_and_nothing_is_decoded(
    queue_on: None,
    sources: dict[str, bytes],
    big_bytes: bytes,
    headers: list[Path],
    no_decode: list[str],
    no_normalize_jobs: InMemoryLocalSourceJobs,
) -> None:
    store = ReadingStore({**sources, BIG_KEY: big_bytes})
    brief = _clip(_big(), _photo())
    with pytest.raises(LocalSourceNormalizing) as waited:
        _produce(store, brief)
    assert isinstance(waited.value, CheckpointError)  # the worker retries it, never fails
    assert no_normalize_jobs.enqueued == [BIG_KEY]
    assert store.reads == [BIG_KEY]  # its header only: the photo was never read
    assert no_decode == []  # not one frame of it decoded
    # the next pass: the job is queued → waits again, nothing downloaded, no second job
    with pytest.raises(LocalSourceNormalizing):
        _produce(store, brief)
    assert no_normalize_jobs.enqueued == [BIG_KEY] and store.reads == [BIG_KEY]
    assert no_decode == []


def test_every_file_the_part_needs_is_asked_for_in_the_same_pass(
    queue_on: None,
    sources: dict[str, bytes],
    big_bytes: bytes,
    headers: list[Path],
    no_normalize_jobs: InMemoryLocalSourceJobs,
) -> None:
    store = ReadingStore({**sources, BIG_KEY: big_bytes, OTHER_BIG_KEY: big_bytes})
    # the same big file twice and another one: one job each
    brief = _clip(_big(), _big(), _big(OTHER_BIG_KEY))
    with pytest.raises(LocalSourceNormalizing):
        _produce(store, brief)
    assert no_normalize_jobs.enqueued == [BIG_KEY, OTHER_BIG_KEY]


def test_a_normalized_copy_is_what_the_assembly_reads_and_records(
    queue_on: None,
    sources: dict[str, bytes],
    headers: list[Path],
    no_decode: list[str],
    no_normalize_jobs: InMemoryLocalSourceJobs,
) -> None:
    copy_key = normalized_key(TENANT_ID, BIG_KEY)
    no_normalize_jobs.jobs[BIG_KEY] = NormalizeJob(
        status="done", normalized_key=copy_key, version=NORMALIZE_LOCAL_VERSION
    )
    # the original is not even in the store: only the copy can be read
    store = ReadingStore({**sources, copy_key: sources[VIDEO_KEY]})
    outcome = _produce(store, _clip(_big(), _photo()))
    assert outcome.failure is None, outcome.detail
    assert BIG_KEY not in store.reads and copy_key in store.reads
    assert headers == []  # a copy is not checked again
    assert len(no_decode) == 1
    (write,) = outcome.media
    (video, photo) = write.params["local"]["segments"]
    assert video["key"] == BIG_KEY  # the recipe as the owner made it
    assert video["source"] == {
        "source_key": BIG_KEY,
        "normalized_key": copy_key,
        "normalizer_version": "local-source-v3",
        "limits_version": "local-source-limits-v1",
    }
    assert "source" not in photo
    assert [u.cost_usd for u in outcome.usage] == [0]  # cost 0, as every local video
    assert no_normalize_jobs.enqueued == []


def test_a_failed_normalization_fails_the_piece_without_charging(
    queue_on: None,
    sources: dict[str, bytes],
    big_bytes: bytes,
    headers: list[Path],
    no_normalize_jobs: InMemoryLocalSourceJobs,
) -> None:
    no_normalize_jobs.jobs[BIG_KEY] = NormalizeJob(
        status="failed",
        normalized_key=normalized_key(TENANT_ID, BIG_KEY),
        version=NORMALIZE_LOCAL_VERSION,
        error_code="unreadable",
    )
    store = ReadingStore({**sources, BIG_KEY: big_bytes})
    outcome = _produce(store, _clip(_big(), _photo()))
    assert outcome.failure is not None and outcome.media == ()
    assert outcome.detail == local.LOCAL_SOURCE_FAILED_TEXT
    assert outcome.usage == ()
    assert store.reads == [] and no_normalize_jobs.enqueued == []


def test_a_4k_8_bit_source_is_read_as_it_is_with_its_check_recorded(
    queue_on: None,
    sources: dict[str, bytes],
    headers: list[Path],
    no_normalize_jobs: InMemoryLocalSourceJobs,
) -> None:
    outcome = _produce(ReadingStore(sources), _clip())
    assert outcome.failure is None, outcome.detail
    assert no_normalize_jobs.enqueued == [] and len(headers) == 1
    video = outcome.media[0].params["local"]["segments"][0]
    assert video["source"]["normalized_key"] is None
    assert video["source"]["header"]["bits"] == 8


def test_a_galeria_video_is_neither_looked_up_nor_checked(
    queue_on: None,
    sources: dict[str, bytes],
    headers: list[Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looked: list[Any] = []

    class Spy(InMemoryLocalSourceJobs):
        def lookup(self, tenant_id: Any, source_keys: Any) -> Any:
            looked.append(list(source_keys))
            return super().lookup(tenant_id, source_keys)

    monkeypatch.setattr(local_sources, "default_jobs", Spy)
    store = ReadingStore({**sources, GALLERY_KEY: sources[VIDEO_KEY]})
    gallery = SourceSegment(key=GALLERY_KEY, start_s=0.0, end_s=4.0, speed=2.0)
    outcome = _produce(store, _clip(gallery, _photo()))
    assert outcome.failure is None, outcome.detail
    assert looked == [] and headers == []
    assert "source" not in outcome.media[0].params["local"]["segments"][0]


def test_the_job_key_and_the_copy_key_are_per_file_and_version() -> None:
    assert normalize_job_key(BIG_KEY) == f"normalize_local:local-source-v3:{BIG_KEY}"
    first = normalized_key(TENANT_ID, BIG_KEY)
    assert first == normalized_key(TENANT_ID, BIG_KEY)  # deterministic
    assert first.startswith(f"t/{TENANT_ID}/normalized/") and first.endswith("/video.mp4")
    assert first != normalized_key(TENANT_ID, OTHER_BIG_KEY)
    assert first != normalized_key(
        TENANT_ID, BIG_KEY, version="local-source-v1"
    )  # v1 copies were silent: never reused
    assert first != normalized_key(
        TENANT_ID, BIG_KEY, version="local-source-v2"
    )  # m-25071265: v2 copies (no B-frames) are another encode: a new copy
    assert local.owned_by(TENANT_ID, first)


def test_a_waiting_source_releases_the_run_not_done_and_logs_no_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    draft_id = uuid4()
    run = SimpleNamespace(
        draft_id=draft_id, tenant_id=TENANT_ID, revision=1, phase="generation", step=0, video=0
    )

    @contextmanager
    def session(_tenant: Any) -> Any:
        yield SimpleNamespace(
            execute=lambda *_a, **_k: _Rows(
                [{"draft_id": draft_id, "revision": 1, "phase": "generation"}]
            )
        )

    monkeypatch.setattr(worker_pipeline, "tenant_session", session)

    def run_generation(**_kwargs: Any) -> None:
        raise LocalSourceNormalizing("a source is being normalized")

    service = SimpleNamespace(
        _repo=SimpleNamespace(get_draft=lambda **_k: SimpleNamespace(revision=1)),
        run_generation=run_generation,
    )
    store = LeaseStore(run)
    preparation = PipelinePreparation(service, store, [TENANT_ID])  # type: ignore[arg-type]
    with caplog.at_level(logging.INFO, logger=worker_pipeline.logger.name):
        preparation()
    assert store.releases == [False]  # still dirty: a later pass makes it
    assert "reason=LocalSourceNormalizing" in caplog.text
    assert "preparation_failed" not in caplog.text


def test_a_photo_only_part_needs_no_job_door(
    queue_on: None, sources: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_door() -> Any:
        raise AssertionError("no video stretch: nothing to look up")

    monkeypatch.setattr(local_sources, "default_jobs", no_door)
    store = ReadingStore(sources)
    photo = SourceSegment(key=PHOTO_KEY, start_s=0.0, end_s=3.0, kind="photo")
    outcome = _produce(store, _clip(photo))
    assert outcome.failure is None, outcome.detail


# ---------------------------------------------------------------------------
# review of m-25042483: a failure of the machine is retried (capped), a wait has a
# deadline, and a waiting piece is held out of the worker's passes for a minute


def _failed(code: str) -> NormalizeJob:
    return NormalizeJob(
        status="failed",
        normalized_key=normalized_key(TENANT_ID, BIG_KEY),
        version=NORMALIZE_LOCAL_VERSION,
        error_code=code,
    )


@pytest.mark.parametrize(
    "code", ["unreadable", "source_missing", "normalized_over_limit", "normalized_too_large"]
)
def test_a_failure_of_the_file_fails_the_piece_at_once(
    queue_on: None,
    sources: dict[str, bytes],
    big_bytes: bytes,
    no_normalize_jobs: InMemoryLocalSourceJobs,
    code: str,
) -> None:
    no_normalize_jobs.jobs[BIG_KEY] = _failed(code)
    store = ReadingStore({**sources, BIG_KEY: big_bytes})
    outcome = _produce(store, _clip(_big(), _photo()))
    assert outcome.detail == local.LOCAL_SOURCE_FAILED_TEXT and outcome.usage == ()
    assert store.reads == []
    assert no_normalize_jobs.enqueued == []


@pytest.mark.parametrize("code", ["attempts_exhausted", "normalize:TranscodeInterrupted"])
def test_a_failure_of_the_machine_queues_a_new_job_twice_then_fails(
    queue_on: None,
    sources: dict[str, bytes],
    big_bytes: bytes,
    no_normalize_jobs: InMemoryLocalSourceJobs,
    code: str,
) -> None:
    store = ReadingStore({**sources, BIG_KEY: big_bytes})
    brief = _clip(_big(), _photo())
    no_normalize_jobs.jobs[BIG_KEY] = _failed(code)
    with pytest.raises(LocalSourceNormalizing):  # 1st failed job: a new one, the piece waits
        _produce(store, brief)
    assert no_normalize_jobs.enqueued == [BIG_KEY] and store.reads == []
    no_normalize_jobs.jobs[BIG_KEY] = _failed(code)  # the new one failed too
    outcome = _produce(store, brief)  # 2 failed jobs of the machine: the cap
    assert outcome.detail == local.LOCAL_SOURCE_FAILED_TEXT and outcome.usage == ()
    assert no_normalize_jobs.enqueued == [BIG_KEY]


def test_a_wait_past_its_deadline_fails_the_piece_with_a_warning(
    queue_on: None,
    sources: dict[str, bytes],
    big_bytes: bytes,
    no_normalize_jobs: InMemoryLocalSourceJobs,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from datetime import UTC, datetime

    assert local_sources.MAX_NORMALIZE_WAIT == timedelta(hours=11, minutes=15)
    store = ReadingStore({**sources, BIG_KEY: big_bytes})
    brief = _clip(_big(), _photo())
    queued = NormalizeJob(
        status="running",
        normalized_key=normalized_key(TENANT_ID, BIG_KEY),
        version=NORMALIZE_LOCAL_VERSION,
        created_at=datetime.now(UTC) - timedelta(hours=11, minutes=14),
    )
    no_normalize_jobs.jobs[BIG_KEY] = queued
    with pytest.raises(LocalSourceNormalizing):  # inside the deadline: it waits
        _produce(store, brief)
    no_normalize_jobs.jobs[BIG_KEY] = replace(
        queued, created_at=datetime.now(UTC) - timedelta(hours=11, minutes=16)
    )
    with caplog.at_level(logging.WARNING, logger=local_sources.logger.name):
        outcome = _produce(store, brief)
    assert outcome.detail == local.LOCAL_SOURCE_FAILED_TEXT and outcome.usage == ()
    assert "normalize_timeout" in caplog.text and store.reads == []


def test_a_held_draft_is_left_out_of_the_passes_for_a_minute() -> None:
    now = {"t": 1000.0}
    draft = uuid4()
    heavy_video.hold(draft, LocalSourceNormalizing.retry_after_s, clock=lambda: now["t"])
    assert draft in heavy_video.held(clock=lambda: now["t"] + 59)
    assert draft not in heavy_video.held(clock=lambda: now["t"] + 60)
    heavy_video.hold(uuid4(), 0)  # a join wait (`LocalAssemblyWait`) is not held
    assert heavy_video.LocalAssemblyWait.retry_after_s == 0
    heavy_video.release_held()


def test_the_worker_holds_a_waiting_draft_and_leaves_it_out_of_the_next_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heavy_video.release_held()
    draft_id = uuid4()
    run = SimpleNamespace(
        draft_id=draft_id, tenant_id=TENANT_ID, revision=1, phase="generation", step=0, video=0
    )
    queries: list[dict[str, Any]] = []

    @contextmanager
    def session(_tenant: Any) -> Any:
        def execute(_statement: Any, params: dict[str, Any] | None = None) -> Any:
            queries.append(dict(params or {}))
            return _Rows([{"draft_id": draft_id, "revision": 1, "phase": "generation"}])

        yield SimpleNamespace(execute=execute)

    monkeypatch.setattr(worker_pipeline, "tenant_session", session)
    calls: list[int] = []

    def run_generation(**_kwargs: Any) -> None:
        calls.append(1)
        raise LocalSourceNormalizing("a source is being normalized")

    service = SimpleNamespace(
        _repo=SimpleNamespace(get_draft=lambda **_k: SimpleNamespace(revision=1)),
        run_generation=run_generation,
    )
    preparation = PipelinePreparation(service, LeaseStore(run), [TENANT_ID])  # type: ignore[arg-type]
    preparation()
    preparation()
    assert queries[0]["waiting"] == [] and queries[1]["waiting"] == [str(draft_id)]
    heavy_video.release_held()
