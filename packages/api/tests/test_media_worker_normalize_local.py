"""m-25042483: `media-worker`'s `normalize_local` job, offline — a local-video source
brought to 4K 8 bits at its deterministic key, once; failures settle like the other kinds.
The DB door is a double of `tenant_session` holding the job row; FFmpeg and the header
reader are doubles too (the real command is pinned in `packages/creative`)."""

from __future__ import annotations

import io
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.video import source_limits
from qualify_creative.video.business import TranscodeInterrupted, UnreadableVideo
from qualify_creative.video.local_normalize import NORMALIZE_LOCAL_VERSION
from qualify_creative.video.source_limits import SourceHeader
from qualify_shared.objects.gate import ObjectNotFound, ObjectSizeExceeded

from qualify_api.catalog import media_worker
from qualify_api.catalog.business_media_models import (
    JOB_NORMALIZE_LOCAL,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
)
from qualify_api.catalog.media_worker import ClaimedJob, MediaJobRunner
from qualify_api.creative.video_pipeline.local_sources import normalized_key

TENANT = UUID("a0000000-0000-4000-8000-0000000c4c01")
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
SOURCE_KEY = f"t/{TENANT}/uploads/{uuid4()}/iphone.mov"
TARGET_KEY = normalized_key(TENANT, SOURCE_KEY)
BIG = SourceHeader(width=5120, height=2880, pix_fmt="yuv420p10le", duration_s=42.0)
FOUR_K = SourceHeader(width=3840, height=2160, pix_fmt="yuv420p", duration_s=42.0)


class Gate:
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = dict(files or {})
        self.puts: list[str] = []
        self.fail_put: Exception | None = None

    def has_object(self, tenant_id: UUID, key: str) -> bool:
        assert key.startswith(f"t/{tenant_id}/")
        return key in self.files

    def open_object(self, tenant_id: UUID, key: str) -> Any:
        if key not in self.files:
            raise ObjectNotFound(key)
        return io.BytesIO(self.files[key])

    def put_media(self, tenant_id: UUID, key: str, fileobj: Any, content_type: str) -> None:
        if self.fail_put is not None:
            raise self.fail_put
        assert content_type == "video/mp4"
        self.puts.append(key)
        self.files[key] = fileobj.read()


class Normalizer:
    version = NORMALIZE_LOCAL_VERSION

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[float | None] = []

    def allowance(self, duration_s: float | None) -> timedelta:
        return timedelta(minutes=40)

    def normalize_file(self, source: Path, out: Path, *, duration_s: float | None) -> None:
        self.calls.append(duration_s)
        if self.error is not None:
            raise self.error
        out.write_bytes(b"normalized:" + source.read_bytes())


@pytest.fixture
def row() -> SimpleNamespace:
    return SimpleNamespace(
        status=STATUS_RUNNING,
        attempts=1,
        lease_until=None,
        updated_at=None,
        finished_at=None,
        last_error_code=None,
        result={},
    )


@pytest.fixture(autouse=True)
def db(monkeypatch: pytest.MonkeyPatch, row: SimpleNamespace) -> None:
    @contextmanager
    def session(_tenant: Any) -> Any:
        yield SimpleNamespace(get=lambda *_a, **_k: row)

    monkeypatch.setattr(media_worker, "tenant_session", session)


@pytest.fixture(autouse=True)
def headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """The source reads as 5K 10-bit; the normalizer's output as 4K 8-bit."""

    def header(path: Path) -> SourceHeader:
        return FOUR_K if path.read_bytes().startswith(b"normalized:") else BIG

    monkeypatch.setattr(source_limits, "read_header", header)


def _runner(gate: Gate, normalizer: Normalizer | None, root: Path) -> MediaJobRunner:
    return MediaJobRunner(
        gate=gate,  # type: ignore[arg-type]
        staging_root=root,
        normalizer=None,  # type: ignore[arg-type]
        local_normalizer=normalizer,
        clock=lambda: NOW,
    )


def _job(source_key: str = SOURCE_KEY, target_key: str = TARGET_KEY) -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(),
        tenant_id=TENANT,
        brand_id=uuid4(),
        kind=JOB_NORMALIZE_LOCAL,
        staged_path=None,
        filename="",
        upload_sha256=None,
        attempts=1,
        payload={
            "source_key": source_key,
            "normalized_key": target_key,
            "version": NORMALIZE_LOCAL_VERSION,
        },
    )


