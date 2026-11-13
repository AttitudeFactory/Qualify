"""Asking for, and reading, a reel's shared analysis — the screen's side (ADR 44,
m-24921056 VE-04a; contract: `docs/traspasos/historias-video-por-partes-backend.md`
§VE-04a and §3, `docs/diseno-video-por-planos.md` §13.3).

The screen never analyses, downloads or uploads anything (F5: only the `reels-worker`
does). It runs as `qualify_app` through `tenant_session` — the tenant only opens the
session; the tables are global and NO column records who asked:

- `request_analysis(tenant_id, source)` — an `ok` of the current version is reused (no
  network, no row); a row still in the queue gets `wanted_at` (the on-demand lane, set
  once); otherwise a `queued` row is created with `INSERT … ON CONFLICT DO NOTHING` and
  re-read. Without a usable video URL (missing, off the network's CDN, or read more than
  20 h ago) nothing is created: `no_video`. Past the platform's on-demand quota for the
  last 24 h (`QUALIFY_REEL_ANALYSIS_ON_DEMAND_DAILY`, 50) nothing is created:
  `daily_limit`. An existing row also takes the caller's usable URL (m-24984404, through
  `offer_url`, one locked step with the quota count): a `failed` row whose URL had
  expired (`source_expired`) goes back to the queue with it and `wanted_at = now`, and a
  `queued` row whose pending URL is missing or stale gets it swapped in (a `running` row
  is never touched). Past the quota a failed row answers `daily_limit` without an id and
  stays as it is (the owner's call, 2026-11-09: the screen says «come back tomorrow»
  rather than «we could not download it»). Any other `failed` row is returned as it is:
  re-queueing it is the worker's call. Only a write that brings a URL dates it
  (`pending_url_at`); `mark_wanted` never makes an old URL look fresh.
- `get_analysis_status`, `get_analysis` (only an `ok`), `analysis_badges` (one query for
  a whole list of ideas).

`ReelSource` comes from the server-held card (or, after R7, from `public_reels`), never
from an event's arguments.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from qualify_shared.objects.public import is_reel_post_id

from qualify_api.referentes.reel_analysis_source import url_is_stale
from qualify_api.referentes.reel_analysis_store import (
    OFFER_DAILY_LIMIT,
    OFFER_REPLACED,
    OFFER_REQUEUED,
    OFFER_UNCHANGED,
    AnalysisRecord,
    AnalysisRequests,
    OnDemandQuotaReached,
    PostgresAnalysisRequests,
    pending_url_read_at,
)
from qualify_api.referentes.reel_analysis_types import (
    ANALYSIS_VERSION,
    ERROR_SOURCE_EXPIRED,
    NETWORKS,
    STATUS_DAILY_LIMIT,
    STATUS_FAILED,
    STATUS_NO_VIDEO,
    STATUS_OK,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TRANSCRIPT_NONE,
    AnalysisProvenance,
    AnalysisRef,
    AnalysisStatus,
    ReelAnalysis,
    ReelSource,
    TranscriptSegment,
)
from qualify_api.referentes.reel_reference import source_allowed

logger = logging.getLogger(__name__)

ON_DEMAND_DAILY_ENV = "QUALIFY_REEL_ANALYSIS_ON_DEMAND_DAILY"
#: The platform's on-demand quota (handoff §VE-04a). Platform-wide, not per business,
#: until the founder decides otherwise (open question of m-24921056).
DEFAULT_ON_DEMAND_DAILY = 50
FLEET_DAILY_ENV = "QUALIFY_REEL_ANALYSIS_FLEET_DAILY"
#: §13.3: 1,500 model calls a day for the whole fleet (≤ USD 8.3 a day) [H].
DEFAULT_FLEET_DAILY = 1500
DAY = timedelta(hours=24)

_store: AnalysisRequests | None = None


def default_store() -> AnalysisRequests:
    global _store
    if _store is None:
        _store = PostgresAnalysisRequests()
    return _store


def _env_int(name: str, default: int, env: Mapping[str, str] | None = None) -> int:
    raw = ((os.environ if env is None else env).get(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return value if value >= 0 else default


def on_demand_daily(env: Mapping[str, str] | None = None) -> int:
    return _env_int(ON_DEMAND_DAILY_ENV, DEFAULT_ON_DEMAND_DAILY, env)


def fleet_daily(env: Mapping[str, str] | None = None) -> int:
    return _env_int(FLEET_DAILY_ENV, DEFAULT_FLEET_DAILY, env)


def _now() -> datetime:
    return datetime.now(UTC)


def _check_identity(source: ReelSource) -> None:
    if source.network not in NETWORKS:
        raise ValueError("a reel analysis is for an Instagram or TikTok reel")
    if not (source.post_id or "").strip() or not (source.post_url or "").strip():
        raise ValueError("a reel analysis needs the reel's id and its public URL")
    if not is_reel_post_id(source.post_id):
        raise ValueError("the reel's id is not a plain Instagram or TikTok identifier")


def usable_video_url(source: ReelSource, now: datetime) -> str | None:
    """The source's video URL if the worker may try it: on the network's CDN and fresh."""
    url = (source.video_url or "").strip()
    if not url or not source_allowed(source.network, url):
        return None
    if url_is_stale(url, source.video_url_at or now, now):
        return None
    return url


def request_analysis(
    tenant_id: UUID,
    source: ReelSource,
    *,
    store: AnalysisRequests | None = None,
    clock: Callable[[], datetime] = _now,
    daily_limit: int | None = None,
) -> AnalysisRef:
    """Ask for `source`'s analysis (see the module docstring). Never calls the network."""
    _check_identity(source)
    active = store or default_store()
    now = clock()
    url = usable_video_url(source, now)
    cap = on_demand_daily() if daily_limit is None else daily_limit
    found = active.find(tenant_id, source.network, source.post_id, ANALYSIS_VERSION)
    if found is not None:
        return _answer_existing(active, tenant_id, found, url, now, cap)
    if url is None:
        return AnalysisRef(id=None, status=STATUS_NO_VIDEO)
    try:
        # Count and insert are one locked step: two screens never both take the last place.
        new_id = active.insert_queued(
            tenant_id,
            network=source.network,
            post_id=source.post_id,
            version=ANALYSIS_VERSION,
            post_url=source.post_url,
            pending_video_url=url,
            wanted_at=now,
            quota=(now - DAY, cap),
        )
    except OnDemandQuotaReached:
        logger.info("reel analysis: on-demand quota of %d for 24 h reached", cap)
        return AnalysisRef(id=None, status=STATUS_DAILY_LIMIT)
    if new_id is not None:
        return AnalysisRef(id=new_id, status=STATUS_QUEUED)
    # Lost a race with another business or the weekly run: the row exists now.
    found = active.find(tenant_id, source.network, source.post_id, ANALYSIS_VERSION)
    if found is None:  # pragma: no cover — a conflict always leaves the row
        raise RuntimeError("reel analysis row vanished after a conflict")
    return _answer_existing(active, tenant_id, found, url, now, cap)


