"""m-25026384: «Subir foto o video» in «Nueva publicación», step 1.

- The «+» card is the grid's first card, with zero and with N ready publications.
- Picking a file stores it (a photo converted to a JPEG of at most 8 MB, a video
  streamed); a wrong type or size is refused BEFORE any storage call.
- «Guardar y continuar» creates the piece (idempotent on the file's id), reloads the
  candidates, selects it and goes to «Cuándo sale»; a refusal keeps the file, says why
  and selects nothing; a retry reuses the same id.

Storage, the normaliser and the backend are faked: nothing touches R2 or the database.
"""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from qualify_api.creative.own_upload import OwnUploadRefused, UploadRefusal
from qualify_creative.enums import ContentFormat, PostCategory
from qualify_creative.video import VideoFacts, VideoStill

from . import planner_drawer, planner_state, planner_upload_vm, upload_video_still
from .heavy_media import heavy_media_slot
from .planner_state import PlannerState
from .planner_upload_vm import (
    ADD_TILE_TITLE,
    NOT_LISTED_TEXT,
    PHOTO_TOO_HEAVY_TEXT,
    SAVE_FAILED_TEXT,
    TOO_MANY_TEXT,
    VIDEO_TOO_HEAVY_TEXT,
    WRONG_TYPE_TEXT,
)
from .planner_vm import STEP_POST, STEP_WHEN, PostOptionVM
from .upload_images import StoredPhoto
from .upload_store import UploadNotKept
from .upload_video_still import video_still_when_free

_TENANT = UUID("00000000-0000-0000-0000-0000000000aa")
_DRAFT = UUID("00000000-0000-0000-0000-0000000000d1")
_KEY = f"t/{_TENANT}/uploads/planner/abc_foto.jpg"


class _Upload:
    """What Reflex hands the handler: a name and a spooled file."""

    def __init__(self, name: str, size: int = 1024, head: bytes | None = None) -> None:
        self.name = name
        self.size = size
        self.file = io.BytesIO(head if head is not None else b"x" * min(size, 16))


#: The first bytes of a real MP4 (an ISO-BMFF `ftyp` box) and of a QuickTime MOV.
_MP4_HEAD = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00"
_MOV_HEAD = b"\x00\x00\x00\x14ftypqt  \x00\x00\x00\x00"


async def _save(state: PlannerState) -> list:
    """Run the background «Guardar y continuar» to the end; what it yields."""
    return [event async for event in PlannerState.save_own_upload.fn(state)]


def _post(post_id: str, *, schedulable: bool = True) -> PostOptionVM:
    return PostOptionVM(
        post_id=post_id,
        title="Mi foto",
        caption_excerpt="",
        thumbnail_url="",
        category_label="Publicación",
        approval_label="Aprobado",
        approval_tone="ok",
        detail_href="",
        kind="feed",
        schedulable=schedulable,
    )


@pytest.fixture
def storage(monkeypatch) -> dict[str, list]:
    calls: dict[str, list] = {"bytes": [], "stream": [], "normalize": []}

    async def fake_tenant(self):
        return _TENANT

    async def fake_normalize(fileobj, name, *, wait_seconds=None, jpeg_max_bytes=None):
        calls["normalize"].append((name, jpeg_max_bytes))
        return StoredPhoto(b"jpeg-bytes", "foto.jpg", "image/jpeg", 1080, 1350)

    async def fake_save_bytes(tenant_id, data, name, *, folder=""):
        calls["bytes"].append((tenant_id, data, name, folder))
        return f"t/{tenant_id}/uploads/{folder}/abc_{name}"

    async def fake_save(tenant_id, upload, name, *, folder=""):
        calls["stream"].append((tenant_id, upload, name, folder))
        return f"t/{tenant_id}/uploads/{folder}/abc_{name}"

    monkeypatch.setattr(PlannerState, "_tenant", fake_tenant)
    monkeypatch.setattr(planner_state, "normalize_photo_when_free", fake_normalize)
    monkeypatch.setattr(planner_state, "save_upload_bytes", fake_save_bytes)
    monkeypatch.setattr(planner_state, "save_upload", fake_save)

    async def no_still(fileobj, suffix, *, wait_seconds=None):
        calls.setdefault("still", []).append(suffix)
        return None

    # m-25026481: ffmpeg never runs here; the video tests below set their own still
    monkeypatch.setattr(planner_state, "video_still_when_free", no_still)
    return calls


