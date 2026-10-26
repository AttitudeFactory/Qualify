"""Recover billed BytePlus videos without waiting for a screen (m-24852492).

PR #325 (m-24852154) keeps every Seedance task by id and resumes a draft whose wait ran
out — but only when a screen READS drafts (`ContentService._sweep`). If nobody opens
Qualify for 24 h after BytePlus finishes, the task's `video_url` expires, the resumed run
fails and refunds the owner, and BytePlus has already billed the video.

This module is the same recovery as a pass that runs on its own, every minute, from a
worker — `creative-worker` (ADR 41, m-24852163: `creative.worker.runner`, its recovery
sidecar). The calendar worker (`planner.worker`, `planner.embedded`) ran it first and
still does unless `QUALIFY_CALENDAR_VENDOR_RECOVERY=off` (`runs_in_calendar_worker`);
production compose sets it off, so one service owns the pass (two at once stay safe, see
below):

1. **Discovery** — which tenants have a `drafting` draft silent for the quiet window
   (ids only; `discover_tenants`, `qualify_admin` already reads `content_drafts`).
   Scoped runs (`--tenant`) never read across tenants.
2. Per tenant, in its own `tenant_session`: the reaper (`reap_stale_drafts`: a task past
   BytePlus's 48 h expiry is given up, the piece fails and is refunded), then the drafts
   whose thread went quiet with a task still pending (`waiting`).
3. **Ask BytePlus by id** (`get_task`) for each pending task — ModelArk for a Seedance
   task, OmniHuman for a presenter's render (m-24852495, `StatusByProvider`; OmniHuman's
   `in_queue`/`generating`/`done` read `queued`/`running`/`succeeded`, and its result URL
   lives one hour, well over the pass's ~4 min). Still `queued`/`running` →
   nothing to do this pass (the resumed run would only sit polling). Every task ended —
   `succeeded`, `failed`/`cancelled`/`expired`, or unknown to BytePlus →
4. **Claim** the draft atomically (`claim_waiting_drafts(draft_ids=…)`, the same
   `UPDATE … RETURNING` stamp a screen read uses — so a screen read and the worker never
   both resume it) and **resume** it: `ContentService.run_generation`, which waits for
   the (already ended) tasks, rebuilds the piece from the kept copy, stores the video in
   R2 and records its cost once — or fails the piece and gives its creations back.

The run is synchronous inside the worker's recovery thread (never on the tick: see
`planner.worker.run_worker`'s `sidecar`), so passes never overlap within a process; two
processes are safe because of the claim and `run_generation`'s own idempotency.

Timing: the worker passes every `RECOVERY_EVERY_SECONDS` (60) and a draft becomes a
candidate `RECOVER_AFTER_QUIET_MINUTES` (3) after its thread's last sign of life, so a
video BytePlus delivers is in the piece within ~4 min (well under the 24 h URL life and
the 10 min target of the ticket).

Kill switch: `QUALIFY_VENDOR_RECOVERY=off` (read on every pass).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative.dispatch import (
    RECOVER_AFTER_QUIET_MINUTES,
    claim_waiting_drafts,
    reap_stale_drafts,
)
from qualify_api.creative.fsm import DRAFTING
from qualify_api.creative.models import ContentDraft, CreativeVendorTask
from qualify_api.creative.vendor_tasks import GIVE_UP_AFTER, PENDING

logger = logging.getLogger("qualify_api.creative.vendor_recovery")

ENV_SWITCH = "QUALIFY_VENDOR_RECOVERY"
#: How often the worker runs a pass (seconds).
RECOVERY_EVERY_SECONDS = 60
QUIET = timedelta(minutes=RECOVER_AFTER_QUIET_MINUTES)

#: BytePlus's task states (`get_task`), as the adapter reads them.
STILL_RUNNING = frozenset({"queued", "running"})
ENDED = frozenset({"succeeded", "failed", "cancelled", "expired"})
#: `get_task` answered «no such task» (404 / NotFound): BytePlus will never deliver it.
UNKNOWN = "unknown"


_OFF = frozenset({"off", "0", "false", "no"})
#: m-24852163: the calendar worker leaves the pass to `creative-worker` when this is off.
CALENDAR_SWITCH = "QUALIFY_CALENDAR_VENDOR_RECOVERY"


def enabled(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return env.get(ENV_SWITCH, "").strip().lower() not in _OFF


def runs_in_calendar_worker(env: Mapping[str, str] | None = None) -> bool:
    """Whether the calendar worker (CLI or embedded) still runs the pass. On by default
    so a local stack without `creative-worker` keeps recovering; off in production."""
    env = os.environ if env is None else env
    return env.get(CALENDAR_SWITCH, "").strip().lower() not in _OFF


# -- what the pass works with ---------------------------------------------------------------


@dataclass(frozen=True)
class PendingTask:
    slot: str
    vendor_task_id: str
    provider: str


@dataclass(frozen=True)
class WaitingDraft:
    """A `drafting` draft whose thread went quiet with vendor tasks still pending."""

    tenant_id: UUID
    draft_id: UUID
    brand_id: UUID
    tasks: tuple[PendingTask, ...]


class RecoveryStore(Protocol):
    """Every method but discovery runs inside the given tenant's session."""

    def reap(self, *, tenant_id: UUID) -> int: ...

    def waiting(self, *, tenant_id: UUID, now: datetime) -> list[WaitingDraft]: ...

    def claim(self, *, tenant_id: UUID, draft_id: UUID) -> bool:
        """Stamp the draft if it is still quiet and waiting; True = this caller won it."""
        ...


