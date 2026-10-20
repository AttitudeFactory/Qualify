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
import json

from qualify_creative.enums import (
    AvatarSource,
    ContentKind,
    EmojiPolicy,
    GenerationTask,
    SlideSource,
    SlideText,
)
from qualify_creative.providers import RenderedPrompt
from qualify_creative.schemas import (
    ADS_DESCRIPTION_MAX,
    ADS_HEADLINE_MAX,
    HOOK_MAX,
    PRINTED_CTA_MAX,
    PRINTED_HOOK_MAX,
    SCRIPT_MAX,
    BrandAccount,
    BrandContext,
    BrandKit,
    BrandVoiceProfile,
    ContentBrief,
    ToneAxes,
)

_NONE = "(none)"

#: Conversational Spanish is ~2.5 words per second; a script is sized to its target
#: length at a slightly slower pace so a presenter never has to rush it.
_SPOKEN_WORDS_PER_SECOND = 2.3

#: One angle per variant (§ request 2026-10-08). Every variant used to get the same
#: prompt and "take a distinct angle", blind to which variant it was — and the three
#: converged on one opening. Claude Opus 5.5 takes no `temperature`, so the variety has to
#: be asked for; each draft starts the rotation at its own offset.
VARIANT_ANGLES: tuple[str, ...] = (
    "lead with one concrete, sensory detail of the product",
    "a small everyday scene or a touch of humour the audience recognises",
    "open with a direct question to the audience",
    "urgency or the offer: why today, why now",
    "a first reaction, as if someone had just tried it",
)

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


def _context_section(context: BrandContext | None) -> tuple[str, ...]:
    """The business context (§ 2026-10-01) as one more standing section — none at all
    when there is nothing to say, so a brand without it renders exactly as before."""
    if context is None or context.is_empty:
        return ()
    lines = ["== Business context =="]
    if context.sector:
        lines.append(f"Business / sector: {context.sector}")
    if context.location:
        lines.append(f"Location: {context.location}. Local references are welcome when natural.")
    if context.account_category or context.account_bio:
        lines.append(
            f"The brand's own account: {context.account_category or _NONE}."
            f" Bio: {context.account_bio or _NONE}"
        )
    if context.hashtags:
        lines.append(
            "The brand's hashtags (pick the ones that fit and add ones specific to this"
            " piece's topic, within the hashtag limits): "
            + " ".join(f"#{tag}" for tag in context.hashtags)
        )
    if context.elements:
        lines.append(
            "Brandboard elements (reference them in scripts and visual directions when they"
            " fit; follow each one's usage note):"
        )
        lines.extend(
            f"- {e.name}: {e.context}" if e.context else f"- {e.name}" for e in context.elements
        )
    # § 2026-10-06: each sorted account with what the discovery learned about it, and
    # what to do with it — learn from it, stand apart from it, or stay away from it
    for accounts, heading in (
        (
            context.referentes,
            "Accounts the brand looks up to, most influential first. Learn from their tone,"
            " hooks and formats; never copy their lines, never name them:",
        ),
        (
            context.competitors,
            "Competitors. Stand apart from them — do not echo their offers, claims or"
            " slogans; never mention them, never compare against them by name:",
        ),
        (
            context.detractors,
            "Accounts the brand does NOT want to resemble. Avoid their tone, style and"
            " formats; never mention them:",
        ),
    ):
        if accounts:
            lines.append(heading)
            lines.extend(_account_line(account) for account in accounts)
    return ("\n".join(lines),)


def _account_line(account: BrandAccount) -> str:
    """`- @handle (network, kind): why. Operator's note: …. Their own words: «…»` — only
    the parts the discovery has, in a fixed order (the prefix is cached)."""
    head = f"- {account.handle} ({account.network}" + (
        f", {account.kind})" if account.kind else ")"
    )
    parts = [head + (f": {account.why}" if account.why else "")]
    if account.note:
        parts.append(f"Operator's note: {account.note}")
    if account.sample:
        parts.append(f"Their own words: «{account.sample}»")
    return " ".join(part if part.endswith((".", "»", "…", ")")) else part + "." for part in parts)


