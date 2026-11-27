"""EF-18 (m-25026598): the contact sheet right before «Aprobar», offline.

The sheet's reader is a double of `DbContactSheets` (`provider.READER`) and the minting
of `/r2media` paths is a double of `issue_view_path` (`provider.MINT`); the session's
tenant is stubbed on the state's CLASS and the background `watch` runs through
`.fn(state)` (the harness of `test_final_video_card.py`).

Pins:
1. The panel sits before «Aprobar» on both screens: the Clip's page and «Tu video
   completo».
2. Every frame goes out through `/r2media/`, and only keys of the viewing business.
3. Three columns on every width, a 375 px phone included (Deivid, option A).
4. Without a sheet «Aprobar» stays as it was: nothing of the panel reaches it.
5. One read per piece and file; retries only while the worker has not made it, only
   while mounted, bounded; a failed read leaves no sheet.
6. Each frame's `alt` and button name as a screen reader says them («el segundo 3»,
   «el minuto 1:05»), «0:03» under it; the ticket's texts and «Toca un cuadro…».
7. «Si algo se ve mal, …» names the way each screen really offers, only while offered.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
import reflex as rx
from qualify_api.creative.contact_sheet import (
    CONTACT_SHEET_HELP,
    CONTACT_SHEET_TITLE,
    ContactSheetView,
    SheetFrameView,
)

from . import contact_sheet_panel as module
from . import contact_sheet_provider as provider
from . import contact_sheet_vm as vm
from . import creative_pages
from . import final_video_card as final_card
from .contact_sheet_panel import ContactSheetState, contact_sheet_panel
from .final_video_card_state import FinalVideoState
from .r2_media import issue_view_path

TENANT = UUID("a0000000-0000-4000-8000-0000000000a1")
OTHER_TENANT = UUID("b0000000-0000-4000-8000-0000000000b2")
DRAFT = UUID("e0000000-0000-4000-8000-0000000000e1")
VIDEO = f"t/{TENANT}/generated/{DRAFT}/r1/preview.mp4"


def _frame(n: int, seconds: float, tenant: UUID = TENANT) -> SheetFrameView:
    return SheetFrameView(
        key=f"t/{tenant}/generated/{DRAFT}/r1/contact-{n}.jpg",
        time_s=seconds,
        width=540,
        height=960,
    )


def _view(video_key: str = VIDEO, frames: tuple[SheetFrameView, ...] | None = None):
    return ContactSheetView(
        video_key=video_key,
        frames=frames
        if frames is not None
        else tuple(_frame(i + 1, s) for i, s in enumerate((0.0, 1.5, 3.2, 6.0, 9.9, 14.8))),
        sheet_key=f"t/{TENANT}/generated/{DRAFT}/r1/contact-sheet.jpg",
        version="1",
    )


class Reader:
    """A double of `DbContactSheets`: answers in turn, records each read."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.reads: list[tuple[UUID, UUID]] = []

    def read(self, *, tenant_id: UUID, draft_id: UUID) -> ContactSheetView | None:
        self.reads.append((tenant_id, draft_id))
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


class Tokens:
    """A double of the `/r2media` token store: one opaque token per object."""

    def __init__(self) -> None:
        self.issued: list[tuple[UUID, str, str]] = []

    def issue(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        self.issued.append((tenant_id, object_key, content_type))
        return f"tok{len(self.issued)}"


@pytest.fixture
def tokens(monkeypatch: pytest.MonkeyPatch) -> Tokens:
    store = Tokens()

    def mint(tenant_id: UUID, key: str) -> str:
        return issue_view_path(tenant_id, key, "image", "image/jpeg", store=store)

    monkeypatch.setattr(provider, "MINT", mint)
    return store


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[float]]:
    waited: list[float] = []

    async def sleep(seconds: float) -> None:
        waited.append(seconds)

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    SESSION["tenant"] = TENANT

    async def tenant(self: ContactSheetState) -> UUID | None:
        return SESSION["tenant"]

    monkeypatch.setattr(ContactSheetState, "_session_tenant", tenant)
    yield waited


