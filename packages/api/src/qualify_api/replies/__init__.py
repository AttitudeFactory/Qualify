"""Assisted reply drafts over positive-sentiment public comments on own content
(QUA-22, comments tranche only). The DM tranche is deliberately absent from this
module — not deferred inside it, absent — it stays blocked by Advanced Access +
Business Verification, tracked in QUA-20/QUA-69, until the "Verificación Meta
Business — Qualify" project (QUA-5…QUA-12) closes the administrative clock.

Since m-24789645 (Fase B) a comment with commercial intent (Fase A) is a candidate too: the
gate routes it to a grounded generator (`public_drafts`: catalog only, never a price) and
its draft records grounding, review verdict, cost and the intent result.

Pipeline: `gate.evaluate_gate` (cheap, pure, pre-generator) → `ReplyDraftProvider`
(`qualify_models.providers`, lazy-imported — the `ml` group) → `comment_reply_drafts`
(migration 0014, write-ahead) → human decision (`accepted`/`edited`/`discarded`) →
`send` (write-ahead again, then the real Meta call via `replies/client.py`).

**No send without a `HumanApproval`** (m-24789645): `send_draft(..., approval=...)` and
`ReplyService.send` require one naming the draft, or raise `ApprovalRequired`.

`generate_drafts`/`list_pending_drafts`/`decide_draft`/`send_draft` are the published
seams for HTTP/Reflex — plain functions over ids, no HTTP hop internally, same role
`sentiment.analyze_pending_comments`/`inbox.sync_comments` have for their own modules.
"""

from qualify_api.assisted.approval import ApprovalRequired, HumanApproval
from qualify_api.replies.composition import (
    current_reply_generator_version,
    decide_draft,
    generate_drafts,
    list_pending_drafts,
    list_retryable_drafts,
    prepare_retry,
    production_reply_service,
    public_reply_generator,
    regenerate_draft,
    send_draft,
)
from qualify_api.replies.gate import GateInput, GateVerdict, IntentEvidence, evaluate_gate
from qualify_api.replies.repository import (
    CandidateComment,
    DraftProvenance,
    DraftRecord,
    MemoryReplyRepository,
    PostgresReplyRepository,
    ReplyRepository,
)
from qualify_api.replies.service import (
    DecisionResult,
    GenerationSummary,
    RegenerationRefused,
    ReplyService,
    RetryRefused,
    UnknownDraft,
    require_approval,
)

__all__ = [
    "ApprovalRequired",
    "CandidateComment",
    "DecisionResult",
    "DraftProvenance",
    "DraftRecord",
    "GateInput",
    "GateVerdict",
    "GenerationSummary",
    "HumanApproval",
    "IntentEvidence",
    "MemoryReplyRepository",
    "PostgresReplyRepository",
    "ReplyRepository",
    "RegenerationRefused",
    "ReplyService",
    "RetryRefused",
    "UnknownDraft",
    "current_reply_generator_version",
    "decide_draft",
    "evaluate_gate",
    "generate_drafts",
    "list_pending_drafts",
    "list_retryable_drafts",
    "prepare_retry",
    "production_reply_service",
    "public_reply_generator",
    "regenerate_draft",
    "require_approval",
    "send_draft",
]
