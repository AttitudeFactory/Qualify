"""m-24852131 offline: «Plan» / «Paquete» / «Motivo» on the «Alta de cliente» item.

Reading and validating the selects, what «Datos» stores on the invite, what «Plan
ampliado» does (applied, waiting for the signup, refused + rollback) and the comment
texts. The database half (registration, idempotency by event) is in
`test_alta_plan_db.py`."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from qualify_api.auth.invites import AltaPlanChoice, CreatedInvite
from qualify_api.mail import FakeMailer
from qualify_api.meegle import onboarding, plan_request
from qualify_api.meegle.client import FieldMeta, WorkflowNode, WorkItem
from qualify_api.meegle.onboarding import OnboardingEngine
from qualify_api.meegle.plan_request import (
    InvalidPlanRequest,
    PlanApplied,
    confirmation_text,
    pack_code_for,
    plan_code_for,
)
from qualify_api.meegle.schema import SchemaResolver
from qualify_api.meegle.settings import MeegleNames
from qualify_api.plans.catalog import load_plans, load_prices
from qualify_api.plans.pack_service import PackRefused

NOW = datetime(2026, 10, 16, 15, 0, tzinfo=UTC)
TENANT = UUID("77777777-7777-4777-8777-777777777777")
ITEM = 5390584662
EVENT = "evt-90d94fba"
ACTOR = "meegle:herwin@attitudefactory.co"

# -- the slice of `MeegleClient` and the invite functions (as in test_meegle_onboarding)


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
}
STATUS_OPTIONS = tuple(
    (label, f"opt_{label}")
    for label in ("pendiente", "invitada", "entregada", "registrada", "vencida", "error")
)


class FakeMeegle:
    """The slice of `MeegleClient` the engine uses, recording every write."""

    def __init__(self) -> None:
        self.items: dict[int, WorkItem] = {}
        self.updates: list[tuple[int, dict[str, Any]]] = []
        self.comments: list[tuple[int, str]] = []
        self.operations: list[tuple[int, str, str, str]] = []
        self.refuse_operate: Exception | None = None
        self.keys: dict[str, str] = dict(KEYS)  # the type's fields, by display name

    def query(self, ids: list[int]) -> list[WorkItem]:
        return [self.items[i] for i in ids if i in self.items]

    def update_fields(self, work_item_id: int, pairs: dict[str, Any]) -> None:
        self.updates.append((work_item_id, dict(pairs)))

    def operate_node(
        self, work_item_id: int, node_id: str, *, action: str = "confirm", rollback_reason: str = ""
    ) -> None:
        if self.refuse_operate is not None:
            raise self.refuse_operate
        self.operations.append((work_item_id, node_id, action, rollback_reason))

    def comment(self, work_item_id: int, markdown: str) -> int | None:
        self.comments.append((work_item_id, markdown))
        return len(self.comments)

    def fields_meta(self) -> list[FieldMeta]:
        return [
            FieldMeta(
                key,
                name,
                "select" if name == "Estado Qualify" else "text",
                STATUS_OPTIONS if name == "Estado Qualify" else (),
            )
            for name, key in self.keys.items()
        ]

    def workflow(self, work_item_id: int) -> list[WorkflowNode]:
        return [
            WorkflowNode("started", "started", "Datos"),
            WorkflowNode("state_0", "state_0", "Invitada"),
            WorkflowNode("state_1", "state_1", "Registrada"),
        ]


class Invites:
    """Stubs for `create_invite` / `send_invite_email` / `expire_invites_for_work_item`."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.sent: list[tuple[CreatedInvite, str, str]] = []
        self.expired: list[int] = []
        self.create_raises: Exception | None = None
        self.send_raises: Exception | None = None
        self.expire_returns = 1

    def create_invite(self, email: str, **kwargs: Any) -> CreatedInvite:
        if self.create_raises is not None:
            raise self.create_raises
        self.created.append({"email": email, **kwargs})
        return CreatedInvite(
            email=email,
            token="tok123",
            expires_at=NOW + timedelta(days=7),
            recipient_name=kwargs.get("recipient_name", ""),
            business_name=kwargs.get("business_name", ""),
            note=kwargs.get("note", ""),
            id=UUID("12345678-1234-4123-8123-123456789abc"),
        )

    def send_invite_email(self, mailer, invite, base_url, *, signer="", can_reply=False):  # noqa: ANN001, ANN201
        if self.send_raises is not None:
            raise self.send_raises
        self.sent.append((invite, base_url, signer))
        return mailer.send.__self__.__class__.__name__ and "re_123"

    def expire_invites_for_work_item(self, work_item_id: int) -> int:
        self.expired.append(work_item_id)
        return self.expire_returns


