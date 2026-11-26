"""«Publicación del mes» chore (m-25120705): opt-in, once per brand and month, one charge."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID, uuid4

from qualify_creative.enums import ContentKind

from qualify_api.ads.month_plan import PlanDate
from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.service import BrandNotReady
from qualify_api.planner import monthly_post_job as job_mod
from qualify_api.planner.monthly_post_job import EnabledBrand, MonthlyPostJob, request_key

T = uuid4()
OWNER = uuid4()
MOTHERS_DAY = PlanDate("dia_madre", "Día de la Madre", date(2026, 5, 10), date(2026, 5, 10),
                       "grande", "verified")  # fmt: skip


@dataclass
class FakeStore:
    brands: dict[UUID, list[EnabledBrand]] = field(default_factory=dict)
    rows: dict[tuple[UUID, date], dict] = field(default_factory=dict)

    def enabled_brands(self, tenant_id: UUID) -> list[EnabledBrand]:
        return self.brands.get(tenant_id, [])

    def claim(self, *, tenant_id, brand_id, period, event, kind) -> bool:
        if (brand_id, period) in self.rows:
            return False
        self.rows[(brand_id, period)] = {"status": "pending", "event": event and event.id}
        return True

    def settle(self, *, tenant_id, brand_id, period, status, skip_reason=None, draft_id=None):
        row = self.rows[(brand_id, period)]
        if row["status"] == "pending":
            row.update(status=status, reason=skip_reason, draft=draft_id)


@dataclass
class FakeDrafts:
    """`create_draft`'s contract: a known key returns its draft, never a second charge."""

    balance: int = 10
    raise_: Exception | None = None
    by_key: dict[UUID, UUID] = field(default_factory=dict)
    charges: int = 0
    briefs: list = field(default_factory=list)

    def create_draft(self, *, tenant_id, brand_id, brief, user_id, request_key=None) -> UUID:
        assert user_id == OWNER and request_key is not None
        if request_key in self.by_key:
            return self.by_key[request_key]
        if self.raise_ is not None:
            raise self.raise_
        if self.balance < 1:
            raise NotEnoughCreations(weight=1, left=0)
        self.balance -= 1
        self.charges += 1
        self.briefs.append(brief)
        self.by_key[request_key] = draft = uuid4()
        return draft

    def draft_for_request(self, *, tenant_id, request_key) -> UUID | None:
        return self.by_key.get(request_key)


def _job(store: FakeStore, drafts: FakeDrafts, monkeypatch, event=MOTHERS_DAY) -> MonthlyPostJob:
    monkeypatch.setattr(job_mod, "event_of_month", lambda *a, **k: event)
    return MonthlyPostJob(
        store=store, drafts=lambda: drafts, country_of=lambda t: "CO", owner_of=lambda t: OWNER
    )


def _brand(kind: ContentKind = ContentKind.STATIC_FLYER) -> EnabledBrand:
    return EnabledBrand(uuid4(), kind, "comida")


def test_twice_in_a_month_one_draft_one_charge(monkeypatch) -> None:
    brand = _brand()
    store, drafts = FakeStore({T: [brand]}), FakeDrafts()
    job = _job(store, drafts, monkeypatch)
    job.run([T], date(2026, 5, 1))
    job.run([T], date(2026, 5, 2))
    assert drafts.charges == 1
    row = store.rows[(brand.brand_id, date(2026, 5, 1))]
    assert row["status"] == "created" and row["draft"] is not None
    assert drafts.briefs[0].topic == "Día de la Madre"
    assert drafts.briefs[0].kind is ContentKind.STATIC_FLYER


def test_retry_after_a_crash_gets_the_same_draft_without_charge(monkeypatch) -> None:
    brand = _brand()
    drafts = FakeDrafts()
    # a previous run created the draft and died before settling; its claim went stale
    drafts.by_key[request_key(brand.brand_id, date(2026, 5, 1))] = existing = uuid4()
    store = FakeStore({T: [brand]})
    _job(store, drafts, monkeypatch).run([T], date(2026, 5, 1))
    assert drafts.charges == 0
    assert store.rows[(brand.brand_id, date(2026, 5, 1))]["draft"] == existing


