"""Getting a public reel's video to disk, safely (ADR 44, m-24921056 VE-04a).

The signed CDN URL is UNTRUSTED input — since 0119 the screen may insert it — so:

- **Only the network's own CDN hosts** (`reel_reference.source_allowed`: https, port 443,
  no credentials in the URL, a host under the network's CDN suffixes) — nothing internal,
  nothing else. **No redirects**: a 3xx, even to another CDN host, is refused.
- **Bounded**: `Content-Length` over the cap is refused before reading; the body is
  streamed in 1 MiB chunks to a temporary FILE (never held whole in memory), hashed on
  the fly (sha256, provenance) and cut off past 80 MiB; a partial file is removed.
- **Never logged**: errors carry a stable code and, at most, the host — the signed URL
  stays out of every log line (RN3).

Then `remux_video_only` copies the video stream's packets — no decode, no re-encode, no
audio — up to 60 s into a new MP4 (§13.2: the `edit` window is re-encoded by `cut_window`
anyway, so normalizing the whole source would be CPU spent for nothing), and reads the
facts the row records. A source outside Seedance's aspect limits, or at a frame rate the
cut cannot bring into Seedance's 24–60 fps unnoticed (`_EDIT_FPS`), is still analysed; it
is only marked `edit_eligible = false` (V13). 23.976 fps is eligible: `cut_window` re-times
the window to 24 (m-24973444).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from fractions import Fraction
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from qualify_api.referentes.reel_analysis_types import (
    ERROR_SOURCE_TOO_LARGE,
    ERROR_SOURCE_UNAVAILABLE,
    ERROR_SOURCE_UNREADABLE,
)
from qualify_api.referentes.reel_reference import source_allowed

MAX_SOURCE_BYTES = 80 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
MAX_ANALYSED_SECONDS = 60.0
#: A signed CDN URL lives ~24 h (TikTok) to ~33 h (Instagram); past 20 h it is not tried.
URL_MAX_AGE = timedelta(hours=20)
#: Per phase (connect / each read), like every httpx timeout in this repo.
TIMEOUT_SECONDS = 20.0
# Seedance's reference-video limits (`reel_reference.py`): only the `edit` mode needs them.
# The frame rate is the SOURCE's: `cut_window` writes every «Igual al original» window at
# 24-60 fps (`cut.EDIT_FPS_RANGE`, m-24973444), so a source is eligible when that re-timing
# stays invisible. Only the 23.976 family enters below 24 (TikTok's rate: one repeated
# frame every ~42 s); 23.0-23.8 stays ineligible, conservatively. Above 60, up to the
# 120 fps `cut` still reads as a real rate (re-timed down to 60).
_EDIT_FPS = (23.9, 120.0)
_EDIT_ASPECT = (0.4, 2.5)


class SourceError(Exception):
    """The source cannot be used. `code` is one of 0119's error codes; `retryable` says
    whether trying again later could help (a 5xx or a timeout), never for a refusal."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class Downloaded:
    sha256: str
    size: int


@dataclass(frozen=True)
class RemuxedSource:
    source_seconds: float
    width: int
    height: int
    fps: float
    covered_from_s: float
    covered_to_s: float
    edit_eligible: bool


def url_host(url: str) -> str:
    """The host only — the one part of a signed URL safe to log."""
    try:
        return (urlsplit(url).hostname or "?").lower()
    except ValueError:
        return "?"


#: TikTok's CDN signs its expiry as a PATH segment, not a query parameter: 8 hex chars of
#: unix seconds (`…/6af12bc8/video/tos/…`, ~24 h after the read; observed 2026-11-08 on
#: TikTok 7705422594442284301, m-24975868). Other path segments can be hex too (object ids,
#: hashes), so only an 8-char one whose value lands within a week of `now` counts.
_TIKTOK_HOSTS = ("tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com", "byteoversea.com")
_HEX_EXPIRY_WINDOW = timedelta(days=7)
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def url_expires_at(url: str, now: datetime | None = None) -> datetime | None:
    """The expiry a CDN signs into its own URL, when it does: Instagram/Facebook `oe`
    (hex epoch seconds), TikTok `x-expires` / `expire` (decimal), else — on a TikTok CDN
    host — the first 8-hex-char path segment that decodes to within 7 days of `now`
    (default: the current time). None when absent."""
    try:
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    try:
        if "oe" in query:
            return datetime.fromtimestamp(int(query["oe"][0], 16), UTC)
        for name in ("x-expires", "expire"):
            if name in query:
                return datetime.fromtimestamp(int(query[name][0]), UTC)
    except (ValueError, OverflowError, OSError):
        return None
    if any(host == s or host.endswith("." + s) for s in _TIKTOK_HOSTS):
        return _tiktok_path_expiry(parts.path, now or datetime.now(UTC))
    return None


def _tiktok_path_expiry(path: str, now: datetime) -> datetime | None:
    """The first 8-hex-char segment of `path` that is a plausible expiry around `now`."""
    for segment in path.split("/"):
        if len(segment) != 8 or not _HEX_DIGITS.issuperset(segment):
            continue
        expires = datetime.fromtimestamp(int(segment, 16), UTC)
        if abs(expires - now) <= _HEX_EXPIRY_WINDOW:
            return expires
    return None


def url_is_stale(url: str, read_at: datetime, now: datetime) -> bool:
    """Too old to try: read more than 20 h ago, or past the expiry the CDN signed."""
    if now - read_at > URL_MAX_AGE:
        return True
    expires = url_expires_at(url, now)
    return expires is not None and expires <= now


