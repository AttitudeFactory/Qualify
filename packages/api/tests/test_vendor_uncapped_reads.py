"""Uncapped ScrapeCreators reads for a business, switched from its Meegle Alta
(m-24956180, founder decision 2026-11-05) — offline.

- the switch (`vendors.uncapped`): no row = capped, Sí/No set it, cache and its reset, an
  unreadable store reads as capped;
- the gate: an uncapped business past 150/day and 600/month is still called AND booked;
  a capped one is refused as before; `no_tenant` and `usage_unreadable` still stop both;
- «Actualizar» a creator: past the Creators budget (50/300) and the business cap
  (150/600) an uncapped business reads, never `cap_reached`;
- the Alta field «Lecturas sin límite»: parsing, «Plan ampliado» applying it, the choice
  waiting on the invite, and its provenance.

The database half (RLS of `business_read_limits`, the invite column) is
`test_vendor_uncapped_reads_db.py`.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.auth.invites import AltaPlanChoice, _alta_columns, alta_plan_of
from qualify_api.creators import access, service, snapshots
from qualify_api.creators.tracking import MemoryTrackedCreatorStore
from qualify_api.meegle import onboarding, plan_request
from qualify_api.meegle.client import FieldMeta, WorkflowNode, WorkItem
from qualify_api.meegle.onboarding import OnboardingEngine
from qualify_api.meegle.plan_request import (
    InvalidPlanRequest,
    PlanApplied,
    confirmation_text,
    describe_choice,
    uncapped_flag_for,
)
from qualify_api.meegle.schema import SchemaResolver
from qualify_api.meegle.settings import MeegleNames
from qualify_api.tenancy.models import SignupInvite
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import uncapped, usage

UNCAPPED = UUID("d0000000-0000-4000-8000-0000000000d1")
CAPPED = UUID("d0000000-0000-4000-8000-0000000000d2")
ITEM = 24936000
EVENT = "evt-uncapped"
ACTOR = "meegle:herwin@attitudefactory.co"


def _uncap(tenant: UUID = UNCAPPED, value: bool = True) -> None:
    uncapped.set_uncapped_reads(tenant, value, set_by=ACTOR, meegle_work_item_id=ITEM)


# --------------------------------------------------------------------------------------
# The switch
# --------------------------------------------------------------------------------------


def test_a_business_without_a_row_is_capped() -> None:
    assert uncapped.is_uncapped(UNCAPPED) is False


def test_si_uncaps_and_no_caps_again_with_provenance() -> None:
    _uncap()
    assert uncapped.is_uncapped(UNCAPPED) is True
    assert uncapped.is_uncapped(CAPPED) is False  # per business, never everyone
    _uncap(value=False)
    assert uncapped.is_uncapped(UNCAPPED) is False
    store = uncapped.store()
    assert isinstance(store, uncapped.InMemoryUncappedStore)
    row = store.rows[UNCAPPED]
    assert (row.set_by, row.meegle_work_item_id, row.uncapped_reads) == (ACTOR, ITEM, False)
    assert row.updated_at is not None


def test_the_value_is_cached_for_a_minute_and_a_write_forgets_it() -> None:
    store = uncapped.store()
    assert isinstance(store, uncapped.InMemoryUncappedStore)
    assert uncapped.is_uncapped(UNCAPPED, clock=1000.0) is False
    # a write from ANOTHER process: this one keeps its cached answer for the minute
    store.set(uncapped.ReadLimit(UNCAPPED, True, ACTOR))
    assert uncapped.is_uncapped(UNCAPPED, clock=1030.0) is False
    assert uncapped.is_uncapped(UNCAPPED, clock=1000.0 + uncapped.CACHE_SECONDS) is True
    # a write in THIS process is read at once
    _uncap(value=False)
    assert uncapped.is_uncapped(UNCAPPED, clock=1061.0) is False


class _Broken:
    def uncapped(self, tenant_id: UUID) -> bool:
        raise RuntimeError("database down")

    def set(self, limit: uncapped.ReadLimit) -> None:
        raise RuntimeError("database down")


def test_an_unreadable_switch_reads_as_capped() -> None:
    uncapped.configure_store(_Broken())
    assert uncapped.is_uncapped(UNCAPPED) is False


# --------------------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------------------


class Wire:
    """The vendor's side of `sc._vendor_request`: answers 200, counts requests."""

    def __init__(self) -> None:
        self.requests: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, client: httpx.Client, path: str, params: dict[str, str]) -> httpx.Response:
        with self._lock:
            self.requests.append(path)
        return httpx.Response(
            200,
            json={"success": True, "credits_remaining": 5000, "credits_charged": 1},
            request=httpx.Request("GET", f"https://vendor.test{path}"),
        )


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_uncapped")
    fake = Wire()
    monkeypatch.setattr(sc, "_vendor_request", fake)
    return fake


