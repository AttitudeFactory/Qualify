"""Instagram Direct as a channel of the Conversaciones module (QUA-226, E3): the
`ConversationSource` / `ConversationSender` pair over the Messenger Platform's Instagram
Messaging API, under the signed Facebook Login fork (ADR 25).

## What this module talks to — and what it has NOT been able to prove

Every endpoint below was read from the corpus (`reference/meta-instagram-platform/
documentation/business-messaging/instagram-messaging/...`). Verified live on 2026-10-16
(`@qualifymkt.co`, Standard Access, `instagram_manage_messages` granted to a tester with
a role on the app): the access probe, the conversations listing with participants, and
the messages edge for a text message — all 200, all parsed without adjustment. Still
`[V]`-pending: attachments (media messages) and the send response (`POST /messages`
has never been called from this code). `SHAPE_VERSION_IG_DM` is stamped on every row so
a later correction can find what an earlier reading wrote. The verifiable list of these
dependencies is `docs/conversaciones-limitaciones-meta.md`.

- `GET /{page-id}/conversations?platform=instagram&fields=id,updated_time,participants`
  (`get-started.md:133`): the Page's Instagram conversations. The counterpart is the
  participant whose id is NOT the connected account's `external_account_id`.
- `GET /{conversation-id}/messages?fields=id,created_time,from,to,message,attachments`
  (`conversations-api.md`, "Get information about a message"): newest first; **only the
  ~20 most recent carry details** — older ids come back as deleted. The poll is a
  reconciliation, the webhook (`webhook.py`) is the forward path. With
  `story_replies=True` (the `story_reply_context` capability, m-24789646) the request
  also asks for `story` (`graph-api/reference/message.md`: «The link and ID for a story.
  Only mentions and replies are supported»), and `story.reply_to` becomes the message's
  story reply; a `story.mention` is not a reply and is ignored. Corpus-only until R3.
- `POST /{page-id}/messages` with `{"recipient": {"id": IGSID}, "message": {"text"}}`
  (`send-message.md`): text ≤ 1000 UTF-8 bytes, inside the 24 h window, and — with
  Standard Access — only to people with a role on the app. m-24789472: the same POST
  carries `message.quick_replies` (`features/quick-replies.md`) or a button template
  (`message.attachment.type = template`, `button-template.md`); both corpus-only, behind
  the `quick_replies` / `structured_templates` capabilities until R7 / R8.

## Access is a verdict (`check_access`)

1. The connection's `granted_scopes` lack every spelling of the messages scope
   (`permission_capability.SCOPE_LITERALS[MANAGE_MESSAGES]`) → `PERMISSION_MISSING`,
   **without calling Meta**: the C-05 matrix already knows the answer.
2. A probe (`limit=1` on the conversations edge): HTTP 401 / code 190 →
   `AUTH_EXPIRED`; code 10 or 200–299 → `PERMISSION_MISSING`; any other failure →
   `ERROR` with `http_<status>_code_<code>` as detail; 200 → `OK`.
3. The owner's «Allow Access to Messages» toggle (`get-started.md:129`) has **no API
   signal** (`ig_shapes.UNCOVERED_SURFACES["direct_messages_human_toggle"]`): an `OK`
   probe with an empty list is still ambiguous, and the UI says so.

## Token discipline

Same as every Meta client here: the module never sees a token. `client_for` yields an
`AuthenticatedClient` already carrying the Page access token (the resolver injects it,
R3). Errors carry HTTP status and Meta's numeric codes only — never a response body, which
echoes request parameters and user text.
"""

from __future__ import annotations

import copy
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import httpx
from qualify_shared.social.graph_errors import is_auth_error

from qualify_api.connections.resolver import AuthenticatedClient
from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    REPLY_MEDIA_TYPES,
    REPLY_STICKERS,
    SENDER_ACTIONS,
    AccessStatus,
    AccessVerdict,
    Page,
    RemoteConversation,
    RemoteMessage,
    RemoteProfile,
    SendResult,
    SourceConnection,
    story_reference,
)
from qualify_api.conversations.interactive import (
    QuickReply,
    TemplateButton,
    button_template_message,
    clean_quick_replies,
    quick_replies_wire,
)

logger = logging.getLogger("qualify_api.conversations.instagram")

