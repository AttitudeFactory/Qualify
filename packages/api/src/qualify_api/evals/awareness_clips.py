"""The awareness level in clips and video by parts (m-25026509, NIVELES-004) — the pure
half of `packages/api/evals/niveles_consciencia/` for the Clip flow.

A clip brief is built the way the app builds it: `CreativeState._generator_form` (the
owner's sentence as the topic, the product, its «Precio» key fact, kind clip, the clip's
media) through `clip_brief`, a mirror of `Qualify.creative_provider.build_brief` (a test
pins that they agree). The copy is the production copy adapter's (`copy_quality.generate`)
and the parts proposal is `parts_ai.propose_parts` with `PartsBrief.awareness_level` —
the path the app takes, not a `CreativeAngle`.

Deterministic checks here: `clip_text` (what a clip's copy says, shots included),
`quotes_price` (the price, or any amount, in it), `filmable_shot` (a shot still
describes something a camera can show, not a slogan), `caption_words`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_creative.angles import AngleBrand, AngleProduct, price_mentions
from qualify_creative.enums import (
    AwarenessLevel,
    BriefIntent,
    BriefObjective,
    ContentFormat,
    ContentKind,
    ContentType,
    ImageRoute,
    objective_for_level,
)
from qualify_creative.schemas import BriefConstraints, ContentBrief, MediaInputs, quotes_money

#: The screen's objective for a clip when the owner picks no reader.
DEFAULT_OBJECTIVE = "consideration"
#: A catalog photo key shaped like the app's (no file is read: copy only).
_PHOTO = "uploads/00000000-0000-0000-0000-000000000001/catalog/{product}/foto-1.jpg"

#: NIVELES-004, written before judging clips: what the judge reads for a clip.
JUDGE_CLIP_VERSION = "juez-niveles-v4+clip-v2"
JUDGE_CLIP_ADDENDUM = """
Estas ideas son CLIPS cortos sin presentador ni voz: no hay guion hablado. Juzga el \
gancho, el texto de la publicación (caption), la llamada a la acción y las TRES TOMAS (lo \
que muestra la cámara). Las tomas no llevan texto en pantalla. Para el nivel cuenta todo \
lo que el cliente ve o lee; most_aware se juzga con la medida de su regla.
"""


def _split_commas(text: str) -> tuple[str, ...]:
    """`creative_provider._split_commas`: «a, b» → ("a", "b"), blanks dropped."""
    return tuple(part.strip() for part in (text or "").split(",") if part.strip())


def clip_form(
    case: Mapping[str, Any], level: str | None, *, sentence: str | None = None
) -> dict[str, Any]:
    """The form the Clip flow submits for `case` (a brand of `cases_clips.json`) with the
    owner's answer `level` ("" or None = «Sin preferencia»). The «Precio» key fact is
    there as the screen pre-fills it; for an unaware clip the screen hides that row and
    the brief strips it anyway — keeping it here tests the brief's own guard."""
    product = case["product"]
    photo = _PHOTO.format(product=re.sub(r"\W+", "-", product["name"].lower()))
    return {
        "objective": objective_for_level(level, DEFAULT_OBJECTIVE),
        "awareness_level": level or None,
        "content_type": ContentType.PRODUCT.value,
        "topic": sentence if sentence is not None else case["sentence"],
        "product_ref": product["name"],
        "intent": BriefIntent.ORGANIC.value,
        "image_route": "",
        "source_media_key": "",
        "must_mention": "",
        "must_avoid": "",
        "highlights": [("Precio", product["price_label"])] if product.get("price_label") else [],
        "kind": ContentKind.CLIP.value,
        "media": {
            "duration_seconds": 5,
            "clip_audio": True,
            "clip_subtitles": False,
            "clip_image_keys": [photo],
            "clip_image_roles": ["product"],
            "clip_video_keys": [],
            "clip_reference_mode": "motion",
            "product_source": "catalog",
            "brand_logo_in_scene": True,
        },
        "content_format": "",
        "variants_requested": 1,
    }


