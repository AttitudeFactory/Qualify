"""`qualify_api.webhooks.processor` (QUA-147) against an in-memory queue — offline.

Carries over the guarantees the webhook route used to test inline before QUA-147
(ORPHAN/AMBIGUOUS never ingested, RESOLVED ingested with the event's own ids, a resolved
but unpersisted mention never reads as success), now at their new home, plus the queue
behavior: unsupported fields, retries with backoff, `dead` after the last attempt.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution
from qualify_api.webhooks.processor import (
    INSTAGRAM_COMMENTS_HANDLER_KEY,
    NOT_A_MENTION,
    SELF_COMMENT,
    Outcome,
    Processor,
    comment_mentions_handler,
    handler_key,
    mentions_handler,
)
from qualify_api.webhooks.repository import (
    COMMENT_USERNAME_UNKNOWN,
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


def _event(
    field: str = "mentions",
    *,
    entry: str = "111",
    value=None,
    attempts: int = 1,
    object_: str = "instagram",
):
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object=object_,
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


class Analyzer:
    """Fake after-ingest sentiment step (QUA-152)."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[tuple[UUID, UUID]] = []
        self._raises = raises

    def __call__(self, *, tenant_id: UUID, mention_id: UUID) -> None:
        self.calls.append((tenant_id, mention_id))
        if self._raises is not None:
            raise self._raises


def _processor_with(pipeline: Pipeline, analyzer: Analyzer, queue: FakeQueue) -> Processor:
    handler = mentions_handler(resolve=pipeline.resolve, ingest=pipeline.ingest, analyze=analyzer)
    return Processor(queue=queue, handlers={"mentions": handler}, worker_id="w1", clock=lambda: NOW)


async def test_a_persisted_mention_is_analyzed_after_ingest() -> None:
    pipeline = Pipeline()
    pipeline.resolutions["111"] = RESOLVED
    analyzer = Analyzer()
    event = _event()
    queue = FakeQueue([event])

    await _processor_with(pipeline, analyzer, queue).run_once()

    assert analyzer.calls == [(TENANT, MENTION)]
    assert queue.settled[event.id] == ("processed", None)


async def test_a_sentiment_failure_never_changes_the_outcome() -> None:
    pipeline = Pipeline()
    pipeline.resolutions["111"] = RESOLVED
    analyzer = Analyzer(raises=RuntimeError("model exploded"))
    event = _event()
    queue = FakeQueue([event])

    report = await _processor_with(pipeline, analyzer, queue).run_once()

    assert analyzer.calls == [(TENANT, MENTION)]
    assert queue.settled[event.id] == ("processed", None)
    assert queue.failed == {}
    assert report.outcomes == {"processed": 1}


async def test_nothing_is_analyzed_when_nothing_was_persisted() -> None:
    pipeline = Pipeline(ingest_returns=None)
    pipeline.resolutions["111"] = RESOLVED
    analyzer = Analyzer()
    orphan = _event(entry="999")
    unpersisted = _event()
    queue = FakeQueue([orphan, unpersisted])

    await _processor_with(pipeline, analyzer, queue).run_once()

    assert analyzer.calls == []
    assert queue.settled[orphan.id] == ("orphan", None)
    assert queue.settled[unpersisted.id] == ("dead", "resolved_not_persisted")


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


# --- dispatch by (object, field), falling back to the bare field (WA-07) -----------------


class Recorder:
    def __init__(self, status: str = "processed") -> None:
        self.events: list[ClaimedEvent] = []
        self._status = status

    async def __call__(self, event: ClaimedEvent) -> Outcome:
        self.events.append(event)
        return Outcome(self._status)


async def test_a_qualified_key_wins_over_the_bare_field_for_its_object() -> None:
    qualified, bare = Recorder(), Recorder()
    wa = _event("messages", object_="whatsapp_business_account", value={})
    ig = _event("messages", object_="instagram", value={})
    queue = FakeQueue([wa, ig])
    processor = Processor(
        queue=queue,
        handlers={
            handler_key("whatsapp_business_account", "messages"): qualified,
            "messages": bare,
        },
        worker_id="w1",
        clock=lambda: NOW,
    )

    report = await processor.run_once()

    assert [e.id for e in qualified.events] == [wa.id]
    assert [e.id for e in bare.events] == [ig.id]
    assert report.outcomes == {"processed": 2}


