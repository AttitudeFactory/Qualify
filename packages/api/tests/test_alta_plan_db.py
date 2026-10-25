"""`db`-marked (m-24852131): the plan and pack of an «Alta de cliente» against Postgres.

- 0097: `create_invite(alta_plan=…)` stores the choice; spending the invite stamps the
  business it became (`registered_tenant_id`);
- an Alta without plan: the business registers on Básico, no assignment, no pack;
- an Alta with Plus + «+2 videos»: right after `register_business` the business is on Plus
  (with who / why / Meegle item in the history) and holds the pack, ending registration
  + 90 days;
- the same Meegle event applied twice applies once; a NEW event (the node completed
  again) adds the pack once more;
- «Plan ampliado» before the signup replaces the choice waiting on the invite.

Who may write plans and packs (RLS + grants: the owner can neither change their plan nor
create or read assignments and payments) is proven by `test_plans_db.py` and
`test_creation_packs_db.py`; this file only drives the Meegle path into those services.
The root `conftest.py` migrates the test database to head before any `db` test runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from sqlalchemy import select, text

from qualify_api.auth import FakeAuthProvider, authorize_signup, register_business
from qualify_api.auth import service as auth_service
from qualify_api.auth.invites import (
    AltaPlanChoice,
    create_invite,
    registered_tenant_for_work_item,
    set_pending_alta_plan,
)
from qualify_api.meegle.plan_request import apply_alta_plan
from qualify_api.plans.models import CreationPack, CreationPayment, SubscriptionPlanAssignment
from qualify_api.plans.notify import RecordingTeamNotifier
from qualify_api.tenancy.models import SignupInvite

pytestmark = pytest.mark.db

ACTOR = "meegle:herwin@attitudefactory.co"


def _email() -> str:
    return f"hlrd1993+alta-plan-{uuid4().hex[:8]}@gmail.com"


def _work_item_id() -> int:
    return int(uuid4().int % 10**12)


@pytest.fixture
def applied(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, UUID, AltaPlanChoice]]:
    """The registration path, with Meegle's write-back off and a recording notifier."""
    calls: list[tuple[int, UUID, AltaPlanChoice]] = []
    monkeypatch.setattr(auth_service, "notify_meegle_registered", lambda item, tenant: None)

    def apply(work_item_id: int, tenant_id: UUID, choice: AltaPlanChoice) -> None:
        calls.append((work_item_id, tenant_id, choice))
        apply_alta_plan(
            tenant_id, choice, work_item_id=work_item_id, notifier=RecordingTeamNotifier()
        )

    monkeypatch.setattr(auth_service, "apply_alta_plan_on_register", apply)
    return calls


def _register(email: str, token: str) -> UUID:
    return register_business(
        FakeAuthProvider(),
        business_name=f"Arepera {uuid4().hex[:4]}",
        email=email,
        password="correct-horse-9",
        country="CO",
        timezone="America/Bogota",
        currency="COP",
        invite_id=authorize_signup(email, token),
    ).tenant_id


def _plan_rows(tenant_id: UUID) -> list[SubscriptionPlanAssignment]:
    with admin_session() as session:
        sid = session.scalar(
            text("SELECT subscription_id FROM tenants WHERE id = :id"), {"id": tenant_id}
        )
        if sid is None:
            return []
        rows = list(
            session.scalars(
                select(SubscriptionPlanAssignment).where(
                    SubscriptionPlanAssignment.subscription_id == sid
                )
            )
        )
        session.expunge_all()
        return rows


def _packs(tenant_id: UUID) -> list[CreationPack]:
    with admin_session() as session:
        rows = list(
            session.scalars(select(CreationPack).where(CreationPack.tenant_id == tenant_id))
        )
        session.expunge_all()
        return rows


def _business_plan(tenant_id: UUID) -> str | None:
    with admin_session() as session:
        return session.scalar(
            text("SELECT plan_code FROM business_plans WHERE tenant_id = :id"), {"id": tenant_id}
        )


