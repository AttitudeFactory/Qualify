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
        account_error: Exception | None = None,
    ) -> None:
        self._answers = answers or {}
        self._default = default
        self._permalink = permalink
        self._permalink_error = permalink_error
        self.usage_percent = usage_percent
        self._account_error = account_error
        self.account_checks = 0
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

    async def account_reachable(self, *, ig_user_id: str) -> None:
        self.account_checks += 1
        if self._account_error is not None:
            raise self._account_error

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

CODE_100_ONLY = MentionedContentReadError("deleted", http_status=400, platform_code=100)
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
        "no-subcode": CODE_100_ONLY,
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


async def test_a_does_not_exist_about_the_account_removes_nothing(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """The reads are field expansions on the account's node: when the account itself is
    unreadable (unlinked, access lost), every read answers 100/33 too. That is an account
    problem — no mention is removed, and the account is checked once per run."""
    ids = {_store(repo, f"m{i}") for i in range(5)}
    client = ScriptedClient(default=GONE, account_error=GONE)
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.credential_failed) == (0, 5)
    assert _visible_ids(repo) == ids
    assert client.account_checks == 1


async def test_a_throttled_account_check_stops_the_run_without_removing(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    gone_id = _store(repo, "gone")
    throttled = MentionedContentReadError("limit", http_status=400, platform_code=4)
    _use(monkeypatch, ScriptedClient({"gone": [GONE]}, account_error=throttled))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.rate_limited, report.not_attempted) == (0, True, 1)
    assert _visible_ids(repo) == {gone_id}


async def test_the_account_is_checked_once_for_many_deleted_mentions(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    for i in range(4):
        _store(repo, f"m{i}")
    client = ScriptedClient(default=GONE)
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.remaining_scope, client.account_checks) == (4, 0, 1)


def test_removing_twice_still_counts_as_removed(repo: MemoryMentionsRepository) -> None:
    """Two runs (two tabs) can both find the same deleted mention: the second one must not
    report it as "no se pudo leer"."""
    gone_id = _store(repo, "gone")

    assert repo.mark_removed(tenant_id=TENANT, mention_id=gone_id) is True
    assert repo.mark_removed(tenant_id=TENANT, mention_id=gone_id) is True
    assert _visible_ids(repo) == set()


def test_a_successful_read_brings_a_removed_mention_back(repo: MemoryMentionsRepository) -> None:
    from qualify_api.mentions.repository import MentionContent

    gone_id = _store(repo, "gone")
    repo.mark_removed(tenant_id=TENANT, mention_id=gone_id)

    stored = repo.refresh_content(
        tenant_id=TENANT,
        mention_id=gone_id,
        content=MentionContent(
            caption=None,
            text=None,
            author_username=None,
            media_type=None,
            like_count=4,
            content_posted_at=None,
            permalink=None,
        ),
    )

    assert stored is True
    assert _visible_ids(repo) == {gone_id}


def _remove_long_ago(repo: MemoryMentionsRepository, mention_id: UUID) -> None:
    repo.mark_removed(tenant_id=TENANT, mention_id=mention_id)
    row = repo._mentions[mention_id]
    row.removed_at = row.content_refresh_attempted_at = datetime.now(UTC) - timedelta(days=2)


async def test_a_removed_mention_that_answers_again_shows_again(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """ "Ya no está disponible" can end (account public again, block lifted): spare
    capacity re-reads removed mentions, and one that answers comes back."""
    live_id = _store(repo, "live")
    back_id = _store(repo, "back")
    _remove_long_ago(repo, back_id)
    _use(monkeypatch, ScriptedClient())

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.in_scope, report.refreshed, report.restored, report.complete) == (
        1,
        1,
        1,
        True,
    )
    assert _visible_ids(repo) == {live_id, back_id}


async def test_a_removed_mention_still_unavailable_stays_out_silently(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    gone_id = _store(repo, "gone")
    _remove_long_ago(repo, gone_id)
    client = ScriptedClient({"gone": [GONE]})
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert client.calls == ["gone"]
    assert (report.in_scope, report.failed, report.restored, report.complete) == (0, 0, 0, True)
    assert _visible_ids(repo) == set()
    # Re-checked now: not again before the recheck window passes.
    client.calls.clear()
    await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)
    assert client.calls == []


