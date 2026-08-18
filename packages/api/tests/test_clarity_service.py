"""Unit tests for the Clarity service: token custody through the Encryptor, the daily
budget over the snapshot ledger, parameter validation, and the guard ordering."""

from __future__ import annotations

from uuid import uuid4

import pytest

from qualify_api.clarity.repository import MemoryClarityRepository
from qualify_api.clarity.service import (
    DAILY_REFRESH_BUDGET,
    ClarityNotConfigured,
    ClarityService,
    RefreshBudgetExhausted,
)
from qualify_api.connections.crypto import DevEncryptor

TENANT = uuid4()

PAYLOAD = [{"metricName": "Traffic", "information": [{"totalSessionCount": "42"}]}]


class FakeClient:
    def __init__(self, payload: list[dict] | None = None) -> None:
        self.payload = payload or PAYLOAD
        self.calls: list[dict] = []

    def live_insights(self, *, token: str, num_of_days: int, dimensions) -> list[dict]:
        self.calls.append(
            {"token": token, "num_of_days": num_of_days, "dimensions": list(dimensions)}
        )
        return self.payload


def make_service(
    client: FakeClient | None = None,
) -> tuple[ClarityService, MemoryClarityRepository, FakeClient]:
    repo = MemoryClarityRepository()
    fake = client or FakeClient()
    service = ClarityService(repository=repo, client=fake, encryptor=DevEncryptor())
    return service, repo, fake


def test_configure_encrypts_and_refresh_decrypts_roundtrip() -> None:
    service, repo, client = make_service()
    service.configure(tenant_id=TENANT, project_id="abc123", api_token="tok-plain")

    stored = repo.get_settings(tenant_id=TENANT)
    assert stored is not None
    # At rest the token is ciphertext, never the plaintext.
    assert b"tok-plain" not in stored.token_ciphertext

    service.refresh(tenant_id=TENANT)
    # The client received the decrypted original.
    assert client.calls[0]["token"] == "tok-plain"


def test_settings_status_never_carries_the_token() -> None:
    service, _, _ = make_service()
    service.configure(tenant_id=TENANT, project_id="abc123", api_token="tok-plain")
    status = service.settings_status(tenant_id=TENANT)
    assert status is not None
    assert status.project_id == "abc123"
    assert not hasattr(status, "api_token")
    assert not hasattr(status, "token_ciphertext")


def test_refresh_without_configuration_raises() -> None:
    service, _, _ = make_service()
    with pytest.raises(ClarityNotConfigured):
        service.refresh(tenant_id=TENANT)


def test_refresh_stores_snapshot_and_latest_reads_it_back() -> None:
    service, _, _ = make_service()
    service.configure(tenant_id=TENANT, project_id="abc123", api_token="t")
    snapshot = service.refresh(tenant_id=TENANT, num_of_days=2, dimensions=["URL"])
    assert snapshot.payload == PAYLOAD
    latest = service.latest(tenant_id=TENANT)
    assert latest is not None
    assert latest.id == snapshot.id
    assert latest.num_of_days == 2
    assert latest.dimensions == ["URL"]


def test_budget_counts_down_and_exhausts() -> None:
    service, _, client = make_service()
    service.configure(tenant_id=TENANT, project_id="abc123", api_token="t")
    assert service.remaining_budget(tenant_id=TENANT) == DAILY_REFRESH_BUDGET

    for _ in range(DAILY_REFRESH_BUDGET):
        service.refresh(tenant_id=TENANT)
    assert service.remaining_budget(tenant_id=TENANT) == 0

    with pytest.raises(RefreshBudgetExhausted):
        service.refresh(tenant_id=TENANT)
    # The guard fired before the client was reached.
    assert len(client.calls) == DAILY_REFRESH_BUDGET


def test_budget_is_checked_before_configuration() -> None:
    """An unconfigured tenant with an exhausted ledger must see the budget error:
    the guard protects the whole path, mirroring the leads limiter ordering."""
    service, repo, _ = make_service()
    for _ in range(DAILY_REFRESH_BUDGET):
        repo.insert_snapshot(tenant_id=TENANT, num_of_days=1, dimensions=[], payload=[])
    with pytest.raises(RefreshBudgetExhausted):
        service.refresh(tenant_id=TENANT)


def test_latest_is_free_of_api_calls() -> None:
    service, _, client = make_service()
    service.configure(tenant_id=TENANT, project_id="abc123", api_token="t")
    service.refresh(tenant_id=TENANT)
    for _ in range(20):
        service.latest(tenant_id=TENANT)
    assert len(client.calls) == 1


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"num_of_days": 5}, "num_of_days"),
        ({"dimensions": ["URL", "OS", "Device", "Browser"]}, "three"),
        ({"dimensions": ["Nope"]}, "unknown"),
    ],
)
def test_refresh_validates_parameters(kwargs: dict, message: str) -> None:
    service, _, _ = make_service()
    service.configure(tenant_id=TENANT, project_id="abc123", api_token="t")
    with pytest.raises(ValueError, match=message):
        service.refresh(tenant_id=TENANT, **kwargs)


def test_inactive_settings_read_as_not_configured() -> None:
    service, repo, _ = make_service()
    service.configure(tenant_id=TENANT, project_id="abc123", api_token="t")
    stored = repo.settings[TENANT]
    repo.settings[TENANT] = (
        stored[0],
        type(stored[1])(
            project_id=stored[1].project_id,
            token_ciphertext=stored[1].token_ciphertext,
            token_key_id=stored[1].token_key_id,
            active=False,
        ),
    )
    with pytest.raises(ClarityNotConfigured):
        service.refresh(tenant_id=TENANT)


def test_configure_rejects_blank_values() -> None:
    service, _, _ = make_service()
    with pytest.raises(ValueError):
        service.configure(tenant_id=TENANT, project_id="  ", api_token="t")
    with pytest.raises(ValueError):
        service.configure(tenant_id=TENANT, project_id="abc", api_token="")
