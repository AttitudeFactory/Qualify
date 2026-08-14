"""Reading comments on the tenant's own connected Instagram media (B1, Fase 1 Parte 4-B).

Comments only — the DM/conversations half is out of reach on the signed login fork (see
`qualify_shared.social.ig_shapes.UNCOVERED_SURFACES["direct_messages"]`).

Only the read client exists so far. No repository, no service, no sync/poll, no HTTP
route — this package grows into the shape of `qualify_api.publishing` as those stories
land, not before.
"""

from qualify_api.inbox.client import (
    COMMENT_FIELDS,
    CommentsClient,
    CommentsReadError,
    HttpCommentsClient,
)

__all__ = [
    "COMMENT_FIELDS",
    "CommentsClient",
    "CommentsReadError",
    "HttpCommentsClient",
]
