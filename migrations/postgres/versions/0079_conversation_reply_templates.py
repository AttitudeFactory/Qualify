"""conversation_reply_templates: the library of text templates an agent picks from the
Conversaciones composer (m-24789472, PR 1)

Revision ID: 0079
Revises: 0078
Create Date: 2026-10-22

One library per connected account (a `social_connections` row): «Gracias por escribirnos»,
«Te comparto el precio…», and whatever the business adds. A template is only TEXT the
person starts from — picking or rendering one writes nothing anywhere else. It reaches the
counterpart only through the existing reply flow (`ConversationService.reply_text` →
`conversation_outbox` with a `HumanApproval`), so nothing here touches the queue and
nothing here talks to Meta.

Two tables, on purpose:

- `conversation_reply_templates` — the templates. `position` orders the picker (no UNIQUE:
  a reorder rewrites every position in one transaction and a unique index would trip on
  the intermediate states). `default_key` marks a row Qualify seeded (`greeting`,
  `price`, `hours`, `catalog`); a person may edit or delete it like any other.
  `uq_conv_reply_template_default` (partial: only seeded rows) makes a second copy of the
  same default for the same account impossible, so seeding is `INSERT … ON CONFLICT DO
  NOTHING` and two concurrent first opens cannot duplicate anything.
- `conversation_reply_template_seeds` — one row per account whose library was seeded,
  with the `defaults_version` it got. It is the memory that the defaults were ALREADY
  given: a person who deletes every default does not get them back on the next open
  (the unique index alone cannot say that — a deleted row leaves no trace). The seed
  marker is written with `ON CONFLICT DO NOTHING` in the same transaction as the default
  rows, and only the transaction that inserted the marker inserts the defaults; a second
  concurrent first open waits on the marker's primary key, finds it, and seeds nothing.
  The marker row is also the per-account lock that create and reorder take (`SELECT …
  FOR UPDATE`) so the per-account cap cannot be overrun by two concurrent creates.

Lengths are CHECKed as the service validates them (title 1–60, body 1–1000 characters
after trimming): the body is one Instagram DM (1000 characters, the channel's limit), so a
template never silently becomes two messages; a person who writes more in the composer
still can — `reply_text` splits it.

The composite FKs follow R2 and CASCADE from the account: a library has no meaning without
its account. `created_by_user_id` / `updated_by_user_id` say who wrote it (NULL for the
seeded defaults).

**Grants.** `qualify_app`: SELECT, INSERT, UPDATE, DELETE on the templates (a person
deletes a template for real — it explains no send: the sent text lives in the outbox);
SELECT, INSERT, UPDATE on the seeds (UPDATE because `FOR UPDATE` needs it, and a future
`defaults_version` bump). Nothing for `qualify_webhook_worker` nor `qualify_admin`.
Standard RLS (R7) on both.

**Downgrade** drops both tables; no other row is touched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None

_TITLE_MAX = 60
_BODY_MAX = 1000


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
        "conversation_reply_templates",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        # The short label of the picker; `body` is what lands in the composer.
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        # Set only on a row Qualify seeded (`greeting`, `price`, `hours`, `catalog`).
        sa.Column("default_key", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "updated_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
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
            name="fk_conv_reply_template_conn_tenant",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            f"char_length(btrim(title)) BETWEEN 1 AND {_TITLE_MAX}",
            name="ck_conv_reply_template_title",
        ),
        sa.CheckConstraint(
            f"char_length(btrim(body)) BETWEEN 1 AND {_BODY_MAX}",
            name="ck_conv_reply_template_body",
        ),
        sa.CheckConstraint("position >= 0", name="ck_conv_reply_template_position"),
        sa.CheckConstraint(
            "default_key IS NULL OR char_length(default_key) > 0",
            name="ck_conv_reply_template_default_key",
        ),
    )
    op.create_index("ix_conv_reply_template_tenant", "conversation_reply_templates", ["tenant_id"])
    # The picker: one account's templates in order.
    op.create_index(
        "ix_conv_reply_template_order",
        "conversation_reply_templates",
        ["connection_id", "position"],
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_conv_reply_template_default ON conversation_reply_templates "
        "(tenant_id, connection_id, default_key) WHERE default_key IS NOT NULL;"
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON conversation_reply_templates TO qualify_app;"
    )
    _enable_tenant_rls("conversation_reply_templates")

    op.create_table(
        "conversation_reply_template_seeds",
        sa.Column("connection_id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        # Which set of defaults this account received (`templates.DEFAULTS_VERSION`).
        sa.Column("defaults_version", sa.Integer(), nullable=False),
        sa.Column(
            "seeded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_conv_reply_template_seed_conn_tenant",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("defaults_version >= 1", name="ck_conv_reply_template_seed_version"),
    )
    op.create_index(
        "ix_conv_reply_template_seed_tenant", "conversation_reply_template_seeds", ["tenant_id"]
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON conversation_reply_template_seeds TO qualify_app;")
    # Deliberately nothing for qualify_webhook_worker or qualify_admin.
    _enable_tenant_rls("conversation_reply_template_seeds")


def downgrade() -> None:
    op.drop_index(
        "ix_conv_reply_template_seed_tenant", table_name="conversation_reply_template_seeds"
    )
    op.drop_table("conversation_reply_template_seeds")
    op.execute("DROP INDEX IF EXISTS uq_conv_reply_template_default;")
    op.drop_index("ix_conv_reply_template_order", table_name="conversation_reply_templates")
    op.drop_index("ix_conv_reply_template_tenant", table_name="conversation_reply_templates")
    op.drop_table("conversation_reply_templates")
