"""One frame of a reel analysis, for the parts list's thumbnails (UI-3, m-24921077).

Step 2 of «Tu video, parte por parte» shows each part with a 72 px picture of the cuts
it comes from. Those pictures already exist: the analysis (VE-04a/c) stored a few JPEG
frames per cut in the public R2 door (`…/<analysis id>/frames/NN-N.jpg`,
`ShotAnalysis.frame_keys`). This module only READS them — the same shape as the idea
covers (`reel_covers.open_cover`):

- `representative_frame(analysis, shot_indexes)` — PURE: which stored frame stands for a
  part (its cuts' frames in time order, the middle one; the first when there is one),
  as a `FramePick` the screen signs (`Qualify/avatar_proxy.part_thumbnail_path`). None
  when the cuts have no frame or the frames were purged (`frames_available`).
- `open_frame(network, post_id, analysis_id, frame)` — the frame's bytes for the route,
  or None. The key is REBUILT here from its parts through the door's own builder
  (`reel_frame_key`), never taken from the request, so a request can only ever name a
  frame of an analysis folder; the route also checks the screen's signature before any
  read. Reads R2 through its own client, bounded for a request path (one attempt, short
  timeouts): a slow R2 costs the row its placeholder, never a held thread.

Of the public door this module calls `open_public` only (static test). It writes
nothing, charges nobody and calls no vendor.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from qualify_shared.objects.config import R2ConfigurationError
from qualify_shared.objects.gate import ObjectNotFound
from qualify_shared.objects.public import (
    FRAME_CONTENT_TYPE,
    PublicKeyViolation,
    PublicObjectGate,
    reel_frame_key,
)

from qualify_api.referentes.reel_analysis_types import ReelAnalysis

logger = logging.getLogger(__name__)

#: `NN-N` — the stored frame's name without `.jpg`: cut 00-99, frame 0-99 within it.
FRAME_NAME_RE = re.compile(r"([0-9]{2})-([0-9]{1,2})")
_KEY_TAIL_RE = re.compile(r"/frames/([0-9]{2}-[0-9]{1,2})\.jpg")

#: The route's R2 read (an `<img>` request): seconds to connect and to read, one attempt.
ROUTE_CONNECT_SECONDS = 2.0
ROUTE_READ_SECONDS = 5.0


@dataclass(frozen=True)
class FramePick:
    """One stored frame, by the parts its key is rebuilt from (never the key itself)."""

    network: str
    post_id: str
    analysis_id: UUID
    #: `NN-N`, as in `…/frames/NN-N.jpg`.
    frame: str


def frame_name(key: str, network: str, post_id: str, analysis_id: UUID) -> str | None:
    """`NN-N` when `key` is exactly a frame of THIS analysis (the door's builder gives the
    same key back), else None — a key of another analysis or reel is never picked."""
    match = _KEY_TAIL_RE.search(key)
    if match is None:
        return None
    name = match.group(1)
    if frame_key(network, post_id, analysis_id, name) != key:
        return None
    return name


def frame_key(network: str, post_id: str, analysis_id: UUID, frame: str) -> str | None:
    """The door's key of frame `NN-N` of an analysis, or None when any part is not one
    the door keys (an unknown network, a made-up post id, an out-of-range position)."""
    match = FRAME_NAME_RE.fullmatch(frame)
    if match is None:
        return None
    try:
        return reel_frame_key(
            network, post_id, analysis_id, int(match.group(1)), int(match.group(2))
        )
    except (PublicKeyViolation, ValueError):
        return None


def representative_frame(analysis: ReelAnalysis, shot_indexes: Sequence[int]) -> FramePick | None:
    """The frame that stands for a part made of `shot_indexes` (the part's cuts, as in
    `PartRef.shot_indexes` / `VideoPartPlan.shot_indexes`): every stored frame of those
    cuts in time order, the middle one (the first when there is one). None when the
    frames were purged, the cuts are unknown or none kept a frame — the row then shows its
    placeholder. Pure."""
    if not analysis.frames_available:
        return None
    wanted = set(shot_indexes)
    timed: list[tuple[float, int, str]] = []
    for shot in sorted(analysis.shots, key=lambda s: s.shot_index):
        if shot.shot_index not in wanted:
            continue
        times = shot.frame_times_s if len(shot.frame_times_s) == len(shot.frame_keys) else ()
        for position, key in enumerate(shot.frame_keys):
            name = frame_name(key, analysis.network, analysis.post_id, analysis.id)
            if name is None:
                continue
            at = times[position] if times else shot.start_s
            timed.append((at, len(timed), name))
    if not timed:
        return None
    timed.sort()
    return FramePick(analysis.network, analysis.post_id, analysis.id, timed[len(timed) // 2][2])


_route: PublicObjectGate | None = None
#: boto3's default session is not thread-safe: the door is built once, under this lock.
_route_guard = threading.Lock()


def _route_gate() -> PublicObjectGate:
    """The route's door over the real R2 bucket: built once, bounded, no retry
    (`R2ConfigurationError` when the environment has no R2)."""
    global _route
    with _route_guard:
        if _route is None:
            from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
            from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

            settings = R2Settings.from_env().bounded(
                connect=ROUTE_CONNECT_SECONDS, read=ROUTE_READ_SECONDS, attempts=1
            )
            _route = PublicObjectGate(R2ObjectStore(settings))
        return _route


def open_frame(
    network: str,
    post_id: str,
    analysis_id: UUID,
    frame: str,
    *,
    gate: PublicObjectGate | None = None,
) -> bytes | None:
    """The stored frame `NN-N` of an analysis, or None: a frame the door cannot key, no
    such object (never stored, or purged after 30 days), R2 not configured or
    unreachable. Blocking: the route runs it in a thread."""
    key = frame_key(network, post_id, analysis_id, frame)
    if key is None:
        return None
    try:
        with (gate or _route_gate()).open_public(key) as body:
            return body.read()
    except (ObjectNotFound, KeyError):
        return None
    except R2ConfigurationError:
        logger.debug("reel frames: no R2 configured")
        return None
    except Exception as exc:  # noqa: BLE001 — a picture must never break the page
        logger.warning(
            "reel frame %s/%s/%s/%s unreadable from R2: %s",
            network,
            post_id,
            analysis_id,
            frame,
            type(exc).__name__,
        )
        return None


__all__ = [
    "FRAME_CONTENT_TYPE",
    "FRAME_NAME_RE",
    "FramePick",
    "frame_key",
    "frame_name",
    "open_frame",
    "representative_frame",
]