async def test_a_qualified_key_never_catches_the_same_field_of_another_object() -> None:
    qualified = Recorder()
    ig = _event("messages", object_="instagram", value={})
    queue = FakeQueue([ig])
    processor = Processor(
        queue=queue,
        handlers={handler_key("whatsapp_business_account", "messages"): qualified},
        worker_id="w1",
        clock=lambda: NOW,
    )

    report = await processor.run_once()

    assert qualified.events == []
    assert queue.settled[ig.id] == ("unsupported", None)
    assert report.outcomes == {"unsupported": 1}


async def test_the_bare_field_key_still_serves_every_object() -> None:
    bare = Recorder()
    ig = _event("mentions", object_="instagram")
    other = _event("mentions", object_="page")
    queue = FakeQueue([ig, other])
    processor = Processor(
        queue=queue, handlers={"mentions": bare}, worker_id="w1", clock=lambda: NOW
    )

    await processor.run_once()

    assert {e.id for e in bare.events} == {ig.id, other.id}


def test_handler_key_is_object_colon_field() -> None:
    assert handler_key("whatsapp_business_account", "messages") == (
        "whatsapp_business_account:messages"
    )


# --- `instagram:comments`: comments on the account's own media that @mention it ---------

ACCOUNT = "qualifymkt.co"


class CommentPipeline:
    """Fake resolver + username reader + comment ingestor, recording their calls."""

    def __init__(
        self,
        *,
        username: str | None = ACCOUNT,
        resolution: TenantResolution | None = None,
        ingest_returns: UUID | None = MENTION,
        ingest_raises: Exception | None = None,
    ) -> None:
        self.username = username
        self.resolution = resolution or RESOLVED
        self.resolver_calls: list[str] = []
        self.username_calls: list[tuple[UUID | None, UUID | None]] = []
        self.ingestor_calls: list[dict[str, object]] = []
        self._returns = ingest_returns
        self._raises = ingest_raises

    def resolve(self, *, platform: str, external_account_id: str) -> TenantResolution:
        self.resolver_calls.append(external_account_id)
        return self.resolution

    def username_of(self, *, tenant_id: UUID | None, connection_id: UUID | None) -> str | None:
        self.username_calls.append((tenant_id, connection_id))
        return self.username

    async def ingest(self, **kwargs: object) -> UUID | None:
        self.ingestor_calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return self._returns

    def processor(self, queue: FakeQueue, *, analyze=None) -> Processor:
        return Processor(
            queue=queue,
            handlers={
                "mentions": mentions_handler(resolve=self.resolve, ingest=self.ingest),
                INSTAGRAM_COMMENTS_HANDLER_KEY: comment_mentions_handler(
                    resolve=self.resolve,
                    username_of=self.username_of,
                    ingest=self.ingest,
                    analyze=analyze,
                ),
            },
            worker_id="w1",
            clock=lambda: NOW,
        )


def _comment(
    text: str | None = "@qualifymkt.co mira esto",
    *,
    drop: tuple[str, ...] = (),
    object_: str = "instagram",
    **extra: object,
) -> ClaimedEvent:
    """The `comments` value as the webhooks field reference documents it (`id` = comment)."""
    value: dict[str, object] = {
        "from": {"id": "irrelevant-igsid", "username": "yesii_roa"},
        "id": "comment-9",
        "media": {"id": "media-9", "media_product_type": "REELS"},
    }
    if text is not None:
        value["text"] = text
    value.update(extra)
    for key in drop:
        value.pop(key)
    return _event("comments", value=value, object_=object_)


async def test_a_comment_mentioning_the_account_is_ingested_with_ids_text_and_author() -> None:
    pipeline = CommentPipeline()
    event = _comment()
    queue = FakeQueue([event])

    report = await pipeline.processor(queue).run_once()

    assert pipeline.resolver_calls == ["111"]
    assert pipeline.username_calls == [(TENANT, CONNECTION)]
    assert pipeline.ingestor_calls == [
        {
            "media_id": "media-9",
            "comment_id": "comment-9",
            "resolution": RESOLVED,
            "text": "@qualifymkt.co mira esto",
            "author_username": "yesii_roa",
            "observed_at": None,  # this event recorded no `entry[].time`
        }
    ]
    assert queue.settled[event.id] == ("processed", None)
    assert report.outcomes == {"processed": 1}


async def test_the_facebook_login_comment_id_spelling_is_accepted() -> None:
    pipeline = CommentPipeline()
    event = _comment(drop=("id",), comment_id="comment-7")
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls[0]["comment_id"] == "comment-7"
    assert queue.settled[event.id] == ("processed", None)


