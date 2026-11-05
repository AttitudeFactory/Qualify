"""The public door to the object plane (ADR 44 F5; the R8 slice of VE-04a m-24921056 and
VE-12 m-24921060): copies of PUBLIC reels, keyed without a tenant under
`public/reel-analyses/` (`keys.require_public_key`).

A class of its own on purpose, apart from `ObjectGate`: the tenant gate's surface stays
pinned (`test_objects_gate.py`), and code that holds an `ObjectGate` cannot reach a public
key at all. `public/` means «no tenant», not «open to all»: three server-side operations
and nothing else — no URL, no presigned link, no route (`test_public_gate_surface` pins
it). Who may call them is pinned too (`test_public_objects_sanctity.py`): the
reels-worker's copy and purge, and the server-side «Replicar» reference.
"""

from __future__ import annotations

from typing import IO

from qualify_shared.objects.gate import (
    DELETE_BATCH,
    MAX_MEDIA_BYTES,
    ObjectSizeExceeded,
    ObjectStore,
    PrefixDeletion,
    StoredObject,
    _stream_length,
)
from qualify_shared.objects.keys import require_public_folder, require_public_key


class PublicObjectGate:
    """Server-side access to `public/reel-analyses/`. One instance wraps one store."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def put_public(self, object_key: str, fileobj: IO[bytes], content_type: str) -> None:
        """Write one public object (same single PUT and size ceiling as `put_media`)."""
        key = require_public_key(object_key)
        if not content_type:
            raise ValueError("content_type is required — it is stored with the object")
        size = _stream_length(fileobj)
        if size > MAX_MEDIA_BYTES:
            raise ObjectSizeExceeded(f"object is {size} bytes, over {MAX_MEDIA_BYTES}")
        self._store.put(key, fileobj, content_type)

    def open_public(self, object_key: str) -> IO[bytes]:
        """Open one public object; the key shape is re-checked on read."""
        return self._store.open(require_public_key(object_key))

    def delete_public_prefix(self, prefix: str, *, execute: bool = False) -> PrefixDeletion:
        """List the `source/` or `frames/` folder of one analysis and, with `execute=True`,
        delete it. A dry run reports what it WOULD delete; idempotent like `delete_prefix`."""
        key = require_public_folder(prefix)
        found: list[StoredObject] = list(self._store.list_prefix(key))  # type: ignore[attr-defined]
        if execute:
            keys = [require_public_key(item.key) for item in found]
            for start in range(0, len(keys), DELETE_BATCH):
                self._store.delete_keys(keys[start : start + DELETE_BATCH])  # type: ignore[attr-defined]
        return PrefixDeletion(objects=len(found), bytes=sum(item.size for item in found))


__all__ = ["PublicObjectGate"]