class TaskStatusReader(Protocol):
    def status(self, task: PendingTask, *, tenant_id: UUID, brand_id: UUID) -> str:
        """BytePlus's state of the task (`queued`, `running`, `succeeded`, `failed`,
        `cancelled`, `expired`) or `UNKNOWN`. Raises when it could not be asked."""
        ...


#: (tenant_id, draft_id) → the resumed run (`ContentService.run_generation`).
Resume = Callable[[UUID, UUID], None]


@dataclass
class RecoveryReport:
    started_at: datetime
    tenants: int = 0
    reaped: int = 0
    resumed: list[UUID] = field(default_factory=list)
    still_running: list[UUID] = field(default_factory=list)
    lost_claim: list[UUID] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# -- the pass -------------------------------------------------------------------------------


def recover_once(
    *,
    tenants: Callable[[datetime], Iterable[UUID]],
    store: RecoveryStore,
    statuses: TaskStatusReader,
    resume: Resume,
    now: datetime | None = None,
) -> RecoveryReport:
    """One recovery pass over the tenants in scope. Never raises: a tenant, a status
    call or a resumed run that fails is logged and the pass goes on."""
    now = now or datetime.now(UTC)
    report = RecoveryReport(started_at=now)
    try:
        tenant_ids = list(dict.fromkeys(tenants(now)))
    except Exception as exc:
        logger.exception("creative.recovery.discovery_failed")
        report.errors.append(f"discovery: {type(exc).__name__}")
        return report
    for tenant_id in tenant_ids:
        report.tenants += 1
        try:
            _recover_tenant(tenant_id, store, statuses, resume, now, report)
        except Exception as exc:
            logger.exception("creative.recovery.tenant_failed tenant_id=%s", tenant_id)
            report.errors.append(f"{tenant_id}: {type(exc).__name__}")
    if report.resumed or report.errors or report.reaped:
        logger.info(
            "creative.recovery.pass tenants=%s reaped=%s resumed=%s still_running=%s "
            "lost_claim=%s errors=%s",
            report.tenants,
            report.reaped,
            len(report.resumed),
            len(report.still_running),
            len(report.lost_claim),
            len(report.errors),
        )
    return report


def _recover_tenant(
    tenant_id: UUID,
    store: RecoveryStore,
    statuses: TaskStatusReader,
    resume: Resume,
    now: datetime,
    report: RecoveryReport,
) -> None:
    report.reaped += store.reap(tenant_id=tenant_id)
    for draft in store.waiting(tenant_id=tenant_id, now=now):
        try:
            states = [
                statuses.status(task, tenant_id=tenant_id, brand_id=draft.brand_id)
                for task in draft.tasks
            ]
        except Exception as exc:
            logger.warning(
                "creative.recovery.status_unreadable draft_id=%s", draft.draft_id, exc_info=True
            )
            report.errors.append(f"{draft.draft_id}: status {type(exc).__name__}")
            continue
        if any(state not in ENDED and state != UNKNOWN for state in states):
            # still in BytePlus's queue (or an answer we do not know): the next pass asks
            report.still_running.append(draft.draft_id)
            continue
        if not store.claim(tenant_id=tenant_id, draft_id=draft.draft_id):
            # a screen read (or another worker) resumed it first
            report.lost_claim.append(draft.draft_id)
            continue
        logger.info(
            "creative.recovery.resume tenant_id=%s draft_id=%s states=%s",
            tenant_id,
            draft.draft_id,
            ",".join(states),
        )
        try:
            resume(tenant_id, draft.draft_id)
        except Exception as exc:
            logger.exception("creative.recovery.resume_failed draft_id=%s", draft.draft_id)
            report.errors.append(f"{draft.draft_id}: resume {type(exc).__name__}")
            continue
        report.resumed.append(draft.draft_id)


