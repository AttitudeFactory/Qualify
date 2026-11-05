"""The public R2 door (ADR 44 F5; the R8 slice of VE-04a): the exact key shape of a copied
public reel, and `PublicObjectGate`'s `put_public` / `open_public` / `delete_public_prefix`
over an in-memory store — three server-side operations and no URL of any kind; the
tenant `ObjectGate` keeps its pinned surface and never reaches `public/`. Offline."""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence
from uuid import uuid4

import pytest

from qualify_shared.objects import (
    ObjectGate,
    PublicKeyViolation,
    PublicObjectGate,
    StoredObject,
    TenantPrefixViolation,
    public_analysis_prefix,
    public_source_key,
    require_public_folder,
    require_public_key,
)


class DictStore:
    """`ObjectStore` plus the list/delete pair the deletion paths need."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, fileobj: io.BufferedIOBase, content_type: str) -> None:
        self.objects[key] = fileobj.read()

    def open(self, key: str) -> io.BytesIO:
        return io.BytesIO(self.objects[key])

    def list_prefix(self, prefix: str) -> Iterator[StoredObject]:
        for key, data in sorted(self.objects.items()):
            if key.startswith(prefix):
                yield StoredObject(key, len(data))

    def delete_keys(self, keys: Sequence[str]) -> None:
        for key in keys:
            self.objects.pop(key, None)


ANALYSIS = uuid4()


def test_the_key_of_a_stored_reel_video() -> None:
    key = public_source_key("instagram", "C1aB_x-9", ANALYSIS)
    assert key == f"public/reel-analyses/instagram/C1aB_x-9/{ANALYSIS}/source/source.mp4"
    frame = f"public/reel-analyses/tiktok/7312345678901234567/{ANALYSIS}/frames/03-2.jpg"
    assert require_public_key(frame) == frame


@pytest.mark.parametrize(
    "key",
    [
        "public/reel-analyses/instagram/",
        f"public/reel-analyses/instagram/C1/{ANALYSIS}/",
        f"public/reel-analyses/youtube/C1/{ANALYSIS}/source/source.mp4",
        f"public/reel-analyses/instagram/../{ANALYSIS}/source/source.mp4",
        f"public/reel-analyses/instagram/C1/{ANALYSIS}/source/other.mp4",
        "public/reel-covers/instagram/C1.jpg",
        f"t/{uuid4()}/generated/x/source/source.mp4",
        f"public/reel-analyses/instagram/C 1/{ANALYSIS}/source/source.mp4",
    ],
)
def test_anything_else_is_refused(key: str) -> None:
    with pytest.raises(PublicKeyViolation):
        require_public_key(key)


def test_only_the_source_and_frames_folders_of_one_analysis_are_deletable() -> None:
    prefix = public_analysis_prefix("instagram", "C1", ANALYSIS)
    assert require_public_folder(prefix + "source/") == prefix + "source/"
    assert require_public_folder(prefix + "frames/") == prefix + "frames/"
    for bad in ("public/", "public/reel-analyses/", prefix, prefix + "source"):
        with pytest.raises(PublicKeyViolation):
            require_public_folder(bad)


def test_put_open_and_delete_through_the_public_door() -> None:
    store = DictStore()
    gate = PublicObjectGate(store)
    key = public_source_key("instagram", "C1", ANALYSIS)
    gate.put_public(key, io.BytesIO(b"mp4"), "video/mp4")
    assert gate.open_public(key).read() == b"mp4"
    folder = public_analysis_prefix("instagram", "C1", ANALYSIS) + "source/"
    dry = gate.delete_public_prefix(folder)
    assert (dry.objects, dry.bytes) == (1, 3) and key in store.objects  # only reported
    done = gate.delete_public_prefix(folder, execute=True)
    assert done.objects == 1 and key not in store.objects
    assert gate.delete_public_prefix(folder, execute=True).objects == 0  # idempotent


def test_the_tenant_doors_never_reach_the_public_prefix() -> None:
    gate = ObjectGate(DictStore())
    tenant = uuid4()
    key = public_source_key("instagram", "C1", ANALYSIS)
    with pytest.raises(TenantPrefixViolation):
        gate.open_object(tenant, key)
    with pytest.raises(TenantPrefixViolation):
        gate.delete_prefix(tenant, "public/reel-analyses/", execute=True)
    with pytest.raises(ValueError):
        PublicObjectGate(DictStore()).put_public(key, io.BytesIO(b"x"), "")


def test_public_gate_surface() -> None:
    """Pinned like `ObjectGate`'s (`test_gate_exposes_no_presign_method`): reads and writes
    by key on the server, never a presigned or public URL."""
    surface = {name for name in dir(PublicObjectGate) if not name.startswith("_")}
    assert surface == {"put_public", "open_public", "delete_public_prefix"}
    assert not {n for n in dir(ObjectGate) if "public" in n}
