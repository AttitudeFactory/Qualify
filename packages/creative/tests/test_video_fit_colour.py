"""The fitter keeps a clip's colour (m-25029127): `fit`, `fit_reference`, `subtitle` and
`animate_still` write BT.709 limited-range YUV and tag it so. Before, the graph's
`format=yuv420p` let swscale write BT.601 YUV into an untagged file — a player reads that
as BT.709, so a phone's green [39,168,89] came out [25,149,85].

The clips are synthetic, flat colours encoded with PyAV, tagged BT.709 (every phone),
BT.601 (`bt470bg`, an older camera) or not at all; an untagged one is read as BT.709 when
HD and BT.601 below (`_source.source_colour`, the policy `prepare` follows). Skipped where
PyAV is not installed."""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from PIL import Image  # noqa: E402

from qualify_creative.video import FittedVideo, PyAvVideoFitter  # noqa: E402
from qualify_creative.video._source import source_colour  # noqa: E402
from qualify_creative.video.fit import SubtitleLayer  # noqa: E402

#: A phone's green (the colour the ticket measured), a brand red and a skin tone.
COLOURS = [(39, 168, 89), (200, 40, 50), (224, 172, 140)]
#: AVCOL codes per tag: (matrix, primaries, transfer); None writes no tag at all.
TAGS: dict[str | None, tuple[int, int, int] | None] = {
    "bt709": (1, 1, 1),
    "bt470bg": (5, 5, 6),
    None: None,
}
#: The largest per-channel difference allowed: x264's and swscale's rounding.
TOLERANCE = 3


def _clip(
    rgb: tuple[int, int, int],
    *,
    tag: str | None,
    size: tuple[int, int] = (160, 284),
    rotation: int = 0,
    full_range: bool = False,
    frames: int = 4,
) -> bytes:
    """A flat-colour H.264 clip whose YUV is written with the matrix its tag names (an
    untagged one with the matrix the policy reads it with) and tagged accordingly."""
    width, height = size
    matrix = (
        "ITU709"
        if tag == "bt709"
        else "ITU601"
        if tag == "bt470bg"
        else source_colour(None, None, "yuv420p", width, height)[0]
    )
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=12)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        stream.options = {"crf": "10", "preset": "ultrafast"}
        context = stream.codec_context
        codes = TAGS[tag]
        if codes is not None:
            context.colorspace, context.color_primaries, context.color_trc = codes
            context.color_range = 2 if full_range else 1
        if rotation:
            stream.set_display_rotation(rotation)
        picture = np.full((height, width, 3), rgb, dtype=np.uint8)
        for _ in range(frames):
            frame = av.VideoFrame.from_ndarray(picture, format="rgb24").reformat(
                format="yuv420p",
                dst_colorspace=matrix,
                dst_color_range="JPEG" if full_range else "MPEG",
            )
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return out.getvalue()