@pytest.fixture
def ledger() -> usage.InMemoryUsageStore:
    active = usage.InMemoryUsageStore()
    usage.configure_store(active)
    return active


def _spend(
    ledger: usage.InMemoryUsageStore,
    tenant: UUID,
    credits: int,
    at: datetime | None = None,
    feature: str = sc.FEATURE_REELS_LIST,
) -> None:
    ledger.events.append(
        usage.UsageEvent(
            tenant_id=tenant,
            brand_id=None,
            vendor=usage.SCRAPECREATORS,
            feature=feature,
            credits=credits,
            usd_estimate=Decimal("0"),
            pricing_table_version=usage.PRICING_TABLE_VERSION,
            request_key=f"seed:{uuid4()}",
            created_at=at or datetime.now(UTC),
        )
    )


def _call(tenant: UUID | None) -> dict:
    charge = usage.UsageCharge(tenant) if tenant is not None else None
    with usage.bind(httpx.Client(), charge) as client:
        return sc.metered_get(
            client, "/v1/tiktok/profile", {"handle": "x"}, feature=sc.FEATURE_PROFILE
        )


def test_past_the_daily_cap_an_uncapped_business_is_called_and_booked(
    wire: Wire, ledger: usage.InMemoryUsageStore
) -> None:
    _uncap()
    _spend(ledger, UNCAPPED, usage.DAILY_CAP)
    assert _call(UNCAPPED)["success"] is True
    assert wire.requests == ["/v1/tiktok/profile"]
    booked = [e for e in ledger.of(UNCAPPED) if not e.request_key.startswith("seed:")]
    assert [(e.feature, e.credits) for e in booked] == [(sc.FEATURE_PROFILE, 1)]
    assert booked[0].pricing_table_version == usage.PRICING_TABLE_VERSION  # provenance
    assert ledger.spent(UNCAPPED, usage.SCRAPECREATORS).day == usage.DAILY_CAP + 1


def test_past_the_monthly_cap_an_uncapped_business_is_called_and_booked(
    wire: Wire, ledger: usage.InMemoryUsageStore
) -> None:
    _uncap()
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=5, second=0, microsecond=0)
    _spend(ledger, UNCAPPED, usage.MONTHLY_CAP, at=month_start)
    if datetime.now(UTC) - month_start < timedelta(hours=1):  # the seed would be "today"
        pytest.skip("too close to the start of the month to separate day from month")
    _call(UNCAPPED)
    assert len(wire.requests) == 1
    assert ledger.spent(UNCAPPED, usage.SCRAPECREATORS).month == usage.MONTHLY_CAP + 1


def test_a_capped_business_is_still_refused_at_its_cap(
    wire: Wire, ledger: usage.InMemoryUsageStore
) -> None:
    _uncap()  # another business is uncapped: nothing changes for this one
    _spend(ledger, CAPPED, usage.DAILY_CAP)
    with pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _call(CAPPED)
    assert caught.value.reason == usage.REASON_DAILY_CAP
    assert wire.requests == []


def test_an_uncapped_business_turned_off_is_refused_again(
    wire: Wire, ledger: usage.InMemoryUsageStore
) -> None:
    _uncap()
    _uncap(value=False)
    _spend(ledger, UNCAPPED, usage.DAILY_CAP)
    with pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _call(UNCAPPED)
    assert caught.value.reason == usage.REASON_DAILY_CAP


