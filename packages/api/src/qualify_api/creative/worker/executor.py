"""What the worker does with a claimed job — the contract a job kind implements (m-24852163).

The worker owns the queue mechanics (claim, slot, lease, `vendor_task_id` written once,
settle, release); a `JobExecutor` owns what a kind of job means for BytePlus and for the
piece. One executor per vendor pool (`byteplus:seedance-2-5`, …), registered in the
worker's composition. The generator's executors arrive with m-24852166 (the generator
enqueues instead of starting threads); until then production registers none and the
queue loop only runs the recoveries.

Every method gets a `JobContext` built from the job row read under
`tenant_session(job.tenant_id)` and opens its OWN short `tenant_session(ctx.tenant_id)`
when it touches the piece (security review §3.3: never a session shared between jobs nor
kept by the worker). The BytePlus key is the platform's (env), never a business
credential.

- `submit` sends the paid task and returns its id. BytePlus busy (429) → raise
  `qualify_creative.adapters.byteplus_ark.VendorBusy`: nothing was created, the worker
  puts the job back for later and it does not count as a failure.
- `poll` asks BytePlus by id; it never submits.
- `finish` is idempotent: it stores the result (`succeeded`: download, R2, cost once) or
  fails the piece and gives its creations back (`failed`/`cancelled`/`expired`/`unknown`).
  It may be called again for the same task after a crash.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

#: BytePlus's terminal task states as the adapters read them, plus «no such task».
SUCCEEDED = "succeeded"
FAILED_STATES = frozenset({"failed", "cancelled", "expired", "unknown"})
TERMINAL_STATES = FAILED_STATES | {SUCCEEDED}


@dataclass(frozen=True)
class JobContext:
    job_id: UUID
    tenant_id: UUID
    draft_id: UUID
    kind: str
    revision: int
    position: int
    vendor_model: str
    lane: str  # the worker lane (`lanes.NOW` …), aged
    vendor_priority: int  # BytePlus `priority` 0–9 for this lane
    deadline: datetime | None
    claim_token: int = 0


@dataclass(frozen=True)
class TaskPoll:
    status: str  # queued | running | succeeded | failed | cancelled | expired | unknown
    next_poll_seconds: float = 5.0

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATES


class JobExecutor(Protocol):
    def submit(self, job: JobContext) -> str:
        """Send the paid task; return BytePlus's task id. Raise `VendorBusy` on 429."""
        ...

    def poll(self, job: JobContext, vendor_task_id: str) -> TaskPoll: ...

    def finish(self, job: JobContext, vendor_task_id: str | None, status: str) -> None:
        """Store the result or fail the piece. `vendor_task_id` is None when the job never
        reached BytePlus (the submit itself failed)."""
        ...
