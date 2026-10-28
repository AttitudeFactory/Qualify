"""The sanctioned door to the object plane (ADR 28c) — the R2 analogue of
`qualify_shared.db`'s three session doors.

Two operations, and deliberately only two:

- `put_media`  — a composed asset goes to durable storage before it is scheduled.
- `open_object` — the publisher streams those bytes straight to `rupload.facebook.com`
  (video) or, since QUA-68, to `GET /public/media/{token}` (image).

**`presign_get` stays absent — QUA-68 did not add it back.** The image branch (Meta cURLs
the media from a public URL) is real now, but it is served by STREAMING the existing
`open_object` through a route in `qualify_api.http.public_media_routes`, not by handing out
an R2 presigned URL. Reasoning kept from the original ADR 28(e) design: a presigned URL
leaks the bucket/key structure of R2 to whoever holds the link, and cannot be revoked before
its own expiry (deleting our own token mapping can). `open_object` needed no change to serve
this second caller — it already returns a plain seekable `IO[bytes]`.

R2 is still required even with no public hosting: scheduling that survives restarts forces a
durable store between composing and publishing (ADR 28d). What the resumable path removed is
the public hosting of the store, not the store.

Isolation is structural rather than disciplinary: every method routes its key through
`require_tenant_prefix`, and a static test (`tests/test_object_store_sanctity.py`) forbids
constructing an S3/boto3 client anywhere outside this package.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import IO, Protocol
from uuid import UUID

from qualify_shared.objects.keys import (
    TenantPrefixViolation,
    require_tenant_prefix,
    tenant_prefix,
)

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


class ObjectNotFound(Exception):
    """No object exists at this key (QUA-68).

    Translated by `R2ObjectStore.open()` from the store's own not-found signal (a boto3
    `ClientError` for a missing S3 key) so callers above the store never need to know that
    detail. Exists specifically for `public_media_routes.py`: a token can outlive the object
    it names (nothing deletes R2 objects on this path today), and that case must answer with
    the SAME 404 as an unknown or expired token — never a distinguishable 500 or a bare
    `KeyError` leaking past the route.
    """


#: The only roots under a tenant's prefix `delete_prefix` may empty (m-24828907): the
#: generator's pieces (`t/{tenant}/generated/{draft_id}/…`). The Brand Kit, the stock
#: library, first-party raw payloads and publish media are never deleted by prefix — a
#: new root here is a reviewed decision, like the gate's method set.
PURGEABLE_ROOTS: tuple[str, ...] = ("generated/",)

#: S3/R2 `DeleteObjects` takes at most 1,000 keys per request.
DELETE_BATCH = 1000


@dataclass(frozen=True)
class StoredObject:
    """One object found under a prefix: its key and its size in bytes."""

    key: str
    size: int


@dataclass(frozen=True)
class PrefixDeletion:
    """What `delete_prefix` found (and removed, unless it was a dry run)."""

    objects: int
    bytes: int


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

    def delete_connection_objects(
        self, tenant_id: UUID, connection_id: UUID, platform: str, object_keys: list[str]
    ) -> None:
        """Delete an explicit manifest, validating ALL keys before touching the store.

        Only connection purge's durable, reference-checked manifest should call this.
        Missing keys are successful retries; store failures propagate to its worker.
        This deliberately grants no new prefix deletion roots.
        """
        keys = list(dict.fromkeys(object_keys))
        for key in keys:
            require_connection_object(tenant_id, connection_id, platform, key)
        for start in range(0, len(keys), DELETE_BATCH):
            self._store.delete_keys(keys[start : start + DELETE_BATCH])  # type: ignore[attr-defined]

    def list_connection_objects(
        self, tenant_id: UUID, connection_id: UUID, platform: str
    ) -> list[str]:
        """Inventory one connection's exact folders, including unreferenced uploads."""
        root = tenant_prefix(tenant_id)
        prefixes = (
            f"{root}media/{connection_id}/",
            f"{root}inbox/thumbs/{connection_id}/",
            f"{root}fp/{platform}/{connection_id}/",
        )
        found: list[str] = []
        for prefix in prefixes:
            require_connection_object(tenant_id, connection_id, platform, prefix + "probe")
            for item in self._store.list_prefix(prefix):  # type: ignore[attr-defined]
                found.append(
                    require_connection_object(tenant_id, connection_id, platform, item.key)
                )
        return found

    def put_connection_media(
        self,
        tenant_id: UUID,
        connection_id: UUID,
        object_key: str,
        fileobj: IO[bytes],
        content_type: str,
    ) -> None:
        """Serialize a connection upload against consent deletion's manifest snapshot.

        The lock covers only the bounded store PUT, not media fetching. It prevents a
        stale fetch from uploading after the purge has inventoried the folder.
        """
        from sqlalchemy import text

        from qualify_shared.db.session import tenant_session

        with tenant_session(tenant_id) as session:
            row = session.execute(
                text("""SELECT platform, purge_started_at FROM social_connections
                WHERE id=:cid FOR SHARE"""),
                {"cid": connection_id},
            ).first()
            if row is None or row.purge_started_at is not None:
                raise ValueError("connection_deletion_in_progress")
            require_connection_object(tenant_id, connection_id, row.platform, object_key)
            self.put_media(tenant_id, object_key, fileobj, content_type)

    def sha256(self, tenant_id: UUID, object_key: str) -> str:
        """Current object's digest; never cross the tenant prefix."""
        key = require_tenant_prefix(tenant_id, object_key)
        return self._store.sha256(key)  # type: ignore[attr-defined]

    # Ranged reads for the browser's video preview (`Qualify/r2_media.py`). Same prefix
    # check as `open_object`. Not part of the `ObjectStore` protocol: only a store that
    # can read ranges (`R2ObjectStore`) offers them, and nothing else needs to.

    def object_size(self, tenant_id: UUID, object_key: str) -> int:
        key = require_tenant_prefix(tenant_id, object_key)  # checked before any store call
        return self._store.size(key)  # type: ignore[attr-defined]

    def open_range(self, tenant_id: UUID, object_key: str, start: int, end: int) -> IO[bytes]:
        key = require_tenant_prefix(tenant_id, object_key)
        return self._store.open_range(key, start, end)  # type: ignore[attr-defined]

    # Deletion by prefix (m-24828907, ADR 39): the retention rule empties a piece's
    # folder 90 days after it was last used. Narrow on purpose — only under a root in
    # `PURGEABLE_ROOTS`, only a folder BELOW that root (never the root itself), and the
    # tenant prefix is checked like every other call. Not part of the `ObjectStore`
    # protocol: only a store that can list and delete (`R2ObjectStore`) offers it.

    def delete_prefix(
        self, tenant_id: UUID, prefix: str, *, execute: bool = False
    ) -> PrefixDeletion:
        """List every object under `prefix` and, with `execute=True`, delete them.
        Returns what was found either way, so a dry run reports what it WOULD delete.
        Idempotent: an empty (or already emptied) prefix answers `PrefixDeletion(0, 0)`."""
        key = _purgeable_prefix(tenant_id, prefix)
        found: list[StoredObject] = list(self._store.list_prefix(key))  # type: ignore[attr-defined]
        if execute:
            keys = [item.key for item in found]
            for start in range(0, len(keys), DELETE_BATCH):
                self._store.delete_keys(keys[start : start + DELETE_BATCH])  # type: ignore[attr-defined]
        return PrefixDeletion(objects=len(found), bytes=sum(item.size for item in found))


