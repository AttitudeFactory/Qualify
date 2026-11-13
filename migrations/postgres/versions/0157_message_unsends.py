"""messages: an Instagram DM the person unsent is erased, and stays erased (m-25018661)

Revision ID: 0157
Revises: 0156
Create Date: 2026-11-13

Meta requires an app to delete a message when its webhook says the person deleted
(«unsent») it — a `messages` item whose `message` carries `mid` and `is_deleted: true`
(`instagram-messaging/webhooks.md:79`; `overview.md:70`). Documented only, never observed
live here. Until now the handler settled such an item `unsupported` and kept the copy.

Two pieces:

1. `messages.unsent_at timestamptz NULL` — set when the stored row is erased in place. The
   row is REDACTED, not deleted: `qualify_app` holds no DELETE on `messages`, nor on the
   rows that reference it (`conversation_drafts`, `interaction_followups`,
   `comment_intent_results`), and this revision does not widen those grants. What survives
   is ids and instants only (id, thread, connection, `external_message_id`, direction,
   `author_external_id` — the IGSID that is already the thread's key — `posted_at`,
   `ingested_at`, `shape_version`); every content column is NULL, `deleted_at` is set so
   every listing that hides «Eliminar para mí» rows hides it too.
   `ck_message_unsent_redacted` makes that a schema guarantee: an unsent row cannot carry
   text, media, story or choice data. `ck_message_unsent_inbound`: only a person's message
   is unsent (an echo `is_deleted` is out of scope and never touches a row).

2. `message_unsends` — the tombstone: `(connection_id, external_message_id)` UNIQUE, plus
   when and from which webhook change (`source_event_id`, provenance — no FK, the intake
   purges its rows after 29 days) and `pipeline_version`. No text, no URL. It exists
   because the unsend may arrive BEFORE its message (out of order) or the reconciliation
   poll may still list it: the insert path checks it under a per-message advisory lock,
   so neither the webhook nor the poll can store that `mid` again. A side table rather
   than a placeholder `messages` row, because a placeholder needs a thread, and creating
   one for a person whose only message was unsent would put an empty conversation in the
   inbox.

RLS: `message_unsends` gets `tenant_id NOT NULL`, ENABLE + FORCE and the house policy in
this same revision. Grants: `qualify_app` SELECT, INSERT (append-only; a tombstone is never
edited); `qualify_admin` SELECT. The connection purge (0106) erases it with the rest of a
connection's synchronized data: `qualify_connection_purge` gets SELECT (tenant_id,
connection_id) + DELETE, and the table gets the same `connection_purge_fence` trigger.

**Downgrade** drops the table, the CHECKs and the column. Rows already redacted stay
redacted (content is not restorable, by design); they read as «Eliminar para mí» rows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0157"
down_revision = "0156"
branch_labels = None
depends_on = None

_TABLE = "message_unsends"

_CHECKS = (
    ("ck_message_unsent_inbound", "unsent_at IS NULL OR direction = 'inbound'"),
    (
        "ck_message_unsent_redacted",
        "unsent_at IS NULL OR (text IS NULL AND author_username IS NULL"
        " AND media_type IS NULL AND media_url IS NULL AND media_object_key IS NULL"
        " AND media_id IS NULL AND media_mime IS NULL AND raw_payload_r2_key IS NULL"
        " AND story_reply_id IS NULL"
        " AND story_reply_url IS NULL AND NOT story_mention AND story_mention_id IS NULL"
        " AND story_mention_url IS NULL AND story_mention_basis IS NULL"
        " AND choice_kind IS NULL AND choice_payload IS NULL AND deleted_at IS NOT NULL)",
    ),
)


def upgrade() -> None:
    op.add_column("messages", sa.Column("unsent_at", sa.DateTime(timezone=True), nullable=True))
    for name, condition in _CHECKS:
        op.create_check_constraint(name, "messages", condition)

    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("external_message_id", sa.Text(), nullable=False),
        sa.Column(
            "unsent_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        # The webhook change that carried the unsend (provenance; purged after 29 days).
        sa.Column("source_event_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "connection_id", "external_message_id", name="uq_message_unsend_external_id"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_message_unsend_conn_tenant",
        ),
    )
    op.create_index("ix_message_unsend_tenant", _TABLE, ["tenant_id"])
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {_TABLE}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
        """
    )
    op.execute(f"GRANT SELECT, INSERT ON {_TABLE} TO qualify_app")
    op.execute(f"GRANT SELECT ON {_TABLE} TO qualify_admin")
    op.execute(
        f"GRANT SELECT (tenant_id, connection_id), DELETE ON {_TABLE} TO qualify_connection_purge"
    )
    op.execute(
        f"CREATE TRIGGER connection_purge_fence BEFORE INSERT OR UPDATE ON {_TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION connection_purge_write_fence()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER connection_purge_fence ON {_TABLE}")
    op.execute(f"DROP POLICY tenant_isolation ON {_TABLE}")
    op.drop_index("ix_message_unsend_tenant", table_name=_TABLE)
    op.drop_table(_TABLE)
    for name, _condition in reversed(_CHECKS):
        op.drop_constraint(name, "messages", type_="check")
    op.drop_column("messages", "unsent_at")
