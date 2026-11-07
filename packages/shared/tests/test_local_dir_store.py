"""The E2E's fake bucket (m-24955929): `QUALIFY_OBJECT_STORE_DIR` — test-only.

Pins:
1. Off by default: `R2ObjectStore(R2Settings.from_env())` is the real R2 store.
2. With the variable, every `R2ObjectStore(...)` is a `LocalDirObjectStore` over it, and
   `R2Settings.from_env()` reads no credentials.
3. Refused in production (`QUALIFY_DEPLOY_ENV=production`), for both.
4. An explicit `client` (unit tests of the real store) always gets the real class.
5. The store keeps R2's semantics: missing key → `ObjectNotFound`, deleting a missing key
   is fine, no key may leave the directory, `ObjectGate`'s Galería methods work on it.
"""

from __future__ import annotations

import io
from uuid import UUID

import pytest

from qualify_shared.objects.config import R2ConfigurationError, R2Settings
from qualify_shared.objects.gate import ObjectGate, ObjectNotFound
from qualify_shared.objects.local_dir import (
    LOCAL_STORE_ENV,
    LocalDirObjectStore,
    LocalStoreRefused,
)
from qualify_shared.objects.s3 import R2ObjectStore

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
MEDIA = UUID("d0000000-0000-4000-8000-000000000001")
_R2_VARS = (
    "QUALIFY_R2_ENDPOINT_URL",
    "QUALIFY_R2_ACCESS_KEY_ID",
    "QUALIFY_R2_SECRET_ACCESS_KEY",
    "QUALIFY_R2_BUCKET",
)


def test_off_by_default_settings_still_require_the_bucket(monkeypatch) -> None:
    monkeypatch.delenv(LOCAL_STORE_ENV, raising=False)
    for name in _R2_VARS:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(R2ConfigurationError):
        R2Settings.from_env()


def test_off_by_default_the_store_is_r2(monkeypatch) -> None:
    monkeypatch.delenv(LOCAL_STORE_ENV, raising=False)
    store = R2ObjectStore(R2Settings("https://x", "a", "b", "bucket"), client=object())
    assert type(store) is R2ObjectStore
    store = R2ObjectStore(R2Settings("https://x", "a", "b", "bucket"))
    assert type(store) is R2ObjectStore


def test_the_variable_swaps_every_store_for_the_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(LOCAL_STORE_ENV, str(tmp_path))
    monkeypatch.delenv("QUALIFY_DEPLOY_ENV", raising=False)
    for name in _R2_VARS:
        monkeypatch.delenv(name, raising=False)
    settings = R2Settings.from_env()  # no credentials read
    assert settings.endpoint_url.startswith("local-dir://")
    store = R2ObjectStore(settings)
    assert isinstance(store, LocalDirObjectStore)
    # an explicit client is a unit test of the real store: never swapped
    assert type(R2ObjectStore(settings, client=object())) is R2ObjectStore


def test_refused_in_production(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(LOCAL_STORE_ENV, str(tmp_path))
    monkeypatch.setenv("QUALIFY_DEPLOY_ENV", "production")
    with pytest.raises(LocalStoreRefused):
        R2Settings.from_env()
    with pytest.raises(LocalStoreRefused):
        R2ObjectStore(R2Settings("https://x", "a", "b", "bucket"))


def test_the_directory_keeps_r2s_semantics(tmp_path) -> None:
    store = LocalDirObjectStore(tmp_path)
    store.put("t/x/a.jpg", io.BytesIO(b"abc"), "image/jpeg")
    assert store.open("t/x/a.jpg").read() == b"abc"
    assert store.size("t/x/a.jpg") == 3
    assert store.open_range("t/x/a.jpg", 1, 2).read() == b"bc"
    assert len(store.sha256("t/x/a.jpg")) == 64
    assert [o.key for o in store.list_prefix("t/")] == ["t/x/a.jpg"]
    with pytest.raises(ObjectNotFound):
        store.open("t/x/missing.jpg")
    store.delete_keys(["t/x/a.jpg", "t/x/missing.jpg"])  # a missing key is not an error
    assert list(store.list_prefix("t/")) == []
    for bad in ("../escape", "/abs", "a/../../b"):
        with pytest.raises(ValueError):
            store.put(bad, io.BytesIO(b"x"), "image/jpeg")


def test_the_galleria_gate_works_on_it(tmp_path) -> None:
    gate = ObjectGate(LocalDirObjectStore(tmp_path))
    key = gate.put_gallery_media(
        TENANT, MEDIA, "photo.jpg", io.BytesIO(b"\xff\xd8jpg"), "image/jpeg"
    )
    assert key == f"gallery/{TENANT}/{MEDIA}/photo.jpg"
    assert [o.media_id for o in gate.list_gallery_media(TENANT)] == [MEDIA]
    gate.delete_gallery_media(TENANT, MEDIA)
    assert list(gate.list_gallery_media(TENANT)) == []
