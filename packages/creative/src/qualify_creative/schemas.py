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
from decimal import Decimal
from typing import Literal, get_args
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from qualify_creative.ad_destination import (
    AdCTA,
    normalize_legacy_ad_cta,
    validate_ad_destination_url,
)
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
DURATIONS_SECONDS = (5, 10, 15, 30, 45, 60)
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
#: A Galería slide (CM-6, m-24955927): who the medium belongs to — the business
#: (`business_media`) or one of its products (`product_media`).
GALLERY_ORIGIN_BUSINESS = "business"
GALLERY_ORIGIN_PRODUCT = "product"
GALLERY_ORIGINS = (GALLERY_ORIGIN_BUSINESS, GALLERY_ORIGIN_PRODUCT)
#: The longest stretch of a Galería video a slide takes: what Instagram plays in a
#: carousel (and the longest business video Galería keeps, D2).
GALLERY_SEGMENT_MAX_MS = 60_000
#: An animated carousel slide's length: Instagram plays a carousel video from 3 s, and
#: every Seedance family renders 5 and 10 (1.0 takes 2-12, 2.x 4-15).
SLIDE_SECONDS = (5, 10)
#: A part of a video by parts (ADR 44, VE-06; founder 2026-11-04): its length in the
#: joined video, 1 to 10 whole seconds (10 = the per-video ceiling, D5) — whole so the
#: `edit` cut keeps its ±0.5 s check.
PART_SECONDS = range(1, 11)
#: Seedance 2.x makes no video shorter than 4 s (`SeedanceFamily.min_seconds`): a part of
#: 1-3 s is GENERATED at 4 s and trimmed to its length at the join (VE-07's `JoinClip`).
PART_GENERATION_MIN_SECONDS = 4
#: The lengths a part's child clip asks Seedance for: `max(part, 4)`, so 4 to 10.
PART_GENERATION_SECONDS = range(PART_GENERATION_MIN_SECONDS, PART_SECONDS.stop)
#: How far a part's trim may differ from its whole seconds (a cut is rarely whole).
PART_TRIM_TOLERANCE_S = 0.5
#: Parts per video by parts; `content_drafts.part_index` is 1..PARTS_MAX (migration 0119).
PARTS_MAX = 6
#: UI-4: the parts a parent may keep aside (`MediaInputs.parts_removed`) — the plan's own
#: plus as many parts added by hand and removed again; removed parts take no active place.
PARTS_REMOVED_MAX = PARTS_MAX * 2
#: How a part is made: `reference` (new, from the product photos and the shot's sheet, no
#: bytes of the original reel), `edit` (the original's window with the product in it),
#: `extend` (continues the previous part — never the first one).
PART_MODES = ("reference", "edit", "extend")
#: The longest description a part keeps (what the part shows), as long as a scene.
PART_DESCRIPTION_MAX = 600


class ToneAxes(BaseModel):
    """Numeric rather than adjectives. "Warm but professional" cannot be scored; a point
    on an axis can, which is what the fidelity judge needs to compare against."""

    model_config = ConfigDict(frozen=True)

    formal_casual: int = Field(ge=0, le=100)
    sober_enthusiastic: int = Field(ge=0, le=100)
    technical_plain: int = Field(ge=0, le=100)
    brief_elaborate: int = Field(ge=0, le=100)


#: m-25026376: what Meta's API accepts per post (IG User Media `caption`: 30 hashtags).
#: The one hard cap — the editor (`Qualify.creative_vm.HASHTAG_LIMIT`) and the owner's
#: edit (`ContentService.edit_variant`) both read it from here.
HASHTAG_HARD_LIMIT = 30


class HashtagPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum: int = Field(default=0, ge=0)
    # m-25026376 (founder, 2026-11-13): five well-chosen tags unless the brand says
    # otherwise. Only the default moves: a policy the brand saved keeps its own maximum.
    maximum: int = Field(default=5, ge=0)
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


