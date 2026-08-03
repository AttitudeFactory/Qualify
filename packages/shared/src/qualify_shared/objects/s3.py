"""The real R2-backed `ObjectStore`. The ONLY module permitted to build an S3 client.

`boto3` is imported lazily, inside the factory, for a specific reason: it is not yet declared
as a dependency of `qualify-shared`, because declaring it mutates `uv.lock` and forces a
`uv sync` — the operation documented in CLAUDE.md as the one that corrupts this workspace's
shared venv. A module-level import would make `qualify_shared.objects` unimportable, and with
it the gate's entire test suite, until that sync happens. With the import deferred, the gate
and its tests run today against an in-memory double, and only constructing the real store
needs the package present.

The static guard in `tests/test_object_store_sanctity.py` names this file as the sole
exception. When `boto3` is declared, move the import to module level and delete this note —
but leave the guard.
"""

from __future__ import annotations

from typing import IO, Any

from qualify_shared.objects.config import R2Settings


def _build_client(settings: R2Settings) -> Any:
    import boto3  # noqa: PLC0415 — deliberate, see module docstring
    from botocore.config import Config  # noqa: PLC0415 — deliberate, see module docstring

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
