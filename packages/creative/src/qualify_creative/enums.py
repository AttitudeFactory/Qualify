"""Closed vocabularies of the Brand Content Engine.

Two of these enums carry a decision that must never drift into prose, so the decision
lives on the member itself rather than in a table someone has to remember:

- `ImageRoute` encodes BOTH the preference order and whether Meta requires an
  "AI-generated" disclosure. The order is the product recommendation (a neutral dropdown
  would present the routes as equivalent, which the evidence says they are not), and the
  disclosure flag is a compliance fact: undisclosed AI content was the third-largest
  cause of Meta ad rejections in 2026.
- `VideoEffect` is the catalogue of the video sub-module, which treats footage the
  operator already shot. Every member is a deterministic ffmpeg operation — none of them
  is generation, none of them requires a disclosure label, and all of them cost nothing.

Rationale and sources: `docs/diseno-motor-contenido-marca.md` §1.3/§1.7 and
`docs/estrategia-contenido-bianki-polet.md` §3.
"""

from __future__ import annotations

from enum import StrEnum


class ImageRoute(StrEnum):
    """How the image for a piece comes to exist, ordered from "no pixel of the subject is
    touched" to "the subject is invented". Declaration order IS the UI order."""

    TEMPLATE_ONLY = "template_only"
    FROM_UPLOAD = "from_upload"
    RESTYLE_ENHANCE = "restyle_enhance"
    RESTYLE_SCENE = "restyle_scene"
    GENERATE = "generate"

    @property
    def rank(self) -> int:
        """Position in the accordion. Lower is more recommended."""
        return _ROUTE_ORDER.index(self)

    @property
    def requires_ai_disclosure(self) -> bool:
        """Whether Meta requires this piece to be labelled as AI-generated when it runs
        as an ad. Colour correction, cropping, cleanup and upscaling are exempt; a
        generated subject or a substantially composited scene is not."""
        return self in _DISCLOSURE_REQUIRED

    @property
    def uses_model(self) -> bool:
        """False for the two deterministic routes, which never call a vendor and
        therefore have no cost, no latency and no failure chain."""
        return self not in (ImageRoute.TEMPLATE_ONLY, ImageRoute.FROM_UPLOAD)

    @property
    def needs_source_media(self) -> bool:
        """Whether the route operates on a photo the operator supplies. A menu card or an
        opening-hours card is typography on brand — there is no photograph involved, and
        demanding one would block the pieces a shop publishes most often."""
        return self in (
            ImageRoute.FROM_UPLOAD,
            ImageRoute.RESTYLE_ENHANCE,
            ImageRoute.RESTYLE_SCENE,
        )

    @property
    def touches_subject_pixels(self) -> bool:
        """The question that decides truthfulness: does a model modify or invent the
        thing the customer will actually receive?"""
        return self in (ImageRoute.RESTYLE_ENHANCE, ImageRoute.RESTYLE_SCENE, ImageRoute.GENERATE)


_ROUTE_ORDER: tuple[ImageRoute, ...] = (
    ImageRoute.TEMPLATE_ONLY,
    ImageRoute.FROM_UPLOAD,
    ImageRoute.RESTYLE_ENHANCE,
    ImageRoute.RESTYLE_SCENE,
    ImageRoute.GENERATE,
)

_DISCLOSURE_REQUIRED: frozenset[ImageRoute] = frozenset(
    {ImageRoute.RESTYLE_SCENE, ImageRoute.GENERATE}
)


class VideoEffect(StrEnum):
    """Deterministic treatments applied to footage the operator already shot. Every
    member maps to an ffmpeg filter chain; none of them generates content."""

    SLOW_MOTION_HALF = "slow_motion_half"
    SLOW_MOTION_QUARTER = "slow_motion_quarter"
    REVERSE = "reverse"
    BOOMERANG = "boomerang"
    SPEED_RAMP = "speed_ramp"
    FREEZE_LAST_FRAME = "freeze_last_frame"


class Platform(StrEnum):
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"


