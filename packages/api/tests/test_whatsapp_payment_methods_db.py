"""m-24955648 — `brand_payment_methods` (0131) against the real database: RLS isolation
(and the NULLIF policy with no tenant set), the folded unique name per business, the
«active needs content unless paid on delivery» CHECK, the QR key's tenant prefix, and the
worker reader's tenant + brand filter.

Provisioning through `admin_session`; everything under test through `tenant_session` or
the worker door, as production does.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from qualify_api.tenancy.models import Brand, Tenant
from qualify_api.whatsapp.models import BrandPaymentMethod
from qualify_api.whatsapp.payments import (
    MemoryQrStore,
    PaymentMethodService,
    PaymentNameTaken,
    PostgresPaymentMethodRepository,
    active_payment_methods,
)

pytestmark = pytest.mark.db

TENANT_A = UUID("a0000000-0000-4000-8000-000000955649")
TENANT_B = UUID("b0000000-0000-4000-8000-000000955649")


def _brand(tenant_id: UUID, name: str) -> UUID:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=name,
                    country="VE",
                    timezone="America/Caracas",
                    currency="USD",
                )
            )
            session.flush()
        brand = Brand(tenant_id=tenant_id, name=f"pagos-{uuid4()}")
        session.add(brand)
        session.flush()
        return brand.id


def _service() -> PaymentMethodService:
    return PaymentMethodService(PostgresPaymentMethodRepository(), MemoryQrStore())


def test_a_method_round_trips_and_another_tenant_never_sees_it() -> None:
    brand = _brand(TENANT_A, "A")
    _brand(TENANT_B, "B")
    service = _service()
    pago = service.create_payment_method(
        tenant_id=TENANT_A,
        brand_id=brand,
        user_id=None,
        name="Pago móvil",
        currency="VES",
        instructions="Banco de Venezuela · 0414-1234567",
    )
    service.set_active(
        tenant_id=TENANT_A, brand_id=brand, method_id=pago.id, user_id=None, active=True
    )
    listed = service.list_payment_methods(tenant_id=TENANT_A, brand_id=brand)
    assert [(m.name, m.currency, m.active) for m in listed] == [("Pago móvil", "VES", True)]
    with tenant_session(TENANT_B) as session:
        assert session.scalars(select(BrandPaymentMethod)).all() == []
    assert active_payment_methods(TENANT_B, brand) == ()
    # The worker door: tenant AND brand filtered in code.
    assert [m.name for m in active_payment_methods(TENANT_A, brand, as_worker=True)] == [
        "Pago móvil"
    ]
    assert active_payment_methods(TENANT_B, brand, as_worker=True) == ()


def test_no_tenant_set_reads_nothing() -> None:
    """The NULLIF policy: an app connection with no `app.tenant_id` sees no row."""
    brand = _brand(TENANT_A, "A")
    _service().create_payment_method(
        tenant_id=TENANT_A, brand_id=brand, user_id=None, name=f"N-{uuid4().hex[:6]}"
    )
    from qualify_shared.db.config import app_dsn
    from sqlalchemy import create_engine

    engine = create_engine(app_dsn())
    try:
        with engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM brand_payment_methods")).scalar_one()
        assert count == 0
    finally:
        engine.dispose()


def test_the_folded_name_is_unique_per_business() -> None:
    brand = _brand(TENANT_A, "A")
    repo = PostgresPaymentMethodRepository()
    service = _service()
    first = service.create_payment_method(
        tenant_id=TENANT_A, brand_id=brand, user_id=None, name="Pago Móvil"
    )
    # Past the service's pre-check, the constraint still holds.
    with pytest.raises(PaymentNameTaken):
        repo.insert(
            first.__class__(
                id=uuid4(),
                tenant_id=TENANT_A,
                brand_id=brand,
                name="pago movil",
                name_key=first.name_key,
            )
        )
    other = _brand(TENANT_A, "A")
    service.create_payment_method(
        tenant_id=TENANT_A, brand_id=other, user_id=None, name="Pago Móvil"
    )


@pytest.mark.parametrize(
    ("values", "ok"),
    [
        ({"active": True}, False),  # nothing to send
        ({"active": True, "pay_on_delivery": True}, True),  # cash on delivery
        ({"active": True, "instructions": "Pagas así."}, True),
        ({"qr_media_key": "t/00000000-0000-0000-0000-000000000000/whatsapp/payments/x.png"}, False),
        ({"name": "x" * 21}, False),
        ({"instructions": "x" * 901}, False),
        ({"source": "pedidos"}, False),
    ],
)
def test_the_checks_hold_in_the_database(values: dict, ok: bool) -> None:
    brand = _brand(TENANT_A, "A")
    row = {"name": f"F-{uuid4().hex[:8]}", **values}
    row.setdefault("name_key", row["name"].casefold())

    def insert() -> None:
        with tenant_session(TENANT_A) as session:
            session.add(BrandPaymentMethod(tenant_id=TENANT_A, brand_id=brand, **row))
            session.flush()

    if ok:
        insert()
    else:
        with pytest.raises(DBAPIError):
            insert()


def test_a_row_cannot_point_at_another_tenants_brand() -> None:
    brand_b = _brand(TENANT_B, "B")
    with pytest.raises(DBAPIError), tenant_session(TENANT_A) as session:
        session.add(
            BrandPaymentMethod(tenant_id=TENANT_A, brand_id=brand_b, name="X", name_key="x")
        )
        session.flush()
