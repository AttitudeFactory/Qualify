"""Where the persistent reels run keeps what it paid for (ADR 42 R4, m-24854848).

Two halves over the tables of migration 0117:

- **Global, public data** (`reel_accounts`, `public_reels`; no `tenant_id`, no RLS): one
  row per public account and per public reel, shared by every business — two businesses
  that follow the same account pay ONE read. Nothing written here names the tenant or
  brand that triggered it (0117's rule). `qualify_app` reaches them through the same
  `tenant_session` as the rest (the tables have no policy to scope them), so the run never
  needs a tenant-less door.
- **Per business** (`brand_reel_runs`, `brand_reel_verdicts`, `brand_reel_ideas`; RLS):
  the runs, Claude's verdicts with their provenance, and the ideas a run kept.

`ReelRunStore` is the seam; `PostgresReelRunStore` is the real one and
`MemoryReelRunStore` the offline twin the tests drive. Every timestamp comes from the
caller's clock, so a run is reproducible under a fake clock in both.

R8 (m-24854855, migration 0126) adds the run's lifecycle under the `reels-worker`:
`claim` counts an attempt (`attempts`); `progress`, `finish` and `save_ideas` (which replaces
an earlier attempt's ideas) write only while the run is still `running` with the
`started_at` its claim set — a fencing token, so a process
whose run was recovered meanwhile never overwrites the new attempt; `release` puts a
claimed run back in the queue (a SIGTERM, or a stale run) and `abandon` ends a stale run
that spent its attempts, both behind the same fence. `brand_reel_activity` keeps when
the owner last opened the screen (`mark_opened`), the signal of ADR 42 §2.6.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.orm import Session

#: `save_transcript` takes a `text=` argument (the transcript); the SQL builder is `_text`.
_text = text

TRIGGER_WEEKLY = "weekly"
TRIGGER_MANUAL = "manual"
TRIGGER_OPERATOR_90D = "operator_90d"
TRIGGERS = (TRIGGER_WEEKLY, TRIGGER_MANUAL, TRIGGER_OPERATOR_90D)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_OK = "ok"
#: The check could not run (no brief, no key, Claude down). Whatever was read stays
#: stored; a retry pays nothing already paid and only redoes the review.
STATUS_CHECK_FAILED = "check_failed"
#: The metered gate refused a paid call (switch off, 500-credit floor, a 402, or the
#: business's daily / monthly cap of ADR 42 R5).
STATUS_BUDGET_STOPPED = "budget_stopped"
STATUS_ERROR = "error"
#: What `enqueue_run(retry=True)` puts back in the queue («Intentar de nuevo», a later
#: slice: no screen calls it yet).
RETRYABLE = frozenset({STATUS_CHECK_FAILED, STATUS_ERROR})

ACCOUNT_OK = "ok"
ACCOUNT_MISSING = "missing"
ACCOUNT_PRIVATE = "private"
ACCOUNT_ERROR = "error"

TRANSCRIPT_VENDOR = "vendor_stt"
TRANSCRIPT_TIKTOK = "tiktok_vtt"
TRANSCRIPT_NONE = "none"


@dataclass(frozen=True)
class RunRecord:
    id: UUID
    tenant_id: UUID
    brand_id: UUID
    trigger: str
    run_date: date
    status: str
    days: int
    accounts_total: int
    accounts_done: int
    credits: int
    cost_usd: Decimal
    brief_hash: str | None
    pipeline_version: str
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    #: How many times the run was claimed (0126); `enqueue_run(retry=True)` sets it back
    #: to 0.
    attempts: int = 0


@dataclass(frozen=True)
class AccountState:
    """A public account's refresh bookkeeping (`reel_accounts`)."""

    network: str
    handle: str
    page1_at: datetime | None = None
    full_walk_at: datetime | None = None
    covered_days: int = 0
    newest_taken_at: datetime | None = None
    status: str = ACCOUNT_OK
    last_http_status: int | None = None
    credits_total: int = 0
    refresh_lock_until: datetime | None = None


@dataclass(frozen=True)
class PublicReel:
    """One public reel (`public_reels`) as the run reads and writes it. `transcript_at`
    None = never transcribed; set = known, even when the video says nothing ("")."""

    network: str
    reel_id: str
    handle: str
    taken_at: datetime
    metrics_at: datetime
    parser_version: int
    caption: str = ""
    duration_s: float | None = None
    sound: str = ""
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    saves: int | None = None
    shares: int | None = None
    video_url: str | None = None
    transcript: str | None = None
    transcript_source: str = TRANSCRIPT_NONE
    transcript_at: datetime | None = None
    #: When `video_url` was read: the vendor's signed CDN URL lives 24-33 h (0117).
    video_url_at: datetime | None = None
    # parser 2 (m-24946121, migration 0125). `coauthors` / `sound_id` /
    # `sound_is_original` None = not read; `is_paid_partnership` False = not declared.
    is_paid_partnership: bool = False
    coauthors: tuple[str, ...] | None = None
    sound_id: str | None = None
    sound_is_original: bool | None = None
    counts_hidden: bool = False
    #: Provenance: the raw page (`vendor_payloads.id`) and WHICH fetch of it (0117).
    source_payload_id: UUID | None = None
    source_payload_fetched_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.coauthors is not None:
            object.__setattr__(self, "coauthors", tuple(self.coauthors))
        if self.source_payload_id is not None and self.source_payload_fetched_at is None:
            raise ValueError("source_payload_id needs source_payload_fetched_at")


@dataclass(frozen=True)
class NewVerdict:
    """Claude's judgement of one reel for one brand, with its provenance."""

    network: str
    reel_id: str
    brief_hash: str
    input_hash: str
    fits: bool
    model_id: str
    prompt_version: str
    affinity: str = ""
    format: str = ""
    hook: str = ""
    reason: str = ""
    effort: str | None = None
    cost_usd: Decimal = Decimal("0")

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.network, self.reel_id, self.input_hash)


@dataclass(frozen=True)
class StoredVerdict(NewVerdict):
    id: UUID = field(default_factory=uuid4)


@dataclass(frozen=True)
class NewIdea:
    network: str
    reel_id: str
    rank: int
    window_days: int
    verdict_id: UUID | None


