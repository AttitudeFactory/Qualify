"""End-to-end `db` test against the REAL comments already ingested into Postgres by the
2026-08-21 live Meta validation (tenant PuntoServis, `@qualifymkt.co`) — not a fixture,
not synthetic data. Uses a stub provider (fast, deterministic, no weights) under a
test-only `AnalysisVersion` so it never collides with `CURRENT_ANALYSIS_VERSION` (the
real robertuito checkpoint).

**No cleanup — by design, confirmed with the founder 2026-08-22.** `comment_sentiment_
results` grants `qualify_app`/`qualify_admin` only `SELECT, INSERT` (migration 0012) —
the same append-only enforcement "versionar, no sobrescribir" requires. That means
there is structurally no sanctioned way for this test to DELETE its own rows without
either weakening the grant (which would defeat the point of the grant) or reaching for
an unsanctioned privileged connection (which the static Engine/Session guard exists to
prevent). The rows this test writes are permanently marked as test data —
`detector_version="test-e2e-stub-v1"`, `model_id="test/e2e-deterministic-stub"` — and
can never be mistaken for, or interfere with, a real production analysis pass. Nothing
about the two real `messages` rows or the connection is touched.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.sentiment.repository import AnalysisVersion, PostgresSentimentRepository
from qualify_api.sentiment.service import SentimentService

pytestmark = pytest.mark.db

# The real, live-validated connection from the 2026-08-21 Meta audit session.
TENANT_ID = UUID("a0000000-0000-4000-8000-000000000001")  # PuntoServis
CONNECTION_ID = UUID("ce99a28c-f875-4af1-8147-2a671124ce2d")


def _fresh_test_version() -> AnalysisVersion:
    """A unique version per call, not per module — two test functions in this file must
    not share one (the first would consume the second's "pending" comments). Since
    nothing is ever deleted (see module docstring), uniqueness per test is what keeps
    this file safely re-runnable against the same persistent dev database."""
    run_id = uuid4().hex[:8]
    return AnalysisVersion(
        detector_version=f"test-e2e-stub-v1-{run_id}",
        pipeline_version="test-e2e-stub-pipeline-v1",
        model_id="test/e2e-deterministic-stub",
        model_revision=None,
    )


class StubProvider:
    model_id = "test/e2e-deterministic-stub"

    def classify(self, text: str) -> tuple[str, float]:
        return ("NEG", 0.9) if any(w in text.lower() for w in ("mal", "pésim")) else ("NEU", 0.7)


def test_real_comments_already_in_postgres_get_analyzed_with_provenance() -> None:
    version = _fresh_test_version()
    repository = PostgresSentimentRepository()
    service = SentimentService(repository=repository, version=version, provider=StubProvider())

    summary = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    # The two real comments validated live on 2026-08-21 (17963827341154600,
    # 18107136746160164) are the known floor — more may exist if the account was synced
    # again since, which is fine, this asserts "at least", not "exactly".
    assert summary.comments_checked >= 2
    assert summary.new_results >= 2

    with tenant_session(TENANT_ID) as session:
        rows = session.execute(
            text(
                "SELECT source_id, tenant_id, connection_id, detector_version, "
                "pipeline_version, model_id, model_revision, label "
                "FROM comment_sentiment_results "
                "WHERE connection_id = :cid AND detector_version = :dv"
            ),
            {"cid": str(CONNECTION_ID), "dv": version.detector_version},
        ).all()

    source_ids = {row.source_id for row in rows}
    assert {"17963827341154600", "18107136746160164"} <= source_ids
    for row in rows:
        assert str(row.tenant_id) == str(TENANT_ID)
        assert str(row.connection_id) == str(CONNECTION_ID)
        assert row.detector_version == version.detector_version
        assert row.pipeline_version == version.pipeline_version
        assert row.model_id == version.model_id
        assert row.model_revision is None  # honest value, not invented
        assert row.label in {"POS", "NEG", "NEU"}


def test_running_it_twice_is_idempotent_no_duplicates() -> None:
    version = _fresh_test_version()
    repository = PostgresSentimentRepository()
    service = SentimentService(repository=repository, version=version, provider=StubProvider())

    first = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)
    second = service.analyze_pending_comments(tenant_id=TENANT_ID, connection_id=CONNECTION_ID)

    assert first.new_results >= 2
    assert second.comments_checked == 0  # nothing left pending under this version

    with tenant_session(TENANT_ID) as session:
        count = session.execute(
            text(
                "SELECT count(*) FROM comment_sentiment_results "
                "WHERE connection_id = :cid AND detector_version = :dv "
                "AND source_id IN ('17963827341154600', '18107136746160164')"
            ),
            {"cid": str(CONNECTION_ID), "dv": version.detector_version},
        ).scalar_one()
    assert count == 2  # one row per real comment, not duplicated by the second run
