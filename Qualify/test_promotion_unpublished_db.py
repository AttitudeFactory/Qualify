"""The unpublished-piece source read against real Postgres and RLS (m-24828982)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from qualify_api.tenancy.acting import acting_login
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from packages.api.tests.test_ad_audience_db import audience_world as shared_audience_world
from packages.api.tests.test_ad_unpublished_db import unpublished_world as shared_unpublished

from .promotion_unpublished_provider import unpublished_sources

pytestmark = pytest.mark.db
audience_world = shared_audience_world
unpublished_world = shared_unpublished


def test_unpublished_piece_offers_its_own_pair_scoped_to_its_business(unpublished_world):
    source, _, login, _ = unpublished_world
    with acting_login(login):
        (row,) = unpublished_sources(source.tenant_id, source.draft_id)
    assert row.media_kind == "images" and row.ad_account_id == str(source.account_id)
    assert [m.id for m in row.feed_media] == [str(source.feed.asset_id)]
    assert [m.id for m in row.vertical_media] == [str(source.vertical.asset_id)]
    assert not row.feed_covers and not row.vertical_covers
    # Another business sees nothing of it (RLS), not even the piece.
    assert unpublished_sources(uuid4(), source.draft_id) == []


def test_a_published_or_unselected_source_is_not_offered(unpublished_world):
    source, _, login, _ = unpublished_world
    with tenant_session(source.tenant_id) as session:
        session.execute(
            text("UPDATE ad_accounts SET selected=false WHERE id=:id"), {"id": source.account_id}
        )
    with acting_login(login):
        assert unpublished_sources(source.tenant_id, source.draft_id) == []
    with tenant_session(source.tenant_id) as session:
        session.execute(
            text("UPDATE ad_accounts SET selected=true WHERE id=:id"), {"id": source.account_id}
        )
        session.execute(
            text("UPDATE content_drafts SET published_media_id='1' WHERE id=:id"),
            {"id": source.draft_id},
        )
    with acting_login(login):
        assert unpublished_sources(source.tenant_id, source.draft_id) == []


def test_story_source_offers_only_the_vertical_file(unpublished_world):
    """m-25026350: a story with a link button never uses the 4:5 file."""
    source, _, login, _ = unpublished_world
    with acting_login(login):
        (row,) = unpublished_sources(source.tenant_id, source.draft_id, story=True)
    assert row.story and row.media_kind == "images" and not row.feed_media
    assert [m.id for m in row.vertical_media] == [str(source.vertical.asset_id)]
    with acting_login(login):
        (pair,) = unpublished_sources(source.tenant_id, source.draft_id)
    assert row.id != pair.id and not pair.story  # distinct, stable per kind
