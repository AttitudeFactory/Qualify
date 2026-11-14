"""Facts + poster from a video file on disk (m-25026481): the parsing, the command and the
best-effort fallbacks with the subprocess faked (everywhere); the real binaries on two
committed fixtures and a rotated clip only where ffmpeg exists (`integration`)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from qualify_creative.video import (
    POSTER_TIMEOUT_SECONDS,
    FfmpegUnavailable,
    VideoFacts,
    VideoStill,
    VideoStillError,
    poster_from_video_file,
    probe_video_file,
    video_still,
)
from qualify_creative.video import still as still_module
from qualify_creative.video.still import (
    facts_from_probe,
    poster_command,
    poster_moment,
    probe_command,
)

FIXTURES = Path(__file__).parent / "fixtures"
#: Never exists: the faked runs prove nothing in Python opens the file.
GHOST = Path("/nonexistent/t/tenant-uuid/planner/video.mov")
JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


class _Proc:
    def __init__(self, returncode: int = 0, stdout: Any = "", stderr: Any = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _probe_json(**over: Any) -> str:
    info: dict[str, Any] = {
        "format": {"duration": "12.5"},
        "streams": [
            {"codec_type": "audio"},
            {"codec_type": "video", "width": 1920, "height": 1080, "duration": "12.4"},
        ],
    }
    info.update(over)
    return json.dumps(info)


def _fake(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[list[str]]:
    seen: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> _Proc:
        seen.append(cmd)
        return handler(cmd, **kwargs)

    monkeypatch.setattr(still_module.subprocess, "run", fake_run)
    monkeypatch.setattr(still_module.shutil, "which", lambda _: "/bin/x")
    return seen


# -- parsing -------------------------------------------------------------------------------


def test_duration_prefers_format_then_stream() -> None:
    assert facts_from_probe(json.loads(_probe_json())) == VideoFacts(1920, 1080, 12.5)
    no_format = json.loads(_probe_json(format={}))
    assert facts_from_probe(no_format).duration_seconds == 12.4


@pytest.mark.parametrize("raw", [None, "N/A", "garbage", "0", "-3", "nan", "inf"])
def test_missing_or_garbage_duration_is_none(raw: Any) -> None:
    info = {
        "format": {"duration": raw},
        "streams": [{"codec_type": "video", "width": 10, "height": 20, "duration": raw}],
    }
    assert facts_from_probe(info).duration_seconds is None


def test_no_video_stream_gives_unknown_size() -> None:
    facts = facts_from_probe({"format": {"duration": "3"}, "streams": [{"codec_type": "audio"}]})
    assert facts == VideoFacts(None, None, 3.0)


@pytest.mark.parametrize(
    "stream_extra, swapped",
    [
        ({"side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]}, True),
        ({"side_data_list": [{"rotation": 90}]}, True),
        ({"side_data_list": [{"rotation": 270}]}, True),
        ({"side_data_list": [{"rotation": 180}]}, False),
        ({"tags": {"rotate": "90"}}, True),
        ({"tags": {"rotate": "270"}}, True),
        ({"tags": {"rotate": "0"}}, False),
        ({"tags": {"rotate": "sideways"}}, False),
        ({}, False),
    ],
)
def test_rotation_gives_the_display_size(stream_extra: dict[str, Any], swapped: bool) -> None:
    stream = {"codec_type": "video", "width": 1920, "height": 1080, **stream_extra}
    facts = facts_from_probe({"format": {"duration": "1"}, "streams": [stream]})
    assert (facts.width, facts.height) == ((1080, 1920) if swapped else (1920, 1080))


def test_poster_moment() -> None:
    assert poster_moment(None) == 0.0 and poster_moment(0) == 0.0
    assert poster_moment(0.6) == pytest.approx(0.3)
    assert poster_moment(65) == 1.0


# -- the commands --------------------------------------------------------------------------


def test_poster_command_seeks_before_input_one_frame_capped_threads() -> None:
    cmd = poster_command(GHOST, at_seconds=1.0, max_side=1080)
    source = cmd.index("-i")
    assert cmd[source + 1] == str(GHOST)
    assert cmd.index("-ss") < source and cmd[cmd.index("-ss") + 1] == "1.000"
    assert cmd[cmd.index("-frames:v") + 1] == "1"
    assert {"-an", "-sn", "-dn"} <= set(cmd[source:])
    threads = [cmd[i + 1] for i, a in enumerate(cmd) if a == "-threads"]
    assert threads == ["1", "1"]
    assert cmd.index("-filter_threads") < source and cmd[cmd.index("-filter_threads") + 1] == "1"
    vf = cmd[cmd.index("-vf") + 1]
    assert "min(1080,iw)" in vf and "force_original_aspect_ratio=decrease" in vf
    assert cmd[-1] == "pipe:1" and cmd[cmd.index("-q:v") + 1] == "3"


def test_both_commands_only_allow_local_protocols() -> None:
    for cmd in (poster_command(GHOST, at_seconds=1.0), probe_command(GHOST)):
        flag = cmd.index("-protocol_whitelist")
        assert cmd[flag + 1] == "file,pipe"
        assert flag < cmd.index(str(GHOST))
    poster = poster_command(GHOST, at_seconds=1.0)
    assert poster.index("-protocol_whitelist") < poster.index("-i")


def test_children_get_only_the_allow_listed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    envs: list[dict[str, str]] = []

    def handler(cmd: list[str], **kwargs: Any) -> _Proc:
        envs.append(kwargs["env"])
        if cmd[0] == "ffprobe":
            return _Proc(stdout=_probe_json())
        return _Proc(stdout=JPEG, stderr=b"")

    _fake(monkeypatch, handler)
    video_still(GHOST)
    assert len(envs) == 2
    for env in envs:
        assert set(env) <= set(still_module.CHILD_ENV_KEYS)
        assert env["PATH"] == "/usr/bin:/bin"
        assert "secret" not in "".join(env.values())


def test_probe_runs_with_timeout_and_never_opens_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs_seen: dict[str, Any] = {}

    def handler(cmd: list[str], **kwargs: Any) -> _Proc:
        kwargs_seen.update(kwargs)
        return _Proc(stdout=_probe_json())

    seen = _fake(monkeypatch, handler)
    assert probe_video_file(GHOST) == VideoFacts(1920, 1080, 12.5)
    assert seen[0][0] == "ffprobe" and seen[0][-1] == str(GHOST)
    assert kwargs_seen["timeout"] == still_module.PROBE_TIMEOUT_SECONDS


def test_probe_errors_are_redacted_and_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake(monkeypatch, lambda cmd, **_: _Proc(1, stderr=f"{GHOST}: Invalid data found"))
    with pytest.raises(VideoStillError) as err:
        probe_video_file(GHOST)
    assert "tenant-uuid" not in str(err.value) and "<video>" in str(err.value)

    _fake(monkeypatch, lambda cmd, **_: _Proc(stdout="not json"))
    with pytest.raises(VideoStillError):
        probe_video_file(GHOST)


def test_timeouts_and_missing_binaries_are_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(cmd: list[str], **kwargs: Any) -> _Proc:
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    _fake(monkeypatch, hang)
    with pytest.raises(VideoStillError, match="timed out"):
        probe_video_file(GHOST)
    with pytest.raises(VideoStillError, match="timed out"):
        poster_from_video_file(GHOST, at_seconds=1.0)

    def missing(cmd: list[str], **_: Any) -> _Proc:
        raise FileNotFoundError(cmd[0])

    _fake(monkeypatch, missing)
    with pytest.raises(FfmpegUnavailable):
        poster_from_video_file(GHOST)


def test_poster_uses_its_timeout_and_returns_the_jpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    timeouts: list[Any] = []

    def handler(cmd: list[str], **kwargs: Any) -> _Proc:
        timeouts.append(kwargs["timeout"])
        assert kwargs["text"] is False
        return _Proc(stdout=JPEG, stderr=b"")

    _fake(monkeypatch, handler)
    assert poster_from_video_file(GHOST, at_seconds=1.0) == JPEG
    assert timeouts == [POSTER_TIMEOUT_SECONDS]


@pytest.mark.parametrize("first", [_Proc(0, b"", b""), _Proc(234, b"", b"no frame")])
def test_a_seek_without_frame_retries_once_at_zero(
    monkeypatch: pytest.MonkeyPatch, first: _Proc
) -> None:
    answers = [first, _Proc(0, JPEG, b"")]
    seen = _fake(monkeypatch, lambda cmd, **_: answers.pop(0))
    assert poster_from_video_file(GHOST, at_seconds=1.0) == JPEG
    assert [c[c.index("-ss") + 1] for c in seen] == ["1.000", "0.000"]


def test_no_frame_at_zero_is_an_error_without_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _fake(monkeypatch, lambda cmd, **_: _Proc(0, b"", b""))
    with pytest.raises(VideoStillError, match="no frame"):
        poster_from_video_file(GHOST)
    assert len(seen) == 1

    _fake(monkeypatch, lambda cmd, **_: _Proc(0, b"GIF89a", b""))
    with pytest.raises(VideoStillError, match="not a JPEG"):
        poster_from_video_file(GHOST)


# -- video_still: best effort ---------------------------------------------------------------


def test_video_still_happy_path_seeks_one_second(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(cmd: list[str], **_: Any) -> _Proc:
        if cmd[0] == "ffprobe":
            return _Proc(stdout=_probe_json())
        return _Proc(stdout=JPEG, stderr=b"")

    seen = _fake(monkeypatch, handler)
    assert video_still(GHOST) == VideoStill(VideoFacts(1920, 1080, 12.5), JPEG)
    grab = seen[1]
    assert grab[grab.index("-ss") + 1] == "1.000"


def test_failed_probe_still_tries_the_poster_at_zero(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def handler(cmd: list[str], **_: Any) -> _Proc:
        if cmd[0] == "ffprobe":
            return _Proc(1, stderr=f"{GHOST}: moov atom not found")
        return _Proc(stdout=JPEG, stderr=b"")

    seen = _fake(monkeypatch, handler)
    with caplog.at_level(logging.INFO, logger=still_module.__name__):
        result = video_still(GHOST)
    assert result == VideoStill(VideoFacts(None, None, None), JPEG)
    assert seen[1][seen[1].index("-ss") + 1] == "0.000"
    assert "VideoStillError" in caplog.text and "tenant-uuid" not in caplog.text


def test_failed_poster_gives_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(cmd: list[str], **kwargs: Any) -> _Proc:
        if cmd[0] == "ffprobe":
            return _Proc(stdout=_probe_json())
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    _fake(monkeypatch, handler)
    assert video_still(GHOST) == VideoStill(VideoFacts(1920, 1080, 12.5), None)


def test_everything_failing_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(cmd: list[str], **kwargs: Any) -> _Proc:
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    _fake(monkeypatch, handler)
    assert video_still(GHOST) == VideoStill(VideoFacts(None, None, None), None)

    def gone(cmd: list[str], **_: Any) -> _Proc:
        raise FileNotFoundError(cmd[0])

    _fake(monkeypatch, gone)
    assert video_still(GHOST) == VideoStill(VideoFacts(None, None, None), None)


def test_missing_binaries_give_unknowns_without_running(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _fake(monkeypatch, lambda cmd, **_: _Proc())
    monkeypatch.setattr(still_module.shutil, "which", lambda _: None)
    assert video_still(GHOST) == VideoStill(VideoFacts(None, None, None), None)
    assert seen == []


# -- the real binaries ---------------------------------------------------------------------


def _need_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")


def _jpeg_size(jpeg: bytes) -> tuple[int, int]:
    """(width, height) from the JPEG's SOF marker — no image library needed."""
    i = 2
    while i < len(jpeg):
        marker, length = jpeg[i + 1], int.from_bytes(jpeg[i + 2 : i + 4], "big")
        if 0xC0 <= marker <= 0xC3:
            return int.from_bytes(jpeg[i + 7 : i + 9], "big"), int.from_bytes(
                jpeg[i + 5 : i + 7], "big"
            )
        i += 2 + length
    raise AssertionError("no SOF marker")


