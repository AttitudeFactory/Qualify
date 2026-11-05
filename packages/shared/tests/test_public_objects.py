"""The public door to R2 (ADR 44, m-24921056 VE-04a): `public/reel-analyses/…` only, in
exactly two key shapes, with a delete that reaches one analysis' `source/` or `frames/`
folder and nothing wider. The tenant door is unchanged: it still refuses `public/`."""

from __future__ import annotations

import io
from typing import IO
from uuid import UUID, uuid4

import pytest

from qualify_shared.objects import PURGEABLE_ROOTS, ObjectGate, TenantPrefixViolation
from qualify_shared.objects.gate import ObjectSizeExceeded, PrefixDeletion, StoredObject
from qualify_shared.objects.public import (
    MAX_PUBLIC_BYTES,
    PublicKeyViolation,
    PublicObjectGate,
    reel_frame_key,
    reel_frames_prefix,
    reel_source_key,
    reel_source_prefix,
    require_public_key,
)

_ID = UUID("0b0e0c3a-5f7e-4a51-9d0b-1c2d3e4f5a6b")


class ListingStore:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.batches: list[list[str]] = []

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> IO[bytes]:
        return io.BytesIO(self.objects[key][0])

    def size(self, key: str) -> int:
        return len(self.objects[key][0])

    def open_range(self, key: str, start: int, end: int) -> IO[bytes]:
        return io.BytesIO(self.objects[key][0][start : end + 1])

    def list_prefix(self, prefix: str) -> list[StoredObject]:
        return [
            StoredObject(key=k, size=len(v[0]))
            for k, v in sorted(self.objects.items())
            if k.startswith(prefix)
        ]

    def delete_keys(self, keys: list[str]) -> None:
        self.batches.append(list(keys))
        for key in keys:
            self.objects.pop(key, None)


def test_the_two_key_shapes() -> None:
    assert (
        reel_source_key("instagram", "DAbc_-1", _ID)
        == f"public/reel-analyses/instagram/DAbc_-1/{_ID}/source/source.mp4"
    )
    assert (
        reel_frame_key("tiktok", "7301", _ID, 3, 1)
        == f"public/reel-analyses/tiktok/7301/{_ID}/frames/03-1.jpg"
    )


@pytest.mark.parametrize(
    "key",
    [
        "public/reel-analyses/instagram/",
        f"public/reel-analyses/instagram/abc/{_ID}/",
        f"public/reel-analyses/instagram/abc/{_ID}/source/other.mp4",
        f"public/reel-analyses/facebook/abc/{_ID}/source/source.mp4",
        f"public/reel-analyses/instagram/a.b/{_ID}/source/source.mp4",
        "public/reel-analyses/instagram/abc/not-a-uuid/source/source.mp4",
        f"public/reel-analyses/instagram/../{_ID}/source/source.mp4",
        f"public/reel-analyses/instagram//abc/{_ID}/source/source.mp4",
        f"public/reel-covers/instagram/abc/{_ID}/source/source.mp4",
        f"t/{uuid4()}/generated/{_ID}/source/source.mp4",
        f"t/x/public/reel-analyses/instagram/abc/{_ID}/source/source.mp4",
        f"public/reel-analyses/instagram/abc/{_ID}/frames/3-1.jpg",
        f"public/reel-analyses/instagram/abc/{_ID}/frames/03-1.png",
        "",
    ],
)
def test_the_door_refuses_every_other_key(key: str) -> None:
    gate = PublicObjectGate(ListingStore())
    with pytest.raises(PublicKeyViolation):
        require_public_key(key)
    with pytest.raises(PublicKeyViolation):
        gate.put_public(key, io.BytesIO(b"x"), "video/mp4")
    with pytest.raises(PublicKeyViolation):
        gate.open_public(key)


def test_builders_refuse_a_bad_network_or_post_id() -> None:
    with pytest.raises(PublicKeyViolation):
        reel_source_key("facebook", "abc", _ID)
    with pytest.raises(PublicKeyViolation):
        reel_source_key("instagram", "../x", _ID)
    with pytest.raises(PublicKeyViolation):
        reel_frame_key("instagram", "abc", _ID, 100, 0)


def test_put_open_size_and_range() -> None:
    store = ListingStore()
    gate = PublicObjectGate(store)
    key = reel_source_key("instagram", "abc", _ID)
    gate.put_public(key, io.BytesIO(b"0123456789"), "video/mp4")
    assert store.objects[key] == (b"0123456789", "video/mp4")
    assert gate.open_public(key).read() == b"0123456789"
    assert gate.public_size(key) == 10
    assert gate.open_public_range(key, 2, 4).read() == b"234"
    with pytest.raises(ValueError):
        gate.put_public(key, io.BytesIO(b"x"), "text/html")


def test_put_refuses_an_oversized_body() -> None:
    class Big(io.BytesIO):
        def seek(self, offset: int, whence: int = 0) -> int:
            return MAX_PUBLIC_BYTES + 1 if whence == 2 else 0

    with pytest.raises(ObjectSizeExceeded):
        PublicObjectGate(ListingStore()).put_public(
            reel_source_key("instagram", "abc", _ID), Big(b""), "video/mp4"
        )


def test_delete_reaches_one_folder_only() -> None:
    store = ListingStore()
    gate = PublicObjectGate(store)
    other = uuid4()
    for analysis in (_ID, other):
        gate.put_public(
            reel_source_key("instagram", "abc", analysis), io.BytesIO(b"123"), "video/mp4"
        )
        gate.put_public(
            reel_frame_key("instagram", "abc", analysis, 0, 0), io.BytesIO(b"45"), "image/jpeg"
        )
    dry = gate.delete_public_prefix(reel_source_prefix("instagram", "abc", _ID))
    assert dry == PrefixDeletion(objects=1, bytes=3) and store.batches == []
    gate.delete_public_prefix(reel_source_prefix("instagram", "abc", _ID), execute=True)
    gate.delete_public_prefix(reel_frames_prefix("instagram", "abc", _ID), execute=True)
    assert sorted(store.objects) == sorted(
        [
            reel_source_key("instagram", "abc", other),
            reel_frame_key("instagram", "abc", other, 0, 0),
        ]
    )
    again = gate.delete_public_prefix(reel_source_prefix("instagram", "abc", _ID), execute=True)
    assert again == PrefixDeletion(objects=0, bytes=0)


@pytest.mark.parametrize(
    "prefix",
    [
        "public/",
        "public/reel-analyses/",
        "public/reel-analyses/instagram/",
        "public/reel-analyses/instagram/abc/",
        f"public/reel-analyses/instagram/abc/{_ID}/",
        f"public/reel-analyses/instagram/abc/{_ID}/source",
        f"public/reel-analyses/instagram/abc/{_ID}/source/source.mp4",
        f"public/reel-covers/instagram/abc/{_ID}/source/",
    ],
)
def test_delete_refuses_anything_wider_than_one_folder(prefix: str) -> None:
    with pytest.raises(PublicKeyViolation):
        PublicObjectGate(ListingStore()).delete_public_prefix(prefix, execute=True)


def test_the_tenant_door_still_refuses_public_keys() -> None:
    assert PURGEABLE_ROOTS == ("generated/",)
    gate = ObjectGate(ListingStore())
    with pytest.raises(TenantPrefixViolation):
        gate.delete_prefix(uuid4(), reel_source_prefix("instagram", "abc", _ID), execute=True)
    with pytest.raises(TenantPrefixViolation):
        gate.put_media(
            uuid4(), reel_source_key("instagram", "abc", _ID), io.BytesIO(b"x"), "video/mp4"
        )