# --- the «+» card ----------------------------------------------------------------------


def _tree(component) -> str:
    return str(component)


@pytest.mark.parametrize("count", [0, 3])
def test_the_add_card_is_the_first_card_with_zero_or_n_publications(count: int) -> None:
    state = PlannerState()
    state.schedulable = [_post(str(uuid4())) for _ in range(count)]
    assert len(state.form_tiles) == count

    grid = _tree(planner_drawer._step_grid())

    # the card sits outside every `schedulable` condition, before the foreach over the
    # tiles: it is drawn whatever the count
    assert ADD_TILE_TITLE in grid
    assert grid.index(ADD_TILE_TITLE) < grid.index("form_tiles")
    # the empty state still offers «Crear una publicación» (/create)
    assert "/create" in grid


def test_step_one_swaps_to_the_upload_view_in_the_same_panel() -> None:
    state = PlannerState()
    PlannerState.open_own_upload.fn(state)
    assert state.own_upload_view is True
    PlannerState.close_own_upload.fn(state)
    assert state.own_upload_view is False
    content = _tree(planner_drawer._step_content())
    assert planner_upload_vm.VIEW_TITLE in content
    assert planner_upload_vm.SAVE in content


# --- picking a file -------------------------------------------------------------------


async def test_a_photo_is_converted_to_a_jpeg_under_8_mb_and_stored(storage) -> None:
    state = PlannerState()
    await PlannerState.handle_own_upload.fn(state, [_Upload("IMG_0001.HEIC")])

    assert storage["normalize"] == [("IMG_0001.HEIC", 8 * 1024 * 1024)]
    assert storage["bytes"][0][1:] == (b"jpeg-bytes", "foto.jpg", "planner")
    assert storage["stream"] == []
    assert state.own_upload_key == f"t/{_TENANT}/uploads/planner/abc_foto.jpg"
    assert state.own_upload_media == "image"
    assert (state._own_upload_width, state._own_upload_height) == (1080, 1350)
    assert state._own_upload_content_type == "image/jpeg"
    assert state._own_upload_size == len(b"jpeg-bytes")
    assert UUID(state._own_upload_id)
    assert state.own_upload_busy is False
    assert state.own_upload_error == ""


async def test_a_video_is_streamed_from_its_spooled_file(storage) -> None:
    state = PlannerState()
    upload = _Upload("clip.MOV", size=120 * 1024 * 1024, head=_MOV_HEAD)
    await PlannerState.handle_own_upload.fn(state, [upload])

    assert storage["normalize"] == [] and storage["bytes"] == []
    # the upload object itself goes to `save_upload` (it streams `upload.file`), with its
    # position put back after the 12-byte check
    assert storage["stream"][0][1] is upload
    assert upload.file.tell() == 0
    assert state.own_upload_media == "video"
    assert state._own_upload_content_type == "video/quicktime"
    assert state._own_upload_size == 120 * 1024 * 1024