def _shown_rgb(data: bytes) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """The first frame's mean RGB in its middle half, read with the matrix and range the
    file is tagged with (as a player does), and the stream's (colorspace, range,
    primaries, transfer) tags."""
    with av.open(io.BytesIO(data)) as source:
        stream = source.streams.video[0]
        context = stream.codec_context
        tags = (
            int(context.colorspace),
            int(context.color_range),
            int(context.color_primaries),
            int(context.color_trc),
        )
        frame = next(source.decode(stream))
        matrix, colour_range = source_colour(
            frame.colorspace, frame.color_range, frame.format.name, frame.width, frame.height
        )
        pixels = frame.to_ndarray(
            format="rgb24", src_colorspace=matrix, src_color_range=colour_range
        )
    height, width = pixels.shape[:2]
    middle = pixels[height // 4 : 3 * height // 4, width // 4 : 3 * width // 4]
    return middle.reshape(-1, 3).mean(axis=0), tags


ENCODES: dict[str, Callable[[bytes], FittedVideo]] = {
    "fit": lambda data: PyAvVideoFitter().fit(data, size=(144, 180)),
    "fit_reference": lambda data: PyAvVideoFitter().fit_reference(data),
    "subtitle": lambda data: PyAvVideoFitter().subtitle(data, layers=lambda size: ()),
}
BT709_LIMITED = (1, 1, 1, 1)


def _assert_kept(got: np.ndarray, want: np.ndarray) -> None:
    difference = np.abs(got - want)
    assert difference.max() <= TOLERANCE, (got.round(1).tolist(), want.round(1).tolist())


@pytest.mark.parametrize("rotation", [0, 90])
@pytest.mark.parametrize("encode", sorted(ENCODES))
@pytest.mark.parametrize("rgb", COLOURS)
def test_a_bt709_clip_keeps_its_colour_and_is_tagged_bt709(
    rgb: tuple[int, int, int], encode: str, rotation: int
) -> None:
    source = _clip(rgb, tag="bt709", rotation=rotation)
    want, _ = _shown_rgb(source)
    got, tags = _shown_rgb(ENCODES[encode](source).data)
    assert tags == BT709_LIMITED
    _assert_kept(got, want)


@pytest.mark.parametrize("encode", sorted(ENCODES))
@pytest.mark.parametrize(
    ("tag", "size"),
    [
        ("bt470bg", (160, 284)),  # tagged BT.601
        (None, (160, 284)),  # untagged SD: read as BT.601
        (None, (720, 1280)),  # untagged HD: read as BT.709
    ],
)
def test_a_bt601_or_untagged_clip_is_converted_to_bt709_without_a_shift(
    tag: str | None, size: tuple[int, int], encode: str
) -> None:
    rgb = COLOURS[0]
    source = _clip(rgb, tag=tag, size=size, frames=2)
    want, _ = _shown_rgb(source)
    got, tags = _shown_rgb(ENCODES[encode](source).data)
    assert tags == BT709_LIMITED
    _assert_kept(got, want)
    _assert_kept(got, np.array(rgb, dtype=float))


def test_a_full_range_clip_comes_out_limited_range_with_its_colour() -> None:
    source = _clip(COLOURS[1], tag="bt709", full_range=True)
    want, source_tags = _shown_rgb(source)
    assert source_tags[1] == 2  # really written full range
    got, tags = _shown_rgb(ENCODES["fit"](source).data)
    assert tags == BT709_LIMITED
    _assert_kept(got, want)


def test_the_poster_shows_the_same_colour() -> None:
    source = _clip(COLOURS[0], tag="bt709")
    want, _ = _shown_rgb(source)
    for name, encode in ENCODES.items():
        poster = encode(source).poster
        assert poster is not None, name
        image = Image.open(io.BytesIO(poster)).convert("RGB")
        _assert_kept(np.array(image.getpixel((image.width // 2, image.height // 2)), float), want)


def test_a_layer_and_a_subtitle_keep_their_colours() -> None:
    """The RGBA layers laid over the video are converted with the video's BT.709 too: a
    subtitle's red [230,40,40] came out [244,56,36] before."""
    source = _clip(COLOURS[0], tag="bt709", size=(144, 180))
    teal, red = (14, 165, 164), (230, 40, 40)
    layer = Image.new("RGBA", (144, 180), (0, 0, 0, 0))
    layer.paste((*teal, 255), (0, 0, 144, 60))
    layer_png = io.BytesIO()
    layer.save(layer_png, format="PNG")
    subtitle_png = io.BytesIO()
    Image.new("RGBA", (60, 30), (*red, 255)).save(subtitle_png, format="PNG")

    def first_frame(data: bytes) -> np.ndarray:
        with av.open(io.BytesIO(data)) as out:
            frame = next(out.decode(video=0))
            return frame.to_ndarray(
                format="rgb24", src_colorspace="ITU709", src_color_range="MPEG"
            ).astype(float)

    fitter = PyAvVideoFitter()
    worded = first_frame(fitter.fit(source, size=(144, 180), overlay=layer_png.getvalue()).data)
    _assert_kept(worded[20:40, 50:90].reshape(-1, 3).mean(axis=0), np.array(teal, float))
    subtitled = first_frame(
        fitter.subtitle(
            source,
            layers=lambda size: [
                SubtitleLayer(png=subtitle_png.getvalue(), position=(10, 10), start=0, end=5)
            ],
        ).data
    )
    _assert_kept(subtitled[18:32, 20:60].reshape(-1, 3).mean(axis=0), np.array(red, float))


def test_an_animated_still_keeps_its_colour_and_is_tagged_bt709() -> None:
    rgb = COLOURS[0]
    still = io.BytesIO()
    Image.new("RGB", (200, 250), rgb).save(still, format="PNG")
    reel = PyAvVideoFitter().animate_still(still.getvalue(), size=(144, 180), seconds=0.2)
    got, tags = _shown_rgb(reel.data)
    assert tags == BT709_LIMITED
    _assert_kept(got, np.array(rgb, dtype=float))
