"""image_assets.role: the stored base photo of a still, hidden from every ordinary read
(m-25017279, ADR 49 §2 item 1 and §2.1)

Revision ID: 0164
Revises: 0163
Create Date: 2026-11-14

## Why this exists

ADR 49 keeps the raw Seedream photograph each image or generated gallery slide is composed
over — «con su fila en `image_assets`» — so that the text layer (`piece_layers.base_asset_id`,
0163) can point at it and a later re-compose reuses it without paying Seedream again. Until
now `image_assets` held only a piece's outputs, and some forty readers (the draft cover,
the media list, the carousel children, the Planificador, the export, the WhatsApp
attachment…) treat every row of a version as an output.

## What it does

- `role text NOT NULL DEFAULT 'output'`, `CHECK (role IN ('output', 'base'))`. Every
  existing row is an output; the constant default makes the column a catalog-only change
  (no table rewrite), and the CHECK scans the table once under the ALTER's lock — a few
  rows per generated piece, well under a second.
- The table's one `tenant_isolation` policy gains a second condition (ANDed with the same
  `NULLIF` tenant check, so the inventory of `test_rls_policy_shape.py` — exactly one
  isolation policy, always `NULLIF` — still holds): a `role='base'` row is invisible, and
  cannot be written, unless the transaction set `app.base_photos = 'on'`
  (`creative.base_photos.base_photos_visible`). A base is also only ever visible to its
  own business. Being a database rule, no reader —
  present or future — has to remember a filter to keep a base out of a cover, a carousel
  or a publication. `qualify_admin` (BYPASSRLS) is not affected: its readers of this table
  are the retention purge (which wants every file of the piece) and the warning mail's
  thumbnail (only `https://` URLs; a base is an R2 key). Foreign keys and cascades ignore
  RLS, so `piece_layers.base_asset_id` and the version cascade work as for any row.
- `uq_image_assets_base_position`: at most one base per version and position — the base
  of a slide is written once (a completed version is immutable; a retry adds nothing).

Retention (ADR 39): a base's object lives under `t/{tenant}/generated/{draft_id}/r{n}/base/`,
inside the folder the purge deletes whole (`retention.piece_prefix`); its row stays with
the piece's other rows, as provenance.

No backfill: pieces made before this revision have no stored base (ADR 49 §8.5).
"""

from alembic import op

revision = "0164"
down_revision = "0163"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE image_assets
      ADD COLUMN role text NOT NULL DEFAULT 'output'
        CONSTRAINT ck_image_assets_role CHECK (role IN ('output', 'base'));
    CREATE UNIQUE INDEX uq_image_assets_base_position
      ON image_assets (tenant_id, version_id, position) WHERE role = 'base';
    ALTER POLICY tenant_isolation ON image_assets
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
             AND (role <> 'base' OR current_setting('app.base_photos', true) = 'on'))
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
                  AND (role <> 'base' OR current_setting('app.base_photos', true) = 'on'));
    """)


def downgrade() -> None:
    # back to 0009's policy, exactly
    op.execute("""
    ALTER POLICY tenant_isolation ON image_assets
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    """)
    op.execute("DROP INDEX uq_image_assets_base_position")
    # a base row would lose its meaning without its column: none survive the downgrade
    op.execute("DELETE FROM image_assets WHERE role = 'base'")
    op.execute("ALTER TABLE image_assets DROP COLUMN role")
