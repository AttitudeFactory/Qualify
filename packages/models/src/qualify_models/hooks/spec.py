"""The operational definition of a "hook", as constants the code can be held to.

`docs/ingenieria-inversa-sortfeed.md:396` gated the "viral hooks library" feature on
*defining* what a hook is. This module is that definition, written so it can be
falsified rather than argued about: the window is a parameter with a stated default,
the taxonomy is a closed vocabulary, and NOTES_hook_pattern_spike.md §A.3 lists the
four observations that would force each of them to change.

Nothing here imports torch/transformers, so the definition (and everything derived
from it deterministically) is readable and testable without the `ml` group.
"""

from __future__ import annotations

from enum import StrEnum

# Bumped when the definition itself changes (window default, taxonomy, channel set)
# in a way that makes two extractions non-comparable. Distinct from DETECTOR_VERSION
# (the implementation) and pipeline_version (the cascade): a feature row pins all three.
HOOK_SPEC_VERSION = "hook-spec-1"

# The primary window, in seconds. See NOTES_hook_pattern_spike.md §A.2 for the three
# reasons (a Spanish clause needs ~3 s; a *sequence* of shots needs ~3 s; past ~7 s you
# are describing the body of the video, not its opening).
PRIMARY_WINDOW_SECONDS = 3.0

# Emitted in the same pass so "is 3 s the right N?" is an empirical question answerable
# from the corpus instead of an assumption. Deterministic + lexical features cost nothing
# extra per window; the VLM runs on the primary window only unless asked otherwise.
WINDOW_SECONDS: tuple[float, ...] = (3.0, 5.0, 7.0)

# Frames sampled per second inside a window. 3 fps over 3 s = 9 frames: enough to see
# 2-3 cuts (short-form montage cuts every 1-2 s) without paying for 90 decoded frames.
FRAME_SAMPLE_FPS = 3.0

# Mean absolute inter-frame difference (0-1, on a 64x64 grayscale downscale) above which
# two consecutive sampled frames are called a cut. Deliberately a constant and not a
# tuned value: it has never been calibrated against labelled cuts, and `cut_count` is
# reported as a *proxy* until it is. See NOTES_hook_pattern_spike.md §B.3.
CUT_DIFF_THRESHOLD = 0.18


class HookType(StrEnum):
    """Closed vocabulary for the opening's rhetorical move.

    Closed on purpose: free prose does not aggregate, and the whole point of the
    extractor is comparing posts against each other. Categories are documented with
    examples in NOTES_hook_pattern_spike.md §A.4.
    """

    QUESTION = "question"
    PAIN_POINT = "pain_point"
    DIRECT_CLAIM = "direct_claim"
    CURIOSITY_GAP = "curiosity_gap"
    NUMERIC_LIST = "numeric_list"
    NEGATION_WARNING = "negation_warning"
    COMMAND_CTA = "command_cta"
    PERSONAL_STORY = "personal_story"
    SOCIAL_PROOF = "social_proof"
    PRICE_REVEAL = "price_reveal"
    LOCATION_REVEAL = "location_reveal"

    # A finding about the video: nothing was said and nothing was written on screen.
    NONE_DETECTED = "none_detected"
    # A failure of the extractor: the model returned something unparseable. Kept
    # separate from NONE_DETECTED so a broken run cannot masquerade as a silent video.
    UNKNOWN = "unknown"


class Setting(StrEnum):
    """What the opening frames show. Closed vocabulary, real-estate oriented."""

    INTERIOR_HOME = "interior_home"
    EXTERIOR_HOME = "exterior_home"
    LAND_PLOT = "land_plot"
    NATURE_LANDSCAPE = "nature_landscape"
    URBAN_STREET = "urban_street"
    OFFICE = "office"
    PERSON_CLOSEUP = "person_closeup"
    SCREEN_GRAPHIC = "screen_graphic"
    OTHER = "other"
    UNKNOWN = "unknown"


class TextDensity(StrEnum):
    """How much on-screen text the opening carries."""

    NONE = "none"
    LOW = "low"  # a few words, one line
    MEDIUM = "medium"  # a sentence or two
    HIGH = "high"  # a wall of text / dense caption burn-in
    UNKNOWN = "unknown"
