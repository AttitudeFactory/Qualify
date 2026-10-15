"""Production assembly for the `mentions` module (QUA-49) — the analogue of
`inbox/composition.py` and `sentiment/composition.py`.

`ingest_mention` is the seam `mentions_routes.py`'s POST handler calls for every
`RESOLVED` event: build a credential-resolved client for THAT connection, attempt
enrichment (`mentioned_media` for a caption mention, `mentioned_comment` for a comment
mention — never both, decided by whether the event carries a `comment_id`), and persist
the result either way. **Enrichment failing is not an ingestion failure** — a mention
whose Meta call errored (still-pending Advanced Access, a transient 5xx) is persisted with
`enrichment_status="ENRICHMENT_FAILED"` and null content fields rather than being dropped;
the fact that Instagram mentioned this account IS the fact worth keeping, independent of
whether Meta's content API cooperated at that moment. Same "persist the fact, degrade the
content" posture already established across this codebase (`InboxService.sync_comments`
persists what it got before a mid-pagination truncation, rather than discarding it).

A redelivered webhook for the same event is a silent no-op via the natural-key
idempotency; it does not re-attempt a previously-failed enrichment. Since QUA-152 the
re-read path is "Actualizar menciones" (`refresh_mentions_content` /
`refresh_mentions_in_scope` below): it re-reads stored mentions from the network in
bounded runs, so a mention whose enrichment failed at ingestion is filled in (and marked
ENRICHED) the next time its scope is refreshed and the network answers.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import cache
from typing import Literal
from uuid import UUID

import httpx
from qualify_shared.db.session import tenant_session
from qualify_shared.social.graph_errors import is_auth_error
from sqlalchemy import select

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.credential_reader import DbCredentialReader
from qualify_api.connections.crypto import DevEncryptor
from qualify_api.connections.models import SocialConnection
from qualify_api.connections.resolver import AuthenticatedClient, InjectingCredentialResolver
from qualify_api.mentions.meta_client import (
    HttpMentionedContentClient,
    MentionedContentReadError,
    is_gone,
    is_rate_limited,
    is_transient,
)
from qualify_api.mentions.repository import (
    DEFAULT_MENTION_PAGE_SIZE,
    ENRICHMENT_FAILED,
    ENRICHMENT_OK,
    MentionContent,
    MentionCounts,
    MentionPage,
    MentionQuery,
    MentionRecord,
    MentionsRepository,
    NewMention,
    PostgresMentionsRepository,
    RefreshTarget,
)
from qualify_api.mentions.resolve import TenantResolution, instagram_tenant_ids
from qualify_api.mentions.sentiment import (
    MENTIONS_PIPELINE_VERSION,
    MentionAnalysisSummary,
    MentionSentimentService,
)
from qualify_api.sentiment.repository import AnalysisVersion

_LOGGER = logging.getLogger(__name__)


class _ConnectionIgUserIdReader:
    """Reads only `external_account_id` from `social_connections` — duplicated from
    `inbox.composition.PostgresIgUserIdReader` rather than imported, same
    self-containment discipline every composition module in this codebase already
    follows independently of its siblings."""

    def read(self, *, tenant_id: UUID, connection_id: UUID) -> str | None:
        with tenant_session(tenant_id) as session:
            return session.scalar(
                select(SocialConnection.external_account_id).where(
                    SocialConnection.id == connection_id
                )
            )


def connection_username(*, tenant_id: UUID, connection_id: UUID) -> str | None:
    """The connected account's Instagram username (`social_connections.external_username`)
    — what an own-post comment must @mention to be a mention. Read through
    `tenant_session` with the tenant `resolve_external_account` just produced, never
    through the webhook worker's cross-tenant door."""
    with tenant_session(tenant_id) as session:
        return session.scalar(
            select(SocialConnection.external_username).where(SocialConnection.id == connection_id)
        )


@cache
def production_mentions_repository() -> MentionsRepository:
    return PostgresMentionsRepository()


def _resolve_graph_client_blocking(
    *, tenant_id: UUID, connection_id: UUID, scheme: str
) -> AuthenticatedClient:
    """The credential read + decrypt, in a WORKER THREAD (QUA-152 audit). The resolver's
    `client_for` is `async` but does a blocking Postgres query (`credential_session`) with no
    await inside; run on the Reflex backend's event loop it would stall every session. It
    is driven here with its own short-lived loop; the client it builds is not bound to that
    loop (httpx creates its pool lazily) and is used and closed on the caller's loop. The
    shared resolver is deliberately not changed: publishing and the inbox use it too."""
    resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), DevEncryptor())
    return asyncio.run(resolver.client_for(connection_id, scheme=scheme))


async def _close_client(client: object) -> None:
    """Close a content client's HTTP pool; a failure to close is logged, never raised."""
    close = getattr(client, "aclose", None)
    if close is None:
        return
    try:
        await close()
    except Exception as exc:  # noqa: BLE001 — cleanup only
        _LOGGER.info("mentions content client not closed cleanly (%s)", type(exc).__name__)


