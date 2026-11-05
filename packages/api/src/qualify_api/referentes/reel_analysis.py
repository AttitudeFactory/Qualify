"""Keep a copy of each idea's video in R2 during the weekly run (founder, 2026-11-04), so
«Replicar con mi marca» works all week after the vendor's CDN link dies (24-33 h).

The minimal slice of VE-04a (m-24921056) and VE-12 (m-24921060) the architect specified
for R8 (`docs/traspasos/historias-video-por-partes-backend.md` §VE-04a): no Haiku, no
drain, no `request_analysis`, no badges.

`analyze_run_ideas(charge, sources)` is R4's `analyze` hook (`reel_runs.run(analyze=…)`,
called once a run ends `ok`). For each idea, at `ANALYSIS_VERSION`:

1. **Upsert** its row in `public_reel_analyses` (0119: global, one per reel and version,
   no column says which business asked). A row whose video is still stored is skipped:
   one copy serves every business that gets the reel as an idea.
2. **Claim** it: `running`, a 2-min lease renewed while it works, `attempts + 1`. A live
   lease of another process is left alone; an expired one is taken over by the next run
   that lists the reel. A `failed` row comes back only for `source_expired` /
   `source_unavailable`, with a fresh URL, while `attempts < 3`.
3. **Download** the CDN video like `stream_to_tempfile`: only the vendor's CDN hosts, no
   redirects, at most 80 MiB, sha256 while reading, to a temporary file. A URL read 20 h
   ago or more is not even requested (`source_expired`).
4. **Convert** with PyAV, file to file: at most 60 s, no audio, H.264, at most 1280 px.
5. **Upload** it to `public/reel-analyses/<network>/<post_id>/<id>/source/source.mp4`
   through the public door (`PublicObjectGate`), and leave the row **stored, not
   described**: `queued` with `stage='detecting'`, no lease, `pending_video_url` empty,
   `source_*` set and `source_purge_after` = +30 days (F9; `reel_retention` deletes it).
   Every 0119 CHECK holds; VE-04c's drain will continue from that stage.

A failure ends the row `failed` with its code and never touches the run (the hook's
caller logs and goes on). Every write goes through `reels_worker_session()` (0119 grants
the role INSERT and UPDATE on these tables); `qualify_app` only reads. Server-side only:
no URL, presigned link or route points at the copy. Nothing here calls a paid service.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

import httpx
from qualify_shared.objects import public_source_key
from sqlalchemy import text

from qualify_api.referentes.reel_reference import source_allowed
from qualify_api.referentes.reel_runs import IdeaSource, RunInterrupted
from qualify_api.referentes.reel_store import VIDEO_URL_FRESH

logger = logging.getLogger(__name__)

#: The version of what this slice writes (a stored source, not yet described).
ANALYSIS_VERSION = 1
#: VE-04a: a 2-min lease, renewed while the work goes on.
LEASE = timedelta(minutes=2)
LEASE_RENEW_EVERY = timedelta(seconds=40)
#: VE-04a: the download ceiling (same as `reel_reference.MAX_BYTES`) and the stored copy.
MAX_SOURCE_BYTES = 80 * 1024 * 1024
MAX_SOURCE_SECONDS = 60
MAX_SIDE = 1280
#: ADR 44 F9: the copy of a reel that is not ours is deleted 30 days after it was made.
SOURCE_KEPT_FOR = timedelta(days=30)
#: A failed row is tried again only for these codes, and only while `attempts < 3`.
MAX_ATTEMPTS = 3
RETRYABLE_CODES = frozenset({"source_expired", "source_unavailable"})
DOWNLOAD_TIMEOUT_SECONDS = 30.0
CHUNK_BYTES = 1024 * 1024
#: Fast enough for a 60 s reel on the VPS, small enough to store: a reference, not a final.
#: Two threads each for x264 and the decoder: their buffers grow with the thread count, so
#: the peak no longer depends on how many cores the host has (measured, see `transcode`).
X264 = {"preset": "veryfast", "crf": "26", "threads": "2"}
DECODE_THREADS = 2

_STORED_STAGE = "detecting"


# --------------------------------------------------------------------------------------
# what fails, and with which 0119 error code
# --------------------------------------------------------------------------------------


class SourceFailure(Exception):
    code = "source_unavailable"


class SourceExpired(SourceFailure):
    code = "source_expired"


class SourceUnavailable(SourceFailure):
    code = "source_unavailable"


class SourceTooLarge(SourceFailure):
    code = "source_too_large"


class SourceUnreadable(SourceFailure):
    code = "source_unreadable"


class LeaseLost(Exception):
    """Another process took the row over (this one's lease had expired): stop, write
    nothing more."""


# --------------------------------------------------------------------------------------
# the rows
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunCharge:
    """The run whose ideas these are (VE-04a's `RunCharge`). Nothing here costs money in
    this slice, so it only names the run in the log."""

    tenant_id: UUID
    brand_id: UUID
    run_id: UUID


@dataclass(frozen=True)
class AnalysisRow:
    id: UUID
    network: str
    post_id: str
    status: str
    stage: str | None
    lease_token: UUID | None
    lease_until: datetime | None
    attempts: int
    error_code: str | None
    source_key: str | None
    source_purge_after: datetime | None
    source_purged_at: datetime | None

    @property
    def video_stored(self) -> bool:
        return self.source_key is not None and self.source_purged_at is None


@dataclass(frozen=True)
class StoredSource:
    """The copy as uploaded, and what the row records about it."""

    key: str
    sha256: str
    seconds: float
    width: int
    height: int
    fps: float
    edit_eligible: bool


class AnalysisStore(Protocol):
    def upsert(
        self, network: str, post_id: str, *, post_url: str, video_url: str | None
    ) -> AnalysisRow:
        """The reel's row at `ANALYSIS_VERSION`, created `queued` when missing."""
        ...

    def requeue(self, row_id: UUID, *, video_url: str) -> bool:
        """A `failed` row with a retryable code and attempts left goes back to `queued`
        with the fresh URL."""
        ...

    def claim(self, row_id: UUID, *, token: UUID, now: datetime) -> AnalysisRow | None:
        """`queued`, or `running` with an expired lease, with attempts left → `running`
        (`downloading`, a new lease, `attempts + 1`); None otherwise."""
        ...

    def renew(self, row_id: UUID, *, token: UUID, until: datetime) -> bool: ...

    def fail(self, row_id: UUID, *, token: UUID, code: str, now: datetime) -> bool: ...

    def stored(self, row_id: UUID, *, token: UUID, source: StoredSource, now: datetime) -> bool:
        """The row becomes «stored, not described» (see the module docstring)."""
        ...

    def due_for_purge(
        self, *, now: datetime, limit: int, after: tuple[datetime, UUID] | None = None
    ) -> list[AnalysisRow]:
        """Rows whose copy is due (`source_purge_after <= now`, not purged yet), in
        `(source_purge_after, id)` order after `after`."""
        ...

    def mark_purged(self, row_id: UUID, *, now: datetime) -> bool: ...


# ======================================================================================
# In memory — the offline twin
# ======================================================================================


@dataclass
class _MemoryRow:
    row: AnalysisRow
    post_url: str
    pending_video_url: str | None
    values: dict[str, Any] = field(default_factory=dict)


class MemoryAnalysisStore:
    """`AnalysisStore` in process memory, with the same guards as Postgres (and a record of
    every value the Postgres store would write, for the tests)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.rows: dict[UUID, _MemoryRow] = {}

    def _find(self, network: str, post_id: str) -> _MemoryRow | None:
        return next(
            (r for r in self.rows.values() if (r.row.network, r.row.post_id) == (network, post_id)),
            None,
        )

    def upsert(
        self, network: str, post_id: str, *, post_url: str, video_url: str | None
    ) -> AnalysisRow:
        with self._lock:
            found = self._find(network, post_id)
            if found is None:
                found = _MemoryRow(
                    row=AnalysisRow(
                        uuid4(),
                        network,
                        post_id,
                        "queued",
                        None,
                        None,
                        None,
                        0,
                        None,
                        None,
                        None,
                        None,
                    ),
                    post_url=post_url,
                    pending_video_url=video_url,
                )
                self.rows[found.row.id] = found
            return found.row

    def _set(self, row_id: UUID, **values: Any) -> None:
        item = self.rows[row_id]
        pending = values.pop("pending_video_url", item.pending_video_url)
        own = {k: v for k, v in values.items() if k in AnalysisRow.__dataclass_fields__}
        item.row = replace(item.row, **own)
        item.pending_video_url = pending
        item.values.update(values)

    def requeue(self, row_id: UUID, *, video_url: str) -> bool:
        with self._lock:
            row = self.rows[row_id].row
            if not (
                row.status == "failed"
                and row.error_code in RETRYABLE_CODES
                and row.attempts < MAX_ATTEMPTS
            ):
                return False
            self._set(row_id, status="queued", error_code=None, stage=None)
            self._set(row_id, pending_video_url=video_url, finished_at=None)
            return True

    def claim(self, row_id: UUID, *, token: UUID, now: datetime) -> AnalysisRow | None:
        with self._lock:
            row = self.rows[row_id].row
            takeover = row.status == "running" and (row.lease_until or now) < now
            if row.attempts >= MAX_ATTEMPTS or not (row.status == "queued" or takeover):
                return None
            self._set(
                row_id,
                status="running",
                stage="downloading",
                lease_token=token,
                lease_until=now + LEASE,
                attempts=row.attempts + 1,
                error_code=None,
            )
            return self.rows[row_id].row

    def _mine(self, row_id: UUID, token: UUID) -> bool:
        row = self.rows[row_id].row
        return row.status == "running" and row.lease_token == token

    def renew(self, row_id: UUID, *, token: UUID, until: datetime) -> bool:
        with self._lock:
            if not self._mine(row_id, token):
                return False
            self._set(row_id, lease_until=until)
            return True

    def fail(self, row_id: UUID, *, token: UUID, code: str, now: datetime) -> bool:
        with self._lock:
            if not self._mine(row_id, token):
                return False
            self._set(
                row_id,
                status="failed",
                error_code=code,
                lease_token=None,
                lease_until=None,
                pending_video_url=None,
                finished_at=now,
            )
            return True

    def stored(self, row_id: UUID, *, token: UUID, source: StoredSource, now: datetime) -> bool:
        with self._lock:
            if not self._mine(row_id, token):
                return False
            self._set(
                row_id,
                status="queued",
                stage=_STORED_STAGE,
                lease_token=None,
                lease_until=None,
                pending_video_url=None,
                error_code=None,
                source_key=source.key,
                source_sha256=source.sha256,
                source_seconds=source.seconds,
                width=source.width,
                height=source.height,
                fps=source.fps,
                covered_from_s=0,
                covered_to_s=source.seconds,
                edit_eligible=source.edit_eligible,
                source_purge_after=now + SOURCE_KEPT_FOR,
                source_purged_at=None,
                frames_purged_at=None,
            )
            return True

    def due_for_purge(
        self, *, now: datetime, limit: int, after: tuple[datetime, UUID] | None = None
    ) -> list[AnalysisRow]:
        due = sorted(
            (
                r.row
                for r in self.rows.values()
                if r.row.source_purged_at is None
                and r.row.source_purge_after is not None
                and r.row.source_purge_after <= now
            ),
            key=lambda r: (r.source_purge_after, str(r.id)),
        )
        if after is not None:
            due = [r for r in due if (r.source_purge_after, str(r.id)) > (after[0], str(after[1]))]
        return due[:limit]

    def mark_purged(self, row_id: UUID, *, now: datetime) -> bool:
        with self._lock:
            if self.rows[row_id].row.source_purged_at is not None:
                return False
            self._set(row_id, source_purged_at=now, frames_purged_at=now)
            return True


# ======================================================================================
# Postgres — every statement through the reels-worker's door
# ======================================================================================

_COLUMNS = (
    "id, network, post_id, status, stage, lease_token, lease_until, attempts, error_code, "
    "source_key, source_purge_after, source_purged_at"
)


def _row(row: Any) -> AnalysisRow:
    return AnalysisRow(**dict(row._mapping))


class PostgresAnalysisStore:
    """`AnalysisStore` over 0119's `public_reel_analyses`, through `reels_worker_session()`
    (`qualify_reels_worker`: SELECT, INSERT, UPDATE, DELETE on the two global analysis
    tables, nothing else of them for `qualify_app` but SELECT)."""

    def _session(self) -> Any:
        # Imported on use: the door opens no socket at import, and the static test pins
        # who names it (`test_reels_worker_door_sanctity.py`).
        from qualify_shared.db.reels_worker import reels_worker_session  # noqa: PLC0415

        return reels_worker_session()

    def _one(self, sql: str, params: dict[str, Any]) -> Any:
        with self._session() as session:
            return session.execute(text(sql), params).first()

    def upsert(
        self, network: str, post_id: str, *, post_url: str, video_url: str | None
    ) -> AnalysisRow:
        params = {
            "network": network,
            "post_id": post_id,
            "version": ANALYSIS_VERSION,
            "post_url": post_url,
            "video_url": video_url,
        }
        with self._session() as session:
            session.execute(
                text(
                    "INSERT INTO public_reel_analyses (network, post_id, analysis_version, "
                    "post_url, pending_video_url) VALUES (:network, :post_id, :version, "
                    ":post_url, :video_url) "
                    "ON CONFLICT ON CONSTRAINT uq_public_reel_analysis DO NOTHING"
                ),
                params,
            )
            row = session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM public_reel_analyses WHERE network = :network "
                    "AND post_id = :post_id AND analysis_version = :version"
                ),
                params,
            ).first()
        return _row(row)

    def requeue(self, row_id: UUID, *, video_url: str) -> bool:
        return (
            self._one(
                "UPDATE public_reel_analyses SET status = 'queued', error_code = NULL, "
                "stage = NULL, pending_video_url = :url, finished_at = NULL "
                "WHERE id = :id AND status = 'failed' AND error_code = ANY(:codes) "
                "AND attempts < :max RETURNING id",
                {
                    "id": row_id,
                    "url": video_url,
                    "codes": sorted(RETRYABLE_CODES),
                    "max": MAX_ATTEMPTS,
                },
            )
            is not None
        )

    def claim(self, row_id: UUID, *, token: UUID, now: datetime) -> AnalysisRow | None:
        row = self._one(
            "UPDATE public_reel_analyses SET status = 'running', stage = 'downloading', "
            "lease_token = :token, lease_until = :until, attempts = attempts + 1, "
            "error_code = NULL WHERE id = :id AND attempts < :max "
            "AND (status = 'queued' OR (status = 'running' AND lease_until < :now)) "
            f"RETURNING {_COLUMNS}",
            {"id": row_id, "token": token, "until": now + LEASE, "now": now, "max": MAX_ATTEMPTS},
        )
        return _row(row) if row is not None else None

    _MINE = "id = :id AND status = 'running' AND lease_token = :token"

    def renew(self, row_id: UUID, *, token: UUID, until: datetime) -> bool:
        return (
            self._one(
                f"UPDATE public_reel_analyses SET lease_until = :until WHERE {self._MINE} "
                "RETURNING id",
                {"id": row_id, "token": token, "until": until},
            )
            is not None
        )

    def fail(self, row_id: UUID, *, token: UUID, code: str, now: datetime) -> bool:
        return (
            self._one(
                "UPDATE public_reel_analyses SET status = 'failed', error_code = :code, "
                "lease_token = NULL, lease_until = NULL, pending_video_url = NULL, "
                f"finished_at = :now WHERE {self._MINE} RETURNING id",
                {"id": row_id, "token": token, "code": code, "now": now},
            )
            is not None
        )

    def stored(self, row_id: UUID, *, token: UUID, source: StoredSource, now: datetime) -> bool:
        return (
            self._one(
                "UPDATE public_reel_analyses SET status = 'queued', stage = :stage, "
                "lease_token = NULL, lease_until = NULL, pending_video_url = NULL, "
                "error_code = NULL, source_key = :key, source_sha256 = :sha, "
                "source_seconds = :seconds, width = :width, height = :height, fps = :fps, "
                "covered_from_s = 0, covered_to_s = :seconds, edit_eligible = :edit, "
                "source_purge_after = :purge, source_purged_at = NULL, "
                f"frames_purged_at = NULL WHERE {self._MINE} RETURNING id",
                {
                    "id": row_id,
                    "token": token,
                    "stage": _STORED_STAGE,
                    "key": source.key,
                    "sha": source.sha256,
                    "seconds": source.seconds,
                    "width": source.width,
                    "height": source.height,
                    "fps": source.fps,
                    "edit": source.edit_eligible,
                    "purge": now + SOURCE_KEPT_FOR,
                },
            )
            is not None
        )

    def due_for_purge(
        self, *, now: datetime, limit: int, after: tuple[datetime, UUID] | None = None
    ) -> list[AnalysisRow]:
        where = "source_purged_at IS NULL AND source_purge_after IS NOT NULL "
        where += "AND source_purge_after <= :now"
        params: dict[str, Any] = {"now": now, "limit": limit}
        if after is not None:
            where += " AND (source_purge_after, id) > (:after_at, :after_id)"
            params.update(after_at=after[0], after_id=after[1])
        with self._session() as session:
            rows = session.execute(
                text(
                    f"SELECT {_COLUMNS} FROM public_reel_analyses WHERE {where} "
                    "ORDER BY source_purge_after, id LIMIT :limit"
                ),
                params,
            ).all()
        return [_row(r) for r in rows]

    def mark_purged(self, row_id: UUID, *, now: datetime) -> bool:
        return (
            self._one(
                "UPDATE public_reel_analyses SET source_purged_at = :now, frames_purged_at = :now "
                "WHERE id = :id AND source_purged_at IS NULL RETURNING id",
                {"id": row_id, "now": now},
            )
            is not None
        )


# ======================================================================================
# The work: lease, download, convert
# ======================================================================================


class _Lease:
    """The row's lease, renewed every `LEASE_RENEW_EVERY` from inside the long loops."""

    def __init__(
        self, store: AnalysisStore, row_id: UUID, token: UUID, clock: Callable[[], datetime]
    ) -> None:
        self.store, self.row_id, self.token, self._clock = store, row_id, token, clock
        self._renewed = clock()

    def keep(self) -> None:
        now = self._clock()
        if now - self._renewed < LEASE_RENEW_EVERY:
            return
        if not self.store.renew(self.row_id, token=self.token, until=now + LEASE):
            raise LeaseLost(str(self.row_id))
        self._renewed = now


@contextmanager
def download(
    url: str, *, client: httpx.Client, keep: Callable[[], None]
) -> Iterator[tuple[Path, str]]:
    """The video at `url` in a temporary file, and its sha256: no redirects, at most
    `MAX_SOURCE_BYTES`, written and hashed in chunks (never held whole). The file is
    removed when the block ends, also on error. Raises `SourceUnavailable` /
    `SourceTooLarge`."""
    handle, name = tempfile.mkstemp(prefix="qualify-reel-", suffix=".mp4")
    path = Path(name)
    digest = hashlib.sha256()
    try:
        with os.fdopen(handle, "wb") as out:
            try:
                with client.stream("GET", url, follow_redirects=False) as response:
                    if response.status_code != 200:  # a redirect included
                        raise SourceUnavailable(f"HTTP {response.status_code}")
                    declared = response.headers.get("content-length", "")
                    if declared.isdigit() and int(declared) > MAX_SOURCE_BYTES:
                        raise SourceTooLarge("declared over the ceiling")
                    size = 0
                    for chunk in response.iter_bytes(CHUNK_BYTES):
                        size += len(chunk)
                        if size > MAX_SOURCE_BYTES:
                            raise SourceTooLarge("over the ceiling")
                        digest.update(chunk)
                        out.write(chunk)
                        keep()
            except httpx.HTTPError as exc:
                raise SourceUnavailable(type(exc).__name__) from None
        yield path, digest.hexdigest()
    finally:
        path.unlink(missing_ok=True)


def fitted_size(width: int, height: int) -> tuple[int, int]:
    """At most `MAX_SIDE` on the longer side, the aspect kept, even (H.264)."""
    scale = min(1.0, MAX_SIDE / max(width, height))
    w, h = round(width * scale), round(height * scale)
    return max(2, w - w % 2), max(2, h - h % 2)


def _frame_rate(stream: Any) -> Fraction:
    rate = stream.average_rate or stream.guessed_rate
    value = Fraction(rate) if rate else Fraction(30)
    return value if 0 < value <= 60 else Fraction(30)


def transcode(source: Path, target: Path, *, keep: Callable[[], None]) -> StoredSource:
    """`source` → `target`, file to file, one frame in memory at a time: at most
    `MAX_SOURCE_SECONDS`, no audio, H.264 `yuv420p` (`+faststart`), at most `MAX_SIDE` px.
    The returned `StoredSource` has no key nor sha256 yet. `SourceUnreadable` when PyAV
    cannot read it."""
    import av  # noqa: PLC0415 — lazy: only the reels-worker decodes reels

    try:
        with av.open(str(source)) as container:
            if not container.streams.video:
                raise SourceUnreadable("no video stream")
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            stream.codec_context.thread_count = DECODE_THREADS
            width, height = stream.codec_context.width, stream.codec_context.height
            if not width or not height:
                raise SourceUnreadable("no frame size")
            rate = _frame_rate(stream)
            size = fitted_size(width, height)
            base = stream.time_base
            origin = stream.start_time * base if stream.start_time is not None and base else 0
            tick = Fraction(1) / rate
            limit = MAX_SOURCE_SECONDS * rate
            frames = 0
            with av.open(
                str(target), mode="w", format="mp4", options={"movflags": "+faststart"}
            ) as sink:
                encoder = sink.add_stream("libx264", rate=rate)
                encoder.width, encoder.height = size
                encoder.pix_fmt = "yuv420p"
                encoder.options = dict(X264)
                # stamped by hand: a frame without pts is written at time 0
                encoder.codec_context.time_base = tick
                for frame in container.decode(stream):
                    if frame.pts is not None and base is not None:
                        if frame.pts * base - origin >= MAX_SOURCE_SECONDS:
                            break
                    elif frames >= limit:
                        break
                    picture = frame.reformat(width=size[0], height=size[1], format="yuv420p")
                    picture.pts = frames
                    picture.time_base = tick
                    for packet in encoder.encode(picture):
                        sink.mux(packet)
                    frames += 1
                    if frames % 30 == 0:
                        keep()
                for packet in encoder.encode():
                    sink.mux(packet)
    except (SourceUnreadable, LeaseLost):
        raise
    except Exception as exc:  # noqa: BLE001 — PyAV raises many kinds for a bad file
        raise SourceUnreadable(type(exc).__name__) from None
    if not frames:
        raise SourceUnreadable("no frames")
    fps = float(rate)
    seconds = min(float(MAX_SOURCE_SECONDS), round(frames / fps, 3))
    return StoredSource(
        key="",
        sha256="",
        seconds=seconds,
        width=size[0],
        height=size[1],
        fps=round(fps, 3),
        edit_eligible=24 <= fps <= 60,
    )


# ======================================================================================
# The hook
# ======================================================================================


DescribeFn = Callable[[UUID], None]


def _fresh(source: IdeaSource, now: datetime) -> bool:
    read_at = source.video_url_at
    return bool(source.video_url) and read_at is not None and now - read_at < VIDEO_URL_FRESH


def keep_source(
    source: IdeaSource,
    *,
    store: AnalysisStore,
    gate: Any,
    client: httpx.Client,
    clock: Callable[[], datetime],
    describe: DescribeFn | None = None,
) -> str:
    """Steps 1-5 of the module docstring for one idea; returns what happened (logged)."""
    now = clock()
    row = store.upsert(
        source.network, source.post_id, post_url=source.post_url, video_url=source.video_url
    )
    if row.video_stored:
        return "already_stored"
    if row.status == "failed":
        if not (_fresh(source, now) and store.requeue(row.id, video_url=source.video_url)):
            return f"failed:{row.error_code}"
    elif row.status == "ok":
        return "described"
    token = uuid4()
    claimed = store.claim(row.id, token=token, now=now)
    if claimed is None:
        return "busy"
    lease = _Lease(store, row.id, token, clock)
    try:
        if not _fresh(source, now):
            raise SourceExpired("the CDN URL is 20 h old or more")
        if not source_allowed(source.network, source.video_url):
            raise SourceUnavailable("not a CDN host of the network")
        key = public_source_key(source.network, source.post_id, row.id)
        with download(source.video_url, client=client, keep=lease.keep) as (raw, sha256):
            with tempfile.TemporaryDirectory(prefix="qualify-reel-out-") as folder:
                target = Path(folder) / "source.mp4"
                shape = transcode(raw, target, keep=lease.keep)
                lease.keep()
                with target.open("rb") as body:
                    gate.put_public(key, body, "video/mp4")
        stored = replace(shape, key=key, sha256=sha256)
        if not store.stored(row.id, token=token, source=stored, now=clock()):
            raise LeaseLost(str(row.id))
    except SourceFailure as exc:
        store.fail(row.id, token=token, code=exc.code, now=clock())
        logger.info("reel source %s:%s not kept: %s", source.network, source.post_id, exc.code)
        return f"failed:{exc.code}"
    except LeaseLost:
        logger.warning(
            "reel source %s:%s taken over by another worker", source.network, source.post_id
        )
        return "lease_lost"
    if describe is not None:
        describe(row.id)
    return "stored"


def analyze_run_ideas(
    charge: RunCharge,
    sources: Sequence[IdeaSource],
    *,
    describe: DescribeFn | None = None,
    store: AnalysisStore | None = None,
    gate: Any = None,
    client: httpx.Client | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Decimal:
    """R4's `analyze` hook: keep each idea's video (see the module docstring). Returns
    what it cost — nothing, in this slice. One idea that fails never stops the others;
    `RunInterrupted` (the worker's SIGTERM) goes through."""
    active = store or PostgresAnalysisStore()
    the_gate = gate if gate is not None else production_gate()
    owned = client is None
    http = client or httpx.Client(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=False)
    outcomes: dict[str, int] = {}
    try:
        for source in sources:
            try:
                outcome = keep_source(
                    source, store=active, gate=the_gate, client=http, clock=clock, describe=describe
                )
            except RunInterrupted:
                raise
            except Exception:  # noqa: BLE001 — one idea never stops the others
                logger.exception("reel source %s:%s failed", source.network, source.post_id)
                outcome = "error"
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
    finally:
        if owned:
            http.close()
    logger.info("reels run %s: idea videos %s", charge.run_id, outcomes)
    return Decimal("0")


def production_gate() -> Any:
    """The public R2 door from the environment (`QUALIFY_R2_*`, the shared env file)."""
    from qualify_shared.objects import PublicObjectGate  # noqa: PLC0415
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return PublicObjectGate(R2ObjectStore(R2Settings.from_env()))


class RunHook:
    """The `analyze` the reels-worker passes to `reel_runs.run`: `analyze_run_ideas` with
    the production store and gate, built on first use (`client`, `clock`: tests)."""

    def __init__(
        self,
        *,
        store: AnalysisStore | None = None,
        gate: Any = None,
        client: httpx.Client | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store, self._gate, self._client, self._clock = store, gate, client, clock

    def __call__(
        self, tenant_id: UUID, brand_id: UUID, run_id: UUID, sources: Sequence[IdeaSource]
    ) -> Decimal:
        if self._gate is None:
            self._gate = production_gate()
        if self._store is None:
            self._store = PostgresAnalysisStore()
        return analyze_run_ideas(
            RunCharge(tenant_id, brand_id, run_id),
            sources,
            store=self._store,
            gate=self._gate,
            client=self._client,
            clock=self._clock,
        )


__all__ = [
    "ANALYSIS_VERSION",
    "LEASE",
    "MAX_SIDE",
    "MAX_SOURCE_BYTES",
    "MAX_SOURCE_SECONDS",
    "SOURCE_KEPT_FOR",
    "AnalysisRow",
    "AnalysisStore",
    "LeaseLost",
    "MemoryAnalysisStore",
    "PostgresAnalysisStore",
    "RunCharge",
    "RunHook",
    "SourceExpired",
    "SourceFailure",
    "SourceTooLarge",
    "SourceUnavailable",
    "SourceUnreadable",
    "StoredSource",
    "analyze_run_ideas",
    "download",
    "fitted_size",
    "keep_source",
    "production_gate",
    "transcode",
]
