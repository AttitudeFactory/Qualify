"""The dev-only Meta READ simulator for Interacciones (m-24852203).

Locally there is no Meta token, so «Buscar comentarios nuevos» failed with
`CredentialNotFound` (shown as the generic sync error) and the publication list failed the
same way: Interacciones could not be exercised end to end on a laptop or in e2e. With

    QUALIFY_META_READS=fixture

the inbox answers its three Meta READS — the media list (`GET /{ig-user-id}/media`, with
pictures), one media (`GET /{media-id}`) and a media's comments (`GET /{media-id}/comments`)
— from a JSON fixture instead, for ANY connection, and no credential is resolved. The
default fixture is synthetic and committed (`dev/meta-fixtures/inbox.json`);
`QUALIFY_META_READS_FIXTURE=<path>` points at another one (e.g. a local file built from
your own data — never commit third-party media or real usernames).

Same posture as `QUALIFY_CONVERSATIONS_DM_CHANNEL=memory` (`conversations/composition.py`),
with two extra guarantees:

- **Reads only.** This module implements `MediaClient` and `CommentsClient`, nothing else.
  Replies (`qualify_api.replies`), publishing and DMs never pass through it: they stay real
  or use their own in-memory channels. Nothing here can send or publish.
- **Impossible in production.** When the production marker `QUALIFY_DEPLOY_ENV=production`
  is set (`deploy/docker-compose.prod.yml` sets it on every app container, and forces
  `QUALIFY_META_READS` empty there too), asking for the simulator raises
  `MetaReadsSimulatorRefused` instead of silently answering fake data. Any value other than
  exactly `fixture` means the real Graph API (a typo never turns it on).

Fixture shape (`version` 1). Times are RELATIVE to now, so the fixture never ages out of the
14-day window:

    {"version": 1,
     "media": [{"id": "1790...", "posted_hours_ago": 30, "media_product_type": "REELS",
                "media_type": "VIDEO", "caption": "...", "permalink": "...",
                "thumbnail_url": "data:image/svg+xml,...", "media_url": null}],
     "comments": {"1790...": [{"id": "1780...", "text": "...", "username": "ana.demo",
                               "minutes_ago": 90, "like_count": 0}]}}

To demo with a tenant's OWN local data instead (same ids, so the sync adds nothing):

    just inbox-fixture-export --tenant <uuid> --connection <uuid> --out /tmp/mine.json
    QUALIFY_META_READS=fixture QUALIFY_META_READS_FIXTURE=/tmp/mine.json  # then run the app

A media id in `comments` that is not in `media` still answers its comments. An unknown id
answers like Meta for a missing node (HTTP 400, code 100, subcode 33), so the sync's
"deleted at the source" path can be exercised too.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from qualify_shared.social.ig_shapes import IGComment, IGCommentsPage

from qualify_api.inbox.client import CommentsReadError
from qualify_api.inbox.media_client import MediaReadError, MediaSummary

_LOGGER = logging.getLogger(__name__)

META_READS_ENV: Final = "QUALIFY_META_READS"
META_READS_FIXTURE: Final = "fixture"
FIXTURE_PATH_ENV: Final = "QUALIFY_META_READS_FIXTURE"
#: The production marker. Set by `deploy/docker-compose.prod.yml`; never set locally.
DEPLOY_ENV: Final = "QUALIFY_DEPLOY_ENV"
DEPLOY_ENV_PRODUCTION: Final = "production"

#: The committed, synthetic fixture.
DEFAULT_FIXTURE: Final = Path(__file__).resolve().parents[5] / "dev/meta-fixtures/inbox.json"
#: Comments per page, like a short Meta page, so pagination is exercised too.
PAGE_SIZE: Final = 25
_MISSING = {"http_status": 400, "platform_code": 100, "platform_subcode": 33}


class MetaReadsSimulatorRefused(RuntimeError):
    """`QUALIFY_META_READS=fixture` was asked for where the production marker is set."""


def is_production() -> bool:
    return os.environ.get(DEPLOY_ENV, "").strip().lower() == DEPLOY_ENV_PRODUCTION


def simulator_enabled() -> bool:
    """True only for exactly `QUALIFY_META_READS=fixture` (any case) outside production.
    Raises `MetaReadsSimulatorRefused` when it is asked for in production."""
    if os.environ.get(META_READS_ENV, "").strip().lower() != META_READS_FIXTURE:
        return False
    if is_production():
        raise MetaReadsSimulatorRefused(
            f"{META_READS_ENV}={META_READS_FIXTURE} is dev-only and refused in production "
            f"({DEPLOY_ENV}={DEPLOY_ENV_PRODUCTION})"
        )
    return True


def fixture_path() -> Path:
    override = os.environ.get(FIXTURE_PATH_ENV, "").strip()
    return Path(override) if override else DEFAULT_FIXTURE


class MetaReadsFixture:
    """A parsed fixture, with times resolved against `now` once, at load."""

    def __init__(self, payload: dict[str, Any], *, now: datetime | None = None) -> None:
        if payload.get("version") != 1:
            raise ValueError("unsupported Meta reads fixture version")
        reference = now or datetime.now(UTC)
        self.media: dict[str, MediaSummary] = {}
        for entry in payload.get("media") or []:
            summary = _media(entry, reference)
            self.media[summary.id] = summary
        self.comments: dict[str, list[IGComment]] = {
            str(media_id): [_comment(c, reference) for c in entries]
            for media_id, entries in (payload.get("comments") or {}).items()
        }

    @classmethod
    def load(cls, path: Path | None = None, *, now: datetime | None = None) -> MetaReadsFixture:
        source = path or fixture_path()
        return cls(json.loads(source.read_text(encoding="utf-8")), now=now)


def _media(entry: dict[str, Any], now: datetime) -> MediaSummary:
    return MediaSummary(
        id=str(entry["id"]),
        timestamp=now - timedelta(hours=float(entry.get("posted_hours_ago", 1))),
        media_product_type=entry.get("media_product_type"),
        caption=entry.get("caption"),
        permalink=entry.get("permalink"),
        thumbnail_url=entry.get("thumbnail_url"),
        media_type=entry.get("media_type"),
        media_url=entry.get("media_url"),
    )


def _comment(entry: dict[str, Any], now: datetime) -> IGComment:
    posted = now - timedelta(minutes=float(entry.get("minutes_ago", 1)))
    username = entry.get("username")
    payload: dict[str, Any] = {
        "id": str(entry["id"]),
        "text": entry.get("text"),
        "timestamp": posted.isoformat(),
        "like_count": entry.get("like_count", 0),
    }
    if username:
        payload["username"] = username
        payload["from"] = {"id": f"fx-{username}", "username": username}
    return IGComment.model_validate(payload)


class FixtureMediaClient:
    """`MediaClient` over a fixture — answers any account's media list."""

    def __init__(self, fixture: MetaReadsFixture) -> None:
        self._fixture = fixture

    async def list_recent_media(
        self, *, ig_user_id: str, since: datetime
    ) -> tuple[MediaSummary, ...]:
        return tuple(
            media
            for media in sorted(
                self._fixture.media.values(), key=lambda m: m.timestamp, reverse=True
            )
            if media.timestamp >= since and media.media_product_type != "STORY"
        )

    async def list_recent_stories(self, *, ig_user_id: str) -> tuple[MediaSummary, ...]:
        return tuple(m for m in self._fixture.media.values() if m.media_product_type == "STORY")

    async def get_media(self, *, media_id: str) -> MediaSummary:
        media = self._fixture.media.get(media_id)
        if media is None:
            raise MediaReadError(f"GET /{media_id} failed with HTTP 400", **_MISSING)
        return media


