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
from botocore.exceptions import ClientError

from qualify_shared.objects.config import R2Settings
from qualify_shared.objects.gate import ObjectNotFound
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
        self.ranges: list[str] = []

    def put_object(self, *, Bucket: str, Key: str, Body: Any, ContentType: str) -> None:
        data = Body.read()
        self.put_calls.append((Key, data, ContentType))
        self.stored[Key] = data

    def get_object(self, *, Bucket: str, Key: str, Range: str | None = None) -> dict[str, Any]:
        if Key not in self.stored:
            # The real shape botocore raises for a missing S3/R2 key — reproduced so
            # `R2ObjectStore.open()`'s translation to `ObjectNotFound` (QUA-68) is
            # exercised against the actual exception type, not a stand-in.
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject")
        data = self.stored[Key]
        if Range is not None:
            self.ranges.append(Range)
            start, end = (int(part) for part in Range.removeprefix("bytes=").split("-"))
            data = data[start : end + 1]
        return {"Body": _UnseekableStreamingBody(data)}

    def head_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        if Key not in self.stored:
            # HEAD has no body, so S3/R2 report a missing key as a bare "404".
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {"ContentLength": len(self.stored[Key])}


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


def test_open_on_a_missing_key_raises_object_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """QUA-68: `public_media_routes.py` needs a store-agnostic signal for "nothing here" —
    a bare botocore `ClientError` (or its `NoSuchKey` code) must never reach that route."""
    store = R2ObjectStore(_SETTINGS, client=_FakeS3Client())

    with pytest.raises(ObjectNotFound):
        store.open("t/tenant/media/conn/does-not-exist")


def test_open_reraises_a_client_error_that_is_not_a_missing_key() -> None:
    """A DIFFERENT ClientError (bad credentials, throttling, wrong bucket) is a real
    infrastructure failure and must keep propagating — silently reading it as "object
    missing" would misreport an outage as a 404."""

    class _DenyingClient(_FakeS3Client):
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            raise ClientError({"Error": {"Code": "AccessDenied", "Message": "nope"}}, "GetObject")

    store = R2ObjectStore(_SETTINGS, client=_DenyingClient())

    with pytest.raises(ClientError):
        store.open("t/tenant/media/conn/m-1")


# --- ranged reads (browser video preview) ----------------------------------------------------


def test_size_is_a_head_request_and_open_range_asks_r2_for_just_those_bytes() -> None:
    client = _FakeS3Client({"t/tenant/media/conn/v": b"0123456789"})
    store = R2ObjectStore(_SETTINGS, client=client)
    assert store.size("t/tenant/media/conn/v") == 10
    assert store.open_range("t/tenant/media/conn/v", 2, 5).read() == b"2345"
    assert client.ranges == ["bytes=2-5"]


def test_ranged_reads_of_a_missing_key_raise_object_not_found() -> None:
    store = R2ObjectStore(_SETTINGS, client=_FakeS3Client())
    with pytest.raises(ObjectNotFound):
        store.size("t/tenant/media/conn/gone")
    with pytest.raises(ObjectNotFound):
        store.open_range("t/tenant/media/conn/gone", 0, 1)


# --- deletion by prefix (m-24828907, piece retention) ----------------------------------------


class _ListingClient(_FakeS3Client):
    """Adds `ListObjectsV2` pagination (2 keys per page, to exercise paging) and
    `DeleteObjects`, with optional per-key errors."""

    def __init__(self, stored: dict[str, bytes], refuse: frozenset[str] = frozenset()) -> None:
        super().__init__(stored)
        self.refuse = refuse
        self.delete_calls: list[list[str]] = []

    def get_paginator(self, name: str) -> Any:
        assert name == "list_objects_v2"
        client = self

        class _Paginator:
            def paginate(self, *, Bucket: str, Prefix: str) -> Any:
                keys = sorted(k for k in client.stored if k.startswith(Prefix))
                for start in range(0, len(keys), 2):
                    page = keys[start : start + 2]
                    yield {"Contents": [{"Key": k, "Size": len(client.stored[k])} for k in page]}
                if not keys:
                    yield {"KeyCount": 0}  # an empty listing has no "Contents" at all

        return _Paginator()

    def delete_objects(self, *, Bucket: str, Delete: dict[str, Any]) -> dict[str, Any]:
        keys = [item["Key"] for item in Delete["Objects"]]
        self.delete_calls.append(keys)
        errors = [{"Key": k, "Code": "AccessDenied"} for k in keys if k in self.refuse]
        for key in keys:
            if key not in self.refuse:
                self.stored.pop(key, None)
        return {"Errors": errors} if errors else {}


def test_list_prefix_pages_through_every_object_with_its_size() -> None:
    stored = {f"t/x/generated/d/r1/{i}.jpg": b"a" * i for i in range(1, 6)}
    stored["t/x/generated/other/r1/0.jpg"] = b"zz"
    store = R2ObjectStore(_SETTINGS, client=_ListingClient(stored))
    found = list(store.list_prefix("t/x/generated/d/"))
    assert [item.size for item in found] == [1, 2, 3, 4, 5]
    assert all(item.key.startswith("t/x/generated/d/") for item in found)


def test_list_prefix_of_an_empty_folder_is_empty() -> None:
    store = R2ObjectStore(_SETTINGS, client=_ListingClient({}))
    assert list(store.list_prefix("t/x/generated/d/")) == []


def test_delete_keys_removes_them_and_skips_an_empty_call() -> None:
    client = _ListingClient({"t/x/generated/d/a": b"1", "t/x/generated/d/b": b"2"})
    store = R2ObjectStore(_SETTINGS, client=client)
    store.delete_keys([])
    store.delete_keys(["t/x/generated/d/a", "t/x/generated/d/b"])
    assert client.stored == {}
    assert client.delete_calls == [["t/x/generated/d/a", "t/x/generated/d/b"]]


def test_delete_keys_raises_when_r2_refuses_one() -> None:
    """A refused key must never be recorded as deleted: the caller marks the piece only
    after this returns."""
    client = _ListingClient({"t/x/generated/d/a": b"1"}, refuse=frozenset({"t/x/generated/d/a"}))
    store = R2ObjectStore(_SETTINGS, client=client)
    with pytest.raises(RuntimeError, match="AccessDenied"):
        store.delete_keys(["t/x/generated/d/a"])
