"""`business_read_limits` and `signup_invites.alta_uncapped_reads` against the live schema
(0130, m-24956180).

- `PostgresUncappedStore` round-trips the switch with its provenance, and a second write
  replaces the first (one row per business);
- RLS: a business reads only its own row; `qualify_app` can never write it (no business
  uncaps itself);
- «Plan ampliado» before the signup stores the flag on the invite.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from qualify_api.auth.invites import AltaPlanChoice, create_invite, set_pending_alta_plan
from qualify_api.tenancy.models import SignupInvite, Tenant
from qualify_api.vendors import uncapped

pytestmark = pytest.mark.db

ACTOR = "meegle:herwin@attitudefactory.co"


@pytest.fixture(autouse=True)
def _postgres() -> None:
    uncapped.configure_store(uncapped.PostgresUncappedStore())
    yield
    uncapped.configure_store(None)


def _tenant() -> UUID:
    tenant = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(id=tenant, name="Uncapped test", country="CO", timezone="UTC", currency="COP")
        )
    return tenant


def test_the_switch_round_trips_with_its_provenance() -> None:
    tenant = _tenant()
    assert uncapped.is_uncapped(tenant) is False  # no row
    uncapped.set_uncapped_reads(
        tenant, True, set_by=ACTOR, meegle_work_item_id=24936000, event_key="evt-1"
    )
    assert uncapped.is_uncapped(tenant) is True
    uncapped.set_uncapped_reads(tenant, False, set_by=ACTOR, event_key="evt-2")
    assert uncapped.is_uncapped(tenant) is False
    with admin_session() as session:
        rows = session.execute(
            text(
                "SELECT uncapped_reads, set_by, event_key, meegle_work_item_id, updated_at "
                "FROM business_read_limits WHERE tenant_id = :t"
            ),
            {"t": tenant},
        ).all()
    assert len(rows) == 1  # one row per business: the last write is the state
    (row,) = rows
    assert (row.uncapped_reads, row.set_by, row.event_key) == (False, ACTOR, "evt-2")
    assert row.updated_at > datetime.now(UTC) - timedelta(minutes=5)


def test_a_business_reads_only_its_own_row_and_can_never_write_one() -> None:
    mine, other = _tenant(), _tenant()
    uncapped.set_uncapped_reads(other, True, set_by=ACTOR)
    with tenant_session(mine) as session:
        seen = session.execute(text("SELECT tenant_id FROM business_read_limits")).all()
    assert seen == []
    assert uncapped.is_uncapped(mine) is False and uncapped.is_uncapped(other) is True
    with pytest.raises(DBAPIError), tenant_session(mine) as session:
        session.execute(
            text(
                "INSERT INTO business_read_limits (tenant_id, uncapped_reads, set_by) "
                "VALUES (:t, true, 'me')"
            ),
            {"t": mine},
        )


def test_plan_ampliado_before_the_signup_stores_the_flag_on_the_invite() -> None:
    work_item_id = int(uuid4().int % 10**12)
    email = f"hlrd1993+uncapped-{uuid4().hex[:8]}@gmail.com"
    create_invite(email, meegle_work_item_id=work_item_id)
    changed = set_pending_alta_plan(
        work_item_id, AltaPlanChoice(uncapped_reads=True, requested_by=ACTOR, event_key="evt")
    )
    assert changed == 1
    with admin_session() as session:
        flag = session.scalar(
            select(SignupInvite.alta_uncapped_reads).where(
                SignupInvite.meegle_work_item_id == work_item_id
            )
        )
    assert flag is True
