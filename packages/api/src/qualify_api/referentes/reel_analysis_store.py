"""Where a reel's shared analysis lives (ADR 44, m-24921056 VE-04a): two protocols over the
global tables of 0119, an in-memory store that implements both (the offline tests and
creative's VE-08 build against it), and the screen's Postgres side.

- `AnalysisRequests` — what the screen may do, as `qualify_app` through `tenant_session`
  (the tenant only opens the session: the tables have no RLS and no `tenant_id`). It reads
  and it ENQUEUES — the column grants of 0119 let it insert `(network, post_id,
  analysis_version, post_url, pending_video_url, wanted_at)` and update `wanted_at`,
  nothing else. It can never write a result.
- `AnalysisQueue` — what only the `reels-worker` may do (`qualify_reels_worker`): claim a
  row with a lease, record the downloaded source, count a model call against the guards,
  write the result and its shots in one transaction, fail or retry. Its Postgres side is
  `reel_analysis_queue.PostgresAnalysisQueue`, the only module besides the worker allowed
  to import the role's door. The same two classes also serve the 30-day purge
  (`reel_retention.SourcePurge`, VE-12): `purge_due` and `mark_purged`.

Every worker write after the claim is fenced by `lease_token`: a process whose lease
another process took writes nothing.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_api.referentes.reel_analysis_types import (
    ANALYSIS_VERSION,
    ERROR_MODEL_FAILED,
    ERROR_SOURCE_EXPIRED,
    ERROR_SOURCE_UNAVAILABLE,
    OBSERVED,
    STAGE_DONE,
    STATUS_FAILED,
    STATUS_OK,
    STATUS_QUEUED,
    STATUS_RUNNING,
    TRANSCRIPT_NONE,
    ReelSource,
    ShotAnalysis,
)

#: ≤ 2 model calls per row (0119 `ck_pra_counters`): one try and one retry, never more.
MAX_MODEL_CALLS = 2
#: A failed URL can be put back in the queue with a fresh URL (a new run read it again).
URL_ERRORS = (ERROR_SOURCE_EXPIRED, ERROR_SOURCE_UNAVAILABLE)
#: Transaction-scoped advisory locks (`pg_advisory_xact_lock`) that make a cap check and
#: the write it allows one step: without them two processes can both pass at cap - 1.
QUOTA_LOCK_KEY = 4_492_105_601  # the on-demand quota: count + insert
FLEET_LOCK_KEY = 4_492_105_602  # the fleet's daily model calls: count + charge


class OnDemandQuotaReached(Exception):
    """`insert_queued` refused: the platform's on-demand quota for the window is spent."""


# What `add_model_call` answers.
CALL_OK = "ok"
CALL_ROW_CAP = "row_cap"
CALL_FLEET_CAP = "fleet_cap"
CALL_LOST = "lost"

# What `analysis_badges` answers per reel (the screen picks the words, handoff §3).
BADGE_PERSON = "person"  # some shot shows a person or a face (`observed`)
BADGE_NONE = "none"  # analysed; nothing observed, or something unknown: no label
BADGE_LOOKING = "looking"  # queued or running
BADGE_NOT_ANALYZED = "not_analyzed"  # no `ok`: failed, past a cap, or nobody asked


@dataclass(frozen=True)
class AnalysisRecord:
    """One row of `public_reel_analyses` (the columns VE-04a reads)."""

    id: UUID
    network: str
    post_id: str
    analysis_version: int
    status: str
    post_url: str
    created_at: datetime
    stage: str | None = None
    lease_token: UUID | None = None
    lease_until: datetime | None = None
    attempts: int = 0
    model_calls: int = 0
    error_code: str | None = None
    wanted_at: datetime | None = None
    pending_video_url: str | None = None
    source_key: str | None = None
    source_sha256: str | None = None
    source_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    covered_from_s: float | None = None
    covered_to_s: float | None = None
    edit_eligible: bool | None = None
    transcript: Mapping[str, Any] | None = None
    transcript_source: str = TRANSCRIPT_NONE
    detector_version: str | None = None
    sampling_version: str | None = None
    sampling_params: Mapping[str, Any] | None = None
    model_id: str | None = None
    model_revision: str | None = None
    prompt_version: str | None = None
    schema_version: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    reel_sheet: Mapping[str, Any] | None = None
    finished_at: datetime | None = None
    source_purge_after: datetime | None = None
    source_purged_at: datetime | None = None
    frames_purged_at: datetime | None = None


@dataclass(frozen=True)
class DueSource:
    """A row whose R2 objects are due for the 30-day purge (VE-12, `reel_retention`): the
    folders are derived from it, never read from `source_key` — an upload whose
    `record_source` never landed has no key, but has the date (`set_purge_date`)."""

    id: UUID
    network: str
    post_id: str
    purge_after: datetime


@dataclass(frozen=True)
class Claimed:
    """A row this process now holds, and the token every later write must present."""

    record: AnalysisRecord
    token: UUID


