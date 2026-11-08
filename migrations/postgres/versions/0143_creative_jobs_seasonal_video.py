"""creative_jobs for seasonal AI videos: a job keyed by a seasonal medium, not a draft
(m-24976893, on 0142's `brand_seasonal_media`).

A seasonal AI video (Seedance, run by `creative-worker` under ADR 41's vendor slots,
NOT by `media-worker`) has no `content_drafts` row. So `creative_jobs` gains:

- `kind = 'seasonal_video'` in `ck_creative_jobs_kind`;
- `draft_id` becomes NULLable; `seasonal_media_id uuid` + `attempt int` are added, with
  the FK `(tenant_id, seasonal_media_id)` → `brand_seasonal_media (tenant_id, id)` (ON
  DELETE CASCADE, like the draft FK) — which needs `uq_brand_seasonal_media_tenant_id`;
- `ck_creative_jobs_subject`: exactly ONE of `draft_id` / `seasonal_media_id` is set, and
  `attempt` is set iff `seasonal_media_id` is (1–3, the library's «Pedir otro» cap);
  `ck_creative_jobs_seasonal_kind`: a seasonal job is `seasonal_video` and only it;
- idempotency: `uq_creative_jobs_seasonal` UNIQUE `(tenant_id, seasonal_media_id,
  attempt)` WHERE `seasonal_media_id IS NOT NULL` (one paid call per medium attempt).
  The draft side keeps `uq_creative_jobs_step` (0099) as it is: a seasonal row has
  `draft_id` NULL, and NULLs never collide in a UNIQUE constraint, so it binds draft
  jobs exactly as before and nothing seasonal.

Worker grants: NONE added. `qualify_creative_worker` reads the queue columns only and
never `draft_id` (0096, ADR 41: «a new GRANT to this role is a change to ADR 41»); the
seasonal subject is its twin and stays tenant-side (`tenant_session`), so the claim, the
slot cap and the lease work unchanged on a seasonal row (`kind` is already readable).
`qualify_app` holds table-level SELECT/INSERT, which covers the new columns.

`creative_pipeline_steps` (0098) is keyed by the draft and is NOT extended: a seasonal
video has no pipeline phases there.

Downgrade refuses while a seasonal job exists (deleting paid-task provenance silently is
not a rollback), then restores every constraint and drops the columns.
"""

from alembic import op

revision = "0143"
down_revision = "0142"
branch_labels = None
depends_on = None

JOBS = "creative_jobs"
OLD_KINDS = "('preview', 'final', 'presenter', 'carousel_scene')"
NEW_KINDS = "('preview', 'final', 'presenter', 'carousel_scene', 'seasonal_video')"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE brand_seasonal_media
            ADD CONSTRAINT uq_brand_seasonal_media_tenant_id UNIQUE (tenant_id, id);

        ALTER TABLE {JOBS} DROP CONSTRAINT ck_creative_jobs_kind;
        ALTER TABLE {JOBS} ADD CONSTRAINT ck_creative_jobs_kind CHECK (kind IN {NEW_KINDS});

        ALTER TABLE {JOBS} ALTER COLUMN draft_id DROP NOT NULL;
        ALTER TABLE {JOBS} ADD COLUMN seasonal_media_id uuid;
        ALTER TABLE {JOBS} ADD COLUMN attempt integer;
        ALTER TABLE {JOBS} ADD CONSTRAINT fk_creative_jobs_seasonal_media_tenant
            FOREIGN KEY (tenant_id, seasonal_media_id)
            REFERENCES brand_seasonal_media (tenant_id, id) ON DELETE CASCADE;
        ALTER TABLE {JOBS} ADD CONSTRAINT ck_creative_jobs_subject CHECK (
            num_nonnulls(draft_id, seasonal_media_id) = 1
            AND (attempt IS NULL) = (seasonal_media_id IS NULL)
            AND (attempt IS NULL OR attempt BETWEEN 1 AND 3)
        );
        ALTER TABLE {JOBS} ADD CONSTRAINT ck_creative_jobs_seasonal_kind CHECK (
            (seasonal_media_id IS NOT NULL) = (kind = 'seasonal_video')
        );
        CREATE UNIQUE INDEX uq_creative_jobs_seasonal
            ON {JOBS} (tenant_id, seasonal_media_id, attempt)
            WHERE seasonal_media_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            SET LOCAL row_security = off;
            IF EXISTS (SELECT 1 FROM {JOBS} WHERE seasonal_media_id IS NOT NULL) THEN
                RAISE EXCEPTION 'creative_jobs holds seasonal video jobs; downgrading would '
                                'drop paid-task provenance — move or archive them first';
            END IF;
        END
        $$;
        DROP INDEX uq_creative_jobs_seasonal;
        ALTER TABLE {JOBS} DROP CONSTRAINT ck_creative_jobs_seasonal_kind;
        ALTER TABLE {JOBS} DROP CONSTRAINT ck_creative_jobs_subject;
        ALTER TABLE {JOBS} DROP CONSTRAINT fk_creative_jobs_seasonal_media_tenant;
        ALTER TABLE {JOBS} DROP COLUMN attempt;
        ALTER TABLE {JOBS} DROP COLUMN seasonal_media_id;
        ALTER TABLE {JOBS} ALTER COLUMN draft_id SET NOT NULL;
        ALTER TABLE {JOBS} DROP CONSTRAINT ck_creative_jobs_kind;
        ALTER TABLE {JOBS} ADD CONSTRAINT ck_creative_jobs_kind CHECK (kind IN {OLD_KINDS});
        ALTER TABLE brand_seasonal_media DROP CONSTRAINT uq_brand_seasonal_media_tenant_id;
        """
    )