#: Stamped on every row this adapter writes. Bump when a reading of the corpus is
#: corrected by a live observation. `1.0.0` = the conversations listing (participants,
#: updated_time) and a TEXT message (id, created_time, from.id/username, message) were
#: observed live on 2026-10-16 against `@qualifymkt.co` under Standard Access and parsed
#: without adjustment; attachments (media) and the send response are still corpus-only.
SHAPE_VERSION_IG_DM: Final = "ig-dm-messenger-platform-1.0.0"

CONVERSATION_FIELDS: Final = "id,updated_time,participants"
MESSAGE_FIELDS: Final = "id,created_time,from,to,message,attachments"
#: m-24789646: the same request plus the story a message replies to (or mentions).
MESSAGE_FIELDS_WITH_STORY: Final = f"{MESSAGE_FIELDS},story"
#: `user-profile.md`: the three fields the inbox shows. `profile_pic` expires in days.
PROFILE_FIELDS: Final = "name,username,profile_pic"
#: httpx's default is 5 s, which Graph exceeds routinely: the messages edge with
#: attachments, and a send whose media Meta fetches from Qualify DURING the request
#: (measured 2026-10-16: a photo send timed out, was retried and reached the person
#: twice). Reads get 30 s; a send gets 60 s.
READ_TIMEOUT_S: Final = 30.0
SEND_TIMEOUT_S: Final = 60.0
#: Transport failures AFTER the request may have reached Meta: the outcome is unknown,
#: so a send with one of these must NOT be retried blindly.
_AMBIGUOUS_TRANSPORT: Final = (
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    httpx.WriteError,
)
#: Qualify's `messages.media_type` → the Messenger Platform's `attachment.type`
#: (`send-message.md` «Limitations»: a PDF goes as `file`). Identity for the rest.
WIRE_ATTACHMENT_TYPES: Final[dict[str, str]] = {"document": "file"}
#: `conversations-api.md`: details exist only for the ~20 most recent messages.
MESSAGES_PAGE_LIMIT: Final = 20

#: Every spelling Meta has used for the DM scope (C-05 matrix, `permission_capability`).
MESSAGES_SCOPE_LITERALS: Final = frozenset(
    {
        "instagram_manage_messages",  # Facebook Login fork (ADR 25) — the one Qualify needs
        "instagram_business_manage_messages",  # Instagram Login (not Qualify's fork)
        "business_manage_messages",  # deprecated 2025-01-27
    }
)

#: Meta error codes read as "the app lacks the permission" (`code 10`, and the 200-299
#: permission family). `[V]`-pending, like everything else here.
_PERMISSION_CODES: Final = frozenset({10, *range(200, 300)})
#: Attachment kinds of the Messenger Platform → `messages.media_type`'s CHECKed list.
_ATTACHMENT_MEDIA_TYPES: Final = {
    "image": "image",
    "video": "video",
    "audio": "audio",
    "file": "document",
    "share": "other",
    "story_mention": "other",
    "reel": "video",
    "ig_reel": "video",
    "template": "interactive",
}

ClientFactory = Callable[[UUID, UUID], Awaitable[AuthenticatedClient]]
ScopeReader = Callable[[UUID, UUID], tuple[str, ...] | None]


