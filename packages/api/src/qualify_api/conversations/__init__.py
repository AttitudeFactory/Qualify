"""Conversaciones — the multichannel private-messaging inbox (QUA-226, Fase 1 Parte 4-B,
ADR 21c: assisted replies only, never autonomous).

E1 (this package as of 2026-10-16) is the FOUNDATION: contracts, persistence, the queue
and their tests. No channel adapter talks to Meta yet (E3), no worker sends (later), no
UI reads it (E2), no model drafts a reply (E4).

- `contracts` — `ConversationSource` / `ConversationSender`, the channel seam; a channel
  is one implementation of each, registered in a `ChannelRegistry`. Thread identity is
  the COUNTERPART's external id (IGSID), so the webhook and poll paths converge.
- `repository` — `threads`/`messages` (0004 + 0063) and `conversation_sync_state`
  (0063): dedup by `(connection_id, external_message_id)` at INSERT time, access + sync
  state per connection, `tenant_session` per call.
- `outbox` — `conversation_outbox` (0063) and `HumanApproval`, the only way in. The
  approving person is a NOT NULL column; the webhook worker holds no grant on the table.
- `sync` — the reconciliation poll and the single-message door, channel-agnostic.
- `service` — list / read / mark read / reply (window-checked, then queued), the seam the
  UI will consume. `attention_state` derives «pendiente / leído / respondido».
- `drafts` — the assisted-draft CONTRACT (statuses of 0014, pure transition); no table
  yet.
- `memory_source` — the second channel: an in-memory source + sender pair, the proof the
  seam holds and the fixture of the offline tests.
- `window` — the 24 h window, re-exported from `whatsapp.window` (one decision, shared).

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
    DraftRepository,
    DraftStatus,
    InvalidDraftTransition,
    MemoryDraftRepository,
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
from qualify_api.conversations.service import (
    AttentionState,
    ConversationService,
    ThreadNotFound,
    ThreadView,
    WindowClosed,
    attention_state,
)
from qualify_api.conversations.sync import ConversationSyncService, IngestResult, SyncReport

__all__ = [
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
    "DraftRepository",
    "DraftStatus",
    "HumanApproval",
    "IngestResult",
    "InvalidDraftTransition",
    "MemoryConversationOutboxRepository",
    "MemoryConversationRepository",
    "MemoryDraftRepository",
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
