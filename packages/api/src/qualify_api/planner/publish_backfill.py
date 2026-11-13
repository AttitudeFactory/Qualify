"""Bring the publications made from «Publicar» BEFORE 0159 into «Tu semana» (m-25019220,
epic m-25019215; founder 2026-11-13).

    just publish-backfill --tenant <uuid> [--connection <uuid>] [--since 2026-11-01]
                          [--limit 50] [--execute]
    just publish-backfill --tenant <uuid> --probe [--attempt <uuid>]

**Dry run by default**: it prints one line per publication with what it WOULD do and
why, and writes nothing — no row, no R2 object, no permalink, no Graph call (each Graph
read is logged in the hourly budget table, a write). `--execute` writes. `--probe` reads
ONE media from Graph and prints what came back: the live check ADR 25 asks for before
any batch. `--tenant` is mandatory; there is no all-tenants mode.

## Which publications

`publish_attempts` settled `published`, not from a scheduled post (`scheduled_post_id IS
NULL`), not the planner executor's (`cal:` key), with no calendar event, on an Instagram
connection that still exists, belongs to a brand and is not being deleted. Oldest first,
at most `--limit`.

## The media of each one

- A carousel: its children's keys (`publish_attempt_children`, always recorded).
- A single attempt that recorded its key (0159 onwards): that key.
- An older single attempt: its staged file is still in R2 under
  `t/{tenant}/media/{connection}/{32 hex}` («Publicar» names it `uuid4().hex`), but the
  row never said which. `match_single` decides — see «The matching rule» below. The
  attempt row is never written (a settled row refuses it; the match is recorded on the
  piece instead).
- No clear match: Instagram's own copy of the picture (`media_url`), copied ONCE into
  R2 at `t/{tenant}/media/{connection}/ig-{media id}` (write-once root: checked before
  writing, never overwritten), recorded as a VIEW-ONLY piece. A video without a clear
  match is skipped (Instagram's `media_url` of a reel is the video file, and copying
  videos is out of scope): reported, nothing written.

## The matching rule (`match_single`)

For attempt A on connection C, started at S, whose previous attempt on C (any kind, any
status) started at P:

    window(A) = ( max(S − 120 s, P + 5 s) , S + 5 s ]

«Publicar» stages the file and only then inserts the attempt (its row is written before
any Meta call), so A's file was written shortly before S and after the previous attempt
started. Consecutive windows on one connection never overlap (each starts 5 s after the
previous attempt's start, where the previous window ended), so **no file can fall in two
windows**. The 5 s tolerate a clock difference between Postgres and R2.

That clock tolerance is also why close neighbours are not trusted: when the previous or
the next attempt on the connection started less than 30 s away (`MIN_GAP`: 20 s of
staging lead + 2 × 5 s), the next file could land in A's window while A's own file sits
just before it — so the match is DOUBTFUL, whatever the window holds. With neighbours
≥ 30 s apart, A's own file is provably inside A's window and no neighbour's file is.

A match is CLEAR only when the neighbours are ≥ 30 s away and exactly ONE object in the
window is a «Publicar» file (32 lower-case hex), is not referenced anywhere (an attempt,
a carousel child, a scheduled post, a piece's asset, brief or preview), and its first
bytes fit the attempt's type: a JPEG of at most 8 MB for an IMAGE, an MP4/QuickTime
header for a reel, either for a story. Zero objects, two or more, or one whose bytes do
not fit → DOUBTFUL → Instagram's copy, never a guessed file. In a burst sent one by one
at ≥ 30 s intervals every image gets its own file; images sent faster fall back to
Instagram's copy — never a wrong one.

## Provenance and what the owner sees

The piece is `own_media`, source = the attempt (`content_drafts.request_key =
request_key_for(attempt)`, the event's `publish_attempt_id`), pipeline
`publish-backfill-v1`, and every `image_assets.params` says `match` =
`r2_original` / `attempt_key` / `carousel_children` / `instagram_copy`, with the rule.

- Original found: reusable (`recurrente`) — «Lista para programar» in «Aprobados».
- Instagram's copy: `promocional` — published once, so the gallery shows it «Ya salió»
  with «Ver», and it is not offered in «Sin programar». (The server does not forbid
  scheduling it; nothing offers it.)

Both get their calendar event, `published`, at `settled_at`.

## Idempotent

The piece's request key and the event's unique `(tenant, publish_attempt_id)` make a
second `--execute` find nothing to do (recorded attempts have an event). The Instagram
copy has a fixed key, checked before writing. The permalink is written only while NULL.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from qualify_creative.enums import ReuseType
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate, StoredObject
from qualify_shared.objects.keys import tenant_prefix
from sqlalchemy import select, union

from qualify_api.connections.models import SocialConnection
from qualify_api.creative import models as creative
from qualify_api.creative.own_media import OwnMediaItem
from qualify_api.inbox.media_client import MediaSummary
from qualify_api.inbox.thumbnails import PictureFetcher, ThumbnailUnavailable
from qualify_api.planner.immediate import (
    ATTEMPT_PUBLISHED,
    CALENDAR_KEY_PREFIX,
    Outcome,
    RecordingOverride,
    owner_of,
    record_backfilled_publication,
)
from qualify_api.planner.models import CalendarEvent
from qualify_api.planner.permalinks import (
    CallBudget,
    LedgerBudget,
    MediaReader,
    PermalinkTarget,
    ReaderFactory,
    production_reader,
    read_media,
    store_permalink,
)
from qualify_api.planner.permalinks import Outcome as LinkOutcome
from qualify_api.publishing.client import (
    IMAGE_MAX_BYTES,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_REELS,
    MEDIA_TYPE_STORIES,
    MEDIA_TYPE_VIDEO,
)
from qualify_api.publishing.models import PublishAttempt, PublishAttemptChild, ScheduledPost
from qualify_api.publishing.service import MEDIA_TYPE_CAROUSEL

#: `pipeline_version` of the pieces this backfill writes (distinct from `publish-now-v1`).
PIPELINE_VERSION = "publish-backfill-v1"
MATCH_RULE = (
    "window(max(start-120s,prev_start+5s),start+5s];neighbours>=30s;one_unreferenced_publicar_file"
)
WINDOW_BACK = timedelta(seconds=120)
SKEW = timedelta(seconds=5)
#: Neighbouring attempts closer than this make a match doubtful: 20 s for the staging
#: lead (file written → attempt row inserted) plus twice the clock tolerance.
MIN_GAP = timedelta(seconds=30)
DEFAULT_LIMIT = 50
MAX_LIMIT = 500
#: Bytes read from a candidate to tell a JPEG from a video.
SNIFF_BYTES = 16

_PUBLICAR_NAME = re.compile(r"[0-9a-f]{32}")
_SAFE_MEDIA_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SINGLE_TYPES = (MEDIA_TYPE_IMAGE, MEDIA_TYPE_REELS, MEDIA_TYPE_VIDEO, MEDIA_TYPE_STORIES)


# -- the pure part --------------------------------------------------------------------------


def sniff(head: bytes) -> str | None:
    """The content type the first bytes say, among the ones «Publicar» stages."""
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp":
        return "video/quicktime" if head[8:12] == b"qt  " else "video/mp4"
    return None


def window_for(
    started_at: datetime, previous_started_at: datetime | None
) -> tuple[datetime, datetime]:
    """`(low, high]`: where the staged file of an attempt started at `started_at` can be."""
    low = started_at - WINDOW_BACK
    if previous_started_at is not None:
        low = max(low, previous_started_at + SKEW)
    return low, started_at + SKEW


def is_publicar_file(key: str, folder: str) -> bool:
    return key.startswith(folder) and bool(_PUBLICAR_NAME.fullmatch(key[len(folder) :]))


def fits(product: str, content_type: str | None, size: int) -> bool:
    """Whether a file with these bytes can be what this attempt published."""
    if content_type is None:
        return False
    image = content_type == "image/jpeg" and size <= IMAGE_MAX_BYTES
    video = content_type.startswith("video/")
    if product == MEDIA_TYPE_IMAGE:
        return image
    if product in (MEDIA_TYPE_REELS, MEDIA_TYPE_VIDEO):
        return video
    if product == MEDIA_TYPE_STORIES:
        return image or video
    return False


@dataclass(frozen=True)
class Match:
    key: str | None  # None == doubtful
    content_type: str | None
    reason: str
    window: tuple[datetime, datetime]

    @property
    def clear(self) -> bool:
        return self.key is not None


def in_window(obj: StoredObject, window: tuple[datetime, datetime]) -> bool:
    low, high = window
    return obj.last_modified is not None and low < obj.last_modified <= high


def crowding(
    started_at: datetime, previous_start: datetime | None, next_start: datetime | None
) -> str | None:
    """Why the neighbours are too close for a window to be trusted, or None."""
    if previous_start is not None and started_at - previous_start < MIN_GAP:
        gap = (started_at - previous_start).total_seconds()
        return f"previous attempt started {gap:.0f} s before (< {MIN_GAP.seconds} s)"
    if next_start is not None and next_start - started_at < MIN_GAP:
        gap = (next_start - started_at).total_seconds()
        return f"next attempt started {gap:.0f} s after (< {MIN_GAP.seconds} s)"
    return None


def match_single(
    *,
    product: str,
    started_at: datetime,
    previous_start: datetime | None,
    next_start: datetime | None,
    objects: Iterable[StoredObject],
    folder: str,
    referenced: frozenset[str] | set[str],
    content_types: Mapping[str, str | None],
) -> Match:
    """The rule in the module docstring. Pure: the caller lists and sniffs."""
    window = window_for(started_at, previous_start)
    crowded = crowding(started_at, previous_start, next_start)
    if crowded is not None:
        return Match(None, None, crowded, window)
    pool = [
        obj
        for obj in objects
        if is_publicar_file(obj.key, folder)
        and obj.key not in referenced
        and in_window(obj, window)
    ]
    if not pool:
        return Match(None, None, "no unreferenced «Publicar» file in the window", window)
    if len(pool) > 1:
        return Match(None, None, f"{len(pool)} unreferenced «Publicar» files in the window", window)
    only = pool[0]
    content_type = content_types.get(only.key)
    if not fits(product, content_type, only.size):
        return Match(
            None,
            None,
            f"the only file does not fit {product} ({content_type or 'unknown'})",
            window,
        )
    return Match(
        only.key, content_type, f"only file in the window, {content_type} {only.size} B", window
    )


# -- what is read from the database ---------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    id: UUID
    connection_id: UUID
    started_at: datetime
    settled_at: datetime
    product: str
    media_object_key: str | None
    media_content_type: str | None
    published_media_id: str | None
    permalink: str | None
    has_children: bool


def candidates(
    *,
    tenant_id: UUID,
    connection_id: UUID | None,
    since: datetime | None,
    limit: int,
) -> list[Candidate]:
    """The publications to bring in (module docstring), oldest first. RLS-scoped."""
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
    query = (
        select(
            PublishAttempt.id,
            PublishAttempt.connection_id,
            PublishAttempt.started_at,
            PublishAttempt.settled_at,
            PublishAttempt.media_product_type,
            PublishAttempt.media_object_key,
            PublishAttempt.media_content_type,
            PublishAttempt.published_media_id,
            PublishAttempt.permalink,
            has_children,
        )
        .join(
            SocialConnection,
            (SocialConnection.id == PublishAttempt.connection_id)
            & (SocialConnection.tenant_id == PublishAttempt.tenant_id),
        )
        .where(
            PublishAttempt.status == ATTEMPT_PUBLISHED,
            PublishAttempt.settled_at.is_not(None),
            PublishAttempt.scheduled_post_id.is_(None),
            ~PublishAttempt.idempotency_key.startswith(CALENDAR_KEY_PREFIX, autoescape=True),
            SocialConnection.platform == "instagram",
            SocialConnection.brand_id.is_not(None),
            SocialConnection.purge_started_at.is_(None),
            no_event,
        )
    )
    if connection_id is not None:
        query = query.where(PublishAttempt.connection_id == connection_id)
    if since is not None:
        query = query.where(PublishAttempt.settled_at >= since)
    query = query.order_by(PublishAttempt.started_at, PublishAttempt.id).limit(limit)
    with tenant_session(tenant_id) as session:
        return [Candidate(*row) for row in session.execute(query).all()]


def attempt_starts(*, tenant_id: UUID, connection_id: UUID) -> list[datetime]:
    """Every attempt's start on the connection (any kind, any status), ascending."""
    with tenant_session(tenant_id) as session:
        return list(
            session.scalars(
                select(PublishAttempt.started_at)
                .where(PublishAttempt.connection_id == connection_id)
                .order_by(PublishAttempt.started_at)
            ).all()
        )


