"""`join_clips` in a short-lived child process (VE-10b m-24921068).

Why: the 1080p final join of a video by parts (10-bit H.265 parts decoded, 1080p H.264
encoded) grew the creative worker past its 768 MiB cap in one process (measured
2026-11-06, native amd64): decoder, encoder and malloc arenas never went back to the OS.
A child that exits gives ALL of it back. The parent (the worker) keeps everything that
needs the database or R2 — the lease heartbeat, the fence, the save; the child only
reads the parts from local paths, joins them (logo included), writes the output file
and exits.

The boundary: the parent writes a JSON spec beside the output (`<out>.spec.json`: the
parts' paths and intervals, size, the overlay PNG's path, threads) and runs
`sys.executable -m qualify_creative.video.join_child <spec>` with `MALLOC_ARENA_MAX=2`.
The child answers with its exit code and a JSON result (`<out>.result.json`):

- `0` — joined: frames and the poster's path;
- `3` (`EXIT_PARTS`) — a typed `JoinError` from the PARTS (no video, undecodable data,
  a bad interval): re-raised as a `JoinError` in the parent, the caller's permanent path;
- `4` (`EXIT_IO`) — the machine failed (an `OSError` in the error's causes: full disk, a
  file cut short);
- anything else — killed (signal, OOM 137), crashed, no result, or past `timeout` (the
  child is killed first).

Every non-`3` outcome is raised as a `JoinError` CAUSED BY an `OSError`, so the
callers' `io_failure` classifies it as a retry: never a charge, never a failed row. The
temp files (spec, result, overlay, poster, a half-written output) live in the caller's
folder, which the caller removes.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any

#: `prctl` option that turns transparent huge pages off for this process and its
#: children (Linux 3.15+).
PR_SET_THP_DISABLE = 41


def disable_thp(*, platform: str = sys.platform, libc: Any = None) -> bool:
    """Turn transparent huge pages off for THIS process (Deivid, 2026-11-07): a 1080p
    decoder's and encoder's buffers in 2 MiB huge pages were ~100 MiB of the child's
    anon memory at the measured peak. Linux only — elsewhere a no-op; when `prctl` is
    missing or refuses, one line on stderr and the join goes on. True when disabled."""
    if not platform.startswith("linux"):
        return False
    try:
        import ctypes  # noqa: PLC0415

        lib = libc if libc is not None else ctypes.CDLL(None, use_errno=True)
        if lib.prctl(PR_SET_THP_DISABLE, 1, 0, 0, 0) != 0:
            errno = ctypes.get_errno()
            print(f"join child: transparent huge pages left on (errno {errno})", file=sys.stderr)
            return False
    except Exception as exc:  # noqa: BLE001 — a memory hint, never a reason to fail
        print(f"join child: transparent huge pages left on ({exc})", file=sys.stderr)
        return False
    return True


if __name__ == "__main__":
    # first, before PyAV/numpy or any codec is imported or allocates (the child only)
    disable_thp()

from qualify_creative.video.join import (  # noqa: E402
    JOIN_FPS,
    JoinClip,
    JoinedVideo,
    JoinError,
    JoinSegment,
    encode_segment,
    join_clips,
)

#: Exit codes of the child (anything else: killed or crashed — retried).
EXIT_OK = 0
EXIT_PARTS = 3
EXIT_IO = 4
#: Threads per codec in the child: production's creative-worker has `cpus: 1.0`.
JOIN_CHILD_THREADS = int(os.getenv("QUALIFY_JOIN_THREADS", "1"))
#: How long a join may take before its child is killed (and the run retried): six 10 s
#: 1080p parts encode in well under this on one arm64 core; a hung decoder must not
#: hold the worker's one join slot for ever.
JOIN_CHILD_TIMEOUT_S = float(os.getenv("QUALIFY_JOIN_TIMEOUT_S", "1200"))
#: What the child's malloc may keep: two arenas instead of one per thread.
CHILD_ENV = {"MALLOC_ARENA_MAX": "2"}


def _io_shaped(exc: BaseException) -> bool:
    """An `OSError` anywhere in the causes: the machine, not the parts."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, OSError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


class JoinChildLost(JoinError):
    """The child died, was killed (signal, OOM 137) or timed out without a typed answer:
    retried by the next pass — but a part that always kills its child must not loop for
    ever, so callers count these (`part_final`: 3, then the join row fails)."""


#: Set by the worker when it stops (Docker stop, a deploy): a child killed then was not
#: lost to its part — it is retried without counting (`BackgroundJoins.shutdown`).
WORKER_STOPPING = threading.Event()
#: Signals a stopping worker (or Docker) sends to the whole container.
_STOP_SIGNALS = frozenset({signal.SIGTERM, signal.SIGINT})