# -- production implementations -----------------------------------------------------------


class PostgresRecoveryStore:
    """The real reaper and claim (`creative.dispatch`), and the waiting drafts read in
    the tenant's own session."""

    def reap(self, *, tenant_id: UUID) -> int:
        return reap_stale_drafts(tenant_id=tenant_id)

    def waiting(self, *, tenant_id: UUID, now: datetime) -> list[WaitingDraft]:
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(
                    ContentDraft.id,
                    ContentDraft.brand_id,
                    CreativeVendorTask.slot,
                    CreativeVendorTask.vendor_task_id,
                    CreativeVendorTask.provider,
                )
                .join(
                    CreativeVendorTask,
                    (CreativeVendorTask.draft_id == ContentDraft.id)
                    & (CreativeVendorTask.revision == ContentDraft.revision),
                )
                .where(
                    ContentDraft.status == DRAFTING,
                    ContentDraft.updated_at < now - QUIET,
                    CreativeVendorTask.status == PENDING,
                    CreativeVendorTask.created_at >= now - GIVE_UP_AFTER,
                )
                .order_by(ContentDraft.updated_at, CreativeVendorTask.created_at)
            ).all()
        drafts: dict[UUID, tuple[UUID, list[PendingTask]]] = {}
        for draft_id, brand_id, slot, task_id, provider in rows:
            drafts.setdefault(draft_id, (brand_id, []))[1].append(
                PendingTask(slot=slot, vendor_task_id=task_id, provider=provider)
            )
        return [
            WaitingDraft(tenant_id, draft_id, brand_id, tuple(tasks))
            for draft_id, (brand_id, tasks) in drafts.items()
        ]

    def claim(self, *, tenant_id: UUID, draft_id: UUID) -> bool:
        return draft_id in claim_waiting_drafts(
            tenant_id=tenant_id,
            quiet_minutes=RECOVER_AFTER_QUIET_MINUTES,
            draft_ids=[draft_id],
        )


def discover_tenants(now: datetime) -> list[UUID]:
    """PRODUCTION discovery (`--all-tenants`): ids of tenants with a `drafting` draft
    silent for the quiet window — the only drafts the pass can act on (waiting on a
    task, or stale for the reaper). Same narrow terms as
    `planner.discovery.DiscoveredTenants`: read-only, ids only, `qualify_admin` already
    holds SELECT on `content_drafts` (0009); everything after it is `tenant_session`."""
    from qualify_shared.db.admin import admin_session  # noqa: PLC0415 — production only

    with admin_session() as session:
        rows: Sequence[UUID] = session.scalars(
            select(ContentDraft.tenant_id)
            .where(ContentDraft.status == DRAFTING, ContentDraft.updated_at < now - QUIET)
            .distinct()
        ).all()
    return sorted(set(rows), key=str)


def scoped_tenants(tenant_ids: Iterable[UUID]) -> Callable[[datetime], list[UUID]]:
    ids = list(dict.fromkeys(tenant_ids))
    if not ids:
        raise ValueError("a scoped recovery needs at least one tenant id")
    return lambda _now: list(ids)


class SeedanceTaskStatus:
    """`TaskStatusReader` over `SeedanceVideoAdapter.get_task` with the platform key —
    a read: nothing is created or billed."""

    def __init__(self, adapter: Any, credentials: Any) -> None:
        self._adapter = adapter
        self._credentials = credentials

    def status(self, task: PendingTask, *, tenant_id: UUID, brand_id: UUID) -> str:
        from qualify_creative.adapters.byteplus_ark import ArkAPIError  # noqa: PLC0415

        key = self._credentials.resolve(
            tenant_id=tenant_id, brand_id=brand_id, provider=task.provider or "seedance"
        )
        try:
            body = self._adapter.get_task(task.vendor_task_id, api_key=key.api_key)
        except ArkAPIError as exc:
            if exc.status_code == 404 or "notfound" in str(exc.code or "").lower():
                return UNKNOWN
            raise
        return str(body.get("status") or "").lower()


#: OmniHuman's states (`get_result` → `data.status`) in the pass's words (m-24852495).
OMNIHUMAN_STATES = {
    "in_queue": "queued",
    "generating": "running",
    "done": "succeeded",
    "expired": "expired",
    "canceled": "cancelled",
    "cancelled": "cancelled",
    "failed": "failed",
}