@pytest.mark.integration
@pytest.mark.parametrize(
    "name, size, duration",
    [("video-portrait-2s.mp4", (180, 320), 2.0), ("video-portrait-65s.mp4", (90, 160), 65.0)],
)
def test_real_fixture(name: str, size: tuple[int, int], duration: float) -> None:
    _need_ffmpeg()
    result = video_still(FIXTURES / name)
    assert (result.facts.width, result.facts.height) == size
    assert result.facts.duration_seconds == pytest.approx(duration, abs=0.2)
    assert result.poster_jpeg is not None and result.poster_jpeg[:2] == b"\xff\xd8"
    assert _jpeg_size(result.poster_jpeg) == size


@pytest.mark.integration
def test_real_poster_is_capped_and_a_late_seek_falls_back() -> None:
    _need_ffmpeg()
    clip = FIXTURES / "video-portrait-2s.mp4"
    small = poster_from_video_file(clip, at_seconds=1.0, max_side=100)
    width, height = _jpeg_size(small)
    assert max(width, height) <= 100 and height > width
    late = poster_from_video_file(clip, at_seconds=600.0)
    assert late[:2] == b"\xff\xd8"


@pytest.mark.integration
def test_real_rotated_clip_reports_display_size(tmp_path: Path) -> None:
    _need_ffmpeg()
    rotated = tmp_path / "rotated.mp4"
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-display_rotation",
            "90",
            "-i",
            str(FIXTURES / "video-portrait-2s.mp4"),
            "-c",
            "copy",
            str(rotated),
        ],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        pytest.skip("this ffmpeg cannot write a display matrix (-display_rotation)")
    facts = probe_video_file(rotated)
    assert (facts.width, facts.height) == (320, 180)
    poster = video_still(rotated).poster_jpeg
    assert poster is not None and _jpeg_size(poster) == (320, 180)


@pytest.mark.integration
def test_real_garbage_file_is_best_effort(tmp_path: Path) -> None:
    _need_ffmpeg()
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video at all" * 100)
    assert video_still(junk) == VideoStill(VideoFacts(None, None, None), None)
