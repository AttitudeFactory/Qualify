"""What a creator charges (m-24955847): the owner's amount parser, the rate's rules, the
facade's `set_creator_rate` / `business_currency`, and how prices meet the comparison."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from qualify_api.creators import access, service
from qualify_api.creators import metrics as m
from qualify_api.creators.rates import (
    MAX_RATE,
    InvalidRate,
    parse_rate_amount,
    validate_rate,
)
from qualify_api.creators.tracking import MemoryTrackedCreatorStore, NewReelRead, NewSnapshot
from qualify_api.tenancy.locale import BusinessLocale

NOW = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
TENANT = UUID("c0000000-0000-4000-8000-0000000000d1")
OTHER_TENANT = UUID("c0000000-0000-4000-8000-0000000000d2")
BRAND = uuid4()
OTHER_BRAND = uuid4()


# -- parse_rate_amount ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "amount"),
    [
        ("150.000", "150000"),
        ("150000", "150000"),
        ("1.500,50", "1500.50"),
        ("1,500.50", "1500.50"),
        ("$ 150.000", "150000"),
        ("$150.000", "150000"),
        ("150.000 COP", "150000"),
        ("COP 150.000", "150000"),
        ("US$ 200", "200"),
        ("Bs. 300", "300"),
        ("150 mil", "150000"),
        ("150mil", "150000"),
        ("150 mil pesos", "150000"),
        ("150k", "150000"),
        ("1,5 millones", "1500000"),
        ("2 millones", "2000000"),
        ("1 millón", "1000000"),
        ("150.5", "150.50"),  # one «.» + 1-2 digits = decimals
        ("150,50", "150.50"),
        ("0,5", "0.50"),
        ("1,500", "1500"),  # one separator + exactly 3 digits = thousands
        ("1.500.000", "1500000"),
        ("1,500,000", "1500000"),
        ("150 000", "150000"),
        ("12,345,678.9", "12345678.90"),
        ("0", "0"),
        ("-0", "0"),
        ("9.999.999.999,99", "9999999999.99"),
    ],
)
def test_the_owner_s_amount_is_read_by_its_shape(typed: str, amount: str) -> None:
    value = parse_rate_amount(typed)
    assert value == Decimal(amount)
    assert value is not None and value.as_tuple().exponent == -2  # always in cents


@pytest.mark.parametrize("typed", ["", "   ", " "])
def test_a_blank_amount_is_none(typed: str) -> None:
    assert parse_rate_amount(typed) is None


@pytest.mark.parametrize(
    ("typed", "reason"),
    [
        ("abc", "not_a_number"),
        ("mil", "not_a_number"),
        ("1.2.3", "not_a_number"),
        ("1.50.000", "not_a_number"),
        ("150.5555", "not_a_number"),  # money has at most 2 decimals
        ("1234.567", "not_a_number"),  # «thousands» with 4 digits before the mark
        (".5", "not_a_number"),
        ("1.", "not_a_number"),
        ("150.000 - 200.000", "not_a_number"),  # a range is two amounts
        ("1.500,000", "not_a_number"),
        ("150 500 mil 3", "not_a_number"),
        ("-5", "negative"),
        ("$ -150.000", "negative"),
        ("−20", "negative"),
        ("99999999999", "too_large"),
        ("10.000 millones", "too_large"),
    ],
)
def test_an_amount_that_is_not_one_clear_number_is_refused(typed: str, reason: str) -> None:
    with pytest.raises(InvalidRate) as caught:
        parse_rate_amount(typed)
    assert caught.value.reason == reason


# -- validate_rate ------------------------------------------------------------------------------


def test_validate_strips_notes_upcases_currency_and_rounds_to_cents() -> None:
    rate = validate_rate("  1 reel 150.000  ", Decimal("150000.005"), " cop ")
    assert (rate.notes, rate.amount, rate.currency) == (
        "1 reel 150.000",
        Decimal("150000.01"),
        "COP",
    )


def test_without_an_amount_the_currency_is_dropped() -> None:
    rate = validate_rate("solo canje", None, "USD")
    assert (rate.notes, rate.amount, rate.currency) == ("solo canje", None, None)


@pytest.mark.parametrize(
    ("notes", "amount", "currency", "reason"),
    [
        ("x" * 1001, None, None, "notes_too_long"),
        ("", Decimal("100"), None, "currency_required"),
        ("", Decimal("100"), "  ", "currency_required"),
        ("", Decimal("100"), "EUR", "unsupported_currency"),
        ("", Decimal("-1"), "COP", "negative"),
        ("", MAX_RATE + Decimal("0.01"), "COP", "too_large"),
        ("", Decimal("NaN"), "COP", "not_a_number"),
        ("", Decimal("Infinity"), "COP", "not_a_number"),
    ],
)
def test_a_rate_breaking_a_rule_is_refused(
    notes: str, amount: Decimal | None, currency: str | None, reason: str
) -> None:
    with pytest.raises(InvalidRate) as caught:
        validate_rate(notes, amount, currency)
    assert caught.value.reason == reason


def test_a_thousand_characters_of_notes_fit_after_stripping() -> None:
    assert len(validate_rate("  " + "x" * 1000 + "  ", None, None).notes) == 1000


# -- the facade -------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(access.ENV, f"{TENANT},{OTHER_TENANT}")
    access.reset_cache()
    yield
    access.reset_cache()
    service.configure_store(None)


@pytest.fixture
def store() -> MemoryTrackedCreatorStore:
    memory = MemoryTrackedCreatorStore()
    service.configure_store(memory)
    return memory


def _track(store, handle: str = "fake.creator", tenant: UUID = TENANT, brand: UUID = BRAND):
    return store.add(
        tenant, brand, network="instagram", handle=handle, note="", user_id=None, now=NOW
    )


def test_set_creator_rate_saves_and_list_and_sheet_return_it(store) -> None:
    tracked = _track(store)
    saved = service.set_creator_rate(
        TENANT,
        BRAND,
        tracked.id,
        notes=" 1 reel 150.000; paquete 3 reels + 5 historias 380.000 ",
        amount=Decimal("150000"),
        currency="cop",
        now=NOW,
    )
    assert saved.rate_notes == "1 reel 150.000; paquete 3 reels + 5 historias 380.000"
    assert (saved.rate_from, saved.rate_currency, saved.rate_updated_at) == (
        Decimal("150000.00"),
        "COP",
        NOW,
    )
    (card,) = service.list_creators(TENANT, BRAND, now=NOW)
    assert card.tracked.rate_from == Decimal("150000.00")
    assert card.tracked.rate_currency == "COP"
    # the sheet carries the rate next to the read's figures
    snap_id = uuid4()
    store.snapshot_rows[snap_id] = NewSnapshot(
        id=snap_id,
        network="instagram",
        handle="fake.creator",
        read_at=NOW,
        status="ok",
        parser_version=1,
        reels_target=48,
    )
    store.mark(TENANT, BRAND, tracked.id, state="ok", error=None, now=NOW, snapshot_id=snap_id)
    sheet = service.creator_sheet(TENANT, BRAND, tracked.id, now=NOW)
    assert sheet is not None
    assert (sheet.rate_notes, sheet.rate_from, sheet.rate_currency, sheet.rate_updated_at) == (
        saved.rate_notes,
        Decimal("150000.00"),
        "COP",
        NOW,
    )


def test_clearing_the_amount_clears_the_currency_and_keeps_the_notes(store) -> None:
    tracked = _track(store)
    service.set_creator_rate(
        TENANT, BRAND, tracked.id, notes="a", amount=Decimal("10"), currency="USD"
    )
    later = NOW + timedelta(hours=1)
    saved = service.set_creator_rate(
        TENANT, BRAND, tracked.id, notes="canje", amount=None, currency="USD", now=later
    )
    assert (saved.rate_notes, saved.rate_from, saved.rate_currency) == ("canje", None, None)
    assert saved.rate_updated_at == later


def test_set_creator_rate_validates_before_touching_the_row(store) -> None:
    tracked = _track(store)
    with pytest.raises(service.InvalidRate) as caught:
        service.set_creator_rate(
            TENANT, BRAND, tracked.id, notes="", amount=Decimal("5"), currency=None
        )
    assert caught.value.reason == "currency_required"
    assert store.get(TENANT, BRAND, tracked.id).rate_updated_at is None


def test_an_archived_or_foreign_creator_cannot_be_priced(store) -> None:
    tracked = _track(store)
    other = _track(store, "fake.other", OTHER_TENANT, OTHER_BRAND)
    for tenant, brand, tracked_id in (
        (TENANT, BRAND, other.id),  # another business's creator
        (TENANT, OTHER_BRAND, tracked.id),  # another brand
        (TENANT, BRAND, uuid4()),
    ):
        with pytest.raises(service.CreatorNotFound):
            service.set_creator_rate(
                tenant, brand, tracked_id, notes="x", amount=None, currency=None
            )
    assert store.get(OTHER_TENANT, OTHER_BRAND, other.id).rate_notes == ""
    service.archive_creator(TENANT, BRAND, tracked.id)
    with pytest.raises(service.CreatorNotFound):
        service.set_creator_rate(TENANT, BRAND, tracked.id, notes="x", amount=None, currency=None)


def test_re_adding_an_archived_creator_keeps_his_rate(store) -> None:
    tracked = _track(store)
    service.set_creator_rate(
        TENANT, BRAND, tracked.id, notes="n", amount=Decimal("7"), currency="USD"
    )
    service.archive_creator(TENANT, BRAND, tracked.id)
    again = _track(store)
    assert (again.id, again.rate_from, again.rate_currency) == (tracked.id, Decimal("7.00"), "USD")


def test_the_rate_functions_refuse_a_business_without_the_module(store, monkeypatch) -> None:
    monkeypatch.setenv(access.ENV, str(OTHER_TENANT))
    access.reset_cache()
    with pytest.raises(service.CreatorsDisabled):
        service.set_creator_rate(TENANT, BRAND, uuid4(), notes="", amount=None, currency=None)
    with pytest.raises(service.CreatorsDisabled):
        service.business_currency(TENANT)


@pytest.mark.parametrize(
    ("locale", "currency"),
    [
        (BusinessLocale("CO", "America/Bogota", "COP"), "COP"),
        (BusinessLocale("VE", "America/Caracas", "USD"), "USD"),
        (BusinessLocale("VE", "America/Caracas", "VES"), "VES"),
        (BusinessLocale("UY", "America/Montevideo", "UYU"), "UYU"),
        (BusinessLocale("XX", "UTC", "EUR"), "COP"),
        (None, "COP"),
    ],
)
def test_business_currency_preselects_the_business_s_own(
    monkeypatch, locale: BusinessLocale | None, currency: str
) -> None:
    monkeypatch.setattr(service, "read_business_locale", lambda _tenant: locale)
    assert service.business_currency(TENANT) == currency


def test_the_facade_exports_the_contract() -> None:
    assert service.RATE_CURRENCIES == ("COP", "USD", "VES", "UYU")
    assert service.parse_rate_amount("150 mil") == Decimal("150000")
    assert issubclass(service.InvalidRate, Exception)


# -- prices in the comparison ----------------------------------------------------------------

READ_AT = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)


def _reels(views: int, count: int = 12) -> list[m.ReelRead]:
    return [
        m.ReelRead(
            reel_id=f"r{views}-{i}",
            url="",
            taken_at=READ_AT - timedelta(days=4 + i),
            duration_s=20.0,
            views=views,
            likes=10,
            comments=1,
            counts_hidden=False,
            is_paid_partnership=False,
            coauthors=(),
            sound_id=None,
            sound_title="",
            sound_is_original=None,
        )
        for i in range(count)
    ]


def _entry(
    views: int,
    rate: str | None,
    currency: str | None,
    *,
    reels: int = 12,
) -> m.CompareEntry:
    snapshot = m.SnapshotFacts(
        snapshot_id=uuid4(),
        network="instagram",
        handle=f"fake.{uuid4().hex[:6]}",
        read_at=READ_AT,
        status="ok",
        followers=10_000,
    )
    return m.CompareEntry(
        uuid4(),
        snapshot,
        _reels(views, reels),
        rate_from=Decimal(rate) if rate is not None else None,
        rate_currency=currency,
        rate_notes="notas" if rate is not None else "",
    )


def _compare(*entries: m.CompareEntry) -> m.Comparison:
    return m.compare(entries, now=READ_AT)


def test_cost_per_thousand_views_is_the_price_over_typical_views() -> None:
    result = _compare(_entry(2_000, "150000", "COP"), _entry(3_000, None, None))
    priced, unpriced = result.creators
    assert priced.cost_per_thousand_views == Decimal("75000.00")  # 150000 / 2000 * 1000
    assert (priced.rate_from, priced.rate_currency, priced.rate_notes) == (
        Decimal("150000"),
        "COP",
        "notas",
    )
    assert unpriced.cost_per_thousand_views is None
    # one priced creator: nothing to be the lowest against
    assert not any(c.lowest_rate or c.lowest_cost_per_thousand for c in result.creators)
    assert result.mixed_currencies is False


def test_lowest_price_and_lowest_cost_can_be_different_creators() -> None:
    cheap_small = _entry(1_000, "100000", "COP")  # 100,000 per 1,000 views
    dear_big = _entry(5_000, "300000", "COP")  # 60,000 per 1,000 views
    result = _compare(cheap_small, dear_big)
    a, b = result.creators
    assert (a.lowest_rate, b.lowest_rate) == (True, False)
    assert (a.lowest_cost_per_thousand, b.lowest_cost_per_thousand) == (False, True)
    assert b.cost_per_thousand_views == Decimal("60000.00")


def test_ties_flag_every_tied_creator() -> None:
    result = _compare(
        _entry(2_000, "200", "USD"), _entry(2_000, "200", "USD"), _entry(1_000, "300", "USD")
    )
    assert [c.lowest_rate for c in result.creators] == [True, True, False]
    assert [c.lowest_cost_per_thousand for c in result.creators] == [True, True, False]


def test_prices_are_only_compared_within_one_currency() -> None:
    result = _compare(
        _entry(1_000, "150000", "COP"),
        _entry(1_000, "100", "USD"),
        _entry(1_000, "90", "USD"),
        _entry(1_000, "50", "UYU"),
    )
    assert result.mixed_currencies is True
    # COP and UYU have one price each: never «the lowest»; USD's lowest is 90, not 50 UYU
    assert [c.lowest_rate for c in result.creators] == [False, False, True, False]
    assert [c.lowest_cost_per_thousand for c in result.creators] == [False, False, True, False]


def test_a_creator_with_too_few_reels_has_no_cost_and_never_wins_it() -> None:
    few = _entry(100, "10", "USD", reels=2)  # cheapest price, but no typical views
    result = _compare(few, _entry(1_000, "100", "USD"), _entry(2_000, "300", "USD"))
    first = result.creators[0]
    assert first.few_reels is True
    assert first.cost_per_thousand_views is None
    assert first.lowest_rate is True  # the price itself is still the owner's fact
    assert first.lowest_cost_per_thousand is False
    # the other two still compare their cost: 100 and 150 per 1,000 views
    assert [c.lowest_cost_per_thousand for c in result.creators] == [False, True, False]


def test_no_views_means_no_cost() -> None:
    assert (
        m.cost_per_thousand_views(Decimal("10"), m.MetricValue("median_views", 0.0, "ok", 3))
        is None
    )
    assert (
        m.cost_per_thousand_views(Decimal("10"), m.MetricValue("median_views", None, "unknown", 0))
        is None
    )
    assert m.cost_per_thousand_views(None, m.MetricValue("median_views", 500.0, "ok", 3)) is None
    assert m.cost_per_thousand_views(
        Decimal("0"), m.MetricValue("median_views", 500.0, "ok", 3)
    ) == Decimal("0.00")


def test_compare_creators_reads_the_rate_from_the_tracked_creator(store) -> None:
    ids = []
    for handle, views, price in (("fake.a", 1_000, "100"), ("fake.b", 4_000, "200")):
        tracked = _track(store, handle)
        snap_id = uuid4()
        store.snapshot_rows[snap_id] = NewSnapshot(
            id=snap_id,
            network="instagram",
            handle=handle,
            read_at=READ_AT,
            status="ok",
            parser_version=1,
            reels_target=48,
            followers=10_000,
        )
        store.read_rows[snap_id] = [_new_read(snap_id, handle, i, views) for i in range(12)]
        store.mark(TENANT, BRAND, tracked.id, state="ok", error=None, now=NOW, snapshot_id=snap_id)
        service.set_creator_rate(
            TENANT, BRAND, tracked.id, notes="", amount=Decimal(price), currency="USD"
        )
        ids.append(tracked.id)
    result = service.compare_creators(TENANT, BRAND, ids, now=READ_AT)
    a, b = result.creators
    assert (a.rate_from, b.rate_from) == (Decimal("100.00"), Decimal("200.00"))
    assert (a.lowest_rate, b.lowest_rate) == (True, False)
    assert (a.cost_per_thousand_views, b.cost_per_thousand_views) == (
        Decimal("100.00"),
        Decimal("50.00"),
    )
    assert (a.lowest_cost_per_thousand, b.lowest_cost_per_thousand) == (False, True)


def _new_read(snap_id: UUID, handle: str, i: int, views: int) -> NewReelRead:
    return NewReelRead(
        snapshot_id=snap_id,
        network="instagram",
        reel_id=f"{handle}-{i}",
        position=i,
        taken_at=READ_AT - timedelta(days=4 + i),
        parser_version=1,
        views=views,
        likes=10,
        comments=1,
    )
