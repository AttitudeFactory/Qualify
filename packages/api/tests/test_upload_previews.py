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
    STALE_VERSION,
    FrameStrip,
    NotPreviewable,
    UploadPreview,
    is_previewable,
    preview_job_key,
    preview_key,
    preview_play_key,
    preview_root,
    previews_for,
    request_preview,
    strip_key,
)

V1 = "upload-preview-480p-v1"
V2 = "upload-preview-480p-strip-v2"
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
    assert preview_job_key(source) == f"upload_preview:{V2}:{source}"
    # ED-11b: the strip sits in the copy's own folder
    strip = strip_key(TENANT, source)
    assert strip.rsplit("/", 1)[0] == key.rsplit("/", 1)[0] and strip.endswith("/strip.jpg")
    assert strip.startswith(preview_root(TENANT)) and strip == strip_key(TENANT, source)


def _row(
    source: str,
    status: str,
    *,
    code: str | None = None,
    created: datetime = T0,
    result: dict[str, Any] | None = None,
    version: str = V2,
    payload: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        idempotency_key=preview_job_key(source, version),
        status=status,
        payload=payload
        or {"source_key": source, "preview_key": preview_key(TENANT, source, version)},
        result=result or {},
        last_error_code=code,
        pipeline_version=version,
        created_at=created,
    )


class Jobs:
    """The `gallery_jobs` rows of TENANT, newest first, as `previews_for` reads them; an
    insert appends a queued row unless one that did not fail holds the key."""

    def __init__(self, rows: list[SimpleNamespace] | None = None) -> None:
        self.rows = list(rows or [])
        self.inserts: list[dict[str, Any]] = []
        self.updates: list[str] = []

    def execute(self, statement: Any) -> Any:
        if statement.is_update:  # only the stale-v2 release: check its shape, then apply
            sql = str(statement.compile(dialect=postgresql.dialect()))
            params = statement.compile(dialect=postgresql.dialect()).params
            assert "gallery_jobs.status = " in sql and "->> " in sql
            assert params["status"] == "failed" and params["last_error_code"] == STALE_VERSION
            key = params["idempotency_key_1"]
            self.updates.append(key)
            for r in self.rows:
                made = (r.result or {}).get("version")
                if r.idempotency_key == key and r.status == "done" and made != V2:
                    r.status, r.last_error_code = "failed", STALE_VERSION
            return None
        if statement.is_insert:
            values = dict(statement.compile(dialect=postgresql.dialect()).params)
            assert "ON CONFLICT DO NOTHING" in str(statement.compile(dialect=postgresql.dialect()))
            self.inserts.append(values)
            key = values["idempotency_key"]
            held = any(r.idempotency_key == key and r.status != "failed" for r in self.rows)
            if not held:
                source = values["payload"]["source_key"]
                queued = _row(
                    source,
                    "queued",
                    created=T0 + timedelta(hours=1),
                    version=values["pipeline_version"],
                    payload=values["payload"],
                )
                self.rows.insert(0, queued)
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
    assert values["pipeline_version"] == V2
    # ED-11b: ONE job for the copy and its strip — the original is read once
    assert values["payload"] == {
        "source_key": source,
        "preview_key": preview_key(TENANT, source),
        "strip_key": strip_key(TENANT, source),
        "version": V2,
    }
    assert preview.strip_status == "queued" and preview.strip is None
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
    by_job_key = {preview_job_key(source, v): (source, v) for v in (V2, V1)}
    folded = upload_previews._fold(TENANT, [source], by_job_key, rows)
    assert folded[source] == UploadPreview(
        source_key=source,
        status="queued",
        preview_key=preview_key(TENANT, source),
        version=V2,
        created_at=T0 + timedelta(hours=1),
        transient_failures=1,
        strip_status="queued",
    )


# -- the frame strip (ED-11b, m-25029110) -----------------------------------------------

STRIP_FACTS = {
    "frames": 20,
    "columns": 20,
    "rows": 1,
    "interval_s": 1,
    "offset_s": 0.5,
    "tile_width": 100,
    "tile_height": 56,
    "bytes": 21_000,
}


