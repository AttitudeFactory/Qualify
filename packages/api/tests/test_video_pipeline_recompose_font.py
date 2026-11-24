"""ED-13 (m-25029108): a Clip made by Seedance draws its texts in the Brand Kit's own font
file exactly as a local Clip does — the producer's `_video_text_brand` (only a file
FreeType draws; anything else leaves the family, recorded as `font_file_rejected`, never a
failed piece) — and its 1080p final, composed again by EF-14 from the frozen recipe, uses
the same file. A recipe frozen before this change keeps its digest.

Offline: an in-memory store, `recompose`'s FakeComposer double for the producer, and the
real `ClipComposer` over a fake render service (with PyAV on a tiny 9:16 video)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.render.video_text import BrandText, TextFont
from qualify_creative.schemas import VideoTextLayer

from qualify_api.creative.video_pipeline import recompose
from qualify_api.creative.video_pipeline.recompose import (
    ClipComposer,
    ComposeRecipe,
    font_params,
    stored_font,
    stored_recipe,
)

from .test_creative_media_byteplus import BUDGET, COPY, _kit
from .test_creative_media_byteplus import TENANT_ID as MEDIA_TENANT
from .test_video_pipeline_compose_motions import FakeService
from .test_video_pipeline_compose_motions import _kit as _kit_with_family
from .test_video_pipeline_compose_motions import _video as _tiny_video
from .test_video_pipeline_recompose import (
    WORDS,
    FakeComposer,
    _brief_with,
    _composing_producer,
    _final,
    _with_attempt,
)

FONT_BYTES = (
    Path(__file__).resolve().parents[2] / "creative" / "tests" / "fixtures" / "DejaVuSans.ttf"
).read_bytes()
KEY = f"t/{MEDIA_TENANT}/brand/b/font/heading/marca.ttf"
FONT = TextFont.of(FONT_BYTES, key=KEY)
NOT_A_FONT = b"wOF2" + b"\x00" * 60


@pytest.fixture(autouse=True)
def in_the_worker() -> Iterator[None]:
    """The compose decodes video: only inside the creative worker (`is_worker_process`)."""
    from qualify_api.creative.process import mark_worker_process, unmark_worker_process

    mark_worker_process()
    yield
    unmark_worker_process()


def _producer_with_font(composer: FakeComposer, data: bytes | None) -> tuple[Any, Any]:
    producer, store, _ = _composing_producer(composer)
    producer._brand_fonts = lambda **_: KEY
    if data is not None:
        store.files[KEY] = data
    return producer, store


def _preview(producer: Any, brief: Any) -> Any:
    outcome = producer.produce(
        tenant_id=MEDIA_TENANT,
        draft_id=uuid4(),
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    assert outcome.failure is None
    (video,) = outcome.media
    return video


# ---------------------------------------------------------------------------
# the producer: the same rules as a local Clip


def test_a_seedance_clip_draws_its_texts_in_the_brand_font_file() -> None:
    composer = FakeComposer()
    producer, _ = _producer_with_font(composer, FONT_BYTES)
    video = _preview(producer, _brief_with(text_layers=(WORDS,)))

    (drawn_with,) = composer.draws
    assert drawn_with.font is not None and drawn_with.font.sha256 == FONT.sha256
    assert drawn_with.font_ref == f"asset://{FONT.sha256}" and not drawn_with.font_rejected
    brand = drawn_with.text_brand()
    assert isinstance(brand, BrandText) and brand.font == drawn_with.font
    block = video.params["compose"]
    # the file is named in the frozen brand (its sha256 is in the digest) and kept beside it
    assert block["recipe"]["brand"]["fontFiles"] == {"heading": f"asset://{FONT.sha256}"}
    assert block["font"] == {"key": KEY, "sha256": FONT.sha256}
    assert block["preview"]["recipe_sha256"] == drawn_with.digest()


@pytest.mark.parametrize("data", [NOT_A_FONT, None], ids=["not_a_font", "unreadable"])
def test_an_unusable_font_file_falls_back_to_the_family(data: bytes | None) -> None:
    composer = FakeComposer()
    producer, _ = _producer_with_font(composer, data)
    video = _preview(producer, _brief_with(text_layers=(WORDS,)))

    (drawn_with,) = composer.draws
    assert drawn_with.font is None and drawn_with.font_rejected is True
    assert drawn_with.font_ref is None
    brand = drawn_with.text_brand()
    assert isinstance(brand, BrandText) and brand.font is None and brand.font_rejected
    block = video.params["compose"]
    assert "fontFiles" not in block["recipe"]["brand"] and "font" not in block


def test_a_kit_without_a_font_file_freezes_exactly_as_before() -> None:
    composer = FakeComposer()
    producer, _, _ = _composing_producer(composer)  # no brand fonts wired
    video = _preview(producer, _brief_with(text_layers=(WORDS,)))
    (drawn_with,) = composer.draws
    assert drawn_with.font is None and not drawn_with.font_rejected
    assert drawn_with.text_brand() == dict(drawn_with.brand)
    assert set(video.params["compose"]["recipe"]["brand"]) == {"name", "palette", "fonts", "logo"}
    assert "font" not in video.params["compose"]


# ---------------------------------------------------------------------------
# the final: the same frozen recipe, the same file


def test_the_final_reads_back_the_previews_font_file() -> None:
    composer = FakeComposer()
    producer, store = _producer_with_font(composer, FONT_BYTES)
    brief = _brief_with(text_layers=(WORDS,))
    draft_id = uuid4()
    outcome = producer.produce(
        tenant_id=MEDIA_TENANT,
        draft_id=draft_id,
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    (draft,) = outcome.media
    # the kit's font changes after the preview: the final keeps the approved one
    producer._brand_fonts = lambda **_: None

    final = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)

    assert final.failure is None
    preview_recipe = composer.composes[0][1]
    _, recipe, _, stage = composer.composes[-1]
    assert stage == "final" and recipe == preview_recipe
    assert recipe.digest() == preview_recipe.digest()
    assert recipe.font is not None and recipe.font.sha256 == FONT.sha256
    assert final.media.params["compose"]["font"] == {"key": KEY, "sha256": FONT.sha256}


@pytest.mark.parametrize("damage", ["missing", "altered"])
def test_a_final_whose_font_file_is_gone_draws_in_the_family_recorded(damage: str) -> None:
    composer = FakeComposer()
    producer, store = _producer_with_font(composer, FONT_BYTES)
    brief = _brief_with(text_layers=(WORDS,))
    draft_id = uuid4()
    outcome = producer.produce(
        tenant_id=MEDIA_TENANT,
        draft_id=draft_id,
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
    )
    (draft,) = outcome.media
    if damage == "missing":
        del store.files[KEY]
    else:
        store.files[KEY] = FONT_BYTES + b"x"

    final = _final(producer, brief, _with_attempt(draft, "a1"), draft_id)

    assert final.failure is None  # never fails the final
    _, recipe, _, _ = composer.composes[-1]
    assert recipe.font is None and recipe.digest() == composer.composes[0][1].digest()
    redrawn = recipe.text_brand(drawing=True)
    assert isinstance(redrawn, BrandText) and redrawn.font is None and redrawn.font_rejected
    # a text kept from the preview is laid as drawn: nothing to record then
    assert recipe.text_brand(drawing=False) == dict(recipe.brand)


def test_stored_font_refuses_a_file_that_is_not_the_frozen_one() -> None:
    recipe = ComposeRecipe(
        text_layers=(WORDS,), brand={"fontFiles": {"heading": f"asset://{FONT.sha256}"}}
    )
    files = {KEY: FONT_BYTES}
    good = stored_font({"font": {"key": KEY, "sha256": FONT.sha256}}, recipe, files.get)
    assert good.font is not None and good.font.data == FONT_BYTES
    other = {"font": {"key": KEY, "sha256": "0" * 64}}
    assert stored_font(other, recipe, files.get).font is None
    assert stored_font({}, recipe, files.get).font is None
    bad = {KEY: NOT_A_FONT}
    sha = hashlib.sha256(NOT_A_FONT).hexdigest()
    fake = ComposeRecipe(text_layers=(WORDS,), brand={"fontFiles": {"heading": f"asset://{sha}"}})
    assert stored_font({"font": {"key": KEY, "sha256": sha}}, fake, bad.get).font is None

    def boom(_: str) -> bytes:
        raise OSError("R2 down")

    assert stored_font({"font": {"key": KEY, "sha256": FONT.sha256}}, recipe, boom).font is None


# ---------------------------------------------------------------------------
# digests: a recipe frozen before this change reads and hashes the same


OLD_RECIPE = {
    "text_layers": [
        {
            "text": "Shawarma mixto",
            "place": "top",
            "start_s": 0.0,
            "end_s": None,
            "fade_s": 0.5,
        }
    ],
    "effects": [],
    "brand": {"name": "", "palette": ["#B5532A"], "fonts": {"heading": "Poppins"}, "logo": None},
    "effects_pipeline_version": 1,
}


def test_a_recipe_frozen_before_keeps_its_digest() -> None:
    frozen = stored_recipe({"compose": {"recipe": OLD_RECIPE}})
    assert frozen is not None and frozen.font is None and frozen.font_ref is None
    canonical = json.dumps(frozen.to_params(), sort_keys=True, separators=(",", ":"))
    assert frozen.digest() == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert frozen.to_params()["brand"] == OLD_RECIPE["brand"]  # no fontFiles added
    assert stored_font({}, frozen, {}.get) is frozen
    assert font_params(frozen) is None
    # with a file the digest moves (its sha256 is named), with the same file it does not
    with_file = ComposeRecipe(
        text_layers=frozen.text_layers,
        brand={**OLD_RECIPE["brand"], "fontFiles": {"heading": f"asset://{FONT.sha256}"}},
        font=FONT,
    )
    assert with_file.digest() != frozen.digest()
    assert with_file.digest() == ComposeRecipe.from_params(with_file.to_params()).digest()


def test_compose_recipe_of_a_plain_kit_is_unchanged_by_brand_text() -> None:
    brief = _brief_with(text_layers=(WORDS,))
    plain = recompose.compose_recipe_of(brief, _kit())
    wrapped = recompose.compose_recipe_of(brief, BrandText(_kit(), None))
    assert plain is not None and wrapped is not None
    assert plain.digest() == wrapped.digest() and plain.to_params() == wrapped.to_params()
    with_file = recompose.compose_recipe_of(brief, BrandText(_kit(), FONT))
    assert with_file is not None and with_file.font == FONT
    assert with_file.to_params()["brand"] == {
        **plain.to_params()["brand"],
        "fontFiles": {"heading": f"asset://{FONT.sha256}"},
    }


# ---------------------------------------------------------------------------
# the real composer: what the render service is asked and what is recorded

pytest.importorskip("av")


def _recipe(kit: Any) -> ComposeRecipe:
    recipe = recompose.compose_recipe_of(
        _brief_with(text_layers=(VideoTextLayer(text="Hoy", place="top"),)), kit
    )
    assert recipe is not None
    return recipe


def test_the_composer_uploads_the_file_and_records_it(tmp_path: Path) -> None:
    service = FakeService()
    recipe = _recipe(BrandText(_kit_with_family(), FONT))
    composer = ClipComposer(service)
    (image,) = composer.draw(recipe)
    assert service.assets == {FONT.sha256: FONT_BYTES}
    (call,) = service.calls
    assert call["props"]["brand"]["fontFiles"] == {"heading": f"asset://{FONT.sha256}"}
    assert image.provenance["font_source"] == "file"
    assert image.provenance["font_sha256"] == FONT.sha256

    video = _tiny_video(tmp_path / "in.mp4", 1.0).read_bytes()
    made = composer.compose(video, recipe, drawn=(image,), stage="preview")
    (layer,) = made.params["text_layers"]["layers"]
    assert layer["font_source"] == "file" and "font_file_rejected" not in layer
    assert made.params["recipe_sha256"] == recipe.digest()


def test_the_composer_with_a_rejected_file_draws_the_family(tmp_path: Path) -> None:
    service = FakeService()
    recipe = _recipe(BrandText(_kit_with_family(), None, font_rejected=True))
    composer = ClipComposer(service)
    video = _tiny_video(tmp_path / "in.mp4", 1.0).read_bytes()
    made = composer.compose(video, recipe, stage="preview")
    assert service.assets == {}
    (call,) = service.calls
    assert "fontFiles" not in call["props"]["brand"]
    (layer,) = made.params["text_layers"]["layers"]
    assert layer["font_source"] == "family" and layer["font_file_rejected"] is True


def test_a_final_without_its_file_redraws_in_the_family_never_failing(tmp_path: Path) -> None:
    """The frozen recipe names a file the final cannot read back: a text it must draw
    again is drawn in the family, recorded — the final is not lost for it."""
    service = FakeService()
    frozen = _recipe(BrandText(_kit_with_family(), FONT))
    recipe = stored_recipe({"compose": {"recipe": frozen.to_params()}})
    assert recipe is not None and recipe.font is None and recipe.digest() == frozen.digest()
    video = _tiny_video(tmp_path / "in.mp4", 1.0).read_bytes()
    made = ClipComposer(service).compose(video, recipe, stage="final")
    assert service.assets == {}
    (call,) = service.calls
    assert "fontFiles" not in call["props"]["brand"]
    (layer,) = made.params["text_layers"]["layers"]
    assert layer["font_source"] == "family" and layer["font_file_rejected"] is True
    assert made.params["recipe_sha256"] == frozen.digest()
