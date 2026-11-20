"""A phone video shown upright (EF-01): its display matrix is applied to the pixels by
`upright_image` / `upright_frame`, and the fitter's encodes (`fit`, `fit_reference`,
`subtitle`) come out with the size and the orientation a player shows.

The rotated fixtures (`fixtures/make_rotated_fixtures.py`) store a 64×36 landscape picture
with a red band on its stored top edge and a blue one on its stored left edge: turned 90°
counter-clockwise the red band ends on the left; turned 270° on the right. Skipped where
PyAV is not installed."""

from __future__ import annotations

import hashlib
import io
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.video import (  # noqa: E402
    FittedVideo,
    PyAvVideoFitter,
    VideoSourceError,
    turn_pixels,
    upright_filters,
    upright_frame,
    upright_image,
    upright_size,
)

FIXTURES = Path(__file__).parent / "fixtures"
PORTRAIT = FIXTURES / "video-portrait-2s.mp4"


def _fixture(rotation: int) -> bytes:
    return (FIXTURES / f"video-rotated-{rotation}.mp4").read_bytes()


def _first_decoded(data: bytes) -> av.VideoFrame:
    with av.open(io.BytesIO(data)) as source:
        return next(source.decode(video=0))


def _is_red(pixel: tuple[int, ...]) -> bool:
    return pixel[0] > 180 and pixel[1] < 80 and pixel[2] < 80


def _is_blue(pixel: tuple[int, ...]) -> bool:
    return pixel[2] > 180 and pixel[0] < 80 and pixel[1] < 80


