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

import pytest

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


async def test_quitar_esta_parte_is_immediate_and_deshacer_brings_it_back(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch)
    assert state.can_undo is False
    state.move_line([12_000])
    state.cut_here()
    state.remove_selected()
    assert len(state.rows) == 2  # nothing selected yet: nothing removed
    state.move_line([20_000])
    state.select_part(2)
    assert state.playhead_ms == 20_000  # selecting never moves the line (UX review)
    state.remove_selected()
    assert [r.label for r in state.rows] == ["Parte 1 · 0:00 a 0:12"]
    assert state.selected == 0
    # named by its times: the parts are renumbered after a removal (UX review)
    assert state.notice == "Quitaste la parte de 0:12 a 0:31. Si fue un error, toca «Deshacer»."
    state.undo()  # the removal
    assert [r.label for r in state.rows] == ["Parte 1 · 0:00 a 0:12", "Parte 2 · 0:12 a 0:31"]
    assert state.notice == "Volvió la parte de 0:12 a 0:31."
    state.undo()  # the cut
    assert [r.label for r in state.rows] == ["Parte 1 · 0:00 a 0:31"]
    assert state.notice == "Quitamos el último corte."
    assert state.can_undo is False
    state.undo()  # nothing left: nothing changes
    assert len(state.rows) == 1


async def test_a_refused_cut_leaves_nothing_to_undo(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch)
    state.cut_here()  # at 0:00: «Aquí ya empieza una parte…»
    assert state.error != "" and state.can_undo is False


async def test_pausar_puts_the_line_where_the_video_stopped(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch)
    key = state.line_key
    state.started()
    assert state.playing is True
    state.paused_at(17_250)
    assert state.playing is False and state.playhead_ms == 17_250
    assert state.line_key == key + 1  # the slider remounts at the new place
    state.paused_at(5_000)  # a stray report when not playing never moves the line
    assert state.playhead_ms == 17_250


async def test_cortar_aqui_while_watching_cuts_at_the_frame_on_screen(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch)
    state.started()
    state.cut_here(9_500)
    assert state.playing is False and state.playhead_ms == 9_500
    assert [r.label for r in state.rows] == ["Parte 1 · 0:00 a 0:09", "Parte 2 · 0:09 a 0:31"]


async def test_the_cutter_has_its_own_address_and_atras_closes_it(monkeypatch) -> None:
    """N5: opening pushes `/catalog?cortar=<id>`; the phone's «atrás» drops it and the
    cutter closes (asking first with changes, and «Volver» puts the address back)."""
    from .catalog_cut_state import cut_href

    query: dict[str, str] = {}
    monkeypatch.setattr(CatalogCutState, "_url_cut", lambda self: query.get("cortar", ""))
    state = CatalogCutState()
    events = await _open_events(state, monkeypatch)
    assert cut_href(_MEDIA) == f"/catalog?cortar={_MEDIA}" and len(events) == 1
    query["cortar"] = _MEDIA
    assert state.sync_url() == [] and state.open  # the push landed: nothing to do
    query.clear()  # «atrás» without changes
    state.sync_url()
    assert state.open is False
    events = await _open_events(state, monkeypatch)
    query["cortar"] = _MEDIA
    state.move_line([12_000])
    state.cut_here()
    query.clear()  # «atrás» with changes: ask, and put `?cortar=` straight back
    assert len(state.sync_url()) == 1  # a second «atrás» lands on the same question
    assert state.open and state.leave_open
    query["cortar"] = _MEDIA
    assert state.stay() == []  # «Volver»: the address is already back
    assert state.leave_open is False
    # a reload with `?cortar=` this tab did not open: dropped, the Galería shows
    fresh = CatalogCutState()
    query["cortar"] = _MEDIA
    assert len(fresh.sync_url()) == 1 and fresh.open is False


async def _open_events(state: CatalogCutState, monkeypatch) -> list:
    gallery = CatalogGalleryState()
    gallery.items = [_video()]

    async def get_state(self: Any, cls: type) -> Any:
        return gallery if cls is CatalogGalleryState else _Auth()

    monkeypatch.setattr(CatalogCutState, "get_state", get_state)
    return await CatalogCutState.open_cut.fn(state, _MEDIA) or []


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
    # off the address (history back), track_cut, the «Listo, ya estamos cortando» toast
    assert len(events) == 3


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


