"""The Creators read and its facade (m-24946121, design §8.3, §10, §11) — offline:
`httpx.MockTransport` for the vendor and `MemoryTrackedCreatorStore` for Postgres."""

from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from qualify_api.creators import access, service, snapshots
from qualify_api.creators.tracking import MemoryTrackedCreatorStore, NewSnapshot
from qualify_api.vendors import scrapecreators as sc


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
NOW = fake.NOW
HANDLE = fake.HANDLE
TENANT = UUID("c0000000-0000-4000-8000-0000000000c1")
OTHER_TENANT = UUID("c0000000-0000-4000-8000-0000000000c2")
BRAND = uuid4()
OTHER_BRAND = uuid4()
USER = uuid4()


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_123")
    monkeypatch.setenv(access.ENV, f"{TENANT},{OTHER_TENANT}")
    monkeypatch.delenv(sc.PAID_SWITCH_ENV, raising=False)
    access.reset_cache()
    yield
    access.reset_cache()
    service.configure_store(None)


@pytest.fixture
def store() -> MemoryTrackedCreatorStore:
    memory = MemoryTrackedCreatorStore(clock=lambda: NOW)
    service.configure_store(memory)
    return memory


def _track(store: MemoryTrackedCreatorStore, tenant: UUID = TENANT, brand: UUID = BRAND):
    return store.add(
        tenant, brand, network="instagram", handle=HANDLE, note="", user_id=USER, now=NOW
    )


def _refresh(store, tracked, vendor, *, tenant=TENANT, brand=BRAND, **kwargs):
    return snapshots.refresh_creator(
        tenant,
        brand,
        tracked.id,
        store=store,
        now=NOW,
        client=vendor.client(),
        clock=lambda: NOW,
        sleep=lambda _s: None,
        **kwargs,
    )


def _credits(store: MemoryTrackedCreatorStore, tenant: UUID = TENANT) -> int:
    return sum(e["credits"] for e in store.usage_events if e["tenant_id"] == tenant)


# -- the paid read ----------------------------------------------------------------------


def test_a_full_read_costs_five_credits_and_keeps_its_provenance(store) -> None:
    tracked = _track(store)
    vendor = fake.FakeVendor()
    outcome = _refresh(store, tracked, vendor)
    assert (outcome.status, outcome.credits, outcome.partial) == ("read", 5, False)
    assert vendor.paid_calls == 5
    snap = store.snapshot_rows[outcome.snapshot_id]
    assert (snap.status, snap.reels_read, snap.pages_read, snap.credits) == ("ok", 48, 4, 5)
    assert snap.followers == 20000 and snap.parser_version == 2
    assert snap.profile_payload_id is not None and snap.profile_payload_fetched_at == NOW
    reads = store.read_rows[outcome.snapshot_id]
    assert [r.position for r in reads] == list(range(1, 49))
    assert all(r.source_payload_id is not None for r in reads)
    assert len({r.source_payload_id for r in reads}) == 4  # one payload per page
    reel = store.reels.reels[("instagram", "R000")]
    assert reel.source_payload_id == reads[0].source_payload_id and reel.parser_version == 2
    keys = sorted(e["request_key"] for e in store.usage_events)
    sid = outcome.snapshot_id
    assert keys == sorted(
        [f"creators:{sid}:profile"] + [f"creators:{sid}:reels:{n}" for n in range(1, 5)]
    )
    assert {e["feature"] for e in store.usage_events} == {"creator_profile", "creator_reels"}
    current = store.get(TENANT, BRAND, tracked.id)
    assert current is not None
    assert (current.last_snapshot_id, current.refresh_state) == (sid, "ok")
    assert store.pool.creator("instagram", HANDLE).read_at == NOW  # the 0036 pool row
    # the account lock is released
    assert store.reels.accounts[("instagram", HANDLE)].refresh_lock_until is None


