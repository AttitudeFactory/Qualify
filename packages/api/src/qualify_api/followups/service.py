"""Continuing an interaction in private (m-24789646): open the followup with the author's
DM thread, say which ways of writing to them are available right now, and queue the one a
person approved.

**Opening** a followup reads its origin (a comment, or a DM that replied to a story)
and stores the link, idempotently per interaction. Nothing is sent and nothing appears in
Conversaciones: a comment author's DM thread — keyed by their IGSID, which a comment's
`from.id` already is — is found or created only when a person approves a send.

**Routes**, decided at read time and again at approval (never stored as «expired»):

- `dm` — a normal DM. Verified in production (QUA-226) and always offered, but only
  while the thread's 24 h window is open, i.e. the person wrote in the last 24 h.
- `private_reply` — Meta's one-off reply to a comment, addressed by the comment: the way
  to write first to someone who never messaged the business. Only for a comment, only
  within 7 days of it, and only while the `comment_private_reply` capability is on (B6:
  it is off until R1 verifies it against the real API).

When both are open the DM wins: it is verified, it keeps the conversation in the window
the person opened, and it does not spend the comment's single private reply.

**Approving** is the only way out, and it goes through the outbox with the person's
`HumanApproval` (ADR 21c) — this module never calls a channel. The sender revalidates the
window (or the 7-day deadline) when it actually sends.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from qualify_api.conversations.contracts import CHANNEL_DM, ChannelRegistry
from qualify_api.conversations.outbox import (
    ApprovalRequired,
    ConversationOutboxRepository,
    HumanApproval,
    PrivateReplyTarget,
)
from qualify_api.conversations.repository import ConversationRepository, ThreadRecord
from qualify_api.conversations.service import MAX_REPLY_CHARS
from qualify_api.conversations.window import (
    WindowState,
    private_reply_deadline,
    private_reply_window,
    window_state,
)
from qualify_api.followups.capabilities import Availability, Capabilities, Capability
from qualify_api.followups.origins import OriginMessage, OriginReader
from qualify_api.followups.repository import (
    Followup,
    FollowupOpening,
    FollowupRepository,
    FollowupStatus,
    FollowupTrigger,
    InvalidFollowupTransition,
    OriginKind,
    SendRoute,
    UnknownFollowup,
    new_followup,
)

COMMENT_CHANNEL: Final = "comment"

# Why a route is not available right now (Spanish, shown next to it).
REASON_DM_WINDOW_CLOSED: Final = (
    "La persona no ha escrito por mensaje directo en las últimas 24 horas."
)
REASON_PRIVATE_REPLY_EXPIRED: Final = (
    "Pasaron más de 7 días desde el comentario: Meta ya no acepta una respuesta privada."
)
REASON_PRIVATE_REPLY_NOT_A_COMMENT: Final = "La respuesta privada solo existe para comentarios."


class UnknownOrigin(LookupError):
    """No message with that id is visible in this tenant."""


class OriginNotSupported(ValueError):
    """The message cannot be continued in private (not inbound, deleted, no author id,
    or an origin whose capability is off). `reason` is Spanish, for the UI."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class RouteOption:
    route: SendRoute
    available: bool
    # When the route stops being possible (24 h window or 7-day limit); None if closed.
    closes_at: datetime | None
    # Empty when available.
    reason: str


@dataclass(frozen=True)
class SendOptions:
    dm: RouteOption
    private_reply: RouteOption

    @property
    def chosen(self) -> RouteOption | None:
        """The route an approval would use now: the DM when its window is open, else the
        private reply when possible, else none."""
        for option in (self.dm, self.private_reply):
            if option.available:
                return option
        return None


class RouteUnavailable(PermissionError):
    """No route can reach the person right now; `options` says why for each."""

    def __init__(self, options: SendOptions) -> None:
        super().__init__("no route can reach this person right now")
        self.options = options


class CapabilityUnavailable(PermissionError):
    def __init__(self, availability: Availability) -> None:
        super().__init__(availability.reason)
        self.availability = availability


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _option(route: SendRoute, window: WindowState, closed_reason: str) -> RouteOption:
    if window.is_open:
        return RouteOption(route, True, window.closes_at, "")
    return RouteOption(route, False, None, closed_reason)


