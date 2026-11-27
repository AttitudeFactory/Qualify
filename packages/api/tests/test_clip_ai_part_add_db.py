"""m-25142982 against Postgres: a new «parte con IA» added to a made Clip writes in ONE
transaction under the Clip's fence — the new child at the next place, its vista previa,
the Clip's next version with its local-build row, both queued after the commit; the same
`request_key` again adds nothing; a refusal writes nothing; another business sees none of
it (RLS). No vendor is called."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.schemas import VideoPartPlan
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.creative import clip_ai_parts as cap

from .test_clip_ai_part_actions_db import _made, _status, _world
from .test_clip_ai_parts_db import _count, _create

pytestmark = pytest.mark.db


def _made_clip(world: dict[str, Any]) -> tuple[cap.ClipWithAiParts, str]:
    """A Clip as its first assembly leaves it: its part a stretch of its file, made."""
    tenant, user, content = world["tenant"], world["user"], world["content"]
    made = _create(world)
    part = made.part_ids[0]
    key = _made(tenant, part)
    clip = content.repository.get_draft(tenant_id=tenant, draft_id=made.clip_id)
    asked = content.repository.get_brief(tenant_id=tenant, brief_id=clip.brief_id)
    video = cap.PostgresAiPartsStore().part_video(tenant_id=tenant, part_id=part)
    assert video is not None
    resolved = cap.resolve(asked, {0: video}).brief
    resolved = resolved.model_copy(
        update={"media": resolved.media.model_copy(update={"derived_from_brief_id": clip.brief_id})}
    )
    content.repository.replace_brief(
        tenant_id=tenant, draft_id=made.clip_id, user_id=user, brief=resolved
    )
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'generated' WHERE id = :c"),
            {"c": made.clip_id},
        )
        session.execute(
            text("UPDATE creative_jobs SET status = 'succeeded' WHERE draft_id = :c"),
            {"c": made.clip_id},
        )
    return made, key


def _entry() -> VideoPartPlan:
    return VideoPartPlan(mode="reference", seconds=4, description="Las manos amasando")


def test_a_new_part_is_written_in_one_go_and_the_same_tap_twice_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    tenant, user = world["tenant"], world["user"]
    made, key = _made_clip(world)
    actions = world["actions"]
    assert actions.can_add_part(tenant_id=tenant, clip_id=made.clip_id)
    args: dict[str, Any] = {
        "tenant_id": tenant,
        "user_id": user,
        "clip_id": made.clip_id,
        "entry": _entry(),
        "position": 1,
        "request_key": uuid4(),
    }
    new = actions.add_part(**args)
    assert _status(tenant, new) == ("drafting", 1)
    assert _status(tenant, made.clip_id) == ("drafting", 2)
    store = cap.PostgresAiPartsStore()
    rows = store.parts_of(tenant_id=tenant, clip_id=made.clip_id)
    assert [(r.id, r.slot) for r in rows] == [(made.part_ids[0], 1), (new, 2)]
    assert _status(tenant, made.part_ids[0]) == ("generated", 1)  # reused, not asked again
    charges = "SELECT count(*) FROM creation_charges WHERE draft_id = :d"
    assert _count(tenant, charges, d=new) == 1
    local = (
        "SELECT count(*) FROM creation_charges WHERE draft_id = :d AND revision = 2 "
        "AND request_kind = 'local_video'"
    )
    assert _count(tenant, local, d=made.clip_id) == 1  # the owner's assembly counts
    queued = "SELECT count(*) FROM creative_jobs WHERE draft_id = :d AND status = 'queued'"
    assert _count(tenant, queued, d=new) == 1
    assert _count(tenant, queued, d=made.clip_id) == 1
    repo = world["content"].repository
    clip = repo.get_draft(tenant_id=tenant, draft_id=made.clip_id)
    brief = repo.get_brief(tenant_id=tenant, brief_id=clip.brief_id)
    assert [s.kind for s in brief.media.segments] == ["video", "ai_part", "video"]
    assert brief.media.segments[2].key == key
    assert cap.entry_slots(brief, rows) == {0: 2}
    # another business sees none of it (RLS)
    assert store.parts_of(tenant_id=uuid4(), clip_id=made.clip_id) == ()
    # the same tap again: the same part, nothing more
    total = _count(tenant, "SELECT count(*) FROM creation_charges")
    assert actions.add_part(**args) == new
    assert _count(tenant, "SELECT count(*) FROM creation_charges") == total
    assert _count(tenant, queued, d=new) == 1
    # the Clip is busy now: nothing else is added
    assert not actions.can_add_part(tenant_id=tenant, clip_id=made.clip_id)
    with pytest.raises(cap.ClipAiPartsRefused):
        actions.add_part(**{**args, "request_key": uuid4()})
    assert _count(tenant, "SELECT count(*) FROM creation_charges") == total


def test_an_approved_clip_takes_no_new_part_and_nothing_is_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(monkeypatch)
    tenant, user = world["tenant"], world["user"]
    made, _ = _made_clip(world)
    with tenant_session(tenant) as session:
        session.execute(
            text("UPDATE content_drafts SET status = 'approved' WHERE id = :c"),
            {"c": made.clip_id},
        )
    charges = _count(tenant, "SELECT count(*) FROM creation_charges")
    drafts = _count(tenant, "SELECT count(*) FROM content_drafts")
    with pytest.raises(cap.ClipAiPartsRefused) as refused:
        world["actions"].add_part(
            tenant_id=tenant, user_id=user, clip_id=made.clip_id, entry=_entry(), position=2
        )
    assert refused.value.code == "clip_approved"
    assert _count(tenant, "SELECT count(*) FROM creation_charges") == charges
    assert _count(tenant, "SELECT count(*) FROM content_drafts") == drafts