def test_a_fresh_read_by_another_business_costs_nothing(store) -> None:
    first = _track(store, OTHER_TENANT, OTHER_BRAND)
    _refresh(store, first, fake.FakeVendor(), tenant=OTHER_TENANT, brand=OTHER_BRAND)
    mine = _track(store)
    vendor = fake.FakeVendor()
    outcome = _refresh(store, mine, vendor)
    assert (outcome.status, outcome.credits) == ("fresh", 0)
    assert vendor.paid_calls == 0
    assert _credits(store) == 0
    assert store.get(TENANT, BRAND, mine.id).last_snapshot_id == outcome.snapshot_id


def test_the_cap_stops_the_read_before_any_call(store) -> None:
    store.usage_events.append(
        {
            "tenant_id": TENANT,
            "brand_id": BRAND,
            "vendor": "scrapecreators",
            "feature": "creator_reels",
            "credits": 46,
            "request_key": "seed",
            "payload_id": None,
            "created_at": NOW - timedelta(hours=1),
        }
    )
    tracked = _track(store)
    vendor = fake.FakeVendor()
    outcome = _refresh(store, tracked, vendor)
    assert (outcome.status, outcome.credits) == ("cap_reached", 0)
    assert vendor.paid_calls == 0
    current = store.get(TENANT, BRAND, tracked.id)
    assert (current.refresh_state, current.refresh_error) == ("failed", "cap_reached")


def test_a_missing_account_costs_one_credit(store) -> None:
    tracked = _track(store)
    vendor = fake.FakeVendor(profile_status=404)
    outcome = _refresh(store, tracked, vendor)
    assert (outcome.status, outcome.credits) == ("missing", 1)
    assert vendor.paid_calls == 1
    assert _credits(store) == 1
    assert store.snapshot_rows[outcome.snapshot_id].status == "missing"


def test_a_private_account_costs_one_credit_and_its_reels_are_not_read(store) -> None:
    tracked = _track(store)
    vendor = fake.FakeVendor(profile=fake.profile_payload(private=True))
    outcome = _refresh(store, tracked, vendor)
    assert (outcome.status, outcome.credits) == ("private", 1)
    assert vendor.calls == ["/v1/instagram/profile"]


def test_an_error_on_page_3_keeps_a_partial_read_and_its_three_credits(store) -> None:
    tracked = _track(store)
    vendor = fake.FakeVendor(fail_page=3)
    outcome = _refresh(store, tracked, vendor)
    assert (outcome.status, outcome.partial, outcome.credits) == ("read", True, 3)
    assert _credits(store) == 3
    snap = store.snapshot_rows[outcome.snapshot_id]
    assert (snap.status, snap.reels_read, snap.pages_read) == ("partial", 24, 2)
    assert store.get(TENANT, BRAND, tracked.id).last_snapshot_id == outcome.snapshot_id


def test_a_retry_with_the_same_snapshot_id_charges_nothing_twice(store) -> None:
    tracked = _track(store)
    sid = uuid4()
    store.fail_save = 1  # the first attempt pays, then loses its write
    first = _refresh(store, tracked, fake.FakeVendor(), snapshot_id=sid)
    assert first.status == "error" and first.credits == 5
    assert store.get(TENANT, BRAND, tracked.id).last_snapshot_id is None
    second = _refresh(store, tracked, fake.FakeVendor(), snapshot_id=sid)
    assert second.status == "read" and second.snapshot_id == sid
    assert len(store.usage_events) == 5  # not 10
    assert _credits(store) == 5


def test_a_blocked_gate_keeps_the_last_good_read(store, monkeypatch) -> None:
    tracked = _track(store)
    good = _refresh(store, tracked, fake.FakeVendor())
    # 25 h later, with the switch off
    later = NOW + timedelta(hours=25)
    monkeypatch.setenv(sc.PAID_SWITCH_ENV, "0")
    vendor = fake.FakeVendor()
    outcome = snapshots.refresh_creator(
        TENANT,
        BRAND,
        tracked.id,
        store=store,
        now=later,
        client=vendor.client(),
        clock=lambda: later,
        sleep=lambda _s: None,
    )
    assert (outcome.status, outcome.snapshot_id, outcome.credits) == (
        "blocked",
        good.snapshot_id,
        0,
    )
    assert vendor.paid_calls == 0
    assert store.get(TENANT, BRAND, tracked.id).last_snapshot_id == good.snapshot_id
    assert store.reels.accounts[("instagram", HANDLE)].refresh_lock_until is None