async def _content_client_for(
    *, tenant_id: UUID, connection_id: UUID
) -> tuple[HttpMentionedContentClient, str] | None:
    """Builds an authenticated `mentioned_media`/`mentioned_comment` client for one
    connection, plus that connection's own `ig_user_id` (the node these endpoints are
    queried against). Returns `None` if the connection is not visible to this tenant —
    should not happen in practice (`resolve_external_account` just produced this exact
    pair), but a defensive `None` here is cheaper than trusting that invariant blindly."""
    # Off the event loop: this also runs inside the Reflex backend (QUA-152 refresh).
    ig_user_id = await asyncio.to_thread(
        _ConnectionIgUserIdReader().read, tenant_id=tenant_id, connection_id=connection_id
    )
    if ig_user_id is None:
        return None
    settings = MetaOAuthSettings.from_env()
    graph_client = await asyncio.to_thread(
        _resolve_graph_client_blocking,
        tenant_id=tenant_id,
        connection_id=connection_id,
        scheme=settings.graph_auth_scheme,
    )
    return (
        HttpMentionedContentClient(graph_client=graph_client, graph_url=settings.graph_url),
        ig_user_id,
    )


async def ingest_mention(
    *,
    media_id: str,
    comment_id: str | None,
    resolution: TenantResolution,
    text: str | None = None,
    author_username: str | None = None,
    observed_at: datetime | None = None,
) -> UUID | None:
    """Enrich (best-effort) and persist one `RESOLVED` mention event. Returns the
    persisted mention's id, or `None` if the connection turned out not to be resolvable
    to a live client (see `_content_client_for`).

    Enrichment picks exactly one endpoint: `mentioned_comment` when `comment_id` is
    present (a mention inside a comment), `mentioned_media` otherwise (a caption
    mention) — mirrors `MentionsChangeValue`'s own caption-vs-comment split, never both.

    `text`/`author_username`/`observed_at` come only from the `comments` webhook (a
    comment on the account's OWN media that @mentions it), which carries what
    `mentions` does not — see `_enrich_and_store`. The `mentions` path passes none of
    them and behaves exactly as before.
    """
    assert resolution.tenant_id is not None and resolution.connection_id is not None

    client_and_user = await _content_client_for(
        tenant_id=resolution.tenant_id, connection_id=resolution.connection_id
    )
    if client_and_user is None:
        return None
    client, ig_user_id = client_and_user
    try:
        return await _enrich_and_store(
            client,
            ig_user_id=ig_user_id,
            media_id=media_id,
            comment_id=comment_id,
            resolution=resolution,
            webhook_text=text,
            webhook_author=author_username,
            observed_at=observed_at,
        )
    finally:
        await _close_client(client)