def test_the_other_refusals_still_stop_an_uncapped_business(
    wire: Wire, monkeypatch: pytest.MonkeyPatch
) -> None:
    _uncap()
    with pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _call(None)
    assert caught.value.reason == usage.REASON_NO_TENANT

    class Unreadable(usage.InMemoryUsageStore):
        def book(self, event: usage.UsageEvent, *, capped: bool) -> str | None:
            raise RuntimeError("database down")

    usage.configure_store(Unreadable())
    with pytest.raises(sc.ScrapeCreatorsBlocked) as caught:
        _call(UNCAPPED)
    assert caught.value.reason == usage.REASON_USAGE_UNREADABLE

    monkeypatch.setenv(sc.PAID_SWITCH_ENV, "0")
    usage.configure_store(usage.InMemoryUsageStore())
    with pytest.raises(sc.ScrapeCreatorsBlocked):
        _call(UNCAPPED)
    assert wire.requests == []


# --------------------------------------------------------------------------------------
# «Actualizar» a creator
# --------------------------------------------------------------------------------------


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


@pytest.fixture
def creators(monkeypatch: pytest.MonkeyPatch) -> MemoryTrackedCreatorStore:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_123")
    monkeypatch.setenv(access.ENV, f"{UNCAPPED},{CAPPED}")
    monkeypatch.delenv(sc.PAID_SWITCH_ENV, raising=False)
    access.reset_cache()
    memory = MemoryTrackedCreatorStore()
    service.configure_store(memory)
    yield memory
    access.reset_cache()
    service.configure_store(None)


def _refresh(store: MemoryTrackedCreatorStore, tenant: UUID) -> snapshots.RefreshOutcome:
    brand = uuid4()
    tracked = store.add(
        tenant,
        brand,
        network="instagram",
        handle=fake.HANDLE,
        note="",
        user_id=uuid4(),
        now=fake.NOW,
    )
    return snapshots.refresh_creator(
        tenant,
        brand,
        tracked.id,
        store=store,
        now=fake.NOW,
        client=fake.FakeVendor().client(),
        clock=lambda: fake.NOW,
        sleep=lambda _s: None,
    )


def _seed_both_caps(tenant: UUID) -> None:
    ledger = usage.store()
    assert isinstance(ledger, usage.InMemoryUsageStore)
    # past the Creators budget (50/day) AND the business's whole day (150)
    _spend(ledger, tenant, snapshots.CREATOR_DAY_CAP, feature=sc.FEATURE_CREATOR_REELS)
    _spend(ledger, tenant, usage.DAILY_CAP, feature=sc.FEATURE_REELS_LIST)


def test_an_uncapped_business_past_both_caps_reads_a_creator(
    creators: MemoryTrackedCreatorStore,
) -> None:
    _uncap()
    _seed_both_caps(UNCAPPED)
    outcome = _refresh(creators, UNCAPPED)
    assert (outcome.status, outcome.credits) == ("read", snapshots.SNAPSHOT_MAX_CREDITS)
    ledger = usage.store()
    assert isinstance(ledger, usage.InMemoryUsageStore)
    booked = [e for e in ledger.of(UNCAPPED) if not e.request_key.startswith("seed:")]
    assert sum(e.credits for e in booked) == snapshots.SNAPSHOT_MAX_CREDITS  # every credit


def test_a_capped_business_past_both_caps_still_reads_cap_reached(
    creators: MemoryTrackedCreatorStore,
) -> None:
    _uncap()  # the other business
    _seed_both_caps(CAPPED)
    outcome = _refresh(creators, CAPPED)
    assert (outcome.status, outcome.credits) == ("cap_reached", 0)


# --------------------------------------------------------------------------------------
# «Lecturas sin límite» on the Alta
# --------------------------------------------------------------------------------------

KEYS = {
    "Correo": "f_mail",
    "Nombre de la persona": "f_name",
    "Nota personal": "f_note",
    "Estado Qualify": "f_status",
    "Enlace de invitación": "f_link",
    "Vence": "f_expires",
    "Registrada el": "f_registered",
    "Tenant": "f_tenant",
    "Qualify ref": "f_ref",
    "Lecturas sin límite": "f_uncapped",
}
SELECTS = {
    "Estado Qualify": tuple(
        (label, f"opt_{label}") for label in ("invitada", "registrada", "error")
    ),
    "Lecturas sin límite": (("Sí", "opt_si"), ("No", "opt_no")),
}


