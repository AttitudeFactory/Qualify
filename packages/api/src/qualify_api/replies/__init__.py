"""Assisted reply drafts over positive-sentiment public comments on own content
(QUA-22, comments tranche only). The DM tranche is deliberately absent from this
module — not deferred inside it, absent — it stays blocked by Advanced Access +
Business Verification, tracked in QUA-20/QUA-69, until the "Verificación Meta
Business — Qualify" project (QUA-5…QUA-12) closes the administrative clock.

Pipeline: `gate.evaluate_gate` (cheap, pure, pre-generator) → `ReplyDraftProvider`
(`qualify_models.providers`, lazy-imported — the `ml` group) → `comment_reply_drafts`
(migration 0014, write-ahead) → human decision (`accepted`/`edited`/`discarded`) →
`send` (write-ahead again, then the real Meta call via `replies/client.py`).

`generate_drafts`/`list_pending_drafts`/`decide_draft`/`send_draft` are the published
seams for HTTP/Reflex — plain functions over ids, no HTTP hop internally, same role
`sentiment.analyze_pending_comments`/`inbox.sync_comments` have for their own modules.
"""

from qualify_api.replies.composition import (
    current_reply_generator_version,
    decide_draft,
    generate_drafts,
    list_pending_drafts,
    production_reply_service,
    send_draft,
)
from qualify_api.replies.gate import GateInput, GateVerdict, evaluate_gate
from qualify_api.replies.repository import (
    CandidateComment,
    DraftRecord,
    MemoryReplyRepository,
    PostgresReplyRepository,
    ReplyRepository,
)
from qualify_api.replies.service import (
    DecisionResult,
    GenerationSummary,
    ReplyService,
    UnknownDraft,
)

__all__ = [
    "CandidateComment",
    "DecisionResult",
    "DraftRecord",
    "GateInput",
    "GateVerdict",
    "GenerationSummary",
    "MemoryReplyRepository",
    "PostgresReplyRepository",
    "ReplyRepository",
    "ReplyService",
    "UnknownDraft",
    "current_reply_generator_version",
    "decide_draft",
    "evaluate_gate",
    "generate_drafts",
    "list_pending_drafts",
    "production_reply_service",
    "send_draft",
]
