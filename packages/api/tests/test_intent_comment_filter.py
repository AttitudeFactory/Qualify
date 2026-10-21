"""«Requiere atención comercial» (m-24789644, PR 4b): the Reel detail's comment read,
narrowed to the comments whose intent signal is commercial under a given intent version.
The filter lives on the SAME keyset-paginated `list_comments_for_thread` the detail view
already uses, so it combines with the sentiment filter, the search and the cursor.

The memory tests run offline; the Postgres ones need the compose database (`db`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qualify_api.intent import CURRENT_INTENT_VERSION, IntentClass, IntentSignal
from qualify_api.intent.repository import PostgresIntentRepository
from qualify_api.sentiment.repository import (
    AnalysisVersion,
    MemorySentimentRepository,
    PostgresSentimentRepository,
)

from .test_sentiment_repository import (
    TENANT_S,
    VERSION,
    _seed_message,
    _seed_second_message_in_thread,
    _thread_id_for,
)

OTHER_INTENT_VERSION = AnalysisVersion(
    detector_version="intent-claude-v1",
    pipeline_version=CURRENT_INTENT_VERSION.pipeline_version,
    model_id=CURRENT_INTENT_VERSION.model_id,
    model_revision=None,
)


def _signal(
    message_id: UUID, classes: dict[IntentClass, float], version: AnalysisVersion
) -> IntentSignal:
    return IntentSignal(
        comment_id=message_id,
        source_id=f"src-{message_id}",
        classes=classes,
        detector_version=version.detector_version,
        pipeline_version=version.pipeline_version,
        model_id=version.model_id,
        model_revision=version.model_revision,
    )


# --------------------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------------------


def _memory_list(
    repo: MemorySentimentRepository,
    connection_id: UUID,
    thread_id: UUID,
    commercial_intent: AnalysisVersion | None,
    sentiment_filter: str | None = None,
) -> list[UUID]:
    return [
        c.message_id
        for c in repo.list_comments_for_thread(
            tenant_id=TENANT_S,
            connection_id=connection_id,
            thread_id=thread_id,
            version=VERSION,
            sentiment_filter=sentiment_filter,
            search=None,
            cursor=None,
            commercial_intent=commercial_intent,
        )
    ]


def test_memory_keeps_only_comments_commercial_under_that_version() -> None:
    repo = MemorySentimentRepository()
    connection_id, thread_id = uuid4(), uuid4()
    commercial, general, other_version = uuid4(), uuid4(), uuid4()
    for minute, message_id in enumerate((commercial, general, other_version)):
        repo.seed_message(
            message_id=message_id,
            connection_id=connection_id,
            source_id=str(message_id),
            text="x",
            posted_at=datetime(2026, 10, 20, 10, minute, tzinfo=UTC),
            thread_id=thread_id,
        )
    repo.seed_commercial_intent(message_id=commercial, version=CURRENT_INTENT_VERSION)
    repo.seed_commercial_intent(message_id=other_version, version=OTHER_INTENT_VERSION)

    assert _memory_list(repo, connection_id, thread_id, CURRENT_INTENT_VERSION) == [commercial]
    # No intent filter: every comment, newest first — what every pre-existing caller reads.
    assert _memory_list(repo, connection_id, thread_id, None) == [
        other_version,
        general,
        commercial,
    ]


# --------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------


def _pg_list(
    tenant_id: UUID,
    connection_id: UUID,
    thread_id: UUID,
    commercial_intent: AnalysisVersion | None,
    sentiment_filter: str | None = None,
) -> set[UUID]:
    return {
        c.message_id
        for c in PostgresSentimentRepository().list_comments_for_thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            thread_id=thread_id,
            version=VERSION,
            sentiment_filter=sentiment_filter,
            search=None,
            cursor=None,
            commercial_intent=commercial_intent,
        )
    }


@pytest.mark.db
def test_postgres_keeps_only_comments_commercial_under_that_version() -> None:
    connection_id, price_q, _source = _seed_message(TENANT_S)
    thread_id = _thread_id_for(TENANT_S, price_q)
    praise = _seed_second_message_in_thread(TENANT_S, connection_id, thread_id, text="lindo")
    pending = _seed_second_message_in_thread(TENANT_S, connection_id, thread_id, text="¿talla?")
    old_only = _seed_second_message_in_thread(TENANT_S, connection_id, thread_id, text="¿dónde?")
    intents = PostgresIntentRepository()
    for signal in (
        _signal(price_q, {IntentClass.PRICE: 0.9}, CURRENT_INTENT_VERSION),
        _signal(praise, {IntentClass.GENERAL: 0.95}, CURRENT_INTENT_VERSION),
        # Commercial, but under another version: not this deployment's answer.
        _signal(old_only, {IntentClass.LOCATION: 0.8}, OTHER_INTENT_VERSION),
    ):
        assert intents.record_intent_result(
            tenant_id=TENANT_S, connection_id=connection_id, signal=signal
        )

    assert _pg_list(TENANT_S, connection_id, thread_id, CURRENT_INTENT_VERSION) == {price_q}
    assert _pg_list(TENANT_S, connection_id, thread_id, OTHER_INTENT_VERSION) == {old_only}
    assert _pg_list(TENANT_S, connection_id, thread_id, None) == {
        price_q,
        praise,
        pending,
        old_only,
    }


@pytest.mark.db
def test_postgres_commercial_filter_combines_with_the_sentiment_filter() -> None:
    connection_id, positive_q, source_id = _seed_message(TENANT_S)
    thread_id = _thread_id_for(TENANT_S, positive_q)
    unanalyzed_q = _seed_second_message_in_thread(
        TENANT_S, connection_id, thread_id, text="¿precio?"
    )
    PostgresSentimentRepository().record_sentiment_result(
        tenant_id=TENANT_S,
        connection_id=connection_id,
        message_id=positive_q,
        source_id=source_id,
        version=VERSION,
        label="POS",
        score=0.9,
    )
    intents = PostgresIntentRepository()
    for message_id in (positive_q, unanalyzed_q):
        intents.record_intent_result(
            tenant_id=TENANT_S,
            connection_id=connection_id,
            signal=_signal(message_id, {IntentClass.PRICE: 0.9}, CURRENT_INTENT_VERSION),
        )

    assert _pg_list(TENANT_S, connection_id, thread_id, CURRENT_INTENT_VERSION, "POS") == {
        positive_q
    }
    assert _pg_list(TENANT_S, connection_id, thread_id, CURRENT_INTENT_VERSION, "PENDING") == {
        unanalyzed_q
    }
