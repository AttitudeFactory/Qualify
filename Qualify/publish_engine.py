"""The ONE publish engine of «Publicar ahora»: a list of jobs, run strictly in sequence.

Before 2026-11-12 `/publish` carried two near-copies of the same machine —
`PublishState` for a publication and `StoriesState` for a historia — each with its own
toasts, poll loop, poll ceiling and error mapping. Now every mode is a list of
`PublishJob`s and `run_jobs` runs them; the Reflex state only stores what this reports.

- **post / story / carousel** → one job (a carousel job carries all its files).
- **one by one** → one job per file, from the LAST to the FIRST of the owner's list
  (`publish_wizard_vm.execution_order`), each with its own description.
- **stories** → one job per file, in the listed order, no text.

Idempotency (backend contract of 2026-11-12, `qualify_api.publishing`): every press of
«Publicar» mints ONE batch key; job k uses `f"{batch_key}:{k}"`. Reusing a key returns
that job's existing attempt without staging again, so an event that fires twice never
publishes twice. Job k+1 starts only once job k is settled. «Continuar» resumes from the
first job not yet published:

- a job whose attempt settled as **failed** gets a NEW key (`…:k:r1`, `…:k:r2`…);
- a job whose outcome is **unknown** (a poll failed, or the poll ceiling was hit — it may
  still be awaiting Instagram's confirmation) keeps its SAME key, so the backend hands
  back that same attempt and polling simply resumes. Never a new key for it.

Plain Python with injected ports (`start`, `poll`, `sleep`): `test_publish_engine.py`
drives it with in-memory fakes, no Reflex, no network, no R2.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from qualify_api.publishing import (
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_REELS,
    MEDIA_TYPE_STORIES,
    UnsupportedPlatform,
)
from qualify_api.publishing.failure_text import CONNECTION_TEXT
from qualify_api.publishing.service import TooManyItems, UnknownConnection
from qualify_api.publishing.staging import UnsupportedImageFormat
from qualify_shared.objects.config import R2ConfigurationError
from qualify_shared.objects.gate import ObjectSizeExceeded, UnsizedStream
from qualify_shared.objects.keys import TenantPrefixViolation

from .publish_wizard_vm import (
    MODE_CAROUSEL,
    MODE_ONE_BY_ONE,
    MODE_STORIES,
    MODE_STORY,
    STATUS_FAILED,
    STATUS_PUBLISHED,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
    STATUS_WAITING,
    execution_order,
)
from .publishing_vm import PublishAttemptVM

logger = logging.getLogger(__name__)

#: A carousel job's `product` — every other job names its Meta media product type.
PRODUCT_CAROUSEL = "CAROUSEL"

#: Client-side safety net: the SERVER settles an attempt as failed once its own
#: ceiling elapses (`publishing/client.py`); this only guards a runaway loop.
MAX_POLLS = 30

# -- the owner's words for a failure (qualify-copy-es: what happened, what to do) -------

NOT_CONFIGURED = (
    "No podemos subir archivos en este momento. Inténtalo en unos minutos; si sigue, escríbenos."
)
VIDEO_TOO_LARGE = "El video supera el tamaño máximo permitido (300 MB)."
IMAGE_TOO_LARGE = "La imagen supera el tamaño máximo permitido (8 MB)."
BAD_MEDIA = "No se pudo leer el archivo subido. Intenta con otro archivo."
UNSUPPORTED_IMAGE_FORMAT = (
    "Esta foto no se puede usar tal cual. Desde tu celular, compártela como “JPG” o "
    "haz una captura de pantalla y súbela."
)
UNKNOWN_CONNECTION = "Esa cuenta ya no está disponible. Conéctala de nuevo en Tus redes."
UNSUPPORTED_PLATFORM = (
    "Desde aquí solo publicamos en Instagram. Elige tu cuenta de Instagram e inténtalo de nuevo."
)
TOO_MANY = "Un carrusel lleva hasta 10 fotos o videos. Quita alguno e inténtalo de nuevo."
START_FAILED = "No se pudo iniciar la publicación. Vuelve a intentarlo en un momento."
POLL_FAILED = (
    "No sabemos todavía si se publicó. Revisa tu Instagram en unos minutos antes de "
    "volver a intentarlo, para no publicarlo dos veces."
)
NO_TENANT = "No encontramos tu negocio en esta sesión. Cierra sesión y vuelve a entrar."


@dataclass(frozen=True)
class JobFile:
    """One buffered file a job publishes — bytes stay server-side, never a Reflex var."""

    content_type: str
    data: bytes
    media_type: str  # MEDIA_TYPE_IMAGE / MEDIA_TYPE_VIDEO


@dataclass(frozen=True)
class PublishJob:
    """One thing that goes out: a publication, a carousel or a historia.

    `pieces` are the positions (0-based) in the owner's list this job covers — one for
    every job but a carousel, which covers them all — so the screen can mark them."""

    pieces: tuple[int, ...]
    files: tuple[JobFile, ...]
    product: str  # MEDIA_TYPE_IMAGE / REELS / STORIES / PRODUCT_CAROUSEL
    caption: str = ""


@dataclass(frozen=True)
class JobRecord:
    """Where one job stands. `retries` counts the new keys «Continuar» minted for it."""

    status: str = STATUS_WAITING
    key: str = ""
    retries: int = 0
    attempt_id: str = ""
    reason: str = ""
    needs_reconnect: bool = False
    #: The attempt is waiting for Instagram (shown as the polling wait).
    polling: bool = False


@dataclass(frozen=True)
class RunEnd:
    """How `run_jobs` stopped: `done` (every job published), `failed` (job `at` did not
    go out or its outcome is unknown), `stopped` (the owner left: job `at` never
    started) or `superseded` (the screen was reset under the run)."""

    kind: str
    at: int | None = None


class Ports(Protocol):
    """What the engine needs from the outside world."""

    async def start(self, job: PublishJob, key: str) -> PublishAttemptVM: ...

    async def poll(self, job: PublishJob, attempt_id: str) -> PublishAttemptVM: ...

    async def sleep(self, seconds: float) -> None: ...


#: Called after every change of a job's record. Returning False before a job starts
#: stops the run there (the owner left, or the screen was reset).
Report = Callable[[int, JobRecord], Awaitable[bool]]
#: Called once per job that settled as published, with its attempt id (m-25019217:
#: «Publicar» → «Tu semana»). Its failure is logged and swallowed — see `_record`.
OnPublished = Callable[[str], Awaitable[None]]


# -- planning ------------------------------------------------------------------------


def single_product(file: JobFile) -> str:
    """A lone file's Meta product: a photo is IMAGE, a video goes out as a reel."""
    return MEDIA_TYPE_IMAGE if file.media_type == MEDIA_TYPE_IMAGE else MEDIA_TYPE_REELS