def test_a_private_read_never_replaces_the_last_good_one(store) -> None:
    tracked = _track(store)
    good = _refresh(store, tracked, fake.FakeVendor())
    later = NOW + timedelta(hours=25)
    vendor = fake.FakeVendor(profile=fake.profile_payload(private=True))
    outcome = snapshots.refresh_creator(
        TENANT,
        BRAND,
        tracked.id,
        store=store,
        now=later,
        client=vendor.client(),
        clock=lambda: later,
        sleep=lambda _s: None,
    )
    assert outcome.status == "private" and outcome.snapshot_id == good.snapshot_id
    current = store.get(TENANT, BRAND, tracked.id)
    assert current.last_snapshot_id == good.snapshot_id
    assert (current.refresh_state, current.refresh_error) == ("failed", "private")


def test_a_held_lock_answers_busy_without_calling(store) -> None:
    tracked = _track(store)
    assert store.try_lock_account(
        OTHER_TENANT, "instagram", HANDLE, now=NOW, until=NOW + timedelta(minutes=2)
    )
    vendor = fake.FakeVendor()
    outcome = _refresh(store, tracked, vendor)
    assert outcome.status == "busy" and vendor.paid_calls == 0


def test_an_archived_creator_cannot_be_refreshed(store) -> None:
    tracked = _track(store)
    store.archive(TENANT, BRAND, tracked.id, now=NOW)
    with pytest.raises(snapshots.CreatorNotFound):
        _refresh(store, tracked, fake.FakeVendor())


def _later(store, tracked, vendor, hours: float = 25, *, tenant=TENANT, brand=BRAND):
    later = NOW + timedelta(hours=hours)
    return snapshots.refresh_creator(
        tenant,
        brand,
        tracked.id,
        store=store,
        now=later,
        client=vendor.client(),
        clock=lambda: later,
        sleep=lambda _s: None,
    )


def test_a_reel_list_failing_on_page_1_never_replaces_the_good_read(store) -> None:
    tracked = _track(store)
    good = _refresh(store, tracked, fake.FakeVendor())
    outcome = _later(store, tracked, fake.FakeVendor(fail_page=1))
    assert (outcome.status, outcome.snapshot_id, outcome.credits) == (
        "error",
        good.snapshot_id,
        1,
    )
    current = store.get(TENANT, BRAND, tracked.id)
    assert current.last_snapshot_id == good.snapshot_id
    assert (current.refresh_state, current.refresh_error) == ("failed", "error")
    # kept as provenance with status «error», never served as fresh to another business
    errors = [s for s in store.snapshot_rows.values() if s.status == "error"]
    assert len(errors) == 1 and errors[0].reels_read == 0
    other = _track(store, OTHER_TENANT, OTHER_BRAND)
    vendor = fake.FakeVendor()
    again = _later(store, other, vendor, 25.5, tenant=OTHER_TENANT, brand=OTHER_BRAND)
    assert again.status == "read" and vendor.paid_calls == 5


def test_a_first_read_failing_on_page_1_links_nothing(store) -> None:
    tracked = _track(store)
    outcome = _refresh(store, tracked, fake.FakeVendor(fail_page=1))
    assert (outcome.status, outcome.snapshot_id) == ("error", None)
    assert store.get(TENANT, BRAND, tracked.id).last_snapshot_id is None


