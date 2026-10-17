"""conversations: the private-messaging inbox foundation (QUA-226, E1)

Numbered 0065 (not 0063) because `main` took 0063 (`signup_invites`) and 0064
(`signup_invites_meegle`) while this branch was open; production had never applied the
0063 of this branch, so the renumbering is a rename, not a data change.

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-16

What exists and is REUSED, untouched: `threads`/`messages` (0004) already model a DM
conversation — `channel` admits `'dm'` since 0004, `uq_thread_natural_key (connection_id,
channel, external_thread_id)` is the thread identity, `uq_message_external_id
(connection_id, external_message_id)` is the message dedup (webhook and poll both carry
Meta's `mid`), `last_inbound_at` is the base of the 24 h window (0004's B2 condition) and
`assigned_agent_id` the seat. Nothing of that is re-created here.

What a multichannel inbox still lacks, and this revision adds:

- `threads.external_conversation_id` — the id the Conversations API gives a conversation
  (`t_…`), when the thread was reached by polling. The thread's identity stays the
  COUNTERPART's external id in `external_thread_id` (an IGSID for Instagram, the same
  rule WhatsApp uses with `wa_id`): a webhook change carries `sender.id` and `mid` but no
  conversation id, so keying on the counterpart is what lets both paths converge on ONE
  thread. Nullable (a thread born from a webhook has none until a poll meets it); unique
  per connection when present.
- `threads.last_read_at` — when a person last opened the thread. «Pendiente» / «leído» /
  «respondido» derive from `last_inbound_at`, `last_read_at` and the last outbound
  message at read time; none of the three is a stored enum that could drift.
- `conversation_sync_state` — one row per `(connection, channel)`: the ACCESS verdict
  (`access_status`) and the last synchronisation. The access verdict is what lets the UI
  distinguish «no DMs» from «the permission is missing» or «the owner never enabled Allow
  Access to Messages» (`ig_shapes.UNCOVERED_SURFACES["direct_messages_human_toggle"]`):
  an empty poll alone is AMBIGUOUS, so `unknown` is a legitimate stored state, not a
  default to paper over. `sync_cursor` is opaque to this schema — each source owns its
  own paging token.
- `conversation_outbox` — every private message Qualify intends to send, channel-agnostic
  (`payload` is the already-built body in the channel's own wire shape). Same queue shape
  as `whatsapp_outbox` (0057) and `meta_webhook_events` (0050): claim by `(status,
  next_attempt_at)` with `FOR UPDATE SKIP LOCKED`, `attempts`/`locked_*`, terminal
  `failed`/`dead`. A media reply (an image or an audio the person attached) carries the
  R2 object (`media_object_key`, `media_type`, `media_content_type`): the sender mints the
  short-lived public URL Meta fetches AT SEND TIME (QUA-68's `/public/media/{token}`),
  never at enqueue time, so a row that waited longer than the token's TTL still goes out.
- `messages.media_url` — the channel's own CDN URL of an INBOUND attachment (Instagram
  hands one per `attachments[]` item, signed and expiring). The outbound side keeps using
  0061's `media_object_key` (the R2 copy Qualify itself sent). A row may have either,
  never both.
- `threads.counterpart_name/username/avatar_url/profile_at` — what the channel's profile
  API says about the counterpart (Instagram's User Profile API, consented by the fact
  that they messaged the business). The picture URL expires after days, so the sync
  refreshes a stale profile; the UI falls back to initials without one.
- `conversation_drafts` — E4: a reply a model proposed for ONE inbound message, with the
  statuses of `comment_reply_drafts` (0014) and the same rule: a draft is never a send.
  Sending is `conversation_outbox` with the person's approval (`draft_id` points back),
  so «no path sends without a human» stays a property of the outbox's NOT NULL column.
  Each row carries its cost provenance (model, tokens, USD — QUA-144) and the validated
  facts the model was given (`grounding`), which is what `needs_review` is judged
  against: a draft that asserts something outside those facts is flagged for review.

**Why a second outbox and not `whatsapp_outbox`.** The one invariant this module must
make unbreakable is ADR 21c: NO private reply leaves without a human. `whatsapp_outbox`
cannot carry it — its `automation` kind is the menu engine answering on its own
(legitimate there, WA-14), its `created_by_user_id` is nullable, and `qualify_webhook_worker`
holds INSERT on it. Here `approved_by_user_id` is NOT NULL (a row without a person is
unbuildable), the only `kind` is `reply`, and the webhook worker has NO privilege on the
table at all — so the webhook path, the only automated path into this system, cannot
enqueue a send even by mistake. `draft_id` is a bare uuid: the assisted-draft table (E4)
does not exist yet, same move 0057 made with `menu_version_id` before WA-14.

**Grants (minimal, per role).**

| table | qualify_app | qualify_webhook_worker | qualify_admin |
|---|---|---|---|
| `conversation_sync_state` | SELECT, INSERT, UPDATE | — | SELECT |
| `conversation_outbox` | SELECT, INSERT, UPDATE | — (deliberate) | — |

`qualify_admin` reads `conversation_sync_state` for the same reason it reads
`whatsapp_phone_numbers`: a future worker's cross-tenant discovery of connections that
have a channel to drain, ids only. Both tables carry the standard `NULLIF` isolation
policy of 0001 (R7) and the composite-FK discipline of R2.

**Adding a channel** is one revision widening `ck_thread_channel` and
`ck_conversation_outbox_channel` — the module's code is channel-agnostic, the schema
names the channels on purpose (an unknown string must not become a thread).

**Downgrade** drops the two tables (their rows with them — nothing else references them)
and the two columns; `threads`/`messages` rows are never touched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None

# The channels the private-messaging outbox may send on. `comment` replies go through
# `comment_reply_drafts` (0014) and WhatsApp through `whatsapp_outbox` (0057).
_OUTBOX_CHANNELS = ("dm",)
_OUTBOX_KINDS = ("reply",)
_OUTBOX_STATUSES = ("pending", "sending", "sent", "failed", "dead")
_ACCESS_STATUSES = (
    "unknown",
    "ok",
    "permission_missing",
    "access_disabled",
    "auth_expired",
    "error",
)
_SYNC_STATUSES = ("ok", "partial", "failed")


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
    # --- threads: the poll-side conversation id and the read marker --------------------
    op.add_column("threads", sa.Column("external_conversation_id", sa.Text(), nullable=True))
    op.add_column("threads", sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "CREATE UNIQUE INDEX uq_thread_conversation_id ON threads "
        "(connection_id, external_conversation_id) WHERE external_conversation_id IS NOT NULL;"
    )
    # --- threads: the counterpart's profile (User Profile API; the picture URL expires) --
    op.add_column("threads", sa.Column("counterpart_name", sa.Text(), nullable=True))
    op.add_column("threads", sa.Column("counterpart_username", sa.Text(), nullable=True))
    op.add_column("threads", sa.Column("counterpart_avatar_url", sa.Text(), nullable=True))
    op.add_column(
        "threads", sa.Column("counterpart_profile_at", sa.DateTime(timezone=True), nullable=True)
    )
    # --- messages: the channel's CDN URL of an inbound attachment ----------------------
    op.add_column("messages", sa.Column("media_url", sa.Text(), nullable=True))

    # --- conversation_sync_state -------------------------------------------------------
    op.create_table(
        "conversation_sync_state",
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("access_status", sa.Text(), nullable=False, server_default="unknown"),
        # A code or an exception class name, never user text and never a token.
        sa.Column("access_detail", sa.Text(), nullable=True),
        sa.Column("access_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_cursor", sa.Text(), nullable=True),
        sa.Column("last_sync_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_status", sa.Text(), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("connection_id", "channel", name="pk_conversation_sync_state"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_conv_sync_state_conn_tenant",
        ),
        sa.CheckConstraint(
            f"access_status IN ({_sql_list(_ACCESS_STATUSES)})",
            name="ck_conv_sync_state_access_status",
        ),
        sa.CheckConstraint(
            f"last_sync_status IS NULL OR last_sync_status IN ({_sql_list(_SYNC_STATUSES)})",
            name="ck_conv_sync_state_sync_status",
        ),
    )
    op.create_index("ix_conv_sync_state_tenant", "conversation_sync_state", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON conversation_sync_state TO qualify_app;")
    op.execute("GRANT SELECT ON conversation_sync_state TO qualify_admin;")
    _enable_tenant_rls("conversation_sync_state")

    # --- conversation_outbox -----------------------------------------------------------
    op.create_table(
        "conversation_outbox",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        # NOT NULL, unlike `whatsapp_outbox`: a private reply always answers a thread —
        # the 24 h window is decided from it, and there are no campaigns here.
        sa.Column("thread_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="reply"),
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
        # The channel's id for the message once accepted (Meta's `mid`); the key the
        # outbound `messages` row is written under.
        sa.Column("external_message_id", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        # ADR 21c as a column: the person who approved this exact text. NOT NULL.
        sa.Column(
            "approved_by_user_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        # Bare uuid until the assisted-draft table exists (E4 adds the FK).
        sa.Column("draft_id", PGUUID(as_uuid=True), nullable=True),
        # A media reply: the R2 object the sender links into a public URL at send time.
        sa.Column("media_object_key", sa.Text(), nullable=True),
        sa.Column("media_type", sa.Text(), nullable=True),
        sa.Column("media_content_type", sa.Text(), nullable=True),
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
            name="fk_conv_outbox_conn_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_conv_outbox_thread_tenant",
        ),
        sa.CheckConstraint(
            f"channel IN ({_sql_list(_OUTBOX_CHANNELS)})", name="ck_conversation_outbox_channel"
        ),
        sa.CheckConstraint(
            f"kind IN ({_sql_list(_OUTBOX_KINDS)})", name="ck_conversation_outbox_kind"
        ),
        sa.CheckConstraint(
            f"status IN ({_sql_list(_OUTBOX_STATUSES)})", name="ck_conversation_outbox_status"
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_conversation_outbox_attempts"),
    )
    op.create_index("ix_conv_outbox_tenant", "conversation_outbox", ["tenant_id"])
    # The sender's claim: `WHERE status = 'pending' AND next_attempt_at <= now()`.
    op.create_index("ix_conv_outbox_claim", "conversation_outbox", ["status", "next_attempt_at"])
    op.create_index("ix_conv_outbox_thread", "conversation_outbox", ["thread_id", "created_at"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON conversation_outbox TO qualify_app;")
    # Deliberately NO grant to qualify_webhook_worker: see the module docstring.
    _enable_tenant_rls("conversation_outbox")

    # --- conversation_drafts (E4): model-suggested replies, decided by a person -----------
    op.create_table(
        "conversation_drafts",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("thread_id", PGUUID(as_uuid=True), nullable=False),
        # The inbound message the draft answers.
        sa.Column("message_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("generator_version", sa.Text(), nullable=False),
        sa.Column("generated_text", sa.Text(), nullable=False),
        sa.Column("gate_reason", sa.Text(), nullable=False),
        # True when the model lacked validated tenant data for something it says.
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.Text(), nullable=False, server_default="proposed"),
        sa.Column("final_text", sa.Text(), nullable=True),
        # Cost provenance (QUA-144): the model that wrote it and what the call cost.
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("model_revision", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        # The validated facts the model was given (product names and prices, the
        # business name): what «requiere revisión» is judged against.
        sa.Column("grounding", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_conv_draft_thread_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "tenant_id"],
            ["messages.id", "messages.tenant_id"],
            name="fk_conv_draft_message_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('proposed','accepted','edited','discarded','sending','sent',"
            "'send_failed','send_ambiguous')",
            name="ck_conv_draft_status",
        ),
    )
    op.create_index("ix_conv_draft_tenant", "conversation_drafts", ["tenant_id"])
    op.create_index("ix_conv_draft_thread", "conversation_drafts", ["thread_id", "created_at"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON conversation_drafts TO qualify_app;")
    _enable_tenant_rls("conversation_drafts")


def downgrade() -> None:
    op.drop_index("ix_conv_draft_thread", table_name="conversation_drafts")
    op.drop_index("ix_conv_draft_tenant", table_name="conversation_drafts")
    op.drop_table("conversation_drafts")
    op.drop_index("ix_conv_outbox_thread", table_name="conversation_outbox")
    op.drop_index("ix_conv_outbox_claim", table_name="conversation_outbox")
    op.drop_index("ix_conv_outbox_tenant", table_name="conversation_outbox")
    op.drop_table("conversation_outbox")
    op.drop_index("ix_conv_sync_state_tenant", table_name="conversation_sync_state")
    op.drop_table("conversation_sync_state")
    op.execute("DROP INDEX IF EXISTS uq_thread_conversation_id;")
    op.drop_column("messages", "media_url")
    op.drop_column("threads", "counterpart_profile_at")
    op.drop_column("threads", "counterpart_avatar_url")
    op.drop_column("threads", "counterpart_username")
    op.drop_column("threads", "counterpart_name")
    op.drop_column("threads", "last_read_at")
    op.drop_column("threads", "external_conversation_id")
