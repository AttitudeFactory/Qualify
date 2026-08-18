"""Deterministic prompt render for the copy layer (MC-08).

The economics of this module live in one property: the brand kit and the active voice
profile serialize to a byte-identical *stable prefix* for every generation of the same
(kit, voice) pair, so the prefix can take the prompt-cache breakpoint and repeated calls
read it at cache price (~0.1x). The brief is the only volatile part and always comes
last. Nothing in the prefix may depend on the clock, a request id, the locale or
unsorted iteration — `prefix_fingerprint` exists so a test (and a monitor) can prove
that instead of trusting it.

Serialization rules, applied everywhere in the prefix:
- fixed section order and fixed wording;
- tuples render in their declared order (that order is part of the kit's meaning);
- sets and mappings render sorted by key;
- `distilled_at` is deliberately never rendered — it is a timestamp, and one timestamp
  in the prefix silently invalidates the cache on every re-distillation replay;
- no uuid appears beyond `brand_id`, which is stable per brand by definition.

Design: `docs/diseno-motor-contenido-marca.md` sections 4.2 and 2.1 (caching
restriction); backlog MC-08.
"""

from __future__ import annotations

import hashlib

from qualify_creative.enums import EmojiPolicy, GenerationTask
from qualify_creative.providers import RenderedPrompt
from qualify_creative.schemas import (
    ADS_DESCRIPTION_MAX,
    ADS_HEADLINE_MAX,
    HOOK_MAX,
    BrandKit,
    BrandVoiceProfile,
    ContentBrief,
    ToneAxes,
)

_NONE = "(none)"

_EMOJI_GUIDANCE: dict[EmojiPolicy, str] = {
    EmojiPolicy.NONE: "none — do not use any emoji",
    EmojiPolicy.SPARSE: "sparse — at most 3 emoji, and only where one adds meaning",
    EmojiPolicy.FREE: "free — use emoji wherever the tone calls for them",
}


def _listing(items: tuple[str, ...]) -> str:
    """Inline listing; empty collections render explicitly so removing the last item
    still changes the bytes."""
    return "; ".join(items) if items else _NONE


def _bullets(items: tuple[str, ...]) -> str:
    if not items:
        return f"- {_NONE}"
    return "\n".join(f"- {item}" for item in items)


def _tone_lines(axes: ToneAxes) -> str:
    return "\n".join(
        (
            f"- formal (0) to casual (100): {axes.formal_casual}",
            f"- sober (0) to enthusiastic (100): {axes.sober_enthusiastic}",
            f"- technical (0) to plain (100): {axes.technical_plain}",
            f"- brief (0) to elaborate (100): {axes.brief_elaborate}",
        )
    )


def _stable_prefix(kit: BrandKit, voice: BrandVoiceProfile) -> str:
    hashtag = kit.hashtag_policy
    lengths = kit.length_targets
    image = kit.image_policy
    allowed_routes = ", ".join(sorted(route.value for route in image.allowed_routes))
    blocked_routes = (
        "; ".join(
            f"{route.value}: {reason}" for route, reason in sorted(image.blocked_reason.items())
        )
        or _NONE
    )
    sources = (
        "\n".join(
            f"- {source.kind.value} [{source.ref}]: {source.excerpt}" for source in voice.sources
        )
        or f"- {_NONE}"
    )
    sections = (
        "You write social media copy as the brand described below. Everything in this"
        " briefing is the brand's standing identity; the specific assignment comes at the end.",
        "== Brand ==\n"
        f"Brand id: {kit.brand_id}\n"
        f"Positioning: {kit.positioning}\n"
        f"Audience: {kit.audience}\n"
        f"Language: {kit.language}\n"
        f"Regional variant: {kit.regional_variant}. Write natively in this variant: match its"
        " register, its vocabulary and its forms of address, and do not drift into a neutral"
        " or foreign variant.",
        "== Declared tone targets (0-100) ==\n"
        "Hit each axis as a numeric target, not a vague direction:\n" + _tone_lines(kit.tone_axes),
        "== Voice profile ==\n"
        f"Version: {voice.version} (status: {voice.status.value})\n"
        f"Distilled by model: {voice.distilled_by_model or _NONE}\n"
        "Distilled tone targets (0-100):\n" + _tone_lines(voice.tone_axes) + "\n"
        f"Preferred lexicon, use where natural: {_listing(voice.lexicon)}\n"
        f"Avoid this lexicon: {_listing(voice.avoid_lexicon)}\n"
        f"Sentence rhythm: {voice.sentence_rhythm or _NONE}\n"
        f"Signature moves: {_listing(voice.signature_moves)}\n"
        "Evidence the profile was distilled from:\n" + sources,
        "== Writing examples ==\n"
        "On-brand, write like this:\n" + _bullets(kit.do_examples) + "\n"
        "Off-brand, never write like this:\n" + _bullets(kit.dont_examples),
        "== Hard rules ==\n"
        f"Banned words, never use them: {_listing(kit.banned_words)}\n"
        f"Forbidden claims, never state or imply them: {_listing(kit.forbidden_claims)}\n"
        f"Emoji policy: {_EMOJI_GUIDANCE[kit.emoji_policy]}\n"
        f"Hashtags: use between {hashtag.minimum} and {hashtag.maximum} hashtags."
        f" Always include: {_listing(hashtag.always)}. Never use: {_listing(hashtag.never)}\n"
        f"Caption length: between {lengths.caption_min_chars} and"
        f" {lengths.caption_max_chars} characters.",
        f"== Calls to action ==\nPreferred CTA patterns: {_listing(kit.cta_patterns)}",
        "== Visual identity ==\n"
        f"Palette (RGB): {_listing(kit.palette_rgb)}\n"
        f"Logo asset: {kit.logo_asset_key or _NONE}\n"
        f"Template asset: {kit.template_asset_key or _NONE}\n"
        f"Reference images: {_listing(kit.reference_image_keys)}\n"
        f"Allowed image routes: {allowed_routes or _NONE}\n"
        f"Blocked image routes: {blocked_routes}",
    )
    return "\n\n".join(sections) + "\n"