class InstagramDirectError(Exception):
    """A Messenger Platform call failed. Status and numeric codes only — no body."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        platform_code: int | None = None,
        platform_subcode: int | None = None,
        is_transport: bool = False,
        is_ambiguous: bool = False,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.platform_code = platform_code
        self.platform_subcode = platform_subcode
        self.is_transport = is_transport
        # The request may have reached Meta (a read timeout, a dropped response): the
        # sender must not retry it as if it had never happened.
        self.is_ambiguous = is_ambiguous

    @property
    def is_auth_error(self) -> bool:
        return is_auth_error(http_status=self.http_status, platform_code=self.platform_code)

    @property
    def is_permission_error(self) -> bool:
        return self.platform_code in _PERMISSION_CODES

    @property
    def is_retryable(self) -> bool:
        """Transport failures BEFORE the request went out, rate limits and 5xx are
        retried; an ambiguous transport failure is not (the message may have gone out);
        everything else is a definitive answer from Meta (a policy refusal, a bad
        recipient, a closed window)."""
        if self.is_ambiguous:
            return False
        if self.is_transport or self.http_status == 429:
            return True
        return self.http_status is not None and self.http_status >= 500

    def access_detail(self) -> str:
        return f"http_{self.http_status}_code_{self.platform_code}"


def has_messages_scope(granted: tuple[str, ...] | list[str] | None) -> bool:
    return bool(granted) and any(scope in MESSAGES_SCOPE_LITERALS for scope in granted or ())


def _error_codes(response: httpx.Response) -> tuple[int | None, int | None]:
    """Meta's numeric `error.code` / `error.error_subcode`, or Nones. Duplicated from the
    other clients on purpose (each one is self-contained)."""
    try:
        error = dict(response.json()).get("error")
    except ValueError:
        return None, None
    if not isinstance(error, dict):
        return None, None
    code, subcode = error.get("code"), error.get("error_subcode")
    return (
        code if isinstance(code, int) else None,
        subcode if isinstance(subcode, int) else None,
    )


def _failed(what: str, response: httpx.Response) -> InstagramDirectError:
    code, subcode = _error_codes(response)
    return InstagramDirectError(
        f"{what} failed with HTTP {response.status_code}",
        http_status=response.status_code,
        platform_code=code,
        platform_subcode=subcode,
    )


def _transport(what: str, exc: Exception) -> InstagramDirectError:
    return InstagramDirectError(
        f"{what} failed in transport ({type(exc).__name__})",
        is_transport=True,
        is_ambiguous=isinstance(exc, _AMBIGUOUS_TRANSPORT),
    )


# --- [V]-pending response parsing. One function per endpoint. ---------------------------


def parse_graph_time(value: Any) -> datetime | None:
    """`2022-07-12T19:11:07+0000` (Graph's ISO 8601 with a colon-less offset) or a Unix
    timestamp in seconds / milliseconds → aware UTC datetime; `None` for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        seconds = value / 1000 if value >= 10**11 else value
        try:
            return datetime.fromtimestamp(seconds, UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # `+0000` → `+00:00` so `fromisoformat` accepts it on every supported Python.
    if len(text) >= 5 and text[-5] in "+-" and text[-3] != ":" and text[-4:].isdigit():
        text = f"{text[:-2]}:{text[-2:]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _next_cursor(payload: Mapping[str, Any]) -> str | None:
    paging = payload.get("paging")
    if not isinstance(paging, Mapping):
        return None
    cursors = paging.get("cursors")
    after = cursors.get("after") if isinstance(cursors, Mapping) else None
    if isinstance(after, str) and after and paging.get("next"):
        return after
    return None


def parse_conversations_page(
    payload: Mapping[str, Any], *, own_account_id: str
) -> Page[RemoteConversation]:
    """`{"data": [{"id", "updated_time", "participants": {"data": [{"id", "username"}]}}],
    "paging": {...}}`. A conversation whose participants do not include a counterpart
    (only the account itself, or no participants field) is skipped: there is nobody to
    key the thread on."""
    data = payload.get("data")
    if not isinstance(data, list):
        raise InstagramDirectError("conversations response has no 'data' list")
    items: list[RemoteConversation] = []
    for raw in data:
        if not isinstance(raw, Mapping):
            continue
        conversation_id = raw.get("id")
        participants = raw.get("participants")
        people = participants.get("data") if isinstance(participants, Mapping) else None
        counterpart: Mapping[str, Any] | None = None
        for person in people or []:
            if not isinstance(person, Mapping):
                continue
            person_id = str(person.get("id", ""))
            if person_id and person_id != own_account_id:
                counterpart = person
                break
        if counterpart is None:
            continue
        username = counterpart.get("username")
        items.append(
            RemoteConversation(
                counterpart_external_id=str(counterpart["id"]),
                external_conversation_id=str(conversation_id) if conversation_id else None,
                counterpart_username=username if isinstance(username, str) else None,
                updated_at=parse_graph_time(raw.get("updated_time")),
            )
        )
    return Page(items=tuple(items), next_cursor=_next_cursor(payload))


def _media_type(raw: Mapping[str, Any]) -> str | None:
    """`attachments.data[0]` → `messages.media_type`; `None` when there is none. A node
    flagged `is_unsupported` (verified live 2026-10-16: every audio — the person's voice
    notes and Qualify's own audio echoes — comes back so, with an empty `message` and no
    `attachments`) is `other`: content the API does not expose."""
    if raw.get("is_unsupported") is True:
        return "other"
    attachments = raw.get("attachments")
    data = attachments.get("data") if isinstance(attachments, Mapping) else None
    if not data or not isinstance(data, list):
        return None
    first = data[0]
    if not isinstance(first, Mapping):
        return "other"
    for key, media_type in _ATTACHMENT_MEDIA_TYPES.items():
        if key in first or first.get("type") == key or f"{key}_data" in first:
            return media_type
    if "image_data" in first:
        return "image"
    if "video_data" in first:
        return "video"
    if "file_url" in first:
        return "document"
    return "other"


def _media_url(raw: Mapping[str, Any]) -> str | None:
    """The CDN URL of `attachments.data[0]` on the message node (`graph-api/reference/
    message.md:98`): `image_data.url`, `video_data.url`, `file_url`, or the generic
    `payload.url` / `url` of any other kind. `None` without an attachment."""
    attachments = raw.get("attachments")
    data = attachments.get("data") if isinstance(attachments, Mapping) else None
    if not data or not isinstance(data, list) or not isinstance(data[0], Mapping):
        return None
    first = data[0]
    for key in ("image_data", "video_data", "audio_data", "payload"):
        nested = first.get(key)
        if isinstance(nested, Mapping) and isinstance(nested.get("url"), str):
            return nested["url"]
    for key in ("file_url", "url"):
        if isinstance(first.get(key), str) and first[key]:
            return first[key]
    return None


def parse_messages_page(payload: Mapping[str, Any], *, own_account_id: str) -> Page[RemoteMessage]:
    """`{"data": [{"id", "created_time", "from": {"id", "username"}, "to": {"data": [...]},
    "message", "attachments"}], "paging": {...}}`. Direction is decided by `from.id`
    against the connected account's id: the account's own messages are `outbound`."""
    data = payload.get("data")
    if not isinstance(data, list):
        raise InstagramDirectError("messages response has no 'data' list")
    items: list[RemoteMessage] = []
    for raw in data:
        if not isinstance(raw, Mapping) or not raw.get("id"):
            continue
        sender = raw.get("from") if isinstance(raw.get("from"), Mapping) else {}
        author_id = str(sender.get("id")) if sender.get("id") is not None else None
        username = sender.get("username")
        text = raw.get("message")
        outbound = author_id == own_account_id
        story = None if outbound else _story_reply(raw)
        items.append(
            RemoteMessage(
                external_message_id=str(raw["id"]),
                direction="outbound" if outbound else "inbound",
                text=text if isinstance(text, str) and text else None,
                posted_at=parse_graph_time(raw.get("created_time")),
                shape_version=SHAPE_VERSION_IG_DM,
                author_external_id=author_id,
                author_username=username if isinstance(username, str) else None,
                media_type=_media_type(raw),
                media_url=_media_url(raw),
                story_reply_id=story[0] if story else None,
                story_reply_url=story[1] if story else None,
            )
        )
    return Page(items=tuple(items), next_cursor=_next_cursor(payload))


def _story_reply(raw: Mapping[str, Any]) -> tuple[str, str | None] | None:
    """`story.reply_to = {"link", "id"}` on the Message node. `[CORPUS]`: the reference
    names the two kinds (StoryReply / StoryMention) without showing the wrapper key;
    `reply_to` mirrors the webhook's. A mention, or a shape without it, is not a reply."""
    story = raw.get("story")
    return story_reference(story.get("reply_to")) if isinstance(story, Mapping) else None


def parse_profile(payload: Mapping[str, Any]) -> RemoteProfile | None:
    """`{"name", "username", "profile_pic", ...}` (`user-profile.md`); `None` when it
    carries nothing usable."""

    def _str(key: str) -> str | None:
        value = payload.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    profile = RemoteProfile(
        name=_str("name"), username=_str("username"), avatar_url=_str("profile_pic")
    )
    if profile.name is None and profile.username is None and profile.avatar_url is None:
        return None
    return profile


def parse_send_response(payload: Mapping[str, Any]) -> SendResult:
    """`{"recipient_id": IGSID, "message_id": "m_…"}` (`send-message.md`)."""
    message_id = payload.get("message_id")
    if not isinstance(message_id, str) or not message_id:
        raise InstagramDirectError("send response carries no 'message_id'")
    recipient_id = payload.get("recipient_id")
    return SendResult(
        external_message_id=message_id,
        recipient_external_id=recipient_id
        if isinstance(recipient_id, str) and recipient_id
        else None,
    )


# --- the channel ------------------------------------------------------------------------


class _Clients:
    """Per-connection authenticated clients, built lazily through the factory and kept
    for the life of this object (a sync pass, a sender pass, a UI process)."""

    def __init__(self, factory: ClientFactory) -> None:
        self._factory = factory
        self._clients: dict[UUID, AuthenticatedClient] = {}

    async def get(self, connection: SourceConnection) -> AuthenticatedClient:
        client = self._clients.get(connection.connection_id)
        if client is None:
            client = await self._factory(connection.tenant_id, connection.connection_id)
            self._clients[connection.connection_id] = client
        return client

    def forget(self, connection_id: UUID) -> None:
        self._clients.pop(connection_id, None)


def _page_node(connection: SourceConnection) -> str:
    """The Messenger Platform addresses the Page (ADR 25: `linked_page_id` is NOT NULL on
    every Instagram connection; `me` is the fallback the docs also accept)."""
    return connection.linked_page_id or "me"


class InstagramDirectSource:
    def __init__(
        self,
        *,
        client_factory: ClientFactory,
        graph_url: str,
        scope_reader: ScopeReader | None = None,
        story_replies: bool = False,
    ) -> None:
        self._clients = _Clients(client_factory)
        self._graph_url = graph_url.rstrip("/")
        self._scopes = scope_reader
        # m-24789646: ask the messages edge for `story` only while the capability is on.
        self._message_fields = MESSAGE_FIELDS_WITH_STORY if story_replies else MESSAGE_FIELDS

    @property
    def channel(self) -> str:
        return CHANNEL_DM

    async def check_access(self, connection: SourceConnection) -> AccessVerdict:
        if self._scopes is not None:
            granted = self._scopes(connection.tenant_id, connection.connection_id)
            if not has_messages_scope(granted):
                return AccessVerdict(AccessStatus.PERMISSION_MISSING, "scope_not_granted")
        try:
            client = await self._clients.get(connection)
            response = await client.get(
                f"{self._graph_url}/{_page_node(connection)}/conversations",
                params={"platform": "instagram", "limit": 1},
                timeout=READ_TIMEOUT_S,
            )
        except InstagramDirectError as exc:
            return AccessVerdict(AccessStatus.ERROR, type(exc).__name__)
        except httpx.HTTPError as exc:
            return AccessVerdict(AccessStatus.ERROR, f"transport_{type(exc).__name__}")
        except Exception as exc:  # noqa: BLE001 — a credential that cannot be read, etc.
            logger.warning(
                "conversations.instagram.check_access connection=%s error=%s",
                connection.connection_id,
                type(exc).__name__,
            )
            return AccessVerdict(AccessStatus.ERROR, type(exc).__name__)
        if response.status_code == 200:
            return AccessVerdict(AccessStatus.OK)
        error = _failed("probe", response)
        if error.is_auth_error:
            self._clients.forget(connection.connection_id)
            return AccessVerdict(AccessStatus.AUTH_EXPIRED, error.access_detail())
        if error.is_permission_error:
            return AccessVerdict(AccessStatus.PERMISSION_MISSING, error.access_detail())
        return AccessVerdict(AccessStatus.ERROR, error.access_detail())

    async def list_conversations(
        self, connection: SourceConnection, *, cursor: str | None = None
    ) -> Page[RemoteConversation]:
        params: dict[str, Any] = {"platform": "instagram", "fields": CONVERSATION_FIELDS}
        if cursor:
            params["after"] = cursor
        what = "GET /{page-id}/conversations"
        try:
            client = await self._clients.get(connection)
            response = await client.get(
                f"{self._graph_url}/{_page_node(connection)}/conversations",
                params=params,
                timeout=READ_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            raise _transport(what, exc) from exc
        if response.status_code != 200:
            raise _failed(what, response)
        return parse_conversations_page(
            dict(response.json()), own_account_id=connection.external_account_id
        )

    async def list_messages(
        self,
        connection: SourceConnection,
        conversation: RemoteConversation,
        *,
        cursor: str | None = None,
    ) -> Page[RemoteMessage]:
        if not conversation.external_conversation_id:
            return Page(items=())
        params: dict[str, Any] = {"fields": self._message_fields, "limit": MESSAGES_PAGE_LIMIT}
        if cursor:
            params["after"] = cursor
        what = "GET /{conversation-id}/messages"
        try:
            client = await self._clients.get(connection)
            response = await client.get(
                f"{self._graph_url}/{conversation.external_conversation_id}/messages",
                params=params,
                timeout=READ_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            raise _transport(what, exc) from exc
        if response.status_code != 200:
            raise _failed(what, response)
        page = parse_messages_page(
            dict(response.json()), own_account_id=connection.external_account_id
        )
        # Only the newest ~20 carry details; following the cursor past them returns
        # "deleted" errors. One page is the reconciliation's horizon.
        return Page(items=page.items, next_cursor=None)

    async def fetch_profile(
        self, connection: SourceConnection, counterpart_external_id: str
    ) -> RemoteProfile | None:
        """User Profile API (`features/user-profile.md`): `GET /{IGSID}?fields=name,
        username,profile_pic`, Page token. Consent is implicit in the person having
        messaged the business; a blocked business or any error answers `None`."""
        try:
            client = await self._clients.get(connection)
            response = await client.get(
                f"{self._graph_url}/{counterpart_external_id}",
                params={"fields": PROFILE_FIELDS},
                timeout=READ_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001 — decoration, never a failure of the sync
            logger.info(
                "conversations.instagram.profile connection=%s error=%s",
                connection.connection_id,
                type(exc).__name__,
            )
            return None
        if response.status_code != 200:
            error = _failed("GET /{igsid}", response)
            if error.is_auth_error:
                self._clients.forget(connection.connection_id)
            logger.info(
                "conversations.instagram.profile connection=%s %s",
                connection.connection_id,
                error.access_detail(),
            )
            return None
        return parse_profile(dict(response.json()))


class InstagramDirectSender:
    def __init__(self, *, client_factory: ClientFactory, graph_url: str) -> None:
        self._clients = _Clients(client_factory)
        self._graph_url = graph_url.rstrip("/")

    @property
    def channel(self) -> str:
        return CHANNEL_DM

    def build_payload(
        self,
        *,
        recipient_external_id: str,
        text: str,
        quick_replies: Sequence[QuickReply] | None = None,
    ) -> dict[str, Any]:
        """`send-message.md`: one text message. With `quick_replies`
        (`features/quick-replies.md`, m-24789472) they ride in `message.quick_replies`,
        validated by `interactive.clean_quick_replies` (≤ 13, titles 1–20 characters,
        unique; default payload `QR_<slug>`) — `InteractiveMessageError` otherwise."""
        if not recipient_external_id:
            raise ValueError("a recipient is required")
        body = text.strip()
        if not body:
            raise ValueError("an empty message cannot be sent")
        if len(body.encode("utf-8")) > 1000:
            raise ValueError("a message is at most 1000 UTF-8 bytes")
        message: dict[str, Any] = {"text": body}
        replies = clean_quick_replies(quick_replies or ())
        if replies:
            message["quick_replies"] = quick_replies_wire(replies)
        return {"recipient": {"id": recipient_external_id}, "message": message}

    def build_button_template_payload(
        self, *, recipient_external_id: str, text: str, buttons: Sequence[TemplateButton]
    ) -> dict[str, Any]:
        """`button-template.md` (m-24789472): a text of 1–640 characters with 1–3
        `postback` (`QFB_…` payload) or `web_url` (https) buttons, as ONE message — never
        split. `InteractiveMessageError` (Spanish) for anything the channel would refuse."""
        if not recipient_external_id:
            raise ValueError("a recipient is required")
        return {
            "recipient": {"id": recipient_external_id},
            "message": button_template_message(text, buttons),
        }

    def build_private_reply_payload(self, *, comment_id: str, text: str) -> dict[str, Any]:
        """`features/private-replies.md`: `POST /{page-id}/messages` with the COMMENT as
        recipient — the same endpoint and token as every DM, so `send` ships it unchanged.
        One message per comment, within 7 days of it (the outbox and the sender enforce
        both); the person sees it in Inbox, or in Requests if they do not follow the
        account."""
        if not comment_id:
            raise ValueError("a private reply needs the comment it answers")
        body = text.strip()
        if not body:
            raise ValueError("an empty message cannot be sent")
        if len(body.encode("utf-8")) > 1000:
            raise ValueError("a message is at most 1000 UTF-8 bytes")
        return {"recipient": {"comment_id": comment_id}, "message": {"text": body}}

    def build_media_payload(self, *, recipient_external_id: str, media_type: str) -> dict[str, Any]:
        """`send-message.md` («Send an image»): one `attachment` with `type` and a
        `payload.url` Meta fetches. The URL is NOT here — `with_media_url` adds it at send
        time, because the public link Qualify mints is short-lived (QUA-68)."""
        if not recipient_external_id:
            raise ValueError("a recipient is required")
        if media_type not in REPLY_MEDIA_TYPES:
            raise ValueError(f"media_type {media_type!r} is not one of {REPLY_MEDIA_TYPES}")
        wire_type = WIRE_ATTACHMENT_TYPES.get(media_type, media_type)
        return {
            "recipient": {"id": recipient_external_id},
            "message": {"attachment": {"type": wire_type, "payload": {}}},
        }

    def build_sticker_payload(self, *, recipient_external_id: str, sticker: str) -> dict[str, Any]:
        """`send-message.md` («Send a heart sticker»): `attachment.type = like_heart`,
        no payload at all."""
        if not recipient_external_id:
            raise ValueError("a recipient is required")
        if sticker not in REPLY_STICKERS:
            raise ValueError(f"sticker {sticker!r} is not one of {REPLY_STICKERS}")
        return {
            "recipient": {"id": recipient_external_id},
            "message": {"attachment": {"type": sticker}},
        }

    def with_media_url(self, payload: Mapping[str, Any], url: str) -> dict[str, Any]:
        body = copy.deepcopy(dict(payload))
        message = body.get("message")
        attachment = message.get("attachment") if isinstance(message, Mapping) else None
        if not isinstance(attachment, dict):
            raise ValueError("payload carries no attachment to put a URL on")
        attachment["payload"] = {"url": url}
        return body

    async def _post_messages(
        self, connection: SourceConnection, body: Mapping[str, Any], what: str
    ) -> httpx.Response:
        try:
            client = await self._clients.get(connection)
            response = await client.post(
                f"{self._graph_url}/{_page_node(connection)}/messages",
                json=dict(body),
                timeout=SEND_TIMEOUT_S,
            )
        except httpx.HTTPError as exc:
            raise _transport(what, exc) from exc
        if response.status_code != 200:
            error = _failed(what, response)
            if error.is_auth_error:
                self._clients.forget(connection.connection_id)
            raise error
        return response

    async def send(self, connection: SourceConnection, payload: Mapping[str, Any]) -> SendResult:
        response = await self._post_messages(connection, payload, "POST /{page-id}/messages")
        return parse_send_response(dict(response.json()))

    async def send_action(
        self, connection: SourceConnection, *, recipient_external_id: str, action: str
    ) -> None:
        """`sender-actions.md`: `mark_seen` / `typing_on` / `typing_off`, only `recipient`
        and `sender_action` in the body. Shown only while the person is signed in."""
        if action not in SENDER_ACTIONS:
            raise ValueError(f"unknown sender action {action!r}")
        body = {"recipient": {"id": recipient_external_id}, "sender_action": action}
        await self._post_messages(connection, body, f"POST /{{page-id}}/messages ({action})")


__all__ = [
    "CONVERSATION_FIELDS",
    "MESSAGES_PAGE_LIMIT",
    "MESSAGES_SCOPE_LITERALS",
    "MESSAGE_FIELDS",
    "MESSAGE_FIELDS_WITH_STORY",
    "SHAPE_VERSION_IG_DM",
    "ClientFactory",
    "InstagramDirectError",
    "InstagramDirectSender",
    "InstagramDirectSource",
    "ScopeReader",
    "has_messages_scope",
    "parse_conversations_page",
    "parse_graph_time",
    "parse_messages_page",
    "parse_send_response",
]