@dataclass(frozen=True)
class SourceFacts:
    """What the download + remux learned about the source (written in one UPDATE)."""

    source_key: str
    source_sha256: str
    source_seconds: float
    width: int
    height: int
    fps: float
    covered_from_s: float
    covered_to_s: float
    edit_eligible: bool


@dataclass(frozen=True)
class DescribeResult:
    """What the describe step (VE-04c) hands back: the shots, the sheet and the
    provenance, written with `status = ok` in one transaction."""

    shots: tuple[ShotAnalysis, ...]
    reel_sheet: Mapping[str, Any]
    model_id: str
    prompt_version: str
    schema_version: str
    detector_version: str
    sampling_version: str
    sampling_params: Mapping[str, Any] = field(default_factory=dict)
    model_revision: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    #: When frames covered only the first shots (VE-04c's 32-image cap), how far.
    covered_to_s: float | None = None


@dataclass(frozen=True)
class Spend:
    """What a model call that produced no result still billed (VE-04c): added to the
    row's tokens and `cost_usd` when it is retried or failed — the row is the cost record."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")


def _add_spend(row: AnalysisRecord, spent: Spend | None) -> AnalysisRecord:
    if spent is None:
        return row
    return replace(
        row,
        input_tokens=row.input_tokens + spent.input_tokens,
        output_tokens=row.output_tokens + spent.output_tokens,
        cost_usd=row.cost_usd + spent.cost_usd,
    )


class AnalysisRequests(Protocol):
    """The screen's side (`qualify_app`, `tenant_session(tenant_id)`)."""

    def find(
        self, tenant_id: UUID, network: str, post_id: str, version: int
    ) -> AnalysisRecord | None: ...

    def get(self, tenant_id: UUID, analysis_id: UUID) -> AnalysisRecord | None: ...

    def shots(self, tenant_id: UUID, analysis_id: UUID) -> list[ShotAnalysis]: ...

    def insert_queued(
        self,
        tenant_id: UUID,
        *,
        network: str,
        post_id: str,
        version: int,
        post_url: str,
        pending_video_url: str | None,
        wanted_at: datetime,
        quota: tuple[datetime, int] | None = None,
    ) -> UUID | None: ...

    def mark_wanted(self, tenant_id: UUID, analysis_id: UUID, now: datetime) -> None: ...

    def wanted_since(self, tenant_id: UUID, since: datetime) -> int: ...

    def queue_ahead(self, tenant_id: UUID, record: AnalysisRecord) -> int: ...

    def model_calls_since(self, tenant_id: UUID, since: datetime, now: datetime) -> int: ...

    def badges(
        self, tenant_id: UUID, keys: Sequence[tuple[str, str]], version: int
    ) -> dict[tuple[str, str], str]: ...


class AnalysisQueue(Protocol):
    """The `reels-worker`'s side (`qualify_reels_worker`)."""

    def claim_next(
        self, now: datetime, lease: timedelta, *, download_only: bool, max_attempts: int
    ) -> Claimed | None: ...

    def claim(
        self, analysis_id: UUID, now: datetime, lease: timedelta, *, max_attempts: int
    ) -> Claimed | None: ...

    def renew(self, analysis_id: UUID, token: UUID, until: datetime) -> bool: ...

    def set_stage(self, analysis_id: UUID, token: UUID, stage: str) -> bool: ...

    def set_purge_date(self, analysis_id: UUID, token: UUID, purge_after: datetime) -> bool:
        """VE-12: written BEFORE any object of the row goes to R2, so an upload whose
        `record_source` never lands (a lost lease, a crash) still has the date the purge
        deletes it on. Clears the purged marks: a row revived after a purge (a failed
        download that a new URL brings back) is purged again."""
        ...

    def record_source(
        self, analysis_id: UUID, token: UUID, facts: SourceFacts, purge_after: datetime
    ) -> bool: ...

    def add_model_call(
        self, analysis_id: UUID, token: UUID, *, now: datetime, since: datetime, fleet_cap: int
    ) -> str: ...

    def complete(
        self, analysis_id: UUID, token: UUID, result: DescribeResult, now: datetime
    ) -> bool: ...

    def release(
        self,
        analysis_id: UUID,
        token: UUID,
        *,
        not_before: datetime | None = None,
        refund_call: bool = False,
    ) -> bool: ...

    def retry_later(
        self,
        analysis_id: UUID,
        token: UUID,
        error_code: str | None,
        not_before: datetime,
        *,
        spent: Spend | None = None,
    ) -> bool: ...

    def fail(
        self,
        analysis_id: UUID,
        token: UUID,
        error_code: str,
        now: datetime,
        *,
        spent: Spend | None = None,
    ) -> bool: ...

    def reap_exhausted(self, now: datetime, max_attempts: int) -> int: ...

    def ensure(
        self, source: ReelSource, version: int, now: datetime
    ) -> tuple[AnalysisRecord, bool]: ...

    def refresh_url(
        self, analysis_id: UUID, video_url: str, now: datetime, max_attempts: int
    ) -> AnalysisRecord | None: ...

    def get(self, analysis_id: UUID) -> AnalysisRecord | None: ...

    def get_by_key(self, network: str, post_id: str, version: int) -> AnalysisRecord | None: ...


