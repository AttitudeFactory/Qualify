"""The Galería's waiting room on the shared `uploads` volume (m-24955918, ADR 47 §4.3).

A 60 s phone video is up to ~400 MB. It must never be held in memory nor copied whole to
`/tmp` before anyone can refuse it, so the Reflex screen (CM-2) uses the background
upload handler with `UploadChunkIterator` and hands the chunks to `stage_chunks`, which:

- writes each file to `uploads/{tenant}/gallery-staging/{upload_id}` 1 MiB at a time,
  computing its SHA-256 on the way (the ingest idempotency key);
- **stops writing and deletes the partial file the moment a file passes
  `MAX_UPLOAD_BYTES`** (500 MB, the same number as the picker's `max_size` and Caddy's
  `request_body max_size 500MB` on `/_upload*`); the rest of that file's chunks are
  read off the wire and dropped, never written;
- accepts at most `max_videos` videos (the «3 videos waiting» rule is checked before the
  upload starts; this is the last line).

`media-worker` reads the staged file by its relative path (`gallery_jobs.staged_path`)
and deletes it once the medium is in R2; the daily reconciler deletes anything older
than 24 h that no active job points at (an upload abandoned half-way).
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import AsyncIterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from qualify_creative.video import is_video_filename

logger = logging.getLogger(__name__)

#: 500 MB in Caddy's decimal sense (`500MB` = 500 × 10⁶ bytes), ADR 47 §4.3.
MAX_UPLOAD_BYTES = 500_000_000
STAGING_DIRNAME = "gallery-staging"

OUTCOME_STAGED = "staged"
OUTCOME_TOO_LARGE = "too_large"
OUTCOME_NO_SLOT = "no_slot"
OUTCOME_EMPTY = "empty"
OUTCOME_FULL = "full"

_RELPATH = re.compile(
    r"uploads/(?P<tenant>[0-9a-f-]{36})/" + STAGING_DIRNAME + r"/(?P<upload>[0-9a-f-]{36})"
)


class ChunkLike(Protocol):
    """What Reflex's `UploadChunk` carries: `filename`, `data` and `offset` (the chunk's
    position inside its file — every multipart part starts at 0, which is how two files
    with the same name in one upload are told apart; `content_type` is unused)."""

    filename: str
    data: bytes
    offset: int


@dataclass(frozen=True)
class StagedFile:
    """One file of an upload. `relpath` is set only when `outcome == "staged"`."""

    filename: str
    outcome: str
    bytes: int
    sha256: str = ""
    relpath: str = ""
    upload_id: UUID | None = None

    @property
    def is_video(self) -> bool:
        return is_video_filename(self.filename)


def staging_relpath(tenant_id: UUID, upload_id: UUID) -> str:
    return f"uploads/{tenant_id}/{STAGING_DIRNAME}/{upload_id}"


def staging_dir(root: Path, tenant_id: UUID) -> Path:
    return root / "uploads" / str(tenant_id) / STAGING_DIRNAME


def resolve_staged(root: Path, tenant_id: UUID, relpath: str) -> Path:
    """The absolute path of a staged file of THIS tenant; raise for anything else (a
    path read back from a row is still input)."""
    match = _RELPATH.fullmatch(relpath or "")
    if match is None or UUID(match["tenant"]) != tenant_id:
        raise ValueError("not a staged upload of this tenant")
    UUID(match["upload"])
    return root / relpath


class _Writer:
    def __init__(self, root: Path, tenant_id: UUID, filename: str, max_bytes: int) -> None:
        self.filename = filename
        self.upload_id = uuid4()
        self.relpath = staging_relpath(tenant_id, self.upload_id)
        self.path = root / self.relpath
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("wb")
        self._digest = hashlib.sha256()
        self._max = max_bytes
        self.size = 0
        self.cut = False

    def write(self, data: bytes) -> None:
        if self.cut or not data:
            return
        if self.size + len(data) > self._max:
            self.cut = True
            self.size += len(data)
            self.discard()
            return
        self._fh.write(data)
        self._digest.update(data)
        self.size += len(data)

    def discard(self) -> None:
        if not self._fh.closed:
            self._fh.close()
        self.path.unlink(missing_ok=True)

    def finish(self) -> StagedFile:
        if self.cut:
            return StagedFile(self.filename, OUTCOME_TOO_LARGE, self.size)
        self._fh.close()
        if self.size == 0:
            self.path.unlink(missing_ok=True)
            return StagedFile(self.filename, OUTCOME_EMPTY, 0)
        return StagedFile(
            self.filename,
            OUTCOME_STAGED,
            self.size,
            sha256=self._digest.hexdigest(),
            relpath=self.relpath,
            upload_id=self.upload_id,
        )


async def stage_chunks(
    chunks: AsyncIterable[ChunkLike],
    *,
    root: Path,
    tenant_id: UUID,
    max_videos: int,
    max_files: int | None = None,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> list[StagedFile]:
    """Write every file of a chunked upload to the waiting room; one `StagedFile` per
    file, in upload order. A file begins when the name changes or a chunk's `offset` is 0
    (multipart parts arrive one after the other), so two files that share a name stay two
    files. Videos beyond `max_videos` are `no_slot`; any file beyond `max_files` (the
    Galería's free places) is `full`. A failure mid-stream (the owner closed the screen,
    the connection dropped) deletes every partial file it wrote and re-raises."""
    results: list[_Writer | StagedFile] = []
    current: _Writer | StagedFile | None = None
    current_name: str | None = None
    videos = files = 0
    try:
        async for chunk in chunks:
            name = chunk.filename or ""
            offset = getattr(chunk, "offset", None)
            starts = current is None or name != current_name or offset == 0
            if starts:
                current_name = name
                if max_files is not None and files >= max_files:
                    current = StagedFile(name, OUTCOME_FULL, 0)
                elif is_video_filename(name) and videos >= max_videos:
                    current = StagedFile(name, OUTCOME_NO_SLOT, 0)
                else:
                    files += 1
                    videos += 1 if is_video_filename(name) else 0
                    current = _Writer(root, tenant_id, name, max_bytes)
                results.append(current)
            if isinstance(current, _Writer):
                current.write(chunk.data)
    except BaseException:
        for item in results:
            if isinstance(item, _Writer):
                item.discard()
        raise
    return [item.finish() if isinstance(item, _Writer) else item for item in results]


def discard_staged(root: Path, tenant_id: UUID, relpath: str) -> None:
    """Delete one staged file (refused, duplicated or already in R2). Never raises for a
    file that is already gone."""
    try:
        resolve_staged(root, tenant_id, relpath).unlink(missing_ok=True)
    except (OSError, ValueError):
        logger.warning("gallery.staging.discard_failed tenant=%s", tenant_id)