def referenced_keys(*, tenant_id: UUID, folder: str) -> set[str]:
    """Every key under `folder` some row already points at — never matched again."""
    columns = (
        PublishAttempt.media_object_key,
        PublishAttemptChild.media_object_key,
        ScheduledPost.media_object_key,
        creative.ImageAsset.object_key,
        creative.ContentBrief.source_media_key,
        creative.ContentDraft.preview_key,
    )
    query = union(
        *(select(column).where(column.startswith(folder, autoescape=True)) for column in columns)
    )
    with tenant_session(tenant_id) as session:
        return {key for key in session.scalars(query).all() if key}


def _neighbours(
    starts: list[datetime], started_at: datetime
) -> tuple[datetime | None, datetime | None]:
    """The previous and next attempt starts on the connection (any kind, any status)."""
    earlier = [start for start in starts if start < started_at]
    later = [start for start in starts if start > started_at]
    return (earlier[-1] if earlier else None, later[0] if later else None)


# -- the run --------------------------------------------------------------------------------


class Action(StrEnum):
    ORIGINAL = "original"  # the R2 file «Publicar» staged, clear match
    ATTEMPT_KEY = "attempt_key"  # the attempt recorded its key (0159 onwards)
    CAROUSEL = "carousel_children"
    INSTAGRAM_COPY = "instagram_copy"  # view-only, Instagram's picture
    SKIP = "skip"