def _takes_screen_url(record: AnalysisRecord, url: str, now: datetime) -> bool:
    """Whether the screen's fresh `url` is worth offering to an existing row (m-24984404):
    a `failed` row whose URL had expired, or a `queued` row (never a running one) whose
    pending URL is missing or stale. The store re-checks under its locks."""
    if record.source_key is not None:
        return False
    if record.status == STATUS_FAILED:
        return record.error_code == ERROR_SOURCE_EXPIRED
    if record.status != STATUS_QUEUED or record.pending_video_url == url:
        return False
    pending = record.pending_video_url
    return not pending or url_is_stale(pending, pending_url_read_at(record), now)


def _answer_existing(
    store: AnalysisRequests,
    tenant_id: UUID,
    record: AnalysisRecord,
    url: str | None,
    now: datetime,
    cap: int,
) -> AnalysisRef:
    if record.status == STATUS_OK:
        return AnalysisRef(id=record.id, status=STATUS_OK, reused=True)
    if url is not None and _takes_screen_url(record, url, now):
        offered = store.offer_url(
            tenant_id,
            record.id,
            video_url=url,
            expected=record.pending_video_url,
            wanted_at=now,
            quota=(now - DAY, cap),
        )
        if offered in (OFFER_REQUEUED, OFFER_REPLACED):
            return AnalysisRef(id=record.id, status=STATUS_QUEUED)
        if offered == OFFER_DAILY_LIMIT and record.status == STATUS_FAILED:
            logger.info("reel analysis: on-demand quota of %d for 24 h reached", cap)
            return AnalysisRef(id=None, status=STATUS_DAILY_LIMIT)
        if offered == OFFER_UNCHANGED:
            # The worker (or a run) moved the row in between: answer what it is now.
            record = store.get(tenant_id, record.id) or record
            if record.status == STATUS_OK:
                return AnalysisRef(id=record.id, status=STATUS_OK, reused=True)
    if record.status in (STATUS_QUEUED, STATUS_RUNNING) and record.wanted_at is None:
        store.mark_wanted(tenant_id, record.id, now)
    return AnalysisRef(id=record.id, status=record.status)