def download_source(
    network: str,
    url: str,
    dest: Path,
    *,
    client: httpx.Client,
    max_bytes: int = MAX_SOURCE_BYTES,
    chunk_bytes: int = CHUNK_BYTES,
) -> Downloaded:
    """Stream `url` into `dest` (created/truncated). On any failure `dest` is removed and
    a `SourceError` raised; nothing is ever followed off the CDN."""
    if not source_allowed(network, url):
        raise SourceError(ERROR_SOURCE_UNAVAILABLE, "the URL is not on this network's CDN")
    digest = hashlib.sha256()
    written = 0
    try:
        with client.stream("GET", url, follow_redirects=False) as response:
            status = response.status_code
            if 300 <= status < 400:
                raise SourceError(ERROR_SOURCE_UNAVAILABLE, "the CDN answered a redirect")
            if status == 429 or status >= 500:
                raise SourceError(
                    ERROR_SOURCE_UNAVAILABLE, f"the CDN answered {status}", retryable=True
                )
            if status != 200:
                raise SourceError(ERROR_SOURCE_UNAVAILABLE, f"the CDN answered {status}")
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise SourceError(ERROR_SOURCE_TOO_LARGE, "the video is over the size cap")
            with dest.open("wb") as out:
                for chunk in response.iter_bytes(chunk_bytes):
                    written += len(chunk)
                    if written > max_bytes:
                        raise SourceError(ERROR_SOURCE_TOO_LARGE, "the video is over the size cap")
                    digest.update(chunk)
                    out.write(chunk)
    except SourceError:
        dest.unlink(missing_ok=True)
        raise
    except httpx.HTTPError:
        dest.unlink(missing_ok=True)
        raise SourceError(ERROR_SOURCE_UNAVAILABLE, "the download failed", retryable=True) from None
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    if written == 0:
        dest.unlink(missing_ok=True)
        raise SourceError(ERROR_SOURCE_UNREADABLE, "the CDN sent an empty body")
    return Downloaded(sha256=digest.hexdigest(), size=written)


def _rate(stream: object) -> Fraction | None:
    for name in ("average_rate", "guessed_rate", "base_rate"):
        value = getattr(stream, name, None)
        if value and 1 <= value <= 240:
            return Fraction(value)
    return None


def remux_video_only(
    src: Path, dst: Path, *, max_seconds: float = MAX_ANALYSED_SECONDS
) -> RemuxedSource:
    """Copy the first video stream's packets of `src` into `dst` (MP4), up to `max_seconds`
    from its first packet; no audio, no decode except one frame to prove it plays."""
    import av  # noqa: PLC0415 — lazy, like every PyAV use

    try:
        with av.open(os.fspath(src)) as inp:
            if not inp.streams.video:
                raise SourceError(ERROR_SOURCE_UNREADABLE, "the file has no video stream")
            stream = inp.streams.video[0]
            width = int(stream.codec_context.width or 0)
            height = int(stream.codec_context.height or 0)
            rate = _rate(stream)
            header = None
            if stream.duration is not None and stream.time_base is not None:
                header = float(stream.duration * stream.time_base)
            elif inp.duration is not None:
                header = inp.duration / 1_000_000
            first = last = None
            with av.open(os.fspath(dst), "w", format="mp4") as out:
                copy = out.add_stream_from_template(stream)
                for packet in inp.demux(stream):
                    if packet.dts is None or packet.size == 0:
                        continue
                    at = float(packet.dts * stream.time_base)
                    if first is None:
                        first = at
                    if at - first >= max_seconds:
                        break
                    if packet.pts is not None:
                        end = float(packet.pts * stream.time_base) - first
                        if packet.duration:
                            end += float(packet.duration * stream.time_base)
                        last = end if last is None else max(last, end)
                    packet.stream = copy
                    out.mux(packet)
            if first is None or width <= 0 or height <= 0:
                raise SourceError(ERROR_SOURCE_UNREADABLE, "the video has no frames")
        with av.open(os.fspath(dst)) as check:
            next(check.decode(video=0))
    except SourceError:
        dst.unlink(missing_ok=True)
        raise
    except (av.error.FFmpegError, StopIteration, ValueError) as error:
        dst.unlink(missing_ok=True)
        raise SourceError(ERROR_SOURCE_UNREADABLE, f"the video cannot be read: {error}") from None
    fps = float(rate) if rate else 0.0
    covered = min(max_seconds, last or 0.0)
    if covered <= 0:
        covered = min(max_seconds, 1.0 / fps if fps else 0.001)
    seconds = header if header and header > 0 else covered
    edit = (
        _EDIT_FPS[0] <= fps <= _EDIT_FPS[1] and _EDIT_ASPECT[0] <= width / height <= _EDIT_ASPECT[1]
    )
    return RemuxedSource(
        source_seconds=round(seconds, 3),
        width=width,
        height=height,
        fps=round(fps, 3) if fps else 30.0,
        covered_from_s=0.0,
        covered_to_s=round(covered, 3),
        edit_eligible=edit,
    )


__all__ = [
    "MAX_ANALYSED_SECONDS",
    "MAX_SOURCE_BYTES",
    "URL_MAX_AGE",
    "Downloaded",
    "RemuxedSource",
    "SourceError",
    "download_source",
    "remux_video_only",
    "url_expires_at",
    "url_host",
    "url_is_stale",
]
