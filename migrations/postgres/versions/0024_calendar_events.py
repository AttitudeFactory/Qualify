"""calendar_events: the Planificador's own table (QUA-108)

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-25

A calendar event says one thing: "this POST goes out on this connection at this instant".
It carries planning state only. The content (assets, caption, script, approval) belongs to
the POST (QUA-109) and is read through `qualify_api.planner.post_reader.PostReader`, never
copied here.

## Why a new table instead of evolving `scheduled_posts` (0003)

Audited 2026-09-25 before writing this revision:

- `scheduled_posts` has ZERO consumers: no service, route, UI or test reads or writes it
  (only its ORM class exists), and `PublishService.start/start_many` never pass
  `publish_attempts.scheduled_post_id` (`staging.py:9` documents why). Local DB: 0 rows,
  and 0 of 4671 publish attempts reference it.
- Every NOT NULL column it has beyond scheduling (`media_object_key`,
  `media_content_type`, `media_product_type`, `caption`, `thumb_offset`) duplicates the
  POST, and its CHECK excludes IMAGE/CAROUSEL. Reusing it means relaxing five columns and
  a CHECK on a table whose name and comments keep saying "one media".
- A new table leaves `scheduled_posts` and `publish_attempts` byte-for-byte untouched, so
  nothing in Publicar can break. Retiring `scheduled_posts` is a separate, later decision.

## `post_id` has no foreign key — on purpose

The POST entity is QUA-109's, and it does not exist yet. Until it lands, events point at
whatever the active `PostReader` resolves (today, a read-only adapter over
`content_drafts`). The service validates the id through the reader before inserting. The
FK is added, additively, once QUA-109 decides where POSTs live.

## Link to the publish attempt

`publish_attempt_id` points at the latest attempt QUA-111 starts for this event, through
the `(id, tenant_id)` pair 0016 added to `publish_attempts`. The link lives on this table
so `publish_attempts` needs no new column.

## Status vocabulary

The same five values `scheduled_posts.ck_sched_status` already used. QUA-108 writes
`scheduled`/`cancelled`; `publishing`/`published`/`failed` are reserved for QUA-111.
`revision` increases on every reschedule; QUA-111 derives the idempotency key
`cal:{id}:{revision}` from it, so a rescheduled event can never reuse an old attempt.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`. Duplicated per-migration
    # rather than shared, same as every prior revision in this chain does.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def upgrade() -> None:
    op.create_table(
        "calendar_events",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        # The POST this event plans. No FK until QUA-109 exists (see module docstring).
        sa.Column("post_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        # The absolute instant. `scheduled_tz` is the IANA zone the operator planned in
        # (0003's A3 rule): a later change to `tenants.timezone` must not move the event.
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_tz", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("publish_attempt_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_cal_event_conn_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["publish_attempt_id", "tenant_id"],
            ["publish_attempts.id", "publish_attempts.tenant_id"],
            name="fk_cal_event_attempt_tenant",
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_cal_event_id_tenant"),
        sa.CheckConstraint(
            "status IN ('scheduled','cancelled','publishing','published','failed')",
            name="ck_cal_event_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_cal_event_revision"),
    )
    op.create_index("ix_cal_event_tenant", "calendar_events", ["tenant_id"])
    # The week view's query: one brand, one time window.
    op.create_index("ix_cal_event_brand_scheduled", "calendar_events", ["brand_id", "scheduled_at"])
    # "Which POSTs already have an event" — the Sin programar panel.
    op.create_index("ix_cal_event_post", "calendar_events", ["tenant_id", "post_id"])
    # QUA-111's only query: what is due? Partial, because cancelled/published rows
    # accumulate and must not slow down the hot path.
    op.execute(
        "CREATE INDEX ix_cal_event_due ON calendar_events (scheduled_at) "
        "WHERE status = 'scheduled';"
    )
    # DELETE only ever runs on a `cancelled` event (enforced in the service and in the
    # repository's WHERE): a withdrawn plan never reached Meta, so removing it loses nothing.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON calendar_events TO qualify_app;")
    op.execute("GRANT SELECT ON calendar_events TO qualify_admin;")
    _enable_tenant_rls("calendar_events")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cal_event_due;")
    op.drop_index("ix_cal_event_post", table_name="calendar_events")
    op.drop_index("ix_cal_event_brand_scheduled", table_name="calendar_events")
    op.drop_index("ix_cal_event_tenant", table_name="calendar_events")
    op.drop_table("calendar_events")