async def test_a_second_guardar_while_saving_sends_nothing(monkeypatch) -> None:
    monkeypatch.setattr(module, "start_cut", lambda *_a: pytest.fail("sent twice"))
    state = CatalogCutState()
    await _open(state, monkeypatch)
    state.move_line([12_000])
    state.cut_here()
    state.saving = True
    assert [e async for e in CatalogCutState.confirm_save.fn(state)] == []


async def test_a_gone_video_or_a_lost_session_says_so(monkeypatch) -> None:
    def gone(*_a: Any) -> str:
        raise KeyError("gone")

    monkeypatch.setattr(module, "start_cut", gone)
    state = CatalogCutState()
    await _open(state, monkeypatch)
    state.move_line([12_000])
    state.cut_here()
    await _drain(CatalogCutState.confirm_save.fn(state))
    assert state.error.startswith("Ese video ya no está en tu Galería.")
    assert state.saving is False and state.open is True

    class _NoSession:
        session_tenant_id = ""

    async def no_session(self: Any, cls: type) -> Any:
        return _NoSession()

    monkeypatch.setattr(CatalogCutState, "get_state", no_session)
    await _drain(CatalogCutState.confirm_save.fn(state))
    assert state.error.startswith("Algo falló de nuestro lado.")


async def test_leaving_galeria_closes_the_cutter(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch)
    state.move_line([12_000])
    state.cut_here()
    state.page_left()
    assert state.open is False and state.rows == []


def test_the_section_keeps_watching_while_a_cut_runs(monkeypatch) -> None:
    from . import catalog_gallery_provider as provider

    class _Job:
        def __init__(self, status: str) -> None:
            self.id = UUID(int=7)
            self.status = status
            self.part_ids = (UUID(int=8), UUID(int=9)) if status != "queued" else ()

    class _Service:
        def __init__(self, status: str) -> None:
            self.status = status

        def list_business_media(self, **_k: Any) -> tuple[()]:
            return ()

        def list_gallery_jobs(self, **_k: Any) -> tuple[()]:
            return ()

        def list_cut_jobs(self, **_k: Any) -> tuple[Any, ...]:
            return (_Job(self.status),)

    monkeypatch.setattr(provider, "_service", lambda: _Service("parts_saved"))
    snapshot = provider.load_gallery(_TENANT, UUID(int=1))
    assert snapshot.busy and snapshot.cuts == ((str(UUID(int=7)), "parts_saved", 2),)
    monkeypatch.setattr(provider, "_service", lambda: _Service("done"))
    assert provider.load_gallery(_TENANT, UUID(int=1)).busy is False


async def _drain(events: Any) -> list[Any]:
    return [e async for e in events]


async def test_the_line_follows_playback_and_the_end_brings_it_back(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch)
    state.move_line([5_000])
    state.started()
    state.follow(7_500)
    assert state.playhead_ms == 7_500 and state.playhead_text == "0:07,5"
    assert state.playback_ended() is not None  # the video seeks back
    assert state.playing is False and state.playhead_ms == 5_000
    state.follow(9_000)  # a late tick after the end moves nothing
    assert state.playhead_ms == 5_000
    assert state.playback_ended() is None


async def test_a_double_tap_on_cortar_video_pushes_one_entry(monkeypatch) -> None:
    state = CatalogCutState()
    first = await _open_events(state, monkeypatch)
    again = await _open_events(state, monkeypatch)
    assert len(first) == 1 and again == []


def test_the_cutters_address_keeps_the_others() -> None:
    from .catalog_cut_state import cut_href

    assert cut_href("m1", {"volver": "/create"}) == "/catalog?volver=%2Fcreate&cortar=m1"
    assert cut_href("", {"volver": "/create", "cortar": "m1"}) == "/catalog?volver=%2Fcreate"
    assert cut_href("", {"cortar": "m1"}) == "/catalog"


async def test_leaving_galeria_mid_save_never_steps_back_on_another_page(monkeypatch) -> None:
    state = CatalogCutState()
    await _open(state, monkeypatch)
    state.saving = True
    state.page_left()
    assert state.open is True  # the save finishes
    assert state._leave_nav() == []  # …and does not drag the owner back
