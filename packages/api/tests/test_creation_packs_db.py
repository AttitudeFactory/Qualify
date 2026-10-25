"""`db`-marked tests for the 90-day packs (0095, m-24852129): `add_pack` and its payment,
the isolation of packs and payments (RLS + grants: the owner can neither create a pack
nor read an amount), the consumption order written at charge time, given back with the
charge, day 91 and the month change, the cost report and the «Pedir más» request.

The root `conftest.py` migrates the test database to head before any `db` test runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_creative.creations import CreationPrice
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from qualify_api.creative.creations import NotEnoughCreations, PostgresCreationsLedger
from qualify_api.plans import report
from qualify_api.plans.ask_more import ask_more_status, request_more
from qualify_api.plans.models import CreationAllocation, CreationPack
from qualify_api.plans.notify import RecordingTeamNotifier
from qualify_api.plans.pack_service import PackRefused, add_pack, list_packs, revoke_pack
from qualify_api.plans.schedule import month_of
from qualify_api.support.models import SupportRequest
from qualify_api.support.notify import SupportNotification
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

OCT_24 = datetime(2026, 10, 24, 15, tzinfo=UTC)


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


class RecordingSupport:
    def __init__(self) -> None:
        self.sent: list[SupportNotification] = []

    def notify(self, notification: SupportNotification) -> bool:
        self.sent.append(notification)
        return True


def _tenant() -> tuple[UUID, UUID]:
    with admin_session() as session:
        tenant = Tenant(
            name=f"packs-{uuid4().hex[:6]}",
            country="CO",
            timezone="America/Bogota",
            currency="COP",
        )
        session.add(tenant)
        session.flush()
        brand = Brand(tenant_id=tenant.id, name="packs-brand")
        session.add(brand)
        session.flush()
        return tenant.id, brand.id


def _add(tenant: UUID, pack: str, at: datetime = OCT_24, **kw: object):  # noqa: ANN202
    return add_pack(
        tenant_id=tenant,
        pack=pack,
        reason=kw.pop("reason", "pidió más"),
        granted_by="equipo@attitudefactory.co",
        now=at,
        notifier=RecordingTeamNotifier(),
        **kw,
    )


def _charge(ledger: PostgresCreationsLedger, tenant: UUID, brand: UUID, weight: int) -> UUID:
    draft = uuid4()
    ledger.charge(
        tenant_id=tenant,
        brand_id=brand,
        draft_id=draft,
        revision=1,
        price=CreationPrice("image", weight),
    )
    return draft


def _approve_video(ledger: PostgresCreationsLedger, tenant: UUID, brand: UUID) -> UUID:
    draft = uuid4()
    ledger.charge_videos(tenant_id=tenant, brand_id=brand, draft_id=draft, revision=1, videos=1)
    return draft


def _allocations(tenant: UUID) -> list[tuple[str, str, int, int]]:
    with tenant_session(tenant) as session:
        rows = session.scalars(
            select(CreationAllocation).order_by(
                CreationAllocation.created_at, CreationAllocation.seq
            )
        )
        return [(r.dimension, r.source, r.units, r.reversed_units) for r in rows]


# --- the team's write path -------------------------------------------------------------


def test_add_pack_writes_the_pack_its_payment_and_closes_the_request() -> None:
    tenant, brand = _tenant()
    ticket = request_more(
        tenant, email="dueno@negocio.co", exhausted="videos", notifier=RecordingSupport()
    )
    assert ticket.created and ticket.ticket is not None
    result = _add(tenant, "+2 videos", support_request_id=ticket.ticket.id, payment_ref="Zelle 1")
    assert result.changed and result.pack_code == "videos_2"
    assert result.usd_paid == Decimal("29.00") and result.prices_version == "precios-planes-v1"
    assert result.expires_at == OCT_24 + timedelta(days=90)
    with admin_session() as session:
        pack = session.get(CreationPack, result.pack_id)
        assert pack is not None
        assert (pack.creations, pack.videos, pack.previews) == (0, 2, 0)
        assert (pack.source, pack.brand_id, pack.granted_by) == (
            "support_request",
            brand,
            "equipo@attitudefactory.co",
        )
        paid = session.execute(
            text(
                "SELECT usd_paid, prices_version, payment_ref FROM creation_payments "
                "WHERE pack_id = :id"
            ),
            {"id": result.pack_id},
        ).one()
        assert tuple(paid) == (Decimal("29.00"), "precios-planes-v1", "Zelle 1")
        status = session.scalar(
            text("SELECT status FROM support_requests WHERE id = :id"), {"id": ticket.ticket.id}
        )
        assert status == "closed"
    # the same request and pack again: nothing new
    again = _add(tenant, "+2 videos", support_request_id=ticket.ticket.id)
    assert not again.changed and again.pack_id == result.pack_id


def test_only_the_fixed_packs_are_accepted_and_nothing_is_written() -> None:
    tenant, _ = _tenant()
    for name in ("+3 videos", "7", "videos"):
        with pytest.raises(PackRefused):
            _add(tenant, name)
    assert list_packs(tenant) == []


def test_a_request_of_another_business_is_refused() -> None:
    a, _ = _tenant()
    b, _ = _tenant()
    other = request_more(a, email="a@a.co", exhausted="creations", notifier=RecordingSupport())
    assert other.ticket is not None
    with pytest.raises(PackRefused, match="not one of tenant"):
        _add(b, "+20 creaciones", support_request_id=other.ticket.id)
    assert list_packs(b) == []


def test_revoke_stops_the_pack_and_is_idempotent() -> None:
    tenant, brand = _tenant()
    result = _add(tenant, "+20 creaciones")
    ledger = PostgresCreationsLedger(clock=Clock(OCT_24 + timedelta(hours=1)))
    assert ledger.balance(tenant_id=tenant, brand_id=brand).quota == 50
    assert revoke_pack(
        result.pack_id, reason="error", revoked_by="e@a.co", notifier=RecordingTeamNotifier()
    )
    assert not revoke_pack(
        result.pack_id, reason="error", revoked_by="e@a.co", notifier=RecordingTeamNotifier()
    )
    assert ledger.balance(tenant_id=tenant, brand_id=brand).quota == 30


# --- isolation --------------------------------------------------------------------------


def test_the_owner_cannot_create_a_pack_nor_read_an_amount() -> None:
    tenant, brand = _tenant()
    _add(tenant, "+2 videos")
    with pytest.raises(ProgrammingError, match="permission denied"):
        with tenant_session(tenant) as session:
            session.execute(text("SELECT usd_paid FROM creation_payments"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        with tenant_session(tenant) as session:
            session.execute(
                text(
                    "INSERT INTO creation_packs (tenant_id, brand_id, subscription_id, "
                    "pack_code, prices_version, creations, videos, previews, granted_at, "
                    "expires_at, source, reason, granted_by, idempotency_key) "
                    "SELECT :t, :b, subscription_id, 'videos_2', 'v', 0, 2, 0, now(), "
                    "now() + interval '90 days', 'manual', 'x', 'x', 'owner' "
                    "FROM tenants WHERE id = :t"
                ),
                {"t": tenant, "b": brand},
            )


def test_a_business_never_sees_another_ones_packs() -> None:
    a, _ = _tenant()
    b, _ = _tenant()
    _add(a, "+20 creaciones")
    with tenant_session(b) as session:
        assert session.scalars(select(CreationPack)).all() == []
    with tenant_session(a) as session:
        assert len(session.scalars(select(CreationPack)).all()) == 1


# --- consumption order, given back, day 91, month change --------------------------------


def test_plan_first_then_the_pack() -> None:
    tenant, brand = _tenant()
    _add(tenant, "+20 creaciones")
    ledger = PostgresCreationsLedger(clock=Clock(OCT_24 + timedelta(hours=1)))
    _charge(ledger, tenant, brand, 29)
    assert _allocations(tenant)[-1] == ("creations", "plan", 29, 0)
    _charge(ledger, tenant, brand, 3)  # 1 from the plan, 2 from the pack
    assert _allocations(tenant)[-2:] == [("creations", "plan", 1, 0), ("creations", "pack", 2, 0)]
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert (balance.left, balance.quota, balance.extra_left) == (18, 50, 18)


def test_a_refund_gives_the_units_back_to_the_pack() -> None:
    tenant, brand = _tenant()
    _add(tenant, "+20 creaciones")
    ledger = PostgresCreationsLedger(clock=Clock(OCT_24 + timedelta(hours=1)))
    _charge(ledger, tenant, brand, 30)
    draft = _charge(ledger, tenant, brand, 5)
    assert ledger.balance(tenant_id=tenant, brand_id=brand).extra_left == 15
    assert ledger.refund(tenant_id=tenant, draft_id=draft, revision=1, reason="falló")
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert (balance.left, balance.extra_left) == (20, 20)
    assert ("creations", "pack", 5, 5) in _allocations(tenant)


def test_founders_example_and_a_failed_final() -> None:
    tenant, brand = _tenant()
    clock = Clock(OCT_24 + timedelta(hours=1))
    ledger = PostgresCreationsLedger(clock=clock)
    _approve_video(ledger, tenant, brand)
    _add(tenant, "+2 videos")
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert (balance.videos_left, balance.video_quota, balance.extra_videos_left) == (5, 6, 2)
    assert str(balance.extra_videos_expires_on) == "2027-01-22"
    for _ in range(3):
        _approve_video(ledger, tenant, brand)  # the plan's 4 are gone
    last = _approve_video(ledger, tenant, brand)  # paid by the pack
    assert ledger.balance(tenant_id=tenant, brand_id=brand).extra_videos_left == 1
    assert ledger.refund_final(
        tenant_id=tenant, draft_id=last, revision=1, reason="x", asset_ids=[uuid4()]
    )
    assert ledger.balance(tenant_id=tenant, brand_id=brand).extra_videos_left == 2


def test_the_pack_crosses_the_month_and_stops_on_day_91() -> None:
    tenant, brand = _tenant()
    clock = Clock(OCT_24 + timedelta(hours=1))
    ledger = PostgresCreationsLedger(clock=clock)
    for _ in range(4):
        _approve_video(ledger, tenant, brand)
    _add(tenant, "+2 videos")
    _approve_video(ledger, tenant, brand)  # October: from the pack
    clock.at = datetime(2026, 11, 10, 15, tzinfo=UTC)  # November: a new plan month
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert (balance.videos_left, balance.video_quota, balance.extra_videos_left) == (5, 5, 1)
    clock.at = OCT_24 + timedelta(days=90) - timedelta(minutes=1)  # 22 Jan, still live
    assert ledger.balance(tenant_id=tenant, brand_id=brand).extra_videos_left == 1
    clock.at = OCT_24 + timedelta(days=90)  # day 91
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert (balance.videos_left, balance.extra_videos_left) == (4, 0)
    for _ in range(4):
        _approve_video(ledger, tenant, brand)
    with pytest.raises(NotEnoughCreations):
        _approve_video(ledger, tenant, brand)


# --- the team's report -------------------------------------------------------------------


def test_the_report_adds_the_pack_to_the_month_charged() -> None:
    tenant, _ = _tenant()
    _add(tenant, "+10 vistas previas", usd_paid="19")
    _add(tenant, "+2 videos", usd_paid="25")
    [month] = report.fetch(month_of(OCT_24), tenant)
    packs = [(line.code, line.usd, line.prices_version) for line in month.lines]
    assert ("previews_10", Decimal("19.00"), "precios-planes-v1") in packs
    assert ("videos_2", Decimal("25.00"), "precios-planes-v1") in packs
    assert month.charged_usd == Decimal("44.00")


# --- «Pedir más a Qualify» ---------------------------------------------------------------


def test_pedir_mas_saves_once_by_email_and_comes_back_after_a_pack() -> None:
    tenant, _ = _tenant()
    support = RecordingSupport()
    first = request_more(tenant, email="dueno@negocio.co", exhausted="videos", notifier=support)
    assert first.created and not first.by_whatsapp
    assert ask_more_status(tenant).pending
    second = request_more(tenant, email="dueno@negocio.co", exhausted="videos", notifier=support)
    assert not second.created
    assert len(support.sent) == 1
    sent = support.sent[0]
    assert sent.topic == "more_creations" and sent.contact_email == "dueno@negocio.co"
    assert sent.context == {"screen": "crear", "plan": "basico", "exhausted": "videos"}
    with tenant_session(tenant) as session:
        rows = session.scalars(select(SupportRequest)).all()
        assert [(r.topic, r.tenant_id, r.contact_whatsapp) for r in rows] == [
            ("more_creations", tenant, "")
        ]
    _add(tenant, "+2 videos", at=datetime.now(UTC))
    assert not ask_more_status(tenant).pending