def _stable_prefix(
    kit: BrandKit, voice: BrandVoiceProfile, context: BrandContext | None = None
) -> str:
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
        "They show the voice; never reuse their sentences or their openings word for word.\n"
        "On-brand, write like this:\n" + _bullets(kit.do_examples) + "\n"
        "Off-brand, never write like this:\n" + _bullets(kit.dont_examples),
        "== Hard rules ==\n"
        f"Banned words, never use them: {_listing(kit.banned_words)}\n"
        f"Forbidden claims, never state or imply them: {_listing(kit.forbidden_claims)}\n"
        f"Emoji policy: {_EMOJI_GUIDANCE[kit.emoji_policy]}\n"
        f"Hashtags: use between {hashtag.minimum} and {hashtag.maximum} hashtags, mixing the"
        " brand's own with ones specific to the piece's topic."
        f" Always include: {_listing(hashtag.always)}. Never use: {_listing(hashtag.never)}\n"
        f"Caption length: between {lengths.caption_min_chars} and"
        f" {lengths.caption_max_chars} characters.",
        "== Calls to action ==\n"
        "Preferred CTA patterns — keep their intent, but word each CTA freshly; never copy a"
        f" pattern verbatim: {_listing(kit.cta_patterns)}",
        "== Visual identity ==\n"
        f"Palette (RGB): {_listing(kit.palette_rgb)}\n"
        # § 2026-10-06: whether the files exist, not their storage keys — the model
        # cannot open a key, it only cost tokens
        f"Logo: {'on file' if kit.logo_asset_key else _NONE}\n"
        f"Brand template: {'on file' if kit.template_asset_key else _NONE}\n"
        f"Reference images: {len(kit.reference_image_keys) or _NONE}\n"
        f"Allowed image routes: {allowed_routes or _NONE}\n"
        f"Blocked image routes: {blocked_routes}",
        *_context_section(context),
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


#: What each kind asks of the copy beyond the post itself (`ContentKind`).
_KIND_ASSIGNMENT: dict[ContentKind, str] = {
    ContentKind.CREATOR_SCRIPT: (
        "A real person from the brand will record this video. Write the script they"
        " will follow: `script` is everything they say, start to finish, in their own"
        " voice; `shots` breaks it into the shots to record — what the camera shows"
        " (`visual`), the line said over it (`line`) and its length (`seconds`)."
        " The hook is the first line said on camera."
    ),
    ContentKind.AVATAR_VIDEO: (
        "A generated presenter will read `script` aloud, word for word, in a vertical"
        " video. Write it to be spoken: short sentences, no emojis, no hashtags, no"
        " stage directions, numbers written the way they are said. Leave `shots` empty."
        " The hook is the first sentence of the script."
    ),
    ContentKind.ANIMATED_AVATAR_VIDEO: (
        "An animated character will read `script` aloud, word for word, in a vertical"
        " video. Write it to be spoken: short sentences, no emojis, no hashtags, no"
        " stage directions, numbers written the way they are said. Leave `shots` empty."
        " The hook is the first sentence of the script."
    ),
    ContentKind.STATIC_FLYER: (
        "This is a still image. The hook and the CTA are printed on it, so keep them"
        " short and punchy. Leave `script` empty and `shots` empty."
    ),
    ContentKind.TEMPLATE: (
        "A brand template composes the operator's real product photos into a vertical"
        " Reel and its feed and story stills. The hook and the CTA are printed on them, so"
        " keep them short and punchy. Leave `script` empty and `shots` empty."
    ),
    ContentKind.CLIP: (
        "This is a short generated advertising video that tells a story, with no"
        " presenter and no words on screen: the visuals carry it. Write its story in"
        " `shots`, exactly three beats: (1) the hook — the first seconds SHOW what your"
        " hook promises, so people stop scrolling; (2) the development — the product in"
        " action and what it gives, the key facts at work; (3) the payoff — the product"
        " as the hero, the moment that leads to your CTA. Each `visual` says what the"
        " camera shows (one or two sentences, concrete, no words on screen); `line`"
        " stays empty. The hook also opens the caption; the caption and the CTA carry"
        " the message. Leave `script` empty."
    ),
    ContentKind.CAROUSEL: (
        "This is a feed carousel: several slides — images and short silent videos — the"
        " viewer swipes through. The hook and the CTA are printed on the slides the"
        " operator chose, so keep them short and punchy; the caption carries the rest."
        " Leave `script` empty and `shots` empty."
    ),
}


