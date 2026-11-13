"""Tests for historias in «Publicar ahora» — one or several, since 2026-11-12 published by
the same engine as any publication (`publish_engine.py` via `PublishState`). Before
that a historia had its own state (`StoriesState`, removed) with a copy of the whole
publish/poll machine; the guarantees it carried are pinned here against the one engine:
STORIES as the media product, never a caption, one historia per file in the listed
order, the double-submit guard, a JPEG or a video accepted, and the phone handoff
(«Abrir en Instagram») — which never touches the Graph API.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from uuid import UUID

import pytest
from qualify_api.publishing import MEDIA_TYPE_STORIES

from . import publishing_state as state_module
from . import stories_page
from .publish_wizard_vm import MODE_STORIES, MODE_STORY
from .publishing_state import PublishState, _ProviderPorts, _resolve_media
from .publishing_vm import ConnectionOptionVM, PublishAttemptVM

_IG = ConnectionOptionVM(id="c-ig", external_username="b", platform="instagram", handle="@b")


class _FakeUpload:
    def __init__(
        self, data: bytes = b"x", content_type: str = "video/mp4", filename: str = "clip.mp4"
    ) -> None:
        self._data = data
        self.content_type = content_type
        self.filename = filename

    async def read(self) -> bytes:
        return self._data


def _story_state(*uploads: _FakeUpload) -> PublishState:
    s = PublishState()
    s.connections = [_IG]
    s.selected_connection_id = "c-ig"
    asyncio.run(s.add_files(list(uploads) or [_FakeUpload()]))
    s.choose_kind(MODE_STORY if len(s.pending_items) == 1 else MODE_STORIES)
    return s


def test_resolve_media_accepts_mp4_mov_and_jpeg_only() -> None:
    assert _resolve_media("video/mp4", "a") == ("VIDEO", "video/mp4")
    assert _resolve_media("", "a.MOV") == ("VIDEO", "video/quicktime")
    assert _resolve_media(None, "a.jpeg") == ("IMAGE", "image/jpeg")
    assert _resolve_media("image/png", "a.png") is None
    assert _resolve_media("", "a.webp") is None


def test_one_historia_is_one_stories_job_without_text() -> None:
    s = _story_state(_FakeUpload(b"v"))
    s.caption = "no se manda"
    assert s.primary_label == "Publicar historia"
    assert s.review_text == "Sale ahora en Instagram @b como historia (se ve 24 horas)."
    s.publish()
    (job,) = s._jobs
    assert job.product == MEDIA_TYPE_STORIES and job.caption == ""


def test_a_jpeg_historia_goes_through_the_same_stories_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _story_state(_FakeUpload(b"j", "image/jpeg", "foto.jpg"))
    s.publish()
    calls: list = []

    async def fake_start(**kwargs: object) -> PublishAttemptVM:
        calls.append(kwargs)
        return PublishAttemptVM("a", "processing", False, "", "", False, 60)

    monkeypatch.setattr(state_module, "start_publish", fake_start)
    ports = _ProviderPorts(s, tenant_id=UUID(int=1), connection_id=UUID(int=2), token="t")
    asyncio.run(ports.start(s._jobs[0], "K:0"))
    (call,) = calls
    assert call["media_product_type"] == MEDIA_TYPE_STORIES
    assert call["content_type"] == "image/jpeg"
    assert call["caption"] == ""


def test_three_files_as_historias_are_three_stories_in_order() -> None:
    s = _story_state(_FakeUpload(b"1"), _FakeUpload(b"2"), _FakeUpload(b"3"))
    assert s.mode == MODE_STORIES
    assert s.primary_label == "Publicar las 3 historias"
    s.publish()
    assert [j.files[0].data for j in s._jobs] == [b"1", b"2", b"3"]
    assert {j.product for j in s._jobs} == {MEDIA_TYPE_STORIES}


def test_a_historia_is_never_blocked_by_the_count() -> None:
    s = _story_state(*[_FakeUpload(bytes([i])) for i in range(10)])
    assert s.mode == MODE_STORIES and s.can_publish


def test_a_resubmit_while_in_flight_is_a_no_op() -> None:
    s = _story_state()
    assert s.publish() is not None
    key = s._batch_key
    assert s.publish() is None
    assert s._batch_key == key


def test_the_share_handoff_never_touches_the_run() -> None:
    s = _story_state()
    for result in ("shared", "desktop", "insecure", "unsupported", "no_file", "x"):
        assert s.handle_share_result(result) is not None
    assert s.handle_share_result("cancelled") is None
    assert s.phase == "idle" and s._jobs == []


def test_share_to_instagram_reads_only_the_given_gallery_file() -> None:
    script = stories_page.share_to_instagram_script("publish-gallery-root")
    assert "lastFile" not in script
    assert "__STORIES_GALLERY_FILE__" not in script
    assert 'filesByRoot["publish-gallery-root"]' in script


def test_the_share_button_answers_to_the_one_publish_state() -> None:
    source = inspect.getsource(stories_page.share_to_instagram_button)
    assert "PublishState.handle_share_result" in source


def test_stories_state_is_gone_and_nothing_imports_it() -> None:
    here = Path(__file__).parent
    assert not (here / "stories_state.py").exists()
    for path in here.glob("*.py"):
        if path.name.startswith("test_"):
            continue
        assert "stories_state import" not in path.read_text(encoding="utf-8"), path.name