def test_setting_off_does_nothing(monkeypatch) -> None:
    store, drafts = FakeStore(), FakeDrafts()  # no enabled brand
    _job(store, drafts, monkeypatch).run([T], date(2026, 5, 1))
    assert drafts.charges == 0 and store.rows == {}


def test_not_enough_creations_is_skipped_without_draft(monkeypatch) -> None:
    brand = _brand()
    store, drafts = FakeStore({T: [brand]}), FakeDrafts(balance=0)
    _job(store, drafts, monkeypatch).run([T], date(2026, 5, 1))
    row = store.rows[(brand.brand_id, date(2026, 5, 1))]
    assert row == {"status": "skipped", "event": "dia_madre", "reason": "not_enough_creations",
                   "draft": None}  # fmt: skip
    assert drafts.by_key == {}


def test_brand_not_ready_is_skipped(monkeypatch) -> None:
    brand = _brand()
    store = FakeStore({T: [brand]})
    drafts = FakeDrafts(raise_=BrandNotReady(missing=("voice_profile",)))
    _job(store, drafts, monkeypatch).run([T], date(2026, 5, 1))
    assert store.rows[(brand.brand_id, date(2026, 5, 1))]["reason"] == "brand_not_ready"


def test_event_passed_or_too_close_writes_nothing(monkeypatch) -> None:
    brand = _brand()
    store, drafts = FakeStore({T: [brand]}), FakeDrafts()
    job = _job(store, drafts, monkeypatch)
    job.run([T], date(2026, 5, 8))  # 2 days before: under LEAD_DAYS
    job.run([T], date(2026, 5, 20))
    assert store.rows == {} and drafts.charges == 0


def test_no_event_is_skipped(monkeypatch) -> None:
    brand = _brand()
    store, drafts = FakeStore({T: [brand]}), FakeDrafts()
    _job(store, drafts, monkeypatch, event=None).run([T], date(2026, 5, 1))
    assert store.rows[(brand.brand_id, date(2026, 5, 1))]["reason"] == "no_event"
    assert drafts.charges == 0


def test_two_brands_of_one_tenant_are_independent(monkeypatch) -> None:
    a, b = _brand(), _brand(ContentKind.CLIP)
    store, drafts = FakeStore({T: [a, b]}), FakeDrafts(balance=1)
    _job(store, drafts, monkeypatch).run([T], date(2026, 5, 1))
    assert store.rows[(a.brand_id, date(2026, 5, 1))]["status"] == "created"
    assert store.rows[(b.brand_id, date(2026, 5, 1))]["reason"] == "not_enough_creations"
    assert request_key(a.brand_id, date(2026, 5, 1)) != request_key(b.brand_id, date(2026, 5, 1))


def test_a_kind_needing_owner_inputs_is_skipped_uncharged(monkeypatch) -> None:
    brand = _brand(ContentKind.CAROUSEL)  # needs slides the owner chooses
    store, drafts = FakeStore({T: [brand]}), FakeDrafts()
    _job(store, drafts, monkeypatch).run([T], date(2026, 5, 1))
    assert store.rows[(brand.brand_id, date(2026, 5, 1))]["reason"] == "brief_refused"
    assert drafts.charges == 0


def test_unexpected_error_without_draft_stays_pending(monkeypatch) -> None:
    brand = _brand()
    store, drafts = FakeStore({T: [brand]}), FakeDrafts(raise_=ConnectionError("db down"))
    _job(store, drafts, monkeypatch).run([T], date(2026, 5, 1))
    assert store.rows[(brand.brand_id, date(2026, 5, 1))]["status"] == "pending"


def test_request_key_is_stable_per_brand_and_month() -> None:
    brand = uuid4()
    assert request_key(brand, date(2026, 5, 1)) == request_key(brand, date(2026, 5, 1))
    assert request_key(brand, date(2026, 5, 1)) != request_key(brand, date(2026, 6, 1))