@dataclass(frozen=True)
class Idea:
    """One idea of a run, as the view reads it: the reel and the verdict that kept it."""

    rank: int
    window_days: int
    reel: PublicReel
    verdict: StoredVerdict | None
    seen_at: datetime | None = None
    #: The shared analysis stored the reel's source in R2, not purged yet (ADR 44 VE-04a;
    #: R8).
    source_available: bool = False
    #: «Replicar con mi marca» can work now: the stored source, or a CDN URL still usable
    #: (`reel_analysis_source.url_is_stale`). Set by `reel_runs.view()`.
    can_replicate: bool = False


class ReelRunStore(Protocol):
    # -- runs (per tenant, RLS) ------------------------------------------------------
    def enqueue(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        *,
        trigger: str,
        run_date: date,
        days: int,
        pipeline_version: str,
        now: datetime,
        retry: bool = False,
    ) -> RunRecord: ...

    def get_run(self, tenant_id: UUID, run_id: UUID) -> RunRecord | None: ...

    def claim(self, tenant_id: UUID, run_id: UUID, *, now: datetime) -> RunRecord | None:
        """`queued` → `running` (`started_at = now`, one more attempt); None when the run
        is not `queued` (another worker has it, or it already ended)."""
        ...

    def progress(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        accounts_total: int,
        accounts_done: int,
        started_at: datetime,
    ) -> bool:
        """Written only while the run is `running` with this `started_at` (the claim's
        fencing token); False when it is no longer that claim's."""
        ...

    def finish(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        status: str,
        now: datetime,
        credits: int,
        cost_usd: Decimal,
        brief_hash: str | None,
        started_at: datetime,
    ) -> bool:
        """Same fence as `progress`; False when the run is no longer that claim's."""
        ...

    def release(self, tenant_id: UUID, run_id: UUID, *, started_at: datetime) -> bool:
        """The claimed run back to `queued` (its `queued_at` and attempts kept), behind the
        same fence; False when it was not that claim's any more."""
        ...

    def abandon(
        self, tenant_id: UUID, run_id: UUID, *, started_at: datetime, now: datetime
    ) -> bool:
        """The claimed run ends `error`, behind the same fence."""
        ...

    def retry_check(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        finished_before: datetime,
        finished_after: datetime,
        max_attempts: int,
    ) -> bool:
        """The brand's LATEST run (`latest_run`'s order: what the screen shows), when it is
        `check_failed`, was claimed fewer than `max_attempts` times and ended after
        `finished_after` and before `finished_before`, goes back to `queued` (its
        `queued_at` and attempts kept); False when it is not such a run (any more)."""
        ...

    def add_cost(self, tenant_id: UUID, run_id: UUID, cost_usd: Decimal) -> None: ...

    def latest_run(
        self, tenant_id: UUID, brand_id: UUID, *, status: str | None = None
    ) -> RunRecord | None: ...

    # -- the screen's opening and the tenant's clock (R8) ------------------------------
    def mark_opened(
        self, tenant_id: UUID, brand_id: UUID, *, now: datetime, every: timedelta
    ) -> None:
        """`brand_reel_activity.last_opened_at = now`, only forward and only when the stored
        one is at least `every` older."""
        ...

    def timezone(self, tenant_id: UUID) -> str:
        """The tenant's IANA timezone (`tenants.timezone`); LookupError when unknown."""
        ...

    # -- public accounts and reels (global) -----------------------------------------
    def account(self, tenant_id: UUID, network: str, handle: str) -> AccountState | None: ...

    def try_lock_account(
        self, tenant_id: UUID, network: str, handle: str, *, now: datetime, until: datetime
    ) -> bool: ...

    def finish_account(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        *,
        now: datetime,
        status: str,
        http_status: int | None = None,
        page1: bool = False,
        full_walk_days: int | None = None,
        newest_taken_at: datetime | None = None,
        credits: int = 0,
        lock_until: datetime | None = None,
    ) -> None:
        """Record a refresh. The lock is cleared only while it is still the caller's
        (`refresh_lock_until == lock_until`): a lock another run has taken since — after
        this one's expired — is never released by this one."""
        ...

    def release_account(
        self, tenant_id: UUID, network: str, handle: str, *, lock_until: datetime
    ) -> None:
        """Clear the caller's lock (same rule as `finish_account`), changing nothing else."""
        ...

    def upsert_reels(self, tenant_id: UUID, reels: Sequence[PublicReel]) -> None: ...

    def reels_of(
        self, tenant_id: UUID, accounts: Sequence[tuple[str, str]], *, since: datetime
    ) -> list[PublicReel]: ...

    def save_transcript(
        self,
        tenant_id: UUID,
        network: str,
        reel_id: str,
        *,
        text: str,
        source: str,
        now: datetime,
    ) -> None: ...

    # -- verdicts and ideas (per tenant, RLS) ---------------------------------------
    def verdicts(
        self, tenant_id: UUID, brand_id: UUID, *, brief_hash: str, reel_ids: Sequence[str]
    ) -> dict[tuple[str, str, str], StoredVerdict]: ...

    def save_verdicts(
        self, tenant_id: UUID, brand_id: UUID, verdicts: Sequence[NewVerdict]
    ) -> dict[tuple[str, str, str], StoredVerdict]: ...

    def save_ideas(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        run_id: UUID,
        ideas: Sequence[NewIdea],
        *,
        started_at: datetime,
    ) -> bool:
        """The run's ideas become exactly `ideas`: an earlier attempt's are replaced, so
        a run done again under the same id never mixes two rankings. Same fence as
        `progress`; False (and nothing written) when the run is no longer that claim's."""
        ...

    def ideas(self, tenant_id: UUID, brand_id: UUID, run_id: UUID) -> list[Idea]: ...


# ======================================================================================
# In memory — the offline twin
# ======================================================================================