_COPY_FIELD_LINES: tuple[str, ...] = (
    f"- hook: string, at most {HOOK_MAX} characters, the first line that stops the scroll",
    "- caption: string, the body of the piece",
    "- hashtags: array of strings, each without the leading #",
    "- cta: string, the closing call to action",
)

_ADS_FIELD_LINES: tuple[str, ...] = (
    "- ads_primary_text: string, the primary text slot of the ad",
    f"- ads_headline: string, at most {ADS_HEADLINE_MAX} characters",
    f"- ads_description: string, at most {ADS_DESCRIPTION_MAX} characters",
    "- ads_cta_type: string, the call-to-action button type",
)


def _volatile_suffix(brief: ContentBrief, task: GenerationTask) -> str:
    constraints = brief.constraints
    width, height = brief.format.dimensions
    max_chars = (
        str(constraints.max_caption_chars)
        if constraints.max_caption_chars is not None
        else "(brand default)"
    )
    field_lines = list(_COPY_FIELD_LINES)
    if brief.intent.includes_ads:
        field_lines.extend(_ADS_FIELD_LINES)
        ads_note = "This piece will run as an ad: fill every ads_* field."
    else:
        ads_note = "This piece is organic only: do not include any ads_* field."
    lines = (
        "== Assignment ==",
        f"Task: {task.value}",
        f"Objective: {brief.objective.value}",
        f"Content type: {brief.content_type.value}",
        f"Topic: {brief.topic}",
        f"Product reference: {brief.product_ref or _NONE}",
        f"Platform: {brief.platform.value}",
        f"Format: {brief.format.value} ({width}x{height})",
        f"Intent: {brief.intent.value}",
        f"Image route: {brief.image_route.value}",
        f"Must mention: {_listing(constraints.must_mention)}",
        f"Must avoid: {_listing(constraints.must_avoid)}",
        f"Maximum caption characters for this piece: {max_chars}",
        f"Variants requested: {brief.variants_requested}",
        "",
        "== Output ==",
        f"Return only a JSON array of exactly {brief.variants_requested} variant objects,"
        " with no prose before or after it. Each object has exactly these fields:",
        *field_lines,
        ads_note,
        "Each variant takes a distinctly different angle on the same assignment.",
    )
    return "\n".join(lines) + "\n"


def render_prompt(
    *,
    kit: BrandKit,
    voice: BrandVoiceProfile,
    brief: ContentBrief,
    task: GenerationTask,
) -> RenderedPrompt:
    """Deterministic: the same (kit, voice, brief, task) renders the same bytes, always.

    The stable prefix depends only on (kit, voice); briefs of the same pair share it
    byte for byte, which is what lets it take the prompt-cache breakpoint. The suffix
    carries the brief and the output instructions. `prefix_fingerprint` is the sha256 of
    the prefix, so a cache miss can be traced to the exact field that moved.
    """
    prefix = _stable_prefix(kit, voice)
    suffix = _volatile_suffix(brief, task)
    fingerprint = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
    return RenderedPrompt(
        stable_prefix=prefix,
        volatile_suffix=suffix,
        prefix_fingerprint=fingerprint,
    )