#: The longest type face name a prompt carries — a family name is short (`BrandKit.typeface`).
TYPEFACE_MAX = 60


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
    #: Declared by the owner; a default for new ad pieces, never an LLM-generated URL.
    ads_destination_url: str | None = None

    @field_validator("ads_destination_url")
    @classmethod
    def _ad_destination(cls, value: str | None) -> str | None:
        return validate_ad_destination_url(value)

    @property
    def typeface(self) -> str:
        """The brand's ONE type face, as every generation prompt names it ("" = none).
        The Brand Kit asks a single family and stores it in both columns
        (`set_kit_font_heading`); a kit saved when it asked two keeps its headline face.
        One line, at most `TYPEFACE_MAX` characters: the kit stores no cap."""
        for face in (self.font_heading, self.font_body):
            name = " ".join(face.split())[:TYPEFACE_MAX].strip()
            if name:
                return name
        return ""


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
    ads_cta_type: AdCTA | None = None
    ads_destination_url: str | None = None

    @field_validator("ads_cta_type", mode="before")
    @classmethod
    def _ad_cta(cls, value: object, info: ValidationInfo) -> object:
        # Existing snapshots carried arbitrary free text. New model/editor inputs
        # opt into strict validation; reading a snapshot only projects a safe enum.
        if (info.context or {}).get("strict_ad_cta"):
            return value
        return normalize_legacy_ad_cta(value)

    @field_validator("ads_destination_url")
    @classmethod
    def _ad_destination(cls, value: str | None) -> str | None:
        return validate_ad_destination_url(value)

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
    #: When `product_index` is an inspiration GUIDE (role «composition», live test
    #: 2026-11-03), the product photo that appears in the slide — chosen by the owner
    #: among the gallery's product photos. None (every brief before it): the guide
    #: pairs with the only product photo, and with several it is refused, as before.
    guide_product_index: int | None = Field(default=None, ge=0, lt=MAX_PRODUCT_IMAGES)
    use_background: bool = True
    text: SlideText = SlideText.NONE
    seconds: int = 5
    object_key: str | None = None
    #: An animated slide's motion reference (§ request 2026-10-19: «en la galería los
    #: videos solo para referencia»): a video whose camera and rhythm Seedance follows
    #: — never shown itself. Upload-store, piece or stock key.
    reference_video_key: str | None = None
    #: An animated slide with the sound Seedance makes for it (§ request 2026-10-23:
    #: «generar el clip con audio, igual la galería») — ambience and voices, kept through
    #: the fitter and the draft's final. Off: silent, as every slide was before. On a
    #: Galería video slide (CM-6): the video's own sound kept — the owner's choice
    #: («Usar el sonido de tus videos», off by default, D6), never for a product's video.
    audio: bool = False
    #: A Galería slide (CM-6, m-24955927): whose medium it is (`GALLERY_ORIGINS`) and its
    #: id — `object_key` is that medium's file as it was chosen; the producer checks the
    #: medium is still this brand's and live before reading it.
    gallery_origin: str | None = None
    gallery_media_id: UUID | None = None
    #: A Galería VIDEO slide: the stretch of the video it shows, in ms from its start,
    #: chosen by `qualify_api.creative.gallery_piece.select_segment` (D2) and kept with
    #: the piece (provenance). None on a photo and on every other slide.
    segment_start_ms: int | None = Field(default=None, ge=0)
    segment_end_ms: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _source_has_its_inputs(self) -> CarouselSlide:
        if self.guide_product_index is not None and self.product_index is None:
            raise ValueError("a guide's product photo goes with the slide's guide photo")
        if self.reference_video_key and self.source is not SlideSource.ANIMATED:
            raise ValueError("only an animated slide takes a reference video")
        if self.audio and self.source not in (SlideSource.ANIMATED, SlideSource.GALLERY):
            raise ValueError("only an animated or a Galería slide has sound of its own")
        gallery_fields = (
            self.gallery_origin is not None
            or self.gallery_media_id is not None
            or self.segment_start_ms is not None
            or self.segment_end_ms is not None
        )
        if gallery_fields and self.source is not SlideSource.GALLERY:
            raise ValueError("only a Galería slide names a Galería medium")
        if self.source is SlideSource.GALLERY:
            self._gallery_slide_is_whole()
        elif self.source is SlideSource.EXISTING:
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

    def _gallery_slide_is_whole(self) -> None:
        """A Galería slide (CM-6) is the owner's medium as it is: its file, whose it is,
        its id; the stretch of a video both ends or neither; no words, scene or photo."""
        if not self.object_key:
            raise ValueError("a Galería slide needs the medium's file")
        if self.gallery_origin not in GALLERY_ORIGINS or self.gallery_media_id is None:
            raise ValueError(f"a Galería slide names its medium: one of {GALLERY_ORIGINS}")
        if (
            self.text is not SlideText.NONE
            or self.scene_prompt.strip()
            or self.product_index is not None
            or self.guide_product_index is not None
        ):
            raise ValueError("a Galería slide is used as it is: no text, no scene, no photo")
        if (self.segment_start_ms is None) != (self.segment_end_ms is None):
            raise ValueError("a Galería video's stretch has both ends or neither")
        if self.segment_start_ms is not None and self.segment_end_ms is not None:
            if self.segment_end_ms <= self.segment_start_ms:
                raise ValueError("a Galería video's stretch ends after it starts")
            if self.segment_end_ms - self.segment_start_ms > GALLERY_SEGMENT_MAX_MS:
                raise ValueError("a carousel plays at most 60 s of a video")
        if self.audio and self.gallery_origin == GALLERY_ORIGIN_PRODUCT:
            raise ValueError("a product's video always goes without sound (D3)")


#: A clip's references (§ request 2026-10-14) — Seedance 2.x takes up to 9 images (the
#: frames count among them once there are references), 3 videos and 3 audio files.
CLIP_MAX_IMAGES = 9
CLIP_MAX_VIDEOS = 3
CLIP_MAX_AUDIOS = 3


PRODUCT_SOURCE_CATALOG = "catalog"
PRODUCT_SOURCE_STOCK = "stock"
PRODUCT_SOURCES = (PRODUCT_SOURCE_CATALOG, PRODUCT_SOURCE_STOCK)


class SourceReelProvenance(BaseModel):
    """m-24820837: the reel a «copiar» replica was made from, as the brief keeps it. The
    discovery card lives only in the browser session and the original reel can be forgotten
    from one week's list to the next; stored with the brief, the piece still names its
    origin later. `platform` is the network value of the card (`instagram`, `tiktok`,
    `facebook`), `post_id` the network's own id, `handle` the account's with its `@`,
    `analysis_version` the replication pipeline that read the reel (raised when the
    pipeline changes, so a piece records the analysis that made it)."""

    model_config = ConfigDict(frozen=True)

    platform: str = Field(max_length=20)
    post_id: str = Field(max_length=120)
    url: str = Field(default="", max_length=500)
    handle: str = Field(default="", max_length=120)
    analysis_version: int = Field(default=1, ge=1)


