"""The screen may hand a reel's analysis a fresh video URL (m-24984404)

Revision ID: 0142
Revises: 0141
Create Date: 2026-11-09

Bug: a reel first asked for with an already-expired CDN URL fails `source_expired` and,
from then on, every «Hacer uno parecido» answered that failed row — even once a run had
read a fresh URL — because 0119 lets `qualify_app` update only `wanted_at` on
`public_reel_analyses` ("it enqueues, it never writes a result"). A queued row whose
pending URL expired failed the same way.

Rather than widening the column grants (an UPDATE grant on `status` would let the screen
write any status, `ok` included), the screen gets ONE bounded SECURITY DEFINER function,
`reel_analysis_offer_url`, that does exactly two things under the on-demand quota's
advisory lock (`QUOTA_LOCK_KEY` of `reel_analysis_store`, the same one `insert_queued`
takes, so the count and the write stay one step):

- a `failed` row with `source_expired`, no stored source, attempts (< 3) and model calls
  (< 2) left goes back to `queued` with the new URL and `wanted_at = now` (`requeued`);
- a `queued` row with no stored source whose pending URL is still the one the caller
  judged stale takes the new URL and `wanted_at = now` (`replaced`) — a compare-and-swap,
  so a URL a run wrote in between is never overwritten. A `running` row is never touched.

Either write counts against the on-demand quota of the window, the row itself excluded
(re-asking a row already counted today takes no new place); a full quota answers
`daily_limit` and writes nothing (the screen then answers `daily_limit` without an id for
a failed row — the owner's call, 2026-11-09). Anything else answers `unchanged`. The row
lock (`FOR UPDATE`) serializes it with the worker's claim. The limits 3 and 2 are
`MAX_ATTEMPTS` / `MAX_MODEL_CALLS` of `reel_analysis_store` (0119's `ck_pra_counters`),
fixed here so a caller cannot widen them.

New column `pending_url_at`: when a write that BROUGHT a URL to an existing row stored it
(this function, and the worker's `ensure` / `refresh_url`). The worker judges a stored
URL's age from `COALESCE(pending_url_at, created_at)`, never from `wanted_at`, which
`mark_wanted` moves without a new URL. NULL for existing rows and for rows created with
their URL (`created_at` is then the read). No grant changes: `qualify_app` reads it with
its table-wide SELECT and writes it only through the function; `qualify_reels_worker`
holds UPDATE on the whole table. `qualify_app` gains EXECUTE on the function only.
"""

from alembic import op

revision = "0142"
down_revision = "0141"
branch_labels = None
depends_on = None

_SIGNATURE = "public.reel_analysis_offer_url(uuid, text, text, timestamptz, timestamptz, integer)"


def upgrade() -> None:
    op.execute("ALTER TABLE public_reel_analyses ADD COLUMN pending_url_at timestamptz;")
    op.execute("""
        CREATE FUNCTION public.reel_analysis_offer_url(
            p_id uuid, p_url text, p_expected text, p_now timestamptz, p_since timestamptz,
            p_cap integer)
        RETURNS text
        LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
            r public.public_reel_analyses%ROWTYPE;
            used bigint;
        BEGIN
            IF p_url IS NULL OR btrim(p_url) = '' THEN
                RETURN 'unchanged';
            END IF;
            PERFORM pg_advisory_xact_lock(4492105601);
            SELECT * INTO r FROM public.public_reel_analyses WHERE id = p_id FOR UPDATE;
            IF NOT FOUND OR r.source_key IS NOT NULL THEN
                RETURN 'unchanged';
            END IF;
            IF NOT (
                (r.status = 'failed' AND r.error_code = 'source_expired'
                    AND r.attempts < 3 AND r.model_calls < 2)
                OR (r.status = 'queued'
                    AND r.pending_video_url IS NOT DISTINCT FROM p_expected
                    AND r.pending_video_url IS DISTINCT FROM p_url)
            ) THEN
                RETURN 'unchanged';
            END IF;
            SELECT count(*) INTO used FROM public.public_reel_analyses
                WHERE wanted_at >= p_since AND id <> p_id;
            IF used >= p_cap THEN
                RETURN 'daily_limit';
            END IF;
            IF r.status = 'failed' THEN
                UPDATE public.public_reel_analyses SET status = 'queued', error_code = NULL,
                    pending_video_url = p_url, pending_url_at = p_now, wanted_at = p_now,
                    finished_at = NULL, stage = NULL, lease_token = NULL, lease_until = NULL
                    WHERE id = p_id;
                RETURN 'requeued';
            END IF;
            UPDATE public.public_reel_analyses SET pending_video_url = p_url,
                pending_url_at = p_now, wanted_at = p_now
                WHERE id = p_id;
            RETURN 'replaced';
        END
        $$;
    """)
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC;")
    op.execute(f"GRANT EXECUTE ON FUNCTION {_SIGNATURE} TO qualify_app;")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {_SIGNATURE};")
    op.execute("ALTER TABLE public_reel_analyses DROP COLUMN pending_url_at;")