async def _enrich_and_store(
    client: HttpMentionedContentClient,
    *,
    ig_user_id: str,
    media_id: str,
    comment_id: str | None,
    resolution: TenantResolution,
    webhook_text: str | None = None,
    webhook_author: str | None = None,
    observed_at: datetime | None = None,
) -> UUID:
    """`webhook_text`/`webhook_author`/`observed_at` (the `comments` webhook only) default
    to None, which leaves the `mentions` path exactly as it was. When given, for a comment:

    - the author is the commenter (`from.username`), never the publication's owner;
    - the network text wins; the webhook text is used when the network gives none, so the
      mention is readable even if `mentioned_comment` refuses (still ENRICHED: the content
      came from Meta, through the webhook);
    - `observed_at` (when Meta sent the change) dates the mention only when the network
      gave no creation date, so a replayed old comment is not shown as just received;
    - the same `(connection, media_id, comment_id)` already stored (e.g. first by
      `mentions`) is never duplicated: a successful network read is written to it as
      "Actualizar" would (`refresh_content`); without one, only its missing text/author
      are filled in (`fill_missing_comment_fields`).
    """
    assert resolution.tenant_id is not None and resolution.connection_id is not None
    caption: str | None = None
    text: str | None = None
    author_username: str | None = None
    media_type: str | None = None
    like_count: int | None = None
    content_posted_at = None
    enrichment_status = ENRICHMENT_OK

    try:
        if comment_id is not None:
            comment = await client.get_mentioned_comment(
                ig_user_id=ig_user_id, comment_id=comment_id
            )
            text = comment.text
            like_count = comment.like_count
            content_posted_at = comment.timestamp
        else:
            media = await client.get_mentioned_media(ig_user_id=ig_user_id, media_id=media_id)
            caption = media.caption
            author_username = media.username
            media_type = media.media_type
            like_count = media.like_count
            content_posted_at = media.timestamp
    except MentionedContentReadError as exc:
        # Never re-raise: the mention itself is still a real fact worth persisting even
        # when Meta's content endpoint refuses/fails (see module docstring). The mention
        # is still persisted below with ENRICHMENT_FAILED — this log line exists so an
        # operator can tell WHY without querying the DB and cross-referencing Meta's error
        # code table by hand; only the numeric platform code/subcode/http_status are
        # logged, never a body or any user-generated text, same discipline every sibling
        # client already keeps for its own `*ReadError`.
        enrichment_status = ENRICHMENT_FAILED
        _LOGGER.warning(
            "mentions enrichment failed, mention will be persisted as %s: media_id=%s "
            "comment_id=%s platform_code=%s platform_subcode=%s http_status=%s (%s)",
            ENRICHMENT_FAILED,
            media_id,
            comment_id,
            exc.platform_code,
            exc.platform_subcode,
            exc.http_status,
            type(exc).__name__,
        )

    network_read = enrichment_status == ENRICHMENT_OK
    network_posted_at = content_posted_at
    from_comments_webhook = comment_id is not None and (
        webhook_text is not None or webhook_author is not None
    )
    if from_comments_webhook:
        author_username = webhook_author
        if text is None and webhook_text is not None:
            text = webhook_text
            enrichment_status = ENRICHMENT_OK
        if content_posted_at is None:
            content_posted_at = observed_at

    permalink: str | None = None
    if network_read:
        # QUA-152: best-effort, AFTER the content read and in its own call — a refusal
        # leaves the mention exactly as it would be without a link, never ENRICHMENT_FAILED.
        permalink = await _read_permalink(
            client, ig_user_id=ig_user_id, media_id=media_id, comment_id=comment_id
        )

    mention = NewMention(
        tenant_id=resolution.tenant_id,
        connection_id=resolution.connection_id,
        external_account_id=ig_user_id,
        media_id=media_id,
        comment_id=comment_id,
        caption=caption,
        text=text,
        author_username=author_username,
        media_type=media_type,
        like_count=like_count,
        content_posted_at=content_posted_at,
        enrichment_status=enrichment_status,
        permalink=permalink,
    )
    repo = production_mentions_repository()
    mention_id, created = repo.upsert_mention(mention)
    if not created and from_comments_webhook:
        # Already stored (e.g. first by `mentions`, which carries no author).
        if network_read:
            # The network's current content, as "Actualizar" writes it; the author is
            # never part of a network read, so it only fills a missing one (below).
            repo.refresh_content(
                tenant_id=resolution.tenant_id,
                mention_id=mention_id,
                content=MentionContent(
                    caption=None,
                    text=text,
                    author_username=None,
                    media_type=None,
                    like_count=like_count,
                    # Never the send-time fallback: it would overwrite a real date.
                    content_posted_at=network_posted_at,
                    permalink=permalink,
                ),
            )
        repo.fill_missing_comment_fields(
            tenant_id=resolution.tenant_id,
            mention_id=mention_id,
            text=None if network_read else text,
            author_username=author_username,
        )
    return mention_id


def list_mentions_for_tenant(
    *, tenant_id: UUID, connection_id: UUID | None = None, limit: int = DEFAULT_MENTION_PAGE_SIZE
) -> tuple[MentionRecord, ...]:
    """The published read seam for both the HTTP route and the Reflex Dashboard de
    Menciones — in-process, no HTTP hop for the Reflex caller, same role
    `inbox.composition.list_candidate_media` plays for its own module."""
    return production_mentions_repository().list_mentions(
        tenant_id=tenant_id,
        connection_id=connection_id,
        version=current_mention_analysis_version(),
        limit=limit,
    )


# --- "Actualizar menciones" (QUA-152) --------------------------------------------------
#
# The button re-reads every mention of the dashboard's scope (account + period) from its
# network and stores what changed. Limits, per run:
#   - at most REFRESH_MAX_PER_RUN mentions (the rest is reported as pending and taken
#     first by the next run — least recently attempted first);
#   - REFRESH_CONCURRENCY reads in flight;
#   - a transient failure (5xx, network, Meta codes 1/2) is retried REFRESH_RETRIES times
#     with backoff; a content error (4xx: deleted, comments disabled) is not;
#   - a throttling answer from Meta, or a reported usage at/above REFRESH_USAGE_STOP_PERCENT,
#     stops the run: nothing more is requested, what is left is reported as pending;
#   - a mention re-read successfully in the last REFRESH_FRESH_SECONDS is current and is
#     not requested again (two tabs, a double click);
#   - a mention Meta reports unavailable (`is_gone`: deleted, made private, blocked) is
#     marked removed and stops showing — once per connection and run, the account itself
#     is confirmed readable first, since the same answer can be about the account (then
#     it is an account problem: nothing is removed). Not a failure: nothing to read;
#   - with the capacity left (at most REMOVED_RECHECK_PER_RUN), removed mentions not tried
#     for REMOVED_RECHECK_SECONDS and removed no longer than REMOVED_RECHECK_MAX_AGE_SECONDS
#     ago are re-read: one that answers shows again (`restored`).
# One read per mention; the link only while it is not stored yet (it does not change).

