"""EF-06 (m-25026574) isolation against the compose Postgres: the job of one business
cannot read the `segments` (its own videos and photos) of another's piece. The job reads
its piece through `tenant_session` (RLS), and the producer refuses any stretch whose key
is not the business's before a single read."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative.service import PostgresContentRepository
from qualify_api.creative.video_pipeline import local
from qualify_api.creative.video_pipeline.recipe import recipe_of

from .test_piece_layers_db import _piece
from .test_video_pipeline_local import ReadingStore, _local_clip, _stamped

pytestmark = pytest.mark.db


def _with_segments(tenant_id: UUID) -> tuple[UUID, UUID, str]:
    """A `local` piece of `tenant_id` whose brief keeps its stretches."""
    _, draft_id, _ = _piece(tenant_id, version=False)
    key = f"uploads/{tenant_id}/{uuid4()}.mp4"
    media = {"clip_reference_mode": "local", "segments": [{"key": key, "start_s": 0, "end_s": 4}]}
    with tenant_session(tenant_id) as session:
        brief_id = session.execute(
            text(
                "UPDATE content_briefs SET media = CAST(:m AS jsonb) WHERE id = "
                "(SELECT brief_id FROM content_drafts WHERE id = :d) RETURNING id"
            ),
            {"m": json.dumps(media), "d": draft_id},
        ).scalar_one()
    return draft_id, brief_id, key


def test_a_job_of_one_business_cannot_read_the_segments_of_another(
    seeded_ab: tuple[UUID, UUID],
) -> None:
    tenant_a, tenant_b = seeded_ab
    draft_b, brief_b, key_b = _with_segments(tenant_b)
    # the job reads its piece through its own tenant's door: B's piece is not there
    repo = PostgresContentRepository()
    assert repo.get_draft(tenant_id=tenant_a, draft_id=draft_b) is None
    with tenant_session(tenant_a) as session:
        seen = session.execute(
            text("SELECT media->'segments' FROM content_briefs WHERE id = :b"), {"b": brief_b}
        ).all()
        everywhere = session.execute(
            text("SELECT count(*) FROM content_briefs WHERE media::text LIKE :k"),
            {"k": f"%{key_b}%"},
        ).scalar_one()
    assert seen == [] and everywhere == 0
    # B's own door sees them
    with tenant_session(tenant_b) as session:
        (segments,) = session.execute(
            text("SELECT media->'segments' FROM content_briefs WHERE id = :b"), {"b": brief_b}
        ).one()
    assert segments[0]["key"] == key_b


def test_a_job_of_one_business_never_opens_a_file_of_another(
    seeded_ab: tuple[UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a brief that names B's file (forged) is refused for A before any read."""
    from qualify_creative.schemas import SourceSegment

    from qualify_api.creative.queue_dispatch import SWITCH

    monkeypatch.setenv(SWITCH, "queue")
    tenant_a, tenant_b = seeded_ab
    _, _, key_b = _with_segments(tenant_b)
    store = ReadingStore({key_b: b"not read"})
    forged = SourceSegment(key=key_b, start_s=0.0, end_s=4.0)
    brief = _stamped(_local_clip(forged))
    assert recipe_of(brief)[0].segments[0].key == key_b
    outcome = local.produce_local(
        tenant_id=tenant_a, draft_id=uuid4(), brief=brief, store=store, save=None
    )
    assert outcome.failure == "route_blocked_by_policy" and store.reads == []