def _on_screen(brief: ContentBrief) -> tuple[str, ...]:
    """What the viewer will SEE while the words play (§ 2026-10-06: a video got less to
    go on than a creator's script) — the presenter and the images the operator gave, so
    the script can refer to them instead of being written blind. Nothing for a kind
    whose visuals the copy does not share the screen with."""
    media = brief.media
    seen: list[str] = []
    if brief.kind is ContentKind.AVATAR_VIDEO:
        seen.append(
            "a generated photoreal presenter described as «" + media.avatar_prompt.strip() + "»"
            if media.avatar_source is AvatarSource.AI and media.avatar_prompt.strip()
            else "a photoreal presenter from the video library"
        )
    elif brief.kind is ContentKind.ANIMATED_AVATAR_VIDEO:
        if media.avatar_source is AvatarSource.IMAGE:
            seen.append("an animated character made from the operator's own image")
        else:
            seen.append(
                "an animated character described as «" + media.avatar_prompt.strip() + "»"
                if media.avatar_prompt.strip()
                else "an animated character"
            )
    if brief.kind.is_video:
        if media.background_key:
            seen.append("behind it, the operator's own background image (e.g. their venue)")
        if media.product_keys:
            seen.append(
                f"{len(media.product_keys)} photo(s) of the product composed into the scene"
            )
    elif brief.kind is ContentKind.TEMPLATE and media.product_keys:
        seen.append(f"{len(media.product_keys)} real photo(s) of the product")
    elif brief.kind is ContentKind.CAROUSEL:
        seen.extend(_carousel_slides(brief))
    if not seen:
        return ()
    return ("On screen: " + "; ".join(seen) + ". Write so the words fit what is shown.",)


def _carousel_slides(brief: ContentBrief) -> list[str]:
    """One line per carousel slide, in order: what it shows and what is printed on it."""
    lines: list[str] = []
    slides = brief.media.slides
    total = len(slides) + int(brief.media.closing_slide)
    for number, slide in enumerate(slides, start=1):
        what = {
            SlideSource.GENERATED: "a generated image",
            SlideSource.ANIMATED: "a short silent video",
            SlideSource.EXISTING: "an image or video the brand already made",
            SlideSource.STOCK: "a stock video with the brand's words over it",
        }[slide.source]
        scene = slide.scene_prompt.strip()
        text = {SlideText.HOOK: ", the hook printed on it", SlideText.CTA: ", the CTA on it"}.get(
            slide.text, ""
        )
        lines.append(f"slide {number}/{total}: {what}" + (f" of «{scene}»" if scene else "") + text)
    if brief.media.closing_slide:
        lines.append(f"slide {total}/{total}: the CTA, large, on the brand's colours")
    return lines


#: The kinds whose hook and CTA are printed on an image (§ request 2026-10-08).
_PRINTED_KINDS = frozenset({ContentKind.STATIC_FLYER, ContentKind.TEMPLATE, ContentKind.CAROUSEL})


def printed_limits(kind: ContentKind) -> dict[str, int]:
    """The character limits the prompt asks for on a kind whose hook and CTA are printed
    on an image — the same numbers the copy adapter holds the answer to (2026-10-13: a
    model is only ASKED for them; structured outputs cannot carry `maxLength`). Empty for
    a kind whose words are not printed."""
    if kind in _PRINTED_KINDS:
        return {"hook": PRINTED_HOOK_MAX, "cta": PRINTED_CTA_MAX}
    return {}


