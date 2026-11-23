"""m-25026643 (ED-09): `media-worker`'s `upload_preview` job, offline — the light 480p
copy of a generator upload written once at its deterministic key, next to the original;
failures settle like the other kinds; nothing of another business is read or written.
The DB door is a double of `tenant_session` holding the job row; FFmpeg and the header
reader are doubles too (the real command is pinned in `packages/creative`)."""

from __future__ import annotations

import io
from contextlib import contextmanager
from dataclasses import replace
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
from qualify_api.creative.upload_previews import preview_key, strip_key

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
        if self.fail_put is not None and (self.fail_put_on is None or key == self.fail_put_on):
            raise self.fail_put
        assert content_type == ("image/jpeg" if key.endswith("/strip.jpg") else "video/mp4")
        self.puts.append(key)
        self.files[key] = fileobj.read()

    fail_put_on: str | None = None


def _jpeg(width: int, height: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 40, 40)).save(buffer, format="JPEG")
    return buffer.getvalue()


class Previewer:
    """FFmpeg's double: the copy is `preview:` + the source; the strip a real JPEG of
    `TILE` px tiles in the layout's grid (the worker reads its size back)."""

    version = UPLOAD_PREVIEW_VERSION
    TILE = (100, 56)

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[float | None] = []
        self.made: list[tuple[bool, Any]] = []  # (copy made, strip layout)

    def allowance(self, duration_s: float | None) -> timedelta:
        return timedelta(minutes=47)

    def make_preview(
        self,
        source: Path,
        out: Path | None,
        *,
        duration_s: float | None,
        strip_out: Path | None = None,
        layout: Any = None,
    ) -> None:
        self.calls.append(duration_s)
        self.made.append((out is not None, layout))
        if self.error is not None:
            raise self.error
        if out is not None:
            out.write_bytes(b"preview:" + source.read_bytes())
        if strip_out is not None:
            width, height = self.TILE
            strip_out.write_bytes(_jpeg(layout.columns * width, layout.rows * height))


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
    assert result["version"] == UPLOAD_PREVIEW_VERSION and result["cost_usd"] == "0.00"
    assert "strip_key" not in result  # a v1 payload (no `strip_key`): the copy alone
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


# -- the frame strip (ED-11b, m-25029110) -----------------------------------------------

STRIP_KEY = strip_key(TENANT, SOURCE_KEY)


def _strip_job(target_key: str = TARGET_KEY, strip: str = STRIP_KEY) -> ClaimedJob:
    job = _job(target_key=target_key)
    return replace(job, payload={**(job.payload or {}), "strip_key": strip})