@pytest.mark.parametrize(
    ("files", "message"),
    [
        ([_Upload("menu.pdf")], WRONG_TYPE_TEXT),
        ([_Upload("animacion.gif")], WRONG_TYPE_TEXT),
        ([_Upload("foto.png", size=51 * 1024 * 1024)], PHOTO_TOO_HEAVY_TEXT),
        ([_Upload("video.mp4", size=301 * 1024 * 1024)], VIDEO_TOO_HEAVY_TEXT),
        # a text file renamed .mp4: its first bytes are not a video container
        ([_Upload("video.mp4", head=b"hola, esto es texto")], WRONG_TYPE_TEXT),
        ([_Upload("a.jpg"), _Upload("b.jpg")], TOO_MANY_TEXT),
    ],
)
async def test_unsupported_type_or_size_is_refused_before_any_storage_call(
    storage, files, message
) -> None:
    state = PlannerState()
    await PlannerState.handle_own_upload.fn(state, files)

    assert state.own_upload_error == message
    assert storage == {"bytes": [], "stream": [], "normalize": []}
    assert state.own_upload_key == "" and state._own_upload_id == ""
    assert state.own_upload_busy is False


def test_the_picker_refusals_are_plain_sentences() -> None:
    too_heavy = [{"file": {"path": "x.mp4"}, "errors": [{"code": "file-too-large"}]}]
    assert "300 MB" in planner_upload_vm.rejection_text(too_heavy)
    wrong = [{"file": {"path": "x.gif"}, "errors": [{"code": "file-invalid-type"}]}]
    assert planner_upload_vm.rejection_text(wrong) == WRONG_TYPE_TEXT
    many = [{"errors": [{"code": "too-many-files"}]}]
    assert planner_upload_vm.rejection_text(many) == TOO_MANY_TEXT


# --- «Guardar y continuar» --------------------------------------------------------------


def _stored_state() -> PlannerState:
    state = PlannerState()
    state.form_open = True
    state.form_step = STEP_POST
    state.own_upload_view = True
    state.own_upload_key = _KEY
    state.own_upload_media = "image"
    state.own_upload_name = "foto.jpg"
    state.own_upload_caption = "  Nuevo en el menú  "
    state._own_upload_id = "5b0f1d4e-1111-4222-8333-444455556666"
    state._own_upload_content_type = "image/jpeg"
    state._own_upload_width = 1080
    state._own_upload_height = 1350
    state._own_upload_size = 2048
    return state


@pytest.fixture
def backend(monkeypatch):
    seen: dict[str, list] = {"requests": [], "reloads": []}
    behaviour: dict[str, object] = {"refuse": None, "listed": True}

    async def fake_tenant(self):
        return _TENANT

    def fake_record(tenant_id, upload):
        seen["requests"].append(upload)
        refusal = behaviour["refuse"]
        if isinstance(refusal, BaseException):
            raise refusal
        return SimpleNamespace(
            draft_id=_DRAFT,
            created=True,
            category=PostCategory.GALERIA,
            format=ContentFormat.FEED_4_5,
        )

    def fake_load_week(tenant_id, *week):
        seen["reloads"].append(week)
        listed = [_post(str(_DRAFT))] if behaviour["listed"] else []
        return SimpleNamespace(schedulable=listed, unscheduled=listed)

    monkeypatch.setattr(PlannerState, "_tenant", fake_tenant)
    monkeypatch.setattr(planner_state, "record_upload_piece", fake_record)
    monkeypatch.setattr(planner_state, "load_week", fake_load_week)
    return seen, behaviour


async def test_save_creates_the_piece_selects_it_and_goes_to_when(backend) -> None:
    seen, _ = backend
    state = _stored_state()

    events = await _save(state)

    request = seen["requests"][0]
    assert str(request.upload_id) == "5b0f1d4e-1111-4222-8333-444455556666"
    assert (request.object_key, request.media_type, request.content_type) == (
        _KEY,
        "image",
        "image/jpeg",
    )
    assert (request.width, request.height, request.size_bytes) == (1080, 1350, 2048)
    assert request.caption == "Nuevo en el menú"
    assert len(seen["reloads"]) == 1  # the candidates are read again explicitly
    assert state.form_selected_ids == [str(_DRAFT)]
    assert state.form_step == STEP_WHEN
    assert state.own_upload_view is False
    assert state.own_upload_key == "" and state._own_upload_id == ""
    assert state.own_upload_saving is False
    # the focus goes to step 2's title in the drawer («Paso 2 de 3»)
    assert len(events) == 1 and ".q-drawer .q-step-title" in str(events[0])


