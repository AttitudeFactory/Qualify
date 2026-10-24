"""Every media prompt within `MEDIA_PROMPT_BUDGET` (founder, 2026-10-23: «si el proveedor
admite más aumenta el límite a unos 2500 y ajusta los prompts para que nunca pasen estos
caracteres»). The topic is no longer cut at a fixed 600: it gets the room the rest leaves —
a ~900-character topic whose last sentence told slide 1 what to show reached no slide."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from qualify_creative.adapters.byteplus_ark import MAX_PROMPT_CHARS
from qualify_creative.enums import (
    AdImageMode,
    AvatarSource,
    BriefObjective,
    ContentKind,
    ImageRoute,
    VideoEngine,
)
from qualify_creative.schemas import (
    AVATAR_PROMPT_MAX,
    HIGHLIGHT_KEY_MAX,
    HIGHLIGHT_VALUE_MAX,
    HIGHLIGHTS_MAX,
    SCENE_PROMPT_MAX,
    SCRIPT_MAX,
    BrandKit,
    BriefConstraints,
    ContentBrief,
    CopyPayload,
    MediaInputs,
    ScriptShot,
    ToneAxes,
)

from qualify_api.creative.media import (
    _DIALOGUE_WRAPPER,
    _SPOKEN_MIN,
    _TALKING_MOTION_BUDGET,
    MEDIA_PROMPT_BUDGET,
    SPOKEN_LINE_NO_ROOM_TEXT,
    _budgeted,
    _cut,
    _Flex,
    _spoken_line,
    ad_scene_prompt,
    carousel_motion_prompt,
    carousel_scene_prompt,
    clip_prompt,
    first_frame_prompt,
    motion_prompt,
)

BRAND_ID = UUID("7e7e0000-0000-4000-8000-000000000031")
PRODUCT_KEY = "uploads/7e7e0000-0000-4000-8000-000000000030/p1.jpg"
#: The regression: ~900 characters whose tail is the instruction for slide 1.
TOPIC_900 = (
    "Carrusel de la promoción de aniversario de la tienda: queremos contar que todos los "
    "productos de la colección de temporada tienen descuento durante el fin de semana, que "
    "el envío es gratis en la ciudad y que quien compre dos prendas se lleva un accesorio "
    "de regalo. El tono es cercano y alegre, con fotos luminosas de las prendas en uso, "
    "personas reales en la calle y en casa, colores de la marca presentes pero sin "
    "saturar, y siempre con la misma luz cálida de la tarde. Cada diapositiva muestra "
    "una prenda distinta con su beneficio principal, y "
    "la última invita a escribir por mensaje directo para apartar la talla antes de que "
    "se agote, porque las existencias son limitadas y la promoción termina el domingo a "
    "medianoche. La primera imagen debe mostrar el 15% de descuento sobre la chaqueta de "
    "jean, en grande, con la prenda colgada en un perchero de madera frente a una pared "
    "clara."
)
LONG_TOPIC = " ".join(f"Detalle {i} que el operador quiso contar," for i in range(130))
#: The «Datos clave» at their stored maximum (the prompt keeps what fits its own cap).
MAX_FACTS = tuple(
    (f"{i:02d}" + "k" * (HIGHLIGHT_KEY_MAX - 2), "v" * HIGHLIGHT_VALUE_MAX)
    for i in range(HIGHLIGHTS_MAX)
)
#: How every builder's prompt ends: the closing instruction never gives way.
ENDINGS = (
    "anywhere in the image.",
    "No text on screen.",
    "the product shown match.",
    "the post's text carries them.",
)


def _kit() -> BrandKit:
    return BrandKit(
        brand_id=BRAND_ID,
        positioning="Moda",
        audience="Jóvenes",
        tone_axes=ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        ),
        palette_rgb=("#C4622D", "#F5C518", "#111111", "#FAFAFA"),
        font_heading="F" * 500,
    )


def _brief(kind: ContentKind, topic: str, *, facts: bool = True, **media: Any) -> ContentBrief:
    return ContentBrief(
        brand_id=BRAND_ID,
        objective=BriefObjective.SALE,
        topic=topic,
        image_route=ImageRoute.TEMPLATE_ONLY,
        kind=kind,
        format=kind.default_format,
        media=MediaInputs(**media),
        constraints=BriefConstraints(highlights=MAX_FACTS if facts else ()),
    )


def _prompts(topic: str, *, facts: bool = True, long_parts: bool = True) -> dict[str, str]:
    """Every builder; with `long_parts`, every other variable part at its longest."""
    kit = _kit()
    scene = "x" * SCENE_PROMPT_MAX if long_parts else "La chaqueta en un perchero"
    flyer = _brief(
        ContentKind.STATIC_FLYER,
        topic,
        facts=facts,
        ad_mode=AdImageMode.PRODUCT,
        product_keys=(PRODUCT_KEY,),
        scene_prompt=scene,
    )
    avatar = _brief(
        ContentKind.AVATAR_VIDEO,
        topic,
        facts=facts,
        video_engine=VideoEngine.SEEDANCE,
        avatar_source=AvatarSource.AI,
        avatar_prompt="y" * AVATAR_PROMPT_MAX if long_parts else "Mujer joven",
    )
    clip = _brief(ContentKind.CLIP, topic, facts=facts)
    shots = tuple(ScriptShot(visual=f"Toma {n} " + "z" * 600, seconds=4) for n in range(1, 5))
    copy = CopyPayload(
        hook="h" * 60 if long_parts else "¿Ya viste?",
        caption="c",
        cta="Escríbenos",
        shots=shots if long_parts else (),
    )
    many = 10 if long_parts else 1
    roles = ("product", "place", "style", "product", "place", "style", "product")
    return {
        "ad": ad_scene_prompt(
            brief=flyer,
            kit=kit,
            brand="Marca " * 10,
            mode=AdImageMode.PRODUCT,
            products=many,
            has_background=True,
        ),
        "slide": carousel_scene_prompt(
            brief=flyer,
            kit=kit,
            brand="Marca " * 10,
            scene=scene,
            ratio="4:5",
            has_product=True,
            has_background=True,
            has_text=True,
        ),
        "slide motion": carousel_motion_prompt(flyer),
        "first frame": first_frame_prompt(
            brief=avatar, kit=kit, has_character_image=False, products=many, has_background=True
        ),
        "avatar motion": motion_prompt(brief=avatar, products=many),
        "clip": clip_prompt(
            brief=clip.model_copy(update={"product_ref": "p" * 400}),
            kit=kit,
            copy=copy,
            first_frame=True,
            last_frame=True,
            images=len(roles) if long_parts else 0,
            videos=3 if long_parts else 0,
            audios=3 if long_parts else 0,
            image_roles=roles if long_parts else (),
        ),
    }


def test_the_budget_leaves_the_vendor_a_margin() -> None:
    assert MEDIA_PROMPT_BUDGET == 2500 < MAX_PROMPT_CHARS


def test_a_5000_character_topic_never_takes_a_prompt_over_the_budget() -> None:
    topic = (LONG_TOPIC * 4)[:5000]
    assert len(topic) == 5000
    for facts in (True, False):
        for name, prompt in _prompts(topic, facts=facts).items():
            assert len(prompt) <= MEDIA_PROMPT_BUDGET, (name, len(prompt))
            assert prompt.endswith(ENDINGS), (name, prompt[-60:])
            if "motion" not in name:  # the motion prompts carry no topic
                assert "Detalle 0 que el operador" in prompt, name
                assert "Detalle 129" not in prompt, name


def test_a_900_character_topic_now_goes_in_whole() -> None:
    assert 850 <= len(TOPIC_900) <= 950
    for name, prompt in _prompts(TOPIC_900, facts=False, long_parts=False).items():
        assert len(prompt) <= MEDIA_PROMPT_BUDGET, name
        if "motion" not in name:
            assert TOPIC_900 in prompt, name
            assert "La primera imagen debe mostrar el 15%" in prompt, name


def test_a_900_character_topic_goes_whole_into_a_slide_with_a_full_scene() -> None:
    """The gallery that broke: a per-slide scene at its own cap (600) and the operator's
    long topic — the topic now reaches the slide whole, its last sentence included."""
    flyer = _brief(ContentKind.STATIC_FLYER, TOPIC_900, facts=False)
    prompt = carousel_scene_prompt(
        brief=flyer,
        kit=_kit(),
        brand="Bianki",
        scene="x" * SCENE_PROMPT_MAX,
        ratio="4:5",
        has_product=True,
        has_background=True,
        has_text=True,
    )
    assert TOPIC_900 in prompt and "x" * SCENE_PROMPT_MAX in prompt
    assert len(prompt) <= MEDIA_PROMPT_BUDGET


def test_short_prompts_are_left_as_they_were() -> None:
    """Under the budget nothing is trimmed or reformatted: the lines joined by a space,
    the operator's words as typed (double quotes turned single)."""
    topic = 'Smash doble   con "papas"'
    for name, prompt in _prompts(topic, facts=False, long_parts=False).items():
        if "motion" not in name:
            assert "Smash doble   con 'papas'" in prompt, name
    flyer = _brief(ContentKind.STATIC_FLYER, topic, facts=False)
    prompt = carousel_scene_prompt(
        brief=flyer,
        kit=_kit(),
        brand="",
        scene="En la barra",
        ratio="4:5",
        has_product=False,
        has_background=False,
        has_text=False,
    )
    assert (
        'This slide shows (in Spanish): "En la barra". The carousel is about (in Spanish): '
        "\"Smash doble   con 'papas'\"." in prompt
    )


