"""N1 (m-25142900): a video historia gets its cover from the worker's pass and becomes a
story ad source — against real Postgres and RLS, with two businesses."""

from __future__ import annotations

import io
from uuid import uuid4

import pytest
from packages.api.tests.test_ad_audience_db import make_audience_world
from packages.api.tests.test_ad_unpublished_db import make_unpublished_world
from qualify_creative.video.still import VideoStillError
from qualify_shared.db.session import tenant_session
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore
from sqlalchemy import text

from qualify_api.ads.story_readiness import StoryBlock, story_block
from qualify_api.ads.unpublished_repository import load_image_source
from qualify_api.creative import story_covers
from qualify_api.creative.story_covers import COVER_VERSION, pending, sweep
from qualify_api.tenancy.acting import acting_login

pytestmark = pytest.mark.db


def _frame(*_args, **_kwargs) -> bytes:
    from packages.api.tests.test_story_covers import jpeg

    return jpeg(90, 160)


def _video_historia(gate: ObjectGate):
    """A ready historia whose only 9:16 file is an MP4 (the fixture's image turned video)."""
    source, _, login, _ = make_unpublished_world(make_audience_world())
    key = f"t/{source.tenant_id}/generated/{source.draft_id}/{source.vertical.asset_id}.mp4"
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
    gate.put_media(source.tenant_id, key, io.BytesIO(b"mp4 bytes"), "video/mp4")
    return source, login


def _covers(tenant) -> list[dict]:
    with tenant_session(tenant) as session:
        return [
            dict(row)
            for row in session.execute(
                text("SELECT * FROM piece_story_covers ORDER BY created_at")
            ).mappings()
        ]


@pytest.fixture
def gate() -> ObjectGate:
    return ObjectGate(MemoryObjectStore())


def test_the_pass_makes_one_cover_and_the_historia_becomes_ready(gate) -> None:
    mine, login = _video_historia(gate)
    other, other_login = _video_historia(gate)
    with acting_login(login):
        assert story_block(mine.tenant_id, mine.draft_id) == StoryBlock.VIDEO_WITHOUT_COVER

    assert sweep([mine.tenant_id], gate, grab=_frame) == 1
    (cover,) = _covers(mine.tenant_id)
    assert cover["state"] == "stored" and cover["pipeline_version"] == COVER_VERSION
    assert cover["source_asset_id"] == mine.vertical.asset_id  # provenance: its video
    assert cover["version_id"] == mine.version_id and (cover["width"], cover["height"]) == (90, 160)
    assert gate.has_object(mine.tenant_id, cover["object_key"])
    with acting_login(login):
        assert story_block(mine.tenant_id, mine.draft_id) is None
        # the ad itself takes it as the video's thumbnail
        loaded = load_image_source(
            mine.tenant_id,
            mine.draft_id,
            mine.account_id,
            None,
            mine.vertical.asset_id,
            (None, cover["id"]),
        )
    assert loaded.vertical.thumbnail.object_key == cover["object_key"]

    # idempotent: nothing left to do, a second pass makes nothing
    assert pending(mine.tenant_id) == [] and sweep([mine.tenant_id], gate, grab=_frame) == 0
    assert len(_covers(mine.tenant_id)) == 1
    # the other business: untouched, and it never sees the first one's cover (RLS)
    assert _covers(other.tenant_id) == []
    with acting_login(other_login):
        assert story_block(other.tenant_id, other.draft_id) == StoryBlock.VIDEO_WITHOUT_COVER


def test_a_historia_with_its_own_vertical_image_is_left_alone(gate) -> None:
    source, *_ = make_unpublished_world(make_audience_world())  # its 9:16 file is a PNG
    assert pending(source.tenant_id) == []


def test_a_cover_never_hides_an_edit_after_approval(gate) -> None:
    mine, login = _video_historia(gate)
    sweep([mine.tenant_id], gate, grab=_frame)
    with tenant_session(mine.tenant_id) as session:
        session.execute(
            text("UPDATE content_drafts SET revision=revision+1 WHERE id=:id"),
            {"id": mine.draft_id},
        )
    with acting_login(login):  # edited after approval: the cause is the edit, not the cover
        assert story_block(mine.tenant_id, mine.draft_id) == StoryBlock.EDITED


