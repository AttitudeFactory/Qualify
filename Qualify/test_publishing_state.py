"""Tests for `PublishState` — the files, the order, the modes, the descriptions, the
accounts and the run of «Publicar ahora» (spec `docs/mockups/publicar-varias-imagenes.md`).

Constructing a `rx.State` directly only works under pytest (`is_testing_env()`), and
`run_batch` needs a live event context (`get_state`), so the run itself is exercised in
`test_publish_engine.py` with fakes; here the foreground handlers run for real, and the
background handler's seams (`_ProviderPorts`, `_finish`, `_apply_record`) directly.
"""

from __future__ import annotations

import asyncio
import inspect
from uuid import UUID

import pytest
from qualify_api.publishing import MEDIA_TYPE_STORIES

from . import publish_engine as engine
from . import publishing_state as state_module
from .publish_engine import JobRecord, RunEnd
from .publish_wizard_vm import (
    MODE_CAROUSEL,
    MODE_ONE_BY_ONE,
    MODE_POST,
    MODE_STORIES,
    MODE_STORY,
    STATUS_FAILED,
    STATUS_PUBLISHED,
    STATUS_RUNNING,
    STATUS_UNKNOWN,
    STEP_ORDER,
)
from .publishing_state import (
    _MAX_ITEMS,
    PublishState,
    _ProviderPorts,
    _resolve_media,
)
from .publishing_vm import ConnectionOptionVM, PublishAttemptVM

_IG = ConnectionOptionVM(
    id="c-ig", external_username="bianki", platform="instagram", handle="@bianki"
)
_IG2 = ConnectionOptionVM(
    id="c-ig2", external_username="polette", platform="instagram", handle="@polette"
)
_FB = ConnectionOptionVM(
    id="c-fb",
    external_username="bianki",
    platform="facebook",
    selectable=False,
    note="Todavía no publicamos en Facebook desde aquí.",
)


class _FakeUpload:
    def __init__(
        self, data: bytes = b"x", content_type: str = "image/jpeg", filename: str = "a.jpg"
    ) -> None:
        self._data = data
        self.content_type = content_type
        self.filename = filename

    async def read(self) -> bytes:
        return self._data


def _state(*names: str, connections: list | None = None) -> PublishState:
    s = PublishState()
    s.connections = connections if connections is not None else [_IG]
    s.selected_connection_id = "c-ig"
    if names:
        asyncio.run(s.add_files([_FakeUpload(n.encode(), filename=f"{n}.jpg") for n in names]))
    return s


def _ids(s: PublishState) -> list[str]:
    return [item.id for item in s.pending_items]


def _data(s: PublishState) -> list[bytes]:
    return [s._files[i].data for i in s._order]


# -- files ---------------------------------------------------------------------------------


def test_add_files_appends_in_order_with_numbers_and_labels() -> None:
    s = _state("a", "b")
    asyncio.run(s.add_files([_FakeUpload(b"v", "video/mp4", "c.mp4")]))
    assert [i.label for i in s.pending_items] == ["Foto 1", "Foto 2", "Video 3"]
    assert [i.position for i in s.pending_items] == [1, 2, 3]
    assert _data(s) == [b"a", b"b", b"v"]
    assert set(s.item_captions) == set(_ids(s))


def test_add_files_rejects_over_the_gallery_cap_as_one_batch() -> None:
    s = _state(*[f"f{i}" for i in range(9)])
    result = asyncio.run(s.add_files([_FakeUpload(), _FakeUpload()]))
    assert result is not None
    assert len(s.pending_items) == 9
    assert _MAX_ITEMS == 10


def test_add_files_never_guesses_a_video() -> None:
    assert _resolve_media("image/png", "a.png") is None
    assert _resolve_media(None, "clip.mov") == ("VIDEO", "video/quicktime")
    s = _state()
    assert asyncio.run(s.add_files([_FakeUpload(content_type="", filename="x.heic")])) is not None
    assert s.pending_items == []


