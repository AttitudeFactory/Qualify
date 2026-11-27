"""m-25129406: the producer's half of «Sigue a la anterior» after the owner's OWN video —
`MediaProducer._own_extend_source` cuts the last seconds of the stretch into the part's
own folder for Seedance to continue, or refuses before any spend (`part_failed`). Behind
`QUALIFY_CLIP_EXTEND_OWN_VIDEO` (off). Offline: no vendor is called, the video is made
here."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from qualify_creative.schemas import SourceSegment

from qualify_api.creative.media import _MediaFailed, _Saver
from qualify_api.creative.part_extend import EXTEND_MANIFEST, EXTEND_SWITCH
from qualify_api.creative.video_pipeline.ai_parts import CLIP_EXTEND_OWN_VIDEO_SWITCH

from .test_clip_avatar import _video_with_sound_bytes
from .test_content_service import TENANT_ID
from .test_video_pipeline_local import ExplodingByteplus, ReadingStore, _producer

OWN = f"uploads/{TENANT_ID}/mi-cocina.mp4"


def _own(start: float = 0.0, end: float = 6.0, key: str = OWN) -> SourceSegment:
    return SourceSegment(key=key, start_s=start, end_s=end, speed=1)


def _call(store: ReadingStore, own: SourceSegment) -> tuple[dict, str]:
    draft = uuid4()
    producer = _producer(store, ExplodingByteplus())
    save = _Saver(store, TENANT_ID, draft, 1)
    return producer._own_extend_source(TENANT_ID, draft, own, save), str(draft)  # noqa: SLF001


@pytest.fixture
def switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLIP_EXTEND_OWN_VIDEO_SWITCH, "on")
    monkeypatch.setenv(EXTEND_SWITCH, "draft")


def test_with_its_switch_off_it_refuses_before_reading_anything() -> None:
    store = ReadingStore({OWN: _video_with_sound_bytes(6.0, 1.5)})
    with pytest.raises(_MediaFailed) as refused:
        _call(store, _own())
    assert refused.value.failure == "part_failed"
    assert store.reads == []


def test_a_file_of_another_business_is_never_read(switch_on: None) -> None:
    foreign = f"uploads/{uuid4()}/ajeno.mp4"
    store = ReadingStore({foreign: _video_with_sound_bytes(6.0, 1.5)})
    with pytest.raises(_MediaFailed) as refused:
        _call(store, _own(key=foreign))
    assert refused.value.failure == "part_failed" and store.reads == []


def test_a_file_that_cannot_be_read_or_cut_fails_the_part(switch_on: None) -> None:
    with pytest.raises(_MediaFailed) as missing:
        _call(ReadingStore(), _own())
    assert missing.value.failure == "part_failed"
    with pytest.raises(_MediaFailed) as broken:
        _call(ReadingStore({OWN: b"not a video"}), _own())
    assert broken.value.failure == "part_failed"


def test_the_last_seconds_of_the_stretch_go_to_the_parts_own_folder(switch_on: None) -> None:
    store = ReadingStore({OWN: _video_with_sound_bytes(14.0, 1.5)})
    manifest, draft = _call(store, _own(1.0, 13.0))
    assert manifest["source_kind"] == "own_video" and manifest["source_key"] == OWN
    assert manifest["source_draft_id"] is None
    # at most 10 s, ending where the owner's stretch ends
    start, end = manifest["source_window"]
    assert end == pytest.approx(13.0, abs=0.05) and end - start <= 10.0 + 1e-6
    assert 2.0 <= manifest["input_seconds"] <= 10.5
    sent = manifest["sent_key"]
    assert f"/{draft}/" in sent and sent in store.files and store.files[sent] != store.files[OWN]
    assert len(manifest["sha256"]) == 64
    json.dumps(manifest)  # the manifest the producer writes as `EXTEND_MANIFEST`
    assert EXTEND_MANIFEST.endswith(".json")