@dataclass(frozen=True)
class Line:
    attempt_id: UUID
    started_at: datetime
    product: str
    action: Action
    detail: str
    permalink: str = ""
    recorded: str = ""

    def render(self) -> str:
        parts = [
            f"attempt={self.attempt_id}",
            f"started={self.started_at.astimezone(UTC).isoformat(timespec='seconds')}",
            f"type={self.product}",
            f"action={self.action.value}",
            f'why="{self.detail}"',
        ]
        if self.permalink:
            parts.append(f"permalink={self.permalink}")
        if self.recorded:
            parts.append(f"result={self.recorded}")
        return " ".join(parts)


@dataclass
class Report:
    execute: bool
    lines: list[Line] = field(default_factory=list)
    stopped: str = ""  # why the run ended early (budget), with what is left

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for line in self.lines:
            out[line.action.value] = out.get(line.action.value, 0) + 1
        return out

    def render(self) -> str:
        head = "EXECUTE" if self.execute else "DRY RUN (nothing written, no Graph call)"
        body = [line.render() for line in self.lines]
        tail = " ".join(f"{k}={v}" for k, v in sorted(self.counts().items())) or "nothing to do"
        out = [head, *body, f"total {len(self.lines)}: {tail}"]
        if self.stopped:
            out.append(f"stopped: {self.stopped}")
        return "\n".join(out)


