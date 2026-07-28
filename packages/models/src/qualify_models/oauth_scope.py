"""Which Fase 1 cascade stages apply to OAuth-reachable content, and why.

A connected Instagram Business/Creator account reaches a genuine sliver of
*earned* media (`mentioned_media`, `mentioned_comment`, `tags`) alongside the
client's owned media and the comments on it. The Fase 1 cascade was designed
for *scraped* content, so its stages do not transfer uniformly across those
surfaces. This module is that assessment as data rather than prose, so the
cost model in `eval/fase0_cost.py` reads the same matrix a human argues with —
a cost curve that disagrees with the applicability matrix is a bug in one of
them, and keeping both in one place makes that detectable.

Surface definitions and Graph API edges follow `docs/fase0-zernio-mercado.md`
§4.1/§4.3. The edge names are PROVISIONAL: grounding field shapes in the
harvested Meta reference is task D1's job, not this module's. Nothing here
names a CRM entity, table or column — that is the architect's call.

Load-bearing caveat on the `filter` stage: `filter.py` is currently a
constant-`False` function. Its `threshold=0.22` is calibrated for softmax
scores, but SigLIP emits independent per-label *sigmoid* scores that measure
~1e-4 on real input (measured 2026-07-23 on `tests/fixtures/sample_frame.jpg`
across three label sets). So wherever this matrix says the discard gate
survives, it means the architectural slot survives — not that the incumbent
implementation can fill it. See `NOTES_fase0_oauth_crm.md`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

ASSESSMENT_VERSION = "oauth-scope-v1"


class ContentSurface(StrEnum):
    """A distinct body of content, defined by how Qualify can legally reach it.

    The unreachable members are deliberately modeled rather than omitted: the
    negative result ("OAuth cannot see competitors") is the load-bearing
    strategic finding of `docs/fase0-zernio-mercado.md` §4.2, and a matrix that
    simply lacked those rows would read as an oversight instead of a verdict.
    """

    OWNED_MEDIA = "owned_media"
    OWNED_MEDIA_COMMENTS = "owned_media_comments"
    MENTIONED_MEDIA = "mentioned_media"
    MENTIONED_COMMENT = "mentioned_comment"
    TAGS = "tags"
    COMPETITOR_CONTENT = "competitor_content"
    UNAFFILIATED_CREATOR_CONTENT = "unaffiliated_creator_content"


class CascadeStage(StrEnum):
    """The four Fase 1 cascade stages, as implemented in this package."""

    FILTER = "filter"
    VISION = "vision"
    TRANSCRIPTION = "transcription"
    SENTIMENT = "sentiment"


class Verdict(StrEnum):
    """Why a stage does or does not carry over.

    The distinction between UNCHANGED and REPURPOSED is the point of this enum.
    A boolean would collapse "run the Fase 1 stage as-is" together with "the
    slot survives but the prompt, output schema and instrument all change",
    and those two have very different build costs.
    """

    APPLIES_UNCHANGED = "applies_unchanged"
    APPLIES_REPURPOSED = "applies_repurposed"
    DOES_NOT_APPLY = "does_not_apply"
    UNREACHABLE = "unreachable"


class SurfaceProfile(BaseModel):
    """Properties of a surface that determine which stages can even run on it.

    Modality is why most stage verdicts are forced: a comment has no visual or
    audio track, so three of the four stages are structurally inapplicable to
    it regardless of how valuable they would be.
    """

    surface: ContentSurface
    oauth_reachable: bool
    graph_api_edge: str | None
    has_visual_track: bool
    has_audio_track: bool
    has_text: bool
    third_party_authored: bool
    volume_bounded_by: str


class StageApplicability(BaseModel):
    """One cell of the (stage x surface) matrix."""

    stage: CascadeStage
    surface: ContentSurface
    verdict: Verdict
    reason: str

    @property
    def billable(self) -> bool:
        """Whether this cell consumes paid compute.

        Drives `eval/fase0_cost.py`: a stage that does not apply contributes a
        structural zero, not a number someone typed into a spreadsheet.
        """
        return self.verdict in (Verdict.APPLIES_UNCHANGED, Verdict.APPLIES_REPURPOSED)


SURFACE_PROFILES: tuple[SurfaceProfile, ...] = (
    SurfaceProfile(
        surface=ContentSurface.OWNED_MEDIA,
        oauth_reachable=True,
        graph_api_edge="GET /{ig-user-id}/media",
        has_visual_track=True,
        has_audio_track=True,
        has_text=True,
        third_party_authored=False,
        volume_bounded_by="the client's own publishing rate (~20-200/month)",
    ),
    SurfaceProfile(
        surface=ContentSurface.OWNED_MEDIA_COMMENTS,
        oauth_reachable=True,
        graph_api_edge="GET /{ig-media-id}/comments",
        has_visual_track=False,
        has_audio_track=False,
        has_text=True,
        third_party_authored=True,
        volume_bounded_by="the client's audience size and engagement rate — UNMEASURED",
    ),
    SurfaceProfile(
        surface=ContentSurface.MENTIONED_MEDIA,
        oauth_reachable=True,
        graph_api_edge="GET /{ig-user-id}/mentioned_media",
        has_visual_track=True,
        has_audio_track=True,
        has_text=True,
        third_party_authored=True,
        volume_bounded_by="third-party behaviour — effectively unbounded, UNMEASURED",
    ),
    SurfaceProfile(
        surface=ContentSurface.MENTIONED_COMMENT,
        oauth_reachable=True,
        graph_api_edge="GET /{ig-user-id}/mentioned_comment",
        has_visual_track=False,
        has_audio_track=False,
        has_text=True,
        third_party_authored=True,
        volume_bounded_by="third-party behaviour — effectively unbounded, UNMEASURED",
    ),
    SurfaceProfile(
        surface=ContentSurface.TAGS,
        oauth_reachable=True,
        graph_api_edge="GET /{ig-user-id}/tags",
        has_visual_track=True,
        has_audio_track=True,
        has_text=True,
        third_party_authored=True,
        volume_bounded_by="third-party behaviour — unbounded and cheaper to trigger than a mention",
    ),
    SurfaceProfile(
        surface=ContentSurface.COMPETITOR_CONTENT,
        oauth_reachable=False,
        graph_api_edge=None,
        has_visual_track=True,
        has_audio_track=True,
        has_text=True,
        third_party_authored=True,
        volume_bounded_by="n/a — not reachable",
    ),
    SurfaceProfile(
        surface=ContentSurface.UNAFFILIATED_CREATOR_CONTENT,
        oauth_reachable=False,
        graph_api_edge=None,
        has_visual_track=True,
        has_audio_track=True,
        has_text=True,
        third_party_authored=True,
        volume_bounded_by="n/a — not reachable",
    ),
)

_NO_VISUAL_TRACK = "This surface is text-only: there is no frame to classify or describe."
_NO_AUDIO_TRACK = "This surface is text-only: there is no audio track to transcribe."
_UNREACHABLE = (
    "No OAuth grant can exist — a client cannot authorize access to an account it does "
    "not control. Reaching this content requires packages/scraper, i.e. the Fase 1 "
    "pipeline. docs/fase0-zernio-mercado.md §4.2 treats this as structural, not a "
    "limitation that scale or spend removes."
)

# The enrichment gate on third-party media. Named separately from the matrix
# because `eval/fase0_cost.py` needs it as a cost multiplier (pass-rate), not
# merely as a yes/no.
GATED_SURFACES: frozenset[ContentSurface] = frozenset(
    {ContentSurface.MENTIONED_MEDIA, ContentSurface.TAGS}
)

APPLICABILITY: tuple[StageApplicability, ...] = (
    # --- owned_media: the client's own posts -------------------------------
    StageApplicability(
        stage=CascadeStage.FILTER,
        surface=ContentSurface.OWNED_MEDIA,
        verdict=Verdict.DOES_NOT_APPLY,
        reason=(
            "The filter exists to answer 'is this content about the brand'. On a "
            "connected account that question is answered a priori by the OAuth grant "
            "— the client owns the media. Nothing is discarded, so none of the "
            "cascade's discard economics exist on this surface."
        ),
    ),
    StageApplicability(
        stage=CascadeStage.VISION,
        surface=ContentSurface.OWNED_MEDIA,
        verdict=Verdict.APPLIES_REPURPOSED,
        reason=(
            "Description is worth ~nothing: the client authored the video and already "
            "knows what is in it. The value is structured creative-feature extraction "
            "for cross-post comparison (hook type, on-screen text density, face "
            "presence, cut rate), which is a different prompt and a different output "
            "schema behind the same Provider seam. NOTES_fase0_agentive_layer.md §3.1."
        ),
    ),
    StageApplicability(
        stage=CascadeStage.TRANSCRIPTION,
        surface=ContentSurface.OWNED_MEDIA,
        verdict=Verdict.APPLIES_REPURPOSED,
        reason=(
            "Not brand-mention detection — the brand is the author. Repurposed as "
            "spoken-topic extraction (a creative feature joinable against platform "
            "analytics) and as subtitle/caption source text."
        ),
    ),
    StageApplicability(
        stage=CascadeStage.SENTIMENT,
        surface=ContentSurface.OWNED_MEDIA,
        verdict=Verdict.DOES_NOT_APPLY,
        reason=(
            "Polarity of a caption the client wrote themselves is an authored "
            "property, not a measurement of anything. Measuring it tells the client "
            "what they already decided."
        ),
    ),
    # --- owned_media_comments: the bridge ----------------------------------
    StageApplicability(
        stage=CascadeStage.FILTER,
        surface=ContentSurface.OWNED_MEDIA_COMMENTS,
        verdict=Verdict.DOES_NOT_APPLY,
        reason=_NO_VISUAL_TRACK,
    ),
    StageApplicability(
        stage=CascadeStage.VISION,
        surface=ContentSurface.OWNED_MEDIA_COMMENTS,
        verdict=Verdict.DOES_NOT_APPLY,
        reason=_NO_VISUAL_TRACK,
    ),
    StageApplicability(
        stage=CascadeStage.TRANSCRIPTION,
        surface=ContentSurface.OWNED_MEDIA_COMMENTS,
        verdict=Verdict.DOES_NOT_APPLY,
        reason=_NO_AUDIO_TRACK,
    ),
    StageApplicability(
        stage=CascadeStage.SENTIMENT,
        surface=ContentSurface.OWNED_MEDIA_COMMENTS,
        verdict=Verdict.APPLIES_UNCHANGED,
        reason=(
            "The composition point, and the only cell in this matrix that transfers "
            "with no change at all. robertuito is trained on Spanish social-media "
            "text and IG comments are in-distribution for it. Third-party audience "
            "voice, reachable with no scraping, no ClickHouse, no VLM and no GPU. "
            "docs/fase0-zernio-mercado.md §4.3."
        ),
    ),
    # --- mentioned_media: real earned media --------------------------------
    StageApplicability(
        stage=CascadeStage.FILTER,
        surface=ContentSurface.MENTIONED_MEDIA,
        verdict=Verdict.APPLIES_REPURPOSED,
        reason=(
            "The discard gate genuinely survives here: third-party mention volume is "
            "unbounded, and an @-mention proves only that the brand was NAMED, not "
            "that the media is worth a VLM pass. But the predicate changes from "
            "visual brand-relevance to enrichment-worthiness (author reach, spam and "
            "giveaway density, substantive vs drive-by), which lives in payload "
            "metadata and caption text rather than in pixels. So the architectural "
            "slot survives while siglip2 is the wrong instrument to fill it — free "
            "numeric predicates from the payload first, then a cheap text classifier, "
            "and only then the VLM."
        ),
    ),
    StageApplicability(
        stage=CascadeStage.VISION,
        surface=ContentSurface.MENTIONED_MEDIA,
        verdict=Verdict.APPLIES_UNCHANGED,
        reason=(
            "Genuine earned media authored by a third party. Describing what someone "
            "else showed about the brand is the Fase 1 visual-listening use case "
            "verbatim — this is the one surface where the cascade transfers wholesale, "
            "prompt and output schema included."
        ),
    ),
    StageApplicability(
        stage=CascadeStage.TRANSCRIPTION,
        surface=ContentSurface.MENTIONED_MEDIA,
        verdict=Verdict.APPLIES_UNCHANGED,
        reason=(
            "In-video/in-audio mention detection on third-party content, unchanged "
            "from Fase 1. What was said about the brand out loud is exactly the signal "
            "text-only listening tools miss."
        ),
    ),
    StageApplicability(
        stage=CascadeStage.SENTIMENT,
        surface=ContentSurface.MENTIONED_MEDIA,
        verdict=Verdict.APPLIES_REPURPOSED,
        reason=(
            "Applies to the caption text, but captions run longer than the "
            "tweet-length distribution robertuito was trained on. Treat polarity here "
            "as weaker evidence than on comments until measured against a golden set."
        ),
    ),
    # --- mentioned_comment: text-only earned media -------------------------
    StageApplicability(
        stage=CascadeStage.FILTER,
        surface=ContentSurface.MENTIONED_COMMENT,
        verdict=Verdict.DOES_NOT_APPLY,
        reason=_NO_VISUAL_TRACK,
    ),
    StageApplicability(
        stage=CascadeStage.VISION,
        surface=ContentSurface.MENTIONED_COMMENT,
        verdict=Verdict.DOES_NOT_APPLY,
        reason=_NO_VISUAL_TRACK,
    ),
    StageApplicability(
        stage=CascadeStage.TRANSCRIPTION,
        surface=ContentSurface.MENTIONED_COMMENT,
        verdict=Verdict.DOES_NOT_APPLY,
        reason=_NO_AUDIO_TRACK,
    ),
    StageApplicability(
        stage=CascadeStage.SENTIMENT,
        surface=ContentSurface.MENTIONED_COMMENT,
        verdict=Verdict.APPLIES_UNCHANGED,
        reason=(
            "Third-party text naming the brand, in robertuito's native distribution. "
            "Same cell as owned_media_comments, but this one is earned media about "
            "the brand rather than audience reaction to the brand's own post."
        ),
    ),
    # --- tags: earned media with the worst signal-to-volume ratio ----------
    StageApplicability(
        stage=CascadeStage.FILTER,
        surface=ContentSurface.TAGS,
        verdict=Verdict.APPLIES_REPURPOSED,
        reason=(
            "The gate matters MORE here than on mentioned_media. Tagging costs the "
            "tagger less effort than composing an @-mention, so bulk-tag, giveaway and "
            "spam density is higher and signal-to-volume is worse — this is the "
            "surface most able to run up a VLM bill on worthless content. Same "
            "instrument caveat as mentioned_media: the predicate is metadata and text, "
            "not pixels."
        ),
    ),
    StageApplicability(
        stage=CascadeStage.VISION,
        surface=ContentSurface.TAGS,
        verdict=Verdict.APPLIES_UNCHANGED,
        reason=(
            "Same Fase 1 use case as mentioned_media — third-party visual content "
            "about the brand — but with a lower prior that any given item is worth "
            "describing, which is what the gate above is for."
        ),
    ),
    StageApplicability(
        stage=CascadeStage.TRANSCRIPTION,
        surface=ContentSurface.TAGS,
        verdict=Verdict.APPLIES_UNCHANGED,
        reason="Third-party audio about the brand; identical to mentioned_media.",
    ),
    StageApplicability(
        stage=CascadeStage.SENTIMENT,
        surface=ContentSurface.TAGS,
        verdict=Verdict.APPLIES_REPURPOSED,
        reason=(
            "Caption-length text, same distribution caveat as mentioned_media, and a "
            "higher share of it is promotional boilerplate carrying no real polarity."
        ),
    ),
    # --- structurally unreachable -----------------------------------------
    StageApplicability(
        stage=CascadeStage.FILTER,
        surface=ContentSurface.COMPETITOR_CONTENT,
        verdict=Verdict.UNREACHABLE,
        reason=_UNREACHABLE,
    ),
    StageApplicability(
        stage=CascadeStage.VISION,
        surface=ContentSurface.COMPETITOR_CONTENT,
        verdict=Verdict.UNREACHABLE,
        reason=_UNREACHABLE,
    ),
    StageApplicability(
        stage=CascadeStage.TRANSCRIPTION,
        surface=ContentSurface.COMPETITOR_CONTENT,
        verdict=Verdict.UNREACHABLE,
        reason=_UNREACHABLE,
    ),
    StageApplicability(
        stage=CascadeStage.SENTIMENT,
        surface=ContentSurface.COMPETITOR_CONTENT,
        verdict=Verdict.UNREACHABLE,
        reason=_UNREACHABLE,
    ),
    StageApplicability(
        stage=CascadeStage.FILTER,
        surface=ContentSurface.UNAFFILIATED_CREATOR_CONTENT,
        verdict=Verdict.UNREACHABLE,
        reason=_UNREACHABLE,
    ),
    StageApplicability(
        stage=CascadeStage.VISION,
        surface=ContentSurface.UNAFFILIATED_CREATOR_CONTENT,
        verdict=Verdict.UNREACHABLE,
        reason=_UNREACHABLE,
    ),
    StageApplicability(
        stage=CascadeStage.TRANSCRIPTION,
        surface=ContentSurface.UNAFFILIATED_CREATOR_CONTENT,
        verdict=Verdict.UNREACHABLE,
        reason=_UNREACHABLE,
    ),
    StageApplicability(
        stage=CascadeStage.SENTIMENT,
        surface=ContentSurface.UNAFFILIATED_CREATOR_CONTENT,
        verdict=Verdict.UNREACHABLE,
        reason=_UNREACHABLE,
    ),
)


def profile_for(surface: ContentSurface) -> SurfaceProfile:
    """The modality/reachability profile of one surface."""
    for profile in SURFACE_PROFILES:
        if profile.surface is surface:
            return profile
    raise KeyError(f"No profile for surface {surface!r}")


def lookup(stage: CascadeStage, surface: ContentSurface) -> StageApplicability:
    """The verdict for one (stage, surface) pair."""
    for cell in APPLICABILITY:
        if cell.stage is stage and cell.surface is surface:
            return cell
    raise KeyError(f"No applicability entry for {stage!r} on {surface!r}")


def stages_for_surface(surface: ContentSurface) -> tuple[CascadeStage, ...]:
    """Stages that consume paid compute on this surface, in cascade order."""
    return tuple(cell.stage for cell in APPLICABILITY if cell.surface is surface and cell.billable)


def surfaces_for_stage(stage: CascadeStage) -> tuple[ContentSurface, ...]:
    """Surfaces on which this stage consumes paid compute."""
    return tuple(cell.surface for cell in APPLICABILITY if cell.stage is stage and cell.billable)


def oauth_reachable_surfaces() -> tuple[ContentSurface, ...]:
    """Surfaces a connected Instagram account can actually read."""
    return tuple(p.surface for p in SURFACE_PROFILES if p.oauth_reachable)


def requires_enrichment_gate(surface: ContentSurface) -> bool:
    """Whether unbounded third-party volume makes a pre-VLM discard gate necessary.

    True only for the third-party *media* surfaces. Owned media is bounded by
    the client's own publishing rate, and the text-only surfaces have no
    expensive stage to gate.
    """
    return surface in GATED_SURFACES
