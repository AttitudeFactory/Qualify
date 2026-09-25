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