@dataclass
class Deps:
    gate: ObjectGate
    fetcher: PictureFetcher
    readers: ReaderFactory = production_reader
    budget: CallBudget | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)


def instagram_copy_key(tenant_id: UUID, connection_id: UUID, media_id: str) -> str | None:
    if not _SAFE_MEDIA_ID.fullmatch(media_id):
        return None
    return f"{tenant_prefix(tenant_id)}media/{connection_id}/ig-{media_id}"


def _sniff_object(gate: ObjectGate, tenant_id: UUID, key: str) -> str | None:
    return sniff(gate.open_range(tenant_id, key, 0, SNIFF_BYTES - 1).read())


def _resolve(
    candidate: Candidate,
    *,
    tenant_id: UUID,
    gate: ObjectGate,
    objects: list[StoredObject],
    folder: str,
    referenced: set[str],
    starts: list[datetime],
    sniffed: dict[str, str | None],
) -> tuple[Action, Match | None, str]:
    """What the media is — without writing anything."""
    if candidate.product == MEDIA_TYPE_CAROUSEL:
        if candidate.has_children:
            return Action.CAROUSEL, None, "carousel items recorded on the attempt"
        return Action.SKIP, None, "carousel without recorded items"
    if candidate.product not in _SINGLE_TYPES:
        return Action.SKIP, None, f"unsupported type {candidate.product}"
    if candidate.media_object_key and (
        candidate.product == MEDIA_TYPE_IMAGE or candidate.media_content_type
    ):
        return Action.ATTEMPT_KEY, None, "the attempt recorded its file"
    previous_start, next_start = _neighbours(starts, candidate.started_at)
    window = window_for(candidate.started_at, previous_start)
    for obj in objects:
        if (
            obj.key not in sniffed
            and is_publicar_file(obj.key, folder)
            and obj.key not in referenced
            and in_window(obj, window)
        ):
            sniffed[obj.key] = _sniff_object(gate, tenant_id, obj.key)
    match = match_single(
        product=candidate.product,
        started_at=candidate.started_at,
        previous_start=previous_start,
        next_start=next_start,
        objects=objects,
        folder=folder,
        referenced=referenced,
        content_types=sniffed,
    )
    low, high = (moment.astimezone(UTC).strftime("%H:%M:%S") for moment in window)
    detail = f"{match.reason} ({low},{high}]"
    if match.clear:
        return Action.ORIGINAL, match, f"{match.key.rsplit('/', 1)[-1]}: {detail}"  # type: ignore[union-attr]
    if candidate.product in (MEDIA_TYPE_REELS, MEDIA_TYPE_VIDEO):
        return Action.SKIP, match, f"video without a clear file: {detail}"
    return Action.INSTAGRAM_COPY, match, f"doubtful: {detail}"