def test_the_copy_and_its_strip_come_out_of_one_decode(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    gate, previewer = Gate({SOURCE_KEY: b"5k"}), Previewer()
    outcome = _runner(gate, previewer, tmp_path).process(_strip_job())
    assert outcome.status == STATUS_DONE
    # ONE FFmpeg run made both: the original was read once
    ((copy, layout),) = previewer.made
    assert copy and (layout.frames, layout.columns, layout.rows) == (112, 60, 2)
    assert gate.reads == [SOURCE_KEY]
    assert gate.puts == [TARGET_KEY, STRIP_KEY]  # the copy first, then the strip
    assert STRIP_KEY.startswith(f"t/{TENANT}/uploads/previews/")
    result = row.result
    assert result["strip_key"] == STRIP_KEY and result["cost_usd"] == "0.00"
    assert result["strip"] == {
        "frames": 112,
        "columns": 60,
        "rows": 2,
        "interval_s": 1,
        "offset_s": 0.5,
        "tile_width": 100,
        "tile_height": 56,
        "bytes": len(gate.files[STRIP_KEY]),
    }
    assert result["preview_key"] == TARGET_KEY and result["version"] == UPLOAD_PREVIEW_VERSION


def test_the_results_version_is_the_jobs_and_the_encoders_is_kept_beside_it(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    """ED-11b review: a v1 job (queued before the deploy) settled by this worker says v1
    — what it asked for, the copy alone — so the readers never take it for a v2 job with
    a strip; the encoder that made it is `made_with`."""
    job = _job()
    v1_job = replace(job, payload={**(job.payload or {}), "version": "upload-preview-480p-v1"})
    gate = Gate({SOURCE_KEY: b"5k"})
    assert _runner(gate, Previewer(), tmp_path).process(v1_job).status == STATUS_DONE
    assert row.result["version"] == "upload-preview-480p-v1"
    assert row.result["made_with"] == UPLOAD_PREVIEW_VERSION


def test_a_kept_copy_gets_its_strip_alone_never_a_second_encode(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    """A v1 copy whose strip was asked for apart, or a retry after the copy's PUT: the
    original is decoded for the strip only, and the copy is never written again."""
    v1_copy = preview_key(TENANT, SOURCE_KEY, "upload-preview-480p-v1")
    gate, previewer = Gate({SOURCE_KEY: b"5k", v1_copy: b"v1 copy"}), Previewer()
    outcome = _runner(gate, previewer, tmp_path).process(_strip_job(target_key=v1_copy))
    assert outcome.status == STATUS_DONE
    ((copy, layout),) = previewer.made
    assert not copy and layout.frames == 112
    assert gate.puts == [STRIP_KEY] and gate.files[v1_copy] == b"v1 copy"
    result = row.result
    assert result["reused"] is True and result["preview_key"] == v1_copy
    assert result["source"] == BIG.to_dict()  # the editor still learns the original's size
    assert result["strip_key"] == STRIP_KEY and result["strip"]["tile_height"] == 56


def test_a_strip_put_that_fails_is_retried_as_the_strip_alone(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    gate = Gate({SOURCE_KEY: b"5k"})
    gate.fail_put, gate.fail_put_on = ConnectionError("r2 down"), STRIP_KEY
    first = Previewer()
    _runner(gate, first, tmp_path).process(_strip_job())
    assert row.status == STATUS_QUEUED and row.last_error_code == "r2_write_strip:ConnectionError"
    assert gate.puts == [TARGET_KEY]  # the copy is kept (write-once `t/`)
    gate.fail_put, row.status, row.attempts = None, STATUS_RUNNING, 2
    retried = replace(_strip_job(), attempts=2)
    second = Previewer()
    assert _runner(gate, second, tmp_path).process(retried).status == STATUS_DONE
    assert [copy for copy, _ in second.made] == [False]  # never encoded twice
    assert gate.puts == [TARGET_KEY, STRIP_KEY] and row.result["strip_key"] == STRIP_KEY


def test_both_kept_nothing_is_decoded_and_the_strip_is_described_from_its_file(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    kept = {SOURCE_KEY: b"5k", TARGET_KEY: b"made", STRIP_KEY: _jpeg(6000, 112)}
    gate, previewer = Gate(kept), Previewer()
    outcome = _runner(gate, previewer, tmp_path).process(_strip_job())
    assert outcome.status == STATUS_DONE and previewer.calls == [] and gate.puts == []
    strip = row.result["strip"]
    assert (strip["frames"], strip["tile_width"], strip["tile_height"]) == (112, 100, 56)
    assert row.result["strip_key"] == STRIP_KEY and strip["reused"] is True


def test_a_video_without_a_length_gets_its_copy_and_no_strip(
    tmp_path: Path,
    row: SimpleNamespace,
    made: dict[str, SourceHeader],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endless = replace(BIG, duration_s=None)
    monkeypatch.setattr(
        source_limits,
        "read_header",
        lambda path: SMALL if path.read_bytes().startswith(b"preview:") else endless,
    )
    gate, previewer = Gate({SOURCE_KEY: b"5k"}), Previewer()
    assert _runner(gate, previewer, tmp_path).process(_strip_job()).status == STATUS_DONE
    assert previewer.made == [(True, None)] and gate.puts == [TARGET_KEY]
    assert row.result["strip_skipped"] == "no_duration" and "strip_key" not in row.result
    # a kept copy of such a video: nothing to decode at all
    row.status, row.result = STATUS_RUNNING, {}
    again = Previewer()
    assert _runner(gate, again, tmp_path).process(_strip_job()).status == STATUS_DONE
    assert again.calls == [] and row.result["strip_skipped"] == "no_duration"


def test_a_strip_ffmpeg_did_not_write_leaves_the_copy_done(
    tmp_path: Path, row: SimpleNamespace, made: dict[str, SourceHeader]
) -> None:
    class NoStrip(Previewer):
        def make_preview(self, source: Path, out: Path | None, **kwargs: Any) -> None:
            super().make_preview(source, out, duration_s=kwargs["duration_s"])

    gate = Gate({SOURCE_KEY: b"5k"})
    assert _runner(gate, NoStrip(), tmp_path).process(_strip_job()).status == STATUS_DONE
    assert gate.puts == [TARGET_KEY] and row.result["strip_skipped"] == "empty"


@pytest.mark.parametrize(
    "strip",
    [
        f"t/{OTHER}/uploads/previews/{uuid4()}/strip.jpg",
        f"t/{TENANT}/uploads/previews/../../{OTHER}/strip.jpg",
        f"t/{TENANT}/normalized/{uuid4()}/strip.jpg",
    ],
)
def test_a_strip_key_outside_the_tenants_copies_is_refused(
    tmp_path: Path, row: SimpleNamespace, strip: str
) -> None:
    gate, previewer = Gate({SOURCE_KEY: b"5k"}), Previewer()
    outcome = _runner(gate, previewer, tmp_path).process(_strip_job(strip=strip))
    assert outcome.status == STATUS_FAILED and row.last_error_code == "payload_invalid"
    assert gate.reads == [] and gate.puts == [] and previewer.calls == []