def test_the_topic_gives_way_first_then_the_scene_then_the_shots() -> None:
    lines: list[str | _Flex] = [
        "a" * 1000,
        _Flex('Topic: "', "t" * 1000),
        _Flex('Scene: "', "s" * 1000, rank=1),
        _Flex('Shot: "', "h" * 500, rank=2, floor=80),
    ]
    whole = len(_budgeted(lines, budget=10_000))
    # 300 over: the topic alone pays
    prompt = _budgeted(lines, budget=whole - 300)
    assert len(prompt) <= whole - 300
    assert "t" * 700 in prompt and "t" * 701 not in prompt
    assert "s" * 1000 in prompt and "h" * 500 in prompt
    # past the topic's floor, the scene pays, then the shots
    prompt = _budgeted(lines, budget=1700)
    assert len(prompt) <= 1700
    assert "t" * 200 in prompt and "t" * 201 not in prompt
    assert "s" * 200 in prompt and "s" * 201 not in prompt
    assert "h" * 80 in prompt
    # below every floor the order turns: the shots go first, the topic last
    prompt = _budgeted(lines, budget=1100)
    assert len(prompt) <= 1100 and "Shot:" not in prompt and "Topic:" in prompt


def test_the_spoken_line_fits_the_room_the_motion_prompt_leaves() -> None:
    avatar = _brief(
        ContentKind.AVATAR_VIDEO,
        "x",
        video_engine=VideoEngine.SEEDANCE,
        avatar_source=AvatarSource.AI,
        avatar_prompt="Mujer joven",
    )
    motion = motion_prompt(brief=avatar, products=1)
    script = " ".join(f"Frase número {i} del guion largo." for i in range(400))
    spoken = _spoken_line(script, motion)
    assert len(spoken) <= SCRIPT_MAX and spoken.endswith("largo.")
    assert len(motion) + len(_DIALOGUE_WRAPPER) + len(spoken) <= MEDIA_PROMPT_BUDGET
    assert _spoken_line("Hola. Pídela hoy.", motion) == "Hola. Pídela hoy."


