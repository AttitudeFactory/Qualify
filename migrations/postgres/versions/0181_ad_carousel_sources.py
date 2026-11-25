"""ad_unpublished_sources: a catalog carousel has no piece (m-25113484)

Revision ID: 0181
Revises: 0180
Create Date: 2026-11-24

A carousel ad whose cards are Catálogo products is approved and prepared through the same
immutable approval (`ad_unpublished_sources`) and upload intents (`ad_unpublished_uploads`,
`asset_id` = the `product_media` photo id, no FK by design since 0150) as the ad from a
piece. It has no `content_drafts` row, so `draft_id` becomes nullable, but ONLY for the
carousel pipeline: every other row still needs its piece. Provenance of a carousel row:
the product and photo ids plus their digests in `source`, and `pipeline_version`.

No new table, so RLS, grants, the immutability trigger and the purge grants are 0150's.
Downgrade deletes carousel approvals first (they cannot satisfy NOT NULL); the promotions
they created stay in `ad_promotions`.
"""

from alembic import op

revision = "0181"
down_revision = "0180"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE ad_unpublished_sources ALTER COLUMN draft_id DROP NOT NULL;
    ALTER TABLE ad_unpublished_sources ADD CONSTRAINT ck_ad_unpublished_sources_piece
      CHECK (draft_id IS NOT NULL OR pipeline_version = 'ad-catalog-carousel-v1');
    """)


def downgrade() -> None:
    op.execute("""
    DELETE FROM ad_unpublished_sources WHERE draft_id IS NULL;
    ALTER TABLE ad_unpublished_sources DROP CONSTRAINT ck_ad_unpublished_sources_piece;
    ALTER TABLE ad_unpublished_sources ALTER COLUMN draft_id SET NOT NULL;
    """)