def plan_jobs(mode: str, files: Sequence[JobFile], captions: Sequence[str]) -> list[PublishJob]:
    """The jobs for `mode`, in the order they run. `files` and `captions` are in the
    owner's list order (`captions[i]` is file i's own description; for a carousel or a
    single publication only `captions[0]` is used — it is the one description)."""
    if not files:
        return []
    caption = captions[0] if captions else ""
    if mode == MODE_CAROUSEL and len(files) > 1:
        return [
            PublishJob(
                pieces=tuple(range(len(files))),
                files=tuple(files),
                product=PRODUCT_CAROUSEL,
                caption=caption,
            )
        ]
    if mode == MODE_STORY or mode == MODE_STORIES:
        return [
            PublishJob(pieces=(i,), files=(files[i],), product=MEDIA_TYPE_STORIES)
            for i in execution_order(mode, len(files))
        ]
    if mode == MODE_ONE_BY_ONE:
        return [
            PublishJob(
                pieces=(i,),
                files=(files[i],),
                product=single_product(files[i]),
                caption=captions[i] if i < len(captions) else "",
            )
            for i in execution_order(mode, len(files))
        ]
    first = files[0]
    return [PublishJob(pieces=(0,), files=(first,), product=single_product(first), caption=caption)]


# -- keys ----------------------------------------------------------------------------


