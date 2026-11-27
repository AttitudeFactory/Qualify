"""m-25142725 (PR A): the reference tracks of the single editor — the contract.

`MediaInputs.clip_references` are photos, videos and audios laid on tracks under a
normal `local` Clip, in seconds of the final video; each AI part takes the ones under it
(`references_for_parts`). Offline and pure: the real effects library, no file, no
database, no vendor, nothing paid."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.reference_caps import (
    REFERENCE_CAPS_BY_MODEL,
    SEEDANCE_REFERENCE_CAPS,
    reference_caps_for,
)
from qualify_creative.schemas import (
    CLIP_REFERENCES_MAX,
    RECIPE_REFUSALS,
    CharacterSceneBackground,
    CharacterSceneItem,
    CharacterSceneProduct,
    ClipReference,
    ContentBrief,
    MediaInputs,
    SourceSegment,
    VideoPartPlan,
    ai_part_key,
)

from qualify_api.creative import media as media_module
from qualify_api.creative.composition import SEEDANCE_REFERENCE_MODEL_ENV
from qualify_api.creative.video_pipeline import validate_brief_recipe
from qualify_api.creative.video_pipeline.ai_parts import (
    CLIP_AI_PARTS_SWITCH,
    REFERENCE_NOTICE_TEXTS,
    REFERENCE_NOTICES_THAT_BLOCK,
    REFERENCE_TEXTS,
    plan_references,
    reference_caps,
    reference_notices,
    reference_problems,
    reference_text,
    references_for_parts,
)
from qualify_api.creative.video_pipeline.recipe import RecipeRefused, refuse_unbuilt_recipe

from .test_content_service import TENANT_ID, make_brief

VIDEO = f"uploads/{TENANT_ID}/mi-cocina.mp4"
ANALYSIS = UUID("00000000-0000-4000-8000-0000000000aa")
CODES = (
    "too_many_references",
    "reference_type",
    "reference_out_of_clip",
    "references_and_old_fields",
)


@pytest.fixture(autouse=True)
def _switch_on_and_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "on")
    monkeypatch.delenv(SEEDANCE_REFERENCE_MODEL_ENV, raising=False)


def _key(name: str) -> str:
    return f"uploads/{TENANT_ID}/{name}"


def _ref(
    kind: str, start: float, end: float, name: str | None = None, **extra: Any
) -> ClipReference:
    suffix = {"photo": "png", "video": "mp4", "audio": "mp3"}[kind]
    return ClipReference(
        kind=kind,  # type: ignore[arg-type]
        key=_key(name or f"{kind}-{start}-{end}.{suffix}"),
        start_s=start,
        end_s=end,
        **extra,
    )


def _video(start: float = 0.0, end: float = 4.0) -> SourceSegment:
    return SourceSegment(key=VIDEO, start_s=start, end_s=end)


def _ai(at: int, seconds: float = 5.0) -> SourceSegment:
    return SourceSegment(key=ai_part_key(at), start_s=0.0, end_s=seconds, kind="ai_part")


def _new(**extra: Any) -> VideoPartPlan:
    return VideoPartPlan(mode="reference", seconds=5, description="Una arepa", **extra)


def _same_as_reel() -> VideoPartPlan:
    return VideoPartPlan(
        mode="edit", seconds=5, description="Igual", analysis_id=ANALYSIS, shot_indexes=(0,)
    )


#: own video 0-4 s, «Nueva» 4-9 s, «Igual al original» 9-14 s.
SEGMENTS = (_video(), _ai(0), _ai(1))
AI_PARTS = (_new(), _same_as_reel())


def _media(refs: tuple[ClipReference, ...], version: int = 1, **extra: Any) -> MediaInputs:
    return MediaInputs(
        duration_seconds=5,
        clip_reference_mode=extra.pop("mode", "local"),
        segments=extra.pop("segments", SEGMENTS),
        ai_parts=extra.pop("ai_parts", AI_PARTS),
        clip_references=refs,
        references_version=version,
        **extra,
    )


def _clip(refs: tuple[ClipReference, ...], version: int = 1, **extra: Any) -> ContentBrief:
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=_media(refs, version, **extra),
    )


def _producer_key_problems(brief: ContentBrief) -> tuple[list[str], list[str]]:
    """`media._key_problems` without the AI blocks' `ai_part:<n>` (never a file; PR 2,
    m-25129406, takes them out of that list)."""
    malformed, foreign = media_module._key_problems(
        TENANT_ID, brief, SimpleNamespace(logo_asset_key=None)
    )
    return [k for k in malformed if not k.startswith("ai_part:")], foreign


def _codes(problems: tuple) -> list[tuple[str, str]]:
    return [(p.code, p.field) for p in problems]


# ---------------------------------------------------------------------------
# the shape


def test_a_reference_is_a_free_standing_item_with_its_own_seconds() -> None:
    ref = _ref("photo", 1.0, 3.5, row=2)
    assert ref.origin == "owner" and ref.product_id is None
    again = ClipReference.model_validate(ref.model_dump(mode="json"))
    assert again == ref
    product = uuid4()
    of_product = _ref("photo", 0, 14, origin="product", product_id=product)
    assert of_product.product_id == product
    with pytest.raises(ValidationError):
        _ref("photo", 3.0, 3.0)  # ends after it starts
    with pytest.raises(ValidationError):
        _ref("photo", -1.0, 3.0)
    with pytest.raises(ValidationError):
        _ref("video", 0, 2, origin="product", product_id=product)  # a product's is a photo
    with pytest.raises(ValidationError):
        _ref("photo", 0, 2, origin="product")  # names its product
    with pytest.raises(ValidationError):
        _ref("photo", 0, 2, product_id=product)  # only a product's names one
    with pytest.raises(ValidationError):
        ClipReference(kind="sticker", key=_key("a.png"), start_s=0, end_s=1)  # type: ignore[arg-type]


def test_the_tracks_hold_at_most_40_and_say_their_version() -> None:
    refs = tuple(_ref("photo", 0, 1, f"f{i}.png") for i in range(CLIP_REFERENCES_MAX))
    assert len(_media(refs).clip_references) == 40
    with pytest.raises(ValidationError):
        _media((*refs, _ref("photo", 0, 1, "one-more.png")))
    with pytest.raises(ValidationError):
        _media((), version=2)
    stored = MediaInputs()
    assert stored.clip_references == () and stored.references_version == 0


def test_the_codes_are_appended_in_order() -> None:
    at = RECIPE_REFUSALS.index(CODES[0])
    assert RECIPE_REFUSALS[at : at + len(CODES)] == CODES
    # the notices are never refusals (`REFERENCE_NOTICES_THAT_BLOCK` is empty)
    for notice in ("reference_mode_ignored", "reference_unused", "reference_over_scene"):
        assert notice not in RECIPE_REFUSALS
    assert REFERENCE_NOTICES_THAT_BLOCK == frozenset()


# ---------------------------------------------------------------------------
# caps per model


def test_caps_are_per_model_and_default_to_the_active_video_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert dict(reference_caps()) == {"photo": 9, "video": 3, "audio": 3}
    assert dict(reference_caps("dreamina-seedance-2-5-260128")) == {
        "photo": 9,
        "video": 3,
        "audio": 3,
    }
    monkeypatch.setenv(SEEDANCE_REFERENCE_MODEL_ENV, "dreamina-seedance-2-0-260128")
    assert reference_caps()["photo"] == 9
    assert reference_caps_for("dreamina-seedance-2-0-fast") is SEEDANCE_REFERENCE_CAPS
    assert set(REFERENCE_CAPS_BY_MODEL) == {
        "dreamina-seedance-2-0",
        "dreamina-seedance-2-0-fast",
        "dreamina-seedance-2-0-mini",
        "dreamina-seedance-2-5",
    }
    with pytest.raises(ValueError, match="no reference caps"):
        reference_caps("seedance-1-0-pro-250528")  # takes no references: never guessed
    with pytest.raises(TypeError):
        reference_caps()["photo"] = 30  # type: ignore[index]


def test_the_cap_comes_from_the_model_the_part_uses(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_creative import reference_caps as caps_module

    bigger = caps_module.ReferenceCaps(photo=10, video=5, audio=5)
    monkeypatch.setattr(
        caps_module,
        "REFERENCE_CAPS_BY_MODEL",
        {**caps_module.REFERENCE_CAPS_BY_MODEL, "magi-2": bigger},
    )
    refs = tuple(_ref("photo", 4, 9, f"f{i}.png") for i in range(10))
    media = _media(refs)
    assert _codes(plan_references(media).problems) == [
        ("too_many_references", "ai_parts[0].references.photo")
    ]
    assert plan_references(media, model="magi-2").problems == ()
    assert reference_text("too_many_references", kind="photo", model="magi-2") == (
        "Esta parte con IA tiene más de 10 fotos de referencia. Quita o acorta alguna para seguir."
    )


# ---------------------------------------------------------------------------
# which part takes what


def test_photos_apply_in_every_mode_video_and_audio_only_to_new() -> None:
    photo = _ref("photo", 0, 14)
    video = _ref("video", 0, 14)
    audio = _ref("audio", 0, 14)
    brief = _clip((photo, video, audio))
    new, same = references_for_parts(brief)
    assert (new.entry_at, new.block_at, new.mode) == (0, 1, "reference")
    assert (new.start_s, new.end_s) == (4.0, 9.0)
    assert (new.photos, new.videos, new.audios) == ((photo,), (video,), (audio,))
    assert (same.entry_at, same.block_at, same.start_s, same.end_s) == (1, 2, 9.0, 14.0)
    assert (same.photos, same.videos, same.audios) == ((photo,), (), ())
    assert new.problems == same.problems == ()
    notes = reference_notices(brief)
    assert [(n.code, n.field, n.entry_at) for n in notes] == [
        ("reference_mode_ignored", "clip_references[1]", 1),
        ("reference_mode_ignored", "clip_references[2]", 1),
    ]
    # the notices never block
    assert validate_brief_recipe(brief, tenant_id=TENANT_ID) == ()


def test_a_reference_applies_when_it_overlaps_by_more_than_005_s() -> None:
    edge = _ref("photo", 0.0, 4.05, "edge.png")  # 0.05 s into «Nueva»: not enough
    inside = _ref("photo", 0.0, 4.06, "inside.png")
    touching = _ref("photo", 9.0, 9.5, "after.png")  # only the next part
    new, same = references_for_parts(_clip((edge, inside, touching)))
    assert new.photos == (inside,)
    assert same.photos == (touching,)
    notes = reference_notices(_clip((edge, inside, touching)))
    assert [(n.code, n.field) for n in notes] == [("reference_unused", "clip_references[0]")]


def test_order_is_start_row_position_and_a_repeated_key_counts_once() -> None:
    late = _ref("photo", 6, 9, "late.png")
    row1 = _ref("photo", 5, 9, "row1.png", row=1)
    row0 = _ref("photo", 5, 9, "row0.png", row=0)
    twin_a = _ref("photo", 4, 9, "twin.png", row=3)
    twin_b = _ref("photo", 4, 9, "twin.png", row=4)
    (new, _same) = references_for_parts(_clip((late, row1, row0, twin_b, twin_a)))
    assert new.photos == (twin_a, row0, row1, late)


def test_over_the_cap_the_part_is_refused_never_cut() -> None:
    photos = tuple(_ref("photo", 4, 9, f"f{i}.png") for i in range(10))
    videos = tuple(_ref("video", 4, 9, f"v{i}.mp4") for i in range(4))
    audios = tuple(_ref("audio", 4, 9, f"a{i}.mp3") for i in range(4))
    brief = _clip((*photos, *videos, *audios))
    new, same = references_for_parts(brief)
    assert len(new.photos) == 10 and len(new.videos) == 4 and len(new.audios) == 4
    assert _codes(new.problems) == [
        ("too_many_references", "ai_parts[0].references.photo"),
        ("too_many_references", "ai_parts[0].references.video"),
        ("too_many_references", "ai_parts[0].references.audio"),
    ]
    assert same.problems == ()
    found = validate_brief_recipe(brief, tenant_id=TENANT_ID)
    assert _codes(found) == _codes(new.problems)  # blocking: «Crear» stays off
    with pytest.raises(RecipeRefused):
        refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)


def test_nine_photos_and_three_of_each_fit() -> None:
    refs = (
        *(_ref("photo", 4, 9, f"f{i}.png") for i in range(9)),
        *(_ref("video", 4, 9, f"v{i}.mp4") for i in range(3)),
        *(_ref("audio", 4, 9, f"a{i}.mp3") for i in range(3)),
        _ref("photo", 4, 9, "f0.png"),  # the same file again counts once
    )
    assert validate_brief_recipe(_clip(refs), tenant_id=TENANT_ID) == ()


def test_unused_and_over_scene_are_notices() -> None:
    own = _ref("photo", 0.5, 3.5, "own.png")  # under the owner's video only
    scene = CharacterSceneItem(
        character_id=uuid4(),
        product=CharacterSceneProduct(product_id=uuid4(), photo_key=_key("p.png")),
        background=CharacterSceneBackground(key=_key("lugar.png")),
        line="Prueba la arepa",
        start=0.0,
        duration=5,
    )
    media = _media((own,), character_scenes=(scene,))
    notes = plan_references(media).notices
    assert [(n.code, n.field, n.scene_at) for n in notes] == [
        ("reference_unused", "clip_references[0]", None),
        ("reference_over_scene", "clip_references[0]", 0),
    ]
    assert plan_references(media).problems == ()


# ---------------------------------------------------------------------------
# the refusals


def test_a_reference_of_another_type_is_refused() -> None:
    refs = (
        ClipReference(kind="photo", key=_key("foto.gif"), start_s=4, end_s=9),
        ClipReference(kind="video", key=_key("baile.mp3"), start_s=4, end_s=9),
        ClipReference(kind="audio", key=_key("cancion.wav"), start_s=4, end_s=9),
        ClipReference(kind="photo", key=_key("FOTO.JPEG"), start_s=4, end_s=9),
    )
    assert _codes(validate_brief_recipe(_clip(refs), tenant_id=TENANT_ID)) == [
        ("reference_type", "clip_references[0].key"),
        ("reference_type", "clip_references[1].key"),
    ]


def test_a_reference_past_the_end_of_the_clip_is_refused() -> None:
    fits = _ref("photo", 10, 14.04, "fits.png")
    past = _ref("photo", 10, 14.2, "past.png")
    assert _codes(validate_brief_recipe(_clip((fits, past)), tenant_id=TENANT_ID)) == [
        ("reference_out_of_clip", "clip_references[1]")
    ]


def test_tracks_and_old_fields_together_are_refused() -> None:
    ref = _ref("photo", 4, 9)
    assert _codes(validate_brief_recipe(_clip((ref,), version=0), tenant_id=TENANT_ID)) == [
        ("references_and_old_fields", "references_version")
    ]
    old = _clip(
        (ref,),
        clip_image_keys=(_key("vieja.png"),),
        ai_parts=(_new(clip_video_keys=(_key("guia.mp4"),)), _same_as_reel()),
    )
    assert _codes(validate_brief_recipe(old, tenant_id=TENANT_ID)) == [
        ("references_and_old_fields", "clip_image_keys"),
        ("references_and_old_fields", "ai_parts[0].clip_video_keys"),
    ]
    # a brief before the tracks (version 0, none) reads as today
    before = _clip(
        (), version=0, ai_parts=(_new(clip_video_keys=(_key("guia.mp4"),)), _same_as_reel())
    )
    assert validate_brief_recipe(before, tenant_id=TENANT_ID) == ()


def test_every_reference_key_is_the_business_s() -> None:
    other = uuid4()
    refs = (
        ClipReference(kind="photo", key="no-es-ruta.png", start_s=4, end_s=9),
        ClipReference(kind="photo", key=f"uploads/{other}/ajena.png", start_s=4, end_s=9),
    )
    assert _codes(validate_brief_recipe(_clip(refs), tenant_id=TENANT_ID)) == [
        ("malformed_key", "clip_references[0].key"),
        ("foreign_key", "clip_references[1].key"),
    ]
    # without a business the keys are not checked (the screen before it knows it)
    assert validate_brief_recipe(_clip(refs)) == ()
    # and the producer's own gate reads them too
    malformed, foreign = _producer_key_problems(_clip(refs))
    assert malformed == ["no-es-ruta.png"] and foreign == [f"uploads/{other}/ajena.png"]


def test_the_same_file_may_be_a_block_and_a_reference() -> None:
    """Plan §5: copying a file from a block to a track copies the string, never the
    object, and no rule refuses the same key in both."""
    same = ClipReference(kind="video", key=VIDEO, start_s=4, end_s=9)
    brief = _clip((same,))
    assert validate_brief_recipe(brief, tenant_id=TENANT_ID) == ()
    (new, _same) = references_for_parts(brief)
    assert new.videos == (same,)
    assert _producer_key_problems(brief) == ([], [])


def test_the_tracks_go_only_on_a_normal_local_clip() -> None:
    seedance_clip = _clip((_ref("photo", 0, 4),), mode="motion", segments=(), ai_parts=())
    assert _codes(validate_brief_recipe(seedance_clip, tenant_id=TENANT_ID)) == [
        ("ai_part_outside_clip", "clip_references")
    ]


def test_with_the_switch_off_the_tracks_are_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "off")
    only_tracks = _clip((_ref("photo", 0, 4),), segments=(_video(),), ai_parts=())
    assert _codes(validate_brief_recipe(only_tracks)) == [("switched_off", "clip_references")]
    with pytest.raises(RecipeRefused):
        refuse_unbuilt_recipe(only_tracks, tenant_id=TENANT_ID)


def test_reference_problems_is_empty_without_tracks() -> None:
    assert reference_problems(MediaInputs()) == ()


# ---------------------------------------------------------------------------
# the words


def test_every_code_has_its_spanish_words() -> None:
    assert reference_text("too_many_references", kind="photo") == (
        "Esta parte con IA tiene más de 9 fotos de referencia. Quita o acorta alguna para seguir."
    )
    assert reference_text("too_many_references", kind="video") == (
        "Esta parte con IA tiene más de 3 videos de referencia. Quita o acorta alguno para seguir."
    )
    assert reference_text("too_many_references", kind="audio") == (
        "Esta parte con IA tiene más de 3 audios de referencia. Quita o acorta alguno para seguir."
    )
    assert reference_text("too_many_references") is None  # names its kind
    assert REFERENCE_TEXTS == {
        "reference_type": (
            "No podemos usar ese archivo como referencia. Usa una foto JPG o PNG, un video MP4 "
            "o MOV, o un audio MP3 o WAV."
        ),
        "reference_out_of_clip": (
            "Esta referencia queda fuera del video. Muévela o acórtala para seguir."
        ),
        "references_and_old_fields": "Vuelve a abrir el editor para seguir.",
    }
    assert REFERENCE_NOTICE_TEXTS == {
        "reference_mode_ignored": "Esta parte no usa videos ni audios de referencia.",
        "reference_unused": "Esta referencia no está debajo de ninguna parte con IA.",
    }
    assert reference_text("reference_over_scene") is None  # decided with PR 4
    assert reference_text("foreign_key") is None
    texts = [
        *REFERENCE_TEXTS.values(),
        *REFERENCE_NOTICE_TEXTS.values(),
        *(reference_text("too_many_references", kind=k) or "" for k in ("photo", "video", "audio")),
    ]
    for text in texts:
        assert text[0].isupper() and text.endswith("."), text
        for word in ("clip", "post", "track", "AI ", "timeline", "línea de tiempo"):
            assert word not in text, (text, word)