def test_a_topic_a_little_over_its_room_keeps_almost_all_of_it() -> None:
    """Review fix: the cut used to take the LAST PAUSE that fits — with one early comma
    a topic 10 characters over its room was cut back to that comma."""
    topic = "Promo de aniversario, " + " ".join(f"detalle{i} de la tienda" for i in range(40))
    lines: list[str | _Flex] = ["Fixed instruction line.", _Flex('About: "', topic)]
    whole = _budgeted(lines, budget=10_000)
    budget = len(whole) - 10

    prompt = _budgeted(lines, budget=budget)

    assert len(prompt) <= budget
    assert len(prompt) >= budget - 25  # one word and its dangling article at most
    assert "Promo de aniversario, detalle0" in prompt


def test_the_cut_still_prefers_a_pause_near_the_limit() -> None:
    text = "a" * 90 + ", y algo más que no cabe en el límite de la línea"
    cut = _cut(text, 100)
    assert cut == "a" * 90  # the comma is within the last fifth of the room


def test_a_talking_videos_motion_prompt_always_leaves_room_for_the_line() -> None:
    """Review round 4: the line could be cut to "" by a motion prompt that left no room
    — a talking video with nothing said. The room is reserved; with none, the piece
    fails before anything is paid for."""
    import pytest

    from qualify_api.creative.media import _MediaFailed

    avatar = _brief(
        ContentKind.AVATAR_VIDEO,
        "x",
        video_engine=VideoEngine.SEEDANCE,
        avatar_source=AvatarSource.AI,
        avatar_prompt="Mujer joven",
    )
    motion = motion_prompt(brief=avatar, products=3, budget=_TALKING_MOTION_BUDGET)
    assert MEDIA_PROMPT_BUDGET - len(motion) - len(_DIALOGUE_WRAPPER) >= _SPOKEN_MIN
    script = " ".join(f"Frase número {i} del guion largo." for i in range(400))
    assert _spoken_line(script, motion).endswith("largo.")

    with pytest.raises(_MediaFailed) as excinfo:
        _spoken_line("Hola, pídela hoy.", "m" * MEDIA_PROMPT_BUDGET)
    assert excinfo.value.detail == SPOKEN_LINE_NO_ROOM_TEXT
    assert _spoken_line("", "m" * MEDIA_PROMPT_BUDGET) == ""  # nothing to say: no failure
