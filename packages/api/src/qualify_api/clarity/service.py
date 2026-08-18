"""Clarity insights service — configuration custody plus the budgeted refresh.

The shape that matters: `refresh` is the ONLY path that spends a live API request,
and it spends from an explicit daily budget (8, deliberately under Microsoft's hard
10-per-project-per-day) counted from the snapshot ledger. Everything else — the
dashboard, repeated page loads, tenant switching — reads the latest cached snapshot
and costs nothing. An analytics screen that silently burned quota on every render
would exhaust the day in one curious session.

Token custody: `configure` encrypts before the repository sees anything; `refresh`
decrypts for the single client call and lets the plaintext go out of scope. No other
method touches the token, and `SettingsStatus` (what the UI reads) never carries it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from qualify_api.clarity.client import ALLOWED_DIMENSIONS, ClarityClient
from qualify_api.clarity.repository import ClarityRepository, SnapshotRow
from qualify_api.connections.crypto import Encryptor

# Under Microsoft's 10 on purpose: the ledger only sees Qualify's own calls, so the
# margin absorbs a manual curl or two made outside the app on the same project.
DAILY_REFRESH_BUDGET = 8

_VALID_DAYS = (1, 2, 3)


class ClarityNotConfigured(Exception):
    """No active Clarity settings for this tenant — configure project id + token first."""


class RefreshBudgetExhausted(Exception):
    """Qualify's own daily budget is spent; cached snapshots remain readable."""


@dataclass(frozen=True)
class SettingsStatus:
    """What the UI may know about the configuration. Deliberately token-free."""

    project_id: str
    active: bool


class ClarityService:
    def __init__(
        self, *, repository: ClarityRepository, client: ClarityClient, encryptor: Encryptor
    ) -> None:
        self._repository = repository
        self._client = client
        self._encryptor = encryptor

    def settings_status(self, *, tenant_id: UUID) -> SettingsStatus | None:
        settings = self._repository.get_settings(tenant_id=tenant_id)
        if settings is None:
            return None
        return SettingsStatus(project_id=settings.project_id, active=settings.active)

    def configure(self, *, tenant_id: UUID, project_id: str, api_token: str) -> UUID:
        """Store (or replace) the tenant's Clarity project id + Data Export token."""
        project = project_id.strip()
        token = api_token.strip()
        if not project:
            raise ValueError("project_id must not be empty")
        if not token:
            raise ValueError("api_token must not be empty")
        return self._repository.upsert_settings(
            tenant_id=tenant_id,
            project_id=project,
            token_ciphertext=self._encryptor.encrypt(token),
            token_key_id=self._encryptor.key_id,
            active=True,
        )

    def latest(self, *, tenant_id: UUID) -> SnapshotRow | None:
        """The cached view — costs nothing, safe on every page load."""
        return self._repository.latest_snapshot(tenant_id=tenant_id)

    def remaining_budget(self, *, tenant_id: UUID) -> int:
        spent = self._repository.fetches_on(tenant_id=tenant_id, day=datetime.now(UTC).date())
        return max(0, DAILY_REFRESH_BUDGET - spent)

    def refresh(
        self,
        *,
        tenant_id: UUID,
        num_of_days: int = 3,
        dimensions: Sequence[str] = (),
    ) -> SnapshotRow:
        """Spend one live API request and cache the answer.

        Raises `ClarityNotConfigured`, `RefreshBudgetExhausted`, `ValueError` (bad
        parameters) or the client's `ClarityAPIError` family. Budget is checked before
        the settings read for the same reason the leads limiter fires first: the guard
        must protect the whole path, not the cheap half.
        """
        if num_of_days not in _VALID_DAYS:
            raise ValueError(f"num_of_days must be one of {_VALID_DAYS}")
        requested = [d for d in dimensions if d]
        if len(requested) > 3:
            raise ValueError("clarity accepts at most three dimensions")
        unknown = [d for d in requested if d not in ALLOWED_DIMENSIONS]
        if unknown:
            raise ValueError(f"unknown clarity dimensions: {unknown}")

        if self.remaining_budget(tenant_id=tenant_id) <= 0:
            raise RefreshBudgetExhausted

        settings = self._repository.get_settings(tenant_id=tenant_id)
        if settings is None or not settings.active:
            raise ClarityNotConfigured

        token = self._encryptor.decrypt(settings.token_ciphertext, key_id=settings.token_key_id)
        payload = self._client.live_insights(
            token=token, num_of_days=num_of_days, dimensions=requested
        )
        return self._repository.insert_snapshot(
            tenant_id=tenant_id,
            num_of_days=num_of_days,
            dimensions=requested,
            payload=payload,
        )