class ContentFormat(StrEnum):
    """Aspect ratio and placement. `REELS_9_16` / `STORY_9_16` are separate renders at
    full vertical size, never a crop of the 4:5. `enabled` is /create's original form
    (feed 4:5 only); the generator on /signals offers each kind its own formats
    (`ContentKind.formats`)."""

    FEED_4_5 = "feed_4_5"
    FEED_1_1 = "feed_1_1"
    REELS_9_16 = "reels_9_16"
    STORY_9_16 = "story_9_16"

    @property
    def dimensions(self) -> tuple[int, int]:
        return _FORMAT_DIMENSIONS[self]

    @property
    def aspect_ratio(self) -> str:
        """The ratio as the vendors name it (HeyGen's `aspect_ratio`)."""
        return _FORMAT_ASPECT[self]

    @property
    def is_feed(self) -> bool:
        """A feed post — the only placement Instagram takes a carousel in."""
        return self in (ContentFormat.FEED_4_5, ContentFormat.FEED_1_1)

    @property
    def enabled(self) -> bool:
        return self is ContentFormat.FEED_4_5


_FORMAT_DIMENSIONS: dict[ContentFormat, tuple[int, int]] = {
    ContentFormat.FEED_4_5: (1080, 1350),
    ContentFormat.FEED_1_1: (1080, 1080),
    ContentFormat.REELS_9_16: (1080, 1920),
    ContentFormat.STORY_9_16: (1080, 1920),
}
_FORMAT_ASPECT: dict[ContentFormat, str] = {
    ContentFormat.FEED_4_5: "4:5",
    ContentFormat.FEED_1_1: "1:1",
    ContentFormat.REELS_9_16: "9:16",
    ContentFormat.STORY_9_16: "9:16",
}


class BriefObjective(StrEnum):
    AWARENESS = "awareness"
    CONSIDERATION = "consideration"
    LEAD = "lead"
    SALE = "sale"


class BriefIntent(StrEnum):
    ORGANIC = "organic"
    ADS = "ads"
    BOTH = "both"

    @property
    def includes_ads(self) -> bool:
        return self in (BriefIntent.ADS, BriefIntent.BOTH)


class DraftStatus(StrEnum):
    DRAFTING = "drafting"
    GENERATED = "generated"
    APPROVED = "approved"
    REJECTED = "rejected"
    STAGED = "staged"  # §1.8: Meta container created+verified, unpublished; expires in 24h
    PUBLISHED = "published"
    FAILED = "failed"

    @property
    def is_artifact(self) -> bool:
        """Whether downstream modules (publishing, ads) may read this draft. A GENERATED
        draft is work in progress, not an artifact: nothing that no human approved leaves
        the module."""
        return self in (DraftStatus.APPROVED, DraftStatus.STAGED, DraftStatus.PUBLISHED)


class FailureReason(StrEnum):
    """Typed rather than free text: the UI has to be able to tell the operator what to do
    about it, and a string cannot be branched on."""

    BUDGET_EXCEEDED = "budget_exceeded"
    CREDENTIAL_INVALID = "credential_invalid"
    PROVIDER_ERROR = "provider_error"
    FIDELITY_REJECTED = "fidelity_rejected"
    ROUTE_BLOCKED_BY_POLICY = "route_blocked_by_policy"
    REFUSAL = "refusal"
    MEDIA_EXPIRED = "media_expired"
    TIMEOUT = "timeout"
    # Template render (packages/render/CONTRACT.md §4.2): the render service's typed
    # reasons, kept 1:1 so a job's failure maps onto a draft's without interpretation.
    RENDER_ERROR = "render_error"
    INVALID_PARAMETERS = "invalid_parameters"
    DEPENDENCY_FAILED = "dependency_failed"
    CANCELLED = "cancelled"


class VoiceProfileStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class VoiceSourceKind(StrEnum):
    MANUAL_KIT = "manual_kit"
    OWNED_MEDIA = "owned_media"
    PUBLIC_WEB = "public_web"


class EmojiPolicy(StrEnum):
    NONE = "none"
    SPARSE = "sparse"
    FREE = "free"