#: What the piece does with the logo it was given, per kind — the brand mark's place.
_LOGO_PLACEMENT: dict[ContentKind, str] = {
    ContentKind.AVATAR_VIDEO: "it is shown in a corner of the video, behind the presenter",
    ContentKind.ANIMATED_AVATAR_VIDEO: "it is shown in a corner of the video, behind the character",
    ContentKind.STATIC_FLYER: "it is printed on the image",
    ContentKind.TEMPLATE: "the template places it where the brand mark goes",
    ContentKind.CAROUSEL: "it is printed in a corner of the generated slides",
    ContentKind.CLIP: "it is not printed: a clip shows only what its frames and references show",
    ContentKind.CREATOR_SCRIPT: "show it on camera where it fits (packaging, the counter, a sign)",
}


def _chosen_resources(brief: ContentBrief, context: BrandContext | None) -> tuple[str, ...]:
    """The Brand Kit resources the operator chose for THIS piece (§ request 2026-10-06),
    with each one's usage note: the logo in the brand mark's place, every other element
    used as its note says. A key the context does not know (deleted since) is skipped."""
    media = brief.media
    if not (media.brand_logo_key or media.brand_element_keys) or context is None:
        return ()
    by_key = {element.key: element for element in context.elements if element.key}
    lines: list[str] = []
    logo = by_key.get(media.brand_logo_key or "")
    if logo is not None:
        note = f" Usage note: {logo.context}." if logo.context else ""
        lines.append(f"- Logo «{logo.name}»: {_LOGO_PLACEMENT[brief.kind]}.{note}")
    for key in media.brand_element_keys:
        element = by_key.get(key)
        if element is None:
            continue
        note = element.context or "no usage note: use it where it naturally fits"
        lines.append(f"- «{element.name}» — {note}")
    if not lines:
        return ()
    return (
        "Brand resources chosen for this piece — use each one as its note says; refer to"
        " them in the script and visual directions where they fit:",
        *lines,
    )


def variant_angle(variant: int, offset: int = 0) -> str:
    """The angle of `variant` (0-based) for a draft whose rotation starts at `offset`."""
    return VARIANT_ANGLES[(offset + variant) % len(VARIANT_ANGLES)]


def _variant_lines(brief: ContentBrief, variant: int | None, angle_offset: int) -> tuple[str, ...]:
    """One option asks for no angle (§ 2026-10-06, videos). Several, with a known
    variant, get that variant's own angle; without one (the preview of the brief as a
    whole) only the count."""
    count = brief.variants_requested
    if count <= 1:
        return ()
    if variant is None:
        return (f"This is one of {count} variants: take a distinct angle on the assignment.",)
    return (
        f"This is variant {variant + 1} of {count}. Its angle:"
        f" {variant_angle(variant, angle_offset)}. The other variants take other angles, so"
        " commit to this one: its own opening, its own wording, its own CTA.",
    )


def _recent_lines(recent: tuple[str, ...]) -> tuple[str, ...]:
    """What the brand already published or drafted lately (§ request 2026-10-08): every
    draft used to open with the same line, copied from the writing examples."""
    if not recent:
        return ()
    return (
        "Openings and CTAs this brand used recently. Do not start or close this piece the"
        " same way, and do not reuse their wording:",
        *(f"- {line}" for line in recent),
    )


