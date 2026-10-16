"""Settle recorded webhook changes, outside the HTTP request (QUA-147).

One `run_once` = claim a batch from the intake queue, hand each change to the handler
for its `(object, field)`, settle it. A handler returns the outcome; an exception is a RETRYABLE
failure (backoff, then `dead` after `MAX_ATTEMPTS`) — so a database blip or a crash
loses nothing, and a reclaimed change is safe to replay because the handler's write is
itself idempotent (`uq_mention_natural_key` for mentions).

Handlers: `mentions` — the same resolution + ingestion the webhook route did
inline before QUA-147 (`mentions.resolve.resolve_external_account` +
`mentions.composition.ingest_mention`, both unchanged in behavior):

- `ORPHAN` / `AMBIGUOUS` → settled `orphan` / `ambiguous`; NEVER reaches the ingestor,
  so it can never become a row associated with any tenant (QUA-97's invariant).
- `RESOLVED` → ingested → `processed`. An ingestor that returns `None` (tenant resolved
  but nothing persisted) is settled `dead` with that reason: retrying cannot fix it, and
  it must never read as a success.
- A `mentions` value that is not the documented shape → `dead` (`contract_violation`).

Handlers are keyed by `"<object>:<field>"` first and by bare `field` second (WA-07).
Meta reuses field names across products — `messages` is both an Instagram DM change
(`object = "instagram"`) and a WhatsApp change (`object = "whatsapp_business_account"`)
— so a handler that must see only one product registers under the qualified key;
`mentions` keeps its bare key and keeps working untouched. `production_processor`
registers `whatsapp_business_account:messages` → `qualify_api.whatsapp.handler`.

Instagram `comments` (`instagram:comments`): a comment on media the connected account
owns. Meta delivers a comment there that @mentions the account under THIS field — with its
text and author — not under `mentions`; `comment_mentions_handler` turns exactly those into
mentions (`mentions.composition.ingest_mention` with the webhook's text and author: same
natural key, so the same comment arriving by both fields is one row). Every other comment
stays `unsupported`, as before, with the reason in `last_error`.

Every other change is settled `unsupported` and kept: it stays in the log, replayable once
its handler exists. The comment polling is untouched.

The intake is not Meta-only any more: `qualify_api.meegle` records Meegle Event Listener
calls as `object = "meegle"`, `field = "<event_type>"` and registers its handlers here
(`production_meegle_handlers`), same queue, same `Outcome` contract; `qualify_api.mail`
does the same for Resend's delivery webhooks (`object = "resend"`, `field = "email.<x>"`,
`production_resend_handlers`).
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from pydantic import ValidationError
from qualify_shared.social.ig_shapes import (
    CommentsChangeValue,
    MentionsChangeValue,
    mentions_username,
    normalize_handle,
)

from qualify_api.mentions.resolve import (
    PLATFORM_INSTAGRAM,
    ResolutionOutcome,
    TenantResolution,
)
from qualify_api.webhooks.repository import (
    COMMENT_USERNAME_UNKNOWN,
    STATUS_AMBIGUOUS,
    STATUS_DEAD,
    STATUS_ORPHAN,
    STATUS_PROCESSED,
    STATUS_UNSUPPORTED,
    ClaimedEvent,
)

logger = logging.getLogger("qualify_api.webhooks.processor")

DEFAULT_BATCH = 50

TenantResolver = Callable[..., TenantResolution]
MentionIngestor = Callable[..., Awaitable[UUID | None]]
UsernameReader = Callable[..., str | None]
MentionAnalyzer = Callable[..., None]


@dataclass(frozen=True)
class Outcome:
    status: str
    error: str | None = None


Handler = Callable[[ClaimedEvent], Awaitable[Outcome]]


class Queue(Protocol):
    def claim(self, *, worker_id: str, now: datetime, limit: int) -> list[ClaimedEvent]: ...

    def settle(
        self,
        *,
        event_id: UUID,
        worker_id: str,
        now: datetime,
        status: str,
        error: str | None = None,
    ) -> bool: ...

    def fail(
        self, *, event_id: UUID, worker_id: str, now: datetime, attempts: int, error: str
    ) -> str | None: ...


@dataclass
class ProcessReport:
    claimed: int = 0
    outcomes: Counter[str] = field(default_factory=Counter)
    lost: int = 0  # settled by someone else meanwhile (this worker's lock went stale)


def mentions_handler(
    *,
    resolve: TenantResolver,
    ingest: MentionIngestor,
    analyze: MentionAnalyzer | None = None,
) -> Handler:
    """`analyze` (QUA-152) runs after the mention is persisted. Its result and any error
    it raises are ignored: the outcome is decided before it runs and never changes."""

    async def handle(event: ClaimedEvent) -> Outcome:
        try:
            value = MentionsChangeValue.model_validate(event.value or {})
        except ValidationError:
            logger.error("meta webhook: event=%s mentions value off-contract", event.id)
            return Outcome(STATUS_DEAD, "contract_violation")

        # Sync DB read — off the event loop.
        resolution = await asyncio.to_thread(
            resolve, platform=PLATFORM_INSTAGRAM, external_account_id=event.entry_id
        )
        if resolution.outcome is ResolutionOutcome.ORPHAN:
            logger.warning(
                "mentions webhook: orphan event, no connection for external_account_id=%s — "
                "not persisted",
                event.entry_id,
            )
            return Outcome(STATUS_ORPHAN)
        if resolution.outcome is not ResolutionOutcome.RESOLVED:
            logger.error(
                "mentions webhook: AMBIGUOUS external_account_id=%s matches more than one "
                "tenant — event dropped, not associated with any of them, not persisted",
                event.entry_id,
            )
            return Outcome(STATUS_AMBIGUOUS)

        mention_id = await ingest(
            media_id=value.media_id, comment_id=value.comment_id, resolution=resolution
        )
        if mention_id is None:
            logger.warning(
                "mentions webhook: tenant=%s connection=%s media_id=%s comment_id=%s "
                "resolved but NOT persisted — connection has no readable "
                "external_account_id (see composition._content_client_for)",
                resolution.tenant_id,
                resolution.connection_id,
                value.media_id,
                value.comment_id,
            )
            return Outcome(STATUS_DEAD, "resolved_not_persisted")
        logger.info(
            "mentions webhook: resolved tenant=%s connection=%s media_id=%s comment_id=%s "
            "mention_id=%s",
            resolution.tenant_id,
            resolution.connection_id,
            value.media_id,
            value.comment_id,
            mention_id,
        )
        await _analyze_quietly(analyze, tenant_id=resolution.tenant_id, mention_id=mention_id)
        return Outcome(STATUS_PROCESSED)

    return handle


async def _analyze_quietly(
    analyze: MentionAnalyzer | None, *, tenant_id: UUID | None, mention_id: UUID
) -> None:
    """Sentiment right after ingest. Its result and any error are ignored: the event's
    outcome is decided before it runs and never changes."""
    if analyze is None:
        return
    try:
        # Sync model call — off the event loop.
        await asyncio.to_thread(analyze, tenant_id=tenant_id, mention_id=mention_id)
    except Exception as exc:  # noqa: BLE001 — never changes the outcome
        logger.warning(
            "mentions webhook: mention_id=%s sentiment skipped (%s)",
            mention_id,
            type(exc).__name__,
        )


# `comments` changes a handler looked at and deliberately did not turn into a mention.
# Settled `unsupported` (kept, as before) with one of these reasons in `last_error`.
NOT_A_MENTION = "no_account_mention"
SELF_COMMENT = "self_comment"
INSTAGRAM_COMMENTS_HANDLER_KEY = "instagram:comments"

# `entry[].time` is documented in seconds; a value this large can only be milliseconds.
_EPOCH_MS_THRESHOLD = 10**11


def _sent_at(entry_time: int | None) -> datetime | None:
    """When Meta sent the change (`entry[].time`), or None when it is absent or absurd."""
    if entry_time is None or entry_time <= 0:
        return None
    seconds = entry_time / 1000 if entry_time >= _EPOCH_MS_THRESHOLD else entry_time
    try:
        return datetime.fromtimestamp(seconds, UTC)
    except (OverflowError, OSError, ValueError):
        return None


def comment_mentions_handler(
    *,
    resolve: TenantResolver,
    username_of: UsernameReader,
    ingest: MentionIngestor,
    analyze: MentionAnalyzer | None = None,
) -> Handler:
    """Instagram `comments` changes: a comment on media the connected account owns. Meta
    delivers a comment there that @mentions the account under THIS field, with its text
    and author — so it becomes a mention exactly when its text @mentions the connected
    account's own username (`mentions_username`: the whole handle, case-insensitive).

    - a value that is not an object → `dead` (`contract_violation`);
    - no "@" in its text → `unsupported` (`no_account_mention`), the state every comment
      had before this handler existed — decided on the raw text, BEFORE the contract
      check, so a comment that could never be a mention never turns `dead`;
    - `ORPHAN` / `AMBIGUOUS` → `orphan` / `ambiguous`, never persisted;
    - no stored username → `unsupported` (`connection_username_unknown`), replayable by
      `WebhookQueue.requeue_unsupported_comments`;
    - not this account's handle → `unsupported` (`no_account_mention`);
    - this account's handle but off-contract → `dead` (`contract_violation`), as for
      `mentions` — checked only now, so a comment tagging someone else never turns `dead`;
    - the account commenting on its own post (its id or its username in `from`) →
      `unsupported` (`self_comment`);
    - otherwise ingested (`composition.ingest_mention` with the comment's text, author and
      Meta's send time) → `processed`."""

    async def handle(event: ClaimedEvent) -> Outcome:
        if not isinstance(event.value, dict):
            logger.error("meta webhook: event=%s comments value is not an object", event.id)
            return Outcome(STATUS_DEAD, "contract_violation")
        # Cheap exit, no contract check and no database: a mention needs an "@".
        raw_text = event.value.get("text")
        if not isinstance(raw_text, str) or "@" not in raw_text:
            return Outcome(STATUS_UNSUPPORTED, NOT_A_MENTION)

        resolution = await asyncio.to_thread(
            resolve, platform=PLATFORM_INSTAGRAM, external_account_id=event.entry_id
        )
        if resolution.outcome is ResolutionOutcome.ORPHAN:
            logger.warning(
                "comments webhook: orphan event, no connection for external_account_id=%s — "
                "not persisted",
                event.entry_id,
            )
            return Outcome(STATUS_ORPHAN)
        if resolution.outcome is not ResolutionOutcome.RESOLVED:
            logger.error(
                "comments webhook: AMBIGUOUS external_account_id=%s matches more than one "
                "tenant — event dropped, not persisted",
                event.entry_id,
            )
            return Outcome(STATUS_AMBIGUOUS)

        username = await asyncio.to_thread(
            username_of, tenant_id=resolution.tenant_id, connection_id=resolution.connection_id
        )
        if not username:
            logger.warning(
                "comments webhook: connection=%s has no stored username — mention cannot be "
                "recognized, kept replayable",
                resolution.connection_id,
            )
            return Outcome(STATUS_UNSUPPORTED, COMMENT_USERNAME_UNKNOWN)
        if not mentions_username(raw_text, username):
            return Outcome(STATUS_UNSUPPORTED, NOT_A_MENTION)

        # Only a comment that DOES mention the account is held to the contract: one that
        # tags someone else never turns `dead` because of its shape.
        try:
            value = CommentsChangeValue.model_validate(event.value)
        except ValidationError:
            logger.error("meta webhook: event=%s comments value off-contract", event.id)
            return Outcome(STATUS_DEAD, "contract_violation")

        author = value.from_.username if value.from_ is not None else None
        if value.from_ is not None and (
            value.from_.id == event.entry_id
            or (author is not None and normalize_handle(author) == normalize_handle(username))
        ):
            return Outcome(STATUS_UNSUPPORTED, SELF_COMMENT)

        comment_id = value.the_comment_id
        mention_id = await ingest(
            media_id=value.media.id,
            comment_id=comment_id,
            resolution=resolution,
            text=value.text,
            author_username=author,
            observed_at=_sent_at(event.entry_time),
        )
        if mention_id is None:
            logger.warning(
                "comments webhook: tenant=%s connection=%s media_id=%s comment_id=%s "
                "resolved but NOT persisted — connection has no readable external_account_id",
                resolution.tenant_id,
                resolution.connection_id,
                value.media.id,
                comment_id,
            )
            return Outcome(STATUS_DEAD, "resolved_not_persisted")
        logger.info(
            "comments webhook: mention on own media tenant=%s connection=%s media_id=%s "
            "comment_id=%s mention_id=%s",
            resolution.tenant_id,
            resolution.connection_id,
            value.media.id,
            comment_id,
            mention_id,
        )
        await _analyze_quietly(analyze, tenant_id=resolution.tenant_id, mention_id=mention_id)
        return Outcome(STATUS_PROCESSED)

    return handle


def handler_key(object_: str, field: str) -> str:
    """The qualified key a product-specific handler registers under."""
    return f"{object_}:{field}"


class Processor:
    """`handlers` may be keyed by `handler_key(object, field)` or by bare `field`; the
    qualified key wins when both are present."""

    def __init__(
        self,
        *,
        queue: Queue,
        handlers: Mapping[str, Handler],
        worker_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._queue = queue
        self._handlers = dict(handlers)
        self._worker_id = worker_id
        self._clock = clock

    async def run_once(self, *, limit: int = DEFAULT_BATCH) -> ProcessReport:
        report = ProcessReport()
        events = self._queue.claim(worker_id=self._worker_id, now=self._clock(), limit=limit)
        report.claimed = len(events)
        for event in events:
            handler = self._handlers.get(handler_key(event.object, event.field))
            if handler is None:
                handler = self._handlers.get(event.field)
            if handler is None:
                status = self._settle(event, Outcome(STATUS_UNSUPPORTED))
            else:
                try:
                    outcome = await handler(event)
                except Exception as exc:  # noqa: BLE001 — any failure is a retry, logged
                    status = self._queue.fail(
                        event_id=event.id,
                        worker_id=self._worker_id,
                        now=self._clock(),
                        attempts=event.attempts,
                        error=type(exc).__name__,
                    )
                    logger.warning(
                        "meta webhook: event=%s object=%s field=%s attempt=%d failed (%s) -> %s",
                        event.id,
                        event.object,
                        event.field,
                        event.attempts,
                        type(exc).__name__,
                        status,
                    )
                else:
                    status = self._settle(event, outcome)
            if status is None:
                report.lost += 1
            else:
                report.outcomes[status] += 1
        return report

    def _settle(self, event: ClaimedEvent, outcome: Outcome) -> str | None:
        ok = self._queue.settle(
            event_id=event.id,
            worker_id=self._worker_id,
            now=self._clock(),
            status=outcome.status,
            error=outcome.error,
        )
        return outcome.status if ok else None


def production_processor(*, worker_id: str) -> Processor:
    """The real queue (`qualify_webhook_worker`), the real mentions pipeline, the real
    WhatsApp inbound handler (WA-07) and the template webhooks (WA-18). Imported lazily
    so building a processor for tests never pulls the Meta/credential stack."""
    from qualify_api.mail.handlers import production_resend_handlers  # noqa: PLC0415
    from qualify_api.meegle.handlers import production_meegle_handlers  # noqa: PLC0415
    from qualify_api.mentions.composition import (  # noqa: PLC0415
        analyze_mention_after_ingest,
        connection_username,
        ingest_mention,
    )
    from qualify_api.mentions.resolve import resolve_external_account  # noqa: PLC0415
    from qualify_api.webhooks.repository import WebhookQueue  # noqa: PLC0415
    from qualify_api.whatsapp.campaigns import PostgresCampaignReceiptRepository  # noqa: PLC0415
    from qualify_api.whatsapp.catalog import load_catalog_for_phone  # noqa: PLC0415
    from qualify_api.whatsapp.handler import (  # noqa: PLC0415
        WHATSAPP_MESSAGES_HANDLER_KEY,
        whatsapp_messages_handler,
    )
    from qualify_api.whatsapp.menus import load_published_menu_for_phone  # noqa: PLC0415
    from qualify_api.whatsapp.optins import PostgresOptOutRepository  # noqa: PLC0415
    from qualify_api.whatsapp.repository import PostgresWhatsAppInboxRepository  # noqa: PLC0415
    from qualify_api.whatsapp.resolve import resolve_phone_number  # noqa: PLC0415
    from qualify_api.whatsapp.templates import (  # noqa: PLC0415
        TEMPLATE_QUALITY_HANDLER_KEY,
        TEMPLATE_STATUS_HANDLER_KEY,
        production_template_handler,
    )

    # WA-18: one handler for both template fields, keyed by the envelope's WABA id.
    template_handler = production_template_handler()
    return Processor(
        queue=WebhookQueue(),
        handlers={
            "mentions": mentions_handler(
                resolve=resolve_external_account,
                ingest=ingest_mention,
                analyze=analyze_mention_after_ingest,
            ),
            # A comment on the account's own media that @mentions it (Meta sends it as
            # `comments`, not `mentions`).
            INSTAGRAM_COMMENTS_HANDLER_KEY: comment_mentions_handler(
                resolve=resolve_external_account,
                username_of=connection_username,
                ingest=ingest_mention,
                analyze=analyze_mention_after_ingest,
            ),
            # WA-15: `products` nodes render the number's brand catalog (`brand_products`).
            WHATSAPP_MESSAGES_HANDLER_KEY: whatsapp_messages_handler(
                resolve=resolve_phone_number,
                repo=PostgresWhatsAppInboxRepository(),
                menu_loader=load_published_menu_for_phone,
                catalog_loader=load_catalog_for_phone,
                # WA-19: an inbound STOP/BAJA/CANCELAR revokes the sender's opt-in.
                opt_outs=PostgresOptOutRepository(),
                # WA-20: delivery receipts of campaign sends, by wamid.
                campaign_receipts=PostgresCampaignReceiptRepository(),
            ),
            TEMPLATE_STATUS_HANDLER_KEY: template_handler,
            TEMPLATE_QUALITY_HANDLER_KEY: template_handler,
            # Meegle onboarding (plan-altas-meegle M1): `meegle:2001|1005|2004`, only when
            # QUALIFY_MEEGLE_* is set; otherwise those events stay `unsupported`.
            **production_meegle_handlers(),
            # Resend delivery trail (plan-altas-meegle M2): `resend:email.delivered|opened|
            # bounced` → `signup_invites` columns, then the Meegle item when configured.
            **production_resend_handlers(),
        },
        worker_id=worker_id,
    )
