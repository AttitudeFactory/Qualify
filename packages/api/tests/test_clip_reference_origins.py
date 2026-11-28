"""m-25143472: where an item of the reference tracks («Mostrar a la IA») came from, and
the rule that a stock file or a Pin's image only guides the AI — it never goes into the
video (Deivid, 2026-11-14).

Offline and pure: the real effects library, no file, no database, no vendor, nothing
paid."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.scene_plan import unroled_image_role
from qualify_creative.schemas import (
    RECIPE_REFUSALS,
    REFERENCE_ORIGINS,
    ClipReference,
    ContentBrief,
    MediaInputs,
    SourcePinProvenance,
    SourceSegment,
    VideoPartPlan,
    ai_part_key,
    is_stock_reference_key,
)

from qualify_api.creative import clip_ai_parts as cap
from qualify_api.creative.video_pipeline import validate_brief_recipe
from qualify_api.creative.video_pipeline.ai_parts import (
    CLIP_AI_PARTS_SWITCH,
    not_for_video,
    reference_problems,
    reference_text,
    references_for_parts,
)
from qualify_api.creative.video_pipeline.recipe import RecipeRefused, refuse_unbuilt_recipe
from qualify_api.stock.keys import is_stock_key, stock_object_key

from .test_content_service import TENANT_ID, make_brief

OWN_VIDEO = f"uploads/{TENANT_ID}/mi-cocina.mp4"
STOCK_PHOTO = stock_object_key(TENANT_ID, "pixabay", "4021", "a" * 64, "jpg")
STOCK_VIDEO = stock_object_key(TENANT_ID, "pixabay", "9087", "b" * 64, "mp4")
PIN_PHOTO = f"uploads/{TENANT_ID}/pin-arepa.png"
PIN_ID = "812345"
NOT_FOR_VIDEO_TEXT = (
    "Esta imagen es solo para guiar a la IA y no puede ir dentro del video. "
    "Quítala del video o usa una foto o un video tuyo."
)


@pytest.fixture(autouse=True)
def _switch_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(CLIP_AI_PARTS_SWITCH, "on")


def _key(name: str) -> str:
    return f"uploads/{TENANT_ID}/{name}"


def _pin(key: str = PIN_PHOTO, pin: str = PIN_ID) -> SourcePinProvenance:
    return SourcePinProvenance(
        image_key=key, pin_id=pin, board_id="9", url=f"https://www.pinterest.com/pin/{pin}/"
    )


def _ref(kind: str, key: str, start: float = 4.0, end: float = 9.0, **extra: Any) -> ClipReference:
    return ClipReference(kind=kind, key=key, start_s=start, end_s=end, **extra)  # type: ignore[arg-type]


def _video(key: str = OWN_VIDEO, end: float = 4.0) -> SourceSegment:
    return SourceSegment(key=key, start_s=0.0, end_s=end)


def _photo(key: str, end: float = 3.0) -> SourceSegment:
    return SourceSegment(key=key, start_s=0.0, end_s=end, kind="photo")


def _ai(at: int, seconds: float = 5.0) -> SourceSegment:
    return SourceSegment(key=ai_part_key(at), start_s=0.0, end_s=seconds, kind="ai_part")


#: own video 0-4 s, «Nueva» 4-9 s.
SEGMENTS = (_video(), _ai(0))
AI_PARTS = (VideoPartPlan(mode="reference", seconds=5, description="Una arepa"),)


def _clip(
    refs: tuple[ClipReference, ...] = (),
    *,
    segments: tuple[SourceSegment, ...] = SEGMENTS,
    ai_parts: tuple[VideoPartPlan, ...] = AI_PARTS,
    version: int | None = None,
    **media: Any,
) -> ContentBrief:
    return make_brief(
        variants=1,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(
            duration_seconds=5,
            clip_reference_mode="local",
            segments=segments,
            ai_parts=ai_parts,
            clip_references=refs,
            references_version=(1 if refs else 0) if version is None else version,
            **media,
        ),
    )


def _codes(problems: tuple) -> list[tuple[str, str]]:
    return [(p.code, p.field) for p in problems]


# ---------------------------------------------------------------------------
# the shape: origin × kind × product_id / source_id


def test_the_origins_and_the_code_are_appended() -> None:
    assert REFERENCE_ORIGINS == ("owner", "product", "piece", "gallery", "stock", "pinterest")
    assert RECIPE_REFUSALS[-1] == "reference_not_for_video"
    assert reference_text("reference_not_for_video") == NOT_FOR_VIDEO_TEXT


def test_the_stock_test_is_the_stock_modules() -> None:
    for key in (STOCK_PHOTO, STOCK_VIDEO, OWN_VIDEO, "t/x/stock/a", "t/x/y/stock/a.jpg", "", None):
        assert is_stock_reference_key(key) == is_stock_key(key), key


PRODUCT = uuid4()
ALLOWED: list[tuple[str, str, dict[str, Any]]] = [
    ("photo", _key("a.png"), {}),
    ("video", _key("a.mp4"), {}),
    ("audio", _key("a.mp3"), {}),
    ("photo", _key("p.png"), {"origin": "product", "product_id": PRODUCT}),
    ("photo", _key("pieza.png"), {"origin": "piece", "source_id": str(uuid4())}),
    ("video", _key("pieza.mp4"), {"origin": "piece", "source_id": str(uuid4())}),
    ("photo", _key("g.png"), {"origin": "gallery"}),
    ("video", _key("g.mp4"), {"origin": "gallery", "source_id": str(uuid4())}),
    ("photo", STOCK_PHOTO, {"origin": "stock", "source_id": "pixabay:4021"}),
    ("video", STOCK_VIDEO, {"origin": "stock", "source_id": "9087"}),
    ("photo", PIN_PHOTO, {"origin": "pinterest", "source_id": PIN_ID}),
]
REFUSED: list[tuple[str, str, dict[str, Any]]] = [
    # owner: neither field
    ("photo", _key("a.png"), {"product_id": PRODUCT}),
    ("photo", _key("a.png"), {"source_id": "x"}),
    # product: a photo, with its product and no source
    ("video", _key("p.mp4"), {"origin": "product", "product_id": PRODUCT}),
    ("photo", _key("p.png"), {"origin": "product"}),
    ("photo", _key("p.png"), {"origin": "product", "product_id": PRODUCT, "source_id": "x"}),
    # the other four never name a product
    ("photo", _key("pieza.png"), {"origin": "piece", "source_id": "1", "product_id": PRODUCT}),
    ("photo", _key("g.png"), {"origin": "gallery", "product_id": PRODUCT}),
    ("photo", STOCK_PHOTO, {"origin": "stock", "source_id": "1", "product_id": PRODUCT}),
    ("photo", PIN_PHOTO, {"origin": "pinterest", "source_id": "1", "product_id": PRODUCT}),
    # source required for piece, stock and pinterest
    ("photo", _key("pieza.png"), {"origin": "piece"}),
    ("photo", STOCK_PHOTO, {"origin": "stock"}),
    ("photo", PIN_PHOTO, {"origin": "pinterest"}),
    ("photo", _key("pieza.png"), {"origin": "piece", "source_id": ""}),
    ("photo", _key("pieza.png"), {"origin": "piece", "source_id": "x" * 501}),
    # audio is only the owner's; a Pin is a photo
    ("audio", _key("a.mp3"), {"origin": "gallery"}),
    ("audio", _key("a.mp3"), {"origin": "piece", "source_id": "1"}),
    ("audio", STOCK_PHOTO.replace(".jpg", ".mp3"), {"origin": "stock", "source_id": "1"}),
    ("video", _key("pin.mp4"), {"origin": "pinterest", "source_id": "1"}),
    # a stock origin is a stock key, and a stock key is only a stock origin
    ("photo", _key("no-stock.png"), {"origin": "stock", "source_id": "1"}),
    ("photo", STOCK_PHOTO, {}),  # the owner-origin copy of a stock file
    ("photo", STOCK_PHOTO, {"origin": "gallery"}),
    ("photo", STOCK_PHOTO, {"origin": "piece", "source_id": "1"}),
    ("photo", STOCK_PHOTO, {"origin": "pinterest", "source_id": "1"}),
    ("photo", STOCK_PHOTO, {"origin": "product", "product_id": PRODUCT}),
]


@pytest.mark.parametrize(("kind", "key", "extra"), ALLOWED)
def test_an_origin_takes_what_it_names(kind: str, key: str, extra: dict[str, Any]) -> None:
    ref = _ref(kind, key, **extra)
    assert ClipReference.model_validate(ref.model_dump(mode="json")) == ref


@pytest.mark.parametrize(("kind", "key", "extra"), REFUSED)
def test_an_origin_refuses_what_it_does_not(kind: str, key: str, extra: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _ref(kind, key, **extra)


def test_a_reference_without_source_dumps_as_before_the_field() -> None:
    """A brief stored before m-25143472 reads and writes byte for byte the same."""
    stored = {
        "kind": "photo",
        "key": _key("arepa.png"),
        "start_s": 4.0,
        "end_s": 9.0,
        "row": 0,
        "origin": "owner",
        "product_id": None,
    }
    ref = ClipReference.model_validate(stored)
    assert ref.model_dump(mode="json") == stored
    assert json.dumps(ref.model_dump(mode="json")) == json.dumps(stored)
    with_source = _ref("photo", STOCK_PHOTO, origin="stock", source_id="4021")
    assert with_source.model_dump(mode="json")["source_id"] == "4021"


def test_an_old_saved_brief_still_loads_and_round_trips() -> None:
    old = _clip((_ref("photo", _key("arepa.png")), _ref("video", OWN_VIDEO, 5.0, 8.0)))
    stored = old.model_dump(mode="json")
    assert all("source_id" not in ref for ref in stored["media"]["clip_references"])
    again = ContentBrief.model_validate(stored)
    assert again == old and again.model_dump(mode="json") == stored
    assert validate_brief_recipe(again, tenant_id=TENANT_ID) == ()


def test_a_stored_brief_with_a_stock_block_still_loads() -> None:
    """The refusal is only at recipe time: a brief that already carries a stock block
    reads (it is refused only when it is created or made again)."""
    brief = _clip(segments=(_photo(STOCK_PHOTO), _video(), _ai(0)))
    assert ContentBrief.model_validate(brief.model_dump(mode="json")) == brief


def test_a_pinterest_reference_needs_its_pin() -> None:
    pinned = _ref("photo", PIN_PHOTO, origin="pinterest", source_id=PIN_ID)
    with pytest.raises(ValidationError, match="source_pins"):
        _clip((pinned,))
    with pytest.raises(ValidationError):  # a pin of another image names nothing selected
        _clip((pinned,), source_pins=(_pin(key=_key("otra.png")),))
    other_photo = _ref("photo", _key("otra.png"))
    with pytest.raises(ValidationError, match="source_pins"):  # the pin is another's
        _clip((pinned, other_photo), source_pins=(_pin(key=other_photo.key),))
    brief = _clip((pinned,), source_pins=(_pin(),))
    assert brief.media.source_pins[0].image_key == pinned.key
    assert validate_brief_recipe(brief, tenant_id=TENANT_ID) == ()


# ---------------------------------------------------------------------------
# roles and provenance: the four new origins guide the part like the owner's


def test_the_new_origins_take_the_unroled_role_and_keep_their_origin() -> None:
    refs = (
        _ref("photo", _key("pieza.png"), origin="piece", source_id="p-1"),
        _ref("photo", _key("g.png"), origin="gallery"),
        _ref("photo", STOCK_PHOTO, origin="stock", source_id="pixabay:4021"),
        _ref("photo", PIN_PHOTO, origin="pinterest", source_id=PIN_ID),
        _ref("video", STOCK_VIDEO, origin="stock", source_id="9087"),
    )
    brief = _clip(refs, source_pins=(_pin(),))
    assert validate_brief_recipe(brief, tenant_id=TENANT_ID) == ()
    (part,) = references_for_parts(brief)
    assert part.photos == refs[:4] and part.videos == refs[4:]
    assert [(r.origin, r.source_id) for r in part.photos] == [
        ("piece", "p-1"),
        ("gallery", None),
        ("stock", "pixabay:4021"),
        ("pinterest", PIN_ID),
    ]
    # roles unchanged: only a product's photo is the `product`, the rest the unroled role
    entry, taken = cap._entry_from_references(brief, AI_PARTS[0], part)
    assert taken == refs
    assert entry.clip_image_roles == (unroled_image_role(brief),) * 4
    product = _ref("photo", _key("p.png"), origin="product", product_id=PRODUCT)
    with_product = _clip((product, *refs[:1]))
    (of_product,) = references_for_parts(with_product)
    entry, _ = cap._entry_from_references(with_product, AI_PARTS[0], of_product)
    assert entry.clip_image_roles == ("product", unroled_image_role(with_product))


# ---------------------------------------------------------------------------
# reference_not_for_video: by the KEY, never by the origin alone


def test_a_stock_reference_also_in_the_video_is_refused() -> None:
    ref = _ref("video", STOCK_VIDEO, origin="stock", source_id="9087")
    brief = _clip((ref,), segments=(_video(STOCK_VIDEO), _ai(0)))
    assert _codes(validate_brief_recipe(brief, tenant_id=TENANT_ID)) == [
        ("reference_not_for_video", "clip_references[0].key"),
        ("reference_not_for_video", "segments[0].key"),
    ]
    with pytest.raises(RecipeRefused) as refused:
        refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)
    assert "reference_not_for_video" in {p.code for p in refused.value.problems}


def test_a_pinterest_reference_also_in_the_video_is_refused() -> None:
    ref = _ref("photo", PIN_PHOTO, origin="pinterest", source_id=PIN_ID)
    brief = _clip((ref,), segments=(_photo(PIN_PHOTO), _video(), _ai(0)), source_pins=(_pin(),))
    assert _codes(validate_brief_recipe(brief, tenant_id=TENANT_ID)) == [
        ("reference_not_for_video", "clip_references[0].key"),
        ("reference_not_for_video", "segments[0].key"),
    ]


def test_a_pinned_image_copied_as_the_owners_is_refused_by_its_pin() -> None:
    """The loophole: the screen sends the Pin's image with origin `owner`. The pin in
    `source_pins` still names it, so it cannot go into the video."""
    copy = _ref("photo", PIN_PHOTO)
    brief = _clip((copy,), segments=(_photo(PIN_PHOTO), _video(), _ai(0)), source_pins=(_pin(),))
    assert not_for_video(brief.media, PIN_PHOTO)
    assert ("reference_not_for_video", "clip_references[0].key") in _codes(
        reference_problems(brief.media, tenant_id=TENANT_ID)
    )
    with pytest.raises(RecipeRefused):
        refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)


def test_a_stock_key_directly_in_the_video_is_refused_at_recipe_time() -> None:
    """No track at all: a stock file as an own block is still refused — but only when
    the recipe is checked before it is created or made again."""
    brief = _clip(segments=(_photo(STOCK_PHOTO), _video(), _ai(0)))
    assert brief.media.clip_references == ()
    assert _codes(validate_brief_recipe(brief, tenant_id=TENANT_ID)) == [
        ("reference_not_for_video", "segments[0].key")
    ]
    with pytest.raises(RecipeRefused):
        refuse_unbuilt_recipe(brief, tenant_id=TENANT_ID)
    only_own = _clip(segments=(_video(), _ai(0)))
    assert validate_brief_recipe(only_own, tenant_id=TENANT_ID) == ()


def test_own_piece_and_gallery_files_may_go_into_the_video() -> None:
    piece = _ref("video", OWN_VIDEO, origin="piece", source_id="p-1")
    gallery = _ref("photo", _key("g.png"), origin="gallery", source_id="g-1")
    owner = _ref("photo", _key("mia.png"), 9.0, 12.0)
    brief = _clip(
        (piece, gallery, owner),
        segments=(_video(), _photo(_key("g.png")), _photo(_key("mia.png")), _ai(0)),
    )
    assert "reference_not_for_video" not in {
        p.code for p in validate_brief_recipe(brief, tenant_id=TENANT_ID)
    }
