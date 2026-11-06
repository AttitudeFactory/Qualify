"""brand payment methods: how a business takes payment, for its WhatsApp menu and chat

Revision ID: 0134
Revises: 0133
Create Date: 2026-11-05

Ticket m-24955648 («WhatsApp: al terminar el pedido, el menú pregunta cómo pagar y envía
el QR o los datos de la forma elegida»), design `docs/opciones-conectar-sistema-de-
pedidos.md` §3.1 and UX spec `docs/ux-paso-de-pago.md` (founder decision D3: the methods
live in Qualify, per business). One row per method the owner offers:

- `name` («Pago móvil», ≤ 20 characters: it is a WhatsApp reply-button label);
- `currency` (`USD`, `VES`, `COP`, `USDT`… or empty);
- `instructions` (what the customer reads, the QR's caption; ≤ 900 characters because
  Qualify appends the total and the closing line and a caption stops at 1024);
- `pay_on_delivery` (cash or paid on arrival: no receipt is asked for);
- `qr_media_key` (the QR image in R2 under `t/{tenant}/whatsapp/payments/{brand}/…`,
  normalised like a chat photo), `active`, `position`.

One list feeds both the automatic menu and the chat picker
(`qualify_api.whatsapp.payments.active_payment_methods`).

**Assisted, never autonomous.** This table only says HOW to pay. Nothing here records a
payment, and Qualify never marks one as received: the owner or the cashier does.

**Shape.** `name_key` is the comparable form (`catalog.order.category_key`: case, accents
and spaces folded) and carries the uniqueness per brand, so «Pago Móvil» and «pago movil»
cannot both exist and a repeated import cannot duplicate. `external_code` is the client
system's code (Pedidos' `codigo`), unused until the import. `source` is the provenance of
the load: `manual` (the owner typed it) or `import` (read from the client's system; the
owner still activates each one). A method paid before delivery can only be active with
instructions or a QR (`ck_brand_payment_methods_active_has_content`): an active method
with nothing to send would leave the customer without a way to pay; a `pay_on_delivery`
one needs neither. At most 10 active per brand (the WhatsApp list limit) and no `[…]`
placeholder in the instructions are the service's rules (`whatsapp.payments`), not
CHECKs. No JSONB, nothing derived, nothing to backfill (every business starts empty).

**Tenancy.** `tenant_id` NOT NULL; composite FK `(brand_id, tenant_id) → brands (id,
tenant_id)` (`uq_ads_brand_tenant`, 0114), so a row can never point at another tenant's
brand; `qr_media_key` must start with the row's own tenant prefix. RLS ENABLE + FORCE
with the house NULLIF policy (R7).

**Grants.** `qualify_app`: SELECT, INSERT, UPDATE, DELETE (the owner's settings).
`qualify_admin`: SELECT. `qualify_webhook_worker` (BYPASSRLS, column grants only, as
0059/0128): SELECT on exactly `id, tenant_id, brand_id, name, currency, instructions,
qr_media_key, active, pay_on_delivery, position`, what the menu's payment step reads; it
filters by the phone row's tenant AND brand in code.

**Downgrade** drops the table (with its policy and grants). The QR objects in R2 are not
deleted by a downgrade (`whatsapp/payments/` is outside `PURGEABLE_ROOTS`).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0134"
down_revision = "0133"
branch_labels = None
depends_on = None

_TABLE = "brand_payment_methods"
_WORKER_COLUMNS = (
    "id",
    "tenant_id",
    "brand_id",
    "name",
    "currency",
    "instructions",
    "qr_media_key",
    "active",
    "pay_on_delivery",
    "position",
)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("qr_media_key", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("pay_on_delivery", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("position", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("external_code", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("created_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
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
            ["brand_id", "tenant_id"],
            ["brands.id", "brands.tenant_id"],
            name="fk_brand_payment_methods_brand_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("brand_id", "name_key", name="uq_brand_payment_methods_key"),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 20", name="ck_brand_payment_methods_name"
        ),
        sa.CheckConstraint("name_key <> ''", name="ck_brand_payment_methods_key"),
        sa.CheckConstraint("char_length(currency) <= 8", name="ck_brand_payment_methods_currency"),
        sa.CheckConstraint(
            "char_length(instructions) <= 900", name="ck_brand_payment_methods_instructions"
        ),
        sa.CheckConstraint(
            "qr_media_key IS NULL OR qr_media_key LIKE ('t/' || tenant_id::text || "
            "'/whatsapp/payments/%')",
            name="ck_brand_payment_methods_qr_key",
        ),
        sa.CheckConstraint(
            "NOT active OR pay_on_delivery OR btrim(instructions) <> '' "
            "OR qr_media_key IS NOT NULL",
            name="ck_brand_payment_methods_active_has_content",
        ),
        sa.CheckConstraint("position >= 0", name="ck_brand_payment_methods_position"),
        sa.CheckConstraint(
            "source IN ('manual', 'import')", name="ck_brand_payment_methods_source"
        ),
    )
    op.create_index("ix_brand_payment_methods_tenant", _TABLE, ["tenant_id"])
    op.create_index("ix_brand_payment_methods_brand", _TABLE, ["brand_id", "position"])
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {_TABLE}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {_TABLE} TO qualify_admin;")
    op.execute(
        f"GRANT SELECT ({', '.join(_WORKER_COLUMNS)}) ON {_TABLE} TO qualify_webhook_worker;"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT ({', '.join(_WORKER_COLUMNS)}) ON {_TABLE} FROM qualify_webhook_worker;"
    )
    op.drop_index("ix_brand_payment_methods_brand", table_name=_TABLE)
    op.drop_index("ix_brand_payment_methods_tenant", table_name=_TABLE)
    op.drop_table(_TABLE)
