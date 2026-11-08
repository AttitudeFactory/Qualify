"""A bounded, silent motion reference for the Seedance replication experiment.

Only the CDN URL in a server-held discovery card is accepted. No scraper, VLM or
paid generation is called here. The original is never used as an output piece.

R8 (founder, 2026-11-04): «Hacer uno parecido» for an idea of «Ideas para tus reels»
goes through `prepare_idea_reference(network, reel_id)`. It looks the video up itself, on
the server — the source the shared analysis stored in R2 (ADR 44 VE-04a, not purged yet),
else the reel's own CDN URL while it is fresh (`reel_analysis_source.url_is_stale`: read
under 20 h ago and not past the expiry the CDN signed) — and never takes a URL from the
client. Of the public R2 door it only calls `open_public` (static test).
"""

from __future__ import annotations

import io
import logging
import math
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
from qualify_creative.video.fit import FittedVideo, PyAvVideoFitter

if TYPE_CHECKING:
    from qualify_shared.objects.public import PublicObjectGate

logger = logging.getLogger(__name__)

MAX_BYTES = 80 * 1024 * 1024
REFERENCE_SECONDS = 5.0
# ModelArk Seedance 2.5 video requirements, verified 2026-10-27 (also measured live):
# https://docs.byteplus.com/en/docs/ModelArk/seedance-2-5
MIN_REFERENCE_PIXELS = 407696
#: The frame rates ModelArk takes in a reference video — 24–60 fps, BytePlus
#: CreateAsset (https://docs.byteplus.com/en/docs/ModelArk/create-asset-api), cited in
#: `docs/omnihuman-caras-reales-y-edicion-seedance.md`. A source outside it is re-timed
#: to the nearest end (m-24972160): 23.976 → 24 repeats at most one frame in 5 s, where
#: 30 would repeat one in four and add judder to the motion Seedance copies.
REFERENCE_FPS = (24, 60)
#: An MP4's average rate is measured from its timestamps, so 24 fps can read 23.99.
FPS_TOLERANCE = 0.05
#: One frame at 24 fps: a fitted reference longer than the cut plus this is mis-timed.
DURATION_TOLERANCE = 0.05
_SUFFIXES = {
    "instagram": ("cdninstagram.com", "fbcdn.net"),
    "tiktok": ("tiktokcdn.com", "tiktokcdn-us.com", "tiktokcdn-eu.com", "byteoversea.com"),
}


class ReelReferenceUnavailable(ValueError):
    """A safe message for the operator, without signed CDN URLs."""