REFRESH_MAX_PER_RUN = 200
REFRESH_CONCURRENCY = 4
REFRESH_RETRIES = 2
REFRESH_BACKOFF_SECONDS = (1.0, 3.0)
REFRESH_USAGE_STOP_PERCENT = 75
REFRESH_FRESH_SECONDS = 60

_Outcome = Literal[
    "refreshed",
    "failed",
    "not_attempted",
    "credential_failed",
    "removed",
    "restored",  # a removed mention answered again: it shows again
    "unchanged",  # a removed mention re-checked and still unavailable: not reported
]
_AccountState = Literal["ok", "account_gone", "unknown"]


class _RateLimited(Exception):
    """Meta throttled a read: the run stops dispatching."""


@dataclass(frozen=True)
class ContentRefreshReport:
    """How one refresh run left its scope. It is COMPLETE only when every mention of the
    scope is current; anything else is pending and must be reported as such."""

    in_scope: int  # mentions in the scope (the visible page, or account + period)
    refreshed: int  # re-read and stored in this run
    already_fresh: int  # re-read successfully moments ago — not requested again
    failed: int  # the network refused or failed after retries; stored data kept
    not_attempted: int  # left for a later run: the per-run cap or Meta's throttling
    rate_limited: bool = False  # Meta answered with a throttling error
    usage_paused: bool = False  # Meta's reported usage reached REFRESH_USAGE_STOP_PERCENT
    planning_failed: bool = False  # the run could not even list its scope
    # Not readable because the CONNECTION has no usable credential (revoked, undecryptable):
    # an account problem, not the mention's — never stamped as an attempt on the mention.
    credential_failed: int = 0
    # The network says the content is no longer available (deleted, made private, the
    # author blocked the account): the mention left the dashboard (migration 0062).
    # Neither current nor pending — it left the scope.
    removed: int = 0
    # Removed mentions re-checked (outside the scope's counts) that answered again and
    # show again.
    restored: int = 0

    @property
    def remaining_scope(self) -> int:
        """The scope once the removed mentions left it — what "N de M" counts."""
        return self.in_scope - self.removed

    @property
    def pending(self) -> int:
        return self.failed + self.not_attempted + self.credential_failed

    @property
    def complete(self) -> bool:
        return self.pending == 0 and not self.planning_failed


async def refresh_mentions_content(
    *, tenant_id: UUID, mention_ids: tuple[UUID, ...]
) -> ContentRefreshReport:
    """The VISIBLE page, right away (QUA-152): always re-read, whatever their freshness —
    it is what the person is looking at. Nothing raises out of here."""
    repo = production_mentions_repository()
    try:
        targets = await asyncio.to_thread(
            repo.list_refresh_targets, tenant_id=tenant_id, mention_ids=mention_ids
        )
    except Exception as exc:  # noqa: BLE001 — reported, never raised into the UI
        _LOGGER.warning("mentions visible refresh could not start (%s)", type(exc).__name__)
        return ContentRefreshReport(
            in_scope=len(mention_ids),
            refreshed=0,
            already_fresh=0,
            failed=0,
            not_attempted=len(mention_ids),
        )
    return await _refresh_targets(
        repo, tenant_id=tenant_id, targets=targets, in_scope=len(targets), already_fresh=0
    )


async def refresh_mentions_in_scope(
    *, tenant_id: UUID, scope: MentionQuery, max_mentions: int = REFRESH_MAX_PER_RUN
) -> ContentRefreshReport:
    """One bounded run over the SCOPE — the account and period of `scope` (origin,
    sentiment and search never narrow it). Nothing raises out of here; a failure to even
    plan the run is reported as everything pending."""
    repo = production_mentions_repository()
    try:
        plan = await asyncio.to_thread(
            repo.plan_scope_refresh,
            tenant_id=tenant_id,
            query=scope,
            fresh_seconds=REFRESH_FRESH_SECONDS,
            limit=max_mentions,
        )
    except Exception as exc:  # noqa: BLE001 — reported, never raised into the UI
        _LOGGER.warning("mentions scope refresh could not be planned (%s)", type(exc).__name__)
        return ContentRefreshReport(
            in_scope=0,
            refreshed=0,
            already_fresh=0,
            failed=0,
            not_attempted=0,
            planning_failed=True,
        )
    return await _refresh_targets(
        repo,
        tenant_id=tenant_id,
        targets=plan.targets,
        in_scope=plan.in_scope,
        already_fresh=plan.fresh,
        recently_failed=plan.recently_failed,
    )


