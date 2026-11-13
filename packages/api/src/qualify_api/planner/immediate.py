"""«Publicar» → «Tu semana» (m-25019217, epic m-25019215; founder 2026-11-13).

A publication made from «Publicar» (`/publish`, immediate) wrote only `publish_attempts`,
and the calendar reads only `calendar_events`. Once Instagram ACCEPTED it, this module
records it: one piece of the owner (`creative.own_media`, kind `own_media`, shown under
«Aprobados» and plannable again) and one calendar event, `published`, at the instant the
attempt settled, linked to the attempt.

## Entry points

- `record_publication(tenant_id=, attempt_id=, user_id=)` — what the app calls right after
  its poll reports the publication settled (`Qualify/publishing_provider.poll_publish`).
  One `tenant_session` transaction; idempotent; returns a `RecordResult`.
- `sweep_recent_publications(tenant_id=, now=)` — the backstop the calendar tick runs per
  tenant (`planner.tick`): attempts settled `published` in the last `SWEEP_WINDOW`, with
  no event and a key not starting with `cal:`, newest first, at most `SWEEP_LIMIT`.

## What is never done here

Assisted, never autonomous: nothing here starts, retries, advances or settles a
publication — it only reads attempts that ALREADY settled `published`. An attempt not
settled, settled `failed`, or started by the planner executor (`cal:{event}:{revision}`
keys, `rules.idempotency_key`: that event already exists) writes nothing. The event is
never created as `publishing` while the attempt is in flight: the worker would then drive
the same attempt as the browser (`record_publish_sent` is an unconditional write).

## Idempotency — two layers

1. The piece: `content_drafts.request_key = request_key_for(attempt_id)` (UUIDv5), unique
   per tenant (0070).
2. The event: partial UNIQUE `uq_cal_event_attempt (tenant_id, publish_attempt_id)` (0159)
   with `INSERT … ON CONFLICT DO NOTHING`.

Both are written in ONE transaction, behind a transaction-scoped advisory lock on the
attempt, so two concurrent callers (the app and the tick) serialize: the second finds the
event and returns `EXISTING`. Calling it twice leaves one piece and one event.

## Brand and author

The event and the piece belong to the connection's brand (`social_connections.brand_id`);
a connection with no brand records nothing (logged). The app passes the acting user; the
sweep has none, so it attributes the record to the tenant's owner (`_owner_of`) — the
person accountable for the account. Neither path changes who published: the attempt is
the source, traceable through `request_key` and `publish_attempt_id`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from qualify_creative.enums import ContentFormat, PostCategory
from qualify_shared.db.session import tenant_session
from sqlalchemy import Select, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from qualify_api.connections.models import SocialConnection
from qualify_api.creative.own_media import (
    OwnMediaItem,
    OwnMediaPiece,
    create_own_media_piece,
    request_key_for,
)
from qualify_api.planner.fsm import EventStatus
from qualify_api.planner.models import CalendarEvent
from qualify_api.planner.publishable import (
    DESTINATION_POST,
    DESTINATION_REEL,
    DESTINATION_STORY,
)
from qualify_api.publishing.client import (
    IMAGE_CONTENT_TYPE,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_REELS,
    MEDIA_TYPE_STORIES,
    MEDIA_TYPE_VIDEO,
)
from qualify_api.publishing.models import PublishAttempt, PublishAttemptChild
from qualify_api.publishing.service import MEDIA_TYPE_CAROUSEL
from qualify_api.tenancy.models import Tenant, TenantMember, User

logger = logging.getLogger(__name__)

#: How far back the tick's sweep looks for unrecorded publications.
SWEEP_WINDOW = timedelta(hours=48)
#: At most this many publications recorded per tenant per tick.
SWEEP_LIMIT = 50
#: The planner executor's attempts (`rules.idempotency_key`): their event already exists.
CALENDAR_KEY_PREFIX = "cal:"
#: The attempt status of a publication Instagram accepted (`publishing.repository`).
ATTEMPT_PUBLISHED = "published"
DEFAULT_TIMEZONE = "UTC"

_LOCK_NAMESPACE = "own_media:"


class Outcome(StrEnum):
    RECORDED = "recorded"  # piece + event written now
    EXISTING = "existing"  # already recorded: nothing written
    SKIPPED = "skipped"  # not a publication to record (see `Skip`)


class Skip(StrEnum):
    NOT_FOUND = "not_found"  # no such attempt in this tenant (RLS)
    CALENDAR_ATTEMPT = "calendar_attempt"  # the planner executor's (`cal:`)
    NOT_SETTLED = "not_settled"  # still in flight
    NOT_PUBLISHED = "not_published"  # settled, but not `published` (failed…)
    NO_MEDIA = "no_media"  # the staged object (or its type) is not recorded
    UNSUPPORTED_TYPE = "unsupported_type"  # a media product type this cannot map
    CONNECTION_GONE = "connection_gone"
    CONNECTION_PURGING = "connection_purging"  # its deletion started (0106 fence)
    NO_BRAND = "no_brand"  # the connection belongs to no brand
    NO_AUTHOR = "no_author"  # the sweep found no user to attribute it to


@dataclass(frozen=True)
class RecordResult:
    attempt_id: UUID
    outcome: Outcome
    skip: Skip | None = None
    draft_id: UUID | None = None
    event_id: UUID | None = None

    @property
    def recorded(self) -> bool:
        return self.outcome is Outcome.RECORDED


# -- the pure part --------------------------------------------------------------------------


@dataclass(frozen=True)
class AttemptFacts:
    """What the plan reads of one attempt — a snapshot, no session."""

    id: UUID
    idempotency_key: str
    status: str
    settled_at: datetime | None
    caption: str | None
    media_product_type: str
    media_object_key: str | None
    media_content_type: str | None


@dataclass(frozen=True)
class ChildFacts:
    """One item of a carousel attempt (`publish_attempt_children`)."""

    position: int
    media_object_key: str
    media_content_type: str
    media_product_type: str  # IMAGE / VIDEO


@dataclass(frozen=True)
class PublicationPlan:
    """What `record_publication` writes for one eligible attempt."""

    published_at: datetime
    caption: str
    category: PostCategory
    format: ContentFormat
    destination: str
    items: tuple[OwnMediaItem, ...]


def _media_type(content_type: str) -> str:
    return "image" if content_type.lower().startswith("image/") else "video"


def eligibility(attempt: AttemptFacts) -> Skip | None:
    """Why this attempt is not a publication to record, or None. Order: the executor's
    attempts first (never ours), then settled, then published."""
    if attempt.idempotency_key.startswith(CALENDAR_KEY_PREFIX):
        return Skip.CALENDAR_ATTEMPT
    if attempt.settled_at is None:
        return Skip.NOT_SETTLED
    if attempt.status != ATTEMPT_PUBLISHED:
        return Skip.NOT_PUBLISHED
    return None


def plan_publication(
    attempt: AttemptFacts, children: tuple[ChildFacts, ...] = ()
) -> PublicationPlan | Skip:
    """The piece and event for one attempt, or why there is none. Pure.

    IMAGE → one feed image (galería, «Publicación»); REELS (and a legacy VIDEO) → one
    video (reel); STORIES → one image or video (story); CAROUSEL → its children in
    `position` order (galería, «Publicación»)."""
    skip = eligibility(attempt)
    if skip is not None:
        return skip
    assert attempt.settled_at is not None  # eligibility() checked it
    kind = attempt.media_product_type
    caption = attempt.caption or ""
    if kind == MEDIA_TYPE_CAROUSEL:
        if not children:
            return Skip.NO_MEDIA
        ordered = sorted(children, key=lambda child: child.position)
        items = tuple(
            OwnMediaItem(
                object_key=child.media_object_key,
                content_type=child.media_content_type,
                media_type="image" if child.media_product_type == MEDIA_TYPE_IMAGE else "video",
                position=index,
            )
            for index, child in enumerate(ordered)
        )
        return PublicationPlan(
            attempt.settled_at,
            caption,
            PostCategory.GALERIA,
            ContentFormat.FEED_4_5,
            DESTINATION_POST,
            items,
        )
    if kind not in (MEDIA_TYPE_IMAGE, MEDIA_TYPE_REELS, MEDIA_TYPE_VIDEO, MEDIA_TYPE_STORIES):
        return Skip.UNSUPPORTED_TYPE
    if not attempt.media_object_key:
        return Skip.NO_MEDIA
    content_type = attempt.media_content_type
    if kind == MEDIA_TYPE_IMAGE:
        # «Publicar» stages images as JPEG only (`client.IMAGE_CONTENT_TYPE`)
        content_type = content_type or IMAGE_CONTENT_TYPE
    if not content_type:
        return Skip.NO_MEDIA
    item = (
        OwnMediaItem(
            object_key=attempt.media_object_key,
            content_type=content_type,
            media_type=_media_type(content_type),
            position=0,
        ),
    )
    if kind == MEDIA_TYPE_IMAGE:
        shape = (PostCategory.GALERIA, ContentFormat.FEED_4_5, DESTINATION_POST)
    elif kind == MEDIA_TYPE_STORIES:
        shape = (PostCategory.STORY, ContentFormat.STORY_9_16, DESTINATION_STORY)
    else:
        if item[0].media_type != "video":
            return Skip.UNSUPPORTED_TYPE
        shape = (PostCategory.REEL, ContentFormat.REELS_9_16, DESTINATION_REEL)
    category, fmt, destination = shape
    return PublicationPlan(attempt.settled_at, caption, category, fmt, destination, item)


# -- the database part ----------------------------------------------------------------------


def _facts(row: PublishAttempt) -> AttemptFacts:
    return AttemptFacts(
        id=row.id,
        idempotency_key=row.idempotency_key,
        status=row.status,
        settled_at=row.settled_at,
        caption=row.caption,
        media_product_type=row.media_product_type,
        media_object_key=row.media_object_key,
        media_content_type=row.media_content_type,
    )


def _children(session: Session, attempt_id: UUID) -> tuple[ChildFacts, ...]:
    rows = session.scalars(
        select(PublishAttemptChild)
        .where(PublishAttemptChild.attempt_id == attempt_id)
        .order_by(PublishAttemptChild.position)
    ).all()
    return tuple(
        ChildFacts(
            position=row.position,
            media_object_key=row.media_object_key,
            media_content_type=row.media_content_type,
            media_product_type=row.media_product_type,
        )
        for row in rows
    )


def _existing_event(session: Session, attempt_id: UUID) -> CalendarEvent | None:
    return session.scalar(
        select(CalendarEvent).where(CalendarEvent.publish_attempt_id == attempt_id).limit(1)
    )


def _timezone(session: Session, tenant_id: UUID) -> str:
    tenant = session.get(Tenant, tenant_id)
    return tenant.timezone if tenant is not None and tenant.timezone else DEFAULT_TIMEZONE


def _skipped(attempt_id: UUID, skip: Skip, *, tenant_id: UUID) -> RecordResult:
    log = logger.warning if skip in (Skip.NO_BRAND, Skip.NO_MEDIA, Skip.NO_AUTHOR) else logger.info
    log(
        "calendar.immediate_skipped tenant_id=%s attempt_id=%s reason=%s",
        tenant_id,
        attempt_id,
        skip,
    )
    return RecordResult(attempt_id, Outcome.SKIPPED, skip=skip)


def _record(session: Session, *, tenant_id: UUID, attempt_id: UUID, user_id: UUID) -> RecordResult:
    # Serializes every caller recording THIS attempt until the transaction ends.
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"{_LOCK_NAMESPACE}{attempt_id}"},
    )
    row = session.get(PublishAttempt, attempt_id)
    if row is None:
        return _skipped(attempt_id, Skip.NOT_FOUND, tenant_id=tenant_id)
    facts = _facts(row)
    skip = eligibility(facts)
    if skip is not None:
        return _skipped(attempt_id, skip, tenant_id=tenant_id)
    event = _existing_event(session, attempt_id)
    if event is not None:
        return RecordResult(attempt_id, Outcome.EXISTING, draft_id=event.post_id, event_id=event.id)

    connection = session.get(SocialConnection, row.connection_id)
    if connection is None:
        return _skipped(attempt_id, Skip.CONNECTION_GONE, tenant_id=tenant_id)
    if connection.purge_started_at is not None:
        return _skipped(attempt_id, Skip.CONNECTION_PURGING, tenant_id=tenant_id)
    if connection.brand_id is None:
        return _skipped(attempt_id, Skip.NO_BRAND, tenant_id=tenant_id)

    children = (
        _children(session, attempt_id) if facts.media_product_type == MEDIA_TYPE_CAROUSEL else ()
    )
    plan = plan_publication(facts, children)
    if isinstance(plan, Skip):
        return _skipped(attempt_id, plan, tenant_id=tenant_id)

    draft_id, _created = create_own_media_piece(
        session,
        tenant_id=tenant_id,
        piece=OwnMediaPiece(
            brand_id=connection.brand_id,
            user_id=user_id,
            caption=plan.caption,
            category=plan.category,
            format=plan.format,
            approved_at=plan.published_at,
            items=plan.items,
            request_key=request_key_for(attempt_id),
        ),
    )
    event_id = session.scalar(
        pg_insert(CalendarEvent)
        .values(
            tenant_id=tenant_id,
            brand_id=connection.brand_id,
            post_id=draft_id,
            connection_id=row.connection_id,
            scheduled_at=plan.published_at,
            scheduled_tz=_timezone(session, tenant_id),
            status=EventStatus.PUBLISHED.value,
            revision=1,
            publish_attempt_id=attempt_id,
            created_by_user_id=user_id,
            destination=plan.destination,
            goals=[],
        )
        .on_conflict_do_nothing(
            index_elements=[CalendarEvent.tenant_id, CalendarEvent.publish_attempt_id],
            index_where=CalendarEvent.publish_attempt_id.is_not(None),
        )
        .returning(CalendarEvent.id)
    )
    if event_id is None:  # pragma: no cover — the advisory lock makes this unreachable
        event = _existing_event(session, attempt_id)
        return RecordResult(
            attempt_id,
            Outcome.EXISTING,
            draft_id=event.post_id if event is not None else draft_id,
            event_id=event.id if event is not None else None,
        )
    logger.info(
        "calendar.immediate_recorded tenant_id=%s attempt_id=%s draft_id=%s event_id=%s items=%s",
        tenant_id,
        attempt_id,
        draft_id,
        event_id,
        len(plan.items),
    )
    return RecordResult(attempt_id, Outcome.RECORDED, draft_id=draft_id, event_id=event_id)


def record_publication(*, tenant_id: UUID, attempt_id: UUID, user_id: UUID) -> RecordResult:
    """Record one publication from «Publicar» in «Tu semana» — the piece and its
    `published` event, in ONE transaction. Idempotent and safe to call concurrently;
    returns SKIPPED (writing nothing) for anything that is not a publication Instagram
    accepted from «Publicar». Never touches the attempt itself."""
    with tenant_session(tenant_id) as session:
        return _record(session, tenant_id=tenant_id, attempt_id=attempt_id, user_id=user_id)


def _owner_of(session: Session, tenant_id: UUID) -> UUID | None:
    """The tenant's first owner, else its first user — who the sweep attributes a
    record to when no acting user is known."""
    owner = session.scalar(
        select(TenantMember.user_id)
        .where(TenantMember.tenant_id == tenant_id, TenantMember.role == "owner")
        .order_by(TenantMember.created_at)
        .limit(1)
    )
    if owner is not None:
        return owner
    return session.scalar(
        select(User.id).where(User.tenant_id == tenant_id).order_by(User.created_at).limit(1)
    )


def _recordable_since(since: datetime) -> Select[tuple[UUID]]:
    """The attempts `record_publication` CAN record, settled since `since`: published,
    not the executor's, no event yet — and only those whose own preconditions hold, so a
    permanent skip never comes back every tick nor takes a slot of `SWEEP_LIMIT`:

    - its connection still exists, belongs to a brand and is not being deleted;
    - its media product type is one `plan_publication` maps;
    - a single attempt recorded its staged object (`media_object_key`, 0159 — NULL on
      every attempt written before it: those wait for the backfill, m-25019220) and, for
      a video or story, its content type; a carousel has at least one child.

    What is left to skip after this is a race (the connection lost its brand meanwhile),
    which `record_publication` still refuses safely."""
    no_event = (
        ~select(CalendarEvent.id)
        .where(
            (CalendarEvent.publish_attempt_id == PublishAttempt.id)
            & (CalendarEvent.tenant_id == PublishAttempt.tenant_id)
        )
        .exists()
    )
    has_children = (
        select(PublishAttemptChild.id)
        .where(
            (PublishAttemptChild.attempt_id == PublishAttempt.id)
            & (PublishAttemptChild.tenant_id == PublishAttempt.tenant_id)
        )
        .exists()
    )
    single_types = (MEDIA_TYPE_IMAGE, MEDIA_TYPE_REELS, MEDIA_TYPE_VIDEO, MEDIA_TYPE_STORIES)
    has_media = or_(
        (PublishAttempt.media_product_type == MEDIA_TYPE_CAROUSEL) & has_children,
        PublishAttempt.media_product_type.in_(single_types)
        & PublishAttempt.media_object_key.is_not(None)
        & (
            (PublishAttempt.media_product_type == MEDIA_TYPE_IMAGE)
            | PublishAttempt.media_content_type.is_not(None)
        ),
    )
    return (
        select(PublishAttempt.id)
        .join(
            SocialConnection,
            (SocialConnection.id == PublishAttempt.connection_id)
            & (SocialConnection.tenant_id == PublishAttempt.tenant_id),
        )
        .where(
            PublishAttempt.status == ATTEMPT_PUBLISHED,
            PublishAttempt.settled_at.is_not(None),
            PublishAttempt.settled_at >= since,
            ~PublishAttempt.idempotency_key.startswith(CALENDAR_KEY_PREFIX, autoescape=True),
            SocialConnection.brand_id.is_not(None),
            SocialConnection.purge_started_at.is_(None),
            has_media,
            no_event,
        )
    )


def unrecorded_publications(
    session: Session, *, since: datetime, limit: int = SWEEP_LIMIT
) -> list[UUID]:
    """Recordable attempts (`_recordable_since`) newest first, at most `limit`. Under the
    caller's session (RLS-scoped)."""
    return list(
        session.scalars(
            _recordable_since(since).order_by(PublishAttempt.settled_at.desc()).limit(limit)
        ).all()
    )