def _retry(message: str, *, counted: bool = True) -> JoinError:
    """A retry. `counted`: a real loss of the child (killed, OOM, crashed, timed out),
    counted towards the part's limit; else the machine or a stopping worker."""
    error = JoinChildLost(message) if counted else JoinError(message)
    error.__cause__ = OSError(message)
    return error


def _lost_to_its_part(returncode: int) -> bool:
    """Whether a child that ended without a result counts as lost: not when the machine
    failed (`EXIT_IO`: a full disk) nor when the worker is stopping (its flag, or the
    stop signal the whole container got)."""
    if WORKER_STOPPING.is_set():
        return False
    if returncode == EXIT_IO:
        return False
    return not (returncode < 0 and -returncode in _STOP_SIGNALS)


#: What the child may see of the worker's environment (review, 2026-11-08): what Python
#: and the codecs need, the join's own settings — never a database URL, an R2 or vendor
#: key. Exact names, then prefixes.
_CHILD_ENV_NAMES = frozenset(
    {"PATH", "PYTHONPATH", "PYTHONUTF8", "HOME", "TEMP", "TMP", "TMPDIR", "LANG",
     "MALLOC_ARENA_MAX", "SYSTEMROOT", "WINDIR"}
)  # fmt: skip
_CHILD_ENV_PREFIXES = ("LC_", "QUALIFY_JOIN_")


def child_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The child's environment: the allowed part of `environ` (the worker's), plus
    `MALLOC_ARENA_MAX=2`."""
    source = os.environ if environ is None else environ
    kept = {
        name: value
        for name, value in source.items()
        if name.upper() in _CHILD_ENV_NAMES or name.upper().startswith(_CHILD_ENV_PREFIXES)
    }
    return {**kept, **CHILD_ENV}


def _run(
    spec: dict[str, Any],
    out: Path,
    *,
    overlay: bytes | None,
    timeout: float | None,
    command: Sequence[str] | None,
) -> dict[str, Any]:
    """Run the child over `spec` (written beside `out`) and return its answer, or raise:
    a parts error as a plain `JoinError`, anything else as a retry. Its own files (spec,
    overlay, result) are removed on every path; the poster is the caller's to take."""
    spec_path = out.with_name(f"{out.name}.spec.json")
    result_path = out.with_name(f"{out.name}.result.json")
    overlay_path = out.with_name(f"{out.name}.overlay.png") if overlay is not None else None
    if overlay_path is not None:
        overlay_path.write_bytes(overlay)
    result_path.unlink(missing_ok=True)
    spec = {
        **spec,
        "overlay": None if overlay_path is None else str(overlay_path),
        "result": str(result_path),
    }
    spec.setdefault("threads", JOIN_CHILD_THREADS)
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    argv = [
        *(command or (sys.executable, "-m", "qualify_creative.video.join_child")),
        str(spec_path),
    ]
    try:
        done = subprocess.run(  # noqa: S603 — our own interpreter and module, no shell
            argv,
            env=child_env(),
            timeout=JOIN_CHILD_TIMEOUT_S if timeout is None else timeout,
            capture_output=True,
            check=False,
        )
    except subprocess.TimeoutExpired:  # `run` killed the child before raising
        raise _retry(  # noqa: B904
            "the join's child process timed out and was killed",
            counted=not WORKER_STOPPING.is_set(),
        )
    finally:
        for path in (spec_path, overlay_path):
            if path is not None:
                path.unlink(missing_ok=True)
    try:
        answer = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        answer = {}
    finally:
        result_path.unlink(missing_ok=True)
    tail = done.stderr.decode("utf-8", "replace")[-400:] if done.stderr else ""
    if done.returncode == EXIT_PARTS:
        raise JoinError(str(answer.get("error") or "the parts could not be joined"))
    if done.returncode != EXIT_OK or "frames" not in answer:
        raise _retry(
            f"the join's child process ended with {done.returncode}: "
            f"{answer.get('error') or tail or 'no result'}",
            counted=_lost_to_its_part(done.returncode),
        )
    return answer


def _take(path: Path) -> bytes | None:
    if not path.exists():
        return None
    data = path.read_bytes()
    path.unlink(missing_ok=True)
    return data


