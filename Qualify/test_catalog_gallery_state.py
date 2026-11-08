"""«Fotos y videos de tu negocio» (CM-2, m-24955919): the state's handlers, offline.

No database, no R2: the provider functions the state calls are replaced with stand-ins
and `_session_ids` is monkeypatched on the CLASS (as in `test_catalog_state.py`).
Background handlers are driven through `.fn(state, ...)`.

Pins:
1. The upload is refused BEFORE a single chunk is read (3 videos waiting, the Galería
   full, more files than places): the handler returns without touching the iterator.
2. An accepted upload stages the chunks, saves each file through the service, shows
   its refusals in the service's words, re-reads the section and keeps watching while
   a video is being prepared.
3. A cut connection (the handler cancelled) says «Se cortó la subida…», leaves nothing
   «uploading» and lets the cancellation through.
4. An «uploading» flag left by another process (a deploy) is cleared on arrival.
5. «Quitar» asks first; a video being cut is refused with the service's sentence; a
   failed video is dismissed without a question.
6. Logout resets this state (tenant hygiene).
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import pytest

from . import catalog_gallery_state as module
from .catalog_gallery_provider import CatalogError, GallerySnapshot
from .catalog_gallery_state import CatalogGalleryState
from .catalog_gallery_vm import (
    UPLOAD_CUT_TEXT,
    VIDEO_TOO_HEAVY_TEXT,
    VIDEOS_WAITING_NOTICE,
    VIDEOS_WAITING_TEXT,
    GalleryItemVM,
    OutcomeRow,
)
from .catalog_vm import TOO_MUCH_AT_ONCE

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_BRAND = UUID("b0000000-0000-4000-8000-000000000001")
_MEDIA = "d0000000-0000-4000-8000-000000000001"
_JOB = "e0000000-0000-4000-8000-000000000001"


async def _ids(self: CatalogGalleryState) -> tuple[UUID, UUID]:
    return (_TENANT, _BRAND)


async def _same_tenant(self: CatalogGalleryState) -> UUID:
    return _TENANT


def _state(monkeypatch) -> CatalogGalleryState:
    monkeypatch.setattr(CatalogGalleryState, "_session_ids", _ids)
    monkeypatch.setattr(CatalogGalleryState, "_current_tenant", _same_tenant)
    return CatalogGalleryState()


def _tile(**kw: Any) -> GalleryItemVM:
    base: dict[str, Any] = {
        "key": f"media-{_MEDIA}",
        "state": "ready",
        "media_id": _MEDIA,
        "job_id": "",
        "media_type": "video",
        "thumb_url": "/r2media/p",
        "video_url": "/r2media/v",
        "duration": "0:42",
        "duration_ms": 42_000,
        "label": "Video de 42 segundos",
        "remove_label": "el video de 42 segundos",
        "note": "",
        "note_tone": "neutral",
        "can_remove": True,
        "selectable": True,
        "cuttable": True,
    }
    base.update(kw)
    return GalleryItemVM(**base)


def _snapshot(*items: GalleryItemVM, waiting: int = 0) -> GallerySnapshot:
    return GallerySnapshot(items=items, waiting=waiting, busy=waiting > 0, trimmed_ids=())


class _Untouchable:
    """An `UploadChunkIterator` that fails the test if anyone reads it."""

    def __aiter__(self) -> _Untouchable:
        return self

    async def __anext__(self) -> Any:
        raise AssertionError("the upload was read although it had to be refused first")


async def _drain(events: Any) -> list[Any]:
    return [event async for event in events]


async def test_three_videos_waiting_refuse_the_upload_before_reading_it(monkeypatch) -> None:
    def refuse(tenant_id: UUID, brand_id: UUID, videos: int) -> None:
        assert (tenant_id, brand_id, videos) == (_TENANT, _BRAND, 1)
        raise CatalogError(VIDEOS_WAITING_TEXT)

    monkeypatch.setattr(module, "check_upload", refuse)
    state = _state(monkeypatch)
    picked = [{"name": "IMG_1.MOV", "size": 120_000_000}]

    events = await _drain(CatalogGalleryState.receive_upload.fn(state, _Untouchable(), picked))

    assert len(events) == 1  # rx.cancel_upload: the browser stops sending
    # the epic's sentence first, then what the owner can still do
    assert state.upload_error == VIDEOS_WAITING_NOTICE
    assert state.upload_error.startswith(VIDEOS_WAITING_TEXT)
    assert state.upload_error.endswith("Las fotos sí puedes subirlas ahora.")
    assert state.uploading is False


async def test_a_drop_on_the_section_meets_the_same_refusals(monkeypatch) -> None:
    """m-24976806: files dropped anywhere on the section go through the same checks,
    before any byte, and the refusal stops THAT upload (the section's own)."""

    def full(*_a: Any) -> None:
        raise CatalogError(module.GALLERY_FULL_TEXT)

    monkeypatch.setattr(module, "check_upload", full)
    state = _state(monkeypatch)
    picked = [{"name": "local.jpg", "size": 2_000_000}]

    events = await _drain(CatalogGalleryState.receive_drop.fn(state, _Untouchable(), picked))

    assert state.upload_error == module.GALLERY_FULL_TEXT and state.uploading is False
    assert len(events) == 1 and module.DROP_ID in str(events[0])


async def test_more_files_than_places_are_refused_before_reading(monkeypatch) -> None:
    monkeypatch.setattr(module, "check_upload", lambda *_a: None)
    monkeypatch.setattr(module, "free_places", lambda *_a: (3, 1))
    state = _state(monkeypatch)
    picked = [{"name": "a.jpg", "size": 1}, {"name": "b.jpg", "size": 1}]

    await _drain(CatalogGalleryState.receive_upload.fn(state, _Untouchable(), picked))

    assert "Tu Galería guarda hasta 60" in state.upload_error
    assert state.uploading is False


async def test_an_accepted_upload_saves_each_file_and_watches_the_video(monkeypatch) -> None:
    staged_calls: list[dict[str, Any]] = []
    saved: list[str] = []

    class _Staged:
        def __init__(self, name: str) -> None:
            self.filename = name
            self.is_video = name.endswith(".mov")
            self.relpath = f"uploads/{_TENANT}/gallery-staging/x"

    async def fake_stage(chunks: Any, tenant_id: UUID, *, max_videos: int, max_files: int):
        staged_calls.append({"tenant": tenant_id, "videos": max_videos, "files": max_files})
        return [_Staged("a.jpg"), _Staged("b.mov"), _Staged("huge.mov")]

    def fake_add(tenant_id: UUID, brand_id: UUID, staged: Any) -> OutcomeRow:
        saved.append(staged.filename)
        if staged.filename == "huge.mov":
            return OutcomeRow(staged.filename, error_text=VIDEO_TOO_HEAVY_TEXT, is_video=True)
        return OutcomeRow(staged.filename, is_video=staged.is_video)

    preparing = _tile(key=f"job-{_JOB}", state="preparing", media_id="", job_id=_JOB)
    monkeypatch.setattr(module, "check_upload", lambda *_a: None)
    monkeypatch.setattr(module, "free_places", lambda *_a: (3, 60))
    monkeypatch.setattr(module, "stage_upload", fake_stage)
    monkeypatch.setattr(module, "add_staged", fake_add)
    monkeypatch.setattr(module, "load_gallery", lambda *_a: _snapshot(preparing, waiting=1))
    state = _state(monkeypatch)
    picked = [{"name": "a.jpg"}, {"name": "b.mov"}, {"name": "huge.mov"}]

    events = await _drain(CatalogGalleryState.receive_upload.fn(state, object(), picked))

    assert staged_calls == [{"tenant": _TENANT, "videos": 3, "files": 60}]
    assert saved == ["a.jpg", "b.mov", "huge.mov"]
    assert state.upload_error == VIDEO_TOO_HEAVY_TEXT  # one failure: no file name
    assert state.uploading is False and state.upload_percent == 0
    assert [i.state for i in state.items] == ["preparing"] and state.waiting == 1
    assert CatalogGalleryState.watch in events  # keeps reading until the video is ready


async def test_a_cut_connection_says_so_and_leaves_nothing_uploading(monkeypatch) -> None:
    async def cut(*_a: Any, **_k: Any) -> list[Any]:
        raise asyncio.CancelledError

    monkeypatch.setattr(module, "check_upload", lambda *_a: None)
    monkeypatch.setattr(module, "free_places", lambda *_a: (3, 60))
    monkeypatch.setattr(module, "stage_upload", cut)
    state = _state(monkeypatch)

    with pytest.raises(asyncio.CancelledError):
        await _drain(
            CatalogGalleryState.receive_upload.fn(state, object(), [{"name": "IMG_1.MOV"}])
        )

    assert state.upload_error == UPLOAD_CUT_TEXT
    assert state.uploading is False


async def test_a_choice_over_the_request_cap_is_refused_before_reading(monkeypatch) -> None:
    """PR #495: Caddy refuses a request over 520 MB before Reflex sees it. Two big
    videos in one drop are refused here first, in words, and the browser stops."""
    monkeypatch.setattr(module, "check_upload", lambda *_a: None)
    monkeypatch.setattr(module, "free_places", lambda *_a: (3, 60))
    state = _state(monkeypatch)
    picked = [{"name": "a.mov", "size": 300_000_000}, {"name": "b.mov", "size": 300_000_000}]

    events = await _drain(CatalogGalleryState.receive_upload.fn(state, _Untouchable(), picked))

    assert state.upload_error == TOO_MUCH_AT_ONCE
    assert len(events) == 1 and state.uploading is False


def test_progress_is_the_browsers_and_never_says_100_before_the_end() -> None:
    state = CatalogGalleryState()
    state.upload_progress({"progress": 0.5})
    assert state.upload_percent == 0  # not uploading: a stray event changes nothing
    state.uploading = True
    state.upload_videos = 1
    state.upload_progress({"progress": 0.45})
    assert state.upload_label.startswith("Subiendo tu video (45 %).")
    state.upload_progress({"progress": 1.0})
    assert state.upload_percent == 99


def test_an_upload_left_by_another_process_is_cleared_on_arrival() -> None:
    state = CatalogGalleryState()
    state.uploading = True
    state.busy = True
    state._watching = True
    state._process = "a-process-that-is-gone"
    assert state.arrive() == CatalogGalleryState.load
    assert state.uploading is False and state.busy is False and state._watching is False
    assert state.upload_error == UPLOAD_CUT_TEXT


def test_the_picker_refusal_names_the_heavy_video() -> None:
    state = CatalogGalleryState()
    state.picker_rejected([{"file": {"path": "IMG_2.MOV"}, "errors": [{"code": "file-too-large"}]}])
    assert state.upload_error == VIDEO_TOO_HEAVY_TEXT


def test_quitar_asks_first_with_the_right_words() -> None:
    state = CatalogGalleryState()
    state.items = [_tile(), _tile(key="media-p", media_id="p", media_type="image")]
    state.ask_remove(_MEDIA)
    assert state.remove_open is True
    assert state.remove_title_text == "¿Quitar este video de tu Galería?"
    state.set_remove_open(False)
    assert state.remove_open is False
    state.ask_remove("p")
    assert state.remove_title_text == "¿Quitar esta foto de tu Galería?"
    assert state.confirm_remove() is not None and state.remove_id == ""


def test_a_preparing_or_cutting_tile_never_opens_the_question() -> None:
    state = CatalogGalleryState()
    state.items = [_tile(state="cutting", can_remove=False)]
    state.ask_remove(_MEDIA)
    assert state.remove_open is False


async def test_removing_a_video_being_cut_shows_the_services_sentence(monkeypatch) -> None:
    def refuse(tenant_id: UUID, media_id: UUID) -> None:
        raise CatalogError("Estamos cortando este video. Podrás quitarlo cuando termine.")

    monkeypatch.setattr(module, "remove_media", refuse)
    state = _state(monkeypatch)

    events = await _drain(CatalogGalleryState.remove.fn(state, _MEDIA))

    assert events == []
    assert state.upload_error.startswith("Estamos cortando este video.")
    assert state.busy is False


async def test_removing_rereads_and_confirms(monkeypatch) -> None:
    removed: list[tuple[UUID, UUID]] = []
    monkeypatch.setattr(module, "remove_media", lambda t, m: removed.append((t, m)))
    monkeypatch.setattr(module, "load_gallery", lambda *_a: _snapshot())
    state = _state(monkeypatch)
    state.items = [_tile()]

    events = await _drain(CatalogGalleryState.remove.fn(state, _MEDIA))

    assert removed == [(_TENANT, UUID(_MEDIA))]
    assert state.items == [] and state.busy is False
    assert len(events) == 1  # the «Listo» toast


async def test_a_failed_video_is_dismissed_without_a_question(monkeypatch) -> None:
    dismissed: list[UUID] = []
    monkeypatch.setattr(module, "dismiss_job", lambda t, j: dismissed.append(j))
    monkeypatch.setattr(module, "load_gallery", lambda *_a: _snapshot())
    state = _state(monkeypatch)

    await CatalogGalleryState.dismiss.fn(state, _JOB)

    assert dismissed == [UUID(_JOB)]
    assert state.busy is False


def test_logout_resets_the_gallery() -> None:
    from .auth_state import business_state_classes

    assert CatalogGalleryState in business_state_classes()


def test_a_new_visit_starts_without_the_last_uploads_message() -> None:
    state = CatalogGalleryState()
    state.arrive()  # this process's state from now on
    state.upload_error = "Son muchos videos para subirlos juntos. Súbelos de uno o dos a la vez."
    state.upload_info = "Esa foto ya estaba en tu Galería."
    state.arrive()
    assert state.upload_error == "" and state.upload_info == ""


async def test_an_unexpected_error_while_saving_never_leaves_it_uploading(monkeypatch) -> None:
    """Review: a failed R2 PUT (botocore, not OSError) must not keep «Subiendo…»."""

    class _Staged:
        filename = "a.jpg"
        is_video = False
        relpath = ""

    async def fake_stage(*_a: Any, **_k: Any) -> list[Any]:
        return [_Staged()]

    def boom(*_a: Any) -> OutcomeRow:
        raise RuntimeError("R2 down")

    monkeypatch.setattr(module, "check_upload", lambda *_a: None)
    monkeypatch.setattr(module, "free_places", lambda *_a: (3, 60))
    monkeypatch.setattr(module, "stage_upload", fake_stage)
    monkeypatch.setattr(module, "add_staged", boom)
    monkeypatch.setattr(module, "load_gallery", lambda *_a: _snapshot())
    state = _state(monkeypatch)

    await _drain(CatalogGalleryState.receive_upload.fn(state, object(), [{"name": "a.jpg"}]))

    assert state.uploading is False
    assert state.upload_error.startswith("Algo falló de nuestro lado.")


async def test_a_read_failing_unexpectedly_never_leaves_the_skeleton(monkeypatch) -> None:
    def boom(*_a: Any) -> GallerySnapshot:
        raise RuntimeError("missing R2 configuration")

    monkeypatch.setattr(module, "load_gallery", boom)
    state = _state(monkeypatch)
    await _drain(CatalogGalleryState.load.fn(state))
    assert state.loaded is True and state.load_error != ""


async def test_a_read_for_another_business_is_dropped(monkeypatch) -> None:
    """Review: an upload or watch started before «Cambiar de negocio» must not paint
    the previous business's media into the new one."""

    async def other(self: CatalogGalleryState) -> UUID:
        return UUID("a0000000-0000-4000-8000-0000000000ff")

    monkeypatch.setattr(module, "load_gallery", lambda *_a: _snapshot(_tile()))
    state = _state(monkeypatch)
    monkeypatch.setattr(CatalogGalleryState, "_current_tenant", other)

    assert await state._read(_TENANT, _BRAND) is None
    assert state.items == []


async def test_watch_follows_the_owner_back_and_stops_when_they_leave(monkeypatch) -> None:
    """Review: leaving and coming back within a turn must not kill the polling."""
    reads: list[int] = []
    state = _state(monkeypatch)
    monkeypatch.setattr(module, "WATCH_EVERY_S", 0.001)

    def read(*_a: Any) -> GallerySnapshot:
        reads.append(1)
        if len(reads) == 1:  # the owner leaves and comes back during the first turn
            state.leave()
            state.arrive()
        if len(reads) == 2:
            state.leave()  # …and leaves for good
        return _snapshot(_tile(state="preparing"), waiting=1)

    monkeypatch.setattr(module, "load_gallery", read)
    state.arrive()
    await CatalogGalleryState.watch.fn(state)

    assert len(reads) == 2  # kept serving the new visit, stopped after the real leave
    assert state._watching is False


def test_a_finished_video_clears_the_three_waiting_refusal() -> None:
    state = CatalogGalleryState()
    state.upload_error = VIDEOS_WAITING_NOTICE
    state._apply(_snapshot(waiting=2))
    assert state.upload_error == ""


def test_ver_todas_unfolds_the_tiles_and_ver_menos_folds_them() -> None:
    state = CatalogGalleryState()
    state.items = [_tile(key=f"media-{i}", media_id=str(i)) for i in range(8)]
    assert len(state.shown_items) == 6 and state.more_text == "Ver todas (8)"
    state.toggle_show_all()
    assert len(state.shown_items) == 8 and state.more_text == "Ver menos"
    state.items = state.items[:6]
    assert state.more_text == ""  # everything fits: no button


async def test_a_drop_during_an_upload_is_stopped_and_said(monkeypatch) -> None:
    """Review: the button waits during an upload, but a drop on the section is its own
    controller — it is stopped (that upload only) and the owner reads why."""
    state = _state(monkeypatch)
    state.uploading = True
    picked = [{"name": "local.jpg", "size": 2_000_000}]

    events = await _drain(CatalogGalleryState.receive_drop.fn(state, _Untouchable(), picked))

    assert len(events) == 1 and module.DROP_ID in str(events[0])
    assert state.upload_info == module.ONE_AT_A_TIME and state.uploading is True


def test_retry_cut_asks_for_the_same_timeline_again(monkeypatch) -> None:
    """The provider rebuilds the whole timeline from the failed job's kept spans (the
    gaps as removed spans) and queues it through `start_cut`; anything but a cut with
    its source and spans is «gone»."""
    from types import SimpleNamespace

    from . import catalog_gallery_provider as provider

    source = UUID(int=6)
    job = SimpleNamespace(
        kind="cut",
        source_media_id=source,
        segments=((0, 8_000), (14_000, 20_000)),
        source_duration_ms=20_000,
    )

    class _Service:
        def get_gallery_job(self, **_k: Any) -> Any:
            return job

    sent: list[Any] = []

    def fake_start(tenant_id: UUID, media_id: UUID, spans: list[Any]) -> str:
        sent.append((media_id, [(s.start_ms, s.end_ms, s.keep) for s in spans]))
        return "job-2"

    monkeypatch.setattr(provider, "_service", lambda: _Service())
    monkeypatch.setattr(provider, "start_cut", fake_start)
    assert provider.retry_cut(_TENANT, UUID(int=1)) == "job-2"
    assert sent == [(source, [(0, 8_000, True), (8_000, 14_000, False), (14_000, 20_000, True)])]
    for wrong in ({"kind": "ingest"}, {"source_media_id": None}, {"segments": ()}):
        job = SimpleNamespace(**{**vars(job), **wrong})
        monkeypatch.setattr(
            provider, "_service", lambda job=job: SimpleNamespace(get_gallery_job=lambda **_k: job)
        )
        with pytest.raises(KeyError):
            provider.retry_cut(_TENANT, UUID(int=1))