PLAN_OPTIONS = (("Básico", "opt_basico"), ("Plus", "opt_plus"), ("Pro", "opt_pro"))
PACK_OPTIONS = (
    ("+2 videos", "opt_v2"),
    ("+20 creaciones", "opt_c20"),
    ("+10 vistas previas", "opt_p10"),
    ("+3 videos", "opt_v3"),  # an option someone added by hand: not a pack of the table
)


class PlanMeegle(FakeMeegle):
    """The Alta type once the founder added the plan fields and the «Plan ampliado» node."""

    def __init__(self) -> None:
        super().__init__()
        self.keys.update({"Plan": "f_plan", "Paquete": "f_pack", "Motivo": "f_reason"})
        self.options = {"Plan": PLAN_OPTIONS, "Paquete": PACK_OPTIONS}

    def fields_meta(self) -> list[FieldMeta]:
        metas = super().fields_meta()
        return [
            FieldMeta(m.key, m.name, "select", self.options[m.name])
            if m.name in self.options
            else m
            for m in metas
        ]

    def workflow(self, work_item_id: int) -> list[WorkflowNode]:
        return [
            *super().workflow(work_item_id),
            WorkflowNode("state_2", "state_2", "Plan ampliado"),
        ]


@pytest.fixture
def meegle() -> PlanMeegle:
    from qualify_api.meegle.client import WorkItem

    fake = PlanMeegle()
    fake.items[ITEM] = WorkItem(
        id=ITEM,
        name="Arepera La Nona",
        fields={"f_mail": "maria@arepera.com", "f_name": "María", "f_note": ""},
    )
    return fake


@pytest.fixture
def invites(monkeypatch: pytest.MonkeyPatch) -> Invites:
    stubs = Invites()
    monkeypatch.setattr(onboarding, "create_invite", stubs.create_invite)
    monkeypatch.setattr(onboarding, "send_invite_email", stubs.send_invite_email)
    monkeypatch.setattr(onboarding, "mail_reply_to", lambda: "")
    return stubs


@pytest.fixture
def engine(meegle: PlanMeegle, invites: Invites) -> OnboardingEngine:
    mailer = FakeMailer()
    return OnboardingEngine(
        meegle,  # type: ignore[arg-type]
        SchemaResolver(meegle, MeegleNames()),
        mailer=lambda: mailer,
        base_url="https://app.qualify.la",
        clock=lambda: NOW,
        account_exists=lambda email: False,
    )


def _fill(meegle: PlanMeegle, **values: Any) -> None:
    keys = {"plan": "f_plan", "pack": "f_pack", "reason": "f_reason"}
    for name, value in values.items():
        meegle.items[ITEM].fields[keys[name]] = value


def _status(meegle: PlanMeegle) -> Any:
    return meegle.updates[-1][1].get("f_status")


# --------------------------------------------------------------------------------------
# Catalog lookups
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "code"),
    [("Básico", "basico"), ("basico", "basico"), (" PLUS ", "plus"), ("Pro", "pro"), ("", None)],
)
def test_plan_labels_map_to_catalog_codes(label: str, code: str | None) -> None:
    assert plan_code_for(label, load_plans()) == code


def test_a_plan_that_does_not_exist_is_refused_in_spanish() -> None:
    with pytest.raises(InvalidPlanRequest) as raised:
        plan_code_for("Oro", load_plans())
    assert raised.value.message == "«Oro» no es un plan. Los planes son: Básico, Plus, Pro."


