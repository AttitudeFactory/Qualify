"""The real R2-backed `ObjectStore`. The ONLY module permitted to build an S3 client.

The static guard in `tests/test_object_store_sanctity.py` names this file as the sole
exception.
"""

from __future__ import annotations

import io
from typing import IO, Any

import boto3
from botocore.config import Config

from qualify_shared.objects.config import R2Settings


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
        response = self._client.get_object(Bucket=self._settings.bucket, Key=key)
        body: IO[bytes] = response["Body"]
        return io.BytesIO(body.read())
