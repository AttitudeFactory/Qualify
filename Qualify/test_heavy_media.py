"""m-25017273: one heavy media job at a time in the Reflex process — «Subir»'s photo
conversion and the catalog's Pillow/ffmpeg `add_media` share ONE gate, waited on the
event loop before a thread is taken; re-entrant along one call chain; released on an
error or a cancellation. The catalog waits (no new failure); the photo says «busy»."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from uuid import UUID

import pytest

from . import catalog_state as catalog_state_module
from . import heavy_media, upload_images
from .catalog_state import CatalogState
from .heavy_media import heavy_media_slot


@pytest.fixture(autouse=True)
def fresh_gate(monkeypatch: pytest.MonkeyPatch) -> asyncio.Semaphore:
    """A gate per test: an asyncio primitive is bound to the loop that first waits on it."""
    gate = asyncio.Semaphore(1)
    monkeypatch.setattr(heavy_media, "_GATE", gate)
    return gate


async def test_two_jobs_never_overlap() -> None:
    running, peak = 0, 0

    async def job() -> None:
        nonlocal running, peak
        async with heavy_media_slot():
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1

    await asyncio.gather(*(job() for _ in range(5)))
    assert peak == 1


async def test_reentrant_within_one_task_never_deadlocks(fresh_gate) -> None:
    async with heavy_media_slot():
        # e.g. a clip whose handling also converts a poster frame
        async with asyncio.timeout(1):
            async with heavy_media_slot(timeout=0.01):
                pass
        assert fresh_gate.locked()
    assert not fresh_gate.locked()


async def test_released_on_error_and_on_cancellation(fresh_gate) -> None:
    with pytest.raises(RuntimeError):
        async with heavy_media_slot():
            raise RuntimeError("ffmpeg died")
    assert not fresh_gate.locked()

    started = asyncio.Event()

    async def long_job() -> None:
        async with heavy_media_slot():
            started.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(long_job())
    await started.wait()
    waiter = asyncio.create_task(_acquire_and_release())
    await asyncio.sleep(0)
    waiter.cancel()  # a waiter cancelled while queued takes nothing
    task.cancel()
    for one in (task, waiter):
        with pytest.raises(asyncio.CancelledError):
            await one
    assert not fresh_gate.locked()
    async with heavy_media_slot(timeout=0.1):  # still usable
        pass


async def _acquire_and_release() -> None:
    async with heavy_media_slot():
        pass


async def test_a_photo_waits_behind_a_catalog_clip_then_says_busy(fresh_gate) -> None:
    from PIL import Image

    data = io.BytesIO()
    Image.new("RGB", (4, 4)).save(data, format="JPEG")
    async with heavy_media_slot():  # a catalog clip is transcoding (another task)
        with pytest.raises(upload_images.PhotoBusy):
            await asyncio.create_task(
                upload_images.normalize_photo_when_free(
                    io.BytesIO(data.getvalue()), "a.jpg", wait_seconds=0.02
                )
            )
    photo = await upload_images.normalize_photo_when_free(
        io.BytesIO(data.getvalue()), "a.jpg", wait_seconds=0.5
    )
    assert photo.content_type == "image/jpeg" and not fresh_gate.locked()


async def test_the_catalog_adds_media_inside_the_gate_and_waits(
    monkeypatch, tmp_path: Path, fresh_gate
) -> None:
    from .test_catalog_state import _PRODUCT_ID, _product, _state

    held: list[bool] = []

    def fake_add_media(tenant_id: UUID, product_id: UUID, *, data: bytes, filename: str) -> None:
        held.append(fresh_gate.locked())

    monkeypatch.setattr(catalog_state_module, "add_media", fake_add_media)
    monkeypatch.setattr(catalog_state_module, "list_products", lambda *a: (_product(),))
    state = _state(monkeypatch)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"v")
    state._pending = [[str(clip), "clip.mp4", str(_PRODUCT_ID)]]

    async def drain() -> None:
        async for _ in CatalogState.ingest_pending.fn(state):
            pass

    async with heavy_media_slot():  # a photo is converting: the clip waits, no failure
        run = asyncio.create_task(drain())
        await asyncio.sleep(0.05)
        assert held == []
    await run
    assert held == [True] and not fresh_gate.locked()
    assert "clip.mp4" not in state.upload_error


async def test_a_cancelled_job_keeps_the_slot_until_its_thread_ends(fresh_gate) -> None:
    """Reflex cancels an upload handler when the client leaves; the conversion thread
    keeps running, so the slot must stay taken until it ends — never two at once."""
    import threading

    from .heavy_media import run_heavy_in_thread

    release = threading.Event()
    started = threading.Event()
    log: list[str] = []

    def conversion() -> str:
        started.set()
        release.wait(5)
        log.append("conversion done")
        return "ok"

    async def upload() -> None:
        async with heavy_media_slot():
            await run_heavy_in_thread(conversion)

    async def catalog_clip() -> None:
        async with heavy_media_slot():
            log.append("clip started")

    job = asyncio.create_task(upload())
    await asyncio.to_thread(started.wait, 5)
    waiter = asyncio.create_task(catalog_clip())
    job.cancel()  # the client disconnected
    await asyncio.sleep(0.05)
    job.cancel()  # cancelled again: still waits
    await asyncio.sleep(0.05)
    assert log == [] and fresh_gate.locked() and not job.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await job
    await waiter
    assert log == ["conversion done", "clip started"] and not fresh_gate.locked()
