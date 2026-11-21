"""m-25026643 (ED-09): the door the screens use for the 480p copy of a generator upload —
which keys may have one, where it lives, what the editor plays, and when a request queues
a job. Offline: the job rows are a double of `previews_for`'s query (`_fold`) and of the
insert; the SQL itself is `test_gallery_jobs_upload_preview_db.py`."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

from qualify_api.creative import upload_previews
from qualify_api.creative.upload_previews import (
    NotPreviewable,
    UploadPreview,
    is_previewable,
    preview_job_key,
    preview_key,
    preview_play_key,
    preview_root,
    previews_for,
    request_preview,
)

TENANT = UUID("a0000000-0000-4000-8000-000025026643")
OTHER = UUID("b0000000-0000-4000-8000-000025026644")
BRAND = uuid4()
T0 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def _upload(tenant: UUID = TENANT, name: str = "iphone.MOV") -> str:
    return f"t/{tenant}/uploads/{uuid4().hex}_{name}"


@pytest.mark.parametrize(
    ("key", "ok"),
    [
        (_upload(), True),
        (f"uploads/{TENANT}/{uuid4().hex}_clip.mp4", True),  # an old local upload
        (_upload(name="foto.jpg"), False),  # not a video
        (_upload(OTHER), False),  # another business's
        (f"t/{TENANT}/uploads/previews/{uuid4()}/video.mp4", False),  # a copy itself
        (f"t/{TENANT}/normalized/{uuid4()}/video.mp4", False),  # not an upload
        (f"gallery/{TENANT}/{uuid4()}/video.mp4", False),  # the Galería's own
        (f"t/{TENANT}/uploads/../{OTHER}/x.mov", False),
        ("", False),
    ],
)
def test_only_this_tenants_uploaded_videos_have_a_copy(key: str, ok: bool) -> None:
    assert is_previewable(TENANT, key) is ok


def test_the_copys_key_is_deterministic_and_under_the_tenants_uploads() -> None:
    source = _upload()
    key = preview_key(TENANT, source)
    assert key == preview_key(TENANT, source)
    assert key.startswith(preview_root(TENANT)) and key.endswith("/video.mp4")
    assert key != preview_key(TENANT, _upload())
    assert preview_job_key(source) == f"upload_preview:upload-preview-480p-v1:{source}"


def _row(
    source: str,
    status: str,
    *,
    code: str | None = None,
    created: datetime = T0,
    result: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        idempotency_key=preview_job_key(source),
        status=status,
        payload={"source_key": source, "preview_key": preview_key(TENANT, source)},
        result=result or {},
        last_error_code=code,
        pipeline_version="upload-preview-480p-v1",
        created_at=created,
    )


class Jobs:
    """The `gallery_jobs` rows of TENANT, newest first, as `previews_for` reads them; an
    insert appends a queued row unless one that did not fail holds the key."""

    def __init__(self, rows: list[SimpleNamespace] | None = None) -> None:
        self.rows = list(rows or [])
        self.inserts: list[dict[str, Any]] = []

    def execute(self, statement: Any) -> Any:
        if statement.is_insert:
            values = dict(statement.compile(dialect=postgresql.dialect()).params)
            assert "ON CONFLICT DO NOTHING" in str(statement.compile(dialect=postgresql.dialect()))
            self.inserts.append(values)
            key = values["idempotency_key"]
            held = any(r.idempotency_key == key and r.status != "failed" for r in self.rows)
            if not held:
                source = values["payload"]["source_key"]
                self.rows.insert(0, _row(source, "queued", created=T0 + timedelta(hours=1)))
            return None
        return SimpleNamespace(all=lambda: list(self.rows))


@pytest.fixture
def jobs(monkeypatch: pytest.MonkeyPatch) -> Jobs:
    from qualify_shared.db import session as session_module

    store = Jobs()
    tenants: list[UUID] = []

    @contextmanager
    def tenant_session(tenant: UUID) -> Any:
        tenants.append(tenant)
        yield store

    monkeypatch.setattr(session_module, "tenant_session", tenant_session)
    store.tenants = tenants  # type: ignore[attr-defined]
    return store


def test_a_video_never_asked_for_plays_its_original(jobs: Jobs) -> None:
    source = _upload()
    preview = previews_for(TENANT, [source])[source]
    assert preview.status == "none" and not preview.ready
    assert preview.preview_play_key == source == preview_play_key(TENANT, source)


def test_a_made_copy_is_what_the_editor_plays(jobs: Jobs) -> None:
    source = _upload()
    made = preview_key(TENANT, source)
    jobs.rows = [_row(source, "done", result={"preview_key": made, "version": "v1x"})]
    preview = previews_for(TENANT, [source])[source]
    assert preview.ready and preview.preview_key == made and preview.version == "v1x"
    assert preview_play_key(TENANT, source) == made


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_until_the_copy_is_made_the_editor_plays_the_original(jobs: Jobs, status: str) -> None:
    source = _upload()
    jobs.rows = [_row(source, status, code="attempts_exhausted" if status == "failed" else None)]
    assert preview_play_key(TENANT, source) == source


def test_a_key_of_another_business_is_never_looked_up(jobs: Jobs) -> None:
    foreign = _upload(OTHER)
    assert previews_for(TENANT, [foreign]) == {}
    assert preview_play_key(TENANT, foreign) == foreign  # the caller's own check stands
    assert jobs.tenants == []  # type: ignore[attr-defined]
    with pytest.raises(NotPreviewable):
        request_preview(TENANT, BRAND, foreign)
    assert jobs.inserts == []


def test_a_result_pointing_outside_the_tenants_copies_is_never_handed_out(jobs: Jobs) -> None:
    source = _upload()
    jobs.rows = [_row(source, "done", result={"preview_key": f"t/{OTHER}/uploads/x.mp4"})]
    assert previews_for(TENANT, [source])[source].preview_key == preview_key(TENANT, source)


def test_a_request_queues_one_job_with_its_provenance(jobs: Jobs) -> None:
    source = _upload()
    preview = request_preview(TENANT, BRAND, source)
    assert preview.status == "queued"
    (values,) = jobs.inserts
    assert values["tenant_id"] == TENANT and values["brand_id"] == BRAND
    assert values["kind"] == "upload_preview"
    assert values["idempotency_key"] == preview_job_key(source)
    assert values["pipeline_version"] == "upload-preview-480p-v1"
    assert values["payload"] == {
        "source_key": source,
        "preview_key": preview_key(TENANT, source),
        "version": "upload-preview-480p-v1",
    }
    assert set(jobs.tenants) == {TENANT}  # type: ignore[attr-defined]


@pytest.mark.parametrize("status", ["queued", "running", "done"])
def test_asking_again_never_makes_a_second_copy(jobs: Jobs, status: str) -> None:
    source = _upload()
    jobs.rows = [_row(source, status)]
    assert request_preview(TENANT, BRAND, source).status == status
    assert jobs.inserts == []


def test_a_file_that_failed_for_good_is_not_asked_again(jobs: Jobs) -> None:
    source = _upload()
    jobs.rows = [_row(source, "failed", code="unreadable")]
    preview = request_preview(TENANT, BRAND, source)
    assert preview.failed_for_good and jobs.inserts == []


def test_a_copy_that_ran_out_of_time_is_not_asked_again(jobs: Jobs) -> None:
    source = _upload()
    jobs.rows = [_row(source, "failed", code="preview_timeout")]
    preview = request_preview(TENANT, BRAND, source)
    assert preview.failed_for_good and preview.transient_failures == 0
    assert jobs.inserts == [] and preview_play_key(TENANT, source) == source


def test_a_failure_of_the_machine_is_re_queued_up_to_its_bound(jobs: Jobs) -> None:
    source = _upload()
    jobs.rows = [_row(source, "failed", code="attempts_exhausted")]
    assert request_preview(TENANT, BRAND, source).status == "queued"
    assert len(jobs.inserts) == 1
    jobs.rows[0].status, jobs.rows[0].last_error_code = "failed", "r2_write:ConnectionError"
    preview = request_preview(TENANT, BRAND, source)
    assert preview.transient_failures == upload_previews.MAX_TRANSIENT_FAILURES
    assert preview.failed_for_good and len(jobs.inserts) == 1


def test_the_newest_job_is_the_files_state() -> None:
    source = _upload()
    rows = [
        _row(source, "queued", created=T0 + timedelta(hours=1)),
        _row(source, "failed", code="attempts_exhausted", created=T0),
    ]
    folded = upload_previews._fold(TENANT, [source], {preview_job_key(source): source}, rows)
    assert folded[source] == UploadPreview(
        source_key=source,
        status="queued",
        preview_key=preview_key(TENANT, source),
        created_at=T0 + timedelta(hours=1),
        transient_failures=1,
    )


# -- the original's size, for the editor's «Cortar» while it shows the copy -------------


@pytest.mark.parametrize(
    ("header", "size"),
    [
        ({"width": 3840, "height": 2160, "rotation": 0}, (3840, 2160)),
        ({"width": 3840, "height": 2160, "rotation": 90}, (2160, 3840)),  # a phone's portrait
        ({"width": 3840, "height": 2160, "rotation": -90}, (2160, 3840)),
        ({"width": 3840, "height": 2160, "rotation": 270}, (2160, 3840)),
        ({"width": 1920, "height": 1080, "rotation": 180}, (1920, 1080)),
        ({"width": 1920, "height": 1080}, (1920, 1080)),
        ({"width": 0, "height": 1080}, (0, 0)),
        ({"width": "x", "height": 1080}, (0, 0)),
        (None, (0, 0)),
        ("1920x1080", (0, 0)),
    ],
)
def test_the_originals_size_is_read_upright(header: Any, size: tuple[int, int]) -> None:
    assert upload_previews.upright_size(header) == size


def test_a_made_copy_carries_the_originals_upright_size(jobs: Jobs) -> None:
    source = _upload()
    head = {"width": 3840, "height": 2160, "pix_fmt": "yuv420p10le", "bits": 10, "rotation": 90}
    copy = {"width": 270, "height": 480, "rotation": 0}
    jobs.rows = [_row(source, "done", result={"source": head, "upload_preview": copy})]
    preview = previews_for(TENANT, [source])[source]
    assert preview.ready
    assert (preview.source_width, preview.source_height) == (2160, 3840)


def test_without_a_header_the_size_is_unknown(jobs: Jobs) -> None:
    source = _upload()
    jobs.rows = [_row(source, "done", result={"preview_key": preview_key(TENANT, source)})]
    preview = previews_for(TENANT, [source])[source]
    assert (preview.source_width, preview.source_height) == (0, 0)
