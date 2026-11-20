"""m-25026643 (ED-09): `media-worker`'s `upload_preview` job, offline — the light 480p
copy of a generator upload written once at its deterministic key, next to the original;
failures settle like the other kinds; nothing of another business is read or written.
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
from qualify_creative.video.business import (
    TranscodeInterrupted,
    TranscodeTimedOut,
    UnreadableVideo,
)
from qualify_creative.video.source_limits import SourceHeader
from qualify_creative.video.upload_preview import UPLOAD_PREVIEW_VERSION
from qualify_shared.objects.gate import ObjectNotFound, ObjectSizeExceeded

from qualify_api.catalog import media_worker
from qualify_api.catalog.business_media_models import (
    JOB_UPLOAD_PREVIEW,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_RUNNING,
)
from qualify_api.catalog.media_worker import ClaimedJob, MediaJobRunner
from qualify_api.creative.upload_previews import preview_key

TENANT = UUID("a0000000-0000-4000-8000-000025026643")
OTHER = UUID("b0000000-0000-4000-8000-000025026644")
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
SOURCE_KEY = f"t/{TENANT}/uploads/{uuid4().hex}_iphone.mov"
TARGET_KEY = preview_key(TENANT, SOURCE_KEY)
BIG = SourceHeader(width=5120, height=2880, pix_fmt="yuv420p10le", duration_s=112.0)
SMALL = SourceHeader(width=854, height=480, pix_fmt="yuv420p", duration_s=112.0)


class Gate:
    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        self.files = dict(files or {})
        self.puts: list[str] = []
        self.reads: list[str] = []
        self.fail_put: Exception | None = None

    def has_object(self, tenant_id: UUID, key: str) -> bool:
        assert key.startswith(f"t/{tenant_id}/")
        return key in self.files

    def open_object(self, tenant_id: UUID, key: str) -> Any:
        assert key.startswith(f"t/{tenant_id}/")
        self.reads.append(key)
        if key not in self.files:
            raise ObjectNotFound(key)
        return io.BytesIO(self.files[key])

    def put_media(self, tenant_id: UUID, key: str, fileobj: Any, content_type: str) -> None:
        assert key.startswith(f"t/{tenant_id}/")
        if self.fail_put is not None:
            raise self.fail_put
        assert content_type == "video/mp4"
        self.puts.append(key)
        self.files[key] = fileobj.read()


class Previewer:
    version = UPLOAD_PREVIEW_VERSION

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[float | None] = []

    def allowance(self, duration_s: float | None) -> timedelta:
        return timedelta(minutes=47)

    def make_preview(self, source: Path, out: Path, *, duration_s: float | None) -> None:
        self.calls.append(duration_s)
        if self.error is not None:
            raise self.error
        out.write_bytes(b"preview:" + source.read_bytes())


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


@pytest.fixture
def made(monkeypatch: pytest.MonkeyPatch) -> dict[str, SourceHeader]:
    """The source reads as 5K 10-bit; the previewer's output as 854×480 8-bit (a test
    swaps `made["copy"]` for a bad copy)."""
    headers = {"copy": SMALL}

    def header(path: Path) -> SourceHeader:
        return headers["copy"] if path.read_bytes().startswith(b"preview:") else BIG

    monkeypatch.setattr(source_limits, "read_header", header)
    return headers


def _runner(gate: Gate, previewer: Previewer | None, root: Path) -> MediaJobRunner:
    return MediaJobRunner(
        gate=gate,  # type: ignore[arg-type]
        staging_root=root,
        normalizer=None,  # type: ignore[arg-type]
        previewer=previewer,
        clock=lambda: NOW,
    )


def _job(
    source_key: str = SOURCE_KEY, target_key: str = TARGET_KEY, tenant: UUID = TENANT
) -> ClaimedJob:
    return ClaimedJob(
        id=uuid4(),
        tenant_id=tenant,
        brand_id=uuid4(),
        kind=JOB_UPLOAD_PREVIEW,
        staged_path=None,
        filename="",
        upload_sha256=None,
        attempts=1,
        payload={
            "source_key": source_key,
            "preview_key": target_key,
            "version": UPLOAD_PREVIEW_VERSION,
        },
    )


def test_an_upload_gets_its_copy_once_with_its_provenance(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    gate, previewer = Gate({SOURCE_KEY: b"5k"}), Previewer()
    outcome = _runner(gate, previewer, tmp_path).process(_job())
    assert outcome.status == STATUS_DONE
    assert gate.puts == [TARGET_KEY] and gate.files[TARGET_KEY] == b"preview:5k"
    assert gate.files[SOURCE_KEY] == b"5k"  # the original is kept as it came
    assert previewer.calls == [112.0]  # the length from the header scales the time
    assert row.status == STATUS_DONE and row.lease_until is None
    result = row.result
    assert result["preview_key"] == TARGET_KEY and result["source_key"] == SOURCE_KEY
    assert result["version"] == "upload-preview-480p-v1" and result["cost_usd"] == "0.00"
    assert result["source"]["width"] == 5120 and result["source"]["bits"] == 10
    assert result["preview"]["height"] == 480 and result["preview"]["bits"] == 8
    assert result["bytes"] == len(b"preview:5k") and "encode_s" in result
    assert result["worker"]


def test_the_copy_lives_next_to_the_original_under_the_tenants_uploads() -> None:
    assert TARGET_KEY.startswith(f"t/{TENANT}/uploads/previews/")
    assert TARGET_KEY.endswith("/video.mp4")
    assert preview_key(TENANT, SOURCE_KEY) == TARGET_KEY  # deterministic
    assert preview_key(TENANT, SOURCE_KEY, "upload-preview-480p-v2") != TARGET_KEY


def test_the_lease_is_held_for_the_encodes_whole_allowance(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    leases: list[Any] = []

    class Watching(Previewer):
        def make_preview(self, source: Path, out: Path, *, duration_s: float | None) -> None:
            leases.append(row.lease_until)
            super().make_preview(source, out, duration_s=duration_s)

    _runner(Gate({SOURCE_KEY: b"5k"}), Watching(), tmp_path).process(_job())
    assert leases == [NOW + timedelta(minutes=47)]


def test_a_copy_already_kept_is_never_encoded_again(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    gate, previewer = Gate({SOURCE_KEY: b"5k", TARGET_KEY: b"made before"}), Previewer()
    outcome = _runner(gate, previewer, tmp_path).process(_job())
    assert outcome.status == STATUS_DONE and row.result["reused"] is True
    assert previewer.calls == [] and gate.puts == []
    assert row.result["preview_key"] == TARGET_KEY
    # review: the original's header is still read (never encoded), so the editor knows
    # its size while it shows the copy
    assert gate.reads == [SOURCE_KEY]
    assert row.result["source"] == BIG.to_dict()


def test_a_reused_copy_whose_original_cannot_be_read_still_settles(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    gate, previewer = Gate({TARGET_KEY: b"made before"}), Previewer()  # the original is gone
    outcome = _runner(gate, previewer, tmp_path).process(_job())
    assert outcome.status == STATUS_DONE and row.result["reused"] is True
    assert "source" not in row.result and previewer.calls == [] and gate.puts == []


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (UnreadableVideo("bad"), STATUS_FAILED, "unreadable"),
        (TranscodeInterrupted("killed"), STATUS_QUEUED, "preview:TranscodeInterrupted"),
        (MemoryError(), STATUS_QUEUED, "preview:MemoryError"),
    ],
)
def test_an_unreadable_file_fails_for_good_and_a_killed_encode_retries(
    tmp_path: Path,
    row: SimpleNamespace,
    made: dict[str, SourceHeader],
    error: Exception,
    status: str,
    code: str,
) -> None:
    gate = Gate({SOURCE_KEY: b"5k"})
    _runner(gate, Previewer(error), tmp_path).process(_job())
    assert row.status == status and row.last_error_code == code
    assert gate.puts == []


def test_a_copy_that_runs_out_of_time_fails_for_good_at_once(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    """Review of m-25026643: nobody waits for the copy — a timed-out encode is not tried
    again (the attempts would be three more long encodes of the same file)."""
    gate = Gate({SOURCE_KEY: b"5k"})
    outcome = _runner(gate, Previewer(TranscodeTimedOut("2540s")), tmp_path).process(_job())
    assert outcome.status == STATUS_FAILED and row.status == STATUS_FAILED
    assert row.last_error_code == "preview_timeout" and row.attempts == 1
    assert gate.puts == []


def test_a_timed_out_normalize_is_still_retried(tmp_path: Path, row: SimpleNamespace) -> None:
    """The timeout rule is the preview's alone: a piece is waiting for a normalize."""
    from qualify_creative.video.local_normalize import NORMALIZE_LOCAL_VERSION
    from qualify_creative.video.source_limits import SourceHeader as Header

    from qualify_api.catalog.business_media_models import JOB_NORMALIZE_LOCAL
    from qualify_api.creative.video_pipeline.local_sources import normalized_key

    class TimingOut:
        version = NORMALIZE_LOCAL_VERSION

        def allowance(self, duration_s: float | None) -> timedelta:
            return timedelta(minutes=40)

        def normalize_file(self, source: Path, out: Path, *, duration_s: float | None) -> None:
            raise TranscodeTimedOut("3h")

    def header(_path: Path) -> Header:
        return BIG

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as patch:
        patch.setattr(source_limits, "read_header", header)
        runner = MediaJobRunner(
            gate=Gate({SOURCE_KEY: b"5k"}),  # type: ignore[arg-type]
            staging_root=tmp_path,
            normalizer=None,  # type: ignore[arg-type]
            local_normalizer=TimingOut(),
            clock=lambda: NOW,
        )
        job = ClaimedJob(
            id=uuid4(),
            tenant_id=TENANT,
            brand_id=uuid4(),
            kind=JOB_NORMALIZE_LOCAL,
            staged_path=None,
            filename="",
            upload_sha256=None,
            attempts=1,
            payload={
                "source_key": SOURCE_KEY,
                "normalized_key": normalized_key(TENANT, SOURCE_KEY),
                "version": NORMALIZE_LOCAL_VERSION,
            },
        )
        runner.process(job)
    assert row.status == STATUS_QUEUED and row.last_error_code == "normalize:timeout"


