"""An in-memory object store for tests (CM-9, m-24957283) — never R2, never the network.

It behaves like the production bucket where it matters: with `locked=True` (the default)
every key under `t/` is write-once and undeletable, like the bucket lock the founder keeps
on `t/` (m-24971181) — an overwrite or a delete there raises `ObjectLockedError`, so a
test proves code never relies on either. `gallery/` and `reel-windows/` stay deletable.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from typing import IO

from qualify_shared.objects.gate import ObjectNotFound, StoredObject


class ObjectLockedError(RuntimeError):
    """The bucket lock on `t/` refused an overwrite or a delete."""


class MemoryObjectStore:
    def __init__(self, *, locked: bool = True) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.locked = locked
        self.puts: list[str] = []
        #: raise on the next N puts (a passing R2 failure)
        self.fail_puts = 0

    def _is_locked(self, key: str) -> bool:
        return self.locked and key.startswith("t/")

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        if self.fail_puts:
            self.fail_puts -= 1
            raise ConnectionError("R2 down (test)")
        data = fileobj.read()
        if key in self.objects and self._is_locked(key):
            raise ObjectLockedError(f"overwrite refused under t/: {key}")
        self.objects[key] = data
        self.content_types[key] = content_type
        self.puts.append(key)

    def _get(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError:
            raise ObjectNotFound(key) from None

    def open(self, key: str) -> IO[bytes]:
        return io.BytesIO(self._get(key))

    def size(self, key: str) -> int:
        return len(self._get(key))

    def open_range(self, key: str, start: int, end: int) -> IO[bytes]:
        return io.BytesIO(self._get(key)[start : end + 1])

    def sha256(self, key: str) -> str:
        return hashlib.sha256(self._get(key)).hexdigest()

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        now = datetime.now(UTC)
        for key in sorted(self.objects):
            if key.startswith(prefix):
                yield StoredObject(key=key, size=len(self.objects[key]), last_modified=now)

    def delete_keys(self, keys: Sequence[str]) -> None:
        for key in keys:
            if self._is_locked(key):
                raise ObjectLockedError(f"delete refused under t/: {key}")
            self.objects.pop(key, None)
