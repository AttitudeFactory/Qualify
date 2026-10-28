"""The full WhatsApp contact stays in tenant storage, never the public details."""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from qualify_api.creative import brand_kit_store as store_module
from qualify_api.creative.brand_kit_store import (
    BrandKitStore,
    carry_reserved,
    visible_connect,
)

NUMBER = "573001234548"


@pytest.mark.parametrize(
    "number",
    ["", "+573001234548", "012345678", "1234567", "1" * 16, "•" * 12, "57 300 123 4548", None],
)
def test_invalid_contacts_never_open_a_database_session(number: Any, monkeypatch: Any) -> None:
    def forbidden(*_a: Any) -> None:
        pytest.fail("invalid contact reached the database")

    monkeypatch.setattr(store_module, "tenant_session", forbidden)
    with pytest.raises(ValueError, match="invalid WhatsApp contact") as error:
        BrandKitStore().capture_whatsapp_contact(tenant_id=uuid4(), brand_id=uuid4(), number=number)
    if number:
        assert str(number) not in str(error.value)


def test_visible_details_are_a_copy_and_a_wizard_save_preserves_private_contact() -> None:
    stored = {"city": "Cúcuta", "contact": {"whatsapp": NUMBER, "label": "Pedidos"}}
    visible = visible_connect(stored)
    assert visible == {"city": "Cúcuta", "contact": {"label": "Pedidos"}}
    assert NUMBER not in json.dumps(visible)
    assert stored["contact"]["whatsapp"] == NUMBER
    assert carry_reserved("connect", stored, {"city": "Bogotá"})["contact"] == stored["contact"]
    visible["contact"]["label"] = "Reservas"
    saved = carry_reserved("connect", stored, visible)
    assert saved["contact"] == {"whatsapp": NUMBER, "label": "Reservas"}
    assert stored["contact"]["label"] == "Pedidos"


@pytest.mark.parametrize(
    "existing", [{"label": "Pedidos"}, {"whatsapp": ""}, {"whatsapp": "otro"}, {"whatsapp": None}]
)
def test_capture_is_locked_tenant_scoped_and_never_overwrites_an_existing_choice(
    existing: dict, monkeypatch: Any
) -> None:
    tenant, brand = uuid4(), uuid4()
    row = SimpleNamespace(
        connect={"city": "Cúcuta", "contact": existing.copy()}, logo_brief={}, profile={}
    )
    calls: list = []
    locks: list[bool] = []

    class Session:
        def execute(self, statement: Any) -> None:
            calls.append(str(statement))

        def get(self, model: Any, identity: Any, *, with_for_update: bool = False) -> Any:
            assert model is store_module.DetailsRow
            assert identity == brand
            locks.append(with_for_update)
            return row

        def flush(self) -> None:
            calls.append("flush")

    @contextmanager
    def door(actual: Any) -> Any:
        assert actual == tenant
        yield Session()

    monkeypatch.setattr(store_module, "tenant_session", door)
    store = BrandKitStore()
    assert store.capture_whatsapp_contact(tenant_id=tenant, brand_id=brand, number=NUMBER) == (
        "whatsapp" not in existing
    )
    assert row.connect["city"] == "Cúcuta"
    assert row.connect["contact"] == (
        existing if "whatsapp" in existing else existing | {"whatsapp": NUMBER}
    )
    assert "ON CONFLICT (brand_id) DO NOTHING" in calls[0]
    assert not store.capture_whatsapp_contact(
        tenant_id=tenant, brand_id=brand, number="59899123456"
    )
    assert locks == [True, True]
    assert "whatsapp" not in store.load_details(tenant_id=tenant, brand_id=brand).connect["contact"]
