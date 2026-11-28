"""m-25142725 (PR B, gaps the screen found): a Clip on the reference tracks end to end.

A Clip with `references_version` 1 carries no Clip-level `clip_image_keys` /
`clip_image_roles` / `clip_video_keys` / `clip_audio_keys` (refused there) — its own
photos and videos are `segments`. It must still be created, wait for its parts, be
assembled (`produce_local`) and have its parts changed, with nothing asking for those
keys. A Pinterest origin of a photo on the tracks goes with that photo to the part that
took it. «Igual al original» keeps its reel window in `clip_video_keys` on the tracks.

Offline only: the doubles of `test_clip_ai_parts` — no vendor, no database, nothing paid."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.schemas import (
    ClipReference,
    ContentBrief,
    MediaInputs,
    PartRef,
    SourcePinProvenance,
    VideoPartPlan,
)

from qualify_api.creative import clip_ai_part_actions as act
from qualify_api.creative import clip_ai_parts as cap
from qualify_api.creative.composition import SEEDANCE_REFERENCE_MODEL_ENV
from qualify_api.creative.fsm import FAILED, GENERATED
from qualify_api.creative.video_pipeline import validate_brief_recipe
from qualify_api.creative.video_pipeline.recipe import RecipeRefused

from .test_clip_ai_parts import (
    OTHER,
    World,
    _brief_of,
    _charged,
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
from .test_clip_avatar import OWN_VIDEO
from .test_content_service import TENANT_ID, USER_ID

__all__ = [  # fixtures used by name, or autouse
    "_switches",
    "assemble_at_the_sources_size",
    "assembly_files",
    "no_normalize_jobs",
    "queue_on",
]

WINDOW = f"uploads/{TENANT_ID}/ventana-del-reel.mp4"


@pytest.fixture(autouse=True)
def _default_model(monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: PT004
    monkeypatch.delenv(SEEDANCE_REFERENCE_MODEL_ENV, raising=False)


def _key(name: str) -> str:
    return f"uploads/{TENANT_ID}/{name}"


def _ref(kind: str, start: float, end: float, name: str, **extra: Any) -> ClipReference:
    return ClipReference(kind=kind, key=_key(name), start_s=start, end_s=end, **extra)  # type: ignore[arg-type]


def _pin(key: str, pin: str = "123") -> SourcePinProvenance:
    return SourcePinProvenance(
        image_key=key, pin_id=pin, board_id="9", url=f"https://www.pinterest.com/pin/{pin}/"
    )


def _on_tracks(brief: ContentBrief, *refs: ClipReference, **media: Any) -> ContentBrief:
    return brief.model_copy(
        update={
            "media": brief.media.model_copy(
                update={"references_version": 1, "clip_references": refs, **media}
            )
        }
    )


def _assembled(world: World, made: cap.ClipWithAiParts) -> ContentBrief:
    _made(world, made.part_ids[0], 5.0)
    _made(world, made.part_ids[1], 4.0)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == GENERATED
    return _brief_of(world, made.clip_id)


# ---------------------------------------------------------------------------
# (1) no Clip-level keys: created, waited for, assembled


def test_a_clip_on_the_tracks_without_clip_keys_is_made_end_to_end() -> None:
    """The screen sends `clip_image_keys`, `clip_image_roles` and `source_pins` empty:
    the photo role of a part still comes out (`unroled_image_role`), the parts are made,
    the Clip is assembled from its `segments`, and the assembled brief carries no tracks
    (they fed the parts; nothing after «Crear» reads them)."""
    photo = _ref("photo", 4.0, 9.0, "arepa.png")
    world = _world()
    brief = _on_tracks(_clip(), photo)
    assert brief.media.clip_image_keys == () and brief.media.clip_image_roles == ()
    made = _create(world, brief)
    first = _brief_of(world, made.part_ids[0])
    assert first.media.clip_image_keys == (photo.key,)
    assert len(first.media.clip_image_roles) == 1
    assembled = _assembled(world, made)
    assert [s.key for s in assembled.media.segments][::2] == [OWN_VIDEO, OTHER]
    assert assembled.media.clip_references == () and assembled.media.references_version == 0
    assert validate_brief_recipe(assembled, tenant_id=TENANT_ID) == ()
    # the brief the owner sent keeps his tracks, as the record of what he asked for
    asked = world.repo.briefs[assembled.media.derived_from_brief_id]  # type: ignore[index]
    assert asked.media.clip_references == (photo,)


def test_the_recipe_checked_after_create_never_reads_the_tracks() -> None:
    """«Quitar» a part shortens the Clip: a reference past the new end must not refuse
    the recipe the assembly will make (`virtual_brief` carries no tracks)."""
    late = _ref("photo", 12.0, 16.0, "final.png")
    brief = _on_tracks(_clip(), late)
    checked = cap.virtual_brief(brief, TENANT_ID)
    assert checked.media.clip_references == () and checked.media.references_version == 0


def test_a_pinterest_origin_goes_with_its_photo_to_the_part_that_took_it() -> None:
    pinned = _ref("photo", 4.0, 9.0, "pin.png")
    other = _ref("photo", 12.5, 15.0, "cocina.png")
    world = _world()
    made = _create(world, _on_tracks(_clip(), pinned, other, source_pins=(_pin(pinned.key),)))
    first, second = (_brief_of(world, part) for part in made.part_ids)
    assert [p.image_key for p in first.media.source_pins] == [pinned.key]
    assert second.media.source_pins == ()


def test_a_pinned_track_photo_is_assembled_without_its_origin() -> None:
    """Review of fa5caf93: the assembled Clip leaves the tracks AND the Pinterest origin
    of a photo only they held — before, it kept the pin and failed its own validation
    after its parts were made and charged."""
    pinned = _ref("photo", 4.0, 9.0, "pin.png")
    world = _world()
    made = _create(world, _on_tracks(_clip(), pinned, source_pins=(_pin(pinned.key),)))
    assembled = _assembled(world, made)
    assert assembled.media.source_pins == () and assembled.media.clip_references == ()
    # the part that took the photo keeps its origin
    assert [p.image_key for p in _brief_of(world, made.part_ids[0]).media.source_pins] == [
        pinned.key
    ]


def test_a_clip_whose_assembly_breaks_gives_every_parts_preview_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The money path: a Clip with AI parts that fails for a reason of ours (its
    assembly broke) gives back its own creations AND the vistas previas of its parts."""
    world = _world()
    made = _create(world, _on_tracks(_clip(), _ref("photo", 4.0, 9.0, "arepa.png")))
    _made(world, made.part_ids[0], 5.0)
    _made(world, made.part_ids[1], 4.0)

    def broken(*_: Any, **__: Any) -> Any:
        raise ValueError("assembly broke")

    monkeypatch.setattr(cap, "resolve", broken)
    world.content.run_generation(tenant_id=TENANT_ID, draft_id=made.clip_id)
    assert world.repo.drafts[made.clip_id].status == FAILED
    for draft in (made.clip_id, *made.part_ids):
        assert not _charged(world, draft)