class AltaMeegle:
    """The slice of `MeegleClient` the engine uses, with the new select on the type."""

    def __init__(self) -> None:
        self.items: dict[int, WorkItem] = {
            ITEM: WorkItem(id=ITEM, name="Bianki", fields={"f_mail": "a@b.co"})
        }
        self.updates: list[tuple[int, dict[str, Any]]] = []
        self.comments: list[str] = []
        self.operations: list[tuple[int, str, str]] = []

    def query(self, ids: list[int]) -> list[WorkItem]:
        return [self.items[i] for i in ids if i in self.items]

    def update_fields(self, work_item_id: int, pairs: dict[str, Any]) -> None:
        self.updates.append((work_item_id, dict(pairs)))

    def operate_node(
        self, work_item_id: int, node_id: str, *, action: str = "confirm", rollback_reason: str = ""
    ) -> None:
        self.operations.append((work_item_id, node_id, action))

    def comment(self, work_item_id: int, markdown: str) -> int | None:
        self.comments.append(markdown)
        return len(self.comments)

    def fields_meta(self) -> list[FieldMeta]:
        return [
            FieldMeta(key, name, "select" if name in SELECTS else "text", SELECTS.get(name, ()))
            for name, key in KEYS.items()
        ]

    def workflow(self, work_item_id: int) -> list[WorkflowNode]:
        return [
            WorkflowNode("started", "started", "Datos"),
            WorkflowNode("state_2", "state_2", "Plan ampliado"),
        ]


@pytest.fixture
def meegle() -> AltaMeegle:
    return AltaMeegle()


@pytest.fixture
def resolver(meegle: AltaMeegle) -> SchemaResolver:
    return SchemaResolver(meegle, MeegleNames())  # type: ignore[arg-type]


@pytest.fixture
def engine(meegle: AltaMeegle, resolver: SchemaResolver) -> OnboardingEngine:
    return OnboardingEngine(meegle, resolver)  # type: ignore[arg-type]


NAME = "Lecturas sin límite"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("opt_si", True),
        ("opt_no", False),
        ({"value": "opt_si", "label": "Sí"}, True),
        ("Sí", True),
        ("si", True),
        (" SÍ ", True),
        ("No", False),
        ("", None),
        ("   ", None),
        (None, None),
        (True, True),
        (False, None),  # an untouched Switch never turns a business off
    ],
)
def test_the_field_reads_si_no_or_nothing(
    resolver: SchemaResolver, raw: Any, expected: Any
) -> None:
    assert uncapped_flag_for(raw, resolver, NAME) is expected


def test_any_other_value_is_refused_in_spanish(resolver: SchemaResolver) -> None:
    with pytest.raises(InvalidPlanRequest) as raised:
        uncapped_flag_for("Todas", resolver, NAME)
    assert raised.value.message == (
        "«Todas» no es una opción de «Lecturas sin límite». Las opciones son: Sí, No."
    )


def test_a_type_without_the_field_changes_nothing(engine: OnboardingEngine) -> None:
    class Plain(AltaMeegle):
        def fields_meta(self) -> list[FieldMeta]:
            return [m for m in super().fields_meta() if m.name != NAME]

    plain = Plain()
    choice = OnboardingEngine(plain, SchemaResolver(plain, MeegleNames())).plan_choice(  # type: ignore[arg-type]
        plain.items[ITEM], event_key=EVENT, actor=ACTOR
    )
    assert choice.uncapped_reads is None and choice.empty


def test_plan_ampliado_with_only_the_field_uncaps_the_business(
    engine: OnboardingEngine, meegle: AltaMeegle, monkeypatch: pytest.MonkeyPatch
) -> None:
    meegle.items[ITEM].fields["f_uncapped"] = "opt_si"
    monkeypatch.setattr(onboarding, "registered_tenant_for_work_item", lambda item: UNCAPPED)
    monkeypatch.setattr(plan_request, "_business_name", lambda tenant: "Bianki")
    result = engine.apply_plan_update(ITEM, event_key=EVENT, actor=ACTOR)
    assert result.ok and result.reason == "applied"
    assert uncapped.is_uncapped(UNCAPPED) is True
    row = uncapped.store().rows[UNCAPPED]  # type: ignore[attr-defined]
    assert (row.set_by, row.meegle_work_item_id, row.event_key) == (ACTOR, ITEM, EVENT)
    assert meegle.comments[-1].startswith("Lecturas sin límite para Bianki: activadas.")
    assert meegle.operations == []  # nothing rolled back


