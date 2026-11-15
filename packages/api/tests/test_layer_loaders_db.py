"""m-25017283 review: what the layer stage reads from the database, with real rows — the
business's saved data (its WhatsApp line's address and number, its ACTIVE payment methods
in order, at most four) and the catalog products a brief names (whether each price prints
whole) — and that one business never reads another's data, regeneration claims included."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative.layer_store import (
    claim_base_regeneration,
    load_business_facts,
    load_catalog_products,
)
from qualify_api.creative.models import PieceBaseRegeneration
from qualify_api.whatsapp.models import BrandPaymentMethod, WhatsAppPhoneNumber

from .test_piece_layers_db import _piece
from .test_whatsapp_catalog_grants_db import OTHER_TENANT, TENANT, _product, seeded

pytestmark = pytest.mark.db

__all__ = ["seeded"]  # the fixture, imported for this module


def _methods(brand: UUID, *rows: tuple[str, bool]) -> None:
    with tenant_session(TENANT) as session:
        for position, (name, active) in enumerate(rows):
            session.add(
                BrandPaymentMethod(
                    tenant_id=TENANT,
                    brand_id=brand,
                    name=name,
                    name_key=f"{name.lower()}-{uuid4().hex[:6]}",
                    pay_on_delivery=True,
                    active=active,
                    position=position,
                )
            )


def test_the_saved_data_is_the_line_and_the_active_payment_methods(seeded) -> None:  # noqa: ANN001
    with tenant_session(TENANT) as session:
        line = session.get(WhatsAppPhoneNumber, seeded["phone"])
        line.location_address = "C.C. Las Palmas, local 5"
    _methods(
        seeded["brand"],
        ("Efectivo", True),
        ("Tarjeta", False),
        ("Nequi", True),
        ("Daviplata", True),
        ("Transferencia", True),
        ("Bancolombia", True),
    )
    facts = load_business_facts(TENANT, seeded["brand"])
    assert facts.location == "C.C. Las Palmas, local 5"
    assert facts.contact == "+57 300 000 0015"
    assert facts.payment == "Efectivo · Nequi · Daviplata · Transferencia"  # active, ≤ 4
    assert facts.hours is None and facts.products is None  # not stored yet


def test_a_business_without_saved_data_has_none(seeded) -> None:  # noqa: ANN001
    facts = load_business_facts(TENANT, uuid4())
    assert facts.available() == []


def test_another_business_s_data_is_never_read(seeded) -> None:  # noqa: ANN001
    _methods(seeded["brand"], ("Efectivo", True))
    facts = load_business_facts(OTHER_TENANT, seeded["brand"])  # A's brand, as B
    assert facts.payment is None and facts.contact is None and facts.location is None
    assert load_catalog_products(OTHER_TENANT, seeded["brand"], "Agua") == ()


def test_the_products_a_brief_names_with_whether_their_price_prints(seeded) -> None:  # noqa: ANN001
    with tenant_session(TENANT) as session:
        _product(session, TENANT, seeded["brand"], "Shawarma mixto", position=3)
        _product(session, TENANT, seeded["brand"], "Shawarma de pollo", position=4, price=None)
    exact = load_catalog_products(TENANT, seeded["brand"], "Agua")
    assert [(p.name, p.has_price) for p in exact] == [("Agua", True)]
    prefix = load_catalog_products(TENANT, seeded["brand"], "shawarma")
    assert [(p.name, p.has_price) for p in prefix] == [
        ("Shawarma mixto", True),
        ("Shawarma de pollo", False),  # no price: the layer may not point at it
    ]
    assert load_catalog_products(TENANT, seeded["brand"], "Descontinuado") == ()  # inactive
    assert load_catalog_products(TENANT, seeded["brand"], " ") == ()


def test_another_business_cannot_read_a_regeneration_claim(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = seeded_ab
    brand, draft, _ = _piece(tenant_a, version=False)
    assert claim_base_regeneration(
        tenant_id=tenant_a,
        brand_id=brand,
        draft_id=draft,
        revision=1,
        position=0,
        reason="base_has_invented_text",
        model_id="claude-sonnet-5-5",
        prompt_version="capa-v2",
    )
    query = select(PieceBaseRegeneration).where(PieceBaseRegeneration.draft_id == draft)
    with tenant_session(tenant_a) as session:
        assert len(session.scalars(query).all()) == 1
    with tenant_session(tenant_b) as session:
        assert session.scalars(query).all() == []
