"""whatsapp marketing: templates, opt-ins, campaigns and their sends (WA-18/19/20)

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-14

Backlog: `docs/backlog-modulo-whatsapp.md` §5 WA-18, WA-19, WA-20 (it says "0058" for all
three; 0058 is the menus migration, so this is the next free number). Plan:
`docs/plan-modulo-whatsapp-cloud-api.md` §2.4-§2.5 (template limits, per-message pricing,
per-user marketing limit `131049`) and §5.4. Services: `qualify_api.whatsapp.templates`,
`.optins`, `.campaigns`, `.pricing`.

**What it creates.** Four tenant-scoped tables, each with the standard `NULLIF` isolation
policy of 0001 (R7) and the composite-FK discipline of R2:

- `whatsapp_templates` — the mirror of the message templates of a WABA. Natural key
  `(tenant_id, waba_id, name, language)`: Meta lets the same name exist once per language.
  `meta_template_id` is NULL until Meta answers the create call (or the sync finds it).
  `status` and `quality` are Meta's strings verbatim and deliberately NOT CHECKed — Meta
  adds template statuses without a version bump (`LIMIT_EXCEEDED`, `ARCHIVED` … arrived
  that way) and a CHECK would turn every addition into a failed webhook. `category` IS
  checked: the three values are what pricing keys on. `phone_number_row_id` is optional:
  a template belongs to the WABA, not to one number; the column records which number the
  author was working with, when there is one.
- `whatsapp_opt_ins` — one consent per `(tenant_id, phone_e164)`. `source` is where it was
  captured (`lead_form`, `menu`, `import`, `manual`); `consent_text` is the text the person
  agreed to, stored with the row (Meta: the opt-in must name the business and say the
  person agrees to receive its messages — getting-opt-in); `proof` is free evidence (lead
  id, import file key…). `revoked_at`/`revoke_reason` mark an opt-out; a revoked row is
  kept, never deleted — it is the evidence the audience must exclude that phone.
- `whatsapp_campaigns` — one marketing send: a connection (the number it sends from), an
  APPROVED template, an audience filter (`audience_filter`, evaluated against opt-ins by
  `CampaignService.build_audience`), the template's send-time `components`
  (`send_components`, the parameters) and a pace (`max_per_minute`, default 30).
- `whatsapp_campaign_sends` — one row per `(campaign_id, phone_e164)` (UNIQUE: relaunching
  a campaign never sends twice), with the outbox row that carries it (`outbox_id`), Meta's
  `wamid` once accepted, the receipt status, `error_code`, Meta's `price_category` from the
  status webhook and the `cost_estimate`/`currency` computed at launch.

**What it changes.**

- `whatsapp_outbox` gains the `(id, tenant_id)` UNIQUE (target of the sends' composite FK)
  and the trigger `wa_outbox_campaign_mirror` (below).
- `qualify_webhook_worker` gains a column SELECT on `whatsapp_phone_numbers.waba_id`: the
  template webhooks (`message_template_status_update`, `…_quality_update`) carry the WABA
  id (`entry.id`) and no phone number, so the worker resolves the tenant from it
  (`resolve.resolve_waba`).

**How `whatsapp_campaign_sends.wamid` gets filled — a trigger, and why.** The send's
`wamid` is born when the outbox sender (WA-08, `qualify_app` under `tenant_session`) marks
the outbox row `sent`. Three candidates were weighed:

1. *The sender writes it after `mark_sent`.* Correct, but it couples WA-08's sender to the
   campaign tables and is not atomic with `mark_sent` unless it lives inside it.
2. *The receipt handler joins through `whatsapp_outbox.wamid`.* Needs a SELECT grant on
   the outbox for `qualify_webhook_worker`, which 0057 deliberately withheld ("it never
   reads the outbox").
3. **An `AFTER UPDATE OF status` trigger on `whatsapp_outbox`** (chosen). When a
   `campaign_send` row moves to `sent`, the trigger copies its `wamid` to the send row
   and sets `status = 'sent'`; to `failed`/`dead`, it sets `failed` (or `skipped` for
   `131049` and `campaign_cancelled`) with the outbox's `error_code`. It runs in the
   SAME transaction as the sender's settle, as the invoker (`qualify_app`, which holds
   UPDATE on the sends and whose RLS context is the row's tenant), so it is atomic, needs
   no new grant for anyone, and works whichever code path settles the outbox (the sender,
   the stale-lock reaper, a cancel). Each transition is guarded so it never regresses a
   send a receipt already moved further (`delivered`, `read`).

After that, delivery receipts (`statuses[]` of the `messages` webhook) update the send by
`wamid` under the worker role (`CampaignReceiptRepository`). The existing
`messages.delivery_status` path cannot do it: WA-08 writes no `messages` row for an outbox
item without a thread, which is every campaign send.

**Grants (minimal, per role).**

| table | qualify_app | qualify_webhook_worker | qualify_admin |
|---|---|---|---|
| `whatsapp_templates` | S, I, U | SELECT 6 cols (a), UPDATE 4 cols (b) | SELECT |
| `whatsapp_opt_ins` | S, I, U | SELECT 4 (c), UPDATE 2 (d), INSERT 8 cols (e) | SELECT |
| `whatsapp_campaigns` | S, I, U | — | SELECT |
| `whatsapp_campaign_sends` | S, I, U | SELECT 5 cols (f), UPDATE 4 cols (g) | SELECT |
| `whatsapp_phone_numbers` (existing) | unchanged | **+ SELECT (`waba_id`)** | unchanged |

(S, I, U = SELECT, INSERT, UPDATE.)

(a) `id, tenant_id, waba_id, name, language, meta_template_id` — find the template a
    webhook names. (b) `status, quality, rejected_reason, updated_at` — what the webhook
    changes. (c) `id, tenant_id, phone_e164, revoked_at` — find a live consent.
(d) `revoked_at, revoke_reason` — the STOP keyword's revocation. (e) `tenant_id, brand_id,
    phone_e164, source, consent_text, consent_policy_version, proof, captured_at` — the
    menu's opt-in node (`id` has its default). (f) `id, tenant_id, outbox_id, wamid,
    status` — find a send by `wamid`; `status` is read by the monotonic guard of the
    receipt update (an UPDATE's WHERE needs SELECT on what it reads). (g) `status,
    error_code, price_category, updated_at` — what a receipt changes.

No role may DELETE from any of the four. `test_whatsapp_marketing_schema_db.py` pins the
table cell by cell; `test_webhook_schema_db.py` carries the worker's new column grants.

**Downgrade** drops the trigger and its function, the four tables (their data is deleted
with them — templates are re-syncable from Meta, opt-ins are NOT: they are consent
evidence, so a downgrade on a database with real opt-ins must be preceded by an export),
the `(id, tenant_id)` UNIQUE on `whatsapp_outbox` and the worker's `waba_id` grant.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None

_TEMPLATE_CATEGORIES = ("marketing", "utility", "authentication")
_OPT_IN_SOURCES = ("lead_form", "menu", "import", "manual")
_CAMPAIGN_STATUSES = ("draft", "scheduled", "running", "paused", "done", "cancelled")
_SEND_STATUSES = ("pending", "queued", "sent", "delivered", "read", "failed", "skipped")

_WORKER_TEMPLATE_SELECT = ("id", "tenant_id", "waba_id", "name", "language", "meta_template_id")
_WORKER_TEMPLATE_UPDATE = ("status", "quality", "rejected_reason", "updated_at")
_WORKER_OPT_IN_SELECT = ("id", "tenant_id", "phone_e164", "revoked_at")
_WORKER_OPT_IN_UPDATE = ("revoked_at", "revoke_reason")
_WORKER_OPT_IN_INSERT = (
    "tenant_id",
    "brand_id",
    "phone_e164",
    "source",
    "consent_text",
    "consent_policy_version",
    "proof",
    "captured_at",
)
_WORKER_SEND_SELECT = ("id", "tenant_id", "outbox_id", "wamid", "status")
_WORKER_SEND_UPDATE = ("status", "error_code", "price_category", "updated_at")

# The outbox → send mirror (see the docstring). `pending`/`queued` are the only states a
# settle may move forward from; a send a receipt already moved stays where it is.
_MIRROR_FUNCTION = """
CREATE OR REPLACE FUNCTION wa_outbox_campaign_mirror() RETURNS trigger AS $$
BEGIN
    IF NEW.status = 'sent' THEN
        UPDATE whatsapp_campaign_sends
           SET wamid = NEW.wamid, status = 'sent', error_code = NULL, updated_at = now()
         WHERE outbox_id = NEW.id AND tenant_id = NEW.tenant_id
           AND status IN ('pending', 'queued');
    ELSIF NEW.status IN ('failed', 'dead') THEN
        UPDATE whatsapp_campaign_sends
           SET status = CASE WHEN NEW.error_code IN ('131049', 'campaign_cancelled')
                             THEN 'skipped' ELSE 'failed' END,
               error_code = NEW.error_code,
               updated_at = now()
         WHERE outbox_id = NEW.id AND tenant_id = NEW.tenant_id
           AND status IN ('pending', 'queued');
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


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