def test_a_pinterest_origin_of_no_photo_is_still_refused() -> None:
    media = _clip().media.model_dump()
    with pytest.raises(ValidationError, match="Pinterest"):
        MediaInputs.model_validate(
            {**media, "references_version": 1, "source_pins": [_pin(_key("nada.png"))]}
        )


# ---------------------------------------------------------------------------
# (2) «Igual al original» keeps its reel window on the tracks


def _edit_on_tracks(*refs: ClipReference, mode: str = "edit") -> ContentBrief:
    entries = (
        _entry(4),
        _entry(
            5,
            mode=mode,
            clip_video_keys=(WINDOW,),
            analysis_id=uuid4(),
            shot_indexes=(1,),
            notices=("people_unclear",) if mode == "edit" else (),
        ),
    )
    return _on_tracks(_clip(entries=entries), *refs)


def test_an_edit_part_with_people_unclear_keeps_its_reel_window() -> None:
    """The window is the part's source, not a reference: accepted on the tracks only in
    «Igual al original», kept on the child, never counted among its references; a video
    of the tracks under it is ignored (only «Nueva» takes them)."""
    photo = _ref("photo", 4.0, 9.0, "arepa.png")
    video = _ref("video", 5.0, 8.0, "baile.mp4")
    brief = _edit_on_tracks(photo, video)
    assert not [p for p in validate_brief_recipe(brief, tenant_id=TENANT_ID)]
    world = _world()
    made = _create(world, brief)
    child = _brief_of(world, made.part_ids[0])
    assert child.media.part is not None and child.media.part.mode == "edit"
    assert child.media.clip_video_keys == (WINDOW,)
    assert child.media.part.clip_video_keys == (WINDOW,)
    assert child.media.clip_image_keys == (photo.key,)
    assert child.media.part.references == (photo,)


def test_a_reel_window_on_a_part_that_is_not_edit_is_still_refused() -> None:
    world = _world()
    with pytest.raises(RecipeRefused) as refused:
        _create(world, _edit_on_tracks(mode="reference"))
    assert ("references_and_old_fields", "ai_parts[1].clip_video_keys") in {
        (p.code, p.field) for p in refused.value.problems
    }


