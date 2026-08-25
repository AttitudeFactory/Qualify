"""`db`-marked tests for `PostgresSentimentRepository` — idempotency, versioning and
tenant isolation against the real constraints from migration 0012. Same
`seeded_connection`-style fixture as `test_inbox_repository.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.sentiment.repository import (
    NULL_POSTED_AT_SENTINEL,
    SENTIMENT_FILTER_PENDING,
    AnalysisVersion,
    CommentListCursor,
    PostgresSentimentRepository,
    ReelListCursor,
)
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_S = UUID("e0000000-0000-4000-8000-0000000000f3")
TENANT_S2 = UUID("e0000000-0000-4000-8000-0000000000f4")

VERSION = AnalysisVersion(
    detector_version="robertuito-sentiment-v1",
    pipeline_version="owned-comments-0.1.0",
    model_id="pysentimiento/robertuito-sentiment-analysis",
    model_revision=None,
)


def _seed_tenant(tenant_id: UUID, *, name: str) -> None:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=name,
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()


def _seed_message(tenant_id: UUID) -> tuple[UUID, UUID, str]:
    """(connection_id, message_id, source_id) with a real comment-channel `messages`
    row backing it, so the repository's JOIN through `threads` has something real to
    find."""
    _seed_tenant(tenant_id, name=f"t-{tenant_id}")
    with admin_session() as session:
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@s.co", display_name="U")
        session.add(user)
        session.flush()
        app_id = app.id
        user_id = user.id

    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        connection_id = conn.id

        source_id = f"comment-{uuid4()}"
        # `last_message_at` mirrors `InboxRepository.upsert_comment`'s real contract
        # (`posted_at or now`) — a Thread row is never left with a NULL one in
        # production, and QUA-93's cursor pagination relies on that invariant.
        now = datetime.now(UTC)
        thread = Thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel="comment",
            external_thread_id=f"media-{uuid4()}",
            status="open",
            last_message_at=now,
        )
        session.add(thread)
        session.flush()
        message = Message(
            tenant_id=tenant_id,
            thread_id=thread.id,
            connection_id=connection_id,
            external_message_id=source_id,
            direction="inbound",
            text="me encanta este producto",
            posted_at=now,
            shape_version="ig-comment-shapes-1.0.0",
        )
        session.add(message)
        session.flush()
        message_id = message.id

    return connection_id, message_id, source_id


def _thread_id_for(tenant_id: UUID, message_id: UUID) -> UUID:
    with tenant_session(tenant_id) as session:
        return session.execute(
            select(Message.thread_id).where(Message.id == message_id)
        ).scalar_one()


def _seed_new_thread(tenant_id: UUID, connection_id: UUID, *, text: str) -> UUID:
    """A second Reel (thread + one message) under an ALREADY-seeded connection — for
    tests that need >1 Reel per connection, unlike `_seed_message`'s own connection.
    Deliberately 1 minute NEWER than `_seed_message`'s own thread, so cursor-ordering
    tests have a real, unambiguous "newest first" to assert against."""
    with tenant_session(tenant_id) as session:
        now = datetime.now(UTC) + timedelta(minutes=1)
        thread = Thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            channel="comment",
            external_thread_id=f"media-{uuid4()}",
            status="open",
            last_message_at=now,
        )
        session.add(thread)
        session.flush()
        message = Message(
            tenant_id=tenant_id,
            thread_id=thread.id,
            connection_id=connection_id,
            external_message_id=f"comment-{uuid4()}",
            direction="inbound",
            text=text,
            posted_at=now,
            shape_version="ig-comment-shapes-1.0.0",
        )
        session.add(message)
        session.flush()
        return thread.id


def _seed_second_message_in_thread(
    tenant_id: UUID, connection_id: UUID, thread_id: UUID, *, text: str
) -> UUID:
    """A second `messages` row on an ALREADY-seeded thread — QUA-93's per-Reel grouping
    only shows something interesting with more than one comment per Reel."""
    with tenant_session(tenant_id) as session:
        message = Message(
            tenant_id=tenant_id,
            thread_id=thread_id,
            connection_id=connection_id,
            external_message_id=f"comment-{uuid4()}",
            direction="inbound",
            text=text,
            shape_version="ig-comment-shapes-1.0.0",
        )
        session.add(message)
        session.flush()
        return message.id


@pytest.fixture
def seeded_message() -> tuple[UUID, UUID, UUID, str]:
    connection_id, message_id, source_id = _seed_message(TENANT_S)
    return TENANT_S, connection_id, message_id, source_id


def test_pending_lists_a_never_analyzed_comment(
    seeded_message: tuple[UUID, UUID, UUID, str],
) -> None:
    tenant_id, connection_id, message_id, source_id = seeded_message
    repo = PostgresSentimentRepository()

    pending = repo.list_pending_for_analysis(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION
    )

    assert any(p.message_id == message_id and p.source_id == source_id for p in pending)


def test_recorded_result_is_no_longer_pending(
    seeded_message: tuple[UUID, UUID, UUID, str],
) -> None:
    tenant_id, connection_id, message_id, source_id = seeded_message
    repo = PostgresSentimentRepository()

    inserted = repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=VERSION,
        label="POS",
        score=0.9,
    )
    assert inserted is True

    pending = repo.list_pending_for_analysis(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION
    )
    assert not any(p.message_id == message_id for p in pending)


def test_recording_the_same_version_twice_is_idempotent(
    seeded_message: tuple[UUID, UUID, UUID, str],
) -> None:
    tenant_id, connection_id, message_id, source_id = seeded_message
    repo = PostgresSentimentRepository()

    first = repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=VERSION,
        label="POS",
        score=0.9,
    )
    second = repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=VERSION,
        label="NEG",
        score=0.1,
    )

    assert first is True
    assert second is False  # same (message, version) key — refused, not a second row


def test_a_new_model_version_is_pending_again_and_the_old_row_survives(
    seeded_message: tuple[UUID, UUID, UUID, str],
) -> None:
    """Pins the whole point of 'versionar, no sobrescribir' in one test: bump
    `model_revision`, the comment becomes pending again, AND the row from the previous
    version is still there afterward — untouched, not replaced."""
    tenant_id, connection_id, message_id, source_id = seeded_message
    repo = PostgresSentimentRepository()
    repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=VERSION,
        label="POS",
        score=0.9,
    )

    upgraded = AnalysisVersion(
        detector_version=VERSION.detector_version,
        pipeline_version=VERSION.pipeline_version,
        model_id=VERSION.model_id,
        model_revision="rev-2",
    )
    pending_under_new_version = repo.list_pending_for_analysis(
        tenant_id=tenant_id, connection_id=connection_id, version=upgraded
    )
    assert any(p.message_id == message_id for p in pending_under_new_version)

    second = repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=upgraded,
        label="NEG",
        score=0.2,
    )
    assert second is True

    with tenant_session(tenant_id) as session:
        count = session.execute(
            text("SELECT count(*) FROM comment_sentiment_results WHERE message_id = :mid"),
            {"mid": str(message_id)},
        ).scalar_one()
    assert count == 2  # both versions coexist


def test_tenant_isolation_a_tenant_cannot_see_another_tenants_results() -> None:
    conn_a, message_a, source_a = _seed_message(TENANT_S)
    conn_b, message_b, source_b = _seed_message(TENANT_S2)
    repo = PostgresSentimentRepository()

    repo.record_sentiment_result(
        tenant_id=TENANT_S,
        connection_id=conn_a,
        message_id=message_a,
        source_id=source_a,
        version=VERSION,
        label="POS",
        score=0.9,
    )
    repo.record_sentiment_result(
        tenant_id=TENANT_S2,
        connection_id=conn_b,
        message_id=message_b,
        source_id=source_b,
        version=VERSION,
        label="NEG",
        score=0.9,
    )

    # TENANT_S2's pending list must never include TENANT_S's message, even though both
    # were just recorded — RLS scopes every read.
    pending_for_s2 = repo.list_pending_for_analysis(
        tenant_id=TENANT_S2, connection_id=conn_b, version=VERSION
    )
    assert not any(p.message_id == message_a for p in pending_for_s2)


# --- list_reel_summaries / global_sentiment_summary / list_comments_for_thread (QUA-93) --
#
# The `LATERAL` join shape used by all three is exercised here against real Postgres
# with 2-3 rows — correctness only. The 1,000-Reel/100-comment scale claim is validated
# separately (module docstring); these tests are NOT a substitute for re-running that
# validation if the SQL strings in repository.py are ever touched.


def test_reel_summary_shows_unanalyzed_comment_as_not_analyzed_never_neu(
    seeded_message: tuple[UUID, UUID, UUID, str],
) -> None:
    tenant_id, connection_id, message_id, source_id = seeded_message
    repo = PostgresSentimentRepository()

    (summary,) = repo.list_reel_summaries(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION, cursor=None
    )

    assert summary.total == 1
    assert summary.not_analyzed == 1
    assert summary.positive == summary.neutral == summary.negative == 0


def test_reel_summary_counts_by_label_bounded_to_its_own_thread(
    seeded_message: tuple[UUID, UUID, UUID, str],
) -> None:
    """Two comments on the SAME Reel, one analyzed POS — the summary must count both,
    correctly split, and never spill into a different Reel's counts."""
    tenant_id, connection_id, message_id, source_id = seeded_message
    thread_id = _thread_id_for(tenant_id, message_id)
    _seed_second_message_in_thread(tenant_id, connection_id, thread_id, text="que mal")
    repo = PostgresSentimentRepository()
    repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=VERSION,
        label="POS",
        score=0.9,
    )

    (summary,) = repo.list_reel_summaries(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION, cursor=None
    )

    assert summary.total == 2
    assert summary.positive == 1
    assert summary.not_analyzed == 1


