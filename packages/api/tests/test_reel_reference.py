"""Replication downloads are bounded; only a silent normalized reference survives."""

from __future__ import annotations

import io

import httpx
import pytest

from qualify_api.referentes import reel_reference as ref

URL = "https://scontent.cdninstagram.com/reel.mp4?secret=do-not-log"


@pytest.mark.parametrize(
    "url",
    [
        "http://scontent.cdninstagram.com/reel.mp4",
        "https://cdninstagram.com.evil.test/reel.mp4",
        "https://127.0.0.1/reel.mp4",
        "https://user:password@cdninstagram.com/reel.mp4",
        "https://cdninstagram.com:444/reel.mp4",
        "https://unavatar.io/reel.mp4",
        "https://[bad",
    ],
)
def test_untrusted_sources_never_make_a_request(url: str) -> None:
    def unwanted(request: httpx.Request) -> httpx.Response:
        pytest.fail("an untrusted source was fetched")

    with httpx.Client(transport=httpx.MockTransport(unwanted)) as client:
        with pytest.raises(ref.ReelReferenceUnavailable):
            ref.prepare_reference("instagram", url, client=client)
    assert not ref.source_allowed("tiktok", URL)


@pytest.mark.parametrize("status", [302, 403, 404, 410, 500])
def test_expired_and_redirected_urls_are_recoverable(status: int) -> None:
    seen = []

    def response(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(status, headers={"location": "https://127.0.0.1/private"})

    with httpx.Client(transport=httpx.MockTransport(response), follow_redirects=True) as client:
        with pytest.raises(ref.ReelReferenceUnavailable) as exc:
            ref.prepare_reference("instagram", URL, client=client)
    assert seen == [URL]
    assert "secret" not in str(exc.value)


def test_download_is_capped_before_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ref, "MAX_BYTES", 3)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"1234"))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(ref.ReelReferenceUnavailable, match="demasiado grande"):
            ref.prepare_reference("instagram", URL, client=client)


def test_the_real_reference_is_five_seconds_and_has_no_original_audio() -> None:
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    buf = io.BytesIO()
    with av.open(buf, "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=24)
        video.width, video.height, video.pix_fmt = 96, 160, "yuv420p"
        audio = sink.add_stream("aac", rate=44100)
        audio.layout = "mono"
        for i in range(12 * 24):
            pixels = np.full((160, 96, 3), i % 255, dtype=np.uint8)
            for packet in video.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                sink.mux(packet)
        for i in range(12 * 44100 // 1024):
            frame = av.AudioFrame.from_ndarray(
                np.zeros((1, 1024), dtype=np.float32), format="fltp", layout="mono"
            )
            frame.sample_rate, frame.pts = 44100, i * 1024
            for packet in audio.encode(frame):
                sink.mux(packet)
        for stream in (video, audio):
            for packet in stream.encode():
                sink.mux(packet)
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=buf.getvalue()))
    with httpx.Client(transport=transport) as client:
        fitted = ref.prepare_reference("instagram", URL, client=client)
    assert fitted.duration_sec == pytest.approx(5, abs=0.1)
    assert fitted.width * fitted.height >= ref.MIN_REFERENCE_PIXELS
    assert fitted.width / fitted.height == pytest.approx(96 / 160, abs=0.01)
    with av.open(io.BytesIO(fitted.data)) as source:
        assert not source.streams.audio
        assert source.streams.video[0].codec_context.name == "h264"
        assert source.duration / 1_000_000 == pytest.approx(5, abs=0.1)


def test_non_video_content_is_a_safe_error() -> None:
    with pytest.raises(ref.ReelReferenceUnavailable, match="preparar"):
        ref.normalize_reference(b"not a video")


@pytest.mark.parametrize("size", [(404, 720), (360, 640), (540, 960), (1920, 1080), (3840, 2160)])
def test_reference_size_meets_the_provider_limits(size: tuple[int, int]) -> None:
    width, height = ref.reference_size(*size)
    assert 300 <= min(width, height) and max(width, height) <= 1280
    assert width * height >= ref.MIN_REFERENCE_PIXELS
    assert width % 2 == height % 2 == 0
    assert width / height == pytest.approx(size[0] / size[1], abs=0.01)


@pytest.mark.parametrize("size", [(0, 0), (100, 1000), (1000, 100)])
def test_invalid_reference_aspects_are_rejected(size: tuple[int, int]) -> None:
    with pytest.raises(ValueError):
        ref.reference_size(*size)
