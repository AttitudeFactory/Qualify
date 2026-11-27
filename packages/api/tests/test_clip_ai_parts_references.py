"""m-25142725 (PR B): «Crear» gives each AI part the items of the reference tracks under it.

On a Clip with `references_version` 1 each child's `clip_image_keys` / `clip_image_roles`
/ `clip_video_keys` / `clip_audio_keys` are derived from `references_for_parts` (a
product's photo is the `product`; any other photo `unroled_image_role`), the items it took
are kept on `PartRef.references`, and a part under no photo takes none — it no longer
inherits the Clip's. Every refusal of the tracks happens before anything is written or
paid. A brief with `references_version` 0 is made exactly as before.

Offline only: the doubles of `test_clip_ai_parts` — no vendor, no database, nothing paid."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.scene_plan import unroled_image_role
from qualify_creative.schemas import (
    ClipReference,
    ContentBrief,
    PartRef,
)

from qualify_api.creative import clip_ai_parts as cap
from qualify_api.creative.composition import SEEDANCE_REFERENCE_MODEL_ENV
from qualify_api.creative.media import _key_problems
from qualify_api.creative.part_extend import EXTEND_SWITCH
from qualify_api.creative.video_pipeline.ai_parts import (
    CLIP_AI_PARTS_SWITCH,
    CLIP_EXTEND_OWN_VIDEO_SWITCH,
)
from qualify_api.creative.video_pipeline.recipe import RecipeRefused

from . import test_clip_ai_parts as base
from .test_clip_ai_parts import (
    OWN_VIDEO,
    _block,
    _brief_of,
    _clip,
    _create,
    _entry,
    _nothing_written,
    _own,
    _world,
)
from .test_content_service import TENANT_ID, make_kit

queue_on = base.queue_on
__all__ = ["queue_on"]  # fixture used by name

PRODUCT = UUID("00000000-0000-4000-8000-00000000babe")


@pytest.fixture(autouse=True)
def _switches(queue_on: None, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: PT004
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "on")
    monkeypatch.delenv(CLIP_EXTEND_OWN_VIDEO_SWITCH, raising=False)
    monkeypatch.delenv(SEEDANCE_REFERENCE_MODEL_ENV, raising=False)


def _key(name: str) -> str:
    return f"uploads/{TENANT_ID}/{name}"


def _ref(kind: str, start: float, end: float, name: str, **extra: Any) -> ClipReference:
    return ClipReference(kind=kind, key=_key(name), start_s=start, end_s=end, **extra)  # type: ignore[arg-type]


def _tracks(*refs: ClipReference, **media: Any) -> ContentBrief:
    """The default Clip — own 0-4 s, AI part (entry 1, 5 s) 4-9 s, own 9-12 s, AI part
    (entry 0, 4 s) 12-16 s — on the tracks."""
    return _clip(references_version=1, clip_references=refs, **media)


def _children(world: base.World, made: cap.ClipWithAiParts) -> tuple[ContentBrief, ...]:
    return tuple(_brief_of(world, part_id) for part_id in made.part_ids)


# ---------------------------------------------------------------------------
# each part takes what lies under it


def test_each_part_takes_the_items_under_its_block() -> None:
    arepa = _ref("photo", 4.0, 9.0, "arepa.png", origin="product", product_id=PRODUCT)
    cocina = _ref("photo", 12.5, 15.0, "cocina.jpg")
    baile = _ref("video", 5.0, 8.0, "baile.mp4")
    musica = _ref("audio", 13.0, 16.0, "musica.mp3")
    world = _world()
    made = _create(world, _tracks(arepa, cocina, baile, musica))
    first, second = _children(world, made)  # slot 1 = entry 1 (4-9 s), slot 2 = entry 0
    unroled = unroled_image_role(_brief_of(world, made.clip_id))

    assert first.media.clip_image_keys == (arepa.key,)
    assert first.media.clip_image_roles == ("product",)
    assert first.media.clip_video_keys == (baile.key,)
    assert first.media.clip_audio_keys == ()
    assert first.media.part is not None and first.media.part.references == (arepa, baile)

    assert second.media.clip_image_keys == (cocina.key,)
    assert second.media.clip_image_roles == (unroled,)
    assert second.media.clip_video_keys == ()
    assert second.media.clip_audio_keys == (musica.key,)
    assert second.media.part is not None and second.media.part.references == (cocina, musica)

    for child in (first, second):
        # the child never carries the Clip's tracks; its own brief round-trips as stored
        assert child.media.clip_references == ()
        assert ContentBrief.model_validate_json(child.model_dump_json()) == child
    # the Clip keeps its tracks as the owner laid them
    assert _brief_of(world, made.clip_id).media.clip_references == (
        arepa,
        cocina,
        baile,
        musica,
    )


def test_a_part_under_no_photo_takes_none_and_no_longer_inherits_the_clips() -> None:
    """v0: an entry without photos takes the parent's (`parts.part_images`); v1: an
    explicit empty tuple, whatever the Clip carries."""
    photo = _key("arepa.jpg")
    old = _world()
    made_old = _create(old, _clip(product_keys=(photo,)))
    assert all(child.media.clip_image_keys == (photo,) for child in _children(old, made_old))

    world = _world()
    made = _create(world, _tracks(product_keys=(photo,)))
    for child in _children(world, made):
        assert child.media.clip_image_keys == () and child.media.clip_image_roles == ()
        assert child.media.part is not None and child.media.part.references == ()


def test_a_brief_before_the_tracks_is_made_exactly_as_before() -> None:
    photo = _key("arepa.jpg")
    world = _world()
    made = _create(world, _clip(clip_image_keys=(photo,), clip_image_roles=("product",)))
    for child in _children(world, made):
        assert child.media.clip_image_keys == (photo,)
        assert child.media.part is not None and child.media.part.references == ()
        assert child.media.references_version == 0


def test_videos_and_audios_under_a_part_that_is_not_new_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deivid: ignored with a notice, never a refusal; its photos still apply."""
    monkeypatch.setenv(EXTEND_SWITCH, "draft")
    monkeypatch.setenv(CLIP_EXTEND_OWN_VIDEO_SWITCH, "on")
    photo = _ref("photo", 5.0, 8.0, "arepa.png")
    video = _ref("video", 5.0, 8.0, "baile.mp4")
    audio = _ref("audio", 5.0, 8.0, "musica.mp3")
    world = _world()
    brief = _clip(
        (_own(4.0), _block(0)),
        (_entry(mode="extend"),),
        references_version=1,
        clip_references=(photo, video, audio),
    )
    made = _create(world, brief)
    (child,) = _children(world, made)
    assert child.media.clip_image_keys == (photo.key,)
    assert child.media.clip_video_keys == () and child.media.clip_audio_keys == ()
    assert child.media.part is not None and child.media.part.references == (photo,)
    # the owner's own video «Sigue a la anterior» continues is not one of the references
    assert child.media.part.extend_own is not None
    assert child.media.part.extend_own.key == OWN_VIDEO


