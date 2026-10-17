"""A mention whose content Meta served at ingestion counts as read from the start.

Regression (2026-10-16): `upsert_mention` created rows with `content_refreshed_at = NULL`
even when the webhook's initial read of the comment succeeded. `ever_read` (the guard of
the 400/100-without-subcode removal in `composition.refresh_mentions_content`) was
therefore False for every mention born from a webhook, so a comment deleted on Instagram
afterwards answered 400/100 to "Actualizar" and was kept as failed — it never left the
dashboard. The fix stamps the read on creation, and ONLY on a successful network read:
webhook-only text (the network refused, `ENRICHMENT_OK` thanks to the webhook's own text)
stays unstamped, so the guard keeps treating it as never read.

The removal itself keeps every other condition QUA-152 set: a bare 400/100 is settled
only with a COMPARABLE read (another comment of the same connection read fine in the
run) and an account that answers. Those are exercised here as they happen in production:
several comments ingested by webhook, one deleted, "Actualizar" over all of them.

Same harness as `test_mentions_composition.py` (fake client, memory repository) and
`test_mentions_refresh.py` (scripted client for the later "Actualizar").
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from qualify_shared.social.ig_shapes import MentionedComment, MentionedMedia

from qualify_api.mentions import composition
from qualify_api.mentions.meta_client import MentionedContentReadError
from qualify_api.mentions.repository import (
    ENRICHMENT_FAILED,
    ENRICHMENT_OK,
    MemoryMentionsRepository,
    MentionQuery,
)
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
IG_USER = "ig-user-1"
RESOLUTION = TenantResolution(
    outcome=ResolutionOutcome.RESOLVED, tenant_id=TENANT, connection_id=CONNECTION
)
POSTED = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)
SENT_AT = datetime(2026, 10, 14, 17, 1, tzinfo=UTC)

# Meta's "does not exist" signatures, verbatim from `test_mentions_refresh.py`.
CODE_100_ONLY = MentionedContentReadError("deleted", http_status=400, platform_code=100)
GONE = MentionedContentReadError(
    "does not exist", http_status=400, platform_code=100, platform_subcode=33
)
REFUSED = MentionedContentReadError("refused", http_status=400)
COMMENTS_OFF = MentionedContentReadError("comments off", http_status=400, platform_code=10)


def _comment(comment_id: str) -> MentionedComment:
    return MentionedComment(
        id=comment_id, text=f"@qualifymkt.co {comment_id}", like_count=2, timestamp=POSTED
    )


MEDIA = MentionedMedia(
    id="media-1",
    caption="hola @qualifymkt.co",
    username="autora",
    media_type="IMAGE",
    like_count=1,
    timestamp=POSTED,
)


class ScriptedClient:
    """Each call to a content endpoint pops the next scripted answer for that id; an
    exception instance is raised, anything else returned."""

    def __init__(self, answers: dict[str, list[object]] | None = None) -> None:
        self._answers = {k: list(v) for k, v in (answers or {}).items()}
        self.account_checks = 0

    def _next(self, key: str) -> object:
        answers = self._answers.get(key) or []
        if not answers:
            raise AssertionError(f"no scripted answer left for {key!r}")
        answer = answers.pop(0)
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


async def _ingest_own_comment(
    comment_id: str = "comment-9", *, text: str | None = "@qualifymkt.co mira esto"
) -> UUID:
    """The `comments` webhook path: a comment on the account's own media that @mentions
    it, with the webhook's own text and author."""
    mention_id = await composition.ingest_mention(
        media_id="media-9",
        comment_id=comment_id,
        resolution=RESOLUTION,
        text=text,
        author_username="yesii_roa",
        observed_at=SENT_AT,
    )
    assert mention_id is not None
    return mention_id


def _row(repo: MemoryMentionsRepository, mention_id: UUID):
    return repo._mentions[mention_id]


def _visible_ids(repo: MemoryMentionsRepository) -> set[UUID]:
    page = repo.list_mentions_page(
        tenant_id=TENANT,
        version=composition.current_mention_analysis_version(),
        query=MentionQuery(),
        page=1,
        page_size=1000,
    )
    return {row.id for row in page.rows}


# ---------------------------------------------------------------- the stamp on creation


