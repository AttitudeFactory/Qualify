"""`ingest_mention` (QUA-49) — the enrichment + persistence orchestration, fully offline.

`_content_client_for` (real credential resolution against Postgres) and
`production_mentions_repository` (the real Postgres repository) are monkeypatched to a
fake client and `MemoryMentionsRepository` respectively — this test is about the
orchestration logic itself (which endpoint gets called, how a failure degrades, that
persistence always happens), not about credential resolution or Postgres, which
`test_mentions_repository_db.py` and the `inbox`/`publishing` composition tests already
cover for their own modules.
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
    MentionRecord,
)
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
IG_USER = "ig-user-1"

RESOLUTION = TenantResolution(
    outcome=ResolutionOutcome.RESOLVED, tenant_id=TENANT, connection_id=CONNECTION
)


class FakeContentClient:
    def __init__(
        self,
        *,
        media: MentionedMedia | None = None,
        comment: MentionedComment | None = None,
        media_error: Exception | None = None,
        comment_error: Exception | None = None,
        permalink: str | None = None,
        permalink_error: Exception | None = None,
    ) -> None:
        self._permalink = permalink
        self._permalink_error = permalink_error
        self.permalink_calls: list[tuple[str, str, str | None]] = []
        self._media = media
        self._comment = comment
        self._media_error = media_error
        self._comment_error = comment_error
        self.media_calls: list[tuple[str, str]] = []
        self.comment_calls: list[tuple[str, str]] = []

    async def get_mentioned_media(self, *, ig_user_id: str, media_id: str) -> MentionedMedia:
        self.media_calls.append((ig_user_id, media_id))
        if self._media_error:
            raise self._media_error
        assert self._media is not None
        return self._media

    async def get_mentioned_comment(self, *, ig_user_id: str, comment_id: str) -> MentionedComment:
        self.comment_calls.append((ig_user_id, comment_id))
        if self._comment_error:
            raise self._comment_error
        assert self._comment is not None
        return self._comment

    async def get_mentioned_permalink(
        self, *, ig_user_id: str, media_id: str, comment_id: str | None
    ) -> str | None:
        self.permalink_calls.append((ig_user_id, media_id, comment_id))
        if self._permalink_error:
            raise self._permalink_error
        return self._permalink


@pytest.fixture
def memory_repo(monkeypatch: pytest.MonkeyPatch) -> MemoryMentionsRepository:
    repo = MemoryMentionsRepository()
    monkeypatch.setattr(composition, "production_mentions_repository", lambda: repo)
    return repo


def _patch_content_client(monkeypatch: pytest.MonkeyPatch, client: FakeContentClient) -> None:
    async def fake_content_client_for(*, tenant_id: UUID, connection_id: UUID):
        return client, IG_USER

    monkeypatch.setattr(composition, "_content_client_for", fake_content_client_for)


async def test_caption_mention_calls_mentioned_media_and_persists_caption(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    client = FakeContentClient(
        media=MentionedMedia(
            id="media-1",
            caption="hola @qualifymkt.co",
            media_type="IMAGE",
            like_count=4,
            timestamp=datetime(2026, 8, 1, tzinfo=UTC),
            username="creator1",
        )
    )
    _patch_content_client(monkeypatch, client)

    mention_id = await composition.ingest_mention(
        media_id="media-1", comment_id=None, resolution=RESOLUTION
    )

    assert client.media_calls == [(IG_USER, "media-1")]
    assert client.comment_calls == []
    records = memory_repo.list_mentions(
        tenant_id=TENANT, connection_id=None, version=composition.current_mention_analysis_version()
    )
    assert len(records) == 1
    assert records[0].id == mention_id
    assert records[0].caption == "hola @qualifymkt.co"
    assert records[0].author_username == "creator1"
    assert records[0].enrichment_status == ENRICHMENT_OK


async def test_comment_mention_calls_mentioned_comment_and_persists_text(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    client = FakeContentClient(
        comment=MentionedComment(
            id="comment-1",
            text="Shout out to @qualifymkt.co",
            like_count=9,
            timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        )
    )
    _patch_content_client(monkeypatch, client)

    await composition.ingest_mention(
        media_id="media-1", comment_id="comment-1", resolution=RESOLUTION
    )

    assert client.comment_calls == [(IG_USER, "comment-1")]
    assert client.media_calls == []
    records = memory_repo.list_mentions(
        tenant_id=TENANT, connection_id=None, version=composition.current_mention_analysis_version()
    )
    assert records[0].text == "Shout out to @qualifymkt.co"
    assert records[0].caption is None


async def test_enrichment_failure_is_persisted_with_null_content(
    monkeypatch: pytest.MonkeyPatch,
    memory_repo: MemoryMentionsRepository,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The audit's central ruling for `ingest_mention`: enrichment failing is not
    ingestion failing. Meta erroring on `mentioned_media` (still-pending Advanced
    Access, a transient 5xx) must still leave a real, queryable mention row."""
    client = FakeContentClient(media_error=MentionedContentReadError("boom", http_status=502))
    _patch_content_client(monkeypatch, client)

    with caplog.at_level("WARNING"):
        mention_id = await composition.ingest_mention(
            media_id="media-1", comment_id=None, resolution=RESOLUTION
        )

    assert mention_id is not None
    records = memory_repo.list_mentions(
        tenant_id=TENANT, connection_id=None, version=composition.current_mention_analysis_version()
    )
    assert len(records) == 1
    assert records[0].enrichment_status == ENRICHMENT_FAILED
    assert records[0].caption is None
    assert records[0].text is None
    # Diagnostic gap the QUA-97 audit found: an enrichment failure used to be swallowed
    # with zero log trace. Once real Advanced Access checks start running, this line is
    # what tells "still not granted" (a stable platform_code) apart from "actual bug".
    assert "enrichment failed" in caplog.text
    assert "media-1" in caplog.text
    assert "http_status=502" in caplog.text