def test_a_reference_under_no_ai_part_is_allowed() -> None:
    world = _world()
    made = _create(world, _tracks(_ref("photo", 0.0, 3.0, "fachada.png")))
    for child in _children(world, made):
        assert child.media.clip_image_keys == ()


def test_the_same_file_may_be_a_block_and_a_reference() -> None:
    """Deivid: the same key in `segments` and in `clip_references` — no duplicate rule."""
    world = _world()
    own = ClipReference(kind="video", key=OWN_VIDEO, start_s=4.5, end_s=8.0)
    made = _create(world, _tracks(own))
    first, _ = _children(world, made)
    assert first.media.clip_video_keys == (OWN_VIDEO,)


# ---------------------------------------------------------------------------
# refused before anything is written or paid


def test_over_the_models_cap_is_refused_never_cut() -> None:
    world = _world()
    photos = tuple(_ref("photo", 4.0, 9.0, f"foto-{n}.png") for n in range(10))
    with pytest.raises(RecipeRefused) as refused:
        _create(world, _tracks(*photos))
    assert {(p.code, p.field) for p in refused.value.problems} >= {
        ("too_many_references", "ai_parts[1].references.photo")
    }
    _nothing_written(world)


@pytest.mark.parametrize(
    ("media", "field"),
    [
        ({"clip_image_keys": (_key("vieja.jpg"),)}, "clip_image_keys"),
        ({"clip_audio_keys": (_key("vieja.mp3"),)}, "clip_audio_keys"),
    ],
)
def test_the_tracks_with_the_clips_old_fields_are_refused(
    media: dict[str, Any], field: str
) -> None:
    world = _world()
    with pytest.raises(RecipeRefused) as refused:
        _create(world, _tracks(_ref("photo", 4.0, 9.0, "arepa.png"), **media))
    assert ("references_and_old_fields", field) in {
        (p.code, p.field) for p in refused.value.problems
    }
    _nothing_written(world)


