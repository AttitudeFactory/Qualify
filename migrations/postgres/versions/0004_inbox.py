"""inbox: threads + messages, Postgres only (QUA-20, ADR 22d)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-29

Architect sign-off 2026-07-29, with two conditions encoded here:

B1: `UNIQUE(connection_id, external_message_id)` carries NO `tenant_id`. Adding it would state
    a WEAKER invariant — implying the same `external_message_id` could coexist under the same
    connection in another tenant, which the composite FK already makes impossible. The
    `tenant_id` denormalization exists for RLS, not for uniqueness; they are separate jobs.
B2: The messaging window derives from `last_inbound_at`, NOT `last_message_at`. The 24 h window
    is opened by the INBOUND message (`overview.md:178`) and replying does NOT extend it.
    Deriving from a column that includes outbound messages would reopen a window Meta considers
    closed, letting the system permit sends the platform rejects — or accepts and counts as a
    policy violation. `window_expires_at` is deliberately NOT a column: a materialized copy of
    (base + policy) can go stale, and its stale failure mode is exactly "sent outside the
    window", which this ticket requires the system to prevent.

Nullability here is derived from the QUA-67 contract (`qualify_shared.social.ig_shapes`), not
guessed. Two consequences that look surprising and are not:
  - `posted_at` is NULLABLE because the contract marks the comment `timestamp` as
    `Presence.IF_REQUESTED` — it can legitimately be absent. `ingested_at` is always known, so
    ordering falls back to it rather than to a fabricated timestamp.
  - `author_external_id`/`author_username` are NULLABLE because `from`/`username` are
    `Presence.REQUIRES_PERMISSION` (`instagram_manage_comments`) and absent without it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
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
        "threads",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("external_thread_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        # Nullable from day one: the assignment UI is parking-lot, but retrofitting the column
        # later would mean a migration on a table that by then holds real conversations.
        sa.Column(
            "assigned_agent_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        # Inbox ordering only. NEVER the basis of the messaging window — see B2 above.
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        # The window's one true base. NULL means "no window ever opened", which is NOT the same
        # as "window expired" (R10: a zero/absent value has several distinct causes and they
        # must not be collapsed).
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "connection_id", "channel", "external_thread_id", name="uq_thread_natural_key"
        ),
        # Anti-drift target for the composite FK from `messages` (same shape as R2).
        sa.UniqueConstraint("id", "tenant_id", name="uq_thread_id_tenant"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_thread_conn_tenant",
        ),
        sa.CheckConstraint("channel IN ('comment','dm')", name="ck_thread_channel"),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_thread_status"),
    )
    op.create_index("ix_thread_tenant", "threads", ["tenant_id"])
    op.create_index("ix_thread_inbox_order", "threads", ["tenant_id", "last_message_at"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON threads TO qualify_app;")
    op.execute("GRANT SELECT ON threads TO qualify_admin;")
    _enable_tenant_rls("threads")

    op.create_table(
        "messages",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("external_message_id", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        # An IGSID: stable per app/account, NOT a portable user identity
        # (`qualify_shared.social.ig_shapes.IGSID_IS_PORTABLE_IDENTITY is False`). Do not join
        # it against any other person identifier — that is the decision this comment protects.
        sa.Column("author_external_id", sa.Text(), nullable=True),
        sa.Column("author_username", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        # Nullable by contract, not by oversight — see the module docstring.
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("raw_payload_r2_key", sa.Text(), nullable=True),
        # Which version of the QUA-67 contract parsed this row — provenance, so a re-parse can
        # tell what shape it was written under.
        sa.Column("shape_version", sa.Text(), nullable=False),
        # THE dedup guarantee (decision 2026-07-28): a Postgres constraint plus an idempotent
        # upsert, deliberately not a Redis SETNX. At one tenant polling on a minutes cadence
        # with no concurrent webhook, a constraint covers it without a second dependency.
        sa.UniqueConstraint("connection_id", "external_message_id", name="uq_message_external_id"),
        sa.ForeignKeyConstraint(
            ["thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_message_thread_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_message_conn_tenant",
        ),
        sa.CheckConstraint("direction IN ('inbound','outbound')", name="ck_message_direction"),
    )
    op.create_index("ix_message_tenant", "messages", ["tenant_id"])
    op.create_index("ix_message_thread", "messages", ["thread_id", "posted_at"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON messages TO qualify_app;")
    op.execute("GRANT SELECT ON messages TO qualify_admin;")
    _enable_tenant_rls("messages")


def downgrade() -> None:
    op.drop_index("ix_message_thread", table_name="messages")
    op.drop_index("ix_message_tenant", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_thread_inbox_order", table_name="threads")
    op.drop_index("ix_thread_tenant", table_name="threads")
    op.drop_table("threads")
