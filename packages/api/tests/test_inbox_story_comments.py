"""Story comments behind the `story_comments` capability (m-24789644, B6).

Off — the default and production's state until R1 — nothing changes: `/stories` is never
read and a story is `unsupported_surface`. On: the picker adds the account's stories, a
story can be monitored, and its comments travel the same `/comments` contract as a Reel's,
so sentiment and intent see them as ordinary pending comments. Plus the HTTP contract of
`GET /{ig-user-id}/stories`, the deployment switch, and the R1 probe's report.

Offline against fakes and `MemoryInboxRepository`, except the last section (`db`), which
follows one story comment from the sync into the sentiment and intent queues in Postgres.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from qualify_shared.social.ig_shapes import COMMENTS_EDGE_PERMISSIONS, IGComment, IGCommentsPage

from qualify_api.config import MetaOAuthSettings
from qualify_api.connections.resolver import _InjectedAuthClient
from qualify_api.inbox import composition
from qualify_api.inbox.client import CommentsReadError
from qualify_api.inbox.media_client import (
    MEDIA_FIELDS,
    HttpMediaClient,
    MediaReadError,
    MediaSummary,
)
from qualify_api.inbox.repository import MemoryInboxRepository
from qualify_api.inbox.service import (
    MONITORABLE_MEDIA_PRODUCT_TYPES,
    STORY_MEDIA_PRODUCT_TYPE,
    InboxService,
    MediaNotEligible,
)
from qualify_api.inbox.story_probe import MAX_STORIES, probe_stories

TENANT = UUID("f2470000-0000-4000-8000-000000000001")
CONNECTION = UUID("f2470000-0000-4000-8000-000000000002")
NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=UTC)
TOKEN = "SUPER_SECRET_STORY_TOKEN"
GRAPH = "https://graph.facebook.com/v21.0"


class FakeComments:
    def __init__(
        self,
        comments_by_media: dict[str, list[IGComment]] | None = None,
        errors: dict[str, Exception] | None = None,
    ) -> None:
        self._comments = comments_by_media or {}
        self._errors = errors or {}
        self.calls: list[str] = []

    async def list_comments(self, *, ig_media_id: str, after: str | None = None) -> IGCommentsPage:
        self.calls.append(ig_media_id)
        if ig_media_id in self._errors:
            raise self._errors[ig_media_id]
        return IGCommentsPage(data=self._comments.get(ig_media_id, []))


class FakeMedia:
    def __init__(
        self,
        media: list[MediaSummary] | None = None,
        stories: list[MediaSummary] | None = None,
        stories_error: Exception | None = None,
    ) -> None:
        self._media = media or []
        self._stories = stories or []
        self._stories_error = stories_error
        self.story_reads = 0
        self.get_calls: list[str] = []

    async def list_recent_media(
        self, *, ig_user_id: str, since: datetime
    ) -> tuple[MediaSummary, ...]:
        return tuple(m for m in self._media if m.timestamp >= since)

    async def list_recent_stories(self, *, ig_user_id: str) -> tuple[MediaSummary, ...]:
        self.story_reads += 1
        if self._stories_error is not None:
            raise self._stories_error
        return tuple(self._stories)

    async def get_media(self, *, media_id: str) -> MediaSummary:
        self.get_calls.append(media_id)
        for media in [*self._media, *self._stories]:
            if media.id == media_id:
                return media
        raise MediaReadError("no such media")


def _summary(media_id: str, product: str, media_type: str = "IMAGE") -> MediaSummary:
    return MediaSummary(
        id=media_id,
        timestamp=NOW - timedelta(hours=3),
        media_product_type=product,
        media_type=media_type,
    )


def _service(
    repo: MemoryInboxRepository,
    *,
    media: FakeMedia,
    comments: FakeComments | None = None,
    story_comments: bool,
) -> InboxService:
    return InboxService(
        repository=repo,
        comments_client=comments or FakeComments(),
        media_client=media,
        granted_scopes=frozenset(COMMENTS_EDGE_PERMISSIONS),
        story_comments=story_comments,
    )


async def _candidates(service: InboxService) -> set[str]:
    found = await service.list_candidate_media(
        tenant_id=TENANT, connection_id=CONNECTION, ig_user_id="ig", now=NOW
    )
    return {c.external_media_id for c in found}


async def _activate(service: InboxService, media_id: str) -> None:
    await service.set_media_monitored(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        external_media_id=media_id,
        monitored=True,
        now=NOW,
    )


# --- off: nothing changes ----------------------------------------------------------------


def test_the_default_surfaces_still_exclude_stories() -> None:
    assert STORY_MEDIA_PRODUCT_TYPE not in MONITORABLE_MEDIA_PRODUCT_TYPES


async def test_off_the_picker_never_reads_stories() -> None:
    media = FakeMedia(media=[_summary("post", "FEED")], stories=[_summary("story", "STORY")])

    found = await _candidates(_service(MemoryInboxRepository(), media=media, story_comments=False))

    assert found == {"post"}
    assert media.story_reads == 0


async def test_off_a_story_is_still_refused_as_unsupported() -> None:
    media = FakeMedia(stories=[_summary("story", "STORY")])

    with pytest.raises(MediaNotEligible) as exc_info:
        await _activate(
            _service(MemoryInboxRepository(), media=media, story_comments=False), "story"
        )

    assert exc_info.value.reason == "unsupported_surface"


def test_the_service_defaults_to_off() -> None:
    service = InboxService(
        repository=MemoryInboxRepository(),
        comments_client=FakeComments(),
        media_client=FakeMedia(),
    )
    assert service._story_comments is False


# --- on: stories become ordinary monitored media ------------------------------------------


async def test_on_the_picker_adds_the_stories_once_and_still_no_ads() -> None:
    media = FakeMedia(
        media=[_summary("post", "FEED"), _summary("reel", "REELS", "VIDEO"), _summary("ad", "AD")],
        stories=[_summary("story", "STORY", "VIDEO"), _summary("post", "FEED")],
    )

    service = _service(MemoryInboxRepository(), media=media, story_comments=True)
    found = await service.list_candidate_media(
        tenant_id=TENANT, connection_id=CONNECTION, ig_user_id="ig", now=NOW
    )

    assert [c.external_media_id for c in found] == ["post", "reel", "story"]
    story = next(c for c in found if c.external_media_id == "story")
    assert (story.media_product_type, story.is_monitored) == ("STORY", False)


async def test_on_a_failed_stories_read_keeps_the_rest_of_the_picker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = MediaReadError(
        "GET /ig/stories failed with HTTP 400", http_status=400, platform_code=10
    )
    media = FakeMedia(media=[_summary("post", "FEED")], stories_error=error)

    with caplog.at_level(logging.WARNING, logger="qualify_api.inbox.service"):
        found = await _candidates(
            _service(MemoryInboxRepository(), media=media, story_comments=True)
        )

    assert found == {"post"}
    assert "inbox.stories.read_failed status=400 code=10" in caplog.text


async def test_on_a_story_is_monitored_and_its_comments_sync_like_a_reel_s() -> None:
    repo = MemoryInboxRepository()
    media = FakeMedia(stories=[_summary("story", "STORY", "VIDEO")])
    comments = FakeComments(
        {"story": [IGComment.model_validate({"id": "c-story", "text": "¿precio?"})]}
    )
    service = _service(repo, media=media, comments=comments, story_comments=True)

    await _activate(service, "story")
    summary = await service.sync_comments(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)

    row = repo.get_monitored_media(
        tenant_id=TENANT, connection_id=CONNECTION, external_media_id="story"
    )
    assert row is not None and row.media_product_type == "STORY"
    assert comments.calls == ["story"]  # the same /comments edge, on the story id
    assert summary.new_comments == 1


async def test_on_ads_are_still_refused() -> None:
    media = FakeMedia(media=[_summary("ad", "AD")])

    with pytest.raises(MediaNotEligible) as exc_info:
        await _activate(_service(MemoryInboxRepository(), media=media, story_comments=True), "ad")

    assert exc_info.value.reason == "unsupported_surface"


# --- GET /{ig-user-id}/stories: the HTTP contract -----------------------------------------


def _http(handler) -> HttpMediaClient:
    settings = MetaOAuthSettings(
        app_id="app", app_secret="secret", redirect_uri="https://x/cb", state_secret="s"
    )
    return HttpMediaClient(
        graph_client=_InjectedAuthClient(
            TOKEN, scheme=settings.graph_auth_scheme, transport=httpx.MockTransport(handler)
        ),
        graph_url=GRAPH,
    )


async def test_stories_are_read_from_their_own_edge_with_the_media_fields_and_paged() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if "after" not in request.url.params:
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "s1",
                            "timestamp": "2026-10-21T09:00:00+0000",
                            "media_product_type": "STORY",
                            "media_type": "VIDEO",
                        }
                    ],
                    "paging": {"cursors": {"after": "CUR"}},
                },
            )
        return httpx.Response(
            200,
            json={"data": [{"id": "s2", "timestamp": "2026-10-21T10:00:00+0000"}]},
        )

    stories = await _http(handler).list_recent_stories(ig_user_id="17841400000000000")

    assert [s.id for s in stories] == ["s1", "s2"]
    assert stories[0].media_product_type == "STORY"
    assert all(url.path == "/v21.0/17841400000000000/stories" for url in seen)
    assert seen[0].params["fields"] == MEDIA_FIELDS
    assert "since" not in seen[0].params  # the edge is already the last 24 hours
    assert seen[1].params["after"] == "CUR"


async def test_a_refused_stories_read_is_a_media_read_error_without_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"code": 10, "message": f"needs permission {TOKEN}"}}
        )

    with pytest.raises(MediaReadError) as exc_info:
        await _http(handler).list_recent_stories(ig_user_id="ig")

    assert (exc_info.value.http_status, exc_info.value.platform_code) == (400, 10)
    assert TOKEN not in str(exc_info.value)


# --- the deployment switch ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "enabled"),
    [("on", True), ("ON", True), (" on ", True), ("off", False), ("", False), ("1", False)],
)
def test_only_on_turns_the_capability_on(
    monkeypatch: pytest.MonkeyPatch, raw: str, enabled: bool
) -> None:
    monkeypatch.setenv(composition.STORY_COMMENTS_ENV, raw)
    assert composition.story_comments_enabled() is enabled


def test_unset_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(composition.STORY_COMMENTS_ENV, raising=False)
    assert composition.story_comments_enabled() is False


def test_production_wires_the_switch_into_the_service() -> None:
    import inspect

    source = inspect.getsource(composition.production_inbox_service_for)
    assert "story_comments=story_comments_enabled()" in source


# --- the R1 probe ---------------------------------------------------------------------------


async def _probe(media: FakeMedia, comments: FakeComments) -> tuple[dict, int]:
    calls: list[None] = []
    report = await probe_stories(
        media_client=media,
        comments_client=comments,
        ig_user_id="ig",
        record_call=lambda: calls.append(None),
    )
    return json.loads(report.to_json()), len(calls)


async def test_the_probe_reports_served_comments_without_their_text() -> None:
    media = FakeMedia(stories=[_summary("s1", "STORY", "VIDEO")])
    comments = FakeComments(
        {"s1": [IGComment.model_validate({"id": "c1", "text": "texto privado"})]}
    )

    report, calls = await _probe(media, comments)

    assert report["verdict"] == "comments_served"
    assert report["checks"][0]["comments_on_first_page"] == 1
    assert report["checks"][0]["media_product_type"] == "STORY"
    assert calls == 3  # /stories, /{id}, /{id}/comments — each logged before it fires
    assert "texto privado" not in json.dumps(report)


async def test_the_probe_reports_a_refused_comments_edge_with_its_codes() -> None:
    media = FakeMedia(stories=[_summary("s1", "STORY")])
    comments = FakeComments(
        errors={"s1": CommentsReadError("x", http_status=400, platform_code=100)}
    )

    report, _calls = await _probe(media, comments)

    assert report["verdict"] == "comments_refused"
    assert report["checks"][0]["comments_error"] == {
        "http_status": 400,
        "code": 100,
        "subcode": None,
    }


@pytest.mark.parametrize(
    ("media", "verdict"),
    [
        (
            FakeMedia(stories_error=MediaReadError("x", http_status=403, platform_code=10)),
            "stories_not_listed",
        ),
        (FakeMedia(), "no_live_story"),
        (FakeMedia(stories=[_summary("s1", "STORY")]), "comments_empty"),
    ],
)
async def test_the_probe_names_every_other_outcome(media: FakeMedia, verdict: str) -> None:
    report, _calls = await _probe(media, FakeComments())
    assert report["verdict"] == verdict


async def test_the_probe_checks_at_most_a_few_stories() -> None:
    media = FakeMedia(stories=[_summary(f"s{i}", "STORY") for i in range(MAX_STORIES + 4)])

    report, calls = await _probe(media, FakeComments())

    assert report["stories_listed"] == MAX_STORIES + 4
    assert len(report["checks"]) == MAX_STORIES
    assert calls == 1 + 2 * MAX_STORIES
