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
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

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


async def run_heavy_in_thread[T](func: Callable[..., T], /, *args: Any) -> T:
    """`func(*args)` in a worker thread, for use INSIDE `heavy_media_slot`: a thread
    cannot be stopped, so when this task is cancelled (Reflex cancels an upload handler
    when the client disconnects) it still waits for the thread to end before letting
    the cancellation through — the slot is never released while the work is running,
    and no second heavy job can start beside it."""
    future = asyncio.ensure_future(asyncio.to_thread(func, *args))
    try:
        return await asyncio.shield(future)
    except asyncio.CancelledError:
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                continue  # cancelled again: still wait for the thread
            except Exception:  # noqa: BLE001 — the job's own error no longer matters
                break
        raise
