"""m-25017279 (ADR 49 §2 item 1): the raw Seedream photograph of the advertising image and
of every GENERATED gallery slide is kept under the piece's `base/` folder the moment it is
paid for, and travels on the still it made (`MediaWrite.base`) — never as an output of its
own. An animated slide's first frame is not a base. A base R2 refuses does not fail the
paid piece. The stills, their order and their files are unchanged."""

from __future__ import annotations

import hashlib
from uuid import uuid4

from qualify_creative.enums import SlideSource

from qualify_api.creative.brand_references import BrandReferencesSet
from qualify_api.creative.media import (
    BasePhoto,
    MediaWrite,
    _media_write_from_json,
    _media_write_json,
)

from .test_creative_media_byteplus import BUDGET, COPY, TENANT_ID, FakeSeedance, _kit
from .test_v9_flyer_consumer import (  # noqa: F401 - `no_generation` is autouse
    PHOTO,
    SimulatedFitter,
    gallery_setup,
    no_generation,
    run_flyer,
)


def _produce(producer, brief):  # noqa: ANN001, ANN202
    return producer.produce(
        tenant_id=TENANT_ID,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=BrandReferencesSet(block_version=9),
    )


def test_each_flyer_slide_carries_its_kept_base(monkeypatch) -> None:
    outcome, requests = run_flyer(monkeypatch, count=3)
    assert outcome.failure is None, outcome.detail
    assert len(outcome.media) == 3  # the stills only: no base is an output
    for index, (write, request) in enumerate(zip(outcome.media, requests, strict=True)):
        base = write.base
        assert base is not None
        assert base.key.endswith(f"/base/flyer-{index + 1}.jpg")
        assert base.sha256 == hashlib.sha256(PHOTO).hexdigest()
        assert base.rendered_prompt == request.params["prompt"]
        assert base.prompt_compiler_version == 0  # the fixture brief's own stamp
        assert base.key != write.object_key
        assert write.params["base_key"] == base.key
        assert write.params["base_sha256"] == base.sha256


def test_each_generated_gallery_slide_carries_its_kept_base(monkeypatch) -> None:
    producer, brief, vendor = gallery_setup(monkeypatch)
    outcome = _produce(producer, brief)
    assert outcome.failure is None, outcome.detail
    assert len(outcome.media) == 2
    for number, (write, request) in enumerate(
        zip(outcome.media, vendor.requests, strict=True), start=1
    ):
        assert write.base is not None
        assert write.base.key.endswith(f"/base/slide-{number}.jpg")
        assert write.base.rendered_prompt == request.params["prompt"]
        # the bytes kept are the bytes the still was composed over
        kept = producer._store.files[write.base.key]
        assert hashlib.sha256(kept).hexdigest() == write.base.sha256


def test_an_animated_slide_keeps_no_base(monkeypatch) -> None:
    producer, brief, _ = gallery_setup(monkeypatch)
    producer._router._providers["seedance"] = FakeSeedance()
    producer._fitter = SimulatedFitter()
    slides = tuple(
        slide.model_copy(update={"source": SlideSource.ANIMATED}) for slide in brief.media.slides
    )
    brief = brief.model_copy(update={"media": brief.media.model_copy(update={"slides": slides})})
    outcome = _produce(producer, brief)
    assert outcome.failure is None, outcome.detail
    assert all(write.base is None for write in outcome.media)
    assert not [key for key in producer._store.files if "/base/" in key]


def test_a_base_r2_refuses_is_recorded_never_fails_the_piece(
    monkeypatch, base_photo_alerts
) -> None:
    """Review of m-25017279: a base that is not kept is never silent — it comes back as a
    missing base (stored as a `missing` row) and the still says so. No alert is sent from
    inside the generation: ONE goes per piece, after its media is written (db test)."""
    producer, brief, _ = gallery_setup(monkeypatch)
    store = producer._store

    def keep(tenant_id, key, data, content_type):  # noqa: ANN001, ANN202
        if "/base/" in key:
            return False
        store.files[key] = data
        return True

    store.keep = keep
    outcome = _produce(producer, brief)
    assert outcome.failure is None, outcome.detail
    assert len(outcome.media) == 2
    for write in outcome.media:
        assert write.base is not None and write.base.key is None
        assert write.base.missing_reason
        assert write.params["base_missing"] is True and "base_key" not in write.params
    assert base_photo_alerts.sent == []