def test_reel_summary_paginates_by_cursor_never_offset(seeded_message) -> None:
    tenant_id, connection_id, message_id, _source_id = seeded_message
    second_thread_id = _seed_new_thread(tenant_id, connection_id, text="otro reel")
    repo = PostgresSentimentRepository()

    page1 = repo.list_reel_summaries(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION, cursor=None, limit=1
    )
    assert len(page1) == 1
    cursor = ReelListCursor(last_message_at=page1[0].last_message_at, thread_id=page1[0].thread_id)
    page2 = repo.list_reel_summaries(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION, cursor=cursor, limit=1
    )

    assert len(page2) == 1
    assert page1[0].thread_id != page2[0].thread_id
    assert {page1[0].thread_id, page2[0].thread_id} == {
        _thread_id_for(tenant_id, message_id),
        second_thread_id,
    }


def test_reel_summary_isolated_by_connection() -> None:
    conn_a, message_a, _source_a = _seed_message(TENANT_S)
    repo = PostgresSentimentRepository()

    summaries = repo.list_reel_summaries(
        tenant_id=TENANT_S, connection_id=conn_a, version=VERSION, cursor=None
    )

    assert len(summaries) == 1
    assert summaries[0].thread_id == _thread_id_for(TENANT_S, message_a)