class OmniHumanTaskStatus:
    """`TaskStatusReader` over `OmniHumanVideoAdapter.get_task` with the platform key
    (m-24852495) — a read: nothing is submitted or billed. `not_found` reads `UNKNOWN`;
    an error code on the task's own result (a refused render) reads `failed`; an answer
    that says nothing about the task (no answer, a 5xx, a refused key) raises, so the
    draft is left for the next pass."""

    def __init__(self, adapter: Any, credentials: Any) -> None:
        self._adapter = adapter
        self._credentials = credentials

    def status(self, task: PendingTask, *, tenant_id: UUID, brand_id: UUID) -> str:
        from qualify_creative.adapters.byteplus_omnihuman import (  # noqa: PLC0415
            ACCESS_ERROR_CODES,
            OmniHumanError,
        )

        key = self._credentials.resolve(
            tenant_id=tenant_id, brand_id=brand_id, provider=task.provider or "omnihuman"
        )
        try:
            data = self._adapter.get_task(task.vendor_task_id, api_key=key.api_key)
        except OmniHumanError as exc:
            if isinstance(exc.code, int) and exc.code not in ACCESS_ERROR_CODES:
                return "failed"
            raise
        status = str(data.get("status") or "").lower()
        if status == "not_found":
            return UNKNOWN
        return OMNIHUMAN_STATES.get(status, status)


class StatusByProvider:
    """`TaskStatusReader` that asks each task's own vendor: OmniHuman for an `omnihuman`
    row (m-24852495), Seedance for everything else (the rows before it name
    `seedance`)."""

    def __init__(self, seedance: TaskStatusReader, omnihuman: TaskStatusReader) -> None:
        self._seedance = seedance
        self._omnihuman = omnihuman

    def status(self, task: PendingTask, *, tenant_id: UUID, brand_id: UUID) -> str:
        reader = self._omnihuman if task.provider == "omnihuman" else self._seedance
        return reader.status(task, tenant_id=tenant_id, brand_id=brand_id)


def recovery_chore(tenant_ids: Iterable[UUID] | None) -> Callable[[], RecoveryReport | None]:
    """The worker's recovery pass over its own scope (`None` = production discovery).
    Its parts are built on the FIRST pass (after `.env`), once — the content service
    only on the first resume; `QUALIFY_VENDOR_RECOVERY=off` skips the pass (read every
    time)."""
    scope = scoped_tenants(tenant_ids) if tenant_ids is not None else discover_tenants
    built: dict[str, Any] = {}

    def run() -> RecoveryReport | None:
        if not enabled():
            return None
        if not built:
            built.update(_production_parts())
        return recover_once(
            tenants=scope,
            store=built["store"],
            statuses=built["statuses"],
            resume=built["resume"],
        )

    return run


def _production_parts() -> dict[str, Any]:
    """The store and the status reader are light; the content service (copy, media,
    Remotion, PyAV…) is built only when a draft is actually resumed — the calendar
    worker's container is small (320 MiB) and most passes resume nothing."""
    from qualify_creative.adapters.byteplus_ark import SeedanceVideoAdapter  # noqa: PLC0415
    from qualify_creative.adapters.byteplus_omnihuman import (  # noqa: PLC0415
        DEFAULT_REQ_KEY as DEFAULT_OMNIHUMAN_REQ_KEY,
    )
    from qualify_creative.adapters.byteplus_omnihuman import (  # noqa: PLC0415
        REQ_KEY_ENV as OMNIHUMAN_REQ_KEY_ENV,
    )
    from qualify_creative.adapters.byteplus_omnihuman import (  # noqa: PLC0415
        OmniHumanVideoAdapter,
    )

    from qualify_api.creative.composition import (  # noqa: PLC0415 — after .env
        ARK_BASE_URL,
        ARK_BASE_URL_ENV,
        PlatformKeyResolver,
    )

    adapter = SeedanceVideoAdapter(base_url=os.environ.get(ARK_BASE_URL_ENV) or ARK_BASE_URL)
    # the same version the generation submits with (`production_content_service`)
    omnihuman = OmniHumanVideoAdapter(
        req_key=os.environ.get(OMNIHUMAN_REQ_KEY_ENV) or DEFAULT_OMNIHUMAN_REQ_KEY
    )
    credentials = PlatformKeyResolver()
    services: list[Any] = []

    def resume(tenant_id: UUID, draft_id: UUID) -> None:
        if not services:
            from qualify_api.creative.composition import (  # noqa: PLC0415 — heavy, lazy
                production_content_service,
            )

            services.append(production_content_service())
        services[0].run_generation(tenant_id=tenant_id, draft_id=draft_id)

    return {
        "store": PostgresRecoveryStore(),
        "statuses": StatusByProvider(
            SeedanceTaskStatus(adapter, credentials),
            OmniHumanTaskStatus(omnihuman, credentials),
        ),
        "resume": resume,
    }
