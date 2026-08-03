"""The object gate's invariants (QUA-19 / ADR 28c), all offline.

The store is an in-memory double, so nothing here imports boto3 or touches a network — the
gate is exactly the layer where tenant isolation and the size ceiling live, and both are
testable without a bucket.
"""

from __future__ import annotations

import io
from typing import IO
from uuid import UUID, uuid4

import pytest

from qualify_shared.objects import (
    MAX_MEDIA_BYTES,
    ObjectGate,
    ObjectSizeExceeded,
    TenantPrefixViolation,
    UnsizedStream,
    media_key,
    tenant_prefix,
)

_TENANT = UUID("11111111-1111-1111-1111-111111111111")
_OTHER_TENANT = UUID("22222222-2222-2222-2222-222222222222")


class InMemoryStore:
    """Records what it was asked to write, so tests can assert on the KEY the gate derived
    rather than on the gate's return value (it has none)."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> IO[bytes]:
        if key not in self.objects:
            raise KeyError(key)
        return io.BytesIO(self.objects[key][0])


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def gate(store: InMemoryStore) -> ObjectGate:
    return ObjectGate(store)


def test_put_media_stores_bytes_and_content_type(gate: ObjectGate, store: InMemoryStore) -> None:
    key = media_key(_TENANT, uuid4(), "reel-1")
    gate.put_media(_TENANT, key, io.BytesIO(b"video-bytes"), "video/mp4")
    assert store.objects[key] == (b"video-bytes", "video/mp4")


def test_media_key_sits_under_the_tenant_prefix() -> None:
    key = media_key(_TENANT, uuid4(), "reel-1")
    assert key.startswith(tenant_prefix(_TENANT))


def test_tenant_prefix_ends_with_a_slash() -> None:
    """Without the trailing slash, `t/{a}` would prefix-match `t/{ab}/...`. The tenant ids
    are UUIDs of fixed length today, so this cannot bite yet — which is precisely why it
    would survive unnoticed if the key space ever gained a shorter identifier."""
    assert tenant_prefix(_TENANT).endswith("/")


def test_put_media_rejects_a_key_belonging_to_another_tenant(gate: ObjectGate) -> None:
    foreign = media_key(_OTHER_TENANT, uuid4(), "reel-1")
    with pytest.raises(TenantPrefixViolation):
        gate.put_media(_TENANT, foreign, io.BytesIO(b"x"), "video/mp4")


def test_put_media_rejects_an_unprefixed_key(gate: ObjectGate) -> None:
    with pytest.raises(TenantPrefixViolation):
        gate.put_media(_TENANT, "media/loose-key", io.BytesIO(b"x"), "video/mp4")


def test_put_media_rejects_parent_traversal(gate: ObjectGate) -> None:
    key = f"{tenant_prefix(_TENANT)}media/../../{_OTHER_TENANT}/media/stolen"
    with pytest.raises(TenantPrefixViolation):
        gate.put_media(_TENANT, key, io.BytesIO(b"x"), "video/mp4")


def test_violation_message_does_not_echo_the_offending_key(gate: ObjectGate) -> None:
    """The rejected key can carry another tenant's identifier, and exception messages end up
    in logs. The message names the expected prefix, never the input."""
    foreign = media_key(_OTHER_TENANT, uuid4(), "reel-1")
    with pytest.raises(TenantPrefixViolation) as excinfo:
        gate.put_media(_TENANT, foreign, io.BytesIO(b"x"), "video/mp4")
    assert str(_OTHER_TENANT) not in str(excinfo.value)


def test_open_object_rechecks_the_prefix(gate: ObjectGate, store: InMemoryStore) -> None:
    """A key read back from a database row is still input. The other tenant's object exists
    in the store, so this asserts the GATE refused rather than the store missing."""
    foreign = media_key(_OTHER_TENANT, uuid4(), "reel-1")
    store.objects[foreign] = (b"not-yours", "video/mp4")
    with pytest.raises(TenantPrefixViolation):
        gate.open_object(_TENANT, foreign)


def test_open_object_round_trips_its_own_bytes(gate: ObjectGate) -> None:
    key = media_key(_TENANT, uuid4(), "reel-1")
    gate.put_media(_TENANT, key, io.BytesIO(b"video-bytes"), "video/mp4")
    assert gate.open_object(_TENANT, key).read() == b"video-bytes"


def test_put_media_rejects_over_the_ceiling(gate: ObjectGate) -> None:
    """300 MB is Meta's reel ceiling (`ig-user/media.md:86`). Asserting on a real oversized
    buffer would allocate 300 MB, so this drives a stream that reports its size without
    holding the bytes — the gate only ever seeks to measure."""

    class OversizedStream(io.RawIOBase):
        def seek(self, offset: int, whence: int = 0) -> int:
            return MAX_MEDIA_BYTES + 1 if whence == 2 else offset

    with pytest.raises(ObjectSizeExceeded):
        gate.put_media(_TENANT, media_key(_TENANT, uuid4(), "big"), OversizedStream(), "video/mp4")


def test_put_media_accepts_exactly_the_ceiling(gate: ObjectGate) -> None:
    """The boundary is inclusive. Off-by-one here would reject a legal 300 MB reel."""

    class ExactStream(io.RawIOBase):
        def seek(self, offset: int, whence: int = 0) -> int:
            return MAX_MEDIA_BYTES if whence == 2 else offset

        def read(self, size: int = -1) -> bytes:
            return b""

    gate.put_media(_TENANT, media_key(_TENANT, uuid4(), "exact"), ExactStream(), "video/mp4")


def test_put_media_measures_from_the_current_position(
    gate: ObjectGate, store: InMemoryStore
) -> None:
    """A stream handed over mid-read has fewer bytes remaining than its total length. If the
    gate measured absolute length it would over-count, and — worse — `put` would store only
    the remainder while the size check judged the whole."""
    stream = io.BytesIO(b"HEADERvideo-bytes")
    stream.seek(len(b"HEADER"))
    key = media_key(_TENANT, uuid4(), "reel-1")
    gate.put_media(_TENANT, key, stream, "video/mp4")
    assert store.objects[key][0] == b"video-bytes"


def test_put_media_leaves_the_stream_position_untouched(gate: ObjectGate) -> None:
    """Measuring must not consume: the store reads the same stream immediately afterwards."""

    class PositionSpy(io.BytesIO):
        pass

    stream = PositionSpy(b"video-bytes")
    ObjectGate(_NullStore()).put_media(
        _TENANT, media_key(_TENANT, uuid4(), "reel-1"), stream, "video/mp4"
    )
    assert stream.tell() == 0


def test_put_media_refuses_an_unseekable_stream(gate: ObjectGate) -> None:
    """An unmeasurable stream would silently exempt itself from the ceiling."""

    class Unseekable(io.RawIOBase):
        def seek(self, offset: int, whence: int = 0) -> int:
            raise OSError("not seekable")

    with pytest.raises(UnsizedStream):
        gate.put_media(_TENANT, media_key(_TENANT, uuid4(), "x"), Unseekable(), "video/mp4")


def test_put_media_requires_a_content_type(gate: ObjectGate) -> None:
    """Stored `Content-Type` is replayed to Meta later; an octet-stream default is a
    plausible cause of a container ERROR that looks unrelated."""
    with pytest.raises(ValueError):
        gate.put_media(_TENANT, media_key(_TENANT, uuid4(), "x"), io.BytesIO(b"x"), "")


def test_gate_exposes_no_presign_method() -> None:
    """ADR 28c: `presign_get` served only the deferred image branch (QUA-68). Its absence is
    the guarantee that this sprint opens no public HTTP surface, so it is asserted rather
    than left to review."""
    surface = {name for name in dir(ObjectGate) if not name.startswith("_")}
    assert surface == {"put_media", "open_object"}
    assert not any("presign" in name or "sign" in name for name in surface)


class _NullStore:
    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        return None

    def open(self, key: str) -> IO[bytes]:
        raise KeyError(key)
