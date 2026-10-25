"""m-24852129 (offline): the fixed 90-day packs — only the three named packs, their
prices from `precios-planes-v1`, the consumption order (plan first, then the pack that
expires first), the units given back to whoever paid, day 91, and the «Pedir más»
request (once, by WhatsApp or by email)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_creative.creations import CreationPrice

from qualify_api.creative.creations import InMemoryCreationsLedger, NotEnoughCreations
from qualify_api.plans import ask_more
from qualify_api.plans.billing import LINE_PACK, PackPurchase, charges_for_month
from qualify_api.plans.catalog import (
    PACK_DAYS,
    UnknownPack,
    load_plans,
    load_prices,
    pack_by_name,
)
from qualify_api.plans.pack_service import PackRefused, add_pack
from qualify_api.plans.packs import (
    CREATIONS,
    SOURCE_PACK,
    SOURCE_PLAN,
    VIDEOS,
    PackBalance,
    SourcesExhausted,
    dimension_balance,
    split,
)
from qualify_api.support.service import CONTEXT_KEYS

BASICO = load_plans().get("basico")
OCT_24 = datetime(2026, 10, 24, 15, tzinfo=UTC)


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


# --- only the three fixed packs, priced by the versioned table -----------------------


@pytest.mark.parametrize(
    ("name", "code", "units", "price"),
    [
        ("+2 videos", "videos_2", (0, 2, 0), "29"),
        ("+20 creaciones", "creations_20", (20, 0, 0), "12"),
        ("+10 vistas previas", "previews_10", (0, 0, 10), "19"),
        ("  +2  Videos ", "videos_2", (0, 2, 0), "29"),
        ("creations_20", "creations_20", (20, 0, 0), "12"),
    ],
)
def test_the_three_packs_by_name(name: str, code: str, units: tuple, price: str) -> None:
    pack = pack_by_name(name)
    assert pack.code == code
    assert (pack.creations, pack.videos, pack.previews) == units
    assert pack.price == Decimal(price)


@pytest.mark.parametrize("name", ["+3 videos", "5", "20 creaciones extra", "", "+2"])
def test_a_free_quantity_or_unknown_name_is_refused(name: str) -> None:
    with pytest.raises(UnknownPack):
        pack_by_name(name)


def test_add_pack_refuses_before_touching_the_database(monkeypatch) -> None:
    def boom():  # noqa: ANN202
        raise AssertionError("admin_session must not open for a refused pack")

    monkeypatch.setattr("qualify_api.plans.pack_service.admin_session", boom)
    with pytest.raises(PackRefused, match="not a pack"):
        add_pack(tenant_id=uuid4(), pack="+5 videos", reason="x", granted_by="e@a.co")
    with pytest.raises(PackRefused, match="reason"):
        add_pack(tenant_id=uuid4(), pack="+2 videos", reason=" ", granted_by="e@a.co")
    with pytest.raises(PackRefused, match="negative"):
        add_pack(
            tenant_id=uuid4(), pack="+2 videos", reason="x", granted_by="e@a.co", usd_paid="-1"
        )


def test_packs_last_90_days() -> None:
    assert PACK_DAYS == 90
    assert (OCT_24 + timedelta(days=PACK_DAYS)).date() == date(2027, 1, 22)


def test_the_report_charges_a_pack_at_what_was_paid() -> None:
    oct_ = date(2026, 10, 1)
    paid = PackPurchase("videos_2", OCT_24, "precios-planes-v1", usd=Decimal("25.00"))
    default = PackPurchase("creations_20", OCT_24, "precios-planes-v1")
    lines = charges_for_month([], oct_, packs=[paid, default])
    assert [(line.kind, line.code, line.usd) for line in lines] == [
        (LINE_PACK, "videos_2", Decimal("25.00")),
        (LINE_PACK, "creations_20", Decimal("12")),
    ]
    assert {line.prices_version for line in lines} == {"precios-planes-v1"}


# --- consumption order (D17) -----------------------------------------------------------


def _pack(expires: datetime, *, videos: int = 2, used: int = 0, live: bool = True) -> PackBalance:
    return PackBalance(
        id=uuid4(),
        code="videos_2",
        expires_at=expires,
        live=live,
        units={VIDEOS: videos},
        used={VIDEOS: used},
        used_in_period={VIDEOS: used},
    )


def test_split_takes_the_plan_first_then_the_pack_that_expires_first() -> None:
    late = _pack(OCT_24 + timedelta(days=60))
    soon = _pack(OCT_24 + timedelta(days=10))
    out = split(VIDEOS, 4, 1, [late, soon])
    assert [(a.source, a.pack_id, a.units) for a in out] == [
        (SOURCE_PLAN, None, 1),
        (SOURCE_PACK, soon.id, 2),
        (SOURCE_PACK, late.id, 1),
    ]
    with pytest.raises(SourcesExhausted):
        split(VIDEOS, 6, 1, [late, soon])
    assert [a.source for a in split(VIDEOS, 3, None, [soon])] == [SOURCE_PLAN]


def test_with_plan_left_a_creation_comes_from_the_plan_not_the_pack() -> None:
    ledger = InMemoryCreationsLedger(plan=BASICO, clock=Clock(OCT_24))
    ledger.add_pack(pack_by_name("+20 creaciones"))
    tenant, brand = uuid4(), uuid4()
    ledger.charge(
        tenant_id=tenant, brand_id=brand, draft_id=uuid4(), revision=1, price=CreationPrice("x", 1)
    )
    [row] = ledger.rows.values()
    assert [(a.source, a.units) for a in row.allocations] == [(SOURCE_PLAN, 1)]
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert (balance.left, balance.quota, balance.extra_left) == (49, 50, 20)


def test_with_the_plan_at_zero_a_creation_comes_from_the_pack() -> None:
    ledger = InMemoryCreationsLedger(plan=BASICO, used=30, clock=Clock(OCT_24))
    pack_id = ledger.add_pack(pack_by_name("+20 creaciones"))
    tenant, brand = uuid4(), uuid4()
    ledger.charge(
        tenant_id=tenant, brand_id=brand, draft_id=uuid4(), revision=1, price=CreationPrice("x", 2)
    )
    [row] = ledger.rows.values()
    assert [(a.source, a.pack_id, a.units) for a in row.allocations] == [(SOURCE_PACK, pack_id, 2)]
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert (balance.left, balance.extra_left) == (18, 18)


def test_founders_example_basico_plus_two_videos_one_used() -> None:
    ledger = InMemoryCreationsLedger(plan=BASICO, videos_used=1, clock=Clock(OCT_24))
    ledger.add_pack(pack_by_name("+2 videos"), granted_at=OCT_24)
    balance = ledger.balance(tenant_id=uuid4(), brand_id=uuid4())
    assert (balance.videos_left, balance.video_quota) == (5, 6)
    assert balance.extra_videos_left == 2
    assert balance.extra_videos_expires_on == date(2027, 1, 22)


def test_the_balance_grows_after_a_pack_and_the_kind_can_be_created_again() -> None:
    tenant, brand = uuid4(), uuid4()
    ledger = InMemoryCreationsLedger(plan=BASICO, videos_used=4, clock=Clock(OCT_24))
    draft = uuid4()
    with pytest.raises(NotEnoughCreations):
        ledger.charge_videos(tenant_id=tenant, brand_id=brand, draft_id=draft, revision=1, videos=1)
    ledger.add_pack(pack_by_name("+2 videos"))
    assert ledger.balance(tenant_id=tenant, brand_id=brand).videos_left == 2
    assert ledger.charge_videos(
        tenant_id=tenant, brand_id=brand, draft_id=draft, revision=1, videos=1
    )


def test_day_91_the_pack_stops_counting() -> None:
    clock = Clock(OCT_24)
    ledger = InMemoryCreationsLedger(plan=BASICO, videos_used=4, clock=clock)
    ledger.add_pack(pack_by_name("+2 videos"), granted_at=OCT_24)
    clock.at = OCT_24 + timedelta(days=90) - timedelta(seconds=1)
    assert ledger.balance(tenant_id=uuid4(), brand_id=uuid4()).videos_left == 2
    clock.at = OCT_24 + timedelta(days=90)
    balance = ledger.balance(tenant_id=uuid4(), brand_id=uuid4())
    assert (balance.videos_left, balance.extra_videos_left) == (0, 0)


def test_a_pack_carries_into_next_month_while_it_lives() -> None:
    # November: the plan's month is new, the pack still has what October left of it
    pack = _pack(OCT_24 + timedelta(days=90), used=1)
    november = PackBalance(
        id=pack.id,
        code=pack.code,
        expires_at=pack.expires_at,
        live=True,
        units=pack.units,
        used={VIDEOS: 1},
        used_in_period={},
    )
    dim = dimension_balance(VIDEOS, 4, 0, [november])
    assert (dim.plan_left, dim.extra_left, dim.left, dim.quota) == (4, 1, 5, 5)
    expired = PackBalance(
        id=pack.id,
        code=pack.code,
        expires_at=pack.expires_at,
        live=False,
        units=pack.units,
        used={VIDEOS: 1},
        used_in_period={},
    )
    gone = dimension_balance(VIDEOS, 4, 0, [expired])
    assert (gone.left, gone.quota, gone.extra_left) == (4, 4, 0)


def test_a_refund_gives_the_units_back_to_the_pack_that_paid() -> None:
    tenant, brand = uuid4(), uuid4()
    ledger = InMemoryCreationsLedger(plan=BASICO, used=29, clock=Clock(OCT_24))
    ledger.add_pack(pack_by_name("+20 creaciones"))
    draft = uuid4()
    ledger.charge(
        tenant_id=tenant, brand_id=brand, draft_id=draft, revision=1, price=CreationPrice("x", 3)
    )
    assert ledger.balance(tenant_id=tenant, brand_id=brand).extra_left == 18
    assert ledger.refund(tenant_id=tenant, draft_id=draft, revision=1, reason="falló")
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert (balance.left, balance.extra_left) == (21, 20)


def test_a_failed_final_gives_its_video_back_to_the_last_source_first() -> None:
    tenant, brand = uuid4(), uuid4()
    ledger = InMemoryCreationsLedger(plan=BASICO, videos_used=3, clock=Clock(OCT_24))
    ledger.add_pack(pack_by_name("+2 videos"))
    draft = uuid4()
    ledger.charge_videos(tenant_id=tenant, brand_id=brand, draft_id=draft, revision=1, videos=2)
    assert ledger.balance(tenant_id=tenant, brand_id=brand).extra_videos_left == 1
    assert ledger.refund_final(
        tenant_id=tenant, draft_id=draft, revision=1, reason="x", asset_ids=[uuid4()]
    )
    balance = ledger.balance(tenant_id=tenant, brand_id=brand)
    assert (balance.videos_left, balance.extra_videos_left) == (2, 2)


def test_a_revoked_pack_stops_counting() -> None:
    ledger = InMemoryCreationsLedger(plan=BASICO, clock=Clock(OCT_24))
    pack_id = ledger.add_pack(pack_by_name("+20 creaciones"))
    assert ledger.revoke_pack(pack_id)
    assert not ledger.revoke_pack(pack_id)
    assert ledger.balance(tenant_id=uuid4(), brand_id=uuid4()).quota == 30


def test_without_packs_the_balance_is_the_plans() -> None:
    balance = InMemoryCreationsLedger(plan=BASICO).balance(tenant_id=uuid4(), brand_id=uuid4())
    assert (balance.quota, balance.video_quota, balance.preview_quota) == (30, 4, 20)
    assert (balance.extra_left, balance.extra_videos_left, balance.extra_previews_left) == (0, 0, 0)
    assert dimension_balance(CREATIONS, 30, 5, []).quota == 30


def test_prices_file_holds_the_founders_prices() -> None:
    packs = load_prices().packs
    assert {code: p.price for code, p in packs.items()} == {
        "videos_2": Decimal("29"),
        "creations_20": Decimal("12"),
        "previews_10": Decimal("19"),
    }


# --- «Pedir más a Qualify» -------------------------------------------------------------


def test_the_request_may_say_what_ran_out() -> None:
    assert "exhausted" in CONTEXT_KEYS


@contextmanager
def _no_db(_tenant: UUID):  # noqa: ANN202
    yield object()


@pytest.mark.parametrize(("whatsapp", "expected"), [("+57 300 000 0000", True), ("", False)])
def test_request_more_contact_by_whatsapp_or_email(monkeypatch, whatsapp, expected) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(ask_more, "tenant_session", _no_db)
    monkeypatch.setattr(ask_more, "business_whatsapp", lambda _s, _t: whatsapp)
    monkeypatch.setattr(ask_more, "pending_in_session", lambda _s, _t, _n: False)
    monkeypatch.setattr(ask_more, "_zone", lambda _s, _t: "America/Bogota")
    monkeypatch.setattr(ask_more, "plan_in_session", lambda _s, _t, _p: BASICO)
    monkeypatch.setattr(
        ask_more, "create_support_request", lambda **kw: seen.update(kw) or "ticket"
    )
    tenant = uuid4()
    result = ask_more.request_more(tenant, email="dueno@negocio.co", exhausted="videos")
    assert result.created and result.by_whatsapp is expected
    assert seen == {
        "tenant_id": tenant,
        "topic": "more_creations",
        "contact_email": "dueno@negocio.co",
        "contact_whatsapp": whatsapp,
        "context": {"screen": "crear", "plan": "basico", "exhausted": "videos"},
        "notifier": None,
    }


def test_request_more_from_settings_says_so(monkeypatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(ask_more, "tenant_session", _no_db)
    monkeypatch.setattr(ask_more, "business_whatsapp", lambda _s, _t: "")
    monkeypatch.setattr(ask_more, "pending_in_session", lambda _s, _t, _n: False)
    monkeypatch.setattr(ask_more, "_zone", lambda _s, _t: "UTC")
    monkeypatch.setattr(ask_more, "plan_in_session", lambda _s, _t, _p: BASICO)
    monkeypatch.setattr(ask_more, "create_support_request", lambda **kw: seen.update(kw))
    ask_more.request_more(uuid4(), email="d@n.co", exhausted="settings")
    assert seen["context"] == {
        "screen": "settings",
        "plan": "basico",
        "exhausted": "desde Configuración",
    }


def test_a_second_tap_creates_no_second_request(monkeypatch) -> None:
    monkeypatch.setattr(ask_more, "tenant_session", _no_db)
    monkeypatch.setattr(ask_more, "business_whatsapp", lambda _s, _t: "")
    monkeypatch.setattr(ask_more, "pending_in_session", lambda _s, _t, _n: True)

    def never(**_kw: object) -> None:
        raise AssertionError("no second request")

    monkeypatch.setattr(ask_more, "create_support_request", never)
    result = ask_more.request_more(uuid4(), email="d@n.co", exhausted="creations")
    assert not result.created


def test_request_more_refuses_an_unknown_kind() -> None:
    with pytest.raises(ask_more.InvalidAskMore):
        ask_more.request_more(uuid4(), email="d@n.co", exhausted="dinero")
