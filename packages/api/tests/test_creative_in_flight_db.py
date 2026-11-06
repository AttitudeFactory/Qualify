"""`db`-marked test of the menu's «creating your publication» read (m-24973458) against
the real schema and RLS: true with a piece being made, false without one, false for
a dead run past the reaper's window, and never lit by another business's work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import update

from qualify_api.creative import models as creative
from qualify_api.creative.fsm import GENERATED
from qualify_api.creative.in_flight import ALIVE_MINUTES, generation_in_flight

from .test_creative_regenerate_db import _brand, _drafting_draft

pytestmark = pytest.mark.db

TENANT_BUSY = UUID("c0000000-0000-4000-8000-000000001041")
TENANT_IDLE = UUID("c0000000-0000-4000-8000-000000001042")


def _settle_all(tenant_id: UUID) -> None:
    """Leave the tenant with nothing in flight (the suite may run twice on one DB)."""
    with tenant_session(tenant_id) as session:
        session.execute(
            update(creative.ContentDraft)
            .where(creative.ContentDraft.status == "drafting")
            .values(status=GENERATED)
        )


def test_a_piece_being_made_lights_only_its_own_business() -> None:
    busy_brand = _brand(TENANT_BUSY)
    _brand(TENANT_IDLE)
    _settle_all(TENANT_BUSY)
    _settle_all(TENANT_IDLE)
    assert generation_in_flight(TENANT_BUSY) is False
    assert generation_in_flight(TENANT_IDLE) is False

    draft_id = _drafting_draft(TENANT_BUSY, busy_brand)
    assert generation_in_flight(TENANT_BUSY) is True
    # RLS: another business's generation never lights this one's menu
    assert generation_in_flight(TENANT_IDLE) is False

    # a run silent past the reaper's window is dead, not in progress
    later = datetime.now(UTC) + timedelta(minutes=ALIVE_MINUTES + 1)
    assert generation_in_flight(TENANT_BUSY, now=later) is False

    # it lands: the ring goes off
    with tenant_session(TENANT_BUSY) as session:
        session.execute(
            update(creative.ContentDraft)
            .where(creative.ContentDraft.id == draft_id)
            .values(status=GENERATED)
        )
    assert generation_in_flight(TENANT_BUSY) is False