class PaidBy(StrEnum):
    PLATFORM = "platform"
    TENANT = "tenant"


class GenerationTask(StrEnum):
    """What a `GenerationProvider` is being asked for. `FROM_UPLOAD` is deliberately
    absent: composing the operator's photo into their brand frame is local rendering, not
    a vendor call, and giving it a fake provider so it could ride the router would buy
    uniformity at the price of pretending it has a key, a price and a fallback chain."""

    COPY = "copy"
    PRODUCT_IMAGE = "product_image"
    RESTYLE_ENHANCE = "restyle_enhance"
    RESTYLE_SCENE = "restyle_scene"
    # A spokesperson video: an existing vendor avatar lip-syncing a script. It is always
    # AI-generated footage, so it always carries Meta's disclosure label (F5-MA-10).
    AVATAR_VIDEO = "avatar_video"
    # A generated scene video (Seedance, § request 2026-10-07): a prompt and the first
    # frame it starts on. AI-generated footage, so it carries the disclosure label too.
    SCENE_VIDEO = "scene_video"
    # A brand template rendered by the Remotion service (plan-mvp-plantillas-remotion.md
    # §2): the operator's real photos/video composed into a Reel + stills. Deterministic,
    # no model touches a pixel, so no AI disclosure — but it IS a provider call (a
    # separate process with a queue, an ETA and, one day, a price), unlike FROM_UPLOAD.
    TEMPLATE_RENDER = "template_render"
    # A script read aloud by a voice (Seed Speech, § request 2026-10-16): the brand's own
    # cloned voice or a public one. What OmniHuman lip-syncs a presenter to.
    VOICEOVER = "voiceover"


class ContentType(StrEnum):
    """What the piece is *about*. This is the entry point of the brief, because it is how
    a shop owner actually thinks — "producto nuevo", not "objetivo: consideración".

    Three things people usually put in a list like this are deliberately NOT here, because
    they are other dimensions and mixing them turns the enum into a junk drawer:
    the **hook** is a field of `CopyPayload`; **ads** is the brief's `intent`; and
    **carousel / stories** are formats. Keeping them separate is what lets a content type
    preset the other three dimensions instead of competing with them.
    """

    # Product and offer — the piece shows something the customer will receive.
    PRODUCT = "product"
    NEW_PRODUCT = "new_product"
    MENU = "menu"
    PRICE = "price"
    PROMOTION = "promotion"
    COMBO = "combo"

    # Business and trust — no sellable item is depicted.
    HOURS_LOCATION = "hours_location"
    BEHIND_SCENES = "behind_scenes"
    TEAM_STORY = "team_story"
    TESTIMONIAL = "testimonial"
    FAQ = "faq"
    LOYALTY = "loyalty"

    # Moment — tied to a date or a state of the business.
    OPENING_COUNTDOWN = "opening_countdown"
    SEASONAL = "seasonal"
    SOLD_OUT = "sold_out"
    POLL = "poll"

    # B2B — a different audience from the walk-in customer.
    CATERING = "catering"
    SUBSCRIPTION = "subscription"

    @property
    def depicts_sellable_item(self) -> bool:
        """The question that decides which image routes are defensible. If the picture
        represents something concrete the person will receive, its pixels are not
        invented — see `ImageRoute`."""
        return self in _DEPICTS_SELLABLE

    @property
    def default_image_route(self) -> ImageRoute:
        """What the accordion opens on for this type. A piece that depicts a real item
        opens on the operator's own photo; a menu, an hours card or an FAQ opens on the
        pure template, because there is nothing to photograph."""
        return ImageRoute.FROM_UPLOAD if self.depicts_sellable_item else ImageRoute.TEMPLATE_ONLY

    @property
    def allows_generate(self) -> bool:
        """Whether `GENERATE` is defensible at all for this type, before per-brand policy
        narrows it further. Never for a sellable item; fine for a hours card."""
        return not self.depicts_sellable_item


