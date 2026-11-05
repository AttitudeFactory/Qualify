"""Migration 0125 and the Postgres side of the Creators read (m-24946121, design §7.7,
§10.4) against the live schema:

- `tracked_creators` isolates tenant A from tenant B through `tenant_session` (RLS ENABLE +
  FORCE + the NULLIF policy) and refuses another tenant's brand (composite FK);
- the two new global tables stay global (no column naming a tenant, a brand or a user;
  no RLS) and append-only for `qualify_app`;
- a read through `PostgresTrackedCreatorStore` writes the snapshot, its reel reads, the
  provenance and the usage rows, and the facade reads them back;
- two businesses refreshing the same account at once pay ONE read (the `reel_accounts`
  lock);
- migration 0130 (m-24955847): business B can neither read nor write A's creator rate,
  and the rate's CHECKs hold even for a statement that skips the service.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from qualify_api.creators import access, service, snapshots
from qualify_api.creators.tracking import PostgresTrackedCreatorStore
from qualify_api.tenancy.models import Brand, Tenant, User
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

pytestmark = pytest.mark.db

_GLOBAL_TABLES = ("creator_snapshots", "public_reel_reads")


def _load_fake():  # `--import-mode=importlib` puts no test directory on `sys.path`
    if "creators_fake" not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            "creators_fake", Path(__file__).with_name("creators_fake.py")
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["creators_fake"] = module
        spec.loader.exec_module(module)
    return sys.modules["creators_fake"]


fake = _load_fake()


def _world() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name="Creators test",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="Creators brand"))
    return tenant, brand


def _user(tenant: UUID) -> UUID:
    user = uuid4()
    with admin_session() as session:
        session.add(User(id=user, tenant_id=tenant, email=f"{user}@example.test", display_name="Q"))
    return user


@pytest.fixture
def two_worlds() -> tuple[tuple[UUID, UUID], tuple[UUID, UUID]]:
    return _world(), _world()


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_123")
    monkeypatch.delenv(sc.PAID_SWITCH_ENV, raising=False)
    access.reset_cache()
    yield
    access.reset_cache()
    service.configure_store(None)


def _handle() -> str:
    return f"fake.{uuid4().hex[:10]}"


def _vendor(now: datetime, handle: str, *, tag: str | None = None) -> object:
    """Four pages of 12 reels with ids unique to this test (the reels table is global)."""
    tag = tag or uuid4().hex[:8]
    pages = [
        [
            fake.reel_item(
                f"{tag}{p:02d}{i:02d}", days_ago=1 + 2 * (12 * p + i), now=now, owner=handle
            )
            for i in range(12)
        ]
        for p in range(4)
    ]
    return fake.FakeVendor(pages=pages)


def _track(tenant: UUID, brand: UUID, handle: str) -> UUID:
    store = PostgresTrackedCreatorStore()
    return store.add(
        tenant,
        brand,
        network="instagram",
        handle=handle,
        note="",
        user_id=None,
        now=datetime.now(UTC),
    ).id


# -- schema ------------------------------------------------------------------------------


def test_tracked_creators_isolates_tenants(two_worlds) -> None:
    (tenant_a, brand_a), (tenant_b, brand_b) = two_worlds
    a = _track(tenant_a, brand_a, _handle())
    b = _track(tenant_b, brand_b, _handle())

    def visible(tenant: UUID, row: UUID) -> int:
        with tenant_session(tenant) as session:
            return session.scalar(
                text("SELECT count(*) FROM tracked_creators WHERE id = :id"), {"id": row}
            )

    assert (visible(tenant_a, a), visible(tenant_a, b)) == (1, 0)
    assert (visible(tenant_b, b), visible(tenant_b, a)) == (1, 0)
    # a reset GUC filters to nothing instead of raising on ''::uuid
    with tenant_session(tenant_a) as session:
        session.execute(text("SELECT set_config('app.tenant_id', '', true)"))
        assert session.scalar(text("SELECT count(*) FROM tracked_creators")) == 0
    # WITH CHECK: B's session cannot write a row stamped with A
    with pytest.raises(ProgrammingError), tenant_session(tenant_b) as session:
        session.execute(
            text(
                "INSERT INTO tracked_creators (tenant_id, brand_id, network, handle) "
                "VALUES (:t, :b, 'instagram', 'x.y')"
            ),
            {"t": tenant_a, "b": brand_a},
        )
    # the composite FK: A cannot follow a creator for B's brand
    with pytest.raises(IntegrityError), tenant_session(tenant_a) as session:
        session.execute(
            text(
                "INSERT INTO tracked_creators (tenant_id, brand_id, network, handle) "
                "VALUES (:t, :b, 'instagram', 'x.y')"
            ),
            {"t": tenant_a, "b": brand_b},
        )
    # B's id is invisible to A's facade-level store
    assert PostgresTrackedCreatorStore().get(tenant_a, brand_a, b) is None


def test_rls_is_enabled_and_forced_on_tracked_creators_and_not_on_the_history() -> None:
    with admin_session() as session:
        rows = session.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = ANY(:names) AND relkind = 'r'"
            ),
            {"names": ["tracked_creators", *_GLOBAL_TABLES]},
        ).all()
    flags = {row.relname: (row.relrowsecurity, row.relforcerowsecurity) for row in rows}
    assert flags == {
        "tracked_creators": (True, True),
        "creator_snapshots": (False, False),
        "public_reel_reads": (False, False),
    }


def test_the_history_tables_name_no_tenant_brand_or_user() -> None:
    with admin_session() as session:
        columns = session.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_name = ANY(:names)"
            ),
            {"names": list(_GLOBAL_TABLES)},
        ).all()
    assert columns, "the history tables exist"
    for table, column in columns:
        assert column not in ("tenant_id", "brand_id", "user_id"), (table, column)
        assert not column.endswith(("_tenant_id", "_brand_id", "_user_id")), (table, column)


@pytest.mark.parametrize("table", _GLOBAL_TABLES)
def test_the_history_is_append_only_for_the_app(table: str) -> None:
    tenant, _ = _world()
    for statement in (f"UPDATE {table} SET network = network", f"DELETE FROM {table}"):
        with pytest.raises(ProgrammingError), tenant_session(tenant) as session:
            session.execute(text(statement))


def test_the_app_cannot_delete_a_tracked_creator() -> None:
    tenant, brand = _world()
    row = _track(tenant, brand, _handle())
    with pytest.raises(ProgrammingError), tenant_session(tenant) as session:
        session.execute(text("DELETE FROM tracked_creators WHERE id = :id"), {"id": row})


def test_add_is_idempotent_on_brand_network_handle() -> None:
    tenant, brand = _world()
    handle = _handle()
    store = PostgresTrackedCreatorStore()
    now = datetime.now(UTC)
    first = store.add(
        tenant, brand, network="instagram", handle=handle, note="n", user_id=None, now=now
    )
    assert store.archive(tenant, brand, first.id, now=now)
    again = store.add(
        tenant, brand, network="instagram", handle=handle, note="", user_id=None, now=now
    )
    assert (again.id, again.status, again.note) == (first.id, "active", "n")


def test_a_creator_s_rate_is_only_its_business_s(two_worlds, monkeypatch) -> None:
    (tenant_a, brand_a), (tenant_b, brand_b) = two_worlds
    monkeypatch.setenv(access.ENV, f"{tenant_a},{tenant_b}")
    access.reset_cache()
    service.configure_store(PostgresTrackedCreatorStore())
    a = _track(tenant_a, brand_a, _handle())
    saved = service.set_creator_rate(
        tenant_a,
        brand_a,
        a,
        notes=" 1 reel 150.000; paquete 3 reels + 5 historias 380.000 ",
        amount=Decimal("150000"),
        currency="COP",
    )
    assert (saved.rate_from, saved.rate_currency) == (Decimal("150000.00"), "COP")
    assert saved.rate_notes.startswith("1 reel") and saved.rate_updated_at is not None
    (card,) = service.list_creators(tenant_a, brand_a)
    assert (card.tracked.rate_from, card.tracked.rate_notes) == (saved.rate_from, saved.rate_notes)

    # B, even naming A's brand, neither sees nor changes the rate
    for brand in (brand_b, brand_a):
        with pytest.raises(service.CreatorNotFound):
            service.set_creator_rate(
                tenant_b, brand, a, notes="mine", amount=Decimal("1"), currency="USD"
            )
    with tenant_session(tenant_b) as session:
        changed = session.execute(
            text("UPDATE tracked_creators SET rate_notes = 'x' WHERE id = :id"), {"id": a}
        ).rowcount
        seen = session.scalar(
            text("SELECT count(*) FROM tracked_creators WHERE id = :id"), {"id": a}
        )
    assert (changed, seen) == (0, 0)
    again = PostgresTrackedCreatorStore().get(tenant_a, brand_a, a)
    assert again is not None
    assert (again.rate_notes, again.rate_from, again.rate_currency) == (
        saved.rate_notes,
        Decimal("150000.00"),
        "COP",
    )

    # an archived creator is not priced
    service.archive_creator(tenant_a, brand_a, a)
    with pytest.raises(service.CreatorNotFound):
        service.set_creator_rate(tenant_a, brand_a, a, notes="", amount=None, currency=None)


@pytest.mark.parametrize(
    "assignment",
    [
        "rate_from = -1, rate_currency = 'COP'",
        "rate_from = 10, rate_currency = 'EUR'",
        "rate_from = 10, rate_currency = NULL",
        "rate_from = NULL, rate_currency = 'USD'",
        "rate_notes = repeat('x', 1001)",
    ],
)
def test_the_rate_checks_hold_without_the_service(assignment: str) -> None:
    tenant, brand = _world()
    row = _track(tenant, brand, _handle())
    with pytest.raises(IntegrityError), tenant_session(tenant) as session:
        session.execute(
            text(f"UPDATE tracked_creators SET {assignment} WHERE id = :id"), {"id": row}
        )


def test_spent_sums_only_the_creators_features_in_the_tenant_zone() -> None:
    tenant, brand = _world()
    store = usage.PostgresUsageStore()
    for feature, credits in (
        (sc.FEATURE_CREATOR_PROFILE, 1),
        (sc.FEATURE_CREATOR_REELS, 4),
        (sc.FEATURE_REELS_LIST, 7),  # «Ideas para tus reels»: not the creators' budget
    ):
        assert (
            store.book(
                usage.UsageEvent(
                    tenant_id=tenant,
                    brand_id=brand,
                    vendor=usage.SCRAPECREATORS,
                    feature=feature,
                    credits=credits,
                    usd_estimate=usage.usd_per_credit() * credits,
                    pricing_table_version=usage.PRICING_TABLE_VERSION,
                    request_key=f"{feature}:{uuid4()}",
                ),
                capped=True,
            )
            is None
        )  # 0125's CHECK takes the two creators' features
    creators = store.spent(tenant, usage.SCRAPECREATORS, features=snapshots.CREATOR_FEATURES)
    everything = store.spent(tenant, usage.SCRAPECREATORS)
    assert (creators.day, creators.month) == (5, 5)
    assert (everything.day, everything.month) == (12, 12)


# -- the read, end to end ----------------------------------------------------------------


def test_a_read_through_postgres_keeps_snapshot_reads_provenance_and_usage(monkeypatch) -> None:
    tenant, brand = _world()
    monkeypatch.setenv(access.ENV, str(tenant))
    usage.configure_store(usage.PostgresUsageStore())  # the gate books in the real table
    now = datetime.now(UTC).replace(microsecond=0)
    handle = _handle()
    tracked = service.add_creator(tenant, brand, handle, user_id=_user(tenant))
    vendor = _vendor(now, handle)
    outcome = service.refresh_creator(tenant, brand, tracked.id, now=now, client=vendor.client())
    assert (outcome.status, outcome.credits, outcome.partial) == ("read", 5, False)
    sid = outcome.snapshot_id
    with tenant_session(tenant) as session:
        snap = session.execute(
            text(
                "SELECT status, reels_read, pages_read, credits, followers, parser_version, "
                "profile_payload_id, profile_payload_fetched_at FROM creator_snapshots "
                "WHERE id = :id"
            ),
            {"id": sid},
        ).one()
        reads = session.execute(
            text(
                "SELECT r.position, r.source_payload_id, r.source_payload_fetched_at, "
                "p.source_payload_id AS reel_payload, p.parser_version, p.coauthors, "
                "p.sound_id, p.counts_hidden FROM public_reel_reads r JOIN public_reels p "
                "ON p.network = r.network AND p.reel_id = r.reel_id "
                "WHERE r.snapshot_id = :id ORDER BY r.position"
            ),
            {"id": sid},
        ).all()
        events = session.execute(
            text("SELECT feature, credits, brand_id FROM vendor_usage_events WHERE tenant_id = :t"),
            {"t": tenant},
        ).all()
        payload_ids = {
            row.id
            for row in session.execute(
                text("SELECT id FROM vendor_payloads WHERE id = ANY(:ids)"),
                {"ids": [snap.profile_payload_id, *{r.source_payload_id for r in reads}]},
            )
        }
    assert (snap.status, snap.reels_read, snap.pages_read, snap.credits) == ("ok", 48, 4, 5)
    assert snap.followers == 20000 and snap.parser_version == 2
    assert snap.profile_payload_fetched_at is not None
    assert [r.position for r in reads] == list(range(1, 49))
    assert all(r.source_payload_id == r.reel_payload and r.parser_version == 2 for r in reads)
    assert all(r.coauthors == [handle] and r.sound_id and r.counts_hidden is False for r in reads)
    assert len(payload_ids) == 5  # the profile + 4 pages, all kept
    assert (
        sorted((e.feature, e.credits) for e in events)
        == [("creator_profile", 1)] + [("creator_reels", 1)] * 4
    )
    assert {e.brand_id for e in events} == {brand}  # booked by the gate, to this brand

    sheet = service.creator_sheet(tenant, brand, tracked.id, now=now)
    assert sheet is not None and sheet.snapshot_id == sid and sheet.reels_read == 48
    assert sheet.median_views.status == "ok" and sheet.collabs_known is True
    card = service.list_creators(tenant, brand, now=now)[0]
    assert card.followers == 20000 and card.read_at == now

    # within 24 h a second business pays nothing
    other_tenant, other_brand = _world()
    monkeypatch.setenv(access.ENV, f"{tenant},{other_tenant}")
    other = service.add_creator(other_tenant, other_brand, handle, user_id=_user(other_tenant))
    again = _vendor(now, handle)
    fresh = service.refresh_creator(
        other_tenant, other_brand, other.id, now=now, client=again.client()
    )
    assert (fresh.status, fresh.snapshot_id, fresh.credits) == ("fresh", sid, 0)
    assert again.paid_calls == 0


def test_two_businesses_refreshing_the_same_account_at_once_pay_one_read() -> None:
    (tenant_a, brand_a), (tenant_b, brand_b) = _world(), _world()
    handle = _handle()
    now = datetime.now(UTC).replace(microsecond=0)
    a = _track(tenant_a, brand_a, handle)
    b = _track(tenant_b, brand_b, handle)
    vendor = _vendor(now, handle)
    # slow every call down, so the second business arrives while the first is reading
    vendor.on_call = lambda _path: time.sleep(0.15)
    store = PostgresTrackedCreatorStore()
    outcomes: dict[str, snapshots.RefreshOutcome] = {}
    errors: list[BaseException] = []

    def run(name: str, tenant: UUID, brand: UUID, tracked: UUID) -> None:
        try:
            outcomes[name] = snapshots.refresh_creator(
                tenant,
                brand,
                tracked,
                store=store,
                client=vendor.client(),
                poll_seconds=0.1,
                lock_wait_seconds=10,
            )
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [
        threading.Thread(target=run, args=("a", tenant_a, brand_a, a)),
        threading.Thread(target=run, args=("b", tenant_b, brand_b, b)),
    ]
    threads[0].start()
    time.sleep(0.05)
    threads[1].start()
    for thread in threads:
        thread.join(timeout=30)
    assert not errors, errors
    assert sorted(o.status for o in outcomes.values()) == ["fresh", "read"]
    assert vendor.paid_calls == 5  # one read, not two
    assert outcomes["a"].snapshot_id == outcomes["b"].snapshot_id
    with admin_session() as session:
        count = session.scalar(
            text("SELECT count(*) FROM creator_snapshots WHERE handle = :h"), {"h": handle}
        )
        lock = session.scalar(
            text("SELECT refresh_lock_until FROM reel_accounts WHERE handle = :h"), {"h": handle}
        )
    assert count == 1 and lock is None


def test_a_reel_shared_by_two_accounts_keeps_both_whichever_is_read_last(monkeypatch) -> None:
    tenant, brand = _world()
    monkeypatch.setenv(access.ENV, str(tenant))
    aaa, bbb = _handle(), _handle()
    shared = f"S{uuid4().hex[:10]}"
    now = datetime.now(UTC).replace(microsecond=0)

    def vendor(owner: str, at: datetime) -> object:
        items = [fake.reel_item(shared, days_ago=5, owner=aaa, coauthors=[bbb], now=at)] + [
            fake.reel_item(f"{owner[-6:]}{uuid4().hex[:6]}{i}", days_ago=6 + i, owner=owner, now=at)
            for i in range(4)
        ]
        return fake.FakeVendor(pages=[items])

    user = _user(tenant)
    ids = {}
    for offset, handle in enumerate((aaa, bbb)):
        at = now + timedelta(minutes=offset)
        tracked = service.add_creator(tenant, brand, handle, user_id=user)
        outcome = snapshots.refresh_creator(
            tenant,
            brand,
            tracked.id,
            store=PostgresTrackedCreatorStore(),
            now=at,
            clock=lambda at=at: at,
            client=vendor(handle, at).client(),
        )
        assert outcome.status == "read"
        ids[handle] = tracked.id
    with tenant_session(tenant) as session:
        stored = session.scalar(
            text("SELECT coauthors FROM public_reels WHERE reel_id = :r"), {"r": shared}
        )
    assert stored == sorted([aaa, bbb])
    for handle, other in ((aaa, bbb), (bbb, aaa)):
        sheet = service.creator_sheet(tenant, brand, ids[handle], now=now)
        assert (
            sheet is not None and other in sheet.collaborators and handle not in sheet.collaborators
        )