def sweep_recent_publications(
    *,
    tenant_id: UUID,
    now: datetime,
    window: timedelta = SWEEP_WINDOW,
    limit: int = SWEEP_LIMIT,
) -> list[RecordResult]:
    """The tick's backstop: records each unrecorded publication of the last `window`
    (at most `limit`), each in its own transaction, so one failure costs only itself.
    Idempotent: a recorded attempt has an event and is not listed again."""
    with tenant_session(tenant_id) as session:
        pending = unrecorded_publications(session, since=now - window, limit=limit)
        author = _owner_of(session, tenant_id) if pending else None
    if not pending:
        return []
    if author is None:
        # once per sweep, not per attempt: a tenant without users repeats every tick
        logger.info("calendar.immediate_no_author tenant_id=%s pending=%s", tenant_id, len(pending))
        return [
            RecordResult(attempt_id, Outcome.SKIPPED, skip=Skip.NO_AUTHOR) for attempt_id in pending
        ]
    results: list[RecordResult] = []
    for attempt_id in pending:
        try:
            results.append(
                record_publication(tenant_id=tenant_id, attempt_id=attempt_id, user_id=author)
            )
        except Exception as exc:  # one publication's failure never blocks the next
            # the exception's own message (a constraint, a lock) — never the caption,
            # which this code never puts in an exception
            logger.error(
                "calendar.immediate_failed tenant_id=%s attempt_id=%s error=%s: %s",
                tenant_id,
                attempt_id,
                type(exc).__name__,
                str(exc)[:300],
            )
    return results


def tenants_with_unrecorded_publications(session: Session, *, since: datetime) -> list[UUID]:
    """Ids of tenants with a RECORDABLE publication since `since` (`_recordable_since`)
    — for the production discovery (`discovery.DiscoveredTenants`, admin session, ids
    only). A tenant whose only unrecorded attempts can never be recorded is not listed."""
    return list(
        session.scalars(
            _recordable_since(since)
            .with_only_columns(PublishAttempt.tenant_id)
            .distinct()
            .order_by(PublishAttempt.tenant_id)
        ).all()
    )


__all__ = [
    "ATTEMPT_PUBLISHED",
    "CALENDAR_KEY_PREFIX",
    "SWEEP_LIMIT",
    "SWEEP_WINDOW",
    "AttemptFacts",
    "ChildFacts",
    "Outcome",
    "PublicationPlan",
    "RecordResult",
    "Skip",
    "eligibility",
    "plan_publication",
    "record_publication",
    "sweep_recent_publications",
    "tenants_with_unrecorded_publications",
    "unrecorded_publications",
]
