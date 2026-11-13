"""piece_base_photos: the raw Seedream photograph each still was composed over
(m-25017279, ADR 49 §2 item 1 and §2.1)

Revision ID: 0165
Revises: 0164
Create Date: 2026-11-14

## Why this exists

ADR 49 keeps the base photograph of every advertising image and generated gallery slide,
so the text layer (`piece_layers`, 0163) can point at it and a later re-compose reuses it
without paying Seedream again. It is its OWN table — not an `image_assets` row — so that no
reader of a piece's outputs (the cover, the media list, the carousel children, the
Planificador, the export, the WhatsApp attachment…) can ever see a base: there is nothing
for them to filter (architecture review of m-25017279).

## Columns

- `tenant_id` + RLS (ENABLE + FORCE + the `NULLIF` policy, the 0163 shape), grants like
  0163 (`qualify_app` SELECT + INSERT, `qualify_admin` SELECT).
- `brand_id` → `brands (id, tenant_id)`; `draft_id` → `content_drafts (id, tenant_id)` and
  `version_id` → `piece_versions (id, tenant_id)` with `ON DELETE CASCADE`.
- `position` 0..9 and `UNIQUE (tenant_id, version_id, position)`: one base per slide and
  version — the base is written once, with its version (a completed version is immutable).
- `state`: `stored` (with `object_key`, `sha256`, `content_type`) or `missing` (the base was
  paid for but R2 did not keep it; `missing_reason` says why). A `missing` row is what a
  later re-compose reads to offer only «Crear otra».
- `width`, `height` (from the image header, NULL when unreadable), `rendered_prompt`,
  `model_id`, `provider`, `prompt_compiler_version`, `pipeline_version`: provenance.

## `piece_layers.base_asset_id`

0163 pointed it at `image_assets (id, tenant_id)`; it now points here, composite and
`ON DELETE SET NULL (base_asset_id)`. Both tables are empty in production. The
`uq_image_assets_id_tenant` unique of 0163 is no longer used by any key; it is left as it is
(dropping it is a decision of its own). The downgrade restores 0163's key exactly.

Retention (ADR 39): a stored base's object lives under
`t/{tenant}/generated/{draft_id}/r{n}/base/`, inside the folder the purge deletes whole;
its row stays, as the other rows of a purged piece do. No backfill (ADR 49 §8.5).
"""

from alembic import op

revision = "0165"
down_revision = "0164"
branch_labels = None
depends_on = None


#: Repointing `piece_layers`' key takes a short ACCESS EXCLUSIVE lock on `image_assets` (a
#: hot table) and `piece_layers`: fail fast behind a long transaction instead of queueing
#: every reader of the app. A failed migrate stops `deploy/server-deploy.sh` before `up`,
#: so the previous release stays live; the deploy is simply run again.
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute("""
    CREATE TABLE piece_base_photos (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        brand_id uuid NOT NULL,
        draft_id uuid NOT NULL,
        version_id uuid NOT NULL,
        position integer NOT NULL CHECK (position BETWEEN 0 AND 9),
        state text NOT NULL CHECK (state IN ('stored', 'missing')),
        object_key text,
        sha256 text CHECK (sha256 ~ '^[a-f0-9]{64}$'),
        content_type text CHECK (content_type IN ('image/jpeg', 'image/png', 'image/webp')),
        width integer CHECK (width > 0),
        height integer CHECK (height > 0),
        rendered_prompt text NOT NULL,
        model_id text NOT NULL CHECK (char_length(model_id) BETWEEN 1 AND 200),
        provider text NOT NULL CHECK (char_length(provider) BETWEEN 1 AND 64),
        prompt_compiler_version integer NOT NULL CHECK (prompt_compiler_version >= 0),
        pipeline_version text NOT NULL CHECK (char_length(pipeline_version) BETWEEN 1 AND 64),
        missing_reason text CHECK (char_length(missing_reason) <= 200),
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_piece_base_photos_position UNIQUE (tenant_id, version_id, position),
        CONSTRAINT uq_piece_base_photos_id_tenant UNIQUE (id, tenant_id),
        CONSTRAINT fk_piece_base_photos_brand FOREIGN KEY (brand_id, tenant_id)
            REFERENCES brands(id, tenant_id),
        CONSTRAINT fk_piece_base_photos_draft FOREIGN KEY (draft_id, tenant_id)
            REFERENCES content_drafts(id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT fk_piece_base_photos_version FOREIGN KEY (version_id, tenant_id)
            REFERENCES piece_versions(id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT ck_piece_base_photos_state CHECK (
            (state = 'stored' AND object_key IS NOT NULL AND sha256 IS NOT NULL
             AND content_type IS NOT NULL AND missing_reason IS NULL)
            OR (state = 'missing' AND object_key IS NULL AND missing_reason IS NOT NULL)
        ),
        -- inside the piece's own folder: R2 (`t/…`) or a dev store without R2 (`generated/…`)
        CONSTRAINT ck_piece_base_photos_key CHECK (
            object_key IS NULL
            OR (
                position('..' in object_key) = 0
                AND (
                    object_key LIKE 't/' || tenant_id::text || '/generated/'
                        || draft_id::text || '/%'
                    OR object_key LIKE 'generated/' || tenant_id::text || '/'
                        || draft_id::text || '/%'
                )
            )
        )
    );
    CREATE INDEX ix_piece_base_photos_draft ON piece_base_photos (tenant_id, draft_id);
    -- the version cascade's lookup (the unique above leads with tenant_id, version_id)

    ALTER TABLE piece_base_photos ENABLE ROW LEVEL SECURITY;
    ALTER TABLE piece_base_photos FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON piece_base_photos
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    GRANT SELECT, INSERT ON piece_base_photos TO qualify_app;
    GRANT SELECT ON piece_base_photos TO qualify_admin;

    ALTER TABLE piece_layers DROP CONSTRAINT fk_piece_layers_base_asset;
    ALTER TABLE piece_layers ADD CONSTRAINT fk_piece_layers_base_asset
      FOREIGN KEY (base_asset_id, tenant_id)
      REFERENCES piece_base_photos(id, tenant_id) ON DELETE SET NULL (base_asset_id);
    """)


def downgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute("""
    ALTER TABLE piece_layers DROP CONSTRAINT fk_piece_layers_base_asset;
    -- a layer's base pointed at a row that goes away with this table
    UPDATE piece_layers SET base_asset_id = NULL WHERE base_asset_id IS NOT NULL;
    ALTER TABLE piece_layers ADD CONSTRAINT fk_piece_layers_base_asset
      FOREIGN KEY (base_asset_id, tenant_id)
      REFERENCES image_assets(id, tenant_id) ON DELETE SET NULL (base_asset_id);
    DROP TABLE piece_base_photos;
    """)
