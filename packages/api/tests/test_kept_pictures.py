"""`kept_pictures` (m-24852537): a network's picture copied to the brand's own R2 prefix.

Offline: the gate wraps an in-memory store (no R2, no network). Pinned: the key layout
and its tenant/brand isolation, that the same bytes keep the same key, that the format
is read from the bytes, the retries, and that every failure is `PictureNotKept`."""

from __future__ import annotations

import io
from typing import IO, Any
from uuid import UUID

import pytest
from PIL import Image
from qualify_shared.objects.gate import PURGEABLE_ROOTS, ObjectGate
from qualify_shared.objects.keys import TenantPrefixViolation

from qualify_api.creative import kept_pictures
from qualify_api.creative.kept_pictures import (
    KIND_POST,
    KIND_PROFILE,
    PictureNotKept,
    R2PictureKeeper,
)

TENANT = UUID("c0000000-0000-4000-8000-0000000000d1")
OTHER_TENANT = UUID("c0000000-0000-4000-8000-0000000000d2")
BRAND = UUID("b0000000-0000-4000-8000-0000000000d1")
OTHER_BRAND = UUID("b0000000-0000-4000-8000-0000000000d2")


def _image(fmt: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), "#0f766e").save(buffer, fmt)
    return buffer.getvalue()


JPEG = _image("JPEG")


class MemoryStore:
    def __init__(self, fail_times: int = 0) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.fail_times = fail_times
        self.calls = 0

    def put(self, key: str, fileobj: IO[bytes], content_type: str) -> None:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise OSError("r2 hiccup")
        self.objects[key] = (fileobj.read(), content_type)

    def open(self, key: str) -> IO[bytes]:
        return io.BytesIO(self.objects[key][0])


def _keeper(store: MemoryStore, **kw: Any) -> R2PictureKeeper:
    return R2PictureKeeper(gate_factory=lambda: ObjectGate(store), sleep=lambda _s: None, **kw)


def test_a_picture_is_kept_under_the_brands_own_prefix() -> None:
    store = MemoryStore()
    kept = _keeper(store).keep(TENANT, BRAND, KIND_PROFILE, JPEG)
    assert kept.key.startswith(f"t/{TENANT}/brand/{BRAND}/kept/profile/")
    assert kept.key.endswith(".jpg") and kept.content_type == "image/jpeg"
    assert kept.size == len(JPEG) and len(kept.sha256) == 64
    assert store.objects[kept.key] == (JPEG, "image/jpeg")
    # never under a root the retention job empties
    rest = kept.key.split("/", 2)[2]
    assert not any(rest.startswith(root) for root in PURGEABLE_ROOTS)


def test_the_same_bytes_keep_the_same_key_and_other_bytes_another() -> None:
    store = MemoryStore()
    keeper = _keeper(store)
    first = keeper.keep(TENANT, BRAND, KIND_PROFILE, JPEG)
    again = keeper.keep(TENANT, BRAND, KIND_PROFILE, JPEG)
    other = keeper.keep(TENANT, BRAND, KIND_PROFILE, _image("PNG"))
    assert first.key == again.key and other.key != first.key
    assert len(store.objects) == 2


def test_keys_are_isolated_by_tenant_and_brand() -> None:
    mine = kept_pictures.kept_key(TENANT, BRAND, KIND_PROFILE, JPEG, ".jpg")
    theirs = kept_pictures.kept_key(OTHER_TENANT, BRAND, KIND_PROFILE, JPEG, ".jpg")
    assert mine != theirs
    assert kept_pictures.is_kept_key(TENANT, BRAND, mine)
    assert not kept_pictures.is_kept_key(OTHER_TENANT, BRAND, mine)
    assert not kept_pictures.is_kept_key(TENANT, OTHER_BRAND, mine)
    assert kept_pictures.owner_of(mine) == (TENANT, BRAND)
    for bad in ("", None, 3, f"t/{TENANT}/brand/{BRAND}/logo.png", f"{mine}/../x"):
        assert not kept_pictures.is_kept_key(TENANT, BRAND, bad)
        assert kept_pictures.owner_of(bad) is None


def test_the_gate_refuses_a_key_of_another_tenant() -> None:
    gate = ObjectGate(MemoryStore())
    theirs = kept_pictures.kept_key(OTHER_TENANT, BRAND, KIND_PROFILE, JPEG, ".jpg")
    with pytest.raises(TenantPrefixViolation):
        gate.put_media(TENANT, theirs, io.BytesIO(JPEG), "image/jpeg")


def test_post_thumbnails_have_their_own_folder_and_unknown_kinds_are_refused() -> None:
    kept = _keeper(MemoryStore()).keep(TENANT, BRAND, KIND_POST, JPEG)
    assert f"/kept/{KIND_POST}/" in kept.key
    with pytest.raises(ValueError):
        kept_pictures.kept_key(TENANT, BRAND, "../logo", JPEG, ".jpg")


@pytest.mark.parametrize(
    ("fmt", "content_type"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp"), ("GIF", "image/gif")],
)
def test_the_format_comes_from_the_bytes(fmt: str, content_type: str) -> None:
    sniffed = kept_pictures.sniff_image(_image(fmt))
    assert sniffed is not None and sniffed[0] == content_type


@pytest.mark.parametrize("data", [b"", b"<html>no</html>", b"\x00" * 64])
def test_what_is_not_an_image_is_not_kept(data: bytes) -> None:
    store = MemoryStore()
    with pytest.raises(PictureNotKept):
        _keeper(store).keep(TENANT, BRAND, KIND_PROFILE, data)
    assert store.calls == 0


def test_a_picture_over_the_cap_is_not_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kept_pictures, "MAX_PICTURE_BYTES", 10)
    with pytest.raises(PictureNotKept):
        _keeper(MemoryStore()).keep(TENANT, BRAND, KIND_PROFILE, JPEG)


def test_a_failed_write_is_retried() -> None:
    store = MemoryStore(fail_times=2)
    kept = _keeper(store, attempts=3).keep(TENANT, BRAND, KIND_PROFILE, JPEG)
    assert store.calls == 3 and kept.key in store.objects


def test_a_write_that_keeps_failing_is_not_kept_and_names_no_url() -> None:
    store = MemoryStore(fail_times=99)
    with pytest.raises(PictureNotKept) as caught:
        _keeper(store, attempts=3).keep(TENANT, BRAND, KIND_PROFILE, JPEG)
    assert store.calls == 3 and "http" not in str(caught.value)


def test_r2_not_configured_is_not_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QUALIFY_R2_ENDPOINT_URL", raising=False)
    with pytest.raises(PictureNotKept):
        R2PictureKeeper().keep(TENANT, BRAND, KIND_PROFILE, JPEG)
