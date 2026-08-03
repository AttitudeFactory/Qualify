"""The sanctioned door to the object plane (ADR 28c) — the R2 analogue of
`qualify_shared.db`'s three session doors.

Two operations, and deliberately only two:

- `put_media`  — a composed asset goes to durable storage before it is scheduled.
- `open_object` — the publisher streams those bytes straight to `rupload.facebook.com`.

**`presign_get` is absent by design, not by omission.** It existed only to serve the image
branch, where Meta cURLs the media from a public URL; that branch is deferred to QUA-68
(ADR 28b). The video path uploads bytes directly, so Qualify exposes no public HTTP surface
and there is nothing here to sign. Adding a signing method back "just in case" would
re-create the surface the current scope exists to avoid.

R2 is still required even with no public hosting: scheduling that survives restarts forces a
durable store between composing and publishing (ADR 28d). What the resumable path removed is
the public hosting of the store, not the store.

Isolation is structural rather than disciplinary: every method routes its key through
`require_tenant_prefix`, and a static test (`tests/test_object_store_sanctity.py`) forbids
constructing an S3/boto3 client anywhere outside this package.
"""

from __future__ import annotations

from typing import IO, Protocol
from uuid import UUID

from qualify_shared.objects.keys import require_tenant_prefix

# Meta's ceiling for the largest video we can publish: a reel is 300 MB
# (`ig-user/media.md:86`). A video story is 100 MB (`:127`), but that limit depends on the
# media TYPE, which this layer does not know — the publisher enforces the tighter one. The
# gate enforces the absolute ceiling so an oversized object cannot reach the bucket at all.
MAX_MEDIA_BYTES = 300 * 1024 * 1024


class ObjectSizeExceeded(Exception):
    """The payload is larger than `MAX_MEDIA_BYTES`.

    Raised instead of falling back to a multipart upload. Multipart is explicitly out of
    scope, and silently switching strategies at a size boundary is how a rarely-exercised
    code path ships untested.
    """


class UnsizedStream(Exception):
    """The stream's length could not be determined, so the size cap cannot be enforced.

    Refusing is the conservative branch: uploading an unmeasurable stream means the ceiling
    silently stops applying for exactly the inputs most likely to be large.
    """


class ObjectStore(Protocol):
    """The raw `(key, bytes)` sink. Knows nothing about tenants — key derivation and prefix
    enforcement happen above it (ADR 22, reasoning 3: if each store derived its own keys,
    each implementation would re-implement isolation and any one could get it wrong)."""

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None: ...

    def open(self, key: str) -> IO[bytes]: ...


def _stream_length(fileobj: IO[bytes]) -> int:
    """Length of a seekable stream, leaving the position where it was found."""
    try:
        origin = fileobj.seek(0, 1)  # SEEK_CUR — do not assume the caller is at position 0
        size = fileobj.seek(0, 2)  # SEEK_END
        fileobj.seek(origin, 0)
    except (AttributeError, OSError) as exc:
        raise UnsizedStream("stream is not seekable, so its size cannot be checked") from exc
    return size - origin


class ObjectGate:
    """Tenant-scoped access to the object plane. One instance wraps one store."""

    def __init__(self, store: ObjectStore) -> None:
        self._store = store

    def put_media(
        self, tenant_id: UUID, object_key: str, fileobj: IO[bytes], content_type: str
    ) -> None:
        """Write a media asset. Single PUT, no multipart, hard size ceiling.

        `content_type` is required rather than guessed, and is stored WITH the object. It is
        load-bearing downstream: the bytes are replayed to Meta later, and an object stored
        as `application/octet-stream` is a plausible cause of a container `ERROR` that looks
        like it came from somewhere else entirely.
        """
        key = require_tenant_prefix(tenant_id, object_key)
        if not content_type:
            raise ValueError("content_type is required — it is stored with the object")
        size = _stream_length(fileobj)
        if size > MAX_MEDIA_BYTES:
            raise ObjectSizeExceeded(
                f"media is {size} bytes, over the {MAX_MEDIA_BYTES}-byte ceiling; "
                "multipart is deliberately not implemented"
            )
        self._store.put(key, fileobj, content_type)

    def open_object(self, tenant_id: UUID, object_key: str) -> IO[bytes]:
        """Open a stored object for streaming — the publisher's source for the resumable
        upload body.

        The prefix is re-checked on read even though the key normally arrives from a row this
        system wrote: a key read back from a database is still input, and the cost of
        re-checking is a string comparison.
        """
        return self._store.open(require_tenant_prefix(tenant_id, object_key))
