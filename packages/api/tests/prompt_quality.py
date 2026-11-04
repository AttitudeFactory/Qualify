"""The «no quality loss» guard of a compiled edit-clip prompt (m-24820842, 2026-11-02).

Founder's condition: shortening a prompt may remove genuine duplication, never intent. This
helper checks a FINAL prompt (after `_budgeted`) against the inputs it was compiled from, and
is deliberately written without the compiler's own helpers — only PARTLY independent: it
reuses the screen's template recognizer (`known_replication_prose`) and the declared coverage
table (`REPLICATION_PROSE_V1_COVERAGE`), which are the contract it checks against. It
checks: the operator's text and the product literal (the current `product_ref`, else the
guidance's), the Brand Kit CTAs verbatim when `replication_brand_text` is on, every
resource with its real index, alias/label/role and usage note, the palette hexes, the
typefaces, the key facts, the brand identity WHOLE (founder, 2026-11-02: nothing is trimmed
on Seedance 2.x), the replication guidance (verbatim, or covered sentence by sentence), no
duplicated sentence, nothing reported as trimmed, and the length within the character budget
— or, with none (`budget=None`, Seedance 2.x), within the documented 1,000 words.

Design: `docs/modelos-generativos/diagnostico-presupuesto-prompt-20261102.md` §8.

Since prompt compiler 2 (2026-11-03) the functions above guard the FROZEN compiler-0/1
prompts (their wording is the contract a frozen draft was paid with); a compiler-2 prompt is
checked by `assert_video_prompt_v2_quality` at the end of this module, which protects
quality instead of wording (audit `auditoria-prompts-clip-20261103.md` §5).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from qualify_creative.prompt_text import (
    REEL_METADATA_MARKER,
    REPLICATION_COVERAGE_NEEDS_PRODUCT_PHOTO,
    REPLICATION_MARKER,
    REPLICATION_PROSE_V1_COVERAGE,
    REPLICATION_PROSE_V2_COVERAGE,
    known_replication_prose,
    visual_text,
)
from qualify_creative.schemas import BrandKit, ContentBrief

from qualify_api.creative.brand_references import BrandReference, BrandReferenceRole

_LOGO_KINDS = {"logo", "logo_version"}
#: The documented Seedance recommendation, the ceiling of a prompt with no character budget.
_MAX_WORDS = 1000
_FACTS_MAX = 500


def _plain(text: str) -> str:
    """A text as the compiler quotes it: emoji removed, stripped, double quotes → single."""
    return " ".join(visual_text(text).strip().replace('"', "'").split())


def _split_topic(brief: ContentBrief) -> tuple[str, str]:
    """(operator words, the screen's replication context) — read here independently."""
    operator, marker, context = brief.topic.partition(REPLICATION_MARKER)
    if not marker:
        prose = brief.topic.strip().partition(REEL_METADATA_MARKER)[0]
        if known_replication_prose(prose) is not None:
            return "", brief.topic.strip()
        return brief.topic, ""
    return operator, context


def _sentences(prompt: str) -> list[str]:
    """Sentences over 40 characters, their numbers masked: the same sentence with another
    image index (`@Image1: X.` / `@Image2: X.`) is a duplicate too (round 7b)."""
    return [
        re.sub(r"\d+", "N", s.strip())
        for s in re.split(r"(?<=[.!?])\s+", prompt)
        if len(s.strip()) > 40 and "#" not in s
    ]


def assert_prompt_keeps_intent(
    prompt: str,
    *,
    brief: ContentBrief,
    kit: BrandKit,
    refs: Sequence[BrandReference],
    images: int,
    budget: int | None,
    trims: Sequence[Mapping[str, Any]] = (),
) -> None:
    """Fail with the first piece of intent the prompt lost (see the module docstring)."""
    flat = " ".join(prompt.split())
    if budget is None:
        assert len(prompt.split()) <= _MAX_WORDS, f"{len(prompt.split())} words > {_MAX_WORDS}"
    else:
        assert len(prompt) <= budget, f"{len(prompt)} > {budget}"
    assert not trims, f"something was trimmed: {list(trims)}"

    operator, context = _split_topic(brief)
    if _plain(operator):
        assert _plain(operator) in flat, "operator text not literal"

    prose = context.partition(REEL_METADATA_MARKER)[0]
    roles = brief.media.clip_image_roles
    product_photo = images > 0 and (len(roles) != images or "product" in roles)
    guide_product = known_replication_prose(prose) if prose else None
    product = brief.product_ref or guide_product or ""
    if _plain(product):
        assert f'Client product: "{_plain(product)}"' in flat, f"product {product!r} missing"

    for color in kit.palette_rgb:
        assert color in flat, f"palette {color} missing"
    for face in (kit.font_heading, kit.font_body):
        if face.strip():
            assert _plain(face) in flat, f"typeface {face!r} missing"

    facts: dict[str, str] = {}
    for name, value in brief.constraints.highlights:
        if len(json.dumps({**facts, name: value}, ensure_ascii=False)) > _FACTS_MAX:
            break
        facts[name] = value
    for name, value in facts.items():
        pair = json.dumps({name: value}, ensure_ascii=False)[1:-1]
        assert pair in flat, f"key fact {pair} missing"

    for offset, ref in enumerate(refs):
        index = images + 1 + offset
        assert f"Image {index}:" in flat, f"resource index {index} missing"
        if ref.asset_kind in _LOGO_KINDS:
            category = ref.asset_slot if ref.asset_kind == "logo_version" else "unspecified"
            alias = f"{'principal' if ref.selected_logo else 'alternative'} {category}"
            assert f"Image {index}: {alias}." in flat, f"logo alias {alias!r} missing"
        else:
            role = (
                "presenter"
                if ref.rol is BrandReferenceRole.PERSONAJE_PRESENTADOR
                else "brand element, not product/presenter"
            )
            labelled = f"Image {index}: {_plain(ref.label)} ({role})."
            assert labelled in flat, f"resource label/role {labelled!r} missing"
        if ref.note.strip():
            assert f"Usage: {_plain(ref.note)}" in flat, f"usage note of {index} not literal"

    identity = _plain(kit.positioning)
    if identity:
        assert f'Client identity: "{identity}".' in flat, "brand identity not whole"

    if prose.strip() and _plain(prose) not in flat:
        assert guide_product is not None, "an unknown replication guidance was dropped"
        for sentence, phrases in REPLICATION_PROSE_V1_COVERAGE:
            assert sentence in prose, f"coverage table out of date: {sentence!r}"
            for phrase in phrases or ():
                if phrase in REPLICATION_COVERAGE_NEEDS_PRODUCT_PHOTO and not product_photo:
                    continue
                assert phrase in flat, f"guidance {sentence!r} not covered by {phrase!r}"
        if guide_product:
            assert "Client product: " in flat, "the guidance's product lost its line"

    if brief.media.replication_brand_text:
        for cta in kit.cta_patterns:
            if _plain(cta):
                assert f'"{_plain(cta)}"' in flat, f"Brand Kit wording {cta!r} not verbatim"
        assert "CTAs, promotions" not in flat, "a rule still forbids the CTAs it carries"

    repeated = [s for s, n in Counter(_sentences(flat)).items() if n > 1]
    assert not repeated, f"duplicated sentences: {repeated}"


def assert_image_prompt_keeps_intent(
    prompt: str,
    *,
    brief: ContentBrief,
    kit: BrandKit,
    refs: Sequence[BrandReference],
    base_index: int,
    budget: int,
    scene: str = "",
    trims: Sequence[Mapping[str, Any]] = (),
) -> None:
    """The «no quality loss» guard for a Seedream image prompt (flyer, gallery slide;
    m-24820842 round 6): the scene and the post's words literal (each at least once — the
    exact repetition is what compiler 1 removes), plus everything `_assert_media_intent`
    checks, within `budget` characters."""
    assert len(prompt) <= budget, f"{len(prompt)} > {budget}"
    flat = " ".join(prompt.split())
    for text in (scene or brief.media.scene_prompt, brief.topic):
        if _plain(text):
            assert _plain(text) in flat, f"text not literal: {text[:40]!r}"
    _assert_media_intent(
        prompt, brief=brief, kit=kit, refs=refs, base_index=base_index, trims=trims
    )


def assert_video_prompt_keeps_intent(
    prompt: str,
    *,
    brief: ContentBrief,
    kit: BrandKit,
    refs: Sequence[BrandReference],
    base_index: int,
    texts: Sequence[str] = (),
    numbered: bool = True,
    trims: Sequence[Mapping[str, Any]] = (),
    product: str = "",
    resources_mandatory: bool = False,
) -> None:
    """The same guard for a Seedance 2.x video prompt (motion clip, talking video, animated
    slide; round 7b): `texts` (the operator's words, a scene) literal, everything
    `_assert_media_intent` checks, within the documented 1,000 words."""
    words = len(prompt.split())
    assert words <= _MAX_WORDS, f"{words} words > {_MAX_WORDS}"
    flat = " ".join(prompt.split())
    # round 8: the meaning units of the two merged sentences, each still said
    if product:
        for unit in (
            f'"{_plain(product)}"',
            "the client's real product",
            "shown",
            "exactly as it is",
            "shape, colors, label",
        ):
            assert unit in flat, f"product unit {unit!r} lost"
    if resources_mandatory:
        for unit in (
            "none is optional",
            "in its own role",
            "exact identity/colors/proportions",
            "requested presence/action across all relevant shots and cuts",
            "no invented marks/props",
        ):
            assert unit in flat, f"resource unit {unit!r} lost"
    for text in texts:
        if _plain(text):
            assert _plain(text) in flat, f"text not literal: {text[:40]!r}"
    _assert_media_intent(
        prompt,
        brief=brief,
        kit=kit,
        refs=refs,
        base_index=base_index,
        trims=trims,
        numbered=numbered,
    )


def _assert_media_intent(
    prompt: str,
    *,
    brief: ContentBrief,
    kit: BrandKit,
    refs: Sequence[BrandReference],
    base_index: int,
    trims: Sequence[Mapping[str, Any]] = (),
    numbered: bool = True,
) -> None:
    """Every resource with its real index (or scene number), alias/label/role and usage
    note, the palette, the typefaces, the key facts, the label/lettering and text rules,
    no duplicated sentence (numbers masked), nothing trimmed."""
    flat = " ".join(prompt.split())
    assert not trims, f"something was trimmed: {list(trims)}"
    for color in kit.palette_rgb:
        assert color in flat, f"palette {color} missing"
    for face in (kit.font_heading, kit.font_body):
        if face.strip():
            assert _plain(face) in flat, f"typeface {face!r} missing"
    facts: dict[str, str] = {}
    for name, value in brief.constraints.highlights:
        if len(json.dumps({**facts, name: value}, ensure_ascii=False)) > _FACTS_MAX:
            break
        facts[name] = value
    for name, value in facts.items():
        pair = json.dumps({name: value}, ensure_ascii=False)[1:-1]
        assert pair in flat, f"key fact {pair} missing"
    for offset, ref in enumerate(refs):
        index = base_index + 1 + offset
        name = f"Image {index}" if numbered else f"Scene resource {offset + 1}"
        if ref.asset_kind in _LOGO_KINDS:
            category = ref.asset_slot if ref.asset_kind == "logo_version" else "unspecified"
            alias = f"{'principal' if ref.selected_logo else 'alternative'} {category}"
            assert f"{name}: {alias}." in flat, f"logo alias {name}: {alias!r} missing"
        else:
            assert f"{name}: {_plain(ref.label)} (" in flat, f"resource {name} missing"
        if ref.note.strip():
            assert f"Usage: {_plain(ref.note)}" in flat, f"usage note of {name} not literal"
    assert "logo lettering" in flat, "logo lettering rule lost"
    assert "authentic product" in flat or "Preserve product and labels" in flat, "label rule lost"
    assert "no invented text" in flat or "no added captions" in flat, "text rule lost"
    repeated = [s for s, n in Counter(_sentences(flat)).items() if n > 1]
    assert not repeated, f"duplicated sentences: {repeated}"


# -- prompt compiler 2 (2026-11-03): a guard on quality, not on wording ----------------------
#
# Audit `docs/modelos-generativos/auditoria-prompts-clip-20261103.md` §5: the guards above
# only check that substrings are there, and in places they ENFORCE the 2026-11-02 wording
# (they still protect the frozen compiler-0/1 prompts, byte for byte). The compiler-2 guard
# checks what a good Seedance prompt needs: `main`'s points per route (written HERE, not
# taken from the compiler — the guard is not its own judge), no contradictory pair, logo
# mentions against the logo images actually sent, the product and the main instruction near
# the start, no internal jargon, one image syntax, nothing foreign-branded outside the
# untrusted metadata, every operator/Brand Kit datum literal and nothing trimmed.

#: `main` (56746531)'s points per route, as compiler 2 must say them in plain English.
MAIN_UNITS: dict[str, tuple[str, ...]] = {
    "motion": (
        "advertising video for social media that tells a short story",
        "with no presenter talking to the camera",
        "Do not show any written text, captions, subtitles or titles",
    ),
    "edit": (
        "Edit @Video1 in place",
        "keep its footage",
        "shot count",
        "shot order",
        "cut timings",
        "camera angle and trajectory",
        "gestures, hand positions",
        "duration and aspect ratio",
        "Preserve every stage of assembly: do not show the fully assembled product early",
        "Replace packaging only where it exists in the original",
        "Do not cut to a catalog still or a new final hero shot",
        "do not recreate its music or speech",
        "The client's brand look takes priority over the source reel's look",
        "Do not recolor food, skin or the real product",
    ),
    "slide": (
        "slow, smooth camera move",
        "Nobody talks to the camera",
        "The product keeps its exact look and label",
        "Do not show any written text, captions, subtitles or titles",
    ),
}
#: A replica with a product photo also says `main`'s product units.
EDIT_PRODUCT_UNITS = (
    "ingredients, layers, shape, colors, proportions, labels and packaging",
    "consistently throughout the actions",
)
#: Never both in one prompt (audit §5.2): each pair is a semantic conflict.
CONTRADICTIONS: tuple[tuple[str, str], ...] = (
    ("shape the story", "Edit @Video1 in place"),
    ("Let them shape", "slow, smooth camera move"),
    ("approved client wording", "never written"),
    ("Restyle", "Do not show any written text"),
    ("not its visual style", "keep its footage"),
    ("added afterwards", "Do not show any written text"),
    ("No logo image is supplied", "is the client's logo"),
)
#: Internal notes a video model cannot act on (audit H3).
BANNED_JARGON = (
    "filenames",
    "already resolved",
    "local composition",
    "principal",
    "Used assets",
    "REPLACE BRAND GRAPHICS",
    "approved text accents",
    "Honor usage notes",
    "Client identity",
)
_SLASHED = re.compile(r"\b[A-Za-z]{2,}/[A-Za-z]{2,}\b")
_QUOTED = re.compile(r'"[^"]*"')
_NO_LOGO = "No logo image is supplied"
#: The share of the prompt (in words) the product and the main instruction must fall in.
_HEAD_SHARE = 0.2
_HEAD_MIN_WORDS = 40


def _unquoted(flat: str) -> str:
    """The prompt's own words: the operator's, the copy's and the metadata's quoted texts
    blanked — they are data, and may legitimately hold any word."""
    return _QUOTED.sub('""', flat)


def assert_video_prompt_v2_quality(
    prompt: str,
    *,
    route: str,
    brief: ContentBrief,
    kit: BrandKit,
    refs: Sequence[BrandReference],
    base_index: int,
    numbered: bool = True,
    texts: Sequence[str] = (),
    product: str = "",
    product_photo: bool = False,
    foreign: Sequence[str] = (),
    trims: Sequence[Mapping[str, Any]] = (),
) -> None:
    """Fail with the first quality problem of a compiler-2 Seedance prompt. `route` is
    "motion" (a motion clip), "edit" (a reel replica) or "slide" (an animated gallery
    slide); `base_index` is the number of the first brand image (`Image N` / `@ImageN`);
    `numbered=False` (a slide with no reference video) sends no brand image at all;
    `texts` are what must travel literal (the operator's words, the copy's shots);
    `foreign` are the source brand's words (its handle, its caption's names)."""
    flat = " ".join(prompt.split())
    own = _unquoted(flat)
    words = flat.split()
    assert len(words) <= _MAX_WORDS, f"{len(words)} words > {_MAX_WORDS}"
    assert not trims, f"something was trimmed: {list(trims)}"

    for unit in MAIN_UNITS[route]:
        assert unit in flat, f"{route}: `main` unit lost: {unit!r}"
    if route == "edit" and product_photo:
        for unit in EDIT_PRODUCT_UNITS:
            assert unit in flat, f"edit: product unit lost: {unit!r}"
    for one, other in CONTRADICTIONS:
        assert not (one in flat and other in flat), f"contradiction: {one!r} with {other!r}"
    for jargon in BANNED_JARGON:
        assert jargon not in own, f"internal jargon: {jargon!r}"
    slashed = _SLASHED.findall(own)
    assert not slashed, f"slash-joined words: {slashed}"

    # one image syntax per prompt (audit §6): a replica says «@ImageN» as it says «@Video1»
    if route == "edit":
        assert not re.search(r"\bImages? \d", own), "a replica mixes «Image N» with «@ImageN»"
    else:
        assert "@Image" not in own and "@Video" not in own, "«@ImageN» outside a replica"

    # the main instruction and the product near the start (audit H5/H7)
    head = " ".join(words[: max(_HEAD_MIN_WORDS, int(len(words) * _HEAD_SHARE))])
    opening = {
        "motion": "advertising video for social media",
        "edit": "Edit @Video1 in place",
        "slide": "Bring this photograph to life",
    }[route]
    assert opening in head, f"main instruction {opening!r} not near the start"
    if _plain(product):
        assert f'"{_plain(product)}"' in head, f"product {product!r} not near the start"

    # logo mentions against the logo images actually sent (audit H2)
    logos = [r for r in refs if r.asset_kind in _LOGO_KINDS]
    if route == "slide":
        if not refs:
            assert "Do not add any logo" in flat, "a slide with no resource may add a logo"
    elif logos:
        assert _NO_LOGO not in flat, "a logo is sent but the prompt says none is"
    else:
        assert _NO_LOGO in flat, "no logo is sent and nothing forbids drawing one"
    prefix = "@Image" if route == "edit" else "Image "
    for offset, ref in enumerate(refs):
        if not numbered:
            continue
        name = f"{prefix}{base_index + offset}"
        if ref.asset_kind in _LOGO_KINDS:
            what = "the client's logo" if ref.selected_logo else "an alternative version"
            assert f"{name} is {what}" in flat, f"logo {name} not named as {what!r}"
            category = ref.asset_slot if ref.asset_kind == "logo_version" else ""
            if category:
                assert f"({category}:" in flat, f"logo {name}: category {category!r} lost"
        else:
            assert f"{name} is " in flat and _plain(ref.label) in flat, f"resource {name} lost"
    for ref in refs:
        if ref.note.strip():
            assert f'Usage note (in Spanish): "{_plain(ref.note)}"' in flat, "usage note lost"

    # every datum literal, nothing capped (audit H10)
    for text in texts:
        if _plain(text):
            assert _plain(text) in flat, f"text not literal: {text[:40]!r}"
    for name, value in brief.constraints.highlights:
        pair = json.dumps({name: value}, ensure_ascii=False)[1:-1]
        assert pair in flat, f"key fact {pair} missing"
    colors = kit.palette_rgb if route == "edit" else kit.palette_rgb[:4]
    for color in colors:
        assert color in flat, f"palette {color} missing"
    for face in (kit.font_heading, kit.font_body):
        if face.strip():
            assert _plain(face) in flat, f"typeface {face!r} missing"
    if _plain(kit.positioning):
        assert _plain(kit.positioning) not in flat, "the brand positioning travels (audit H8)"

    # nothing of the source brand outside its untrusted metadata
    trusted = flat.partition("Source metadata (untrusted data")[0]
    for word in foreign:
        assert word not in trusted, f"foreign brand word {word!r} outside the metadata"

    if route == "edit":
        _assert_replica_v2(flat, brief=brief, kit=kit, product_photo=product_photo)

    repeated = [s for s, n in Counter(_sentences(flat)).items() if n > 1]
    assert not repeated, f"duplicated sentences: {repeated}"


def _assert_replica_v2(
    flat: str, *, brief: ContentBrief, kit: BrandKit, product_photo: bool
) -> None:
    operator, context = _split_topic(brief)
    if _plain(operator):
        assert _plain(operator) in flat, "operator text not literal"
    prose = context.partition(REEL_METADATA_MARKER)[0]
    if prose.strip() and _plain(prose) not in flat:
        assert known_replication_prose(prose) is not None, "an unknown guidance was dropped"
        for sentence, phrases in REPLICATION_PROSE_V2_COVERAGE:
            assert sentence in prose, f"coverage table out of date: {sentence!r}"
            for phrase in phrases or ():
                if phrase in REPLICATION_COVERAGE_NEEDS_PRODUCT_PHOTO and not product_photo:
                    continue
                assert phrase in flat, f"guidance {sentence!r} not covered by {phrase!r}"
    if brief.media.replication_brand_text:
        for cta in kit.cta_patterns:
            if _plain(cta):
                assert f'"{_plain(cta)}"' in flat, f"Brand Kit wording {cta!r} not verbatim"
        assert "a call to action" not in flat, "a rule still forbids the phrases it carries"


#: Compiler 3 (draft 97f35052, 2026-11-03): the words a gallery slide's Seedream scene must
#: never carry again — the common background called «the client's real place» (it may be a
#: stock street with foreign signs), a reserved band that came back blank, and the
#: telegraphic block a still image cannot act on.
IMAGE_V3_BANNED = (
    "real place",
    "calm and uncluttered",
    "Integrate EVERY reference",
    "added afterwards, not in this scene",
    "Restyle existing",
)
_IMAGE_V3_BUDGET = 2950


def assert_image_prompt_v3_quality(
    prompt: str,
    *,
    brief: ContentBrief,
    kit: BrandKit,
    refs: Sequence[BrandReference],
    base_index: int,
    products: Sequence[int] = (),
    guides: Sequence[int] = (),
    place: int | None = None,
    scene: str = "",
) -> None:
    """Fail with the first quality problem of a compiler-3 gallery-slide Seedream prompt.
    `products`, `guides` and `place` are the image numbers of each role; `base_index` the
    first brand image's number. Written without the compiler's helpers."""
    flat = " ".join(prompt.split())
    own = _unquoted(flat)
    assert len(prompt) <= _IMAGE_V3_BUDGET, f"{len(prompt)} chars > {_IMAGE_V3_BUDGET}"
    for banned in (*IMAGE_V3_BANNED, *BANNED_JARGON):
        assert banned not in own, f"banned wording: {banned!r}"
    slashed = _SLASHED.findall(own)
    assert not slashed, f"slash-joined words: {slashed}"
    assert flat.startswith("Create one professional advertising photograph"), "no main line"

    # what this slide shows, near the start
    head = " ".join(flat.split()[: _HEAD_MIN_WORDS + 40])
    assert "this slide shows" in head.lower(), "the slide's own content is not stated early"
    if _plain(scene):
        assert _plain(scene) in flat, "the operator's scene for this slide is not literal"

    # each reference in its role
    for number in products:
        name = f"Image {number}"
        assert f"{name} is the client's real product photo" in flat, f"{name}: product lost"
        assert "never replace it with another product" in flat, "the product may be swapped"
    if not products:
        assert "never replace it with another product" not in flat, "a product rule, no photo"
    for number in guides:
        assert f"Image {number} is a layout guide only" in flat, f"guide {number} lost"
        assert "Do not copy its products, brand names, signs or text" in flat, "guide leaks"
        if place is not None:
            assert f"nor its setting: the setting is Image {place}" in flat, "guide sets scene"
    if place is not None:
        assert f"Image {place} is the common background chosen for this gallery" in flat
        assert "Do not copy any shop names, signs, logos or text" in flat, "foreign signs"
        if products or guides:
            assert "not the photo's background" in flat, "the product photo's backdrop wins"
    else:
        assert "common background" not in flat, "a background named but not sent"

    # the request is context, never lettering
    if _plain(brief.topic) and _plain(brief.topic) != _plain(scene):
        assert "do not write any of its words in the image" in flat, "the request may be drawn"
    assert "Do not write any text in the image" in flat, "no text rule"
    logos = [r for r in refs if r.asset_kind in _LOGO_KINDS]
    if logos:
        assert "The only lettering allowed is the supplied logo" in flat
        assert _NO_LOGO not in flat
    else:
        assert _NO_LOGO in flat, "no logo is sent and nothing forbids drawing one"
    assert "fills the whole frame from edge to edge" in flat, "a blank band is allowed"

    # brand identity
    for offset, ref in enumerate(refs):
        name = f"Image {base_index + offset}"
        if ref.asset_kind in _LOGO_KINDS:
            what = "the client's logo" if ref.selected_logo else "an alternative version"
            assert f"{name} is {what}" in flat, f"logo {name} not named as {what!r}"
        else:
            assert f"{name} is " in flat and _plain(ref.label) in flat, f"resource {name} lost"
    for color in kit.palette_rgb[:4]:
        assert color in flat, f"palette {color} missing"
    for face in (kit.font_heading, kit.font_body):
        if face.strip():
            assert _plain(face) in flat, f"typeface {face!r} missing"
    repeated = [s for s, n in Counter(_sentences(flat)).items() if n > 1]
    assert not repeated, f"duplicated sentences: {repeated}"
