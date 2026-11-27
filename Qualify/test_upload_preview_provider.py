"""ED-09 (m-25026643): an uploaded video asks for its 480p copy right after it is stored —
without making the upload wait and without ever breaking it. Offline: the service is a
fake (`conftest._no_upload_preview_requests` keeps every other test off it)."""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.upload_previews import NotPreviewable

from . import clip_gallery_vm
from . import upload_preview_provider as provider
from .creative_state import CreativeState

TENANT = UUID("a0000000-0000-4000-8000-0000000e0909")
BRAND = UUID("b0000000-0000-4000-8000-0000000e0909")
VIDEO = f"t/{TENANT}/uploads/abc_clip.mp4"
PHOTO = f"t/{TENANT}/uploads/abc_foto.jpg"

#: The real door, taken before the autouse fixture swaps it for a no-op.
ASK = provider.ask_for_preview


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[UUID, UUID, str]]:
    seen: list[tuple[UUID, UUID, str]] = []
    monkeypatch.setattr(provider, "request_preview", lambda t, b, k: seen.append((t, b, k)))
    monkeypatch.setattr(provider, "default_brand_id", lambda _t: BRAND)
    return seen


def test_a_video_is_requested_with_the_cached_brand(calls) -> None:
    other = UUID("c0000000-0000-4000-8000-0000000e0909")
    assert provider.request_quietly(TENANT, str(other), VIDEO) is True
    assert calls == [(TENANT, other, VIDEO)]


def test_without_a_cached_brand_the_tenants_brand_is_read(calls) -> None:
    assert provider.request_quietly(TENANT, "", VIDEO) is True
    assert calls == [(TENANT, BRAND, VIDEO)]


def test_no_brand_asks_nothing(calls, monkeypatch) -> None:
    monkeypatch.setattr(provider, "default_brand_id", lambda _t: None)
    assert provider.request_quietly(TENANT, "", VIDEO) is False
    assert calls == []


@pytest.mark.parametrize("error", [NotPreviewable(VIDEO), RuntimeError("db down")])
def test_a_failure_is_logged_never_raised(monkeypatch, caplog, error) -> None:
    def refuse(*_a: Any) -> None:
        raise error

    monkeypatch.setattr(provider, "request_preview", refuse)
    with caplog.at_level(logging.INFO, logger=provider.__name__):
        assert provider.request_quietly(TENANT, str(BRAND), VIDEO) is False
    assert "upload preview not requested" in caplog.text
    assert VIDEO not in caplog.text  # no file names in the log


def test_a_bad_cached_brand_is_logged_never_raised(calls) -> None:
    assert provider.request_quietly(TENANT, "not-a-uuid", VIDEO) is False
    assert calls == []


def test_only_videos_are_asked_for(calls) -> None:
    ASK(TENANT, str(BRAND), PHOTO)  # no running loop: runs right here
    ASK(TENANT, str(BRAND), "")
    assert calls == []
    ASK(TENANT, str(BRAND), VIDEO)
    assert calls == [(TENANT, BRAND, VIDEO)]


async def test_the_upload_does_not_wait_for_the_request(monkeypatch) -> None:
    started, release = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    seen: list[str] = []

    def slow(_t: UUID, _b: UUID, key: str) -> None:
        loop.call_soon_threadsafe(started.set)
        asyncio.run_coroutine_threadsafe(release.wait(), loop).result(timeout=5)
        seen.append(key)

    monkeypatch.setattr(provider, "request_preview", slow)
    ASK(TENANT, str(BRAND), VIDEO)  # returns at once
    await asyncio.wait_for(started.wait(), timeout=5)
    assert seen == []  # still running while the caller goes on
    release.set()
    for _ in range(100):
        if seen:
            break
        await asyncio.sleep(0.01)
    assert seen == [VIDEO]
    assert not provider._pending  # the finished request is released


def test_a_scheduling_failure_never_reaches_the_upload(monkeypatch, caplog) -> None:
    def broken(*_a: Any) -> None:
        raise RuntimeError("no executor")

    monkeypatch.setattr(provider, "_schedule", broken)
    with caplog.at_level(logging.WARNING, logger=provider.__name__):
        ASK(TENANT, str(BRAND), VIDEO)
    assert "upload preview not scheduled" in caplog.text


# -- the hook in `CreativeState._add_clip_files` -----------------------------------------


class _Upload:
    def __init__(self, data: bytes, name: str) -> None:
        self.file = io.BytesIO(data)
        self.name = name
        self.size = len(data)

    async def read(self, size: int = -1) -> bytes:
        return self.file.read(size)


class _Auth:
    session_tenant_id = str(TENANT)


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> CreativeState:
    async def get_state(_self: Any, _wanted: type) -> _Auth:
        return _Auth()

    monkeypatch.setattr(CreativeState, "get_state", get_state)
    state = CreativeState()
    state._brand_id = str(BRAND)
    return state


async def test_a_clip_video_asks_for_its_copy(signed_in, memory_r2, monkeypatch) -> None:
    asked: list[tuple[UUID, str, str]] = []
    monkeypatch.setattr(provider, "ask_for_preview", lambda t, b, k: asked.append((t, b, k)))
    left = await CreativeState._add_clip_files(
        signed_in, clip_gallery_vm.VIDEO, [_Upload(b"video", "clip.mp4")]
    )
    assert left == 0
    (video,) = signed_in.clip_videos
    assert asked == [(TENANT, str(BRAND), video["key"])]


async def test_other_upload_zones_never_ask(signed_in, memory_r2, monkeypatch) -> None:
    """Review: only the Clip's videos (what the editor shows) ask — a carousel slide's
    motion reference, an avatar's reference video… go through `_save_uploads` alone."""
    asked: list[Any] = []
    monkeypatch.setattr(provider, "ask_for_preview", lambda *a: asked.append(a))
    saved = await CreativeState._save_uploads(signed_in, [_Upload(b"video", "ref.mp4")])
    assert len(saved) == 1 and asked == []
    await CreativeState._add_clip_files(
        signed_in, clip_gallery_vm.IMAGE, [_Upload(_photo(), "foto.jpg")]
    )
    assert asked == []


async def test_without_a_session_nothing_is_asked(monkeypatch) -> None:
    class _NoAuth:
        session_tenant_id = ""

    async def get_state(_self: Any, _wanted: type) -> _NoAuth:
        return _NoAuth()

    asked: list[Any] = []
    monkeypatch.setattr(provider, "ask_for_preview", lambda *a: asked.append(a))
    monkeypatch.setattr(CreativeState, "get_state", get_state)
    await provider.ask_for_previews(CreativeState(), [VIDEO])
    assert asked == []


async def test_a_failing_request_keeps_the_upload(signed_in, memory_r2, monkeypatch) -> None:
    def refuse(*_a: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(provider, "ask_for_preview", ASK)
    monkeypatch.setattr(provider, "request_preview", refuse)
    await CreativeState._add_clip_files(
        signed_in, clip_gallery_vm.VIDEO, [_Upload(b"video", "clip.mp4")]
    )
    (video,) = signed_in.clip_videos
    assert memory_r2.objects[video["key"]] == b"video"
    assert signed_in.upload_error == ""
    for _ in range(100):  # let the background request finish (and fail quietly)
        if not provider._pending:
            break
        await asyncio.sleep(0.01)
    assert not provider._pending


def _photo() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 120, 110)).save(out, format="JPEG")
    return out.getvalue()
