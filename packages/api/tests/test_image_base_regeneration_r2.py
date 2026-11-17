"""Draft 70399135 (2026-11-17): a base regenerated for invented text finds its slide's key
(`r1/base/slide-2.jpg`) already holding the first base. R2 never overwrites: the new base
goes BESIDE it, under a key named by its content, and THAT base is the one the layer is
written for, the compositor draws and the piece records. The «already holds another file»
line is information, not a loss."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

import pytest

from qualify_api.creative.media import KEPT, OCCUPIED

from .test_creative_media_byteplus import MemoryStore
from .test_image_layer_run import Writer, _produce, _wire
from .test_v9_flyer_consumer import (  # noqa: F401 - `no_generation` is autouse
    PHOTO,
    Capture,
    gallery_setup,
    no_generation,
)


class LockedBucket(MemoryStore):
    """The bucket's rule: a key that holds other bytes is never overwritten."""

    def keep_outcome(self, tenant_id: Any, key: str, data: bytes, content_type: str) -> str:
        if key in self.files and self.files[key] != data:
            logging.getLogger("qualify_api.creative.media").info(
                "R2 key %s already holds another file: never overwritten, the new one goes "
                "beside it",
                key,
            )
            return OCCUPIED
        self.files[key] = data
        return KEPT

    def keep(self, tenant_id: Any, key: str, data: bytes, content_type: str) -> bool:
        return self.keep_outcome(tenant_id, key, data, content_type) == KEPT


class NewPhotoAfterTwo(Capture):
    """Seedream: the third photo (the regeneration) is a different image."""

    def generate(self, request: Any, *, api_key: str) -> Any:
        result = super().generate(request, api_key=api_key)
        if len(self.requests) == 3:
            result.payload["images"] = [PHOTO + b"regenerated"]
        return result


def test_a_regenerated_base_is_kept_beside_and_is_the_one_composed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("QUALIFY_IMAGE_LAYER", "on")
    producer, brief, _ = gallery_setup(monkeypatch)
    vendor = NewPhotoAfterTwo()
    producer._router._providers["seedream"] = vendor
    bucket = LockedBucket(dict(producer._store.files))
    producer._store = bucket
    composer = _wire(producer, Writer(invented=(1,)), [])
    with caplog.at_level(logging.INFO):
        outcome = _produce(producer, brief)
    assert outcome.failure is None and len(vendor.requests) == 3  # 2 slides + 1 regeneration
    fresh = PHOTO + b"regenerated"
    sha = hashlib.sha256(fresh).hexdigest()
    second = outcome.media[1]
    # kept beside the first base of slide 2, named by its content
    assert second.base is not None and second.base.key.endswith(f"/base/slide-2-{sha[:12]}.jpg")
    assert bucket.files[second.base.key] == fresh
    assert second.base.sha256 == sha and second.params["base_regenerated"] is True
    # the layer was written for it and the compositor drew it
    drawn = [r for r in composer.requests if r.position == 1]
    assert drawn and drawn[-1].base_sha256 == sha and drawn[-1].base_key == second.base.key
    assert "kept as" in caplog.text and "goes beside it" in caplog.text
    assert not any(
        r.levelno >= logging.WARNING and "holds another" in r.getMessage() for r in caplog.records
    )
