"""Act on any chat by its thread id alone, through the channel that owns it (m-25027372, BU-A6).

`docs/arquitectura-bandeja-unica.md` §1.3 and §2.2: the inbox converges the READ side
(`inbox.unified`) but not the write side. An owner's action on a chat — send a text,
close, reopen, assign — takes only `thread_id`; this dispatcher reads `threads.channel`
for that id **under RLS** (`tenant_session`) and calls the channel's EXISTING service:

- `send_text`: `dm` → `ConversationService.reply_text` (→ `conversation_outbox`);
  `whatsapp` → `ChatService.send(TextSend)` (→ `whatsapp_outbox`).
- `close`: `dm` → `ConversationService.close` (compare-and-set on the inbound the owner
  saw); `whatsapp` → `ChatService.close`.
- `reopen`: `ConversationService.reopen` / `ChatService.reopen`.
- `assign`: `dm` is refused with `ActionNotSupported` (descriptor `assign=False`);
  `whatsapp` → `ChatService.assign`.

## What it guarantees, and what it leaves to the channel

- **The channel never comes from the caller.** No method takes a channel: it is the
  stored `threads.channel`, read in the business's own `tenant_session`. Another
  business's thread is invisible there and reads as `ThreadNotFound` — nothing is
  written. A stored channel the inbox does not list (`comment`, a future channel with no
  route here) is `UnknownChannel`, also before any write.
- **Capabilities come from `inbox.channels`.** An action the channel's descriptor does not
  offer (`assign` on Instagram) is `ActionNotSupported`, raised before the channel service
  is called.
- **Assisted, never autonomous.** `send_text` demands a `HumanApproval` (the person who
  approved this exact text, and when) for BOTH channels; there is no overload without it.
  Instagram gets it unchanged — `conversation_outbox.enqueue` keeps demanding it and its
  NOT NULL column keeps holding it (`test_conversations_outbox_sanctity.py`); WhatsApp
  gets `approval.user_id` only — the `created_by_user_id` its outbox stores today. Its
  outbox has no column for `approved_at` or `draft_id`, so `approved_at` is dropped and an
  approval carrying a `draft_id` is refused on WhatsApp (`DraftNotSupported`, nothing
  written): no WhatsApp caller passes one today, and WhatsApp has no AI drafts
  (`suggest_reply=False`). Nothing is sent inline: both services only queue, and each
  channel's own worker sends.
- **No second idempotency layer.** Each call is the channel call the screens make today,
  with the same arguments, so each outbox's own guarantees hold unchanged. Neither text
  send takes a request key today (WhatsApp's `send` and Instagram's `reply_text`), so
  this one does not either.
- **Errors.** The two channels' `ThreadNotFound` and `WindowClosed`, and Instagram's
  «no sender for this channel» (`conversations.contracts.UnknownChannel`), are translated
  to the ones below (the cause chained), so a caller catches one type whatever the
  channel. `WindowClosed`, `ActionNotSupported` and `DraftNotSupported` derive from plain
  `Exception` on purpose — not `PermissionError` (the chat screens read a
  `PermissionError` as «no session»), not `ValueError`, not `LookupError`. Everything else
  a channel service raises passes through unchanged: `ValueError` (empty or too long
  text), `ApprovalRequired`, `NotAMember` (only when the caller wraps the call in
  `tenancy.acting.acting_login`), `CapabilityUnavailable`, WhatsApp's `UnknownAgent`,
  Instagram's `ThreadChangedSinceSeen` (its `view` is the thread as it is now).
  **Caveats:** two of those pass-through errors ARE `PermissionError`s (their existing
  bases): `ApprovalRequired` (reachable only when a caller passes no approval — a caller
  bug) and `CapabilityUnavailable` (unreachable today: the dispatcher never passes quick
  replies). A caller must catch them before a generic `except PermissionError` («no
  session»). Likewise `UnknownChannel` and WhatsApp's `UnknownAgent` are `ValueError`s,
  so a caller's `except ValueError` meant for «texto rechazado» must catch them first.

## What it does NOT check — the caller's job

- **Which account the screen is on.** The screens check that the thread belongs to the
  connection they show (`_owned` in `Qualify/conversations_provider.py` and
  `Qualify/whatsapp_chats_provider.py`); the dispatcher only knows the business.
- **Whether the account may answer now.** The Instagram composer opens only for an
  account whose C-05 matrix grants `manage_dms` and that is not degraded
  (`Qualify/conversations_state.py` `account_can_reply`), and revoked accounts are not
  listed; the WhatsApp screen has no such rule today. The dispatcher does not repeat
  either rule: it is per channel, lives in the connections projection, and a status-only
  check here would be a third, new rule. What happens today to a row queued on a
  connection that is not `active`: in both workers the connection check runs BEFORE the
  24 h window check, so the row is put back (`connection_unavailable`, retried every 60 s,
  attempts kept). If the connection never becomes `active` again it is re-polled every
  60 s indefinitely and never reaches `window_closed`. Once the connection is `active`
  again, the window is checked: within 24 h of the customer's last message the approved
  text goes out late; after that it fails as `window_closed`. Capping those retries is
  worker work, outside this module.
- **Membership on close/reopen/assign.** Neither channel service gates those on
  `require_acting_member` today; only the sends do.

The two outboxes and their workers are untouched (out of scope: unifying them).
No screen calls this yet; BU-A7 (m-25027371) and m-25027374 will.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text as sql_text

from qualify_api.assisted.approval import ApprovalRequired, HumanApproval
from qualify_api.conversations import service as instagram
from qualify_api.conversations.contracts import UnknownChannel as NoSenderForChannel
from qualify_api.inbox.channels import (
    CHANNEL_INSTAGRAM_DM,
    CHANNEL_WHATSAPP,
    ChannelCapabilities,
    UnknownChannel,
    capabilities_for,
)
from qualify_api.whatsapp import chats as whatsapp

Action = Literal["send_text", "close", "reopen", "assign"]


class ThreadNotFound(LookupError):
    """No chat with this id for this business — another business's chat included: RLS
    makes the two indistinguishable, and the dispatcher keeps it that way."""


class WindowClosed(Exception):
    """The channel's 24 h window is closed, so a free-form text would be refused. Nothing
    was written. `closes_at` is the instant it closed when the channel knows it (WhatsApp),
    else `None`; `channel` is the thread's."""

    def __init__(self, channel: str, closes_at: datetime | None) -> None:
        super().__init__(f"the 24 h window of this {channel} chat is closed")
        self.channel = channel
        self.closes_at = closes_at


