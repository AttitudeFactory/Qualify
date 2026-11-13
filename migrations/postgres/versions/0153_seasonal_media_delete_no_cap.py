"""seasonal media: «Eliminar» and «Pedir otro» without the three-attempt cap (m-25016851)

Revision ID: 0153
Revises: 0152
Create Date: 2026-11-12

Ticket m-25016851 (founder, 2026-11-12): the owner hit «Ya pediste otro tres veces para
esta pieza.» on a sticker and could not delete one he did not want.

**`brand_seasonal_media`** (0145):

- `ck_brand_seasonal_media_attempt`: `attempt BETWEEN 1 AND 3` → `BETWEEN 1 AND 99` — a
  technical ceiling only (the key builder's `SEASONAL_MAX_ATTEMPTS`), never shown to the
  owner. Each «Pedir otro» still deletes the previous attempt's file.
- `ck_brand_seasonal_media_status` gains `deleted`: «Eliminar» keeps the row (provenance:
  recipe, source, pipeline version, `cost_usd`; and the paid `creative_jobs` rows that 0146
  would CASCADE away with a hard delete) but clears its file fields — the R2 objects are
  deleted by the application through `ObjectGate.delete_seasonal_media`. A new CHECK
  `ck_brand_seasonal_media_deleted_no_file` says a deleted row points at no file.

**`creative_jobs`** (0146): `ck_creative_jobs_subject` allows `attempt BETWEEN 1 AND 99`.

No new table, column or grant: RLS (R7) and the grants of 0145/0146 cover these rows
unchanged.

**Downgrade** refuses (and changes nothing) while a row uses what it would forbid — an
attempt above 3 or a `deleted` row — like 0146's downgrade, so no provenance is dropped
silently; on a database without them it restores the 0145/0146 CHECKs exactly.
"""

from __future__ import annotations

from alembic import op

revision = "0153"
down_revision = "0152"
branch_labels = None
depends_on = None

_TABLE = "brand_seasonal_media"
_JOBS = "creative_jobs"
_OLD_STATUSES = "('pending', 'ready', 'approved', 'rejected', 'archived', 'failed')"
_NEW_STATUSES = "('pending', 'ready', 'approved', 'rejected', 'archived', 'failed', 'deleted')"


def _subject(ceiling: int) -> str:
    return (
        "num_nonnulls(draft_id, seasonal_media_id) = 1 "
        "AND (attempt IS NULL) = (seasonal_media_id IS NULL) "
        f"AND (attempt IS NULL OR attempt BETWEEN 1 AND {ceiling})"
    )


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {_TABLE} DROP CONSTRAINT ck_brand_seasonal_media_attempt;
        ALTER TABLE {_TABLE} ADD CONSTRAINT ck_brand_seasonal_media_attempt
            CHECK (attempt BETWEEN 1 AND 99);
        ALTER TABLE {_TABLE} DROP CONSTRAINT ck_brand_seasonal_media_status;
        ALTER TABLE {_TABLE} ADD CONSTRAINT ck_brand_seasonal_media_status
            CHECK (status IN {_NEW_STATUSES});
        ALTER TABLE {_TABLE} ADD CONSTRAINT ck_brand_seasonal_media_deleted_no_file
            CHECK (status <> 'deleted' OR object_key IS NULL);

        ALTER TABLE {_JOBS} DROP CONSTRAINT ck_creative_jobs_subject;
        ALTER TABLE {_JOBS} ADD CONSTRAINT ck_creative_jobs_subject CHECK ({_subject(99)});
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            -- scoped to this check: every tenant's rows, then RLS back on for the rest
            PERFORM set_config('row_security', 'off', true);
            IF EXISTS (SELECT 1 FROM {_TABLE} WHERE attempt > 3 OR status = 'deleted')
               OR EXISTS (SELECT 1 FROM {_JOBS} WHERE attempt > 3) THEN
                RAISE EXCEPTION 'downgrade 0153 refused: seasonal media past attempt 3 or '
                                'deleted by the owner remain (provenance would be lost)'
                    USING ERRCODE = '23514';
            END IF;
            PERFORM set_config('row_security', 'on', true);
        END
        $$;
        ALTER TABLE {_JOBS} DROP CONSTRAINT ck_creative_jobs_subject;
        ALTER TABLE {_JOBS} ADD CONSTRAINT ck_creative_jobs_subject CHECK ({_subject(3)});

        ALTER TABLE {_TABLE} DROP CONSTRAINT ck_brand_seasonal_media_deleted_no_file;
        ALTER TABLE {_TABLE} DROP CONSTRAINT ck_brand_seasonal_media_status;
        ALTER TABLE {_TABLE} ADD CONSTRAINT ck_brand_seasonal_media_status
            CHECK (status IN {_OLD_STATUSES});
        ALTER TABLE {_TABLE} DROP CONSTRAINT ck_brand_seasonal_media_attempt;
        ALTER TABLE {_TABLE} ADD CONSTRAINT ck_brand_seasonal_media_attempt
            CHECK (attempt BETWEEN 1 AND 3);
        """
    )