async def test_ingesting_the_same_event_twice_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    """A redelivered webhook (Meta retries up to 36h on a non-200, and can also just
    duplicate) must never create a second mention — proven here at the orchestration
    layer, on top of `repository.py`'s own idempotency guarantee."""
    client = FakeContentClient(
        media=MentionedMedia(
            id="media-1",
            caption="hola",
            media_type="IMAGE",
            like_count=1,
            timestamp=None,
            username=None,
        )
    )
    _patch_content_client(monkeypatch, client)

    first_id = await composition.ingest_mention(
        media_id="media-1", comment_id=None, resolution=RESOLUTION
    )
    second_id = await composition.ingest_mention(
        media_id="media-1", comment_id=None, resolution=RESOLUTION
    )

    assert first_id == second_id
    records = memory_repo.list_mentions(
        tenant_id=TENANT, connection_id=None, version=composition.current_mention_analysis_version()
    )
    assert len(records) == 1
    # The Meta call itself is NOT deduped by this layer — a second identical webhook
    # delivery still enriches again (cheap, idempotent) before the repository's own
    # natural-key uniqueness makes the second persist a no-op.
    assert len(client.media_calls) == 2


# --------------------------------------------------------------------------------------
# QUA-152 — the best-effort permalink ("Ver" link)
# --------------------------------------------------------------------------------------

_MEDIA = MentionedMedia(
    id="media-1",
    caption="hola @qualifymkt.co",
    media_type="IMAGE",
    like_count=4,
    timestamp=datetime(2026, 8, 1, tzinfo=UTC),
    username="creator1",
)


def _only_record(memory_repo: MemoryMentionsRepository) -> MentionRecord:
    records = memory_repo.list_mentions(
        tenant_id=TENANT, connection_id=None, version=composition.current_mention_analysis_version()
    )
    assert len(records) == 1
    return records[0]


