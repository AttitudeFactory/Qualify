"""EF-18 (m-25026598): the contact sheet block kept with a piece, and how the screen reads
it back — offline (a synthetic MP4, a dict for R2). The wiring into the local Clip, the
Seedance preview and the joined preview is tested next to each of them
(`test_video_pipeline_local.py`, `test_video_pipeline_recompose.py`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from qualify_api.creative.contact_sheet import (
    CONTACT_SHEET_HELP,
    CONTACT_SHEET_TITLE,
    contact_sheet_of,
    keep_contact_sheet,
    with_source_key,
)

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

KEY = "t/tenant/generated/draft/r1/clip.mp4"


@pytest.fixture(scope="module")
def video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("sheet") / "clip.mp4"
    with av.open(str(path), "w") as sink:
        stream = sink.add_stream("libx264", rate=30)
        stream.width, stream.height, stream.pix_fmt = 180, 320, "yuv420p"
        for index in range(90):
            shade = 40 if index < 45 else 200  # one cut at 1.5 s
            picture = np.full((320, 180, 3), shade, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(picture, format="rgb24")):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return path


class Bucket:
    """R2's double: a key keeps its first bytes (the same bytes again are a success)."""

    def __init__(self, refuse: str | None = None) -> None:
        self.files: dict[str, bytes] = {}
        self.refuse = refuse

    def keep(self, name: str, data: bytes) -> str | None:
        if self.refuse and self.refuse in name:
            return None
        key = f"t/tenant/generated/draft/r1/{name}"
        if self.files.setdefault(key, data) != data:
            return None
        return key


def test_the_block_records_where_the_frames_come_from(video: Path) -> None:
    bucket = Bucket()
    block = keep_contact_sheet(video, bucket.keep, source={"stage": "local", "object_key": KEY})
    assert block is not None
    assert block["version"] == "contact-sheet-4" and block["cost_usd"] == "0"
    assert block["review"] == "owner_only"  # D8: no AI looks at it
    assert block["source"]["stage"] == "local" and block["source"]["object_key"] == KEY
    assert len(block["source"]["sha256"]) == 64
    assert len(block["frames"]) == 6
    assert [f["key"].rsplit("/", 1)[1] for f in block["frames"]] == [
        f"contact-{n}.jpg" for n in range(1, 7)
    ]
    assert all(set(f) >= {"time_s", "target_s", "role", "sha256"} for f in block["frames"])
    assert any(f["role"] == "cut" and 1.5 <= f["time_s"] <= 2.1 for f in block["frames"])
    assert block["sheet"]["key"].endswith("/contact-sheet.jpg")
    assert len(bucket.files) == 7


def test_a_second_run_keeps_the_same_files_and_block(video: Path) -> None:
    bucket = Bucket()
    first = keep_contact_sheet(video, bucket.keep, source={"stage": "local", "object_key": KEY})
    second = keep_contact_sheet(video, bucket.keep, source={"stage": "local", "object_key": KEY})
    assert first == second and len(bucket.files) == 7


@pytest.mark.parametrize("refused", ["contact-3.jpg", "contact-sheet.jpg"])
def test_a_file_not_kept_leaves_the_sheet_out(video: Path, refused: str) -> None:
    bucket = Bucket(refuse=refused)
    assert keep_contact_sheet(video, bucket.keep, source={"stage": "local"}) is None


def test_a_file_that_is_no_video_leaves_the_sheet_out(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"nope")
    assert keep_contact_sheet(bad, Bucket().keep, source={"stage": "local"}) is None


def _block(video: Path, key: str | None = KEY) -> dict[str, Any]:
    block = keep_contact_sheet(video, Bucket().keep, source={"stage": "preview"})
    assert block is not None
    return with_source_key(block, key) if key else block  # type: ignore[return-value]


def test_the_screen_reads_the_sheet_of_the_video_it_shows(video: Path) -> None:
    view = contact_sheet_of(KEY, {"contact_sheet": _block(video)})
    assert view is not None and view.video_key == KEY
    assert len(view.frames) == 6 and view.sheet_key.endswith("contact-sheet.jpg")
    assert view.version == "contact-sheet-4"
    assert view.title == CONTACT_SHEET_TITLE and view.help == CONTACT_SHEET_HELP
    assert [f.time_s for f in view.frames] == sorted(f.time_s for f in view.frames)


def test_a_sheet_of_another_file_is_not_offered(video: Path) -> None:
    params = {"contact_sheet": _block(video)}
    assert contact_sheet_of("t/tenant/generated/draft/r1/clip-final-a1.mp4", params) is None
    assert contact_sheet_of(KEY, {"contact_sheet": _block(video, key=None)}) is None
    assert contact_sheet_of(None, params) is None
    assert contact_sheet_of(KEY, None) is None
    assert contact_sheet_of(KEY, {"contact_sheet": {"source": {"object_key": KEY}}}) is None
    broken = _block(video)
    broken["frames"][2] = {"time_s": 1.0}
    assert contact_sheet_of(KEY, {"contact_sheet": broken}) is None


def test_a_module_that_does_not_import_leaves_the_sheet_out(
    video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "qualify_creative.video.contact_sheet", None)
    assert keep_contact_sheet(video, Bucket().keep, source={"stage": "local"}) is None


def test_a_path_that_is_no_path_leaves_the_sheet_out() -> None:
    assert keep_contact_sheet(object(), Bucket().keep, source={}) is None  # type: ignore[arg-type]


def test_the_sheet_is_not_offered_when_the_clean_file_is_shown(video: Path) -> None:
    """A part whose logo could not be laid shows its clean file (no texts): the sheet,
    made from the composed file, is not offered; otherwise it is tied to the file shown."""
    from qualify_api.creative.contact_sheet import shown_contact_sheet

    block = _block(video, key=None)
    clean = "t/tenant/generated/draft/r1/clip.mp4"
    assert shown_contact_sheet(block, clean, clean_key=clean, logo_laid=False) is None
    shown = "t/tenant/generated/draft/r1/clip-logo.mp4"
    laid = shown_contact_sheet(block, shown, clean_key=clean, logo_laid=True)
    assert laid is not None and laid["source"]["object_key"] == shown
    plain = shown_contact_sheet(block, KEY, clean_key=None, logo_laid=False)
    assert plain is not None and contact_sheet_of(KEY, {"contact_sheet": plain}) is not None
    assert shown_contact_sheet(None, KEY, clean_key=None, logo_laid=True) is None


def test_the_texts_the_owner_reads_are_spanish_without_english_words() -> None:
    for text in (CONTACT_SHEET_TITLE, CONTACT_SHEET_HELP):
        lowered = text.lower()
        assert not any(word in lowered for word in ("preview", "frame", "sheet", "clip"))
