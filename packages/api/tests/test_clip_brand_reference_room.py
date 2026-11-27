"""m-25078714: a Clip's Brand Kit images (logo in the scene, brand elements) travel to
Seedance as reference images with the frames — the PREPARED opening frame of own
stretches included (EF-11) — and the owner's photos. Together they must fit the model's
limit, checked before the copy is paid; over it the piece is refused naming what to
remove. Offline: the generator's fakes stand in for Claude and Seedance, nothing is paid."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_creative.enums import ContentKind

from qualify_api.creative.brand_references import BrandReferenceError
from qualify_api.creative.media import _clip_over_limit_text
from qualify_api.creative.service import ContentService
from qualify_api.creative.video_pipeline.prepared_frame import PREPARED_FRAME_REFS_SWITCH

from .test_brand_references import KEY, LOGO, _assets
from .test_creative_media_byteplus import BRAND_ID, BUDGET, COPY, TENANT_ID, _brief, _image, _kit
from .test_creative_prepared_frame import _clip, _part, _setup

pytest.importorskip("av")

PHOTOS = tuple(f"uploads/{TENANT_ID}/p{i}.jpg" for i in range(9))
OVER_TEXT = (
    "Tu video lleva 10 imágenes y el máximo es 9. Cuentan: 1 imagen de tu propio video, "
    "8 fotos y 1 imagen de tu marca. Quita 1 de tus fotos o imágenes de tu marca y vuelve "
    "a crear el video. No se cobró nada."
)


@pytest.fixture(autouse=True)
def refs_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PREPARED_FRAME_REFS_SWITCH, raising=False)


@pytest.fixture(autouse=True)
def no_normalize_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """The prepared frame's `normalize_local` jobs in memory: offline, no database."""
    from qualify_api.creative.video_pipeline import local_sources

    jobs = local_sources.InMemoryLocalSourceJobs()
    monkeypatch.setattr(local_sources, "default_jobs", lambda: jobs)


def _own_clip_with_logo(photos: int) -> Any:
    return _clip(
        clip_image_keys=PHOTOS[:photos],
        clip_image_roles=("product",) * photos,
        brand_logo_key=LOGO,
        brand_logo_in_scene=True,
    )


def _with_brand() -> tuple[Any, Any, Any]:
    producer, store, seedance = _setup({key: _image() for key in PHOTOS})
    _assets(producer, store)
    return producer, store, seedance


def _prepare(producer: Any, brief: Any) -> Any:
    return producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=uuid4(), brief=brief, kit=_kit()
    )


def _service(producer: Any) -> tuple[ContentService, list[dict[str, Any]]]:
    service = object.__new__(ContentService)
    service._brand = SimpleNamespace(kit=lambda **_: _kit())
    service._voice = SimpleNamespace(active=lambda **_: SimpleNamespace())
    service._repo = SimpleNamespace(budget_state=lambda **_: None)
    service._media = producer
    settled: list[dict[str, Any]] = []
    service._finish_brief = lambda **data: settled.append(data)
    service._copy_stage = lambda **_: pytest.fail("paid copy reached")
    return service, settled


# ---------------------------------------------------------------------------
# Criterion 1 — never over the limit after the copy is paid


def test_eight_photos_own_stretches_and_a_logo_are_refused_before_the_copy() -> None:
    """The ticket's case: 8 photos + the prepared frame + the logo = 10 over 9. Before
    m-25078714 both checks passed (8 + 1 logo, 8 + 1 frame) and the adapter refused it
    after Claude's copy was paid."""
    producer, store, _seedance = _with_brand()
    store.reads.clear()
    with pytest.raises(BrandReferenceError) as refused:
        _prepare(producer, _own_clip_with_logo(8))
    assert refused.value.detail == OVER_TEXT
    assert store.reads == []  # nothing read, nothing sent, nothing paid


def test_the_service_settles_it_without_paying_the_copy() -> None:
    producer, _store, seedance = _with_brand()
    service, settled = _service(producer)
    service._generate_brief(
        tenant_id=TENANT_ID,
        draft=SimpleNamespace(
            brand_id=BRAND_ID,
            id=uuid4(),
            revision=1,
            pipeline_version=producer.new_generation_pipeline_version,
        ),
        brief=_own_clip_with_logo(8),
    )
    assert settled[0]["spent"] == 0
    assert settled[0]["media_failure"] == "invalid_parameters"
    assert settled[0]["media_detail"] == OVER_TEXT
    assert seedance.requests == []


def test_at_the_limit_the_clip_is_made_with_every_image_it_counted() -> None:
    """7 photos + the prepared frame + the logo = 9: accepted, and the request carries
    exactly those 9 reference images — the count before the copy is the count sent."""
    producer, _store, seedance = _with_brand()
    brief = _own_clip_with_logo(7)
    draft_id = uuid4()
    refs = producer.prepare_brand_references(
        tenant_id=TENANT_ID, draft_id=draft_id, brief=brief, kit=_kit()
    )
    producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=draft_id, brief=brief)
    outcome = producer.produce(
        tenant_id=TENANT_ID,
        draft_id=draft_id,
        brief=brief,
        kit=_kit(),
        copy=COPY,
        budget=BUDGET,
        brand_references=refs,
    )
    assert outcome.failure is None, outcome.detail
    (request,) = seedance.requests
    assert len(request.params["reference_images"]) == 9