async def _copy_from_instagram(
    media: MediaSummary,
    *,
    tenant_id: UUID,
    connection_id: UUID,
    deps: Deps,
) -> tuple[str, str] | str:
    """`(key, content_type)` of Instagram's picture in R2, or why there is none."""
    if (media.media_type or "").upper() != "IMAGE":
        return f"Instagram says it is {media.media_type or 'unknown'}, not an image"
    key = instagram_copy_key(tenant_id, connection_id, media.id)
    if key is None:
        return "media id is not a plain identifier"
    if deps.gate.has_object(tenant_id, key):  # write-once root: reuse, never overwrite
        content_type = _sniff_object(deps.gate, tenant_id, key)
        if content_type is None or not content_type.startswith("image/"):
            return "an earlier copy exists but is not an image"
        return key, content_type
    if not media.media_url:
        return "Instagram gave no picture address"
    try:
        body, content_type = await deps.fetcher.fetch(media.media_url)
    except ThumbnailUnavailable as exc:
        return f"picture not downloaded: {exc}"
    await asyncio.to_thread(
        deps.gate.put_connection_media,
        tenant_id,
        connection_id,
        key,
        io.BytesIO(body),
        content_type,
    )
    return key, content_type


async def run_backfill(
    *,
    tenant_id: UUID,
    deps: Deps,
    connection_id: UUID | None = None,
    since: datetime | None = None,
    limit: int = DEFAULT_LIMIT,
    execute: bool = False,
) -> Report:
    """The whole run (module docstring). Dry run unless `execute`."""
    report = Report(execute=execute)
    pending = candidates(tenant_id=tenant_id, connection_id=connection_id, since=since, limit=limit)
    if not pending:
        return report
    author = owner_of(tenant_id) if execute else None
    if execute and author is None:
        report.stopped = "the tenant has no user to attribute the pieces to"
        return report
    budget = deps.budget or (LedgerBudget() if execute else None)
    per_connection: dict[UUID, tuple[list[StoredObject], set[str], list[datetime], str]] = {}
    readers: dict[UUID, MediaReader | None] = {}
    sniffed: dict[str, str | None] = {}

    for index, candidate in enumerate(pending):
        conn = candidate.connection_id
        if conn not in per_connection:
            folder = f"{tenant_prefix(tenant_id)}media/{conn}/"
            per_connection[conn] = (
                deps.gate.list_connection_media(tenant_id, conn),
                referenced_keys(tenant_id=tenant_id, folder=folder),
                attempt_starts(tenant_id=tenant_id, connection_id=conn),
                folder,
            )
        objects, referenced, starts, folder = per_connection[conn]
        action, match, detail = _resolve(
            candidate,
            tenant_id=tenant_id,
            gate=deps.gate,
            objects=objects,
            folder=folder,
            referenced=referenced,
            starts=starts,
            sniffed=sniffed,
        )
        if match is not None and match.key is not None:
            referenced.add(match.key)  # never handed to a second attempt in this run
        needs_link = candidate.permalink is None and candidate.published_media_id is not None
        needs_read = action is not Action.SKIP and (needs_link or action is Action.INSTAGRAM_COPY)
        base = Line(candidate.id, candidate.started_at, candidate.product, action, detail)
        if action is Action.INSTAGRAM_COPY and candidate.published_media_id is None:
            report.lines.append(
                _with(base, Action.SKIP, f"{detail}; no Instagram media id to read")
            )
            continue
        if not execute:
            link = "would_read" if needs_read else ("present" if candidate.permalink else "")
            report.lines.append(_with(base, permalink=link))
            continue

        media: MediaSummary | None = None
        link_note = "present" if candidate.permalink else ""
        if needs_read:
            assert candidate.published_media_id is not None and budget is not None
            if conn not in readers:
                try:
                    readers[conn] = await deps.readers(tenant_id, conn)
                except Exception as exc:  # noqa: BLE001 — reported per publication
                    readers[conn] = None
                    link_note = f"connection not readable ({type(exc).__name__})"
            reader = readers[conn]
            if reader is not None:
                read = await read_media(
                    PermalinkTarget(candidate.id, conn, candidate.published_media_id),
                    tenant_id=tenant_id,
                    reader=reader,
                    budget=budget,
                    now=deps.clock(),
                )
                if read is LinkOutcome.NO_BUDGET:
                    left = len(pending) - index
                    report.stopped = (
                        f"the connection's hourly Graph budget is spent; {left} publication(s) "
                        "left — run the same command again in an hour"
                    )
                    return report
                if isinstance(read, MediaSummary):
                    media = read
                else:
                    link_note = read.value
            elif not link_note:
                link_note = "connection not readable"

        override = RecordingOverride(
            pipeline_version=PIPELINE_VERSION,
            reuse_type=ReuseType.RECURRENTE,
            asset_params=(("match", action.value), ("source_attempt_id", str(candidate.id))),
        )
        if action is Action.ORIGINAL:
            assert match is not None and match.key is not None and match.content_type is not None
            override = RecordingOverride(
                media=OwnMediaItem(
                    object_key=match.key,
                    content_type=match.content_type,
                    media_type="image" if match.content_type.startswith("image/") else "video",
                    position=0,
                ),
                pipeline_version=PIPELINE_VERSION,
                reuse_type=ReuseType.RECURRENTE,
                asset_params=(
                    ("match", action.value),
                    ("match_rule", MATCH_RULE),
                    ("source_attempt_id", str(candidate.id)),
                ),
            )
        elif action is Action.INSTAGRAM_COPY:
            if media is None:
                report.lines.append(
                    _with(base, Action.SKIP, f"{detail}; Instagram copy not readable ({link_note})")
                )
                continue
            copied = await _copy_from_instagram(
                media, tenant_id=tenant_id, connection_id=conn, deps=deps
            )
            if isinstance(copied, str):
                report.lines.append(_with(base, Action.SKIP, f"{detail}; {copied}"))
                continue
            key, content_type = copied
            override = RecordingOverride(
                media=OwnMediaItem(
                    object_key=key, content_type=content_type, media_type="image", position=0
                ),
                pipeline_version=PIPELINE_VERSION,
                reuse_type=ReuseType.PROMOCIONAL,  # view-only: «Ya salió», never re-offered
                asset_params=(
                    ("match", action.value),
                    ("match_rule", MATCH_RULE),
                    ("instagram_media_id", media.id),
                    ("source_attempt_id", str(candidate.id)),
                ),
            )
        elif action is Action.SKIP:
            report.lines.append(base)
            continue

        assert author is not None
        result = record_backfilled_publication(
            tenant_id=tenant_id, attempt_id=candidate.id, user_id=author, override=override
        )
        recorded = result.outcome.value + (f":{result.skip.value}" if result.skip else "")
        if media is not None and result.outcome is not Outcome.SKIPPED:
            link_note = store_permalink(
                tenant_id=tenant_id, attempt_id=candidate.id, permalink=media.permalink
            ).value
        report.lines.append(_with(base, permalink=link_note, recorded=recorded))
    return report