async def test_a_successful_initial_read_stamps_the_mention_as_read(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    _use(monkeypatch, ScriptedClient({"comment-9": [_comment("comment-9")]}))

    mention_id = await _ingest_own_comment()

    row = _row(repo, mention_id)
    assert row.enrichment_status == ENRICHMENT_OK
    assert row.content_refreshed_at is not None
    assert row.content_refresh_attempted_at == row.content_refreshed_at
    [target] = repo.list_refresh_targets(tenant_id=TENANT, mention_ids=(mention_id,))
    assert target.ever_read is True


async def test_a_caption_mention_read_at_ingestion_is_stamped_too(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    _use(monkeypatch, ScriptedClient({"media-1": [MEDIA]}))

    mention_id = await composition.ingest_mention(
        media_id="media-1", comment_id=None, resolution=RESOLUTION
    )

    assert mention_id is not None
    assert _row(repo, mention_id).content_refreshed_at is not None


async def test_webhook_text_after_a_refused_read_is_not_a_read(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """The network refused; the mention is still readable thanks to the webhook's own
    text (`ENRICHMENT_OK`), but it was never READ: `content_refreshed_at` stays NULL and
    the 400/100 guard keeps protecting it from a removal it has not earned."""
    _use(monkeypatch, ScriptedClient({"comment-9": [REFUSED]}))

    mention_id = await _ingest_own_comment()

    row = _row(repo, mention_id)
    assert row.enrichment_status == ENRICHMENT_OK
    assert row.text == "@qualifymkt.co mira esto"
    assert row.content_refreshed_at is None
    assert row.content_refresh_attempted_at is None
    [target] = repo.list_refresh_targets(tenant_id=TENANT, mention_ids=(mention_id,))
    assert target.ever_read is False


async def test_a_failed_read_with_no_text_anywhere_is_not_a_read(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    _use(monkeypatch, ScriptedClient({"comment-9": [REFUSED]}))

    mention_id = await _ingest_own_comment(text=None)

    row = _row(repo, mention_id)
    assert row.enrichment_status == ENRICHMENT_FAILED
    assert row.content_refreshed_at is None


async def test_a_redelivered_webhook_does_not_duplicate_and_keeps_the_stamp(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """Idempotency: the second delivery finds the row and takes the existing
    `refresh_content` path (QUA-152), never a second creation."""
    _use(monkeypatch, ScriptedClient({"comment-9": [_comment("comment-9")] * 2}))

    first = await _ingest_own_comment()
    stamp = _row(repo, first).content_refreshed_at
    second = await _ingest_own_comment()

    assert second == first
    assert len(repo._mentions) == 1
    assert stamp is not None
    assert _row(repo, first).content_refreshed_at >= stamp  # type: ignore[operator]


# ------------------------------------------------- the removal the stamp makes possible


async def _ingest_two_comments_then(
    monkeypatch: pytest.MonkeyPatch,
    repo: MemoryMentionsRepository,
    *,
    deleted_answers: list[object],
) -> tuple[UUID, UUID]:
    """Two comments of the same connection ingested by webhook with successful reads;
    on the next "Actualizar" the first answers `deleted_answers`, the other reads fine
    again (the comparable read the 400/100 settlement requires)."""
    _use(
        monkeypatch,
        ScriptedClient(
            {
                "comment-9": [_comment("comment-9"), *deleted_answers],
                "comment-10": [_comment("comment-10"), _comment("comment-10")],
            }
        ),
    )
    deleted = await _ingest_own_comment("comment-9")
    other = await _ingest_own_comment("comment-10")
    assert _row(repo, deleted).content_refreshed_at is not None
    assert _row(repo, other).content_refreshed_at is not None
    return deleted, other


async def test_a_comment_deleted_after_a_webhook_ingestion_is_removed_on_refresh(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """The production symptom: ingested by webhook (read fine), deleted on Instagram,
    then "Actualizar" gets 400/100 without subcode while the other comments of the
    account still read fine. With the stamp the mention is a candidate and is removed.
    Before the fix `ever_read` was False and it stayed as failed."""
    deleted, other = await _ingest_two_comments_then(
        monkeypatch, repo, deleted_answers=[CODE_100_ONLY]
    )

    report = await composition.refresh_mentions_content(
        tenant_id=TENANT, mention_ids=(deleted, other)
    )

    assert (report.removed, report.refreshed, report.failed) == (1, 1, 0)
    assert _visible_ids(repo) == {other}


async def test_without_a_comparable_read_the_candidate_is_still_kept(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """The stamp makes the mention a CANDIDATE, nothing more: alone in its run, with no
    other comment of the connection read fine, a bare 400/100 is a failed refresh — the
    QUA-152 proof requirement is untouched."""
    _use(monkeypatch, ScriptedClient({"comment-9": [_comment("comment-9"), CODE_100_ONLY]}))
    mention_id = await _ingest_own_comment()

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    assert (report.removed, report.failed) == (0, 1)
    assert _visible_ids(repo) == {mention_id}


async def test_the_does_not_exist_signature_still_removes_without_the_stamp(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """The subcode-33 signature never depended on `ever_read`; unchanged."""
    _use(monkeypatch, ScriptedClient({"comment-9": [REFUSED, GONE]}))
    mention_id = await _ingest_own_comment()
    assert _row(repo, mention_id).content_refreshed_at is None

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    assert (report.removed, report.failed) == (1, 0)


async def test_a_bare_400_100_on_a_never_read_mention_is_still_kept(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """The guard the fix must not weaken: a mention that was never read (webhook text
    only) answering 400/100 without subcode is a failed refresh, not a removal — even
    with a comparable read in the same run."""
    _use(
        monkeypatch,
        ScriptedClient(
            {
                "comment-9": [REFUSED, CODE_100_ONLY],
                "comment-10": [_comment("comment-10"), _comment("comment-10")],
            }
        ),
    )
    never_read = await _ingest_own_comment("comment-9")
    other = await _ingest_own_comment("comment-10")

    report = await composition.refresh_mentions_content(
        tenant_id=TENANT, mention_ids=(never_read, other)
    )

    assert (report.removed, report.refreshed, report.failed) == (0, 1, 1)
    assert _visible_ids(repo) == {never_read, other}


async def test_a_plain_failure_after_a_stamped_ingestion_never_removes(
    monkeypatch: pytest.MonkeyPatch, repo: MemoryMentionsRepository
) -> None:
    """A read failure that is not Meta's "gone" signature keeps the mention, stamp or
    no stamp, comparable read or not: nothing is removed just because a read failed."""
    deleted, other = await _ingest_two_comments_then(
        monkeypatch, repo, deleted_answers=[COMMENTS_OFF]
    )

    report = await composition.refresh_mentions_content(
        tenant_id=TENANT, mention_ids=(deleted, other)
    )

    assert (report.removed, report.refreshed, report.failed) == (0, 1, 1)
    assert _visible_ids(repo) == {deleted, other}
