"""EF-06 (D-T1): a still photo held on screen — real encodes of tiny pictures written to
`tmp_path` (no network, no `ffmpeg` binary; skipped where PyAV is missing)."""

from __future__ import annotations

from pathlib import Path

import pytest

from qualify_creative.video.photo_hold import (
    HOLD_FPS,
    PhotoHoldError,
    hold_frames,
    render_photo_hold,
)

try:
    import av
    from PIL import Image
except ImportError:  # pragma: no cover — the pure tests still run
    av = None
    Image = None

requires_av = pytest.mark.skipif(av is None, reason="PyAV (qualify-creative[media]) missing")


def test_a_hold_lasts_its_seconds_in_whole_frames() -> None:
    assert hold_frames(1.0) == HOLD_FPS
    assert hold_frames(2.5) == 75
    assert hold_frames(0.01) == 1


def _photo(path: Path, size: tuple[int, int], colour: tuple[int, int, int]) -> Path:
    Image.new("RGB", size, colour).save(path, format="PNG")
    return path


def _frames(path: Path) -> list:
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        assert not container.streams.audio
        return [frame.to_ndarray(format="rgb24") for frame in container.decode(stream)]


@requires_av
def test_a_photo_is_held_still_for_its_seconds(tmp_path: Path) -> None:
    photo = _photo(tmp_path / "foto.png", (400, 300), (200, 30, 30))
    held = render_photo_hold(photo, tmp_path / "foto.mp4", seconds=1.5, size=(180, 320))
    assert (held.width, held.height, held.frames) == (180, 320, 45)
    assert held.duration_s == pytest.approx(1.5)
    frames = _frames(held.path)
    assert len(frames) == 45 and frames[0].shape == (320, 180, 3)
    red, green, _ = frames[-1][160, 90]
    assert red > 150 and green < 80  # the photo, cover-cropped, not stretched nor black


@requires_av
def test_a_turned_photo_is_turned_clockwise(tmp_path: Path) -> None:
    picture = Image.new("RGB", (200, 100), (0, 0, 0))
    picture.paste((255, 255, 255), (0, 0, 100, 100))  # the LEFT half is white
    path = tmp_path / "giro.png"
    picture.save(path, format="PNG")
    held = render_photo_hold(path, tmp_path / "giro.mp4", seconds=1.0, size=(100, 200), rotate=90)
    frame = _frames(held.path)[0]
    # turned 90° clockwise the left half becomes the TOP half
    assert frame[40, 50].mean() > 200 and frame[160, 50].mean() < 60


@requires_av
def test_a_file_that_is_no_photo_is_refused_and_leaves_nothing(tmp_path: Path) -> None:
    path = tmp_path / "nada.png"
    path.write_bytes(b"not a picture")
    with pytest.raises(PhotoHoldError) as refused:
        render_photo_hold(path, tmp_path / "nada.mp4", seconds=1.0, size=(180, 320))
    assert refused.value.reason == "unreadable"
    assert not (tmp_path / "nada.mp4").exists()


@requires_av
def test_a_photo_too_big_to_open_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review #6: Pillow's bomb guard (a photo of absurd size) is `unreadable`."""
    photo = _photo(tmp_path / "enorme.png", (400, 300), (10, 10, 10))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)  # 400×300 is now a «bomb»
    with pytest.raises(PhotoHoldError) as refused:
        render_photo_hold(photo, tmp_path / "enorme.mp4", seconds=1.0, size=(180, 320))
    assert refused.value.reason == "unreadable"


@pytest.mark.parametrize(
    ("size", "rotate", "seconds", "reason"),
    [
        ((181, 320), 0, 1.0, "bad_size"),
        ((180, 320), 45, 1.0, "rotation_unsupported"),
        ((180, 320), 0, 0.0, "bad_seconds"),
    ],
)
def test_impossible_holds_are_refused_before_any_read(
    tmp_path: Path, size: tuple[int, int], rotate: int, seconds: float, reason: str
) -> None:
    with pytest.raises(PhotoHoldError) as refused:
        render_photo_hold(
            tmp_path / "x.png", tmp_path / "x.mp4", seconds=seconds, size=size, rotate=rotate
        )
    assert refused.value.reason == reason
