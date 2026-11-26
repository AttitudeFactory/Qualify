"""subscription_payments: what the team was paid for a subscription's month (m-25129422)

Revision ID: 0187
Revises: 0186
Create Date: 2026-11-26

`plans/billing.py::charges_for_month` says what a subscription owes in a month (D14–D19,
`docs/modelo-cobro-generacion.md`); until now nothing recorded what it paid, so nothing
could be reconciled. Collection stays by hand (D19): the team sends the payment details by
WhatsApp or email (`just plan-invoice`) and records each payment it receives
(`just plan-payment`); `just plan-report` puts expected, paid and pending side by side.
Packs keep their own payment row (`creation_payments`, 0095).

The table is shaped so a payment provider's webhook (KunfuPay, dLocal, Mercado Pago —
epic m-25120476) can later insert into it idempotently with
no schema change: `provider` + `provider_payment_id` UNIQUE (`INSERT … ON CONFLICT DO
NOTHING`), the raw payload kept to re-parse, and our own `reference`
(`<subscription_id>:YYYY-MM`) the provider echoes back. No provider is built here; a
manual payment is `provider = 'manual'` with the payment reference as its id.

**Deliberate exception to "every table has `tenant_id`" (ADR 43 §2.8), exactly like
`subscriptions` and `subscription_cost_alerts` (0093):** a payment belongs to the
subscription, which spans tenants. Isolated by GRANT: `ENABLE` + `FORCE ROW LEVEL
SECURITY` with no policy (every role without BYPASSRLS sees zero rows) and grants only to
`qualify_admin` (SELECT, INSERT — never edited). No request path can read an amount
(decision 8, D19). A future webhook role needs its own grant in its own revision.

Provenance: `provider` + `provider_payment_id` (+ `raw_payload` for a provider),
`recorded_by`, and `pipeline_version` (which writer produced the row).

**Downgrade** drops the table (the record of monthly payments is lost).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0187"
down_revision = "0186"
branch_labels = None
depends_on = None

_METHODS = "('transfer','zelle','mobile_payment','payment_link','cash','other')"


def upgrade() -> None:
    op.create_table(
        "subscription_payments",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id"),
            nullable=False,
        ),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("usd_paid", sa.Numeric(10, 2), nullable=False),
        sa.Column("local_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("local_currency", sa.Text(), nullable=True),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("payment_ref", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("provider", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("provider_payment_id", sa.Text(), nullable=False),
        sa.Column("raw_payload", JSONB(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("usd_paid > 0", name="ck_subscription_payments_usd"),
        sa.CheckConstraint(
            "(local_amount IS NULL) = (local_currency IS NULL)"
            " AND (local_amount IS NULL OR local_amount > 0)"
            " AND (local_currency IS NULL OR local_currency ~ '^[A-Z]{3}$')",
            name="ck_subscription_payments_local",
        ),
        sa.CheckConstraint(f"method IN {_METHODS}", name="ck_subscription_payments_method"),
        sa.CheckConstraint("provider ~ '^[a-z_]+$'", name="ck_subscription_payments_provider"),
        sa.CheckConstraint(
            "btrim(provider_payment_id) <> '' AND btrim(recorded_by) <> ''"
            " AND btrim(reference) <> ''",
            name="ck_subscription_payments_who",
        ),
        sa.CheckConstraint(
            "date_trunc('month', period_month) = period_month",
            name="ck_subscription_payments_month",
        ),
        sa.UniqueConstraint(
            "provider", "provider_payment_id", name="uq_subscription_payments_provider"
        ),
    )
    op.create_index(
        "ix_subscription_payments_month",
        "subscription_payments",
        ["subscription_id", "period_month"],
    )
    op.execute("GRANT SELECT, INSERT ON subscription_payments TO qualify_admin;")
    # ADR 43 §2.8: RLS on, forced, and no policy — only BYPASSRLS (`qualify_admin`) sees rows
    op.execute("ALTER TABLE subscription_payments ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE subscription_payments FORCE ROW LEVEL SECURITY;")
    op.execute("REVOKE ALL ON subscription_payments FROM PUBLIC;")


def downgrade() -> None:
    op.drop_index("ix_subscription_payments_month", table_name="subscription_payments")
    op.drop_table("subscription_payments")
