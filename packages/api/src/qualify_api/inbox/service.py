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

All three take already-constructed `MediaClient`/`CommentsClient` — this service does not
build them and does not resolve credentials. Composition (which client for which
connection) lives in `composition.py`; `sync_comments`'s real caller is `qualify_api.
http.inbox_routes.sync_inbox` (`POST /api/inbox/sync`, B2's acceptance-criterion route).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Protocol
from uuid import UUID

from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS

from qualify_api.inbox.client import CommentsClient, CommentsReadError
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


def _is_missing_media_error(exc: CommentsReadError) -> bool:
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
    return exc.http_status == 400 and exc.platform_code == 100 and exc.platform_subcode == 33


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

        **QUA-101.** A monitored medium's comments are now always walked to Meta's own
        end of pagination (or until the budget runs out), not just to the first page
        with nothing new — the trade-off this accepts is more Meta calls per sync for a
        medium with many comments, in exchange for being able to notice one disappear.
        A walk that completes cleanly (no truncation, no error) reconciles: anything
        stored under that medium but no longer returned is soft-deleted, and anything
        soft-deleted that reappears is restored. See `SyncSummary.deleted_comments` and
        `InboxRepository.reconcile_media_comments`.
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
        deleted_comments = 0
        truncated = False
        skipped_missing_media: list[str] = []
        for media_id in monitored_ids:
            if remaining <= 0:
                truncated = True
                break
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
                    if exc.http_status == 401 or exc.platform_code == 190:
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
        )