def job_key(batch_key: str, index: int, retries: int = 0) -> str:
    """`{batch}:{k}` for the first try of job k; `{batch}:{k}:r{n}` for the n-th new key
    «Continuar» minted after a settled failure."""
    base = f"{batch_key}:{index}"
    return base if retries <= 0 else f"{base}:r{retries}"


def key_for(batch_key: str, index: int, record: JobRecord) -> tuple[str, int]:
    """The key (and retry count) job `index` starts with now.

    - never tried → the base key;
    - settled as failed → a NEW key (the earlier attempt is over: retrying it is safe);
    - running / unknown → the SAME key, so the backend returns that attempt and nothing is
      staged or published again (it may still be awaiting Instagram's confirmation);
    - published → its own key (the caller never restarts a published job)."""
    if record.status == STATUS_FAILED:
        retries = record.retries + 1
        return job_key(batch_key, index, retries), retries
    if record.key:
        return record.key, record.retries
    return job_key(batch_key, index, 0), 0


def first_unpublished(records: Sequence[JobRecord]) -> int | None:
    """Where «Continuar» picks up: the first job that has not gone out."""
    for index, record in enumerate(records):
        if record.status != STATUS_PUBLISHED:
            return index
    return None


def can_resume(records: Sequence[JobRecord]) -> bool:
    """Whether «Continuar» may run now: something is left and nothing is in flight."""
    return first_unpublished(records) is not None and all(
        r.status != STATUS_RUNNING for r in records
    )


# -- errors ----------------------------------------------------------------------------


def start_failure(exc: BaseException, job: PublishJob) -> tuple[str, str, bool]:
    """`(status, message, needs_reconnect)` for an exception raised by `start`.

    Every one of these is raised BEFORE an attempt exists (staging, the platform guard,
    the membership check), so the job is a settled failure — except an unexpected
    exception, whose outcome is unknown (it might have been raised after the attempt was
    written), so «Continuar» keeps the same key for it."""
    if isinstance(exc, R2ConfigurationError):
        return STATUS_FAILED, NOT_CONFIGURED, False
    if isinstance(exc, UnsupportedImageFormat):
        return STATUS_FAILED, UNSUPPORTED_IMAGE_FORMAT, False
    if isinstance(exc, ObjectSizeExceeded | UnsizedStream):
        image = len(job.files) == 1 and job.files[0].media_type == MEDIA_TYPE_IMAGE
        return STATUS_FAILED, IMAGE_TOO_LARGE if image else VIDEO_TOO_LARGE, False
    if isinstance(exc, TenantPrefixViolation | ValueError):
        return STATUS_FAILED, BAD_MEDIA, False
    if isinstance(exc, UnknownConnection):
        return STATUS_FAILED, UNKNOWN_CONNECTION, True
    if isinstance(exc, UnsupportedPlatform):
        return STATUS_FAILED, UNSUPPORTED_PLATFORM, False
    if isinstance(exc, TooManyItems):
        return STATUS_FAILED, TOO_MANY, False
    logger.error("publish start failed: %s", type(exc).__name__)
    return STATUS_UNKNOWN, START_FAILED, False


def settled_record(record: JobRecord, attempt: PublishAttemptVM) -> JobRecord:
    """The record once `attempt` settled."""
    if attempt.status == "published":
        return replace(record, status=STATUS_PUBLISHED, polling=False, reason="")
    reason = attempt.reason or START_FAILED
    return replace(
        record,
        status=STATUS_FAILED,
        polling=False,
        reason=reason,
        needs_reconnect=reason == CONNECTION_TEXT,
    )


# -- the run ---------------------------------------------------------------------------


async def _record(on_published: OnPublished | None, attempt_id: str) -> None:
    """Tell the calendar a job went out. Never turns a publication into a failure: the
    owner's post IS on Instagram; a recording that fails here is retried by the calendar
    tick's sweep (`qualify_api.planner.immediate.sweep_recent_publications`)."""
    if on_published is None or not attempt_id:
        return
    try:
        await on_published(attempt_id)
    except Exception as exc:  # noqa: BLE001 — the publication already succeeded
        # the type and the message (a database or lock error — never the caption)
        logger.error(
            "publish record failed attempt_id=%s: %s: %s", attempt_id, type(exc).__name__, exc
        )