def test_a_refused_pick_stays_on_screen_until_a_valid_one() -> None:
    s = _state()
    s.mark_drop_rejected([])
    assert s.last_drop_rejected
    asyncio.run(s.add_files([_FakeUpload()]))
    assert not s.last_drop_rejected


def test_remove_renumbers_and_undo_puts_it_back() -> None:
    s = _state("a", "b", "c")
    b = _ids(s)[1]
    toast = s.remove_item(b, True)
    assert toast is not None
    assert [i.label for i in s.pending_items] == ["Foto 1", "Foto 2"]
    assert _data(s) == [b"a", b"c"]
    s.undo_remove()
    assert _data(s) == [b"a", b"b", b"c"]
    assert [i.label for i in s.pending_items] == ["Foto 1", "Foto 2", "Foto 3"]


def test_new_files_after_ordering_go_to_the_end() -> None:
    s = _state("a", "b", "c")
    s.place(_ids(s)[2], 0)
    asyncio.run(s.add_files([_FakeUpload(b"d", filename="d.jpg")]))
    assert _data(s) == [b"c", b"a", b"b", b"d"]


# -- modes ---------------------------------------------------------------------------------


def test_two_files_default_to_the_carousel_and_one_by_one_is_off_above_nine() -> None:
    s = _state("a", "b")
    assert s.mode == MODE_CAROUSEL
    assert s.choose_kind(MODE_ONE_BY_ONE)
    assert s.mode == MODE_ONE_BY_ONE
    asyncio.run(s.add_files([_FakeUpload(bytes([i]), filename=f"{i}.jpg") for i in range(8)]))
    assert len(s.pending_items) == 10
    assert s.mode == MODE_CAROUSEL
    assert s.one_by_one_reason == "Una por una llega hasta 9. Quita 1 en el paso anterior."
    assert not s.choose_kind(MODE_ONE_BY_ONE)


def test_three_files_as_historias_is_available() -> None:
    s = _state("a", "b", "c")
    assert s.choose_kind(MODE_STORIES)
    assert s.mode == MODE_STORIES
    assert s.can_publish


def test_dropping_below_two_goes_back_to_the_single_kind() -> None:
    s = _state("a", "b")
    s.choose_kind(MODE_STORIES)
    s.step = STEP_ORDER
    s.remove_item(_ids(s)[0])
    assert s.mode == MODE_STORY
    assert s.step_id != STEP_ORDER  # the order step no longer applies
    s2 = _state("a", "b")
    s2.choose_kind(MODE_ONE_BY_ONE)
    s2.remove_item(_ids(s2)[0])
    assert s2.mode == MODE_POST


def test_a_historia_becomes_historias_when_a_second_file_arrives() -> None:
    s = _state("a")
    s.choose_kind(MODE_STORY)
    asyncio.run(s.add_files([_FakeUpload(b"b", filename="b.jpg")]))
    assert s.mode == MODE_STORIES


def test_steps_count_live() -> None:
    s = _state("a")
    assert (s.step_number, s.step_total) == (1, 3)
    asyncio.run(s.add_files([_FakeUpload(b"b", filename="b.jpg")]))
    assert s.step_total == 4
    s.connections = [_IG, _IG2, _FB]
    assert s.step_total == 5


# -- order -------------------------------------------------------------------------------


def test_the_menu_moves_without_dragging() -> None:
    s = _state("a", "b", "c", "d")
    ids = _ids(s)
    s.place(ids[3], 0)  # Primero
    assert _data(s) == [b"d", b"a", b"b", b"c"]
    s.place(ids[3], 1)  # Bajar uno
    assert _data(s) == [b"a", b"d", b"b", b"c"]
    s.place(ids[3], 3)  # Último
    assert _data(s) == [b"a", b"b", b"c", b"d"]
    s.place(ids[3], 2)  # Subir uno
    assert _data(s) == [b"a", b"b", b"d", b"c"]
    assert s.announce == "Foto 4, ahora en la posición 3 de 4."
    s.remove_item(ids[0], True)  # Quitar
    assert _data(s) == [b"b", b"d", b"c"]


