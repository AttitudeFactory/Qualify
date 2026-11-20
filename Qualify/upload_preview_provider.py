"""ED-09 (m-25026643; ADR 50 D-E2): ask for the light 480p copy of a video the owner just
uploaded to the generator — the screens' door to `qualify_api.creative.upload_previews`.

`ask_for_previews` is called by `CreativeState._add_clip_files` right after the Clip's
videos are stored — only the videos the editor shows (review: the other upload zones, a
carousel slide's motion reference for one, never ask); `upload_preview_state` asks again
when the editor opens a video whose copy was never asked for or is worth retrying.

`ask_for_preview` never blocks nor breaks the upload: the request runs in a worker thread
the upload does not wait for, and anything that fails on the way (no business yet, the
database, a key the service refuses) is logged and dropped — the editor then simply keeps
playing the original (`preview_play_key` falls back to it). Asking twice is harmless: the
service queues ONE job per file (`uq_gallery_jobs_upload_preview`).

The copy is only to SHOW the video; the assembly always reads the original key.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any
from uuid import UUID

from qualify_api.creative.upload_previews import NotPreviewable, request_preview

from .creative_provider import default_brand_id

logger = logging.getLogger(__name__)

#: The requests still running: a reference keeps each future alive until it is done.
_pending: set[asyncio.Future[Any] | Future[Any]] = set()


def is_video_key(key: str) -> bool:
    """A video by its name — the only kind of upload that gets a copy."""
    from qualify_creative.video import is_video_filename  # noqa: PLC0415 — as the service

    return bool(key) and is_video_filename(key)


def request_quietly(tenant_id: UUID, brand_hint: str, key: str) -> bool:
    """Queue the copy of `key` (blocking: database). `brand_hint` is the state's cached
    brand id ("" = not read yet: the tenant's brand is read here). True when the service
    took the request; False — logged, never raised — on any failure."""
    try:
        brand_id = UUID(brand_hint) if brand_hint else default_brand_id(tenant_id)
        if brand_id is None:
            logger.info("upload preview not requested: no brand for the tenant")
            return False
        request_preview(tenant_id, brand_id, key)
        return True
    except NotPreviewable:
        logger.info("upload preview not requested: not an uploaded video of the tenant")
        return False
    except Exception as exc:  # noqa: BLE001 — a copy is never worth failing the upload
        logger.warning("upload preview not requested: %s", type(exc).__name__)
        return False


def _schedule(fn: Callable[..., bool], *args: Any) -> None:
    """Run `fn(*args)` in the default executor without waiting for it; with no running
    loop (a plain call), run it right here."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        fn(*args)
        return
    future = loop.run_in_executor(None, fn, *args)
    _pending.add(future)
    future.add_done_callback(_pending.discard)


def ask_for_preview(tenant_id: UUID, brand_hint: str, key: str) -> None:
    """Right after an upload: ask for `key`'s 480p copy when it is a video, without
    waiting for it and without ever raising."""
    try:
        if not is_video_key(key):
            return
        _schedule(request_quietly, tenant_id, brand_hint or "", key)
    except Exception as exc:  # noqa: BLE001 — the upload already succeeded
        logger.warning("upload preview not scheduled: %s", type(exc).__name__)


async def ask_for_previews(state: Any, keys: list[str]) -> None:
    """`ask_for_preview` for each of `keys` the session's business just stored (its
    tenant read from `AuthState`, never from the browser); never raises."""
    if not keys:
        return
    try:
        from .auth_state import AuthState  # noqa: PLC0415 — AuthState imports the screens
        from .tenant import tenant_uuid  # noqa: PLC0415

        auth = await state.get_state(AuthState)
        tenant_id = tenant_uuid(auth.session_tenant_id)
        if tenant_id is None:
            return
        brand_hint = str(getattr(state, "_brand_id", "") or "")
        for key in keys:
            ask_for_preview(tenant_id, brand_hint, key)
    except Exception as exc:  # noqa: BLE001 — the upload already succeeded
        logger.warning("upload preview not asked: %s", type(exc).__name__)


__all__ = ["ask_for_preview", "ask_for_previews", "is_video_key", "request_quietly"]