#: The session's business as `_session_tenant` reads it (a test switches it).
SESSION: dict[str, UUID | None] = {"tenant": TENANT}


def _reader(monkeypatch: pytest.MonkeyPatch, *answers: Any) -> Reader:
    reader = Reader(*answers)
    monkeypatch.setattr(provider, "READER", reader)
    return reader


async def _mount(state: ContactSheetState, draft: str, video: str) -> None:
    """A panel mounting: `watch` (in order with `stop`), then the `read_loop` it hands
    off, with the token `watch` claimed."""
    spec = await ContactSheetState.watch.fn(state, draft, video)
    if spec is not None:
        await ContactSheetState.read_loop.fn(state, state._token)


async def _watch(state: ContactSheetState, draft: UUID = DRAFT, video: str = VIDEO) -> None:
    await _mount(state, str(draft), video)


# -- 1. before «Aprobar», on both screens ----------------------------------------------------


def test_the_clips_page_shows_the_sheet_before_its_decision() -> None:
    rendered = str(creative_pages._single_piece_detail())
    panel = rendered.find(module.PANEL_ID)
    assert panel != -1
    assert -1 < panel < rendered.find("q-decide-grid")  # the three decision cards
    # the panel is mounted with the piece and the video on screen
    assert "review_video_key" in rendered


def test_tu_video_completo_shows_the_sheet_before_aprobar() -> None:
    rendered = str(final_card.final_video_card(FinalVideoState.parent_id).render())
    panel = rendered.find(module.PANEL_ID)
    assert panel != -1
    assert panel < rendered.find(final_card.APPROVE_WHY_ID)


def test_the_clips_video_key_is_the_video_on_screen() -> None:
    from .creative_state import CreativeState
    from .creative_vm import DraftVM, MediaVM

    state = CreativeState()
    assert state.review_video_key == ""
    state.draft = DraftVM(
        draft_id=str(DRAFT),
        status="generated",
        status_label="",
        status_tone="neutral",
        media=(
            MediaVM(key="poster.jpg", media_type="image", position=0, label="Imagen"),
            MediaVM(key=VIDEO, media_type="video", position=1, label="Video"),
        ),
    )
    assert state.review_video_key == VIDEO
    state.draft = DraftVM(
        draft_id=str(DRAFT),
        status="generated",
        status_label="",
        status_tone="neutral",
        media=(MediaVM(key=VIDEO, media_type="video", position=0, label="Video"),),
        viewing_previous_version=True,
    )
    assert state.review_video_key == ""


# -- 2. /r2media only, keys of this business only --------------------------------------------


def test_frames_go_out_through_r2media(monkeypatch: pytest.MonkeyPatch, tokens: Tokens) -> None:
    _reader(monkeypatch, _view())
    read = provider.read_sheet(TENANT, DRAFT, VIDEO)
    assert read.made
    assert len(read.frames) == 6
    assert all(frame["url"].startswith("/r2media/") for frame in read.frames)
    assert {t for t, _k, _c in tokens.issued} == {TENANT}
    assert {c for _t, _k, c in tokens.issued} == {"image/jpeg"}


def test_a_key_of_another_business_is_never_minted(
    monkeypatch: pytest.MonkeyPatch, tokens: Tokens
) -> None:
    frames = (
        _frame(1, 0.0),
        _frame(2, 2.0, tenant=OTHER_TENANT),
        SheetFrameView(key=f"t/{TENANT}/../{OTHER_TENANT}/x.jpg", time_s=3.0),
        _frame(4, 4.0),
    )
    _reader(monkeypatch, _view(frames=frames))
    read = provider.read_sheet(TENANT, DRAFT, VIDEO)
    assert [frame["time"] for frame in read.frames] == ["0:00,0", "0:04,0"]  # under 10 s: tenths
    assert all(str(OTHER_TENANT) not in key for _t, key, _c in tokens.issued)


