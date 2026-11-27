"""gallery_jobs: the `normalize_local` kind — a local-video source to 4K 8 bits (m-25042483)

Revision ID: 0171
Revises: 0170
Create Date: 2026-11-17

Ticket m-25042483 (founder's decision «Bajarlos a 4K 8 bits»): the local video assembly
(EF-06, in the creative worker's 768m) only decodes a source of at most 3840×2160 at 8
bits. A bigger or 10-bit source is normalized BEFORE, by `media-worker` (ADR 47, one job at
a time), silently and at cost 0; the assembly waits for it.

**`gallery_jobs`** (the `media-worker` queue, 0133/0145) gains the kind `normalize_local`.
Its `payload` (NOT NULL for that kind) is `{source_key, normalized_key, version}`: the
owner's file, the deterministic key of its copy (`t/{tenant}/normalized/{uuid5}/video.mp4`)
and the normalizer's version; the job's `result` repeats them for the provenance.

**Idempotency** — a source is never normalized twice:
`uq_gallery_jobs_normalize_local` is UNIQUE `(tenant_id, idempotency_key)` among the
`normalize_local` jobs that did not fail (queued, running AND done), so two pieces that
use the same file, or a retried assembly, `INSERT … ON CONFLICT DO NOTHING` onto the same
job. The key is `normalize_local:{version}:{source_key}`; a failed job does not hold it.

**Tenancy, RLS and grants** are the table's (0133): `tenant_id` NOT NULL, RLS ENABLE +
FORCE with the house NULLIF policy, `qualify_app` SELECT/INSERT/UPDATE/DELETE — the creative
worker enqueues and reads these jobs through `tenant_session` (`qualify_app`), the
media-worker claims them the same way. Nothing changes there; this revision only checks it
(`test_gallery_jobs_normalize_local_db.py`).

**Downgrade** deletes the `normalize_local` jobs (the old kind CHECK cannot hold with
them) and drops the index and the CHECKs. The normalized copies in R2 are not touched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0171"
down_revision = "0170"
branch_labels = None
depends_on = None

_JOBS = "gallery_jobs"
_KIND = "normalize_local"


def upgrade() -> None:
    op.drop_constraint("ck_gallery_jobs_kind", _JOBS, type_="check")
    op.create_check_constraint(
        "ck_gallery_jobs_kind",
        _JOBS,
        f"kind IN ('ingest', 'cut', 'seasonal_media', '{_KIND}')",
    )
    op.create_check_constraint(
        "ck_gallery_jobs_normalize_local",
        _JOBS,
        f"kind <> '{_KIND}' OR (payload->>'source_key' IS NOT NULL"
        " AND payload->>'normalized_key' IS NOT NULL AND payload->>'version' IS NOT NULL)",
    )
    op.create_index(
        "uq_gallery_jobs_normalize_local",
        _JOBS,
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text(f"kind = '{_KIND}' AND status <> 'failed'"),
    )


def downgrade() -> None:
    # The delete must see every tenant's rows, never zero through RLS (as 0145 does).
    op.execute("SET LOCAL row_security = off;")
    op.execute(f"DELETE FROM {_JOBS} WHERE kind = '{_KIND}';")
    op.execute("SET LOCAL row_security = on;")
    op.drop_index("uq_gallery_jobs_normalize_local", table_name=_JOBS)
    op.drop_constraint("ck_gallery_jobs_normalize_local", _JOBS, type_="check")
    op.drop_constraint("ck_gallery_jobs_kind", _JOBS, type_="check")
    op.create_check_constraint(
        "ck_gallery_jobs_kind", _JOBS, "kind IN ('ingest', 'cut', 'seasonal_media')"
    )