# ---------------------------------------------------------------------------
# a part of a Clip on the tracks made again in another mode


def test_another_mode_keeps_only_what_the_new_mode_uses() -> None:
    old = PartRef(
        index=1,
        mode="reference",
        seconds=5,
        description="Una arepa",
        clip_image_keys=(_key("arepa.png"),),
        clip_video_keys=(_key("baile.mp4"),),
        references=(
            _ref("photo", 4.0, 9.0, "arepa.png"),
            _ref("video", 5.0, 8.0, "baile.mp4"),
        ),
    )
    entry = VideoPartPlan.model_validate(
        {
            **old.model_dump(exclude={"index", "extend_own"}),
            "mode": "edit",
            "analysis_id": uuid4(),
            "shot_indexes": (1,),
        }
    )
    edited, taken = cap.entry_in_mode(old, entry)
    # a reference video never becomes the source «Igual al original» changes
    assert edited.clip_video_keys == () and edited.clip_audio_keys == ()
    assert [r.kind for r in taken] == ["photo"]
    back = VideoPartPlan.model_validate({**old.model_dump(exclude={"index", "extend_own"})})
    again, taken = cap.entry_in_mode(old, back)
    assert again.clip_video_keys == (_key("baile.mp4"),)
    assert [r.kind for r in taken] == ["photo", "video"]


def test_a_made_clip_on_the_tracks_changes_a_parts_mode() -> None:
    photo = _ref("photo", 4.0, 9.0, "arepa.png")
    analysis = uuid4()
    entries = (
        _entry(4),
        _entry(5, mode="edit", analysis_id=analysis, shot_indexes=(1,), original_mode="edit"),
    )
    world = _world()
    made = _create(world, _on_tracks(_clip(entries=entries), photo))
    _assembled(world, made)
    part_id = made.part_ids[0]
    act.ClipAiPartActions(
        world.content, parts_store=world.store, store=object(), env={}
    ).change_part_mode(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=made.clip_id,
        part_id=part_id,
        mode="reference",
    )
    child = _brief_of(world, part_id)
    assert child.media.part is not None and child.media.part.mode == "reference"
    assert child.media.clip_references == () and child.media.references_version == 0
    assert child.media.clip_image_keys == (photo.key,)
    assert child.media.part.references == (photo,)


def test_a_pinterest_reference_keeps_its_pin_when_its_part_changes_mode() -> None:
    """m-25143472: a Pin's image laid with origin `pinterest` keeps its origin, its
    `source_id` and its pin through a mode change (`entry_in_mode`)."""
    pinned = _ref("photo", 4.0, 9.0, "pin.png", origin="pinterest", source_id="123")
    entries = (
        _entry(4),
        _entry(5, mode="edit", analysis_id=uuid4(), shot_indexes=(1,), original_mode="edit"),
    )
    world = _world()
    made = _create(
        world, _on_tracks(_clip(entries=entries), pinned, source_pins=(_pin(pinned.key),))
    )
    _assembled(world, made)
    part_id = made.part_ids[0]
    act.ClipAiPartActions(
        world.content, parts_store=world.store, store=object(), env={}
    ).change_part_mode(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=made.clip_id,
        part_id=part_id,
        mode="reference",
    )
    child = _brief_of(world, part_id)
    assert child.media.part is not None and child.media.part.mode == "reference"
    assert child.media.part.references == (pinned,)
    assert child.media.part.references[0].source_id == "123"
    assert [p.image_key for p in child.media.source_pins] == [pinned.key]


def test_another_mode_never_takes_another_parts_pinned_photo() -> None:
    """Review of fa5caf93: a pin on a track photo the OTHER part took must not come with
    a mode change (it failed validation: a 500 with nothing charged); the part keeps
    its own photo's pin."""
    own = _ref("photo", 4.0, 9.0, "mia.png")
    others = _ref("photo", 12.5, 15.0, "ajena.png")
    entries = (
        _entry(4),
        _entry(5, mode="edit", analysis_id=uuid4(), shot_indexes=(1,), original_mode="edit"),
    )
    pins = (_pin(own.key, "1"), _pin(others.key, "2"))
    world = _world()
    made = _create(world, _on_tracks(_clip(entries=entries), own, others, source_pins=pins))
    _assembled(world, made)
    part_id = made.part_ids[0]
    act.ClipAiPartActions(
        world.content, parts_store=world.store, store=object(), env={}
    ).change_part_mode(
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        clip_id=made.clip_id,
        part_id=part_id,
        mode="reference",
    )
    child = _brief_of(world, part_id)
    assert child.media.part is not None and child.media.part.mode == "reference"
    assert [p.image_key for p in child.media.source_pins] == [own.key]
