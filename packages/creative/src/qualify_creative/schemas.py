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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    SlideSource,
    SlideText,
    VideoEffect,
    VideoEngine,
    VoiceProfileStatus,
    VoiceSourceKind,
)

# Meta renders these two in fixed-width slots; longer strings are truncated with an
# ellipsis in the ad unit, which reads as sloppy rather than as a design choice.
ADS_HEADLINE_MAX = 40
ADS_DESCRIPTION_MAX = 30
HOOK_MAX = 60
#: A hook and a CTA PRINTED on an image (the ad image, a template's outputs): what still
#: reads at a glance and fits the template's text ports (hook 60, cta 40) with room to
#: spare. Asked for in the prompt; the CTA came back at 46-57 characters without a
#: number to aim at (§ request 2026-10-08).
PRINTED_HOOK_MAX = 50
PRINTED_CTA_MAX = 32

#: A script is capped well below what the voice vendor reads in one request (Seed Speech
#: `byteplus_speech.MAX_TEXT_CHARS`), so a 60-second piece never gets near its limit.
SCRIPT_MAX = 2000
#: Target lengths a video / script can be asked for, in seconds.
DURATIONS_SECONDS = (15, 30, 45, 60)
#: Product images per brief — a carousel is at most 10 slides on Instagram.
MAX_PRODUCT_IMAGES = 10
#: Brand Kit elements (not the logo) one piece may draw on (§ request 2026-10-06).
MAX_BRAND_ELEMENTS = 6
AVATAR_PROMPT_MAX = 600
#: The scene an advertising image asks the image model for ("a hand holding the glass,
#: the bar blurred behind").
SCENE_PROMPT_MAX = 600
#: The price a composition prints (`MediaInputs.price_line`, ticket 24803289) — the
#: catalog's label, short enough for a pill or the template's `price_line` port.
PRICE_LINE_MAX = 40
#: HeyGen's avatar engines: IV is the more natural, III costs about a third for stock
#: avatars (pricing_data v2) — the operator picks per piece.
AVATAR_ENGINES = ("avatar_iv", "avatar_iii")
#: A carousel on Instagram is 2 to 10 items (the closing slide counts as one).
CAROUSEL_MIN_SLIDES = 2
CAROUSEL_MAX_SLIDES = 10
#: An animated carousel slide's length: Instagram plays a carousel video from 3 s, and
#: every Seedance family renders 5 and 10 (1.0 takes 2-12, 2.x 4-15).
SLIDE_SECONDS = (5, 10)


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
    #: Its R2 key and whether it is a logo ("logo") or another element ("element"):
    #: what lets a piece that CHOSE it (`MediaInputs.brand_logo_key` /
    #: `brand_element_keys`) be told its name and usage note. Never rendered in the
    #: cached prefix.
    key: str = ""
    kind: str = "element"


class BrandAccount(BaseModel):
    """One account the operator sorted — referente, competencia or detractor — with what
    the discovery learned about it (§ request 2026-10-06: the prompt carried only the
    handle, so the model knew WHO but not WHY). Every text is one line, already capped."""

    model_config = ConfigDict(frozen=True)

    handle: str  # "@name"
    network: str
    kind: str = ""  # creador | marca | medio
    why: str = ""  # the discovery's review of the account
    note: str = ""  # the operator's own note
    sample: str = ""  # their own words: a post (or the bio) as found


class BrandContext(BaseModel):
    """What the Brand Kit knows about the business beyond the kit itself (§ request
    2026-10-01): its rubro and location, its hashtags, the account as read, the
    brandboard's elements and the accounts it looks up to / competes with / does not
    want to resemble. Every field may be empty; an empty context renders nothing."""

    model_config = ConfigDict(frozen=True)

    sector: str = ""
    location: str = ""
    hashtags: tuple[str, ...] = ()
    account_bio: str = ""
    account_category: str = ""
    elements: tuple[BrandElement, ...] = ()
    referentes: tuple[BrandAccount, ...] = ()
    competitors: tuple[BrandAccount, ...] = ()
    detractors: tuple[BrandAccount, ...] = ()

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
                self.detractors,
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
    # No length cap on the stored script (founder, 2026-10-06): the operator writes as
    # much as the video needs. `SCRIPT_MAX` stays the GENERATION target (`render.py`) and
    # the cap of a script handed in for generation (`own_script`).
    script: str = ""
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