def _bands(pixels: np.ndarray) -> dict[str, tuple[int, ...]]:
    """The colour at the middle of each edge of an RGB picture (rows × columns × 3)."""
    height, width = pixels.shape[:2]
    return {
        "left": tuple(pixels[height // 2, 2]),
        "right": tuple(pixels[height // 2, width - 3]),
        "top": tuple(pixels[2, width // 2]),
        "bottom": tuple(pixels[height - 3, width // 2]),
    }


#: rotation → (edge the stored top's red band ends on, edge the stored left's blue one ends on)
TURNED_EDGES = {90: ("left", "bottom"), 270: ("right", "top")}


def _assert_turned(pixels: np.ndarray, rotation: int) -> None:
    height, width = pixels.shape[:2]
    assert height > width, f"{width}×{height} is not upright"
    red_edge, blue_edge = TURNED_EDGES[rotation]
    bands = _bands(pixels)
    assert _is_red(bands[red_edge]), bands
    assert _is_blue(bands[blue_edge]), bands


# --- the public functions ----------------------------------------------------------


@pytest.mark.parametrize("rotation", [90, 270])
def test_upright_image_turns_a_phone_frame_counter_clockwise(rotation: int) -> None:
    frame = _first_decoded(_fixture(rotation))
    assert (frame.width, frame.height) == (64, 36)  # PyAV decodes the stored picture
    image = upright_image(frame)
    assert image.mode == "RGB"
    assert image.size == (36, 64)
    _assert_turned(np.asarray(image), rotation)


@pytest.mark.parametrize("rotation", [90, 270])
def test_upright_frame_turns_it_the_same_way_and_keeps_its_time(rotation: int) -> None:
    frame = _first_decoded(_fixture(rotation))
    turned = upright_frame(frame, format="rgb24")
    assert (turned.width, turned.height) == (36, 64)
    assert turned.rotation == 0  # the turn is in the pixels, no matrix left
    assert (turned.pts, turned.time_base) == (frame.pts, frame.time_base)
    _assert_turned(turned.to_ndarray(), rotation)
    # the same turn as the image, pixel for pixel
    assert np.array_equal(turned.to_ndarray(), np.asarray(upright_image(frame)))
    # scaled as stored first, then turned; the format asked for
    small = upright_frame(frame, width=32, height=18, format="yuv420p")
    assert (small.width, small.height, small.format.name) == (18, 32, "yuv420p")


def test_a_frame_without_a_turn_is_left_as_it_was() -> None:
    frame = _first_decoded(PORTRAIT.read_bytes())
    assert frame.rotation == 0
    assert upright_frame(frame) is frame  # nothing asked of it: the very same frame
    assert upright_frame(frame, rotation=0) is frame
    image = upright_image(frame)
    assert image.mode == "RGB"
    assert image.tobytes() == frame.to_image().convert("RGB").tobytes()
    resized = upright_frame(frame, width=90, height=160, format="yuv420p")
    assert (resized.width, resized.height) == (90, 160)


def test_a_turn_the_caller_already_read_is_used_as_it_is() -> None:
    frame = _first_decoded(PORTRAIT.read_bytes())  # 180×320, no matrix
    assert upright_image(frame, rotation=180).size == (180, 320)
    assert upright_image(frame, rotation=-90).size == (320, 180)
    flipped = upright_frame(frame, format="rgb24", rotation=180).to_ndarray()
    assert np.array_equal(flipped, np.rot90(frame.to_ndarray(format="rgb24"), k=2))


def test_a_display_rotation_that_is_not_a_right_angle_is_refused() -> None:
    frame = _first_decoded(_fixture(45))
    with pytest.raises(VideoSourceError) as image_refused:
        upright_image(frame)
    assert image_refused.value.reason == "rotation_unsupported"
    with pytest.raises(VideoSourceError) as frame_refused:
        upright_frame(frame)
    assert frame_refused.value.reason == "rotation_unsupported"
    with pytest.raises(VideoSourceError) as override_refused:
        upright_frame(_first_decoded(PORTRAIT.read_bytes()), rotation=45)
    assert override_refused.value.reason == "rotation_unsupported"


def test_turn_pixels_is_the_counter_clockwise_turn() -> None:
    pixels = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)
    for rotation in (0, 90, 180, 270, -90, 450):
        turned = turn_pixels(pixels, rotation)
        assert turned.flags["C_CONTIGUOUS"]
        assert np.array_equal(turned, np.rot90(pixels, k=(rotation % 360) // 90))
    # 90: the top row becomes the left column, read bottom to top
    assert np.array_equal(turn_pixels(pixels, 90)[:, 0], pixels[0, ::-1])
    for bad in (45, 90.0, True):
        with pytest.raises(VideoSourceError) as refused:
            turn_pixels(pixels, bad)  # type: ignore[arg-type]
        assert refused.value.reason == "rotation_unsupported"


def _bt709_turned_clip(rotation: int) -> bytes:
    """A green 64×36 clip, tagged BT.709 limited range, with a display rotation."""
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 36, "yuv420p"
        stream.codec_context.colorspace = 1
        stream.codec_context.color_range = 1
        stream.set_display_rotation(rotation)
        pixels = np.full((36, 64, 3), (40, 170, 90), dtype=np.uint8)
        for index in range(3):
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24").reformat(
                format="yuv420p", dst_colorspace="ITU709", dst_color_range="MPEG"
            )
            frame.colorspace, frame.color_range = 1, 1
            frame.pts = index
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return out.getvalue()


def test_a_turned_yuv_frame_keeps_the_source_matrix_and_range() -> None:
    """swscale's defaults would write the turned picture as BT.601 with the range unset:
    a BT.709 green would come back with another luma. The turn keeps the source's tags."""
    frame = _first_decoded(_bt709_turned_clip(90))
    assert (frame.colorspace, frame.color_range) == (1, 1)
    turned = upright_frame(frame, format="yuv420p")
    assert (turned.width, turned.height) == (36, 64)
    assert (turned.colorspace, turned.color_range) == (1, 1)
    luma_turned = turned.to_ndarray()[: turned.height].astype(float).mean()
    luma_stored = frame.reformat(format="yuv420p").to_ndarray()[: frame.height].mean()
    assert abs(luma_turned - luma_stored) <= 2  # read back as BT.601 it is ~14 lower


def test_upright_filters_name_the_same_turn() -> None:
    assert upright_filters(0) == ()
    assert upright_filters(90) == ("transpose=cclock",)
    assert upright_filters(270) == upright_filters(-90) == ("transpose=clock",)
    assert upright_filters(180) == ("hflip", "vflip")
    for bad in (45, 90.0, True):
        with pytest.raises(VideoSourceError) as refused:
            upright_filters(bad)  # type: ignore[arg-type]
        assert refused.value.reason == "rotation_unsupported"


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_upright_filters_turn_like_upright_frame(rotation: int) -> None:
    """FFmpeg's `transpose`/`flip` in YUV and numpy's turn in RGB: the same picture."""
    frame = _first_decoded(_fixture(90))
    graph = av.filter.Graph()
    head = source = graph.add_buffer(template=frame)
    for spec in upright_filters(rotation):
        name, _, args = spec.partition("=")
        node = graph.add(name, args or None)
        head.link_to(node)
        head = node
    sink = graph.add("buffersink")
    head.link_to(sink)
    graph.configure()
    source.push(frame)
    filtered = sink.pull().to_ndarray(format="rgb24").astype(int)
    turned = upright_frame(frame, format="rgb24", rotation=rotation).to_ndarray().astype(int)
    assert filtered.shape == turned.shape
    assert np.abs(filtered - turned).max() <= 8  # chroma subsampling, nothing more


def test_a_turned_frame_without_a_time_base_is_still_turned() -> None:
    frame = av.VideoFrame.from_ndarray(np.zeros((4, 6, 3), dtype=np.uint8), format="rgb24")
    assert frame.time_base is None
    turned = upright_frame(frame, rotation=90)
    assert (turned.width, turned.height) == (4, 6)
    assert turned.time_base is None


def test_upright_size_swaps_on_a_quarter_turn() -> None:
    assert upright_size(1920, 1080, 90) == (1080, 1920)
    assert upright_size(1920, 1080, 270) == (1080, 1920)
    assert upright_size(1920, 1080, 180) == (1920, 1080)
    assert upright_size(1920, 1080, 0) == (1920, 1080)


# --- the fitter ----------------------------------------------------------------------


def _decoded(data: bytes) -> tuple[int, int, int, np.ndarray]:
    """An encoded MP4's stored size, its first frame's rotation and its RGB pixels."""
    with av.open(io.BytesIO(data)) as source:
        stream = source.streams.video[0]
        frame = next(source.decode(stream))
        return (
            stream.codec_context.width,
            stream.codec_context.height,
            frame.rotation,
            frame.to_ndarray(format="rgb24"),
        )


@pytest.mark.parametrize("rotation", [90, 270])
def test_fit_reference_of_a_phone_video_is_upright(rotation: int) -> None:
    fitted = PyAvVideoFitter().fit_reference(_fixture(rotation))
    width, height, matrix, pixels = _decoded(fitted.data)
    assert (fitted.width, fitted.height) == (width, height) == (36, 64)
    assert matrix == 0
    _assert_turned(pixels, rotation)
    assert fitted.poster is not None


@pytest.mark.parametrize("rotation", [90, 270])
def test_fit_crops_the_upright_picture(rotation: int) -> None:
    fitted = PyAvVideoFitter().fit(_fixture(rotation), size=(36, 64))
    width, height, matrix, pixels = _decoded(fitted.data)
    assert (width, height, matrix) == (36, 64, 0)
    _assert_turned(pixels, rotation)


def test_subtitle_keeps_the_upright_size() -> None:
    fitted = PyAvVideoFitter().subtitle(_fixture(270), layers=lambda size: ())
    assert (fitted.width, fitted.height) == (36, 64)
    _assert_turned(_decoded(fitted.data)[3], 270)


def test_fit_and_fit_reference_refuse_a_rotation_that_is_not_a_right_angle() -> None:
    fitter = PyAvVideoFitter()
    for encode in (
        lambda: fitter.fit_reference(_fixture(45)),
        lambda: fitter.fit(_fixture(45), size=(36, 64)),
    ):
        with pytest.raises(VideoSourceError) as refused:
            encode()
        assert refused.value.reason == "rotation_unsupported"


# --- a video without a turn: the same bytes as before EF-01 --------------------------

#: What origin/main (b7fbff73, before EF-01) produced from `video-portrait-2s.mp4` with
#: PyAV 19.0.1, computed before the change: the poster's SHA-256 (Pillow's JPEG of the
#: graph's first frame — stable), and the MP4's shape. The MP4's bytes are compared only
#: under the `reproducible_x264` fixture (conftest.py): with production's x264 settings
#: libx264 writes other bytes for the same frames as the process ages (m-25029128: 18
#: distinct MP4s in 200 encodes of one process — the SIMD macroblock-tree propagation in
#: its lookahead), so a hash without the fixture would be flaky, not wrong.
UNTURNED_POSTER_SHA256 = {
    "fit": "8cf9ef35936ad06054a0c42f8a8394595c495c914ead7f78a5a280f240deecf1",
    "fit_reference": "1e24eda1c967afb450f784e4ebb8ba87a9edbd11d9220ee526f038fa6417584a",
    "fit_reference_small": "3ab83121aee471acd6a213daa0acb898b5f527faa2bccff333b181101a84b29c",
    "subtitle": "1e24eda1c967afb450f784e4ebb8ba87a9edbd11d9220ee526f038fa6417584a",
}
#: (width, height, frames) of each output on origin/main
UNTURNED_SHAPE = {
    "fit": (144, 180),
    "fit_reference": (180, 320),
    "fit_reference_small": (90, 160),
    "subtitle": (180, 320),
}


def _sha(data: bytes | None) -> str:
    assert data is not None
    return hashlib.sha256(data).hexdigest()


def _unturned_outputs() -> dict[str, FittedVideo]:
    source = PORTRAIT.read_bytes()
    fitter = PyAvVideoFitter()
    return {
        "fit": fitter.fit(source, size=(144, 180)),
        "fit_reference": fitter.fit_reference(source),
        "fit_reference_small": fitter.fit_reference(source, short_side=90),
        "subtitle": fitter.subtitle(source, layers=lambda size: ()),
    }


def _contents(data: bytes) -> tuple[tuple[int, int], list[int | None], np.ndarray]:
    """An MP4's stored size, its frames' pts, and all its frames' RGB pixels."""
    with av.open(io.BytesIO(data)) as source:
        stream = source.streams.video[0]
        frames = list(source.decode(stream))
        size = (stream.codec_context.width, stream.codec_context.height)
    pixels = np.stack([frame.to_ndarray(format="rgb24") for frame in frames])
    return size, [frame.pts for frame in frames], pixels


def _reproducible_fitter_tables(reproducible_x264: Callable[..., None]) -> None:
    """Every x264 table `_unturned_outputs` encodes with, made byte-reproducible."""
    from qualify_creative.video import fit as fit_module  # noqa: PLC0415

    reproducible_x264(fit_module.SLIDE_X264, fit_module.REFERENCE_X264, fit_module.DETAIL_X264)


#: The SHA-256 of `fit_reference(video-portrait-2s.mp4, short_side=90)`'s MP4 under
#: `reproducible_x264` with PyAV 19.0.1 (its bundled FFmpeg/x264). Measured 2026-11-20
#: (m-25029128): the same on Windows (60/60 in one process) and on Linux x86_64
#: (python:3.12-slim, 40/40 on 8 cores and 60/60 on 2), so it is not pinned to a platform.
REFERENCE_SMALL_SHA256 = "4eacc08ac3d738b6befd7958ec4e19f1c8ab87ac1aac80655dc7324282f834b5"


def _reference_small() -> bytes:
    return PyAvVideoFitter().fit_reference(PORTRAIT.read_bytes(), short_side=90).data


def test_a_reference_encode_is_the_same_bytes_run_after_run(
    reproducible_x264: Callable[..., None],
) -> None:
    """Any platform and PyAV: under `reproducible_x264` two encodes of the same source in
    one process are the same MP4, byte for byte."""
    _reproducible_fitter_tables(reproducible_x264)
    assert _reference_small() == _reference_small()


@pytest.mark.skipif(
    av.__version__ != "19.0.1",
    reason="hash pinned with PyAV 19.0.1's x264; the run-to-run check above is version-free",
)
def test_a_reference_encode_has_the_pinned_hash(reproducible_x264: Callable[..., None]) -> None:
    _reproducible_fitter_tables(reproducible_x264)
    assert _sha(_reference_small()) == REFERENCE_SMALL_SHA256


@pytest.mark.skipif(
    sys.platform != "win32" or av.__version__ != "19.0.1",
    reason="posters pinned on Windows with PyAV 19.0.1; the platform-free check is below",
)
def test_a_video_without_a_turn_gives_the_same_posters_as_before() -> None:
    produced = _unturned_outputs()
    assert {name: _sha(out.poster) for name, out in produced.items()} == UNTURNED_POSTER_SHA256


def test_a_video_without_a_turn_keeps_its_size_and_length() -> None:
    for name, out in _unturned_outputs().items():
        size, pts, _ = _contents(out.data)
        assert (out.width, out.height) == size == UNTURNED_SHAPE[name], name
        assert len(pts) == 24, name  # 2 s at 12 fps, every frame kept


def test_without_a_turn_the_straightener_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, reproducible_x264: Callable[..., None]
) -> None:
    """Any platform: the fitter's output for a video without a turn is its output with
    EF-01's hooks taken out — the rotation never read and no turning filter in the graph,
    which is what the code before EF-01 did: the same posters and the same MP4s, byte for
    byte (x264 made reproducible: see `UNTURNED_POSTER_SHA256`)."""
    from qualify_creative.video import fit as fit_module  # noqa: PLC0415

    _reproducible_fitter_tables(reproducible_x264)
    with_hooks = _unturned_outputs()
    with monkeypatch.context() as patched:
        patched.setattr(fit_module, "_source_rotation", lambda data: 0)
        patched.setattr(fit_module, "upright_filters", lambda rotation: ())
        without_hooks = _unturned_outputs()
    for name, out in with_hooks.items():
        assert out.poster == without_hooks[name].poster, name
        assert (out.width, out.height) == (without_hooks[name].width, without_hooks[name].height)
        assert out.data == without_hooks[name].data, name


def test_without_a_turn_the_graph_is_the_one_before_ef01(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any platform: for a video without a turn, `fit`, `fit_reference` (with and without
    the `fps` resample) and `subtitle` build exactly the filter graph origin/main
    (b7fbff73, `fit._encode`) built — the same nodes, in the same order, with the same
    arguments — so «without a turn, as before» holds even where the MP4's bytes do not."""
    calls: list[tuple[str, object]] = []

    real_graph = av.filter.Graph

    class _SpyGraph:
        """Records what `fit._encode` adds, then hands it to a real graph (PyAV's
        `Graph` is a compiled type: it cannot be subclassed or patched in place)."""

        def __init__(self) -> None:
            self._graph = real_graph()

        def add_buffer(self, template: object = None, **kwargs: object) -> object:
            calls.append(("buffer", (type(template).__name__, kwargs)))
            return self._graph.add_buffer(template=template, **kwargs)

        def add(self, filter: str, args: object = None, **kwargs: object) -> object:  # noqa: A002
            calls.append((filter, args))
            return self._graph.add(filter, args, **kwargs)

        def __getattr__(self, name: str) -> object:
            return getattr(self._graph, name)

    monkeypatch.setattr(av.filter, "Graph", _SpyGraph)
    source = PORTRAIT.read_bytes()  # 180×320 at 12 fps, no display matrix
    fitter = PyAvVideoFitter()

    def crop(width: int, height: int) -> tuple[str, str]:
        return ("crop", f"w='min(iw,ih*{width}/{height})':h='min(ih,iw*{height}/{width})'")

    def graph(width: int, height: int, fps: str | None = None) -> list[tuple[str, object]]:
        nodes: list[tuple[str, object]] = [
            ("buffer", ("VideoStream", {})),
            crop(width, height),
            ("scale", f"{width}:{height}"),
            ("format", "yuv420p"),
            ("buffersink", None),
        ]
        return nodes + ([("fps", fps)] if fps is not None else [])

    expected = {
        "fit": (lambda: fitter.fit(source, size=(144, 180)), graph(144, 180)),
        "fit_reference": (lambda: fitter.fit_reference(source), graph(180, 320)),
        "fit_reference_resampled": (
            lambda: fitter.fit_reference(source, short_side=90, max_fps=6),
            graph(90, 160, fps="6"),
        ),
        "subtitle": (lambda: fitter.subtitle(source, layers=lambda size: ()), graph(180, 320)),
    }
    for name, (run, nodes) in expected.items():
        calls.clear()
        run()
        assert calls == nodes, name