async def test_removed_mentions_are_rechecked_only_with_spare_capacity(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    for name in ("a", "b"):
        _store(repo, name)
    gone_id = _store(repo, "gone")
    _remove_long_ago(repo, gone_id)
    client = ScriptedClient()
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(
        tenant_id=TENANT, scope=SCOPE, max_mentions=2
    )

    assert sorted(client.calls) == ["a", "b"]
    assert (report.restored, report.not_attempted) == (0, 0)


async def test_a_recently_removed_mention_is_not_rechecked(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    gone_id = _store(repo, "gone")
    repo.mark_removed(tenant_id=TENANT, mention_id=gone_id)
    client = ScriptedClient()
    _use(monkeypatch, client)

    await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert client.calls == []


async def test_a_failing_account_check_is_a_plain_failure_never_a_removal(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """A network blip on the account check (retried, then given up) proves nothing:
    the mention is kept and asked again later — not blamed on the account."""
    gone_id = _store(repo, "gone")
    server = MentionedContentReadError("server", http_status=503)
    _use(monkeypatch, ScriptedClient({"gone": [GONE]}, account_error=server))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.credential_failed, report.failed) == (0, 0, 1)
    assert _visible_ids(repo) == {gone_id}


async def test_an_expired_token_on_the_account_check_is_an_account_problem(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    gone_id = _store(repo, "gone")
    expired = MentionedContentReadError("expired", http_status=401, platform_code=190)
    _use(monkeypatch, ScriptedClient({"gone": [GONE]}, account_error=expired))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.credential_failed) == (0, 1)
    assert _visible_ids(repo) == {gone_id}


def test_inbox_and_mentions_share_one_missing_object_signature() -> None:
    from qualify_api.inbox.client import CommentsReadError
    from qualify_api.inbox.service import _is_missing_media_error
    from qualify_api.mentions.meta_client import is_gone

    for status, code, subcode in ((400, 100, 33), (400, 100, None), (403, 100, 33)):
        inbox = CommentsReadError(
            "x", http_status=status, platform_code=code, platform_subcode=subcode
        )
        mention = MentionedContentReadError(
            "x", http_status=status, platform_code=code, platform_subcode=subcode
        )
        assert _is_missing_media_error(inbox) == is_gone(mention)


async def test_rechecks_respect_the_usage_pause(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    for i in range(5):
        _remove_long_ago(repo, _store(repo, f"r{i}"))
    monkeypatch.setattr(composition, "REFRESH_CONCURRENCY", 1)
    client = ScriptedClient(usage_percent=composition.REFRESH_USAGE_STOP_PERCENT)
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert len(client.calls) == 1  # optional work stops at the limit too
    assert report.restored == 1


async def test_a_throttled_recheck_never_turns_the_run_into_a_limited_one(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """Rechecks run only after every live mention is done, and a throttling answer there
    just ends the rechecks: the person is not told to retry for work they never asked."""
    live_ids = {_store(repo, f"m{i}") for i in range(3)}
    for i in range(3):
        _remove_long_ago(repo, _store(repo, f"r{i}"))
    throttled = MentionedContentReadError("limit", http_status=400, platform_code=4)
    client = ScriptedClient({f"r{i}": [throttled] for i in range(3)})
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.refreshed, report.rate_limited, report.complete) == (3, False, True)
    assert set(client.calls[:3]) == {"m0", "m1", "m2"}  # live first
    assert _visible_ids(repo) == live_ids


async def test_an_unknown_account_answer_is_asked_again_for_the_next_mention(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    for name in ("a", "b"):
        _store(repo, name)
    monkeypatch.setattr(composition, "REFRESH_CONCURRENCY", 1)
    server = MentionedContentReadError("server", http_status=503)
    client = ScriptedClient(default=GONE, account_error=server)
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert report.failed == 2
    assert client.account_checks == 2 * (composition.REFRESH_RETRIES + 1)  # not cached


class _ReadMeanwhileClient(ScriptedClient):
    """Another tab (or the comments webhook) stores a successful read WHILE this run's
    read is in flight, and this run's read then answers "does not exist"."""

    def __init__(self, repo: MemoryMentionsRepository, mention_id: UUID) -> None:
        super().__init__({"m1": [GONE]})
        self._repo = repo
        self._mention_id = mention_id

    async def get_mentioned_media(self, *, ig_user_id: str, media_id: str) -> MentionedMedia:
        # Lands clearly after this read started (a coarse OS clock — Windows — can hand
        # two consecutive calls the same instant; Postgres stamps microseconds).
        later = datetime.now(UTC) + timedelta(seconds=1)
        self._repo._mentions[self._mention_id].content_refreshed_at = later
        return await super().get_mentioned_media(ig_user_id=ig_user_id, media_id=media_id)


async def test_a_mention_read_successfully_meanwhile_is_never_removed(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """A successful read that lands after this one started is newer evidence: it wins
    over the "does not exist" this run got, and the mention counts as current."""
    mention_id = _store(repo, "m1")
    _use(monkeypatch, _ReadMeanwhileClient(repo, mention_id))

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    assert (report.removed, report.refreshed, report.failed) == (0, 1, 0)
    assert _visible_ids(repo) == {mention_id}


async def test_an_earlier_successful_read_never_shields_a_mention_deleted_since(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """Read fine on one click; the author deletes it; the next click, seconds later, gets
    "does not exist". The earlier read is older evidence: the mention is removed."""
    mention_id = _store(repo, "m1")
    repo._mentions[mention_id].content_refreshed_at = datetime.now(UTC) - timedelta(seconds=10)
    _use(monkeypatch, ScriptedClient({"m1": [GONE]}))

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    assert (report.removed, report.refreshed) == (1, 0)
    assert _visible_ids(repo) == set()


async def test_rechecks_of_an_unreadable_connection_never_starve_the_others(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    revoked = _store(repo, "revoked", connection_id=OTHER_CONNECTION)
    _remove_long_ago(repo, revoked)
    client = ScriptedClient()

    async def client_for(*, tenant_id: UUID, connection_id: UUID):
        return (client, IG_USER) if connection_id == CONNECTION else None

    monkeypatch.setattr(composition, "_content_client_for", client_for)
    await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert repo._mentions[revoked].content_refresh_attempted_at > datetime.now(UTC) - timedelta(
        minutes=1
    )  # stamped: it goes to the back of the line, not first again


async def test_rechecks_are_capped_per_run(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    from qualify_api.mentions.repository import REMOVED_RECHECK_PER_RUN

    for i in range(REMOVED_RECHECK_PER_RUN + 5):
        _remove_long_ago(repo, _store(repo, f"r{i}"))
    client = ScriptedClient(default=GONE)
    _use(monkeypatch, client)

    await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert len(client.calls) == REMOVED_RECHECK_PER_RUN


# ------------------------------------------------------------------ recheck window and capacity


def _plan_ids(repo: MemoryMentionsRepository, *, limit: int = 200) -> list[tuple[str, bool]]:
    plan = repo.plan_scope_refresh(
        tenant_id=TENANT, query=MentionQuery(), fresh_seconds=60, limit=limit
    )
    return [(repo._mentions[t.mention_id].media_id, t.removed) for t in plan.targets]


def _removed_for(repo: MemoryMentionsRepository, media_id: str, age: timedelta) -> UUID:
    mention_id = _store(repo, media_id)
    repo.mark_removed(tenant_id=TENANT, mention_id=mention_id)
    row = repo._mentions[mention_id]
    row.removed_at = datetime.now().astimezone() - age
    row.content_refresh_attempted_at = row.removed_at  # last tried when removed
    return mention_id


def test_the_recheck_window_closes_after_thirty_days_exactly() -> None:
    from qualify_api.mentions.repository import REMOVED_RECHECK_MAX_AGE_SECONDS

    repo = MemoryMentionsRepository()
    max_age = timedelta(seconds=REMOVED_RECHECK_MAX_AGE_SECONDS)
    _removed_for(repo, "day-2", timedelta(days=2))
    _removed_for(repo, "just-inside", max_age - timedelta(minutes=1))
    _removed_for(repo, "just-outside", max_age + timedelta(minutes=1))
    _removed_for(repo, "day-90", timedelta(days=90))

    assert sorted(_plan_ids(repo)) == [("day-2", True), ("just-inside", True)]


def test_a_mention_removed_under_a_day_ago_waits_for_the_recheck_interval() -> None:
    repo = MemoryMentionsRepository()
    _removed_for(repo, "hour-old", timedelta(hours=1))

    assert _plan_ids(repo) == []


def test_many_removed_and_few_visible_live_mentions_get_all_their_capacity() -> None:
    from qualify_api.mentions.repository import REMOVED_RECHECK_PER_RUN

    repo = MemoryMentionsRepository()
    for i in range(3):
        _store(repo, f"live{i}")
    for i in range(500):
        _removed_for(repo, f"r{i}", timedelta(days=2))

    targets = _plan_ids(repo)

    assert [name for name, removed in targets if not removed] == ["live0", "live1", "live2"]
    assert sum(removed for _name, removed in targets) == REMOVED_RECHECK_PER_RUN


def test_a_full_run_of_live_mentions_leaves_no_room_for_rechecks() -> None:
    repo = MemoryMentionsRepository()
    for i in range(10):
        _store(repo, f"live{i}")
    for i in range(50):
        _removed_for(repo, f"r{i}", timedelta(days=2))

    targets = _plan_ids(repo, limit=10)

    assert len(targets) == 10 and not any(removed for _name, removed in targets)


async def test_a_run_with_many_removed_reads_the_live_ones_first_and_caps_the_rest(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    from qualify_api.mentions.repository import REMOVED_RECHECK_PER_RUN

    for i in range(3):
        _store(repo, f"live{i}")
    for i in range(300):
        _removed_for(repo, f"r{i}", timedelta(days=2))
    client = ScriptedClient(default=GONE)
    client._answers.update({f"live{i}": [_media(f"live{i}")] for i in range(3)})
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert set(client.calls[:3]) == {"live0", "live1", "live2"}
    assert len(client.calls) == 3 + REMOVED_RECHECK_PER_RUN
    assert (report.in_scope, report.refreshed, report.complete) == (3, 3, True)


def test_a_removal_after_a_restore_starts_a_new_window() -> None:
    from qualify_api.mentions.repository import MentionContent

    repo = MemoryMentionsRepository()
    mention_id = _removed_for(repo, "m1", timedelta(days=90))
    assert _plan_ids(repo) == []  # long past the window

    repo.refresh_content(
        tenant_id=TENANT,
        mention_id=mention_id,
        content=MentionContent(None, None, None, None, 1, None, None),
    )
    repo.mark_removed(tenant_id=TENANT, mention_id=mention_id)

    assert repo._mentions[mention_id].removed_at > datetime.now().astimezone() - timedelta(
        minutes=1
    )


# ------------------------------------------- a deleted COMMENT answers 400/100, no subcode
#
# [VERIFIED LIVE 2026-10-15, production] A `mentioned_comment` read of a comment read
# successfully hours earlier, then deleted, answered 400 / code 100 / no subcode:
# "(#100) Param comment_id is not a valid instagram comment ID". Removed only for a
# comment mention read successfully before, when another comment read of the same
# connection succeeded in the same run and the account answers.

NOT_A_VALID_COMMENT = MentionedContentReadError(
    "GET /ig-user-1 failed with HTTP 400", http_status=400, platform_code=100
)


def _comment(comment_id: str) -> MentionedComment:
    return MentionedComment(
        id=comment_id, text=f"sigue {comment_id}", like_count=1, timestamp=POSTED
    )


def _read_before(repo: MemoryMentionsRepository, mention_id: UUID) -> None:
    """The mention was re-read successfully hours ago (`content_refreshed_at` set)."""
    repo._mentions[mention_id].content_refreshed_at = datetime.now(UTC) - timedelta(hours=3)


def _comment_mention(
    repo: MemoryMentionsRepository,
    comment_id: str,
    *,
    read_before: bool = True,
    connection_id: UUID = CONNECTION,
) -> UUID:
    mention_id = _store(
        repo, f"post-{comment_id}", comment_id=comment_id, connection_id=connection_id
    )
    if read_before:
        _read_before(repo, mention_id)
    return mention_id


def test_the_unavailable_comment_candidate_is_400_100_without_subcode_only() -> None:
    from qualify_api.mentions.meta_client import is_comment_unavailable_candidate

    def error(
        status: int | None, code: int | None, subcode: int | None = None
    ) -> MentionedContentReadError:
        return MentionedContentReadError(
            "x", http_status=status, platform_code=code, platform_subcode=subcode
        )

    assert is_comment_unavailable_candidate(error(400, 100)) is True
    for refused in (
        error(400, 100, 33),  # already `is_gone`
        error(400, 100, 2207),  # another subcode
        error(400, 190),  # credential
        error(400, 10),  # permission
        error(403, 100),
        error(429, None),
        error(500, 100),
        error(None, None),  # a 200 whose body did not match the contract
    ):
        assert is_comment_unavailable_candidate(refused) is False


def test_the_shared_missing_object_signature_still_requires_subcode_33() -> None:
    """The inbox keeps its rule: the widening lives in the mentions module only."""
    from qualify_shared.social.graph_errors import is_missing_object_error

    assert is_missing_object_error(http_status=400, platform_code=100, platform_subcode=33)
    assert not is_missing_object_error(http_status=400, platform_code=100, platform_subcode=None)


async def test_a_deleted_comment_answering_without_subcode_is_removed(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    gone_id = _comment_mention(repo, "gone")
    ok_id = _comment_mention(repo, "ok")
    stored_text = repo._mentions[gone_id].text
    _use(monkeypatch, ScriptedClient({"gone": [NOT_A_VALID_COMMENT], "ok": [_comment("ok")]}))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.refreshed, report.failed, report.complete) == (1, 1, 0, True)
    assert _visible_ids(repo) == {ok_id}
    # A soft delete: the stored content is kept for a possible restore.
    assert repo._mentions[gone_id].text == stored_text


async def test_the_visible_pass_removes_it_too(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    gone_id = _comment_mention(repo, "gone")
    ok_id = _comment_mention(repo, "ok")
    _use(monkeypatch, ScriptedClient({"gone": [NOT_A_VALID_COMMENT], "ok": [_comment("ok")]}))

    report = await composition.refresh_mentions_content(
        tenant_id=TENANT, mention_ids=(gone_id, ok_id)
    )

    assert (report.removed, report.failed) == (1, 0)
    assert _visible_ids(repo) == {ok_id}


async def test_the_decision_waits_for_every_live_read(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """The comparable read finishing AFTER the refused one still counts: candidates are
    settled once every live read is done, never in completion order."""
    gone_id = _comment_mention(repo, "gone")  # stored first: read first
    for i in range(3):
        _comment_mention(repo, f"ok{i}")
    monkeypatch.setattr(composition, "REFRESH_CONCURRENCY", 1)
    _use(monkeypatch, ScriptedClient({"gone": [NOT_A_VALID_COMMENT]}, default=_comment("x")))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert report.removed == 1
    assert gone_id not in _visible_ids(repo)


async def test_a_comment_never_read_successfully_is_kept(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """Without an earlier good read, "not a valid comment ID" may be an id that never was."""
    never_id = _comment_mention(repo, "never", read_before=False)
    _comment_mention(repo, "ok")
    stored_text = _record(repo, never_id).text
    _use(monkeypatch, ScriptedClient({"never": [NOT_A_VALID_COMMENT], "ok": [_comment("ok")]}))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.failed) == (0, 1)
    assert never_id in _visible_ids(repo)
    assert _record(repo, never_id).text == stored_text  # the failed read wrote nothing


async def test_every_comment_read_refused_removes_nothing(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """A refusal of EVERY comment read is systematic (a request-shape change, an outage),
    not a deletion: nothing leaves the dashboard and nothing is overwritten."""
    ids = {_comment_mention(repo, f"c{i}") for i in range(3)}
    texts = {mention_id: _record(repo, mention_id).text for mention_id in ids}
    client = ScriptedClient(default=NOT_A_VALID_COMMENT)
    _use(monkeypatch, client)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.failed) == (0, 3)
    assert _visible_ids(repo) == ids
    assert {mention_id: _record(repo, mention_id).text for mention_id in ids} == texts
    assert client.account_checks == 0


async def test_only_a_comment_read_of_the_same_connection_is_comparable(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """A successful MEDIA read, or a comment read of ANOTHER connection, says nothing about
    whether this connection's `mentioned_comment` requests are valid."""
    gone_id = _comment_mention(repo, "gone")
    _store(repo, "media-ok")  # a caption mention, same connection
    _comment_mention(repo, "elsewhere", connection_id=OTHER_CONNECTION)
    _use(
        monkeypatch,
        ScriptedClient({"gone": [NOT_A_VALID_COMMENT], "elsewhere": [_comment("elsewhere")]}),
    )

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.failed) == (0, 1)
    assert gone_id in _visible_ids(repo)


@pytest.mark.parametrize(
    ("account_error", "expected"),
    [
        (GONE, "credential_failed"),  # "does not exist" about the account itself
        (
            MentionedContentReadError("expired", http_status=401, platform_code=190),
            "credential_failed",
        ),
        (MentionedContentReadError("server", http_status=503), "failed"),
        (NOT_A_VALID_COMMENT, "failed"),
    ],
)
async def test_an_unreadable_account_removes_nothing(
    monkeypatch: pytest.MonkeyPatch,
    repo: MemoryMentionsRepository,
    account_error: MentionedContentReadError,
    expected: str,
) -> None:
    gone_id = _comment_mention(repo, "gone")
    _comment_mention(repo, "ok")
    _use(
        monkeypatch,
        ScriptedClient(
            {"gone": [NOT_A_VALID_COMMENT], "ok": [_comment("ok")]}, account_error=account_error
        ),
    )

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert report.removed == 0
    assert getattr(report, expected) == 1
    assert gone_id in _visible_ids(repo)


@pytest.mark.parametrize(
    "error",
    [
        MentionedContentReadError(
            "other", http_status=400, platform_code=100, platform_subcode=2207
        ),
        MentionedContentReadError("permission", http_status=400, platform_code=10),
        MentionedContentReadError("expired", http_status=400, platform_code=190),
        MentionedContentReadError("server", http_status=500, platform_code=100),
        MentionedContentReadError("forbidden", http_status=403, platform_code=100),
    ],
)
async def test_any_other_refusal_keeps_the_comment_and_its_data(
    monkeypatch: pytest.MonkeyPatch,
    repo: MemoryMentionsRepository,
    error: MentionedContentReadError,
) -> None:
    kept_id = _comment_mention(repo, "kept")
    _comment_mention(repo, "ok")
    stored_text = _record(repo, kept_id).text
    _use(monkeypatch, ScriptedClient({"kept": [error], "ok": [_comment("ok")]}))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.failed) == (0, 1)
    assert kept_id in _visible_ids(repo)
    assert _record(repo, kept_id).text == stored_text


async def test_throttling_keeps_the_comment(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    kept_id = _comment_mention(repo, "kept")
    _comment_mention(repo, "ok")
    throttled = MentionedContentReadError("limit", http_status=429)
    _use(monkeypatch, ScriptedClient({"kept": [throttled], "ok": [_comment("ok")]}))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.rate_limited) == (0, True)
    assert kept_id in _visible_ids(repo)


async def test_a_media_mention_answering_without_subcode_keeps_the_current_behavior(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """No live evidence yet for a deleted `mentioned_media`: 400/100 without subcode stays a
    plain failure there, however good the other reads are."""
    media_id = _store(repo, "media-gone", like_count=7)
    _read_before(repo, media_id)
    _store(repo, "media-ok")
    _comment_mention(repo, "ok")
    _use(monkeypatch, ScriptedClient({"media-gone": [CODE_100_ONLY], "ok": [_comment("ok")]}))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.failed) == (0, 1)
    assert media_id in _visible_ids(repo)
    assert _record(repo, media_id).like_count == 7


async def test_a_comment_read_meanwhile_is_never_removed(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """The guard of every removal applies here too: a good read that landed after the
    refused one started (another tab, the comments webhook) keeps the mention."""
    gone_id = _comment_mention(repo, "gone")
    _comment_mention(repo, "ok")

    class _ReadMeanwhile(ScriptedClient):
        async def account_reachable(self, *, ig_user_id: str) -> None:
            repo._mentions[gone_id].content_refreshed_at = datetime.now(UTC) + timedelta(seconds=1)

    _use(monkeypatch, _ReadMeanwhile({"gone": [NOT_A_VALID_COMMENT], "ok": [_comment("ok")]}))

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.removed, report.refreshed) == (0, 2)
    assert gone_id in _visible_ids(repo)


async def test_a_removed_comment_that_answers_again_is_restored(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    gone_id = _comment_mention(repo, "gone")
    _comment_mention(repo, "ok")
    _use(monkeypatch, ScriptedClient({"gone": [NOT_A_VALID_COMMENT], "ok": [_comment("ok")]}))
    await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)
    assert gone_id not in _visible_ids(repo)

    _remove_long_ago(repo, gone_id)  # past the recheck interval
    _use(monkeypatch, ScriptedClient({"gone": [_comment("gone")]}))
    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert report.restored == 1
    assert gone_id in _visible_ids(repo)
    assert _record(repo, gone_id).text == "sigue gone"