def test_a_made_strip_is_handed_to_the_timeline_with_its_layout(jobs: Jobs) -> None:
    source = _upload()
    made = strip_key(TENANT, source)
    jobs.rows = [_row(source, "done", result={"strip_key": made, "strip": STRIP_FACTS})]
    preview = previews_for(TENANT, [source])[source]
    assert preview.ready and preview.strip_status == "done" and not preview.strip_wanted
    assert preview.strip == FrameStrip(
        key=made, frames=20, columns=20, rows=1, tile_width=100, tile_height=56
    )
    assert preview.strip_key == made
    assert request_preview(TENANT, BRAND, source).strip_key == made and jobs.inserts == []


@pytest.mark.parametrize(
    "result",
    [
        {"strip_key": f"t/{OTHER}/uploads/previews/x/strip.jpg", "strip": STRIP_FACTS},
        {"strip_key": "t/x/../strip.jpg", "strip": STRIP_FACTS},
        {"strip": STRIP_FACTS},  # no key
        {"strip_skipped": "no_duration"},  # a video without a length: no strip
        {"strip_key": "K", "strip": {**STRIP_FACTS, "tile_width": 0}},
        {"strip_key": "K", "strip": {**STRIP_FACTS, "columns": 7}},  # 7 × 1 < 20 frames
        {"strip_key": "K", "strip": {"frames": "x"}},
    ],
)
def test_a_strip_outside_the_tenant_or_that_does_not_add_up_is_never_shown(
    jobs: Jobs, result: dict[str, Any]
) -> None:
    source = _upload()
    if result.get("strip_key") == "K":
        result = {**result, "strip_key": strip_key(TENANT, source)}
    jobs.rows = [_row(source, "done", result=result)]
    preview = previews_for(TENANT, [source])[source]
    assert preview.ready and preview.strip is None and preview.strip_key == ""
    # its job is done: never asked again (the key is held), the copy still plays
    assert not preview.strip_wanted
    assert request_preview(TENANT, BRAND, source).ready and jobs.inserts == []


def test_a_v1_copy_keeps_playing_and_its_strip_is_asked_for_apart(jobs: Jobs) -> None:
    """Copies made before the strip are neither lost nor encoded again: the v1 copy plays,
    and asking queues ONE v2 job whose `preview_key` is that copy (the worker finds it in
    place and decodes the original for the strip alone)."""
    source = _upload()
    old_copy = preview_key(TENANT, source, V1)
    head = {"width": 1920, "height": 1080, "rotation": 0}
    jobs.rows = [_row(source, "done", version=V1, result={"preview_key": old_copy, "source": head})]
    before = previews_for(TENANT, [source])[source]
    assert before.ready and before.preview_play_key == old_copy and before.version == V1
    assert before.strip_status == "none" and before.strip_wanted
    after = request_preview(TENANT, BRAND, source)
    (values,) = jobs.inserts
    assert values["idempotency_key"] == preview_job_key(source, V2)
    assert values["payload"] == {
        "source_key": source,
        "preview_key": old_copy,  # reused, not made again
        "strip_key": strip_key(TENANT, source),
        "version": V2,
    }
    # while the strip is made the v1 copy keeps playing, with the original's size
    assert after.ready and after.preview_play_key == old_copy
    assert (after.source_width, after.source_height) == (1920, 1080)
    assert after.strip_status == "queued" and not after.strip_wanted
    assert request_preview(TENANT, BRAND, source).strip_status == "queued"
    assert len(jobs.inserts) == 1  # asking again queues nothing more
    # done: the copy is still the v1 one, now with its strip
    jobs.rows[0].status = "done"
    jobs.rows[0].result = {
        "preview_key": old_copy,
        "source": head,
        "reused": True,
        "strip_key": strip_key(TENANT, source),
        "strip": STRIP_FACTS,
        "version": V2,
    }
    done = previews_for(TENANT, [source])[source]
    assert done.preview_play_key == old_copy and done.strip_key == strip_key(TENANT, source)


