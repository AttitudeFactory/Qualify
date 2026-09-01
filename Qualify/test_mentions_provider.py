"""`mentions_provider.list_mentions` (QUA-49) — a plain function, no Reflex `State`
involved, so it needs no `PYTEST_CURRENT_TEST` workaround the way `DashboardState`'s own
event handlers do (see `test_inbox_state.py`'s module docstring for that constraint).
`qualify_api.mentions.composition.list_mentions_for_tenant` and `.inbox_provider.
instagram_connections` are monkeypatched — this module owns only the VM projection, not
either backend call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from . import mentions_provider
from .publishing_vm import ConnectionOptionVM

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
CONNECTION = UUID("b0000000-0000-4000-8000-000000000001")


class _Record:
    """Minimal stand-in for `qualify_api.mentions.repository.MentionRecord` — only the
    attributes `mentions_provider.list_mentions` actually reads."""

    def __init__(
        self,
        *,
        id: UUID | None = None,
        connection_id: UUID = CONNECTION,
        platform: str = "instagram",
        external_account_id: str = "ig-user-1",
        caption: str | None = None,
        text: str | None = None,
        author_username: str | None = "creator1",
        like_count: int | None = 5,
        content_posted_at: datetime | None = datetime(2026, 8, 1, tzinfo=UTC),
        received_at: datetime = datetime(2026, 8, 2, tzinfo=UTC),
        sentiment_label: str | None = None,
    ) -> None:
        self.id = id or uuid4()
        self.connection_id = connection_id
        self.platform = platform
        self.external_account_id = external_account_id
        self.caption = caption
        self.text = text
        self.author_username = author_username
        self.like_count = like_count
        self.content_posted_at = content_posted_at
        self.received_at = received_at
        self.sentiment_label = sentiment_label


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    records: list,
    connections: list[ConnectionOptionVM] | None = None,
) -> None:
    monkeypatch.setattr(mentions_provider, "list_mentions_for_tenant", lambda tenant_id: records)
    monkeypatch.setattr(
        mentions_provider, "instagram_connections", lambda tenant_id: connections or []
    )


def test_caption_mention_uses_caption_as_display_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, records=[_Record(caption="hola @qualifymkt.co", text=None)])

    rows = mentions_provider.list_mentions(TENANT)

    assert rows[0].caption == "hola @qualifymkt.co"


def test_comment_mention_uses_text_as_display_text(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, records=[_Record(caption=None, text="Shout out to @qualifymkt.co")])

    rows = mentions_provider.list_mentions(TENANT)

    assert rows[0].caption == "Shout out to @qualifymkt.co"


def test_missing_content_renders_as_no_data_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    """An enrichment-failed mention (both `caption`/`text` `None`) must never render an
    empty string or `"None"` — same "—" placeholder discipline as `views`/`likes`."""
    _patch(monkeypatch, records=[_Record(caption=None, text=None)])

    rows = mentions_provider.list_mentions(TENANT)

    assert rows[0].caption == mentions_provider.NO_DATA


def test_views_is_always_the_no_data_placeholder(monkeypatch: pytest.MonkeyPatch) -> None:
    """The audit's hard rule: Meta never gives a view count for a mention on content the
    connected account does not own — this must never become a number, ever."""
    _patch(monkeypatch, records=[_Record()])

    rows = mentions_provider.list_mentions(TENANT)

    assert rows[0].views == mentions_provider.NO_DATA


def test_likes_renders_the_real_count_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, records=[_Record(like_count=42)])

    rows = mentions_provider.list_mentions(TENANT)

    assert rows[0].likes == "42"


def test_likes_is_the_no_data_placeholder_when_meta_omitted_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, records=[_Record(like_count=None)])

    rows = mentions_provider.list_mentions(TENANT)

    assert rows[0].likes == mentions_provider.NO_DATA


def test_sentiment_passes_through_the_raw_pipeline_label(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, records=[_Record(sentiment_label="NEG")])

    rows = mentions_provider.list_mentions(TENANT)

    assert rows[0].sentiment == "NEG"


def test_unanalyzed_sentiment_is_an_empty_string_not_a_fabricated_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ui.primitives.sentiment_badge` matches `""` to "Sin analizar" — this must never
    become `"NEU"` just because a mention has not been analyzed yet."""
    _patch(monkeypatch, records=[_Record(sentiment_label=None)])

    rows = mentions_provider.list_mentions(TENANT)

    assert rows[0].sentiment == ""


def test_brand_is_the_connected_accounts_own_username(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(
        monkeypatch,
        records=[_Record(connection_id=CONNECTION)],
        connections=[
            ConnectionOptionVM(
                id=CONNECTION, external_username="qualifymkt.co", platform="instagram"
            )
        ],
    )

    rows = mentions_provider.list_mentions(TENANT)

    assert rows[0].brand == "qualifymkt.co"


def test_brand_falls_back_to_external_account_id_when_connection_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A connection that vanished/rotated between the mention being persisted and this
    read must still show something identifiable, never crash the whole list."""
    _patch(
        monkeypatch,
        records=[_Record(connection_id=uuid4(), external_account_id="ig-orphaned")],
        connections=[],
    )

    rows = mentions_provider.list_mentions(TENANT)

    assert rows[0].brand == "ig-orphaned"


def test_platform_is_passed_through_lowercase_for_the_platform_badge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ui.tokens.PLATFORM_SCALE`/`PLATFORM_LABEL` key on lowercase `"instagram"` — this
    pins that `mentions_provider` never re-cases it."""
    _patch(monkeypatch, records=[_Record(platform="instagram")])

    rows = mentions_provider.list_mentions(TENANT)

    assert rows[0].platform == "instagram"
