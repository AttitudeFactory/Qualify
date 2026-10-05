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
    AdImageMode,
    AvatarSource,
    BriefIntent,
    BriefObjective,
    ContentFormat,
    ContentKind,
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

#: HeyGen reads at most 5,000 characters per video (`heygen_video.MAX_SCRIPT_CHARS`); a
#: script is capped well below it so a 60-second piece never gets near the vendor limit.
SCRIPT_MAX = 2000
#: Target lengths a video / script can be asked for, in seconds.
DURATIONS_SECONDS = (15, 30, 45, 60)
#: Product images per brief — a carousel is at most 10 slides on Instagram.
MAX_PRODUCT_IMAGES = 10
AVATAR_PROMPT_MAX = 600
#: The scene an advertising image asks the image model for ("a hand holding the glass,
#: the bar blurred behind").
SCENE_PROMPT_MAX = 600
#: HeyGen's avatar engines: IV is the more natural, III costs about a third for stock
#: avatars (pricing_data v2) — the operator picks per piece.
AVATAR_ENGINES = ("avatar_iv", "avatar_iii")


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
    #: The brand's type faces by family name ("" = not declared): headlines and body copy.
    font_heading: str = ""
    font_body: str = ""
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


class BrandElement(BaseModel):
    """One element of the brandboard, as the operator described it (a logo version, a
    mascot, a pattern...): what it is and when to use it."""

    model_config = ConfigDict(frozen=True)

    name: str
    context: str = ""


class BrandContext(BaseModel):
    """What the Brand Kit knows about the business beyond the kit itself (§ request
    2026-10-01): its rubro and location, its hashtags, the account as read, the
    brandboard's elements and the accounts it looks up to / competes with. Every field
    may be empty; an empty context renders nothing."""

    model_config = ConfigDict(frozen=True)

    sector: str = ""
    location: str = ""
    hashtags: tuple[str, ...] = ()
    account_bio: str = ""
    account_category: str = ""
    elements: tuple[BrandElement, ...] = ()
    referentes: tuple[str, ...] = ()
    competitors: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.sector,
                self.location,
                self.hashtags,
                self.account_bio,
                self.account_category,
                self.elements,
                self.referentes,
                self.competitors,
            )
        )


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


class ScriptShot(BaseModel):
    """One shot of a script for a real creator: what the camera shows and what is said
    over it. The avatar kinds do not use shots — HeyGen reads `CopyPayload.script`."""

    model_config = ConfigDict(frozen=True)

    visual: str
    line: str = ""
    seconds: int = Field(default=5, ge=1, le=60)


class CopyPayload(BaseModel):
    """The artifact that leaves the module. Frozen on purpose: if a downstream consumer
    could mutate it, the provenance recorded alongside would stop meaning anything.

    `script` / `shots` are the libreto of the video kinds (`ContentKind.has_script`):
    the spoken text, whole, and — for a real creator — the shot list it is recorded
    from. Empty for a flyer."""

    model_config = ConfigDict(frozen=True)

    hook: str = Field(max_length=HOOK_MAX)
    caption: str
    hashtags: tuple[str, ...] = ()
    cta: str = ""
    script: str = Field(default="", max_length=SCRIPT_MAX)
    shots: tuple[ScriptShot, ...] = ()

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