def _with(
    line: Line,
    action: Action | None = None,
    detail: str | None = None,
    *,
    permalink: str = "",
    recorded: str = "",
) -> Line:
    return Line(
        line.attempt_id,
        line.started_at,
        line.product,
        action or line.action,
        detail if detail is not None else line.detail,
        permalink,
        recorded,
    )


# -- the probe ------------------------------------------------------------------------------


def _probe_target(
    *, tenant_id: UUID, attempt_id: UUID | None, connection_id: UUID | None
) -> PermalinkTarget | None:
    query = select(
        PublishAttempt.id, PublishAttempt.connection_id, PublishAttempt.published_media_id
    ).where(
        PublishAttempt.status == ATTEMPT_PUBLISHED,
        PublishAttempt.published_media_id.is_not(None),
    )
    if attempt_id is not None:
        query = query.where(PublishAttempt.id == attempt_id)
    if connection_id is not None:
        query = query.where(PublishAttempt.connection_id == connection_id)
    with tenant_session(tenant_id) as session:
        row = session.execute(query.order_by(PublishAttempt.settled_at.desc()).limit(1)).first()
    return PermalinkTarget(row[0], row[1], row[2]) if row is not None else None


def _host(url: str | None) -> str:
    return f"present ({urlsplit(url).hostname})" if url else "absent"