async def test_a_missing_author_still_ingests_with_no_author() -> None:
    pipeline = CommentPipeline()
    event = _comment(drop=("from",))
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls[0]["author_username"] is None
    assert queue.settled[event.id] == ("processed", None)


@pytest.mark.parametrize("text", ["@otra.cuenta mira esto", "@yesii_roa hola"])
async def test_a_comment_mentioning_someone_else_is_unsupported_and_not_ingested(
    text: str,
) -> None:
    pipeline = CommentPipeline()
    event = _comment(text)
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("unsupported", NOT_A_MENTION)


@pytest.mark.parametrize("text", [None, "", "qué lindo post"])
async def test_a_comment_with_no_at_sign_is_unsupported_without_any_lookup(
    text: str | None,
) -> None:
    pipeline = CommentPipeline()
    event = _comment(text)
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.resolver_calls == []
    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("unsupported", NOT_A_MENTION)


@pytest.mark.parametrize(
    "text",
    [
        "@qualifymkt.colombia hola",  # a longer handle that starts with ours
        "@qualifymkt.co_oficial hola",
        "@qualifymkt hola",  # a prefix of ours
        "escríbenos a hola@qualifymkt.co",  # an email, not a mention
        "x@qualifymkt.co",
        "@@qualifymkt.co",
    ],
)
async def test_a_partial_username_match_is_not_a_mention(text: str) -> None:
    pipeline = CommentPipeline()
    event = _comment(text)
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("unsupported", NOT_A_MENTION)


@pytest.mark.parametrize(
    "text",
    [
        "@QualifyMkt.co mira",  # case-insensitive, like Instagram handles
        "mira esto @qualifymkt.co.",  # sentence period: a handle never ends in "."
        "(@qualifymkt.co) genial",
        "hola,@qualifymkt.co!",
        "@yesii_roa @qualifymkt.co",
        "@qualifymkt.co",
        "Gracias.@qualifymkt.co",  # punctuation glued before it
        "mira esto...@qualifymkt.co",
    ],
)
async def test_a_whole_handle_mention_is_recognized(text: str) -> None:
    pipeline = CommentPipeline()
    event = _comment(text)
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert len(pipeline.ingestor_calls) == 1
    assert queue.settled[event.id] == ("processed", None)


async def test_an_orphan_comment_is_never_ingested() -> None:
    pipeline = CommentPipeline(resolution=TenantResolution(outcome=ResolutionOutcome.ORPHAN))
    event = _comment()
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.username_calls == []
    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("orphan", None)


async def test_an_ambiguous_comment_is_never_ingested() -> None:
    pipeline = CommentPipeline(resolution=TenantResolution(outcome=ResolutionOutcome.AMBIGUOUS))
    event = _comment()
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.username_calls == []
    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("ambiguous", None)


async def test_no_stored_username_keeps_the_comment_replayable() -> None:
    pipeline = CommentPipeline(username=None)
    event = _comment()
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("unsupported", COMMENT_USERNAME_UNKNOWN)


async def test_the_account_commenting_on_its_own_post_is_not_a_mention() -> None:
    pipeline = CommentPipeline()
    event = _comment(**{"from": {"id": "111", "username": "QualifyMkt.co"}})
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("unsupported", SELF_COMMENT)


@pytest.mark.parametrize(
    "value",
    [
        {"text": "@qualifymkt.co", "media": {"id": "m"}},  # no comment id at all
        {"id": "c", "text": "@qualifymkt.co"},  # no media
        {"id": "c", "comment_id": "other", "text": "@qualifymkt.co", "media": {"id": "m"}},
        {"id": "c", "text": "@qualifymkt.co", "media": "not-an-object"},
        {"id": "c", "text": "@qualifymkt.co", "media": {"id": "m"}, "from": "not-an-object"},
    ],
)
async def test_a_mention_of_the_account_with_an_off_contract_value_is_dead(value: dict) -> None:
    """Held to the contract only once it is known to mention the account."""
    pipeline = CommentPipeline()
    event = _event("comments", value=value)
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("dead", "contract_violation")


@pytest.mark.parametrize("value", [["not", "an", "object"], "a string", 7])
async def test_a_value_that_is_not_an_object_is_dead_without_resolving(value: object) -> None:
    pipeline = CommentPipeline()
    event = _event("comments", value=value)
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.resolver_calls == []
    assert queue.settled[event.id] == ("dead", "contract_violation")


