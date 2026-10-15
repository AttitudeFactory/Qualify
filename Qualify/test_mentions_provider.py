"""`mentions_provider` (QUA-49, reworked by QUA-152) — the projection from a
`MentionRecord` to what the Dashboard de Menciones renders. Plain functions, no Reflex
`State`. The two backend reads (`list_mentions_page_for_tenant`, `connections_for`) are
monkeypatched: this module owns only the projection and the page assembly.

The rules pinned here are the ticket's: three identities never merged, the publication
author never shown as the comment's, absent data as a word (never a 0), publication and
reception dates kept apart, every sentiment state passed through as its own value.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_api.mentions.repository import (
    ENRICHMENT_FAILED,
    ENRICHMENT_OK,
    MentionCounts,
    MentionPage,
    MentionQuery,
    MentionRecord,
)

from . import mentions_provider
from .mentions_provider import (
    AUTHOR_NOTE_COMMENT,
    AUTHOR_NOTE_POST,
    AUTHOR_NOTE_UNREAD,
    CONTENT_UNAVAILABLE,
    LIKES_NOTE_HIDDEN,
    LIKES_NOTE_MISSING,
    NO_TEXT,
    NO_VALUE,
    NOT_AVAILABLE,
    UNKNOWN_ACCOUNT,
    MentionVM,
    format_moment,
    to_vm,
)

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
CONNECTION = UUID("b0000000-0000-4000-8000-000000000001")


@dataclass(frozen=True)
class _Connection:
    """The three `ConnectionVM` attributes the provider reads. `id` is TEXT, as in
    `ConnectionVM` — the provider must convert it to match a record's UUID."""

    id: str
    platform: str
    external_username: str


def _record(
    *,
    comment: bool = False,
    caption: str | None = "me encanta qualifymkt.co",
    text: str | None = "@qualifymkt.co mira esto",
    author: str | None = "autora_demo",
    like_count: int | None = 5,
    posted_at: datetime | None = datetime(2026, 10, 13, 14, 0, tzinfo=UTC),
    received_at: datetime = datetime(2026, 10, 13, 14, 5, tzinfo=UTC),
    enrichment: str = ENRICHMENT_OK,
    state: str = "PENDING",
    connection_id: UUID = CONNECTION,
    permalink: str | None = None,
) -> MentionRecord:
    return MentionRecord(
        id=uuid4(),
        connection_id=connection_id,
        platform="instagram",
        external_account_id="17841448653847824",
        media_id="media-1",
        comment_id="comment-1" if comment else None,
        caption=None if comment else caption,
        text=text if comment else None,
        author_username=None if comment else author,
        like_count=like_count,
        content_posted_at=posted_at,
        received_at=received_at,
        enrichment_status=enrichment,
        sentiment_label=state if state in ("POS", "NEU", "NEG") else None,
        media_type="IMAGE",
        sentiment_state=state,
        permalink=permalink,
    )


def _vm(record: MentionRecord, *, new_since: datetime | None = None) -> MentionVM:
    return to_vm(record, new_since=new_since)


# --- columns ----------------------------------------------------------------------------


def test_caption_mention_shows_its_author_type_and_full_text() -> None:
    vm = _vm(_record())

    assert (vm.kind, vm.kind_label) == ("post", "Publicación")
    assert (vm.author, vm.author_note) == ("@autora_demo", "")
    assert vm.text == "me encanta qualifymkt.co"
    assert vm.text_unavailable is False


def test_comment_mention_never_borrows_the_publication_author() -> None:
    vm = _vm(_record(comment=True))

    assert (vm.kind, vm.kind_label) == ("comment", "Comentario")
    assert vm.author == NOT_AVAILABLE
    assert vm.author_note == AUTHOR_NOTE_COMMENT
    assert vm.text == "@qualifymkt.co mira esto"


def test_a_comment_on_an_own_post_shows_its_commenter() -> None:
    """Only the `comments` webhook writes a comment row's author, and it is the commenter."""
    vm = _vm(replace(_record(comment=True), author_username="yesii_roa"))

    assert (vm.kind, vm.author, vm.author_note) == ("comment", "@yesii_roa", "")