async def test_a_refusal_says_why_keeps_the_file_and_selects_nothing(backend) -> None:
    seen, behaviour = backend
    behaviour["refuse"] = OwnUploadRefused(UploadRefusal.IMAGE_TOO_LARGE)
    state = _stored_state()

    await _save(state)

    assert state.own_upload_error == OwnUploadRefused(UploadRefusal.IMAGE_TOO_LARGE).text
    assert state.form_selected_ids == []
    assert state.form_step == STEP_POST
    assert state.own_upload_key == _KEY  # «Cambiar archivo» or a retry, never re-pick
    assert seen["reloads"] == []
    assert state.own_upload_saving is False


async def test_a_retry_after_a_failure_reuses_the_same_upload_id(backend) -> None:
    seen, behaviour = backend
    behaviour["refuse"] = RuntimeError("db down")
    state = _stored_state()

    await _save(state)
    assert state.own_upload_error == SAVE_FAILED_TEXT

    behaviour["refuse"] = None
    await _save(state)

    first, second = seen["requests"]
    assert first.upload_id == second.upload_id
    assert state.form_step == STEP_WHEN


async def test_a_double_tap_while_saving_does_nothing(backend) -> None:
    seen, _ = backend
    state = _stored_state()
    state.own_upload_saving = True

    await _save(state)

    assert seen["requests"] == []


async def test_save_without_a_stored_file_asks_for_one(backend) -> None:
    seen, _ = backend
    state = PlannerState()

    await _save(state)

    assert seen["requests"] == []
    assert state.own_upload_error == planner_upload_vm.NO_FILE_TEXT


async def test_a_piece_that_does_not_list_offers_show_again_on_the_same_piece(backend) -> None:
    seen, behaviour = backend
    behaviour["listed"] = False
    state = _stored_state()

    await _save(state)

    assert state.own_upload_not_listed is True
    assert state.form_step == STEP_POST
    assert state.own_upload_key == _KEY

    # «Mostrarla otra vez»: the same file id (the backend answers with the same piece),
    # the candidates read again, and this time it is there
    behaviour["listed"] = True
    await _save(state)

    first, second = seen["requests"]
    assert first.upload_id == second.upload_id
    assert len(seen["reloads"]) == 2
    assert state.form_selected_ids == [str(_DRAFT)]
    assert state.form_step == STEP_WHEN
    assert state.own_upload_not_listed is False


def test_show_again_is_a_button_on_the_upload_view() -> None:
    view = str(planner_drawer._own_upload_view())
    assert planner_upload_vm.SHOW_AGAIN in view
    assert json.dumps(NOT_LISTED_TEXT)[1:-1] in view  # JSX escapes the accents


# --- C1: no file swap while saving ---------------------------------------------------


async def test_a_file_picked_while_saving_is_refused_before_storage(storage) -> None:
    state = _stored_state()
    state.own_upload_saving = True

    PlannerState.begin_own_upload.fn(state)
    await PlannerState.handle_own_upload.fn(state, [_Upload("otra.jpg")])

    assert state.own_upload_error == planner_upload_vm.SAVING_WAIT_TEXT
    assert storage == {"bytes": [], "stream": [], "normalize": []}
    assert state.own_upload_key == _KEY  # the file being saved is still the one shown
    assert state.own_upload_busy is False


