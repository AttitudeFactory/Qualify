"""The inbox service: candidate listing, the monitoring toggle, and comment sync.

No server loop, no scheduler — same principle `publishing/service.py` already
establishes for `advance()`: the caller drives the cadence by calling `sync_comments`
again, there is nothing here that sleeps or polls on its own.

## The three operations, and why they are one service

- `list_candidate_media` — what the "pick what to monitor" UI would call. Reads Meta
  (last 2 weeks, via `MediaClient.list_recent_media`) and cross-references what is
  already monitored, so the caller sees both in one shape. Also enforces "Reels only"
  (2026-08-14, same session as the 2-week rule): the rest of the product only ever
  operates on `media_product_type == "REELS"` (`publishing_provider.start_publish` fixes
  the same value for the opposite direction), so a picker offering photos/carousels to
  "monitor" would offer something nothing downstream is built for. Filtered HERE, not in
  `media_client.py`, which stays a faithful mirror of whatever Meta returns — same
  separation of concerns `MONITORING_WINDOW` already establishes for the time rule.
- `set_media_monitored` — the toggle. **Re-validates the 2-week window against Meta
  itself before allowing `monitored=True`** (product decision, 2026-08-14): a caller
  that bypasses the candidate-listing UI and calls this directly with an old media_id
  must be rejected exactly as if the UI had never offered it. Turning monitoring OFF is
  never gated by age — the rule only bounds what can be ADDED.
- `sync_comments` — B2. Reads ONLY `InboxRepository.list_monitored_media_ids`, never
  Meta's full media list. Walks comment pages per monitored media until a page adds
  nothing new or `paging.cursors.after` is absent — the dedup-by-id rule
  `ig_shapes.INCREMENTAL_POLLING_NOTE` already prescribes, not a persisted cursor (which
  would go stale between runs regardless).

All three take already-constructed `MediaClient`/`CommentsClient` — this service does not
build them and does not resolve credentials. Composition (which client for which
connection) lives in `composition.py`; `sync_comments`'s real caller is `qualify_api.
http.inbox_routes.sync_inbox` (`POST /api/inbox/sync`, B2's acceptance-criterion route).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS

from qualify_api.inbox.client import CommentsClient
from qualify_api.inbox.media_client import MediaClient, MediaReadError
from qualify_api.inbox.repository import InboxRepository

# The product rule (Herwin, 2026-08-14): only the last 2 weeks of content is offered for
# monitoring, and re-enforced here — not merely in what the candidate list returns.
MONITORING_WINDOW = timedelta(days=14)

# The only media type this product's monitoring (and publishing — see
# `publishing_provider.start_publish`) ever operates on.
_MONITORABLE_MEDIA_PRODUCT_TYPE = "REELS"

# `reference/meta-instagram-platform/ACCESS-MODEL.md:56` — "rate-limited to 200
# calls/hour per page-app pair" in development mode. QUA-20's own cited floor; QUA-88
# is what actually enforces it. The window itself is owned by `InboxRepository.
# calls_in_last_hour` (a true sliding hour, not a calendar-hour bucket — see that
# ticket for why) — not duplicated here as a second constant that could drift from it.
META_CALL_BUDGET_PER_HOUR: Final = 200


@dataclass(frozen=True)
class CandidateMedia:
    """One piece of recent content, with whether the tenant already monitors it.

    `caption`/`permalink`/`thumbnail_url` are carried through verbatim from
    `MediaSummary` (may be `None`) — this dataclass is still the service's internal
    shape, not a client-facing one; coercing `None` to `""` is a display concern that
    belongs to whatever UI projects this next (Reflex's `inbox_provider.py`), same
    division `publishing_provider._to_vm` already draws for `PublishState`.
    """

    external_media_id: str
    timestamp: datetime
    is_monitored: bool
    caption: str | None = None
    permalink: str | None = None
    thumbnail_url: str | None = None


@dataclass(frozen=True)
class SyncSummary:
    media_checked: int
    new_comments: int
    # True only when the budget ran out mid-pagination and the sync stopped early
    # (QUA-88) — `media_checked` then counts only what was actually begun, not every
    # monitored id. Defaults to False so every pre-existing call site/equality check
    # (`SyncSummary(media_checked=X, new_comments=Y)`) is unaffected.
    truncated: bool = False


class CommentsPermissionMissing(Exception):
    """The connection is missing a scope `qualify_shared.social.ig_shapes.
    COMMENTS_EDGE_PERMISSIONS` requires to read the comments edge AT ALL — not one
    field, the whole endpoint (QUA-67 §3 / NOTES_ig_shapes_contract.md §3). Raised
    BEFORE any Meta call: an empty poll must never be the only signal that a scope is
    missing (`cannot_observe`, distinct from `observed_zero`)."""

    def __init__(self, *, connection_id: UUID) -> None:
        super().__init__(
            f"connection {connection_id} is missing a scope required to read the "
            "comments edge at all (instagram_manage_comments)"
        )
        self.connection_id = connection_id


class SyncBudgetExhausted(Exception):
    """The floor estimate for this sync (one Meta call per monitored medium) alone
    exceeds what remains of the 200/hour budget (QUA-88). Raised BEFORE any Meta call
    — unlike a mid-pagination truncation (`SyncSummary.truncated`), nothing was
    attempted here at all."""

    def __init__(self, *, needed: int, remaining: int) -> None:
        super().__init__(
            f"sync needs at least {needed} Meta call(s) but only {remaining} remain "
            "in the current hour"
        )
        self.needed = needed
        self.remaining = remaining


class MediaNotEligible(Exception):
    """`set_media_monitored(monitored=True)` refused this media. `reason` distinguishes
    "too old" (the product rule) from "could not verify" (Meta 404/error) — both collapse
    to "cannot monitor this" for the caller, but a future UI message should not conflate
    them."""

    def __init__(self, external_media_id: str, *, reason: str) -> None:
        super().__init__(f"media {external_media_id!r} is not eligible for monitoring: {reason}")
        self.external_media_id = external_media_id
        self.reason = reason


class InboxService:
    def __init__(
        self,
        *,
        repository: InboxRepository,
        comments_client: CommentsClient,
        media_client: MediaClient,
        granted_scopes: frozenset[str] = frozenset(),
    ) -> None:
        self._repository = repository
        self._comments_client = comments_client
        self._media_client = media_client
        # Defaults to empty, not "everything granted" — an unwired caller must fail
        # closed (every `sync_comments` call raises `CommentsPermissionMissing`), the
        # same fail-closed posture `AllowAllLimiter` in `leads/rate_limit.py` makes
        # opt-in rather than default.
        self._granted_scopes = granted_scopes

    async def list_candidate_media(
        self, *, tenant_id: UUID, connection_id: UUID, ig_user_id: str, now: datetime | None = None
    ) -> tuple[CandidateMedia, ...]:
        reference_now = now if now is not None else datetime.now(UTC)
        recent = await self._media_client.list_recent_media(
            ig_user_id=ig_user_id, since=reference_now - MONITORING_WINDOW
        )
        monitored_ids = self._repository.list_monitored_media_ids(
            tenant_id=tenant_id, connection_id=connection_id
        )
        return tuple(
            CandidateMedia(
                external_media_id=media.id,
                timestamp=media.timestamp,
                is_monitored=media.id in monitored_ids,
                caption=media.caption,
                permalink=media.permalink,
                thumbnail_url=media.thumbnail_url,
            )
            for media in recent
            if media.media_product_type == _MONITORABLE_MEDIA_PRODUCT_TYPE
        )

    async def set_media_monitored(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        external_media_id: str,
        monitored: bool,
        now: datetime | None = None,
    ) -> None:
        if monitored:
            # Re-verify against Meta, live — never trust a client-supplied timestamp and
            # never a cached one (there is none; this is the whole point of not adding
            # `media_posted_at` to the table).
            try:
                media = await self._media_client.get_media(media_id=external_media_id)
            except MediaReadError as exc:
                raise MediaNotEligible(
                    external_media_id, reason="not_found_or_inaccessible"
                ) from exc
            reference_now = now if now is not None else datetime.now(UTC)
            if media.timestamp < reference_now - MONITORING_WINDOW:
                raise MediaNotEligible(external_media_id, reason="too_old")
        self._repository.set_media_monitored(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_media_id=external_media_id,
            monitored=monitored,
        )

    async def sync_comments(
        self, *, tenant_id: UUID, connection_id: UUID, now: datetime | None = None
    ) -> SyncSummary:
        """Runs one sync pass, gated by two pre-flight checks that must never depend on
        an actual Meta call to discover (QUA-88):

        1. **`cannot_observe`** — the connection lacks a scope the comments edge requires
           at all. Raises `CommentsPermissionMissing` before touching Meta.
        2. **Budget** — the floor estimate (one call per monitored medium) alone exceeds
           what remains of the 200/hour window. Raises `SyncBudgetExhausted` before
           touching Meta.

        Once running, each real `list_comments` call (including every page a
        pagination walk makes) is logged to the ledger immediately before it fires, and
        checked against the remaining budget first — a media object whose comments
        paginate deeply can still exhaust the budget mid-walk, in which case the sync
        stops (not raises) and returns a `truncated=True` summary: whatever was already
        synced is real and idempotent, so surfacing it beats discarding it.
        """
        if not set(COMMENTS_EDGE_PERMISSIONS) <= self._granted_scopes:
            raise CommentsPermissionMissing(connection_id=connection_id)

        reference_now = now if now is not None else datetime.now(UTC)
        monitored_ids = self._repository.list_monitored_media_ids(
            tenant_id=tenant_id, connection_id=connection_id
        )
        needed = len(monitored_ids)  # the floor: at least one call per monitored medium
        calls_made = self._repository.calls_in_last_hour(
            tenant_id=tenant_id, connection_id=connection_id, now=reference_now
        )
        remaining = META_CALL_BUDGET_PER_HOUR - calls_made
        if needed > remaining:
            raise SyncBudgetExhausted(needed=needed, remaining=remaining)

        media_checked = 0
        new_comments = 0
        truncated = False
        for media_id in monitored_ids:
            if remaining <= 0:
                truncated = True
                break
            media_checked += 1
            after: str | None = None
            while True:
                if remaining <= 0:
                    truncated = True
                    break
                self._repository.record_call(
                    tenant_id=tenant_id, connection_id=connection_id, called_at=reference_now
                )
                remaining -= 1
                page = await self._comments_client.list_comments(ig_media_id=media_id, after=after)
                page_had_new = False
                for comment in page.data:
                    if self._repository.upsert_comment(
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        external_media_id=media_id,
                        comment=comment,
                    ):
                        new_comments += 1
                        page_had_new = True
                cursor = ((page.paging or {}).get("cursors") or {}).get("after")
                # Stop at the first fully-known page or when Meta has no more to offer —
                # `ig_shapes.INCREMENTAL_POLLING_NOTE`: dedup is by id, there is no
                # since-cursor to lean on instead.
                if not cursor or not page_had_new:
                    break
                after = cursor
            if truncated:
                break
        return SyncSummary(
            media_checked=media_checked, new_comments=new_comments, truncated=truncated
        )
