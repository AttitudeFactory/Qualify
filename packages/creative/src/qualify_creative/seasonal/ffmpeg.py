"""Running the `ffmpeg` binary for the seasonal recipes, with the hard limits of the
shared server (`media-worker`: 1 CPU, 768 MB, one job at a time — ADR 47):

- `-threads 1` and `-filter_threads 1` (and `-filter_complex_threads 1`): one core;
- under `nice` when the system has it, so a sticker never slows the app;
- a wall-clock `timeout` per call (a 5 s clip or a 2 s sticker takes seconds);
- `-nostdin`, `-y`, `-hide_banner`, `-loglevel error`: no prompt, no chatter;
- only local files in and out — the caller's temp dir.

A non-zero exit is `ffmpeg_failed`; a kill by a signal (negative return code: the OOM
killer) or a timeout is the same code marked `transient`, so the job retries.
"""

from __future__ import annotations

import functools
import shutil
import subprocess
from collections.abc import Sequence

from qualify_creative.seasonal.errors import FFMPEG_FAILED, FFMPEG_MISSING, RecipeError

FFMPEG = "ffmpeg"
#: A seasonal FFmpeg call is a few seconds of work; 90 s means something is wrong.
FFMPEG_TIMEOUT_SECONDS = 90
NICE_LEVEL = "10"
#: Global options (before the inputs): one thread for every filter graph.
GLOBAL_THREAD_ARGS = ("-filter_threads", "1", "-filter_complex_threads", "1")
#: Output option (right before the output file): one encoder thread.
OUTPUT_THREAD_ARGS = ("-threads", "1")


def ffmpeg_path(binary: str = FFMPEG) -> str | None:
    return shutil.which(binary)


@functools.lru_cache(maxsize=4)
def has_encoder(name: str, binary: str = FFMPEG) -> bool:
    """Whether this FFmpeg build has the encoder `name` (e.g. `libwebp_anim`, `libx264`).
    The options doc left `libwebp_anim` in Debian's FFmpeg unverified [S]; this checks it
    at run time instead of assuming."""
    path = ffmpeg_path(binary)
    if path is None:
        return False
    try:
        proc = subprocess.run(
            [path, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return any(
        len(parts) >= 2 and parts[1] == name
        for parts in (line.split() for line in proc.stdout.splitlines())
    )


def run_ffmpeg(
    args: Sequence[str],
    *,
    timeout: float = FFMPEG_TIMEOUT_SECONDS,
    binary: str = FFMPEG,
    use_nice: bool = True,
) -> None:
    """Run `ffmpeg <args>` with the limits above. `args` must not start with the binary;
    the global thread flags are added here, the encoder's `-threads 1` by the caller
    (it is an output option and must sit before the output file)."""
    path = ffmpeg_path(binary)
    if path is None:
        raise RecipeError(FFMPEG_MISSING, "ffmpeg not on PATH")
    cmd = [path, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *GLOBAL_THREAD_ARGS, *args]
    nice = shutil.which("nice") if use_nice else None
    if nice is not None:
        cmd = [nice, "-n", NICE_LEVEL, *cmd]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RecipeError(FFMPEG_FAILED, "timeout", transient=True) from exc
    except OSError as exc:
        raise RecipeError(FFMPEG_FAILED, type(exc).__name__) from exc
    if proc.returncode < 0:
        raise RecipeError(FFMPEG_FAILED, f"killed by signal {-proc.returncode}", transient=True)
    if proc.returncode != 0:
        # The last stderr line only: FFmpeg's error, no file paths beyond our temp dir.
        last = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        raise RecipeError(FFMPEG_FAILED, last[0][:200])
