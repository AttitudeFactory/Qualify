"""The person-facing side of WhatsApp chats (WA-10, QUA-209): list conversations, read a
thread, answer it, and the four thread actions (assign, close/reopen, takeover/resume).

Backlog: `docs/backlog-modulo-whatsapp.md` §3 WA-10. Plan: `docs/plan-modulo-whatsapp-
cloud-api.md` §5.2 (the bandeja reuses `threads`/`messages`; the window is a policy).
The HTTP surface is `http/whatsapp_routes.py`; the UI that consumes it is WA-11.

## What this module decides, and what it delegates

- **The 24 h window** is `window.window_state` / `window.is_free_form_allowed` — this
  module never re-derives "24 h". A send outside the window raises `WindowClosed`
  (the route's 409) BEFORE anything is written.
- **The wire body** is the client's `build_text_body` / `build_media_body` /
  `build_buttons_body`, so Meta's limits (3 buttons, 20-char titles, 4096-char text, …)
  are validated in exactly one place; a violation surfaces as `ValueError` (the route's
  422).
- **Sending** is `OutboxRepository.enqueue(kind='reply')` (WA-08). Nothing is sent
  inline: the sender worker drains the queue, applies the window again (it may have
  closed while the row waited) and the per-recipient pacing.
- **Takeover**: a person's send pauses the menu automation on that thread
  (`whatsapp_thread_state.automation_paused_at` / `paused_by_user_id`) BEFORE the reply
  is queued, so the engine can never answer over the person. `resume` clears the pause,
  resets the cursor (`node_id = NULL`, `attempts = 0`) and keeps `context` (the order in
  progress survives a human interlude). The inbound handler's own `save_thread_state`
  never un-pauses (`COALESCE`), so only `resume` does.

## Tenancy

Every repository method takes `tenant_id`; the Postgres implementation runs each call in
`tenant_session(tenant_id)` (the `qualify_app` role), so RLS bounds every statement and
another tenant's thread reads as missing — the route answers 404, never 403, so a
caller cannot probe which ids exist. `assign` checks the agent is a `users` row visible
under the same RLS scope (1 login = 1 tenant, migration 0008), so a thread cannot be
assigned to another tenant's user.

## Known gaps (documented, not guessed)

- **Inbound media is not retrievable.** WA-07 stores `text = NULL` for a media message
  and persists neither its Meta `media_id` nor its type — there is no column for either
  (0004/0057/0058), and adding one is a migration this story must not ship. So
  `GET /api/whatsapp/media/{message_id}` goes through a `MediaLocator` whose production
  implementation (`NotCapturedMediaLocator`) always answers "not captured" (the route's
  501 `media_not_captured`). Closing the gap needs: a `messages.media_id`/`media_type`
  column (architect call), WA-07 writing it, and a locator that downloads lazily through
  `WhatsAppClient.get_media`/`download_media` into R2 keyed by `media_id`.
- **Inbound previews cannot name the media type** for the same reason: an inbound row
  with `text IS NULL` previews as «[mensaje]». Outbound rows CAN: the sender's
  `messages` row carries the `wamid`, and the `whatsapp_outbox` row that produced it
  holds the body, whose `type` gives «[imagen]» / «[audio]» / «[documento]».
- **Message paging** uses `before` = a timestamp (`posted_at`, falling back to
  `ingested_at` when Meta's timestamp was unparseable). Two messages with the exact same
  instant on a page boundary could be skipped; acceptable at a person's chat pace, and
  the fix (an `(instant, id)` cursor) does not change the response shape.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.whatsapp.client import (
    MAX_BUTTONS,
    ButtonSpec,
    build_buttons_body,
    build_media_body,
    build_text_body,
)
from qualify_api.whatsapp.outbox import OutboxRepository
from qualify_api.whatsapp.window import WINDOW, is_free_form_allowed, window_state

CHANNEL_WHATSAPP: Final = "whatsapp"
THREAD_STATUSES: Final = ("open", "closed")
DEFAULT_LIMIT: Final = 50
MAX_LIMIT: Final = 200
OUTBOX_KIND_REPLY: Final = "reply"

# Preview text for a message whose `text` is NULL, keyed by the body `type` of the
# outbox row that produced it (outbound only — module docstring).
MEDIA_PREVIEWS: Final[dict[str, str]] = {
    "image": "[imagen]",
    "audio": "[audio]",
    "document": "[documento]",
}
GENERIC_PREVIEW: Final = "[mensaje]"


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ======================================================================================
# Errors
# ======================================================================================


class ThreadNotFound(LookupError):
    """No WhatsApp thread with this id for this tenant (another tenant's thread included:
    RLS makes the two indistinguishable, and the route keeps it that way)."""


class UnknownAgent(ValueError):
    """`assign` named a user that is not a member of the caller's tenant."""