def test_global_summary_totals_across_reels(seeded_message) -> None:
    tenant_id, connection_id, message_id, source_id = seeded_message
    thread_id = _thread_id_for(tenant_id, message_id)
    _seed_second_message_in_thread(tenant_id, connection_id, thread_id, text="que mal")
    repo = PostgresSentimentRepository()
    repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=VERSION,
        label="POS",
        score=0.9,
    )

    summary = repo.global_sentiment_summary(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION
    )

    assert summary.total == 2
    assert summary.positive == 1
    assert summary.not_analyzed == 1


def test_comments_for_thread_scoped_to_one_reel(seeded_message) -> None:
    tenant_id, connection_id, message_id, source_id = seeded_message
    thread_id = _thread_id_for(tenant_id, message_id)
    other_connection_id, other_message_id, _other_source = _seed_message(tenant_id)
    repo = PostgresSentimentRepository()

    comments = repo.list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=thread_id,
        version=VERSION,
        sentiment_filter=None,
        search=None,
        cursor=None,
    )

    assert [c.message_id for c in comments] == [message_id]
    assert other_message_id not in [c.message_id for c in comments]


def test_comments_for_thread_filters_by_sentiment(seeded_message) -> None:
    tenant_id, connection_id, message_id, source_id = seeded_message
    thread_id = _thread_id_for(tenant_id, message_id)
    pending_id = _seed_second_message_in_thread(tenant_id, connection_id, thread_id, text="que mal")
    repo = PostgresSentimentRepository()
    repo.record_sentiment_result(
        tenant_id=tenant_id,
        connection_id=connection_id,
        message_id=message_id,
        source_id=source_id,
        version=VERSION,
        label="POS",
        score=0.9,
    )

    pending = repo.list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=thread_id,
        version=VERSION,
        sentiment_filter=SENTIMENT_FILTER_PENDING,
        search=None,
        cursor=None,
    )
    positive = repo.list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=thread_id,
        version=VERSION,
        sentiment_filter="POS",
        search=None,
        cursor=None,
    )

    assert [c.message_id for c in pending] == [pending_id]
    assert [c.message_id for c in positive] == [message_id]