async def run_jobs(
    jobs: Sequence[PublishJob],
    records: Sequence[JobRecord],
    *,
    batch_key: str,
    ports: Ports,
    report: Report,
    max_polls: int = MAX_POLLS,
    on_published: OnPublished | None = None,
) -> RunEnd:
    """Run `jobs` one after another from the first one not yet published.

    Each job is started, then polled until it settles; only then does the next start.
    A failure (or an unknown outcome) stops the series there — in a mural, skipping it
    would break the order. `report(j, record)` is awaited after every change; if it
    returns False just before a job starts, the run stops there (`stopped`) — a job
    already started is always followed to its end, never abandoned mid-flight.

    `on_published(attempt_id)` is awaited once for each job that settles as published —
    before its report, so the screen's «listo» follows the recording — and a failure in
    it never changes the job's outcome (`_record`)."""
    start_at = first_unpublished(records)
    if start_at is None:
        return RunEnd("done")
    current = list(records)
    for index in range(start_at, len(jobs)):
        job = jobs[index]
        key, retries = key_for(batch_key, index, current[index])
        record = JobRecord(status=STATUS_RUNNING, key=key, retries=retries)
        current[index] = record
        if not await report(index, record):
            current[index] = replace(record, status=STATUS_WAITING)
            await report(index, current[index])
            return RunEnd("stopped", index)

        try:
            attempt = await ports.start(job, key)
        except Exception as exc:  # noqa: BLE001 — every failure becomes the owner's words
            status, message, reconnect = start_failure(exc, job)
            record = replace(record, status=status, reason=message, needs_reconnect=reconnect)
            current[index] = record
            await report(index, record)
            return RunEnd("failed", index)

        record = replace(record, attempt_id=attempt.attempt_id, polling=not attempt.settled)
        current[index] = record
        await report(index, record)

        polls = 0
        while not attempt.settled:
            if polls >= max_polls:
                record = replace(record, status=STATUS_UNKNOWN, polling=False, reason=POLL_FAILED)
                current[index] = record
                await report(index, record)
                return RunEnd("failed", index)
            if polls:
                await ports.sleep(attempt.poll_interval_seconds)
            polls += 1
            try:
                attempt = await ports.poll(job, record.attempt_id)
            except Exception as exc:  # noqa: BLE001 — unknown outcome: never re-publish
                logger.error("publish poll failed: %s", type(exc).__name__)
                record = replace(record, status=STATUS_UNKNOWN, polling=False, reason=POLL_FAILED)
                current[index] = record
                await report(index, record)
                return RunEnd("failed", index)

        record = settled_record(record, attempt)
        if record.status == STATUS_PUBLISHED:
            await _record(on_published, record.attempt_id)
        current[index] = record
        await report(index, record)
        if record.status != STATUS_PUBLISHED:
            return RunEnd("failed", index)
    return RunEnd("done")


def piece_statuses(
    jobs: Sequence[PublishJob], records: Sequence[JobRecord], count: int
) -> list[str]:
    """Each list position's status, from the job that covers it."""
    statuses = [STATUS_WAITING] * count
    for job, record in zip(jobs, records, strict=False):
        for piece in job.pieces:
            if 0 <= piece < count:
                statuses[piece] = record.status
    return statuses


def published_count(records: Sequence[JobRecord]) -> int:
    return sum(1 for r in records if r.status == STATUS_PUBLISHED)


__all__ = [
    "MAX_POLLS",
    "MODE_ONE_BY_ONE",
    "PRODUCT_CAROUSEL",
    "JobFile",
    "JobRecord",
    "OnPublished",
    "Ports",
    "PublishJob",
    "RunEnd",
    "can_resume",
    "first_unpublished",
    "job_key",
    "key_for",
    "piece_statuses",
    "plan_jobs",
    "published_count",
    "run_jobs",
    "start_failure",
]
