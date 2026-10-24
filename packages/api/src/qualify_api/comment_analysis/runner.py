"""Automatic comment prioritization (m-24852204): sentiment, then commercial intent, then
the «Quieren comprar» queries — one bounded pass per connection, never raising.

Founder decision (2026-10-24): the owner opens Interacciones and finds the comments
already prioritized; the manual «Ordenar por prioridad» button is gone. This module owns
WHEN analysis runs; HOW stays where it was — `sentiment.analyze_pending_comments`
(robertuito, local), `intent.analyze_pending_intents` (Claude Haiku) and
`followups.FollowupWorkspace.open_from_intents`, each unchanged in what it writes:
versioned, append-only rows with provenance, unique per (comment, version).

## Guarantees

- **Bounded.** Each pass takes at most `batch` pending comments per connection for each
  analysis, newest first. A backlog (a version bump, a long outage) drains over several
  passes instead of one long one.
- **One pass per connection at a time.** The pass holds a non-blocking lock keyed by the
  connection (`planner.locks.PostgresAdvisoryLock`, a transaction-scoped advisory lock: no
  table, released when the process dies). A pass that finds it busy does nothing — the
  holder is already analyzing the same comments. Without it, the after-sync trigger and
  the sweep could both send the same comments to Claude (the rows would still be unique;
  the cost would not).
- **Idempotent.** Re-running a pass with nothing pending writes nothing and calls no
  model: both pending reads exclude what is recorded under the current version, and the
  classifier is never called with an empty batch.
- **Silent degradation.** No local model (`SentimentModelUnavailable`) or no Claude key
  (`IntentModelUnavailable`) skips that half with ONE warning per process and per
  reason, then debug lines; the other half still runs. Any other error is logged by class
  name only (a message could echo a comment's text) and the next pass retries. Nothing
  here ever reaches the client as an error.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from qualify_api.planner.locks import ExecutionLock

logger = logging.getLogger("qualify_api.comment_analysis")

#: Pending comments per connection per pass, for each analysis. Intent sends them to
#: Claude 25 at a time (`intent.classifier.CLAUDE_INTENT_BATCH`), so a full batch is four
#: calls; robertuito takes well under a second per comment on the server.
DEFAULT_BATCH: Final = 100

SKIP_NONE: Final = ""
SKIP_UNAVAILABLE: Final = "unavailable"
SKIP_BUSY: Final = "busy"

#: (tenant_id, connection_id, limit) -> new rows recorded.
AnalysisPass = Callable[[UUID, UUID, int], int]
#: (tenant_id, connection_id) -> queries opened.
FollowupsPass = Callable[[UUID, UUID], int]


def lock_key(connection_id: UUID) -> str:
    return f"m-24852204:comment-analysis:{connection_id}"


@dataclass(frozen=True)
class ConnectionAnalysisReport:
    """What one pass did. `sentiment_skipped`/`intent_skipped` are `""` when that half
    ran, `SKIP_UNAVAILABLE` when its model cannot run here, `SKIP_BUSY` when another pass
    held the connection, or the exception class name when it failed."""

    sentiment_new: int = 0
    intent_new: int = 0
    followups_opened: int = 0
    sentiment_skipped: str = SKIP_NONE
    intent_skipped: str = SKIP_NONE

    @property
    def changed(self) -> bool:
        """Whether the screen has something new to show."""
        return bool(self.sentiment_new or self.intent_new or self.followups_opened)

    @property
    def errored(self) -> bool:
        return any(
            skipped not in (SKIP_NONE, SKIP_UNAVAILABLE, SKIP_BUSY)
            for skipped in (self.sentiment_skipped, self.intent_skipped)
        )


@dataclass(frozen=True)
class SweepReport:
    connections: int
    sentiment_new: int
    intent_new: int
    followups_opened: int
    errored: int  # connections where a half failed (not "unavailable", not "busy")


class _WarnOnce:
    """One warning per reason per process, then debug: a deployment without the model
    would otherwise log the same line for every connection on every sweep."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._guard = threading.Lock()

    def __call__(self, reason: str, message: str, *args: object) -> None:
        with self._guard:
            first = reason not in self._seen
            self._seen.add(reason)
        logger.log(logging.WARNING if first else logging.DEBUG, message, *args)