async def test_file_b_arriving_during_a_save_is_kept_and_a_is_not_selected(
    backend, monkeypatch
) -> None:
    seen, _ = backend
    state = _stored_state()
    key_b = f"t/{_TENANT}/uploads/planner/b_video.mp4"
    record = planner_state.record_upload_piece

    def record_then_swap(tenant_id, upload):
        # while A's piece is being written, file B replaces A in the view
        state.own_upload_key = key_b
        state.own_upload_media = "video"
        state._own_upload_id = "0e4c33a1-2222-4333-8444-555566667777"
        return record(tenant_id, upload)

    monkeypatch.setattr(planner_state, "record_upload_piece", record_then_swap)

    events = await _save(state)

    assert str(seen["requests"][0].upload_id) == "5b0f1d4e-1111-4222-8333-444455556666"
    assert events == []
    assert state.own_upload_view is True
    assert state.own_upload_key == key_b
    assert state._own_upload_id == "0e4c33a1-2222-4333-8444-555566667777"
    assert state.form_selected_ids == []  # A is listed in the grid, not selected
    assert state.form_step == STEP_POST
    assert state.own_upload_saving is False


def test_caption_edits_are_ignored_while_saving() -> None:
    state = _stored_state()
    state.own_upload_saving = True
    PlannerState.set_own_upload_caption.fn(state, "otro texto")
    assert state.own_upload_caption == "  Nuevo en el menú  "


def test_zone_text_back_and_save_are_disabled_while_saving() -> None:
    view = str(planner_drawer._own_upload_view())
    # every control of the view is tied to `own_upload_saving`: the two zones (pick and
    # «Cambiar archivo»), the text field, «Volver a elegir» and «Guardar y continuar»
    assert view.count("own_upload_saving") >= 5
    assert "disabled" in view


# --- U1: focus ---------------------------------------------------------------------------


def test_opening_and_closing_the_view_moves_the_focus() -> None:
    state = PlannerState()
    opened = PlannerState.open_own_upload.fn(state)
    assert planner_upload_vm.VIEW_TITLE_ID in str(opened)
    closed = PlannerState.close_own_upload.fn(state)
    assert planner_upload_vm.ADD_TILE_ID in str(closed)
    assert planner_upload_vm.VIEW_TITLE_ID in str(planner_drawer._own_upload_view())
    assert planner_upload_vm.ADD_TILE_ID in str(planner_drawer._add_tile())


def test_reopening_the_panel_shows_the_grid_but_keeps_the_stored_file() -> None:
    state = _stored_state()
    state._reset_form()
    assert state.own_upload_view is False
    assert state.own_upload_key == _KEY


# --- the photo's conversion (real Pillow, no storage) ----------------------------------