def _purgeable_prefix(tenant_id: UUID, prefix: str) -> str:
    """`prefix` unchanged if it is a folder strictly below a purgeable root of this
    tenant (`t/{tenant}/generated/<something>/`); raise otherwise. The trailing slash is
    required so `…/generated/abc` can never also match `…/generated/abcd/…`."""
    key = require_tenant_prefix(tenant_id, prefix)
    if not key.endswith("/"):
        raise TenantPrefixViolation("a deletion prefix must end with '/'")
    rest = key[len(tenant_prefix(tenant_id)) :]
    root = next((r for r in PURGEABLE_ROOTS if rest.startswith(r)), None)
    if root is None or len(rest) <= len(root) or "//" in rest:
        raise TenantPrefixViolation("this prefix is not a purgeable folder")
    return key


def require_connection_object(
    tenant_id: UUID, connection_id: UUID, platform: str, object_key: str
) -> str:
    """Permit only one connection's media, synchronized thumbnails and raw payloads."""
    key = require_tenant_prefix(tenant_id, object_key)
    if platform not in {"instagram", "facebook", "whatsapp"}:
        raise TenantPrefixViolation("unknown connection platform")
    root = tenant_prefix(tenant_id)
    prefixes = (
        f"{root}media/{connection_id}/",
        f"{root}inbox/thumbs/{connection_id}/",
        f"{root}fp/{platform}/{connection_id}/",
    )
    if not any(key.startswith(prefix) and len(key) > len(prefix) for prefix in prefixes):
        raise TenantPrefixViolation("object does not belong to this connection")
    return key