def test_a_video_without_a_frame_is_recorded_and_not_retried(gate) -> None:
    mine, login = _video_historia(gate)

    def broken(*_args, **_kwargs) -> bytes:
        raise VideoStillError("no frame")

    assert sweep([mine.tenant_id], gate, grab=broken) == 0
    (cover,) = _covers(mine.tenant_id)
    assert cover["state"] == "failed" and cover["object_key"] is None
    assert pending(mine.tenant_id) == []
    with acting_login(login):  # a real failure keeps its own text
        assert story_block(mine.tenant_id, mine.draft_id) == StoryBlock.VIDEO_WITHOUT_COVER


def test_a_failed_r2_write_leaves_nothing_and_the_next_pass_retries(gate, monkeypatch) -> None:
    mine, login = _video_historia(gate)

    def refuse(*_args, **_kwargs) -> None:
        raise RuntimeError("R2 down")

    monkeypatch.setattr(gate, "put_media", refuse)
    assert sweep([mine.tenant_id], gate, grab=_frame) == 0  # logged, never raised
    assert _covers(mine.tenant_id) == [] and len(pending(mine.tenant_id)) == 1
    monkeypatch.undo()
    assert sweep([mine.tenant_id], gate, grab=_frame) == 1


def test_one_failing_video_never_stops_the_others(gate) -> None:
    broken, _ = _video_historia(gate)
    fine, login = _video_historia(gate)
    with tenant_session(broken.tenant_id) as session:  # its file is not where the row says
        session.execute(
            text("UPDATE image_assets SET object_key=object_key || '.lost' WHERE id=:id"),
            {"id": broken.vertical.asset_id},
        )
    timeouts = {"count": 0}

    def slow_once(*args, **kwargs) -> bytes:
        if not timeouts["count"]:
            timeouts["count"] += 1
            raise VideoStillError("ffmpeg timed out after 30 s")
        return _frame()

    # the lost file is recorded once; the timeout is the machine's: not recorded, retried
    assert sweep([broken.tenant_id, fine.tenant_id], gate, grab=slow_once) == 0
    assert [c["failure_reason"] for c in _covers(broken.tenant_id)] == ["source_missing"]
    assert _covers(fine.tenant_id) == [] and len(pending(fine.tenant_id)) == 1
    assert sweep([broken.tenant_id, fine.tenant_id], gate, grab=slow_once) == 1
    with acting_login(login):
        assert story_block(fine.tenant_id, fine.draft_id) is None


def test_a_new_file_in_the_same_row_gets_its_own_cover(gate) -> None:
    """A re-join writes a new file into the video's row: the old frame no longer counts."""
    mine, login = _video_historia(gate)
    sweep([mine.tenant_id], gate, grab=_frame)
    new_key = f"t/{mine.tenant_id}/generated/{mine.draft_id}/r2/video.mp4"
    gate.put_media(mine.tenant_id, new_key, io.BytesIO(b"new mp4"), "video/mp4")
    with tenant_session(mine.tenant_id) as session:
        session.execute(
            text("UPDATE image_assets SET object_key=:key WHERE id=:id"),
            {"key": new_key, "id": mine.vertical.asset_id},
        )
    with acting_login(login):
        assert story_block(mine.tenant_id, mine.draft_id) == StoryBlock.VIDEO_WITHOUT_COVER
    assert sweep([mine.tenant_id], gate, grab=_frame) == 1
    newest = _covers(mine.tenant_id)[-1]
    assert newest["source_object_key"] == new_key and newest["object_key"].startswith(
        f"t/{mine.tenant_id}/generated/{mine.draft_id}/r2/"
    )
    with acting_login(login):
        assert story_block(mine.tenant_id, mine.draft_id) is None


def test_discovery_lists_only_businesses_with_work(gate) -> None:
    mine, _ = _video_historia(gate)
    ready, *_ = make_unpublished_world(make_audience_world())
    found = story_covers.discover_tenants()
    assert mine.tenant_id in found and ready.tenant_id not in found
    sweep([mine.tenant_id], gate, grab=_frame)
    assert mine.tenant_id not in story_covers.discover_tenants()
    assert uuid4() not in found
