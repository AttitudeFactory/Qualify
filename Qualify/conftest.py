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


@pytest.fixture(autouse=True)
def _no_uncategorized_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    """m-24955838: the «N productos sin categoría» rule is a database read
    (`catalog_provider.uncategorized_notice`). Offline tests never touch the database for
    it: nothing to show, unless a test sets its own."""
    from . import catalog_state, whatsapp_menu_state

    monkeypatch.setattr(catalog_state, "uncategorized_notice", lambda _t, _b: (0, False))
    monkeypatch.setattr(whatsapp_menu_state, "uncategorized_notice", lambda _t, _b: (0, False))


@pytest.fixture(autouse=True)
def _no_payment_methods_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """m-24955648: «¿cuántas formas de pago ofreces?» is a database read. Offline tests
    never touch the database for it: «could not read» (None), unless a test sets its own."""
    from . import whatsapp_menu_state

    monkeypatch.setattr(whatsapp_menu_state, "_payment_options", lambda _t, _b: None)
