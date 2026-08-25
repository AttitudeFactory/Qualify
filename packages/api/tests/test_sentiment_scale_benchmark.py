"""Opt-in-only benchmark for QUA-93's scale claim (1,000 Reels x 100 comments). Deliberately
a SEPARATE file from `test_sentiment_repository.py`, not a test inside it: that file sets
`pytestmark = pytest.mark.db` at module level, which would apply to every test in it —
including this one — and defeat the whole point of marking this benchmark `slow`-only
(`just test-db` runs `pytest -m "db"`, which would then sweep this in too).

**Gated by an environment variable, not just a marker — `-m` alone is not safe here.**
`pyproject.toml`'s `addopts` excludes `slow` by default (`-m 'not integration and not
slow'`), but `just test` runs `pytest -m "not integration"` — an EXPLICIT `-m` on the
command line, which REPLACES addopts's `-m` entirely rather than combining with it
(pytest/argparse: the last `-m` value wins). That explicit `-m "not integration"` says
nothing about `slow`, so `just test` would still collect and run this file's test —
confirmed empirically while adding this test (`pytest -m "not integration" -k
scale_benchmark` did collect and start running it). The `@pytest.mark.slow` below is
kept for documentation/selectability (`pytest -m slow` is still the intended way to ask
for it), but the actual gate is `_skip_unless_opted_in`: a `skipif` on an environment
variable, which no `-m` expression composition can accidentally defeat.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import insert

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.sentiment.models import CommentSentimentResult
from qualify_api.sentiment.repository import AnalysisVersion, PostgresSentimentRepository
from qualify_api.tenancy.models import Tenant, User

_RUN_SCALE_BENCHMARK = os.environ.get("QUALIFY_RUN_SCALE_BENCHMARK") == "1"
_skip_unless_opted_in = pytest.mark.skipif(
    not _RUN_SCALE_BENCHMARK,
    reason=(
        "opt-in only — set QUALIFY_RUN_SCALE_BENCHMARK=1 to run "
        "(never in just test/test-db/CI; see the module docstring for why -m alone "
        "cannot be trusted to keep this out of `just test`)"
    ),
)

VERSION = AnalysisVersion(
    detector_version="robertuito-sentiment-v1",
    pipeline_version="owned-comments-0.1.0",
    model_id="pysentimiento/robertuito-sentiment-analysis",
    model_revision=None,
)


def _seed_connection_only(tenant_id: UUID) -> UUID:
    """Same tenant/app/user/connection setup `test_sentiment_repository.py`'s own
    `_seed_message` does, minus its first Reel/comment — not imported from there on
    purpose (this file is deliberately self-contained; see the module docstring for
    why). For a test that seeds every Reel itself, in bulk."""
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"scale-bench-{tenant_id}",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@s.co", display_name="U")
        session.add(user)
        session.flush()
        app_id = app.id
        user_id = user.id

    with tenant_session(tenant_id) as session:
        conn = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        return conn.id


def _bulk_seed_many_reels(
    tenant_id: UUID,
    connection_id: UUID,
    *,
    reel_count: int,
    comments_per_reel: int,
    analyzed_fraction: float,
    version: AnalysisVersion,
) -> UUID:
    """A handful of large, chunked Core `INSERT`s instead of one transaction per Reel, so
    seeding itself does not dominate the test's wall-clock time. Returns the LAST
    thread's id, for the thread-bounded query the benchmark also times."""
    now = datetime.now(UTC)
    thread_rows = []
    message_rows = []
    sentiment_rows = []
    thread_ids = []
    analyzed_count = int(comments_per_reel * analyzed_fraction)
    for i in range(reel_count):
        thread_id = uuid4()
        thread_ids.append(thread_id)
        thread_rows.append(
            {
                "id": thread_id,
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "channel": "comment",
                "external_thread_id": f"media-bench-{i}-{uuid4()}",
                "status": "open",
                "last_message_at": now + timedelta(minutes=i),
            }
        )
        for j in range(comments_per_reel):
            mid = uuid4()
            message_rows.append(
                {
                    "id": mid,
                    "tenant_id": tenant_id,
                    "thread_id": thread_id,
                    "connection_id": connection_id,
                    "external_message_id": f"comment-bench-{i}-{j}-{uuid4()}",
                    "direction": "inbound",
                    "text": f"reel {i} comentario {j}",
                    "posted_at": now + timedelta(minutes=i, seconds=-j),
                    "shape_version": "ig-comment-shapes-1.0.0",
                }
            )
            if j < analyzed_count:
                sentiment_rows.append(
                    {
                        "tenant_id": tenant_id,
                        "connection_id": connection_id,
                        "message_id": mid,
                        "source_id": f"src-{mid}",
                        "detector_version": version.detector_version,
                        "pipeline_version": version.pipeline_version,
                        "model_id": version.model_id,
                        "model_revision": version.model_revision,
                        "label": "POS",
                        "score": 0.9,
                    }
                )

    with tenant_session(tenant_id) as session:
        session.execute(insert(Thread), thread_rows)
        session.flush()
        # Chunked: a single 100k-row executemany is still slow/memory-heavy via the ORM
        # Core path — chunking keeps each round-trip predictable.
        for start in range(0, len(message_rows), 5000):
            session.execute(insert(Message), message_rows[start : start + 5000])
        session.flush()
        for start in range(0, len(sentiment_rows), 5000):
            session.execute(insert(CommentSentimentResult), sentiment_rows[start : start + 5000])
        session.flush()
    return thread_ids[-1]