def test_the_tracks_with_a_parts_old_fields_are_refused() -> None:
    world = _world()
    entries = (_entry(4), _entry(5, clip_video_keys=(_key("guia.mp4"),)))
    brief = _clip(entries=entries, references_version=1)
    with pytest.raises(RecipeRefused) as refused:
        _create(world, brief)
    assert ("references_and_old_fields", "ai_parts[1].clip_video_keys") in {
        (p.code, p.field) for p in refused.value.problems
    }
    _nothing_written(world)


def test_tracks_without_their_version_are_refused() -> None:
    world = _world()
    with pytest.raises(RecipeRefused) as refused:
        _create(world, _clip(clip_references=(_ref("photo", 4.0, 9.0, "arepa.png"),)))
    assert ("references_and_old_fields", "references_version") in {
        (p.code, p.field) for p in refused.value.problems
    }
    _nothing_written(world)


@pytest.mark.parametrize(
    ("ref", "code"),
    [
        (
            ClipReference(kind="photo", key=f"uploads/{uuid4()}/ajena.png", start_s=4, end_s=9),
            "foreign_key",
        ),
        (
            ClipReference(kind="photo", key="fotos/sin-negocio.png", start_s=4, end_s=9),
            "malformed_key",
        ),
        (ClipReference(kind="photo", key=_key("arepa.gif"), start_s=4, end_s=9), "reference_type"),
        (
            ClipReference(kind="photo", key=_key("arepa.png"), start_s=10, end_s=30),
            "reference_out_of_clip",
        ),
    ],
)
def test_every_rule_of_the_tracks_refuses_before_anything(ref: ClipReference, code: str) -> None:
    world = _world()
    with pytest.raises(RecipeRefused) as refused:
        _create(world, _tracks(ref))
    assert code in {p.code for p in refused.value.problems}
    _nothing_written(world)


def test_with_the_switch_off_the_tracks_are_refused_before_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "off")
    world = _world()
    with pytest.raises(RecipeRefused) as refused:
        _create(world, _tracks(_ref("photo", 4.0, 9.0, "arepa.png")))
    assert "switched_off" in {p.code for p in refused.value.problems}
    _nothing_written(world)


def test_child_brief_refuses_a_part_over_its_cap_on_its_own() -> None:
    """The retry path may call `child_brief` without the create-time check: over a cap it
    is still refused, never cut."""
    photos = tuple(_ref("photo", 4.0, 9.0, f"foto-{n}.png") for n in range(10))
    clip = _tracks(*photos)
    planned = cap.planned_parts(clip)[0]
    with pytest.raises(RecipeRefused):
        cap.child_brief(clip, planned)


def test_child_brief_derives_the_references_by_itself() -> None:
    """Without `references` given, `child_brief` reads them off the Clip (the same as at
    «Crear»)."""
    arepa = _ref("photo", 4.0, 9.0, "arepa.png")
    clip = _tracks(arepa)
    planned = cap.planned_parts(clip)[0]
    child = cap.child_brief(clip, planned)
    assert child.media.clip_image_keys == (arepa.key,)
    assert child.media.part is not None and child.media.part.references == (arepa,)


# ---------------------------------------------------------------------------
# every file a part took is checked to be the business's before any read


def test_key_problems_check_the_references_a_part_took() -> None:
    foreign = f"uploads/{uuid4()}/ajena.png"
    part = PartRef(
        index=1,
        mode="reference",
        seconds=5,
        description="Una arepa",
        references=(ClipReference(kind="photo", key=foreign, start_s=0, end_s=5),),
    )
    brief = _clip((_own(4.0),), ()).model_copy(
        update={"media": _clip((_own(4.0),), ()).media.model_copy(update={"part": part})}
    )
    malformed, refused = _key_problems(TENANT_ID, brief, make_kit())
    assert malformed == [] and refused == [foreign]