class MemoryReelRunStore:
    """`ReelRunStore` in process memory, with the same idempotency, monotonic guards and
    tenant scoping as Postgres. `writes` counts every write, so a test can pin that a
    read-only path wrote nothing."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.runs: dict[UUID, RunRecord] = {}
        #: brand → (tenant, last_opened_at): `brand_reel_activity`.
        self.activity: dict[UUID, tuple[UUID, datetime]] = {}
        #: tenant → IANA timezone: `tenants.timezone`.
        self.timezones: dict[UUID, str] = {}
        #: (network, reel_id) whose video a run kept in R2 (`public_reel_analyses`).
        self.stored_sources: set[tuple[str, str]] = set()
        self.accounts: dict[tuple[str, str], AccountState] = {}
        self.reels: dict[tuple[str, str], PublicReel] = {}
        self.verdict_rows: dict[UUID, tuple[UUID, UUID, StoredVerdict]] = {}
        self.idea_rows: list[tuple[UUID, UUID, UUID, NewIdea, datetime | None]] = []
        self.writes = 0

    def _write(self) -> None:
        self.writes += 1

    # runs
    def enqueue(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        *,
        trigger: str,
        run_date: date,
        days: int,
        pipeline_version: str,
        now: datetime,
        retry: bool = False,
    ) -> RunRecord:
        with self._lock:
            for record in self.runs.values():
                if (record.brand_id, record.trigger, record.run_date) == (
                    brand_id,
                    trigger,
                    run_date,
                ):
                    if record.tenant_id != tenant_id:
                        raise PermissionError("another tenant's brand")
                    if retry and record.status in RETRYABLE:
                        self._write()
                        record = replace(
                            record,
                            status=STATUS_QUEUED,
                            queued_at=now,
                            started_at=None,
                            finished_at=None,
                            accounts_done=0,
                            accounts_total=0,
                            attempts=0,
                        )
                        self.runs[record.id] = record
                    return record
            self._write()
            record = RunRecord(
                id=uuid4(),
                tenant_id=tenant_id,
                brand_id=brand_id,
                trigger=trigger,
                run_date=run_date,
                status=STATUS_QUEUED,
                days=days,
                accounts_total=0,
                accounts_done=0,
                credits=0,
                cost_usd=Decimal("0"),
                brief_hash=None,
                pipeline_version=pipeline_version,
                queued_at=now,
                started_at=None,
                finished_at=None,
            )
            self.runs[record.id] = record
            return record

    def get_run(self, tenant_id: UUID, run_id: UUID) -> RunRecord | None:
        record = self.runs.get(run_id)
        return record if record is not None and record.tenant_id == tenant_id else None

    def claim(self, tenant_id: UUID, run_id: UUID, *, now: datetime) -> RunRecord | None:
        with self._lock:
            record = self.get_run(tenant_id, run_id)
            if record is None or record.status != STATUS_QUEUED:
                return None
            self._write()
            record = replace(
                record, status=STATUS_RUNNING, started_at=now, attempts=record.attempts + 1
            )
            self.runs[run_id] = record
            return record

    def _update(self, tenant_id: UUID, run_id: UUID, **values: Any) -> None:
        with self._lock:
            record = self.get_run(tenant_id, run_id)
            if record is None:
                return
            self._write()
            self.runs[run_id] = replace(record, **values)

    def _fenced(self, tenant_id: UUID, run_id: UUID, fence: datetime, **values: Any) -> bool:
        """Apply `values` only while the run is still `running` under the claim that set
        its `started_at` to `fence`."""
        with self._lock:
            record = self.get_run(tenant_id, run_id)
            if record is None or (record.status, record.started_at) != (STATUS_RUNNING, fence):
                return False
            self._write()
            self.runs[run_id] = replace(record, **values)
            return True

    def progress(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        accounts_total: int,
        accounts_done: int,
        started_at: datetime,
    ) -> bool:
        return self._fenced(
            tenant_id,
            run_id,
            started_at,
            accounts_total=accounts_total,
            accounts_done=accounts_done,
        )

    def finish(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        status: str,
        now: datetime,
        credits: int,
        cost_usd: Decimal,
        brief_hash: str | None,
        started_at: datetime,
    ) -> bool:
        with self._lock:
            record = self.get_run(tenant_id, run_id)
            if record is None:
                return False
            return self._fenced(
                tenant_id,
                run_id,
                started_at,
                status=status,
                finished_at=now,
                credits=record.credits + credits,
                cost_usd=record.cost_usd + cost_usd,
                brief_hash=brief_hash,
            )

    def release(self, tenant_id: UUID, run_id: UUID, *, started_at: datetime) -> bool:
        return self._fenced(
            tenant_id,
            run_id,
            started_at,
            status=STATUS_QUEUED,
            started_at=None,
            accounts_done=0,
            accounts_total=0,
        )

    def abandon(
        self, tenant_id: UUID, run_id: UUID, *, started_at: datetime, now: datetime
    ) -> bool:
        return self._fenced(tenant_id, run_id, started_at, status=STATUS_ERROR, finished_at=now)

    def retry_check(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        finished_before: datetime,
        finished_after: datetime,
        max_attempts: int,
    ) -> bool:
        with self._lock:
            record = self.get_run(tenant_id, run_id)
            latest = self.latest_run(tenant_id, record.brand_id) if record else None
            if (
                record is None
                or latest is None
                or latest.id != record.id
                or record.status != STATUS_CHECK_FAILED
                or record.attempts >= max_attempts
                or record.finished_at is None
                or record.finished_at > finished_before
                or record.finished_at <= finished_after
            ):
                return False
            self._write()
            self.runs[run_id] = replace(
                record,
                status=STATUS_QUEUED,
                started_at=None,
                finished_at=None,
                accounts_done=0,
                accounts_total=0,
            )
            return True

    def add_cost(self, tenant_id: UUID, run_id: UUID, cost_usd: Decimal) -> None:
        record = self.get_run(tenant_id, run_id)
        if record is not None:
            self._update(tenant_id, run_id, cost_usd=record.cost_usd + cost_usd)

    def latest_run(
        self, tenant_id: UUID, brand_id: UUID, *, status: str | None = None
    ) -> RunRecord | None:
        mine = [
            r
            for r in self.runs.values()
            if r.tenant_id == tenant_id
            and r.brand_id == brand_id
            and (status is None or r.status == status)
        ]
        return max(
            mine, key=lambda r: (r.finished_at or r.queued_at, r.queued_at, r.id), default=None
        )

    # the screen's opening and the tenant's clock
    def mark_opened(
        self, tenant_id: UUID, brand_id: UUID, *, now: datetime, every: timedelta
    ) -> None:
        with self._lock:
            stored = self.activity.get(brand_id)
            if stored is not None:
                if stored[0] != tenant_id:
                    raise PermissionError("another tenant's brand")
                if stored[1] > now - every:
                    return  # only forward, at most one write per `every`
            self._write()
            self.activity[brand_id] = (tenant_id, now)

    def timezone(self, tenant_id: UUID) -> str:
        try:
            return self.timezones[tenant_id]
        except KeyError:
            raise LookupError(f"no timezone for tenant {tenant_id}") from None

    # accounts and reels
    def account(self, tenant_id: UUID, network: str, handle: str) -> AccountState | None:
        return self.accounts.get((network, handle))

    def try_lock_account(
        self, tenant_id: UUID, network: str, handle: str, *, now: datetime, until: datetime
    ) -> bool:
        with self._lock:
            state = self.accounts.get((network, handle)) or AccountState(network, handle)
            if state.refresh_lock_until is not None and state.refresh_lock_until > now:
                self.accounts[(network, handle)] = state
                return False
            self._write()
            self.accounts[(network, handle)] = replace(state, refresh_lock_until=until)
            return True

    def finish_account(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        *,
        now: datetime,
        status: str,
        http_status: int | None = None,
        page1: bool = False,
        full_walk_days: int | None = None,
        newest_taken_at: datetime | None = None,
        credits: int = 0,
        lock_until: datetime | None = None,
    ) -> None:
        with self._lock:
            self._write()
            state = self.accounts.get((network, handle)) or AccountState(network, handle)
            newest = state.newest_taken_at
            if newest_taken_at is not None and (newest is None or newest_taken_at > newest):
                newest = newest_taken_at
            self.accounts[(network, handle)] = replace(
                state,
                page1_at=now if page1 else state.page1_at,
                full_walk_at=now if full_walk_days else state.full_walk_at,
                covered_days=full_walk_days if full_walk_days else state.covered_days,
                newest_taken_at=newest,
                status=status,
                last_http_status=http_status,
                credits_total=state.credits_total + credits,
                refresh_lock_until=None
                if lock_until is not None and state.refresh_lock_until == lock_until
                else state.refresh_lock_until,
            )

    def release_account(
        self, tenant_id: UUID, network: str, handle: str, *, lock_until: datetime
    ) -> None:
        with self._lock:
            state = self.accounts.get((network, handle))
            if state is not None and state.refresh_lock_until == lock_until:
                self._write()
                self.accounts[(network, handle)] = replace(state, refresh_lock_until=None)

    def upsert_reels(self, tenant_id: UUID, reels: Sequence[PublicReel]) -> None:
        with self._lock:
            for reel in reels:
                key = (reel.network, reel.reel_id)
                old = self.reels.get(key)
                if old is not None and reel.metrics_at <= old.metrics_at:
                    continue  # the monotonic guard: a late write never wins
                self._write()
                if old is not None:
                    reel = replace(
                        reel,
                        video_url=reel.video_url or old.video_url,
                        video_url_at=reel.video_url_at if reel.video_url else old.video_url_at,
                        transcript=old.transcript,
                        transcript_source=old.transcript_source,
                        transcript_at=old.transcript_at,
                        coauthors=old.coauthors if reel.coauthors is None else reel.coauthors,
                        sound_id=reel.sound_id or old.sound_id,
                        sound_is_original=old.sound_is_original
                        if reel.sound_is_original is None
                        else reel.sound_is_original,
                    )
                self.reels[key] = reel

    def reels_of(
        self, tenant_id: UUID, accounts: Sequence[tuple[str, str]], *, since: datetime
    ) -> list[PublicReel]:
        wanted = set(accounts)
        return [
            r
            for r in self.reels.values()
            if (r.network, r.handle) in wanted and r.taken_at >= since
        ]

    def save_transcript(
        self,
        tenant_id: UUID,
        network: str,
        reel_id: str,
        *,
        text: str,
        source: str,
        now: datetime,
    ) -> None:
        with self._lock:
            reel = self.reels.get((network, reel_id))
            if reel is None or reel.transcript_at is not None:
                return  # never overwritten: a transcript is paid once
            self._write()
            self.reels[(network, reel_id)] = replace(
                reel, transcript=text, transcript_source=source, transcript_at=now
            )

    # verdicts and ideas
    def verdicts(
        self, tenant_id: UUID, brand_id: UUID, *, brief_hash: str, reel_ids: Sequence[str]
    ) -> dict[tuple[str, str, str], StoredVerdict]:
        ids = set(reel_ids)
        return {
            v.key: v
            for tenant, brand, v in self.verdict_rows.values()
            if tenant == tenant_id
            and brand == brand_id
            and v.brief_hash == brief_hash
            and v.reel_id in ids
        }

    def save_verdicts(
        self, tenant_id: UUID, brand_id: UUID, verdicts: Sequence[NewVerdict]
    ) -> dict[tuple[str, str, str], StoredVerdict]:
        out: dict[tuple[str, str, str], StoredVerdict] = {}
        with self._lock:
            for verdict in verdicts:
                existing = next(
                    (
                        v
                        for tenant, brand, v in self.verdict_rows.values()
                        if tenant == tenant_id
                        and brand == brand_id
                        and v.key == verdict.key
                        and v.brief_hash == verdict.brief_hash
                    ),
                    None,
                )
                if existing is None:
                    self._write()
                    existing = StoredVerdict(**_fields(verdict))
                    self.verdict_rows[existing.id] = (tenant_id, brand_id, existing)
                out[existing.key] = existing
        return out

    def save_ideas(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        run_id: UUID,
        ideas: Sequence[NewIdea],
        *,
        started_at: datetime,
    ) -> bool:
        with self._lock:
            record = self.get_run(tenant_id, run_id)
            if record is None or (record.status, record.started_at) != (
                STATUS_RUNNING,
                started_at,
            ):
                return False
            self._write()
            kept = [row for row in self.idea_rows if row[2] != run_id]
            have: set[tuple[str, str]] = set()
            for idea in ideas:
                if (idea.network, idea.reel_id) in have:
                    continue  # uq_brand_reel_idea
                have.add((idea.network, idea.reel_id))
                kept.append((tenant_id, brand_id, run_id, idea, None))
            self.idea_rows[:] = kept
            return True

    def ideas(self, tenant_id: UUID, brand_id: UUID, run_id: UUID) -> list[Idea]:
        out: list[Idea] = []
        for tenant, brand, run, idea, seen in self.idea_rows:
            if (tenant, brand, run) != (tenant_id, brand_id, run_id):
                continue
            reel = self.reels.get((idea.network, idea.reel_id))
            if reel is None:
                continue
            verdict = self.verdict_rows.get(idea.verdict_id) if idea.verdict_id else None
            out.append(
                Idea(
                    rank=idea.rank,
                    window_days=idea.window_days,
                    reel=reel,
                    verdict=verdict[2] if verdict else None,
                    seen_at=seen,
                    source_available=(idea.network, idea.reel_id) in self.stored_sources,
                )
            )
        return sorted(out, key=lambda i: i.rank)


def _fields(verdict: NewVerdict) -> dict[str, Any]:
    return {name: getattr(verdict, name) for name in NewVerdict.__dataclass_fields__}


# ======================================================================================
# Postgres
# ======================================================================================

_RUN_COLUMNS = (
    "id, tenant_id, brand_id, trigger, run_date, status, days, accounts_total, "
    "accounts_done, credits, cost_usd, brief_hash, pipeline_version, queued_at, "
    "started_at, finished_at, attempts"
)
#: The fence of every write on a claimed run (R8): still `running`, still this claim's.
_FENCE = "id = :id AND status = 'running' AND started_at = :started_at"
_REEL_COLUMNS = (
    "network, reel_id, handle, taken_at, metrics_at, parser_version, caption, duration_s, "
    "sound, views, likes, comments, saves, shares, video_url, transcript, "
    "transcript_source, transcript_at, video_url_at, is_paid_partnership, coauthors, "
    "sound_id, sound_is_original, counts_hidden, source_payload_id, source_payload_fetched_at"
)
_VERDICT_COLUMNS = (
    "id, network, reel_id, brief_hash, input_hash, fits, model_id, prompt_version, "
    "affinity, format, hook, reason, effort, cost_usd"
)


def _run(row: Any) -> RunRecord:
    return RunRecord(**dict(row._mapping))


def _reel(row: Any, prefix: str = "") -> PublicReel:
    data = {name: row._mapping[prefix + name] for name in PublicReel.__dataclass_fields__}
    sound = data["sound"]
    data["sound"] = str(sound.get("title") or "") if isinstance(sound, dict) else ""
    if data["duration_s"] is not None:
        data["duration_s"] = float(data["duration_s"])
    coauthors = data["coauthors"]
    data["coauthors"] = tuple(str(c) for c in coauthors) if isinstance(coauthors, list) else None
    return PublicReel(**data)


def _verdict(row: Any, prefix: str = "") -> StoredVerdict:
    return StoredVerdict(
        **{name: row._mapping[prefix + name] for name in StoredVerdict.__dataclass_fields__}
    )


#: The brand's latest run, the one the screen shows (`latest_run`) and the only one the
#: worker retries (`retry_check`): one order for both.
_LATEST_ORDER = "COALESCE(finished_at, queued_at) DESC, queued_at DESC, id DESC"
_LATEST_OF_BRAND = (
    "SELECT l.id FROM brand_reel_runs l WHERE l.brand_id = r.brand_id ORDER BY "
    "COALESCE(l.finished_at, l.queued_at) DESC, l.queued_at DESC, l.id DESC LIMIT 1"
)


_UPSERT_REELS = text(
    "INSERT INTO public_reels (network, reel_id, handle, taken_at, metrics_at, "
    "parser_version, caption, duration_s, sound, views, likes, comments, saves, "
    "shares, video_url, video_url_at, is_paid_partnership, coauthors, sound_id, "
    "sound_is_original, counts_hidden, source_payload_id, source_payload_fetched_at) "
    "VALUES (:network, :reel_id, :handle, :taken_at, :metrics_at, :parser_version, "
    ":caption, :duration_s, CAST(:sound AS jsonb), :views, :likes, :comments, :saves, "
    ":shares, :video_url, :video_url_at, :is_paid_partnership, CAST(:coauthors AS jsonb), "
    ":sound_id, :sound_is_original, :counts_hidden, :source_payload_id, "
    ":source_payload_fetched_at) "
    "ON CONFLICT ON CONSTRAINT uq_public_reel DO UPDATE SET "
    "handle = EXCLUDED.handle, taken_at = EXCLUDED.taken_at, "
    "metrics_at = EXCLUDED.metrics_at, "
    "parser_version = EXCLUDED.parser_version, caption = EXCLUDED.caption, "
    "duration_s = EXCLUDED.duration_s, sound = EXCLUDED.sound, "
    "views = EXCLUDED.views, likes = EXCLUDED.likes, "
    "comments = EXCLUDED.comments, saves = EXCLUDED.saves, "
    "shares = EXCLUDED.shares, "
    "video_url = COALESCE(EXCLUDED.video_url, public_reels.video_url), "
    "video_url_at = CASE WHEN EXCLUDED.video_url IS NULL "
    "THEN public_reels.video_url_at ELSE EXCLUDED.video_url_at END, "
    "is_paid_partnership = EXCLUDED.is_paid_partnership, "
    # NULL = this write did not read it: keep what an earlier parser read
    "coauthors = COALESCE(EXCLUDED.coauthors, public_reels.coauthors), "
    "sound_id = COALESCE(EXCLUDED.sound_id, public_reels.sound_id), "
    "sound_is_original = COALESCE(EXCLUDED.sound_is_original, "
    "public_reels.sound_is_original), "
    "counts_hidden = EXCLUDED.counts_hidden, "
    # the counters now come from this write: so does their provenance
    "source_payload_id = EXCLUDED.source_payload_id, "
    "source_payload_fetched_at = EXCLUDED.source_payload_fetched_at, "
    "updated_at = EXCLUDED.metrics_at "
    # the monotonic guard: a late retry never overwrites newer metrics
    "WHERE EXCLUDED.metrics_at > public_reels.metrics_at"
)


def upsert_reels_in(session: Session, reels: Sequence[PublicReel]) -> None:
    """Upsert `public_reels` inside an open session, with the monotonic guard on
    `metrics_at` — so the Creators read writes its reels in the same transaction as its
    snapshot (design §8.3) without writing SQL over this module's tables."""
    if not reels:
        return
    rows = [
        {
            "network": r.network,
            "reel_id": r.reel_id,
            "handle": r.handle,
            "taken_at": r.taken_at,
            "metrics_at": r.metrics_at,
            "parser_version": r.parser_version,
            "caption": r.caption,
            "duration_s": r.duration_s,
            "sound": json.dumps({"title": r.sound}) if r.sound else None,
            "views": r.views,
            "likes": r.likes,
            "comments": r.comments,
            "saves": r.saves,
            "shares": r.shares,
            "video_url": r.video_url,
            "video_url_at": r.metrics_at if r.video_url else None,
            "is_paid_partnership": r.is_paid_partnership,
            "coauthors": json.dumps(list(r.coauthors)) if r.coauthors is not None else None,
            "sound_id": r.sound_id,
            "sound_is_original": r.sound_is_original,
            "counts_hidden": r.counts_hidden,
            "source_payload_id": r.source_payload_id,
            "source_payload_fetched_at": r.source_payload_fetched_at,
        }
        for r in reels
    ]
    session.execute(_UPSERT_REELS, rows)


