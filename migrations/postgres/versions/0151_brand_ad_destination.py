"""Optional brand destination for new advertising pieces (m-24828975).

No backfill, default or rewrite of piece/copy approvals. Existing brand_kits RLS
and table-level application grants cover this nullable column unchanged. URL
validation belongs to the application; legacy brands keep NULL until configured.

Downgrade refuses to silently discard a configured destination. After explicit
operator resolution of those values it drops only the new column.
"""

import sqlalchemy as sa
from alembic import op

revision = "0151"
down_revision = "0150"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brand_kits", sa.Column("ads_destination_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.execute("""
      DO $$ BEGIN
        LOCK TABLE brand_kits IN ACCESS EXCLUSIVE MODE;
        IF EXISTS(SELECT 1 FROM brand_kits WHERE ads_destination_url IS NOT NULL) THEN
          RAISE EXCEPTION 'downgrade 0151 refused: brand advertising destinations remain'
            USING ERRCODE='23514';
        END IF;
      END $$;
    """)
    op.drop_column("brand_kits", "ads_destination_url")