class FixtureCommentsClient:
    """`CommentsClient` over a fixture — paginated by `PAGE_SIZE`, cursor = offset."""

    def __init__(self, fixture: MetaReadsFixture) -> None:
        self._fixture = fixture

    async def list_comments(self, *, ig_media_id: str, after: str | None = None) -> IGCommentsPage:
        if ig_media_id not in self._fixture.comments and ig_media_id not in self._fixture.media:
            raise CommentsReadError(f"GET /{ig_media_id}/comments failed with HTTP 400", **_MISSING)
        comments = self._fixture.comments.get(ig_media_id, [])
        start = int(after) if after and after.isdigit() else 0
        page = comments[start : start + PAGE_SIZE]
        end = start + len(page)
        paging = {"cursors": {"after": str(end)}} if end < len(comments) else None
        return IGCommentsPage(data=page, paging=paging)


def fixture_clients() -> tuple[FixtureMediaClient, FixtureCommentsClient]:
    """Both read clients over the configured fixture, loaded fresh (so editing the file
    takes effect on the next read). Logs that the simulator answered, never silently."""
    fixture = MetaReadsFixture.load()
    _LOGGER.warning("inbox.meta_reads.simulated fixture=%s", fixture_path().name)
    return FixtureMediaClient(fixture), FixtureCommentsClient(fixture)