class WindowClosed(Exception):
    """A free-form reply was refused because the 24 h window is closed. `closes_at` is
    the instant it closed (`last_inbound_at + 24 h`), or `None` if the user never wrote —
    only an approved template can reach them now (WA-18)."""

    def __init__(self, closes_at: datetime | None) -> None:
        super().__init__("whatsapp 24 h window is closed")
        self.closes_at = closes_at


# ======================================================================================
# Send bodies (also the HTTP request body — one definition, discriminated by `type`)
# ======================================================================================


class _SendBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TextSend(_SendBase):
    type: Literal["text"] = "text"
    text: str = Field(min_length=1)


class ImageSend(_SendBase):
    """An image by public URL (Meta fetches it). Uploading a file first (`media_id`) is
    WA-11's composer concern; this API accepts the link form only."""

    type: Literal["image"] = "image"
    link: HttpUrl
    caption: str | None = None


class ReplyButton(_SendBase):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)


class ButtonsSend(_SendBase):
    type: Literal["buttons"] = "buttons"
    text: str = Field(min_length=1)
    buttons: list[ReplyButton] = Field(min_length=1, max_length=MAX_BUTTONS)


SendBody = Annotated[TextSend | ImageSend | ButtonsSend, Field(discriminator="type")]


def build_send_payload(body: TextSend | ImageSend | ButtonsSend, *, to: str) -> dict[str, Any]:
    """The `/messages` body for a person's send. Meta's limits are the client builders'
    to enforce (`ValueError`); Pydantic above only guarantees the shape."""
    if isinstance(body, TextSend):
        return build_text_body(to, body.text, False)
    if isinstance(body, ImageSend):
        return build_media_body(
            to, "image", media_id=None, link=str(body.link), caption=body.caption, filename=None
        )
    return build_buttons_body(
        to,
        body.text,
        [ButtonSpec(id=b.id, title=b.title) for b in body.buttons],
        None,
        None,
    )


# ======================================================================================
# Records (what the repository returns) and views (what the service returns)
# ======================================================================================


@dataclass(frozen=True)
class ThreadRef:
    """The minimum the service needs to act on a thread."""

    id: UUID
    connection_id: UUID
    wa_id: str
    status: str
    last_inbound_at: datetime | None


@dataclass(frozen=True)
class ThreadRecord:
    id: UUID
    connection_id: UUID
    wa_id: str
    status: str
    assigned_agent_id: UUID | None
    last_message_at: datetime | None
    last_inbound_at: datetime | None
    contact_name: str | None
    last_message_text: str | None
    last_message_media_kind: str | None
    last_message_direction: str | None
    unread_count: int
    automation_paused_at: datetime | None


@dataclass(frozen=True)
class MessageRecord:
    id: UUID
    direction: str
    text: str | None
    posted_at: datetime | None
    delivery_status: str | None
    delivery_error_code: str | None
    external_message_id: str
    # Body `type` of the outbox row that produced an outbound message (`image`, `text`,
    # `interactive`, …); always `None` for inbound (not persisted — module docstring).
    media_kind: str | None = None


@dataclass(frozen=True)
class WindowView:
    open: bool
    closes_at: datetime | None


@dataclass(frozen=True)
class ThreadSummary:
    id: UUID
    connection_id: UUID
    wa_id: str
    contact_name: str | None
    last_message_preview: str | None
    last_message_direction: str | None
    last_message_at: datetime | None
    last_inbound_at: datetime | None
    unread_count: int
    status: str
    assigned_agent_id: UUID | None
    automation_paused: bool
    window: WindowView


def message_preview(text_value: str | None, media_kind: str | None) -> str:
    """The one-line preview of a message: its text, else a bracketed type label."""
    if text_value:
        return text_value
    if media_kind is not None:
        return MEDIA_PREVIEWS.get(media_kind, GENERIC_PREVIEW)
    return GENERIC_PREVIEW