def transcript_document(source: ReelSource) -> dict[str, Any] | None:
    """The row's `transcript` JSONB: the text and its timed segments, or None."""
    text = (source.transcript or "").strip()
    if not text and not source.transcript_segments:
        return None
    return {
        "text": text,
        "segments": [
            {"start_s": s.start_s, "end_s": s.end_s, "text": s.text}
            for s in source.transcript_segments
        ],
    }


def badge_for(record: AnalysisRecord | None, shots: Iterable[ShotAnalysis]) -> str:
    if record is None or record.status == STATUS_FAILED:
        return BADGE_NOT_ANALYZED
    if record.status in (STATUS_QUEUED, STATUS_RUNNING):
        return BADGE_LOOKING
    if any(OBSERVED in (s.people_presence, s.visible_faces) for s in shots):
        return BADGE_PERSON
    return BADGE_NONE


def _queue_order(record: AnalysisRecord) -> tuple[int, int, datetime, datetime]:
    """§13.3: rows with a URL still to download first (it expires), then the on-demand
    ones by when they were asked for, then the rest — oldest first in each."""
    wanted = record.wanted_at
    return (
        0 if record.pending_video_url else 1,
        0 if wanted is not None else 1,
        wanted or record.created_at,
        record.created_at,
    )


class InMemoryAnalysisStore:
    """Both sides in one process, with the same rules as the Postgres ones (column
    reach of `qualify_app` included: the screen side only ever sets the enqueue columns).
    Thread-safe; `tenant_id` arguments are accepted and ignored, like RLS on a global
    table."""

    def __init__(self) -> None:
        self._rows: dict[UUID, AnalysisRecord] = {}
        self._shots: dict[UUID, list[ShotAnalysis]] = {}
        self._lock = threading.RLock()

    # -- helpers for tests ---------------------------------------------------------------

    def rows(self) -> list[AnalysisRecord]:
        with self._lock:
            return list(self._rows.values())

    def put(self, record: AnalysisRecord, shots: Sequence[ShotAnalysis] = ()) -> None:
        with self._lock:
            self._rows[record.id] = record
            if shots:
                self._shots[record.id] = list(shots)

    def _by_key(self, network: str, post_id: str, version: int) -> AnalysisRecord | None:
        for row in self._rows.values():
            if (row.network, row.post_id, row.analysis_version) == (network, post_id, version):
                return row
        return None

    def _holding(self, analysis_id: UUID, token: UUID) -> AnalysisRecord | None:
        row = self._rows.get(analysis_id)
        if row is None or row.status != STATUS_RUNNING or row.lease_token != token:
            return None
        return row

    # -- AnalysisRequests ----------------------------------------------------------------

    def find(
        self, tenant_id: UUID, network: str, post_id: str, version: int
    ) -> AnalysisRecord | None:
        with self._lock:
            return self._by_key(network, post_id, version)

    def get(self, *args: Any) -> AnalysisRecord | None:
        # `get(tenant_id, id)` (screen) and `get(id)` (worker) share one body.
        with self._lock:
            return self._rows.get(args[-1])

    def get_by_key(self, network: str, post_id: str, version: int) -> AnalysisRecord | None:
        with self._lock:
            return self._by_key(network, post_id, version)

    def shots(self, tenant_id: UUID, analysis_id: UUID) -> list[ShotAnalysis]:
        with self._lock:
            return sorted(self._shots.get(analysis_id, []), key=lambda s: s.shot_index)

    def insert_queued(
        self,
        tenant_id: UUID,
        *,
        network: str,
        post_id: str,
        version: int,
        post_url: str,
        pending_video_url: str | None,
        wanted_at: datetime,
        quota: tuple[datetime, int] | None = None,
    ) -> UUID | None:
        """`quota = (since, cap)`: refuse (`OnDemandQuotaReached`) when `cap` rows were
        asked for since `since` — counted and inserted under one lock."""
        with self._lock:
            if self._by_key(network, post_id, version) is not None:
                return None  # ON CONFLICT DO NOTHING
            if quota is not None and self.wanted_since(tenant_id, quota[0]) >= quota[1]:
                raise OnDemandQuotaReached
            record = AnalysisRecord(
                id=uuid4(),
                network=network,
                post_id=post_id,
                analysis_version=version,
                status=STATUS_QUEUED,
                post_url=post_url,
                pending_video_url=pending_video_url,
                wanted_at=wanted_at,
                created_at=wanted_at,
            )
            self._rows[record.id] = record
            return record.id

    def mark_wanted(self, tenant_id: UUID, analysis_id: UUID, now: datetime) -> None:
        with self._lock:
            row = self._rows.get(analysis_id)
            if row is not None and row.wanted_at is None:
                self._rows[analysis_id] = replace(row, wanted_at=now)

    def wanted_since(self, tenant_id: UUID, since: datetime) -> int:
        with self._lock:
            return sum(1 for r in self._rows.values() if r.wanted_at and r.wanted_at >= since)

    def queue_ahead(self, tenant_id: UUID, record: AnalysisRecord) -> int:
        with self._lock:
            mine = _queue_order(record)
            return sum(
                1
                for r in self._rows.values()
                if r.id != record.id
                and r.status in (STATUS_QUEUED, STATUS_RUNNING)
                and _queue_order(r) < mine
            )

    def model_calls_since(self, tenant_id: UUID, since: datetime, now: datetime) -> int:
        with self._lock:
            return _fleet_calls(self._rows.values(), since, now)

    def badges(
        self, tenant_id: UUID, keys: Sequence[tuple[str, str]], version: int
    ) -> dict[tuple[str, str], str]:
        with self._lock:
            out = {}
            for network, post_id in keys:
                row = self._by_key(network, post_id, version)
                shots = self._shots.get(row.id, []) if row else []
                out[(network, post_id)] = badge_for(row, shots)
            return out

    # -- AnalysisQueue -------------------------------------------------------------------

    def _claimable(self, row: AnalysisRecord, now: datetime, max_attempts: int) -> bool:
        if row.attempts >= max_attempts:
            return False
        if row.source_key is not None and row.source_purged_at is not None:
            return False  # FN3: its stored source was purged; describing it would fail
        if row.status == STATUS_QUEUED:
            return row.lease_until is None or row.lease_until < now
        return (
            row.status == STATUS_RUNNING and row.lease_until is not None and row.lease_until < now
        )

    def _take(self, row: AnalysisRecord, now: datetime, lease: timedelta) -> Claimed:
        token = uuid4()
        taken = replace(
            row,
            status=STATUS_RUNNING,
            lease_token=token,
            lease_until=now + lease,
            attempts=row.attempts + 1,
        )
        self._rows[row.id] = taken
        return Claimed(record=taken, token=token)

    def claim_next(
        self, now: datetime, lease: timedelta, *, download_only: bool, max_attempts: int
    ) -> Claimed | None:
        with self._lock:
            candidates = [
                r
                for r in self._rows.values()
                if self._claimable(r, now, max_attempts)
                and (
                    r.pending_video_url if download_only else r.analysis_version == ANALYSIS_VERSION
                )
            ]
            if not candidates:
                return None
            return self._take(min(candidates, key=_queue_order), now, lease)

    def claim(
        self, analysis_id: UUID, now: datetime, lease: timedelta, *, max_attempts: int
    ) -> Claimed | None:
        with self._lock:
            row = self._rows.get(analysis_id)
            if row is None or not self._claimable(row, now, max_attempts):
                return None
            return self._take(row, now, lease)

    def renew(self, analysis_id: UUID, token: UUID, until: datetime) -> bool:
        with self._lock:
            row = self._holding(analysis_id, token)
            if row is None:
                return False
            self._rows[analysis_id] = replace(row, lease_until=until)
            return True

    def set_stage(self, analysis_id: UUID, token: UUID, stage: str) -> bool:
        with self._lock:
            row = self._holding(analysis_id, token)
            if row is None:
                return False
            self._rows[analysis_id] = replace(row, stage=stage)
            return True

    def set_purge_date(self, analysis_id: UUID, token: UUID, purge_after: datetime) -> bool:
        with self._lock:
            row = self._holding(analysis_id, token)
            if row is None:
                return False
            self._rows[analysis_id] = replace(
                row, source_purge_after=purge_after, source_purged_at=None, frames_purged_at=None
            )
            return True

    # -- SourcePurge (VE-12, `reel_retention`) ---------------------------------------------

    def purge_due(
        self, now: datetime, *, after: tuple[datetime, UUID] | None, limit: int
    ) -> list[DueSource]:
        with self._lock:
            due = sorted(
                (
                    DueSource(r.id, r.network, r.post_id, r.source_purge_after)
                    for r in self._rows.values()
                    if r.source_purge_after is not None
                    and r.source_purge_after <= now
                    and r.source_purged_at is None
                    and not (
                        r.status == STATUS_RUNNING
                        and r.lease_until is not None
                        and r.lease_until >= now
                    )
                    and (after is None or (r.source_purge_after, r.id) > after)
                ),
                key=lambda d: (d.purge_after, d.id),
            )
            return due[:limit]

    def mark_purged(self, analysis_id: UUID, purge_after: datetime, now: datetime) -> bool:
        with self._lock:
            row = self._rows.get(analysis_id)
            if (
                row is None
                or row.source_purged_at is not None
                or row.source_purge_after != purge_after
            ):
                return False
            self._rows[analysis_id] = replace(row, source_purged_at=now, frames_purged_at=now)
            return True

    def record_source(
        self, analysis_id: UUID, token: UUID, facts: SourceFacts, purge_after: datetime
    ) -> bool:
        with self._lock:
            row = self._holding(analysis_id, token)
            if row is None:
                return False
            self._rows[analysis_id] = replace(
                row,
                pending_video_url=None,
                source_key=facts.source_key,
                source_sha256=facts.source_sha256,
                source_seconds=facts.source_seconds,
                width=facts.width,
                height=facts.height,
                fps=facts.fps,
                covered_from_s=facts.covered_from_s,
                covered_to_s=facts.covered_to_s,
                edit_eligible=facts.edit_eligible,
                source_purge_after=purge_after,
            )
            return True

    def add_model_call(
        self, analysis_id: UUID, token: UUID, *, now: datetime, since: datetime, fleet_cap: int
    ) -> str:
        with self._lock:
            row = self._holding(analysis_id, token)
            if row is None:
                return CALL_LOST
            if row.model_calls >= MAX_MODEL_CALLS:
                return CALL_ROW_CAP
            if _fleet_calls(self._rows.values(), since, now) >= fleet_cap:
                return CALL_FLEET_CAP
            self._rows[analysis_id] = replace(row, model_calls=row.model_calls + 1)
            return CALL_OK

    def complete(
        self, analysis_id: UUID, token: UUID, result: DescribeResult, now: datetime
    ) -> bool:
        with self._lock:
            row = self._holding(analysis_id, token)
            if row is None:
                return False
            self._shots[analysis_id] = list(result.shots)
            self._rows[analysis_id] = replace(
                row,
                status=STATUS_OK,
                stage=STAGE_DONE,
                error_code=None,
                lease_token=None,
                lease_until=None,
                reel_sheet=dict(result.reel_sheet),
                model_id=result.model_id,
                model_revision=result.model_revision,
                prompt_version=result.prompt_version,
                schema_version=result.schema_version,
                detector_version=result.detector_version,
                sampling_version=result.sampling_version,
                sampling_params=dict(result.sampling_params),
                input_tokens=row.input_tokens + result.input_tokens,
                output_tokens=row.output_tokens + result.output_tokens,
                cost_usd=row.cost_usd + result.cost_usd,
                covered_to_s=(
                    result.covered_to_s if result.covered_to_s is not None else row.covered_to_s
                ),
                finished_at=now,
            )
            return True

    def release(
        self,
        analysis_id: UUID,
        token: UUID,
        *,
        not_before: datetime | None = None,
        refund_call: bool = False,
    ) -> bool:
        with self._lock:
            row = self._holding(analysis_id, token)
            if row is None:
                return False
            # Handing the row back spends no attempt (after a download; or the API was
            # unavailable for the whole account: then the model call is given back too and
            # the row waits until `not_before`).
            self._rows[analysis_id] = replace(
                row,
                status=STATUS_QUEUED,
                lease_token=uuid4() if not_before is not None else None,
                lease_until=not_before,
                attempts=max(0, row.attempts - 1),
                model_calls=max(0, row.model_calls - 1) if refund_call else row.model_calls,
            )
            return True

    def retry_later(
        self,
        analysis_id: UUID,
        token: UUID,
        error_code: str | None,
        not_before: datetime,
        *,
        spent: Spend | None = None,
    ) -> bool:
        with self._lock:
            row = self._holding(analysis_id, token)
            if row is None:
                return False
            # A queued row with a lease in the future is «not before then».
            self._rows[analysis_id] = replace(
                _add_spend(row, spent),
                status=STATUS_QUEUED,
                error_code=error_code,
                lease_token=uuid4(),
                lease_until=not_before,
            )
            return True

    def fail(
        self,
        analysis_id: UUID,
        token: UUID,
        error_code: str,
        now: datetime,
        *,
        spent: Spend | None = None,
    ) -> bool:
        with self._lock:
            row = self._holding(analysis_id, token)
            if row is None:
                return False
            self._rows[analysis_id] = replace(
                _add_spend(row, spent),
                status=STATUS_FAILED,
                error_code=error_code,
                lease_token=None,
                lease_until=None,
                finished_at=now,
            )
            return True

    def reap_exhausted(self, now: datetime, max_attempts: int) -> int:
        with self._lock:
            reaped = 0
            for row in list(self._rows.values()):
                stuck = (
                    row.status in (STATUS_QUEUED, STATUS_RUNNING)
                    and row.attempts >= max_attempts
                    and (row.lease_until is None or row.lease_until < now)
                )
                if stuck:
                    self._rows[row.id] = replace(
                        row,
                        status=STATUS_FAILED,
                        error_code=row.error_code or exhausted_code(row),
                        lease_token=None,
                        lease_until=None,
                        finished_at=now,
                    )
                    reaped += 1
            return reaped

    def ensure(
        self, source: ReelSource, version: int, now: datetime
    ) -> tuple[AnalysisRecord, bool]:
        check_enqueueable(source)
        with self._lock:
            row = self._by_key(source.network, source.post_id, version)
            if row is not None:
                if _takes_fresh_url(row, source.video_url):
                    row = replace(row, pending_video_url=source.video_url)
                    self._rows[row.id] = row
                if row.transcript is None and transcript_document(source) is not None:
                    row = replace(
                        row,
                        transcript=transcript_document(source),
                        transcript_source=source.resolved_transcript_source(),
                    )
                    self._rows[row.id] = row
                return row, False
            row = AnalysisRecord(
                id=uuid4(),
                network=source.network,
                post_id=source.post_id,
                analysis_version=version,
                status=STATUS_QUEUED,
                post_url=source.post_url,
                pending_video_url=source.video_url or None,
                transcript=transcript_document(source),
                transcript_source=source.resolved_transcript_source(),
                created_at=now,
            )
            self._rows[row.id] = row
            return row, True

    def refresh_url(
        self, analysis_id: UUID, video_url: str, now: datetime, max_attempts: int
    ) -> AnalysisRecord | None:
        with self._lock:
            row = self._rows.get(analysis_id)
            if not _refreshable(row, max_attempts):
                return None
            assert row is not None
            row = replace(
                row,
                status=STATUS_QUEUED,
                error_code=None,
                pending_video_url=video_url,
                finished_at=None,
                stage=None,
            )
            self._rows[analysis_id] = row
            return row


