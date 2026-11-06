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
                    "El video de este reel ya no está disponible. Elige otra idea."
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