def _volatile_suffix(
    brief: ContentBrief,
    task: GenerationTask,
    context: BrandContext | None = None,
    *,
    variant: int | None = None,
    angle_offset: int = 0,
    recent: tuple[str, ...] = (),
) -> str:
    constraints = brief.constraints
    width, height = brief.format.dimensions
    max_chars = (
        str(constraints.max_caption_chars)
        if constraints.max_caption_chars is not None
        else "(brand default)"
    )
    field_lines = list(_COPY_FIELD_LINES)
    if brief.kind in _PRINTED_KINDS:
        # the hook and the CTA are printed on the image: a number to aim at, no emoji
        field_lines[0] = (
            f"- hook: string, at most {PRINTED_HOOK_MAX} characters, printed on the image, no emoji"
        )
        field_lines[3] = (
            f"- cta: string, at most {PRINTED_CTA_MAX} characters, printed on the image, no emoji"
        )
    own_script = brief.media.own_script.strip()
    if own_script:
        field_lines.append("- script: string, EXACTLY the operator's script below, word for word")
    elif brief.kind.has_script:
        words = round(brief.media.duration_seconds * _SPOKEN_WORDS_PER_SECOND)
        field_lines.append(
            f"- script: string, the spoken text, about {words} words"
            f" (~{brief.media.duration_seconds} seconds), at most {SCRIPT_MAX} characters"
        )
    else:
        field_lines.append("- script: string, empty for this piece")
    if brief.kind is ContentKind.CREATOR_SCRIPT:
        field_lines.append(
            "- shots: array of objects {visual: string, line: string, seconds: integer},"
            f" their seconds adding up to about {brief.media.duration_seconds}"
        )
    elif brief.kind is ContentKind.CLIP:
        field_lines.append(
            '- shots: array of exactly 3 objects {visual: string, line: "", seconds:'
            " integer} — the hook, the development, the payoff — their seconds adding up"
            f" to {brief.media.duration_seconds}"
        )
    else:
        field_lines.append("- shots: array, empty for this piece")
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
        # § 2026-10-06: the operator describes the whole piece in their own words, not
        # just a topic or a product name
        f"What the operator wants (their own words, the piece's general context): {brief.topic}",
        f"Product reference: {brief.product_ref or _NONE}",
        f"Platform: {brief.platform.value}",
        f"Format: {brief.format.value} ({width}x{height})",
        f"Intent: {brief.intent.value}",
        f"Image route: {brief.image_route.value}",
        f"Piece kind: {brief.kind.value}. {_KIND_ASSIGNMENT[brief.kind]}",
        *_on_screen(brief),
        *_chosen_resources(brief, context),
        *(
            (
                "The operator wrote the script themselves. Do not rewrite it: copy it"
                " into `script` word for word, and write the hook, caption and CTA of"
                f" the post to match it. Operator's script: «{own_script}»",
            )
            if own_script
            else ()
        ),
        *_recent_lines(recent),
        f"Must mention: {_listing(constraints.must_mention)}",
        f"Must avoid: {_listing(constraints.must_avoid)}",
        *(
            (
                "Key facts to feature, as JSON (the operator's own data, «Datos clave»):"
                " state each value exactly as written — never change, round or invent one: "
                + json.dumps(dict(constraints.highlights), ensure_ascii=False),
            )
            if constraints.highlights
            else ()
        ),
        f"Maximum caption characters for this piece: {max_chars}",
        "",
        "== Output ==",
        # One call per variant (`ContentService._generate`): each answer is ONE object.
        "Return only one JSON object, with no prose before or after it. It has exactly"
        " these fields:",
        *field_lines,
        ads_note,
        *_variant_lines(brief, variant, angle_offset),
    )
    return "\n".join(lines) + "\n"


def render_prompt(
    *,
    kit: BrandKit,
    voice: BrandVoiceProfile,
    brief: ContentBrief,
    task: GenerationTask,
    context: BrandContext | None = None,
    variant: int | None = None,
    angle_offset: int = 0,
    recent: tuple[str, ...] = (),
) -> RenderedPrompt:
    """Deterministic: the same (kit, voice, brief, task) renders the same bytes, always.

    `variant` (0-based) gives that variant its own angle, rotated from `angle_offset`;
    `recent` lists the brand's recent openings and CTAs not to repeat. Both ride the
    suffix only, so every variant still shares the cached prefix.

    The stable prefix depends only on (kit, voice); briefs of the same pair share it
    byte for byte, which is what lets it take the prompt-cache breakpoint. The suffix
    carries the brief and the output instructions. `prefix_fingerprint` is the sha256 of
    the prefix, so a cache miss can be traced to the exact field that moved.
    """
    prefix = _stable_prefix(kit, voice, context)
    suffix = _volatile_suffix(
        brief, task, context, variant=variant, angle_offset=angle_offset, recent=recent
    )
    fingerprint = hashlib.sha256(prefix.encode("utf-8")).hexdigest()
    return RenderedPrompt(
        stable_prefix=prefix,
        volatile_suffix=suffix,
        prefix_fingerprint=fingerprint,
    )
