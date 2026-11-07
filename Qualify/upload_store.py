"""Where the screens put and read what the owner uploads (CM-9, m-24957283).

Every upload handler used to write `rx.get_upload_dir() / uploads/{tenant}/…` — the local
`uploads` volume, with no backup. Now each one calls `save_upload` (or
`save_upload_bytes`): the file goes to R2 under `t/{tenant}/uploads/…`, written once from
the upload's own spooled file (never read whole into memory here), through `ObjectGate`.
The key is what the handler keeps, exactly as before, and `rx.get_upload_url(key)` still
shows it (`upload_route.py`).

Readers use `read_upload` / `upload_path`: R2 for an R2 key, the volume for an old key
still on disk, and R2 through the key map for an old key the one-time copy moved
(`qualify_api.creative.owner_uploads`).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any
from uuid import UUID

import reflex as rx
from qualify_api.creative.owner_uploads import (
    UPLOAD_NOT_SAVED,
    UPLOAD_TOO_LARGE,
    UploadNotKept,
    UploadTooLarge,
    content_type_for,
    new_upload_key,
    owner_media_path,
    put_once,
    read_owner_media,
    refusal_text,
)

__all__ = [
    "UPLOAD_NOT_SAVED",
    "UPLOAD_TOO_LARGE",
    "UploadNotKept",
    "UploadTooLarge",
    "refusal_text",
    "read_upload",
    "save_upload",
    "save_upload_bytes",
    "save_upload_file",
    "upload_path",
]


def _gate() -> Any:
    from .r2_media import _gate as production_gate  # noqa: PLC0415 — one cached gate

    return production_gate()


def save_upload_file(tenant_id: UUID, fileobj: IO[bytes], name: str, *, folder: str = "") -> str:
    """Blocking: put one upload in R2 and return its new key. Raises `UploadNotKept`."""
    key = new_upload_key(tenant_id, name, folder=folder)
    put_once(tenant_id, key, fileobj, content_type_for(name), gate=_gate())
    return key


async def save_upload(
    tenant_id: UUID, upload: rx.UploadFile, name: str, *, folder: str = ""
) -> str:
    """One `rx.UploadFile` to R2, streamed from its spooled file, off the event loop."""
    upload.file.seek(0)
    return await asyncio.to_thread(save_upload_file, tenant_id, upload.file, name, folder=folder)


async def save_upload_bytes(tenant_id: UUID, data: bytes, name: str, *, folder: str = "") -> str:
    """Bytes the handler already holds (it had to read them to check them) to R2."""
    import io  # noqa: PLC0415

    return await asyncio.to_thread(
        save_upload_file, tenant_id, io.BytesIO(data), name, folder=folder
    )


def read_upload_sync(tenant_id: UUID, key: str) -> bytes:
    return read_owner_media(tenant_id, key, root=rx.get_upload_dir(), gate=_gate())


async def read_upload(tenant_id: UUID, key: str) -> bytes:
    """The bytes behind one of this tenant's upload keys, wherever they live."""
    return await asyncio.to_thread(read_upload_sync, tenant_id, key)


@contextmanager
def upload_path(tenant_id: UUID, key: str) -> Iterator[Path]:
    """Blocking: a local path to one of this tenant's uploads (a temporary copy of the
    R2 object when it is not on the volume) — for Whisper and the voice clone."""
    with owner_media_path(tenant_id, key, root=rx.get_upload_dir(), gate=_gate()) as path:
        yield path