def _cols(values: tuple[str, ...]) -> str:
    return ", ".join(values)


def _id() -> sa.Column:
    return sa.Column(
        "id", PGUUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True
    )


def _ts(name: str, *, nullable: bool = False) -> sa.Column:
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _grant_standard(table: str) -> None:
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {table} TO qualify_admin;")


def upgrade() -> None:
    # --- whatsapp_templates ------------------------------------------------------------
    op.create_table(
        "whatsapp_templates",
        _id(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("waba_id", sa.Text(), nullable=False),
        sa.Column("phone_number_row_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("meta_template_id", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("quality", sa.Text(), nullable=True),
        sa.Column("components", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint(
            "tenant_id", "waba_id", "name", "language", name="uq_wa_template_natural_key"
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_wa_template_id_tenant"),
        # MATCH SIMPLE: a NULL number is not checked; a set one must be the tenant's own.
        sa.ForeignKeyConstraint(
            ["phone_number_row_id", "tenant_id"],
            ["whatsapp_phone_numbers.id", "whatsapp_phone_numbers.tenant_id"],
            name="fk_wa_template_phone_tenant",
        ),
        sa.CheckConstraint(
            f"category IN ({_sql_list(_TEMPLATE_CATEGORIES)})", name="ck_wa_template_category"
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_wa_template_name_not_blank"),
    )
    op.create_index("ix_wa_template_tenant", "whatsapp_templates", ["tenant_id"])
    op.create_index(
        "ix_wa_template_meta_id",
        "whatsapp_templates",
        ["waba_id", "meta_template_id"],
        postgresql_where=sa.text("meta_template_id IS NOT NULL"),
    )
    _grant_standard("whatsapp_templates")
    op.execute(
        f"GRANT SELECT ({_cols(_WORKER_TEMPLATE_SELECT)}) "
        "ON whatsapp_templates TO qualify_webhook_worker;"
    )
    op.execute(
        f"GRANT UPDATE ({_cols(_WORKER_TEMPLATE_UPDATE)}) "
        "ON whatsapp_templates TO qualify_webhook_worker;"
    )
    _enable_tenant_rls("whatsapp_templates")

    # --- whatsapp_opt_ins --------------------------------------------------------------
    op.create_table(
        "whatsapp_opt_ins",
        _id(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("phone_e164", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("consent_text", sa.Text(), nullable=False),
        sa.Column("consent_policy_version", sa.Text(), nullable=True),
        sa.Column("proof", JSONB(), nullable=True),
        _ts("captured_at"),
        _ts("revoked_at", nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.UniqueConstraint("tenant_id", "phone_e164", name="uq_wa_opt_in_tenant_phone"),
        sa.CheckConstraint(f"source IN ({_sql_list(_OPT_IN_SOURCES)})", name="ck_wa_opt_in_source"),
        sa.CheckConstraint(r"phone_e164 ~ '^\+[1-9][0-9]{7,14}$'", name="ck_wa_opt_in_phone_e164"),
        sa.CheckConstraint(
            "length(btrim(consent_text)) > 0", name="ck_wa_opt_in_consent_text_not_blank"
        ),
    )
    op.create_index("ix_wa_opt_in_tenant", "whatsapp_opt_ins", ["tenant_id"])
    _grant_standard("whatsapp_opt_ins")
    op.execute(
        f"GRANT SELECT ({_cols(_WORKER_OPT_IN_SELECT)}) "
        "ON whatsapp_opt_ins TO qualify_webhook_worker;"
    )
    op.execute(
        f"GRANT UPDATE ({_cols(_WORKER_OPT_IN_UPDATE)}) "
        "ON whatsapp_opt_ins TO qualify_webhook_worker;"
    )
    op.execute(
        f"GRANT INSERT ({_cols(_WORKER_OPT_IN_INSERT)}) "
        "ON whatsapp_opt_ins TO qualify_webhook_worker;"
    )
    _enable_tenant_rls("whatsapp_opt_ins")

    # --- whatsapp_campaigns ------------------------------------------------------------
    op.create_table(
        "whatsapp_campaigns",
        _id(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=True),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("template_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column(
            "audience_filter", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "send_components", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("max_per_minute", sa.Integer(), nullable=False, server_default="30"),
        _ts("scheduled_at", nullable=True),
        _ts("started_at", nullable=True),
        _ts("finished_at", nullable=True),
        sa.Column(
            "created_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_wa_campaign_id_tenant"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_wa_campaign_conn_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["template_id", "tenant_id"],
            ["whatsapp_templates.id", "whatsapp_templates.tenant_id"],
            name="fk_wa_campaign_template_tenant",
        ),
        sa.CheckConstraint(
            f"status IN ({_sql_list(_CAMPAIGN_STATUSES)})", name="ck_wa_campaign_status"
        ),
        sa.CheckConstraint(
            "max_per_minute BETWEEN 1 AND 1000", name="ck_wa_campaign_max_per_minute"
        ),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_wa_campaign_name_not_blank"),
    )
    op.create_index("ix_wa_campaign_tenant", "whatsapp_campaigns", ["tenant_id"])
    _grant_standard("whatsapp_campaigns")
    _enable_tenant_rls("whatsapp_campaigns")

    # --- whatsapp_outbox: the composite-FK target --------------------------------------
    op.create_unique_constraint("uq_wa_outbox_id_tenant", "whatsapp_outbox", ["id", "tenant_id"])

    # --- whatsapp_campaign_sends -------------------------------------------------------
    op.create_table(
        "whatsapp_campaign_sends",
        _id(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("phone_e164", sa.Text(), nullable=False),
        sa.Column("outbox_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("wamid", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("price_category", sa.Text(), nullable=True),
        sa.Column("cost_estimate", sa.Numeric(10, 4), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("campaign_id", "phone_e164", name="uq_wa_campaign_send_phone"),
        sa.ForeignKeyConstraint(
            ["campaign_id", "tenant_id"],
            ["whatsapp_campaigns.id", "whatsapp_campaigns.tenant_id"],
            name="fk_wa_campaign_send_campaign_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["outbox_id", "tenant_id"],
            ["whatsapp_outbox.id", "whatsapp_outbox.tenant_id"],
            name="fk_wa_campaign_send_outbox_tenant",
        ),
        sa.CheckConstraint(
            f"status IN ({_sql_list(_SEND_STATUSES)})", name="ck_wa_campaign_send_status"
        ),
        sa.CheckConstraint(
            "cost_estimate IS NULL OR cost_estimate >= 0", name="ck_wa_campaign_send_cost"
        ),
    )
    op.create_index("ix_wa_campaign_send_tenant", "whatsapp_campaign_sends", ["tenant_id"])
    op.create_index(
        "ix_wa_campaign_send_campaign_status", "whatsapp_campaign_sends", ["campaign_id", "status"]
    )
    # The receipt handler's lookup.
    op.create_index(
        "ix_wa_campaign_send_wamid",
        "whatsapp_campaign_sends",
        ["wamid"],
        postgresql_where=sa.text("wamid IS NOT NULL"),
    )
    # The outbox mirror's lookup.
    op.create_index(
        "ix_wa_campaign_send_outbox",
        "whatsapp_campaign_sends",
        ["outbox_id"],
        postgresql_where=sa.text("outbox_id IS NOT NULL"),
    )
    _grant_standard("whatsapp_campaign_sends")
    op.execute(
        f"GRANT SELECT ({_cols(_WORKER_SEND_SELECT)}) "
        "ON whatsapp_campaign_sends TO qualify_webhook_worker;"
    )
    op.execute(
        f"GRANT UPDATE ({_cols(_WORKER_SEND_UPDATE)}) "
        "ON whatsapp_campaign_sends TO qualify_webhook_worker;"
    )
    _enable_tenant_rls("whatsapp_campaign_sends")

    # --- the outbox → send mirror ------------------------------------------------------
    op.execute(_MIRROR_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER wa_outbox_campaign_mirror
            AFTER UPDATE OF status ON whatsapp_outbox
            FOR EACH ROW
            WHEN (NEW.kind = 'campaign_send' AND NEW.status IS DISTINCT FROM OLD.status)
            EXECUTE FUNCTION wa_outbox_campaign_mirror();
        """
    )

    # --- whatsapp_phone_numbers: the template webhooks resolve by WABA -----------------
    op.execute("GRANT SELECT (waba_id) ON whatsapp_phone_numbers TO qualify_webhook_worker;")


def downgrade() -> None:
    op.execute("REVOKE SELECT (waba_id) ON whatsapp_phone_numbers FROM qualify_webhook_worker;")
    op.execute("DROP TRIGGER wa_outbox_campaign_mirror ON whatsapp_outbox;")
    op.execute("DROP FUNCTION wa_outbox_campaign_mirror();")

    op.drop_index("ix_wa_campaign_send_outbox", table_name="whatsapp_campaign_sends")
    op.drop_index("ix_wa_campaign_send_wamid", table_name="whatsapp_campaign_sends")
    op.drop_index("ix_wa_campaign_send_campaign_status", table_name="whatsapp_campaign_sends")
    op.drop_index("ix_wa_campaign_send_tenant", table_name="whatsapp_campaign_sends")
    op.drop_table("whatsapp_campaign_sends")
    op.drop_constraint("uq_wa_outbox_id_tenant", "whatsapp_outbox", type_="unique")

    op.drop_index("ix_wa_campaign_tenant", table_name="whatsapp_campaigns")
    op.drop_table("whatsapp_campaigns")
    op.drop_index("ix_wa_opt_in_tenant", table_name="whatsapp_opt_ins")
    op.drop_table("whatsapp_opt_ins")
    op.drop_index("ix_wa_template_meta_id", table_name="whatsapp_templates")
    op.drop_index("ix_wa_template_tenant", table_name="whatsapp_templates")
    op.drop_table("whatsapp_templates")