def _summarize(record: ThreadRecord, now: datetime) -> ThreadSummary:
    window = window_state(record.last_inbound_at, now)
    has_message = record.last_message_direction is not None
    return ThreadSummary(
        id=record.id,
        connection_id=record.connection_id,
        wa_id=record.wa_id,
        contact_name=record.contact_name,
        last_message_preview=(
            message_preview(record.last_message_text, record.last_message_media_kind)
            if has_message
            else None
        ),
        last_message_direction=record.last_message_direction,
        last_message_at=record.last_message_at,
        last_inbound_at=record.last_inbound_at,
        unread_count=record.unread_count,
        status=record.status,
        assigned_agent_id=record.assigned_agent_id,
        automation_paused=record.automation_paused_at is not None,
        window=WindowView(open=window.is_open, closes_at=window.closes_at),
    )


# ======================================================================================
# Repository seam
# ======================================================================================


class ChatRepository(Protocol):
    """Tenant-scoped reads and writes over `threads`/`messages`/`whatsapp_thread_state`
    (+ a read of `whatsapp_outbox` for outbound previews). Only `channel = 'whatsapp'`
    threads exist for this repository; an id of another channel reads as missing."""

    def list_threads(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID | None,
        status: str | None,
        limit: int,
        before: datetime | None,
        thread_id: UUID | None = None,
    ) -> list[ThreadRecord]:
        """Newest activity first (`last_message_at DESC NULLS LAST`); `before` pages on
        `last_message_at < before`; `thread_id` narrows to one (the action responses)."""
        ...

    def get_thread(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadRef | None: ...

    def list_messages(
        self, *, tenant_id: UUID, thread_id: UUID, before: datetime | None, limit: int
    ) -> list[MessageRecord]:
        """The newest `limit` messages strictly older than `before`, returned OLDEST
        first (chronological, the order a chat renders)."""
        ...

    def user_in_tenant(self, *, tenant_id: UUID, user_id: UUID) -> bool: ...

    def set_assignee(self, *, tenant_id: UUID, thread_id: UUID, agent_id: UUID | None) -> None: ...

    def set_status(self, *, tenant_id: UUID, thread_id: UUID, status: str) -> None: ...

    def pause_automation(
        self, *, tenant_id: UUID, thread_id: UUID, user_id: UUID, at: datetime
    ) -> None:
        """Upsert the thread state with `automation_paused_at = at`,
        `paused_by_user_id = user_id` (the latest person to take over owns the pause)."""
        ...

    def resume_automation(self, *, tenant_id: UUID, thread_id: UUID) -> None:
        """Clear the pause and the cursor (`node_id`, `attempts`); keep `context`."""
        ...


# --------------------------------------------------------------------------------------
# Postgres
# --------------------------------------------------------------------------------------

# A message's instant: Meta's timestamp, else when we stored it (WA-07 keeps `posted_at`
# NULL for an unparseable timestamp).
_INSTANT = "COALESCE({m}.posted_at, {m}.ingested_at)"

_LIST_THREADS = """
SELECT t.id, t.connection_id, t.external_thread_id AS wa_id, t.status, t.assigned_agent_id,
       t.last_message_at, t.last_inbound_at,
       s.automation_paused_at,
       (SELECT n.author_username
          FROM messages n
         WHERE n.thread_id = t.id AND n.direction = 'inbound'
           AND n.author_username IS NOT NULL AND n.deleted_at IS NULL
         ORDER BY {n_instant} DESC, n.id DESC
         LIMIT 1) AS contact_name,
       lm.text AS last_text, lm.direction AS last_direction, lm.media_kind AS last_media_kind,
       (SELECT count(*)
          FROM messages u
         WHERE u.thread_id = t.id AND u.direction = 'inbound' AND u.deleted_at IS NULL
           AND {u_instant} > COALESCE(
                 (SELECT max({o_instant})
                    FROM messages o
                   WHERE o.thread_id = t.id AND o.direction = 'outbound'
                     AND o.deleted_at IS NULL),
                 CAST('-infinity' AS timestamptz))) AS unread_count
  FROM threads t
  LEFT JOIN whatsapp_thread_state s ON s.thread_id = t.id
  LEFT JOIN LATERAL (
        SELECT m.text, m.direction, ob.payload->>'type' AS media_kind
          FROM messages m
          LEFT JOIN whatsapp_outbox ob
                 ON m.direction = 'outbound'
                AND ob.connection_id = m.connection_id
                AND ob.wamid = m.external_message_id
         WHERE m.thread_id = t.id AND m.deleted_at IS NULL
         ORDER BY {m_instant} DESC, m.id DESC
         LIMIT 1) lm ON true
 WHERE t.channel = 'whatsapp' {filters}
 ORDER BY t.last_message_at DESC NULLS LAST, t.id DESC
 LIMIT :limit
""".format(
    n_instant=_INSTANT.format(m="n"),
    u_instant=_INSTANT.format(m="u"),
    o_instant=_INSTANT.format(m="o"),
    m_instant=_INSTANT.format(m="m"),
    filters="{filters}",
)

_GET_THREAD = text(
    """
    SELECT id, connection_id, external_thread_id AS wa_id, status, last_inbound_at
      FROM threads
     WHERE id = :thread_id AND channel = 'whatsapp'
    """
)

_LIST_MESSAGES = """
SELECT * FROM (
    SELECT m.id, m.direction, m.text, {instant} AS posted_at, m.delivery_status,
           m.delivery_error_code, m.external_message_id,
           CASE WHEN m.direction = 'outbound' THEN ob.payload->>'type' END AS media_kind
      FROM messages m
      LEFT JOIN whatsapp_outbox ob
             ON m.direction = 'outbound'
            AND ob.connection_id = m.connection_id
            AND ob.wamid = m.external_message_id
     WHERE m.thread_id = :thread_id AND m.deleted_at IS NULL {before}
     ORDER BY {instant} DESC, m.id DESC
     LIMIT :limit
) page
ORDER BY posted_at ASC, id ASC
"""

_USER_IN_TENANT = text("SELECT 1 FROM users WHERE id = :user_id")

_SET_ASSIGNEE = text(
    "UPDATE threads SET assigned_agent_id = :agent_id "
    "WHERE id = :thread_id AND channel = 'whatsapp'"
)

_SET_STATUS = text(
    "UPDATE threads SET status = :status WHERE id = :thread_id AND channel = 'whatsapp'"
)

_PAUSE = text(
    """
    INSERT INTO whatsapp_thread_state (thread_id, tenant_id, automation_paused_at,
                                       paused_by_user_id, updated_at)
    VALUES (:thread_id, :tenant_id, :at, :user_id, now())
    ON CONFLICT (thread_id) DO UPDATE
       SET automation_paused_at = EXCLUDED.automation_paused_at,
           paused_by_user_id = EXCLUDED.paused_by_user_id,
           updated_at = now()
    """
)

_RESUME = text(
    """
    UPDATE whatsapp_thread_state
       SET automation_paused_at = NULL, paused_by_user_id = NULL, node_id = NULL,
           attempts = 0, updated_at = now()
     WHERE thread_id = :thread_id
    """
)


class PostgresChatRepository:
    """`tenant_session(tenant_id)` per call (`qualify_app`: SELECT/INSERT/UPDATE on
    `threads`, `messages`, `whatsapp_thread_state`, `whatsapp_outbox`; SELECT on `users`).

    The outbound-preview join `whatsapp_outbox (connection_id, wamid)` has no index of its
    own; at one number's volume the per-thread lateral is cheap, and that index is the
    one to add (architect call) when it is not."""

    def list_threads(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID | None,
        status: str | None,
        limit: int,
        before: datetime | None,
        thread_id: UUID | None = None,
    ) -> list[ThreadRecord]:
        filters: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if connection_id is not None:
            filters.append("AND t.connection_id = :connection_id")
            params["connection_id"] = connection_id
        if status is not None:
            filters.append("AND t.status = :status")
            params["status"] = status
        if before is not None:
            filters.append("AND t.last_message_at < :before")
            params["before"] = before
        if thread_id is not None:
            filters.append("AND t.id = :thread_id")
            params["thread_id"] = thread_id
        sql = text(_LIST_THREADS.replace("{filters}", " ".join(filters)))
        with tenant_session(tenant_id) as session:
            rows = session.execute(sql, params).all()
        return [
            ThreadRecord(
                id=r.id,
                connection_id=r.connection_id,
                wa_id=r.wa_id,
                status=r.status,
                assigned_agent_id=r.assigned_agent_id,
                last_message_at=r.last_message_at,
                last_inbound_at=r.last_inbound_at,
                contact_name=r.contact_name,
                last_message_text=r.last_text,
                last_message_media_kind=r.last_media_kind,
                last_message_direction=r.last_direction,
                unread_count=int(r.unread_count),
                automation_paused_at=r.automation_paused_at,
            )
            for r in rows
        ]

    def get_thread(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadRef | None:
        with tenant_session(tenant_id) as session:
            row = session.execute(_GET_THREAD, {"thread_id": thread_id}).one_or_none()
        if row is None:
            return None
        return ThreadRef(
            id=row.id,
            connection_id=row.connection_id,
            wa_id=row.wa_id,
            status=row.status,
            last_inbound_at=row.last_inbound_at,
        )

    def list_messages(
        self, *, tenant_id: UUID, thread_id: UUID, before: datetime | None, limit: int
    ) -> list[MessageRecord]:
        instant = _INSTANT.format(m="m")
        params: dict[str, Any] = {"thread_id": thread_id, "limit": limit}
        before_sql = ""
        if before is not None:
            before_sql = f"AND {instant} < :before"
            params["before"] = before
        sql = text(_LIST_MESSAGES.format(instant=instant, before=before_sql))
        with tenant_session(tenant_id) as session:
            rows = session.execute(sql, params).all()
        return [
            MessageRecord(
                id=r.id,
                direction=r.direction,
                text=r.text,
                posted_at=r.posted_at,
                delivery_status=r.delivery_status,
                delivery_error_code=r.delivery_error_code,
                external_message_id=r.external_message_id,
                media_kind=r.media_kind,
            )
            for r in rows
        ]

    def user_in_tenant(self, *, tenant_id: UUID, user_id: UUID) -> bool:
        with tenant_session(tenant_id) as session:
            return session.execute(_USER_IN_TENANT, {"user_id": user_id}).first() is not None

    def set_assignee(self, *, tenant_id: UUID, thread_id: UUID, agent_id: UUID | None) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(_SET_ASSIGNEE, {"thread_id": thread_id, "agent_id": agent_id})

    def set_status(self, *, tenant_id: UUID, thread_id: UUID, status: str) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(_SET_STATUS, {"thread_id": thread_id, "status": status})

    def pause_automation(
        self, *, tenant_id: UUID, thread_id: UUID, user_id: UUID, at: datetime
    ) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                _PAUSE,
                {"thread_id": thread_id, "tenant_id": tenant_id, "at": at, "user_id": user_id},
            )

    def resume_automation(self, *, tenant_id: UUID, thread_id: UUID) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(_RESUME, {"thread_id": thread_id})


# --------------------------------------------------------------------------------------
# In memory (tests)
# --------------------------------------------------------------------------------------


@dataclass
class MemoryThread:
    id: UUID
    tenant_id: UUID
    connection_id: UUID
    wa_id: str
    status: str = "open"
    assigned_agent_id: UUID | None = None
    last_message_at: datetime | None = None
    last_inbound_at: datetime | None = None
    channel: str = CHANNEL_WHATSAPP


@dataclass
class MemoryMessage:
    id: UUID
    tenant_id: UUID
    thread_id: UUID
    direction: str
    text: str | None
    posted_at: datetime
    external_message_id: str
    author_username: str | None = None
    delivery_status: str | None = None
    delivery_error_code: str | None = None
    media_kind: str | None = None
    deleted: bool = False


@dataclass
class MemoryThreadState:
    tenant_id: UUID
    node_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0
    automation_paused_at: datetime | None = None
    paused_by_user_id: UUID | None = None


class MemoryChatRepository:
    """Same contract in dicts, tenant-scoped the way RLS scopes Postgres: a row of another
    tenant is invisible, not forbidden. `add_thread` / `add_message` / `add_user` seed."""

    def __init__(self) -> None:
        self.threads: dict[UUID, MemoryThread] = {}
        self.messages: list[MemoryMessage] = []
        self.states: dict[UUID, MemoryThreadState] = {}
        self.users: set[tuple[UUID, UUID]] = set()  # (tenant_id, user_id)

    # --- seeding ---------------------------------------------------------------------

    def add_user(self, *, tenant_id: UUID, user_id: UUID) -> None:
        self.users.add((tenant_id, user_id))

    def add_thread(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        wa_id: str,
        last_inbound_at: datetime | None = None,
        status: str = "open",
        channel: str = CHANNEL_WHATSAPP,
    ) -> UUID:
        thread = MemoryThread(
            id=uuid4(),
            tenant_id=tenant_id,
            connection_id=connection_id,
            wa_id=wa_id,
            status=status,
            last_inbound_at=last_inbound_at,
            last_message_at=last_inbound_at,
            channel=channel,
        )
        self.threads[thread.id] = thread
        return thread.id

    def add_message(
        self,
        *,
        thread_id: UUID,
        direction: str,
        text_value: str | None,
        posted_at: datetime,
        author_username: str | None = None,
        media_kind: str | None = None,
        delivery_status: str | None = None,
    ) -> UUID:
        thread = self.threads[thread_id]
        message = MemoryMessage(
            id=uuid4(),
            tenant_id=thread.tenant_id,
            thread_id=thread_id,
            direction=direction,
            text=text_value,
            posted_at=posted_at,
            external_message_id=f"wamid.{uuid4().hex}",
            author_username=author_username,
            media_kind=media_kind,
            delivery_status=delivery_status,
        )
        self.messages.append(message)
        if thread.last_message_at is None or posted_at > thread.last_message_at:
            thread.last_message_at = posted_at
        if direction == "inbound" and (
            thread.last_inbound_at is None or posted_at > thread.last_inbound_at
        ):
            thread.last_inbound_at = posted_at
        return message.id

    # --- contract --------------------------------------------------------------------

    def _visible(self, tenant_id: UUID, thread_id: UUID) -> MemoryThread | None:
        thread = self.threads.get(thread_id)
        if thread is None or thread.tenant_id != tenant_id or thread.channel != CHANNEL_WHATSAPP:
            return None
        return thread

    def _thread_messages(self, thread_id: UUID) -> list[MemoryMessage]:
        rows = [m for m in self.messages if m.thread_id == thread_id and not m.deleted]
        return sorted(rows, key=lambda m: (m.posted_at, str(m.id)))

    def _record(self, thread: MemoryThread) -> ThreadRecord:
        rows = self._thread_messages(thread.id)
        last = rows[-1] if rows else None
        names = [m.author_username for m in rows if m.direction == "inbound" and m.author_username]
        last_out = max((m.posted_at for m in rows if m.direction == "outbound"), default=None)
        unread = sum(
            1
            for m in rows
            if m.direction == "inbound" and (last_out is None or m.posted_at > last_out)
        )
        state = self.states.get(thread.id)
        return ThreadRecord(
            id=thread.id,
            connection_id=thread.connection_id,
            wa_id=thread.wa_id,
            status=thread.status,
            assigned_agent_id=thread.assigned_agent_id,
            last_message_at=thread.last_message_at,
            last_inbound_at=thread.last_inbound_at,
            contact_name=names[-1] if names else None,
            last_message_text=last.text if last else None,
            last_message_media_kind=(
                last.media_kind if last and last.direction == "outbound" else None
            ),
            last_message_direction=last.direction if last else None,
            unread_count=unread,
            automation_paused_at=state.automation_paused_at if state else None,
        )

    def list_threads(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID | None,
        status: str | None,
        limit: int,
        before: datetime | None,
        thread_id: UUID | None = None,
    ) -> list[ThreadRecord]:
        threads = [
            t
            for t in self.threads.values()
            if t.tenant_id == tenant_id
            and t.channel == CHANNEL_WHATSAPP
            and (connection_id is None or t.connection_id == connection_id)
            and (status is None or t.status == status)
            and (thread_id is None or t.id == thread_id)
            and (before is None or (t.last_message_at is not None and t.last_message_at < before))
        ]
        threads.sort(key=lambda t: str(t.id), reverse=True)
        threads.sort(
            key=lambda t: (t.last_message_at is not None, t.last_message_at or datetime.min),
            reverse=True,
        )
        return [self._record(t) for t in threads[:limit]]

    def get_thread(self, *, tenant_id: UUID, thread_id: UUID) -> ThreadRef | None:
        thread = self._visible(tenant_id, thread_id)
        if thread is None:
            return None
        return ThreadRef(
            id=thread.id,
            connection_id=thread.connection_id,
            wa_id=thread.wa_id,
            status=thread.status,
            last_inbound_at=thread.last_inbound_at,
        )

    def list_messages(
        self, *, tenant_id: UUID, thread_id: UUID, before: datetime | None, limit: int
    ) -> list[MessageRecord]:
        if self._visible(tenant_id, thread_id) is None:
            return []
        rows = [
            m for m in self._thread_messages(thread_id) if before is None or m.posted_at < before
        ]
        return [
            MessageRecord(
                id=m.id,
                direction=m.direction,
                text=m.text,
                posted_at=m.posted_at,
                delivery_status=m.delivery_status,
                delivery_error_code=m.delivery_error_code,
                external_message_id=m.external_message_id,
                media_kind=m.media_kind if m.direction == "outbound" else None,
            )
            for m in rows[-limit:]
        ]

    def user_in_tenant(self, *, tenant_id: UUID, user_id: UUID) -> bool:
        return (tenant_id, user_id) in self.users

    def set_assignee(self, *, tenant_id: UUID, thread_id: UUID, agent_id: UUID | None) -> None:
        thread = self._visible(tenant_id, thread_id)
        if thread is not None:
            thread.assigned_agent_id = agent_id

    def set_status(self, *, tenant_id: UUID, thread_id: UUID, status: str) -> None:
        thread = self._visible(tenant_id, thread_id)
        if thread is not None:
            thread.status = status

    def pause_automation(
        self, *, tenant_id: UUID, thread_id: UUID, user_id: UUID, at: datetime
    ) -> None:
        if self._visible(tenant_id, thread_id) is None:
            return
        state = self.states.setdefault(thread_id, MemoryThreadState(tenant_id=tenant_id))
        state.automation_paused_at = at
        state.paused_by_user_id = user_id

    def resume_automation(self, *, tenant_id: UUID, thread_id: UUID) -> None:
        if self._visible(tenant_id, thread_id) is None:
            return
        state = self.states.get(thread_id)
        if state is None:
            return
        self.states[thread_id] = replace(
            state, automation_paused_at=None, paused_by_user_id=None, node_id=None, attempts=0
        )


# ======================================================================================
# Service
# ======================================================================================


def _clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_LIMIT))


