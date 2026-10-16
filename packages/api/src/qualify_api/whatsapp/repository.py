"""The inbound handler's writes (WA-07) — `qualify_webhook_worker` only.

Everything here runs in the intake PROCESSOR, through `webhook_worker_session()`. That
door is tenant-blind (BYPASSRLS), so what bounds it is the GRANT set migration 0057 gave
the role, and this module uses exactly that set and nothing more:

| table | used as |
|---|---|
| `threads` | SELECT/INSERT/UPDATE — `upsert_thread` |
| `messages` | SELECT/INSERT/UPDATE — `insert_inbound_message` (+ 0061 media), `apply_status` |
| `whatsapp_thread_state` | SELECT/INSERT/UPDATE — `get_thread_state`, `save_thread_state` |
| `whatsapp_outbox` | INSERT only — `enqueue_outbox` (id minted in Python, no `RETURNING`) |

Every row written carries the `tenant_id` the resolver derived from `phone_number_id`
(`whatsapp/resolve.py`); the composite FKs of 0004/0057 make a row whose tenant disagrees
with its connection or thread unbuildable, which is the only tenant check a BYPASSRLS
role gets.

**Idempotency** rests on two natural keys, both enforced at INSERT time:

- `uq_thread_natural_key (connection_id, channel, external_thread_id)` — one thread per
  `(number, wa_id)`; a replay only moves `last_inbound_at`/`last_message_at` forward
  (`GREATEST`) and reopens a closed thread.
- `uq_message_external_id (connection_id, external_message_id)` — one row per `wamid`;
  `insert_inbound_message` returns `False` on the duplicate so the handler can skip the
  menu step for a message it already answered.

`apply_status` is monotonic: `sent < delivered < read`, with `failed` terminal, so the
`delivered` and `read` receipts Meta may deliver in either order never regress the row.
A status for a `wamid` this connection has no row for (the outbound row is WA-08's to
create) updates nothing and returns `False`.

`save_thread_state` never un-pauses: `automation_paused_at` is `COALESCE(stored, new)`,
so a person who took the thread over between the handler's read and its write keeps it.
`paused_by_user_id` is never written here — it is the UI's column (WA-10).

One transaction per call, as `WebhookQueue` does. The handler therefore persists the
inbound message BEFORE it steps the menu, so a crash in between loses at most one
automated reply, never a message — and the replay is harmless because the duplicate
insert short-circuits the step (see `handler.py`).

`MemoryWhatsAppInboxRepository` mirrors every rule above for offline tests.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import text
from sqlalchemy.orm import Session

from qualify_api.whatsapp.models import DELIVERY_STATUSES, OUTBOX_KINDS

CHANNEL_WHATSAPP = "whatsapp"
DIRECTION_INBOUND = "inbound"
THREAD_OPEN = "open"
OUTBOX_KIND_AUTOMATION = "automation"

# `sent < delivered < read`; `failed` is terminal. Equal rank re-applies (harmless).
_STATUS_RANK: dict[str, int] = {"sent": 1, "delivered": 2, "read": 3, "failed": 4}

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class ThreadUpsert:
    thread_id: UUID
    created: bool  # True = this call inserted the thread (the first message ever)


@dataclass(frozen=True)
class StoredThreadState:
    """One `whatsapp_thread_state` row as the worker sees it. `context` is the engine's
    JSON-serializable context (plus the handler's reserved keys — see `handler.py`);
    `paused_at` non-`None` means automation is off for this thread, whoever paused it."""

    menu_version_id: UUID | None = None
    node_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    paused_at: datetime | None = None
    # 0058: the engine's consecutive-unknown-input counter, its own column.
    attempts: int = 0


class WhatsAppInboxRepository(Protocol):
    def upsert_thread(
        self, *, tenant_id: UUID, connection_id: UUID, wa_id: str, inbound_at: datetime
    ) -> ThreadUpsert: ...

    def insert_inbound_message(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        connection_id: UUID,
        external_message_id: str,
        author_external_id: str,
        author_username: str | None,
        text: str | None,
        posted_at: datetime | None,
        shape_version: str,
        media_type: str | None = None,
        media_id: str | None = None,
        media_mime: str | None = None,
    ) -> bool: ...

    def apply_status(
        self,
        *,
        connection_id: UUID,
        external_message_id: str,
        status: str,
        error_code: str | None,
    ) -> bool: ...

    def get_thread_state(self, thread_id: UUID) -> StoredThreadState | None: ...

    def save_thread_state(
        self, *, thread_id: UUID, tenant_id: UUID, state: StoredThreadState
    ) -> None: ...

    def enqueue_outbox(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID | None,
        kind: str,
        payload: dict[str, Any],
    ) -> UUID: ...


def _check_status(status: str) -> None:
    if status not in DELIVERY_STATUSES:
        raise ValueError(f"delivery status {status!r} is not one of {DELIVERY_STATUSES}")


def _check_kind(kind: str) -> None:
    if kind not in OUTBOX_KINDS:
        raise ValueError(f"outbox kind {kind!r} is not one of {OUTBOX_KINDS}")


# --- Postgres --------------------------------------------------------------------------

# `xmax = 0` is true only for a row this statement inserted — the standard way to tell an
# INSERT from the DO UPDATE branch without a second round trip.
_UPSERT_THREAD = text(
    """
    INSERT INTO threads (id, tenant_id, connection_id, channel, external_thread_id, status,
                         last_message_at, last_inbound_at)
    VALUES (:id, :tenant_id, :connection_id, :channel, :wa_id, :open, :at, :at)
    ON CONFLICT (connection_id, channel, external_thread_id) DO UPDATE
       SET status = :open,
           last_inbound_at = GREATEST(threads.last_inbound_at, EXCLUDED.last_inbound_at),
           last_message_at = GREATEST(threads.last_message_at, EXCLUDED.last_message_at)
    RETURNING id, (xmax = 0) AS created
    """
)

_INSERT_MESSAGE = text(
    """
    INSERT INTO messages (id, tenant_id, thread_id, connection_id, external_message_id,
                          direction, author_external_id, author_username, text, posted_at,
                          shape_version, media_type, media_id, media_mime)
    VALUES (:id, :tenant_id, :thread_id, :connection_id, :external_message_id, :direction,
            :author_external_id, :author_username, :text, :posted_at, :shape_version,
            :media_type, :media_id, :media_mime)
    ON CONFLICT (connection_id, external_message_id) DO NOTHING
    """
)

_APPLY_STATUS = text(
    """
    UPDATE messages
       SET delivery_status = :status,
           delivery_error_code = COALESCE(:error_code, delivery_error_code)
     WHERE connection_id = :connection_id
       AND external_message_id = :external_message_id
       AND (delivery_status IS NULL
            OR CASE delivery_status
                   WHEN 'sent' THEN 1 WHEN 'delivered' THEN 2
                   WHEN 'read' THEN 3 WHEN 'failed' THEN 4
               END <= :rank)
    """
)

_GET_STATE = text(
    """
    SELECT menu_version_id, node_id, context, attempts, automation_paused_at
      FROM whatsapp_thread_state
     WHERE thread_id = :thread_id
    """
)

_SAVE_STATE = text(
    """
    INSERT INTO whatsapp_thread_state (thread_id, tenant_id, menu_version_id, node_id,
                                       context, attempts, automation_paused_at, updated_at)
    VALUES (:thread_id, :tenant_id, :menu_version_id, :node_id, CAST(:context AS jsonb),
            :attempts, :paused_at, now())
    ON CONFLICT (thread_id) DO UPDATE
       SET menu_version_id = EXCLUDED.menu_version_id,
           node_id = EXCLUDED.node_id,
           context = EXCLUDED.context,
           attempts = EXCLUDED.attempts,
           automation_paused_at = COALESCE(whatsapp_thread_state.automation_paused_at,
                                           EXCLUDED.automation_paused_at),
           updated_at = now()
    """
)

_ENQUEUE_OUTBOX = text(
    """
    INSERT INTO whatsapp_outbox (id, tenant_id, connection_id, thread_id, kind, payload)
    VALUES (:id, :tenant_id, :connection_id, :thread_id, :kind, CAST(:payload AS jsonb))
    """
)


class PostgresWhatsAppInboxRepository:
    """The real thing. `session_factory` defaults to the `qualify_webhook_worker` door;
    tests may pass it explicitly."""

    def __init__(self, session_factory: SessionFactory = webhook_worker_session) -> None:
        self._session = session_factory

    def upsert_thread(
        self, *, tenant_id: UUID, connection_id: UUID, wa_id: str, inbound_at: datetime
    ) -> ThreadUpsert:
        with self._session() as session:
            row = session.execute(
                _UPSERT_THREAD,
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "connection_id": connection_id,
                    "channel": CHANNEL_WHATSAPP,
                    "wa_id": wa_id,
                    "open": THREAD_OPEN,
                    "at": inbound_at,
                },
            ).one()
        return ThreadUpsert(thread_id=row.id, created=bool(row.created))

    def insert_inbound_message(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        connection_id: UUID,
        external_message_id: str,
        author_external_id: str,
        author_username: str | None,
        text: str | None,
        posted_at: datetime | None,
        shape_version: str,
        media_type: str | None = None,
        media_id: str | None = None,
        media_mime: str | None = None,
    ) -> bool:
        with self._session() as session:
            inserted = session.execute(
                _INSERT_MESSAGE,
                {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "thread_id": thread_id,
                    "connection_id": connection_id,
                    "external_message_id": external_message_id,
                    "direction": DIRECTION_INBOUND,
                    "author_external_id": author_external_id,
                    "author_username": author_username,
                    "text": text,
                    "posted_at": posted_at,
                    "shape_version": shape_version,
                    "media_type": media_type,
                    "media_id": media_id,
                    "media_mime": media_mime,
                },
            ).rowcount
        return inserted == 1

    def apply_status(
        self,
        *,
        connection_id: UUID,
        external_message_id: str,
        status: str,
        error_code: str | None,
    ) -> bool:
        _check_status(status)
        with self._session() as session:
            updated = session.execute(
                _APPLY_STATUS,
                {
                    "status": status,
                    "error_code": error_code,
                    "connection_id": connection_id,
                    "external_message_id": external_message_id,
                    "rank": _STATUS_RANK[status],
                },
            ).rowcount
        return updated == 1

    def get_thread_state(self, thread_id: UUID) -> StoredThreadState | None:
        with self._session() as session:
            row = session.execute(_GET_STATE, {"thread_id": thread_id}).one_or_none()
        if row is None:
            return None
        return StoredThreadState(
            menu_version_id=row.menu_version_id,
            node_id=row.node_id,
            context=dict(row.context or {}),
            paused_at=row.automation_paused_at,
            attempts=int(row.attempts),
        )

    def save_thread_state(
        self, *, thread_id: UUID, tenant_id: UUID, state: StoredThreadState
    ) -> None:
        with self._session() as session:
            session.execute(
                _SAVE_STATE,
                {
                    "thread_id": thread_id,
                    "tenant_id": tenant_id,
                    "menu_version_id": state.menu_version_id,
                    "node_id": state.node_id,
                    "context": json.dumps(state.context, ensure_ascii=False),
                    "attempts": state.attempts,
                    "paused_at": state.paused_at,
                },
            )

    def enqueue_outbox(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID | None,
        kind: str,
        payload: dict[str, Any],
    ) -> UUID:
        _check_kind(kind)
        outbox_id = uuid4()
        with self._session() as session:
            session.execute(
                _ENQUEUE_OUTBOX,
                {
                    "id": outbox_id,
                    "tenant_id": tenant_id,
                    "connection_id": connection_id,
                    "thread_id": thread_id,
                    "kind": kind,
                    "payload": json.dumps(payload, ensure_ascii=False),
                },
            )
        return outbox_id


# --- In memory -------------------------------------------------------------------------


def _later(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


class MemoryWhatsAppInboxRepository:
    """Same contract, in dicts. Rows are plain dicts keyed the way the UNIQUE constraints
    key them, so a test reads them back as `repo.threads` / `repo.messages` /
    `repo.states` / `repo.outbox`."""

    def __init__(self) -> None:
        self.threads: dict[tuple[UUID, str, str], dict[str, Any]] = {}
        self.messages: dict[tuple[UUID, str], dict[str, Any]] = {}
        self.states: dict[UUID, tuple[UUID, StoredThreadState]] = {}
        self.outbox: list[dict[str, Any]] = []

    def upsert_thread(
        self, *, tenant_id: UUID, connection_id: UUID, wa_id: str, inbound_at: datetime
    ) -> ThreadUpsert:
        key = (connection_id, CHANNEL_WHATSAPP, wa_id)
        row = self.threads.get(key)
        if row is None:
            row = {
                "id": uuid4(),
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "channel": CHANNEL_WHATSAPP,
                "external_thread_id": wa_id,
                "status": THREAD_OPEN,
                "last_message_at": inbound_at,
                "last_inbound_at": inbound_at,
            }
            self.threads[key] = row
            return ThreadUpsert(thread_id=row["id"], created=True)
        row["status"] = THREAD_OPEN
        row["last_inbound_at"] = _later(row["last_inbound_at"], inbound_at)
        row["last_message_at"] = _later(row["last_message_at"], inbound_at)
        return ThreadUpsert(thread_id=row["id"], created=False)

    def insert_inbound_message(
        self,
        *,
        tenant_id: UUID,
        thread_id: UUID,
        connection_id: UUID,
        external_message_id: str,
        author_external_id: str,
        author_username: str | None,
        text: str | None,
        posted_at: datetime | None,
        shape_version: str,
        media_type: str | None = None,
        media_id: str | None = None,
        media_mime: str | None = None,
    ) -> bool:
        key = (connection_id, external_message_id)
        if key in self.messages:
            return False
        self.messages[key] = {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "thread_id": thread_id,
            "connection_id": connection_id,
            "external_message_id": external_message_id,
            "direction": DIRECTION_INBOUND,
            "author_external_id": author_external_id,
            "author_username": author_username,
            "text": text,
            "posted_at": posted_at,
            "shape_version": shape_version,
            "delivery_status": None,
            "delivery_error_code": None,
            "media_type": media_type,
            "media_id": media_id,
            "media_mime": media_mime,
        }
        return True

    def seed_outbound_message(
        self, *, tenant_id: UUID, thread_id: UUID, connection_id: UUID, wamid: str
    ) -> None:
        """What WA-08 will write once Meta accepts a send — so a test can watch a
        receipt land on it."""
        self.messages[(connection_id, wamid)] = {
            "id": uuid4(),
            "tenant_id": tenant_id,
            "thread_id": thread_id,
            "connection_id": connection_id,
            "external_message_id": wamid,
            "direction": "outbound",
            "author_external_id": None,
            "author_username": None,
            "text": None,
            "posted_at": None,
            "shape_version": "test",
            "delivery_status": None,
            "delivery_error_code": None,
        }

    def apply_status(
        self,
        *,
        connection_id: UUID,
        external_message_id: str,
        status: str,
        error_code: str | None,
    ) -> bool:
        _check_status(status)
        row = self.messages.get((connection_id, external_message_id))
        if row is None:
            return False
        current = row["delivery_status"]
        if current is not None and _STATUS_RANK[current] > _STATUS_RANK[status]:
            return False
        row["delivery_status"] = status
        if error_code is not None:
            row["delivery_error_code"] = error_code
        return True

    def get_thread_state(self, thread_id: UUID) -> StoredThreadState | None:
        entry = self.states.get(thread_id)
        if entry is None:
            return None
        _, state = entry
        return StoredThreadState(
            menu_version_id=state.menu_version_id,
            node_id=state.node_id,
            context=copy.deepcopy(state.context),
            paused_at=state.paused_at,
            attempts=state.attempts,
        )

    def save_thread_state(
        self, *, thread_id: UUID, tenant_id: UUID, state: StoredThreadState
    ) -> None:
        previous = self.states.get(thread_id)
        paused_at = state.paused_at
        if previous is not None and previous[1].paused_at is not None:
            paused_at = previous[1].paused_at
        self.states[thread_id] = (
            tenant_id,
            StoredThreadState(
                menu_version_id=state.menu_version_id,
                node_id=state.node_id,
                context=copy.deepcopy(state.context),
                paused_at=paused_at,
                attempts=state.attempts,
            ),
        )

    def enqueue_outbox(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        thread_id: UUID | None,
        kind: str,
        payload: dict[str, Any],
    ) -> UUID:
        _check_kind(kind)
        outbox_id = uuid4()
        self.outbox.append(
            {
                "id": outbox_id,
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "thread_id": thread_id,
                "kind": kind,
                "payload": copy.deepcopy(payload),
                "status": "pending",
            }
        )
        return outbox_id


__all__ = [
    "CHANNEL_WHATSAPP",
    "DIRECTION_INBOUND",
    "OUTBOX_KIND_AUTOMATION",
    "MemoryWhatsAppInboxRepository",
    "PostgresWhatsAppInboxRepository",
    "StoredThreadState",
    "ThreadUpsert",
    "WhatsAppInboxRepository",
]
