"""m-24976896 against Postgres: «Ahora no» lands in the brand's details under the row
lock, keeps earlier dismissals and the wizard's own answers, and is idempotent."""

from __future__ import annotations

import pytest
from packages.api.tests.test_creative_retention_db import TENANT_A, _provision

from qualify_api.creative.brand_kit_store import BrandKitStore
from qualify_api.whatsapp.seasons import BrandDetailsDismissedStore

pytestmark = pytest.mark.db


def test_dismissals_accumulate_and_survive_a_wizard_save() -> None:
    brand, user, _ = _provision(TENANT_A, "A")
    store = BrandDetailsDismissedStore()
    store.dismiss(TENANT_A, brand, "navidad-2026")
    store.dismiss(TENANT_A, brand, "ano-nuevo-2027")
    store.dismiss(TENANT_A, brand, "navidad-2026")
    BrandKitStore().save_details(
        tenant_id=TENANT_A, brand_id=brand, user_id=user, documents={"connect": {"city": "Cúcuta"}}
    )
    assert store.dismissed(TENANT_A, brand)[-2:] == ["ano-nuevo-2027", "navidad-2026"]
    connect = BrandKitStore().load_details(tenant_id=TENANT_A, brand_id=brand).connect
    assert connect["city"] == "Cúcuta"