def check_enqueueable(source: ReelSource) -> None:
    """A row is only made for a known network and a well-formed post id (the public R2
    door's own shape), so a malformed id never triggers a download."""
    from qualify_shared.objects.public import NETWORKS, is_reel_post_id  # noqa: PLC0415

    if source.network not in NETWORKS or not is_reel_post_id(source.post_id):
        raise ValueError("not an Instagram or TikTok reel id")


def _takes_fresh_url(row: AnalysisRecord, url: str) -> bool:
    """A queued row not downloaded yet, and not held right now, takes the URL a run just
    read (the screen's may be older)."""
    return bool(
        url
        and row.status == STATUS_QUEUED
        and row.source_key is None
        and row.lease_until is None
        and row.pending_video_url != url
    )


def _refreshable(row: AnalysisRecord | None, max_attempts: int) -> bool:
    return (
        row is not None
        and row.status == STATUS_FAILED
        and row.error_code in URL_ERRORS
        and row.source_key is None
        and row.attempts < max_attempts
        and row.model_calls < MAX_MODEL_CALLS
    )


def exhausted_code(row: AnalysisRecord) -> str:
    """The error a row that ran out of attempts ends with: a source never stored is a
    source problem; past the download it is the model's."""
    return ERROR_SOURCE_UNAVAILABLE if row.source_key is None else ERROR_MODEL_FAILED


