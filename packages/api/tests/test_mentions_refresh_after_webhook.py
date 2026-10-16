"""The 60 s freshness window and the two passes of "Actualizar menciones", for a mention
born from a webhook with a successful read (`NewMention.read_from_network`, 2026-10-16).

The stamp on creation makes such a mention "fresh" for `REFRESH_FRESH_SECONDS` exactly as
a mention re-read by "Actualizar" would be. Consequences this file pins:

- the SCOPE pass skips it while fresh (`already_fresh`), so a deletion within the first
  60 s is noticed on the next click, never "prematurely" and never by a read the window
  says is redundant;
- once the window has passed, the scope pass reads it again and a bare 400/100 with a
  comparable read removes it — and the read seams (`list_mentions_for_tenant`, the HTTP
  route's source) stop returning it;
- a webhook-only text (the read failed) is never fresh and never removed by a bare
  400/100, window or no window.

Memory repository + scripted client, as `test_mentions_refresh.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from qualify_shared.social.ig_shapes import MentionedComment

from qualify_api.mentions import composition
from qualify_api.mentions.meta_client import MentionedContentReadError
from qualify_api.mentions.repository import MemoryMentionsRepository, MentionQuery
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
IG_USER = "ig-user-1"
RESOLUTION = TenantResolution(
    outcome=ResolutionOutcome.RESOLVED, tenant_id=TENANT, connection_id=CONNECTION
)
# Relative to now so the scope (`since` = 14 days) holds whatever day the suite runs.
POSTED = datetime.now(UTC) - timedelta(days=2)
SCOPE = MentionQuery(since=datetime.now(UTC) - timedelta(days=14))

CODE_100_ONLY = MentionedContentReadError("deleted", http_status=400, platform_code=100)
REFUSED = MentionedContentReadError("refused", http_status=400)


def _comment(comment_id: str) -> MentionedComment:
    return MentionedComment(
        id=comment_id, text=f"@qualifymkt.co {comment_id}", like_count=2, timestamp=POSTED
    )


class ScriptedClient:
    def __init__(self, answers: dict[str, list[object]]) -> None:
        self._answers = {k: list(v) for k, v in answers.items()}
        self.reads: list[str] = []

    def _next(self, key: str) -> object:
        self.reads.append(key)
        answers = self._answers.get(key) or []
        if not answers:
            raise AssertionError(f"no scripted answer left for {key!r}")
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def get_mentioned_media(self, *, ig_user_id: str, media_id: str):
        return self._next(media_id)

    async def get_mentioned_comment(self, *, ig_user_id: str, comment_id: str) -> MentionedComment:
        answer = self._next(comment_id)
        assert isinstance(answer, MentionedComment)
        return answer

    async def account_reachable(self, *, ig_user_id: str) -> None:
        return None

    async def get_mentioned_permalink(
        self, *, ig_user_id: str, media_id: str, comment_id: str | None
    ) -> str | None:
        return None


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


async def _ingest(comment_id: str, *, text: str | None = "@qualifymkt.co hola") -> UUID:
    mention_id = await composition.ingest_mention(
        media_id="media-9",
        comment_id=comment_id,
        resolution=RESOLUTION,
        text=text,
        author_username="yesii_roa",
        observed_at=POSTED,
    )
    assert mention_id is not None
    return mention_id


def _visible_ids(repo: MemoryMentionsRepository) -> set[UUID]:
    page = repo.list_mentions_page(
        tenant_id=TENANT,
        version=composition.current_mention_analysis_version(),
        query=MentionQuery(),
        page=1,
        page_size=1000,
    )
    return {row.id for row in page.rows}


def _age(repo: MemoryMentionsRepository, mention_id: UUID, seconds: int) -> None:
    """Pretend the stamp happened `seconds` ago (the memory repository's clock is real)."""
    repo._mentions[mention_id].content_refreshed_at = datetime.now(UTC) - timedelta(seconds=seconds)
    repo._mentions[mention_id].content_refresh_attempted_at = repo._mentions[
        mention_id
    ].content_refreshed_at


async def test_the_scope_pass_skips_a_webhook_mention_while_it_is_fresh(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    client = ScriptedClient({"c9": [_comment("c9")], "c10": [_comment("c10")]})
    _use(monkeypatch, client)
    deleted = await _ingest("c9")
    other = await _ingest("c10")
    assert client.reads == ["c9", "c10"]  # the ingestion reads

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.in_scope, report.already_fresh, report.refreshed) == (2, 2, 0)
    assert (report.removed, report.failed) == (0, 0)
    assert client.reads == ["c9", "c10"]  # nothing re-read: the window is 60 s
    assert _visible_ids(repo) == {deleted, other}


async def test_after_the_fresh_window_the_scope_pass_removes_the_deleted_comment(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    client = ScriptedClient(
        {"c9": [_comment("c9"), CODE_100_ONLY], "c10": [_comment("c10"), _comment("c10")]}
    )
    _use(monkeypatch, client)
    deleted = await _ingest("c9")
    other = await _ingest("c10")
    _age(repo, deleted, seconds=composition.REFRESH_FRESH_SECONDS + 60)
    _age(repo, other, seconds=composition.REFRESH_FRESH_SECONDS + 60)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    assert (report.in_scope, report.already_fresh) == (2, 0)
    assert (report.removed, report.refreshed, report.failed) == (1, 1, 0)
    assert _visible_ids(repo) == {other}
    # The read seam the HTTP route and the dashboard consume no longer returns it.
    listed = composition.list_mentions_for_tenant(tenant_id=TENANT)
    assert {m.id for m in listed} == {other}
    assert repo._mentions[deleted].removed_at is not None


async def test_the_visible_pass_reads_a_fresh_webhook_mention_and_still_needs_proof(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """The visible pass has no freshness skip (what the person looks at is re-read on the
    click). Alone, a bare 400/100 is kept — unstamped, for the scope pass of the same
    click — never removed without a comparable read."""
    client = ScriptedClient({"c9": [_comment("c9"), CODE_100_ONLY]})
    _use(monkeypatch, client)
    deleted = await _ingest("c9")

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(deleted,))

    assert client.reads == ["c9", "c9"]
    assert (report.removed, report.failed) == (0, 1)
    assert _visible_ids(repo) == {deleted}


async def test_a_webhook_only_text_is_never_fresh_and_never_removed_by_a_bare_400_100(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    client = ScriptedClient(
        {"c9": [REFUSED, CODE_100_ONLY], "c10": [_comment("c10"), _comment("c10")]}
    )
    _use(monkeypatch, client)
    never_read = await _ingest("c9")
    other = await _ingest("c10")
    assert repo._mentions[never_read].content_refreshed_at is None
    _age(repo, other, seconds=composition.REFRESH_FRESH_SECONDS + 60)

    report = await composition.refresh_mentions_in_scope(tenant_id=TENANT, scope=SCOPE)

    # Not fresh (never read), so it IS re-read; the refusal keeps it.
    assert (report.in_scope, report.already_fresh) == (2, 0)
    assert (report.removed, report.refreshed, report.failed) == (0, 1, 1)
    assert _visible_ids(repo) == {never_read, other}