def test_brand_elements_count_too_and_a_closing_frame_is_named() -> None:
    producer, _store, _seedance = _with_brand()
    brief = _brief(
        ContentKind.CLIP,
        clip_first_frame_key=PHOTOS[0],
        clip_last_frame_key=PHOTOS[1],
        clip_image_keys=PHOTOS[2:8],
        clip_image_roles=("product",) * 6,
        brand_element_keys=(KEY,),
        brand_logo_key=LOGO,
        brand_logo_in_scene=True,
    )
    with pytest.raises(BrandReferenceError) as refused:
        _prepare(producer, brief)
    assert refused.value.detail == (
        "Tu video lleva 10 imágenes y el máximo es 9. Cuentan: la imagen de inicio, la "
        "imagen de cierre, 6 fotos y 2 imágenes de tu marca. Quita 1 de tus fotos o "
        "imágenes de tu marca y vuelve a crear el video. No se cobró nada."
    )


@pytest.mark.parametrize("reference", [None, "seedance-1-0-pro-250528"])
def test_a_model_that_takes_no_references_is_said_before_the_count(
    reference: str | None,
) -> None:
    """Review #1: without a reference model (or with one that takes no references) the
    owner reads that this video cannot use brand images, never «Quita N…» first."""
    producer, _store, _seedance = _with_brand()
    producer._seedance_reference_model = reference
    brief = _brief(
        ContentKind.CLIP,
        clip_image_keys=PHOTOS,
        clip_image_roles=("product",) * 9,
        brand_logo_key=LOGO,
        brand_logo_in_scene=True,
    )
    with pytest.raises(BrandReferenceError) as refused:
        _prepare(producer, brief)
    assert refused.value.detail.startswith(
        "Este tipo de video no puede usar las imágenes de tu marca"
    )


# ---------------------------------------------------------------------------
# Pieces without brand images and parts: unchanged


def test_a_clip_without_brand_images_is_unchanged() -> None:
    """8 photos + the prepared frame = 9, no brand: accepted as before; 9 photos keep
    EF-11's own refusal (`_prepared_frame_room`), never the new text."""
    producer, _store, _seedance = _with_brand()
    fits = _clip(clip_image_keys=PHOTOS[:8], clip_image_roles=("product",) * 8)
    assert _prepare(producer, fits).refs == ()
    producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=uuid4(), brief=fits)

    over = _clip(clip_image_keys=PHOTOS, clip_image_roles=("product",) * 9)
    assert _prepare(producer, over).refs == ()  # the brand check has nothing to count
    with pytest.raises(BrandReferenceError) as refused:
        producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=uuid4(), brief=over)
    assert refused.value.detail.startswith("Con tu video caben hasta 8 fotos")


def test_a_part_carries_no_brand_images_and_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VE-09: a part sends no Brand Kit image, so the brand check never refuses it; with
    the switch on, 8 photos + the prepared frame still fit as before."""
    monkeypatch.setenv(PREPARED_FRAME_REFS_SWITCH, "on")
    producer, _store, _seedance = _with_brand()
    part = _part(
        "reference",
        clip_image_keys=PHOTOS[:8],
        clip_image_roles=("product",) * 8,
    ).model_copy(update={"product_ref": "Smash doble"})
    assert _prepare(producer, part).refs == ()
    producer.prepare_reference_videos(tenant_id=TENANT_ID, draft_id=uuid4(), brief=part)


# ---------------------------------------------------------------------------
# Criterion 2 — the refusal says what to remove


@pytest.mark.parametrize(
    "fields, expected",
    [
        (
            {"limit": 9, "prepared": True, "frames": 1, "photos": 0, "brand_images": 9},
            "Tu video lleva 10 imágenes y el máximo es 9. Cuentan: 1 imagen de tu propio "
            "video y 9 imágenes de tu marca. Quita 1 de las imágenes de tu marca y vuelve a "
            "crear el video. No se cobró nada.",
        ),
        (
            {"limit": 9, "prepared": False, "frames": 0, "photos": 1, "brand_images": 10},
            "Tu video lleva 11 imágenes y el máximo es 9. Cuentan: 1 foto y 10 imágenes de "
            "tu marca. Quita 2 de tus fotos o imágenes de tu marca y vuelve a crear el "
            "video. No se cobró nada.",
        ),
        (
            {"limit": 9, "prepared": True, "frames": 2, "photos": 8, "brand_images": 0},
            "Tu video lleva 10 imágenes y el máximo es 9. Cuentan: 1 imagen de tu propio "
            "video, la imagen de cierre y 8 fotos. Quita 1 de tus fotos y vuelve a crear el "
            "video. No se cobró nada.",
        ),
    ],
)
def test_the_refusal_names_what_the_clip_carries_and_how_many_to_remove(
    fields: dict[str, Any], expected: str
) -> None:
    assert _clip_over_limit_text(**fields) == expected
