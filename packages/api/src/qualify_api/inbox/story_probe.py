"""The R1 probe for story comments (m-24789644): does Meta serve the comments of a story
through the same `/comments` edge Reels and posts use? Read-only, for one real connection,
with the `story_comments` capability still OFF — it answers the question before anything
is switched on.

    just story-probe --tenant <uuid> --connection <uuid>

Steps 1-3 run here; step 4 is the operator's (`docs/conversaciones-limitaciones-meta.md`):

1. `GET /{ig-user-id}/stories` — are the account's live stories listed at all? A failure
   here is usually the token missing `pages_read_engagement` (the edge's documented
   permission next to `instagram_basic`).
2. `GET /{story-id}` for each listed story (at most `MAX_STORIES`) — is it a `STORY`, and
   is its `timestamp` there (the window rule needs it)?
3. `GET /{story-id}/comments` (first page) — the actual question: does Meta answer with
   comments, with an empty page, or with an error?
4. With a comment confirmed in step 3: `QUALIFY_STORY_COMMENTS=on`, monitor the story in
   Interacciones, sync, then «Analizar sentimiento» / «Analizar intención».

The report is JSON on stdout: ids, timestamps, counts, HTTP status and Meta's numeric
error codes — never a token, never a comment's text or author. Every Meta call is logged
to the connection's 200/hour ledger first, like the sync's own calls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from qualify_api.inbox.client import CommentsClient, CommentsReadError
from qualify_api.inbox.media_client import MediaClient, MediaReadError

#: Enough to see the pattern; a probe must not spend the hour's budget on one account.
MAX_STORIES: Final = 3


@dataclass
class StoryCheck:
    story_id: str
    media_product_type: str | None = None
    timestamp: str | None = None
    media_error: dict[str, int | None] | None = None
    comments_on_first_page: int | None = None
    has_more_comments: bool | None = None
    comments_error: dict[str, int | None] | None = None


@dataclass
class StoryProbeReport:
    stories_listed: int | None = None
    stories_error: dict[str, int | None] | None = None
    checks: list[StoryCheck] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """One line for the R1 table: what this run proves, and nothing more."""
        if self.stories_error is not None:
            return "stories_not_listed"
        if not self.stories_listed:
            return "no_live_story"
        if any(c.comments_on_first_page for c in self.checks):
            return "comments_served"
        if any(c.comments_error is not None for c in self.checks):
            return "comments_refused"
        return "comments_empty"

    def to_json(self) -> str:
        return json.dumps({"verdict": self.verdict, **asdict(self)}, indent=2)


def _codes(exc: MediaReadError | CommentsReadError) -> dict[str, int | None]:
    return {
        "http_status": exc.http_status,
        "code": exc.platform_code,
        "subcode": exc.platform_subcode,
    }


async def probe_stories(
    *,
    media_client: MediaClient,
    comments_client: CommentsClient,
    ig_user_id: str,
    record_call: Callable[[], None],
) -> StoryProbeReport:
    """Steps 1-3 of the module docstring. `record_call` runs before every Meta call."""
    report = StoryProbeReport()
    record_call()
    try:
        stories = await media_client.list_recent_stories(ig_user_id=ig_user_id)
    except MediaReadError as exc:
        report.stories_error = _codes(exc)
        return report
    report.stories_listed = len(stories)
    for story in stories[:MAX_STORIES]:
        check = StoryCheck(story_id=story.id)
        report.checks.append(check)
        record_call()
        try:
            media = await media_client.get_media(media_id=story.id)
            check.media_product_type = media.media_product_type
            check.timestamp = media.timestamp.isoformat()
        except MediaReadError as exc:
            check.media_error = _codes(exc)
        record_call()
        try:
            page = await comments_client.list_comments(ig_media_id=story.id)
            check.comments_on_first_page = len(page.data)
            cursor = ((page.paging or {}).get("cursors") or {}).get("after")
            check.has_more_comments = bool(cursor)
        except CommentsReadError as exc:
            check.comments_error = _codes(exc)
    return report


async def _run(tenant_id: UUID, connection_id: UUID) -> StoryProbeReport:
    # Imported here: the CLI needs Postgres and the credential, the probe logic does not.
    from qualify_api.config import MetaOAuthSettings
    from qualify_api.connections.credential_reader import DbCredentialReader
    from qualify_api.connections.crypto import DevEncryptor
    from qualify_api.connections.resolver import InjectingCredentialResolver
    from qualify_api.inbox.client import HttpCommentsClient
    from qualify_api.inbox.composition import production_ig_user_id_for
    from qualify_api.inbox.media_client import HttpMediaClient
    from qualify_api.inbox.repository import PostgresInboxRepository

    ig_user_id = production_ig_user_id_for(tenant_id=tenant_id, connection_id=connection_id)
    settings = MetaOAuthSettings.from_env()
    resolver = InjectingCredentialResolver(DbCredentialReader(tenant_id), DevEncryptor())
    graph_client = await resolver.client_for(connection_id, scheme=settings.graph_auth_scheme)
    repository = PostgresInboxRepository()

    def record_call() -> None:
        repository.record_call(
            tenant_id=tenant_id, connection_id=connection_id, called_at=datetime.now(UTC)
        )

    return await probe_stories(
        media_client=HttpMediaClient(graph_client=graph_client, graph_url=settings.graph_url),
        comments_client=HttpCommentsClient(graph_client=graph_client, graph_url=settings.graph_url),
        ig_user_id=ig_user_id,
        record_call=record_call,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tenant", type=UUID, required=True)
    parser.add_argument("--connection", type=UUID, required=True)
    args = parser.parse_args(argv)
    report = asyncio.run(_run(args.tenant, args.connection))
    sys.stdout.write(report.to_json() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