def source_allowed(network: str, url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        return (
            parts.scheme == "https"
            and parts.port in (None, 443)
            and parts.username is None
            and parts.password is None
            and any(host == s or host.endswith("." + s) for s in _SUFFIXES.get(network, ()))
        )
    except ValueError:
        return False


def prepare_reference(
    network: str,
    url: str,
    *,
    client: httpx.Client | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> FittedVideo:
    """Fetch up to 80 MiB; normalize the first 5 s to H.264 without original audio.

    Redirects are refused, including redirects from a trusted CDN to another host.
    The bounded reference keeps its proportions, at most 1280 px on its longer side,
    with ModelArk's minimum pixel count.
    """
    if not source_allowed(network, url):
        raise ReelReferenceUnavailable("Este reel no tiene un video de referencia disponible.")
    if client is None:
        with httpx.Client(timeout=_timeout(READ_TIMEOUT), follow_redirects=False) as owned:
            return prepare_reference(network, url, client=owned, clock=clock, sleep=sleep)
    return normalize_reference(_download(url, client, clock, sleep))


#: m-24975868: a TikTok download stalled ~45 s behind a per-read timeout with no total cap.
#: Now each attempt has a wall-clock cap, the whole call a budget (the button must not hang
#: much past a minute), and one retry covers a transient network failure. The whole file is
#: still downloaded — never a Range prefix: many MP4s keep their `moov` atom at the end.
ATTEMPT_SECONDS = 30.0
TOTAL_SECONDS = 55.0
#: httpx timeouts apply per phase (connect / each read), so the cap is only checked between
#: reads: an attempt can run one read past its deadline. Each deadline therefore leaves
#: `READ_TIMEOUT` of the budget free, which makes `TOTAL_SECONDS` a real bound.
READ_TIMEOUT = 5.0
RETRY_BACKOFF = 1.0
#: A retry with less time than this for its own cap could not download a reel; not attempted.
MIN_RETRY_SECONDS = 5.0
#: Transient failures worth one more try (incl. a connection reset mid-body); an HTTP status
#: (403/404/5xx) is never retried.
_RETRYABLE = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)
_UNREADABLE = "No pudimos leer el video. Inténtalo de nuevo."


class _AttemptTimedOut(Exception):
    """An attempt ran past its wall-clock cap while the body was still arriving."""


def _timeout(seconds: float) -> httpx.Timeout:
    return httpx.Timeout(seconds, connect=min(seconds, READ_TIMEOUT))


def _download(
    url: str, client: httpx.Client, clock: Callable[[], float], sleep: Callable[[float], None]
) -> bytes:
    """The body of `url`, within `TOTAL_SECONDS`, retried once on a transient failure.
    Failures are logged with the error's class and the URL's host only (signed link).

    Bound: every blocking phase waits at most `timeout` (<= what the budget has left) and
    a new one only starts before `deadline`, which sits `READ_TIMEOUT` short of the budget's
    end — so the call returns or raises by `TOTAL_SECONDS`."""
    started = clock()
    attempt = 0
    while True:
        attempt += 1
        remaining = TOTAL_SECONDS - (clock() - started)
        cap = min(ATTEMPT_SECONDS, remaining - READ_TIMEOUT)
        timeout = min(READ_TIMEOUT, remaining)
        try:
            return _attempt(url, client, clock, clock() + cap, timeout)
        except ReelReferenceUnavailable:
            raise
        except (*_RETRYABLE, _AttemptTimedOut) as error:
            elapsed = clock() - started
            left = TOTAL_SECONDS - elapsed - RETRY_BACKOFF - READ_TIMEOUT
            retry = attempt == 1 and left >= MIN_RETRY_SECONDS
            _log_failure(url, error, attempt, elapsed, retry)
            if not retry:
                raise ReelReferenceUnavailable(_UNREADABLE) from None
            sleep(RETRY_BACKOFF)
        except httpx.HTTPError as error:
            _log_failure(url, error, attempt, clock() - started, False)
            raise ReelReferenceUnavailable(_UNREADABLE) from None


def _attempt(
    url: str, client: httpx.Client, clock: Callable[[], float], deadline: float, timeout: float
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    with client.stream("GET", url, follow_redirects=False, timeout=_timeout(timeout)) as response:
        if response.status_code != 200:
            logger.warning(
                "reels replicate: download refused host=%s status=%s",
                _host(url),
                response.status_code,
            )
            raise ReelReferenceUnavailable(
                "El video de este reel ya no está disponible. Elige otra idea."
            )
        for chunk in response.iter_bytes():
            if clock() > deadline:
                raise _AttemptTimedOut
            size += len(chunk)
            if size > MAX_BYTES:
                raise ReelReferenceUnavailable("El video es demasiado grande para usarlo aquí.")
            chunks.append(chunk)
    return b"".join(chunks)


def _log_failure(url: str, error: Exception, attempt: int, elapsed: float, retry: bool) -> None:
    # never the URL nor the error's message (either may carry the signed query)
    logger.warning(
        "reels replicate: download failed host=%s error=%s attempt=%d elapsed=%.1fs retry=%s",
        _host(url),
        type(error).__name__,
        attempt,
        elapsed,
        retry,
    )


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "?").lower()
    except ValueError:
        return "?"


def normalize_reference(data: bytes) -> FittedVideo:
    """The first 5 s of `data` as a reference ModelArk accepts: H.264, no audio, its own
    aspect (`reference_size`) and a frame rate inside `REFERENCE_FPS`. A source outside
    that range is re-timed, not refused (m-24972160: TikTok records at 23.976 fps): a
    slower one comes out at 24 fps, a faster one at 60. Only what cannot be made into
    such a reference — no video, an aspect ModelArk refuses, under 4 s — is refused."""
    import av  # noqa: PLC0415 · only this experiment needs to decode a reel

    low, high = REFERENCE_FPS
    try:
        with av.open(io.BytesIO(data)) as source:
            stream = source.streams.video[0]
            width, height = stream.codec_context.width, stream.codec_context.height
            size = reference_size(width, height)
        fitted = PyAvVideoFitter().fit(
            data,
            size=size,
            max_seconds=REFERENCE_SECONDS,
            keep_audio=False,
            fps_range=REFERENCE_FPS,
        )
        if fitted.duration_sec < 4:
            raise ValueError("an edited reference must last at least 4 s")
        if fitted.duration_sec > REFERENCE_SECONDS + DURATION_TOLERANCE:
            raise ValueError("the fitted reference is longer than its cut (mis-timed source)")
        # the rate checked is the fitted file's, as ModelArk will read it
        with av.open(io.BytesIO(fitted.data)) as result:
            rate = result.streams.video[0].average_rate
        if rate is None or not low - FPS_TOLERANCE <= float(rate) <= high + FPS_TOLERANCE:
            raise ValueError(f"the fitted reference came out at {rate} fps")
        return fitted
    except Exception:
        raise ReelReferenceUnavailable(
            "No pudimos preparar este video como referencia. Prueba con otro reel."
        ) from None


def reference_size(width: int, height: int) -> tuple[int, int]:
    """Even dimensions preserving aspect, within ModelArk's reference-video limits."""
    if width <= 0 or height <= 0 or not 0.4 <= width / height <= 2.5:
        raise ValueError("reference aspect ratio outside ModelArk's limits")
    scale = max(
        min(1.0, 1280 / max(width, height)),
        math.sqrt(MIN_REFERENCE_PIXELS / (width * height)),
        300 / min(width, height),
    )
    return math.ceil(width * scale / 2) * 2, math.ceil(height * scale / 2) * 2


#: What the owner reads when an idea's video can no longer be used (no copy, link too old).
#: Shown on «Ideas para tus reels» (UI-1, m-24921075: no «replicar» in client copy).
#: The same sentence as the card's (`Qualify/reels_ideas_vm.CANNOT_REPLICATE`, UX review).
IDEA_VIDEO_GONE = (
    "Este video ya no está disponible para hacer uno parecido. Puedes verlo para "
    "inspirarte o elegir otra idea."
)


def prepare_idea_reference(network: str, reel_id: str) -> FittedVideo:
    """«Hacer uno parecido» (ex «Replicar con mi marca») for an idea: the source of the
    reel that the shared analysis stored in R2 (its first 5 s), else the reel's CDN video
    while its link is fresh — both looked up here by `(network, reel_id)`; a URL from the
    client is never used. `ReelReferenceUnavailable` with a plain sentence when neither is there."""
    stored_key, fresh_url = _idea_video(network, reel_id)
    if stored_key is not None:
        data = b""
        try:
            with _public_gate().open_public(stored_key) as body:
                data = body.read()
        except Exception as error:  # noqa: BLE001 — a missing copy falls back to the link
            # never the URL nor the key's bucket: the reel and the kind of failure
            logger.warning(
                "reels replicate: stored source unreadable network=%s reel_id=%s error=%s",
                network,
                reel_id,
                type(error).__name__,
            )
        if data:
            return normalize_reference(data)
    if fresh_url is not None:
        return prepare_reference(network, fresh_url)
    raise ReelReferenceUnavailable(IDEA_VIDEO_GONE)


def _idea_video(network: str, reel_id: str) -> tuple[str | None, str | None]:
    """`(the key of a stored, not yet purged source, a fresh CDN URL)`, read from the two
    global tables (0117, 0119) through the tenant-less door: they belong to no business,
    so no tenant is needed (`global_session`, pinned by a static test)."""
    from qualify_shared.db.session import global_session  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    # imported on use: `reel_analysis_source` imports this module (`source_allowed`)
    from qualify_api.referentes.reel_analysis_source import url_is_stale  # noqa: PLC0415

    params = {"network": network, "reel_id": reel_id}
    with global_session() as session:
        stored = session.scalar(
            text(
                "SELECT source_key FROM public_reel_analyses WHERE network = :network "
                "AND post_id = :reel_id AND source_key IS NOT NULL "
                "AND source_purged_at IS NULL ORDER BY analysis_version DESC LIMIT 1"
            ),
            params,
        )
        reel = session.execute(
            text(
                "SELECT video_url, video_url_at FROM public_reels "
                "WHERE network = :network AND reel_id = :reel_id"
            ),
            params,
        ).first()
    fresh = None
    if reel is not None and reel.video_url and reel.video_url_at is not None:
        if not url_is_stale(str(reel.video_url), reel.video_url_at, datetime.now(UTC)):
            fresh = str(reel.video_url)
    return (str(stored) if stored else None), fresh


def _public_gate() -> PublicObjectGate:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.public import PublicObjectGate  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    return PublicObjectGate(R2ObjectStore(R2Settings.from_env()))