async def _refresh_targets(
    repo: MentionsRepository,
    *,
    tenant_id: UUID,
    targets: tuple[RefreshTarget, ...],
    in_scope: int,
    already_fresh: int,
    recently_failed: int = 0,
) -> ContentRefreshReport:
    """Every repository call runs in a worker thread (`asyncio.to_thread`): this coroutine
    runs on the Reflex backend's event loop, which serves every other session too."""
    clients: dict[UUID, tuple[HttpMentionedContentClient, str] | None] = {}
    clients_lock = asyncio.Lock()
    slots = asyncio.Semaphore(REFRESH_CONCURRENCY)
    stop = asyncio.Event()  # no new reads: throttled, or usage at the limit
    throttled = asyncio.Event()
    usage_paused = asyncio.Event()
    # connection -> the state of its account node, checked only when a read says "does
    # not exist" (see `is_gone`). A settled answer is kept for the run; an `unknown` one is
    # dropped so the next mention asks again. Registered without awaiting: no lock, so it
    # never waits behind another connection's credential resolution.
    accounts: dict[UUID, asyncio.Task[_AccountState]] = {}

    async def client_for(connection_id: UUID) -> tuple[HttpMentionedContentClient, str] | None:
        async with clients_lock:  # ONE credential resolution per connection and run
            if connection_id not in clients:
                try:
                    clients[connection_id] = await _content_client_for(
                        tenant_id=tenant_id, connection_id=connection_id
                    )
                except Exception as exc:  # noqa: BLE001 — cached: never retried per mention
                    _LOGGER.warning(
                        "mentions refresh: connection=%s has no usable credential (%s)",
                        connection_id,
                        type(exc).__name__,
                    )
                    clients[connection_id] = None
            return clients[connection_id]

    def on_throttle() -> None:
        throttled.set()
        stop.set()

    def watch_usage(client: HttpMentionedContentClient) -> None:
        if getattr(client, "usage_percent", 0) >= REFRESH_USAGE_STOP_PERCENT:
            usage_paused.set()
            stop.set()
            _LOGGER.warning("mentions refresh paused: Meta usage at or above the limit")

    async def account_state(
        client: HttpMentionedContentClient, ig_user_id: str, connection_id: UUID
    ) -> _AccountState:
        task = accounts.get(connection_id)
        if task is None:
            task = asyncio.ensure_future(_account_state(client, ig_user_id))
            accounts[connection_id] = task
        state = await task
        if state == "unknown" and accounts.get(connection_id) is task:
            del accounts[connection_id]
        return state

    async def store(target: RefreshTarget, content: MentionContent) -> bool | None:
        """True stored, False not this tenant's, None the database failed."""
        try:
            return await asyncio.to_thread(
                repo.refresh_content,
                tenant_id=tenant_id,
                mention_id=target.mention_id,
                content=content,
            )
        except Exception as exc:  # noqa: BLE001 — a DB error on one row, not the run
            _LOGGER.warning(
                "mentions refresh could not store: mention=%s (%s)",
                target.mention_id,
                type(exc).__name__,
            )
            return None

    async def stamp_attempt(target: RefreshTarget) -> None:
        await asyncio.to_thread(
            _mark_attempt, repo, tenant_id=tenant_id, mention_id=target.mention_id
        )

    async def recheck_removed(target: RefreshTarget) -> _Outcome:
        """A removed mention, re-read with the spare capacity left once every live mention
        is done: it shows again only if it answers. Nothing about it is reported unless it
        comes back, and a throttling answer here only ends the rechecks — it never turns
        the run into a "limited" one the person has to retry."""
        async with slots:
            if stop.is_set():
                return "unchanged"
            client_and_user = await client_for(target.connection_id)
            if client_and_user is None:
                # Stamped all the same: an unreadable connection's removed mentions must
                # not stay first in line and starve every other connection's rechecks.
                await stamp_attempt(target)
                return "unchanged"
            client, ig_user_id = client_and_user
            try:
                content = await _read_content(
                    client, ig_user_id=ig_user_id, target=target, on_throttle=stop.set
                )
            except _RateLimited:
                stop.set()
                return "unchanged"
            except Exception:  # noqa: BLE001 — still unavailable (or unknown): stays removed
                await stamp_attempt(target)
                return "unchanged"
            finally:
                watch_usage(client)
            if await store(target, content):
                _LOGGER.info("mentions refresh restored a mention: mention=%s", target.mention_id)
                return "restored"
            return "unchanged"

    async def refresh_one(target: RefreshTarget) -> _Outcome:
        async with slots:
            if stop.is_set():
                return "not_attempted"
            client_and_user = await client_for(target.connection_id)
            if client_and_user is None:
                return "credential_failed"
            client, ig_user_id = client_and_user
            # Taken BEFORE the read: only a successful read that lands after this moment
            # (another tab, the comments webhook) can keep a refused mention from removal.
            # Compared with `content_refreshed_at`, which Postgres stamps: app and database
            # share the host clock (compose locally, one VPS in production).
            read_started = datetime.now(UTC)
            try:
                content = await _read_content(
                    client, ig_user_id=ig_user_id, target=target, on_throttle=on_throttle
                )
            except _RateLimited:
                on_throttle()
                _LOGGER.warning("mentions refresh stopped: Meta is throttling this account")
                return "not_attempted"
            except MentionedContentReadError as exc:
                watch_usage(client)
                if is_gone(exc):
                    try:
                        account = await account_state(client, ig_user_id, target.connection_id)
                    except _RateLimited:
                        on_throttle()
                        return "not_attempted"
                    watch_usage(client)  # the account check is a Graph call too
                    if account == "account_gone":
                        # The "does not exist" is about the account: nothing is removed.
                        _LOGGER.warning(
                            "mentions refresh: connection=%s account node not readable",
                            target.connection_id,
                        )
                        return "credential_failed"
                    if account == "ok":
                        removed = await asyncio.to_thread(
                            _mark_removed,
                            repo,
                            tenant_id=tenant_id,
                            mention_id=target.mention_id,
                            read_started=read_started,
                        )
                        if removed is not None:
                            _LOGGER.info(
                                "mentions refresh: mention=%s %s",
                                target.mention_id,
                                "removed (unavailable)" if removed else "read meanwhile, kept",
                            )
                            # Not removed = a successful read landed after this one started
                            # (another tab, the comments webhook): it exists and is current.
                            return "removed" if removed else "refreshed"
                    # The account check itself failed (network, 5xx), or the removal could
                    # not be written: never remove on a doubt — a plain failure, asked
                    # again later.
                # Error codes only, never the body: they are what tells a deleted object
                # apart from any other refusal when this path is checked in production.
                _LOGGER.info(
                    "mentions refresh kept stored content: mention=%s (%s http=%s code=%s "
                    "subcode=%s)",
                    target.mention_id,
                    type(exc).__name__,
                    exc.http_status,
                    exc.platform_code,
                    exc.platform_subcode,
                )
                await stamp_attempt(target)
                return "failed"
            except Exception as exc:  # noqa: BLE001 — keep the stored data, log the type only
                _LOGGER.info(
                    "mentions refresh kept stored content: mention=%s (%s)",
                    target.mention_id,
                    type(exc).__name__,
                )
                await stamp_attempt(target)
                return "failed"
            watch_usage(client)
            return "refreshed" if await store(target, content) else "failed"

    async def run_all(
        batch: list[RefreshTarget],
        one: Callable[[RefreshTarget], Awaitable[_Outcome]],
        *,
        on_error: _Outcome,
    ) -> list[_Outcome]:
        """Every coroutine settles before this returns — an unexpected error in one never
        leaves the others running against clients the `finally` below closes."""
        results = await asyncio.gather(*(one(target) for target in batch), return_exceptions=True)
        outcomes: list[_Outcome] = []
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                _LOGGER.warning("mentions refresh: unexpected error (%s)", type(result).__name__)
                outcomes.append(on_error)
            else:
                outcomes.append(result)
        return outcomes

    live = [target for target in targets if not target.removed]
    rechecks = [target for target in targets if target.removed]
    try:
        outcomes = await run_all(live, refresh_one, on_error="failed")
        # Removed mentions only with what the live ones left: never competing for the
        # slots, the usage budget or the throttling answer of what the person asked for.
        if rechecks and not stop.is_set():
            outcomes += await run_all(rechecks, recheck_removed, on_error="unchanged")
    finally:
        # A cancelled run may leave an account check in flight: cancel it, wait until it
        # has settled (its exception retrieved), and only then close the clients it uses.
        for task in accounts.values():
            task.cancel()
        await asyncio.gather(*accounts.values(), return_exceptions=True)
        for client_and_user in clients.values():
            if client_and_user is not None:
                await _close_client(client_and_user[0])
    planned_but_left = in_scope - already_fresh - recently_failed - len(live)
    return ContentRefreshReport(
        in_scope=in_scope,
        refreshed=outcomes.count("refreshed"),
        already_fresh=already_fresh,
        # A mention whose re-read failed moments ago (the visible pass of this same click)
        # is reported as failed, not requested again.
        failed=outcomes.count("failed") + recently_failed,
        credential_failed=outcomes.count("credential_failed"),
        removed=outcomes.count("removed"),
        restored=outcomes.count("restored"),
        not_attempted=outcomes.count("not_attempted") + max(0, planned_but_left),
        rate_limited=throttled.is_set(),
        usage_paused=usage_paused.is_set() and not throttled.is_set(),
    )


