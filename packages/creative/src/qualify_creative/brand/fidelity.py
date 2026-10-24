"""Layer 1 of the Brand Fidelity Gate (MC-11): deterministic, no network, no model.

This layer runs ALWAYS — including when the LLM judge (layer 2) is disabled or a BYOK
key is dead — because it is the layer that makes regulated-brand output publishable.
Every check is a hard rule: a violation is a rejection, not an opinion, and each
`HardFailure` carries the rule id plus a human-readable detail the UI can show verbatim.

Matching is case-insensitive and accent-insensitive (NFD decomposition, combining marks
stripped, casefold), so "Grátis" trips a ban on "gratis" and vice versa. Banned words
match on word boundaries; forbidden claims match as plain substrings — a claim smuggled
inside a longer sentence is still the claim.

Ads slot overflow (headline/description length) is deliberately NOT re-checked here:
`CopyPayload` enforces it at construction, so a payload that exists cannot overflow.

Design: `docs/diseno-motor-contenido-marca.md` section 4.3; backlog MC-11.
"""

from __future__ import annotations

import re
import unicodedata

from qualify_creative.enums import EmojiPolicy, ImageRoute
from qualify_creative.schemas import BrandKit, CopyPayload, HardFailure, ImagePolicy

RULE_BANNED_WORD = "banned_word"
RULE_FORBIDDEN_CLAIM = "forbidden_claim"
RULE_CAPTION_LENGTH = "caption_length"
RULE_EMOJI_POLICY = "emoji_policy"
RULE_HASHTAG_POLICY = "hashtag_policy"
RULE_ROUTE_BLOCKED = "route_blocked"

SPARSE_EMOJI_MAX = 3

#: How far over the brand's caption maximum a generated caption may land and still be
#: fitted (trimmed at a sentence or word boundary) instead of rejected. Measured
#: 2026-10-22: a clip for a real brand came back at 601 characters against a cap of
#: 600 — the model miscounts by a handful of characters around emoji and accents — and
#: the whole run (and its spend) was thrown away for one character. The fit is
#: deterministic and recorded in the variant's fidelity verdict; a caption further over
#: than this is a real miss and keeps failing the hard rule.
CAPTION_FIT_TOLERANCE = 0.10
#: A fitted caption keeps at least this share of the brand maximum: a sentence end is
#: taken only within the last fifth of it, else the cut is at the last whole word —
#: a caption 5 characters over is not cut back to a sentence that ends at 95.
CAPTION_FIT_KEEP = 0.8

# A sentence end followed by whitespace: terminal punctuation plus any closing quote
# or bracket that rides with it.
_SENTENCE_END = re.compile(r"[.!?…]+[\"»)\]]*(?=\s)")

# Blocks that unicodedata's So/Sk categories alone would miss are covered explicitly;
# combining marks (skin tones ride as Sk, variation selectors as Mn) never double-count.
_EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x1F1E6, 0x1F1FF),  # regional indicators (flags)
    (0x1F300, 0x1F5FF),  # misc symbols and pictographs
    (0x1F600, 0x1F64F),  # emoticons
    (0x1F680, 0x1F6FF),  # transport and map
    (0x1F700, 0x1F77F),  # alchemical
    (0x1F900, 0x1F9FF),  # supplemental symbols and pictographs
    (0x1FA00, 0x1FAFF),  # symbols and pictographs extended-A
    (0x2600, 0x26FF),  # miscellaneous symbols
    (0x2700, 0x27BF),  # dingbats
)


def normalize(text: str) -> str:
    """Canonical comparison form: NFD-decompose, drop combining marks, casefold.

    'Grátis' and 'gratis' normalize to the same bytes, which is what makes the banned
    word and forbidden claim checks accent- and case-insensitive.
    """
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _is_emoji(ch: str) -> bool:
    if unicodedata.category(ch) in ("So", "Sk"):
        return True
    code = ord(ch)
    return any(low <= code <= high for low, high in _EMOJI_RANGES)


def _count_emoji(text: str) -> int:
    return sum(1 for ch in text if _is_emoji(ch) and not unicodedata.combining(ch))


def _full_text(copy: CopyPayload) -> str:
    """Every string the payload carries, organic and ads slots alike: a banned word in
    an ad headline is exactly as banned as one in the caption."""
    parts = (
        copy.hook,
        copy.caption,
        copy.cta,
        *copy.hashtags,
        copy.ads_primary_text or "",
        copy.ads_headline or "",
        copy.ads_description or "",
        # the libreto is copy too: a banned word said on camera is still said
        copy.script,
        *(f"{shot.visual}\n{shot.line}" for shot in copy.shots),
    )
    return "\n".join(part for part in parts if part)


def _normalized_tag(tag: str) -> str:
    return normalize(tag.lstrip("#"))


