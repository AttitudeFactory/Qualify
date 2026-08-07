"""C1 — Principal authentication for the HTTP surface, fully offline.

What is protected here: identity reaches routes ONLY through an authenticated
`Principal`. The dev resolver maps opaque bearer credentials from the environment;
tenant/user never travel in a request body, and `qualify_shared.dev`'s process-global
never leaks into HTTP.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from qualify_api.http import connections_routes, deps
from qualify_api.http.app import create_app
from qualify_api.http.deps import Principal, build_dev_principal_dependency, parse_dev_principals

TENANT_A = UUID("11111111-1111-4111-8111-111111111111")
USER_A = UUID("33333333-3333-4333-8333-333333333333")
TENANT_B = UUID("55555555-5555-4555-8555-555555555555")
USER_B = UUID("66666666-6666-4666-8666-666666666666")

HTTP_SRC = Path(__file__).resolve().parents[1] / "src" / "qualify_api" / "http"


class RecordingService:
    """The one method the start route needs, recording what identity it was handed."""

    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID | None, UUID]] = []

    def start_connect(self, *, tenant_id: UUID, brand_id: UUID | None, user_id: UUID) -> str:
        self.calls.append((tenant_id, brand_id, user_id))
        return "https://platform.example/dialog?state=st"


def _client(map_env: str, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, RecordingService]:
    monkeypatch.setenv("QUALIFY_DEV_PRINCIPALS", map_env)
    service = RecordingService()
    app = create_app(configure_production=False)
    app.dependency_overrides[connections_routes.get_connect_service] = lambda: service
    app.dependency_overrides[deps.current_principal] = build_dev_principal_dependency()
    return TestClient(app), service


# --------------------------------------------------------------------------------------
# Parsing the operator's map
# --------------------------------------------------------------------------------------


def test_parse_reads_multiple_entries_and_tolerates_whitespace() -> None:
    mapping = parse_dev_principals(f"tok-a:{TENANT_A}:{USER_A} , tok-b:{TENANT_B}:{USER_B},")
    assert mapping == {
        "tok-a": Principal(tenant_id=TENANT_A, user_id=USER_A),
        "tok-b": Principal(tenant_id=TENANT_B, user_id=USER_B),
    }


def test_parse_rejects_malformed_entries_loudly() -> None:
    """A typo in the operator's own map must fail the BOOT, not surface as a mystery 401."""
    for raw in (f"tok:{TENANT_A}", f":{TENANT_A}:{USER_A}", f"tok:not-a-uuid:{USER_A}"):
        with pytest.raises(ValueError):
            parse_dev_principals(raw)


def test_malformed_env_fails_app_assembly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUALIFY_DEV_PRINCIPALS", "garbage")
    with pytest.raises(ValueError):
        create_app(configure_production=True)


# --------------------------------------------------------------------------------------
# The credential on the wire
# --------------------------------------------------------------------------------------


def test_valid_bearer_resolves_principal_and_reaches_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, service = _client(f"tok-a:{TENANT_A}:{USER_A}", monkeypatch)

    response = client.post(
        "/api/connections/start", json={}, headers={"Authorization": "Bearer tok-a"}
    )

    assert response.status_code == 200
    assert response.json()["authorization_url"].startswith("https://platform.example/")
    # The service received the PRINCIPAL's identity — nothing came from the body.
    assert service.calls == [(TENANT_A, None, USER_A)]


def test_every_credential_failure_is_one_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing header, wrong scheme, unknown token: one indistinguishable 401 — naming
    the failed check would help the caller forge the next attempt."""
    client, service = _client(f"tok-a:{TENANT_A}:{USER_A}", monkeypatch)

    for headers in (
        {},
        {"Authorization": "tok-a"},
        {"Authorization": "Basic tok-a"},
        {"Authorization": "Bearer wrong"},
    ):
        response = client.post("/api/connections/start", json={}, headers=headers)
        assert response.status_code == 401, headers
        assert response.json()["detail"] == "not authenticated"
    assert service.calls == []


def test_body_supplied_identity_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """A client naming a tenant/user in the body changes NOTHING — the fields do not
    exist on the model, and the principal's identity is what reaches the service."""
    client, service = _client(f"tok-a:{TENANT_A}:{USER_A}", monkeypatch)

    response = client.post(
        "/api/connections/start",
        json={"tenant_id": str(TENANT_B), "user_id": str(USER_B)},
        headers={"Authorization": "Bearer tok-a"},
    )

    assert response.status_code == 200
    assert service.calls == [(TENANT_A, None, USER_A)]


# --------------------------------------------------------------------------------------
# Structural shields
# --------------------------------------------------------------------------------------


def test_http_layer_never_touches_the_dev_tenant_global() -> None:
    """C1: `qualify_shared.dev` keeps ONE legitimate consumer (the in-process Reflex UI).
    An HTTP client cannot set a process-local global, so any `get_dev_tenant` in `http/`
    is a route that lies about where identity comes from."""
    for source_file in HTTP_SRC.glob("*.py"):
        assert "get_dev_tenant" not in source_file.read_text(), source_file.name


def test_principal_resolution_never_touches_the_database() -> None:
    """The dev resolver is env-only. RLS (via `tenant_session`, fed by the routes) stays
    the single decider of visibility; deps.py building sessions would be a second door."""
    source = (HTTP_SRC / "deps.py").read_text()
    assert "qualify_shared" not in source
    assert "Session" not in source