def test_business_key_needs_the_tenants_own_prefix() -> None:
    assert vm.business_key(TENANT, f"t/{TENANT}/generated/x.jpg")
    assert not vm.business_key(TENANT, f"t/{OTHER_TENANT}/generated/x.jpg")
    assert not vm.business_key(TENANT, f"gallery/{TENANT}/x.jpg")
    assert not vm.business_key(TENANT, f"t/{TENANT}/../x.jpg")
    assert not vm.business_key(TENANT, "")


def test_a_sheet_of_another_file_is_not_shown(
    monkeypatch: pytest.MonkeyPatch, tokens: Tokens
) -> None:
    _reader(monkeypatch, _view(video_key=f"t/{TENANT}/generated/{DRAFT}/r0/preview.mp4"))
    read = provider.read_sheet(TENANT, DRAFT, VIDEO)
    assert read.made and read.frames == ()
    assert tokens.issued == []


def test_a_frame_without_a_token_is_left_out(monkeypatch: pytest.MonkeyPatch) -> None:
    _reader(monkeypatch, _view())
    monkeypatch.setattr(provider, "MINT", lambda _t, key: "" if key.endswith("-2.jpg") else "/r")
    assert len(provider.read_sheet(TENANT, DRAFT, VIDEO).frames) == 5


# -- 3. three columns, a 375 px phone included (Deivid, option A) ---------------------------


def test_three_columns_on_every_width() -> None:
    assert module.GRID_COLUMNS == "repeat(3, 1fr)"
    rendered = str(
        contact_sheet_panel(FinalVideoState.parent_id, FinalVideoState.video_key).render()
    )
    assert '["gridTemplateColumns"] : "repeat(3, 1fr)"' in rendered
    # one value for every width: no breakpoint brings back two columns on a phone
    assert "repeat(2" not in rendered
    assert "min-width: 30em" not in rendered


def test_the_frames_open_bigger_and_say_so() -> None:
    rendered = str(contact_sheet_panel("d", "v").render())
    assert vm.TAP_HINT == "Toca un cuadro para verlo más grande."
    assert "Toca un cuadro para verlo m" in rendered  # «más» may be escaped
    assert '"zoom-in"' in rendered


def _frame_var() -> rx.Var:
    return rx.Var.create({"url": "/r2media/a", "time": "0:03", "alt": "A", "zoom": "Z"})


def test_each_frame_is_the_trigger_of_its_own_dialog() -> None:
    """The focus goes back to the frame that opened it: Radix does that for a dialog's
    own trigger. The dialog has a title, a description and «Cerrar»."""
    rendered = str(module._frame(_frame_var()).render())
    trigger = rendered.find("Trigger")
    assert trigger != -1
    assert trigger < rendered.find('"button"')  # the frame's button is the trigger
    for part in ("Title", "Description", "Close"):
        assert part in rendered
    assert vm.CLOSE_LABEL in rendered
    assert vm.ZOOM_HELP == "Fíjate que el texto se lea completo y no tape tu producto."


# -- 4. without a sheet, «Aprobar» as it was -------------------------------------------------


def test_aprobar_never_depends_on_the_sheet() -> None:
    state_name = ContactSheetState.get_full_name()
    assert state_name not in str(final_card._approve_button())
    assert state_name not in str(final_card._actions())
    assert state_name not in str(creative_pages._decision_bar())


