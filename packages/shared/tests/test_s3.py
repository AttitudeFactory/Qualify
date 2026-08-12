"""Tests for `R2ObjectStore` (the only module allowed to construct a boto3/S3 client).

`open()` specifically: boto3's `get_object()` response `Body` is a `StreamingBody` that
inherits `io.IOBase.seek()` unoverridden — calling `.seek()` on it raises
`io.UnsupportedOperation`, which IS a `ValueError` subclass. `PublishService._length()`
seeks the object `ObjectGate.open_object()` returns to measure the upload size before
streaming to Meta, so a raw `StreamingBody` here broke every real publish at the read-back
step — measured live against real R2, 2026-08-11 (see `open()`'s docstring for the fix).

No other test double in the suite would have caught this: every `MemoryStore.open()`
elsewhere returns `io.BytesIO` directly, which is already seekable. This file exists
specifically to hold the one double that reproduces the actual, non-seekable shape.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from qualify_shared.objects.config import R2Settings
from qualify_shared.objects.s3 import R2ObjectStore

_SETTINGS = R2Settings(
    endpoint_url="https://example.r2.cloudflarestorage.com",
    access_key_id="key",
    secret_access_key="secret",
    bucket="qualify-artifacts",
)


class _UnseekableStreamingBody(io.IOBase):
    """Reproduces the exact shape of botocore's real `StreamingBody`: a plain `io.IOBase`
    subclass that never overrides `seek`/`tell`, so the inherited `IOBase` defaults raise
    `io.UnsupportedOperation` — never `AttributeError`, never anything `open()`'s caller
    could mistake for a simply-missing method. Only `.read()` is provided, same as the
    real thing — everything else is `IOBase`'s unsupported-by-default surface.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._consumed = False

    def read(self, amt: int | None = None) -> bytes:
        if self._consumed:
            return b""
        self._consumed = True
        return self._data


class _FakeS3Client:
    """Stands in for the boto3 client `R2ObjectStore` normally builds — injected through
    the constructor's `client=` seam (already present for exactly this purpose), never a
    real network call."""

    def __init__(self, stored: dict[str, bytes] | None = None) -> None:
        self.stored: dict[str, bytes] = stored or {}
        self.put_calls: list[tuple[str, bytes, str]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: Any, ContentType: str) -> None:
        data = Body.read()
        self.put_calls.append((Key, data, ContentType))
        self.stored[Key] = data

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        return {"Body": _UnseekableStreamingBody(self.stored[Key])}


def test_open_returns_a_seekable_stream_even_though_get_object_is_not() -> None:
    """The real bug, reproduced exactly: `get_object()`'s raw `Body` cannot be seeked, and
    `open()` must never hand that raw object to a caller — `PublishService._length()` (and
    any future caller) requires `seek()` to work on whatever `open()` returns."""
    client = _FakeS3Client({"t/tenant/media/conn/m-1": b"reel-bytes"})
    store = R2ObjectStore(_SETTINGS, client=client)

    stream = store.open("t/tenant/media/conn/m-1")

    # This is exactly what `PublishService._length()` does — and exactly what broke
    # against real R2 before the fix.
    origin = stream.seek(0, 1)
    end = stream.seek(0, 2)
    stream.seek(origin, 0)
    assert end - origin == len(b"reel-bytes")
    assert stream.read() == b"reel-bytes"


def test_the_raw_streaming_body_is_genuinely_unseekable() -> None:
    """Documents the failure this file exists to prevent regressing to: seeking the RAW
    body (what `open()` used to return, before the fix) raises `io.UnsupportedOperation` —
    and that type IS a `ValueError`, which is why the old bug surfaced through
    `publishing_state.py`'s `except (TenantPrefixViolation, ValueError)` branch as "No se
    pudo leer el archivo subido" instead of a clearly-labeled infrastructure error."""
    raw = _UnseekableStreamingBody(b"x")
    with pytest.raises(io.UnsupportedOperation):
        raw.seek(0, 1)
    assert issubclass(io.UnsupportedOperation, ValueError)


def test_put_then_open_round_trips_through_the_real_client_seam() -> None:
    client = _FakeS3Client()
    store = R2ObjectStore(_SETTINGS, client=client)

    store.put("t/tenant/media/conn/m-2", io.BytesIO(b"video-bytes"), "video/mp4")
    stream = store.open("t/tenant/media/conn/m-2")

    assert stream.read() == b"video-bytes"
    assert client.put_calls == [("t/tenant/media/conn/m-2", b"video-bytes", "video/mp4")]