def test_a_strip_that_failed_keeps_the_v1_copy_and_retries_to_its_bound(jobs: Jobs) -> None:
    source = _upload()
    old_copy = preview_key(TENANT, source, V1)
    v1_done = _row(source, "done", version=V1, result={"preview_key": old_copy})
    strip_job = {"source_key": source, "preview_key": old_copy, "strip_key": "x"}
    jobs.rows = [
        _row(
            source,
            "failed",
            code="attempts_exhausted",
            created=T0 + timedelta(minutes=5),
            payload=strip_job,
        ),
        v1_done,
    ]
    preview = previews_for(TENANT, [source])[source]
    assert preview.ready and preview.preview_play_key == old_copy
    assert preview.strip_status == "failed" and preview.strip_wanted
    assert request_preview(TENANT, BRAND, source).strip_status == "queued"
    jobs.rows[0].status, jobs.rows[0].last_error_code = "failed", "r2_read:Timeout"
    again = request_preview(TENANT, BRAND, source)
    assert again.strip_failed_for_good and not again.strip_wanted
    assert again.ready and len(jobs.inserts) == 1


def test_a_strip_that_failed_for_a_reason_of_the_file_is_not_asked_again(jobs: Jobs) -> None:
    source = _upload()
    old_copy = preview_key(TENANT, source, V1)
    jobs.rows = [
        _row(source, "failed", code="unreadable", created=T0 + timedelta(minutes=5)),
        _row(source, "done", version=V1, result={"preview_key": old_copy}),
    ]
    preview = request_preview(TENANT, BRAND, source)
    assert preview.ready and preview.strip_failed_for_good and jobs.inserts == []


def test_a_v1_copy_still_on_its_way_is_waited_for(jobs: Jobs) -> None:
    """A v1 job queued before the deploy is made by the new worker as a v1 copy; nothing
    else is queued meanwhile, and once it is done its strip is asked for apart."""
    source = _upload()
    jobs.rows = [_row(source, "queued", version=V1)]
    preview = request_preview(TENANT, BRAND, source)
    assert preview.status == "queued" and jobs.inserts == []
    assert not preview.strip_wanted


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


def test_a_v2_job_settled_by_an_old_worker_keeps_its_copy_and_asks_for_its_strip(
    jobs: Jobs,
) -> None:
    """ED-11b review (the deploy's race): an old media-worker took a v2 job, made the copy
    alone and wrote ITS version in the result. The copy plays; the strip counts as failed,
    so it is asked for again — the stale job is marked failed (its key freed, its copy
    still counted) and ONE strip-only job reuses that copy."""
    source = _upload()
    made = preview_key(TENANT, source)
    head = {"width": 1920, "height": 1080, "rotation": 0}
    stale = _row(source, "done", result={"preview_key": made, "version": V1, "source": head})
    jobs.rows = [stale]
    before = previews_for(TENANT, [source])[source]
    assert before.ready and before.preview_play_key == made and before.strip is None
    assert before.strip_status == "failed" and before.strip_error_code == STALE_VERSION
    assert before.strip_wanted and not before.strip_failed_for_good
    after = request_preview(TENANT, BRAND, source)
    assert jobs.updates == [preview_job_key(source)]
    assert stale.status == "failed" and stale.last_error_code == STALE_VERSION
    (values,) = jobs.inserts
    assert values["payload"]["preview_key"] == made  # reused, never encoded again
    assert values["payload"]["strip_key"] == strip_key(TENANT, source)
    # the copy keeps playing from the stale job, with the original's size
    assert after.ready and after.preview_play_key == made and after.error_code is None
    assert (after.source_width, after.source_height) == (1920, 1080)
    assert after.strip_status == "queued" and after.transient_failures == 0
    assert request_preview(TENANT, BRAND, source).strip_status == "queued"
    assert len(jobs.inserts) == 1 and len(jobs.updates) == 1


def test_a_v2_job_that_made_its_strip_is_never_taken_for_stale(jobs: Jobs) -> None:
    source = _upload()
    result = {"version": V2, "strip_key": strip_key(TENANT, source), "strip": STRIP_FACTS}
    jobs.rows = [_row(source, "done", result=result)]
    preview = request_preview(TENANT, BRAND, source)
    assert preview.strip is not None and preview.strip_status == "done"
    assert jobs.updates == [] and jobs.inserts == []
