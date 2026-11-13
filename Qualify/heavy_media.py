"""One heavy media job at a time in the Reflex process (m-25017273).

The app container has 768 MB and no swap (`deploy/docker-compose.prod.yml`), idles at
~260 MiB, and two kinds of work in it can each take ~250-280 MB for a few seconds:

- converting a photo from «Subir» in «Crear publicación» (`upload_images`, measured
  ≤ 276 MB at the caps);
- adding a product photo or clip to the catalog (`catalog_state` → `add_media` → Pillow
  or the ffmpeg transcode of `FfmpegVideoNormalizer`, ~245 MB measured for ffmpeg).

Two at once could OOM-kill the whole app for every client, so both wait on this ONE gate,
on the event loop and BEFORE taking a `to_thread` worker (a queued job never holds a
thread the app's DB reads need). The gate is re-entrant within the ONE task that holds
it (a `ContextVar` naming that task), so a job that already holds it never waits on
itself — while a task it spawns, which inherits the context, still waits its turn.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar

_GATE = asyncio.Semaphore(1)
_HOLDER: ContextVar[asyncio.Task[object] | None] = ContextVar(
    "qualify_heavy_media_holder", default=None
)


@asynccontextmanager
async def heavy_media_slot(*, timeout: float | None = None) -> AsyncIterator[None]:
    """Hold the process's one heavy-media slot for the body. `timeout` None waits as
    long as it takes (the catalog: its uploads keep today's behaviour, only later); a
    number raises `TimeoutError` after that many seconds (the photo of «Subir», which
    tells the owner to try again). Released on any exit, cancellation included."""
    me = asyncio.current_task()
    if me is not None and _HOLDER.get() is me:
        yield  # this task already holds it: never wait on ourselves
        return
    if timeout is None:
        await _GATE.acquire()
    else:
        await asyncio.wait_for(_GATE.acquire(), timeout=timeout)
    token = _HOLDER.set(me)
    try:
        yield
    finally:
        _HOLDER.reset(token)
        _GATE.release()