_DEPICTS_SELLABLE: frozenset[ContentType] = frozenset(
    {
        ContentType.PRODUCT,
        ContentType.NEW_PRODUCT,
        ContentType.PROMOTION,
        ContentType.COMBO,
        ContentType.CATERING,
        ContentType.SUBSCRIPTION,
    }
)


class ContentKind(StrEnum):
    """What the generator MAKES — the first choice on /create (§ request 2026-09-25).

    A different dimension from `ContentType` (what the piece is about) and from
    `ContentFormat` (its aspect ratio): a "promoción" can be a flyer, an avatar video or a
    script for a real creator. Each kind decides which inputs the brief takes and which
    artifact comes out of the draft:

    - `CREATOR_SCRIPT` — a real person will record it: only the script (and the post's
      copy) is generated, no media.
    - `AVATAR_VIDEO` — a generated human presenter (a HeyGen library look) reads the
      script; background and product images are optional.
    - `ANIMATED_AVATAR_VIDEO` — an animated character reads the script: generated by AI
      from a description, or animated from an image the operator uploads; background and
      product images are optional.
    - `STATIC_FLYER` — an advertising image (or a carousel of them) built from the
      operator's product photo, their background (e.g. their venue), both, or the
      described scene alone when no photo is uploaded, as `AdImageMode` says, plus the
      generated copy. The value keeps its historical name
      (it is stored on every draft); the product calls it "imagen publicitaria". Since
      2026-10-07 Seedream renders the scene (`MediaInputs.scene_prompt`) with those
      photos as references, and the hook, the CTA and the real logo are set on top
      locally — a model is never trusted to spell the brand.
    - `TEMPLATE` — a brand template (plan-mvp-plantillas-remotion.md): the operator's
      real product photos (and optionally a short video) composed by a Remotion
      template of their niche into a Reel 9:16 plus feed and story stills, in one run.
      The template is chosen by the recipe router, not by the operator.
    - `CAROUSEL` — a feed carousel of 2-10 slides the operator lays out one by one
      (§ request 2026-10-09), each a `SlideSource`: a scene Seedream generates (with the
      hook or the CTA printed on it, or not), that scene animated by Seedance into a
      short silent video (its text optional), or an image or video of a piece the brand
      already made. Instagram takes any mix of images and videos in one carousel.
    - `CLIP` — a generated video with no presenter (§ request 2026-10-14): Seedance
      animates from the operator's opening frame (and, optionally, the closing one), or
      follows their references — images, videos, audio — on a 2.x model. The frames and
      references come from the catalog's product or are uploaded.
    """

    CREATOR_SCRIPT = "creator_script"
    AVATAR_VIDEO = "avatar_video"
    ANIMATED_AVATAR_VIDEO = "animated_avatar_video"
    STATIC_FLYER = "static_flyer"
    TEMPLATE = "template"
    CAROUSEL = "carousel"
    CLIP = "clip"

    @property
    def enabled(self) -> bool:
        return True

    @property
    def is_template(self) -> bool:
        return self is ContentKind.TEMPLATE

    @property
    def multi_output(self) -> bool:
        """One run yields several assets with their own status (a Reel and its stills);
        the draft shows each as it lands instead of waiting for the slowest."""
        return self is ContentKind.TEMPLATE

    @property
    def is_video(self) -> bool:
        return self in (ContentKind.AVATAR_VIDEO, ContentKind.ANIMATED_AVATAR_VIDEO)

    @property
    def has_script(self) -> bool:
        """Whether the copy carries a script (`CopyPayload.script`): what the real
        creator or the avatar will say."""
        return self is ContentKind.CREATOR_SCRIPT or self.is_video

    @property
    def requires_ai_disclosure(self) -> bool:
        """A generated presenter is AI-generated footage by definition — Meta's label
        applies whatever the image route says about the product's own pixels. So is a
        generated clip."""
        return self.is_video or self is ContentKind.CLIP

    @property
    def default_format(self) -> ContentFormat:
        """Videos and a creator's script are vertical (Reels); the flyer and the carousel
        are feed 4:5."""
        return _KIND_FORMATS[self][0]

    @property
    def outputs_are_declared_by_template(self) -> bool:
        """The template's manifest, not the brief's `format`, says which formats come out."""
        return self is ContentKind.TEMPLATE

    @property
    def formats(self) -> tuple[ContentFormat, ...]:
        """The formats the generator offers this kind, the default first."""
        return _KIND_FORMATS[self]


