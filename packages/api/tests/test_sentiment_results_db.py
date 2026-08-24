"""`db`-marked end-to-end test for QUA-21: the full stack (`list_pending_for_analysis`
→ `analyze_text` → `record_sentiment_result`) against a self-seeded, disposable
tenant/connection/thread/messages — never real Meta data, never a specific tenant.
Same seeding pattern as `test_sentiment_repository.py::_seed_message`, extended to two
messages under one thread (one Reel, two comments — the shape QUA-88/89 produce).

**Why not the real Meta data from the 2026-08-21 live validation.** That validation
(a real positive and a real negative comment, published on the real `@qualifymkt.co`
Reel, synced via QUA-89, analyzed via `POST /api/sentiment/analyze`, confirmed under
`CURRENT_ANALYSIS_VERSION` in Postgres — see the QUA-21 Linear comment history for the
evidence) is real and stays the record of truth for "does this work against live
Meta". It is **not reproducible in CI**: CI spins up a fresh, empty `postgres:16`
service container every run, with only `alembic upgrade head` applied — the specific
tenant/connection/message rows that session created only ever existed in the local
dev database. Hardcoding those real IDs here made this file pass locally and fail in
CI 100% of the time. This file now validates the same code path with data any
environment can create for itself; the live-Meta validation stays a manual,
separate exercise, not a dependency of the automated suite.

**No cleanup — same reasoning as before, still applies.** `comment_sentiment_results`
grants `qualify_app`/`qualify_admin` only `SELECT, INSERT` (migration 0012) — the
append-only enforcement "versionar, no sobrescribir" requires. There is structurally
no sanctioned way for this test to DELETE its own rows. Harmless here: the tenant
this file seeds is itself disposable test data, not a real production connection.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.sentiment.repository import AnalysisVersion, PostgresSentimentRepository
from qualify_api.sentiment.service import SentimentService
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_E2E = UUID("e0000000-0000-4000-8000-0000000000f6")


class StubProvider:
    """Deterministic, no weights — same discipline every other sentiment test in this
    package uses; this file's job is proving the pipeline wiring, not the model."""

    model_id = "test/e2e-deterministic-stub"

    def classify(self, text: str) -> tuple[str, float]:
        return ("NEG", 0.9) if any(w in text.lower() for w in ("mal", "pésim")) else ("POS", 0.9)


def _fresh_test_version() -> AnalysisVersion:
    """Unique per call — two test functions in this file must not share one (the
    first would consume the second's "pending" comments), and nothing here is ever
    deleted (see module docstring)."""
    run_id = uuid4().hex[:8]
    return AnalysisVersion(
        detector_version=f"test-e2e-stub-v1-{run_id}",
        pipeline_version="test-e2e-stub-pipeline-v1",
        model_id="test/e2e-deterministic-stub",
        model_revision=None,
    )


def _seed_two_comments() -> tuple[UUID, tuple[str, str]]:
    """(connection_id, (source_id_pos, source_id_neg)) — one positive-leaning comment,
    one negative-leaning, both real `messages` rows on a real `comment`-channel
    thread. Same seeding pattern as `test_sentiment_repository.py::_seed_message`:
    `admin_session` for the tenant/app/user (cross-tenant provisioning), `tenant_session`
    for the connection/thread/messages (RLS-scoped, matches production)."""
    with admin_session() as session:
        if session.get(Tenant, TENANT_E2E) is None:
            session.add(
                Tenant(
                    id=TENANT_E2E,
                    name="t-sentiment-e2e",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=TENANT_E2E, email=f"u-{uuid4()}@e2e.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT_E2E) as session:
        conn = SocialConnection(
            tenant_id=TENANT_E2E,
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

        thread = Thread(
            tenant_id=TENANT_E2E,
            connection_id=connection_id,
            channel="comment",
            external_thread_id=f"media-{uuid4()}",
            status="open",
        )
        session.add(thread)
        session.flush()

        source_pos = f"comment-pos-{uuid4()}"
        source_neg = f"comment-neg-{uuid4()}"
        session.add_all(
            [
                Message(
                    tenant_id=TENANT_E2E,
                    thread_id=thread.id,
                    connection_id=connection_id,
                    external_message_id=source_pos,
                    direction="inbound",
                    text="Me encanta este producto, excelente",
                    shape_version="ig-comment-shapes-1.0.0",
                ),
                Message(
                    tenant_id=TENANT_E2E,
                    thread_id=thread.id,
                    connection_id=connection_id,
                    external_message_id=source_neg,
                    direction="inbound",
                    text="Qué mal servicio, pésima atención",
                    shape_version="ig-comment-shapes-1.0.0",
                ),
            ]
        )
        session.flush()

    return connection_id, (source_pos, source_neg)


def test_seeded_comments_get_analyzed_with_provenance() -> None:
    connection_id, (source_pos, source_neg) = _seed_two_comments()
    version = _fresh_test_version()
    service = SentimentService(
        repository=PostgresSentimentRepository(), version=version, provider=StubProvider()
    )

    summary = service.analyze_pending_comments(tenant_id=TENANT_E2E, connection_id=connection_id)

    assert summary.comments_checked == 2
    assert summary.new_results == 2

    with tenant_session(TENANT_E2E) as session:
        rows = session.execute(
            text(
                "SELECT source_id, tenant_id, connection_id, detector_version, "
                "pipeline_version, model_id, model_revision, label "
                "FROM comment_sentiment_results "
                "WHERE connection_id = :cid AND detector_version = :dv"
            ),
            {"cid": str(connection_id), "dv": version.detector_version},
        ).all()

    by_source = {row.source_id: row for row in rows}
    assert set(by_source) == {source_pos, source_neg}
    assert by_source[source_pos].label == "POS"
    assert by_source[source_neg].label == "NEG"
    for row in rows:
        assert str(row.tenant_id) == str(TENANT_E2E)
        assert str(row.connection_id) == str(connection_id)
        assert row.detector_version == version.detector_version
        assert row.pipeline_version == version.pipeline_version
        assert row.model_id == version.model_id
        assert row.model_revision is None  # honest value, not invented


def test_running_it_twice_is_idempotent_no_duplicates() -> None:
    connection_id, _ = _seed_two_comments()
    version = _fresh_test_version()
    service = SentimentService(
        repository=PostgresSentimentRepository(), version=version, provider=StubProvider()
    )

    first = service.analyze_pending_comments(tenant_id=TENANT_E2E, connection_id=connection_id)
    second = service.analyze_pending_comments(tenant_id=TENANT_E2E, connection_id=connection_id)

    assert first.new_results == 2
    assert second.comments_checked == 0  # nothing left pending under this version

    with tenant_session(TENANT_E2E) as session:
        count = session.execute(
            text(
                "SELECT count(*) FROM comment_sentiment_results "
                "WHERE connection_id = :cid AND detector_version = :dv"
            ),
            {"cid": str(connection_id), "dv": version.detector_version},
        ).scalar_one()
    assert count == 2  # one row per seeded comment, not duplicated by the second run
