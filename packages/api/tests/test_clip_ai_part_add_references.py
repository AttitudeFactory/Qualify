"""m-25142982 with the reference tracks of m-25142725 (PR B): a part added to a made Clip
that was asked on the tracks, and «Hacerla nueva» on one, take from the tracks what their
block takes — never the Clip's tracks themselves (version 0 on the child), with
`PartRef.references` and the Pinterest origins of the photos they took.

Offline only: the doubles of `test_clip_ai_parts` — no vendor, no database, nothing paid."""

from __future__ import annotations

from typing import Any

import pytest
from qualify_creative.schemas import ContentBrief

from qualify_api.creative.composition import SEEDANCE_REFERENCE_MODEL_ENV
from qualify_api.creative.fsm import DRAFTING, GENERATED

from .test_clip_ai_part_actions import _actions, _fail
from .test_clip_ai_parts import (
    World,
    _brief_of,
    _clip,
    _create,
    _entry,
    _made,
    _switches,
    _world,
    assemble_at_the_sources_size,
    assembly_files,
    no_normalize_jobs,
    queue_on,
)
from .test_clip_ai_parts_references_flow import WINDOW, _edit_on_tracks, _on_tracks, _pin, _ref
from .test_content_service import TENANT_ID, USER_ID

__all__ = [  # fixtures used by name, or autouse
    "_switches",
    "assemble_at_the_sources_size",
    "assembly_files",
    "no_normalize_jobs",
    "queue_on",
]


@pytest.fixture(autouse=True)
def _default_model(monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: PT004
    monkeypatch.delenv(SEEDANCE_REFERENCE_MODEL_ENV, raising=False)


def _made_on_tracks(world: World, brief: ContentBrief) -> Any:
    made = _create(world, brief)
    _made(world, made.part_ids[0], 5.0)
    _made(world, made.part_ids[1], 4.0)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    assembled = _brief_of(world, made.clip_id)
    assert assembled.media.clip_references == ()  # the assembly drops the tracks
    return made


def _add(world: World, clip_id: Any, position: int) -> Any:
    return _actions(world).add_part(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=clip_id,
        entry=_entry(5, description="La arepa servida en la mesa"),
        position=position,
    )


def test_an_added_part_takes_the_track_photo_under_its_block_with_its_origin() -> None:
    # the photo track under seconds 4-9: the first part's at «Crear», and the new part's
    # once it is added right after the owner's first video (seconds 4-9 again)
    pinned = _ref("photo", 4.0, 9.0, "pin.png")
    world = _world()
    made = _made_on_tracks(world, _on_tracks(_clip(), pinned, source_pins=(_pin(pinned.key),)))
    new = _add(world, made.clip_id, position=1)
    child = _brief_of(world, new).media
    assert child.clip_references == () and child.references_version == 0
    assert child.clip_image_keys == (pinned.key,)
    assert child.part is not None and child.part.references == (pinned,)
    assert [p.image_key for p in child.source_pins] == [pinned.key]
    # the Clip waiting for it carries no tracks either: only its parts read them
    clip = _brief_of(world, made.clip_id).media
    assert clip.clip_references == () and clip.references_version == 0


def test_an_added_part_under_no_track_photo_takes_none_of_the_clips() -> None:
    photo = _ref("photo", 4.0, 9.0, "arepa.png")
    world = _world()
    made = _made_on_tracks(world, _on_tracks(_clip(), photo))
    new = _add(world, made.clip_id, position=4)  # at the end: seconds 16-21, no photo
    child = _brief_of(world, new).media
    assert child.clip_image_keys == ()
    assert child.part is not None and child.part.references == ()
    assert child.clip_references == () and child.references_version == 0


def test_an_added_part_of_a_clip_without_tracks_is_made_as_before() -> None:
    world = _world()
    made = _made_on_tracks(world, _clip())
    new = _add(world, made.clip_id, position=1)
    child = _brief_of(world, new).media
    assert child.references_version == 0 and child.clip_references == ()
    assert child.part is not None and child.part.references == ()


def test_make_new_on_the_tracks_keeps_the_parts_photo_and_origin_never_the_tracks() -> None:
    pinned = _ref("photo", 4.0, 9.0, "pin.png")
    world = _world()
    brief = _edit_on_tracks(pinned)
    brief = brief.model_copy(
        update={"media": brief.media.model_copy(update={"source_pins": (_pin(pinned.key),)})}
    )
    made = _create(world, brief)
    edit_part = made.part_ids[0]  # the «Igual al original» part, first on the timeline
    before = _brief_of(world, edit_part).media
    assert before.part is not None and before.part.mode == "edit"
    assert before.clip_image_keys == (pinned.key,)
    _fail(world, edit_part, reason="refused_face")
    _actions(world).make_part_new(
        tenant_id=TENANT_ID, user_id=USER_ID, clip_id=made.clip_id, part_id=edit_part
    )
    assert world.repo.drafts[edit_part].status == DRAFTING
    child = _brief_of(world, edit_part).media
    assert child.part is not None and child.part.mode == "reference"
    assert child.clip_references == () and child.references_version == 0
    assert child.clip_image_keys == (pinned.key,)
    assert child.part.references == (pinned,)
    assert [p.image_key for p in child.source_pins] == [pinned.key]
    # the reel window of «Igual al original» never becomes a guide of «Nueva»
    assert WINDOW not in child.clip_video_keys