#: What a clip's reference image is for (§ request 2026-10-14): the client's real
#: product, the client's real place, or a look (light, framing, mood) to borrow.
CLIP_IMAGE_ROLES = ("product", "place", "style")

#: «Datos clave» (§ request 2026-10-14): how many facts a brief carries, and how long
#: a fact's name and value may be.
HIGHLIGHTS_MAX = 12
HIGHLIGHT_KEY_MAX = 40
HIGHLIGHT_VALUE_MAX = 200


class BriefConstraints(BaseModel):
    model_config = ConfigDict(frozen=True)

    must_mention: tuple[str, ...] = ()
    must_avoid: tuple[str, ...] = ()
    max_caption_chars: int | None = None
    #: «Datos clave»: facts the piece must feature exactly as the operator wrote them —
    #: the price, a discount, a date… — as (name, value) pairs, in the operator's order.
    highlights: tuple[tuple[str, str], ...] = ()

    @field_validator("highlights")
    @classmethod
    def _highlights_fit(cls, value: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
        if len(value) > HIGHLIGHTS_MAX:
            raise ValueError(f"at most {HIGHLIGHTS_MAX} highlights")
        for name, fact in value:
            if not name.strip() or not fact.strip():
                raise ValueError("a highlight needs a name and a value")
            if len(name) > HIGHLIGHT_KEY_MAX or len(fact) > HIGHLIGHT_VALUE_MAX:
                raise ValueError("highlight too long")
        return value


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


class CarouselSlide(BaseModel):
    """One slide of a `ContentKind.CAROUSEL`, in the order Instagram will show it.

    A generated or animated slide is a Seedream scene described by `scene_prompt` (empty:
    the brief's topic), with the brief's product photo `product_index` and its
    background as references; `text` is what is printed on it. An existing slide is the
    file `object_key` of a piece the brand already made — the producer checks it is one
    of this brand's before reading it, and reuses it as it is (no text added)."""

    model_config = ConfigDict(frozen=True)

    source: SlideSource
    scene_prompt: str = Field(default="", max_length=SCENE_PROMPT_MAX)
    product_index: int | None = Field(default=None, ge=0, lt=MAX_PRODUCT_IMAGES)
    use_background: bool = True
    text: SlideText = SlideText.NONE
    seconds: int = 5
    object_key: str | None = None
    #: An animated slide's motion reference (§ request 2026-10-19: «en la galería los
    #: videos solo para referencia»): a video whose camera and rhythm Seedance follows
    #: — never shown itself. Upload-store, piece or stock key.
    reference_video_key: str | None = None

    @model_validator(mode="after")
    def _source_has_its_inputs(self) -> CarouselSlide:
        if self.reference_video_key and self.source is not SlideSource.ANIMATED:
            raise ValueError("only an animated slide takes a reference video")
        if self.source is SlideSource.EXISTING:
            if not self.object_key:
                raise ValueError("an existing slide needs the piece's file")
            if self.text is not SlideText.NONE or self.scene_prompt.strip():
                raise ValueError("an existing slide is reused as it is: no text, no scene")
        elif self.source is SlideSource.STOCK:
            if not self.object_key:
                raise ValueError("a stock slide needs the stock video's file")
            if self.text is SlideText.NONE:
                # the words (and the logo) are what make it a new work, not stock alone
                raise ValueError("a stock slide always carries the hook or the CTA")
            if self.scene_prompt.strip():
                raise ValueError("a stock slide has no scene to describe")
        elif self.object_key:
            raise ValueError("only an existing slide points at a piece's file")
        if self.seconds not in SLIDE_SECONDS:
            raise ValueError(f"an animated slide lasts one of {SLIDE_SECONDS} seconds")
        return self


#: A clip's references (§ request 2026-10-14) — Seedance 2.x takes up to 9 images (the
#: frames count among them once there are references), 3 videos and 3 audio files.
CLIP_MAX_IMAGES = 9
CLIP_MAX_VIDEOS = 3
CLIP_MAX_AUDIOS = 3


PRODUCT_SOURCE_CATALOG = "catalog"
PRODUCT_SOURCE_STOCK = "stock"
PRODUCT_SOURCES = (PRODUCT_SOURCE_CATALOG, PRODUCT_SOURCE_STOCK)


class MediaInputs(BaseModel):
    """What the operator hands the generator besides the words — per `ContentKind`,
    every image optional unless the kind cannot work without it. Keys are the upload
    store's keys (`uploads/<tenant>/…`), never vendor URLs."""

    model_config = ConfigDict(frozen=True)

    background_key: str | None = None
    product_keys: tuple[str, ...] = Field(default=(), max_length=MAX_PRODUCT_IMAGES)
    #: Where the product's photos come from (stock plan R2, 2026-10-16): the brand's own
    #: (`catalog`: the catalog or an upload), or a stock image the operator chose to
    #: ILLUSTRATE the product (`stock`). Provenance only since 2026-10-19: the licence
    #: guard lets a `t/{tenant}/stock/…` key into `product_keys` either way.
    product_source: str = PRODUCT_SOURCE_CATALOG
    #: Flyer only: one slide per product instead of a single composed image.
    carousel: bool = False
    #: Target length of a script / video.
    duration_seconds: int = 30
    #: Avatar video: the voice that reads the script — `"brand"` (the brand's own cloned
    #: voice, resolved server-side) or a public Seed Speech voice id (§ 2026-10-16).
    #: `avatar_look_id` is the retired HeyGen library look, kept so old briefs still read.
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
    #: The retired HeyGen avatar engine (avatar_iv/iii) — kept so old briefs still read.
    engine: str = "avatar_iv"
    #: Which vendor renders the avatar kinds (§ request 2026-10-07; OmniHuman since
    #: 2026-10-16). HeyGen stays the default so a brief stored before then reads exactly
    #: as it was asked — and is refused as retired; the generator always sends the
    #: platform's engine (`QUALIFY_VIDEO_ENGINE`). With Seedance and OmniHuman there is no
    #: library look: the presenter is described (`avatar_prompt`) or animated from
    #: `avatar_image_key`, and Seedream composes it with the products and the background.
    video_engine: VideoEngine = VideoEngine.HEYGEN
    #: Advertising image only: what it is built from, and the scene the image model is
    #: asked for — Seedream renders it with those photos as references (2026-10-07).
    ad_mode: AdImageMode | None = None
    scene_prompt: str = Field(default="", max_length=SCENE_PROMPT_MAX)
    #: The price the composition PRINTS (a pill on the advertising image, the template's
    #: `price_line`) — ticket 24803289: always the catalog's label, set by the caller,
    #: never a model's words. "" prints nothing.
    price_line: str = Field(default="", max_length=PRICE_LINE_MAX)
    #: Template kind: the recipe the operator picked when they overrode the router's
    #: suggestion (plan-mvp-plantillas-remotion.md §3). Empty = let the router choose.
    template_id: str | None = None
    template_version: int | None = Field(default=None, ge=1)
    #: Template kind: render the template's VIDEO in the brief's format («Video
    #: publicitario», § 2026-10-13) rather than its still («Con plantilla»). A Reel is
    #: always the video, so a brief stored before this field existed reads the same.
    template_video: bool = False
    #: Resources of the Brand Kit chosen for THIS piece (§ request 2026-10-06) — apart
    #: from the background and the products: the logo goes where the brand mark goes (the
    #: template's and the flyer's logo slot, a corner of the avatar's scene), and each
    #: element is used as its own usage note says. R2 keys of the brand's assets.
    brand_logo_key: str | None = None
    brand_element_keys: tuple[str, ...] = Field(default=(), max_length=MAX_BRAND_ELEMENTS)
    #: Clip and Ad (§ request 2026-10-14): a video the operator gives as the piece's
    #: reference — its pace, framing and structure to follow. An upload-store key; kept
    #: on the brief so the draft records it. No engine reads it yet (Seedance 1.0 takes
    #: only a first frame; HeyGen, a look), so it changes nothing rendered today.
    reference_video_key: str | None = None
    #: Clip (§ request 2026-10-14): the frame the video starts on and the one it ends
    #: on, and what it follows — images, videos and audio. Upload-store or catalog keys.
    #: With any reference the clip goes to a Seedance 2.x model, which takes the frames
    #: only as described references (the API does not mix `first_frame` with them);
    #: with frames alone Seedance animates from the first towards the last.
    clip_first_frame_key: str | None = None
    clip_last_frame_key: str | None = None
    clip_image_keys: tuple[str, ...] = Field(default=(), max_length=CLIP_MAX_IMAGES)
    #: What each of `clip_image_keys` is (§ request 2026-10-14), in the same order:
    #: `CLIP_IMAGE_ROLES` — the client's product, its place, or a look to borrow. Empty
    #: means every one is the product (a brief from before the roles).
    clip_image_roles: tuple[str, ...] = Field(default=(), max_length=CLIP_MAX_IMAGES)
    clip_video_keys: tuple[str, ...] = Field(default=(), max_length=CLIP_MAX_VIDEOS)
    clip_audio_keys: tuple[str, ...] = Field(default=(), max_length=CLIP_MAX_AUDIOS)

    @property
    def clip_has_references(self) -> bool:
        return bool(self.clip_image_keys or self.clip_video_keys or self.clip_audio_keys)

    #: Carousel kind (§ request 2026-10-09): the slides in order, and whether a closing
    #: slide with the CTA on the brand gradient ends it (it counts toward the ten).
    slides: tuple[CarouselSlide, ...] = Field(default=(), max_length=CAROUSEL_MAX_SLIDES)
    closing_slide: bool = False

    @model_validator(mode="after")
    def _known_duration(self) -> MediaInputs:
        if self.product_source not in PRODUCT_SOURCES:
            raise ValueError(f"product_source must be one of {PRODUCT_SOURCES}")
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
        if media.template_video and self.kind is not ContentKind.TEMPLATE:
            raise ValueError("only a template renders a template video")
        clip_inputs = (
            media.clip_first_frame_key or media.clip_last_frame_key or media.clip_has_references
        )
        if clip_inputs and self.kind is not ContentKind.CLIP:
            raise ValueError("frames and references are for a clip")
        if self.kind is ContentKind.CLIP:
            if media.clip_last_frame_key and not media.clip_first_frame_key:
                raise ValueError("a clip's closing frame needs its opening frame")
            if media.clip_image_roles and len(media.clip_image_roles) != len(media.clip_image_keys):
                raise ValueError("a clip's image roles must match its images, one each")
            if any(role not in CLIP_IMAGE_ROLES for role in media.clip_image_roles):
                raise ValueError(f"a clip image's role is one of {CLIP_IMAGE_ROLES}")
            if media.clip_has_references:
                frames = int(bool(media.clip_first_frame_key)) + int(
                    bool(media.clip_last_frame_key)
                )
                if len(media.clip_image_keys) + frames > CLIP_MAX_IMAGES:
                    raise ValueError(
                        f"a clip takes at most {CLIP_MAX_IMAGES} images, frames included"
                    )
        heygen = media.video_engine is VideoEngine.HEYGEN
        if self.kind is ContentKind.AVATAR_VIDEO:
            if heygen and not media.voice_id:
                raise ValueError("an avatar video needs a voice")
            # A library look, or a custom synthetic person described by the operator. An
            # uploaded photo is not offered for a human presenter: that is a real person's
            # likeness, and HeyGen's photo mode asks nobody for consent.
            if media.avatar_source is AvatarSource.IMAGE:
                raise ValueError("a human avatar video cannot animate an uploaded photo")
            if media.avatar_source is AvatarSource.AI:
                if not media.avatar_prompt.strip():
                    raise ValueError("a custom human avatar needs a description")
            elif not heygen:
                # no library on Seedance nor OmniHuman: the presenter is always described
                raise ValueError("an avatar video needs the presenter's description")
            elif not media.avatar_look_id:
                raise ValueError("an avatar video needs an avatar look and a voice")
        if self.kind is ContentKind.ANIMATED_AVATAR_VIDEO:
            if heygen and not media.voice_id:
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
            if media.ad_mode is not None:
                raise ValueError("an ad mode is for the advertising image")
            # ticket 24803289: a template may also start from a generated scene (the
            # angle's), which becomes its first photo; any other kind has no scene
            if media.scene_prompt.strip() and self.kind is not ContentKind.TEMPLATE:
                raise ValueError("a scene is for the advertising image or a template")
        elif media.ad_mode is not None:
            if media.ad_mode.needs_product and not media.product_keys:
                raise ValueError(f"an ad image built from {media.ad_mode} needs a product photo")
            if media.ad_mode.needs_background and not media.background_key:
                raise ValueError(f"an ad image built from {media.ad_mode} needs a background")
        if self.kind is ContentKind.CAROUSEL:
            total = len(media.slides) + int(media.closing_slide)
            if not CAROUSEL_MIN_SLIDES <= total <= CAROUSEL_MAX_SLIDES:
                raise ValueError(
                    f"a carousel has {CAROUSEL_MIN_SLIDES} to {CAROUSEL_MAX_SLIDES} slides,"
                    f" not {total}"
                )
            for slide in media.slides:
                if slide.product_index is not None and slide.product_index >= len(
                    media.product_keys
                ):
                    raise ValueError("a slide names a product photo the brief does not have")
        elif media.slides or media.closing_slide:
            raise ValueError("slides are for the carousel")
        if media.own_script.strip() and not self.kind.is_video:
            raise ValueError("an own script is for the avatar videos")
        if media.carousel and not self.format.is_feed:
            raise ValueError("a carousel is a feed post (4:5 or 1:1)")
        if self.format not in self.kind.formats:
            raise ValueError(f"format {self.format} is not offered for {self.kind}")
        return self

    @property
    def wants_template_video(self) -> bool:
        """A template brief asks for the template's video: a Reel always does, any other
        format when `template_video` says so."""
        return self.format is ContentFormat.REELS_9_16 or self.media.template_video

    @property
    def requires_ai_disclosure(self) -> bool:
        """Travels with the artifact to the ads module: forgetting the label is the
        third-largest cause of Meta ad rejections.

        This is the A PRIORI answer, from the brief alone. The draft's stored flag is
        recomputed after every generation from the media actually made (PR #100 review,
        `MediaWrite.ai_generated`): a flyer stored before `ad_mode` existed is still
        rendered by Seedream when it is wired — the producer infers the mode — and only
        the producer's output can say so."""
        # an advertising image with a mode is GENERATED by Seedream since 2026-10-07: its
        # photograph is AI imagery even though the product in it is the operator's
        generated_ad = self.kind is ContentKind.STATIC_FLYER and self.media.ad_mode is not None
        # a carousel's generated and animated slides are Seedream / Seedance imagery
        generated_slides = any(slide.source.is_generated for slide in self.media.slides)
        return (
            self.image_route.requires_ai_disclosure
            or self.kind.requires_ai_disclosure
            or generated_ad
            or generated_slides
        )


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