class SourcePinProvenance(BaseModel):
    """The explicitly selected Pin behind one imported image, never its CDN URL.

    `board_owner` identifies the account owning the selected board; Pinterest does not
    establish that it created the image. Provenance stays with the brief's own image.
    """

    model_config = ConfigDict(frozen=True)

    image_key: str = Field(min_length=1, max_length=1024)
    pin_id: str = Field(pattern=r"^[0-9]+$", max_length=120)
    board_id: str = Field(pattern=r"^[0-9]+$", max_length=120)
    url: str = Field(max_length=500)
    board_owner: str = Field(default="", max_length=120)
    import_version: int = Field(default=1, ge=1, le=1)

    @model_validator(mode="after")
    def _canonical_origin(self) -> SourcePinProvenance:
        if self.url != f"https://www.pinterest.com/pin/{self.pin_id}/":
            raise ValueError("a Pinterest reference names its canonical Pin URL")
        return self


PartMode = Literal["reference", "edit", "extend"]
#: What the plan learned about a part that the owner should read before creating it
#: (VE-08, from the VE-04c UX review; UI-3 renders them, `qualify_api.creative.parts`
#: holds the Spanish text): `people_unclear` — the analysis could not tell whether a
#: person is in it, so it is made new and never «Igual al original»; `describe_it` — the
#: analysis could not see what happens in it, so the owner says it.
PartNotice = Literal["people_unclear", "describe_it"]
PART_NOTICES = ("people_unclear", "describe_it")


class _PartSource(BaseModel):
    """What a part of a video by parts is made from (ADR 44): its mode and, when it comes
    from an analysed reel, the consecutive cuts it covers and the interval kept at the
    join. Shared by the parent's plan entry and the child's reference to it."""

    model_config = ConfigDict(frozen=True)

    mode: PartMode = "reference"
    #: The mode originally assigned by the plan; retained on children as provenance.
    #: A converted split tail remains identifiable after an explicit mode change.
    original_mode: PartMode | None = None
    #: The part's length IN THE JOINED VIDEO, whole seconds (`PART_SECONDS`, 1-10): what
    #: the owner plans and sees. What Seedance is asked for is `generation_seconds`.
    seconds: int = 5
    #: The reel analysis the part comes from (`public_reel_analyses.id`); None without one.
    analysis_id: UUID | None = None
    #: The analysed cuts it covers, consecutive (P2: a part joins cuts up to 4-10 s).
    shot_indexes: tuple[int, ...] = Field(default=(), max_length=32)
    #: The interval of the generated clip the join keeps, in seconds from its start; both
    #: or neither (a 2 s part generated at 4 s keeps 2 of them). Without it the join keeps
    #: the first `seconds`.
    trim_start_s: float | None = Field(default=None, ge=0)
    trim_end_s: float | None = Field(default=None, gt=0)
    #: What the part shows, in the owner's words or the plan's (VE-08). On the child it
    #: is the description THIS version was made from: a new one is a new brief, so an
    #: earlier version keeps showing its own (`piece_versions.brief_id`).
    description: str = Field(default="", max_length=PART_DESCRIPTION_MAX)
    #: VE-08 (UX review of VE-04c): someone seems to talk to the camera in the original
    #: cuts (speech in the cut and a face seen) — the voice family itself is always
    #: `unknown` in the analysis, so this is derived, never read from it.
    talks_to_camera: bool = False
    #: VE-08: what the owner should read about this part (`PartNotice`), in order.
    notices: tuple[PartNotice, ...] = Field(default=(), max_length=len(PART_NOTICES))
    #: UI-4: None inherits the parent's photos; an empty tuple deliberately uses none.
    #: Videos and audio are always this part's own selection, never inherited.
    clip_image_keys: tuple[str, ...] | None = Field(default=None, max_length=CLIP_MAX_IMAGES)
    clip_image_roles: tuple[str, ...] = Field(default=(), max_length=CLIP_MAX_IMAGES)
    clip_video_keys: tuple[str, ...] = Field(default=(), max_length=CLIP_MAX_VIDEOS)
    clip_audio_keys: tuple[str, ...] = Field(default=(), max_length=CLIP_MAX_AUDIOS)

    @property
    def generation_seconds(self) -> int:
        """The length the part's child clip asks Seedance for: the part's own, or 4 for a
        part of 1-3 s (Seedance's minimum) — trimmed back to `seconds` at the join."""
        return max(self.seconds, PART_GENERATION_MIN_SECONDS)

    @model_validator(mode="after")
    def _coherent_source(self) -> _PartSource:
        if self.seconds not in PART_SECONDS:
            raise ValueError(
                f"a part lasts {PART_SECONDS.start} to {PART_SECONDS.stop - 1} whole seconds"
            )
        if self.shot_indexes and self.analysis_id is None:
            raise ValueError("a part's cuts belong to a reel analysis")
        if any(index < 0 for index in self.shot_indexes):
            raise ValueError("a cut index is not negative")
        if any(b != a + 1 for a, b in zip(self.shot_indexes, self.shot_indexes[1:], strict=False)):
            raise ValueError("a part covers consecutive cuts, in order")
        if len(set(self.notices)) != len(self.notices):
            raise ValueError("a part's notice is said once")
        if self.clip_image_roles and (
            self.clip_image_keys is None or len(self.clip_image_roles) != len(self.clip_image_keys)
        ):
            raise ValueError("a part's image roles must match its explicit images")
        if any(role not in CLIP_IMAGE_ROLES for role in self.clip_image_roles):
            raise ValueError("a part's image role must be product, place or style")
        if "people_unclear" in self.notices and self.mode == "edit" and not self.clip_video_keys:
            # unknown people = maybe someone of the original: never «Igual al original»
            raise ValueError("a part that may show someone of the original is made new")
        if self.mode == "edit" and self.analysis_id is None and not self.clip_video_keys:
            # `edit` changes a window of the original reel: without one there is nothing
            raise ValueError("an edit part needs the reel it edits")
        if self.mode == "edit" and (len(self.clip_video_keys) > 1 or self.clip_audio_keys):
            raise ValueError("an edit part takes one original video and no reference audio")
        if self.mode == "extend" and (self.clip_video_keys or self.clip_audio_keys):
            raise ValueError("an extend part cannot use its own reference video or audio")
        if self.original_mode == "extend" and self.mode != "extend":
            if self.analysis_id is None or len(self.shot_indexes) != 1:
                raise ValueError("a converted split part identifies its original reel cut")
            if self.mode == "edit" and not self.clip_video_keys:
                raise ValueError(
                    "a converted split part cannot edit the public source without offsets"
                )
        if (self.trim_start_s is None) != (self.trim_end_s is None):
            raise ValueError("a part's trim has its start and its end")
        if (
            self.trim_start_s is not None
            and self.trim_end_s is not None
            and self.trim_end_s <= self.trim_start_s
        ):
            raise ValueError("a part's trim ends after it starts")
        if self.trim_end_s is not None and self.trim_end_s > self.generation_seconds:
            raise ValueError("a part's trim ends within the clip it is cut from")
        if (
            self.trim_start_s is not None
            and self.trim_end_s is not None
            and abs((self.trim_end_s - self.trim_start_s) - self.seconds) > PART_TRIM_TOLERANCE_S
        ):
            # the join keeps the trim: a «2 s» part must not put 4 s in the video
            raise ValueError("a part's trim lasts the part's seconds")
        return self