def test_plan_ampliado_with_no_turns_it_back_off(
    engine: OnboardingEngine, meegle: AltaMeegle, monkeypatch: pytest.MonkeyPatch
) -> None:
    _uncap()
    meegle.items[ITEM].fields["f_uncapped"] = "opt_no"
    monkeypatch.setattr(onboarding, "registered_tenant_for_work_item", lambda item: UNCAPPED)
    monkeypatch.setattr(plan_request, "_business_name", lambda tenant: "Bianki")
    assert engine.apply_plan_update(ITEM, event_key=EVENT, actor=ACTOR).ok
    assert uncapped.is_uncapped(UNCAPPED) is False
    assert meegle.comments[-1].endswith("desactivadas. Vuelve al tope de siempre.")


def test_an_invalid_value_applies_nothing_and_rolls_back(
    engine: OnboardingEngine, meegle: AltaMeegle, monkeypatch: pytest.MonkeyPatch
) -> None:
    meegle.items[ITEM].fields["f_uncapped"] = "Todas"
    monkeypatch.setattr(onboarding, "registered_tenant_for_work_item", lambda item: UNCAPPED)
    result = engine.apply_plan_update(ITEM, event_key=EVENT, actor=ACTOR)
    assert not result.ok and result.reason == "invalid_plan"
    assert uncapped.is_uncapped(UNCAPPED) is False
    assert meegle.operations[-1] == (ITEM, "state_2", "rollback")


def test_before_the_signup_the_flag_waits_on_the_invite(
    engine: OnboardingEngine, meegle: AltaMeegle, monkeypatch: pytest.MonkeyPatch
) -> None:
    meegle.items[ITEM].fields["f_uncapped"] = "opt_si"
    stored: list[AltaPlanChoice] = []
    monkeypatch.setattr(onboarding, "registered_tenant_for_work_item", lambda item: None)
    monkeypatch.setattr(
        onboarding, "set_pending_alta_plan", lambda item, choice: stored.append(choice) or 1
    )
    result = engine.apply_plan_update(ITEM, event_key=EVENT, actor=ACTOR)
    assert result.ok and result.reason == "pending_registration"
    assert stored[0].uncapped_reads is True and stored[0].plan_code is None
    assert meegle.comments[-1] == (
        "El negocio todavía no se registró. Cuando se registre se aplica: lecturas sin límite."
    )
    assert uncapped.is_uncapped(UNCAPPED) is False  # nothing applied yet


def test_the_flag_rides_on_the_invite_columns_and_back() -> None:
    choice = AltaPlanChoice(uncapped_reads=True, requested_by=ACTOR, event_key=EVENT)
    columns = _alta_columns(choice)
    assert columns["alta_uncapped_reads"] is True and columns["alta_plan_code"] is None
    invite = SignupInvite(**columns)
    assert alta_plan_of(invite) == choice
    assert _alta_columns(AltaPlanChoice())["alta_uncapped_reads"] is None
    assert alta_plan_of(SignupInvite(**_alta_columns(None))) is None


def test_at_signup_the_waiting_flag_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plan_request, "_business_name", lambda tenant: "Bianki")
    choice = AltaPlanChoice(uncapped_reads=True, requested_by=ACTOR, event_key=EVENT)
    applied = plan_request.apply_on_registration(ITEM, UNCAPPED, choice)
    assert applied is not None and applied.uncapped_reads is True
    assert uncapped.is_uncapped(UNCAPPED) is True


def test_texts_name_the_flag_only_when_it_was_set() -> None:
    assert describe_choice(AltaPlanChoice(plan_code="plus", uncapped_reads=True)) == (
        "plan Plus y lecturas sin límite"
    )
    assert describe_choice(AltaPlanChoice(uncapped_reads=False)) == (
        "lecturas con el límite de siempre"
    )
    plain = PlanApplied(
        business="Korner",
        plan_code=None,
        plan_name=None,
        effective_month=None,
        current_month=datetime(2026, 11, 1, tzinfo=UTC).date(),
        pack_code=None,
        pack_expires_at=None,
    )
    assert confirmation_text(plain) == ""
