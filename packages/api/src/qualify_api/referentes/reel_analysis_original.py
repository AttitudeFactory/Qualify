"""The stored copy of an analysed reel, read by byte range for step 2 of «Tu video,
parte por parte» (m-24992893).

Each part of the plan covers a stretch of the original reel (its cuts' `start_s` to
`end_s`). The screen plays THAT stretch from the copy the analysis stored in the public
door (`public/reel-analyses/<network>/<post id>/<analysis id>/source/source.mp4`, VE-04a)
— one URL per analysis, shared by every part, with `#t=start,end` / `currentTime` per
part. A browser only seeks inside a video it can ask by `Range`, so this module answers
a size and a byte range, never the whole object at once:

- `source_size(network, post_id, analysis_id)` — the copy's size in bytes, or None;
- `read_source_range(network, post_id, analysis_id, start, end)` — bytes `start..end`
  (inclusive), or None.

Both REBUILD the key from its parts through the door's own builder (`reel_source_key`),
never take it from the request, so a request can only ever name the source of an
analysis folder; the route (`Qualify/avatar_proxy.part_source`) also checks the screen's
signature before any read. R2 is read through this module's own client, bounded for a
request path (one attempt, short timeouts): a slow R2 costs the player its picture, never
a held thread. The size is remembered per key for the process (the copy never changes
under its key; a purged copy then reads as a failed range, i.e. None).

Of the public door this module calls `public_size` and `open_public_range` only (static
test). It writes nothing, charges nobody and calls no vendor. The copy lives 30 days
(`reel_analysis_worker.SOURCE_RETENTION`, purged by `reel_retention`); after that
`ReelAnalysis.source_available` is False and the screen asks for nothing.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from uuid import UUID

from qualify_shared.objects.config import R2ConfigurationError
from qualify_shared.objects.gate import ObjectNotFound
from qualify_shared.objects.public import (
    SOURCE_CONTENT_TYPE,
    PublicKeyViolation,
    PublicObjectGate,
    reel_source_key,
)

logger = logging.getLogger(__name__)

#: The route's R2 reads (a `<video>` range request): seconds to connect and to read.
ROUTE_CONNECT_SECONDS = 2.0
ROUTE_READ_SECONDS = 8.0
#: Sizes remembered (one per analysis whose step 2 is open; a few bytes each).
SIZE_CACHE_ENTRIES = 512


def source_key(network: str, post_id: str, analysis_id: UUID) -> str | None:
    """The door's key of an analysis' stored source, or None when any part is not one
    the door keys (an unknown network, a made-up post id)."""
    try:
        return reel_source_key(network, post_id, analysis_id)
    except (PublicKeyViolation, ValueError):
        return None


_route: PublicObjectGate | None = None
#: boto3's default session is not thread-safe: the door is built once, under this lock.
_route_guard = threading.Lock()
_sizes: OrderedDict[str, int] = OrderedDict()
_sizes_guard = threading.Lock()


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


def _log_miss(what: str, network: str, post_id: str, analysis_id: UUID, exc: Exception) -> None:
    logger.warning(
        "reel source %s %s/%s/%s unreadable from R2: %s",
        what,
        network,
        post_id,
        analysis_id,
        type(exc).__name__,
    )


def source_size(
    network: str,
    post_id: str,
    analysis_id: UUID,
    *,
    gate: PublicObjectGate | None = None,
) -> int | None:
    """The stored source's size in bytes, or None: a source the door cannot key, no such
    object (never stored, or purged after 30 days), R2 not configured or unreachable.
    Blocking: the route runs it in a thread."""
    key = source_key(network, post_id, analysis_id)
    if key is None:
        return None
    with _sizes_guard:
        if key in _sizes:
            _sizes.move_to_end(key)
            return _sizes[key]
    try:
        size = int((gate or _route_gate()).public_size(key))
    except (ObjectNotFound, KeyError):
        return None
    except R2ConfigurationError:
        logger.debug("reel source: no R2 configured")
        return None
    except Exception as exc:  # noqa: BLE001 — a player must never break the page
        _log_miss("size", network, post_id, analysis_id, exc)
        return None
    with _sizes_guard:
        _sizes[key] = size
        while len(_sizes) > SIZE_CACHE_ENTRIES:
            _sizes.popitem(last=False)
    return size


def read_source_range(
    network: str,
    post_id: str,
    analysis_id: UUID,
    start: int,
    end: int,
    *,
    gate: PublicObjectGate | None = None,
) -> bytes | None:
    """Bytes `start..end` (inclusive) of the stored source, or None (as `source_size`).
    The caller clamps the range to the size and to its per-response cap. Blocking."""
    key = source_key(network, post_id, analysis_id)
    if key is None or start < 0 or end < start:
        return None
    try:
        with (gate or _route_gate()).open_public_range(key, start, end) as body:
            return body.read()
    except (ObjectNotFound, KeyError):
        _forget(key)
        return None
    except R2ConfigurationError:
        logger.debug("reel source: no R2 configured")
        return None
    except Exception as exc:  # noqa: BLE001 — a player must never break the page
        _log_miss("range", network, post_id, analysis_id, exc)
        return None


def _forget(key: str) -> None:
    """A copy gone from R2 (purged) is not remembered as still there."""
    with _sizes_guard:
        _sizes.pop(key, None)


def clear_size_cache() -> None:
    """Tests: forget every remembered size."""
    with _sizes_guard:
        _sizes.clear()


__all__ = [
    "SOURCE_CONTENT_TYPE",
    "clear_size_cache",
    "read_source_range",
    "source_key",
    "source_size",
]