def test_an_unread_comment_never_shows_an_author() -> None:
    record = replace(
        _record(comment=True, enrichment=ENRICHMENT_FAILED), author_username="yesii_roa"
    )

    assert (_vm(record).author, _vm(record).author_note) == (NOT_AVAILABLE, AUTHOR_NOTE_UNREAD)


def test_a_failed_meta_read_says_so_in_author_and_text() -> None:
    vm = _vm(_record(enrichment=ENRICHMENT_FAILED, caption=None))

    assert (vm.author, vm.author_note) == (NOT_AVAILABLE, AUTHOR_NOTE_UNREAD)
    assert (vm.text, vm.text_unavailable) == (CONTENT_UNAVAILABLE, True)
    assert vm.likes == NO_VALUE


def test_a_post_without_author_explains_why() -> None:
    vm = _vm(_record(author=None))

    assert (vm.author, vm.author_note) == (NOT_AVAILABLE, AUTHOR_NOTE_POST)


def test_blank_text_reads_sin_texto() -> None:
    vm = _vm(_record(caption="   "))

    assert (vm.text, vm.text_unavailable) == (NO_TEXT, True)


def test_likes_are_the_mentions_own_and_never_a_made_up_zero() -> None:
    assert (_vm(_record()).likes, _vm(_record()).likes_note) == ("5", "")
    assert _vm(_record(comment=True, like_count=0)).likes == "0"  # a real zero
    hidden = _vm(_record(like_count=None))
    assert (hidden.likes, hidden.likes_note) == (NO_VALUE, LIKES_NOTE_HIDDEN)
    missing = _vm(_record(comment=True, like_count=None))
    assert (missing.likes, missing.likes_note) == (NO_VALUE, LIKES_NOTE_MISSING)


def test_the_link_is_shown_only_when_instagram_gave_one() -> None:
    assert _vm(_record(permalink="https://www.instagram.com/p/A/")).permalink == (
        "https://www.instagram.com/p/A/"
    )
    assert _vm(_record()).permalink == ""


def test_the_date_is_the_mentions_own_falling_back_to_reception() -> None:
    # 14:00 / 14:05 UTC in the display zone (America/Caracas, UTC-4).
    assert _vm(_record()).date == "13 oct 2026, 10:00"
    assert _vm(_record(posted_at=None)).date == "13 oct 2026, 10:05"


def test_format_moment_uses_spanish_months() -> None:
    assert format_moment(datetime(2026, 1, 5, 12, 0, tzinfo=UTC)) == "5 ene 2026, 08:00"
    assert format_moment(None) == NOT_AVAILABLE


def test_account_labels_match_records_by_uuid_and_keep_disconnected_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mentions_provider,
        "connections_for",
        lambda tenant_id: [
            _Connection(
                id=str(CONNECTION), platform="instagram", external_username="qualifymkt.co"
            ),
            _Connection(id=str(uuid4()), platform="instagram", external_username=""),
            _Connection(id=str(uuid4()), platform="facebook", external_username="pagina"),
        ],
    )

    labels = mentions_provider.account_labels(TENANT)

    assert labels[CONNECTION] == "@qualifymkt.co"
    assert sorted(labels.values()) == ["@qualifymkt.co", UNKNOWN_ACCOUNT]


def test_account_options_are_unique_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        mentions_provider,
        "connections_for",
        lambda tenant_id: [
            _Connection(id=str(uuid4()), platform="instagram", external_username=""),
            _Connection(id=str(uuid4()), platform="instagram", external_username=""),
        ],
    )

    assert sorted(mentions_provider.account_options(TENANT)) == [
        UNKNOWN_ACCOUNT,
        f"{UNKNOWN_ACCOUNT} (2)",
    ]


# --- sentiment and the "Nueva" mark -----------------------------------------------------


@pytest.mark.parametrize("state", ["POS", "NEU", "NEG", "PENDING", "NO_TEXT", "ERROR"])
def test_every_sentiment_state_passes_through_untouched(state: str) -> None:
    assert _vm(_record(state=state)).sentiment_state == state


def test_rows_received_after_the_previous_snapshot_are_marked_new() -> None:
    cut = datetime(2026, 10, 13, 14, 3, tzinfo=UTC)

    assert _vm(_record(), new_since=cut).is_new is True  # received 14:05
    assert _vm(_record(), new_since=datetime(2026, 10, 13, 15, 0, tzinfo=UTC)).is_new is False
    assert _vm(_record(), new_since=None).is_new is False