@pytest.mark.parametrize(
    "value",
    [
        {"from": {"username": "x"}, "id": "c", "text": "@amiga mira", "media": {"id": "m"}},
        {"text": "@amiga mira esto"},  # no ids, no media
    ],
)
async def test_tagging_someone_else_with_an_odd_shape_is_unsupported_not_dead(
    value: dict,
) -> None:
    pipeline = CommentPipeline()
    event = _event("comments", value=value)
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("unsupported", NOT_A_MENTION)


async def test_a_resolved_comment_not_persisted_is_dead() -> None:
    pipeline = CommentPipeline(ingest_returns=None)
    event = _comment()
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert queue.settled[event.id] == ("dead", "resolved_not_persisted")


async def test_a_failing_comment_ingest_is_a_retry_and_the_batch_continues() -> None:
    pipeline = CommentPipeline(ingest_raises=RuntimeError("db blip"))
    failing = _comment()
    other = _event("story_insights", value={})
    queue = FakeQueue([failing, other])

    report = await pipeline.processor(queue).run_once()

    assert queue.failed[failing.id] == (1, "RuntimeError")
    assert failing.id not in queue.settled
    assert queue.settled[other.id] == ("unsupported", None)
    assert report.claimed == 2


async def test_comments_of_another_object_never_reach_the_instagram_handler() -> None:
    pipeline = CommentPipeline()
    event = _comment(object_="page")
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.resolver_calls == []
    assert queue.settled[event.id] == ("unsupported", None)


async def test_a_mention_on_a_comment_is_analyzed_after_ingest() -> None:
    pipeline = CommentPipeline()
    analyzed: list[tuple[UUID | None, UUID]] = []
    event = _comment()
    queue = FakeQueue([event])

    def analyze(*, tenant_id: UUID | None, mention_id: UUID) -> None:
        analyzed.append((tenant_id, mention_id))

    await pipeline.processor(queue, analyze=analyze).run_once()

    assert analyzed == [(TENANT, MENTION)]
    assert queue.settled[event.id] == ("processed", None)


@pytest.mark.parametrize(
    "value",
    [
        {"text": "hola"},  # no media, no id — but no "@" either
        {"from": {"username": "x"}, "text": "qué lindo"},  # `from` without its id
        {"id": "c", "text": 5, "media": {"id": "m"}},
        {"id": "c", "media": {"id": "m"}, "text": None},
    ],
)
async def test_an_odd_comment_without_an_at_sign_stays_unsupported_not_dead(value: dict) -> None:
    """Before this handler every comment was `unsupported`; one that can never be a mention
    must not become `dead` just because its shape is unexpected."""
    pipeline = CommentPipeline()
    event = _event("comments", value=value)
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.resolver_calls == []
    assert queue.settled[event.id] == ("unsupported", NOT_A_MENTION)


async def test_the_account_commenting_without_a_username_is_still_its_own_comment() -> None:
    """Meta may send `from` with the id only: the account's own id (the entry) is enough."""
    pipeline = CommentPipeline()
    event = _comment(**{"from": {"id": "111"}})  # `_event`'s entry id is "111"
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls == []
    assert queue.settled[event.id] == ("unsupported", SELF_COMMENT)


@pytest.mark.parametrize(
    ("entry_time", "expected"),
    [
        (1_760_000_000, datetime(2025, 10, 9, 8, 53, 20, tzinfo=UTC)),  # seconds (documented)
        (1_760_000_000_000, datetime(2025, 10, 9, 8, 53, 20, tzinfo=UTC)),  # milliseconds
        (None, None),
        (0, None),
        (-5, None),
    ],
)
async def test_metas_send_time_is_passed_as_the_fallback_date(
    entry_time: int | None, expected: datetime | None
) -> None:
    pipeline = CommentPipeline()
    event = replace(_comment(), entry_time=entry_time)
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls[0]["observed_at"] == expected


async def test_a_from_without_its_id_still_ingests_with_the_author() -> None:
    """`from` is documented, never guaranteed: a missing id must not cost the mention."""
    pipeline = CommentPipeline()
    event = _comment(**{"from": {"username": "fan_1"}})
    queue = FakeQueue([event])

    await pipeline.processor(queue).run_once()

    assert pipeline.ingestor_calls[0]["author_username"] == "fan_1"
    assert queue.settled[event.id] == ("processed", None)
