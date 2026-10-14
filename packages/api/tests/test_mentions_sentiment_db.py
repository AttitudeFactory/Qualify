"""Mention sentiment failures (QUA-152, migration 0051) against real Postgres.

Proves what the in-memory twin cannot: the 0051 table's shape and grants (append-only for
the app role, class name bounded by a CHECK), that the SQL `ERROR` state and the pending
filter agree with `MAX_SENTIMENT_ATTEMPTS`, that a failure row stores the exception class
and never its message, and that RLS isolates failures per tenant.

Fresh tenant per test: `qualify_test` is never emptied between runs.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.mentions.models import MentionSentimentFailure
from qualify_api.mentions.repository import (
    ENRICHMENT_OK,
    MAX_SENTIMENT_ATTEMPTS,
    SENTIMENT_ERROR,
    SENTIMENT_PENDING,
    MentionQuery,
    NewMention,
    PostgresMentionsRepository,
)
from qualify_api.mentions.sentiment import MentionSentimentService
from qualify_api.sentiment.repository import AnalysisVersion
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

VERSION = AnalysisVersion(
    detector_version="v1",
    pipeline_version="mentions-text-1.0.0",
    model_id="m1",
    model_revision=None,
)


class ModelBlewUp(RuntimeError):
    pass


class PoisonProvider:
    model_id = "stub/poison"

    def classify(self, text: str) -> tuple[str, float]:
        if "poison" in text:
            raise ModelBlewUp(f"failed on: {text}")  # message echoes user text on purpose
        return ("POS", 0.9)


def _fresh_tenant_with_connection() -> tuple[UUID, UUID]:
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"mentions-sentiment-{tenant_id}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@t.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

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
        return tenant_id, conn.id


def _add(repo: PostgresMentionsRepository, tenant_id: UUID, connection_id: UUID, caption: str):
    mention_id, _ = repo.upsert_mention(
        NewMention(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_account_id="ig-user-1",
            media_id=f"media-{uuid4()}",
            comment_id=None,
            caption=caption,
            text=None,
            author_username="autora",
            media_type="IMAGE",
            like_count=1,
            content_posted_at=None,
            enrichment_status=ENRICHMENT_OK,
        )
    )
    return mention_id


def _failure_rows(tenant_id: UUID, mention_id: UUID) -> list[MentionSentimentFailure]:
    with tenant_session(tenant_id) as session:
        rows = session.scalars(
            select(MentionSentimentFailure).where(MentionSentimentFailure.mention_id == mention_id)
        ).all()
        session.expunge_all()
        return list(rows)


def test_failures_are_bounded_recorded_by_class_and_end_in_error() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    bad = _add(repo, tenant_id, connection_id, "poison: dato privado del usuario")
    good = _add(repo, tenant_id, connection_id, "me encanta")
    service = MentionSentimentService(repository=repo, version=VERSION, provider=PoisonProvider())

    summaries = [
        service.analyze_pending_mentions(tenant_id=tenant_id)
        for _ in range(MAX_SENTIMENT_ATTEMPTS + 1)
    ]

    failures = _failure_rows(tenant_id, bad)
    assert len(failures) == MAX_SENTIMENT_ATTEMPTS
    assert {f.error_class for f in failures} == {"ModelBlewUp"}
    assert all("privado" not in f.error_class for f in failures)
    assert [s.failed for s in summaries] == [1] * MAX_SENTIMENT_ATTEMPTS + [0]
    assert summaries[0].new_results == 1  # the good mention, analyzed once
    assert sum(s.new_results for s in summaries) == 1

    page = repo.list_mentions_page(
        tenant_id=tenant_id, version=VERSION, query=MentionQuery(), page=1
    )
    states = {r.id: r.sentiment_state for r in page.rows}
    assert states == {bad: SENTIMENT_ERROR, good: "POS"}
    assert (page.counts.error, page.counts.positive, page.counts.pending) == (1, 1, 0)
    assert repo.list_pending_for_analysis(tenant_id=tenant_id, version=VERSION) == ()


def test_below_the_limit_a_failed_mention_stays_pending_and_is_offered_again() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    bad = _add(repo, tenant_id, connection_id, "poison")
    service = MentionSentimentService(repository=repo, version=VERSION, provider=PoisonProvider())

    service.analyze_pending_mentions(tenant_id=tenant_id)

    page = repo.list_mentions_page(
        tenant_id=tenant_id, version=VERSION, query=MentionQuery(), page=1
    )
    assert page.rows[0].sentiment_state == SENTIMENT_PENDING
    assert [
        p.mention_id for p in repo.list_pending_for_analysis(tenant_id=tenant_id, version=VERSION)
    ] == [bad]


def test_error_filter_and_targeted_analysis() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    bad = _add(repo, tenant_id, connection_id, "poison")
    other = _add(repo, tenant_id, connection_id, "hola")
    service = MentionSentimentService(repository=repo, version=VERSION, provider=PoisonProvider())

    for _ in range(MAX_SENTIMENT_ATTEMPTS):
        service.analyze_pending_mentions(tenant_id=tenant_id, mention_id=bad)

    errored = repo.list_mentions_page(
        tenant_id=tenant_id,
        version=VERSION,
        query=MentionQuery(sentiment_state=SENTIMENT_ERROR),
        page=1,
    )
    assert [r.id for r in errored.rows] == [bad]
    assert errored.counts.total == 1
    # The targeted pass never touched the other mention.
    assert [
        p.mention_id for p in repo.list_pending_for_analysis(tenant_id=tenant_id, version=VERSION)
    ] == [other]


def test_failures_are_isolated_per_tenant() -> None:
    repo = PostgresMentionsRepository()
    tenant_a, connection_a = _fresh_tenant_with_connection()
    tenant_b, _connection_b = _fresh_tenant_with_connection()
    bad = _add(repo, tenant_a, connection_a, "poison")
    repo.record_sentiment_failure(
        tenant_id=tenant_a, mention_id=bad, version=VERSION, error_class="ModelBlewUp"
    )

    with tenant_session(tenant_b) as session:
        visible_to_b = session.scalar(select(func.count()).select_from(MentionSentimentFailure))

    assert visible_to_b == 0
    assert len(_failure_rows(tenant_a, bad)) == 1


def test_the_app_role_may_only_insert_and_select_failures() -> None:
    """Append-only for the app role: no UPDATE/DELETE, so the attempt count (one row per
    failure) cannot be rewritten. `has_table_privilege` rather than
    `information_schema.role_table_grants`, which hides other roles' grants."""
    with admin_session() as session:
        privileges = {
            privilege
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
            if session.scalar(
                text(
                    "SELECT has_table_privilege('qualify_app', 'mention_sentiment_failures', "
                    ":privilege)"
                ),
                {"privilege": privilege},
            )
        }
    assert privileges == {"SELECT", "INSERT"}


def test_the_error_class_check_rejects_empty_and_oversized_values() -> None:
    repo = PostgresMentionsRepository()
    tenant_id, connection_id = _fresh_tenant_with_connection()
    mention_id = _add(repo, tenant_id, connection_id, "hola")

    for bad_value in ("", "x" * 201):
        with pytest.raises(DBAPIError), tenant_session(tenant_id) as session:
            session.add(
                MentionSentimentFailure(
                    tenant_id=tenant_id,
                    mention_id=mention_id,
                    detector_version="v1",
                    pipeline_version="p",
                    model_id="m",
                    error_class=bad_value,
                )
            )
            session.flush()

    # The repository bounds the value itself, so recording can never trip the CHECK.
    repo.record_sentiment_failure(
        tenant_id=tenant_id, mention_id=mention_id, version=VERSION, error_class="E" * 500
    )
    assert len(_failure_rows(tenant_id, mention_id)[0].error_class) == 200