class PostgresReelRunStore:
    """`ReelRunStore` over migration 0117, every statement inside `tenant_session` — the
    RLS policies scope the per-tenant tables; the global ones have none to scope."""

    # runs
    def enqueue(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        *,
        trigger: str,
        run_date: date,
        days: int,
        pipeline_version: str,
        now: datetime,
        retry: bool = False,
    ) -> RunRecord:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(
                    "INSERT INTO brand_reel_runs (tenant_id, brand_id, trigger, run_date, "
                    "days, pipeline_version, queued_at) VALUES (:tenant, :brand, :trigger, "
                    ":run_date, :days, :pipeline, :now) "
                    "ON CONFLICT ON CONSTRAINT uq_brand_reel_run DO NOTHING "
                    f"RETURNING {_RUN_COLUMNS}"
                ),
                {
                    "tenant": tenant_id,
                    "brand": brand_id,
                    "trigger": trigger,
                    "run_date": run_date,
                    "days": days,
                    "pipeline": pipeline_version,
                    "now": now,
                },
            ).first()
            if row is not None:
                return _run(row)
            if retry:
                row = session.execute(
                    text(
                        "UPDATE brand_reel_runs SET status = 'queued', queued_at = :now, "
                        "started_at = NULL, finished_at = NULL, accounts_done = 0, "
                        "accounts_total = 0, attempts = 0 "
                        "WHERE brand_id = :brand AND trigger = :trigger "
                        "AND run_date = :run_date AND status IN ('check_failed','error') "
                        f"RETURNING {_RUN_COLUMNS}"
                    ),
                    {"brand": brand_id, "trigger": trigger, "run_date": run_date, "now": now},
                ).first()
                if row is not None:
                    return _run(row)
            row = session.execute(
                text(
                    f"SELECT {_RUN_COLUMNS} FROM brand_reel_runs WHERE brand_id = :brand "
                    "AND trigger = :trigger AND run_date = :run_date"
                ),
                {"brand": brand_id, "trigger": trigger, "run_date": run_date},
            ).first()
            if row is None:
                # the UNIQUE row exists but RLS hides it: another tenant's brand
                raise PermissionError("another tenant's brand")
            return _run(row)

    def get_run(self, tenant_id: UUID, run_id: UUID) -> RunRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(f"SELECT {_RUN_COLUMNS} FROM brand_reel_runs WHERE id = :id"),
                {"id": run_id},
            ).first()
            return _run(row) if row is not None else None

    def claim(self, tenant_id: UUID, run_id: UUID, *, now: datetime) -> RunRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(
                    "UPDATE brand_reel_runs SET status = 'running', started_at = :now, "
                    "attempts = attempts + 1 WHERE id = :id AND status = 'queued' "
                    f"RETURNING {_RUN_COLUMNS}"
                ),
                {"id": run_id, "now": now},
            ).first()
            return _run(row) if row is not None else None

    def _fenced(self, tenant_id: UUID, sets: str, params: dict[str, Any]) -> bool:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(f"UPDATE brand_reel_runs SET {sets} WHERE {_FENCE} RETURNING id"), params
            ).first()
            return row is not None

    def progress(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        accounts_total: int,
        accounts_done: int,
        started_at: datetime,
    ) -> bool:
        return self._fenced(
            tenant_id,
            "accounts_total = :total, accounts_done = :done",
            {
                "id": run_id,
                "started_at": started_at,
                "total": accounts_total,
                "done": accounts_done,
            },
        )

    def finish(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        status: str,
        now: datetime,
        credits: int,
        cost_usd: Decimal,
        brief_hash: str | None,
        started_at: datetime,
    ) -> bool:
        return self._fenced(
            tenant_id,
            "status = :status, finished_at = :now, credits = credits + :credits, "
            "cost_usd = cost_usd + :cost, brief_hash = :brief",
            {
                "id": run_id,
                "started_at": started_at,
                "status": status,
                "now": now,
                "credits": credits,
                "cost": cost_usd,
                "brief": brief_hash,
            },
        )

    def release(self, tenant_id: UUID, run_id: UUID, *, started_at: datetime) -> bool:
        return self._fenced(
            tenant_id,
            "status = 'queued', started_at = NULL, accounts_done = 0, accounts_total = 0",
            {"id": run_id, "started_at": started_at},
        )

    def abandon(
        self, tenant_id: UUID, run_id: UUID, *, started_at: datetime, now: datetime
    ) -> bool:
        return self._fenced(
            tenant_id,
            "status = 'error', finished_at = :now",
            {"id": run_id, "started_at": started_at, "now": now},
        )

    def retry_check(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        finished_before: datetime,
        finished_after: datetime,
        max_attempts: int,
    ) -> bool:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(
                    "UPDATE brand_reel_runs r SET status = 'queued', started_at = NULL, "
                    "finished_at = NULL, accounts_done = 0, accounts_total = 0 "
                    "WHERE r.id = :id AND r.status = 'check_failed' AND r.attempts < :max "
                    "AND r.finished_at <= :before AND r.finished_at > :after "
                    f"AND r.id = ({_LATEST_OF_BRAND}) RETURNING r.id"
                ),
                {
                    "id": run_id,
                    "max": max_attempts,
                    "before": finished_before,
                    "after": finished_after,
                },
            ).first()
            return row is not None

    def add_cost(self, tenant_id: UUID, run_id: UUID, cost_usd: Decimal) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                text("UPDATE brand_reel_runs SET cost_usd = cost_usd + :cost WHERE id = :id"),
                {"id": run_id, "cost": cost_usd},
            )

    def latest_run(
        self, tenant_id: UUID, brand_id: UUID, *, status: str | None = None
    ) -> RunRecord | None:
        where = "brand_id = :brand" + (" AND status = :status" if status else "")
        params: dict[str, Any] = {"brand": brand_id}
        if status:
            params["status"] = status
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(
                    f"SELECT {_RUN_COLUMNS} FROM brand_reel_runs WHERE {where} "
                    f"ORDER BY {_LATEST_ORDER} LIMIT 1"
                ),
                params,
            ).first()
            return _run(row) if row is not None else None

    # the screen's opening and the tenant's clock
    def mark_opened(
        self, tenant_id: UUID, brand_id: UUID, *, now: datetime, every: timedelta
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                text(
                    "INSERT INTO brand_reel_activity (tenant_id, brand_id, last_opened_at) "
                    "VALUES (:tenant, :brand, :now) "
                    "ON CONFLICT ON CONSTRAINT uq_brand_reel_activity_brand DO UPDATE "
                    "SET last_opened_at = EXCLUDED.last_opened_at "
                    # only forward, and at most one write per `every`
                    "WHERE brand_reel_activity.last_opened_at "
                    "<= EXCLUDED.last_opened_at - CAST(:every AS interval)"
                ),
                {"tenant": tenant_id, "brand": brand_id, "now": now, "every": every},
            )

    def timezone(self, tenant_id: UUID) -> str:
        with tenant_session(tenant_id) as session:
            zone = session.scalar(
                text("SELECT timezone FROM tenants WHERE id = :tenant"), {"tenant": tenant_id}
            )
        if zone is None:
            raise LookupError(f"no timezone for tenant {tenant_id}")
        return str(zone)

    # accounts and reels
    def account(self, tenant_id: UUID, network: str, handle: str) -> AccountState | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(
                text(
                    "SELECT network, handle, page1_at, full_walk_at, covered_days, "
                    "newest_taken_at, status, last_http_status, credits_total, "
                    "refresh_lock_until FROM reel_accounts "
                    "WHERE network = :network AND handle = :handle"
                ),
                {"network": network, "handle": handle},
            ).first()
            return AccountState(**dict(row._mapping)) if row is not None else None

    def try_lock_account(
        self, tenant_id: UUID, network: str, handle: str, *, now: datetime, until: datetime
    ) -> bool:
        params = {"network": network, "handle": handle, "now": now, "until": until}
        with tenant_session(tenant_id) as session:
            session.execute(
                text(
                    "INSERT INTO reel_accounts (network, handle) VALUES (:network, :handle) "
                    "ON CONFLICT ON CONSTRAINT uq_reel_account DO NOTHING"
                ),
                params,
            )
            # The row lock serializes two runs: the second re-checks the WHERE after the
            # first commits and finds the lock taken.
            taken = session.execute(
                text(
                    "UPDATE reel_accounts SET refresh_lock_until = :until, updated_at = :now "
                    "WHERE network = :network AND handle = :handle AND "
                    "(refresh_lock_until IS NULL OR refresh_lock_until <= :now) RETURNING id"
                ),
                params,
            ).first()
            return taken is not None

    def finish_account(
        self,
        tenant_id: UUID,
        network: str,
        handle: str,
        *,
        now: datetime,
        status: str,
        http_status: int | None = None,
        page1: bool = False,
        full_walk_days: int | None = None,
        newest_taken_at: datetime | None = None,
        credits: int = 0,
        lock_until: datetime | None = None,
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                text(
                    "UPDATE reel_accounts SET "
                    "page1_at = CASE WHEN CAST(:page1 AS boolean) THEN :now ELSE page1_at END, "
                    "full_walk_at = CASE WHEN CAST(:full AS integer) IS NOT NULL "
                    "THEN :now ELSE full_walk_at END, "
                    "covered_days = COALESCE(CAST(:full AS integer), covered_days), "
                    "newest_taken_at = GREATEST(newest_taken_at, "
                    "CAST(:newest AS timestamptz)), "
                    "status = :status, last_http_status = :http, "
                    "credits_total = credits_total + :credits, "
                    # only the caller's own lock is released (never a newer one)
                    "refresh_lock_until = CASE WHEN refresh_lock_until = "
                    "CAST(:lock_until AS timestamptz) THEN NULL ELSE refresh_lock_until END, "
                    "updated_at = :now "
                    "WHERE network = :network AND handle = :handle"
                ),
                {
                    "network": network,
                    "handle": handle,
                    "now": now,
                    "page1": page1,
                    "full": full_walk_days,
                    "newest": newest_taken_at,
                    "status": status,
                    "http": http_status,
                    "credits": credits,
                    "lock_until": lock_until,
                },
            )

    def release_account(
        self, tenant_id: UUID, network: str, handle: str, *, lock_until: datetime
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                text(
                    "UPDATE reel_accounts SET refresh_lock_until = NULL WHERE network = :network "
                    "AND handle = :handle AND refresh_lock_until = :lock_until"
                ),
                {"network": network, "handle": handle, "lock_until": lock_until},
            )

    def upsert_reels(self, tenant_id: UUID, reels: Sequence[PublicReel]) -> None:
        if not reels:
            return
        with tenant_session(tenant_id) as session:
            upsert_reels_in(session, reels)

    def reels_of(
        self, tenant_id: UUID, accounts: Sequence[tuple[str, str]], *, since: datetime
    ) -> list[PublicReel]:
        if not accounts:
            return []
        out: list[PublicReel] = []
        with tenant_session(tenant_id) as session:
            for network in {n for n, _ in accounts}:
                handles = [h for n, h in accounts if n == network]
                rows = session.execute(
                    text(
                        f"SELECT {_REEL_COLUMNS} FROM public_reels WHERE network = :network "
                        "AND handle = ANY(:handles) AND taken_at >= :since"
                    ),
                    {"network": network, "handles": handles, "since": since},
                ).all()
                out.extend(_reel(row) for row in rows)
        return out

    def save_transcript(
        self,
        tenant_id: UUID,
        network: str,
        reel_id: str,
        *,
        text: str,
        source: str,
        now: datetime,
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                _text(
                    "UPDATE public_reels SET transcript = :text, transcript_source = :source, "
                    "transcript_at = :now WHERE network = :network AND reel_id = :reel_id "
                    # never overwritten: a transcript is paid once
                    "AND transcript_at IS NULL"
                ),
                {
                    "text": text,
                    "source": source,
                    "now": now,
                    "network": network,
                    "reel_id": reel_id,
                },
            )

    # verdicts and ideas
    def verdicts(
        self, tenant_id: UUID, brand_id: UUID, *, brief_hash: str, reel_ids: Sequence[str]
    ) -> dict[tuple[str, str, str], StoredVerdict]:
        if not reel_ids:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(
                    f"SELECT {_VERDICT_COLUMNS} FROM brand_reel_verdicts WHERE "
                    "brand_id = :brand AND brief_hash = :brief AND reel_id = ANY(:ids)"
                ),
                {"brand": brand_id, "brief": brief_hash, "ids": list(reel_ids)},
            ).all()
        return {v.key: v for v in (_verdict(row) for row in rows)}

    def save_verdicts(
        self, tenant_id: UUID, brand_id: UUID, verdicts: Sequence[NewVerdict]
    ) -> dict[tuple[str, str, str], StoredVerdict]:
        if not verdicts:
            return {}
        rows = [{**_fields(v), "tenant": tenant_id, "brand": brand_id} for v in verdicts]
        with tenant_session(tenant_id) as session:
            session.execute(
                text(
                    "INSERT INTO brand_reel_verdicts (tenant_id, brand_id, network, reel_id, "
                    "brief_hash, input_hash, fits, model_id, prompt_version, affinity, format, "
                    "hook, reason, effort, cost_usd) VALUES (:tenant, :brand, :network, "
                    ":reel_id, :brief_hash, :input_hash, :fits, :model_id, :prompt_version, "
                    ":affinity, :format, :hook, :reason, :effort, :cost_usd) "
                    "ON CONFLICT ON CONSTRAINT uq_brand_reel_verdict DO NOTHING"
                ),
                rows,
            )
        stored = self.verdicts(
            tenant_id,
            brand_id,
            brief_hash=verdicts[0].brief_hash,
            reel_ids=[v.reel_id for v in verdicts],
        )
        wanted = {v.key for v in verdicts}
        return {key: v for key, v in stored.items() if key in wanted}

    def save_ideas(
        self,
        tenant_id: UUID,
        brand_id: UUID,
        run_id: UUID,
        ideas: Sequence[NewIdea],
        *,
        started_at: datetime,
    ) -> bool:
        with tenant_session(tenant_id) as session:
            # the run row is locked until the ideas commit: a recovery that would take the
            # run back waits for them, and finds the claim changed only afterwards
            mine = session.execute(
                text(f"SELECT id FROM brand_reel_runs WHERE {_FENCE} FOR UPDATE"),
                {"id": run_id, "started_at": started_at},
            ).first()
            if mine is None:
                return False
            session.execute(
                text("DELETE FROM brand_reel_ideas WHERE run_id = :run"), {"run": run_id}
            )
            if not ideas:
                return True
            session.execute(
                text(
                    "INSERT INTO brand_reel_ideas (tenant_id, brand_id, run_id, network, "
                    "reel_id, rank, window_days, verdict_id) VALUES (:tenant, :brand, :run, "
                    ":network, :reel_id, :rank, :window_days, :verdict_id) "
                    "ON CONFLICT ON CONSTRAINT uq_brand_reel_idea DO NOTHING"
                ),
                [
                    {
                        "tenant": tenant_id,
                        "brand": brand_id,
                        "run": run_id,
                        "network": i.network,
                        "reel_id": i.reel_id,
                        "rank": i.rank,
                        "window_days": i.window_days,
                        "verdict_id": i.verdict_id,
                    }
                    for i in ideas
                ],
            )
            return True

    def ideas(self, tenant_id: UUID, brand_id: UUID, run_id: UUID) -> list[Idea]:
        reel_cols = ", ".join(f"r.{c.strip()} AS r_{c.strip()}" for c in _REEL_COLUMNS.split(","))
        verdict_cols = ", ".join(
            f"v.{c.strip()} AS v_{c.strip()}" for c in _VERDICT_COLUMNS.split(",")
        )
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text(
                    f"SELECT i.rank, i.window_days, i.seen_at, {reel_cols}, {verdict_cols}, "
                    # R8: a stored, not yet purged copy of the reel's video, of any version
                    "EXISTS (SELECT 1 FROM public_reel_analyses a WHERE a.network = i.network "
                    "AND a.post_id = i.reel_id AND a.source_key IS NOT NULL "
                    "AND a.source_purged_at IS NULL) AS source_available "
                    "FROM brand_reel_ideas i JOIN public_reels r "
                    "ON r.network = i.network AND r.reel_id = i.reel_id "
                    "LEFT JOIN brand_reel_verdicts v ON v.id = i.verdict_id "
                    "WHERE i.run_id = :run AND i.brand_id = :brand ORDER BY i.rank"
                ),
                {"run": run_id, "brand": brand_id},
            ).all()
        return [
            Idea(
                rank=row.rank,
                window_days=row.window_days,
                seen_at=row.seen_at,
                reel=_reel(row, "r_"),
                verdict=_verdict(row, "v_") if row._mapping["v_id"] is not None else None,
                source_available=bool(row.source_available),
            )
            for row in rows
        ]


__all__ = [
    "ACCOUNT_ERROR",
    "ACCOUNT_MISSING",
    "ACCOUNT_OK",
    "ACCOUNT_PRIVATE",
    "RETRYABLE",
    "STATUS_BUDGET_STOPPED",
    "STATUS_CHECK_FAILED",
    "STATUS_ERROR",
    "STATUS_OK",
    "STATUS_QUEUED",
    "STATUS_RUNNING",
    "TRANSCRIPT_NONE",
    "TRANSCRIPT_TIKTOK",
    "TRANSCRIPT_VENDOR",
    "TRIGGERS",
    "TRIGGER_MANUAL",
    "TRIGGER_OPERATOR_90D",
    "TRIGGER_WEEKLY",
    "AccountState",
    "Idea",
    "MemoryReelRunStore",
    "NewIdea",
    "NewVerdict",
    "PostgresReelRunStore",
    "PublicReel",
    "ReelRunStore",
    "RunRecord",
    "StoredVerdict",
]
