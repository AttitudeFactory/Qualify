"""Mutual exclusion for the calendar executor (QUA-111): one process at a time per key.

`start_claimed` holds the lock of its EVENT for its whole critical section, so two
executors can never both decide what happens to the same claimed event — the one race
the publisher's own idempotency cannot close (one process failing an event it read as
unpublishable while another is already sending it to Meta). F4 reuses the same lock,
keyed by publish attempt, around `advance()`.

The Postgres implementation is a transaction-scoped advisory lock
(`pg_try_advisory_xact_lock`): non-blocking (a busy key is skipped, not waited on), and
released by Postgres itself when the transaction ends — normally, on error, or because
the process died and its connection went away. No table, no migration, no Redis. It is
taken inside `tenant_session`, the sanctioned door; an advisory lock touches no rows, so
RLS is irrelevant to it and the tenant only scopes the connection.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text


def event_lock_key(event_id: UUID) -> str:
    return f"qua111:calendar-event:{event_id}"


class ExecutionLock(Protocol):
    def hold(self, *, tenant_id: UUID, key: str) -> AbstractContextManager[bool]:
        """Try to take `key` without waiting. Yields True when this caller holds it (until
        the `with` block ends), False when someone else does — the caller must then do
        nothing."""
        ...


class PostgresAdvisoryLock:
    """`pg_try_advisory_xact_lock` over a 64-bit hash of the key, held by the
    transaction `tenant_session` opens for the duration of the `with` block."""

    @contextmanager
    def hold(self, *, tenant_id: UUID, key: str) -> Iterator[bool]:
        with tenant_session(tenant_id) as session:
            acquired = bool(
                session.execute(
                    text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": key},
                ).scalar_one()
            )
            yield acquired


class MemoryExecutionLock:
    """In-process stand-in with the same try-lock semantics, for unit tests."""

    def __init__(self) -> None:
        self._held: set[str] = set()
        self._guard = threading.Lock()

    def is_held(self, key: str) -> bool:
        return key in self._held

    @contextmanager
    def hold(self, *, tenant_id: UUID, key: str) -> Iterator[bool]:
        with self._guard:
            acquired = key not in self._held
            if acquired:
                self._held.add(key)
        try:
            yield acquired
        finally:
            if acquired:
                with self._guard:
                    self._held.discard(key)
