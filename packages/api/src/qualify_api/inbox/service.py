"""The inbox service: candidate listing, the monitoring toggle, and comment sync.

No server loop, no scheduler — same principle `publishing/service.py` already
establishes for `advance()`: the caller drives the cadence by calling `sync_comments`
again, there is nothing here that sleeps or polls on its own.

## The three operations, and why they are one service

- `list_candidate_media` — what the "pick what to monitor" UI would call. Reads Meta
  (last 2 weeks, via `MediaClient.list_recent_media`) and cross-references what is
  already monitored, so the caller sees both in one shape. Also enforces which surfaces
  can be monitored: "Reels only" from 2026-08-14, widened by QUA-146 to `FEED` posts too
  (images, feed videos, carousels — any `media_type`), still never Stories or ads
  (`MONITORABLE_MEDIA_PRODUCT_TYPES`). A carousel is monitored as the album: its
  comments are read on the album id, never per child. Filtered HERE, not in
  `media_client.py`, which stays a faithful mirror of whatever Meta returns — same
  separation of concerns `MONITORING_WINDOW` already establishes for the time rule.
- `set_media_monitored` — the toggle. **Re-validates the 2-week window against Meta
  itself before allowing `monitored=True`** (product decision, 2026-08-14): a caller
  that bypasses the candidate-listing UI and calls this directly with an old media_id
  must be rejected exactly as if the UI had never offered it. The surface rule is
  re-validated the same way (QUA-146): a Story or an ad id is refused here too. Turning
  monitoring OFF is never gated by age — the rule only bounds what can be ADDED.
- `sync_comments` — B2, extended by QUA-101. Reads ONLY `InboxRepository.
  list_monitored_media_ids`, never Meta's full media list. Walks EVERY comment page per
  monitored media to completion — to `paging.cursors.after` being absent, or the QUA-88
  budget running out — never stopping early just because a page added nothing new (that
  optimization, correct for "is there anything NEW", cannot tell "did something
  disappear": a comment deleted on page 3 leaves page 1 looking exactly as fully-known as
  before). Dedup on insert is still by id (`ig_shapes.INCREMENTAL_POLLING_NOTE`), not a
  persisted cursor. After a media's walk completes WITHOUT truncation or a missing-media
  error, its observed comment ids are diffed against storage
  (`InboxRepository.reconcile_media_comments`, QUA-101): anything stored but no longer
  returned is soft-deleted, and anything soft-deleted that reappears is restored. A
  truncated or errored walk never reconciles — it has not seen enough of Meta's current
  state to prove anything absent.

## Story comments (m-24789644), behind a capability that is off by default

`InboxService(story_comments=True)` adds `STORY` to the monitorable surfaces: the
picker also reads `MediaClient.list_recent_stories` (stories never appear on `/media`),
a story can be activated like a Reel, and from then on it is an ordinary monitored media
— `sync_comments` reads its comments through the same `/comments` edge, so sentiment and
intent reach them with no change of their own. Off (the default), nothing changes:
`/stories` is never called and a story id is still `unsupported_surface`. A failed
`/stories` read never sinks the picker: the Reels and posts are still returned.

**R1 (2026-10-21): Meta does not serve story comments.** On a real story with one
comment, `/stories` and `GET /{story-id}` answered (`comments_count: 1`), but
`GET /{story-id}/comments` answered `400 (#10) Comments cannot be made on story media.`
— so the capability must stay off: turned on, a monitored story would raise
`CommentsReadError` on every pass. See `docs/conversaciones-limitaciones-meta.md` §6.

All three take already-constructed `MediaClient`/`CommentsClient` — this service does not
build them and does not resolve credentials. Composition (which client for which
connection) lives in `composition.py`; `sync_comments`'s real caller is `qualify_api.
http.inbox_routes.sync_inbox` (`POST /api/inbox/sync`, B2's acceptance-criterion route).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Final, Protocol
from uuid import UUID

import httpx
from qualify_shared.social.graph_errors import is_missing_object_error
from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS

from qualify_api.inbox.client import CommentsClient, CommentsReadError
from qualify_api.inbox.media_client import MediaClient, MediaReadError, MediaSummary
from qualify_api.inbox.media_type import is_unrecognized_media_type
from qualify_api.inbox.monitoring import (
    MONITORING_WINDOW,
    MediaMetadata,
    MediaToSync,
    MetadataFetchError,
    is_within_window,
    metadata_read_due,
)
from qualify_api.inbox.repository import InboxRepository

# The product rule (Herwin, 2026-08-14): only the last 2 weeks of content is offered for
# monitoring, and re-enforced here — not merely in what the candidate list returns. The
# window itself lives in `monitoring.py` (QUA-149), the one place every caller reads it;
# it is still importable from here for existing callers.

_LOGGER = logging.getLogger(__name__)

# The surfaces (`media_product_type`) a tenant may opt a media into monitoring on:
# Reels since 2026-08-14, feed posts since QUA-146 — whatever their `media_type`
# (image, video, carousel, or one Meta adds later). Never `STORY` or `AD`; a media whose
# surface Meta did not report is not offered either (fail closed).
MONITORABLE_MEDIA_PRODUCT_TYPES: Final = frozenset({"REELS", "FEED"})

# m-24789644: the surface the `story_comments` capability adds to the set above.
STORY_MEDIA_PRODUCT_TYPE: Final = "STORY"

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
    # QUA-146: where the media lives (`REELS`/`FEED`) and what it is (`IMAGE`/`VIDEO`/
    # `CAROUSEL_ALBUM`, or a value this code does not know) — verbatim from Meta, for the
    # picker to label each row. Display only: eligibility is decided above, not on these.
    media_product_type: str | None = None
    media_type: str | None = None
    # QUA-146: Meta's `media_url` — the picture of a photo/carousel, which has no
    # `thumbnail_url` (VIDEO-only). Display only, like the two fields above.
    media_url: str | None = None


@dataclass(frozen=True)
class SyncSummary:
    media_checked: int
    new_comments: int
    # True only when the budget ran out mid-pagination and the sync stopped early
    # (QUA-88) — `media_checked` then counts only what was actually begun, not every
    # monitored id. Defaults to False so every pre-existing call site/equality check
    # (`SyncSummary(media_checked=X, new_comments=Y)`) is unaffected.
    truncated: bool = False
    # Media ids Meta confirmed no longer exist (bug fix, 2026-09-01): a monitored Reel
    # the tenant deleted on Instagram must not abort the WHOLE pass the way any other
    # `CommentsReadError` still correctly does — see `_is_missing_media_error`'s
    # docstring for the narrow detection and `sync_comments`'s per-media handling below.
    # Each such id is also auto-unmonitored (`InboxRepository.set_media_monitored(...,
    # monitored=False)`) so it stops being retried on every future sync. Defaults to an
    # empty tuple so every pre-existing call site/equality check is unaffected, same
    # reasoning `truncated` already documents.
    skipped_missing_media: tuple[str, ...] = ()
    # QUA-101: individual comments newly soft-deleted this pass
    # (`InboxRepository.reconcile_media_comments`) because a COMPLETE walk of their
    # media no longer returned them — distinct from `skipped_missing_media` above,
    # which is the whole Reel disappearing. Restoring an already-deleted comment that
    # reappears is NOT counted here (it is not new information about a deletion).
    # Defaults to 0 so every pre-existing call site/equality check is unaffected, same
    # reasoning `truncated`/`skipped_missing_media` already document.
    deleted_comments: int = 0
    # QUA-149. Every counter below defaults to 0 so pre-existing call sites/equality
    # checks are unaffected, same reasoning as the fields above.
    # Monitored media past the 14-day window: never synced, never a Meta call. Counts
    # both rows already known to be expired and legacy rows this pass found expired once
    # their metadata was read.
    expired_skipped: int = 0
    # Legacy rows (monitored before QUA-149) whose metadata was read successfully now.
    metadata_backfilled: int = 0
    # Metadata reads that failed this pass (transient, permission, rate limit, unknown) —
    # recorded on the row for a spaced retry; nothing stored was changed.
    metadata_failed: int = 0
    # Legacy rows still missing metadata whose last failure's wait is not over: no
    # metadata call this pass. Their comments ARE still synced (date unknown), so each one
    # may be costing comment calls on a media that is in fact already expired — see the
    # "Known limitation" in `InboxService.sync_comments`.
    metadata_deferred: int = 0


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
    """`set_media_monitored(monitored=True)` refused this media. `reason` is one of
    `"too_old"` (the 14-day product rule), `"not_found_or_inaccessible"` (Meta 404/error,
    could not verify) or `"unsupported_surface"` (QUA-146: a Story, an ad, or a surface
    Meta did not report) — all collapse to "cannot monitor this" for the caller, but a
    future UI message should not conflate them."""

    def __init__(self, external_media_id: str, *, reason: str) -> None:
        super().__init__(f"media {external_media_id!r} is not eligible for monitoring: {reason}")
        self.external_media_id = external_media_id
        self.reason = reason


class CommentsAuthExpired(Exception):
    """A `list_comments` call failed on auth grounds (HTTP 401 and/or `error.code=190`,
    QUA-90) — distinct from `CommentsReadError`'s generic 502 the same way
    `CommentsPermissionMissing`/`SyncBudgetExhausted` are distinct from it: a caller
    should tell an operator "reconnect your account", not "something went wrong". Raised
    AFTER the connection has already been degraded (`ACTIVE -> DEGRADED`, see
    `sync_comments`) — by the time this reaches a caller, Conexiones already has
    something real to show."""

    def __init__(self, *, connection_id: UUID) -> None:
        super().__init__(f"connection {connection_id} failed auth on a runtime comments call")
        self.connection_id = connection_id


class ConnectionDegrader(Protocol):
    """QUA-90: degrades a connection to `degraded` after a runtime 401/190. Same shape as
    `qualify_api.connections.composition.degrade_connection_on_auth_error` — synchronous
    and never-raising, so `sync_comments` calls it directly without `await`/try-except."""

    def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> object | None: ...


def _is_missing_media_error(exc: CommentsReadError | MediaReadError) -> bool:
    """True only for Meta's well-established Graph API signature for "this node no
    longer exists (or this app can no longer see it)": HTTP 400, `error.code=100`,
    `error.error_subcode=33`. That pairing — not `code=100` alone — is the documented,
    industry-stable Graph API convention for a dead/inaccessible node id across
    virtually every edge (it is what a real `GET /{id}` returns for a deleted post,
    comment, page, etc.), and is what motivated this bug fix: a Reel a tenant deletes
    on Instagram stays `monitored_media.is_monitored=true` here until this fires.

    Deliberately narrower than `platform_code == 100` alone (bug-fix requirement,
    2026-09-01): `reference/meta-instagram-platform/.../error-codes.md` documents over
    a dozen UNRELATED validation errors that also carry `code=100` on the Content
    Publishing edge (bad media type, too many tags, malformed audio-swap params, ...) —
    matching on code alone would silently swallow those as "the media is gone" and
    auto-unmonitor a Reel that in fact still exists. Subcode `33` is what narrows it to
    specifically "object does not exist / not visible", the same way `platform_code ==
    190` narrows the auth branch above instead of matching on `code` alone.

    **[VERIFIED live 2026-09-01]** against this repo's own comments-read endpoint, same
    "[V]" discipline `inbox/client.py`'s module docstring already applies to this
    module: the real post the bug report was filed about (external_media_id
    `18034792133641940`, deleted from Instagram, `monitored_media.is_monitored` still
    `true`) was temporarily re-added and synced for real — `GET /18034792133641940/
    comments` returned exactly `HTTP 400, error.code=100, error.error_subcode=33`,
    confirming this is not a guess. Same posture `CommentsAuthExpired`'s 401/190 already
    has (verified live 2026-08-14 per QUA-90's docstring).
    """
    return is_missing_object_error(
        http_status=exc.http_status,
        platform_code=exc.platform_code,
        platform_subcode=exc.platform_subcode,
    )


def _is_auth_error(exc: CommentsReadError | MediaReadError) -> bool:
    """QUA-90's signature for an expired/revoked token: HTTP 401 and/or `error.code=190`."""
    return exc.http_status == 401 or exc.platform_code == 190


# Graph API error codes (QUA-149), used only to label a FAILED metadata read so it can be
# retried on a sensible schedule (`monitoring.METADATA_RETRY_AFTER`). None of them ever
# turns monitoring off — only `_is_missing_media_error` is evidence of a deletion.
# Rate limiting: app (4), user (17), page (32), call-type (613) and business-use-case
# (80001-80014, Instagram's own family).
_RATE_LIMIT_CODES: Final = frozenset({4, 17, 32, 613, *range(80001, 80015)})
# Permissions: generic (10) and the 200-299 permission family.
_PERMISSION_CODES: Final = frozenset({10, *range(200, 300)})
# Meta's own "try again" codes: unknown error (1), temporary service issue (2).
_TRANSIENT_CODES: Final = frozenset({1, 2})


def _classify_metadata_error(exc: MediaReadError) -> MetadataFetchError:
    """Why a `get_media` call failed, for a failure that is NOT a confirmed deletion and
    NOT an auth error (both are handled before this is called)."""
    status, code = exc.http_status, exc.platform_code
    if status == 429 or code in _RATE_LIMIT_CODES:
        return MetadataFetchError.RATE_LIMITED
    if status == 403 or code in _PERMISSION_CODES:
        return MetadataFetchError.PERMISSION
    if (status is not None and status >= 500) or code in _TRANSIENT_CODES:
        return MetadataFetchError.TRANSIENT
    return MetadataFetchError.UNKNOWN


def _merge_by_id(
    first: tuple[MediaSummary, ...], second: tuple[MediaSummary, ...]
) -> tuple[MediaSummary, ...]:
    """`first` then whatever of `second` it does not already hold, by id."""
    seen = {media.id for media in first}
    return first + tuple(media for media in second if media.id not in seen)


def _no_op_degrader(*, tenant_id: UUID, connection_id: UUID) -> None:
    """Default for callers (mostly tests) that do not care about QUA-90's auth-error
    path — production composition always injects the real one."""
    return None


class InboxService:
    def __init__(
        self,
        *,
        repository: InboxRepository,
        comments_client: CommentsClient,
        media_client: MediaClient,
        granted_scopes: frozenset[str] = frozenset(),
        connection_degrader: ConnectionDegrader | None = None,
        story_comments: bool = False,
    ) -> None:
        self._repository = repository
        self._comments_client = comments_client
        self._media_client = media_client
        # Defaults to empty, not "everything granted" — an unwired caller must fail
        # closed (every `sync_comments` call raises `CommentsPermissionMissing`), the
        # same fail-closed posture `AllowAllLimiter` in `leads/rate_limit.py` makes
        # opt-in rather than default.
        self._granted_scopes = granted_scopes
        self._degrade = connection_degrader or _no_op_degrader
        # m-24789644: off unless the caller opts in — see "Story comments" above.
        self._story_comments = story_comments
        self._monitorable = (
            MONITORABLE_MEDIA_PRODUCT_TYPES | {STORY_MEDIA_PRODUCT_TYPE}
            if story_comments
            else MONITORABLE_MEDIA_PRODUCT_TYPES
        )

    async def list_candidate_media(
        self, *, tenant_id: UUID, connection_id: UUID, ig_user_id: str, now: datetime | None = None
    ) -> tuple[CandidateMedia, ...]:
        reference_now = now if now is not None else datetime.now(UTC)
        recent = await self._media_client.list_recent_media(
            ig_user_id=ig_user_id, since=reference_now - MONITORING_WINDOW
        )
        if self._story_comments:
            recent = _merge_by_id(recent, await self._recent_stories(ig_user_id))
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
                media_product_type=media.media_product_type,
                media_type=media.media_type,
                media_url=media.media_url,
            )
            for media in recent
            if media.media_product_type in self._monitorable
        )

    async def _recent_stories(self, ig_user_id: str) -> tuple[MediaSummary, ...]:
        """The `/stories` read, best effort: a failure is logged (status and Meta codes
        only) and the picker still shows the Reels and posts it already has."""
        try:
            return await self._media_client.list_recent_stories(ig_user_id=ig_user_id)
        except MediaReadError as exc:
            _LOGGER.warning(
                "inbox.stories.read_failed status=%s code=%s subcode=%s",
                exc.http_status,
                exc.platform_code,
                exc.platform_subcode,
            )
            return ()

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
            # Re-verify against Meta, live — never trust a client-supplied timestamp nor
            # the stored one. `media_posted_at` is persisted below (QUA-149, 0046) only so
            # the window can still be judged after the media leaves Meta's 14-day listing;
            # activation always decides on the date Meta returns now.
            try:
                media = await self._media_client.get_media(media_id=external_media_id)
            except MediaReadError as exc:
                raise MediaNotEligible(
                    external_media_id, reason="not_found_or_inaccessible"
                ) from exc
            if media.media_product_type not in self._monitorable:
                # QUA-146: same rule as the candidate list, re-enforced on a direct call.
                raise MediaNotEligible(external_media_id, reason="unsupported_surface")
            reference_now = now if now is not None else datetime.now(UTC)
            if not is_within_window(media.timestamp, reference_now):
                raise MediaNotEligible(external_media_id, reason="too_old")
            # QUA-149: what Meta just returned is kept, so the media stays readable (and
            # can be judged expired) after it leaves Meta's 14-day listing.
            self._repository.set_media_monitored(
                tenant_id=tenant_id,
                connection_id=connection_id,
                external_media_id=external_media_id,
                monitored=True,
                metadata=_metadata_from(media),
                fetched_at=reference_now,
            )
            return
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

        **QUA-101.** A monitored medium's comments are now always walked to Meta's own
        end of pagination (or until the budget runs out), not just to the first page
        with nothing new — the trade-off this accepts is more Meta calls per sync for a
        medium with many comments, in exchange for being able to notice one disappear.
        A walk that completes cleanly (no truncation, no error) reconciles: anything
        stored under that medium but no longer returned is soft-deleted, and anything
        soft-deleted that reappears is restored. See `SyncSummary.deleted_comments` and
        `InboxRepository.reconcile_media_comments`.

        **QUA-149.** Only media still inside the 14-day window are synced
        (`InboxRepository.list_media_to_sync`): a media KNOWN to be expired costs no Meta
        call, no ledger entry, no place in the budget floor, and is never reconciled — its
        stored comments and metadata stay exactly as they are. A legacy row (monitored
        before its publication date was stored) gets its metadata read once, here, before
        its comments (`_backfill_metadata`); if that read shows it expired, it is skipped
        like any other expired media. Only Meta's confirmed-deletion signature turns
        monitoring off; a rate-limited read ends the pass early (`truncated=True`).

        **Known limitation (accepted 2026-10-09).** While a legacy row's metadata read
        keeps failing, its publication date stays unknown, so it is treated as active
        (`monitoring.effective_state`) and its COMMENTS ARE STILL SYNCED on every pass —
        even if the media is in fact already past its window. Such a row can therefore
        keep costing comment calls until one metadata read succeeds (retries are spaced
        by `monitoring.METADATA_RETRY_AFTER`, so the metadata read itself is not repeated
        every pass). Expired media stop costing calls once their date is KNOWN, not
        before. `SyncSummary.metadata_failed`/`metadata_deferred` make these rows visible.
        """
        if not set(COMMENTS_EDGE_PERMISSIONS) <= self._granted_scopes:
            raise CommentsPermissionMissing(connection_id=connection_id)

        reference_now = now if now is not None else datetime.now(UTC)
        to_sync = self._repository.list_media_to_sync(
            tenant_id=tenant_id, connection_id=connection_id, now=reference_now
        )
        expired_skipped = self._repository.count_expired_media(
            tenant_id=tenant_id, connection_id=connection_id, now=reference_now
        )
        needed = len(to_sync)  # the floor: at least one call per media still in its window
        calls_made = self._repository.calls_in_last_hour(
            tenant_id=tenant_id, connection_id=connection_id, now=reference_now
        )
        remaining = META_CALL_BUDGET_PER_HOUR - calls_made
        if needed > remaining:
            raise SyncBudgetExhausted(needed=needed, remaining=remaining)

        media_checked = 0
        new_comments = 0
        deleted_comments = 0
        truncated = False
        skipped_missing_media: list[str] = []
        metadata_backfilled = 0
        metadata_failed = 0
        metadata_deferred = 0
        for media in to_sync:
            media_id = media.external_media_id
            if remaining <= 0:
                truncated = True
                break
            if metadata_read_due(media, reference_now):
                # One real Meta call: logged immediately before it fires, like every
                # comments call below.
                self._repository.record_call(
                    tenant_id=tenant_id, connection_id=connection_id, called_at=reference_now
                )
                remaining -= 1
                outcome = await self._backfill_metadata(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    media=media,
                    now=reference_now,
                )
                if outcome is _Backfill.DELETED:
                    skipped_missing_media.append(media_id)
                    continue
                if outcome is _Backfill.EXPIRED:
                    metadata_backfilled += 1
                    expired_skipped += 1
                    continue
                if outcome is _Backfill.ACTIVE:
                    metadata_backfilled += 1
                else:
                    metadata_failed += 1
                    if outcome is _Backfill.RATE_LIMITED:
                        # Meta is refusing calls: stop now, the next pass resumes.
                        truncated = True
                        break
                if remaining <= 0:
                    truncated = True
                    break
            elif media.needs_metadata:
                metadata_deferred += 1
            media_checked += 1
            after: str | None = None
            # QUA-101: every comment id actually observed this walk, regardless of
            # whether `upsert_comment` reported it as new — `reconcile_media_comments`
            # needs the COMPLETE current set to diff against storage, not just the new
            # ones. Reconciliation only runs if `walk_completed` ends up `True` below.
            observed_external_ids: set[str] = set()
            media_missing = False
            walk_completed = False
            while True:
                if remaining <= 0:
                    truncated = True
                    break
                self._repository.record_call(
                    tenant_id=tenant_id, connection_id=connection_id, called_at=reference_now
                )
                remaining -= 1
                try:
                    page = await self._comments_client.list_comments(
                        ig_media_id=media_id, after=after
                    )
                except CommentsReadError as exc:
                    if _is_auth_error(exc):
                        # QUA-90: degrade before re-raising, so by the time the caller
                        # (the HTTP route, then Reflex) sees `CommentsAuthExpired`,
                        # Conexiones already has the real "reconnect" state to show —
                        # not a race the UI has to paper over.
                        self._degrade(tenant_id=tenant_id, connection_id=connection_id)
                        raise CommentsAuthExpired(connection_id=connection_id) from exc
                    if _is_missing_media_error(exc):
                        # Bug fix (2026-09-01): a Reel deleted at the source must not
                        # abort the whole pass the way any OTHER `CommentsReadError`
                        # still correctly does below (`raise`) — one dead monitored id
                        # used to fail every sync attempt for the connection, forever,
                        # since it stayed `is_monitored=true` and got retried every
                        # call/poll tick. Stop paginating THIS media only (`break`,
                        # never `raise`) and let the outer `for` move on to the next
                        # monitored id — see `_is_missing_media_error`'s docstring for
                        # the narrow detection this relies on.
                        skipped_missing_media.append(media_id)
                        # Auto-unmonitor: same repository call `set_media_monitored`
                        # already exposes to the toggle (`InboxState.toggle_monitored`)
                        # — Meta itself just confirmed this id can never be read again,
                        # so leaving `is_monitored=true` would only retry it (and burn
                        # QUA-88 budget on it) on every future sync/poll tick forever.
                        # `threads`/`messages` already synced for it are untouched —
                        # same "orthogonal facts" ruling migration 0005 already makes
                        # for turning monitoring off the ordinary way. QUA-101: this is
                        # the WHOLE-REEL case, deliberately distinct from an individual
                        # comment disappearing — never reconciled at the comment level
                        # below (`media_missing` skips that), the Reel-level unmonitor
                        # right below is the complete, correct response to it.
                        self._repository.set_media_monitored(
                            tenant_id=tenant_id,
                            connection_id=connection_id,
                            external_media_id=media_id,
                            monitored=False,
                        )
                        media_missing = True
                        break
                    raise
                for comment in page.data:
                    observed_external_ids.add(comment.id)
                    if self._repository.upsert_comment(
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        external_media_id=media_id,
                        comment=comment,
                    ):
                        new_comments += 1
                cursor = ((page.paging or {}).get("cursors") or {}).get("after")
                # QUA-101: stop ONLY when Meta itself signals the end of pagination —
                # no longer at the first page with nothing new. Detecting a DELETED
                # comment requires having walked to Meta's complete current list; the
                # old "stop once a page adds nothing new" shortcut was correct for "is
                # there anything NEW" (`ig_shapes.INCREMENTAL_POLLING_NOTE`'s dedup-by-id
                # rule still holds for that question) but is structurally blind to a
                # comment disappearing further back in an otherwise-unchanged list.
                if not cursor:
                    walk_completed = True
                    break
                after = cursor
            if walk_completed and not media_missing:
                # A COMPLETE, untruncated, error-free walk of this media's comments —
                # the one precondition `reconcile_media_comments`'s docstring requires
                # before it is safe to conclude anything is actually gone.
                deleted_comments += self._repository.reconcile_media_comments(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    external_media_id=media_id,
                    current_external_ids=frozenset(observed_external_ids),
                )
            if truncated:
                break
        return SyncSummary(
            media_checked=media_checked,
            new_comments=new_comments,
            truncated=truncated,
            skipped_missing_media=tuple(skipped_missing_media),
            deleted_comments=deleted_comments,
            expired_skipped=expired_skipped,
            metadata_backfilled=metadata_backfilled,
            metadata_failed=metadata_failed,
            metadata_deferred=metadata_deferred,
        )

    async def _backfill_metadata(
        self, *, tenant_id: UUID, connection_id: UUID, media: MediaToSync, now: datetime
    ) -> _Backfill:
        """QUA-149: reads a legacy row's metadata once (`GET /{media}`) — the caller has
        already logged the call. Never erases or overwrites stored data on failure:

        - success → stored as complete; `EXPIRED` if the date shows the window is over,
          else `ACTIVE`;
        - Meta's confirmed-deletion signature (HTTP 400, code 100, subcode 33) → turned
          off, exactly as the comments path does (`_is_missing_media_error`);
        - auth failure (401/190) → the connection is degraded and `CommentsAuthExpired`
          raised, same as the comments path (QUA-90);
        - a timeout/connection error (`httpx.TransportError`) → recorded as `TRANSIENT`;
        - anything else → recorded as a labelled failure for a spaced retry, monitoring
          untouched.
        """
        media_id = media.external_media_id
        try:
            summary = await self._media_client.get_media(media_id=media_id)
        except MediaReadError as exc:
            if _is_auth_error(exc):
                self._degrade(tenant_id=tenant_id, connection_id=connection_id)
                raise CommentsAuthExpired(connection_id=connection_id) from exc
            if _is_missing_media_error(exc):
                self._repository.set_media_monitored(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    external_media_id=media_id,
                    monitored=False,
                )
                return _Backfill.DELETED
            error = _classify_metadata_error(exc)
            self._repository.record_media_metadata_failure(
                tenant_id=tenant_id,
                connection_id=connection_id,
                external_media_id=media_id,
                error=error,
                attempted_at=now,
            )
            return (
                _Backfill.RATE_LIMITED
                if error is MetadataFetchError.RATE_LIMITED
                else _Backfill.FAILED
            )
        except httpx.TransportError:
            # A timeout or connection failure never reached Meta's answer, so it proves
            # nothing about the media: a TRANSIENT failure, retried after its wait, and
            # the pass goes on with the other media. Scoped to this metadata read only —
            # the comments path below keeps letting such errors fail the pass, unchanged.
            self._repository.record_media_metadata_failure(
                tenant_id=tenant_id,
                connection_id=connection_id,
                external_media_id=media_id,
                error=MetadataFetchError.TRANSIENT,
                attempted_at=now,
            )
            return _Backfill.FAILED
        if not media.needs_metadata:
            return self._complete_media_type(
                tenant_id=tenant_id,
                connection_id=connection_id,
                media_id=media_id,
                summary=summary,
                now=now,
            )
        self._repository.record_media_metadata(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_media_id=media_id,
            metadata=_metadata_from(summary),
            fetched_at=now,
        )
        return _Backfill.ACTIVE if is_within_window(summary.timestamp, now) else _Backfill.EXPIRED

    def _complete_media_type(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        media_id: str,
        summary: MediaSummary,
        now: datetime,
    ) -> _Backfill:
        """QUA-146: the dedicated read of a row whose metadata was already complete but had
        no `media_type`. Only that field is written — the stored caption, date and
        `metadata_fetched_at` stay as they were. The row was handed over by
        `list_media_to_sync`, so it is inside the window: `ACTIVE`, comments synced next.

        A successful response WITHOUT `media_type` is recorded as an `UNKNOWN` failure,
        so the row waits `METADATA_RETRY_AFTER[UNKNOWN]` instead of being re-read every
        pass; once its window ends it is never handed over, so never read, again."""
        if summary.media_type is None:
            self._repository.record_media_metadata_failure(
                tenant_id=tenant_id,
                connection_id=connection_id,
                external_media_id=media_id,
                error=MetadataFetchError.UNKNOWN,
                attempted_at=now,
            )
            return _Backfill.FAILED
        _warn_if_unrecognized(summary)
        self._repository.record_media_type(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_media_id=media_id,
            media_type=summary.media_type,
            fetched_at=now,
        )
        return _Backfill.ACTIVE


class _Backfill(Enum):
    """Outcome of one metadata read made by the sync (`InboxService._backfill_metadata`):
    a legacy row's full read (QUA-149) or a complete row's dedicated `media_type` read
    (QUA-146, `_complete_media_type`)."""

    ACTIVE = "active"
    EXPIRED = "expired"
    DELETED = "deleted"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"


def _metadata_from(media: MediaSummary) -> MediaMetadata:
    """What `monitored_media` keeps from Meta's `GET /{media}` (QUA-149; `media_type` since
    QUA-146, verbatim, an unknown value included)."""
    _warn_if_unrecognized(media)
    return MediaMetadata(
        posted_at=media.timestamp,
        caption=media.caption,
        permalink=media.permalink,
        media_product_type=media.media_product_type,
        media_type=media.media_type,
    )


def _warn_if_unrecognized(media: MediaSummary) -> None:
    """QUA-146: a `media_type` this code does not know is stored as received and the write
    goes on; this log line is how it gets noticed. Ids and the value only — never a token
    or the caption."""
    if media.media_type is not None and is_unrecognized_media_type(media.media_type):
        _LOGGER.warning(
            "inbox.media_type.unrecognized media_id=%s media_type=%r",
            media.id,
            media.media_type[:64],
        )