def test_a_crash_mid_read_marks_the_creator_failed_and_frees_the_lock(store, monkeypatch) -> None:
    tracked = _track(store)

    def boom(*_a, **_k):
        raise RuntimeError("database went away")

    monkeypatch.setattr(store, "put_payload", boom)
    outcome = _refresh(store, tracked, fake.FakeVendor())
    assert outcome.status == "error"
    current = store.get(TENANT, BRAND, tracked.id)
    assert (current.refresh_state, current.refresh_error) == ("failed", "error")
    assert current.refresh_started_at == NOW
    assert store.reels.accounts[("instagram", HANDLE)].refresh_lock_until is None


def test_a_reading_state_older_than_the_lock_is_shown_as_failed(store) -> None:
    tracked = _track(store)
    store.mark(TENANT, BRAND, tracked.id, state="reading", error=None, now=NOW, started=True)
    fresh = service.list_creators(TENANT, BRAND, now=NOW + timedelta(seconds=60))[0]
    assert fresh.tracked.refresh_state == "reading"
    stuck = service.list_creators(TENANT, BRAND, now=NOW + timedelta(minutes=3))[0]
    assert (stuck.tracked.refresh_state, stuck.tracked.refresh_error) == ("failed", "error")
    assert service.refresh_stuck(stuck.tracked, NOW) is False  # already shown as failed
    raw = store.get(TENANT, BRAND, tracked.id)
    assert service.refresh_stuck(raw, NOW + timedelta(minutes=3)) is True


def test_an_unusable_200_profile_is_still_charged(store) -> None:
    tracked = _track(store)
    vendor = fake.FakeVendor(profile={"success": True, "data": {}})
    outcome = _refresh(store, tracked, vendor)
    assert (outcome.status, outcome.credits) == ("error", 1)
    assert [(e["feature"], e["credits"], e["payload_id"]) for e in store.usage_events] == [
        ("creator_profile", 1, None)
    ]


def test_an_unusable_200_reel_page_is_still_charged(store) -> None:
    tracked = _track(store)
    outcome = _refresh(store, tracked, fake.FakeVendor(bad_page=2))
    assert (outcome.status, outcome.partial, outcome.credits) == ("read", True, 3)
    assert _credits(store) == 3
    prefix = f"creators:{outcome.snapshot_id}:"
    assert sorted(e["request_key"].removeprefix(prefix) for e in store.usage_events) == [
        "profile",
        "reels:1",
        "reels:2",
    ]
    assert store.snapshot_rows[outcome.snapshot_id].reels_read == 12


# -- the facade -----------------------------------------------------------------------


def test_every_function_refuses_a_business_without_the_module(store, monkeypatch) -> None:
    monkeypatch.setenv(access.ENV, str(OTHER_TENANT))
    access.reset_cache()
    assert service.creators_enabled(TENANT) is False
    with pytest.raises(service.CreatorsDisabled):
        service.add_creator(TENANT, BRAND, HANDLE, user_id=USER)
    with pytest.raises(service.CreatorsDisabled):
        service.list_creators(TENANT, BRAND)
    with pytest.raises(service.CreatorsDisabled):
        service.refresh_creator(TENANT, BRAND, uuid4())
    with pytest.raises(service.CreatorsDisabled):
        service.creator_sheet(TENANT, BRAND, uuid4())
    with pytest.raises(service.CreatorsDisabled):
        service.compare_creators(TENANT, BRAND, [uuid4(), uuid4()])
    with pytest.raises(service.CreatorsDisabled):
        service.archive_creator(TENANT, BRAND, uuid4())


def test_the_switch_ignores_garbage_and_empty_means_nobody(monkeypatch) -> None:
    monkeypatch.setenv(access.ENV, f" not-a-uuid , {TENANT} ,")
    access.reset_cache()
    assert access.enabled_tenants() == frozenset({TENANT})
    monkeypatch.setenv(access.ENV, "")
    assert access.creators_enabled(TENANT) is False


