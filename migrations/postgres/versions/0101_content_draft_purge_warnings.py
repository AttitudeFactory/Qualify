"""content_draft_purge_warnings: one email warning per piece and deadline (m-24842840)

Revision ID: 0101
Revises: 0100
Create Date: 2026-10-26

Records successful warnings per piece, deadline, stage and confirmed recipient. A failed
send writes nothing; successful recipients are not repeated when another fails.
Append-only application grants and tenant RLS; downgrade drops the warning ledger.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0101"
down_revision = "0100"
branch_labels = None
depends_on = None


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
        "content_draft_purge_warnings",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("content_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("recipient", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.CheckConstraint("stage IN ('window_15d', 'last_day')", name="ck_purge_warning_stage"),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "draft_id", "deadline", "recipient", "stage", name="uq_purge_warnings_draft_deadline"
        ),
    )
    op.create_index("ix_purge_warnings_tenant", "content_draft_purge_warnings", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT ON content_draft_purge_warnings TO qualify_app;")
    op.execute("GRANT SELECT ON content_draft_purge_warnings TO qualify_admin;")
    _enable_tenant_rls("content_draft_purge_warnings")


def downgrade() -> None:
    op.drop_table("content_draft_purge_warnings")
