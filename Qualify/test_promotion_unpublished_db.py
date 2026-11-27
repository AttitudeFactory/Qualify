"""The unpublished-piece source read against real Postgres and RLS (m-24828982)."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
from qualify_api.creative.story_covers import sweep
from qualify_api.tenancy.acting import acting_login
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore
from sqlalchemy import text

from packages.api.tests.test_ad_audience_db import audience_world as shared_audience_world
from packages.api.tests.test_ad_unpublished_db import publish
from packages.api.tests.test_ad_unpublished_db import unpublished_world as shared_unpublished
from packages.api.tests.test_story_covers import jpeg

from .promotion_unpublished_provider import story_ad_ready, story_ads_ready, unpublished_sources

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
    source, _, login, actor = unpublished_world
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
    publish(source, actor)  # m-25130283: Qualify published it, as a story
    with acting_login(login):
        assert unpublished_sources(source.tenant_id, source.draft_id) == []
        # Epic D1: the story path is a new 9:16 creative, so a published piece stays on it.
        (story,) = unpublished_sources(source.tenant_id, source.draft_id, story=True)
        assert story.story and story_ad_ready(source.tenant_id, source.draft_id)


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


# -- HIS-1 (m-25130281): the cards' batched readiness read ------------------------------


def test_batched_readiness_marks_only_a_piece_the_story_ad_can_use(unpublished_world):
    """Approved, unpublished, 9:16 and an ad account → ready; without the account or
    the 9:16 file → not; an unknown id never makes the read fail."""
    source, _, login, _ = unpublished_world
    with acting_login(login):
        ready = story_ads_ready(source.tenant_id, [source.draft_id, uuid4()])
    assert ready == {source.draft_id}
    with tenant_session(source.tenant_id) as session:
        session.execute(
            text("UPDATE ad_accounts SET selected=false WHERE id=:id"), {"id": source.account_id}
        )
    with acting_login(login):
        assert story_ads_ready(source.tenant_id, [source.draft_id]) == set()
    with tenant_session(source.tenant_id) as session:
        session.execute(
            text("UPDATE ad_accounts SET selected=true WHERE id=:id"), {"id": source.account_id}
        )
        session.execute(
            text("UPDATE image_assets SET height=width WHERE id=:id"),
            {"id": source.vertical.asset_id},
        )
    with acting_login(login):
        assert story_ads_ready(source.tenant_id, [source.draft_id]) == set()


def test_batched_readiness_never_crosses_businesses(unpublished_world):
    source, _, login, _ = unpublished_world
    with acting_login(login):
        assert story_ads_ready(source.tenant_id, [source.draft_id]) == {source.draft_id}
    # Another business asking for the same id sees nothing of it (RLS).
    assert story_ads_ready(uuid4(), [source.draft_id]) == set()


def test_the_cards_offer_a_historia_qualify_already_published(unpublished_world):
    """HIS-1 + epic D1: the gallery's batched readiness never hides a published historia."""
    source, _, login, actor = unpublished_world
    publish(source, actor)
    with acting_login(login):
        assert story_ads_ready(source.tenant_id, [source.draft_id]) == {source.draft_id}


def test_a_video_historia_with_its_automatic_cover_is_offered(unpublished_world):
    """N1 (m-25142900): the worker's cover makes a video historia a story ad source; the
    cover is offered as the video's «Portada» and never becomes a file of the piece."""
    source, _, login, _ = unpublished_world
    gate = ObjectGate(MemoryObjectStore())
    key = f"t/{source.tenant_id}/generated/{source.draft_id}/video.mp4"
    with tenant_session(source.tenant_id) as session:
        session.execute(
            text("""UPDATE image_assets SET media_type='video',content_type='video/mp4',
              object_key=:key WHERE id=:id"""),
            {"key": key, "id": source.vertical.asset_id},
        )
        session.execute(
            text("UPDATE content_drafts SET category='story' WHERE id=:id"),
            {"id": source.draft_id},
        )
    gate.put_media(source.tenant_id, key, io.BytesIO(b"mp4"), "video/mp4")
    with acting_login(login):
        assert not story_ad_ready(source.tenant_id, source.draft_id)
    assert sweep([source.tenant_id], gate, grab=lambda *_a, **_k: jpeg(90, 160)) == 1
    with acting_login(login):
        assert story_ad_ready(source.tenant_id, source.draft_id)
        assert story_ads_ready(source.tenant_id, [source.draft_id]) == {source.draft_id}
        video, *_ = unpublished_sources(source.tenant_id, source.draft_id, story=True)
    assert video.media_kind == "videos"
    assert [m.id for m in video.vertical_media] == [str(source.vertical.asset_id)]
    assert len(video.vertical_covers) == 1
    with tenant_session(source.tenant_id) as session:
        images = session.scalar(
            text("SELECT count(*) FROM image_assets WHERE draft_id=:id AND width*16=height*9"),
            {"id": source.draft_id},
        )
    assert images == 1  # only the video itself: the cover lives apart
