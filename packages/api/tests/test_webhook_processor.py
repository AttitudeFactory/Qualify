"""`qualify_api.webhooks.processor` (QUA-147) against an in-memory queue — offline.

Carries over the guarantees the webhook route used to test inline before QUA-147
(ORPHAN/AMBIGUOUS never ingested, RESOLVED ingested with the event's own ids, a resolved
but unpersisted mention never reads as success), now at their new home, plus the queue
behavior: unsupported fields, retries with backoff, `dead` after the last attempt.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution
from qualify_api.webhooks.processor import Outcome, Processor, mentions_handler
from qualify_api.webhooks.repository import (
    MAX_ATTEMPTS,
    ClaimedEvent,
    backoff_for,
)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
TENANT = UUID("77777777-7777-4777-8777-777777777777")
CONNECTION = UUID("88888888-8888-4888-8888-888888888888")
MENTION = UUID("99999999-9999-4999-8999-999999999999")


class FakeQueue:
    def __init__(self, events: list[ClaimedEvent], *, lose: set[UUID] | None = None) -> None:
        self.events = events
        self.settled: dict[UUID, tuple[str, str | None]] = {}
        self.failed: dict[UUID, tuple[int, str]] = {}
        self._lose = lose or set()

    def claim(self, *, worker_id: str, now: datetime, limit: int) -> list[ClaimedEvent]:
        batch, self.events = self.events[:limit], self.events[limit:]
        return batch

    def settle(self, *, event_id, worker_id, now, status, error=None) -> bool:
        if event_id in self._lose:
            return False
        self.settled[event_id] = (status, error)
        return True

    def fail(self, *, event_id, worker_id, now, attempts, error) -> str | None:
        self.failed[event_id] = (attempts, error)
        return "dead" if attempts >= MAX_ATTEMPTS else "failed"


def _event(field: str = "mentions", *, entry: str = "111", value=None, attempts: int = 1):
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="instagram",
        entry_id=entry,
        field=field,
        value={"media_id": "aaa"} if value is None else value,
        attempts=attempts,
    )


class Pipeline:
    """Fake resolver + ingestor, recording their calls."""

    def __init__(self, *, ingest_returns: UUID | None = MENTION, ingest_raises=None) -> None:
        self.resolutions: dict[str, TenantResolution] = {}
        self.resolver_calls: list[tuple[str, str]] = []
        self.ingestor_calls: list[tuple[str, str | None, TenantResolution]] = []
        self._returns = ingest_returns
        self._raises = ingest_raises

    def resolve(self, *, platform: str, external_account_id: str) -> TenantResolution:
        self.resolver_calls.append((platform, external_account_id))
        return self.resolutions.get(
            external_account_id, TenantResolution(outcome=ResolutionOutcome.ORPHAN)
        )

    async def ingest(self, *, media_id, comment_id, resolution) -> UUID | None:
        self.ingestor_calls.append((media_id, comment_id, resolution))
        if self._raises is not None:
            raise self._raises
        return self._returns

    def processor(self, queue: FakeQueue) -> Processor:
        return Processor(
            queue=queue,
            handlers={"mentions": mentions_handler(resolve=self.resolve, ingest=self.ingest)},
            worker_id="w1",
            clock=lambda: NOW,
        )


RESOLVED = TenantResolution(
    outcome=ResolutionOutcome.RESOLVED, tenant_id=TENANT, connection_id=CONNECTION
)


async def test_orphan_is_settled_orphan_and_never_ingested() -> None:
    pipeline = Pipeline()
    event = _event(entry="does-not-exist")
    queue = FakeQueue([event])

    report = await pipeline.processor(queue).run_once()

    assert pipeline.resolver_calls == [("instagram", "does-not-exist")]
    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("orphan", None)
    assert report.outcomes == {"orphan": 1}


async def test_ambiguous_is_settled_ambiguous_and_never_ingested() -> None:
    pipeline = Pipeline()
    pipeline.resolutions["shared"] = TenantResolution(outcome=ResolutionOutcome.AMBIGUOUS)
    event = _event(entry="shared")
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("ambiguous", None)


async def test_resolved_is_ingested_with_the_events_own_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pipeline = Pipeline()
    pipeline.resolutions["111"] = RESOLVED
    event = _event(value={"media_id": "aaa", "comment_id": "ccc"})
    queue = FakeQueue([event])

    with caplog.at_level("INFO"):
        await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls == [("aaa", "ccc", RESOLVED)]
    assert queue.settled[event.id] == ("processed", None)
    assert str(MENTION) in caplog.text


async def test_resolved_but_not_persisted_is_dead_and_never_reads_as_success(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pipeline = Pipeline(ingest_returns=None)
    pipeline.resolutions["111"] = RESOLVED
    event = _event()
    queue = FakeQueue([event])

    with caplog.at_level("INFO"):
        await pipeline.processor(queue).run_once()

    assert queue.settled[event.id] == ("dead", "resolved_not_persisted")
    assert "resolved but NOT persisted" in caplog.text
    assert "mentions webhook: resolved tenant=" not in caplog.text


async def test_an_off_contract_mentions_value_is_dead_without_resolving() -> None:
    pipeline = Pipeline()
    event = _event(value={"no_media_id": True})
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.resolver_calls == []
    assert queue.settled[event.id] == ("dead", "contract_violation")


async def test_comments_and_unknown_fields_are_unsupported_and_untouched() -> None:
    pipeline = Pipeline()
    comment = _event("comments", value={"id": "c1", "text": "hola"})
    other = _event("story_insights", value={})
    queue = FakeQueue([comment, other])

    report = await pipeline.processor(queue).run_once()

    assert pipeline.resolver_calls == []
    assert pipeline.ingestor_calls == []
    assert queue.settled[comment.id] == ("unsupported", None)
    assert queue.settled[other.id] == ("unsupported", None)
    assert report.outcomes == {"unsupported": 2}


async def test_an_exception_is_a_retry_not_a_settlement() -> None:
    pipeline = Pipeline(ingest_raises=RuntimeError("db blip"))
    pipeline.resolutions["111"] = RESOLVED
    event = _event(attempts=2)
    queue = FakeQueue([event])

    report = await pipeline.processor(queue).run_once()

    assert event.id not in queue.settled
    assert queue.failed[event.id] == (2, "RuntimeError")  # the type only, never the text
    assert report.outcomes == {"failed": 1}


async def test_the_last_attempt_failing_is_dead() -> None:
    pipeline = Pipeline(ingest_raises=RuntimeError("still down"))
    pipeline.resolutions["111"] = RESOLVED
    event = _event(attempts=MAX_ATTEMPTS)
    queue = FakeQueue([event])

    report = await pipeline.processor(queue).run_once()

    assert report.outcomes == {"dead": 1}


async def test_a_lost_lock_is_counted_not_settled() -> None:
    event = _event("comments")
    queue = FakeQueue([event], lose={event.id})

    report = await Pipeline().processor(queue).run_once()

    assert report.lost == 1
    assert report.outcomes == {}


async def test_one_failing_event_does_not_stop_the_batch() -> None:
    pipeline = Pipeline()
    pipeline.resolutions["111"] = RESOLVED

    calls = 0

    async def flaky(*, media_id, comment_id, resolution):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("first one fails")
        return MENTION

    processor = Processor(
        queue=(queue := FakeQueue([_event(), _event(value={"media_id": "bbb"})])),
        handlers={"mentions": mentions_handler(resolve=pipeline.resolve, ingest=flaky)},
        worker_id="w1",
        clock=lambda: NOW,
    )
    report = await processor.run_once()

    assert report.outcomes == {"failed": 1, "processed": 1}
    assert len(queue.failed) == 1


def test_backoff_schedule() -> None:
    assert [backoff_for(n).total_seconds() for n in range(1, 6)] == [
        60,
        300,
        1800,
        7200,
        43200,
    ]


def test_an_outcome_is_a_value_object() -> None:
    assert Outcome("processed") == Outcome("processed", None)
