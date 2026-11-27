"""piece_story_covers: the automatic 9:16 cover of a historia's video (m-25142900, epic
m-25130273 N1)

Revision ID: 0191
Revises: 0190
Create Date: 2026-11-27

## Why this exists

A story ad of a video needs a 9:16 image as its thumbnail (`video_data.image_hash`), and
until now only a 9:16 image of the same version could be it: every video historia without
one was blocked (`video_without_cover`). The creative-worker now takes one frame of the
video (`creative.story_covers`) and keeps it here.

It is its OWN table — not an `image_assets` row — for the reason 0165 gives: no reader of a
piece's outputs (the gallery, the media list, the Planificador, the export, publishing)
may ever see the cover as one more file of the piece. Only the story ad's readers union it
in (`creative.story_covers.PIECE_FILES`).

## Columns

- `tenant_id` + RLS (ENABLE + FORCE + the `NULLIF` policy); `qualify_app` SELECT + INSERT,
  `qualify_admin` SELECT (the worker's discovery of businesses with work to do).
- `draft_id` → `content_drafts (id, tenant_id)`, `version_id` → `piece_versions (id,
  tenant_id)`, `source_asset_id` → `image_assets (id, tenant_id)` (the video the frame was
  taken from), all `ON DELETE CASCADE`: a regeneration that replaces the video's row takes
  its cover with it, and the new video gets its own.
- `UNIQUE (tenant_id, source_asset_id)`: one cover per video file — the worker inserts
  `ON CONFLICT DO NOTHING`, so a second pass never makes a duplicate.
- `state`: `stored` (with `object_key`, `content_type`, `width`, `height`) or `failed` (the
  video gave no frame; `failure_reason`): a failed file is not tried again every minute.
- `pipeline_version`: provenance (which step, which frame, how encoded). No model, no
  vendor, no cost: ffmpeg in the worker.

Retention (ADR 39): the cover's object is written next to its video
(`<video folder>/story-cover-<id>.jpg`), so it lives and is purged with it; `media_purged_at`
already blocks the story ad before any reader looks at a cover. No backfill here: the
worker's pass makes the covers of the historias already approved.
"""

from alembic import op

revision = "0191"
down_revision = "0190"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE piece_story_covers (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        draft_id uuid NOT NULL,
        version_id uuid NOT NULL,
        source_asset_id uuid NOT NULL,
        state text NOT NULL CHECK (state IN ('stored', 'failed')),
        object_key text,
        content_type text CHECK (content_type = 'image/jpeg'),
        width integer CHECK (width > 0),
        height integer CHECK (height > 0),
        pipeline_version text NOT NULL CHECK (char_length(pipeline_version) BETWEEN 1 AND 64),
        failure_reason text CHECK (char_length(failure_reason) <= 200),
        created_at timestamptz NOT NULL DEFAULT now(),
        CONSTRAINT uq_piece_story_covers_source UNIQUE (tenant_id, source_asset_id),
        CONSTRAINT fk_piece_story_covers_draft FOREIGN KEY (draft_id, tenant_id)
            REFERENCES content_drafts(id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT fk_piece_story_covers_version FOREIGN KEY (version_id, tenant_id)
            REFERENCES piece_versions(id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT fk_piece_story_covers_source FOREIGN KEY (source_asset_id, tenant_id)
            REFERENCES image_assets(id, tenant_id) ON DELETE CASCADE,
        CONSTRAINT ck_piece_story_covers_state CHECK (
            (state = 'stored' AND object_key IS NOT NULL AND content_type IS NOT NULL
             AND width IS NOT NULL AND height IS NOT NULL AND failure_reason IS NULL)
            OR (state = 'failed' AND object_key IS NULL AND failure_reason IS NOT NULL)
        ),
        -- 9:16 exactly: the story ad's rule (`ads.story_readiness.VERTICAL`)
        CONSTRAINT ck_piece_story_covers_vertical CHECK (width * 16 = height * 9),
        CONSTRAINT ck_piece_story_covers_key CHECK (
            object_key IS NULL
            OR (position('..' in object_key) = 0
                AND object_key LIKE 't/' || tenant_id::text || '/%')
        )
    );
    CREATE INDEX ix_piece_story_covers_version
      ON piece_story_covers (tenant_id, draft_id, version_id);
    CREATE INDEX ix_piece_story_covers_parent_version ON piece_story_covers (version_id);

    ALTER TABLE piece_story_covers ENABLE ROW LEVEL SECURITY;
    ALTER TABLE piece_story_covers FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON piece_story_covers
      USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
    GRANT SELECT, INSERT ON piece_story_covers TO qualify_app;
    GRANT SELECT ON piece_story_covers TO qualify_admin;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE piece_story_covers;")