@pytest.mark.slow
@_skip_unless_opted_in
def test_scale_benchmark_1000_reels_100_comments_stays_fast_opt_in() -> None:
    """Opt-in only — `QUALIFY_RUN_SCALE_BENCHMARK=1 uv run pytest -m slow` (`just up`
    first) — never in `just test`, `just test-db`, or CI (see the `slow` marker's
    registration in pyproject.toml, and this file's own docstring for why a `skipif` on
    an environment variable, not just `-m`, is what actually keeps it out of `just
    test`).
    Reproduces the 2026-08-25 pre-implementation validation at its original scale
    (1,000 Reels x 100 comments = 100,000 messages, 50,000 sentiment results) and
    asserts the page/thread-bounded queries stay fast — a direct, timing-based
    regression guard for the exact bug `repository.py`'s module docstring documents: a
    `LEFT JOIN comment_sentiment_results ... IS NOT DISTINCT FROM` here regressed to
    28.5 SECONDS at this scale; the `LATERAL` fix measured ~23ms / ~1ms. The 5-second
    thresholds below are ~200x that measured cost and ~5x short of the pathological
    one — generous enough not to flake on a slow CI runner, tight enough that a silent
    regression back to the naive-JOIN shape (which lands near 28s, not near 5s) cannot
    pass unnoticed. Seeding 100k rows costs real wall-clock time (tens of seconds) —
    that cost, not a correctness concern, is why this is opt-in rather than part of the
    default suite.

    KNOWN FAILING (intermittently) as of 2026-08-25 (see the QUA-93 scale-follow-up
    conversation): this test found a SECOND scale regression beyond the one the
    docstring above describes — `list_reel_summaries` measured ~29-30s here on several
    runs, not ~23ms, under real `tenant_session` (RLS). Root-caused via `EXPLAIN
    (ANALYZE, BUFFERS)`: the LATERAL subquery's `WHERE` relies on RLS's
    `current_setting('app.tenant_id')` alone to scope `tenant_id`, and Postgres's
    planner does not always reason about that opaque runtime expression well enough to
    pick `uq_comment_sentiment_analysis` (the ideal, message_id-first composite unique
    index) — it sometimes falls back to `ix_comment_sentiment_tenant` instead, filtering
    out tens of thousands of rows per outer loop iteration. Confirmed fix (not yet
    applied — see the follow-up commit that lands right after this one): repeat
    `csr.tenant_id = :tenant_id` as an explicit, bound-parameter condition inside each
    LATERAL subquery, redundant with RLS but enough for the planner to reliably choose
    the composite index — this was measured at ~21ms under RLS, matching the
    BYPASSRLS/`admin_session` baseline.

    Deliberately NOT deterministic in this repo's shared dev Postgres: across repeated
    runs while developing this test, `list_reel_summaries` failed some runs (~29-30s)
    and passed others (comparable to the clean baseline) with byte-identical code and
    query text — the planner's choice between the two candidate plans is sensitive to
    statistics/cache state that this session's heavy, cumulative test traffic keeps
    disturbing. That is not a reason to distrust the finding; a regression that only
    shows up for SOME tenants/data distributions and not others is a worse production
    risk than a deterministic one, not a smaller one — it is exactly why this guard
    belongs in the suite even though it cannot promise to fail on every single run
    before the fix lands.
    """
    tenant_id = uuid4()
    connection_id = _seed_connection_only(tenant_id)
    last_thread_id = _bulk_seed_many_reels(
        tenant_id,
        connection_id,
        reel_count=1000,
        comments_per_reel=100,
        analyzed_fraction=0.5,
        version=VERSION,
    )
    repo = PostgresSentimentRepository()

    started = time.perf_counter()
    page = repo.list_reel_summaries(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION, cursor=None, limit=20
    )
    reel_page_seconds = time.perf_counter() - started
    assert len(page) == 20
    assert reel_page_seconds < 5.0, (
        f"list_reel_summaries took {reel_page_seconds:.2f}s at 1,000x100 scale — the "
        "module docstring's LATERAL fix measured ~23ms; this smells like the 28.5s "
        "naive-JOIN regression is back"
    )

    started = time.perf_counter()
    detail = repo.list_comments_for_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        thread_id=last_thread_id,
        version=VERSION,
        sentiment_filter=None,
        search=None,
        cursor=None,
        limit=20,
    )
    thread_seconds = time.perf_counter() - started
    assert len(detail) == 20
    assert thread_seconds < 5.0, f"list_comments_for_thread took {thread_seconds:.2f}s at scale"

    started = time.perf_counter()
    totals = repo.global_sentiment_summary(
        tenant_id=tenant_id, connection_id=connection_id, version=VERSION
    )
    global_seconds = time.perf_counter() - started
    assert totals.total == 100_000
    assert totals.positive == 50_000
    # A looser threshold than the two queries above, deliberately: this is the ONE query
    # that's SUPPOSED to touch every row (see repository.py's docstring), so its cost is
    # legitimately proportional to total table size — including whatever this shared dev
    # Postgres has accumulated from unrelated test runs, not just this test's own 100k
    # rows (measured at 5.5-6.4s against ~300k+ accumulated rows during this test's own
    # development, vs. the original clean-slate 268ms at ~100k rows). 15s is still ~55x
    # that clean measurement and nowhere near the LATERAL-vs-plain-JOIN pathology the
    # other two thresholds guard against (that pathology is specific to a per-row
    # correlated LATERAL subquery choosing the wrong index — this query has none; it is
    # one hash join over the full set, so a bad index choice here would look like whole
    # seconds-to-minutes, not a 3x threshold miss).
    assert global_seconds < 15.0, f"global_sentiment_summary took {global_seconds:.2f}s at scale"
