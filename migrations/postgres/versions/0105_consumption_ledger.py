"""consumption_ledger: unified consumption ledger for Anthropic, BytePlus,
and ScrapeCreators (m-24823681)

Revision ID: 0105
Revises: 0104
Create Date: 2026-10-27

One tenant-scoped row per billable operation (an Anthropic `messages.create`,
a ScrapeCreators credit, a BytePlus generation), so the cost of an «Alta de
cliente» (its Meegle work item) can be summarized by tenant, brand and node.
`pricing_table_version` is the provenance marker: every `cost_usd` is
reproducible against the price sheet that produced it (the creative
`JsonPricingTable`, `pricing_data/<version>.json`). RLS is enforced the same
way as every other tenant table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0105"
down_revision = "0104"
branch_labels = None
depends_on = None

_TABLE = "consumption_ledger"


def _enable_tenant_rls(table: str) -> None:
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
        sa.Column(
            "tenant_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "brand_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("meegle_work_item_id", sa.BigInteger(), nullable=True),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "cache_creation_tokens",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False),
        # Provenance: the price sheet the cost was computed against (e.g. "v7"),
        # so a ledger row stays reproducible after a vendor reprices.
        sa.Column("pricing_table_version", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 "
            "AND cache_read_tokens >= 0 AND cache_creation_tokens >= 0",
            name="ck_consumption_tokens_non_negative",
        ),
        sa.CheckConstraint("cost_usd >= 0", name="ck_consumption_cost_non_negative"),
    )
    op.create_index("ix_consumption_ledger_tenant", _TABLE, ["tenant_id"])
    op.create_index("ix_consumption_ledger_work_item", _TABLE, ["meegle_work_item_id"])
    op.create_index("ix_consumption_ledger_operation", _TABLE, ["operation"])

    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {_TABLE} TO qualify_app;")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE} TO qualify_admin;")
    _enable_tenant_rls(_TABLE)


def downgrade() -> None:
    op.drop_index("ix_consumption_ledger_operation", table_name=_TABLE)
    op.drop_index("ix_consumption_ledger_work_item", table_name=_TABLE)
    op.drop_index("ix_consumption_ledger_tenant", table_name=_TABLE)
    op.drop_table(_TABLE)
