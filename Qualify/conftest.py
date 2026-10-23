"""Shared fixtures for the Reflex app's offline tests."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest


@pytest.fixture(autouse=True)
def _business_zone_is_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    """m-24842988: the inbox and reply dates read the business's zone from the database
    (`inbox_provider.tenant_zone`). Offline tests never touch the database for it: the
    zone is UTC unless a test sets its own."""
    from . import inbox_provider, replies_provider

    monkeypatch.setattr(inbox_provider, "tenant_zone", lambda _tenant_id: ZoneInfo("UTC"))
    monkeypatch.setattr(replies_provider, "tenant_zone", lambda _tenant_id: ZoneInfo("UTC"))
