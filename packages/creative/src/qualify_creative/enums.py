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
    """Aspect ratio and placement. `REELS_9_16` is declared but disabled in the MVP: it
    is a separate render with Meta's safe zones applied (top 14% and bottom 35% are
    reserved by the interface), never a crop of the 4:5."""

    FEED_4_5 = "feed_4_5"
    REELS_9_16 = "reels_9_16"

    @property
    def dimensions(self) -> tuple[int, int]:
        return _FORMAT_DIMENSIONS[self]

    @property
    def enabled(self) -> bool:
        return self is ContentFormat.FEED_4_5


_FORMAT_DIMENSIONS: dict[ContentFormat, tuple[int, int]] = {
    ContentFormat.FEED_4_5: (1080, 1350),
    ContentFormat.REELS_9_16: (1080, 1920),
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
    - `STATIC_FLYER` — a still image (or a carousel of them) composed from the optional
      background and product images and the generated copy.
    - `TEMPLATE` — a brand template; declared, not built yet (`enabled` is False).
    """

    CREATOR_SCRIPT = "creator_script"
    AVATAR_VIDEO = "avatar_video"
    ANIMATED_AVATAR_VIDEO = "animated_avatar_video"
    STATIC_FLYER = "static_flyer"
    TEMPLATE = "template"

    @property
    def enabled(self) -> bool:
        return self is not ContentKind.TEMPLATE

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
        applies whatever the image route says about the product's own pixels."""
        return self.is_video

    @property
    def default_format(self) -> ContentFormat:
        """Videos are vertical (Reels); the flyer and the script's post are feed 4:5."""
        return ContentFormat.REELS_9_16 if self.is_video else ContentFormat.FEED_4_5


class AvatarSource(StrEnum):
    """Where an animated avatar comes from (`ContentKind.ANIMATED_AVATAR_VIDEO`)."""

    #: Generated by AI from the operator's description (HeyGen prompt avatar).
    AI = "ai"
    #: Animated from an image the operator uploads (a mascot, an illustration).
    IMAGE = "image"
