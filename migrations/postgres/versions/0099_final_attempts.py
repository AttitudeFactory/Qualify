"""Keep every paid final attempt, without replacing vendor ids (m-24852169).

Only final jobs may have a non-zero attempt. Content revision, preview identity and
charge stay unchanged on retry; the natural key makes concurrent duplicate retries
idempotent. No worker privileges change: attempt is read inside tenant_session.

Downgrade refuses if real retries would collide with the old natural key, rather
than silently deleting paid-task provenance. Such a production rollback needs an
explicit retention/migration plan.
"""

from alembic import op

revision = "0099"
down_revision = "0098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE creative_jobs ADD COLUMN final_attempt integer NOT NULL DEFAULT 0;
        ALTER TABLE creative_jobs ADD CONSTRAINT ck_creative_jobs_final_attempt
            CHECK (final_attempt >= 0 AND (kind = 'final' OR final_attempt = 0));
        ALTER TABLE creative_jobs DROP CONSTRAINT uq_creative_jobs_step;
        ALTER TABLE creative_jobs ADD CONSTRAINT uq_creative_jobs_step
            UNIQUE (tenant_id, draft_id, kind, revision, position, final_attempt);
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM creative_jobs
                GROUP BY tenant_id, draft_id, kind, revision, position HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION 'Cannot downgrade 0099: retain paid final attempts first';
            END IF;
        END $$;
        ALTER TABLE creative_jobs DROP CONSTRAINT uq_creative_jobs_step;
        ALTER TABLE creative_jobs ADD CONSTRAINT uq_creative_jobs_step
            UNIQUE (tenant_id, draft_id, kind, revision, position);
        ALTER TABLE creative_jobs DROP CONSTRAINT ck_creative_jobs_final_attempt;
        ALTER TABLE creative_jobs DROP COLUMN final_attempt;
    """)