def _mark_attempt(repo: MentionsRepository, *, tenant_id: UUID, mention_id: UUID) -> None:
    try:
        repo.mark_refresh_attempt(tenant_id=tenant_id, mention_id=mention_id)
    except Exception as exc:  # noqa: BLE001 — bookkeeping only
        _LOGGER.info("mentions refresh attempt not stamped (%s)", type(exc).__name__)


async def _account_state(client: HttpMentionedContentClient, ig_user_id: str) -> _AccountState:
    """Whether the connected account's node is readable — retried like a content read.
    `account_gone` only for an answer about the account itself ("does not exist", or an
    expired/revoked token); anything else unresolved is `unknown`. Raises `_RateLimited`
    when Meta throttles the check."""
    try:
        await _with_retries(lambda: client.account_reachable(ig_user_id=ig_user_id))
    except _RateLimited:
        raise
    except MentionedContentReadError as exc:
        auth = is_auth_error(http_status=exc.http_status, platform_code=exc.platform_code)
        return "account_gone" if is_gone(exc) or auth else "unknown"
    except Exception:  # noqa: BLE001 — network or anything else: never remove on a doubt
        return "unknown"
    return "ok"


def _mark_removed(
    repo: MentionsRepository, *, tenant_id: UUID, mention_id: UUID, read_started: datetime
) -> bool | None:
    """`repo.mark_removed`'s answer, or None when the write fails (the mention then counts
    as failed and keeps showing; the next run sees the same answer again)."""
    try:
        return repo.mark_removed(
            tenant_id=tenant_id, mention_id=mention_id, unless_read_after=read_started
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("mentions refresh could not remove (%s)", type(exc).__name__)
        return None


async def _read_content(
    client: HttpMentionedContentClient,
    *,
    ig_user_id: str,
    target: RefreshTarget,
    on_throttle: Callable[[], None] | None = None,
) -> MentionContent:
    """The mention's content as the network gives it NOW. Raises when the content read
    fails (the caller keeps what it had) and `_RateLimited` when Meta throttles. The link
    is independent: its failure never affects the other fields."""
    if target.comment_id is not None:
        comment = await _with_retries(
            lambda: client.get_mentioned_comment(
                ig_user_id=ig_user_id, comment_id=target.comment_id
            )
        )
        caption, text, author, media_type = None, comment.text, None, None
        like_count, posted_at = comment.like_count, comment.timestamp
    else:
        media = await _with_retries(
            lambda: client.get_mentioned_media(ig_user_id=ig_user_id, media_id=target.media_id)
        )
        caption, text, author, media_type = media.caption, None, media.username, media.media_type
        like_count, posted_at = media.like_count, media.timestamp
    permalink = (
        None
        if target.has_permalink
        else await _read_permalink(
            client,
            ig_user_id=ig_user_id,
            media_id=target.media_id,
            comment_id=target.comment_id,
            on_throttle=on_throttle,
        )
    )
    return MentionContent(
        caption=caption,
        text=text,
        author_username=author,
        media_type=media_type,
        like_count=like_count,
        content_posted_at=posted_at,
        permalink=permalink,
    )


async def _with_retries[T](call: Callable[[], Awaitable[T]]) -> T:
    """One content read, retried on transient failures only — a Meta 5xx / code 1-2, or
    the network (`httpx.TransportError`, timeouts included). Meta throttling raises
    `_RateLimited` at once; a content error (4xx), a body that does not match the contract
    or any other exception raises at once."""
    for attempt in range(REFRESH_RETRIES + 1):
        try:
            return await call()
        except MentionedContentReadError as exc:
            if is_rate_limited(exc):
                raise _RateLimited from exc
            if not is_transient(exc) or attempt == REFRESH_RETRIES:
                raise
        except httpx.TransportError:
            if attempt == REFRESH_RETRIES:
                raise
        await asyncio.sleep(REFRESH_BACKOFF_SECONDS[min(attempt, len(REFRESH_BACKOFF_SECONDS) - 1)])
    raise AssertionError("unreachable")  # pragma: no cover


async def _read_permalink(
    client: HttpMentionedContentClient,
    *,
    ig_user_id: str,
    media_id: str,
    comment_id: str | None,
    on_throttle: Callable[[], None] | None = None,
) -> str | None:
    """The "Ver" link, best-effort and independent (QUA-152): ANY failure — a refusal, the
    network — leaves it unset and never touches the content read or its persistence. A
    throttling answer is still reported (`on_throttle`) so a refresh run stops asking."""
    try:
        return await client.get_mentioned_permalink(
            ig_user_id=ig_user_id, media_id=media_id, comment_id=comment_id
        )
    except MentionedContentReadError as exc:
        if on_throttle is not None and is_rate_limited(exc):
            on_throttle()
        _LOGGER.info(
            "mentions permalink unavailable: media_id=%s comment_id=%s (%s)",
            media_id,
            comment_id,
            type(exc).__name__,
        )
        return None
    except Exception as exc:  # noqa: BLE001 — the link never fails anything else
        _LOGGER.info(
            "mentions permalink unavailable: media_id=%s comment_id=%s (%s)",
            media_id,
            comment_id,
            type(exc).__name__,
        )
        return None


def list_mentions_page_for_tenant(
    *,
    tenant_id: UUID,
    query: MentionQuery,
    page: int,
    as_of: datetime | None = None,
) -> MentionPage:
    """The Dashboard de Menciones' read seam (QUA-152): one page of 12 over ALL stored
    mentions, with counts over the whole filtered set, under the snapshot `as_of`."""
    return production_mentions_repository().list_mentions_page(
        tenant_id=tenant_id,
        version=current_mention_analysis_version(),
        query=query,
        page=page,
        as_of=as_of,
    )


def summarize_mentions_for_tenant(
    *, tenant_id: UUID, query: MentionQuery, as_of: datetime
) -> MentionCounts:
    """The dashboard's summary cards (QUA-152): counts for the SCOPE query (account +
    period), under the same snapshot as the page — a search never moves them."""
    return production_mentions_repository().summarize(
        tenant_id=tenant_id,
        version=current_mention_analysis_version(),
        query=query,
        as_of=as_of,
    )


def count_new_mentions_for_tenant(*, tenant_id: UUID, query: MentionQuery, after: datetime) -> int:
    """Mentions matching `query` that arrived after the dashboard's snapshot, up to
    `NEW_MENTIONS_CAP` — what the new-mention notice shows (QUA-152)."""
    return production_mentions_repository().count_received_after(
        tenant_id=tenant_id,
        version=current_mention_analysis_version(),
        query=query,
        after=after,
    )


@cache
def current_mention_analysis_version() -> AnalysisVersion:
    """The version this deployment analyzes mentions under today. Lazy import, cached,
    same posture `sentiment.composition.current_analysis_version` documents for the
    identical reason (`qualify_models` lives in the `ml` group)."""
    from qualify_models.sentiment import DETECTOR_VERSION, MODEL_ID  # noqa: PLC0415

    return AnalysisVersion(
        detector_version=DETECTOR_VERSION,
        pipeline_version=MENTIONS_PIPELINE_VERSION,
        model_id=MODEL_ID,
        model_revision=None,
    )


@cache
def _production_mention_sentiment_service() -> MentionSentimentService:
    return MentionSentimentService(
        repository=production_mentions_repository(), version=current_mention_analysis_version()
    )


def analyze_pending_mentions(*, tenant_id: UUID) -> MentionAnalysisSummary:
    """The published seam for the manual sentiment trigger — mirrors
    `sentiment.composition.analyze_pending_comments`'s role for its own module."""
    return _production_mention_sentiment_service().analyze_pending_mentions(tenant_id=tenant_id)


def analyze_mention_after_ingest(*, tenant_id: UUID, mention_id: UUID) -> None:
    """Analyze the mention the intake processor just stored (QUA-152). NEVER raises: the
    mention is already committed and its intake event must settle exactly as it would
    without this call, so any failure — including the model being unavailable — is
    logged (class name only) and left to the worker's sweep."""
    try:
        _production_mention_sentiment_service().analyze_pending_mentions(
            tenant_id=tenant_id, mention_id=mention_id
        )
    except Exception as exc:  # noqa: BLE001 — sentiment must never fail an ingestion
        _LOGGER.warning(
            "mention sentiment after ingest skipped: mention=%s (%s)",
            mention_id,
            type(exc).__name__,
        )


# At most this many mentions per tenant per sweep. A model/pipeline version bump makes
# every stored mention pending at once; a bounded pass keeps the webhook worker claiming
# intake events between sweeps instead of analyzing everything in one go.
SENTIMENT_SWEEP_BATCH = 50


@dataclass(frozen=True)
class SentimentSweepReport:
    tenants: int
    new_results: int
    failed: int
    tenants_errored: int  # the pass raised for that tenant (model unavailable, DB error)


def sweep_pending_mention_sentiment() -> SentimentSweepReport:
    """One pass over every tenant with an Instagram connection (QUA-152): analyzes what is
    still pending (never-analyzed, or failed below the attempt limit). One tenant's error
    never stops the others; nothing here raises."""
    try:
        tenant_ids = instagram_tenant_ids()
    except Exception as exc:  # noqa: BLE001 — a sweep must never crash its worker
        _LOGGER.warning("mention sentiment sweep: tenant listing failed (%s)", type(exc).__name__)
        return SentimentSweepReport(tenants=0, new_results=0, failed=0, tenants_errored=1)

    service = _production_mention_sentiment_service()
    new_results = failed = errored = 0
    for tenant_id in tenant_ids:
        try:
            summary = service.analyze_pending_mentions(
                tenant_id=tenant_id, limit=SENTIMENT_SWEEP_BATCH
            )
        except Exception as exc:  # noqa: BLE001 — next tenant
            errored += 1
            _LOGGER.warning(
                "mention sentiment sweep: tenant=%s skipped (%s)", tenant_id, type(exc).__name__
            )
            continue
        new_results += summary.new_results
        failed += summary.failed
    return SentimentSweepReport(
        tenants=len(tenant_ids), new_results=new_results, failed=failed, tenants_errored=errored
    )
