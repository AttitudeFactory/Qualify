"""The real R2-backed `ObjectStore`. The ONLY module permitted to build an S3 client.

The static guard in `tests/test_object_store_sanctity.py` names this file as the sole
exception.
"""

from __future__ import annotations

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
        response = self._client.get_object(Bucket=self._settings.bucket, Key=key)
        body: IO[bytes] = response["Body"]
        return body
