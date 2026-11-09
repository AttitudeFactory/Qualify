"""m-24820842 (founder, 2026-11-03): a draft frozen on `main` — compiler 0, no brand
resources, no resource plan — compiles EXACTLY as `main` compiled it: the 2,500-character
budget and no `visual_text` cleaning (emoji and decorations travel as the owner wrote
them). The 2,950 budget and the cleaning start at compiler 1.

`MAIN_DIGEST` was taken on 2026-11-03 by running `compile_cases()` from this very file
against origin/main's sources (`fa4ff75c`, `git archive` of packages/*/src) — the same
837 prompts across every public prompt function (ad image, gallery slide, gallery
motion, first frame, talking motion, clip, reel replica) with a short, a long and an
emoji-laden topic and scene. Only public functions and kwargs `main` has are used, so the
module runs unchanged on both trees."""

from __future__ import annotations

import hashlib
import json
from itertools import product as cartesian
from uuid import UUID

from qualify_creative.enums import AdImageMode
from qualify_creative.schemas import (
    BrandKit,
    ContentBrief,
    CopyPayload,
    HashtagPolicy,
    LengthTargets,
    ToneAxes,
)

from qualify_api.creative import media as M

MAIN_DIGEST = "eccf5d358a29fa36ffce402635facab295058bde79380822adcf425e27793987"

BRAND_ID = UUID("a3b1c2d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")
LONG = (
    "Quiero mostrar la Super Smash doble con papas, la plancha prendida, el queso "
    "derritiéndose y la carne aplastándose. "
) * 40
EMOJI = "✨🔥 ¡Promo de la semana! ★★★ Super Smash a 10$ 🍔🍟 — solo viernes y sábado ✔️"
TOPICS = {"short": "Smash burger doble", "long": LONG, "emoji": EMOJI}
SCENES = {"none": "", "long": LONG[:600], "emoji": EMOJI}


def _kit() -> BrandKit:
    return BrandKit(
        brand_id=BRAND_ID,
        positioning="Cakes that taste like your grandmother's kitchen",
        audience="Young families in Bogota ordering for celebrations",
        tone_axes=ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        ),
        do_examples=("Hoy salieron del horno estas delicias",),
        dont_examples=("SOMOS LOS MEJORES DEL MERCADO",),
        banned_words=("barato",),
        forbidden_claims=("el mejor de la ciudad",),
        hashtag_policy=HashtagPolicy(minimum=1, maximum=5, always=("bianki",), never=("ad",)),
        length_targets=LengthTargets(caption_min_chars=20, caption_max_chars=400),
        cta_patterns=("Escribenos al DM",),
    )


def _brief(kind: str, topic: str, scene: str, **media: object) -> ContentBrief:
    data = {
        "brand_id": str(BRAND_ID),
        "objective": "sale",
        "topic": topic,
        "kind": kind,
        "image_route": "template_only",
        "media": {**({"scene_prompt": scene} if kind == "static_flyer" else {}), **media},
    }
    try:  # how a frozen brief is read back on this branch
        return ContentBrief.model_validate(data, context={"preserve_stored_logo_mode": True})
    except TypeError:  # pragma: no cover - main's model_validate takes the same context
        return ContentBrief.model_validate(data)


COPY = CopyPayload.model_validate(
    {
        "hook": "¿Antojo a la 1 a. m.? 🍔",
        "caption": "Dos carnes, costra y cheddar chorreando ✨",
        "hashtags": ["smash"],
        "cta": "Pide por WhatsApp",
        "script": "",
        "shots": [
            {"visual": "plancha prendida 🔥", "line": "", "seconds": 2},
            {"visual": "queso derritiéndose", "line": "", "seconds": 2},
            {"visual": "la hamburguesa lista", "line": "", "seconds": 1},
        ],
    }
)