def join_in_child(
    clips: Sequence[JoinClip],
    *,
    out: Path,
    size: tuple[int, int],
    overlay: bytes | None = None,
    fps: int | Fraction = JOIN_FPS,
    threads: int | None = None,
    timeout: float | None = None,
    command: Sequence[str] | None = None,
) -> JoinedVideo:
    """`join_clips` with the same contract, run in a child process (see the module).
    `command` replaces the child's argv prefix (tests only)."""
    out = Path(out)
    poster_path = out.with_name(f"{out.name}.poster.jpg")
    spec: dict[str, Any] = {
        "mode": "join",
        "clips": [[str(c.path), c.start_s, c.end_s] for c in clips],
        "out": str(out),
        "size": list(size),
        "fps": str(Fraction(fps)),
        "poster": str(poster_path),
    }
    if threads is not None:
        spec["threads"] = threads
    try:
        answer = _run(spec, out, overlay=overlay, timeout=timeout, command=command)
        poster = _take(poster_path)
    finally:
        poster_path.unlink(missing_ok=True)
    return JoinedVideo(
        path=out,
        width=int(answer["width"]),
        height=int(answer["height"]),
        fps=Fraction(answer["fps"]),
        frames=int(answer["frames"]),
        duration_sec=float(answer["duration_sec"]),
        poster=poster,
    )


def segment_in_child(
    clip: JoinClip,
    *,
    out: Path,
    pcm_out: Path,
    size: tuple[int, int],
    overlay: bytes | None = None,
    fade_in: bool = False,
    fade_out: bool = False,
    poster: bool = False,
    fps: int | Fraction = JOIN_FPS,
    threads: int | None = None,
    timeout: float | None = None,
    command: Sequence[str] | None = None,
) -> JoinSegment:
    """`encode_segment` (ONE part) in a child process: the same boundary and outcomes
    as `join_in_child`. The parent runs one child per part, so the decoder and encoder
    memory of each part goes back to the OS before the next part starts."""
    out = Path(out)
    poster_path = out.with_name(f"{out.name}.poster.jpg")
    spec: dict[str, Any] = {
        "mode": "segment",
        "clip": [str(clip.path), clip.start_s, clip.end_s],
        "out": str(out),
        "pcm": str(pcm_out),
        "size": list(size),
        "fps": str(Fraction(fps)),
        "fade_in": fade_in,
        "fade_out": fade_out,
        "poster": str(poster_path) if poster else None,
    }
    if threads is not None:
        spec["threads"] = threads
    try:
        answer = _run(spec, out, overlay=overlay, timeout=timeout, command=command)
        picture = _take(poster_path) if poster else None
    finally:
        poster_path.unlink(missing_ok=True)
    return JoinSegment(
        path=out,
        pcm=Path(pcm_out),
        frames=int(answer["frames"]),
        samples=int(answer["samples"]),
        poster=picture,
    )


def _answer(spec: dict[str, Any], data: dict[str, Any]) -> None:
    Path(str(spec["result"])).write_text(json.dumps(data), encoding="utf-8")


def _work(spec: dict[str, Any]) -> dict[str, Any]:
    overlay = Path(spec["overlay"]).read_bytes() if spec.get("overlay") else None
    size = (int(spec["size"][0]), int(spec["size"][1]))
    threads = int(spec["threads"])
    if spec.get("mode") == "segment":
        path, start, end = spec["clip"]
        segment = encode_segment(
            JoinClip(Path(path), start_s=start, end_s=end),
            out=Path(spec["out"]),
            pcm_out=Path(spec["pcm"]),
            size=size,
            fps=Fraction(spec["fps"]),
            overlay=overlay,
            fade_in=bool(spec["fade_in"]),
            fade_out=bool(spec["fade_out"]),
            threads=threads,
            poster=bool(spec.get("poster")),
        )
        if segment.poster and spec.get("poster"):
            Path(spec["poster"]).write_bytes(segment.poster)
        return {"frames": segment.frames, "samples": segment.samples}
    joined = join_clips(
        [JoinClip(Path(p), start_s=start, end_s=end) for p, start, end in spec["clips"]],
        out=Path(spec["out"]),
        size=size,
        fps=Fraction(spec["fps"]),
        overlay=overlay,
        threads=threads,
    )
    if joined.poster:
        Path(spec["poster"]).write_bytes(joined.poster)
    return {
        "frames": joined.frames,
        "width": joined.width,
        "height": joined.height,
        "fps": str(joined.fps),
        "duration_sec": joined.duration_sec,
    }


def main(argv: Sequence[str]) -> int:
    """The child: do what the spec says, answer, exit."""
    spec = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    try:
        data = _work(spec)
    except JoinError as exc:
        _answer(spec, {"error": str(exc)})
        return EXIT_IO if _io_shaped(exc) else EXIT_PARTS
    except OSError as exc:
        _answer(spec, {"error": f"{type(exc).__name__}: {exc}"})
        return EXIT_IO
    _answer(spec, data)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
