"""A bounded, silent motion reference for the Seedance replication experiment.

Only the CDN URL in a server-held discovery card is accepted. No scraper, VLM or
paid generation is called here. The original is never used as an output piece.
"""

from __future__ import annotations

import io
import math
from urllib.parse import urlsplit

import httpx
from qualify_creative.video.fit import FittedVideo, PyAvVideoFitter

MAX_BYTES = 80 * 1024 * 1024
REFERENCE_SECONDS = 5.0
# ModelArk Seedance 2.5 video requirements, verified 2026-10-27 (also measured live):
# https://docs.byteplus.com/en/docs/ModelArk/seedance-2-5
MIN_REFERENCE_PIXELS = 407696
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


def prepare_reference(network: str, url: str, *, client: httpx.Client | None = None) -> FittedVideo:
    """Fetch up to 80 MiB; normalize the first 5 s to H.264 without original audio.

    Redirects are refused, including redirects from a trusted CDN to another host.
    The bounded reference keeps its proportions, at most 1280 px on its longer side,
    with ModelArk's minimum pixel count.
    """
    if not source_allowed(network, url):
        raise ReelReferenceUnavailable("Este reel no tiene un video de referencia disponible.")
    if client is None:
        with httpx.Client(timeout=20, follow_redirects=False) as owned:
            return prepare_reference(network, url, client=owned)
    chunks: list[bytes] = []
    size = 0
    try:
        with client.stream("GET", url, follow_redirects=False) as response:
            if response.status_code != 200:
                raise ReelReferenceUnavailable(
                    "El video de este reel ya no está disponible. Actualiza los reels y reintenta."
                )
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ReelReferenceUnavailable("El video es demasiado grande para usarlo aquí.")
                chunks.append(chunk)
    except httpx.HTTPError:
        raise ReelReferenceUnavailable("No pudimos leer el video. Inténtalo de nuevo.") from None
    return normalize_reference(b"".join(chunks))


def normalize_reference(data: bytes) -> FittedVideo:
    import av  # noqa: PLC0415 · only this experiment needs to decode a reel

    try:
        with av.open(io.BytesIO(data)) as source:
            stream = source.streams.video[0]
            width, height = stream.codec_context.width, stream.codec_context.height
            rate = stream.average_rate or stream.guessed_rate
            if rate is None or not 24 <= float(rate) <= 60:
                raise ValueError("reference frame rate outside ModelArk's 24–60 fps")
            size = reference_size(width, height)
        fitted = PyAvVideoFitter().fit(
            data, size=size, max_seconds=REFERENCE_SECONDS, keep_audio=False
        )
        if fitted.duration_sec < 4:
            raise ValueError("an edited reference must last at least 4 s")
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