def clip_brief(brand_id: UUID, **form: Any) -> ContentBrief:
    """`Qualify.creative_provider.build_brief`, mirrored (the test
    `test_clip_brief_matches_the_app` pins them together)."""
    kind = ContentKind(form["kind"])
    inputs = MediaInputs.model_validate(dict(form.get("media") or {}))
    image_route, source = form.get("image_route", ""), form.get("source_media_key", "")
    own = [key for key in (*inputs.product_keys, inputs.background_key) if key]
    if kind is not ContentKind.STATIC_FLYER or image_route == "":
        image_route = ImageRoute.FROM_UPLOAD.value if own else ImageRoute.TEMPLATE_ONLY.value
        source = own[0] if own else ""
    level = form.get("awareness_level")
    return ContentBrief(
        brand_id=brand_id,
        objective=BriefObjective(form["objective"]),
        content_type=ContentType(form["content_type"]),
        topic=str(form["topic"]).strip(),
        product_ref=str(form["product_ref"]).strip() or None,
        intent=BriefIntent(form["intent"]),
        image_route=ImageRoute(image_route),
        source_media_key=source or None,
        constraints=BriefConstraints(
            must_mention=_split_commas(form.get("must_mention", "")),
            must_avoid=_split_commas(form.get("must_avoid", "")),
            highlights=tuple((str(n), str(f)) for n, f in form.get("highlights", ())),
        ),
        variants_requested=int(form.get("variants_requested", 1)),
        kind=kind,
        media=inputs,
        format=ContentFormat(form["content_format"])
        if form.get("content_format")
        else kind.default_format,
        awareness_level=AwarenessLevel(level) if level else None,
    )