class CommentAnalysisRunner:
    def __init__(
        self,
        *,
        sentiment: AnalysisPass,
        intent: AnalysisPass,
        open_followups: FollowupsPass,
        lock: ExecutionLock,
        sentiment_unavailable: tuple[type[BaseException], ...] = (),
        intent_unavailable: tuple[type[BaseException], ...] = (),
        batch: int = DEFAULT_BATCH,
    ) -> None:
        if batch < 1:
            raise ValueError("batch must be at least 1")
        self._sentiment = sentiment
        self._intent = intent
        self._open_followups = open_followups
        self._lock = lock
        self._sentiment_unavailable = sentiment_unavailable
        self._intent_unavailable = intent_unavailable
        self._batch = batch
        self._warn = _WarnOnce()

    def analyze_connection(
        self, *, tenant_id: UUID, connection_id: UUID
    ) -> ConnectionAnalysisReport:
        """One bounded pass over the connection. Never raises."""
        try:
            with self._lock.hold(tenant_id=tenant_id, key=lock_key(connection_id)) as acquired:
                if not acquired:
                    logger.debug("comment_analysis.busy connection=%s", connection_id)
                    return ConnectionAnalysisReport(
                        sentiment_skipped=SKIP_BUSY, intent_skipped=SKIP_BUSY
                    )
                return self._run(tenant_id, connection_id)
        except Exception as exc:  # noqa: BLE001 — the lock itself failed (DB down)
            logger.warning(
                "comment_analysis.lock_failed connection=%s error=%s",
                connection_id,
                type(exc).__name__,
            )
            name = type(exc).__name__
            return ConnectionAnalysisReport(sentiment_skipped=name, intent_skipped=name)

    def _run(self, tenant_id: UUID, connection_id: UUID) -> ConnectionAnalysisReport:
        sentiment_new, sentiment_skipped = self._half(
            "sentiment", self._sentiment, self._sentiment_unavailable, tenant_id, connection_id
        )
        intent_new, intent_skipped = self._half(
            "intent", self._intent, self._intent_unavailable, tenant_id, connection_id
        )
        followups_opened = 0
        # Only after an intent pass that ran: with no key there is nothing new to open
        # from, and `open_from_intents` drafts with the same Claude key.
        if intent_skipped == SKIP_NONE:
            try:
                followups_opened = self._open_followups(tenant_id, connection_id)
            except Exception as exc:  # noqa: BLE001 — idempotent; the next pass retries
                logger.warning(
                    "comment_analysis.followups_failed connection=%s error=%s",
                    connection_id,
                    type(exc).__name__,
                )
        report = ConnectionAnalysisReport(
            sentiment_new=sentiment_new,
            intent_new=intent_new,
            followups_opened=followups_opened,
            sentiment_skipped=sentiment_skipped,
            intent_skipped=intent_skipped,
        )
        if report.changed:
            logger.info(
                "comment_analysis.done tenant=%s connection=%s sentiment=%d intent=%d followups=%d",
                tenant_id,
                connection_id,
                sentiment_new,
                intent_new,
                followups_opened,
            )
        return report

    def _half(
        self,
        name: str,
        run: AnalysisPass,
        unavailable: tuple[type[BaseException], ...],
        tenant_id: UUID,
        connection_id: UUID,
    ) -> tuple[int, str]:
        try:
            return run(tenant_id, connection_id, self._batch), SKIP_NONE
        except unavailable as exc:
            self._warn(
                f"{name}:{type(exc).__name__}",
                "comment_analysis.%s_unavailable error=%s — comments stay without it",
                name,
                type(exc).__name__,
            )
            return 0, SKIP_UNAVAILABLE
        except Exception as exc:  # noqa: BLE001 — logged; the next pass retries
            logger.warning(
                "comment_analysis.%s_failed connection=%s error=%s",
                name,
                connection_id,
                type(exc).__name__,
            )
            return 0, type(exc).__name__

    def sweep(self, targets: Iterable[tuple[UUID, UUID]]) -> SweepReport:
        """One pass over every (tenant, connection). One connection's failure never stops
        the others; never raises."""
        connections = sentiment_new = intent_new = followups = errored = 0
        for tenant_id, connection_id in targets:
            connections += 1
            report = self.analyze_connection(tenant_id=tenant_id, connection_id=connection_id)
            sentiment_new += report.sentiment_new
            intent_new += report.intent_new
            followups += report.followups_opened
            errored += int(report.errored)
        return SweepReport(
            connections=connections,
            sentiment_new=sentiment_new,
            intent_new=intent_new,
            followups_opened=followups,
            errored=errored,
        )