def test_an_alta_without_plan_registers_on_basico_with_nothing_written(
    applied: list,
) -> None:
    item = _work_item_id()
    invite = create_invite(_email(), meegle_work_item_id=item)
    tenant_id = _register(invite.email, invite.token)
    assert applied == []  # nothing chosen: nothing to apply
    assert _plan_rows(tenant_id) == [] and _packs(tenant_id) == []
    assert _business_plan(tenant_id) is None  # no row = the catalog's default, Básico
    assert registered_tenant_for_work_item(item) == tenant_id


def test_plus_and_a_pack_apply_at_signup_with_provenance(applied: list) -> None:
    item = _work_item_id()
    event = f"evt-{uuid4().hex}"
    choice = AltaPlanChoice("plus", "videos_2", "Pagó Plus por Nequi", ACTOR, event)
    invite = create_invite(_email(), meegle_work_item_id=item, alta_plan=choice)
    with admin_session() as session:
        row = session.scalar(select(SignupInvite).where(SignupInvite.id == invite.id))
        assert row is not None
        assert (row.alta_plan_code, row.alta_pack_code, row.alta_event_key) == (
            "plus",
            "videos_2",
            event,
        )
    before = datetime.now(UTC)
    tenant_id = _register(invite.email, invite.token)
    after = datetime.now(UTC)

    assert [(c[0], c[1]) for c in applied] == [(item, tenant_id)]
    (assignment,) = _plan_rows(tenant_id)
    assert assignment.plan_code == "plus"
    assert assignment.source == "meegle_alta"
    assert assignment.meegle_work_item_id == item
    assert assignment.reason == "Pagó Plus por Nequi"
    assert assignment.assigned_by == ACTOR
    assert assignment.idempotency_key == f"meegle:{event}:plan"
    assert _business_plan(tenant_id) == "plus"

    (pack,) = _packs(tenant_id)
    assert (pack.pack_code, pack.videos, pack.source) == ("videos_2", 2, "meegle_alta")
    assert pack.meegle_work_item_id == item
    assert before + timedelta(days=90) <= pack.expires_at <= after + timedelta(days=90)
    assert pack.idempotency_key == f"meegle:{event}:pack"


def test_the_same_event_applies_once_and_a_new_event_adds_the_pack_again(
    applied: list,
) -> None:
    item = _work_item_id()
    invite = create_invite(_email(), meegle_work_item_id=item)
    tenant_id = _register(invite.email, invite.token)
    notifier = RecordingTeamNotifier()
    first = AltaPlanChoice("pro", "creations_20", "", ACTOR, f"evt-{uuid4().hex}")
    for _ in range(2):  # a webhook retry of the same event
        apply_alta_plan(tenant_id, first, work_item_id=item, notifier=notifier)
    assert len(_plan_rows(tenant_id)) == 1 and len(_packs(tenant_id)) == 1
    with admin_session() as session:
        paid = session.scalars(
            select(CreationPayment).where(CreationPayment.tenant_id == tenant_id)
        ).all()
        assert len(paid) == 1

    again = AltaPlanChoice("pro", "creations_20", "", ACTOR, f"evt-{uuid4().hex}")
    apply_alta_plan(tenant_id, again, work_item_id=item, notifier=notifier)
    assert len(_plan_rows(tenant_id)) == 1  # already on Pro: no new assignment
    assert len(_packs(tenant_id)) == 2  # the node completed again adds the pack once more


def test_plan_ampliado_before_the_signup_replaces_the_waiting_choice(applied: list) -> None:
    item = _work_item_id()
    first, second = f"evt-{uuid4().hex}", f"evt-{uuid4().hex}"  # Meegle event ids are unique
    invite = create_invite(
        _email(),
        meegle_work_item_id=item,
        alta_plan=AltaPlanChoice("plus", None, "", ACTOR, first),
    )
    assert registered_tenant_for_work_item(item) is None
    assert set_pending_alta_plan(item, AltaPlanChoice(None, "previews_10", "", ACTOR, second))
    tenant_id = _register(invite.email, invite.token)
    assert _plan_rows(tenant_id) == []  # the plan was replaced by the pack-only choice
    (pack,) = _packs(tenant_id)
    assert pack.pack_code == "previews_10"
    assert pack.idempotency_key == f"meegle:{second}:pack"
    # and once spent, nothing waits any more
    late = AltaPlanChoice("pro", None, "", ACTOR, f"evt-{uuid4().hex}")
    assert set_pending_alta_plan(item, late) == 0