class SlideSource(StrEnum):
    """Where one slide of a `ContentKind.CAROUSEL` comes from (§ request 2026-10-09)."""

    #: A scene Seedream generates from the slide's description and photos.
    GENERATED = "generated"
    #: That generated scene, animated by Seedance into a short silent video.
    ANIMATED = "animated"
    #: An image or a video of a piece the brand already made, reused as it is.
    EXISTING = "existing"
    #: A stock video (`t/{tenant}/stock/…`, plan-integracion-stock, § request
    #: 2026-10-16) fitted to the format with the slide's words and the logo over every
    #: frame — never as it is: both stock licences forbid publishing it standalone.
    STOCK = "stock"

    @property
    def is_generated(self) -> bool:
        """Seedream / Seedance imagery — a reused piece or a stock video is not."""
        return self in (SlideSource.GENERATED, SlideSource.ANIMATED)


class SlideText(StrEnum):
    """The words printed on a generated or animated carousel slide — the operator's
    choice per slide (on a video, the text is optional: § request 2026-10-09)."""

    NONE = "none"
    HOOK = "hook"
    CTA = "cta"


class AvatarSource(StrEnum):
    """Where an animated avatar comes from (`ContentKind.ANIMATED_AVATAR_VIDEO`)."""

    #: Generated by AI from the operator's description (Seedream draws it).
    AI = "ai"
    #: Animated from an image the operator uploads (a mascot, an illustration).
    IMAGE = "image"


class VideoEngine(StrEnum):
    """Which vendor renders the two avatar kinds (§ request 2026-10-07). Stored on the
    brief, so a draft regenerates on the engine it was asked for."""

    #: RETIRED 2026-10-16 (avatars moved to ByteDance): a talking presenter over HeyGen
    #: API v3. Kept only so a brief stored before then still reads; the producer refuses
    #: to render it (`MediaProducer.produce`), nothing offers it any more.
    HEYGEN = "heygen"
    #: A generated scene: Seedream composes the first frame from the operator's photos,
    #: Seedance animates it. Seedance 1.0 is silent; the 2.x models speak the script.
    SEEDANCE = "seedance"
    #: A talking presenter over ByteDance (§ request 2026-10-16): Seedream composes the
    #: presenter with the products and background, Seed Speech reads the exact script in
    #: the chosen voice — the brand's own clone or a public one — and OmniHuman makes the
    #: presenter say it, lips in sync.
    OMNIHUMAN = "omnihuman"


class AdImageMode(StrEnum):
    """What an advertising image (`ContentKind.STATIC_FLYER`) is built from — the
    operator's own photos, which the image model must keep recognisable, or nothing but
    the described scene. Since 2026-10-12 the photos are optional and the generator
    derives the mode from what was uploaded; the operator no longer picks it."""

    #: Their product; the scene around it is invented.
    PRODUCT = "product"
    #: Their background (e.g. their venue); what goes in it is invented.
    BACKGROUND = "background"
    #: Both: their product placed in their real background (a hand holding their glass
    #: in their bar).
    BOTH = "both"
    #: No photos: the whole scene is invented from the description (§ 2026-10-12).
    SCENE = "scene"

    @property
    def needs_product(self) -> bool:
        return self in (AdImageMode.PRODUCT, AdImageMode.BOTH)

    @property
    def needs_background(self) -> bool:
        return self in (AdImageMode.BACKGROUND, AdImageMode.BOTH)