def test_drag_and_keyboard_move_the_same_list() -> None:
    s = _state("a", "b", "c")
    ids = _ids(s)
    s.pick(ids[0])
    s.drop(ids[2])
    assert _data(s) == [b"b", b"c", b"a"]
    s.handle_key(ids[1], " ")
    s.handle_key(ids[1], "ArrowDown")
    assert _data(s) == [b"c", b"b", b"a"]
    s.handle_key(ids[1], "Escape")
    assert _data(s) == [b"b", b"c", b"a"]


def test_numbers_stay_with_their_file_when_it_moves() -> None:
    s = _state("a", "b")
    s.place(_ids(s)[1], 0)
    assert [i.label for i in s.pending_items] == ["Foto 2", "Foto 1"]
    assert [i.position for i in s.pending_items] == [1, 2]


def test_reordering_a_carousel_changes_what_reaches_start_many(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _state("a", "b", "c")
    s.place(_ids(s)[2], 0)
    s.caption = "combo"
    assert s.publish() is not None
    seen: dict = {}

    async def fake_start_many(**kwargs: object) -> PublishAttemptVM:
        seen.update(kwargs)
        return PublishAttemptVM("a1", "processing", False, "", "", False, 60)

    monkeypatch.setattr(state_module, "start_many_publish", fake_start_many)
    ports = _ProviderPorts(s, tenant_id=UUID(int=1), connection_id=UUID(int=2), token=s._run_token)
    (job,) = s._jobs
    asyncio.run(ports.start(job, "K:0"))
    assert [item.fileobj.read() for item in seen["items"]] == [b"c", b"a", b"b"]
    assert seen["caption"] == "combo"
    assert seen["idempotency_key"] == "K:0"


def test_one_by_one_hands_each_its_own_description_in_reverse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s = _state("a", "b", "c")
    s.choose_kind(MODE_ONE_BY_ONE)
    for item, text in zip(s.pending_items, ["uno", "dos", "tres"], strict=True):
        s.set_item_caption(item.id, text)
    s.publish()
    assert [(j.files[0].data, j.caption) for j in s._jobs] == [
        (b"c", "tres"),
        (b"b", "dos"),
        (b"a", "uno"),
    ]
    assert s.run_total == 3
    calls: list = []

    async def fake_start(**kwargs: object) -> PublishAttemptVM:
        calls.append(kwargs)
        return PublishAttemptVM("a", "processing", False, "", "", False, 60)

    monkeypatch.setattr(state_module, "start_publish", fake_start)
    ports = _ProviderPorts(s, tenant_id=UUID(int=1), connection_id=UUID(int=2), token="t")
    asyncio.run(ports.start(s._jobs[0], f"{s._batch_key}:0"))
    assert calls[0]["caption"] == "tres" and calls[0]["media_product_type"] == "IMAGE"


def test_historias_go_out_as_stories_in_the_listed_order() -> None:
    s = _state("a", "b", "c")
    s.choose_kind(MODE_STORIES)
    s.caption = "nunca se manda"
    s.publish()
    assert [j.files[0].data for j in s._jobs] == [b"a", b"b", b"c"]
    assert {j.product for j in s._jobs} == {MEDIA_TYPE_STORIES}
    assert {j.caption for j in s._jobs} == {""}


# -- descriptions -------------------------------------------------------------------------


def test_use_this_text_fills_only_the_empty_ones_and_can_be_undone() -> None:
    s = _state("a", "b", "c")
    ids = _ids(s)
    assert not s.can_copy_caption
    s.set_item_caption(ids[0], "Hoy 2x1")
    s.set_item_caption(ids[2], "propio")
    assert s.can_copy_caption
    assert s.copy_first_caption() is not None
    assert [s.item_captions[i] for i in ids] == ["Hoy 2x1", "Hoy 2x1", "propio"]
    s.undo_copy_caption()
    assert [s.item_captions[i] for i in ids] == ["Hoy 2x1", "", "propio"]


# -- accounts --------------------------------------------------------------------------------


def test_facebook_is_listed_but_cannot_be_chosen() -> None:
    s = _state(connections=[_IG, _FB])
    s.selected_connection_id = ""
    assert s.select_connection("c-fb") is None
    assert s.selected_connection_id == ""
    assert s.select_connection("c-ig") is not None
    assert s.selected_connection_id == "c-ig"


def test_one_instagram_is_chosen_for_the_owner_even_with_facebook_listed() -> None:
    s = PublishState()
    s.connections = [_IG, _FB]
    assert s._preselect_single_connection() == "c-ig"
    assert s.selectable_count == 1
    two = PublishState()
    two.connections = [_IG, _IG2]
    assert two._preselect_single_connection() == ""


def test_no_instagram_means_publish_is_refused() -> None:
    s = _state("a", connections=[_FB])
    s.selected_connection_id = "c-fb"
    assert not s.has_instagram
    assert not s.can_publish
    s.publish()
    assert s.phase == "idle" and s._jobs == []


def test_review_sentence_and_button_follow_the_mode() -> None:
    s = _state("a", "b", "c")
    s.choose_kind(MODE_ONE_BY_ONE)
    assert s.review_text.startswith("Salen ahora en Instagram @bianki: 3 publicaciones")
    assert s.primary_label == "Publicar las 3"
    s.choose_kind(MODE_STORIES)
    assert s.primary_label == "Publicar las 3 historias"


# -- the run -----------------------------------------------------------------------------


def test_publish_twice_starts_one_run() -> None:
    s = _state("a", "b")
    first = s.publish()
    assert first is not None and s.phase == "running"
    key = s._batch_key
    assert s.publish() is None
    assert s.continue_run() is None
    assert s._batch_key == key


def test_nothing_changes_while_publishing() -> None:
    s = _state("a", "b")
    s.publish()
    before = _data(s)
    assert asyncio.run(s.add_files([_FakeUpload(b"z")])) is None
    s.remove_item(_ids(s)[0])
    s.place(_ids(s)[1], 0)
    s.set_caption("tarde")
    assert _data(s) == before and s.caption == ""
    assert not s.can_edit_gallery


def _fail_midway(s: PublishState, at: int, status: str = STATUS_FAILED) -> None:
    for index in range(at):
        s._apply_record(index, JobRecord(status=STATUS_PUBLISHED, key=f"{s._batch_key}:{index}"))
    s._apply_record(at, JobRecord(status=status, key=f"{s._batch_key}:{at}", reason="No salió."))
    s._finish(RunEnd("failed", at))


def test_a_failure_midway_shows_how_many_went_out_and_continuar_resumes() -> None:
    s = _state("a", "b", "c", "d", "e")
    s.choose_kind(MODE_ONE_BY_ONE)
    s.publish()
    _fail_midway(s, 2)  # jobs: e, d out; c failed
    assert s.phase == "failure" and s.resumable
    assert s.failed_title == "Salieron 2 de 5. La foto 3 no salió."
    assert s.primary_label == "Continuar desde la foto 3"
    assert s.failed_next.endswith("seguimos desde la foto 3 y tu mural queda en orden.")
    assert [i.status for i in s.pending_items] == [
        "waiting",
        "waiting",
        "failed",
        "published",
        "published",
    ]
    assert s.pending_items[3].status_label == "Publicada"
    # the list is locked: changing it now would break what is out
    assert not s.can_edit_gallery
    assert s.publish() is None  # never a new batch over a run waiting to continue
    batch = s._batch_key
    assert s.continue_run() is not None
    assert s.phase == "running" and s._batch_key == batch
    assert s.run_done == 2


def test_continuar_never_runs_while_the_account_must_be_reconnected() -> None:
    s = _state("a", "b", "c")
    s.choose_kind(MODE_STORIES)
    s.publish()
    s._apply_record(0, JobRecord(status=STATUS_PUBLISHED, key="k0"))
    s._apply_record(1, JobRecord(status=STATUS_FAILED, key="k1", needs_reconnect=True))
    s._finish(RunEnd("failed", 1))
    assert s.needs_reconnect and s.resumable
    assert s.continue_run() is None


def test_an_unknown_single_outcome_is_continued_not_republished() -> None:
    s = _state("a")
    s.publish()
    _fail_midway(s, 0, STATUS_UNKNOWN)
    assert s.resumable and s.run_unknown
    assert s.publish() is None
    assert s.continue_run() is not None


def test_a_settled_single_failure_lets_the_owner_try_again_as_a_new_run() -> None:
    s = _state("a")
    s.publish()
    first = s._batch_key
    _fail_midway(s, 0)
    assert not s.resumable and s.can_edit_gallery
    assert s.error == "No salió."
    assert s.publish() is not None
    assert s._batch_key != first


def test_leaving_mid_run_leaves_the_rest_waiting() -> None:
    s = _state("a", "b", "c")
    s.choose_kind(MODE_ONE_BY_ONE)
    s.publish()
    s.request_stop()
    assert s._stop_requested
    s._apply_record(0, JobRecord(status=STATUS_PUBLISHED, key="k"))
    s._finish(RunEnd("stopped", 1))
    assert s.stopped and s.resumable
    assert s.leftover_text == "Te quedaron 2 sin publicar de tu mural."
    assert s.leave_text.startswith("Las que ya salieron")


def test_dejar_asi_ends_partially_and_releases_the_bytes() -> None:
    s = _state("a", "b", "c")
    s.choose_kind(MODE_STORIES)
    s.publish()
    _fail_midway(s, 1)
    s.keep_as_is()
    assert s.phase == "partial"
    assert s.partial_text == "Salieron 1 de 3. Las otras 2 no se publicaron."
    assert s._files == {} and s._jobs == []


def test_success_shows_the_listo_and_releases_the_bytes() -> None:
    s = _state("a", "b", "c")
    s.choose_kind(MODE_ONE_BY_ONE)
    s.publish()
    for i in range(3):
        s._apply_record(i, JobRecord(status=STATUS_PUBLISHED))
    toast = s._finish(RunEnd("done"))
    assert toast is not None and s.phase == "success"
    assert s.done_text == (
        "Listo, tus 3 publicaciones ya están en Instagram. Tu mural quedó armado."
    )
    assert s._files == {}


def test_progress_counts_publications_not_positions() -> None:
    s = _state("a", "b", "c", "d")
    s.choose_kind(MODE_ONE_BY_ONE)
    s.publish()
    s._apply_record(0, JobRecord(status=STATUS_PUBLISHED))
    s._apply_record(1, JobRecord(status=STATUS_RUNNING, attempt_id="x", polling=True))
    assert s.progress_title == "Publicando 2 de 4…"
    assert s.progress_value == 25
    assert [i.status for i in s.pending_items] == ["waiting", "waiting", "running", "published"]
    assert s.elapsed_label != ""


def test_reset_form_empties_step_one_and_keeps_the_single_account() -> None:
    s = _state("a", "b")
    s.caption = "x"
    s.selected_connection_id = ""
    s.reset_form()
    assert s.pending_items == [] and s.caption == "" and s.phase == "idle"
    assert s.selected_connection_id == "c-ig"


def test_reset_form_is_a_no_op_while_publishing() -> None:
    s = _state("a")
    s.publish()
    s.reset_form()
    assert s.pending_items and s.phase == "running"


def test_run_batch_is_the_only_engine_driver() -> None:
    """One engine: the background handler delegates the sequence to `run_jobs` and
    holds no poll loop of its own (the debt of two copies removed 2026-11-12)."""
    source = inspect.getsource(PublishState.run_batch.fn)
    assert "engine.run_jobs(" in source
    assert "asyncio.sleep" not in source
    assert "for _ in range" not in source
    assert engine.MAX_POLLS == 30


# -- the run's account is pinned (code review 2026-11-12) --------------------------------


def _resumable_mural(*names: str) -> PublishState:
    s = _state(*names, connections=[_IG, _IG2])
    s.choose_kind(MODE_ONE_BY_ONE)
    s.publish()
    _fail_midway(s, 2, STATUS_UNKNOWN)
    return s


def test_publish_pins_the_chosen_account() -> None:
    s = _state("a", "b")
    s.publish()
    assert s.run_connection_id == "c-ig"


def test_the_account_cannot_change_while_a_run_waits_to_continue() -> None:
    s = _resumable_mural("a", "b", "c", "d")
    assert s.resumable and s.account_locked
    assert s.select_connection("c-ig2") is None
    assert s.selected_connection_id == "c-ig"


def test_continuar_uses_the_pinned_account_even_if_the_selection_moved() -> None:
    s = _resumable_mural("a", "b", "c", "d")
    s.selected_connection_id = "c-ig2"  # whatever moved it, the run does not follow
    assert s.continue_run() is not None
    assert s.phase == "running"
    assert s.run_connection_id == "c-ig" and s.selected_connection_id == "c-ig"
    assert "self.run_connection_id" in inspect.getsource(PublishState.run_batch.fn)
    assert "self.selected_connection_id" not in inspect.getsource(PublishState.run_batch.fn)


def test_continuar_is_refused_when_the_pinned_account_is_gone() -> None:
    s = _resumable_mural("a", "b", "c")
    s.connections = [_IG2]  # @bianki disconnected, @polette still there
    assert not s.pinned_account_ready and not s.can_continue
    batch, records = s._batch_key, list(s._records)
    result = s.continue_run()
    assert result is not None  # only the toast
    assert s.phase == "failure" and s._records == records and s._batch_key == batch
    assert s.error == (
        "La cuenta de Instagram de esta publicación ya no está conectada. Conéctala de "
        "nuevo en Tus redes para seguir."
    )


def test_continuar_without_a_pinned_account_never_starts() -> None:
    s = _resumable_mural("a", "b", "c")
    s.run_connection_id = ""
    s.selected_connection_id = ""
    s.continue_run()
    assert s.phase == "failure"


def test_an_unexpected_stop_never_leaves_the_screen_running() -> None:
    s = _state("a", "b", "c")
    s.choose_kind(MODE_STORIES)
    s.publish()
    s._apply_record(0, JobRecord(status=STATUS_PUBLISHED, key="k0"))
    s._apply_record(1, JobRecord(status=STATUS_RUNNING, key="k1", attempt_id="x"))
    s._abort(engine.START_FAILED)
    assert s.phase == "failure" and not s.busy
    assert s._records[1].status == STATUS_UNKNOWN  # «Continuar» keeps its key
    assert s.resumable
    source = inspect.getsource(PublishState.run_batch.fn)
    assert "except Exception" in source and "self._abort(" in source
    assert "UUID(" not in source  # no parse that can raise outside a guard


def test_success_and_dejar_asi_forget_the_list_too() -> None:
    s = _state("a", "b")
    s.publish()
    s._apply_record(0, JobRecord(status=STATUS_PUBLISHED))
    s._finish(RunEnd("done"))
    assert s._order == [] and s._numbers == {} and s._files == {}
    p = _state("a", "b", "c")
    p.choose_kind(MODE_STORIES)
    p.publish()
    _fail_midway(p, 1)
    p.keep_as_is()
    assert p._order == [] and p._numbers == {} and p._files == {}


def test_one_by_one_descriptions_are_named_by_their_place() -> None:
    s = _state("a", "b", "c")
    s.place(_ids(s)[2], 0)
    first = s.pending_items[0]
    assert first.label == "Foto 3"  # the file keeps its own number…
    assert first.publication_title == "Publicación 1 de 3"  # …the card names its place
    assert first.caption_label == "Descripción de la publicación 1 (opcional)"
