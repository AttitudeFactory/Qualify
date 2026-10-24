"""Conversaciones — the multichannel private-messaging inbox (QUA-226, Fase 1 Parte 4-B,
ADR 21c: assisted replies only, never autonomous).

E1 (2026-10-16) is the FOUNDATION: contracts, persistence, the queue and their tests.
E2 (the Reflex screen, `Qualify/conversations_*.py`), E3 (`instagram_source` +
`webhook`: the Instagram Direct channel, read from the corpus and NOT yet verified
against Meta — `docs/conversaciones-limitaciones-meta.md`) and E5 (`sender` + `worker`:
the outbox loop) followed the same day; E4 (`suggest`: Claude-drafted replies grounded
on the catalog, decided by a person) closed the ticket's scope the same evening.

- `contracts` — `ConversationSource` / `ConversationSender`, the channel seam; a channel
  is one implementation of each, registered in a `ChannelRegistry`. Thread identity is
  the COUNTERPART's external id (IGSID), so the webhook and poll paths converge.
- `repository` — `threads`/`messages` (0004 + 0065) and `conversation_sync_state`
  (0065): dedup by `(connection_id, external_message_id)` at INSERT time, access + sync
  state per connection, `tenant_session` per call.
- `outbox` — `conversation_outbox` (0065) and `HumanApproval`, the only way in. The
  approving person is a NOT NULL column; the webhook worker holds no grant on the table.
- `sync` — the reconciliation poll and the single-message door, channel-agnostic.
- `service` — list / read / mark read / reply (window-checked, then queued), the seam the
  UI will consume. `attention_state` derives «pendiente / leído / respondido».
- `drafts` — the assisted-draft contract (statuses of 0014, pure transition) and its
  store, `conversation_drafts` (0065), under RLS.
- `suggest` — E4: the gate (inbound text + open window), the Claude generator (strict
  tool use, `claude-haiku-5-5`), the grounding (brand name + catalog) recorded on each
  draft with its cost, and `ConversationDraftService` (suggest / decide — never send).
- `memory_source` — the second channel: an in-memory source + sender pair, the proof the
  seam holds and the fixture of the offline tests. `composition` can serve `dm` with it
  (`QUALIFY_CONVERSATIONS_DM_CHANNEL=memory`) so the loop runs on localhost without Meta;
  `devseed` fills it.
- `window` — the 24 h window, re-exported from `whatsapp.window` (one decision, shared).
- `instagram_source` / `webhook` — Instagram Direct: the Messenger Platform adapter and
  the `instagram:messages` intake handler (E3).
- `sender` / `worker` — the outbox loop (window re-checked at send time) and its CLI (E5).
- `templates` — m-24789472: the per-account library of text templates the composer
  starts a reply from (0079), with `{nombre}`/`{marca}` rendering. Never sends: the text
  leaves only through `reply_text` and the approved outbox.
- `choices` / `ice_breakers` / `ice_breakers_client` — m-24789472: what a person tapped
  (0082), and each account's «preguntas iniciales» (0083): edited here, published to
  Instagram's Messenger Profile by a person, behind the `ice_breakers` capability.
- `composition` — production wiring; the one place the channel implementation is chosen.

Blocked outside the code (see the ticket): `instagram_manage_messages` is not requested
today and its access level is unconfirmed; Page webhook subscription is QUA-129; the
owner's "Allow Access to Messages" toggle is a human action with no documented API
signal — hence `AccessStatus.UNKNOWN` is a stored state, not a default.
"""

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    AccessStatus,
    AccessVerdict,
    ChannelRegistry,
    ConversationSender,
    ConversationSource,
    Page,
    RemoteConversation,
    RemoteMessage,
    SendResult,
    SourceConnection,
    UnknownChannel,
)
from qualify_api.conversations.drafts import (
    ConversationDraft,
    DraftPending,
    DraftRepository,
    DraftStatus,
    InvalidDraftTransition,
    MemoryDraftRepository,
    PostgresDraftRepository,
    UnknownDraft,
    decide_draft,
    new_draft,
)
from qualify_api.conversations.outbox import (
    ApprovalRequired,
    ClaimedOutboxItem,
    ConversationOutboxRepository,
    HumanApproval,
    MemoryConversationOutboxRepository,
    OutboxRecord,
    PostgresConversationOutboxRepository,
)
from qualify_api.conversations.repository import (
    ConversationRepository,
    MemoryConversationRepository,
    MessageRecord,
    PostgresConversationRepository,
    SyncStateRecord,
    ThreadRecord,
    ThreadUpsert,
)
from qualify_api.conversations.sender import ConversationOutboxSender, SendReport
from qualify_api.conversations.service import (
    AttentionState,
    ConversationService,
    ThreadNotFound,
    ThreadView,
    WindowClosed,
    attention_state,
)
from qualify_api.conversations.sync import ConversationSyncService, IngestResult, SyncReport
from qualify_api.conversations.templates import (
    DEFAULT_TEMPLATES,
    MemoryReplyTemplateRepository,
    PostgresReplyTemplateRepository,
    RenderedTemplate,
    ReplyTemplate,
    ReplyTemplateError,
    ReplyTemplateNotFound,
    ReplyTemplateRepository,
    ReplyTemplateService,
    render_template,
)

__all__ = [
    "DEFAULT_TEMPLATES",
    "MemoryReplyTemplateRepository",
    "PostgresReplyTemplateRepository",
    "RenderedTemplate",
    "ReplyTemplate",
    "ReplyTemplateError",
    "ReplyTemplateNotFound",
    "ReplyTemplateRepository",
    "ReplyTemplateService",
    "render_template",
    "ConversationOutboxSender",
    "SendReport",
    "CHANNEL_DM",
    "AccessStatus",
    "AccessVerdict",
    "ApprovalRequired",
    "AttentionState",
    "ChannelRegistry",
    "ClaimedOutboxItem",
    "ConversationDraft",
    "ConversationOutboxRepository",
    "ConversationRepository",
    "ConversationSender",
    "ConversationService",
    "ConversationSource",
    "ConversationSyncService",
    "DraftPending",
    "DraftRepository",
    "DraftStatus",
    "HumanApproval",
    "IngestResult",
    "InvalidDraftTransition",
    "UnknownDraft",
    "MemoryConversationOutboxRepository",
    "MemoryConversationRepository",
    "MemoryDraftRepository",
    "PostgresDraftRepository",
    "MessageRecord",
    "OutboxRecord",
    "Page",
    "PostgresConversationOutboxRepository",
    "PostgresConversationRepository",
    "RemoteConversation",
    "RemoteMessage",
    "SendResult",
    "SourceConnection",
    "SyncReport",
    "SyncStateRecord",
    "ThreadNotFound",
    "ThreadRecord",
    "ThreadUpsert",
    "ThreadView",
    "UnknownChannel",
    "WindowClosed",
    "attention_state",
    "decide_draft",
    "new_draft",
]