def test_a_missing_source_fails_for_good(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    outcome = _runner(Gate(), Previewer(), tmp_path).process(_job())
    assert outcome.status == STATUS_FAILED and row.last_error_code == "source_missing"


@pytest.mark.parametrize(
    "bad",
    [
        SourceHeader(width=1280, height=720, pix_fmt="yuv420p"),  # not shrunk
        SourceHeader(width=854, height=480, pix_fmt="yuv420p10le"),  # not 8 bits
        SourceHeader(width=854, height=480, pix_fmt="yuv420p", rotation=90),  # not upright
    ],
)
def test_a_copy_that_is_not_a_480p_upright_8_bit_one_is_never_kept(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader], bad: SourceHeader
) -> None:
    made["copy"] = bad
    gate = Gate({SOURCE_KEY: b"5k"})
    outcome = _runner(gate, Previewer(), tmp_path).process(_job())
    assert outcome.status == STATUS_FAILED and row.last_error_code == "preview_over_limit"
    assert gate.puts == []


def test_an_r2_hiccup_on_the_write_is_retried_onto_the_same_key(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    gate = Gate({SOURCE_KEY: b"5k"})
    gate.fail_put = ConnectionError("r2 down")
    _runner(gate, Previewer(), tmp_path).process(_job())
    assert row.status == STATUS_QUEUED and row.last_error_code == "r2_write:ConnectionError"
    gate.fail_put, row.status, row.attempts = None, STATUS_RUNNING, 2
    job = _job()
    retried = ClaimedJob(**{**job.__dict__, "attempts": 2})
    assert _runner(gate, Previewer(), tmp_path).process(retried).status == STATUS_DONE
    assert gate.puts == [TARGET_KEY]


def test_a_copy_too_big_for_one_put_fails_for_good(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    gate = Gate({SOURCE_KEY: b"5k"})
    gate.fail_put = ObjectSizeExceeded("too big")
    _runner(gate, Previewer(), tmp_path).process(_job())
    assert row.status == STATUS_FAILED and row.last_error_code == "preview_too_large"


@pytest.mark.parametrize(
    ("source_key", "target_key"),
    [
        # another business's upload is never read
        (f"t/{OTHER}/uploads/{uuid4().hex}_x.mov", TARGET_KEY),
        # nor written outside this tenant's copies
        (SOURCE_KEY, f"t/{OTHER}/uploads/previews/x/video.mp4"),
        (SOURCE_KEY, f"t/{TENANT}/normalized/x/video.mp4"),
        (SOURCE_KEY, f"t/{TENANT}/uploads/previews/../../x/video.mp4"),
        ("", TARGET_KEY),
    ],
)
def test_a_payload_outside_the_tenant_is_refused_before_anything_is_read(
    tmp_path: Path,
    row: SimpleNamespace,
    made: dict[str, SourceHeader],
    source_key: str,
    target_key: str,
) -> None:
    gate, previewer = Gate({source_key: b"x"} if source_key else {}), Previewer()
    outcome = _runner(gate, previewer, tmp_path).process(_job(source_key, target_key))
    assert outcome.status == STATUS_FAILED and row.last_error_code == "payload_invalid"
    assert gate.reads == [] and gate.puts == [] and previewer.calls == []


def test_a_runner_without_a_previewer_retries_instead_of_failing(
    tmp_path: Path, row: SimpleNamespace
) -> None:
    _runner(Gate({SOURCE_KEY: b"5k"}), None, tmp_path).process(_job())
    assert row.status == STATUS_QUEUED and row.last_error_code == "previewer_unavailable"


def test_a_preview_is_claimed_after_the_galerias_own_jobs_and_after_a_normalize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review of m-25026643: `ingest`/`cut` (0), then `normalize_local` (1) — a piece being
    made waits for it — then `upload_preview` (2), which nobody waits for, then a recent
    seasonal job (3); and only a runner with a previewer claims previews at all."""
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
    with_previewer = _runner(Gate(), Previewer(), Path("."))
    assert with_previewer.claim(TENANT) is None
    without = _runner(Gate(), None, Path("."))
    assert without.claim(TENANT) is None
    where, order = claimed[0].split("ORDER BY")
    assert "'upload_preview'" in where
    normalize = order.index("(gallery_jobs.kind = 'normalize_local') THEN 1")
    preview = order.index("(gallery_jobs.kind = 'upload_preview') THEN 2")
    seasonal = order.index("THEN 3")
    assert normalize < preview < seasonal and "ELSE 0" in order
    assert "'upload_preview'" not in claimed[1].split("ORDER BY")[0]


def test_the_production_runner_has_a_previewer(monkeypatch: pytest.MonkeyPatch) -> None:
    import inspect

    source = inspect.getsource(media_worker.production_runner)
    assert "previewer=FfmpegUploadPreviewer()" in source
