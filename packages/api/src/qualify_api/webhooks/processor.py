"""Settle recorded webhook changes, outside the HTTP request (QUA-147).

One `run_once` = claim a batch from the intake queue, hand each change to the handler
for its `(object, field)`, settle it. A handler returns the outcome; an exception is a RETRYABLE
failure (backoff, then `dead` after `MAX_ATTEMPTS`) — so a database blip or a crash
loses nothing, and a reclaimed change is safe to replay because the handler's write is
itself idempotent (`uq_mention_natural_key` for mentions).

Handlers today: `mentions` only — the same resolution + ingestion the webhook route did
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

Every other change — Instagram `comments` included — is settled `unsupported` and kept:
it stays in the log, replayable once its handler exists. The comment polling is untouched.
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
from qualify_shared.social.ig_shapes import MentionsChangeValue

from qualify_api.mentions.resolve import (
    PLATFORM_INSTAGRAM,
    ResolutionOutcome,
    TenantResolution,
)
from qualify_api.webhooks.repository import (
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
        if analyze is not None:
            try:
                # Sync model call — off the event loop.
                await asyncio.to_thread(
                    analyze, tenant_id=resolution.tenant_id, mention_id=mention_id
                )
            except Exception as exc:  # noqa: BLE001 — never changes the outcome below
                logger.warning(
                    "mentions webhook: mention_id=%s sentiment skipped (%s)",
                    mention_id,
                    type(exc).__name__,
                )
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
    """The real queue (`qualify_webhook_worker`), the real mentions pipeline and the real
    WhatsApp inbound handler (WA-07). Imported lazily so building a processor for tests
    never pulls the Meta/credential stack."""
    from qualify_api.mentions.composition import (  # noqa: PLC0415
        analyze_mention_after_ingest,
        ingest_mention,
    )
    from qualify_api.mentions.resolve import resolve_external_account  # noqa: PLC0415
    from qualify_api.webhooks.repository import WebhookQueue  # noqa: PLC0415
    from qualify_api.whatsapp.handler import (  # noqa: PLC0415
        WHATSAPP_MESSAGES_HANDLER_KEY,
        whatsapp_messages_handler,
    )
    from qualify_api.whatsapp.repository import PostgresWhatsAppInboxRepository  # noqa: PLC0415
    from qualify_api.whatsapp.resolve import resolve_phone_number  # noqa: PLC0415

    return Processor(
        queue=WebhookQueue(),
        handlers={
            "mentions": mentions_handler(
                resolve=resolve_external_account,
                ingest=ingest_mention,
                analyze=analyze_mention_after_ingest,
            ),
            WHATSAPP_MESSAGES_HANDLER_KEY: whatsapp_messages_handler(
                resolve=resolve_phone_number,
                repo=PostgresWhatsAppInboxRepository(),
            ),
        },
        worker_id=worker_id,
    )
