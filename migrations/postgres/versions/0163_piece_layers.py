"""piece_layers: the text layer of each slide of an image or carousel piece (m-25017278,
ADR 49 §2.1, epic m-25017272 «Imagen y carrusel»)

Revision ID: 0163
Revises: 0162
Create Date: 2026-11-13

## Why this exists

ADR 49 (signed 2026-11-13) splits the image and the carousel into four stages: Seedream
makes the base photograph, Claude writes a text layer over it (`LayerSpec`, m-25017283),
Remotion composes (m-25017285) and Claude checks the result once (m-25017287). The layer is
the input of the composition, so it needs a home that survives render retries, versions
with `piece_versions` and carries its own provenance and RLS — option A of ADR 49 §4
(`template_runs.props`, `image_assets.params` and `CopyPayload` were rejected there).

This revision only creates the table. It ships EMPTY: no backfill (pieces made before ADR
49 have no stored base photo and are never recomposed, §8.5) and no reader or writer in the
pipeline yet — m-25017283 is the first writer.

## Columns (ADR 49 §2.1)

- `tenant_id` + RLS (ENABLE + FORCE + the `NULLIF` policy), in this revision.
- `brand_id` → `brands (id, tenant_id)`: a layer never crosses businesses, even by a bug.
- `draft_id` → `content_drafts (id, tenant_id)` and `version_id` → `piece_versions
  (id, tenant_id)`, both `ON DELETE CASCADE`: deleting a piece or one of its versions takes
  its layers with it. `piece_versions` had no `UNIQUE (id, tenant_id)` to point a composite
  key at; this revision adds it (`uq_piece_versions_id_tenant`, dropped on downgrade).
- `position` 0..9: one layer per slide (the 10-slide cap of decision #14) and per version.
- `layout_id`, `layout_version`, `spec` (JSONB object), `spec_sha256`: the content and its
  fingerprint for the render key of §2.2.
- The base photo the layer was written over, one of two kinds (never both):
  `base_asset_id` → `image_assets(id)` (the stored Seedream photo; `ON DELETE SET NULL`,
  so purging the photo keeps the layer's history), or `base_media_ref` — the Galería
  medium as `gallery_piece.py` names it (`n:<business_media id>` / `p:<product_media id>`),
  with NO foreign key: ADR 49 §2.6 keeps the medium's id apart so that releasing the
  reference never erases the history; the lock on deleting the medium is
  `piece_media_refs` (m-25017286), not this table.
- `source` (`model` · `owner_edit` · `owner_photo`), `parent_layer_id` (the layer it was
  derived from; `ON DELETE SET NULL`), `created_by` → `users (id, tenant_id)` (required for
  an owner's edit, the manual-input exception of 2026-11-04 applies only to the fields the
  owner typed).
- Provenance: `model_id`, `prompt_version` (required when `source='model'`) and
  `pipeline_version`.
- `UNIQUE (tenant_id, version_id, position)`: a retry never creates a second layer.

Grants: `qualify_app` SELECT + INSERT (a layer is never edited in place: a change is a new
row with `parent_layer_id`, §2.1), `qualify_admin` SELECT. Nothing for the worker roles:
generation writes through `tenant_session`.
"""

from alembic import op

revision = "0163"
down_revision = "0162"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE piece_versions
      ADD CONSTRAINT uq_piece_versions_id_tenant UNIQUE (id, tenant_id);

    CREATE TABLE piece_layers (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        brand_id uuid NOT NULL,
        draft_id uuid NOT NULL,
        version_id uuid NOT NULL,
        position integer NOT NULL CHECK (position BETWEEN 0 AND 9),
        layout_id text NOT NULL CHECK (layout_id ~ '^[a-z0-9_]{1,64}$'),
        layout_version integer NOT NULL CHECK (layout_version > 0),
        spec jsonb NOT NULL CHECK (jsonb_typeof(spec) = 'object'),
        spec_sha256 text NOT NULL CHECK (spec_sha256 ~ '^[a-f0-9]{64}$'),
        base_asset_id uuid REFERENCES image_assets(id) ON DELETE SET NULL,
        base_media_ref text CHECK (
            base_media_ref ~ '^[np]:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        ),
        source text NOT NULL CHECK (source IN ('model', 'owner_edit', 'owner_photo')),
        parent_layer_id uuid REFERENCES piece_layers(id) ON DELETE SET NULL,
        created_by uuid,
        model_id text,
        prompt_version text,
        pipeline_version text NOT NULL CHECK (char_length(pipeline_version) BETWEEN 1 AND 64),
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_piece_layers_version_position UNIQUE (tenant_id, version_id, position),
        CONSTRAINT uq_piece_layers_id_tenant UNIQUE (id, tenant_id),
        CONSTRAINT fk_piece_layers_brand FOREIGN KEY (brand_id, tenant_id)
            REFERENCES brands(id, tenant_id),
        CONSTRAINT fk_piece_layers_draft FOREIGN KEY (draft_id, tenant_id)
            REFERENCES content_drafts(id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT fk_piece_layers_version FOREIGN KEY (version_id, tenant_id)
            REFERENCES piece_versions(id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT fk_piece_layers_created_by FOREIGN KEY (created_by, tenant_id)
            REFERENCES users(id, tenant_id),
        CONSTRAINT ck_piece_layers_one_base
            CHECK (base_asset_id IS NULL OR base_media_ref IS NULL),
        CONSTRAINT ck_piece_layers_model_provenance
            CHECK (source <> 'model' OR (model_id IS NOT NULL AND prompt_version IS NOT NULL)),
        CONSTRAINT ck_piece_layers_owner_edit
            CHECK (source <> 'owner_edit' OR (created_by IS NOT NULL
                                               AND parent_layer_id IS NOT NULL))
    );
    CREATE INDEX ix_piece_layers_draft ON piece_layers (tenant_id, draft_id);
    CREATE INDEX ix_piece_layers_version ON piece_layers (version_id);
    CREATE INDEX ix_piece_layers_base_asset ON piece_layers (base_asset_id)
      WHERE base_asset_id IS NOT NULL;
    CREATE INDEX ix_piece_layers_parent ON piece_layers (parent_layer_id)
      WHERE parent_layer_id IS NOT NULL;

    ALTER TABLE piece_layers ENABLE ROW LEVEL SECURITY;
    ALTER TABLE piece_layers FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON piece_layers
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    GRANT SELECT, INSERT ON piece_layers TO qualify_app;
    GRANT SELECT ON piece_layers TO qualify_admin;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE piece_layers")
    op.execute("ALTER TABLE piece_versions DROP CONSTRAINT uq_piece_versions_id_tenant")