class ChatService:
    """Every method takes the caller's `tenant_id` explicitly (from the `Principal`) and
    raises `ThreadNotFound` for a thread that tenant cannot see."""

    def __init__(
        self,
        repo: ChatRepository,
        outbox: OutboxRepository,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._repo = repo
        self._outbox = outbox
        self._clock = clock

    # --- reads -----------------------------------------------------------------------

    def list_threads(
        self,
        tenant_id: UUID,
        connection_id: UUID | None = None,
        status: str | None = None,
        limit: int = DEFAULT_LIMIT,
        before: datetime | None = None,
    ) -> list[ThreadSummary]:
        if status is not None and status not in THREAD_STATUSES:
            raise ValueError(f"status must be one of {THREAD_STATUSES}")
        now = self._clock()
        records = self._repo.list_threads(
            tenant_id=tenant_id,
            connection_id=connection_id,
            status=status,
            limit=_clamp_limit(limit),
            before=before,
        )
        return [_summarize(r, now) for r in records]

    def get_thread_summary(self, tenant_id: UUID, thread_id: UUID) -> ThreadSummary:
        records = self._repo.list_threads(
            tenant_id=tenant_id,
            connection_id=None,
            status=None,
            limit=1,
            before=None,
            thread_id=thread_id,
        )
        if not records:
            raise ThreadNotFound(str(thread_id))
        return _summarize(records[0], self._clock())

    def list_messages(
        self,
        tenant_id: UUID,
        thread_id: UUID,
        before: datetime | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> Sequence[MessageRecord]:
        self._thread(tenant_id, thread_id)
        return self._repo.list_messages(
            tenant_id=tenant_id, thread_id=thread_id, before=before, limit=_clamp_limit(limit)
        )

    # --- send ------------------------------------------------------------------------

    def send(
        self,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        body: TextSend | ImageSend | ButtonsSend,
    ) -> UUID:
        """Queue a person's reply; returns the `whatsapp_outbox` id. Order matters: the
        window is checked and the body built (both may refuse) before anything is
        written; then automation is paused, THEN the reply is queued — so the menu
        engine cannot answer over a person whose message is already in the queue."""
        thread = self._thread(tenant_id, thread_id)
        now = self._clock()
        window = window_state(thread.last_inbound_at, now)
        if not is_free_form_allowed(OUTBOX_KIND_REPLY, window):
            closed_at = thread.last_inbound_at + WINDOW if thread.last_inbound_at else None
            raise WindowClosed(closed_at)
        payload = build_send_payload(body, to=thread.wa_id)
        self._repo.pause_automation(
            tenant_id=tenant_id, thread_id=thread_id, user_id=user_id, at=now
        )
        return self._outbox.enqueue(
            tenant_id=tenant_id,
            connection_id=thread.connection_id,
            thread_id=thread_id,
            kind=OUTBOX_KIND_REPLY,
            payload=payload,
            created_by_user_id=user_id,
        )

    # --- actions ---------------------------------------------------------------------

    def assign(self, tenant_id: UUID, thread_id: UUID, agent_user_id: UUID | None) -> None:
        self._thread(tenant_id, thread_id)
        if agent_user_id is not None and not self._repo.user_in_tenant(
            tenant_id=tenant_id, user_id=agent_user_id
        ):
            raise UnknownAgent(str(agent_user_id))
        self._repo.set_assignee(tenant_id=tenant_id, thread_id=thread_id, agent_id=agent_user_id)

    def close(self, tenant_id: UUID, thread_id: UUID) -> None:
        self._thread(tenant_id, thread_id)
        self._repo.set_status(tenant_id=tenant_id, thread_id=thread_id, status="closed")

    def reopen(self, tenant_id: UUID, thread_id: UUID) -> None:
        self._thread(tenant_id, thread_id)
        self._repo.set_status(tenant_id=tenant_id, thread_id=thread_id, status="open")

    def takeover(self, tenant_id: UUID, thread_id: UUID, user_id: UUID) -> None:
        self._thread(tenant_id, thread_id)
        self._repo.pause_automation(
            tenant_id=tenant_id, thread_id=thread_id, user_id=user_id, at=self._clock()
        )

    def resume(self, tenant_id: UUID, thread_id: UUID) -> None:
        self._thread(tenant_id, thread_id)
        self._repo.resume_automation(tenant_id=tenant_id, thread_id=thread_id)

    def _thread(self, tenant_id: UUID, thread_id: UUID) -> ThreadRef:
        thread = self._repo.get_thread(tenant_id=tenant_id, thread_id=thread_id)
        if thread is None:
            raise ThreadNotFound(str(thread_id))
        return thread


# ======================================================================================
# Media (gap — module docstring)
# ======================================================================================


class MediaLocator(Protocol):
    """Where the bytes of an inbound media message can be fetched from: a URL the route
    redirects to, or `None` when the media was never captured."""

    def locate(self, *, tenant_id: UUID, message_id: UUID) -> str | None: ...


class NotCapturedMediaLocator:
    """Production today: WA-07 persists no `media_id`, so nothing can be located."""

    def locate(self, *, tenant_id: UUID, message_id: UUID) -> str | None:
        return None


def production_chat_service() -> ChatService:
    """Postgres repositories under `tenant_session` (the `qualify_app` role)."""
    from qualify_api.whatsapp.outbox import PostgresOutboxRepository  # noqa: PLC0415

    return ChatService(PostgresChatRepository(), PostgresOutboxRepository())


__all__ = [
    "ButtonsSend",
    "ChatRepository",
    "ChatService",
    "ImageSend",
    "MediaLocator",
    "MemoryChatRepository",
    "MessageRecord",
    "NotCapturedMediaLocator",
    "PostgresChatRepository",
    "ReplyButton",
    "SendBody",
    "TextSend",
    "ThreadNotFound",
    "ThreadRecord",
    "ThreadRef",
    "ThreadSummary",
    "UnknownAgent",
    "WindowClosed",
    "WindowView",
    "build_send_payload",
    "message_preview",
    "production_chat_service",
]