class MediaInputs(BaseModel):
    """What the operator hands the generator besides the words — per `ContentKind`,
    every image optional unless the kind cannot work without it. Keys are the upload
    store's keys (`uploads/<tenant>/…`), never vendor URLs."""

    model_config = ConfigDict(frozen=True)

    background_key: str | None = None
    product_keys: tuple[str, ...] = Field(default=(), max_length=MAX_PRODUCT_IMAGES)
    #: Flyer only: one slide per product instead of a single composed image.
    carousel: bool = False
    #: Target length of a script / video.
    duration_seconds: int = 30
    #: Avatar video: the HeyGen library look and the voice that reads the script.
    avatar_look_id: str | None = None
    voice_id: str | None = None
    #: Animated avatar: generated from `avatar_prompt`, or animated from
    #: `avatar_image_key`.
    avatar_source: AvatarSource | None = None
    avatar_prompt: str = Field(default="", max_length=AVATAR_PROMPT_MAX)
    avatar_image_key: str | None = None
    #: The operator confirmed they may animate the uploaded image (it is not a photo of
    #: a real person used without consent — HeyGen's photo mode asks nobody).
    avatar_rights_confirmed: bool = False
    #: The operator's own script for a video — read word for word instead of Claude's.
    own_script: str = Field(default="", max_length=SCRIPT_MAX)
    #: HeyGen engine for an avatar subject (an image subject always runs Avatar IV).
    engine: str = "avatar_iv"
    #: Advertising image only: what it is built from, and the scene the image model is
    #: asked for. Stored with the brief today; rendered once the model is wired.
    ad_mode: AdImageMode | None = None
    scene_prompt: str = Field(default="", max_length=SCENE_PROMPT_MAX)
    #: Template kind: the recipe the operator picked when they overrode the router's
    #: suggestion (plan-mvp-plantillas-remotion.md §3). Empty = let the router choose.
    template_id: str | None = None
    template_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _known_duration(self) -> MediaInputs:
        if self.duration_seconds not in DURATIONS_SECONDS:
            raise ValueError(f"duration_seconds must be one of {DURATIONS_SECONDS}")
        if self.engine not in AVATAR_ENGINES:
            raise ValueError(f"engine must be one of {AVATAR_ENGINES}")
        return self


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
    kind: ContentKind = ContentKind.STATIC_FLYER
    media: MediaInputs = MediaInputs()

    @model_validator(mode="after")
    def _upload_routes_need_media(self) -> ContentBrief:
        """A route that treats the operator's own photo, without a photo, is a brief that
        cannot be executed. Caught at construction rather than three layers down inside
        the router, after a credential has been resolved."""
        if self.image_route.needs_source_media and not self.source_media_key:
            raise ValueError(f"image_route {self.image_route} requires source_media_key")
        return self

    @model_validator(mode="after")
    def _kind_has_its_inputs(self) -> ContentBrief:
        """Each kind's required inputs, checked before anything is stored or paid for."""
        media = self.media
        if not self.kind.enabled:
            raise ValueError(f"content kind {self.kind} is not available yet")
        if self.kind is ContentKind.TEMPLATE and not media.product_keys:
            # Rule 6 of the recipe router is "nothing applies → the product's main photo":
            # a template with zero real photos is a generated image, which is the one
            # thing this kind exists not to be.
            raise ValueError("a template needs at least one product photo")
        if self.kind is ContentKind.AVATAR_VIDEO:
            if not media.voice_id:
                raise ValueError("an avatar video needs a voice")
            # A library look, or a custom synthetic person described by the operator. An
            # uploaded photo is not offered for a human presenter: that is a real person's
            # likeness, and HeyGen's photo mode asks nobody for consent.
            if media.avatar_source is AvatarSource.IMAGE:
                raise ValueError("a human avatar video cannot animate an uploaded photo")
            if media.avatar_source is AvatarSource.AI:
                if not media.avatar_prompt.strip():
                    raise ValueError("a custom human avatar needs a description")
            elif not media.avatar_look_id:
                raise ValueError("an avatar video needs an avatar look and a voice")
        if self.kind is ContentKind.ANIMATED_AVATAR_VIDEO:
            if not media.voice_id:
                raise ValueError("an animated avatar video needs a voice")
            if media.avatar_source is AvatarSource.AI and not media.avatar_prompt.strip():
                raise ValueError("an AI-generated avatar needs a description")
            if media.avatar_source is AvatarSource.IMAGE:
                if not media.avatar_image_key:
                    raise ValueError("an animated avatar from an image needs the image")
                if not media.avatar_rights_confirmed:
                    raise ValueError("animating an image needs the rights confirmation")
            if media.avatar_source is None:
                raise ValueError("an animated avatar needs its source: ai or image")
        if media.carousel and self.kind is not ContentKind.STATIC_FLYER:
            raise ValueError("only a flyer can be a carousel")
        if self.kind is not ContentKind.STATIC_FLYER:
            if media.ad_mode is not None or media.scene_prompt.strip():
                raise ValueError("an ad mode and a scene are for the advertising image")
        elif media.ad_mode is not None:
            if media.ad_mode.needs_product and not media.product_keys:
                raise ValueError(f"an ad image built from {media.ad_mode} needs a product photo")
            if media.ad_mode.needs_background and not media.background_key:
                raise ValueError(f"an ad image built from {media.ad_mode} needs a background")
        if media.own_script.strip() and not self.kind.is_video:
            raise ValueError("an own script is for the avatar videos")
        if media.carousel and not self.format.is_feed:
            raise ValueError("a carousel is a feed post (4:5 or 1:1)")
        if self.format not in self.kind.formats:
            raise ValueError(f"format {self.format} is not offered for {self.kind}")
        return self

    @property
    def requires_ai_disclosure(self) -> bool:
        """Travels with the artifact to the ads module: forgetting the label is the
        third-largest cause of Meta ad rejections."""
        return self.image_route.requires_ai_disclosure or self.kind.requires_ai_disclosure


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
