"""whatsapp: phone numbers, per-thread automation state and the outbox (WA-04, QUA-204)

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-14

Backlog: `docs/backlog-modulo-whatsapp.md` §2 WA-04 (it says "0056"; that number was taken
by `0056_support_requests` the same day, so this is 0057 and the menu migration WA-14 refers
to as "0057" must be 0058 or later). Plan: `docs/plan-modulo-whatsapp-cloud-api.md` §6.

**What it creates.** Three tenant-scoped tables, every one with the standard `NULLIF`
isolation policy of 0001 (R7) and the composite-FK discipline of R2 (a child row whose
tenant disagrees with its parent connection/thread is structurally unbuildable):

- `whatsapp_phone_numbers` — one row per WhatsApp Business phone number connected to
  Qualify. `phone_number_id` is UNIQUE across the whole table, not per tenant: it is Meta's
  global identifier and the webhook resolves the owning tenant from it alone
  (`social_connections.external_account_id = phone_number_id`, same rule as `mentions/
  resolve.py`). The Graph metadata columns (`verified_name`, `name_status`,
  `quality_rating`, `messaging_limit_tier`, `platform_status`) are kept verbatim and
  nullable — WA-05 reads them once at connect time and refreshes them on re-run;
  `last_synced_at` says when. `automation` is the conversational-automation object
  (ice breakers / commands / welcome) as PUBLISHED to Meta, so the editor can diff.
- `whatsapp_thread_state` — the automation cursor of ONE thread (`thread_id` is the PK):
  which menu version and node the conversation sits on, the order being built
  (`context`), and whether a person took over (`automation_paused_at`,
  `paused_by_user_id`). `menu_version_id` is a bare uuid until the menu tables exist
  (WA-14) — that migration adds the FK, the way 0045 added the FK on
  `content_drafts.campaign_id`.
- `whatsapp_outbox` — every message Qualify intends to send, as the already-built body of
  `POST /{phone_number_id}/messages` (`payload`). The sender claims `pending` rows by
  `(status, next_attempt_at)` with `FOR UPDATE SKIP LOCKED` (WA-08), hence
  `ix_wa_outbox_claim`; `attempts`/`next_attempt_at`/`locked_*` are the same queue shape
  0050 gave `meta_webhook_events`. `thread_id` is nullable because a `campaign_send`
  (entrega 4) may open a conversation that has no thread yet; a `reply` always has one.
  `wamid` is Meta's message id once accepted, the key the `statuses[]` webhook updates
  `messages.delivery_status` by.

**What it changes.**

- `threads.channel` admits `'whatsapp'` next to `'comment'`/`'dm'` — same table, same
  inbox: a WhatsApp conversation is a thread of the tenant's connected account, exactly
  what 0004 built for Instagram DMs. The 24 h window keeps deriving from
  `last_inbound_at` (0004's B2 condition holds verbatim for WhatsApp).
- `messages.delivery_status` (`sent`/`delivered`/`read`/`failed`, nullable) and
  `messages.delivery_error_code`: the receipt Meta sends back for an OUTBOUND message.
  Nullable because an inbound message has no delivery status, and an outbound one has
  none until the first receipt arrives. No partial index on pending outbound rows: the
  outbox already is that queue.
- `social_connections.linked_page_id` becomes NULLABLE, guarded by
  `ck_conn_linked_page_by_platform`: `(platform = 'whatsapp') OR (linked_page_id IS NOT
  NULL)`. ADR 25 is intact for Instagram — an Instagram row without its linked Page is
  still unrepresentable, now by a CHECK instead of by NOT NULL — and a WhatsApp number has
  no Facebook Page to link (it hangs off a WABA, `account_type = 'waba_phone_number'`).

**Grants (minimal, per role).**

| table | qualify_app | qualify_webhook_worker | qualify_admin |
|---|---|---|---|
| `whatsapp_phone_numbers` | SELECT, INSERT, UPDATE | SELECT, four columns (*) | SELECT |
| `whatsapp_thread_state` | SELECT, INSERT, UPDATE | SELECT, INSERT, UPDATE | — |
| `whatsapp_outbox` | SELECT, INSERT, UPDATE | INSERT | — |
| `threads` (existing) | unchanged | **+ SELECT, INSERT, UPDATE** | unchanged |
| `messages` (existing) | unchanged | **+ SELECT, INSERT, UPDATE** | unchanged |

(*) `id, tenant_id, connection_id, phone_number_id` — a column grant, no table-level SELECT.

`qualify_webhook_worker` is the role that processes `meta_webhook_events` (0050); until now
its only reach outside the intake was five columns of `social_connections`. WhatsApp's
inbound path (WA-07) is that worker writing the conversation: it upserts `threads` and
`messages`, keeps the automation cursor in `whatsapp_thread_state`, and enqueues what the
menu engine answers into `whatsapp_outbox` — INSERT only there, because sending is the
outbox sender's job (WA-08, running as `qualify_app` under `tenant_session`). It never
reads the outbox, never touches `oauth_credentials`, and reads only the four columns of
`whatsapp_phone_numbers` it needs to resolve a number. BYPASSRLS does not widen any of
this: it bypasses policies, never GRANTs (0050's docstring). `test_webhook_schema_db.py`
pins the resulting table, cell by cell.

**Downgrade deletes WhatsApp data, and says so here.** Restoring `ck_thread_channel` and
`linked_page_id NOT NULL` is impossible while WhatsApp rows exist, so the downgrade
removes, in FK order: the three new tables; `messages`/`threads` of `channel =
'whatsapp'`; and `social_connections` rows of `platform = 'whatsapp'` together with their
`oauth_credentials` and `connection_events` (the only children WA-05 creates). Any other
child of a WhatsApp connection (a scheduled post, a mention…) is unexpected and would stop
the downgrade with an FK error rather than be deleted silently. Instagram data is never
touched. Same posture 0045 took when it cleared dangling `campaign_id`s before declaring
its FK: the migration states the data it destroys instead of failing half-way.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None

_OUTBOX_KINDS = ("reply", "automation", "campaign_send")
_OUTBOX_STATUSES = ("pending", "sending", "sent", "failed", "dead")
_DELIVERY_STATUSES = ("sent", "delivered", "read", "failed")
# The worker resolves a number to its tenant/connection and needs nothing else of the row.
_PHONE_RESOLVE_COLUMNS = ("id", "tenant_id", "connection_id", "phone_number_id")


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


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def upgrade() -> None:
    # --- whatsapp_phone_numbers --------------------------------------------------------
    op.create_table(
        "whatsapp_phone_numbers",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("waba_id", sa.Text(), nullable=False),
        sa.Column("phone_number_id", sa.Text(), nullable=False),
        sa.Column("display_phone_number", sa.Text(), nullable=False),
        sa.Column("verified_name", sa.Text(), nullable=True),
        sa.Column("name_status", sa.Text(), nullable=True),
        sa.Column("quality_rating", sa.Text(), nullable=True),
        sa.Column("messaging_limit_tier", sa.Text(), nullable=True),
        sa.Column("platform_status", sa.Text(), nullable=True),
        sa.Column("automation", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Meta's global id: the webhook resolves the tenant from it, so it is unique
        # across tenants, not within one.
        sa.UniqueConstraint("phone_number_id", name="uq_wa_phone_number_id"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_wa_phone_conn_tenant",
        ),
    )
    op.create_index("ix_wa_phone_tenant", "whatsapp_phone_numbers", ["tenant_id"])
    op.create_index("ix_wa_phone_connection", "whatsapp_phone_numbers", ["connection_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON whatsapp_phone_numbers TO qualify_app;")
    op.execute("GRANT SELECT ON whatsapp_phone_numbers TO qualify_admin;")
    op.execute(
        f"GRANT SELECT ({', '.join(_PHONE_RESOLVE_COLUMNS)}) "
        "ON whatsapp_phone_numbers TO qualify_webhook_worker;"
    )
    _enable_tenant_rls("whatsapp_phone_numbers")

    # --- whatsapp_thread_state ---------------------------------------------------------
    op.create_table(
        "whatsapp_thread_state",
        sa.Column("thread_id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        # Bare uuid until the menu tables exist (WA-14 adds the FK).
        sa.Column("menu_version_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("node_id", sa.Text(), nullable=True),
        sa.Column("context", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("automation_paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "paused_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_wa_thread_state_thread_tenant",
        ),
    )
    op.create_index("ix_wa_thread_state_tenant", "whatsapp_thread_state", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON whatsapp_thread_state TO qualify_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON whatsapp_thread_state TO qualify_webhook_worker;")
    _enable_tenant_rls("whatsapp_thread_state")

    # --- whatsapp_outbox ---------------------------------------------------------------
    op.create_table(
        "whatsapp_outbox",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("wamid", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_wa_outbox_conn_tenant",
        ),
        # MATCH SIMPLE: a NULL `thread_id` is simply not checked (a campaign send with
        # no thread yet); a non-NULL one must belong to the same tenant.
        sa.ForeignKeyConstraint(
            ["thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_wa_outbox_thread_tenant",
        ),
        sa.CheckConstraint(f"kind IN ({_sql_list(_OUTBOX_KINDS)})", name="ck_wa_outbox_kind"),
        sa.CheckConstraint(
            f"status IN ({_sql_list(_OUTBOX_STATUSES)})", name="ck_wa_outbox_status"
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_wa_outbox_attempts"),
    )
    op.create_index("ix_wa_outbox_tenant", "whatsapp_outbox", ["tenant_id"])
    # The sender's claim: `WHERE status = 'pending' AND next_attempt_at <= now()`.
    op.create_index("ix_wa_outbox_claim", "whatsapp_outbox", ["status", "next_attempt_at"])
    op.create_index(
        "ix_wa_outbox_thread",
        "whatsapp_outbox",
        ["thread_id", "created_at"],
        postgresql_where=sa.text("thread_id IS NOT NULL"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON whatsapp_outbox TO qualify_app;")
    op.execute("GRANT INSERT ON whatsapp_outbox TO qualify_webhook_worker;")
    _enable_tenant_rls("whatsapp_outbox")

    # --- threads / messages: the WhatsApp channel and the delivery receipt -------------
    op.execute("ALTER TABLE threads DROP CONSTRAINT ck_thread_channel;")
    op.execute(
        "ALTER TABLE threads ADD CONSTRAINT ck_thread_channel "
        "CHECK (channel IN ('comment','dm','whatsapp'));"
    )
    op.add_column("messages", sa.Column("delivery_status", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("delivery_error_code", sa.Text(), nullable=True))
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT ck_message_delivery_status "
        "CHECK (delivery_status IS NULL OR delivery_status IN "
        f"({_sql_list(_DELIVERY_STATUSES)}));"
    )
    # The processor writes the inbound conversation (WA-07): see the docstring's table.
    op.execute("GRANT SELECT, INSERT, UPDATE ON threads TO qualify_webhook_worker;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON messages TO qualify_webhook_worker;")

    # --- social_connections: the Page link becomes conditional on the platform ---------
    op.execute("ALTER TABLE social_connections ALTER COLUMN linked_page_id DROP NOT NULL;")
    op.execute(
        "ALTER TABLE social_connections ADD CONSTRAINT ck_conn_linked_page_by_platform "
        "CHECK ((platform = 'whatsapp') OR (linked_page_id IS NOT NULL));"
    )


def downgrade() -> None:
    op.execute("REVOKE SELECT, INSERT, UPDATE ON messages FROM qualify_webhook_worker;")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON threads FROM qualify_webhook_worker;")

    op.drop_index("ix_wa_outbox_thread", table_name="whatsapp_outbox")
    op.drop_index("ix_wa_outbox_claim", table_name="whatsapp_outbox")
    op.drop_index("ix_wa_outbox_tenant", table_name="whatsapp_outbox")
    op.drop_table("whatsapp_outbox")
    op.drop_index("ix_wa_thread_state_tenant", table_name="whatsapp_thread_state")
    op.drop_table("whatsapp_thread_state")
    op.drop_index("ix_wa_phone_connection", table_name="whatsapp_phone_numbers")
    op.drop_index("ix_wa_phone_tenant", table_name="whatsapp_phone_numbers")
    op.drop_table("whatsapp_phone_numbers")

    # WhatsApp conversations cannot survive the old CHECK — delete them, messages first.
    op.execute(
        "DELETE FROM messages WHERE thread_id IN "
        "(SELECT id FROM threads WHERE channel = 'whatsapp');"
    )
    op.execute("DELETE FROM threads WHERE channel = 'whatsapp';")
    op.execute("ALTER TABLE messages DROP CONSTRAINT ck_message_delivery_status;")
    op.drop_column("messages", "delivery_error_code")
    op.drop_column("messages", "delivery_status")
    op.execute("ALTER TABLE threads DROP CONSTRAINT ck_thread_channel;")
    op.execute(
        "ALTER TABLE threads ADD CONSTRAINT ck_thread_channel CHECK (channel IN ('comment','dm'));"
    )

    # WhatsApp connections have no Page and cannot satisfy NOT NULL — delete them with the
    # two children WA-05 creates. Anything else referencing them fails loudly on purpose.
    op.execute(
        "DELETE FROM oauth_credentials WHERE connection_id IN "
        "(SELECT id FROM social_connections WHERE platform = 'whatsapp');"
    )
    op.execute(
        "DELETE FROM connection_events WHERE connection_id IN "
        "(SELECT id FROM social_connections WHERE platform = 'whatsapp');"
    )
    op.execute("DELETE FROM social_connections WHERE platform = 'whatsapp';")
    op.execute("ALTER TABLE social_connections DROP CONSTRAINT ck_conn_linked_page_by_platform;")
    op.execute("ALTER TABLE social_connections ALTER COLUMN linked_page_id SET NOT NULL;")