def test_comments_for_thread_search_by_text(seeded_message) -> None:
    tenant_id, connection_id, message_id, source_id = seeded_message  # text: "me encanta..."
    thread_id = _thread_id_for(tenant_id, message_id)
    _seed_second_message_in_thread(tenant_id, connection_id, thread_id, text="saludos")
    repo = PostgresSentimentRepository()

    matches = repo.list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=thread_id,
        version=VERSION,
        sentiment_filter=None,
        search="encanta",
        cursor=None,
    )

    assert [c.message_id for c in matches] == [message_id]


def test_comments_for_thread_search_is_accent_and_case_insensitive(seeded_message) -> None:
    """Bug reported after QUA-93 shipped: searching "llego" (no accent) must still match
    "llegó" (mobile keyboards routinely drop accents), and case must not matter either
    direction. Exercises the real `translate(lower(m.text), ...)` SQL, not just the
    offline `MemorySentimentRepository` (see `test_sentiment_service.py`'s counterpart)."""
    tenant_id, connection_id, _existing_message_id, _source_id = seeded_message
    thread_id = _thread_id_for(tenant_id, _existing_message_id)
    accented_id = _seed_second_message_in_thread(
        tenant_id,
        connection_id,
        thread_id,
        text="El producto llegó tarde y además no cumplió con lo que prometía.",
    )
    repo = PostgresSentimentRepository()

    no_accent = repo.list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=thread_id,
        version=VERSION,
        sentiment_filter=None,
        search="llego tarde",  # no accent, lowercase
        cursor=None,
    )
    upper_with_accent = repo.list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=thread_id,
        version=VERSION,
        sentiment_filter=None,
        search="LLEGÓ",  # accent, uppercase
        cursor=None,
    )

    assert [c.message_id for c in no_accent] == [accented_id]
    assert [c.message_id for c in upper_with_accent] == [accented_id]


def test_comments_for_thread_paginates_by_cursor_including_null_posted_at(
    seeded_message,
) -> None:
    """`messages.posted_at` is nullable by contract — the cursor must still cover a
    NULL-posted_at row exactly once, never lose or duplicate it."""
    tenant_id, connection_id, message_id, source_id = seeded_message
    thread_id = _thread_id_for(tenant_id, message_id)
    null_posted_id = _seed_second_message_in_thread(
        tenant_id, connection_id, thread_id, text="sin fecha"
    )
    repo = PostgresSentimentRepository()

    page1 = repo.list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=thread_id,
        version=VERSION,
        sentiment_filter=None,
        search=None,
        cursor=None,
        limit=1,
    )
    assert len(page1) == 1
    last = page1[0]
    cursor = CommentListCursor(
        sort_key=last.posted_at if last.posted_at is not None else NULL_POSTED_AT_SENTINEL,
        message_id=last.message_id,
    )
    page2 = repo.list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=thread_id,
        version=VERSION,
        sentiment_filter=None,
        search=None,
        cursor=cursor,
        limit=1,
    )

    seen = {row.message_id for row in (*page1, *page2)}
    assert seen == {message_id, null_posted_id}


def test_reel_read_is_tenant_isolated() -> None:
    conn_a, message_a, _source_a = _seed_message(TENANT_S)
    conn_b, message_b, _source_b = _seed_message(TENANT_S2)
    repo = PostgresSentimentRepository()

    summaries_for_s2 = repo.list_reel_summaries(
        tenant_id=TENANT_S2, connection_id=conn_b, version=VERSION, cursor=None
    )

    assert not any(s.thread_id == _thread_id_for(TENANT_S, message_a) for s in summaries_for_s2)
    assert any(s.thread_id == _thread_id_for(TENANT_S2, message_b) for s in summaries_for_s2)
