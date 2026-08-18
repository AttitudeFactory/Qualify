"""The contracts of the Brand Content Engine.

`CopyPayload` is the one that leaves the module: publishing and the future ads module
both consume it, which is why it is structured rather than a caption blob. An ad renders
primary text, headline and description in three different slots — handing downstream a
single string would force it to re-generate, losing the voice guarantee that is the whole
point of the engine.

Everything here is pure: no database, no clock, no network. Serialization is deterministic
so `render_prompt` can rely on byte-identical output for the cacheable prefix.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from qualify_creative.enums import (
    BriefIntent,
    BriefObjective,
    ContentFormat,
    ContentType,
    EmojiPolicy,
    ImageRoute,
    Platform,
    VideoEffect,
    VoiceProfileStatus,
    VoiceSourceKind,
)

# Meta renders these two in fixed-width slots; longer strings are truncated with an
# ellipsis in the ad unit, which reads as sloppy rather than as a design choice.
ADS_HEADLINE_MAX = 40
ADS_DESCRIPTION_MAX = 30
HOOK_MAX = 60


class ToneAxes(BaseModel):
    """Numeric rather than adjectives. "Warm but professional" cannot be scored; a point
    on an axis can, which is what the fidelity judge needs to compare against."""

    model_config = ConfigDict(frozen=True)

    formal_casual: int = Field(ge=0, le=100)
    sober_enthusiastic: int = Field(ge=0, le=100)
    technical_plain: int = Field(ge=0, le=100)
    brief_elaborate: int = Field(ge=0, le=100)


class HashtagPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum: int = Field(default=0, ge=0)
    maximum: int = Field(default=10, ge=0)
    always: tuple[str, ...] = ()
    never: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _range_is_sane(self) -> HashtagPolicy:
        if self.minimum > self.maximum:
            raise ValueError("hashtag policy minimum cannot exceed maximum")
        return self


class LengthTargets(BaseModel):
    model_config = ConfigDict(frozen=True)

    caption_min_chars: int = Field(default=80, ge=0)
    caption_max_chars: int = Field(default=600, ge=1)


class ImagePolicy(BaseModel):
    """Which image routes this brand may use at all. Enforced by layer 1 of the fidelity
    gate BEFORE a vendor is called, so a blocked route costs nothing rather than being
    caught after the money is spent. For a food brand, `GENERATE` of the product is
    blocked here as policy — not left to whoever writes the brief that day."""

    model_config = ConfigDict(frozen=True)

    allowed_routes: frozenset[ImageRoute] = frozenset(
        {ImageRoute.TEMPLATE_ONLY, ImageRoute.FROM_UPLOAD}
    )
    blocked_reason: dict[ImageRoute, str] = Field(default_factory=dict)

    def allows(self, route: ImageRoute) -> bool:
        return route in self.allowed_routes

    def reason_for(self, route: ImageRoute) -> str:
        """Why a route is unavailable. The UI shows blocked routes disabled WITH the
        reason rather than hiding them — a missing option invites the question, a
        disabled one with an explanation answers it."""
        return self.blocked_reason.get(route, "No habilitada para esta marca.")


class BrandKit(BaseModel):
    """What the operator declares about their brand. One per tenant (D14)."""

    model_config = ConfigDict(frozen=True)

    brand_id: UUID
    positioning: str
    audience: str
    language: str = "es"
    regional_variant: str = "es-CO"
    tone_axes: ToneAxes
    do_examples: tuple[str, ...] = ()
    dont_examples: tuple[str, ...] = ()
    banned_words: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    emoji_policy: EmojiPolicy = EmojiPolicy.SPARSE
    hashtag_policy: HashtagPolicy = HashtagPolicy()
    cta_patterns: tuple[str, ...] = ()
    length_targets: LengthTargets = LengthTargets()
    palette_rgb: tuple[str, ...] = ()
    logo_asset_key: str | None = None
    template_asset_key: str | None = None
    reference_image_keys: tuple[str, ...] = Field(default=(), max_length=14)
    image_policy: ImagePolicy = ImagePolicy()


class VoiceSource(BaseModel):
    """Provenance of one inference in the distilled profile. A voice profile without
    sources is an opinion, and an opinion propagates silently into every piece the brand
    ever publishes."""

    model_config = ConfigDict(frozen=True)

    kind: VoiceSourceKind
    ref: str
    excerpt: str


class BrandVoiceProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    brand_id: UUID
    version: int = Field(ge=1)
    status: VoiceProfileStatus
    tone_axes: ToneAxes
    lexicon: tuple[str, ...] = ()
    avoid_lexicon: tuple[str, ...] = ()
    sentence_rhythm: str = ""
    signature_moves: tuple[str, ...] = ()
    sources: tuple[VoiceSource, ...] = ()
    distilled_by_model: str = ""
    distilled_at: datetime | None = None


class CopyPayload(BaseModel):
    """The artifact that leaves the module. Frozen on purpose: if a downstream consumer
    could mutate it, the provenance recorded alongside would stop meaning anything."""

    model_config = ConfigDict(frozen=True)

    hook: str = Field(max_length=HOOK_MAX)
    caption: str
    hashtags: tuple[str, ...] = ()
    cta: str = ""

    ads_primary_text: str | None = None
    ads_headline: str | None = Field(default=None, max_length=ADS_HEADLINE_MAX)
    ads_description: str | None = Field(default=None, max_length=ADS_DESCRIPTION_MAX)
    ads_cta_type: str | None = None

    def rendered_caption(self) -> str:
        """The organic string as it would be pasted. Defined once, here, so the UI, the
        export and the publisher cannot drift into three different concatenations."""
        tags = " ".join(f"#{tag.lstrip('#')}" for tag in self.hashtags)
        blocks = [self.hook, self.caption, self.cta, tags]
        return "\n\n".join(block for block in blocks if block)


class BriefConstraints(BaseModel):
    model_config = ConfigDict(frozen=True)

    must_mention: tuple[str, ...] = ()
    must_avoid: tuple[str, ...] = ()
    max_caption_chars: int | None = None


class TextOverlay(BaseModel):
    """A timed text card over the operator's own footage. Fixed slots rather than a
    timeline: a timeline editor is a product in itself, and start/duration/fade covers
    the promotional Reel this module actually needs to produce."""

    model_config = ConfigDict(frozen=True)

    text: str
    start_seconds: float = Field(ge=0)
    duration_seconds: float = Field(gt=0)
    fade_seconds: float = Field(default=0.3, ge=0)


class VideoPlan(BaseModel):
    """Declared BEFORE processing, previewable, and re-runnable at zero cost because
    every step is deterministic ffmpeg over footage that already exists."""

    model_config = ConfigDict(frozen=True)

    source_media_key: str
    effects: tuple[VideoEffect, ...] = ()
    trim_seconds: float | None = Field(default=None, gt=0)
    overlays: tuple[TextOverlay, ...] = ()
    intro_card: bool = False
    outro_card: bool = False


class ContentBrief(BaseModel):
    """The operator's request. Short on purpose: the value sits in the brand substrate,
    not in making them fill twenty fields."""

    model_config = ConfigDict(frozen=True)

    brand_id: UUID
    objective: BriefObjective
    content_type: ContentType = ContentType.PRODUCT
    topic: str
    product_ref: str | None = None
    platform: Platform = Platform.INSTAGRAM
    format: ContentFormat = ContentFormat.FEED_4_5
    intent: BriefIntent = BriefIntent.ORGANIC
    image_route: ImageRoute = ImageRoute.FROM_UPLOAD
    source_media_key: str | None = None
    video_plan: VideoPlan | None = None
    constraints: BriefConstraints = BriefConstraints()
    variants_requested: int = Field(default=3, ge=1, le=5)

    @model_validator(mode="after")
    def _upload_routes_need_media(self) -> ContentBrief:
        """A route that treats the operator's own photo, without a photo, is a brief that
        cannot be executed. Caught at construction rather than three layers down inside
        the router, after a credential has been resolved."""
        if self.image_route.needs_source_media and not self.source_media_key:
            raise ValueError(f"image_route {self.image_route} requires source_media_key")
        return self

    @property
    def requires_ai_disclosure(self) -> bool:
        """Travels with the artifact to the ads module: forgetting the label is the
        third-largest cause of Meta ad rejections."""
        return self.image_route.requires_ai_disclosure


class HardFailure(BaseModel):
    """A layer-1 rejection: deterministic, explainable, and not overridable by a human.
    A forbidden claim is not a matter of taste."""

    model_config = ConfigDict(frozen=True)

    rule: str
    detail: str


class FidelityVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    passed: bool
    hard_failures: tuple[HardFailure, ...] = ()
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    judged_by_model: str | None = None
