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


@pytest.fixture(autouse=True)
def _generation_queue_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """m-24993023: a video by parts is only offered with the generation queue on
    (`creative_provider.parts_queue_on`). Offline tests do not depend on this machine's
    `QUALIFY_CREATIVE_DISPATCHER`: the queue is on, unless a test sets its own."""
    from . import creative_provider

    monkeypatch.setattr(creative_provider, "queue_enabled", lambda: True)


@pytest.fixture
def memory_r2():
    """CM-9 (m-24957283): the in-memory bucket every upload of a test lands in — with the
    `t/` lock (write-once, undeletable) of the production bucket."""
    from qualify_shared.objects.memory import MemoryObjectStore

    return MemoryObjectStore()


@pytest.fixture(autouse=True)
def _uploads_go_to_memory_r2(monkeypatch: pytest.MonkeyPatch, memory_r2) -> None:
    """Offline tests never reach R2: every screen's upload (`upload_store`) writes to the
    in-memory bucket; a test inspects it through `memory_r2`."""
    from qualify_shared.objects.gate import ObjectGate

    from . import upload_store

    gate = ObjectGate(memory_r2)
    monkeypatch.setattr(upload_store, "_gate", lambda: gate)