async def probe(
    *,
    tenant_id: UUID,
    deps: Deps,
    attempt_id: UUID | None = None,
    connection_id: UUID | None = None,
) -> str:
    """ONE budgeted Graph read of one published attempt's media; what came back. Signed
    CDN addresses are never printed — only whether they came and from which host."""
    target = _probe_target(tenant_id=tenant_id, attempt_id=attempt_id, connection_id=connection_id)
    if target is None:
        return "probe: no published attempt with an Instagram media id"
    reader = await deps.readers(tenant_id, target.connection_id)
    read = await read_media(
        target,
        tenant_id=tenant_id,
        reader=reader,
        budget=deps.budget or LedgerBudget(),
        now=deps.clock(),
    )
    head = f"probe attempt={target.attempt_id} media={target.media_id}"
    if isinstance(read, LinkOutcome):
        return f"{head} result={read.value}"
    return "\n".join(
        [
            f"{head} result=readable",
            f"  timestamp={read.timestamp.isoformat()}",
            f"  media_product_type={read.media_product_type}",
            f"  media_type={read.media_type}",
            f"  permalink={read.permalink}",
            f"  media_url={_host(read.media_url)}",
            f"  thumbnail_url={_host(read.thumbnail_url)}",
            f"  caption_chars={len(read.caption or '')}",
        ]
    )


# -- the CLI --------------------------------------------------------------------------------


def _production_deps() -> Deps:
    from qualify_shared.objects.config import R2Settings  # noqa: PLC0415
    from qualify_shared.objects.s3 import R2ObjectStore  # noqa: PLC0415

    from qualify_api.inbox.thumbnails import HttpPictureFetcher  # noqa: PLC0415

    return Deps(gate=ObjectGate(R2ObjectStore(R2Settings.from_env())), fetcher=HttpPictureFetcher())


def main(argv: list[str] | None = None, *, deps: Deps | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bring «Publicar» publications made before 0159 into «Tu semana»."
    )
    parser.add_argument("--tenant", type=UUID, required=True)
    parser.add_argument("--connection", type=UUID)
    parser.add_argument("--since", type=date.fromisoformat, help="settled on/after (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--execute", action="store_true", help="write (default: dry run)")
    parser.add_argument("--probe", action="store_true", help="read ONE media from Graph")
    parser.add_argument("--attempt", type=UUID, help="with --probe: this attempt's media")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= MAX_LIMIT:
        parser.error(f"--limit must be between 1 and {MAX_LIMIT}")
    if args.probe and args.execute:
        parser.error("--probe reads one media and writes nothing: drop --execute")
    if args.attempt and not args.probe:
        parser.error("--attempt goes with --probe")
    resolved = deps or _production_deps()
    if args.probe:
        out = asyncio.run(
            probe(
                tenant_id=args.tenant,
                deps=resolved,
                attempt_id=args.attempt,
                connection_id=args.connection,
            )
        )
    else:
        since = datetime.combine(args.since, datetime.min.time(), UTC) if args.since else None
        out = asyncio.run(
            run_backfill(
                tenant_id=args.tenant,
                deps=resolved,
                connection_id=args.connection,
                since=since,
                limit=args.limit,
                execute=args.execute,
            )
        ).render()
    sys.stdout.write(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
