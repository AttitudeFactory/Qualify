"""`db` tests for VE-12 RA5 (m-24921060, `referentes.reel_window_retention`) against the
live schema: the production discovery (`tenants_with_part_drafts`, `admin_session`)
returns business ids only — those with a part draft 30+ days old whose files are still
stored — and `_part_drafts` under `tenant_session` sees only its own business's due
parts (never a parent, a young part or an already-purged one).

Provisioning through `admin_session`; drafts through `tenant_session`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.referentes import reel_window_retention as wr
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

NOW = datetime.now(UTC)


def _world() -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant,
                name="VE-12 windows",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="VE-12 brand"))
    return tenant, brand


def _draft(
    tenant: UUID,
    brand: UUID,
    *,
    days_ago: float,
    parent: UUID | None = None,
    part: int | None = None,
    purged: bool = False,
) -> UUID:
    draft_id = uuid4()
    with tenant_session(tenant) as session:
        brief = session.scalar(
            text(
                "INSERT INTO content_briefs (tenant_id, brand_id, objective, topic, platform, "
                "format, intent, content_type, image_route, kind) VALUES (:t, :b, 'o', 't', "
                "'instagram', 'reel', 'i', 'video', 'r', :k) RETURNING id"
            ),
            {"t": tenant, "b": brand, "k": "clip" if parent else "shot_video"},
        )
        created = NOW - timedelta(days=days_ago)
        session.execute(
            text(
                "INSERT INTO content_drafts (id, tenant_id, brief_id, brand_id, status, "
                "parent_draft_id, part_index, created_at, media_purged_at) VALUES "
                "(:d, :t, :brief, :b, 'drafting', :p, :i, :c, :m)"
            ),
            {
                "d": draft_id,
                "t": tenant,
                "brief": brief,
                "b": brand,
                "p": parent,
                "i": part,
                "c": created,
                "m": NOW if purged else None,
            },
        )
    return draft_id


def test_discovery_and_the_tenant_read_see_only_due_part_drafts() -> None:
    a, brand_a = _world()
    a_parent = _draft(a, brand_a, days_ago=40)
    a_due = _draft(a, brand_a, days_ago=31, parent=a_parent, part=1)
    _draft(a, brand_a, days_ago=29, parent=a_parent, part=2)  # too young
    _draft(a, brand_a, days_ago=31, parent=a_parent, part=3, purged=True)  # files gone

    b, brand_b = _world()
    b_parent = _draft(b, brand_b, days_ago=40)
    b_due = _draft(b, brand_b, days_ago=31, parent=b_parent, part=1)

    c, brand_c = _world()  # only a parent, a young part and a purged part: nothing due
    c_parent = _draft(c, brand_c, days_ago=40)
    _draft(c, brand_c, days_ago=29, parent=c_parent, part=1)
    _draft(c, brand_c, days_ago=31, parent=c_parent, part=2, purged=True)

    found = wr.tenants_with_part_drafts(NOW)
    assert all(isinstance(t, UUID) for t in found)  # ids only
    assert a in found and b in found and c not in found

    cutoff = NOW - wr.WINDOW_RETENTION
    with tenant_session(a) as session:
        assert wr._part_drafts(session, cutoff) == [a_due]
    with tenant_session(b) as session:
        assert wr._part_drafts(session, cutoff) == [b_due]
    with tenant_session(c) as session:
        assert wr._part_drafts(session, cutoff) == []
