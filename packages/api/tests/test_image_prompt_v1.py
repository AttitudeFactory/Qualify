"""Seedream image prompts at compiler 1 (m-24820842, round 6, 2026-11-02): the founder's
two refused flyers (75d29899 / 166eedb7) — the same 3,000/2,950 character cap stays (a new
Seedream version is coming), but the prompt loses its genuine duplication: a flyer's topic
IS its scene (`_effective_topic`), so the same words travelled twice; and the text rule
repeated what the typefaces line says about labels and logo lettering. Offline contracts on
a synthetic flyer of the same shape, not model quality."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import ContentKind
from qualify_creative.scene_plan import ad_mode_for, flyer_scene_plans, product_photos
from qualify_creative.schemas import BrandKit, ContentBrief

from qualify_api.creative import media as media_module
from qualify_api.creative.brand_kit_store import BrandAsset
from qualify_api.creative.brand_references import (
    BrandReference,
    BrandReferenceError,
    BrandReferencesSet,
)
from qualify_api.creative.media import (
    _PROMPT_REPORTS,
    MEDIA_PROMPT_BUDGET,
    _selection_combos,
    ad_scene_prompt,
    carousel_scene_prompt,
)

from .prompt_quality import assert_image_prompt_keeps_intent
from .test_creative_media_byteplus import MemoryStore, _image, _producer
from .test_semantic_resource_selection import Selector

DATA = json.loads(
    (
        Path(__file__).parent / "fixtures" / "clip_edit_budget_real_20261102_anonymized.json"
    ).read_text(encoding="utf8")
)
TENANT = UUID("00000000-0000-0000-0000-000000000001")
#: A 287-character scene, like the founder's first try (synthetic words).
SCENE = (
    "Una mano sostiene en alto la hamburguesa de la casa a la altura de los ojos: pan "
    "brillante, dos carnes de bordes crujientes, queso derretido cayendo y tocineta dorada. "
    "Al fondo, un local nocturno desenfocado con luz roja, humo de plancha y gotas brillantes."
    " Vertical, contraluz rojo y brillo."
).ljust(287, ".")[:287]
FACTS = (
    ("Precio", "10$ la combinación con papas"),
    ("Horario", "Viernes y sábado hasta las 2 a. m."),
    ("Domicilio", "Pide por mensaje y te lo llevamos"),
)
#: (logo combination → characters) with the 287-character scene: 0 imagotipo, 1 isologo,
#: 2 isotipo. The founder's real flyer measured 1 more in each (2999/2971/2962/3148).
V0 = {"0": 2998, "1": 2970, "2": 2961, "0+1+2": 3147}
V1 = {"0": 2589, "1": 2561, "2": 2552, "0+1+2": 2738}


def _kit() -> BrandKit:
    return BrandKit.model_validate(DATA["kit"])


def _logos() -> list[dict[str, Any]]:
    return DATA["logo_candidates"]


def _flyer(version: int = 1, scene: str = SCENE) -> ContentBrief:
    logos = _logos()
    brief = ContentBrief.model_validate(
        {
            "brand_id": DATA["brief"]["brand_id"],
            "objective": "consideration",
            "topic": scene,  # `_effective_topic`: a flyer's context IS its scene
            "image_route": "template_only",
            "kind": "static_flyer",
            "format": "feed_4_5",
            "constraints": {
                "highlights": [list(f) for f in FACTS],
                "must_mention": ["Pide por mensaje", "Carne hecha al momento", "Abierto tarde"],
                "must_avoid": ["barato", "comida rápida", "la competencia"],
            },
            "media": {
                "background_key": f"t/{TENANT}/stock/pixabay/1/fondo.jpg",
                "product_keys": [
                    f"t/{TENANT}/stock/pixabay/2/guia.jpg",
                    f"uploads/{TENANT}/catalog/p/foto.jpg",
                ],
                "product_image_roles": ["composition", "product"],
                "scene_prompt": scene,
                "brand_logo_key": logos[2]["asset_key"],
                "brand_logo_reference_keys": [logos[0]["asset_key"], logos[1]["asset_key"]],
                "brand_logo_in_scene": True,
            },
        }
    )
    media = brief.media.model_copy(
        update={
            "resource_plan_version": 2,
            "brand_application_version": 2,
            "prompt_compiler_version": version,
        }
    )
    return brief.model_copy(update={"media": media})


def _references() -> BrandReferencesSet:
    refs = tuple(BrandReference.model_validate(c) for c in _logos())
    return BrandReferencesSet(refs=refs, block_version=9)


def _compile(brief: ContentBrief, refs: tuple[BrandReference, ...]) -> tuple[str, Any]:
    mode = ad_mode_for(brief.media)
    (plan,) = flyer_scene_plans(brief.media, mode)
    reports: list[dict[str, Any]] = []
    token = _PROMPT_REPORTS.set(reports)
    try:
        prompt = ad_scene_prompt(
            brief=brief,
            kit=_kit(),
            brand="",
            mode=mode,
            products=len(plan.photos),
            has_background=bool(plan.background_key),
            background_index=plan.background_number,
            brand_refs=refs,
            scene_plan=plan,
        )
    finally:
        _PROMPT_REPORTS.reset(token)
    return prompt, (reports[-1], plan)


def _needed(brief: ContentBrief, refs: tuple[BrandReference, ...]) -> int:
    try:
        return len(_compile(brief, refs)[0])
    except media_module._PromptOverBudget as exc:
        return exc.needed


def _label(refs: tuple[BrandReference, ...]) -> str:
    keys = [c["asset_key"] for c in _logos()]
    return "+".join(str(keys.index(r.asset_key)) for r in refs)


def test_the_founders_flyer_shape_fits_at_v1_with_nothing_trimmed() -> None:
    assert len(SCENE) == 287 and len(product_photos(_flyer().media)) == 2
    sizes = {}
    for refs in _selection_combos(_references()):
        assert _needed(_flyer(version=0), refs) == V0[_label(refs)]  # the old compiler
        prompt, (report, plan) = _compile(_flyer(), refs)
        sizes[_label(refs)] = len(prompt)
        assert report["trims"] == () and len(prompt) <= MEDIA_PROMPT_BUDGET
        assert_image_prompt_keeps_intent(
            prompt,
            brief=_flyer(),
            kit=_kit(),
            refs=refs,
            base_index=plan.image_count,
            budget=MEDIA_PROMPT_BUDGET,
            trims=report["trims"],
        )
        assert prompt.count(SCENE[:60]) == 1  # the scene once, not twice
    assert sizes == V1


def test_v0_keeps_both_lines_byte_for_byte() -> None:
    brief = _flyer(version=0, scene="Una hamburguesa sobre la mesa.")
    prompt, _ = _compile(brief, _selection_combos(_references())[0])
    assert 'The post is about (in Spanish): "' in prompt
    assert "Preserve authentic product/manufacturer labels and the exact supplied logo" in prompt


def test_a_topic_that_differs_from_the_scene_still_travels() -> None:
    brief = _flyer().model_copy(update={"topic": "Promoción del fin de semana"})
    prompt, _ = _compile(brief, _selection_combos(_references())[0])
    assert 'The post is about (in Spanish): "Promoción del fin de semana".' in prompt


def test_carousel_slide_drops_only_an_exact_repetition() -> None:
    brief = _flyer().model_copy(update={"kind": ContentKind.CAROUSEL, "topic": "Galería"})

    def slide(scene: str, topic: str) -> str:
        return carousel_scene_prompt(
            brief=brief.model_copy(update={"topic": topic}),
            kit=_kit(),
            brand="",
            scene=scene,
            ratio="4:5",
            has_product=True,
            has_background=False,
            has_text=True,
            brand_refs=_selection_combos(_references())[0],
        )

    assert 'The carousel is about (in Spanish): "' not in slide("La mesa.", "La mesa.")
    assert 'The carousel is about (in Spanish): "Galería".' in slide("La mesa.", "Galería")
    same = brief.model_copy(update={"topic": SCENE})
    assert_image_prompt_keeps_intent(
        slide(SCENE, SCENE),
        brief=same,
        kit=_kit(),
        refs=_selection_combos(_references())[0],
        base_index=1,
        budget=MEDIA_PROMPT_BUDGET,
        scene=SCENE,
    )


def _flyer_producer() -> Any:
    store = MemoryStore({c["asset_key"]: _image() for c in _logos()})
    producer = _producer(store)
    producer._semantic_selection = True
    producer._router._providers["anthropic"] = Selector()
    rows = [
        BrandAsset(
            "logo_version",
            c["asset_slot"],
            c["asset_key"],
            label=c["label"],
            content_type=c["content_type"],
        )
        for c in _logos()
    ]
    producer._brand_assets = lambda tenant, brand: list(rows)
    return producer


def test_the_refusal_names_the_worst_excess_of_every_combination() -> None:
    """Founder's tries: 12 characters over, then 144 — the first failing combination was
    reported, not the worst one. Now one refusal says the whole excess."""
    long = (SCENE + " " + "detalle " * 60)[:600]  # the field's own maximum
    brief = _flyer(scene=long)
    needed = [_needed(brief, refs) for refs in _selection_combos(_references())]
    worst = max(needed)
    assert worst > MEDIA_PROMPT_BUDGET and needed[0] != worst
    producer = _flyer_producer()
    with pytest.raises(BrandReferenceError) as caught:
        producer.prepare_brand_references(
            tenant_id=TENANT, draft_id=uuid4(), brief=brief, kit=_kit()
        )
    assert f"sobran {worst - MEDIA_PROMPT_BUDGET} caracteres" in caught.value.detail


def test_a_seedream_disconnect_tells_the_owner_to_retry_later() -> None:
    raw = (
        "SeedreamDisconnected: RemoteProtocolError: Server disconnected without sending a response."
    )
    assert media_module.ark_failure_text(raw) == (
        "Tu imagen tardó más de lo normal y no alcanzó a salir. Lo que elegiste sigue aquí: "
        "inténtalo de nuevo en unos minutos. No se descontó de tus creaciones."
    )
    # a dropped connection elsewhere (a video task) keeps its own wording
    assert media_module.ark_failure_text("RemoteProtocolError: x") == (
        media_module.GENERIC_FAILURE_TEXT
    )


def test_seedream_sizes_are_about_two_megapixels_and_never_under_the_published_size() -> None:
    published = {
        "4:5": (1080, 1350),
        "1:1": (1080, 1080),
        "9:16": (1080, 1920),
        "3:4": (1080, 1440),
    }
    for ratio, size in media_module.SCENE_SIZES.items():
        width, height = (int(v) for v in size.split("x"))
        assert width * height >= 921_600 and width >= published[ratio][0]
        assert height >= published[ratio][1] and width * height <= 2_100_000
        num, den = (int(v) for v in ratio.split(":"))
        assert width * den == height * num
