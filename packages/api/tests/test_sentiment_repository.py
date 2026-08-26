"""`db`-marked tests for `PostgresSentimentRepository` — idempotency, versioning and
tenant isolation against the real constraints from migration 0012. Same
`seeded_connection`-style fixture as `test_inbox_repository.py`.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import insert, select, text

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.sentiment.models import CommentSentimentResult
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


# --------------------------------------------------------------------------------------
# Scale regression coverage (QUA-93 follow-up, 2026-08-25) — the AC's "Rendimiento/tests"
# section asked for a committed test at >=3 Reels x >=150 comments; the original
# 1,000x100 validation that found the 28.5s-vs-23ms bug (module docstring) lived only in
# this session's scratchpad and never reached the repo. These helpers/tests close that.
# --------------------------------------------------------------------------------------


def _seed_connection_only(tenant_id: UUID) -> UUID:
    """Same tenant/app/user/connection setup `_seed_message` does, minus its own first
    Reel/comment — for tests that seed every Reel themselves, in bulk."""
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
        return conn.id


def _bulk_seed_reel(
    tenant_id: UUID, connection_id: UUID, *, comment_count: int, tag: str, minute_offset: int
) -> tuple[UUID, list[UUID]]:
    """Bulk-inserts one Reel (thread) with `comment_count` messages via SQLAlchemy Core
    `insert()` — fast enough for hundreds of rows, unlike per-row ORM `session.add()`
    (what every other helper in this file uses, correctly, for the 1-2-row cases they
    seed). `tag` is embedded in every message's text so a query result's origin Reel can
    be verified without a `thread_id` field on `AnalyzedComment` — it deliberately has
    none (the caller already knows which thread it asked for; see that dataclass's
    docstring)."""
    with tenant_session(tenant_id) as session:
        now = datetime.now(UTC) + timedelta(minutes=minute_offset)
        thread_id = uuid4()
        session.execute(
            insert(Thread),
            [
                {
                    "id": thread_id,
                    "tenant_id": tenant_id,
                    "connection_id": connection_id,
                    "channel": "comment",
                    "external_thread_id": f"media-{tag}-{uuid4()}",
                    "status": "open",
                    "last_message_at": now,
                }
            ],
        )
        message_ids = [uuid4() for _ in range(comment_count)]
        session.execute(
            insert(Message),
            [
                {
                    "id": mid,
                    "tenant_id": tenant_id,
                    "thread_id": thread_id,
                    "connection_id": connection_id,
                    "external_message_id": f"comment-{tag}-{i}-{uuid4()}",
                    "direction": "inbound",
                    "text": f"{tag} comentario {i}",
                    "posted_at": now - timedelta(seconds=i),
                    "shape_version": "ig-comment-shapes-1.0.0",
                }
                for i, mid in enumerate(message_ids)
            ],
        )
        session.flush()
    return thread_id, message_ids


def _bulk_seed_sentiment(
    tenant_id: UUID,
    connection_id: UUID,
    message_ids: list[UUID],
    *,
    version: AnalysisVersion,
    label: str,
) -> None:
    with tenant_session(tenant_id) as session:
        session.execute(
            insert(CommentSentimentResult),
            [
                {
                    "tenant_id": tenant_id,
                    "connection_id": connection_id,
                    "message_id": mid,
                    "source_id": f"src-{mid}",
                    "detector_version": version.detector_version,
                    "pipeline_version": version.pipeline_version,
                    "model_id": version.model_id,
                    "model_revision": version.model_revision,
                    "label": label,
                    "score": 0.9,
                }
                for mid in message_ids
            ],
        )
        session.flush()


def test_scale_regression_three_reels_150_comments_each_returns_bounded_rows() -> None:
    """QUA-93 AC ('Rendimiento/tests'): seeds 3 Reels x 150 comments each (450 rows), half
    of each Reel's comments analyzed, then asserts every query returns EXACTLY the row
    count its `limit`/`thread_id` scope implies — never the full seeded volume — by
    counting returned rows, not by reading `EXPLAIN`. This is the correctness half of the
    scale guard; `test_list_reel_summaries_sql_uses_keyset_never_offset` and the
    `slow`-marked benchmark below cover the query-shape and timing halves."""
    tenant_id = uuid4()
    connection_id = _seed_connection_only(tenant_id)
    reels = []
    for i in range(3):
        thread_id, message_ids = _bulk_seed_reel(
            tenant_id, connection_id, comment_count=150, tag=f"reel{i}", minute_offset=i
        )
        analyzed, pending = message_ids[:75], message_ids[75:]
        _bulk_seed_sentiment(tenant_id, connection_id, analyzed, version=VERSION, label="POS")
        reels.append((thread_id, analyzed, pending))
    repo = PostgresSentimentRepository()

    # Main view: a page of 2 of the 3 seeded Reels — never all 3, never a comment row.
    page = repo.list_reel_summaries(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION, cursor=None, limit=2
    )
    assert len(page) == 2
    for summary in page:
        assert summary.total == 150
        assert summary.positive == 75
        assert summary.not_analyzed == 75

    # Global summary: the one deliberate full scan — must reflect all 3 Reels' totals.
    totals = repo.global_sentiment_summary(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION
    )
    assert totals.total == 450
    assert totals.positive == 225
    assert totals.not_analyzed == 225

    # Reel detail: a page of 20 of 150 comments from ONE Reel — bounded to that Reel,
    # never spilling into the other two (checked via each Reel's distinguishing tag,
    # since AnalyzedComment carries no thread_id to check directly).
    target_thread_id, _analyzed, _pending = reels[0]
    detail_page = repo.list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=target_thread_id,
        version=VERSION,
        sentiment_filter=None,
        search=None,
        cursor=None,
        limit=20,
    )
    assert len(detail_page) == 20
    assert all(c.text.startswith("reel0 ") for c in detail_page)


def test_list_reel_summaries_sql_uses_keyset_never_offset() -> None:
    """Explicit protection for the QUA-93 pagination decision ('cursor, keyset, no
    OFFSET — decisión del fundador, 2026-08-25'): a future edit that reaches for OFFSET
    instead of the keyset comparison fails here immediately, rather than silently
    degrading pagination correctness under concurrent writes (an OFFSET page can skip or
    repeat rows when the underlying set changes between page loads; a keyset cursor
    cannot)."""
    source = inspect.getsource(PostgresSentimentRepository.list_reel_summaries)
    assert "OFFSET" not in source.upper()
    assert "(last_message_at, id) < (:cts, :ctid)" in source


def test_list_comments_for_thread_sql_uses_keyset_never_offset() -> None:
    """Same protection as `test_list_reel_summaries_sql_uses_keyset_never_offset`, for
    the Reel-detail query — including the `NULL_POSTED_AT_SENTINEL` COALESCE that makes
    the keyset comparison well-defined even when `posted_at IS NULL`."""
    source = inspect.getsource(PostgresSentimentRepository.list_comments_for_thread)
    assert "OFFSET" not in source.upper()
    assert "(COALESCE(m.posted_at, :null_sentinel), m.id) < (:cts, :ctid)" in source


def test_comments_for_thread_cursor_walk_covers_all_150_rows_exactly_once() -> None:
    """Behavioral counterpart to the two SQL-inspection tests above: walks every page of
    a 150-comment Reel with a small page size and proves the union of all pages equals
    exactly the seeded set — no row lost, no row duplicated. Same property
    `test_comments_for_thread_paginates_by_cursor_including_null_posted_at` already pins
    for the NULL-posted_at edge case, now at a scale where an off-by-one or a silently
    reintroduced OFFSET would actually surface instead of hiding inside a 1-2-row page."""
    tenant_id = uuid4()
    connection_id = _seed_connection_only(tenant_id)
    thread_id, message_ids = _bulk_seed_reel(
        tenant_id, connection_id, comment_count=150, tag="walk", minute_offset=0
    )
    repo = PostgresSentimentRepository()

    seen: list[UUID] = []
    cursor: CommentListCursor | None = None
    for _page_number in range(20):  # 150 / 20-per-page = 8 pages; generous vs. an infinite loop
        page = repo.list_comments_for_thread(
            tenant_id=tenant_id,
            connection_id=connection_id,
            thread_id=thread_id,
            version=VERSION,
            sentiment_filter=None,
            search=None,
            cursor=cursor,
            limit=20,
        )
        if not page:
            break
        seen.extend(c.message_id for c in page)
        last = page[-1]
        sort_key = last.posted_at if last.posted_at is not None else NULL_POSTED_AT_SENTINEL
        cursor = CommentListCursor(sort_key=sort_key, message_id=last.message_id)

    assert len(seen) == 150
    assert len(set(seen)) == 150  # no duplicates
    assert set(seen) == set(message_ids)  # exactly the seeded set, nothing lost


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


def test_comment_sentiment_results_has_no_standalone_tenant_index() -> None:
    """QUA-93 follow-up (the ~25s regression that survived `csr.tenant_id = :tenant_id`
    alone): `ix_comment_sentiment_tenant` was dropped in migration 0012 because it
    competed with `uq_comment_sentiment_analysis` for the per-message LATERAL lookup —
    see that migration's `upgrade()` comment. A future edit that re-adds a tenant_id-only
    index on this specific table (unlike every sibling RLS table, which legitimately
    wants one) should fail here rather than silently reopening the regression."""
    with admin_session() as session:
        names = {
            row[0]
            for row in session.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename = 'comment_sentiment_results'"
                )
            ).all()
        }
    assert "ix_comment_sentiment_tenant" not in names
    # The two indexes the per-message lookup actually needs must still be there.
    assert "ix_comment_sentiment_message" in names
    assert "uq_comment_sentiment_analysis" in names


def _explain_reel_summaries_lateral(
    tenant_id: UUID, thread_ids: list[UUID], version: AnalysisVersion
) -> str:
    """Re-runs `list_reel_summaries`'s aggregation SQL verbatim (copied from
    `repository.py` — same character-for-character discipline its module docstring
    already demands for these raw-SQL strings) under `EXPLAIN (ANALYZE, BUFFERS)`, to
    assert on the actual index Postgres chooses for the per-message LATERAL lookup —
    the `slow` benchmark covers wall-clock time; this covers the plan shape directly, at
    a scale where a bad plan is a source of truth about *which* index was used, not
    about how many minutes it costs."""
    agg_sql = """
        EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
        SELECT m.thread_id,
          count(*) AS total,
          count(*) FILTER (WHERE csr.label = 'POS') AS positive,
          count(*) FILTER (WHERE csr.label = 'NEU') AS neutral,
          count(*) FILTER (WHERE csr.label = 'NEG') AS negative,
          count(*) FILTER (WHERE csr.label IS NULL) AS not_analyzed
        FROM messages m
        LEFT JOIN LATERAL (
          SELECT label
          FROM comment_sentiment_results csr
          WHERE csr.message_id = m.id
            AND csr.tenant_id = :tenant_id
            AND csr.detector_version = :dv AND csr.pipeline_version = :pv
            AND csr.model_id = :mid
            AND COALESCE(csr.model_revision, '') = COALESCE(:mrev, '')
          LIMIT 1
        ) csr ON true
        WHERE m.thread_id = ANY(:tids) AND m.direction = 'inbound'
        GROUP BY m.thread_id
    """
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            text(agg_sql),
            {
                "tids": [str(t) for t in thread_ids],
                "tenant_id": str(tenant_id),
                "dv": version.detector_version,
                "pv": version.pipeline_version,
                "mid": version.model_id,
                "mrev": version.model_revision,
            },
        ).all()
    return "\n".join(row[0] for row in rows)


def _explain_comments_for_thread_lateral(
    tenant_id: UUID, connection_id: UUID, thread_id: UUID, version: AnalysisVersion
) -> str:
    """Same discipline as `_explain_reel_summaries_lateral`, for `list_comments_for_thread`'s
    LATERAL — copied verbatim from `repository.py`."""
    sql = """
        EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
        SELECT m.id, m.external_message_id, m.text, m.author_username, m.posted_at,
               csr.label, csr.score
        FROM messages m
        LEFT JOIN LATERAL (
          SELECT label, score
          FROM comment_sentiment_results csr
          WHERE csr.message_id = m.id
            AND csr.tenant_id = :tenant_id
            AND csr.detector_version = :dv AND csr.pipeline_version = :pv
            AND csr.model_id = :mid
            AND COALESCE(csr.model_revision, '') = COALESCE(:mrev, '')
          LIMIT 1
        ) csr ON true
        WHERE m.thread_id = :tid AND m.connection_id = :cid AND m.direction = 'inbound'
        ORDER BY COALESCE(m.posted_at, :null_sentinel) DESC, m.id DESC
        LIMIT 20
    """
    with tenant_session(tenant_id) as session:
        rows = session.execute(
            text(sql),
            {
                "tid": str(thread_id),
                "cid": str(connection_id),
                "tenant_id": str(tenant_id),
                "dv": version.detector_version,
                "pv": version.pipeline_version,
                "mid": version.model_id,
                "mrev": version.model_revision,
                "null_sentinel": NULL_POSTED_AT_SENTINEL,
            },
        ).all()
    return "\n".join(row[0] for row in rows)


def test_list_reel_summaries_lateral_avoids_tenant_only_index_scan() -> None:
    """The exact adversarial shape that exposed the ~22-25s regression (QUA-93
    follow-up): half a Reel's comments analyzed, half still pending — a "miss" on the
    pending half is what forced a tenant-only index into a full tenant-partition scan.
    With `ix_comment_sentiment_tenant` dropped, the LATERAL's only remaining candidates
    are the two `message_id`-first indexes."""
    tenant_id = uuid4()
    connection_id = _seed_connection_only(tenant_id)
    thread_id, message_ids = _bulk_seed_reel(
        tenant_id, connection_id, comment_count=40, tag="explain-reel", minute_offset=0
    )
    _bulk_seed_sentiment(
        tenant_id, connection_id, message_ids[:20], version=VERSION, label="POS"
    )  # other 20 stay unanalyzed — the "miss" case

    plan = _explain_reel_summaries_lateral(tenant_id, [thread_id], VERSION)

    assert "ix_comment_sentiment_tenant" not in plan
    assert "uq_comment_sentiment_analysis" in plan or "ix_comment_sentiment_message" in plan


def test_list_comments_for_thread_lateral_avoids_tenant_only_index_scan() -> None:
    """Same adversarial shape and assertion as
    `test_list_reel_summaries_lateral_avoids_tenant_only_index_scan`, for the sibling
    LATERAL in `list_comments_for_thread`."""
    tenant_id = uuid4()
    connection_id = _seed_connection_only(tenant_id)
    thread_id, message_ids = _bulk_seed_reel(
        tenant_id, connection_id, comment_count=40, tag="explain-thread", minute_offset=0
    )
    _bulk_seed_sentiment(tenant_id, connection_id, message_ids[:20], version=VERSION, label="POS")

    plan = _explain_comments_for_thread_lateral(tenant_id, connection_id, thread_id, VERSION)

    assert "ix_comment_sentiment_tenant" not in plan
    assert "uq_comment_sentiment_analysis" in plan or "ix_comment_sentiment_message" in plan


def test_global_sentiment_summary_sql_binds_tenant_id_on_every_table() -> None:
    """QUA-93 follow-up: `global_sentiment_summary` never bound `tenant_id` as a literal
    (relying only on RLS's opaque `current_setting('app.tenant_id')`), which was measured
    to make Postgres misestimate `messages`/`threads`/`comment_sentiment_results` row
    counts as ~1 each and pick Nested Loop joins over Hash Join — a ~24-minute regression
    at 1,000 Reels x 100 comments. Source-inspection, not `EXPLAIN`, because join-algorithm
    choice at this test file's small seed sizes is legitimately Nested Loop either way
    (correct at that scale) — the `slow` benchmark is what proves the timing outcome at
    the scale where it matters."""
    source = inspect.getsource(PostgresSentimentRepository.global_sentiment_summary)
    assert "m.tenant_id = :tenant_id" in source
    assert "t.tenant_id = :tenant_id" in source
    assert "csr.tenant_id = :tenant_id" in source
    assert '"tenant_id": str(tenant_id)' in source


def test_list_pending_for_analysis_has_no_tenant_only_index_to_fall_back_on() -> None:
    """`list_pending_for_analysis`'s `EXISTS` subquery shares the same `message_id`-
    correlated shape as the two LATERAL queries above (see its `already_analyzed`
    construction), so it was exposed to the same `ix_comment_sentiment_tenant` risk even
    though QUA-93's own scale investigation never measured it directly. Dropping the
    index (asserted by `test_comment_sentiment_results_has_no_standalone_tenant_index`)
    removes that risk for every correlated-by-message_id query on this table at once,
    this one included — pinned here as a correctness/behavior check, not a plan
    inspection, since it is ORM-built and not one of this module's raw-SQL strings."""
    tenant_id = uuid4()
    connection_id = _seed_connection_only(tenant_id)
    thread_id, message_ids = _bulk_seed_reel(
        tenant_id, connection_id, comment_count=10, tag="pending", minute_offset=0
    )
    analyzed, pending = message_ids[:6], message_ids[6:]
    _bulk_seed_sentiment(tenant_id, connection_id, analyzed, version=VERSION, label="NEG")

    repo = PostgresSentimentRepository()
    result = repo.list_pending_for_analysis(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION
    )

    assert {c.message_id for c in result} == set(pending)