def get_analysis_status(
    tenant_id: UUID,
    analysis_id: UUID,
    *,
    store: AnalysisRequests | None = None,
    clock: Callable[[], datetime] = _now,
) -> AnalysisStatus | None:
    """What the screen polls every 3 s while the analysis is not `ok`."""
    active = store or default_store()
    record = active.get(tenant_id, analysis_id)
    if record is None:
        return None
    now = clock()
    waiting = record.status in (STATUS_QUEUED, STATUS_RUNNING)
    shots = active.shots(tenant_id, analysis_id) if record.status == STATUS_OK else []
    paused = (
        record.status == STATUS_QUEUED
        and active.model_calls_since(tenant_id, now - DAY, now) >= fleet_daily()
    )
    return AnalysisStatus(
        analysis_id=record.id,
        status=record.status,
        stage=record.stage,
        error_code=record.error_code,
        retryable=record.status == STATUS_QUEUED and record.error_code is not None,
        queued_for_s=max(0.0, (now - (record.wanted_at or record.created_at)).total_seconds())
        if waiting
        else 0.0,
        queue_ahead=active.queue_ahead(tenant_id, record) if waiting else 0,
        shots_found=len(shots),
        covered_to_s=record.covered_to_s,
        source_seconds=record.source_seconds,
        source_available=record.source_key is not None and record.source_purged_at is None,
        fleet_paused=paused,
    )


def get_analysis(
    tenant_id: UUID, analysis_id: UUID, *, store: AnalysisRequests | None = None
) -> ReelAnalysis | None:
    """The analysis, only once `ok` (what `plan_from_analysis` reads)."""
    active = store or default_store()
    r = active.get(tenant_id, analysis_id)
    if r is None or r.status != STATUS_OK:
        return None
    transcript = dict(r.transcript or {})
    return ReelAnalysis(
        id=r.id,
        network=r.network,
        post_id=r.post_id,
        analysis_version=r.analysis_version,
        post_url=r.post_url,
        source_seconds=float(r.source_seconds or 0.0),
        width=int(r.width or 0),
        height=int(r.height or 0),
        fps=float(r.fps or 0.0),
        covered_from_s=float(r.covered_from_s or 0.0),
        covered_to_s=float(r.covered_to_s or 0.0),
        edit_eligible=bool(r.edit_eligible),
        source_available=r.source_key is not None and r.source_purged_at is None,
        transcript_text=str(transcript.get("text") or ""),
        transcript_segments=tuple(
            TranscriptSegment(float(s["start_s"]), float(s["end_s"]), str(s.get("text", "")))
            for s in transcript.get("segments") or ()
        ),
        transcript_source=r.transcript_source or TRANSCRIPT_NONE,
        reel_sheet=dict(r.reel_sheet or {}),
        shots=tuple(active.shots(tenant_id, analysis_id)),
        provenance=AnalysisProvenance(
            model_id=r.model_id or "",
            model_revision=r.model_revision,
            prompt_version=r.prompt_version or "",
            schema_version=r.schema_version or "",
            detector_version=r.detector_version or "",
            sampling_version=r.sampling_version or "",
            sampling_params=dict(r.sampling_params or {}),
            source_sha256=r.source_sha256 or "",
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
            cost_usd=r.cost_usd,
        ),
        finished_at=r.finished_at or r.created_at,
        frames_available=r.frames_purged_at is None,
    )


def analysis_badges(
    tenant_id: UUID,
    keys: Sequence[tuple[str, str]],
    *,
    store: AnalysisRequests | None = None,
) -> dict[tuple[str, str], str]:
    """`(network, post_id)` → `person` / `none` / `looking` / `not_analyzed` for a whole
    list of ideas, in one query (handoff §3; the words are the screen's)."""
    active = store or default_store()
    unique = list(dict.fromkeys((n, p) for n, p in keys))
    return active.badges(tenant_id, unique, ANALYSIS_VERSION)


__all__ = [
    "DEFAULT_FLEET_DAILY",
    "DEFAULT_ON_DEMAND_DAILY",
    "FLEET_DAILY_ENV",
    "ON_DEMAND_DAILY_ENV",
    "analysis_badges",
    "default_store",
    "fleet_daily",
    "get_analysis",
    "get_analysis_status",
    "on_demand_daily",
    "request_analysis",
    "usable_video_url",
]