class ActionNotSupported(Exception):
    """The thread's channel does not offer this action (its `ChannelCapabilities` says
    so). Raised before the channel service is called: nothing was written."""

    def __init__(self, channel: str, action: Action) -> None:
        super().__init__(f"{channel} chats do not support {action!r}")
        self.channel = channel
        self.action = action


class DraftNotSupported(Exception):
    """The approval names an AI draft (`draft_id`) but the thread's channel keeps no
    record of it (WhatsApp's outbox stores only who approved). Refused before the channel
    service is called: nothing was written."""

    def __init__(self, channel: str) -> None:
        super().__init__(f"{channel} chats do not record the draft a reply came from")
        self.channel = channel


# ======================================================================================
# Where a thread's channel is read
# ======================================================================================


class ThreadChannels(Protocol):
    """The stored `threads.channel` of one thread, as the business sees it (None when the
    business cannot see that thread)."""

    def channel_of(self, *, tenant_id: UUID, thread_id: UUID) -> str | None: ...


_CHANNEL_OF: Final = sql_text("SELECT channel FROM threads WHERE id = :thread_id")


class PostgresThreadChannels:
    """`tenant_session(tenant_id)` (the `qualify_app` role): RLS bounds the read, so no
    `tenant_id` predicate is needed — and none could widen it."""

    def channel_of(self, *, tenant_id: UUID, thread_id: UUID) -> str | None:
        with tenant_session(tenant_id) as session:
            return session.execute(_CHANNEL_OF, {"thread_id": thread_id}).scalar_one_or_none()


@dataclass
class MemoryThreadChannels:
    """In-memory twin for offline tests: a thread is visible only to its own business."""

    threads: dict[UUID, tuple[UUID, str]] = field(default_factory=dict)

    def add(self, *, tenant_id: UUID, thread_id: UUID, channel: str) -> None:
        self.threads[thread_id] = (tenant_id, channel)

    def channel_of(self, *, tenant_id: UUID, thread_id: UUID) -> str | None:
        owner = self.threads.get(thread_id)
        if owner is None or owner[0] != tenant_id:
            return None
        return owner[1]


# ======================================================================================
# The dispatcher
# ======================================================================================


@contextmanager
def _channel_errors(channel: str) -> Iterator[None]:
    """One `ThreadNotFound` / `WindowClosed` whatever the channel (module docstring)."""
    try:
        yield
    except (instagram.ThreadNotFound, whatsapp.ThreadNotFound) as error:
        raise ThreadNotFound(str(error)) from error
    except instagram.WindowClosed as error:
        raise WindowClosed(channel, error.window.closes_at) from error
    except whatsapp.WindowClosed as error:
        raise WindowClosed(channel, error.closes_at) from error
    except NoSenderForChannel as error:
        raise UnknownChannel(f"channel {channel!r} has no sender") from error