# --- page assembly ----------------------------------------------------------------------


def test_load_page_returns_the_scope_summary_apart_from_the_filtered_total(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_of = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
    seen: dict = {}

    def fake_page(
        *, tenant_id: UUID, query: MentionQuery, page: int, as_of: datetime | None
    ) -> MentionPage:
        seen.update(query=query, page=page, as_of=as_of)
        return MentionPage(
            rows=(_record(),),
            counts=MentionCounts(total=14),
            page=2,
            page_size=12,
            as_of=as_of or datetime(2026, 10, 13, 16, 0, tzinfo=UTC),
        )

    def fake_summary(*, tenant_id: UUID, query: MentionQuery, as_of: datetime) -> MentionCounts:
        seen.update(summary_query=query, summary_as_of=as_of)
        return MentionCounts(total=57, positive=3, pending=50, no_text=2, error=2)

    monkeypatch.setattr(mentions_provider, "list_mentions_page_for_tenant", fake_page)
    monkeypatch.setattr(mentions_provider, "summarize_mentions_for_tenant", fake_summary)

    since = datetime(2026, 10, 1, tzinfo=UTC)
    query = MentionQuery(connection_id=CONNECTION, origin="comment", search="hola", since=since)
    vm = mentions_provider.load_page(TENANT, query=query, page=2, as_of=as_of.isoformat())

    assert (seen["query"], seen["page"], seen["as_of"]) == (query, 2, as_of)
    # The summary keeps the scope (account + period) and drops search / origin.
    assert seen["summary_query"] == MentionQuery(connection_id=CONNECTION, since=since)
    assert seen["summary_as_of"] == as_of
    assert vm.filtered_total == 14
    assert (vm.summary.total, vm.summary.pending, vm.summary.error) == (57, 50, 2)
    assert (vm.page, vm.total_pages, vm.pages_label) == (2, 2, "Total de 2 páginas")


def test_count_new_needs_a_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mentions_provider, "count_new_mentions_for_tenant", lambda **kwargs: 7)

    assert mentions_provider.count_new(TENANT, query=MentionQuery(), as_of="") == 0
    assert (
        mentions_provider.count_new(TENANT, query=MentionQuery(), as_of="2026-10-13T15:00:00+00:00")
        == 7
    )


def test_day_and_time_are_also_given_apart_for_the_stacked_layout() -> None:
    vm = _vm(_record())

    assert (vm.day, vm.time) == ("13 oct 2026", "10:00")
    assert vm.date == "13 oct 2026, 10:00"


async def test_refresh_content_passes_the_visible_ids_as_uuids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.mentions.composition import ContentRefreshReport

    seen: dict = {}
    report = ContentRefreshReport(
        in_scope=2, refreshed=2, already_fresh=0, failed=0, not_attempted=0
    )

    async def fake_refresh(*, tenant_id: UUID, mention_ids: tuple[UUID, ...]):
        seen.update(tenant_id=tenant_id, mention_ids=mention_ids)
        return report

    monkeypatch.setattr(mentions_provider, "refresh_mentions_content", fake_refresh)
    tenant, first, second = uuid4(), uuid4(), uuid4()

    result = await mentions_provider.refresh_content(tenant, [str(first), str(second)])

    assert result is report
    assert seen == {"tenant_id": tenant, "mention_ids": (first, second)}


async def test_refresh_scope_hands_the_scope_query_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.mentions.composition import ContentRefreshReport

    seen: dict = {}
    report = ContentRefreshReport(
        in_scope=30, refreshed=30, already_fresh=0, failed=0, not_attempted=0
    )

    async def fake_scope(*, tenant_id: UUID, scope: MentionQuery):
        seen.update(tenant_id=tenant_id, scope=scope)
        return report

    monkeypatch.setattr(mentions_provider, "refresh_mentions_in_scope", fake_scope)
    tenant, scope = uuid4(), MentionQuery(connection_id=uuid4())

    assert await mentions_provider.refresh_scope(tenant, scope=scope) is report
    assert seen == {"tenant_id": tenant, "scope": scope}
