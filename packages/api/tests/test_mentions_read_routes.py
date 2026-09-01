"""`GET /api/mentions` and `POST /api/mentions/analyze-sentiment` (QUA-49) — the Dashboard
de Menciones' read/analysis routes, exercised end-to-end with zero network and zero DB.
Mirrors `test_inbox_routes.py`'s harness shape: only the injected seam functions are
fakes, everything below them (request/response models, Principal-based identity) is real.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from qualify_api.http import deps, mentions_routes
from qualify_api.http.app import create_app
from qualify_api.mentions.repository import MentionRecord
from qualify_api.mentions.sentiment import MentionAnalysisSummary

TENANT = UUID("11111111-1111-4111-8111-111111111111")
USER = UUID("22222222-2222-4222-8222-222222222222")
CONNECTION = UUID("33333333-3333-4333-8333-333333333333")
AUTH = {"Authorization": "Bearer tok-mentions"}


class Harness:
    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        records: tuple[MentionRecord, ...] = (),
        analysis: MentionAnalysisSummary | None = None,
    ) -> None:
        monkeypatch.setenv("QUALIFY_DEV_PRINCIPALS", f"tok-mentions:{TENANT}:{USER}")
        self.list_calls: list[tuple[UUID, UUID | None]] = []
        self.analyze_calls: list[UUID] = []

        def fake_list_mentions(
            *, tenant_id: UUID, connection_id: UUID | None = None
        ) -> tuple[MentionRecord, ...]:
            self.list_calls.append((tenant_id, connection_id))
            return records

        def fake_analyze(*, tenant_id: UUID) -> MentionAnalysisSummary:
            self.analyze_calls.append(tenant_id)
            return analysis or MentionAnalysisSummary(
                mentions_checked=0, new_results=0, skipped_empty=0
            )

        app = create_app(configure_production=False)
        app.dependency_overrides[mentions_routes.get_list_mentions] = lambda: fake_list_mentions
        app.dependency_overrides[mentions_routes.get_analyze_mention_sentiment] = lambda: (
            fake_analyze
        )
        app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
        self.http = TestClient(app)


def _record(*, comment_id: str | None = None, sentiment_label: str | None = None) -> MentionRecord:
    return MentionRecord(
        id=uuid4(),
        connection_id=CONNECTION,
        platform="instagram",
        external_account_id="ig-user-1",
        media_id="media-1",
        comment_id=comment_id,
        caption="hola @qualifymkt.co" if comment_id is None else None,
        text="hola @qualifymkt.co" if comment_id is not None else None,
        author_username="someone",
        like_count=3,
        content_posted_at=datetime(2026, 8, 1, tzinfo=UTC),
        received_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
        enrichment_status="ENRICHED",
        sentiment_label=sentiment_label,
    )


def test_list_mentions_returns_the_records(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, records=(_record(sentiment_label="POS"),))

    response = harness.http.get("/api/mentions", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["media_id"] == "media-1"
    assert body[0]["sentiment"] == "POS"
    assert "views" not in body[0]  # never fabricated, never even a field


def test_list_mentions_uses_the_callers_tenant_not_a_client_supplied_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `tenant_id` on the request — identity is the Principal's (C1), same
    discipline `SyncRequest`/`AnalyzeRequest` already document for their own routes."""
    harness = Harness(monkeypatch)

    harness.http.get("/api/mentions", headers=AUTH)

    assert harness.list_calls == [(TENANT, None)]


def test_list_mentions_forwards_the_connection_id_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch)

    harness.http.get("/api/mentions", params={"connection_id": str(CONNECTION)}, headers=AUTH)

    assert harness.list_calls == [(TENANT, CONNECTION)]


def test_list_mentions_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch)

    response = harness.http.get("/api/mentions")

    assert response.status_code in (401, 403)


def test_a_caption_mention_has_no_comment_id_but_has_caption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = Harness(monkeypatch, records=(_record(comment_id=None),))

    body = harness.http.get("/api/mentions", headers=AUTH).json()

    assert body[0]["comment_id"] is None
    assert body[0]["caption"] == "hola @qualifymkt.co"
    assert body[0]["text"] is None


def test_a_comment_mention_has_a_comment_id_and_text(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(monkeypatch, records=(_record(comment_id="c1"),))

    body = harness.http.get("/api/mentions", headers=AUTH).json()

    assert body[0]["comment_id"] == "c1"
    assert body[0]["text"] == "hola @qualifymkt.co"
    assert body[0]["caption"] is None


def test_analyze_sentiment_runs_for_the_callers_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    harness = Harness(
        monkeypatch,
        analysis=MentionAnalysisSummary(mentions_checked=3, new_results=2, skipped_empty=1),
    )

    response = harness.http.post("/api/mentions/analyze-sentiment", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"mentions_checked": 3, "new_results": 2, "skipped_empty": 1}
    assert harness.analyze_calls == [TENANT]