def _fleet_calls(rows: Iterable[AnalysisRecord], since: datetime, now: datetime) -> int:
    """Model calls of the last 24 h: rows finished since then, plus every unfinished row
    (its calls happened at most a lease ago). An approximation that can only over-count —
    the guard errs towards spending less."""
    return sum(r.model_calls for r in rows if (r.finished_at or now) >= since)


class PostgresAnalysisRequests:
    """`AnalysisRequests` as `qualify_app`: only the enqueue columns are ever written."""

    _COLUMNS = (
        "id, network, post_id, analysis_version, status, post_url, created_at, stage, "
        "lease_token, lease_until, attempts, model_calls, error_code, wanted_at, "
        "pending_video_url, source_key, source_sha256, source_seconds, width, height, fps, "
        "covered_from_s, covered_to_s, edit_eligible, transcript, transcript_source, "
        "detector_version, sampling_version, sampling_params, model_id, model_revision, "
        "prompt_version, schema_version, input_tokens, output_tokens, cost_usd, reel_sheet, "
        "finished_at, source_purge_after, source_purged_at, frames_purged_at"
    )

    def _session(self, tenant_id: UUID) -> Any:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415

        return tenant_session(tenant_id)

    def find(
        self, tenant_id: UUID, network: str, post_id: str, version: int
    ) -> AnalysisRecord | None:
        from sqlalchemy import text  # noqa: PLC0415

        with self._session(tenant_id) as session:
            row = (
                session.execute(
                    text(
                        f"SELECT {self._COLUMNS} FROM public_reel_analyses "
                        "WHERE network = :n AND post_id = :p AND analysis_version = :v"
                    ),
                    {"n": network, "p": post_id, "v": version},
                )
                .mappings()
                .first()
            )
        return record_from_row(row) if row else None

    def get(self, tenant_id: UUID, analysis_id: UUID) -> AnalysisRecord | None:
        from sqlalchemy import text  # noqa: PLC0415

        with self._session(tenant_id) as session:
            row = (
                session.execute(
                    text(f"SELECT {self._COLUMNS} FROM public_reel_analyses WHERE id = :id"),
                    {"id": analysis_id},
                )
                .mappings()
                .first()
            )
        return record_from_row(row) if row else None

    def shots(self, tenant_id: UUID, analysis_id: UUID) -> list[ShotAnalysis]:
        from sqlalchemy import text  # noqa: PLC0415

        with self._session(tenant_id) as session:
            rows = (
                session.execute(
                    text(
                        "SELECT shot_index, start_s, end_s, frame_keys, frame_times_s, "
                        "people_presence, visible_faces, families, spoken_text "
                        "FROM public_reel_analysis_shots WHERE analysis_id = :id "
                        "ORDER BY shot_index"
                    ),
                    {"id": analysis_id},
                )
                .mappings()
                .all()
            )
        return [shot_from_row(r) for r in rows]

    def insert_queued(
        self,
        tenant_id: UUID,
        *,
        network: str,
        post_id: str,
        version: int,
        post_url: str,
        pending_video_url: str | None,
        wanted_at: datetime,
        quota: tuple[datetime, int] | None = None,
    ) -> UUID | None:
        """With `quota = (since, cap)` the count and the insert run in one transaction
        under `QUOTA_LOCK_KEY`, so two screens can never both take the last place."""
        from sqlalchemy import text  # noqa: PLC0415

        with self._session(tenant_id) as session:
            if quota is not None:
                session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": QUOTA_LOCK_KEY})
                exists = session.execute(
                    text(
                        "SELECT 1 FROM public_reel_analyses WHERE network = :n "
                        "AND post_id = :p AND analysis_version = :v"
                    ),
                    {"n": network, "p": post_id, "v": version},
                ).first()
                if exists is not None:
                    return None
                used = session.execute(
                    text("SELECT count(*) FROM public_reel_analyses WHERE wanted_at >= :s"),
                    {"s": quota[0]},
                ).scalar_one()
                if int(used) >= quota[1]:
                    raise OnDemandQuotaReached
            return session.execute(
                text(
                    "INSERT INTO public_reel_analyses (network, post_id, analysis_version, "
                    "post_url, pending_video_url, wanted_at) VALUES (:n, :p, :v, :u, :url, :w) "
                    "ON CONFLICT (network, post_id, analysis_version) DO NOTHING RETURNING id"
                ),
                {
                    "n": network,
                    "p": post_id,
                    "v": version,
                    "u": post_url,
                    "url": pending_video_url,
                    "w": wanted_at,
                },
            ).scalar()

    def mark_wanted(self, tenant_id: UUID, analysis_id: UUID, now: datetime) -> None:
        from sqlalchemy import text  # noqa: PLC0415

        with self._session(tenant_id) as session:
            session.execute(
                text(
                    "UPDATE public_reel_analyses SET wanted_at = :now "
                    "WHERE id = :id AND wanted_at IS NULL"
                ),
                {"id": analysis_id, "now": now},
            )

    def wanted_since(self, tenant_id: UUID, since: datetime) -> int:
        from sqlalchemy import text  # noqa: PLC0415

        with self._session(tenant_id) as session:
            return int(
                session.execute(
                    text("SELECT count(*) FROM public_reel_analyses WHERE wanted_at >= :s"),
                    {"s": since},
                ).scalar_one()
            )

    def queue_ahead(self, tenant_id: UUID, record: AnalysisRecord) -> int:
        from sqlalchemy import text  # noqa: PLC0415

        with self._session(tenant_id) as session:
            return int(
                session.execute(
                    text(
                        f"SELECT count(*) FROM public_reel_analyses WHERE id <> :id "
                        f"AND status IN ('queued','running') AND {QUEUE_ORDER_SQL} < "
                        "((:pending)::int, (:has_wanted)::int, CAST(:key AS timestamptz), "
                        "CAST(:created AS timestamptz))"
                    ),
                    {
                        "id": record.id,
                        "pending": 0 if record.pending_video_url else 1,
                        "has_wanted": 0 if record.wanted_at is not None else 1,
                        "key": record.wanted_at or record.created_at,
                        "created": record.created_at,
                    },
                ).scalar_one()
            )

    def model_calls_since(self, tenant_id: UUID, since: datetime, now: datetime) -> int:
        from sqlalchemy import text  # noqa: PLC0415

        with self._session(tenant_id) as session:
            return int(
                session.execute(text(FLEET_CALLS_SQL), {"since": since, "now": now}).scalar_one()
            )

    def badges(
        self, tenant_id: UUID, keys: Sequence[tuple[str, str]], version: int
    ) -> dict[tuple[str, str], str]:
        from sqlalchemy import text  # noqa: PLC0415

        out = {key: BADGE_NOT_ANALYZED for key in keys}
        if not keys:
            return out
        networks = [k[0] for k in keys]
        posts = [k[1] for k in keys]
        with self._session(tenant_id) as session:
            rows = (
                session.execute(
                    text(
                        "SELECT a.network, a.post_id, a.status, "
                        "bool_or(s.people_presence = 'observed' OR s.visible_faces = 'observed') "
                        "AS person "
                        "FROM public_reel_analyses a "
                        "JOIN unnest(CAST(:nets AS text[]), CAST(:posts AS text[])) AS k(n, p) "
                        "ON a.network = k.n AND a.post_id = k.p "
                        "LEFT JOIN public_reel_analysis_shots s ON s.analysis_id = a.id "
                        "WHERE a.analysis_version = :v "
                        "GROUP BY a.network, a.post_id, a.status"
                    ),
                    {"nets": networks, "posts": posts, "v": version},
                )
                .mappings()
                .all()
            )
        for r in rows:
            key = (r["network"], r["post_id"])
            if r["status"] == STATUS_OK:
                out[key] = BADGE_PERSON if r["person"] else BADGE_NONE
            elif r["status"] in (STATUS_QUEUED, STATUS_RUNNING):
                out[key] = BADGE_LOOKING
        return out


