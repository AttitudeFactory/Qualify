"""CM-9 (m-24957283): every upload path of the screens writes to R2 (`t/{tenant}/uploads/…`)
and never to the local volume, and their readers work with R2 keys and with old keys
the one-time copy moved. Offline: the in-memory bucket of `conftest.memory_r2`."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative import owner_uploads as ou

from . import upload_store
from .brand_documents import BrandDocumentState
from .creative_state import CreativeState
from .upload_store import UPLOAD_NOT_SAVED
from .voice_lab import VoiceLabState, _on_sample

TENANT = UUID("a0000000-0000-4000-8000-00000000c921")


class _Upload:
    """What Reflex hands a handler: a spooled `file` and the client's `name`."""

    def __init__(self, data: bytes, name: str) -> None:
        self.file = io.BytesIO(data)
        self.name = name
        self.size = len(data)

    async def read(self, size: int = -1) -> bytes:
        return self.file.read(size)


class _Auth:
    session_tenant_id = str(TENANT)


@pytest.fixture
def volume(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    import reflex as rx

    monkeypatch.setattr(rx, "get_upload_dir", lambda: tmp_path)
    return tmp_path


def _signed_in(monkeypatch: pytest.MonkeyPatch, cls: type) -> None:
    async def get_state(_self: Any, _wanted: type) -> _Auth:
        return _Auth()

    monkeypatch.setattr(cls, "get_state", get_state)


async def test_generator_photos_go_to_r2(monkeypatch, memory_r2, volume) -> None:
    _signed_in(monkeypatch, CreativeState)
    state = CreativeState()
    saved = await CreativeState._save_uploads(
        state, [_Upload(b"one", "uno.jpg"), _Upload(b"two", "../dos.png")]
    )
    assert [name for _k, name in saved] == ["uno.jpg", "dos.png"]
    for key, _name in saved:
        assert key.startswith(f"t/{TENANT}/uploads/")
    assert [memory_r2.objects[k] for k, _ in saved] == [b"one", b"two"]
    assert memory_r2.content_types[saved[1][0]] == "image/png"
    assert not any(volume.rglob("*.*"))  # nothing on the local volume
    await CreativeState.handle_photo_upload.fn(state, [_Upload(b"photo", "foto.jpg")])
    assert memory_r2.objects[state.staged_media_key] == b"photo"


async def test_r2_down_tells_the_owner_and_keeps_nothing(monkeypatch, memory_r2, volume) -> None:
    monkeypatch.setattr(ou.time, "sleep", lambda _s: None)
    _signed_in(monkeypatch, CreativeState)
    memory_r2.fail_puts = 99
    state = CreativeState()
    assert await CreativeState._save_uploads(state, [_Upload(b"one", "uno.jpg")]) == []
    assert state.upload_error == UPLOAD_NOT_SAVED
    assert "guardar" in UPLOAD_NOT_SAVED and memory_r2.objects == {}


async def test_brand_documents_go_to_r2_and_are_read_back(monkeypatch, memory_r2, volume) -> None:
    from qualify_api.creative import brief_ai

    _signed_in(monkeypatch, BrandDocumentState)
    monkeypatch.setattr(brief_ai, "read_document", lambda name, data: object())
    state = BrandDocumentState()
    key = await BrandDocumentState._stage(state, "brief", [_Upload(b"%PDF-1", "menú.pdf")])
    assert key is not None and key.startswith(f"t/{TENANT}/uploads/brief/")
    assert key.endswith("_menú.pdf") and memory_r2.objects[key] == b"%PDF-1"
    assert await upload_store.read_upload(TENANT, key) == b"%PDF-1"


async def test_a_voice_sample_goes_to_r2_and_whisper_gets_a_path(
    monkeypatch, memory_r2, volume
) -> None:
    import qualify_api.creative.owner_uploads as owner

    _signed_in(monkeypatch, VoiceLabState)
    monkeypatch.setattr("Qualify.voice_lab.prefetch_whisper", lambda: None, raising=False)
    state = VoiceLabState()
    await VoiceLabState.handle_sample_upload.fn(state, [_Upload(b"RIFF-voice", "voz.wav")])
    assert state.sample_key.startswith(f"t/{TENANT}/uploads/") and state.sample_error == ""
    seen: list[tuple[bytes, Path]] = []
    _on_sample(TENANT, state.sample_key, lambda p: seen.append((p.read_bytes(), p)))
    assert seen[0][0] == b"RIFF-voice" and not seen[0][1].exists()  # temp copy removed

    # an old sample key whose file the copy moved still reaches Whisper
    old = f"uploads/{TENANT}/x_voz.wav"
    memory_r2.put(ou.moved_key_for(old), io.BytesIO(b"old voice"), "audio/wav")
    monkeypatch.setattr(owner, "resolve_moved_key", lambda t, k: ou.moved_key_for(k))
    assert _on_sample(TENANT, old, lambda p: p.read_bytes()) == b"old voice"


async def test_an_old_upload_on_the_volume_is_still_read_from_it(volume) -> None:
    old = f"uploads/{TENANT}/x_a.jpg"
    (volume / old).parent.mkdir(parents=True)
    (volume / old).write_bytes(b"volume")
    assert await upload_store.read_upload(TENANT, old) == b"volume"
