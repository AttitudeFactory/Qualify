"""«Corta tu video en partes» (CM-4, m-24955924): the cutter's handlers, offline.

No database: `start_cut` is a stand-in; the gallery tiles are set by hand. Pins:
1. «Cortar video» opens on a ready video with its whole length as one part.
2. The line moves with the slider and one frame with «Atrás» / «Adelante»; each move
   seeks the preview.
3. «Quitar esta parte» asks first; «Cancelar» asks only with changes.
4. «Guardar» queues ONE cut with the timeline as spans, closes, and hands the job to
   the section; a refusal stays in the drawer in the service's words.
5. The section says «Listo: tu video quedó en N partes.» when a watched cut ends.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from . import catalog_cut_state as module
from .catalog_cut_state import CatalogCutState
from .catalog_cut_vm import ALREADY_CUTTING_TEXT, CUT_FAILED_TEXT, FRAME_MS
from .catalog_gallery_provider import CatalogError, GallerySnapshot
from .catalog_gallery_state import CatalogGalleryState
from .catalog_gallery_vm import GalleryItemVM

_TENANT = UUID("a0000000-0000-4000-8000-000000000001")
_MEDIA = "d0000000-0000-4000-8000-000000000001"


def _video(**kw: Any) -> GalleryItemVM:
    base: dict[str, Any] = {
        "key": f"media-{_MEDIA}",
        "state": "ready",
        "media_id": _MEDIA,
        "job_id": "",
        "media_type": "video",
        "thumb_url": "/r2media/p",
        "video_url": "/r2media/v",
        "duration": "0:31",
        "duration_ms": 31_000,
        "label": "Video de 31 segundos",
        "remove_label": "el video de 31 segundos",
        "note": "",
        "note_tone": "neutral",
        "can_remove": True,
        "selectable": True,
        "cuttable": True,
    }
    base.update(kw)
    return GalleryItemVM(**base)


class _Auth:
    session_tenant_id = str(_TENANT)


async def _open(state: CatalogCutState, monkeypatch, item: GalleryItemVM | None = None) -> None:
    gallery = CatalogGalleryState()
    gallery.items = [item or _video()]

    async def get_state(self: Any, cls: type) -> Any:
        return gallery if cls is CatalogGalleryState else _Auth()

    monkeypatch.setattr(CatalogCutState, "get_state", get_state)
    await CatalogCutState.open_cut.fn(state, _MEDIA)


async def test_cortar_video_opens_with_the_whole_video_as_one_part(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch)
    assert state.open and state.duration_ms == 31_000
    assert [r.label for r in state.rows] == ["Parte 1 · 0:00 a 0:31"]
    assert state.blocker.startswith("Todavía no cortaste el video.")


async def test_a_video_that_cannot_be_cut_never_opens(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch, _video(state="cutting", cuttable=False))
    assert state.open is False


async def test_the_line_moves_and_cortar_aqui_splits(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch)
    assert state.move_line([12_000]) is not None  # the preview seeks
    state.nudge(1)
    assert state.playhead_ms == 12_000 + FRAME_MS and state.playhead_text == "0:12,0"
    state.nudge(-1)
    state.cut_here()
    assert [r.label for r in state.rows] == ["Parte 1 · 0:00 a 0:12", "Parte 2 · 0:12 a 0:31"]
    assert state.blocker == ""


async def test_quitar_esta_parte_asks_first(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch)
    state.move_line([12_000])
    state.cut_here()
    state.ask_remove_part()
    assert state.remove_open is False  # nothing selected yet
    state.select_part(2)
    assert state.playhead_ms == 12_000
    state.ask_remove_part()
    assert state.remove_open is True
    state.confirm_remove_part()
    assert [r.label for r in state.rows] == ["Parte 1 · 0:00 a 0:12"]
    assert state.selected == 0


async def test_cancel_asks_only_with_changes(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch)
    state.request_close()
    assert state.open is False and state.leave_open is False
    await _open(state, monkeypatch)
    state.move_line([5_000])
    state.cut_here()
    state.request_close()
    assert state.open is True and state.leave_open is True
    state.discard()
    assert state.open is False


async def test_guardar_queues_one_cut_and_hands_it_to_the_section(monkeypatch) -> None:
    sent: list[Any] = []

    def fake_start(tenant_id: UUID, media_id: UUID, spans: list[Any]) -> str:
        sent.append((tenant_id, media_id, [(s.start_ms, s.end_ms, s.keep) for s in spans]))
        return "job-1"

    monkeypatch.setattr(module, "start_cut", fake_start)
    state = CatalogCutState()
    await _open(state, monkeypatch)
    state.move_line([12_000])
    state.cut_here()
    state.ask_save()
    assert state.save_open and state.save_question.startswith("Vamos a guardar 2 partes.")

    events = [e async for e in CatalogCutState.confirm_save.fn(state)]

    assert sent == [(_TENANT, UUID(_MEDIA), [(0, 12_000, True), (12_000, 31_000, True)])]
    assert state.open is False and state.saving is False
    assert len(events) == 2  # track_cut + the «Cortando tu video…» toast


async def test_a_refused_cut_stays_open_with_the_services_sentence(monkeypatch) -> None:
    def refuse(*_a: Any) -> str:
        raise CatalogError(ALREADY_CUTTING_TEXT)

    monkeypatch.setattr(module, "start_cut", refuse)
    state = CatalogCutState()
    await _open(state, monkeypatch)
    state.move_line([12_000])
    state.cut_here()

    events = [e async for e in CatalogCutState.confirm_save.fn(state)]

    assert events == [] and state.open is True and state.error == ALREADY_CUTTING_TEXT


def _snap(job_id: str, status: str, parts: int) -> GallerySnapshot:
    return GallerySnapshot(items=(), waiting=0, busy=False, cuts=((job_id, status, parts),))


def test_the_section_says_when_a_watched_cut_ends() -> None:
    gallery = CatalogGalleryState()
    gallery.track_cut("job-1")
    gallery._apply(
        GallerySnapshot(items=(), waiting=0, busy=False, cuts=(("job-1", "running", 0),))
    )
    assert gallery.cut_notice == ""
    gallery._apply(_snap("job-1", "done", 3))
    assert gallery.cut_notice == "Listo: tu video quedó en 3 partes."
    gallery.dismiss_cut_notice()
    gallery.track_cut("job-2")
    gallery._apply(_snap("job-2", "failed", 0))
    assert gallery.cut_error == CUT_FAILED_TEXT


def test_logout_resets_the_cutter() -> None:
    from .auth_state import business_state_classes

    assert CatalogCutState in business_state_classes()