#: The formats each kind is offered in (§ request 2026-10-13: every kind in every
#: Instagram format that suits what it makes). Instagram's own rules decide the edges:
#: a Reel is a video, a Story takes an image or a video, a feed post an image, a
#: carousel or a video (shown in the feed at its 4:5 / 1:1 shape), and a carousel exists
#: only in the feed. The first one is the kind's default.
_KIND_FORMATS: dict[ContentKind, tuple[ContentFormat, ...]] = {
    # a generated video: any placement Seedance renders (§ 2026-10-14)
    ContentKind.CLIP: (
        ContentFormat.REELS_9_16,
        ContentFormat.STORY_9_16,
        ContentFormat.FEED_4_5,
        ContentFormat.FEED_1_1,
    ),
    # the person records it: a video, so any placement
    ContentKind.CREATOR_SCRIPT: (
        ContentFormat.REELS_9_16,
        ContentFormat.STORY_9_16,
        ContentFormat.FEED_4_5,
        ContentFormat.FEED_1_1,
    ),
    ContentKind.AVATAR_VIDEO: (
        ContentFormat.REELS_9_16,
        ContentFormat.STORY_9_16,
        ContentFormat.FEED_4_5,
        ContentFormat.FEED_1_1,
    ),
    ContentKind.ANIMATED_AVATAR_VIDEO: (
        ContentFormat.REELS_9_16,
        ContentFormat.STORY_9_16,
        ContentFormat.FEED_4_5,
        ContentFormat.FEED_1_1,
    ),
    # an image; as a Reel the composed image is animated into a short video
    # (`VideoFitter.animate_still`), the only thing Instagram publishes as a Reel
    ContentKind.STATIC_FLYER: (
        ContentFormat.FEED_4_5,
        ContentFormat.FEED_1_1,
        ContentFormat.STORY_9_16,
        ContentFormat.REELS_9_16,
    ),
    # Since 2026-10-06 a template renders ONE output, the one of the brief's format and
    # `MediaInputs.template_video` (`media.template_port`): «Video publicitario» is the
    # video in any format, «Con plantilla» the still in the feed and story ones.
    ContentKind.TEMPLATE: (
        ContentFormat.REELS_9_16,
        ContentFormat.FEED_4_5,
        ContentFormat.FEED_1_1,
        ContentFormat.STORY_9_16,
    ),
    # Instagram takes a carousel only in the feed (`ContentFormat.is_feed`).
    ContentKind.CAROUSEL: (
        ContentFormat.FEED_4_5,
        ContentFormat.FEED_1_1,
    ),
}


class PostCategory(StrEnum):
    """HOW a POST is published (QUA-109) — not what is generated (`ContentKind`) nor what
    it is about (`ContentType`). Maps onto Meta's `media_product_type` at publish time:
    `GALERIA` → IMAGE (one image) / CAROUSEL (several), `STORY` → STORIES, `REEL` →
    REELS. `TIKTOK_VIDEO` is declared for the model; scheduled TikTok publishing stays
    blocked by the platform (ADR 23c)."""

    GALERIA = "galeria"
    STORY = "story"
    REEL = "reel"
    TIKTOK_VIDEO = "tiktok_video"


class ReuseType(StrEnum):
    """HOW a POST is reused over time (QUA-109, Herwin's list — not closed yet).
    Distinct from `ContentType.PROMOTION` / `SEASONAL`, which describe the TOPIC."""

    #: Reused several times, the same day of the week.
    RECURRENTE = "recurrente"
    #: Used once, then retired.
    PROMOCIONAL = "promocional"


def default_category(kind: ContentKind, fmt: ContentFormat | None = None) -> PostCategory:
    """The category a new POST starts with: a story format is a story; otherwise anything
    recorded or rendered as a video (the avatar kinds, a real creator's script) is a reel
    and a flyer or carousel a galería — so is a template's feed still, since a template
    renders the one output of its format (2026-10-06). The operator can change it."""
    if fmt is ContentFormat.STORY_9_16:
        return PostCategory.STORY
    if kind in (ContentKind.STATIC_FLYER, ContentKind.CAROUSEL) or (
        kind is ContentKind.TEMPLATE and fmt is not None and fmt.is_feed
    ):
        return PostCategory.GALERIA
    return PostCategory.REEL