def test_a_source_is_normalized_to_its_key_and_the_job_is_done(
    tmp_path: Path, row: SimpleNamespace
) -> None:
    gate, normalizer = Gate({SOURCE_KEY: b"5k"}), Normalizer()
    outcome = _runner(gate, normalizer, tmp_path).process(_job())
    assert outcome.status == STATUS_DONE
    assert gate.puts == [TARGET_KEY] and gate.files[TARGET_KEY] == b"normalized:5k"
    assert normalizer.calls == [42.0]  # the length from the header scales time and rate
    assert row.status == STATUS_DONE and row.lease_until is None
    assert row.result["normalized_key"] == TARGET_KEY
    assert row.result["version"] == "local-source-v3"
    assert row.result["source_key"] == SOURCE_KEY and row.result["cost_usd"] == "0.00"
    assert row.result["source"]["bits"] == 10 and row.result["normalized"]["bits"] == 8


def test_the_lease_is_held_for_the_encodes_whole_allowance(
    tmp_path: Path, row: SimpleNamespace
) -> None:
    leases: list[Any] = []

    class Watching(Normalizer):
        def normalize_file(self, source: Path, out: Path, *, duration_s: float | None) -> None:
            leases.append(row.lease_until)
            super().normalize_file(source, out, duration_s=duration_s)

    _runner(Gate({SOURCE_KEY: b"5k"}), Watching(), tmp_path).process(_job())
    assert leases == [NOW + timedelta(minutes=40)]


def test_a_copy_already_kept_is_never_encoded_again(tmp_path: Path, row: SimpleNamespace) -> None:
    gate, normalizer = Gate({SOURCE_KEY: b"5k", TARGET_KEY: b"made before"}), Normalizer()
    outcome = _runner(gate, normalizer, tmp_path).process(_job())
    assert outcome.status == STATUS_DONE and row.result["reused"] is True
    assert normalizer.calls == [] and gate.puts == []
    assert gate.files[TARGET_KEY] == b"made before"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (UnreadableVideo("bad"), STATUS_FAILED, "unreadable"),
        (TranscodeInterrupted("killed"), STATUS_QUEUED, "normalize:TranscodeInterrupted"),
        (MemoryError(), STATUS_QUEUED, "normalize:MemoryError"),
    ],
)
def test_an_unreadable_file_fails_for_good_and_a_killed_encode_retries(
    tmp_path: Path, row: SimpleNamespace, error: Exception, status: str, code: str
) -> None:
    gate = Gate({SOURCE_KEY: b"5k"})
    _runner(gate, Normalizer(error), tmp_path).process(_job())
    assert row.status == status and row.last_error_code == code
    assert gate.puts == []


def test_a_missing_source_fails_for_good(tmp_path: Path, row: SimpleNamespace) -> None:
    outcome = _runner(Gate(), Normalizer(), tmp_path).process(_job())
    assert outcome.status == STATUS_FAILED and row.last_error_code == "source_missing"


