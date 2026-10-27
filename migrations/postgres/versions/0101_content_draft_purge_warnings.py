"""content_draft_purge_warnings: one email warning per piece and deadline (m-24842840)

Revision ID: 0101
Revises: 0100
Create Date: 2026-10-26

Records successful warnings per piece, deadline, stage and confirmed recipient. A failed
send writes no success marker; its frozen batch remains pending. Successful recipients
are not repeated when another fails.
A frozen outbox is committed before Resend is called, so a response timeout and new
pieces cannot change a retry's payload or provider key. New pieces wait for the next
pass while a batch is pending. A stale/protected/renewed batch is cancelled as a whole;
its payload is never edited. Provider idempotency is bounded by the provider's retention
window (24 h). Retries stop at 23 h and retain their identities for operational review,
not an indefinite exactly-once guarantee. Definitive rejections do not consume this window.
Append-only warning ledger and column-restricted outbox updates both have tenant RLS.
Downgrade drops only these two retention-email tables.
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

    _create_warning_batches()


def _create_warning_batches() -> None:
    """Additive outbox DDL, reusable for a dev DB that already applied the old 0101."""
    op.create_table(
        "content_draft_warning_batches",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("recipient", sa.Text(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("first_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_id", sa.Text(), nullable=True),
        sa.Column("needs_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_warning_batch_key"),
        sa.CheckConstraint("stage IN ('window_15d', 'last_day')", name="ck_warning_batch_stage"),
    )
    op.create_index("ix_warning_batches_tenant", "content_draft_warning_batches", ["tenant_id"])
    op.create_index(
        "uq_warning_batches_pending",
        "content_draft_warning_batches",
        ["tenant_id", "brand_id", "recipient", "stage"],
        unique=True,
        postgresql_where=sa.text(
            "sent_at IS NULL AND cancelled_at IS NULL AND needs_review_at IS NULL"
        ),
    )
    op.execute("GRANT SELECT, INSERT ON content_draft_warning_batches TO qualify_app;")
    op.execute(
        "GRANT UPDATE (first_attempt_at, sent_at, cancelled_at, provider_id, needs_review_at) "
        "ON content_draft_warning_batches TO qualify_app;"
    )
    op.execute("GRANT SELECT ON content_draft_warning_batches TO qualify_admin;")
    _enable_tenant_rls("content_draft_warning_batches")


def downgrade() -> None:
    op.drop_table("content_draft_warning_batches")
    op.drop_table("content_draft_purge_warnings")
