"""QUA-152 — "Actualizar menciones" re-reads the mentions from their network and stores
what changed. Offline: the content client and the repository are swapped for a scripted
fake and `MemoryMentionsRepository` (the Postgres twin of every rule here is in
`test_mentions_paging_db.py`).

What is pinned:
- D1: the whole scope (account + period, every page) is refreshed, in bounded runs that
  report what is left; throttling stops a run; transient failures are retried.
- D2: an omitted field keeps the stored value; an explicit one — `like_count=0` — is
  stored; a failed read stores nothing.
- D4: the link is independent of the content read and of its persistence.
- Idempotency, partial failures and tenant isolation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from qualify_shared.social.ig_shapes import MentionedComment, MentionedMedia

from qualify_api.mentions import composition
from qualify_api.mentions.meta_client import MentionedContentReadError
from qualify_api.mentions.repository import (
    ENRICHMENT_FAILED,
    MemoryMentionsRepository,
    MentionQuery,
    MentionRecord,
    NewMention,
)
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution

TENANT = UUID("11111111-1111-4111-8111-111111111111")
OTHER_TENANT = UUID("99999999-9999-4999-8999-999999999999")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
OTHER_CONNECTION = UUID("88888888-8888-4888-8888-888888888888")
IG_USER = "ig-user-1"
POSTED = datetime.now(UTC) - timedelta(days=2)
SCOPE = MentionQuery(since=datetime.now(UTC) - timedelta(days=14))

Answer = MentionedMedia | MentionedComment | Exception


def _media(media_id: str, **overrides: object) -> MentionedMedia:
    values: dict = {
        "id": media_id,
        "caption": f"hola @marca {media_id}",
        "media_type": "IMAGE",
        "like_count": 5,
        "timestamp": POSTED,
        "username": "autora",
    }
    values.update(overrides)
    return MentionedMedia(**values)


class ScriptedClient:
    """Answers per media/comment id, consumed in order (the last answer repeats)."""

    def __init__(
        self,
        answers: dict[str, list[Answer]] | None = None,
        *,
        default: Answer | None = None,
        permalink: str | None = "https://www.instagram.com/p/NEW/",
        permalink_error: Exception | None = None,
        usage_percent: int = 0,
    ) -> None:
        self._answers = answers or {}
        self._default = default
        self._permalink = permalink
        self._permalink_error = permalink_error
        self.usage_percent = usage_percent
        self.calls: list[str] = []
        self.permalink_calls: list[str] = []
        self.closed = 0

    async def aclose(self) -> None:
        self.closed += 1

    def _next(self, key: str) -> Answer:
        self.calls.append(key)
        queue = self._answers.get(key)
        if queue:
            answer = queue.pop(0) if len(queue) > 1 else queue[0]
        else:
            answer = self._default if self._default is not None else _media(key)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def get_mentioned_media(self, *, ig_user_id: str, media_id: str) -> MentionedMedia:
        answer = self._next(media_id)
        assert isinstance(answer, MentionedMedia)
        return answer

    async def get_mentioned_comment(self, *, ig_user_id: str, comment_id: str) -> MentionedComment:
        answer = self._next(comment_id)
        assert isinstance(answer, MentionedComment)
        return answer

    async def get_mentioned_permalink(
        self, *, ig_user_id: str, media_id: str, comment_id: str | None
    ) -> str | None:
        self.permalink_calls.append(comment_id or media_id)
        if self._permalink_error is not None:
            raise self._permalink_error
        return self._permalink


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch) -> MemoryMentionsRepository:
    memory = MemoryMentionsRepository()
    monkeypatch.setattr(composition, "production_mentions_repository", lambda: memory)
    monkeypatch.setattr(composition, "REFRESH_BACKOFF_SECONDS", (0.0, 0.0))
    return memory


def _use(monkeypatch: pytest.MonkeyPatch, client: ScriptedClient) -> None:
    async def fake_client_for(*, tenant_id: UUID, connection_id: UUID):
        return client, IG_USER

    monkeypatch.setattr(composition, "_content_client_for", fake_client_for)


def _store(
    repo: MemoryMentionsRepository,
    media_id: str,
    *,
    tenant_id: UUID = TENANT,
    connection_id: UUID = CONNECTION,
    comment_id: str | None = None,
    like_count: int | None = 3,
    permalink: str | None = None,
    posted: datetime = POSTED,
) -> UUID:
    mention_id, _ = repo.upsert_mention(
        NewMention(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_account_id=IG_USER,
            media_id=media_id,
            comment_id=comment_id,
            caption=None if comment_id else f"hola @marca {media_id}",
            text=f"comentario {comment_id}" if comment_id else None,
            author_username=None if comment_id else "autora",
            media_type=None if comment_id else "IMAGE",
            like_count=like_count,
            content_posted_at=posted,
            enrichment_status="ENRICHED",
            permalink=permalink,
        )
    )
    return mention_id


def _record(repo: MemoryMentionsRepository, mention_id: UUID) -> MentionRecord:
    page = repo.list_mentions_page(
        tenant_id=TENANT,
        version=composition.current_mention_analysis_version(),
        query=MentionQuery(),
        page=1,
        page_size=1000,
    )
    return next(row for row in page.rows if row.id == mention_id)


# ------------------------------------------------------------------ D2 — persistence


async def test_likes_going_from_positive_to_zero_are_stored(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    mention_id = _store(repo, "m1", like_count=8)
    _use(monkeypatch, ScriptedClient({"m1": [_media("m1", like_count=0)]}))

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    assert report.refreshed == 1
    assert _record(repo, mention_id).like_count == 0


async def test_likes_going_from_zero_to_one_are_stored(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    mention_id = _store(repo, "m1", like_count=0)
    _use(monkeypatch, ScriptedClient({"m1": [_media("m1", like_count=1)]}))

    await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    assert _record(repo, mention_id).like_count == 1


async def test_fields_the_network_omits_keep_their_stored_values(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    mention_id = _store(repo, "m1", like_count=8, permalink="https://www.instagram.com/p/OLD/")
    before = _record(repo, mention_id)
    omitted = _media(
        "m1", caption=None, username=None, media_type=None, like_count=None, timestamp=None
    )
    _use(monkeypatch, ScriptedClient({"m1": [omitted]}, permalink=None))

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    after = _record(repo, mention_id)
    assert report.refreshed == 1
    assert (after.caption, after.author_username, after.media_type) == (
        before.caption,
        before.author_username,
        before.media_type,
    )
    assert (after.like_count, after.content_posted_at, after.permalink) == (
        8,
        POSTED,
        "https://www.instagram.com/p/OLD/",
    )


async def test_text_author_date_type_and_link_changes_are_stored(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    mention_id = _store(repo, "m1")
    new_date = POSTED + timedelta(hours=1)
    changed = _media(
        "m1", caption="editado", username="otra", media_type="VIDEO", timestamp=new_date
    )
    _use(monkeypatch, ScriptedClient({"m1": [changed]}))

    await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    after = _record(repo, mention_id)
    assert (after.caption, after.author_username, after.media_type) == ("editado", "otra", "VIDEO")
    assert after.content_posted_at == new_date
    assert after.permalink == "https://www.instagram.com/p/NEW/"


async def test_a_comment_mention_refreshes_its_own_text_and_likes(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    mention_id = _store(repo, "m1", comment_id="c1", like_count=0)
    fresh = MentionedComment(id="c1", text="comentario editado", like_count=2, timestamp=POSTED)
    _use(monkeypatch, ScriptedClient({"c1": [fresh]}))

    await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    after = _record(repo, mention_id)
    assert (after.text, after.like_count, after.author_username) == ("comentario editado", 2, None)


async def test_a_failed_read_stores_nothing(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    mention_id = _store(repo, "m1", like_count=8)
    gone = MentionedContentReadError("gone", http_status=400, platform_code=100)
    _use(monkeypatch, ScriptedClient({"m1": [gone]}))

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    after = _record(repo, mention_id)
    assert (report.refreshed, report.failed, report.complete) == (0, 1, False)
    assert (after.like_count, after.caption) == (8, "hola @marca m1")


async def test_two_refreshes_in_a_row_are_idempotent(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    mention_id = _store(repo, "m1")
    _use(monkeypatch, ScriptedClient({"m1": [_media("m1", like_count=9)]}))

    for _ in range(2):
        await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    page = repo.list_mentions_page(
        tenant_id=TENANT,
        version=composition.current_mention_analysis_version(),
        query=MentionQuery(),
        page=1,
    )
    assert page.counts.total == 1
    assert _record(repo, mention_id).like_count == 9


# ------------------------------------------------------------------ D4 — the link


async def test_a_failing_link_never_blocks_the_content(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    mention_id = _store(repo, "m1", like_count=1)
    client = ScriptedClient(
        {"m1": [_media("m1", like_count=4)]}, permalink_error=RuntimeError("network down")
    )
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    after = _record(repo, mention_id)
    assert report.refreshed == 1
    assert (after.like_count, after.permalink) == (4, None)


async def test_a_stored_link_is_not_requested_again(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    mention_id = _store(repo, "m1", permalink="https://www.instagram.com/p/OLD/")
    client = ScriptedClient()
    _use(monkeypatch, client)

    await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    assert client.permalink_calls == []
    assert _record(repo, mention_id).permalink == "https://www.instagram.com/p/OLD/"


async def test_ingestion_keeps_the_mention_when_the_link_call_breaks(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    _use(monkeypatch, ScriptedClient(permalink_error=RuntimeError("network down")))
    resolution = TenantResolution(
        outcome=ResolutionOutcome.RESOLVED, tenant_id=TENANT, connection_id=CONNECTION
    )

    mention_id = await composition.ingest_mention(
        media_id="m1", comment_id=None, resolution=resolution
    )

    assert mention_id is not None
    record = _record(repo, mention_id)
    assert (record.enrichment_status, record.permalink, record.like_count) == ("ENRICHED", None, 5)


# ------------------------------------------------------------------ D1 — the whole scope


async def test_every_page_of_the_scope_is_refreshed(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    ids = [_store(repo, f"m{i}", like_count=0) for i in range(30)]  # 3 pages of 12
    client = ScriptedClient(default=None)
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.in_scope, report.refreshed, report.complete) == (30, 30, True)
    assert sorted(client.calls) == sorted(f"m{i}" for i in range(30))
    assert all(_record(repo, mention_id).like_count == 5 for mention_id in ids)


async def test_the_scope_is_the_period_and_account_never_other_tenants(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    _store(repo, "inside")
    _store(repo, "old", posted=datetime.now(UTC) - timedelta(days=40))
    _store(repo, "other-account", connection_id=OTHER_CONNECTION)
    _store(repo, "other-tenant", tenant_id=OTHER_TENANT)
    client = ScriptedClient()
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(
        tenant_id=TENANT, scope=MentionQuery(connection_id=CONNECTION, since=SCOPE.since)
    )

    assert client.calls == ["inside"]
    assert (report.in_scope, report.refreshed) == (1, 1)


async def test_a_capped_run_reports_the_rest_as_pending_and_the_next_run_continues(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    for i in range(25):
        _store(repo, f"m{i}")
    client = ScriptedClient()
    _use(monkeypatch, client)

    first = await composition.refresh_mentions_in_scope(
        tenant_id=TENANT, scope=SCOPE, max_mentions=10
    )
    second = await composition.refresh_mentions_in_scope(
        tenant_id=TENANT, scope=SCOPE, max_mentions=10
    )
    third = await composition.refresh_mentions_in_scope(
        tenant_id=TENANT, scope=SCOPE, max_mentions=10
    )

    assert (first.refreshed, first.not_attempted, first.complete) == (10, 15, False)
    assert (second.refreshed, second.already_fresh, second.not_attempted) == (10, 10, 5)
    assert (third.refreshed, third.already_fresh, third.complete) == (5, 20, True)
    assert len(client.calls) == len(set(client.calls)) == 25  # nobody read twice


async def test_recently_refreshed_mentions_are_not_requested_again(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    ids = [_store(repo, f"m{i}") for i in range(3)]
    client = ScriptedClient()
    _use(monkeypatch, client)
    await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=tuple(ids[:2]))
    client.calls.clear()

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert client.calls == ["m2"]
    assert (report.refreshed, report.already_fresh, report.complete) == (1, 2, True)


async def test_partial_errors_keep_their_data_and_leave_the_run_incomplete(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    ok_id = _store(repo, "ok", like_count=0)
    gone_id = _store(repo, "gone", like_count=7)
    gone = MentionedContentReadError("deleted", http_status=400, platform_code=100)
    _use(monkeypatch, ScriptedClient({"gone": [gone]}))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.refreshed, report.failed, report.complete) == (1, 1, False)
    assert _record(repo, ok_id).like_count == 5
    assert _record(repo, gone_id).like_count == 7
    assert _record(repo, gone_id).enrichment_status != ENRICHMENT_FAILED


async def test_a_failed_mention_goes_last_in_the_next_run(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    for name in ("a", "b", "c"):
        _store(repo, name)
    gone = MentionedContentReadError("deleted", http_status=400, platform_code=100)
    client = ScriptedClient({"a": [gone]})
    _use(monkeypatch, client)
    await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE, max_mentions=1)
    client.calls.clear()

    await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE, max_mentions=2)

    assert sorted(client.calls) == ["b", "c"]  # "a" was attempted last: it waits its turn


async def test_a_transient_failure_is_retried(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    mention_id = _store(repo, "m1", like_count=0)
    flaky = MentionedContentReadError("server", http_status=500)
    client = ScriptedClient({"m1": [flaky, _media("m1", like_count=3)]})
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.refreshed, report.failed) == (1, 0)
    assert client.calls == ["m1", "m1"]
    assert _record(repo, mention_id).like_count == 3


async def test_retries_are_bounded(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    _store(repo, "m1")
    client = ScriptedClient({"m1": [MentionedContentReadError("server", http_status=503)]})
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert report.failed == 1
    assert len(client.calls) == composition.REFRESH_RETRIES + 1


async def test_a_content_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    _store(repo, "m1")
    client = ScriptedClient(
        {"m1": [MentionedContentReadError("comments off", http_status=400, platform_code=10)]}
    )
    _use(monkeypatch, client)

    await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert client.calls == ["m1"]


async def test_throttling_stops_the_run_and_reports_what_is_left(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    for i in range(10):
        _store(repo, f"m{i}")
    monkeypatch.setattr(composition, "REFRESH_CONCURRENCY", 1)
    throttled = MentionedContentReadError("limit", http_status=400, platform_code=80002)
    answers = {f"m{i}": [throttled] for i in range(10)}
    client = ScriptedClient(answers)
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert len(client.calls) == 1  # never retried, nothing more requested
    assert (report.rate_limited, report.not_attempted, report.complete) == (True, 10, False)


async def test_high_reported_usage_pauses_the_run(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    for i in range(5):
        _store(repo, f"m{i}")
    monkeypatch.setattr(composition, "REFRESH_CONCURRENCY", 1)
    client = ScriptedClient(usage_percent=composition.REFRESH_USAGE_STOP_PERCENT)
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.refreshed, report.not_attempted) == (1, 4)
    assert (report.usage_paused, report.rate_limited) == (True, False)  # not a throttle


async def test_a_connection_without_a_client_fails_its_mentions_only(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    _store(repo, "readable")
    _store(repo, "unreadable", connection_id=OTHER_CONNECTION)
    client = ScriptedClient()

    async def client_for(*, tenant_id: UUID, connection_id: UUID):
        return (client, IG_USER) if connection_id == CONNECTION else None

    monkeypatch.setattr(composition, "_content_client_for", client_for)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.refreshed, report.credential_failed, report.failed) == (1, 1, 0)
    assert client.calls == ["readable"]


async def test_the_visible_page_refresh_never_touches_another_tenant(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    foreign = _store(repo, "m1", tenant_id=OTHER_TENANT, like_count=3)
    client = ScriptedClient()
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(foreign,))

    assert (report.in_scope, report.refreshed, client.calls) == (0, 0, [])


# ------------------------------------------------------------------ review follow-ups


async def test_a_mention_that_failed_in_the_visible_pass_is_not_requested_again(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    gone_id = _store(repo, "gone")
    _store(repo, "ok")
    gone = MentionedContentReadError("deleted", http_status=400, platform_code=100)
    client = ScriptedClient({"gone": [gone]})
    _use(monkeypatch, client)
    await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(gone_id,))
    client.calls.clear()

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert client.calls == ["ok"]  # same click: the failed one is not re-read
    assert (report.refreshed, report.failed, report.complete) == (1, 1, False)


async def test_a_body_that_does_not_match_the_contract_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    _store(repo, "m1")
    client = ScriptedClient({"m1": [MentionedContentReadError("no mentioned_media object")]})
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (client.calls, report.failed) == (["m1"], 1)


async def test_a_network_error_is_retried_but_an_unexpected_one_is_not(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    import httpx

    _store(repo, "net")
    _store(repo, "bug")
    client = ScriptedClient(
        {
            "net": [httpx.ConnectError("down"), _media("net", like_count=2)],
            "bug": [ValueError("unexpected")],
        }
    )
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert sorted(client.calls) == ["bug", "net", "net"]
    assert (report.refreshed, report.failed) == (1, 1)


def test_repository_calls_never_run_on_the_event_loop() -> None:
    """The refresh runs inside the Reflex backend's single event loop: every blocking
    repository call goes through `asyncio.to_thread` (review finding, QUA-152)."""
    import inspect

    source = inspect.getsource(composition._refresh_targets)
    assert "repo.refresh_content(" not in source
    assert source.count("asyncio.to_thread(") >= 2
    for function in (composition.refresh_mentions_content, composition.refresh_mentions_in_scope):
        assert "asyncio.to_thread(" in inspect.getsource(function)


# ------------------------------------------------------------------ audit round 2


async def test_every_client_of_a_run_is_closed(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    for i in range(3):
        _store(repo, f"m{i}")
    client = ScriptedClient({"m1": [MentionedContentReadError("gone", http_status=400)]})
    _use(monkeypatch, client)

    await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert client.closed == 1  # one client per connection and run, closed at the end


async def test_a_client_is_closed_even_when_storing_breaks(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    _store(repo, "m1")
    client = ScriptedClient()
    _use(monkeypatch, client)

    def broken_store(**kwargs: object) -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(repo, "refresh_content", broken_store)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.failed, client.closed) == (1, 1)


async def test_ingestion_closes_its_client(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    client = ScriptedClient()
    _use(monkeypatch, client)
    resolution = TenantResolution(
        outcome=ResolutionOutcome.RESOLVED, tenant_id=TENANT, connection_id=CONNECTION
    )

    await composition.ingest_mention(media_id="m1", comment_id=None, resolution=resolution)

    assert client.closed == 1


async def test_a_broken_credential_is_resolved_once_per_run(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    for i in range(5):
        _store(repo, f"m{i}")
    attempts: list[UUID] = []

    async def failing_client_for(*, tenant_id: UUID, connection_id: UUID):
        attempts.append(connection_id)
        raise LookupError("credential revoked")

    monkeypatch.setattr(composition, "_content_client_for", failing_client_for)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert attempts == [CONNECTION]  # not once per mention
    assert (report.credential_failed, report.failed, report.refreshed) == (5, 0, 0)
    assert report.complete is False


async def test_a_throttled_link_read_stops_the_run_but_keeps_the_content(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    for i in range(4):
        _store(repo, f"m{i}", like_count=0)
    monkeypatch.setattr(composition, "REFRESH_CONCURRENCY", 1)
    client = ScriptedClient(
        permalink_error=MentionedContentReadError("limit", http_status=400, platform_code=4)
    )
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert len(client.calls) == 1  # nothing more requested after the throttle
    assert (report.refreshed, report.not_attempted, report.rate_limited) == (1, 3, True)


async def test_a_run_that_cannot_be_planned_is_reported_as_such(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    def broken_plan(**kwargs: object) -> object:
        raise RuntimeError("db down")

    monkeypatch.setattr(repo, "plan_scope_refresh", broken_plan)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert report.planning_failed is True
    assert (report.in_scope, report.not_attempted) == (0, 0)
    assert report.complete is False  # a run that did nothing is never complete


def test_the_credential_read_runs_in_a_worker_thread() -> None:
    import inspect

    source = inspect.getsource(composition._content_client_for)
    assert "asyncio.to_thread(" in source
    assert "_resolve_graph_client_blocking" in source
    assert "resolver.client_for" not in source  # never awaited on the event loop


def test_a_client_built_in_the_worker_thread_works_on_the_callers_loop() -> None:
    """The pattern `_resolve_graph_client_blocking` relies on, with httpx's REAL transport
    and connection pool (not a mock): a client created under a short-lived loop in another
    thread is usable concurrently, reuses its pool, and closes on the caller's loop. Guards
    an httpx/httpcore upgrade that would bind the pool to the loop at construction."""
    import asyncio
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import httpx

    class Ok(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 — http.server's naming
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Ok)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"

    async def build() -> httpx.AsyncClient:
        return httpx.AsyncClient()

    async def main() -> tuple[set[int], bool]:
        client = await asyncio.to_thread(lambda: asyncio.run(build()))
        responses = await asyncio.gather(*(client.get(url) for _ in range(6)))
        responses += [await client.get(url)]  # a pooled connection reused afterwards
        await client.aclose()
        return {r.status_code for r in responses}, client.is_closed

    try:
        assert asyncio.run(main()) == ({200}, True)
    finally:
        server.shutdown()


async def test_an_account_problem_is_not_stamped_on_the_mentions(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    _store(repo, "m1")

    async def no_client(*, tenant_id: UUID, connection_id: UUID) -> None:
        return None

    monkeypatch.setattr(composition, "_content_client_for", no_client)
    first = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)
    client = ScriptedClient()
    _use(monkeypatch, client)  # the credential is fixed

    second = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert first.credential_failed == 1
    assert (second.refreshed, client.calls) == (1, ["m1"])  # retried at once, not "recent"


# ------------------------------------------------------------------ deleted on the network

DELETED = MentionedContentReadError("deleted", http_status=400, platform_code=100)
GONE = MentionedContentReadError(
    "does not exist", http_status=400, platform_code=100, platform_subcode=33
)


def _visible_ids(repo: MemoryMentionsRepository, tenant_id: UUID = TENANT) -> set[UUID]:
    page = repo.list_mentions_page(
        tenant_id=tenant_id,
        version=composition.current_mention_analysis_version(),
        query=MentionQuery(),
        page=1,
        page_size=1000,
    )
    return {row.id for row in page.rows}


async def test_a_deleted_mention_is_removed_and_the_run_is_complete(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    ok_id = _store(repo, "ok")
    gone_id = _store(repo, "gone")
    _use(monkeypatch, ScriptedClient({"gone": [GONE]}))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.refreshed, report.removed, report.failed, report.complete) == (1, 1, 0, True)
    assert _visible_ids(repo) == {ok_id}
    assert gone_id not in _visible_ids(repo)


async def test_a_deleted_comment_mention_is_removed_too(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    comment_id = _store(repo, "post", comment_id="c1")
    _use(monkeypatch, ScriptedClient({"c1": [GONE]}))

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(comment_id,))

    assert (report.removed, report.failed) == (1, 0)
    assert _visible_ids(repo) == set()


async def test_a_removed_mention_leaves_every_read(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    gone_id = _store(repo, "gone")
    _use(monkeypatch, ScriptedClient({"gone": [GONE]}))
    await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(gone_id,))
    version = composition.current_mention_analysis_version()

    counts = repo.summarize(
        tenant_id=TENANT, version=version, query=MentionQuery(), as_of=datetime.now(UTC)
    )
    plan = repo.plan_scope_refresh(tenant_id=TENANT, query=SCOPE, fresh_seconds=0, limit=10)

    assert counts.total == 0
    assert (plan.in_scope, plan.targets) == (0, ())
    assert repo.list_pending_for_analysis(tenant_id=TENANT, version=version) == ()
    assert repo.list_refresh_targets(tenant_id=TENANT, mention_ids=(gone_id,)) == ()
    assert repo.list_mentions(tenant_id=TENANT, connection_id=None, version=version) == ()


async def test_a_redelivered_webhook_does_not_bring_a_removed_mention_back(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    gone_id = _store(repo, "gone")
    _use(monkeypatch, ScriptedClient({"gone": [GONE]}))
    await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(gone_id,))

    again_id = _store(repo, "gone")

    assert again_id == gone_id
    assert _visible_ids(repo) == set()


async def test_only_the_does_not_exist_signature_removes_a_mention(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """Code 100 without subcode 33 also covers unrelated validation errors, and comments
    disabled or a permission refusal are not a deletion: the mention and its data stay."""
    kept = {
        "no-subcode": DELETED,
        "comments-off": MentionedContentReadError("off", http_status=400, platform_code=10),
        "not-400": MentionedContentReadError(
            "x", http_status=403, platform_code=100, platform_subcode=33
        ),
    }
    ids = {name: _store(repo, name, like_count=7) for name in kept}
    _use(monkeypatch, ScriptedClient({name: [error] for name, error in kept.items()}))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.failed) == (0, 3)
    assert _visible_ids(repo) == set(ids.values())
    assert all(_record(repo, mention_id).like_count == 7 for mention_id in ids.values())


async def test_removing_never_touches_another_tenant(repo: MemoryMentionsRepository) -> None:
    foreign = _store(repo, "m1", tenant_id=OTHER_TENANT)

    assert repo.mark_removed(tenant_id=TENANT, mention_id=foreign) is False
    assert _visible_ids(repo, OTHER_TENANT) == {foreign}


async def test_a_mention_that_cannot_be_removed_counts_as_failed(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    gone_id = _store(repo, "gone")
    _use(monkeypatch, ScriptedClient({"gone": [GONE]}))

    def broken(**_kwargs: object) -> bool:
        raise RuntimeError("db down")

    monkeypatch.setattr(repo, "mark_removed", broken)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.failed) == (0, 1)
    assert _visible_ids(repo) == {gone_id}
