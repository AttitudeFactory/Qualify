"""WhatsApp chat shortcuts: the business's «promoción de la semana» and the number's map
point (m-24945889)

Revision ID: 0140
Revises: 0139
Create Date: 2026-11-08

Ticket m-24945889 («WhatsApp: atajos en el chat — promoción de la semana, cómo llegar y
piezas en video»), spec `docs/ux-whatsapp-atajos.md`.

**`whatsapp_weekly_promotions`** — at most ONE piece per business marked «Promoción de
la semana» (`uq_wa_weekly_promotion_brand`: marking another replaces the row, so the
previous one is unmarked in the same statement). The mark does not expire by itself
(founder decision); `marked_at` / `marked_by` say when and who. While a piece is marked it
is HELD by the ADR 39 retention exactly like a scheduled piece
(`creative.retention.read_facts`). Composite FKs keep every row inside its tenant:
`(brand_id, tenant_id) → brands (id, tenant_id)` (`uq_ads_brand_tenant`, 0114) and
`(tenant_id, draft_id) → content_drafts (tenant_id, id)` (`uq_content_drafts_tenant_id`,
0096), both `ON DELETE CASCADE` (a deleted piece or business has no promotion). RLS
ENABLE + FORCE with the house NULLIF policy (R7). Grants: `qualify_app` SELECT, INSERT,
UPDATE, DELETE; `qualify_admin` SELECT. No webhook-worker access.

**`whatsapp_phone_numbers`** gains the number's map point for «Cómo llegar»:
`location_latitude` / `location_longitude` (`numeric(9,6)`, both or neither, within
±90 / ±180 — `ck_wa_phone_location`), the `location_name` / `location_address` a Meta
location message carries (the address is also the text fallback when there is no point),
and `location_updated_at`. Owner input («Marca tu local en el mapa»), so no provenance.
The 0057 table-level grants cover the new columns (`qualify_app` SELECT/UPDATE); the
webhook worker's column grants on this table are unchanged.

**Downgrade** drops the table and the columns: the marks and points are owner settings,
re-enterable, nothing derived.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0140"
down_revision = "0139"
branch_labels = None
depends_on = None

_PROMO = "whatsapp_weekly_promotions"
_PHONE = "whatsapp_phone_numbers"
_LOCATION_COLUMNS = (
    "location_latitude",
    "location_longitude",
    "location_name",
    "location_address",
    "location_updated_at",
)


def upgrade() -> None:
    op.create_table(
        _PROMO,
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("draft_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "marked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("marked_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.ForeignKeyConstraint(
            ["brand_id", "tenant_id"],
            ["brands.id", "brands.tenant_id"],
            name="fk_wa_weekly_promotion_brand_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "draft_id"],
            ["content_drafts.tenant_id", "content_drafts.id"],
            name="fk_wa_weekly_promotion_draft_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("brand_id", name="uq_wa_weekly_promotion_brand"),
    )
    op.create_index("ix_wa_weekly_promotion_tenant", _PROMO, ["tenant_id"])
    op.create_index("ix_wa_weekly_promotion_draft", _PROMO, ["draft_id"])
    op.execute(f"ALTER TABLE {_PROMO} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_PROMO} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {_PROMO}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_PROMO} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {_PROMO} TO qualify_admin;")

    op.add_column(_PHONE, sa.Column("location_latitude", sa.Numeric(9, 6), nullable=True))
    op.add_column(_PHONE, sa.Column("location_longitude", sa.Numeric(9, 6), nullable=True))
    op.add_column(_PHONE, sa.Column("location_name", sa.Text(), nullable=True))
    op.add_column(_PHONE, sa.Column("location_address", sa.Text(), nullable=True))
    op.add_column(
        _PHONE, sa.Column("location_updated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_wa_phone_location",
        _PHONE,
        "(location_latitude IS NULL AND location_longitude IS NULL) OR "
        "(location_latitude IS NOT NULL AND location_longitude IS NOT NULL "
        "AND location_latitude BETWEEN -90 AND 90 AND location_longitude BETWEEN -180 AND 180)",
    )
    op.create_check_constraint(
        "ck_wa_phone_location_text",
        _PHONE,
        "(location_name IS NULL OR char_length(location_name) <= 100) AND "
        "(location_address IS NULL OR char_length(location_address) <= 256)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_wa_phone_location_text", _PHONE, type_="check")
    op.drop_constraint("ck_wa_phone_location", _PHONE, type_="check")
    for column in reversed(_LOCATION_COLUMNS):
        op.drop_column(_PHONE, column)
    op.drop_index("ix_wa_weekly_promotion_draft", table_name=_PROMO)
    op.drop_index("ix_wa_weekly_promotion_tenant", table_name=_PROMO)
    op.drop_table(_PROMO)
