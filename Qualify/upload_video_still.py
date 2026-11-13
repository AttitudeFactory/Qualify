"""The facts (display size, duration) and a JPEG poster of a video the owner picked in
«Subir foto o video» (m-25026481), read from the upload's spooled file without ever
holding the video in Python memory.

`qualify_creative.video.video_still` runs ffprobe/ffmpeg on a PATH. What Reflex hands an
upload handler (0.10, `reflex_components_core.core._upload`) is Starlette's
`SpooledTemporaryFile(max_size=1 MB)`: an `io.BytesIO` up to 1 MB, then an anonymous
`tempfile.TemporaryFile` — `O_TMPFILE` on Linux, created and unlinked at once on macOS —
so there is NO path to give ffmpeg on either platform. The file is therefore copied, in
1 MB chunks (constant memory), to a named temporary file that is deleted in a `finally`,
and the spooled file's position is put back for whoever reads it next (`save_upload`).

Everything runs inside the process's one heavy-media slot (`heavy_media`): the copy and
the two ffmpeg children together, on a worker thread. When the slot is not free within
`VIDEO_STILL_WAIT_SECONDS` the still is simply skipped (None): it is optional, the video
is kept anyway.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import IO

from qualify_creative.video import VideoStill, video_still

from .heavy_media import heavy_media_slot, run_heavy_in_thread

logger = logging.getLogger(__name__)

#: How long a picked video waits for the heavy-media slot before its poster/duration are
#: skipped. Short: the owner is looking at «Subiendo…», and the still is optional.
VIDEO_STILL_WAIT_SECONDS = 5.0
#: The copy to a named file reads this much at a time — the only video bytes ever held.
COPY_CHUNK_BYTES = 1024 * 1024


def copy_spooled(fileobj: IO[bytes], out: IO[bytes]) -> int:
    """Blocking: the whole spooled file into `out`, `COPY_CHUNK_BYTES` at a time; the
    position of `fileobj` is put back. Returns the bytes copied."""
    here = fileobj.tell()
    copied = 0
    try:
        fileobj.seek(0)
        while chunk := fileobj.read(COPY_CHUNK_BYTES):
            out.write(chunk)
            copied += len(chunk)
    finally:
        fileobj.seek(here)
    return copied


def still_from_spooled(fileobj: IO[bytes], suffix: str) -> VideoStill:
    """Blocking: copy to a named temporary file, run `video_still` on it, delete it."""
    fd, raw = tempfile.mkstemp(prefix="qualify-still-", suffix=suffix)
    path = Path(raw)
    try:
        with os.fdopen(fd, "wb") as out:
            copy_spooled(fileobj, out)
        return video_still(path)
    finally:
        path.unlink(missing_ok=True)


async def video_still_when_free(
    fileobj: IO[bytes], suffix: str, *, wait_seconds: float | None = None
) -> VideoStill | None:
    """`still_from_spooled` in a worker thread, inside the heavy-media slot. None when
    the slot stayed busy for `wait_seconds` (`VIDEO_STILL_WAIT_SECONDS`). Any other error
    is the caller's to swallow: the still never decides whether the video is kept."""
    wait = VIDEO_STILL_WAIT_SECONDS if wait_seconds is None else wait_seconds
    async with contextlib.AsyncExitStack() as stack:
        try:
            await stack.enter_async_context(heavy_media_slot(timeout=wait))
        except TimeoutError:  # only the wait: the still is skipped, never refused
            logger.info("video still skipped: heavy-media slot busy for %.0f s", wait)
            return None
        # a cancelled upload still waits for its thread (and its `finally`)
        return await run_heavy_in_thread(still_from_spooled, fileobj, suffix)
