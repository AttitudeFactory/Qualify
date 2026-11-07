"""A directory that stands in for R2 in end-to-end tests (m-24955929). TEST-ONLY.

`QUALIFY_OBJECT_STORE_DIR=<path>` makes every `R2ObjectStore(...)` in the process a
`LocalDirObjectStore` over that directory, and `R2Settings.from_env()` stop asking for
the bucket's credentials (`qualify_shared.objects.config`). The app and `media-worker`,
started with the same variable, then share one fake bucket on disk — what the Galería's
E2E (`tests/e2e/test_galeria_to_por_aprobar.py`) needs to upload, prepare, cut, choose
and create without ever touching the real bucket (the local `.env` points at
production).

Off by default; **refused when `QUALIFY_DEPLOY_ENV=production`** (`local_store_dir()`
raises), so a stray variable on the server can never redirect the bucket. The store
implements what `ObjectGate` calls on R2 — `put`, `open`, `sha256`, `size`,
`open_range`, `list_prefix`, `delete_keys` — with R2's semantics (a missing key is
`ObjectNotFound`, deleting a missing key is not an error).
"""

from __future__ import annotations

import hashlib
import io
import os
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from qualify_shared.objects.gate import ObjectNotFound, StoredObject

LOCAL_STORE_ENV = "QUALIFY_OBJECT_STORE_DIR"
_DEPLOY_ENV = "QUALIFY_DEPLOY_ENV"


class LocalStoreRefused(RuntimeError):
    """`QUALIFY_OBJECT_STORE_DIR` set where it must never be (production)."""


def local_store_dir() -> str | None:
    """The fake bucket's directory, or None (the normal case: the real R2)."""
    value = os.environ.get(LOCAL_STORE_ENV, "").strip()
    if not value:
        return None
    if os.environ.get(_DEPLOY_ENV, "").strip().lower() == "production":
        raise LocalStoreRefused(f"{LOCAL_STORE_ENV} is test-only and refused in production")
    return value


class LocalDirObjectStore:
    """`ObjectStore` over a local directory: a key is a relative path under `root`."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise ValueError("not an object key")
        path = (self._root / key).resolve()
        if self._root not in path.parents:
            raise ValueError("not an object key")
        return path

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        with tmp.open("wb") as out:
            while chunk := fileobj.read(1 << 20):
                out.write(chunk)
        tmp.replace(path)  # atomic, like R2's PUT

    def open(self, key: str) -> IO[bytes]:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return io.BytesIO(path.read_bytes())

    def sha256(self, key: str) -> str:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def size(self, key: str) -> int:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        return path.stat().st_size

    def open_range(self, key: str, start: int, end: int) -> IO[bytes]:
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)
        with path.open("rb") as fh:
            fh.seek(start)
            return io.BytesIO(fh.read(max(0, end - start + 1)))

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        for path in sorted(self._root.rglob("*")):
            if not path.is_file() or path.name.endswith(".part"):
                continue
            key = path.relative_to(self._root).as_posix()
            if key.startswith(prefix):
                stat = path.stat()
                yield StoredObject(
                    key=key,
                    size=stat.st_size,
                    last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                )

    def delete_keys(self, keys: Sequence[str]) -> None:
        for key in keys:
            path = self._path(key)
            path.unlink(missing_ok=True)
            # A bucket has no folders: once its last object goes, the prefix is gone too.
            parent = path.parent
            while parent != self._root and parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
                parent = parent.parent
