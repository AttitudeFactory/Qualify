"""`POST /api/sentiment/analyze` error mapping — same harness shape as
`test_inbox_routes.py`: the route and its mapping are real, only the injected
`analyze_pending_comments` callable is a fake. No network, no DB, no model."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from qualify_api.http import deps, sentiment_routes
from qualify_api.http.app import create_app
from qualify_api.sentiment.composition import UnknownSentimentConnection
from qualify_api.sentiment.service import AnalysisSummary, SentimentModelUnavailable

TENANT = UUID("44444444-4444-4444-8444-444444444445")
USER = UUID("55555555-5555-4555-8555-555555555556")
CONNECTION = UUID("66666666-6666-4666-8666-666666666667")
AUTH = {"Authorization": "Bearer tok-sentiment"}


def _client(monkeypatch: pytest.MonkeyPatch, fn: Callable[..., AnalysisSummary]) -> TestClient:
    monkeypatch.setenv("QUALIFY_DEV_PRINCIPALS", f"tok-sentiment:{TENANT}:{USER}")
    app = create_app(configure_production=False)
    app.dependency_overrides[sentiment_routes.get_analyze_pending_comments] = lambda: fn
    app.dependency_overrides[deps.current_principal] = deps.build_dev_principal_dependency()
    return TestClient(app)


def _post(client: TestClient) -> object:
    return client.post(
        "/api/sentiment/analyze", json={"connection_id": str(CONNECTION)}, headers=AUTH
    )


def test_analysis_runs_for_the_principals_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[UUID, UUID]] = []

    def fn(*, tenant_id: UUID, connection_id: UUID) -> AnalysisSummary:
        calls.append((tenant_id, connection_id))
        return AnalysisSummary(comments_checked=2, new_results=1, skipped_empty=1)

    response = _post(_client(monkeypatch, fn))

    assert response.status_code == 200, response.text
    assert response.json() == {"comments_checked": 2, "new_results": 1, "skipped_empty": 1}
    assert calls == [(TENANT, CONNECTION)]


def test_unknown_connection_is_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def fn(*, tenant_id: UUID, connection_id: UUID) -> AnalysisSummary:
        raise UnknownSentimentConnection(str(connection_id))

    assert _post(_client(monkeypatch, fn)).status_code == 404


def test_a_missing_model_runtime_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """B8: not a 500 — the deployment lacks the model, which is a known, stable state."""

    def fn(*, tenant_id: UUID, connection_id: UUID) -> AnalysisSummary:
        raise SentimentModelUnavailable("the `ml` dependency group is not installed")

    response = _post(_client(monkeypatch, fn))

    assert response.status_code == 503
    assert response.json() == {"detail": "sentiment model unavailable"}