def fit_caption(copy: CopyPayload, kit: BrandKit) -> tuple[CopyPayload, str | None]:
    """Fit a caption that overshoots the brand maximum by a little, BEFORE the hard rule
    judges it.

    Returns the (possibly new) payload and a human-readable note of what was done, or
    `None` when nothing was. Only the caption changes; hook, CTA, hashtags and script
    stay as generated. The cut lands on the last sentence end that fits within the last
    fifth of the maximum (`CAPTION_FIT_KEEP`) — one sentence fewer reads as written, not
    as cut — or, when there is none, on the last word boundary; never below the brand
    minimum (a cut that would go below it takes the maximum itself). A caption over the
    maximum by more than
    `CAPTION_FIT_TOLERANCE` is returned untouched: that is a real miss, and the
    `caption_length` hard rule says so.
    """
    targets = kit.length_targets
    limit = targets.caption_max_chars
    length = len(copy.caption)
    if length <= limit or length > int(limit * (1 + CAPTION_FIT_TOLERANCE)):
        return copy, None

    window = copy.caption[:limit]
    floor = max(targets.caption_min_chars, int(limit * CAPTION_FIT_KEEP))
    cut = 0
    # The trailing space lets a sentence that ends exactly at the limit count.
    for match in _SENTENCE_END.finditer(window + " "):
        if floor <= match.end() <= limit:
            cut = match.end()
    if cut == 0:
        # the character after the window decides whether its last word is whole
        if copy.caption[limit : limit + 1].isspace():
            cut = len(window.rstrip())
        else:
            space = window.rstrip().rfind(" ")
            cut = space if space >= targets.caption_min_chars else limit
    fitted = copy.caption[:cut].rstrip()
    note = (
        f"caption trimmed from {length} to {len(fitted)} characters to fit the brand"
        f" maximum of {limit}"
    )
    return copy.model_copy(update={"caption": fitted}), note


def check_hard_rules(copy: CopyPayload, kit: BrandKit) -> tuple[HardFailure, ...]:
    """Run every layer-1 rule and return all failures, not just the first: the operator
    fixes one regeneration, not a whack-a-mole sequence of them."""
    failures: list[HardFailure] = []
    text = normalize(_full_text(copy))

    for word in kit.banned_words:
        pattern = rf"(?<!\w){re.escape(normalize(word))}(?!\w)"
        if re.search(pattern, text):
            failures.append(
                HardFailure(
                    rule=RULE_BANNED_WORD,
                    detail=f"banned word '{word}' appears in the copy",
                )
            )

    for claim in kit.forbidden_claims:
        if normalize(claim) in text:
            failures.append(
                HardFailure(
                    rule=RULE_FORBIDDEN_CLAIM,
                    detail=f"forbidden claim '{claim}' appears in the copy",
                )
            )

    caption_len = len(copy.caption)
    targets = kit.length_targets
    if caption_len < targets.caption_min_chars:
        failures.append(
            HardFailure(
                rule=RULE_CAPTION_LENGTH,
                detail=(
                    f"caption is {caption_len} characters, below the brand minimum of"
                    f" {targets.caption_min_chars}"
                ),
            )
        )
    elif caption_len > targets.caption_max_chars:
        failures.append(
            HardFailure(
                rule=RULE_CAPTION_LENGTH,
                detail=(
                    f"caption is {caption_len} characters, above the brand maximum of"
                    f" {targets.caption_max_chars}"
                ),
            )
        )

    emoji_count = _count_emoji(_full_text(copy))
    if kit.emoji_policy is EmojiPolicy.NONE and emoji_count > 0:
        failures.append(
            HardFailure(
                rule=RULE_EMOJI_POLICY,
                detail=f"emoji policy is 'none' but the copy contains {emoji_count} emoji",
            )
        )
    elif kit.emoji_policy is EmojiPolicy.SPARSE and emoji_count > SPARSE_EMOJI_MAX:
        failures.append(
            HardFailure(
                rule=RULE_EMOJI_POLICY,
                detail=(
                    f"emoji policy is 'sparse' (at most {SPARSE_EMOJI_MAX}) but the copy"
                    f" contains {emoji_count} emoji"
                ),
            )
        )

    policy = kit.hashtag_policy
    tags = tuple(_normalized_tag(tag) for tag in copy.hashtags)
    if len(tags) < policy.minimum:
        failures.append(
            HardFailure(
                rule=RULE_HASHTAG_POLICY,
                detail=f"{len(tags)} hashtags, below the brand minimum of {policy.minimum}",
            )
        )
    elif len(tags) > policy.maximum:
        failures.append(
            HardFailure(
                rule=RULE_HASHTAG_POLICY,
                detail=f"{len(tags)} hashtags, above the brand maximum of {policy.maximum}",
            )
        )
    for banned_tag in policy.never:
        if _normalized_tag(banned_tag) in tags:
            failures.append(
                HardFailure(
                    rule=RULE_HASHTAG_POLICY,
                    detail=f"hashtag '#{banned_tag.lstrip('#')}' is on the brand's never list",
                )
            )
    for required_tag in policy.always:
        if _normalized_tag(required_tag) not in tags:
            failures.append(
                HardFailure(
                    rule=RULE_HASHTAG_POLICY,
                    detail=(
                        f"required hashtag '#{required_tag.lstrip('#')}' is missing from the copy"
                    ),
                )
            )

    return tuple(failures)


def check_route_allowed(*, route: ImageRoute, policy: ImagePolicy) -> HardFailure | None:
    """Enforced BEFORE any vendor is called, so a blocked route costs nothing. The
    detail is the policy's own reason, which the UI shows verbatim next to the disabled
    option."""
    if policy.allows(route):
        return None
    return HardFailure(rule=RULE_ROUTE_BLOCKED, detail=policy.reason_for(route))
