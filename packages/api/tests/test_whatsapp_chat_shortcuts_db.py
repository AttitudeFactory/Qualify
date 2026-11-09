"""m-24945889 against the compose Postgres (migration 0140): the weekly promotion's one
row per business and its RLS, the ADR 39 hold it gives a piece, the number's map point
CHECK, and the in-flight copies the outbound purge keeps.

Seeding reuses `test_creative_retention_db`'s helpers (tenant, brand, connection, piece).
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from packages.api.tests.test_creative_retention_db import (
    NOW,
    TENANT_A,
    TENANT_B,
    RecordingGate,
    _piece,
    _provision,
    _purged_at,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from qualify_api.creative.retention import (
    RetentionState,
    piece_prefix,
    purge_expired_pieces,
    read_facts,
    retention_of,
)
from qualify_api.whatsapp.models import (
    WhatsAppOutboxItem,
    WhatsAppPhoneNumber,
    WhatsAppWeeklyPromotion,
)
from qualify_api.whatsapp.outbound_purge import in_flight_keys
from qualify_api.whatsapp.promotions import PostgresPromotionRepository

pytestmark = pytest.mark.db


def test_marking_another_piece_replaces_the_businesss_promotion() -> None:
    brand, user, _ = _provision(TENANT_A, "A")
    first = _piece(TENANT_A, brand, generated_days_ago=1)
    second = _piece(TENANT_A, brand, generated_days_ago=1)
    repo = PostgresPromotionRepository()
    repo.mark(tenant_id=TENANT_A, brand_id=brand, draft_id=first, by=user, at=NOW)
    repo.mark(tenant_id=TENANT_A, brand_id=brand, draft_id=second, by=user, at=NOW)
    with tenant_session(TENANT_A) as session:
        rows = session.scalars(
            select(WhatsAppWeeklyPromotion.draft_id).where(
                WhatsAppWeeklyPromotion.brand_id == brand
            )
        ).all()
    assert rows == [second]
    assert repo.get(tenant_id=TENANT_B, brand_id=brand) is None  # RLS
    assert repo.unmark(tenant_id=TENANT_B, brand_id=brand) is False
    assert repo.unmark(tenant_id=TENANT_A, brand_id=brand) is True


def test_a_promotion_cannot_point_at_another_tenants_piece() -> None:
    brand_a, _, _ = _provision(TENANT_A, "A")
    brand_b, _, _ = _provision(TENANT_B, "B")
    piece_b = _piece(TENANT_B, brand_b, generated_days_ago=1)
    with pytest.raises(DBAPIError), tenant_session(TENANT_A) as session:
        session.add(WhatsAppWeeklyPromotion(tenant_id=TENANT_A, brand_id=brand_a, draft_id=piece_b))
        session.flush()


def test_a_marked_piece_is_never_a_purge_candidate() -> None:
    brand, user, _ = _provision(TENANT_A, "A")
    promoted = _piece(TENANT_A, brand, generated_days_ago=300)
    PostgresPromotionRepository().mark(
        tenant_id=TENANT_A, brand_id=brand, draft_id=promoted, by=user, at=NOW
    )
    with tenant_session(TENANT_A) as session:
        assert read_facts(session, TENANT_A, [promoted])[promoted].held is True
        verdict = retention_of(session, TENANT_A, [promoted], NOW)[promoted]
    assert verdict.state is RetentionState.HELD
    gate = RecordingGate()
    purge_expired_pieces(tenant_id=TENANT_A, gate=gate, now=NOW, execute=True)
    assert piece_prefix(TENANT_A, promoted) not in {p for _, p, _ in gate.calls}
    assert _purged_at(TENANT_A, promoted) is None


@pytest.mark.parametrize(
    ("lat", "lng", "ok"),
    [(7.89, -72.5, True), (None, None, True), (91, 0, False), (0, 181, False), (7.89, None, False)],
)
def test_the_number_point_is_both_or_neither_and_in_range(lat, lng, ok) -> None:
    brand, _, conn = _provision(TENANT_A, "A")

    def write() -> None:
        with tenant_session(TENANT_A) as session:
            session.add(
                WhatsAppPhoneNumber(
                    tenant_id=TENANT_A,
                    brand_id=brand,
                    connection_id=conn,
                    waba_id="waba",
                    phone_number_id=f"pn-{uuid4()}",
                    display_phone_number="1555",
                    location_latitude=lat,
                    location_longitude=lng,
                )
            )
            session.flush()

    if ok:
        write()
    else:
        with pytest.raises(DBAPIError):
            write()


def test_the_purge_keeps_the_copies_of_queued_rows() -> None:
    _, user, conn = _provision(TENANT_A, "A")
    queued = f"t/{TENANT_A}/whatsapp/outbound/{conn}/{uuid4()}.jpg"
    sent = f"t/{TENANT_A}/whatsapp/outbound/{conn}/{uuid4()}.jpg"
    with tenant_session(TENANT_A) as session:
        for status, key in (("pending", queued), ("sent", sent)):
            session.add(
                WhatsAppOutboxItem(
                    tenant_id=TENANT_A,
                    connection_id=conn,
                    thread_id=None,
                    kind="reply",
                    payload={"messaging_product": "whatsapp", "to": "57", "type": "image"},
                    status=status,
                    attachment={"kind": "photo", "object_key": key},
                    created_at=NOW - timedelta(days=3),
                )
            )
    keys = in_flight_keys(TENANT_A)
    assert queued in keys and sent not in keys
    assert in_flight_keys(TENANT_B).isdisjoint({queued, sent})