class ChatDispatcher:
    """Routes an owner's action on a chat to its channel's service; see the module
    docstring. Every method takes the caller's `tenant_id` explicitly (from the session,
    never from the browser) and the `thread_id` only."""

    def __init__(
        self,
        *,
        channels: ThreadChannels,
        instagram_service: instagram.ConversationService,
        whatsapp_service: whatsapp.ChatService,
    ) -> None:
        self._channels = channels
        self._instagram = instagram_service
        self._whatsapp = whatsapp_service

    def capabilities(self, *, tenant_id: UUID, thread_id: UUID) -> ChannelCapabilities:
        """The descriptor of the thread's stored channel. `ThreadNotFound` when the
        business cannot see the thread, `UnknownChannel` when the inbox does not list its
        channel."""
        channel = self._channels.channel_of(tenant_id=tenant_id, thread_id=thread_id)
        if channel is None:
            raise ThreadNotFound(str(thread_id))
        caps = capabilities_for(channel)
        if caps.channel not in (CHANNEL_INSTAGRAM_DM, CHANNEL_WHATSAPP):
            # A descriptor with no route here (a future channel): fail closed.
            raise UnknownChannel(f"channel {channel!r} has no service to dispatch to")
        return caps

    def send_text(
        self, *, tenant_id: UUID, thread_id: UUID, text: str, approval: HumanApproval
    ) -> list[UUID]:
        """Queue the owner's approved text on the thread's own channel; returns the outbox
        row ids (Instagram splits a text over 1000 characters into several messages;
        WhatsApp queues one). The approval is checked before the channel is read;
        WhatsApp receives only `approval.user_id` (module docstring)."""
        if not isinstance(approval, HumanApproval):
            raise ApprovalRequired("a reply needs a human approval")
        body = text.strip()
        if not body:
            raise ValueError("an empty reply cannot be sent")
        caps = self.capabilities(tenant_id=tenant_id, thread_id=thread_id)
        if caps.channel == CHANNEL_WHATSAPP and approval.draft_id is not None:
            raise DraftNotSupported(caps.channel)
        with _channel_errors(caps.channel):
            if caps.channel == CHANNEL_INSTAGRAM_DM:
                return self._instagram.reply_text(
                    tenant_id=tenant_id, thread_id=thread_id, text=body, approval=approval
                )
            return [
                self._whatsapp.send(
                    tenant_id, thread_id, approval.user_id, whatsapp.TextSend(text=body)
                )
            ]

    def close(
        self, *, tenant_id: UUID, thread_id: UUID, seen_last_inbound_at: datetime | None
    ) -> None:
        """«Cerrar». `seen_last_inbound_at` is the customer's last message as the owner's
        screen showed it: Instagram refuses with `ThreadChangedSinceSeen` when a newer one
        is stored (m-25026457); WhatsApp's `close` has no such check today and ignores it."""
        caps = self._require(tenant_id, thread_id, "close")
        with _channel_errors(caps.channel):
            if caps.channel == CHANNEL_INSTAGRAM_DM:
                self._instagram.close(
                    tenant_id=tenant_id,
                    thread_id=thread_id,
                    seen_last_inbound_at=seen_last_inbound_at,
                )
            else:
                self._whatsapp.close(tenant_id, thread_id)

    def reopen(self, *, tenant_id: UUID, thread_id: UUID) -> None:
        """«Reabrir»: reopening an open chat is a no-op on both channels."""
        caps = self._require(tenant_id, thread_id, "reopen")
        with _channel_errors(caps.channel):
            if caps.channel == CHANNEL_INSTAGRAM_DM:
                self._instagram.reopen(tenant_id=tenant_id, thread_id=thread_id)
            else:
                self._whatsapp.reopen(tenant_id, thread_id)

    def assign(self, *, tenant_id: UUID, thread_id: UUID, agent_user_id: UUID | None) -> None:
        """Hand the chat to a member of the business (`None` unassigns). Only channels
        whose descriptor has `assign` — WhatsApp today; Instagram is
        `ActionNotSupported`, with nothing written."""
        caps = self._require(tenant_id, thread_id, "assign")
        if caps.channel != CHANNEL_WHATSAPP:
            # Only WhatsApp has an assign door; a descriptor saying otherwise is refused.
            raise ActionNotSupported(caps.channel, "assign")
        with _channel_errors(caps.channel):
            self._whatsapp.assign(tenant_id, thread_id, agent_user_id)

    def _require(self, tenant_id: UUID, thread_id: UUID, action: Action) -> ChannelCapabilities:
        caps = self.capabilities(tenant_id=tenant_id, thread_id=thread_id)
        offered = caps.assign if action == "assign" else caps.close_reopen
        if not offered:
            raise ActionNotSupported(caps.channel, action)
        return caps


def production_chat_dispatcher() -> ChatDispatcher:
    """The channel read and both channel services over Postgres, as production wires
    each of them today."""
    from qualify_api.conversations.composition import (  # noqa: PLC0415
        production_conversation_service,
    )

    return ChatDispatcher(
        channels=PostgresThreadChannels(),
        instagram_service=production_conversation_service(),
        whatsapp_service=whatsapp.production_chat_service(),
    )


__all__ = [
    "Action",
    "ActionNotSupported",
    "ChatDispatcher",
    "DraftNotSupported",
    "MemoryThreadChannels",
    "PostgresThreadChannels",
    "ThreadChannels",
    "ThreadNotFound",
    "UnknownChannel",
    "WindowClosed",
    "production_chat_dispatcher",
]
