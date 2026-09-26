"""planner_tags + calendar_event_tags: planning labels for the Planificador (QUA-108)

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-25

Tags here are PLANNING labels ("Campaña octubre", "Lanzamiento") that the operator puts on
a calendar event to organise and filter the calendar. They belong to the Planificador,
not to the POST: whatever QUA-109 decides about describing content, these are untouched,
and a POST planned twice can carry different labels on each event. Decision recorded
2026-09-25 (tags live on the event).

- `planner_tags`: one row per label per tenant. The name is unique per tenant ignoring
  case (unique index on `lower(name)`), so "Promo" and "promo" are the same label.
  `color` is a palette key the UI maps to a colour; validated by a CHECK so the UI can
  never receive a value it cannot render.
- `calendar_event_tags`: the event ↔ tag link. Both composite FKs carry `tenant_id`, so an
  event can never be labelled with another tenant's tag (same R2 discipline as 0003).

Changing an event's tags does NOT bump `calendar_events.revision`: tags do not change
what or when QUA-111 publishes, so they must not invalidate its idempotency key.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

TAG_COLORS = ("teal", "blue", "violet", "pink", "amber", "green", "orange", "gray")


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
    colors = ", ".join(f"'{c}'" for c in TAG_COLORS)
    op.create_table(
        "planner_tags",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_planner_tag_id_tenant"),
        sa.CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 40", name="ck_planner_tag_name"),
        sa.CheckConstraint(f"color IN ({colors})", name="ck_planner_tag_color"),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_planner_tag_tenant_name ON planner_tags (tenant_id, lower(name));"
    )
    # DELETE: removing a label (its links go first, in the same transaction).
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON planner_tags TO qualify_app;")
    op.execute("GRANT SELECT ON planner_tags TO qualify_admin;")
    _enable_tenant_rls("planner_tags")

    op.create_table(
        "calendar_event_tags",
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("event_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", PGUUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "tag_id", name="pk_calendar_event_tags"),
        sa.ForeignKeyConstraint(
            ["event_id", "tenant_id"],
            ["calendar_events.id", "calendar_events.tenant_id"],
            name="fk_cal_event_tag_event_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id", "tenant_id"],
            ["planner_tags.id", "planner_tags.tenant_id"],
            name="fk_cal_event_tag_tag_tenant",
        ),
    )
    op.create_index("ix_cal_event_tag_tag", "calendar_event_tags", ["tenant_id", "tag_id"])
    # DELETE is granted here (and only here): un-labelling an event removes a link row.
    op.execute("GRANT SELECT, INSERT, DELETE ON calendar_event_tags TO qualify_app;")
    op.execute("GRANT SELECT ON calendar_event_tags TO qualify_admin;")
    _enable_tenant_rls("calendar_event_tags")


def downgrade() -> None:
    op.drop_index("ix_cal_event_tag_tag", table_name="calendar_event_tags")
    op.drop_table("calendar_event_tags")
    op.execute("DROP INDEX IF EXISTS uq_planner_tag_tenant_name;")
    op.drop_table("planner_tags")