def test_a_copy_still_over_the_limit_is_never_kept(
    tmp_path: Path, row: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(source_limits, "read_header", lambda _path: BIG)
    gate = Gate({SOURCE_KEY: b"5k"})
    _runner(gate, Normalizer(), tmp_path).process(_job())
    assert row.status == STATUS_FAILED and row.last_error_code == "normalized_over_limit"
    assert gate.puts == []


def test_a_copy_too_large_to_store_fails_and_an_r2_hiccup_retries(
    tmp_path: Path, row: SimpleNamespace
) -> None:
    gate = Gate({SOURCE_KEY: b"5k"})
    gate.fail_put = ObjectSizeExceeded("too big")
    _runner(gate, Normalizer(), tmp_path).process(_job())
    assert row.status == STATUS_FAILED and row.last_error_code == "normalized_too_large"
    row.status, row.attempts = STATUS_RUNNING, 1
    gate.fail_put = ConnectionError("reset")
    _runner(gate, Normalizer(), tmp_path).process(_job())
    assert row.status == STATUS_QUEUED and row.last_error_code == "r2_write:ConnectionError"


@pytest.mark.parametrize(
    ("source_key", "target_key"),
    [
        (f"t/{uuid4()}/uploads/x/otro.mov", TARGET_KEY),  # another tenant's file
        (SOURCE_KEY, f"t/{uuid4()}/normalized/x/video.mp4"),  # a copy for another tenant
        (SOURCE_KEY, f"t/{TENANT}/generated/x/video.mp4"),  # outside the copies' folder
    ],
)
def test_a_payload_outside_the_tenant_is_refused(
    tmp_path: Path, row: SimpleNamespace, source_key: str, target_key: str
) -> None:
    gate = Gate({source_key: b"5k"})
    _runner(gate, Normalizer(), tmp_path).process(_job(source_key, target_key))
    assert row.status == STATUS_FAILED and row.last_error_code == "payload_invalid"
    assert gate.puts == []


def test_an_old_local_upload_is_read_from_the_volume(
    tmp_path: Path, row: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_api.creative import owner_uploads

    monkeypatch.setattr(owner_uploads, "resolve_moved_key", lambda _t, _k: None)
    key = f"uploads/{TENANT}/viejo.mov"
    (tmp_path / "uploads" / str(TENANT)).mkdir(parents=True)
    (tmp_path / key).write_bytes(b"old")
    gate = Gate()
    target = normalized_key(TENANT, key)
    _runner(gate, Normalizer(), tmp_path).process(_job(key, target))
    assert row.status == STATUS_DONE and gate.files[target] == b"normalized:old"


def test_only_a_runner_with_its_normalizer_claims_the_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A runner built without `local_normalizer` leaves `normalize_local` jobs queued."""
    from sqlalchemy.dialects import postgresql

    claimed: list[str] = []

    @contextmanager
    def session(_tenant: Any) -> Any:
        def scalar(statement: Any) -> None:
            claimed.append(
                str(
                    statement.compile(
                        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                    )
                )
            )

        yield SimpleNamespace(scalar=scalar)

    monkeypatch.setattr(media_worker, "tenant_session", session)
    for normalizer in (None, Normalizer()):
        runner = MediaJobRunner(
            gate=Gate(),  # type: ignore[arg-type]
            staging_root=Path("."),
            normalizer=None,  # type: ignore[arg-type]
            local_normalizer=normalizer,
            clock=lambda: NOW,
        )
        assert runner.claim(TENANT) is None
    where = [sql.split("ORDER BY")[0] for sql in claimed]
    assert "normalize_local" not in where[0] and "normalize_local" in where[1]


def test_a_normalize_is_claimed_after_the_galerias_own_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review of m-25042483: `ingest`/`cut` first (0), then `normalize_local` (1), then a
    recent `seasonal_media` (2) — a long normalize never delays an owner's upload."""
    from sqlalchemy.dialects import postgresql

    claimed: list[str] = []

    @contextmanager
    def session(_tenant: Any) -> Any:
        def scalar(statement: Any) -> None:
            claimed.append(
                str(
                    statement.compile(
                        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                    )
                )
            )

        yield SimpleNamespace(scalar=scalar)

    monkeypatch.setattr(media_worker, "tenant_session", session)
    runner = MediaJobRunner(
        gate=Gate(),  # type: ignore[arg-type]
        staging_root=Path("."),
        normalizer=None,  # type: ignore[arg-type]
        local_normalizer=Normalizer(),
        clock=lambda: NOW,
    )
    assert runner.claim(TENANT) is None
    order = claimed[0][claimed[0].index("ORDER BY") :]
    normalize = order.index("(gallery_jobs.kind = 'normalize_local') THEN 1")
    seasonal = order.index("THEN 3")
    assert normalize < seasonal and "ELSE 0" in order


def test_the_wait_counts_the_media_workers_own_attempts() -> None:
    """`local_sources.JOB_ATTEMPTS` copies `media_worker.MAX_ATTEMPTS` (importing the worker
    there would pull its runner into the creative worker): the deadline holds them all."""
    from qualify_api.catalog import media_worker
    from qualify_api.creative.video_pipeline import local_sources

    assert local_sources.JOB_ATTEMPTS == media_worker.MAX_ATTEMPTS
