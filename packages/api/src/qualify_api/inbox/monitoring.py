"""The monitoring lifecycle of one published media (QUA-149): the 14-day rule, in one place.

Business rule (confirmed 2026-10-09, QUA-149): a media is monitored for **14 days from
its publication on Instagram**. When that window ends it stops being synced — no more
Meta calls for it — while everything already stored about it (its comments, their
sentiment and reply drafts, and its caption/permalink) stays. It can never be turned on
again once outside the window. The same rule applies to every format (QUA-146 D2), so
nothing here knows about Reels, images or carousels.

Every caller asks THIS module, never re-derives the comparison:

- `is_within_window` — may this media be turned on, and is it still synced?
- `window_start` — the same cutoff, for SQL (`media_posted_at >= :cutoff`), so the query
  that picks what to sync and the Python check can never disagree on the boundary.
- `effective_state` — what the UI shows and what the backend does, from one function.

The window is measured from Meta's own `timestamp` of the media, read server-side; a
client-supplied date is never trusted.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Final

MONITORING_WINDOW: Final = timedelta(days=14)


class MonitoringState(StrEnum):
    """The effective monitoring state of one media, as the UI must show it.

    - `ACTIVE` — monitored and inside the window: it is synced ("Monitoreado").
    - `EXPIRED` — was monitored, the window ended: not synced any more ("No monitoreado ·
      vencido"). Its history is kept.
    - `INACTIVE` — monitoring off (turned off by the user, or the media was confirmed
      deleted on Instagram): not synced ("No monitoreado").
    """

    ACTIVE = "active"
    EXPIRED = "expired"
    INACTIVE = "inactive"


class MetadataFetchError(StrEnum):
    """Why reading a media's metadata from Meta failed, recorded on `monitored_media.
    metadata_error` so the attempt can be retried later without losing what is already
    stored. A media confirmed DELETED is not one of these: that is evidence, and it turns
    monitoring off instead (`InboxService._is_missing_media_error`). Every value here is a
    failure that proves nothing about the media itself."""

    TRANSIENT = "transient"
    PERMISSION = "permission"
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class MediaMetadata:
    """What is persisted about a media so it stays readable after the window ends — all
    straight from Meta's `GET /{media}` (`MediaSummary`). `caption`/`permalink`/
    `media_product_type`/`media_type` may legitimately be `None` (no caption set, field
    not returned); `posted_at` never is. `media_type` (QUA-146) is Meta's value verbatim,
    known or not (`inbox.media_type`); `None` means "not in this response" and never
    erases a value already stored."""

    posted_at: datetime
    caption: str | None = None
    permalink: str | None = None
    media_product_type: str | None = None
    media_type: str | None = None

    def __post_init__(self) -> None:
        # The one field the window is computed from: storing a row as "complete" without
        # a real, timezone-aware date would make it impossible to ever expire.
        _require_aware(self.posted_at, "posted_at")


@dataclass(frozen=True)
class MediaToSync:
    """One media the sync may call Meta for: monitored and not KNOWN to be expired.
    `needs_metadata` is a legacy row (monitored before QUA-149) whose metadata was never
    fetched — its publication date is unknown, so it cannot be judged expired until it is
    read once, and until then it is synced like an active media (it may in fact already be
    expired; see `InboxService.sync_comments`, "Known limitation").
    `metadata_attempted_at`/`metadata_error` describe the last failed read, if any, so
    the caller can space out retries.
    `needs_media_type` (QUA-146) is a row whose metadata IS complete but whose
    `media_type` was never stored (monitored before the sync asked Meta for it): it gets
    one dedicated read, under the same retry spacing. Only rows `list_media_to_sync`
    returns are ever turned into a `MediaToSync`, and it never returns an expired one, so
    completing the field never costs a call on an expired media."""

    external_media_id: str
    needs_metadata: bool
    metadata_attempted_at: datetime | None = None
    metadata_error: MetadataFetchError | None = None
    needs_media_type: bool = False


# How long a FAILED metadata read waits before it may be tried again (QUA-149). A legacy
# row is never re-read on every sync: each pass checks this first, and a row still inside
# its wait costs no Meta call. Longer for failures retrying cannot fix soon.
METADATA_RETRY_AFTER: Final[Mapping[MetadataFetchError, timedelta]] = MappingProxyType(
    {
        MetadataFetchError.TRANSIENT: timedelta(minutes=15),
        MetadataFetchError.RATE_LIMITED: timedelta(hours=1),
        MetadataFetchError.UNKNOWN: timedelta(hours=6),
        MetadataFetchError.PERMISSION: timedelta(hours=24),
    }
)


def metadata_read_due(media: MediaToSync, now: datetime) -> bool:
    """True when the sync should read this media's metadata from Meta now: it is still
    missing (all of it, or only `media_type` — QUA-146), and either it was never tried or
    its last failure's wait is over. A complete row that has its `media_type` is never
    due — once read, a media is never asked for again."""
    if not (media.needs_metadata or media.needs_media_type):
        return False
    if media.metadata_attempted_at is None or media.metadata_error is None:
        return True
    return now >= media.metadata_attempted_at + METADATA_RETRY_AFTER[media.metadata_error]


def _require_aware(value: object, name: str) -> None:
    """Naive datetimes are refused: compared against `timestamptz` they would be read in
    the session's time zone and silently shift the window by hours."""
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime, got {value!r}")


def window_start(now: datetime) -> datetime:
    """The earliest publication time still inside the window at `now`."""
    _require_aware(now, "now")
    return now - MONITORING_WINDOW


def is_within_window(posted_at: datetime, now: datetime) -> bool:
    """True while `posted_at` is inside the 14-day window at `now`. The boundary itself
    (exactly 14 days) is inside — the same comparison activation has always used."""
    return posted_at >= window_start(now)


def effective_state(
    *, is_monitored: bool, posted_at: datetime | None, now: datetime
) -> MonitoringState:
    """The one definition of what a media's monitoring state is.

    A monitored media whose publication date is still unknown (`posted_at is None`, a
    legacy row awaiting its one metadata read) is `ACTIVE`: it is still being synced, and
    the state must say what the backend does."""
    if not is_monitored:
        return MonitoringState.INACTIVE
    if posted_at is None or is_within_window(posted_at, now):
        return MonitoringState.ACTIVE
    return MonitoringState.EXPIRED
