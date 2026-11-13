"""Tests for `publish_engine` — the one publish engine of «Publicar ahora», driven by
in-memory fakes (no Reflex, no network, no R2): planning per mode, the idempotency keys,
strict one-after-another runs, a failure midway and «Continuar»."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from qualify_api.publishing import (
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_REELS,
    MEDIA_TYPE_STORIES,
    MEDIA_TYPE_VIDEO,
    UnsupportedPlatform,
)
from qualify_api.publishing.service import UnknownConnection
from qualify_shared.objects.config import R2ConfigurationError

from . import publish_engine as engine
from .publish_engine import JobFile, JobRecord, PublishJob
from .publish_wizard_vm import (
    MODE_CAROUSEL,
    MODE_ONE_BY_ONE,
    MODE_POST,
    MODE_STORIES,
    MODE_STORY,
    STATUS_FAILED,
    STATUS_PUBLISHED,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
    STATUS_WAITING,
)
from .publishing_vm import PublishAttemptVM


def _img(tag: str) -> JobFile:
    return JobFile(content_type="image/jpeg", data=tag.encode(), media_type=MEDIA_TYPE_IMAGE)


def _vid(tag: str) -> JobFile:
    return JobFile(content_type="video/mp4", data=tag.encode(), media_type=MEDIA_TYPE_VIDEO)


def _attempt(attempt_id: str, *, settled: bool, status: str = "processing", reason: str = ""):
    return PublishAttemptVM(
        attempt_id=attempt_id,
        status=status,
        settled=settled,
        published_media_id="m" if status == "published" else "",
        reason=reason,
        awaiting_confirmation=False,
        poll_interval_seconds=1,
    )


@dataclass
class FakePorts:
    """Records every call in order. `fail_on` maps a job's first-file data to a mode:
    `"settled"` (the attempt settles as failed), `"poll"` (polling raises) or an
    exception to raise from `start`. A key seen before returns its existing attempt (the
    backend's idempotency) and is never "published" twice."""

    fail_on: dict[bytes, object] = field(default_factory=dict)
    log: list[tuple[str, str, bytes]] = field(default_factory=list)
    published: list[bytes] = field(default_factory=list)
    attempts_by_key: dict[str, str] = field(default_factory=dict)
    in_flight: int = 0
    max_in_flight: int = 0

    async def start(self, job: PublishJob, key: str) -> PublishAttemptVM:
        tag = job.files[0].data
        self.log.append(("start", key, tag))
        failure = self.fail_on.get(tag)
        if isinstance(failure, BaseException):
            raise failure
        if key in self.attempts_by_key:
            return _attempt(self.attempts_by_key[key], settled=False)
        self.attempts_by_key[key] = f"a-{key}"
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        return _attempt(f"a-{key}", settled=False)

    async def poll(self, job: PublishJob, attempt_id: str) -> PublishAttemptVM:
        tag = job.files[0].data
        self.log.append(("poll", attempt_id, tag))
        failure = self.fail_on.get(tag)
        if failure == "poll":
            raise RuntimeError("network")
        self.in_flight = max(0, self.in_flight - 1)
        if failure == "settled":
            return _attempt(attempt_id, settled=True, status="failed", reason="No salió.")
        if tag not in self.published:
            self.published.append(tag)
        return _attempt(attempt_id, settled=True, status="published")

    async def sleep(self, seconds: float) -> None:
        return None


def _collect() -> tuple[list[JobRecord | None], Callable]:
    seen: list = []

    async def report(index: int, record: JobRecord) -> bool:
        seen.append((index, record.status))
        return True

    return seen, report


def _run(jobs, records, ports, report=None, batch="B"):
    report = report or _collect()[1]
    return asyncio.run(engine.run_jobs(jobs, records, batch_key=batch, ports=ports, report=report))


# -- planning -------------------------------------------------------------------------


def test_a_single_photo_is_one_image_job_and_a_video_a_reel() -> None:
    (job,) = engine.plan_jobs(MODE_POST, [_img("a")], ["hola"])
    assert job.product == MEDIA_TYPE_IMAGE and job.caption == "hola"
    (job,) = engine.plan_jobs(MODE_POST, [_vid("v")], [""])
    assert job.product == MEDIA_TYPE_REELS


def test_a_carousel_is_one_job_with_every_file_in_the_listed_order() -> None:
    files = [_img("c"), _vid("a"), _img("b")]
    (job,) = engine.plan_jobs(MODE_CAROUSEL, files, ["texto"])
    assert job.product == engine.PRODUCT_CAROUSEL
    assert [f.data for f in job.files] == [b"c", b"a", b"b"]
    assert job.pieces == (0, 1, 2)
    assert job.caption == "texto"


def test_one_by_one_runs_from_the_last_to_the_first_each_with_its_own_text() -> None:
    files = [_img("p1"), _vid("p2"), _img("p3")]
    jobs = engine.plan_jobs(MODE_ONE_BY_ONE, files, ["uno", "dos", "tres"])
    assert [j.files[0].data for j in jobs] == [b"p3", b"p2", b"p1"]
    assert [j.caption for j in jobs] == ["tres", "dos", "uno"]
    assert [j.product for j in jobs] == [MEDIA_TYPE_IMAGE, MEDIA_TYPE_REELS, MEDIA_TYPE_IMAGE]
    assert [j.pieces for j in jobs] == [(2,), (1,), (0,)]


def test_three_files_as_historias_are_three_stories_in_the_listed_order_without_text() -> None:
    jobs = engine.plan_jobs(MODE_STORIES, [_img("s1"), _vid("s2"), _img("s3")], ["x"])
    assert [j.files[0].data for j in jobs] == [b"s1", b"s2", b"s3"]
    assert {j.product for j in jobs} == {MEDIA_TYPE_STORIES}
    assert {j.caption for j in jobs} == {""}
    (story,) = engine.plan_jobs(MODE_STORY, [_img("s")], ["ignored"])
    assert story.product == MEDIA_TYPE_STORIES and story.caption == ""


# -- keys -------------------------------------------------------------------------------


def test_keys_one_per_item_and_new_only_after_a_settled_failure() -> None:
    assert engine.job_key("B", 0) == "B:0"
    assert engine.job_key("B", 3, 2) == "B:3:r2"
    assert engine.key_for("B", 1, JobRecord()) == ("B:1", 0)
    failed = JobRecord(status=STATUS_FAILED, key="B:1", retries=0)
    assert engine.key_for("B", 1, failed) == ("B:1:r1", 1)
    # an unknown outcome (maybe still awaiting confirmation) keeps its SAME key
    unknown = JobRecord(status=STATUS_UNKNOWN, key="B:1:r1", retries=1)
    assert engine.key_for("B", 1, unknown) == ("B:1:r1", 1)


# -- the run ------------------------------------------------------------------------------


def test_one_by_one_starts_n_publications_strictly_one_after_another() -> None:
    files = [_img(f"p{i}") for i in range(1, 5)]
    jobs = engine.plan_jobs(MODE_ONE_BY_ONE, files, [f"t{i}" for i in range(1, 5)])
    ports = FakePorts()
    seen, report = _collect()
    end = _run(jobs, [JobRecord() for _ in jobs], ports, report)
    assert end.kind == "done"
    starts = [(key, tag) for kind, key, tag in ports.log if kind == "start"]
    assert starts == [("B:0", b"p4"), ("B:1", b"p3"), ("B:2", b"p2"), ("B:3", b"p1")]
    # each one settled before the next started
    kinds = [kind for kind, _, _ in ports.log]
    assert kinds == ["start", "poll"] * 4
    assert ports.max_in_flight == 1
    assert ports.published == [b"p4", b"p3", b"p2", b"p1"]
    assert seen[-1] == (3, STATUS_PUBLISHED)


def test_a_failure_midway_stops_there_and_continuar_never_republishes() -> None:
    files = [_img(f"p{i}") for i in range(1, 6)]  # list order p1..p5, run p5..p1
    jobs = engine.plan_jobs(MODE_ONE_BY_ONE, files, [""] * 5)
    ports = FakePorts(fail_on={b"p3": "settled"})
    records = [JobRecord() for _ in jobs]

    async def report_into(index: int, record: JobRecord) -> bool:
        records[index] = record
        return True

    end = _run(jobs, records, ports, report_into)
    assert end.kind == "failed" and end.at == 2
    assert engine.published_count(records) == 2
    assert [r.status for r in records] == [
        STATUS_PUBLISHED,
        STATUS_PUBLISHED,
        STATUS_FAILED,
        STATUS_WAITING,
        STATUS_WAITING,
    ]
    assert records[2].reason == "No salió."
    assert engine.first_unpublished(records) == 2

    # «Continuar»: the failed one gets a NEW key, the ones out are never started again
    ports.fail_on = {}
    ports.log.clear()
    end = _run(jobs, records, ports, report_into)
    assert end.kind == "done"
    starts = [(key, tag) for kind, key, tag in ports.log if kind == "start"]
    assert starts == [("B:2:r1", b"p3"), ("B:3", b"p2"), ("B:4", b"p1")]
    assert ports.published == [b"p5", b"p4", b"p3", b"p2", b"p1"]


def test_an_unknown_outcome_resumes_with_the_same_key_and_does_not_publish_twice() -> None:
    jobs = engine.plan_jobs(MODE_STORIES, [_img("s1"), _img("s2")], [])
    ports = FakePorts(fail_on={b"s1": "poll"})
    records = [JobRecord() for _ in jobs]

    async def report_into(index: int, record: JobRecord) -> bool:
        records[index] = record
        return True

    end = _run(jobs, records, ports, report_into)
    assert end.kind == "failed" and records[0].status == STATUS_UNKNOWN
    assert records[0].reason == engine.POLL_FAILED
    ports.fail_on = {}
    ports.log.clear()
    _run(jobs, records, ports, report_into)
    starts = [key for kind, key, _ in ports.log if kind == "start"]
    assert starts == ["B:0", "B:1"]  # B:0 again: the backend hands back the same attempt
    assert ports.published == [b"s1", b"s2"]
    assert len(ports.attempts_by_key) == 2


def test_leaving_stops_before_the_next_piece_never_mid_flight() -> None:
    jobs = engine.plan_jobs(MODE_STORIES, [_img("a"), _img("b"), _img("c")], [])
    ports = FakePorts()
    records = [JobRecord() for _ in jobs]
    stop = {"now": False}

    async def report(index: int, record: JobRecord) -> bool:
        records[index] = record
        if record.status == STATUS_PUBLISHED and index == 0:
            stop["now"] = True  # the owner pressed «Salir igual» while the first went out
        return not stop["now"]

    end = _run(jobs, records, ports, report)
    assert end.kind == "stopped" and end.at == 1
    assert ports.published == [b"a"]
    assert [r.status for r in records] == [STATUS_PUBLISHED, STATUS_WAITING, STATUS_WAITING]


def test_a_start_failure_maps_to_the_owners_words() -> None:
    job = engine.plan_jobs(MODE_POST, [_img("x")], [""])[0]
    import uuid

    cases = [
        (UnsupportedPlatform(connection_id=uuid.uuid4(), platform="whatsapp"), STATUS_FAILED),
        (UnknownConnection(), STATUS_FAILED),
        (R2ConfigurationError("x"), STATUS_FAILED),
        (RuntimeError("boom"), STATUS_UNKNOWN),
    ]
    for exc, status in cases:
        got_status, message, _ = engine.start_failure(exc, job)
        assert got_status == status
        assert message and "whatsapp" not in message.lower()
    status, message, reconnect = engine.start_failure(
        UnsupportedPlatform(connection_id=uuid.uuid4(), platform="whatsapp"), job
    )
    assert message == (
        "Desde aquí solo publicamos en Instagram. Elige tu cuenta de Instagram e "
        "inténtalo de nuevo."
    )
    assert engine.start_failure(UnknownConnection(), job)[2] is True


def test_an_unsupported_platform_stops_the_run_without_publishing() -> None:
    import uuid

    jobs = engine.plan_jobs(MODE_CAROUSEL, [_img("a"), _img("b")], [""])
    ports = FakePorts(
        fail_on={b"a": UnsupportedPlatform(connection_id=uuid.uuid4(), platform="facebook")}
    )
    records = [JobRecord() for _ in jobs]

    async def report_into(index: int, record: JobRecord) -> bool:
        records[index] = record
        return True

    end = _run(jobs, records, ports, report_into)
    assert end.kind == "failed"
    assert records[0].status == STATUS_FAILED
    assert records[0].reason == engine.UNSUPPORTED_PLATFORM
    assert ports.published == []


def test_the_poll_ceiling_leaves_an_unknown_outcome() -> None:
    class SlowPorts(FakePorts):
        async def poll(self, job: PublishJob, attempt_id: str) -> PublishAttemptVM:
            return _attempt(attempt_id, settled=False)

    jobs = engine.plan_jobs(MODE_POST, [_img("a")], [""])
    records = [JobRecord()]

    async def report_into(index: int, record: JobRecord) -> bool:
        records[index] = record
        return True

    end = asyncio.run(
        engine.run_jobs(
            jobs, records, batch_key="B", ports=SlowPorts(), report=report_into, max_polls=3
        )
    )
    assert end.kind == "failed" and records[0].status == STATUS_UNKNOWN


def test_reports_mark_running_then_settled() -> None:
    jobs = engine.plan_jobs(MODE_POST, [_img("a")], [""])
    seen, report = _collect()
    _run(jobs, [JobRecord()], FakePorts(), report)
    assert seen[0] == (0, STATUS_RUNNING)
    assert seen[-1] == (0, STATUS_PUBLISHED)


def test_piece_statuses_follow_their_job() -> None:
    files = [_img("a"), _img("b"), _img("c")]
    jobs = engine.plan_jobs(MODE_ONE_BY_ONE, files, ["", "", ""])
    records = [JobRecord(status=STATUS_PUBLISHED), JobRecord(status=STATUS_RUNNING), JobRecord()]
    # job 0 is position 2 (the last), job 1 position 1
    assert engine.piece_statuses(jobs, records, 3) == [
        STATUS_WAITING,
        STATUS_RUNNING,
        STATUS_PUBLISHED,
    ]
    carousel = engine.plan_jobs(MODE_CAROUSEL, files, [""])
    assert (
        engine.piece_statuses(carousel, [JobRecord(status=STATUS_PUBLISHED)], 3)
        == [STATUS_PUBLISHED] * 3
    )


def test_a_retried_carousel_key_is_never_published_twice() -> None:
    """The many path: a carousel whose outcome is unknown is resumed with its SAME key;
    the backend (faked: a seen key returns its attempt) never stages it again."""
    jobs = engine.plan_jobs(MODE_CAROUSEL, [_img("a"), _vid("b")], ["texto"])
    ports = FakePorts(fail_on={b"a": "poll"})
    records = [JobRecord()]

    async def report_into(index: int, record: JobRecord) -> bool:
        records[index] = record
        return True

    assert _run(jobs, records, ports, report_into).kind == "failed"
    assert records[0].status == STATUS_UNKNOWN
    ports.fail_on = {}
    assert _run(jobs, records, ports, report_into).kind == "done"
    starts = [key for kind, key, _ in ports.log if kind == "start"]
    assert starts == ["B:0", "B:0"]
    assert len(ports.attempts_by_key) == 1
    assert ports.published == [b"a"]