class VideoPartPlan(_PartSource):
    """One entry of a parent's plan (`MediaInputs.parts`, ADR 44 / VE-06): what the part
    shows, how it is made and how long it lasts in the joined video. Its position in the
    plan is its `part_index` (1-based, as `content_drafts.part_index`)."""

    #: m-24984421: the mode the plan first gave this entry (`plan_from_analysis` sets
    #: it). The screen may make an orphan «Sigue a la anterior» new and later put it
    #: back; only an entry born `extend` may become `extend` again. None on entries
    #: stored before it existed or built without a reel: none of them may.


class PartsProvenance(BaseModel):
    """Who proposed a parent's plan without a reel (VE-14, «Proponerme las partes»): the
    model that answered, the prompt it was asked with and what the call cost. Stored on
    the parent (`MediaInputs.parts_provenance`) so the plan the owner started from stays
    traceable after he edits it. None on a plan from a reel or one the owner built."""

    model_config = ConfigDict(frozen=True)

    model_id: str = Field(min_length=1)
    model_revision: str | None = None
    prompt_version: str = Field(min_length=1)
    prompt_fingerprint: str = ""
    pricing_version: str = ""
    cost_usd: Decimal = Field(default=Decimal(0), ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    #: Paid turns the proposal took: 2 means the first answer broke a rule (a price, an
    #: English or film word, too few parts) and was corrected once. 0 on rows stored before
    #: the count existed.
    turns: int = Field(default=0, ge=0)


#: What the owner asked for the parts of a video by parts when he created it (UI-6,
#: m-24921081): `all` its parts, or only the `first` («Probar solo la parte 1»: 1 vista
#: previa, the others stay «Sin crear» until he creates them).
PartsScope = Literal["all", "first"]
#: Why the last attempt to create parts made none (`PartsRequest.refused`). Codes, never
#: client text: the screen chooses the words (`qualify-copy-es`).
PartsRefusal = Literal[
    "unavailable",  # the generation queue is off
    "extend_unavailable",  # VE-13 continuity is not implemented
    "text_missing",  # the video's text did not come out (or is not there yet)
    "needs_description",  # `part` still has to be described
    "needs_previous",  # `part` continues a part that is not created
    "removed",  # `part` was taken out of the video («Quitar parte»)
    "extend_invalid",  # a «Sigue a la anterior» part the reel cannot hold
    "over_budget",  # the team's dollar cap of the business
    "not_enough_previews",  # the month's vistas previas: `missing` short
    "plan_busy",  # the plan kept changing; asking again is safe
    "purged",  # the video's files were purged
    "brand_not_ready",  # the brand kit or the voice is missing
    "error",  # anything else (logged); asking again is safe
]
PARTS_REFUSALS: tuple[str, ...] = get_args(PartsRefusal)


class PartsRequest(BaseModel):
    """The owner's ask for the parts of a video by parts, kept ON THE PARENT
    (`MediaInputs.parts_request`, m-24921081). The screen sets it when it creates the
    parent; the creative worker creates the parts as soon as the parent's text passes,
    with no screen open (`qualify_api.creative.part_request`), and writes here the outcome
    of the last attempt: `refused` None = nothing refused (pending while no part exists,
    done once they do); a code = why nothing was made, `part` the part it is about and
    `missing` the vistas previas short. `attempted_parts` = the parts that attempt asked
    for, always spelled out (m-24993031): scope `all` keeps every part of the plan not
    removed, as `create_parts` reads «all». Empty only before any attempt — or on an
    outcome kept before m-24993031, where empty meant «every part not created yet»."""

    model_config = ConfigDict(frozen=True)

    scope: PartsScope = "all"
    refused: PartsRefusal | None = None
    part: int | None = Field(default=None, ge=1, le=PARTS_MAX)
    missing: int = Field(default=0, ge=0)
    attempted_parts: tuple[int, ...] = Field(default=(), max_length=PARTS_MAX)
    #: When the last outcome was written — the DATABASE's clock, never a process's.
    attempted_at: datetime | None = None
    #: How many attempts were started (0 = none yet). Each attempt takes the next number
    #: before it creates anything and writes its outcome only while it is still the last
    #: one started: a late, older outcome never overwrites a newer attempt's.
    attempt: int = Field(default=0, ge=0)


class PartRef(_PartSource):
    """A child draft's link to its place in the parent's plan (`MediaInputs.part`): the
    part's 1-based index, its length and how it is made. The child is a `CLIP` whose own
    `duration_seconds` — what Seedance is asked for — is `generation_seconds`. That it
    matches the parent's plan entry (seconds, mode, index) is checked by the service that
    creates the children (VE-08): a brief alone does not see its parent."""

    index: int = Field(ge=1, le=PARTS_MAX)


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
    resource_plan_version: int = 0
    brand_application_version: int = 0
    #: Server-owned (m-24820842, 2026-11-02): which prompt compiler a NEW execution was
    #: stamped with (`MediaProducer.prepare_new_brief`). 0 = every brief before it, compiled
    #: byte for byte as before; 1 = edit clips without the duplicated replication guidance,
    #: with the brand identity's hard floor and the clip routes' per-route budget; 2
    #: (2026-11-03, audit `auditoria-prompts-clip-20261103.md` §7) = the Seedance 2.x clip
    #: routes (motion clip, reel replica, animated gallery slide) in plain full sentences,
    #: no written text on screen, no per-field caps. 0 and 1 stay byte for byte as they were.
    prompt_compiler_version: int = 0
    #: Server-owned (m-24820842): the words a GENERATED script may have on a Seedance 2.x
    #: talking video (`MediaProducer.talking_script_word_budget`), set for the copy call
    #: only; and how many times the copy was asked to rewrite a script over it.
    script_word_budget: int | None = None
    script_rewrites: int = 0
    product_image_roles: tuple[str, ...] = ()
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
    #: Avatar video (m-24828920): burn in subtitles of what the presenter says, in the
    #: brand's font and colours. The operator's choice when creating the video; off for
    #: a brief from before it existed.
    subtitles: bool = False
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
    #: Additional logo variants integrated into the scene, never extra local signatures.
    #: The shared resource allowance covers these plus `brand_element_keys`.
    brand_logo_reference_keys: tuple[str, ...] = ()
    #: False: local signature as before. True: the selected logo is part of the
    #: generated scene, without a second local signature of the same mark.
    brand_logo_in_scene: bool = True
    #: m-24820842 (UX review B7): the owner's answer to «¿Dónde lo ponemos?», as a field
    #: instead of a sentence appended to the topic. None (every brief stored before it,
    #: and a request that does not say): today's behaviour, where the topic's own words
    #: (`LOGO_SIGNATURE_REQUEST` included) decide. "scene": the logo goes inside the
    #: image or video. "signature": the main logo (`brand_logo_key`) is the corner
    #: signature, laid locally after the image model; the resource selector and the
    #: preflight treat it so (`qualify_api.creative.resource_selection`). Frozen with the
    #: brief like every other media input.
    brand_logo_placement: Literal["scene", "signature"] | None = None
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
    #: On the PARENT of a video by parts (m-24984421) these are the owner's images for
    #: its parts, with their roles below; each part takes what its mode admits
    #: (`qualify_api.creative.parts.part_images`).
    clip_image_keys: tuple[str, ...] = Field(default=(), max_length=CLIP_MAX_IMAGES)
    #: What each of `clip_image_keys` is (§ request 2026-10-14), in the same order:
    #: `CLIP_IMAGE_ROLES` — the client's product, its place, or a look to borrow. Empty
    #: means every one is the product (a brief from before the roles).
    clip_image_roles: tuple[str, ...] = Field(default=(), max_length=CLIP_MAX_IMAGES)
    clip_video_keys: tuple[str, ...] = Field(default=(), max_length=CLIP_MAX_VIDEOS)
    #: Ordinary clips borrow motion; a reel replica edits one original video in place;
    #: a part of a video by parts may continue the previous part (`extend`, ADR 44).
    clip_reference_mode: Literal["motion", "edit", "extend"] = "motion"
    #: m-24820842 (founder, 2026-11-02): a reel replica may put the Brand Kit's approved
    #: CTAs on the text surfaces the original reel ALREADY shows (never new ones). Off by
    #: default; read only by the edit-clip prompt compiler 1 (`prompt_compiler_version`).
    replication_brand_text: bool = False
    #: m-24820837: the reel a replica was made from — kept on the brief (in
    #: `content_briefs.media`, no migration) so the piece shows its origin even after the
    #: original reel is gone. Only a replica has it: an ordinary clip never carries one.
    source_reel: SourceReelProvenance | None = None
    #: Explicitly imported Pinterest images; source records travel only with a selected
    #: image or frame, and are not prompt instructions or a catalogue of fetched Pins.
    source_pins: tuple[SourcePinProvenance, ...] = Field(
        default=(), max_length=MAX_PRODUCT_IMAGES + CLIP_MAX_IMAGES + 3
    )
    clip_audio_keys: tuple[str, ...] = Field(default=(), max_length=CLIP_MAX_AUDIOS)
    #: Clip (§ request 2026-10-23): the sound Seedance makes with the video. On by
    #: default — what every clip had before the switch; a model without audio (1.0)
    #: makes it silent either way.
    clip_audio: bool = True
    #: Clip (founder, 2026-11-03: «como subtítulos»): the approved copy's hook and CTA burnt
    #: in over the finished clip in the brand's type and colours, AFTER Seedance (which
    #: garbles lettering) — the video prompt stays free of written text either way. Off by
    #: default and for every brief stored before it existed; part of the frozen inputs.
    clip_subtitles: bool = False
    #: A carousel made from Galería (CM-6, m-24955927): what the owner chose on /create
    #: for the sound of their business videos (D1; off by default, D6) — each slide's
    #: `audio` is what it actually keeps — and the version of the assembly that laid the
    #: slides out (provenance). False / "" on every other piece.
    gallery_audio: bool = False
    gallery_assembly_version: str = ""

    @property
    def clip_has_references(self) -> bool:
        return bool(self.clip_image_keys or self.clip_video_keys or self.clip_audio_keys)

    #: Carousel kind (§ request 2026-10-09): the slides in order, and whether a closing
    #: slide with the CTA on the brand gradient ends it (it counts toward the ten).
    slides: tuple[CarouselSlide, ...] = Field(default=(), max_length=CAROUSEL_MAX_SLIDES)
    closing_slide: bool = False
    #: Video by parts (ADR 44, VE-06), the PARENT (`ContentKind.SHOT_VIDEO`): the plan,
    #: parts in order (1 to `PARTS_MAX`, checked by the brief). Empty on any other piece.
    parts: tuple[VideoPartPlan, ...] = ()
    #: Video by parts, the PARENT (m-24984421): the parts the owner took out of the plan
    #: in «Orden del clip», kept so the screen can offer them back. Never made: `parts`
    #: alone is what `create_parts` turns into children, in its order. Bounded (UI-4):
    #: at most the `PARTS_MAX` parts a plan can start with plus `PARTS_MAX` parts the
    #: owner added («Añadir parte») and took out again, so the kept history cannot grow
    #: without limit through repeated add-and-remove.
    parts_removed: tuple[VideoPartPlan, ...] = Field(default=(), max_length=PARTS_REMOVED_MAX)
    #: Video by parts, a CHILD (a `CLIP` draft with `parent_draft_id`): its place in the
    #: parent's plan. Its `duration_seconds` is then the part's `generation_seconds`.
    part: PartRef | None = None
    #: Video by parts, the PARENT: who proposed its plan without a reel (VE-14); None
    #: when the plan came from a reel or the owner built it himself.
    parts_provenance: PartsProvenance | None = None
    #: Video by parts, the PARENT (m-24921081): what the owner asked to create of its
    #: parts and the outcome of the last attempt. None on a parent whose parts are
    #: created only on the screen's own ask, and on any other piece.
    parts_request: PartsRequest | None = None

    @model_validator(mode="before")
    @classmethod
    def _logo_mode_for_new_or_stored_input(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, dict) and value.get("brand_logo_placement") == "signature":
            # the owner chose the corner: the main logo is the local signature, never also
            # an in-scene reference (the same rule `_known_duration` enforces)
            logo = value.get("brand_logo_key")
            refs = value.get("brand_logo_reference_keys") or ()
            return {
                **value,
                "brand_logo_in_scene": False,
                "brand_logo_reference_keys": tuple(k for k in refs if k != logo),
            }
        if isinstance(value, dict) and value.get("brand_logo_placement") == "scene":
            return {**value, "brand_logo_in_scene": True}
        if not isinstance(value, dict) or "brand_logo_in_scene" in value:
            return value
        stored = bool(info.context and info.context.get("preserve_stored_logo_mode"))
        # New requests default to integration without inventing a selected asset.
        # Missing historical flags mean the former implicit signature behavior.
        return {**value, "brand_logo_in_scene": not stored}

    @field_validator("brand_logo_reference_keys", mode="before")
    @classmethod
    def _distinct_logo_references(cls, value: object) -> object:
        if isinstance(value, list | tuple) and all(isinstance(item, str) for item in value):
            return tuple(dict.fromkeys(value))
        return value

    @property
    def pinterest_image_keys(self) -> frozenset[str]:
        """Only selected image inputs, not video, brand assets or fabricated gallery rows."""
        return frozenset(
            key
            for key in (
                *self.product_keys,
                self.background_key,
                *self.clip_image_keys,
                self.clip_first_frame_key,
                self.clip_last_frame_key,
            )
            if key
        )

    @model_validator(mode="after")
    def _known_duration(self) -> MediaInputs:
        pin_keys = [source.image_key for source in self.source_pins]
        selected_images = self.pinterest_image_keys
        if len(set(pin_keys)) != len(pin_keys) or any(
            key not in selected_images for key in pin_keys
        ):
            raise ValueError("a Pinterest origin belongs to one selected image or frame")
        if self.brand_logo_key in self.brand_logo_reference_keys and not self.brand_logo_in_scene:
            raise ValueError("the same logo cannot be a signature and an in-scene reference")
        additional = set(self.brand_logo_reference_keys) | set(self.brand_element_keys)
        additional.discard(self.brand_logo_key)
        if len(additional) > MAX_BRAND_ELEMENTS:
            raise ValueError(f"at most {MAX_BRAND_ELEMENTS} additional brand resources are allowed")
        if self.product_source not in PRODUCT_SOURCES:
            raise ValueError(f"product_source must be one of {PRODUCT_SOURCES}")
        if self.part is not None:
            # ADR 44: a part's clip asks Seedance for the part's length, at least 4 s (a
            # 1-3 s part is generated at 4 and trimmed at the join) — never a length the
            # vendor refuses, nor one that disagrees with the plan
            if self.duration_seconds != self.part.generation_seconds:
                raise ValueError(
                    f"a {self.part.seconds} s part's clip is generated at"
                    f" {self.part.generation_seconds} s, not {self.duration_seconds}"
                )
        elif self.duration_seconds not in DURATIONS_SECONDS:
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

    @model_validator(mode="before")
    @classmethod
    def _stored_brief_without_media(cls, value: object, info: ValidationInfo) -> object:
        if (
            isinstance(value, dict)
            and "media" not in value
            and info.context
            and info.context.get("preserve_stored_logo_mode")
        ):
            return {**value, "media": {"brand_logo_in_scene": False}}
        return value

    @model_validator(mode="before")
    @classmethod
    def _template_logo_is_its_slot(cls, value: object) -> object:
        """A Remotion template never composes a scene: the chosen logo always fills the
        template's own logo slot (a signature). New media default to an in-scene logo
        (m-24820842), which a template cannot honour — so a template brief is normalized
        to the signature mode here, once, for every caller (preview, preflight, render)."""
        if not isinstance(value, dict):
            return value
        try:
            kind = ContentKind(value.get("kind", ContentKind.STATIC_FLYER))
        except ValueError:
            return value
        if kind is not ContentKind.TEMPLATE:
            return value
        media = value.get("media")
        if isinstance(media, MediaInputs):
            if not media.brand_logo_in_scene and media.brand_logo_placement is None:
                return value
            refs = tuple(k for k in media.brand_logo_reference_keys if k != media.brand_logo_key)
            fixed = media.model_copy(
                update={
                    "brand_logo_in_scene": False,
                    "brand_logo_reference_keys": refs,
                    # the slot is the only placement a template has: nothing to choose
                    "brand_logo_placement": None,
                }
            )
            return {**value, "media": fixed}
        if isinstance(media, dict):
            logo = media.get("brand_logo_key")
            refs = tuple(k for k in media.get("brand_logo_reference_keys", ()) if k != logo)
            return {
                **value,
                "media": {
                    **media,
                    "brand_logo_in_scene": False,
                    "brand_logo_reference_keys": refs,
                    "brand_logo_placement": None,
                },
            }
        if media is None:
            return {**value, "media": {"brand_logo_in_scene": False}}
        return value

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
        # m-24984421: the parent of a video by parts carries the owner's images with
        # their roles (`clip_image_keys`/`clip_image_roles`) for its parts to take; any
        # other clip input stays the clip's own
        parent_images = self.kind is ContentKind.SHOT_VIDEO and not (
            media.clip_video_keys or media.clip_audio_keys
        )
        clip_inputs = (
            media.clip_first_frame_key
            or media.clip_last_frame_key
            or (media.clip_has_references and not parent_images)
            or media.clip_reference_mode != "motion"
        )
        if clip_inputs and self.kind is not ContentKind.CLIP:
            raise ValueError("frames and references are for a clip")
        if self.kind in (ContentKind.CLIP, ContentKind.SHOT_VIDEO):
            if media.clip_image_roles and len(media.clip_image_roles) != len(media.clip_image_keys):
                raise ValueError("a clip's image roles must match its images, one each")
            if any(role not in CLIP_IMAGE_ROLES for role in media.clip_image_roles):
                raise ValueError(f"a clip image's role is one of {CLIP_IMAGE_ROLES}")
        self._parts_are_coherent()
        if media.source_reel is not None:
            if self.kind is not ContentKind.CLIP or media.clip_reference_mode != "edit":
                raise ValueError("a source reel belongs to a reel replica")
        if self.kind is ContentKind.CLIP:
            if media.clip_reference_mode == "edit":
                # VE-09: an «Igual al original» part's window is cut by the creative worker
                # into the part's own folder (it needs the part's draft id), so its brief
                # may carry none yet; a pre-cut window is still exactly one video
                videos = len(media.clip_video_keys)
                needs_video = media.part is None or videos > 1
                if (needs_video and videos != 1) or not media.clip_image_keys:
                    raise ValueError("a reel edit needs one original video and product images")
                if media.clip_first_frame_key or media.clip_last_frame_key:
                    raise ValueError("a reel edit keeps the original video's frames")
                if media.clip_audio_keys:
                    raise ValueError("a reel edit does not borrow a reference soundtrack")
            if media.clip_last_frame_key and not media.clip_first_frame_key:
                raise ValueError("a clip's closing frame needs its opening frame")
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
        single = self.single_gallery_medium
        if single is not None:
            # founder, 2026-11-06 (CM-6): ONE Galería medium is a publication of its own —
            # a photo a single feed image, a video a Reel (9:16, the one way Instagram
            # publishes a lone video)
            is_video = single.segment_end_ms is not None
            if is_video and self.format is not ContentFormat.REELS_9_16:
                raise ValueError("a single Galería video is a Reel (9:16)")
            if not is_video and self.format not in self.kind.formats:
                raise ValueError("a single Galería photo is a feed image (4:5 or 1:1)")
        elif self.kind is ContentKind.CAROUSEL:
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
                if slide.guide_product_index is not None and slide.guide_product_index >= len(
                    media.product_keys
                ):
                    raise ValueError("a slide names a product photo the brief does not have")
        elif media.slides or media.closing_slide:
            raise ValueError("slides are for the carousel")
        if media.own_script.strip() and not self.kind.is_video:
            raise ValueError("an own script is for the avatar videos")
        if media.carousel and not self.format.is_feed:
            raise ValueError("a carousel is a feed post (4:5 or 1:1)")
        if self.format not in self.kind.formats and single is None:
            raise ValueError(f"format {self.format} is not offered for {self.kind}")
        return self

    @property
    def single_gallery_medium(self) -> CarouselSlide | None:
        """The one slide of a publication made from ONE Galería medium (CM-6, founder
        2026-11-06): a `CAROUSEL` brief whose only item is a `GALLERY` slide, no closing
        slide. It is published as a single image (a photo) or a Reel (a video), never as a
        carousel. None for every other brief."""
        media = self.media
        if (
            self.kind is ContentKind.CAROUSEL
            and len(media.slides) == 1
            and not media.closing_slide
            and media.slides[0].source is SlideSource.GALLERY
        ):
            return media.slides[0]
        return None

    def _parts_are_coherent(self) -> None:
        """Video by parts (ADR 44, VE-06): the parent holds a plan of 1 to `PARTS_MAX`
        parts and, of the clip inputs, only the images its parts take (m-24984421); a
        child is a `CLIP` whose reference mode is its part's; `extend` continues a
        previous part, so never the first one."""
        media = self.media
        if self.kind is ContentKind.SHOT_VIDEO:
            if not 1 <= len(media.parts) <= PARTS_MAX:
                raise ValueError(
                    f"a video by parts has 1 to {PARTS_MAX} parts, not {len(media.parts)}"
                )
            if media.part is not None:
                raise ValueError("a video by parts is not itself a part")
            if media.parts[0].mode == "extend":
                raise ValueError("the first part cannot continue a previous one")
            covered: dict[tuple[UUID, int], list[VideoPartPlan]] = {}
            previous: VideoPartPlan | None = None
            for plan in media.parts:
                shots = set(plan.shot_indexes)
                # a cut longer than 10 s is split into a part and the `extend` (or
                # several) right after it (design §3). An extend with reel cuts must
                # START on the previous part's last cut, of the same analysis, and share
                # no other cut. An extend without cuts (no reel) continues freely. That
                # the cut lasts > 10 s is not in the plan: VE-08 checks the analysis.
                if plan.mode == "extend" and plan.shot_indexes:
                    if (
                        previous is None
                        or previous.analysis_id != plan.analysis_id
                        or not previous.shot_indexes
                        or plan.shot_indexes[0] != previous.shot_indexes[-1]
                    ):
                        raise ValueError(
                            "an extend part starts on the last cut of the part before it"
                        )
                if plan.analysis_id is not None:
                    for cut in shots:
                        covered.setdefault((plan.analysis_id, cut), []).append(plan)
                previous = plan
            for (_, cut), origins in covered.items():
                ordinary = [
                    plan
                    for plan in origins
                    if not (
                        (plan.mode == "extend" and plan.shot_indexes[0] == cut)
                        or (
                            plan.original_mode == "extend"
                            and len(plan.shot_indexes) == 1
                            and (
                                plan.mode == "reference"
                                or (plan.mode == "edit" and bool(plan.clip_video_keys))
                            )
                        )
                    )
                ]
                if len(ordinary) > 1:
                    raise ValueError("two parts cannot cover the same cut of a reel")
        elif (
            media.parts
            or media.parts_removed
            or media.parts_provenance is not None
            or media.parts_request is not None
        ):
            raise ValueError("a plan of parts is for a video by parts")
        part = media.part
        if part is None:
            if media.clip_reference_mode == "extend":
                raise ValueError("only a part of a video by parts continues a previous one")
            return
        if self.kind is not ContentKind.CLIP:
            raise ValueError("a part of a video by parts is a clip")
        if part.mode == "extend" and part.index == 1:
            raise ValueError("the first part cannot continue a previous one")
        expected = {"reference": "motion", "edit": "edit", "extend": "extend"}[part.mode]
        if media.clip_reference_mode != expected:
            raise ValueError(f"the {part.mode} part uses the {expected} reference mode")

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