def compile_cases() -> dict[str, str]:
    kit = _kit()
    out: dict[str, str] = {}

    def run(name: str, fn, **kwargs) -> None:  # noqa: ANN001
        try:
            out[name] = fn(**kwargs)
        except Exception as exc:  # the same refusal on both trees counts as equal
            out[name] = f"!{type(exc).__name__}: {exc}"

    for (tn, topic), (sn, scene) in cartesian(TOPICS.items(), SCENES.items()):
        flyer = _brief("static_flyer", topic, scene)
        for mode in AdImageMode:
            for products, bg in cartesian((0, 1, 2), (False, True)):
                run(
                    f"ad/{tn}/{sn}/{mode.value}/{products}/{bg}",
                    M.ad_scene_prompt,
                    brief=flyer,
                    kit=kit,
                    brand="Bianki",
                    mode=mode,
                    products=products,
                    has_background=bg,
                )
        gallery = _brief(
            "carousel", topic, scene, slides=[{"source": "generated"}, {"source": "generated"}]
        )
        for hp, hb, ht in cartesian((False, True), (False, True), (False, True)):
            run(
                f"slide/{tn}/{sn}/{hp}/{hb}/{ht}",
                M.carousel_scene_prompt,
                brief=gallery,
                kit=kit,
                brand="Bianki",
                scene=scene or topic,
                ratio="4:5",
                has_product=hp,
                has_background=hb,
                has_text=ht,
            )
        run(f"carousel_motion/{tn}/{sn}", M.carousel_motion_prompt, brief=gallery)
        video = _brief(
            "avatar_video",
            topic,
            scene,
            avatar_look_id="lk",
            voice_id="vo",
            video_engine="seedance",
            avatar_prompt="una mujer joven sonriente",
            avatar_source="ai",
        )
        for ch, products, bg in cartesian((False, True), (0, 1), (False, True)):
            run(
                f"first_frame/{tn}/{sn}/{ch}/{products}/{bg}",
                M.first_frame_prompt,
                brief=video,
                kit=kit,
                has_character_image=ch,
                products=products,
                has_background=bg,
            )
        for products in (0, 1):
            run(f"motion/{tn}/{sn}/{products}", M.motion_prompt, brief=video, products=products)
        clip = _brief("clip", topic, scene, duration_seconds=5)
        for ff, lf, images, videos, audios, with_copy in cartesian(
            (False, True), (False, True), (0, 2), (0, 1), (0, 1), (False, True)
        ):
            if lf and not ff:
                continue
            run(
                f"clip/{tn}/{sn}/{ff}/{lf}/{images}/{videos}/{audios}/{with_copy}",
                M.clip_prompt,
                brief=clip,
                kit=kit,
                first_frame=ff,
                last_frame=lf,
                images=images,
                videos=videos,
                audios=audios,
                copy=COPY if with_copy else None,
            )
        for images in (0, 1):
            run(f"edit/{tn}/{sn}/{images}", M.reel_edit_prompt, brief=clip, kit=kit, images=images)
    return out


def digest(cases: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(cases, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def test_a_brief_frozen_on_main_compiles_byte_for_byte_as_main() -> None:
    cases = compile_cases()
    assert len(cases) == 837
    assert digest(cases) == MAIN_DIGEST


def test_the_frozen_compile_keeps_emoji_and_mains_budget() -> None:
    flyer = _brief("static_flyer", EMOJI, "")
    prompt = M.ad_scene_prompt(
        brief=flyer,
        kit=_kit(),
        brand="Bianki",
        mode=AdImageMode.BACKGROUND,
        products=1,
        has_background=False,
    )
    assert "✨🔥" in prompt  # no `visual_text` cleaning at compiler 0
    long_ad = M.ad_scene_prompt(
        brief=_brief("static_flyer", LONG, ""),
        kit=_kit(),
        brand="Bianki",
        mode=AdImageMode.BACKGROUND,
        products=1,
        has_background=False,
    )
    assert len(long_ad) <= M.V0_MEDIA_PROMPT_BUDGET == 2500
    # compiler 1 cleans and gets the larger budget
    current = flyer.model_copy(
        update={"media": flyer.media.model_copy(update={"prompt_compiler_version": 1})}
    )
    cleaned = M.ad_scene_prompt(
        brief=current,
        kit=_kit(),
        brand="Bianki",
        mode=AdImageMode.BACKGROUND,
        products=1,
        has_background=False,
    )
    assert "✨" not in cleaned
    assert M.media_prompt_budget(current) == M.MEDIA_PROMPT_BUDGET == 2950
