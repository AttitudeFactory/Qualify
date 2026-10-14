"""support_requests: "Pedir ayuda 1:1" from inside /connections (QUA-202)

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-14

A non-technical operator who cannot get an Instagram account connected asks a person for
help from the screen. One row per request, owned by the tenant (standard RLS policy with
the `NULLIF` of 0001 — R7), carrying the contact the operator typed, an optional message
and a small JSON `context` with what the screen knew about the failed attempt: the outcome
code and the two R9(e.1) counts, never a Page id, a username or a token.

`status` belongs to the support team (`open` → `contacted` → `closed`); `notified_at` is
set once the global support channel accepted the notification, so a ticket nobody was
told about is distinguishable from one that was. `qualify_app` gets SELECT, INSERT and
UPDATE: it creates the row and stamps `notified_at`; nothing is ever deleted by the app.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None

_TABLE = "support_requests"


def _enable_tenant_rls(table: str) -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "requested_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("topic", sa.String(), nullable=False),
        sa.Column("contact_email", sa.Text(), nullable=False),
        sa.Column("contact_whatsapp", sa.Text(), nullable=False, server_default=""),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("context", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "topic IN ('connect_accounts','other')", name="ck_support_requests_topic"
        ),
        sa.CheckConstraint(
            "status IN ('open','contacted','closed')", name="ck_support_requests_status"
        ),
        sa.CheckConstraint("contact_email <> ''", name="ck_support_requests_contact_email"),
    )
    op.create_index("ix_support_requests_tenant_created", _TABLE, ["tenant_id", "created_at"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {_TABLE} TO qualify_app;")
    _enable_tenant_rls(_TABLE)


def downgrade() -> None:
    op.drop_index("ix_support_requests_tenant_created", table_name=_TABLE)
    op.drop_table(_TABLE)