class FollowupService:
    def __init__(
        self,
        *,
        followups: FollowupRepository,
        origins: OriginReader,
        conversations: ConversationRepository,
        outbox: ConversationOutboxRepository,
        registry: ChannelRegistry,
        capabilities: Capabilities,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._followups = followups
        self._origins = origins
        self._conversations = conversations
        self._outbox = outbox
        self._registry = registry
        self._capabilities = capabilities
        self._clock = clock

    # -- opening ------------------------------------------------------------------------

    def open_for_interaction(
        self,
        *,
        tenant_id: UUID,
        origin_message_id: UUID,
        trigger: FollowupTrigger,
        intent_result_id: UUID | None = None,
    ) -> FollowupOpening:
        """Open (or return) the followup of one interaction. Nothing is created in
        Conversaciones: a comment author's DM thread is created only when a person
        approves a send. Raises `UnknownOrigin` or `OriginNotSupported`."""
        origin = self._origin(tenant_id, origin_message_id)
        origin_kind = self._origin_kind(origin)
        return self._followups.open(
            new_followup(
                tenant_id=tenant_id,
                connection_id=origin.connection_id,
                origin_kind=origin_kind,
                origin_message_id=origin.id,
                # A story reply already IS a DM: its thread is the conversation.
                dm_thread_id=origin.thread_id if origin_kind is OriginKind.STORY_REPLY else None,
                trigger=trigger,
                intent_result_id=intent_result_id,
                now=self._clock(),
            )
        )

    def _origin(self, tenant_id: UUID, message_id: UUID) -> OriginMessage:
        origin = self._origins.get(tenant_id=tenant_id, message_id=message_id)
        if origin is None:
            raise UnknownOrigin(str(message_id))
        return origin

    def _origin_kind(self, origin: OriginMessage) -> OriginKind:
        if origin.direction != "inbound":
            raise OriginNotSupported("Solo se continúa en privado lo que escribió otra persona.")
        if origin.deleted:
            raise OriginNotSupported("El mensaje se borró en Instagram.")
        if not origin.author_external_id:
            raise OriginNotSupported("Meta no dio el identificador de quien lo escribió.")
        if origin.channel == COMMENT_CHANNEL:
            return OriginKind.COMMENT
        if origin.channel == CHANNEL_DM:
            availability = self._capabilities.availability(Capability.STORY_REPLY_CONTEXT)
            if not availability.enabled:
                raise OriginNotSupported(availability.reason)
            return OriginKind.STORY_REPLY
        raise OriginNotSupported("Este canal no se puede continuar en privado.")

    def _dm_thread(self, followup: Followup, origin: OriginMessage) -> ThreadRecord | None:
        """The author's DM thread if it exists — never created here. A comment author
        who already wrote to the business has one, keyed by the same IGSID."""
        if followup.dm_thread_id is not None:
            return self._conversations.get_thread(
                tenant_id=followup.tenant_id, thread_id=followup.dm_thread_id
            )
        return self._conversations.find_thread(
            tenant_id=followup.tenant_id,
            connection_id=followup.connection_id,
            channel=CHANNEL_DM,
            counterpart_external_id=origin.author_external_id or "",
        )

    # -- routes -------------------------------------------------------------------------

    def send_options(self, *, tenant_id: UUID, followup_id: UUID) -> SendOptions:
        followup = self._followup(tenant_id, followup_id)
        origin = self._origin(tenant_id, followup.origin_message_id)
        thread = self._dm_thread(followup, origin)
        return self._options(
            followup, origin, thread.last_inbound_at if thread else None, self._clock()
        )

    def options_from_origin(
        self, followup: Followup, origin: OriginMessage, now: datetime
    ) -> SendOptions:
        """The routes for a card, from an origin read with its DM window
        (`OriginReader.get_many`) — no read of its own, for a whole page of cards."""
        return self._options(followup, origin, origin.dm_last_inbound_at, now)

    def _options(
        self,
        followup: Followup,
        origin: OriginMessage,
        last_inbound_at: datetime | None,
        now: datetime,
    ) -> SendOptions:
        dm = _option(SendRoute.DM, window_state(last_inbound_at, now), REASON_DM_WINDOW_CLOSED)
        return SendOptions(dm=dm, private_reply=self._private_reply_option(followup, origin, now))

    def _private_reply_option(
        self, followup: Followup, origin: OriginMessage, now: datetime
    ) -> RouteOption:
        route = SendRoute.PRIVATE_REPLY
        if followup.origin_kind is not OriginKind.COMMENT:
            return RouteOption(route, False, None, REASON_PRIVATE_REPLY_NOT_A_COMMENT)
        availability = self._capabilities.availability(Capability.COMMENT_PRIVATE_REPLY)
        if not availability.enabled:
            return RouteOption(route, False, None, availability.reason)
        return _option(
            route, private_reply_window(origin.posted_at, now), REASON_PRIVATE_REPLY_EXPIRED
        )

    # -- approving ------------------------------------------------------------------------

    def approve_and_queue(
        self,
        *,
        tenant_id: UUID,
        followup_id: UUID,
        text: str,
        approval: HumanApproval,
        notice_text: str | None = None,
    ) -> Followup:
        """Queue the approved text on the route available now and record the decision,
        in ONE transaction: the outbox insert and the followup's guarded `open ->
        approved` commit together, so a lost race (a second approval, a discard) rolls
        the queued send back and nothing goes out twice. Raises `ApprovalRequired`,
        `ValueError` (empty / too long), `UnknownFollowup`, `InvalidFollowupTransition`
        (not open, or decided concurrently), `CapabilityUnavailable` (a notice while
        `public_notice` is off), `RouteUnavailable` or `PrivateReplyExists`."""
        if not isinstance(approval, HumanApproval):
            raise ApprovalRequired("a private message needs a human approval")
        body = text.strip()
        if not body:
            raise ValueError("an empty message cannot be sent")
        if len(body) > MAX_REPLY_CHARS:
            raise ValueError(f"a message is at most {MAX_REPLY_CHARS} characters")
        if (notice_text or "").strip():
            notice = self._capabilities.availability(Capability.PUBLIC_NOTICE)
            if not notice.enabled:
                raise CapabilityUnavailable(notice)
        followup = self._followup(tenant_id, followup_id)
        if followup.status is not FollowupStatus.OPEN:
            raise InvalidFollowupTransition(f"followup {followup.id} is {followup.status}")
        now = self._clock()
        origin = self._origin(tenant_id, followup.origin_message_id)
        thread = self._dm_thread(followup, origin)
        options = self._options(followup, origin, thread.last_inbound_at if thread else None, now)
        chosen = options.chosen
        if chosen is None:
            raise RouteUnavailable(options)

        sender = self._registry.sender_for(CHANNEL_DM)
        if chosen.route is SendRoute.DM:
            # An open DM window implies the thread exists (the person wrote in it).
            if thread is None:
                raise RouteUnavailable(options)
            thread_id = thread.id
            payload = sender.build_payload(
                recipient_external_id=thread.counterpart_external_id, text=body
            )
            target = None
        else:
            if origin.posted_at is None:  # unreachable: an open 7-day window implies it
                raise RouteUnavailable(options)
            payload = sender.build_private_reply_payload(
                comment_id=origin.external_message_id, text=body
            )
            target = PrivateReplyTarget(
                comment_id=origin.external_message_id,
                deadline=private_reply_deadline(origin.posted_at),
            )
            # Only now, with a person's decision, does the author get a DM thread.
            thread_id = (
                thread.id
                if thread is not None
                else self._conversations.upsert_thread(
                    tenant_id=tenant_id,
                    connection_id=followup.connection_id,
                    channel=CHANNEL_DM,
                    counterpart_external_id=origin.author_external_id or "",
                ).thread_id
            )

        approved: list[Followup] = []

        def record_decision(session: object, outbox_id: UUID) -> None:
            approved.append(
                self._followups.approve(
                    tenant_id=tenant_id,
                    followup_id=followup_id,
                    outbox_id=outbox_id,
                    send_route=chosen.route,
                    dm_thread_id=thread_id,
                    decided_by_user_id=approval.user_id,
                    now=now,
                    notice_text=notice_text,
                    session=session,
                )
            )

        self._outbox.enqueue(
            tenant_id=tenant_id,
            connection_id=followup.connection_id,
            thread_id=thread_id,
            channel=CHANNEL_DM,
            payload=payload,
            approval=approval,
            private_reply=target,
            on_enqueued=record_decision,
        )
        return approved[0]

    def discard(self, *, tenant_id: UUID, followup_id: UUID, user_id: UUID) -> Followup:
        return self._followups.discard(
            tenant_id=tenant_id,
            followup_id=followup_id,
            decided_by_user_id=user_id,
            now=self._clock(),
        )

    def _followup(self, tenant_id: UUID, followup_id: UUID) -> Followup:
        followup = self._followups.get(tenant_id=tenant_id, followup_id=followup_id)
        if followup is None:
            raise UnknownFollowup(str(followup_id))
        return followup