async def test_no_sheet_yet_draws_nothing(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    reader = _reader(monkeypatch, None)
    state = ContactSheetState()
    await _watch(state)
    assert state.frames == []
    assert not state.has_frames
    assert len(reader.reads) == module.MAX_READS
    assert sleeps == [module.RETRY_SECONDS] * (module.MAX_READS - 1)
    rendered = str(contact_sheet_panel("d", "v").render())
    assert '"none"' in rendered  # the section takes no room without frames


# -- 5. one read per piece and file ----------------------------------------------------------


async def test_reads_once_per_piece_and_file(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    reader = _reader(monkeypatch, _view())
    state = ContactSheetState()
    await _watch(state)
    await _watch(state)  # a re-render, a remount of the same piece and file
    assert len(reader.reads) == 1
    assert reader.reads == [(TENANT, DRAFT)]
    assert len(state.frames) == 6
    assert sleeps == []
    other = f"t/{TENANT}/generated/{DRAFT}/r2/preview.mp4"
    reader.answers = [_view(video_key=other)]
    await _watch(state, video=other)  # a new version: read again
    assert len(reader.reads) == 2
    assert len(state.frames) == 6


async def test_retries_until_the_worker_made_it(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    reader = _reader(monkeypatch, None, None, _view())
    state = ContactSheetState()
    await _watch(state)
    assert len(reader.reads) == 3
    assert sleeps == [module.RETRY_SECONDS, module.RETRY_SECONDS]
    assert len(state.frames) == 6


async def test_leaving_the_screen_stops_the_retries(
    monkeypatch: pytest.MonkeyPatch, tokens: Tokens
) -> None:
    reader = _reader(monkeypatch, None)
    state = ContactSheetState()

    async def tenant(self: ContactSheetState) -> UUID:
        return TENANT

    async def sleep(_seconds: float) -> None:
        ContactSheetState.stop.fn(state)  # unmounted while waiting

    monkeypatch.setattr(ContactSheetState, "_session_tenant", tenant)
    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    await _watch(state)
    assert len(reader.reads) == 1


async def test_a_failed_read_leaves_no_sheet(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], caplog: pytest.LogCaptureFixture
) -> None:
    reader = _reader(monkeypatch, RuntimeError("db down"))
    state = ContactSheetState()
    await _watch(state)
    assert state.frames == []
    assert len(reader.reads) == 1  # no hammering a failing database
    assert "contact sheet unreadable" in caplog.text


async def test_no_draft_or_no_video_reads_nothing(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float]
) -> None:
    reader = _reader(monkeypatch, _view())
    state = ContactSheetState()
    await _mount(state, "", VIDEO)
    await _mount(state, str(DRAFT), "")
    assert reader.reads == []


# -- 6. alt, seconds, words, zoom -------------------------------------------------------------


def test_each_frame_says_its_second_and_alt(
    monkeypatch: pytest.MonkeyPatch, tokens: Tokens
) -> None:
    _reader(monkeypatch, _view())
    frames = provider.read_sheet(TENANT, DRAFT, VIDEO).frames
    assert [f["time"] for f in frames] == ["0:00", "0:01", "0:03", "0:06", "0:09", "0:14"]
    assert frames[2]["alt"] == "Cuadro de tu video en el segundo 3"
    assert frames[2]["zoom"] == "Ver más grande el cuadro del segundo 3"


@pytest.mark.parametrize(
    ("seconds", "alt", "zoom"),
    [
        (0, "Cuadro de tu video en el segundo 0", "Ver más grande el cuadro del segundo 0"),
        (3.2, "Cuadro de tu video en el segundo 3", "Ver más grande el cuadro del segundo 3"),
        (59.9, "Cuadro de tu video en el segundo 59", "Ver más grande el cuadro del segundo 59"),
        (60, "Cuadro de tu video en el minuto 1:00", "Ver más grande el cuadro del minuto 1:00"),
        (65, "Cuadro de tu video en el minuto 1:05", "Ver más grande el cuadro del minuto 1:05"),
    ],
)
def test_spoken_names(seconds: float, alt: str, zoom: str) -> None:
    assert vm.frame_alt(seconds) == alt
    assert vm.zoom_label(seconds) == zoom


def test_the_dialog_is_titled_with_the_frames_alt() -> None:
    big = str(module._big_frame(_frame_var()).render())
    # the title and the big picture's alt are both the frame's own `alt`
    assert big.count('"alt"') >= 2


# -- 7. what to do when something looks wrong: the real way of each screen ------------------


def test_each_screen_names_its_own_real_way() -> None:
    # the Clip: «Editar texto» edits the publication's copy, not the words on the video;
    # the way is the decision card «Pedir otra versión»
    assert vm.FIX_CLIP == "Si algo se ve mal, pide otra versión antes de aprobar."
    clip = str(creative_pages._contact_sheet())
    assert "Si algo se ve mal, pide otra versi" in clip
    assert "can_regenerate" in clip  # only while that way is offered
    decision = str(creative_pages._decision_bar())
    assert "Pedir otra versi" in decision
    # «Tu video completo»: «Cambiar esta» on a part, then «Crear otra versión»
    assert final_card.CHOOSE_LABEL in vm.FIX_PARTS
    assert final_card.CHANGE_SUBMIT == "Crear otra versión"  # the panel's button
    assert "crea otra versión" in vm.FIX_PARTS
    card = str(final_card._decisions(final_card.COLUMNS))
    assert "change_part_visible" in card
    assert "Si algo se ve mal, toca" in card


def test_no_fix_line_when_the_screen_offers_no_way() -> None:
    rendered = str(contact_sheet_panel("d", "v").render())
    assert "Si algo se ve mal" not in rendered
    with_fix = str(contact_sheet_panel("d", "v", fix=vm.FIX_CLIP).render())
    assert "Si algo se ve mal" in with_fix


@pytest.mark.parametrize(
    ("seconds", "label"),
    [(0, "0:00"), (3.9, "0:03"), (65, "1:05"), (-1, "0:00"), (float("nan"), "0:00")],
)
def test_time_label(seconds: float, label: str) -> None:
    assert vm.time_label(seconds) == label


def test_the_panel_has_its_heading_words_and_alt() -> None:
    assert vm.TITLE == CONTACT_SHEET_TITLE == "Revisa tu video antes de aprobarlo"
    assert vm.HELP == CONTACT_SHEET_HELP
    rendered = str(contact_sheet_panel("d", "v", heading="h2", framed=True).render())
    assert CONTACT_SHEET_TITLE in rendered
    assert module.HEADING_ID in rendered
    assert '"list"' in rendered and '"listitem"' in rendered
    assert "alt" in rendered
    assert vm.CLOSE_LABEL in rendered


# -- 8. never another business's frames, never another piece's ------------------------------

B_DRAFT = UUID("e0000000-0000-4000-8000-0000000000e9")
B_VIDEO = f"t/{OTHER_TENANT}/generated/{B_DRAFT}/r1/preview.mp4"


async def test_an_old_watch_never_writes_after_a_business_switch(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    """review-agent (blocking): business A's watch is retrying; a logout or a business
    switch resets the state; business B mounts its own panel. A's watch, whose next
    read finds A's sheet, must write nothing."""
    state = ContactSheetState()
    a_reads = 0

    class Reader2:
        def read(self, *, tenant_id: UUID, draft_id: UUID) -> ContactSheetView | None:
            nonlocal a_reads
            if tenant_id == OTHER_TENANT:
                return None  # B's sheet is not made yet
            a_reads += 1
            return None if a_reads == 1 else _view()  # A's arrives after the switch

    monkeypatch.setattr(provider, "READER", Reader2())
    switched = False

    async def switch_while_waiting(_seconds: float) -> None:
        nonlocal switched
        if switched:
            return
        switched = True
        state.reset()  # logout / switch (`auth_state._reset_business_states`)
        SESSION["tenant"] = OTHER_TENANT
        await _mount(state, str(B_DRAFT), B_VIDEO)  # B's panel

    monkeypatch.setattr(module.asyncio, "sleep", switch_while_waiting)
    await _watch(state)  # A's watch
    assert a_reads == 1  # A stopped at its next turn: no read for the old business
    assert state.frames == []
    assert state.showing == module._target(str(B_DRAFT), B_VIDEO)


async def test_a_read_landing_after_the_switch_is_dropped(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    """The worst case of the review: the switch happens DURING A's read, and B's panel
    gets the token a state counter would have repeated (1 after the reset). A's result
    must still be dropped by the write's own checks."""
    state = ContactSheetState()

    class Reader2:
        def read(self, *, tenant_id: UUID, draft_id: UUID) -> ContactSheetView | None:
            state.reset()  # logout / switch while A's read is in flight
            SESSION["tenant"] = OTHER_TENANT
            state.showing = module._target(str(B_DRAFT), B_VIDEO)  # B's panel mounted…
            state._token = 1  # …with the number a state counter would have reused
            return _view()  # A's sheet

    monkeypatch.setattr(provider, "READER", Reader2())
    await _watch(state)
    assert state.frames == []  # nothing of A on B's screen
    assert state._token == 1


async def test_a_reset_never_hands_an_old_token_back(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    state = ContactSheetState()
    _reader(monkeypatch, None)
    await _watch(state)
    old = state._token
    state.reset()
    assert state._token == 0
    await _watch(state)
    assert state._token > old  # the module's counter, never the state's


async def test_a_result_after_the_session_moved_on_is_dropped(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    class Reader2:
        def read(self, *, tenant_id: UUID, draft_id: UUID) -> ContactSheetView | None:
            SESSION["tenant"] = OTHER_TENANT  # the session moved on during the read
            return _view()

    monkeypatch.setattr(provider, "READER", Reader2())
    state = ContactSheetState()
    await _watch(state)
    assert state.frames == []


def test_a_panel_shows_only_its_own_piece() -> None:
    """The previous piece's frames never show for an instant, nor in a second panel: the
    panel compares `showing` with its own «draft|video»."""
    rendered = str(
        contact_sheet_panel(FinalVideoState.parent_id, FinalVideoState.video_key).render()
    )
    assert "showing" in rendered
    assert '"d1|v1"' in str(contact_sheet_panel("d1", "v1").render())


async def test_showing_is_the_panels_own_target(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    _reader(monkeypatch, _view())
    state = ContactSheetState()
    await _watch(state)
    assert state.showing == f"{DRAFT}|{VIDEO}" == module._key(str(DRAFT), VIDEO)
    assert len(state.frames) == 6
    # another piece mounts: its target first, the frames cleared before any read
    _reader(monkeypatch, None)
    await _watch(state, draft=B_DRAFT, video=VIDEO)
    assert state.showing == f"{B_DRAFT}|{VIDEO}"
    assert state.frames == []


async def test_not_made_is_remembered_for_a_while(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    reader = _reader(monkeypatch, None)
    state = ContactSheetState()
    await _watch(state)
    assert len(reader.reads) == module.MAX_READS
    ContactSheetState.stop.fn(state)
    await _watch(state)  # a remount within MISS_SECONDS: not 7 reads again
    assert len(reader.reads) == module.MAX_READS
    later = module.time.monotonic() + module.MISS_SECONDS + 1
    monkeypatch.setattr(module.time, "monotonic", lambda: later)
    await _watch(state)  # past it: read again
    assert len(reader.reads) == 2 * module.MAX_READS


# -- 9. live review 2026-11-25: the backend's origin, and labels that never repeat -----------


def test_frames_load_from_the_backend_like_every_r2_thumbnail() -> None:
    """The `/r2media` path is the BACKEND's (the frontend answers it with the app's
    HTML): the same `BACKEND_BASE` prefix as the piece's media (`creative_pages`) and
    «Tu video completo». In production it is the public origin, which Caddy routes."""
    from .r2_media import BACKEND_BASE

    # its own expression (the render escapes the regex's backslashes)
    prefix = "String(getBackendURL(env.UPLOAD))"
    assert prefix in str(BACKEND_BASE)
    small = str(module._frame(_frame_var()).render())
    big = str(module._big_frame(_frame_var()).render())
    for rendered in (small, big):
        assert prefix in rendered
        assert 'src:"/r2media' not in rendered
    assert prefix in str(creative_pages._single_piece_detail())  # the same helper


LIVE_TIMES = (0.5, 1.17, 1.83, 2.5, 3.17, 3.83)


def test_close_frames_get_tenths_and_never_repeat(
    monkeypatch: pytest.MonkeyPatch, tokens: Tokens
) -> None:
    frames = tuple(_frame(i + 1, t) for i, t in enumerate(LIVE_TIMES))
    _reader(monkeypatch, _view(frames=frames))
    drawn = provider.read_sheet(TENANT, DRAFT, VIDEO).frames
    times = [f["time"] for f in drawn]
    assert times == ["0:00,5", "0:01,2", "0:01,8", "0:02,5", "0:03,2", "0:03,8"]
    for field in ("time", "alt", "zoom"):
        assert len({f[field] for f in drawn}) == 6, field
    assert drawn[0]["alt"] == "Cuadro de tu video en el segundo 0,5"
    assert drawn[1]["zoom"] == "Ver más grande el cuadro del segundo 1,2"


def test_tenths_past_the_minute() -> None:
    assert vm.time_label(65.5, tenths=True) == "1:05,5"
    assert vm.spoken_time(65.5, tenths=True) == "minuto 1:05,5"
    assert vm.zoom_label(65.5, tenths=True) == "Ver más grande el cuadro del minuto 1:05,5"
    assert vm.time_label(59.96, tenths=True) == "1:00,0"  # the tenth carries


def test_when_tenths_are_used() -> None:
    assert vm.needs_tenths(LIVE_TIMES)  # a video under 10 s
    assert vm.needs_tenths((0.0, 4.0, 12.2, 12.8, 20.0))  # two frames in second 12
    assert not vm.needs_tenths((0.0, 3.2, 6.0, 9.9, 14.8))  # long and apart
    assert not vm.needs_tenths(())


# -- 10. last review: unmounted before the first read, pruning, «made» only with frames ------


async def test_a_panel_gone_before_its_first_read_never_reads(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    """`stop` runs in order after `watch`: the background read it handed off finds another
    token at its first lock and does not start."""
    reader = _reader(monkeypatch, _view())
    state = ContactSheetState()
    spec = await ContactSheetState.watch.fn(state, str(DRAFT), VIDEO)
    assert spec is not None
    claimed = state._token
    ContactSheetState.stop.fn(state)  # unmounted before the read started
    await ContactSheetState.read_loop.fn(state, claimed)
    assert reader.reads == []
    assert state.frames == []


async def test_old_misses_are_pruned_when_writing(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    _reader(monkeypatch, None)
    state = ContactSheetState()
    now = module.time.monotonic()
    state._missed = {
        "old|x": now - module.MISS_SECONDS - 1,  # past it: pruned
        "recent|y": now - 1,  # still within it: kept
    }
    await _watch(state)
    assert set(state._missed) == {"recent|y", module._target(str(DRAFT), VIDEO)}


async def test_made_without_a_drawable_frame_is_not_cached(
    monkeypatch: pytest.MonkeyPatch, sleeps: list[float], tokens: Tokens
) -> None:
    """A sheet made for another file (or with no frame of this business) draws nothing:
    it counts as not made — read again by the normal rule, never cached as done."""
    other_file = _view(video_key=f"t/{TENANT}/generated/{DRAFT}/r0/preview.mp4")
    reader = _reader(monkeypatch, other_file)
    state = ContactSheetState()
    await _watch(state)
    assert len(reader.reads) == module.MAX_READS
    assert not state._made and state.frames == []
    assert module._target(str(DRAFT), VIDEO) in state._missed
    # once drawable frames arrive (past the miss), they are cached as done
    later = module.time.monotonic() + module.MISS_SECONDS + 1
    monkeypatch.setattr(module.time, "monotonic", lambda: later)
    reader.answers = [_view()]
    await _watch(state)
    assert state._made and len(state.frames) == 6