#: `_queue_order` in SQL (the claim's ORDER BY and `queue_ahead` agree on it).
QUEUE_ORDER_SQL = (
    "((pending_video_url IS NULL)::int, (wanted_at IS NULL)::int, "
    "COALESCE(wanted_at, created_at), created_at)"
)
#: `_fleet_calls` in SQL.
FLEET_CALLS_SQL = (
    "SELECT COALESCE(sum(model_calls), 0) FROM public_reel_analyses "
    "WHERE COALESCE(finished_at, CAST(:now AS timestamptz)) >= :since"
)


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


def record_from_row(row: Mapping[str, Any]) -> AnalysisRecord:
    return AnalysisRecord(
        id=row["id"],
        network=row["network"],
        post_id=row["post_id"],
        analysis_version=row["analysis_version"],
        status=row["status"],
        post_url=row["post_url"],
        created_at=row["created_at"],
        stage=row["stage"],
        lease_token=row["lease_token"],
        lease_until=row["lease_until"],
        attempts=row["attempts"],
        model_calls=row["model_calls"],
        error_code=row["error_code"],
        wanted_at=row["wanted_at"],
        pending_video_url=row["pending_video_url"],
        source_key=row["source_key"],
        source_sha256=row["source_sha256"],
        source_seconds=_f(row["source_seconds"]),
        width=row["width"],
        height=row["height"],
        fps=_f(row["fps"]),
        covered_from_s=_f(row["covered_from_s"]),
        covered_to_s=_f(row["covered_to_s"]),
        edit_eligible=row["edit_eligible"],
        transcript=row["transcript"],
        transcript_source=row["transcript_source"],
        detector_version=row["detector_version"],
        sampling_version=row["sampling_version"],
        sampling_params=row["sampling_params"],
        model_id=row["model_id"],
        model_revision=row["model_revision"],
        prompt_version=row["prompt_version"],
        schema_version=row["schema_version"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cost_usd=Decimal(row["cost_usd"]),
        reel_sheet=row["reel_sheet"],
        finished_at=row["finished_at"],
        source_purge_after=row["source_purge_after"],
        source_purged_at=row["source_purged_at"],
        frames_purged_at=row["frames_purged_at"],
    )


def shot_from_row(row: Mapping[str, Any]) -> ShotAnalysis:
    return ShotAnalysis(
        shot_index=int(row["shot_index"]),
        start_s=float(row["start_s"]),
        end_s=float(row["end_s"]),
        frame_keys=tuple(row["frame_keys"] or ()),
        frame_times_s=tuple(float(t) for t in row["frame_times_s"] or ()),
        people_presence=row["people_presence"],
        visible_faces=row["visible_faces"],
        families=dict(row["families"] or {}),
        spoken_text=row["spoken_text"] or "",
    )


__all__ = [
    "BADGE_LOOKING",
    "BADGE_NONE",
    "BADGE_NOT_ANALYZED",
    "BADGE_PERSON",
    "CALL_FLEET_CAP",
    "CALL_LOST",
    "CALL_OK",
    "CALL_ROW_CAP",
    "FLEET_LOCK_KEY",
    "MAX_MODEL_CALLS",
    "QUOTA_LOCK_KEY",
    "OnDemandQuotaReached",
    "AnalysisQueue",
    "AnalysisRecord",
    "AnalysisRequests",
    "Claimed",
    "DescribeResult",
    "DueSource",
    "Spend",
    "InMemoryAnalysisStore",
    "PostgresAnalysisRequests",
    "SourceFacts",
    "badge_for",
    "check_enqueueable",
    "exhausted_code",
    "record_from_row",
    "shot_from_row",
    "transcript_document",
]
