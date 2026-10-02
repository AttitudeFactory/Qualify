"""`brand_kit_store` (0033): the brandboard's files and the wizards' answers, saved at
the end of the Brand Kit (§ request 2026-10-01).

The pure part (which file is the main logo) runs offline; the rest is `db`-marked."""

from __future__ import annotations

import io
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.schemas import BrandKit, ToneAxes
from qualify_shared.db.admin import admin_session
from qualify_shared.objects.keys import TenantPrefixViolation

from qualify_api.creative.brand_kit_store import (
    EXTRA,
    LOGO,
    LOGO_VERSION,
    BrandAsset,
    BrandKitStore,
    brand_asset_prefix,
    main_logo_key,
)
from qualify_api.creative.brand_service import BrandKitService
from qualify_api.creative.media import LocalMediaStore, R2ReadingMediaStore
from qualify_api.tenancy.models import Brand, Tenant, User

TENANT = UUID("c0000000-0000-4000-8000-0000000000a7")
OTHER = UUID("d0000000-0000-4000-8000-0000000000a7")


def _asset(kind: str, slot: str, name: str, **kw: Any) -> BrandAsset:
    return BrandAsset(kind=kind, slot=slot, object_key=f"t/{TENANT}/brand/x/{name}", **kw)


def test_the_main_logo_is_the_standalone_one_then_the_fullest_version() -> None:
    versions = [
        _asset(LOGO_VERSION, "isotipo", "iso.png"),
        _asset(LOGO_VERSION, "logotipo", "logo.png"),
        _asset(EXTRA, "a1", "sticker.png"),
    ]
    assert main_logo_key(versions) == f"t/{TENANT}/brand/x/logo.png"
    assert main_logo_key([*versions, _asset(LOGO_VERSION, "imagotipo", "imago.png")]).endswith(
        "imago.png"
    )
    assert main_logo_key([*versions, _asset(LOGO, "", "main.png")]).endswith("main.png")
    assert main_logo_key([_asset(EXTRA, "a1", "sticker.png")]) is None


def test_a_logo_kept_in_r2_is_read_through_the_tenant_checked_gate(tmp_path: Any) -> None:
    class Gate:
        def __init__(self) -> None:
            self.calls: list[tuple[UUID, str]] = []

        def open_object(self, tenant_id: UUID, key: str) -> io.BytesIO:
            self.calls.append((tenant_id, key))
            return io.BytesIO(b"r2-logo")

    local = LocalMediaStore(tmp_path)
    local.write("uploads/x/photo.png", b"local")
    gate = Gate()
    store = R2ReadingMediaStore(local, gate)
    key = f"t/{TENANT}/brand/b/logo.png"
    assert store.read(key) == b"r2-logo"
    assert gate.calls == [(TENANT, key)]
    assert store.read("uploads/x/photo.png") == b"local"
    store.write("generated/x/out.png", b"gen")  # writes stay local
    assert local.read("generated/x/out.png") == b"gen"


# -- database ------------------------------------------------------------------------------


@pytest.fixture
def seeded() -> tuple[UUID, UUID]:
    """A tenant (and another one) with a fresh brand and a user; idempotent re-runs."""
    with admin_session() as session:
        for tid, name in ((TENANT, "A"), (OTHER, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"brand-kit-store-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        brand = Brand(tenant_id=TENANT, name=f"brand-kit-store-{uuid4()}")
        user = User(tenant_id=TENANT, email=f"bks-{uuid4()}@a.co", display_name="U")
        session.add_all([brand, user])
        session.flush()
        return brand.id, user.id


def _kit(brand_id: UUID) -> BrandKit:
    return BrandKit(
        brand_id=brand_id,
        positioning="cafetería de especialidad",
        audience="oficinistas del centro",
        tone_axes=ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=40
        ),
        do_examples=("¡Tu primer café corre por nuestra cuenta!",),
    )


@pytest.mark.db
def test_the_saved_brandboard_is_exactly_the_last_one_saved(seeded: tuple[UUID, UUID]) -> None:
    brand, user = seeded
    BrandKitService().upsert_kit(tenant_id=TENANT, brand_id=brand, kit=_kit(brand), user_id=user)
    prefix = brand_asset_prefix(TENANT, brand)
    store = BrandKitStore()
    first = [
        BrandAsset(LOGO_VERSION, "isotipo", f"{prefix}logo_version/isotipo/a_iso.png", "iso.png"),
        BrandAsset(
            EXTRA,
            "e1",
            f"{prefix}extra/e1/b_patron.png",
            "patron.png",
            label="Patrón",
            context="Fondos de stories",
        ),
    ]
    assert store.replace_assets(tenant_id=TENANT, brand_id=brand, assets=first) == (
        f"{prefix}logo_version/isotipo/a_iso.png"
    )
    kit = BrandKitService().get_kit(tenant_id=TENANT, brand_id=brand)
    assert kit is not None and kit.logo_asset_key == f"{prefix}logo_version/isotipo/a_iso.png"

    # the extra was removed in the wizard and an imagotipo added: the set follows
    second = [
        first[0],
        BrandAsset(LOGO_VERSION, "imagotipo", f"{prefix}logo_version/imagotipo/c.png", "c.png"),
    ]
    store.replace_assets(tenant_id=TENANT, brand_id=brand, assets=second)
    saved = store.list_assets(tenant_id=TENANT, brand_id=brand)
    assert {(a.kind, a.slot) for a in saved} == {
        (LOGO_VERSION, "isotipo"),
        (LOGO_VERSION, "imagotipo"),
    }
    kit = BrandKitService().get_kit(tenant_id=TENANT, brand_id=brand)
    assert kit is not None and kit.logo_asset_key.endswith("imagotipo/c.png")  # type: ignore[union-attr]
    assert store.list_assets(tenant_id=OTHER, brand_id=brand) == []


@pytest.mark.db
def test_a_file_outside_the_tenants_prefix_is_refused(seeded: tuple[UUID, UUID]) -> None:
    brand, _user = seeded
    foreign = BrandAsset(LOGO_VERSION, "isotipo", f"t/{OTHER}/brand/{brand}/x.png", "x.png")
    with pytest.raises(TenantPrefixViolation):
        BrandKitStore().replace_assets(tenant_id=TENANT, brand_id=brand, assets=[foreign])


@pytest.mark.db
def test_details_save_only_the_documents_given(seeded: tuple[UUID, UUID]) -> None:
    brand, user = seeded
    store = BrandKitStore()
    assert store.load_details(tenant_id=TENANT, brand_id=brand).connect == {}
    store.save_details(
        tenant_id=TENANT,
        brand_id=brand,
        user_id=user,
        documents={
            "connect": {"city": "Cúcuta", "hashtags": [{"tag": "cafe", "origin": "manual"}]},
            "profile": {"username": "cafedelparque", "metrics": []},
        },
    )
    # the manual wizard saves only its logo brief: the connect answers stay
    store.save_details(
        tenant_id=TENANT,
        brand_id=brand,
        user_id=user,
        documents={"logo_brief": {"style": "minimalista"}},
    )
    details = store.load_details(tenant_id=TENANT, brand_id=brand)
    assert details.connect["city"] == "Cúcuta"
    assert details.profile["username"] == "cafedelparque"
    assert details.logo_brief == {"style": "minimalista"}
    assert store.load_details(tenant_id=OTHER, brand_id=brand).connect == {}
    with pytest.raises(ValueError):
        store.save_details(tenant_id=TENANT, brand_id=brand, user_id=user, documents={"x": {}})
