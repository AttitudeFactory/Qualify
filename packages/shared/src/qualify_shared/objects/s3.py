"""The real R2-backed `ObjectStore`. The ONLY module permitted to build an S3 client.

The static guard in `tests/test_object_store_sanctity.py` names this file as the sole
exception.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence
from typing import IO, Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from qualify_shared.objects.config import R2Settings
from qualify_shared.objects.gate import ObjectNotFound, StoredObject

# S3/R2 error codes that mean "no object at this key" — as opposed to any other ClientError
# (bad credentials, wrong bucket, throttling), which must keep propagating as-is rather than
# being silently reinterpreted as a missing object.
_NOT_FOUND_CODES = frozenset({"NoSuchKey", "404", "NotFound"})


def _raise_not_found_or_reraise(exc: ClientError, key: str) -> None:
    code = exc.response.get("Error", {}).get("Code")
    if code in _NOT_FOUND_CODES:
        raise ObjectNotFound(key) from None
    raise exc


def _build_client(settings: R2Settings) -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        config=Config(
            region_name=settings.region_name,
            signature_version=settings.signature_version,
        ),
    )


class R2ObjectStore:
    """`ObjectStore` over Cloudflare R2. Holds no tenant context — see `ObjectGate`."""

    def __init__(self, settings: R2Settings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client if client is not None else _build_client(settings)

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        # `put_object`, not `upload_fileobj`: the latter transparently switches to a
        # multipart upload above a threshold, which is exactly the behaviour the size
        # ceiling exists to forbid. One PUT, or an error.
        self._client.put_object(
            Bucket=self._settings.bucket,
            Key=key,
            Body=fileobj,
            ContentType=content_type,
        )

    def open(self, key: str) -> IO[bytes]:
        # `response["Body"]` is a boto3 `StreamingBody` — it inherits `io.IOBase.seek()`
        # unoverridden, which raises `io.UnsupportedOperation` (a `ValueError` subclass) the
        # moment a caller seeks it. `PublishService._length()` seeks to measure the upload
        # size before streaming to Meta, so a raw `StreamingBody` here breaks every real
        # publish at the read-back step (measured live 2026-08-11 — offline/db tests never
        # caught it because every test double's `open()` already returns `io.BytesIO`, the
        # same shape this now returns for real). Buffering the whole body is bounded by the
        # same ceiling already enforced at write time (`ObjectGate.MAX_MEDIA_BYTES`, 300 MB —
        # a single reel, not a queue of them), so this stays a plain read, not a streaming
        # concern.
        try:
            response = self._client.get_object(Bucket=self._settings.bucket, Key=key)
        except ClientError as exc:
            # QUA-68: translated to a store-agnostic exception so callers (specifically
            # `public_media_routes.py`) never need to inspect a boto3-shaped error to
            # answer their own indistinguishable 404 — a missing-key ClientError becomes
            # ObjectNotFound; anything else (bad credentials, wrong bucket, throttling)
            # keeps propagating unchanged, because those are real infrastructure failures,
            # not "the object is absent".
            code = exc.response.get("Error", {}).get("Code")
            if code in _NOT_FOUND_CODES:
                raise ObjectNotFound(key) from None
            raise
        body: IO[bytes] = response["Body"]
        return io.BytesIO(body.read())

    # -- ranged reads (2026-09-30): the browser previewing a video --------------------------
    #
    # A `<video>` asks for bytes, not files: `Range: bytes=0-` first, then whatever it
    # needs to seek. Serving that through `open()` read the WHOLE object from R2 on every
    # request (a 52 MB reel per card, per seek). R2 answers ranged GETs natively, so these
    # two calls read only what was asked. `open()` — the publisher's whole-object read —
    # is untouched.

    def size(self, key: str) -> int:
        """The object's length in bytes (HEAD, no body read)."""
        try:
            response = self._client.head_object(Bucket=self._settings.bucket, Key=key)
        except ClientError as exc:
            _raise_not_found_or_reraise(exc, key)
        return int(response["ContentLength"])

    def open_range(self, key: str, start: int, end: int) -> IO[bytes]:
        """Bytes `start..end` inclusive (HTTP semantics), buffered like `open()`."""
        try:
            response = self._client.get_object(
                Bucket=self._settings.bucket, Key=key, Range=f"bytes={start}-{end}"
            )
        except ClientError as exc:
            _raise_not_found_or_reraise(exc, key)
        return io.BytesIO(response["Body"].read())

    # -- deletion by prefix (m-24828907): the piece retention rule -------------------------

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        """Every object under `prefix`, paginated (`ListObjectsV2`, 1,000 per page)."""
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._settings.bucket, Prefix=prefix):
            for item in page.get("Contents", ()):
                yield StoredObject(key=item["Key"], size=int(item.get("Size", 0)))

    def delete_keys(self, keys: Sequence[str]) -> None:
        """Delete up to 1,000 keys in one `DeleteObjects`. A key that is already gone is
        not an error (S3 semantics); any per-key error R2 reports is raised, so the caller
        never records a deletion that did not happen."""
        if not keys:
            return
        response = self._client.delete_objects(
            Bucket=self._settings.bucket,
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )
        errors = response.get("Errors") or []
        if errors:
            codes = sorted({str(error.get("Code")) for error in errors})
            raise RuntimeError(f"R2 refused to delete {len(errors)} object(s): {', '.join(codes)}")