def test_only_the_fixed_packs_are_packs() -> None:
    prices = load_prices()
    assert pack_code_for("+2 videos", prices) == "videos_2"
    assert pack_code_for("+20 Creaciones", prices) == "creations_20"
    assert pack_code_for("", prices) is None
    with pytest.raises(InvalidPlanRequest, match="«\\+3 videos» no es un paquete"):
        pack_code_for("+3 videos", prices)


@pytest.mark.parametrize(
    "raw",
    [
        "opt_plus",
        {"value": "opt_plus", "label": "Plus"},
        {"value": "opt_plus"},
        '{"value": "opt_plus", "label": "Plus"}',
        ["opt_plus"],
        "Plus",
    ],
)
def test_every_shape_of_a_select_value_reads_as_its_label(
    engine: OnboardingEngine, meegle: PlanMeegle, raw: Any
) -> None:
    _fill(meegle, plan=raw)
    choice = engine.plan_choice(meegle.items[ITEM], event_key=EVENT, actor=ACTOR)
    assert choice.plan_code == "plus"


# --------------------------------------------------------------------------------------
# «Datos»: the choice rides on the invite
# --------------------------------------------------------------------------------------


def test_an_alta_without_plan_invites_exactly_as_before(
    engine: OnboardingEngine, meegle: PlanMeegle, invites: Invites
) -> None:
    result = engine.start_invitation(ITEM, event_key=EVENT, actor=ACTOR)
    assert result.ok
    (created,) = invites.created
    assert "alta_plan" not in created  # empty = Básico: nothing to apply, no assignment
    assert "Al registrarse" not in meegle.comments[-1][1]


def test_datos_stores_plan_pack_reason_and_provenance_on_the_invite(
    engine: OnboardingEngine, meegle: PlanMeegle, invites: Invites
) -> None:
    _fill(meegle, plan="opt_plus", pack="opt_v2", reason={"doc_text": "Pagó Plus por Nequi"})
    result = engine.start_invitation(ITEM, event_key=EVENT, actor=ACTOR)
    assert result.ok
    (created,) = invites.created
    assert created["alta_plan"] == AltaPlanChoice(
        plan_code="plus",
        pack_code="videos_2",
        reason="Pagó Plus por Nequi",
        requested_by=ACTOR,
        event_key=EVENT,
    )
    comment = meegle.comments[-1][1]
    assert comment.endswith(
        "Al registrarse el negocio se aplica: plan Plus y el paquete «+2 videos»."
    )
    assert "USD" not in comment and "$" not in comment


def test_an_invalid_plan_creates_no_invite_and_rolls_back_datos(
    engine: OnboardingEngine, meegle: PlanMeegle, invites: Invites
) -> None:
    _fill(meegle, plan="Oro")
    result = engine.start_invitation(ITEM, event_key=EVENT, actor=ACTOR)
    assert not result.ok and result.reason == "invalid_plan"
    assert invites.created == [] and invites.sent == []
    assert _status(meegle) == {"value": "opt_error", "label": "error"}
    assert "«Oro» no es un plan" in meegle.comments[-1][1]
    assert meegle.operations[-1][:3] == (ITEM, "started", "rollback")


def test_an_invalid_pack_creates_no_invite(
    engine: OnboardingEngine, meegle: PlanMeegle, invites: Invites
) -> None:
    _fill(meegle, plan="opt_pro", pack="opt_v3")
    result = engine.start_invitation(ITEM, event_key=EVENT, actor=ACTOR)
    assert not result.ok and invites.created == []
    assert "no es un paquete" in meegle.comments[-1][1]


# --------------------------------------------------------------------------------------
# «Plan ampliado»
# --------------------------------------------------------------------------------------


class Applier:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, AltaPlanChoice, int]] = []
        self.raises: Exception | None = None

    def __call__(
        self, tenant_id: UUID, choice: AltaPlanChoice, *, work_item_id: int
    ) -> PlanApplied:
        if self.raises is not None:
            raise self.raises
        self.calls.append((tenant_id, choice, work_item_id))
        return PlanApplied(
            business="Arepera La Nona",
            plan_code=choice.plan_code,
            plan_name={"plus": "Plus", "basico": "Básico", "pro": "Pro"}.get(
                choice.plan_code or ""
            ),
            effective_month=date(2026, 10, 1) if choice.plan_code else None,
            current_month=date(2026, 10, 1),
            pack_code=choice.pack_code,
            pack_expires_at=NOW + timedelta(days=90) if choice.pack_code else None,
        )