async def test_the_permalink_is_read_after_the_content_and_stored(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    client = FakeContentClient(media=_MEDIA, permalink="https://www.instagram.com/p/ABC/")
    _patch_content_client(monkeypatch, client)

    await composition.ingest_mention(media_id="media-1", comment_id=None, resolution=RESOLUTION)

    assert client.permalink_calls == [(IG_USER, "media-1", None)]
    record = _only_record(memory_repo)
    assert record.permalink == "https://www.instagram.com/p/ABC/"
    assert record.enrichment_status == ENRICHMENT_OK


async def test_a_refused_permalink_never_fails_the_mention(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    client = FakeContentClient(
        media=_MEDIA,
        permalink_error=MentionedContentReadError("nope", platform_code=100, http_status=400),
    )
    _patch_content_client(monkeypatch, client)

    await composition.ingest_mention(media_id="media-1", comment_id=None, resolution=RESOLUTION)

    record = _only_record(memory_repo)
    assert record.permalink is None
    assert record.enrichment_status == ENRICHMENT_OK
    assert record.caption == "hola @qualifymkt.co"


async def test_no_permalink_is_requested_when_the_content_read_failed(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    client = FakeContentClient(media_error=MentionedContentReadError("down", http_status=500))
    _patch_content_client(monkeypatch, client)

    await composition.ingest_mention(media_id="media-1", comment_id=None, resolution=RESOLUTION)

    assert client.permalink_calls == []
    assert _only_record(memory_repo).permalink is None


# --------------------------------------------------------------------------------------
# QUA-152 — "Actualizar" re-reads the visible mentions and stores what changed
# --------------------------------------------------------------------------------------


async def _ingest_caption(monkeypatch: pytest.MonkeyPatch, likes: int | None) -> UUID:
    client = FakeContentClient(
        media=MentionedMedia(
            id="media-1",
            caption="hola @qualifymkt.co",
            media_type="IMAGE",
            like_count=likes,
            timestamp=datetime(2026, 8, 1, tzinfo=UTC),
            username="creator1",
        ),
        permalink="https://www.instagram.com/p/OLD/",
    )
    _patch_content_client(monkeypatch, client)
    return await composition.ingest_mention(
        media_id="media-1", comment_id=None, resolution=RESOLUTION
    )


async def test_refresh_stores_the_new_like_count(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    mention_id = await _ingest_caption(monkeypatch, likes=None)
    fresh = FakeContentClient(
        media=MentionedMedia(
            id="media-1",
            caption="hola @qualifymkt.co (editado)",
            media_type="IMAGE",
            like_count=7,
            timestamp=datetime(2026, 8, 1, tzinfo=UTC),
            username="creator1",
        ),
        permalink=None,  # a later read without a link must not erase the stored one
    )
    _patch_content_client(monkeypatch, fresh)

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    record = _only_record(memory_repo)
    assert (report.refreshed, report.failed) == (1, 0)
    assert record.like_count == 7
    assert record.caption == "hola @qualifymkt.co (editado)"
    assert record.permalink == "https://www.instagram.com/p/OLD/"


async def test_a_failed_refresh_keeps_the_stored_data(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    mention_id = await _ingest_caption(monkeypatch, likes=3)
    _patch_content_client(
        monkeypatch,
        FakeContentClient(media_error=MentionedContentReadError("gone", http_status=400)),
    )

    report = await composition.refresh_mentions_content(tenant_id=TENANT, mention_ids=(mention_id,))

    record = _only_record(memory_repo)
    assert (report.refreshed, report.failed) == (0, 1)
    assert (record.like_count, record.caption) == (3, "hola @qualifymkt.co")
    assert record.enrichment_status == ENRICHMENT_OK


async def test_refresh_never_touches_another_tenants_mention(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    mention_id = await _ingest_caption(monkeypatch, likes=3)

    report = await composition.refresh_mentions_content(
        tenant_id=UUID("99999999-9999-4999-8999-999999999999"), mention_ids=(mention_id,)
    )

    assert (report.refreshed, report.failed) == (0, 0)
    assert _only_record(memory_repo).like_count == 3


# --- own-post comments delivered by the `comments` webhook ------------------------------

_OWN_COMMENT = MentionedComment(
    id="comment-9",
    text="@qualifymkt.co mira esto",
    like_count=2,
    timestamp=datetime(2026, 10, 14, 17, 0, tzinfo=UTC),
)


SENT_AT = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)


async def _ingest_own_comment(
    *,
    text: str | None = "@qualifymkt.co mira esto",
    author: str | None = "yesii_roa",
    observed_at: datetime | None = SENT_AT,
) -> UUID | None:
    return await composition.ingest_mention(
        media_id="media-9",
        comment_id="comment-9",
        resolution=RESOLUTION,
        text=text,
        author_username=author,
        observed_at=observed_at,
    )


async def test_an_own_post_comment_stores_ids_text_author_likes_and_date(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    client = FakeContentClient(comment=_OWN_COMMENT, permalink="https://www.instagram.com/p/X/")
    _patch_content_client(monkeypatch, client)

    mention_id = await _ingest_own_comment()

    record = _only_record(memory_repo)
    assert record.id == mention_id
    assert (record.connection_id, record.media_id, record.comment_id) == (
        CONNECTION,
        "media-9",
        "comment-9",
    )
    assert (record.text, record.author_username) == ("@qualifymkt.co mira esto", "yesii_roa")
    assert (record.like_count, record.content_posted_at) == (2, _OWN_COMMENT.timestamp)
    assert record.caption is None
    assert record.enrichment_status == ENRICHMENT_OK
    assert record.permalink == "https://www.instagram.com/p/X/"
    assert client.comment_calls == [(IG_USER, "comment-9")]
    assert client.media_calls == []


async def test_a_refused_network_read_keeps_the_webhook_text_and_author(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    _patch_content_client(
        monkeypatch,
        FakeContentClient(comment_error=MentionedContentReadError("refused", http_status=400)),
    )

    await _ingest_own_comment()

    record = _only_record(memory_repo)
    assert (record.text, record.author_username) == ("@qualifymkt.co mira esto", "yesii_roa")
    assert record.enrichment_status == ENRICHMENT_OK
    assert record.like_count is None


async def test_no_text_anywhere_is_still_persisted_as_failed_enrichment(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    _patch_content_client(
        monkeypatch,
        FakeContentClient(comment_error=MentionedContentReadError("refused", http_status=400)),
    )

    await _ingest_own_comment(text=None)

    record = _only_record(memory_repo)
    assert record.enrichment_status == ENRICHMENT_FAILED
    assert record.author_username == "yesii_roa"


async def test_a_connection_without_ig_user_persists_nothing(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    async def no_client(*, tenant_id: UUID, connection_id: UUID):
        return None

    monkeypatch.setattr(composition, "_content_client_for", no_client)

    assert await _ingest_own_comment() is None
    assert (
        memory_repo.list_mentions(
            tenant_id=TENANT,
            connection_id=None,
            version=composition.current_mention_analysis_version(),
        )
        == ()
    )


async def test_comments_then_mentions_for_the_same_comment_is_one_row_with_its_author(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    _patch_content_client(monkeypatch, FakeContentClient(comment=_OWN_COMMENT))

    first = await _ingest_own_comment()
    second = await composition.ingest_mention(
        media_id="media-9", comment_id="comment-9", resolution=RESOLUTION
    )

    record = _only_record(memory_repo)
    assert first == second == record.id
    assert record.author_username == "yesii_roa"


async def test_mentions_then_comments_for_the_same_comment_fills_the_author_in(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    _patch_content_client(monkeypatch, FakeContentClient(comment=_OWN_COMMENT))

    first = await composition.ingest_mention(
        media_id="media-9", comment_id="comment-9", resolution=RESOLUTION
    )
    assert _only_record(memory_repo).author_username is None
    second = await _ingest_own_comment()

    record = _only_record(memory_repo)
    assert first == second == record.id
    assert record.author_username == "yesii_roa"
    assert record.text == "@qualifymkt.co mira esto"


async def test_a_later_comments_event_never_overwrites_stored_values(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    _patch_content_client(monkeypatch, FakeContentClient(comment=_OWN_COMMENT))
    await _ingest_own_comment()

    await _ingest_own_comment(text="@qualifymkt.co texto distinto", author="otra_persona")

    record = _only_record(memory_repo)
    assert (record.text, record.author_username) == ("@qualifymkt.co mira esto", "yesii_roa")


async def test_an_earlier_unread_mention_gets_its_text_from_the_comments_event(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    _patch_content_client(
        monkeypatch,
        FakeContentClient(comment_error=MentionedContentReadError("refused", http_status=400)),
    )
    await composition.ingest_mention(
        media_id="media-9", comment_id="comment-9", resolution=RESOLUTION
    )
    assert _only_record(memory_repo).enrichment_status == ENRICHMENT_FAILED

    await _ingest_own_comment()

    record = _only_record(memory_repo)
    assert record.text == "@qualifymkt.co mira esto"
    assert record.author_username == "yesii_roa"
    assert record.enrichment_status == ENRICHMENT_OK


async def test_replaying_the_same_comments_event_through_the_worker_never_duplicates(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    """End to end over the real handler + real ingest: the event a requeue hands back to
    the worker, processed three times, is still one mention."""
    from qualify_api.webhooks.processor import (
        INSTAGRAM_COMMENTS_HANDLER_KEY,
        Processor,
        comment_mentions_handler,
    )
    from qualify_api.webhooks.repository import ClaimedEvent

    _patch_content_client(monkeypatch, FakeContentClient(comment=_OWN_COMMENT))
    handler = comment_mentions_handler(
        resolve=lambda *, platform, external_account_id: RESOLUTION,
        username_of=lambda *, tenant_id, connection_id: "qualifymkt.co",
        ingest=composition.ingest_mention,
    )
    value = {
        "from": {"id": "igsid", "username": "yesii_roa"},
        "id": "comment-9",
        "text": "@qualifymkt.co mira esto",
        "media": {"id": "media-9"},
    }

    class ReplayQueue:
        def __init__(self) -> None:
            self.settled: list[str] = []
            self._events = [
                ClaimedEvent(
                    id=UUID(int=n),
                    delivery_id=None,
                    object="instagram",
                    entry_id=IG_USER,
                    field="comments",
                    value=value,
                    attempts=1,
                )
                for n in (1, 2, 3)
            ]

        def claim(self, *, worker_id, now, limit):
            batch, self._events = self._events, []
            return batch

        def settle(self, *, event_id, worker_id, now, status, error=None) -> bool:
            self.settled.append(status)
            return True

        def fail(self, **kwargs) -> str:
            raise AssertionError(f"unexpected failure {kwargs}")

    queue = ReplayQueue()
    processor = Processor(
        queue=queue, handlers={INSTAGRAM_COMMENTS_HANDLER_KEY: handler}, worker_id="w"
    )

    await processor.run_once()

    assert queue.settled == ["processed", "processed", "processed"]
    record = _only_record(memory_repo)
    assert (record.comment_id, record.author_username) == ("comment-9", "yesii_roa")


async def test_the_network_date_wins_over_metas_send_time(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    _patch_content_client(monkeypatch, FakeContentClient(comment=_OWN_COMMENT))

    await _ingest_own_comment()

    assert _only_record(memory_repo).content_posted_at == _OWN_COMMENT.timestamp


async def test_without_a_network_date_the_mention_is_dated_when_meta_sent_it(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    """A replayed old comment whose network read is refused keeps its own date: it is not
    shown, sorted or counted as just received."""
    _patch_content_client(
        monkeypatch,
        FakeContentClient(comment_error=MentionedContentReadError("refused", http_status=400)),
    )

    await _ingest_own_comment()

    assert _only_record(memory_repo).content_posted_at == SENT_AT


async def test_mentions_path_never_uses_a_send_time(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    _patch_content_client(
        monkeypatch,
        FakeContentClient(comment_error=MentionedContentReadError("refused", http_status=400)),
    )

    await composition.ingest_mention(
        media_id="media-9", comment_id="comment-9", resolution=RESOLUTION
    )

    record = _only_record(memory_repo)
    assert record.content_posted_at is None
    assert record.enrichment_status == ENRICHMENT_FAILED


async def test_a_successful_read_completes_a_mention_first_stored_unread(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    """`mentions` first, refused (no likes, date or link); then the `comments` event reads
    it: the fresh read is written to the SAME row, not thrown away."""
    _patch_content_client(
        monkeypatch,
        FakeContentClient(comment_error=MentionedContentReadError("refused", http_status=400)),
    )
    first = await composition.ingest_mention(
        media_id="media-9", comment_id="comment-9", resolution=RESOLUTION
    )
    _patch_content_client(
        monkeypatch,
        FakeContentClient(comment=_OWN_COMMENT, permalink="https://www.instagram.com/p/X/"),
    )

    second = await _ingest_own_comment()

    record = _only_record(memory_repo)
    assert first == second == record.id
    assert (record.text, record.author_username) == ("@qualifymkt.co mira esto", "yesii_roa")
    assert (record.like_count, record.content_posted_at) == (2, _OWN_COMMENT.timestamp)
    assert record.permalink == "https://www.instagram.com/p/X/"
    assert record.enrichment_status == ENRICHMENT_OK


async def test_a_refused_read_does_not_ask_for_the_link_either(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    client = FakeContentClient(
        comment_error=MentionedContentReadError("refused", http_status=400),
        permalink="https://www.instagram.com/p/X/",
    )
    _patch_content_client(monkeypatch, client)

    await _ingest_own_comment()

    assert client.permalink_calls == []
    assert _only_record(memory_repo).permalink is None


async def test_a_read_without_a_date_never_overwrites_a_stored_date(
    monkeypatch: pytest.MonkeyPatch, memory_repo: MemoryMentionsRepository
) -> None:
    """The send-time fallback dates a NEW row only; it is never written over a real date."""
    _patch_content_client(monkeypatch, FakeContentClient(comment=_OWN_COMMENT))
    await composition.ingest_mention(
        media_id="media-9", comment_id="comment-9", resolution=RESOLUTION
    )
    undated = MentionedComment(
        id="comment-9", text="@qualifymkt.co mira esto", like_count=3, timestamp=None
    )
    _patch_content_client(monkeypatch, FakeContentClient(comment=undated))

    await _ingest_own_comment()

    record = _only_record(memory_repo)
    assert record.content_posted_at == _OWN_COMMENT.timestamp
    assert record.like_count == 3
