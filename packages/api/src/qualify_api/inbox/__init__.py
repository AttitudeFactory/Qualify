"""Reading comments on the tenant's own connected Instagram media (Fase 1 Parte 4-B).

Comments only — the DM/conversations half is out of reach on the signed login fork (see
`qualify_shared.social.ig_shapes.UNCOVERED_SURFACES["direct_messages"]`).

Sync/polling is scoped to a tenant-chosen watchlist, not every Reel on the account
(product decision, 2026-08-14): `monitored_media` is the persisted toggle,
`InboxService.sync_comments` only ever processes what is marked there.

Still not here: `composition.py` (no real caller yet — same posture B1 shipped with),
`MonitoringLimitPolicy`/billing, HTTP routes. This package grows into the shape of
`qualify_api.publishing` as those land, not before.
"""

from qualify_api.inbox.client import (
    COMMENT_FIELDS,
    CommentsClient,
    CommentsReadError,
    HttpCommentsClient,
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
    MONITORING_WINDOW,
    CandidateMedia,
    InboxService,
    MediaNotEligible,
    SyncSummary,
)

__all__ = [
    "COMMENT_FIELDS",
    "MEDIA_FIELDS",
    "MONITORING_WINDOW",
    "CandidateMedia",
    "CommentsClient",
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
    "SyncSummary",
]