def test_one_alert_per_piece_never_waits_for_the_channel(monkeypatch) -> None:
    from qualify_api.creative import base_photos

    queued: list = []
    monkeypatch.setattr(base_photos, "alert_dispatch", queued.append)  # nothing runs yet
    tenant, draft = uuid4(), uuid4()
    base_photos.alert_missing_bases(tenant, draft, ["slide-1", "slide-2"])
    assert len(queued) == 1  # one send for the whole piece, handed off — never run inline
    sent: list[str] = []

    class Slow:
        def notify(self, text: str) -> bool:
            sent.append(text)
            raise TimeoutError("webhook down")

    monkeypatch.setattr(base_photos, "notifier_factory", Slow)
    queued[0]()  # the background send: a failing webhook raises nothing
    assert sent == [
        f"Foto base no guardada: negocio {tenant}, pieza {draft}, archivo(s) slide-1, slide-2. "
        "El almacenamiento (R2) la rechazó. El cliente recibió su pieza igual, pero no "
        "podremos rehacer su texto más adelante. Revisar R2 (m-25017279)."
    ]
    base_photos.alert_missing_bases(tenant, draft, [])
    assert len(queued) == 1  # nothing missing, nothing sent


class LockedStore:
    """The production bucket's rule under `t/`: never overwrite; `keep_outcome` compares a
    key's bytes first (`R2ReadingMediaStore.keep_outcome`)."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.puts: list[str] = []

    def read(self, key: str) -> bytes:
        return self.files[key]

    def write(self, key: str, data: bytes) -> None:  # pragma: no cover - R2 path only
        raise AssertionError("an R2 store never writes locally")

    def keep(self, tenant_id, key, data, content_type):  # noqa: ANN001, ANN201
        return self.keep_outcome(tenant_id, key, data, content_type) == "kept"

    def keep_outcome(self, tenant_id, key, data, content_type):  # noqa: ANN001, ANN201
        if key in self.files:
            return "kept" if self.files[key] == data else "occupied"
        self.files[key] = data
        self.puts.append(key)
        return "kept"


def test_a_retry_finding_its_own_base_reuses_it(monkeypatch) -> None:
    """R2 refuses overwrites under `t/` and the base key is fixed per revision: the same
    bytes already there are a success, nothing is written twice."""
    from qualify_api.creative.image_pipeline.base import keep_base
    from qualify_api.creative.media import _Saver

    store = LockedStore({})
    save = _Saver(store, TENANT_ID, uuid4(), 1)
    first = keep_base(save, name="slide-1", image=PHOTO, prompt="p", usage=(), compiler=5)
    again = keep_base(save, name="slide-1", image=PHOTO, prompt="p", usage=(), compiler=5)
    assert first.key is not None and again.key == first.key
    assert store.puts == [first.key]


def test_different_bytes_at_the_base_key_are_never_taken_for_these(monkeypatch) -> None:
    """Another photograph already under the key (a second paid scene of the same revision):
    these bytes are kept under a key named by their own SHA-256, never overwriting."""
    from qualify_api.creative.image_pipeline.base import keep_base
    from qualify_api.creative.media import _Saver

    store = LockedStore({})
    save = _Saver(store, TENANT_ID, uuid4(), 1)
    first = keep_base(save, name="slide-1", image=PHOTO, prompt="p", usage=(), compiler=5)
    other = PHOTO + b"\x00"
    second = keep_base(save, name="slide-1", image=other, prompt="p", usage=(), compiler=5)
    assert second.key is not None and second.key != first.key
    assert second.key.endswith(f"/base/slide-1-{hashlib.sha256(other).hexdigest()[:12]}.jpg")
    assert store.files[first.key] == PHOTO and store.files[second.key] == other
    assert second.sha256 == hashlib.sha256(other).hexdigest()


def test_a_resumed_gallery_keeps_each_slide_base() -> None:
    """«Crear las que faltan» / a queue resume: a slide kept with its vendor task comes back
    with its base, so the base is neither made nor stored twice."""
    base = BasePhoto(
        key="t/x/generated/d/r1/base/slide-1.jpg",
        sha256="a" * 64,
        content_type="image/jpeg",
        model_id="seedream-5-0",
        provider="seedream",
        rendered_prompt="Create one professional advertising photograph",
        prompt_compiler_version=5,
    )
    kept = MediaWrite(
        position=0,
        media_type="image",
        media_url="t/x/generated/d/r1/slide-1.jpg",
        object_key="t/x/generated/d/r1/slide-1.jpg",
        width=1080,
        height=1350,
        aspect_ratio="4:5",
        model_id="seedream-5-0",
        provider="seedream",
        params={"source": "generated", "base_key": base.key},
        content_type="image/jpeg",
        ai_generated=True,
        rendered_prompt=base.rendered_prompt,
        base=base,
    )
    assert _media_write_from_json(_media_write_json(kept)) == kept