# --- a local fixture from the tenant's OWN stored rows (never committed) ----------------


def export_tenant_fixture(
    *, tenant_id: UUID, connection_id: UUID, now: datetime | None = None
) -> dict[str, Any]:
    """A fixture built from what this connection already has in the local database: its
    `monitored_media` rows and the inbound comments of its comment threads, with times
    made relative to `now`. Read through `tenant_session` (RLS). With the SAME ids the
    sync then finds nothing new — the screen works without a token and the rows are not
    duplicated. For local demos only: the output holds real data, keep it out of git."""
    from qualify_shared.db.session import tenant_session  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    from qualify_api.inbox.models import Message, MonitoredMedia, Thread  # noqa: PLC0415

    reference = now or datetime.now(UTC)

    def hours_ago(moment: datetime | None) -> float:
        return round((reference - moment).total_seconds() / 3600, 2) if moment else 1.0

    def minutes_ago(moment: datetime | None) -> float:
        if moment is None:
            return 1.0
        aware = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
        return round((reference - aware).total_seconds() / 60, 1)

    with tenant_session(tenant_id) as session:
        # Explicit columns (not whole rows): works on any local schema that has them.
        media_rows = session.execute(
            select(
                MonitoredMedia.external_media_id,
                MonitoredMedia.media_posted_at,
                MonitoredMedia.media_product_type,
                MonitoredMedia.media_type,
                MonitoredMedia.caption,
                MonitoredMedia.permalink,
            ).where(MonitoredMedia.connection_id == connection_id)
        ).all()
        comment_rows = session.execute(
            select(
                Thread.external_thread_id,
                Message.external_message_id,
                Message.text,
                Message.author_username,
                Message.posted_at,
            )
            .join(Message, Message.thread_id == Thread.id)
            .where(
                Thread.connection_id == connection_id,
                Thread.channel == "comment",
                Message.direction == "inbound",
                Message.deleted_at.is_(None),
            )
            .order_by(Message.posted_at)
        ).all()
        media: list[dict[str, Any]] = [
            {
                "id": row.external_media_id,
                "posted_hours_ago": hours_ago(row.media_posted_at),
                "media_product_type": row.media_product_type or "FEED",
                "media_type": row.media_type,
                "caption": row.caption,
                "permalink": row.permalink,
            }
            for row in media_rows
        ]
        comments: dict[str, list[dict[str, Any]]] = {}
        for message in comment_rows:
            comments.setdefault(message.external_thread_id, []).append(
                {
                    "id": message.external_message_id,
                    "text": message.text,
                    "username": message.author_username,
                    "minutes_ago": minutes_ago(message.posted_at),
                }
            )
    known = {entry["id"] for entry in media}
    for media_id in comments:  # a thread with no monitored_media row still lists
        if media_id not in known:
            media.append({"id": media_id, "posted_hours_ago": 1.0, "media_product_type": "FEED"})
    return {
        "version": 1,
        "_note": "LOCAL export: real data, do not commit.",
        "media": media,
        "comments": comments,
    }