def load_clip_cases(path: Path, copy_cases: Path) -> dict[str, Any]:
    """`cases_clips.json` with each brand's kit and voice resolved (`kit_from` names a
    brand of `copy_ai/cases.json`) and its perks set on the kit."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    base = json.loads(copy_cases.read_text(encoding="utf-8"))["brands"]
    for brand in raw["brands"].values():
        if "kit_from" in brand:
            source = base[brand["kit_from"].split("/", 1)[1]]
            brand["kit"], brand["voice"] = dict(source["kit"]), source["voice"]
        brand["kit"] = {**brand["kit"], "business_perks": list(brand["perks"])}
    return raw


def parts_inputs(brand: Mapping[str, Any]) -> tuple[AngleBrand, AngleProduct]:
    """The `PartsBrief` brand (with the kit's perks, as the app passes them) and product."""
    product = brand["product"]
    return (
        AngleBrand(**brand["parts_brand"], perks=tuple(brand["perks"])),
        AngleProduct(
            product_id=UUID(int=0),
            name=product["name"],
            description=product["description"],
            photo_keys=("foto-1", "foto-2"),
        ),
    )


# -- deterministic checks ----------------------------------------------------------------


def clip_text(payload: Mapping[str, Any]) -> str:
    """Everything a clip's copy says: hook, caption, CTA and each shot's visual."""
    shots = [str((s or {}).get("visual", "")) for s in payload.get("shots") or ()]
    return "\n".join([*(str(payload.get(k, "") or "") for k in ("hook", "caption", "cta")), *shots])


def quotes_price(text: str, price_label: str = "") -> bool:
    """A price in `text`: the catalog's label or its figure, or any amount of money."""
    if quotes_money(text) or price_mentions(text):
        return True
    digits = re.sub(r"\D", "", price_label)
    return bool(digits) and digits in re.sub(r"[.,\s]", "", text)


_SLOGAN = re.compile(r"[¡!¿?«»\"“”]|\b(?:texto|letrero|letras|dice|subt[ií]tulo)\b", re.I)


def filmable_shot(visual: str) -> bool:
    """A shot a camera can film: at least six words, no exclamation, question or quoted
    words, and nothing written on screen (the clip prompt forbids words on screen)."""
    return len(re.findall(r"[^\W\d_]+", visual or "")) >= 6 and not _SLOGAN.search(visual or "")


def shots_ok(payload: Mapping[str, Any]) -> tuple[bool, int]:
    """(exactly three shots, how many of them are filmable)."""
    shots = [str((s or {}).get("visual", "")) for s in payload.get("shots") or ()]
    return len(shots) == 3, sum(filmable_shot(v) for v in shots)


def caption_words(payload: Mapping[str, Any]) -> int:
    return len(re.findall(r"[^\W\d_]+", str(payload.get("caption", "") or "")))


#: NIVELES-005: most_aware's measures with slack («about 6 / 5 / 25 words»).
MOST_HOOK_WORDS, MOST_CTA_WORDS, MOST_CAPTION_WORDS = 8, 7, 35


def most_aware_measure(payload: Mapping[str, Any]) -> bool:
    """Hook ≤ 8 words, CTA ≤ 7 and caption ≤ 35: the most_aware measure, with slack."""

    def count(key: str) -> int:
        return len(re.findall(r"[^\W\d_]+", str(payload.get(key, "") or "")))

    return (
        count("hook") <= MOST_HOOK_WORDS
        and count("cta") <= MOST_CTA_WORDS
        and count("caption") <= MOST_CAPTION_WORDS
    )


#: NIVELES-006: the ways to buy a caption can name, by channel (one channel = one way).
_BUY_WAYS: dict[str, re.Pattern[str]] = {
    "whatsapp": re.compile(r"whatsapp|wasap|wpp", re.I),
    "rappi": re.compile(r"\brappi\b", re.I),
    "domicilio": re.compile(r"\bdomicilio", re.I),
    "dm": re.compile(r"\b(?:dm|mensaje directo|inbox)\b", re.I),
    "web": re.compile(r"\b(?:web|p[aá]gina|link|enlace)\b", re.I),
    "llamada": re.compile(r"\bll[aá]m(?:a|anos|ar)\b", re.I),
    "local": re.compile(
        r"\b(?:local|tienda|sede|ven|v[eé]nganse|c[aá][eé]le|ca[eé]|pasa por)\b", re.I
    ),
}


def ways_to_buy(text: str) -> list[str]:
    """The distinct channels `text` offers to buy through."""
    return [name for name, pattern in _BUY_WAYS.items() if pattern.search(text or "")]


def asks_question(text: str) -> bool:
    return "?" in (text or "") or "¿" in (text or "")


def mentions_all(text: str, must_mention: Sequence[str]) -> bool:
    """Every «Debe mencionar» entry appears (case and accents ignored)."""
    from qualify_api.evals.awareness_levels import fold  # noqa: PLC0415 — levels imports us

    folded = fold(text)
    return all(fold(item) in folded for item in must_mention if item.strip())


#: A perk that is part of «how to buy» for most_aware (NIVELES-006): a way to order, an
#: opening hour or the place — not «another perk».
_BUY_PERK = re.compile(
    r"whatsapp|rappi|domicilio|pedido|reserva|abiert|horario|hasta las|\d\s*[ap]\.?\s?m"
    r"|\blocal en\b|\bcalle\b|\bcarrera\b|\ben la \d+",
    re.I,
)


def is_buy_perk(perk: str) -> bool:
    return bool(_BUY_PERK.search(perk or ""))


def most_checks(
    payload: Mapping[str, Any],
    perks: Sequence[str],
    sources: str,
    must_mention: Sequence[str] = (),
    price_label: str = "",
) -> dict[str, Any]:
    """The deterministic reading of a most_aware copy against rubric v4: what its caption
    adds beyond product, price and how to buy, and what is missing. `ok` = all pass."""
    from qualify_api.evals import awareness_levels as al  # noqa: PLC0415 — levels imports us

    caption = str(payload.get("caption", "") or "")
    said = "\n".join(str(payload.get(k, "") or "") for k in ("hook", "caption", "cta"))
    asked = {i for i, p in enumerate(perks, 1) if al.perks_used(" ".join(must_mention), [p])}
    extra = [
        perks[i - 1]
        for i in al.perks_used(caption, perks)
        if not is_buy_perk(perks[i - 1]) and i not in asked
    ]
    ways = ways_to_buy(said)
    invented_ways = [w for w in ways if w not in ("local",) and w not in ways_to_buy(sources)]
    invented_hours = [m for k, m in al.invented_facts(said, sources) if k == "horario"]
    result = {
        "extra_perks": extra,
        "question": asks_question(caption),
        "ways": ways,
        "invented_ways": invented_ways,
        "invented_hours": invented_hours,
        "price_present": quotes_price(said, price_label) if price_label else None,
        "must_mention_ok": mentions_all(said, must_mention),
        "measure": most_aware_measure(payload),
    }
    result["ok"] = (
        not extra
        and not result["question"]
        and 1 <= len(ways) <= 2
        and not invented_ways
        and not invented_hours
        and result["price_present"] is not False
        and result["must_mention_ok"]
    )
    return result


def judge_ideas(payload: Mapping[str, Any], level: str | None) -> list[dict[str, str]]:
    """The clip as the judge reads it (one idea)."""
    shots = [str((s or {}).get("visual", "")) for s in payload.get("shots") or ()]
    return [
        {
            "gancho": str(payload.get("hook", "")),
            "texto": str(payload.get("caption", "")),
            "cta": str(payload.get("cta", "")),
            "tomas": " | ".join(shots),
            "nivel": level or "",
        }
    ]


def levels_with_none() -> Sequence[str | None]:
    """The arms: «Sin preferencia» (baseline) then the five readers."""
    return (None, *(level.value for level in AwarenessLevel))


__all__ = [
    "JUDGE_CLIP_ADDENDUM",
    "JUDGE_CLIP_VERSION",
    "caption_words",
    "clip_brief",
    "clip_form",
    "clip_text",
    "filmable_shot",
    "asks_question",
    "judge_ideas",
    "mentions_all",
    "ways_to_buy",
    "levels_with_none",
    "load_clip_cases",
    "is_buy_perk",
    "most_aware_measure",
    "most_checks",
    "parts_inputs",
    "quotes_price",
    "shots_ok",
]
