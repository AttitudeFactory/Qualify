"""monitored_media: the tenant's opt-in watchlist of content to sync comments for

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-14

Product decision (Herwin, 2026-08-14): sync/polling must NOT walk every Reel on a
connected account. The tenant explicitly checks which content to monitor from a
last-2-weeks candidate list, and the sync service (B2) only ever processes media_id
values marked here. Quantity limits per subscription plan may land later — this table
carries no such column yet; that stays out of scope until a real plan system exists.

Deliberately NOT reused: `threads`. A thread is created lazily by the sync process only
once a comment actually exists for a media, and carries `status` (community-team
workflow) and `last_message_at`/`last_inbound_at` (system-observed activity) — neither
of which is the same fact as "the tenant wants this media polled". A user can turn
monitoring off on a media whose thread is already `closed` with real messages in it, or
turn it on for a media that has zero comments so far; collapsing all three into one row
would make three independently-changing facts fight over one column. Kept as its own
table instead, same reasoning `oauth_scope.py`/`permission_capability.py` already give
for staying two files: "orthogonal axes, so a shared enum would be a false economy".

`is_monitored` is a column, not row presence/absence — toggling is an UPDATE of the
existing row, never a delete-then-reinsert, matching the "reconnect = UPDATE, never a
second row" idempotency discipline `connections/repository.py` already establishes for
`social_connections`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`. Duplicated per-migration
    # rather than shared, same as 0004 already does.
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
        "monitored_media",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("external_media_id", sa.Text(), nullable=False),
        # The toggle itself. Deliberately NOT nullable, NOT row-presence: see module
        # docstring — an UPDATE must be able to flip it without deleting history.
        sa.Column("is_monitored", sa.Boolean(), nullable=False),
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
        sa.UniqueConstraint(
            "connection_id", "external_media_id", name="uq_monitored_media_natural_key"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_monitored_media_conn_tenant",
        ),
    )
    op.create_index("ix_monitored_media_tenant", "monitored_media", ["tenant_id"])
    # The hot read path for B2's sync: "give me every media_id currently monitored for
    # this connection". Partial-looking but not partial (no WHERE) — is_monitored is
    # low-cardinality and always in the predicate, so a plain composite index is enough
    # at this scale; revisit only if EXPLAIN says otherwise.
    op.create_index(
        "ix_monitored_media_active", "monitored_media", ["connection_id", "is_monitored"]
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON monitored_media TO qualify_app;")
    op.execute("GRANT SELECT ON monitored_media TO qualify_admin;")
    _enable_tenant_rls("monitored_media")


def downgrade() -> None:
    op.drop_index("ix_monitored_media_active", table_name="monitored_media")
    op.drop_index("ix_monitored_media_tenant", table_name="monitored_media")
    op.drop_table("monitored_media")
