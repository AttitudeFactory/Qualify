"""«Ver en Instagram»: the publication's Instagram address on its attempt (m-25019220,
epic m-25019215; founder 2026-11-13).

`publish_attempts.permalink` (0159) is what «Tu semana» links to. Instagram only gives it
AFTER it accepted the publication, so it is read later with ONE `GET /{media-id}`
(`inbox.media_client.HttpMediaClient.get_media`, the fields the inbox already reads,
`permalink` among them) and written once: `UPDATE … WHERE permalink IS NULL`, which the
settled-row trigger accepts only for that change (0160).

## Where it runs

- **The calendar tick** (`planner.tick`, `fill_recent_permalinks`), per tenant, after the
  sweep — never in the publish request path, so the owner never waits for it. The
  production discovery visits a tenant with a permalink due (`tenants_missing_permalinks`).
- **The backfill** (`planner.publish_backfill`) for publications older than the tick's
  window — it reads the same media once for both the permalink and its picture.

## Bounded, without a schema change

- Read-only towards Meta: `GET` only. Every read is logged first in the connection's
  hourly budget (`inbox_meta_call_log`, 200/hour shared with the inbox — `LedgerBudget`),
  and the filler stops while fewer than `TICK_RESERVE` (150) remain: it never uses more
  than 50 of an hour, so Interacciones keeps its reads.
- At most `TICK_LIMIT` reads per tenant per tick.
- An unreadable media (deleted, a story past 24 h, a token without the scope) is not
  retried forever: an attempt is DUE only while the time since it settled falls inside
  one of `RETRY_BANDS` — every tick for its first 10 minutes, then three 3-minute bands
  (1 h, 6 h, 24 h). At the 60 s tick that is at most ~19 reads in its life, and after
  24 h 3 min it is never read again by the tick. No column is needed: the bands are a
  pure function of `settled_at` and the tick's `now`.

Only an `https://instagram.com/…` or `https://www.instagram.com/…` answer is stored; an
empty or any other answer stores nothing (`IGNORED`).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

import httpx
from qualify_shared.db.session import tenant_session
from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.orm import Session

from qualify_api.connections.models import SocialConnection
from qualify_api.inbox.media_client import MediaReadError, MediaSummary
from qualify_api.publishing.models import PublishAttempt

logger = logging.getLogger(__name__)

#: The attempt status of a publication Instagram accepted.
ATTEMPT_PUBLISHED = "published"
#: Reads per tenant per tick.
TICK_LIMIT = 10
#: Of the connection's 200 Graph reads per hour (shared with the inbox), the tick's filler
#: only uses the first 50: it stops once fewer than 150 remain for Interacciones.
TICK_RESERVE = 150
#: The founder's backfill may use up to 100 of the hour, leaving 100 to the inbox.
BACKFILL_RESERVE = 100
#: (from, to) after `settled_at` during which the tick reads a missing permalink.
RETRY_BANDS: tuple[tuple[timedelta, timedelta], ...] = (
    (timedelta(0), timedelta(minutes=10)),
    (timedelta(hours=1), timedelta(hours=1, minutes=3)),
    (timedelta(hours=6), timedelta(hours=6, minutes=3)),
    (timedelta(hours=24), timedelta(hours=24, minutes=3)),
)

_INSTAGRAM = re.compile(r"^https://(www\.)?instagram\.com/[^\s]+$")


def instagram_permalink(value: str | None) -> str | None:
    """`value` when it is an https Instagram address, else None."""
    if value and _INSTAGRAM.fullmatch(value.strip()):
        return value.strip()
    return None


class Outcome(StrEnum):
    FILLED = "filled"  # stored now
    ALREADY = "already"  # someone stored it first: nothing written
    IGNORED = "ignored"  # Instagram answered no usable address
    UNREADABLE = "unreadable"  # the media could not be read (deleted, story > 24 h…)
    NO_BUDGET = "no_budget"  # the connection's hourly budget is spent
    NO_READER = "no_reader"  # the connection could not be read (inactive, no token)


@dataclass(frozen=True)
class PermalinkTarget:
    attempt_id: UUID
    connection_id: UUID
    media_id: str


@dataclass(frozen=True)
class PermalinkResult:
    attempt_id: UUID
    outcome: Outcome


class MediaReader(Protocol):
    async def get_media(self, *, media_id: str) -> MediaSummary: ...


#: Builds the reader of ONE connection; raises when it cannot be read.
ReaderFactory = Callable[[UUID, UUID], Awaitable[MediaReader]]


class CallBudget(Protocol):
    def remaining(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> int: ...

    def spend(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> None: ...


class _CallLog(Protocol):
    def calls_in_last_hour(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> int: ...

    def record_call(self, *, tenant_id: UUID, connection_id: UUID, called_at: datetime) -> None: ...


class LedgerBudget:
    """The inbox's hourly ledger (`inbox_meta_call_log`, 0010), through `tenant_session`.

    `reserve` reads are left to the inbox: these callers stop once fewer than that remain
    of the connection's hour, so a burst of unreadable permalinks never starves
    Interacciones (`TICK_RESERVE` for the tick, `BACKFILL_RESERVE` for the backfill)."""

    def __init__(
        self, limit: int | None = None, *, reserve: int = 0, log: _CallLog | None = None
    ) -> None:
        from qualify_api.inbox.service import META_CALL_BUDGET_PER_HOUR  # noqa: PLC0415

        if log is None:
            from qualify_api.inbox.repository import PostgresInboxRepository  # noqa: PLC0415

            log = PostgresInboxRepository()
        self._repo = log
        self._limit = META_CALL_BUDGET_PER_HOUR if limit is None else limit
        self._reserve = reserve

    def remaining(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> int:
        used = self._repo.calls_in_last_hour(
            tenant_id=tenant_id, connection_id=connection_id, now=now
        )
        return max(0, self._limit - self._reserve - used)

    def spend(self, *, tenant_id: UUID, connection_id: UUID, now: datetime) -> None:
        self._repo.record_call(tenant_id=tenant_id, connection_id=connection_id, called_at=now)


async def read_media(
    target: PermalinkTarget,
    *,
    tenant_id: UUID,
    reader: MediaReader,
    budget: CallBudget,
    now: datetime,
) -> MediaSummary | Outcome:
    """ONE budgeted `GET /{media}`: the summary, or `NO_BUDGET` / `UNREADABLE`."""
    if budget.remaining(tenant_id=tenant_id, connection_id=target.connection_id, now=now) <= 0:
        return Outcome.NO_BUDGET
    budget.spend(tenant_id=tenant_id, connection_id=target.connection_id, now=now)
    try:
        return await reader.get_media(media_id=target.media_id)
    except (MediaReadError, httpx.HTTPError) as exc:
        logger.info(
            "planner.permalink_unreadable tenant_id=%s attempt_id=%s status=%s code=%s",
            tenant_id,
            target.attempt_id,
            getattr(exc, "http_status", None),
            getattr(exc, "platform_code", None),
        )
        return Outcome.UNREADABLE


def store_permalink(*, tenant_id: UUID, attempt_id: UUID, permalink: str | None) -> Outcome:
    """Write the address once (`WHERE permalink IS NULL`; 0160 lets a settled row take
    exactly this change). A non-Instagram or empty answer writes nothing."""
    clean = instagram_permalink(permalink)
    if clean is None:
        return Outcome.IGNORED
    with tenant_session(tenant_id) as session:
        result = session.execute(
            update(PublishAttempt)
            .where(PublishAttempt.id == attempt_id, PublishAttempt.permalink.is_(None))
            .values(permalink=clean)
            .execution_options(synchronize_session=False)
        )
        written = result.rowcount  # type: ignore[attr-defined]
    return Outcome.FILLED if written else Outcome.ALREADY


async def fill_permalinks(
    targets: list[PermalinkTarget],
    *,
    tenant_id: UUID,
    now: datetime,
    readers: ReaderFactory,
    budget: CallBudget,
) -> list[PermalinkResult]:
    """Read and store each target's permalink. One reader per connection; a connection
    that cannot be read costs only its own targets."""
    built: dict[UUID, MediaReader | None] = {}
    results: list[PermalinkResult] = []
    for target in targets:
        if target.connection_id not in built:
            try:
                built[target.connection_id] = await readers(tenant_id, target.connection_id)
            except Exception as exc:  # noqa: BLE001 — one connection never stops the rest
                logger.info(
                    "planner.permalink_no_reader tenant_id=%s connection_id=%s error=%s",
                    tenant_id,
                    target.connection_id,
                    type(exc).__name__,
                )
                built[target.connection_id] = None
        reader = built[target.connection_id]
        if reader is None:
            results.append(PermalinkResult(target.attempt_id, Outcome.NO_READER))
            continue
        read = await read_media(target, tenant_id=tenant_id, reader=reader, budget=budget, now=now)
        if isinstance(read, Outcome):
            results.append(PermalinkResult(target.attempt_id, read))
            continue
        outcome = store_permalink(
            tenant_id=tenant_id, attempt_id=target.attempt_id, permalink=read.permalink
        )
        results.append(PermalinkResult(target.attempt_id, outcome))
    return results


# -- what the tick reads --------------------------------------------------------------------


def _in_retry_band(now: datetime):  # noqa: ANN202 — a SQLAlchemy boolean clause
    return or_(
        *(
            and_(PublishAttempt.settled_at <= now - start, PublishAttempt.settled_at > now - end)
            for start, end in RETRY_BANDS
        )
    )


def _due(now: datetime) -> Select[tuple[UUID, UUID, str]]:
    """Published Instagram attempts with a media id and no permalink, inside a retry
    band, on a connection that exists, is active and is not being deleted."""
    return (
        select(PublishAttempt.id, PublishAttempt.connection_id, PublishAttempt.published_media_id)
        .join(
            SocialConnection,
            (SocialConnection.id == PublishAttempt.connection_id)
            & (SocialConnection.tenant_id == PublishAttempt.tenant_id),
        )
        .where(
            PublishAttempt.status == ATTEMPT_PUBLISHED,
            PublishAttempt.settled_at.is_not(None),
            PublishAttempt.permalink.is_(None),
            PublishAttempt.published_media_id.is_not(None),
            SocialConnection.platform == "instagram",
            SocialConnection.status == "active",
            SocialConnection.purge_started_at.is_(None),
            _in_retry_band(now),
        )
    )


def due_permalinks(session: Session, *, now: datetime, limit: int) -> list[PermalinkTarget]:
    """The tenant's due permalinks (caller's RLS session), newest first, at most `limit`."""
    rows = session.execute(_due(now).order_by(PublishAttempt.settled_at.desc()).limit(limit))
    return [PermalinkTarget(row[0], row[1], row[2]) for row in rows]


def tenants_missing_permalinks(session: Session, *, now: datetime) -> list[UUID]:
    """Ids of tenants with a due permalink — for the production discovery (admin
    session, ids only)."""
    return list(
        session.scalars(
            _due(now)
            .with_only_columns(PublishAttempt.tenant_id)
            .distinct()
            .order_by(PublishAttempt.tenant_id)
        ).all()
    )


async def production_reader(tenant_id: UUID, connection_id: UUID) -> MediaReader:
    """`HttpMediaClient` over this connection's stored credential — the same assembly as
    `inbox.composition.production_inbox_service_for`, GETs only. Refused (raises) for a
    connection that is not `active`."""
    from qualify_api.config import MetaOAuthSettings  # noqa: PLC0415
    from qualify_api.connections.credential_reader import DbCredentialReader  # noqa: PLC0415
    from qualify_api.connections.crypto import DevEncryptor  # noqa: PLC0415
    from qualify_api.connections.resolver import InjectingCredentialResolver  # noqa: PLC0415
    from qualify_api.inbox.media_client import HttpMediaClient  # noqa: PLC0415

    with tenant_session(tenant_id) as session:
        status = session.scalar(
            select(SocialConnection.status).where(SocialConnection.id == connection_id)
        )
    if status != "active":
        raise PermissionError(f"connection is {status or 'not visible'}, not active")
    settings = MetaOAuthSettings.from_env()
    resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), DevEncryptor())
    graph = await resolver.client_for(connection_id, scheme=settings.graph_auth_scheme)
    return HttpMediaClient(graph_client=graph, graph_url=settings.graph_url)


async def fill_recent_permalinks(
    *,
    tenant_id: UUID,
    now: datetime,
    readers: ReaderFactory | None = None,
    budget: CallBudget | None = None,
    limit: int = TICK_LIMIT,
) -> list[PermalinkResult]:
    """The tick's step: the tenant's due permalinks (`due_permalinks`), read and stored."""
    with tenant_session(tenant_id) as session:
        targets = due_permalinks(session, now=now, limit=limit)
    if not targets:
        return []
    return await fill_permalinks(
        targets,
        tenant_id=tenant_id,
        now=now,
        readers=readers or production_reader,
        budget=budget or LedgerBudget(reserve=TICK_RESERVE),
    )


__all__ = [
    "BACKFILL_RESERVE",
    "RETRY_BANDS",
    "TICK_LIMIT",
    "TICK_RESERVE",
    "CallBudget",
    "LedgerBudget",
    "MediaReader",
    "Outcome",
    "PermalinkResult",
    "PermalinkTarget",
    "ReaderFactory",
    "due_permalinks",
    "fill_permalinks",
    "fill_recent_permalinks",
    "instagram_permalink",
    "production_reader",
    "read_media",
    "store_permalink",
    "tenants_missing_permalinks",
]
