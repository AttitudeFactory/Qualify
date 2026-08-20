"""Reading comments on the tenant's own connected Instagram media (Fase 1 Parte 4-B).

Comments only — the DM/conversations half is out of reach on the signed login fork (see
`qualify_shared.social.ig_shapes.UNCOVERED_SURFACES["direct_messages"]`).

Sync/polling is scoped to a tenant-chosen watchlist, not every Reel on the account
(product decision, 2026-08-14): `monitored_media` is the persisted toggle,
`InboxService.sync_comments` only ever processes what is marked there.

`composition.py` (2026-08-14, B2 UI slice) wires the real credential-resolved clients
together and is the published seam for the Reflex CRM — `list_candidate_media`/
`set_media_monitored`/`sync_comments` below, plain async functions over ids, no HTTP
hop, same role `publishing.composition.stage_and_start_publish`/`advance_publish` have
for publishing.

`sync_comments` (2026-08-15) now has a real caller: `qualify_api.http.inbox_routes`'s
`POST /api/inbox/sync` (the B2 acceptance-criterion route). A temporary Reflex
manual-trigger button (`Qualify/inbox_state.py`) reaches this SAME function through that
SAME route too, via an in-process ASGI transport rather than a second, parallel
in-process call — see `Qualify/inbox_provider.py`'s docstring for why and for the one
dev-only limitation that comes with it (a single authenticated tenant). No scheduler
exists yet; that remains the next slice, along with the thread/comments view and
`MonitoringLimitPolicy`/billing.

`sync_comments` (2026-08-18, QUA-88) is now gated by two pre-flight checks, both raised
BEFORE any Meta call: `CommentsPermissionMissing` (the connection lacks a scope the
comments edge requires at all — `cannot_observe`, never confused with a genuinely empty
result) and `SyncBudgetExhausted` (not enough of the real 200-calls/hour Meta budget
remains for the calls this sync would need, tracked by a Postgres ledger —
`InboxRepository.calls_in_last_hour`/`record_call`, backed by migration `0010`). A budget
that runs out mid-pagination instead stops and returns `SyncSummary(truncated=True)`.
"""

from qualify_api.inbox.client import (
    COMMENT_FIELDS,
    CommentsClient,
    CommentsReadError,
    HttpCommentsClient,
)
from qualify_api.inbox.composition import (
    UnknownInboxConnection,
    list_candidate_media,
    set_media_monitored,
    sync_comments,
)
from qualify_api.inbox.media_client import (
    MEDIA_FIELDS,
    HttpMediaClient,
    MediaClient,
    MediaReadError,
    MediaSummary,
)
from qualify_api.inbox.repository import (
    InboxRepository,
    MemoryInboxRepository,
    PostgresInboxRepository,
)
from qualify_api.inbox.service import (
    META_CALL_BUDGET_PER_HOUR,
    MONITORING_WINDOW,
    CandidateMedia,
    CommentsAuthExpired,
    CommentsPermissionMissing,
    InboxService,
    MediaNotEligible,
    SyncBudgetExhausted,
    SyncSummary,
)

__all__ = [
    "COMMENT_FIELDS",
    "MEDIA_FIELDS",
    "META_CALL_BUDGET_PER_HOUR",
    "MONITORING_WINDOW",
    "CandidateMedia",
    "CommentsAuthExpired",
    "CommentsClient",
    "CommentsPermissionMissing",
    "CommentsReadError",
    "HttpCommentsClient",
    "HttpMediaClient",
    "InboxRepository",
    "InboxService",
    "MediaClient",
    "MediaNotEligible",
    "MediaReadError",
    "MediaSummary",
    "MemoryInboxRepository",
    "PostgresInboxRepository",
    "SyncBudgetExhausted",
    "SyncSummary",
    "UnknownInboxConnection",
    "list_candidate_media",
    "set_media_monitored",
    "sync_comments",
]
