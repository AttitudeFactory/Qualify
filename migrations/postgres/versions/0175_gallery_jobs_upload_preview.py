"""gallery_jobs: the `upload_preview` kind — the light 480p copy of a generator upload (m-25026643)

Revision ID: 0175
Revises: 0174
Create Date: 2026-11-20

Ticket m-25026643 (ED-09; ADR 50 D-E2): a video the owner uploads to the generator is kept
as it came (up to 200 MB); playing it again on a phone spends data and battery. The
`media-worker` (ADR 47, one job at a time, 1 CPU, 768m) makes a silent, upright 480p copy
right after the upload, at cost 0, and the editor plays it when the owner comes back.

**`gallery_jobs`** (the `media-worker` queue, 0133/0145/0171) gains the kind
`upload_preview`. Its `payload` (NOT NULL for that kind) is `{source_key, preview_key,
version}`: the owner's file, the deterministic key of its copy
(`t/{tenant}/uploads/previews/{uuid5}/video.mp4`) and the previewer's version; the job's
`result` repeats them with both headers, the size and `cost_usd` for the provenance.

**Idempotency** — a file is never copied twice: `uq_gallery_jobs_upload_preview` is UNIQUE
`(tenant_id, idempotency_key)` among the `upload_preview` jobs that did not fail (queued,
running AND done), so asking twice — a retried upload handler, the editor opened twice —
`INSERT … ON CONFLICT DO NOTHING` onto the same job. The key is
`upload_preview:{version}:{source_key}`; a failed job does not hold it.

**Tenancy, RLS and grants** are the table's own (0133): `tenant_id` NOT NULL, RLS ENABLE +
FORCE with the house NULLIF policy, the composite `(brand_id, tenant_id)` foreign key
(ON DELETE CASCADE: the jobs go with the business), `qualify_app` SELECT/INSERT/UPDATE/
DELETE. This revision creates no table, so it adds no policy; it only checks they hold
(`test_gallery_jobs_upload_preview_db.py`).

**Downgrade** deletes the `upload_preview` jobs (the old kind CHECK cannot hold with them)
and drops the index and the CHECKs. The copies in R2 are not touched (`t/` is write-once).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0175"
down_revision = "0174"
branch_labels = None
depends_on = None

_JOBS = "gallery_jobs"
_KIND = "upload_preview"
_KINDS_BEFORE = "'ingest', 'cut', 'seasonal_media', 'normalize_local'"


def upgrade() -> None:
    op.drop_constraint("ck_gallery_jobs_kind", _JOBS, type_="check")
    op.create_check_constraint(
        "ck_gallery_jobs_kind", _JOBS, f"kind IN ({_KINDS_BEFORE}, '{_KIND}')"
    )
    op.create_check_constraint(
        "ck_gallery_jobs_upload_preview",
        _JOBS,
        f"kind <> '{_KIND}' OR (payload->>'source_key' IS NOT NULL"
        " AND payload->>'preview_key' IS NOT NULL AND payload->>'version' IS NOT NULL)",
    )
    op.create_index(
        "uq_gallery_jobs_upload_preview",
        _JOBS,
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text(f"kind = '{_KIND}' AND status <> 'failed'"),
    )


def downgrade() -> None:
    # The delete must see every tenant's rows, never zero through RLS (as 0145 and 0171 do).
    op.execute("SET LOCAL row_security = off;")
    op.execute(f"DELETE FROM {_JOBS} WHERE kind = '{_KIND}';")
    op.execute("SET LOCAL row_security = on;")
    op.drop_index("uq_gallery_jobs_upload_preview", table_name=_JOBS)
    op.drop_constraint("ck_gallery_jobs_upload_preview", _JOBS, type_="check")
    op.drop_constraint("ck_gallery_jobs_kind", _JOBS, type_="check")
    op.create_check_constraint("ck_gallery_jobs_kind", _JOBS, f"kind IN ({_KINDS_BEFORE})")