@pytest.mark.parametrize(
    ("raw", "handle"),
    [
        ("@Fake.Creator", "fake.creator"),
        ("fake_creator", "fake_creator"),
        ("https://www.instagram.com/fake.creator/?igsh=abc", "fake.creator"),
        ("instagram.com/fake.creator", "fake.creator"),
    ],
)
def test_handles_are_normalized(raw: str, handle: str) -> None:
    assert service.normalize_handle(raw) == handle


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "two words",
        "a" * 31,
        "fake-creator",
        "https://example.com/x",
        "https://www.instagram.com/p/abc/",
    ],
)
def test_invalid_handles_are_refused(raw: str) -> None:
    with pytest.raises(service.InvalidHandle):
        service.normalize_handle(raw)


def test_add_is_idempotent_and_reactivates_an_archived_creator(store) -> None:
    first = service.add_creator(TENANT, BRAND, "@Fake.Creator", user_id=USER, note="buena")
    again = service.add_creator(TENANT, BRAND, HANDLE, user_id=USER)
    assert again.id == first.id and again.note == "buena"
    service.archive_creator(TENANT, BRAND, first.id)
    service.archive_creator(TENANT, BRAND, first.id)  # idempotent
    assert service.list_creators(TENANT, BRAND) == []
    assert [
        c.tracked.status for c in service.list_creators(TENANT, BRAND, include_archived=True)
    ] == ["archived"]
    back = service.add_creator(TENANT, BRAND, HANDLE, user_id=USER)
    assert back.id == first.id and back.status == "active"
    with pytest.raises(service.UnsupportedNetwork):
        service.add_creator(TENANT, BRAND, HANDLE, user_id=USER, network="tiktok")
    with pytest.raises(service.CreatorNotFound):
        service.archive_creator(TENANT, OTHER_BRAND, first.id)


def test_list_sheet_and_compare_through_the_facade(store) -> None:
    a = service.add_creator(TENANT, BRAND, HANDLE, user_id=USER)
    assert service.creator_sheet(TENANT, BRAND, a.id) is None  # not read yet
    cards = service.list_creators(TENANT, BRAND)
    assert cards[0].read_at is None and cards[0].median_views.status == "unknown"
    outcome = service.refresh_creator(
        TENANT, BRAND, a.id, now=NOW, client=fake.FakeVendor().client()
    )
    assert outcome.status == "read"
    sheet = service.creator_sheet(TENANT, BRAND, a.id, now=NOW + timedelta(days=1))
    assert sheet is not None
    assert sheet.snapshot_id == outcome.snapshot_id and sheet.reels_read == 48
    assert sheet.followers.value == 20000 and sheet.median_views.status == "ok"
    assert sheet.freshness_days == 1 and not sheet.stale
    card = service.list_creators(TENANT, BRAND, now=NOW)[0]
    assert card.followers == 20000 and card.median_views == sheet.median_views

    # a second creator, read by hand into the store, to compare with
    b = store.add(
        TENANT, BRAND, network="instagram", handle="other.creator", note="", user_id=USER, now=NOW
    )
    store.save_read(
        TENANT,
        BRAND,
        b.id,
        snapshot=NewSnapshot(
            id=uuid4(),
            network="instagram",
            handle="other.creator",
            read_at=NOW,
            status="ok",
            parser_version=2,
            reels_target=48,
            followers=5000,
        ),
        reads=[],
        reels=[],
        creator=store.pool.creator("instagram", HANDLE),
        link=True,
        state="ok",
        error=None,
        now=NOW,
    )
    comparison = service.compare_creators(TENANT, BRAND, [a.id, b.id, a.id], now=NOW)
    assert [c.tracked_id for c in comparison.creators] == [a.id, b.id]
    with pytest.raises(service.TooManyToCompare):
        service.compare_creators(TENANT, BRAND, [a.id], now=NOW)
    c = service.add_creator(TENANT, BRAND, "never.read", user_id=USER)
    with pytest.raises(service.NotReadYet):
        service.compare_creators(TENANT, BRAND, [a.id, c.id], now=NOW)
    with pytest.raises(service.CreatorNotFound):
        service.creator_sheet(TENANT, OTHER_BRAND, a.id)
