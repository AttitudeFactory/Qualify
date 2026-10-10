"""Meta's `media_type` of a monitored media (QUA-146): the known formats, and what an
unknown one means.

`monitored_media.media_type` stores Meta's value VERBATIM, with no CHECK constraint
(migration 0049): Meta may add a format this code does not know yet, and that value must
be kept, not discarded or rewritten. This module is the one place that interprets it.
A stored value has exactly three possible readings:

- `None` — the format was never read (a row monitored before 0049 that is not a Reel,
  until the sync reads it once).
- a `MediaType` — one of the three formats Qualify knows.
- unrecognized — Meta sent something else. It stays in the column as received;
  `known_media_type` returns `None` for it and `is_unrecognized_media_type` is True, so a
  caller can never mistake it for "not read yet".

Matching is exact and case-sensitive, Meta's own spelling: `"video"` is unrecognized,
not `VIDEO`. Normalizing it would be rewriting what Meta said.
"""

from __future__ import annotations

from enum import StrEnum


class MediaType(StrEnum):
    """The formats of an Instagram media Qualify knows, spelled as Meta's Graph API
    returns them in `media_type`."""

    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    CAROUSEL_ALBUM = "CAROUSEL_ALBUM"


_KNOWN: frozenset[str] = frozenset(MediaType)


def known_media_type(raw: str | None) -> MediaType | None:
    """The `MediaType` for a stored value, or `None` when it was never read OR is not one
    Qualify knows — `is_unrecognized_media_type` tells those two apart. Never raises."""
    if raw is None or raw not in _KNOWN:
        return None
    return MediaType(raw)


def is_unrecognized_media_type(raw: str | None) -> bool:
    """True when Meta sent a value this code does not know (kept as is in the column)."""
    return raw is not None and raw not in _KNOWN
