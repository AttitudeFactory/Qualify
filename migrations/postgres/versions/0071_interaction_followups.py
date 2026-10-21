"""interaction_followups: a commercial query from Interacciones, continued in private
(m-24789646, Interacciones · Fase C)

Revision ID: 0071
Revises: 0070
Create Date: 2026-10-21

One row per INTERACTION — a public comment, or a DM that replied to a story — that a
person may answer in private. It is the link the rest of Fase C hangs on:

    origin message (comment or story reply)
      → its commercial intent (`comment_intent_results`, when an analysis raised it)
      → the author's DM thread in Conversaciones (`threads`, channel `dm`)
      → the send a person approved (`conversation_outbox`)
      → the public notice «Te enviamos la información por DM 💬» (comments only)

What it does NOT duplicate, on purpose:

- The draft. `conversation_drafts` (0065) already stores a model's proposal for one
  message with its grounding and cost; a followup's draft is a row there whose
  `message_id` is the origin message and whose `thread_id` is the DM thread. Nothing
  here points at it — the draft points at the message.
- The delivery. Whether the private message went out is the outbox row's `status` and
  `external_message_id`; a followup keeps only `outbox_id`. A copy here could disagree
  with the queue, and the public notice must trust the queue alone (B4: only after a
  CONFIRMED send).
- The author and the comment time. Both are on the origin `messages` row
  (`author_external_id` — the IGSID, which keys the DM thread — and `posted_at`, the base
  of Meta's 7-day private-reply limit).

Columns that carry a decision:

- `origin_message_id` is UNIQUE: one followup per interaction, so the automatic path
  (an intent analysis) and the manual one («Responder por DM») converge on the same row,
  and a retried analysis cannot open a second one.
- `trigger` says who opened it: `intent` (a commercial `IntentSignal`; `intent_result_id`
  is then required and points at the exact versioned analysis — provenance) or `manual`
  (a person, from Interacciones; no analysis is implied).
- `status` is the human lifecycle only: `open` (waiting for a person), `approved` (a
  person approved a send — `outbox_id`, `send_route`, `decided_*` are then set) and
  `discarded`. Expiry is NOT stored: the 7-day and 24 h windows are computed when read
  and revalidated when sent, so a stored «expired» could only go stale.
- `send_route` is how the approved message leaves: `private_reply` (Meta's reply to a
  comment, `recipient.comment_id`: one message, within 7 days) or `dm` (a normal DM, when
  the author's thread already has the 24 h window open).
- `notice_*` is the public notice, an independent step with its own status. It applies
  only to comments (`not_applicable` otherwise, CHECKed): a story reply has no public
  comment to answer. `notice_external_id` is UNIQUE when present — the id Meta gave the
  public reply — and the row itself (one per interaction) is the idempotency key, so a
  retried notice can never post twice.

The composite FKs follow R2. `comment_intent_results` and `conversation_outbox` had no
`(id, tenant_id)` key to point a composite FK at; this revision adds one to each (both
ids are already primary keys, so the new constraints can never reject an existing row).

**Grants.** `qualify_app`: SELECT, INSERT, UPDATE — no DELETE (a followup is discarded,
never erased: it explains a send). Nothing for `qualify_webhook_worker` (a Meta delivery
must not open, approve or notice anything) nor for `qualify_admin`. Standard RLS (R7).

**Downgrade** drops the table and the two added constraints; no other row is touched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None

_ORIGIN_KINDS = ("comment", "story_reply")
_TRIGGERS = ("intent", "manual")
_STATUSES = ("open", "approved", "discarded")
_SEND_ROUTES = ("private_reply", "dm")
_NOTICE_STATUSES = ("not_applicable", "not_requested", "pending", "posted", "failed", "skipped")


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
    op.create_unique_constraint(
        "uq_comment_intent_id_tenant", "comment_intent_results", ["id", "tenant_id"]
    )
    op.create_unique_constraint(
        "uq_conv_outbox_id_tenant", "conversation_outbox", ["id", "tenant_id"]
    )

    op.create_table(
        "interaction_followups",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("origin_kind", sa.Text(), nullable=False),
        # The comment, or the DM that replied to a story (`messages.id`).
        sa.Column("origin_message_id", PGUUID(as_uuid=True), nullable=False),
        # The author's private thread (channel `dm`, keyed by their IGSID).
        sa.Column("dm_thread_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("intent_result_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("send_route", sa.Text(), nullable=True),
        sa.Column("outbox_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        # The public notice: an independent step with its own status (B4).
        sa.Column("notice_status", sa.Text(), nullable=False),
        sa.Column("notice_text", sa.Text(), nullable=True),
        sa.Column("notice_attempts", sa.Integer(), nullable=False, server_default="0"),
        # Meta's id of the public reply once posted.
        sa.Column("notice_external_id", sa.Text(), nullable=True),
        # A code, never user text.
        sa.Column("notice_error_code", sa.Text(), nullable=True),
        sa.Column("notice_posted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("origin_message_id", name="uq_followup_origin_message"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_followup_conn_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["origin_message_id", "tenant_id"],
            ["messages.id", "messages.tenant_id"],
            name="fk_followup_message_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["dm_thread_id", "tenant_id"],
            ["threads.id", "threads.tenant_id"],
            name="fk_followup_thread_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["intent_result_id", "tenant_id"],
            ["comment_intent_results.id", "comment_intent_results.tenant_id"],
            name="fk_followup_intent_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["outbox_id", "tenant_id"],
            ["conversation_outbox.id", "conversation_outbox.tenant_id"],
            name="fk_followup_outbox_tenant",
        ),
        sa.CheckConstraint(
            f"origin_kind IN ({_sql_list(_ORIGIN_KINDS)})", name="ck_followup_origin_kind"
        ),
        sa.CheckConstraint(f"trigger IN ({_sql_list(_TRIGGERS)})", name="ck_followup_trigger"),
        sa.CheckConstraint(f"status IN ({_sql_list(_STATUSES)})", name="ck_followup_status"),
        sa.CheckConstraint(
            f"send_route IS NULL OR send_route IN ({_sql_list(_SEND_ROUTES)})",
            name="ck_followup_send_route",
        ),
        sa.CheckConstraint(
            f"notice_status IN ({_sql_list(_NOTICE_STATUSES)})", name="ck_followup_notice_status"
        ),
        # An intent-triggered followup names the analysis that raised it.
        sa.CheckConstraint(
            "(trigger = 'intent') = (intent_result_id IS NOT NULL)",
            name="ck_followup_intent_provenance",
        ),
        # Approved ⇔ a person, an instant, a route and the queued send are all recorded.
        sa.CheckConstraint(
            "(status = 'approved') = (outbox_id IS NOT NULL AND send_route IS NOT NULL "
            "AND decided_by_user_id IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_followup_approved_complete",
        ),
        sa.CheckConstraint(
            "status <> 'discarded' OR (decided_by_user_id IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_followup_discarded_decided",
        ),
        # A story reply has no public comment to answer; a private reply needs a comment.
        sa.CheckConstraint(
            "origin_kind = 'comment' OR notice_status = 'not_applicable'",
            name="ck_followup_notice_comments_only",
        ),
        sa.CheckConstraint(
            "origin_kind = 'comment' OR send_route IS DISTINCT FROM 'private_reply'",
            name="ck_followup_private_reply_comments_only",
        ),
        sa.CheckConstraint(
            "(notice_status = 'posted') = (notice_external_id IS NOT NULL)",
            name="ck_followup_notice_posted_has_id",
        ),
        sa.CheckConstraint("notice_attempts >= 0", name="ck_followup_notice_attempts"),
    )
    op.create_index("ix_followup_tenant", "interaction_followups", ["tenant_id"])
    # «Consultas desde comentarios»: a connection's open followups, newest first.
    op.create_index(
        "ix_followup_queue", "interaction_followups", ["connection_id", "status", "created_at"]
    )
    op.create_index("ix_followup_thread", "interaction_followups", ["dm_thread_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_followup_notice_external_id ON interaction_followups "
        "(connection_id, notice_external_id) WHERE notice_external_id IS NOT NULL;"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON interaction_followups TO qualify_app;")
    # Deliberately nothing for qualify_webhook_worker or qualify_admin.
    _enable_tenant_rls("interaction_followups")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_followup_notice_external_id;")
    op.drop_index("ix_followup_thread", table_name="interaction_followups")
    op.drop_index("ix_followup_queue", table_name="interaction_followups")
    op.drop_index("ix_followup_tenant", table_name="interaction_followups")
    op.drop_table("interaction_followups")
    op.drop_constraint("uq_conv_outbox_id_tenant", "conversation_outbox", type_="unique")
    op.drop_constraint("uq_comment_intent_id_tenant", "comment_intent_results", type_="unique")