@pytest.fixture
def applier(monkeypatch: pytest.MonkeyPatch) -> Applier:
    fake = Applier()
    monkeypatch.setattr(onboarding, "apply_alta_plan", fake)
    return fake


def _registered(monkeypatch: pytest.MonkeyPatch, tenant: UUID | None, pending: int = 0) -> list:
    stored: list[tuple[int, AltaPlanChoice]] = []
    monkeypatch.setattr(onboarding, "registered_tenant_for_work_item", lambda item: tenant)

    def set_pending(item: int, choice: AltaPlanChoice) -> int:
        stored.append((item, choice))
        return pending

    monkeypatch.setattr(onboarding, "set_pending_alta_plan", set_pending)
    return stored


def test_plan_node_applies_to_the_registered_business_and_confirms(
    engine: OnboardingEngine,
    meegle: PlanMeegle,
    applier: Applier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _registered(monkeypatch, TENANT)
    _fill(meegle, plan="opt_plus", pack="opt_v2", reason="Subió de plan")
    result = engine.apply_plan_update(ITEM, event_key=EVENT, actor=ACTOR)
    assert result.ok and result.reason == "applied"
    ((tenant, choice, item),) = applier.calls
    assert (tenant, item) == (TENANT, ITEM)
    assert choice.event_key == EVENT and choice.requested_by == ACTOR
    assert meegle.comments[-1][1] == (
        "Plan de Arepera La Nona: Plus. Se sumó el paquete +2 videos, vence el 14 de enero."
    )
    assert _status(meegle) == {"value": "opt_registrada", "label": "registrada"}
    assert meegle.operations == []  # nothing rolled back


def test_plan_node_with_nothing_chosen_is_refused_and_rolled_back(
    engine: OnboardingEngine,
    meegle: PlanMeegle,
    applier: Applier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _registered(monkeypatch, TENANT)
    result = engine.apply_plan_update(ITEM, event_key=EVENT, actor=ACTOR)
    assert not result.ok and result.reason == "nothing_chosen"
    assert applier.calls == []
    assert _status(meegle) == {"value": "opt_error", "label": "error"}
    assert meegle.comments[-1][1].endswith("vuelve a completar «Plan ampliado».")
    assert meegle.operations[-1][:3] == (ITEM, "state_2", "rollback")


def test_plan_node_with_an_invalid_value_applies_nothing(
    engine: OnboardingEngine,
    meegle: PlanMeegle,
    applier: Applier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _registered(monkeypatch, TENANT)
    _fill(meegle, plan="opt_plus", pack="opt_v3")
    result = engine.apply_plan_update(ITEM, event_key=EVENT, actor=ACTOR)
    assert not result.ok and result.reason == "invalid_plan"
    assert applier.calls == []  # not even the (valid) plan
    assert meegle.operations[-1][2] == "rollback"


def test_a_refusal_of_the_plan_services_is_reported_and_rolled_back(
    engine: OnboardingEngine,
    meegle: PlanMeegle,
    applier: Applier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _registered(monkeypatch, TENANT)
    applier.raises = PackRefused("that business has several brands: say which with --brand")
    _fill(meegle, pack="opt_c20")
    result = engine.apply_plan_update(ITEM, event_key=EVENT, actor=ACTOR)
    assert not result.ok and result.reason == "plan_refused"
    assert "several brands" in meegle.comments[-1][1]
    assert meegle.operations[-1][2] == "rollback"


def test_before_the_signup_the_choice_waits_on_the_invite(
    engine: OnboardingEngine,
    meegle: PlanMeegle,
    applier: Applier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _registered(monkeypatch, None, pending=1)
    _fill(meegle, plan="opt_pro")
    result = engine.apply_plan_update(ITEM, event_key=EVENT, actor=ACTOR)
    assert result.ok and result.reason == "pending_registration"
    ((item, choice),) = stored
    assert item == ITEM and choice.plan_code == "pro" and choice.pack_code is None
    assert applier.calls == []
    assert meegle.comments[-1][1] == (
        "El negocio todavía no se registró. Cuando se registre se aplica: plan Pro."
    )


def test_without_business_nor_live_invite_it_is_refused(
    engine: OnboardingEngine,
    meegle: PlanMeegle,
    applier: Applier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _registered(monkeypatch, None, pending=0)
    _fill(meegle, plan="opt_pro")
    result = engine.apply_plan_update(ITEM, event_key=EVENT, actor=ACTOR)
    assert not result.ok and result.reason == "not_registered"
    assert meegle.operations[-1][:3] == (ITEM, "state_2", "rollback")


def test_a_type_without_the_plan_fields_refuses_the_node_politely(
    invites: Invites, applier: Applier, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_api.meegle.client import WorkItem

    plain = FakeMeegle()
    plain.items[ITEM] = WorkItem(id=ITEM, name="X", fields={})
    _registered(monkeypatch, TENANT)
    engine = OnboardingEngine(plain, SchemaResolver(plain, MeegleNames()))  # type: ignore[arg-type]
    result = engine.apply_plan_update(ITEM, event_key=EVENT, actor=ACTOR)
    assert not result.ok and result.reason == "nothing_chosen"


# --------------------------------------------------------------------------------------
# Texts and the apply function
# --------------------------------------------------------------------------------------


def test_a_downgrade_says_from_when() -> None:
    applied = PlanApplied(
        business="Heladería Polette",
        plan_code="basico",
        plan_name="Básico",
        effective_month=date(2026, 11, 1),
        current_month=date(2026, 10, 1),
        pack_code=None,
        pack_expires_at=None,
    )
    assert (
        confirmation_text(applied) == "Plan de Heladería Polette: Básico desde el 1 de noviembre."
    )


def test_a_pack_alone_names_the_business() -> None:
    applied = PlanApplied(
        business="Korner",
        plan_code=None,
        plan_name=None,
        effective_month=None,
        current_month=date(2026, 10, 1),
        pack_code="previews_10",
        pack_expires_at=datetime(2027, 1, 22, 15, tzinfo=UTC),
    )
    assert confirmation_text(applied) == (
        "A Korner se le sumó el paquete +10 vistas previas, vence el 22 de enero."
    )


def test_apply_keys_both_writes_by_the_meegle_event(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.plans import pack_service, service

    calls: list[tuple[str, dict[str, Any]]] = []

    class _Plan:
        effective_month = date(2026, 10, 1)

    class _Pack:
        expires_at = NOW + timedelta(days=90)

    def set_plan(**kw: Any) -> _Plan:
        calls.append(("plan", kw))
        return _Plan()

    def add_pack(**kw: Any) -> _Pack:
        calls.append(("pack", kw))
        return _Pack()

    monkeypatch.setattr(service, "set_plan", set_plan)
    monkeypatch.setattr(pack_service, "add_pack", add_pack)
    monkeypatch.setattr(plan_request, "_business_name", lambda tenant: "Arepera La Nona")
    choice = AltaPlanChoice("plus", "videos_2", "", ACTOR, EVENT)
    applied = plan_request.apply_alta_plan(TENANT, choice, work_item_id=ITEM, now=NOW)
    (_, plan), (_, pack) = calls
    assert plan["idempotency_key"] == f"meegle:{EVENT}:plan"
    assert plan["source"] == "meegle_alta" and plan["meegle_work_item_id"] == ITEM
    assert plan["assigned_by"] == ACTOR
    assert plan["reason"] == f"Alta de cliente en Meegle (ítem {ITEM})"  # «Motivo» empty
    assert pack["idempotency_key"] == f"meegle:{EVENT}:pack"
    assert pack["pack"] == "videos_2" and pack["now"] == NOW
    assert applied.pack_expires_at == NOW + timedelta(days=90)
    assert applied.plan_name == "Plus"
