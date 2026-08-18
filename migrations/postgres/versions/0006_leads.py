"""leads: public lead capture per tenant (funnel demo for small businesses)

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-14

The general leads plane of the CRM: the people a tenant has converted into contactable
leads, whatever the capture channel. Schema-wise its only dependency is `tenants.id` —
no FK to `brands`, `social_connections` or the inbox, because a lead arrives through a
public form, not through a connected account.

Decisions encoded here:

- What gets captured varies per tenant: the fixed columns are the invariant core
  (identity + consent + attribution), and `lead_form_settings.custom_fields` declares
  the tenant-specific questions whose answers land in `leads.extra` (JSONB). Promoting
  a hot key out of `extra` into a real column later is an ALTER, not a redesign.

- `UNIQUE(tenant_id, whatsapp_phone)` DOES carry `tenant_id`, unlike 0004's B1: a phone
  number IS a portable person identity (the opposite of an IGSID), and the same person
  must be able to be a lead of two different businesses. Dedup is per tenant, enforced
  at INSERT time with an idempotent upsert (same discipline as the house convention).
- Consent is a fact, not a flag: `consent_at` + `consent_policy_version` are NOT NULL,
  so a lead row cannot exist without recording when consent was given and which policy
  text it was given against (Ley 1581/habeas data auditability). A boolean column would
  allow a row that says "no" — that row must not exist at all.
- `lead_form_settings` is the server-side resolution of the public `?e=<tenant_id>`
  query param: an intake for a tenant with no ACTIVE settings row answers 404, so the
  public surface never confirms whether a tenant uuid exists. The param is only ever
  used to scope an RLS session, never trusted as authorization (C1 stays intact).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0006"
down_revision = "0005"
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
        "lead_form_settings",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("business_name", sa.Text(), nullable=False),
        # E.164. The wa.me handoff target — where the lead lands after submitting.
        sa.Column("whatsapp_phone", sa.Text(), nullable=False),
        # Optional prefilled-message template; `{name}` / `{promo}` placeholders.
        sa.Column("whatsapp_greeting", sa.Text(), nullable=True),
        # The active hook ("10% off this week"). Nullable: a form can run without one.
        sa.Column("promo_text", sa.Text(), nullable=True),
        sa.Column(
            "interest_options",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        # The exact legal text the form renders, per tenant: the applicable law follows
        # the tenant's country (habeas data CRBV art. 28/60 for VE, Ley 1581 for CO).
        sa.Column("consent_text", sa.Text(), nullable=False),
        # Stamped onto every lead at intake — see the consent decision above.
        sa.Column("consent_policy_version", sa.Text(), nullable=False),
        # Tenant-specific extra questions: [{key, label, options?, required?}, ...].
        # Answers land in `leads.extra` keyed by `key`.
        sa.Column(
            "custom_fields",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        # One public form per tenant. Multi-form (per brand/campaign) would relax this to
        # UNIQUE(tenant_id, slug) — a widening, safe to do later on a small table.
        sa.UniqueConstraint("tenant_id", name="uq_lead_form_settings_tenant"),
    )
    op.create_index("ix_lead_form_settings_tenant", "lead_form_settings", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON lead_form_settings TO qualify_app;")
    op.execute("GRANT SELECT ON lead_form_settings TO qualify_admin;")
    _enable_tenant_rls("lead_form_settings")

    op.create_table(
        "leads",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        # Normalized E.164 (service-side) — the dedup key within a tenant.
        sa.Column("whatsapp_phone", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("birthday", sa.Date(), nullable=True),
        sa.Column("interest", sa.Text(), nullable=True),
        # Declared by the person ("Instagram", "referral"); the utm_* columns carry what
        # the URL said. Both kept: they disagree often and the disagreement is signal.
        sa.Column("source_declared", sa.Text(), nullable=True),
        sa.Column("utm_source", sa.Text(), nullable=True),
        sa.Column("utm_medium", sa.Text(), nullable=True),
        sa.Column("utm_campaign", sa.Text(), nullable=True),
        sa.Column("utm_content", sa.Text(), nullable=True),
        sa.Column("utm_term", sa.Text(), nullable=True),
        # Answers to the tenant's `custom_fields`, keyed by field key. Upserts merge
        # (`extra || excluded.extra`) so a later submission never erases earlier answers.
        sa.Column("extra", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_policy_version", sa.Text(), nullable=False),
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
        # Per-tenant dedup — deliberately WITH tenant_id, see the module docstring.
        sa.UniqueConstraint("tenant_id", "whatsapp_phone", name="uq_lead_tenant_phone"),
    )
    op.create_index("ix_lead_tenant", "leads", ["tenant_id"])
    op.create_index("ix_lead_tenant_created", "leads", ["tenant_id", "created_at"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON leads TO qualify_app;")
    op.execute("GRANT SELECT ON leads TO qualify_admin;")
    _enable_tenant_rls("leads")


def downgrade() -> None:
    op.drop_index("ix_lead_tenant_created", table_name="leads")
    op.drop_index("ix_lead_tenant", table_name="leads")
    op.drop_table("leads")
    op.drop_index("ix_lead_form_settings_tenant", table_name="lead_form_settings")
    op.drop_table("lead_form_settings")
