"""Bounded downloads of vendor videos inside `creative-worker` (m-24852163).

Platform-engineer's verdict (ticket comment, 2026-10-24): the service must fit in
`mem_limit: 512m`, and ten finished tasks downloading whole videos into memory at once do
not. Both halves of the verdict are here:

- **A cap on simultaneous downloads** (`DownloadGate`, 2 by default, at most 3 —
  `QUALIFY_CREATIVE_WORKER_DOWNLOADS`), apart from the 10 vendor slots: the worker holds
  it around every `JobExecutor.finish` of a succeeded task, the step that downloads.
- **Streaming to a temporary file** (`stream_to_tempfile`): the body is written in chunks
  (1 MiB) and never held whole; the file is removed when the block ends, also on error,
  and a body over `MAX_DOWNLOAD_BYTES` is cut off. Executors upload to R2 from that file.
"""

from __future__ import annotations

import errno
import io
import os
import tempfile
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

import httpx

DOWNLOADS_ENV = "QUALIFY_CREATIVE_WORKER_DOWNLOADS"
DEFAULT_DOWNLOADS = 2
MAX_DOWNLOADS = 3
CHUNK_BYTES = 1024 * 1024
CACHE_WINDOW_BYTES = 16 * CHUNK_BYTES
#: Same ceiling as `creative/media.py` (a 15 s 1080p final is ~10–40 MB).
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024


class DownloadTooLarge(Exception):
    """The vendor's body passed `MAX_DOWNLOAD_BYTES`; nothing is kept."""


def _release_cache(fd: int, offset: int, length: int) -> None:
    # Linux charges file page cache to the container too. This is advisory only;
    # unsupported platforms retain the same byte-for-byte file behavior.
    if hasattr(os, "posix_fadvise"):
        try:
            os.posix_fadvise(fd, offset, length, os.POSIX_FADV_DONTNEED)
        except OSError as exc:
            if exc.errno not in {errno.EINVAL, errno.ENOSYS, errno.EOPNOTSUPP}:
                raise


class UncachedUploadFile(io.FileIO):
    """Seekable upload body; discard already consumed clean pages after each read."""

    def read(self, size: int = -1) -> bytes:
        data = super().read(size)
        if data:
            # Advise the whole consumed prefix. Small per-read ranges cannot evict
            # a large Linux file folio even after every byte in it has been read.
            _release_cache(self.fileno(), 0, self.tell())
        return data


def downloads_allowed(env: Mapping[str, str] | None = None) -> int:
    """The configured cap, clamped to 1–3 (a bad value falls back to the default)."""
    source = os.environ if env is None else env
    raw = (source.get(DOWNLOADS_ENV) or "").strip()
    try:
        value = int(raw) if raw else DEFAULT_DOWNLOADS
    except ValueError:
        value = DEFAULT_DOWNLOADS
    return max(1, min(MAX_DOWNLOADS, value))


class DownloadGate:
    """A bounded semaphore that also remembers the most holders it ever had at once (the
    offline test reads `peak`; the worker logs it)."""

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("a download gate needs at least one place")
        self.limit = limit
        self._semaphore = threading.BoundedSemaphore(limit)
        self._lock = threading.Lock()
        self._holders = 0
        self.peak = 0

    @contextmanager
    def hold(self) -> Iterator[None]:
        with self._semaphore:
            with self._lock:
                self._holders += 1
                self.peak = max(self.peak, self._holders)
            try:
                yield
            finally:
                with self._lock:
                    self._holders -= 1


@contextmanager
def stream_to_tempfile(
    url: str,
    *,
    client: httpx.Client,
    suffix: str = ".mp4",
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    chunk_bytes: int = CHUNK_BYTES,
    directory: str | None = None,
    release_cache: bool = False,
) -> Iterator[Path]:
    """Download `url` in chunks into a temporary file and yield its path; the file is
    deleted when the block ends, whatever happens inside or during the download."""
    handle, name = tempfile.mkstemp(prefix="qualify-vendor-", suffix=suffix, dir=directory)
    path = Path(name)
    try:
        with os.fdopen(handle, "wb") as out, client.stream("GET", url) as response:
            response.raise_for_status()
            written = 0
            cached = 0
            for chunk in response.iter_bytes(chunk_bytes):
                written += len(chunk)
                if written > max_bytes:
                    raise DownloadTooLarge(f"vendor body over {max_bytes} bytes")
                out.write(chunk)
                cached += len(chunk)
                if release_cache and cached >= CACHE_WINDOW_BYTES:
                    out.flush()
                    os.fsync(out.fileno())
                    _release_cache(out.fileno(), 0, 0)
                    cached = 0
            if release_cache:
                out.flush()
                os.fsync(out.fileno())
                _release_cache(out.fileno(), 0, 0)
        yield path
    finally:
        path.unlink(missing_ok=True)