def _png(size: tuple[int, int], mode: str = "RGBA", noise: bool = False) -> io.BytesIO:
    from PIL import Image

    if noise:
        image = Image.frombytes("RGB", size, __import__("os").urandom(size[0] * size[1] * 3))
    else:
        image = Image.new(mode, size, (200, 30, 30, 0) if mode == "RGBA" else (200, 30, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def test_a_transparent_png_becomes_a_jpeg_laid_on_white() -> None:
    from PIL import Image

    from .upload_images import normalize_photo

    stored = normalize_photo(_png((300, 200)), "logo.png", jpeg_max_bytes=8 * 1024 * 1024)

    assert (stored.content_type, stored.name) == ("image/jpeg", "logo.jpg")
    assert (stored.width, stored.height) == (300, 200)
    with Image.open(io.BytesIO(stored.data)) as image:
        assert image.format == "JPEG"
        assert image.getpixel((10, 10))[0] > 240  # white, not black, under the alpha


def test_a_jpeg_over_the_byte_cap_is_reencoded_until_it_fits() -> None:
    from .upload_images import normalize_photo

    cap = 300_000
    stored = normalize_photo(_png((900, 900), noise=True), "ruido.png", jpeg_max_bytes=cap)

    assert stored.content_type == "image/jpeg"
    assert len(stored.data) <= cap


def test_without_the_cap_a_png_still_stays_a_png() -> None:
    from .upload_images import normalize_photo

    stored = normalize_photo(_png((40, 40)), "logo.png")
    assert stored.content_type == "image/png"


# --- the saving flag never stays stuck (re-review) --------------------------------------


async def test_an_unexpected_error_in_the_save_clears_the_flag_and_keeps_the_file(
    backend, monkeypatch
) -> None:
    state = _stored_state()

    async def broken_tenant(self):
        raise RuntimeError("session store down")

    monkeypatch.setattr(PlannerState, "_tenant", broken_tenant)

    events = await _save(state)

    assert events == []
    assert state.own_upload_saving is False
    assert state.own_upload_error == SAVE_FAILED_TEXT
    assert state.own_upload_key == _KEY
    assert state._own_upload_id == "5b0f1d4e-1111-4222-8333-444455556666"


def test_a_stale_saving_flag_is_cleared_when_the_owner_comes_back() -> None:
    state = _stored_state()
    state.own_upload_saving = True  # left by a save killed with the process
    PlannerState.open_own_upload.fn(state)
    assert state.own_upload_saving is False

    state.own_upload_saving = True
    state._reset_form()  # the assign panel opening again
    assert state.own_upload_saving is False
    assert state.own_upload_key == _KEY


# --- m-25026481: a video's size, length and poster --------------------------------------

_FIXTURES = Path(__file__).resolve().parents[1] / "packages/creative/tests/fixtures"


def _still(width=1080, height=1920, seconds=65.0, poster=b"\xff\xd8poster") -> VideoStill:
    return VideoStill(VideoFacts(width, height, seconds), poster)


def _video_upload(name: str = "mi clip.mp4") -> _Upload:
    return _Upload(name, size=40 * 1024 * 1024, head=_MP4_HEAD)


def _with_still(monkeypatch, result) -> list:
    """`video_still_when_free` answers `result` (or raises it when it is an exception)."""
    seen: list = []

    async def fake(fileobj, suffix, *, wait_seconds=None):
        seen.append((fileobj, suffix))
        if isinstance(result, BaseException):
            raise result
        return result

    monkeypatch.setattr(planner_state, "video_still_when_free", fake)
    return seen


async def test_a_video_still_fills_the_request_with_size_length_and_poster(
    storage, monkeypatch
) -> None:
    seen = _with_still(monkeypatch, _still())
    state = PlannerState()
    upload = _video_upload("mi_clip.mp4")
    await PlannerState.handle_own_upload.fn(state, [upload])

    assert seen == [(upload.file, ".mp4")]
    # the video streamed, then the poster saved next to it, named after it
    assert storage["stream"][0][1] is upload
    assert storage["bytes"] == [(_TENANT, b"\xff\xd8poster", "mi_clip.jpg", "planner")]
    poster_key = f"t/{_TENANT}/uploads/planner/abc_mi_clip.jpg"
    assert state.own_upload_poster_key == poster_key
    state.own_upload_caption = ""
    request = state._own_upload_request()
    assert (request.width, request.height, request.duration_seconds) == (1080, 1920, 65.0)
    assert request.poster_object_key == poster_key
    assert request.size_bytes == 40 * 1024 * 1024
    assert state.own_upload_error == ""


def _assert_unknown(state: PlannerState) -> None:
    request = state._own_upload_request()
    assert state.own_upload_key and state.own_upload_media == "video"
    assert state.own_upload_error == ""
    assert (request.width, request.height, request.duration_seconds) == (None, None, None)
    assert request.poster_object_key is None
    assert request.size_bytes == 40 * 1024 * 1024  # what the upload measured stays


async def test_a_still_with_nothing_known_keeps_the_video_without_facts(
    storage, monkeypatch
) -> None:
    _with_still(monkeypatch, _still(None, None, None, None))
    state = PlannerState()
    await PlannerState.handle_own_upload.fn(state, [_video_upload()])
    _assert_unknown(state)
    assert storage["bytes"] == []  # no poster to save


@pytest.mark.parametrize("error", [RuntimeError("boom"), OSError("disk"), ValueError("x")])
async def test_an_unexpected_error_in_the_still_never_blocks_the_upload(
    storage, monkeypatch, error
) -> None:
    _with_still(monkeypatch, error)
    state = PlannerState()
    await PlannerState.handle_own_upload.fn(state, [_video_upload()])
    _assert_unknown(state)


async def test_a_busy_heavy_media_slot_skips_the_still(storage, monkeypatch) -> None:
    """The real gate, held by another job: the still is skipped, the video kept."""
    monkeypatch.setattr(planner_state, "video_still_when_free", video_still_when_free)
    monkeypatch.setattr(upload_video_still, "VIDEO_STILL_WAIT_SECONDS", 0.05)

    def never(*_args):  # the copy and ffmpeg must not even start
        raise AssertionError("ran while the slot was busy")

    monkeypatch.setattr(upload_video_still, "still_from_spooled", never)
    holding, release = asyncio.Event(), asyncio.Event()

    async def other_job() -> None:
        async with heavy_media_slot():
            holding.set()
            await release.wait()

    task = asyncio.create_task(other_job())
    await holding.wait()
    try:
        state = PlannerState()
        await PlannerState.handle_own_upload.fn(state, [_video_upload()])
    finally:
        release.set()
        await task
    _assert_unknown(state)


async def test_a_poster_that_cannot_be_kept_keeps_size_and_length(storage, monkeypatch) -> None:
    _with_still(monkeypatch, _still(720, 1280, 12.5))

    async def failing_bytes(tenant_id, data, name, *, folder=""):
        raise UploadNotKept("r2 down")

    monkeypatch.setattr(planner_state, "save_upload_bytes", failing_bytes)
    state = PlannerState()
    await PlannerState.handle_own_upload.fn(state, [_video_upload()])

    request = state._own_upload_request()
    assert state.own_upload_error == "" and state.own_upload_key
    assert (request.width, request.height, request.duration_seconds) == (720, 1280, 12.5)
    assert request.poster_object_key is None


async def test_a_second_file_resets_the_first_files_length_and_poster(storage, monkeypatch) -> None:
    _with_still(monkeypatch, _still())
    state = PlannerState()
    await PlannerState.handle_own_upload.fn(state, [_video_upload()])
    assert state.own_upload_poster_key and state._own_upload_duration == 65.0

    _with_still(monkeypatch, _still(None, None, None, None))
    await PlannerState.handle_own_upload.fn(state, [_video_upload("otro.mov")])
    assert state.own_upload_poster_key == "" and state._own_upload_duration == 0.0

    _with_still(monkeypatch, _still())
    await PlannerState.handle_own_upload.fn(state, [_video_upload()])
    state._clear_own_upload()
    assert state.own_upload_poster_key == "" and state._own_upload_duration == 0.0


async def test_a_photo_request_is_unchanged_and_runs_no_still(storage) -> None:
    state = PlannerState()
    await PlannerState.handle_own_upload.fn(state, [_Upload("foto.jpg")])
    request = state._own_upload_request()
    assert "still" not in storage
    assert (request.width, request.height) == (1080, 1350)
    assert request.duration_seconds is None and request.poster_object_key is None


class _BoundedOnly(io.BytesIO):
    """A spooled file that fails on any read without a bounded size."""

    def read(self, size: int | None = -1) -> bytes:
        if size is None or size < 0 or size > upload_video_still.COPY_CHUNK_BYTES:
            raise AssertionError(f"unbounded read({size})")
        return super().read(size)


async def test_the_video_is_copied_in_bounded_chunks_and_the_copy_is_deleted(
    storage, monkeypatch
) -> None:
    monkeypatch.setattr(planner_state, "video_still_when_free", video_still_when_free)
    body = _MP4_HEAD + bytes(range(256)) * 9000  # ~2.3 MB: three chunks
    seen: dict[str, object] = {}

    def fake_still(path: Path) -> VideoStill:
        seen["path"], seen["bytes"] = path, path.read_bytes()
        return _still(180, 320, 2.0)

    monkeypatch.setattr(upload_video_still, "video_still", fake_still)
    upload = _video_upload()
    upload.file = _BoundedOnly(body)
    upload.file.seek(5)
    state = PlannerState()
    await PlannerState.handle_own_upload.fn(state, [upload])

    assert seen["bytes"] == body  # the whole file reached ffmpeg's path
    assert not Path(str(seen["path"])).exists()  # and the copy is gone
    assert state._own_upload_duration == 2.0 and state.own_upload_error == ""


def test_the_copy_puts_the_position_back() -> None:
    src, out = io.BytesIO(b"abcdef"), io.BytesIO()
    src.seek(3)
    assert upload_video_still.copy_spooled(src, out) == 6
    assert out.getvalue() == b"abcdef" and src.tell() == 3


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg/ffprobe on PATH",
)
@pytest.mark.parametrize(("clip", "seconds"), [("video-portrait-65s.mp4", 65.0)])
def test_the_real_still_of_a_spooled_fixture_clip(clip: str, seconds: float) -> None:
    """End to end with the real ffmpeg, from a Starlette-like spooled file in memory."""
    spooled = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
    spooled.write((_FIXTURES / clip).read_bytes())
    still = upload_video_still.still_from_spooled(spooled, ".mp4")
    assert still.facts.duration_seconds == pytest.approx(seconds, abs=0.2)
    assert (still.facts.width, still.facts.height) == (90, 160)
    assert still.poster_jpeg is not None and still.poster_jpeg[:2] == b"\xff\xd8"


async def test_cancelling_during_the_still_deletes_the_copy_and_frees_the_slot(
    storage, monkeypatch
) -> None:
    """The client leaves (Reflex cancels the handler) while ffmpeg runs: the handler
    waits for the thread, the temp copy is deleted, the slot is released, nothing is
    stored and nothing recorded."""
    import threading

    monkeypatch.setattr(planner_state, "video_still_when_free", video_still_when_free)
    started, release = threading.Event(), threading.Event()
    seen: dict[str, Path] = {}

    def slow_still(path: Path) -> VideoStill:
        seen["path"] = path
        started.set()
        release.wait(5)
        return _still()

    monkeypatch.setattr(upload_video_still, "video_still", slow_still)
    state = PlannerState()
    task = asyncio.create_task(PlannerState.handle_own_upload.fn(state, [_video_upload()]))
    while not started.is_set():
        await asyncio.sleep(0.01)
    assert seen["path"].exists()  # the copy is there while ffmpeg reads it
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()  # the cancelled handler still waits for its thread
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not seen["path"].exists()
    async with heavy_media_slot(timeout=0.5):  # free again
        pass
    assert storage["stream"] == [] and storage["bytes"] == []
    assert state.own_upload_key == "" and state.own_upload_poster_key == ""
    assert state.own_upload_busy is False


async def test_an_empty_upload_after_a_refusal_keeps_the_refusal(storage) -> None:
    """react-dropzone: `on_drop([])` then `on_drop_rejected([pdf])`; the upload of the
    empty list can reach the server after the refusal — the refusal must stay."""
    state = PlannerState()
    PlannerState.begin_own_upload.fn(state)
    rejected = [{"file": {"path": "menu.pdf"}, "errors": [{"code": "file-invalid-type"}]}]
    PlannerState.own_upload_rejected.fn(state, rejected)
    await PlannerState.handle_own_upload.fn(state, [])
    assert state.own_upload_error == WRONG_TYPE_TEXT
    alone = PlannerState()
    await PlannerState.handle_own_upload.fn(alone, [])  # nothing refused: ask for a file
    assert alone.own_upload_error == planner_upload_vm.NO_FILE_TEXT
