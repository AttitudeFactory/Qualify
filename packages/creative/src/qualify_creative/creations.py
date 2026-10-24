"""«Creaciones del mes» (CREAR-5, m-24848531): what each request costs the owner, in
creations, never in money.

The owner sees «Te quedan 18 de 30 este mes»; the team sees the dollars. One creation is
USD 0.15 of vendor cost (a ceiling, not an average) and a request weighs
⌈p95 cost / 0.15⌉, at least 1 — measured in `docs/creaciones-del-mes-medicion.md`. The
weights live in a versioned data file (`creations_data/<version>.json`), never as
literals here: a new weight is a new file, and every charge records the version it was
priced with. `pesos-creaciones-v1` (pricing `v5`) is kept as it was;
`pesos-creaciones-v2` (pricing `v7`, m-24851828) is in force.

**Videos have their own quota (founder, 2026-10-24).** Every Seedance-generated video —
a plain clip, the Seedance avatar, each animated carousel slide, a clip that follows a
reference video — counts as ONE of the month's videos (`pesos-creaciones-v2` →
`videos.monthly_quota`, 4), whatever its length up to `videos.offered_seconds` (5 or
10 s; 15 s is not offered), and uses no creations. A carousel with N animated slides
uses N videos plus its own creations. The talking presenter (OmniHuman) stays in
creations. A video is charged when the piece is CREATED (its 480p preview and the
1080p final made at approval); nothing is charged at approval, and a final that fails
gives its video back (`CreationPrice.videos`, the ledger's `refund_final`).

`VideoRates` still prices a generated video off the pricing table (`v7` tokens per
second at 480p and 1080p, with or without input video): it is the team's USD ceiling
per video (`generated_video_usd`), not a weight — and the v1 table, which had no video
quota, still prices clips in creations by its own steps.

`weight_for_request` is the one rule. The screen calls it with what the form holds (to
say «Este video con presentador usa 25 de tus creaciones» BEFORE anything is created);
the service calls it through `weight_for(brief)` with the stored brief when it charges.
Both read the same table, so what the owner was told is what is charged.

A request the table does not price — a presenter longer than its longest row — raises
`CreationNotOffered`: it is not offered, rather than charged at a guess.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from qualify_creative.enums import ContentKind, SlideSource, VideoEngine
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.schemas import ContentBrief

_DATA_DIR = Path(__file__).parent / "creations_data"

#: The weights in force. A new table is a new file and a new constant, never an edit.
CREATIONS_WEIGHTS_VERSION = "pesos-creaciones-v2"

#: Request keys — what a charge says it paid for (`creation_charges.request_kind`).
REQUEST_IMAGE = "image"
REQUEST_IMAGE_REDO = "image_redo"
REQUEST_SCRIPT = "script"
REQUEST_TEMPLATE = "template"
REQUEST_CAROUSEL = "carousel"
REQUEST_GENERATED_VIDEO = "generated_video"
REQUEST_PRESENTER = "presenter"

#: How fast a presenter reads the operator's own script — the same estimate the media
#: producer uses before the voice exists (`media._CHARS_PER_SECOND`).
CHARS_PER_SECOND = 15.0
#: The longest generated (Seedance) video a v1 request is priced for: every Seedance
#: family the app called capped at 12-15 s, so a longer ask was clamped by the vendor.
#: v2 states its own (`generated_video.max_output_seconds`).
_GENERATED_VIDEO_MAX_SECONDS = 15
#: An animated carousel slide's default length (`CarouselSlide.seconds`).
_SLIDE_SECONDS = 5

#: The kinds that are a Seedance-generated video when not a talking presenter.
_AVATAR_KINDS = (ContentKind.AVATAR_VIDEO.value, ContentKind.ANIMATED_AVATAR_VIDEO.value)


class CreationNotOffered(ValueError):
    """The weights table has no row for this request (e.g. a 45 s presenter)."""


@dataclass(frozen=True)
class _Step:
    up_to: int
    weight: int


@dataclass(frozen=True)
class VideoRates:
    """v2: what one second of generated (Seedance 2.5) video costs, preview + final,
    read off the pricing table the weights cite (`per_mtok_video_<res>[_with_video]`)."""

    model_id: str
    max_output_seconds: int
    #: The copy and the opening still, paid once per video (p95, production).
    fixed_usd: Decimal
    preview_usd_per_second: Decimal
    final_usd_per_second: Decimal
    preview_usd_per_second_with_video: Decimal
    final_usd_per_second_with_video: Decimal
    #: Whether the 1080p final bills the input video again (not measured live yet: the
    #: estimate assumes it does, so the weight never falls short).
    final_counts_input_video: bool
    #: The input seconds a reference video of unknown length is priced at (the most a
    #: Seedance 2.5 task takes in all).
    unknown_input_video_seconds: float
    #: «Con audio»: what the sound adds per second (v7: nothing, measured 2026-10-23).
    audio_usd_per_second: Decimal

    def cost(
        self, seconds: int, *, input_video_seconds: float = 0, audio: bool = False
    ) -> tuple[Decimal, Decimal]:
        """(fixed + preview, final) in USD for `seconds` of output."""
        out = Decimal(min(max(seconds, 1), self.max_output_seconds))
        if input_video_seconds > 0:
            source = Decimal(str(input_video_seconds))
            preview = self.preview_usd_per_second_with_video * (out + source)
            final_seconds = out + source if self.final_counts_input_video else out
            final = self.final_usd_per_second_with_video * final_seconds
        else:
            preview = self.preview_usd_per_second * out
            final = self.final_usd_per_second * out
        if audio:
            sound = self.audio_usd_per_second * out
            preview, final = preview + sound, final + sound
        return self.fixed_usd + preview, final


@dataclass(frozen=True)
class VideoQuota:
    """v2 (founder, 2026-10-24): the month's generated videos, apart from creations."""

    monthly_quota: int
    #: The lengths a generated video is offered at (5 and 10 s); each counts as 1.
    offered_seconds: tuple[int, ...]

    @property
    def max_seconds(self) -> int:
        return self.offered_seconds[-1]


@dataclass(frozen=True)
class CreationWeights:
    """One versioned weights table (`creations_data/<version>.json`)."""

    version: str
    pricing_table_version: str
    usd_per_creation: Decimal
    monthly_quota: int
    flat: dict[str, int]
    carousel_by_images: tuple[_Step, ...]
    generated_video_by_seconds: tuple[_Step, ...]
    presenter_by_seconds: tuple[_Step, ...]
    #: v2 (pricing v7): the generated video's USD priced from the table (the team's
    #: ceiling per video); None in v1.
    video_rates: VideoRates | None = None
    #: v2: generated videos have their own monthly quota and use no creations; None in
    #: v1, which priced them in creations by `generated_video_by_seconds`.
    videos: VideoQuota | None = None

    @property
    def monthly_video_quota(self) -> int:
        """How many generated videos a month brings (0 when the table has no quota)."""
        return 0 if self.videos is None else self.videos.monthly_quota

    def video(self, seconds: int) -> int:
        """v2: one generated video — 1 of the month's videos at any offered length; a
        longer one (15 s and up) is not offered."""
        if self.videos is None:
            raise CreationNotOffered(f"{self.version} has no video quota")
        if seconds > self.videos.max_seconds:
            raise CreationNotOffered(f"no video of {seconds} s is offered")
        return 1

    def flat_weight(self, key: str) -> int:
        try:
            return self.flat[key]
        except KeyError:
            raise KeyError(f"{self.version} has no weight for {key!r}") from None

    @staticmethod
    def _stepped(steps: tuple[_Step, ...], amount: int, what: str) -> int:
        for step in steps:
            if amount <= step.up_to:
                return step.weight
        raise CreationNotOffered(f"no weight for {what} of {amount}")

    def carousel(self, images: int) -> int:
        return self._stepped(self.carousel_by_images, max(images, 1), "a carousel")

    def generated_video_usd(
        self,
        seconds: int,
        *,
        reference_videos: int = 0,
        input_video_seconds: float | None = None,
        audio: bool = False,
    ) -> Decimal:
        """v2: what one generated video costs the team at p95 (480p preview + 1080p
        final, USD) — the ceiling one of the month's videos stands for. A reference
        video whose length is not known is priced at the most a task takes."""
        rates = self.video_rates
        if rates is None:
            raise KeyError(f"{self.version} prices no generated video in USD")
        source = 0.0
        if reference_videos > 0:
            source = (
                rates.unknown_input_video_seconds
                if input_video_seconds is None
                else max(input_video_seconds, 0.0)
            )
        preview, final = rates.cost(seconds, input_video_seconds=source, audio=audio)
        return preview + final

    def generated_video(self, seconds: int) -> int:
        """v1 only: a generated video in creations, by its steps (clamped to 15 s)."""
        clamped = min(max(seconds, 1), _GENERATED_VIDEO_MAX_SECONDS)
        return self._stepped(self.generated_video_by_seconds, clamped, "a generated video")

    def presenter(self, seconds: int) -> int:
        return self._stepped(self.presenter_by_seconds, max(seconds, 1), "a presenter")

    @property
    def presenter_max_seconds(self) -> int:
        return self.presenter_by_seconds[-1].up_to

    @property
    def shortest_presenter(self) -> tuple[int, int]:
        """(seconds, weight) of the cheapest presenter (v2: 5 s, 5 creations)."""
        step = self.presenter_by_seconds[0]
        return step.up_to, step.weight

    def longest_presenter_within(self, left: int) -> tuple[int, int] | None:
        """(seconds, weight) of the longest presenter `left` creations pay for — what the
        screen offers when the month cannot pay the one asked; None when none fits."""
        fits = [step for step in self.presenter_by_seconds if step.weight <= left]
        if not fits:
            return None
        return fits[-1].up_to, fits[-1].weight


def _video_rates(raw: dict[str, Any], pricing_version: str) -> VideoRates:
    """v2's generated-video block, priced off pricing table `pricing_version`: an
    unpriced model or resolution raises from the table instead of weighing zero."""
    table = JsonPricingTable(pricing_version)
    model_id = str(raw["model_id"])
    million = Decimal(1_000_000)

    def per_second(resolution: str, tokens: int, with_video: bool) -> Decimal:
        unit = f"per_mtok_video_{resolution}" + ("_with_video" if with_video else "")
        return Decimal(tokens) * table.unit_price(model_id=model_id, unit=unit) / million

    preview, final = str(raw["preview_resolution"]), str(raw["final_resolution"])
    preview_tokens = int(raw["preview_tokens_per_second"])
    final_tokens = int(raw["final_tokens_per_second"])
    return VideoRates(
        model_id=model_id,
        max_output_seconds=int(raw["max_output_seconds"]),
        fixed_usd=Decimal(str(raw["fixed_usd"])),
        preview_usd_per_second=per_second(preview, preview_tokens, False),
        final_usd_per_second=per_second(final, final_tokens, False),
        preview_usd_per_second_with_video=per_second(preview, preview_tokens, True),
        final_usd_per_second_with_video=per_second(final, final_tokens, True),
        final_counts_input_video=bool(raw["final_counts_input_video"]),
        unknown_input_video_seconds=float(raw["unknown_input_video_seconds"]),
        audio_usd_per_second=Decimal(str(raw["audio_usd_per_second"])),
    )


def _steps(raw: list[dict[str, Any]]) -> tuple[_Step, ...]:
    steps = tuple(_Step(up_to=int(row["up_to"]), weight=int(row["weight"])) for row in raw)
    if list(steps) != sorted(steps, key=lambda s: s.up_to):
        raise ValueError("weight steps must be sorted by `up_to`")
    return steps


@lru_cache(maxsize=4)
def load_weights(version: str = CREATIONS_WEIGHTS_VERSION) -> CreationWeights:
    """Read and cache one weights file; refuses a file that declares another version."""
    path = _DATA_DIR / f"{version}.json"
    if not path.is_file():
        raise KeyError(f"unknown creations weights {version!r}: no data file at {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("version") != version:
        raise ValueError(f"{path.name} declares {raw.get('version')!r}, expected {version!r}")
    pricing_version = str(raw["pricing_table_version"])
    video = raw.get("generated_video")
    videos = raw.get("videos")
    return CreationWeights(
        version=version,
        pricing_table_version=pricing_version,
        usd_per_creation=Decimal(str(raw["usd_per_creation"])),
        monthly_quota=int(raw["monthly_quota"]),
        flat={key: int(value) for key, value in raw["weights"].items()},
        carousel_by_images=_steps(raw["carousel_by_images"]),
        generated_video_by_seconds=_steps(raw.get("generated_video_by_seconds", [])),
        presenter_by_seconds=_steps(raw["presenter_by_seconds"]),
        video_rates=None if video is None else _video_rates(video, pricing_version),
        videos=None
        if videos is None
        else VideoQuota(
            monthly_quota=int(videos["monthly_quota"]),
            offered_seconds=tuple(sorted(int(s) for s in videos["offered_seconds"])),
        ),
    )


@dataclass(frozen=True)
class CreationPrice:
    """What one request costs — creations and (v2) generated videos — and what it is
    (for the charge's row)."""

    request_kind: str
    #: Creations (of the month's 30).
    weight: int
    #: The presenter's length the weight was read for (None for any other request).
    presenter_seconds: int | None = None
    #: v2: how many of the month's generated videos it uses (a clip 1, a carousel one
    #: per animated slide). Charged at creation; a failed 1080p final gives its back.
    videos: int = 0

    @property
    def is_presenter(self) -> bool:
        return self.request_kind == REQUEST_PRESENTER


def own_script_seconds(chars: int) -> int:
    """A presenter reading the operator's own script lasts about this long."""
    return max(1, math.ceil(chars / CHARS_PER_SECOND))


def is_presenter_request(kind: str, video_engine: str) -> bool:
    """A talking presenter: an avatar kind on OmniHuman (or the retired HeyGen, which the
    producer refuses — priced the same so nothing is ever cheaper than it says)."""
    avatar = kind in (ContentKind.AVATAR_VIDEO.value, ContentKind.ANIMATED_AVATAR_VIDEO.value)
    return avatar and video_engine != VideoEngine.SEEDANCE.value


def weight_for_request(
    kind: str,
    *,
    duration_seconds: int = 30,
    video_engine: str = VideoEngine.OMNIHUMAN.value,
    own_script_chars: int = 0,
    carousel_images: int = 0,
    generated_slides: int = 0,
    animated_slide_seconds: tuple[int, ...] = (),
    animated_slide_references: tuple[bool, ...] = (),
    reference_videos: int = 0,
    reference_video_seconds: float | None = None,
    audio: bool = False,
    redo: bool = False,
    weights: CreationWeights | None = None,
) -> CreationPrice:
    """The creations one request uses, from what the form (or the brief) says.

    - an image: 1 (its other version too); as a carousel, by how many images it makes;
    - a script for a real person, a template (still or video): 1;
    - a gallery: by its generated stills, plus (v2) one of the month's videos per
      animated slide — with or without a reference video;
    - a clip, or an avatar on Seedance: (v2) one of the month's videos and no
      creations, at 5 or 10 s (for a clip `duration_seconds` is the CLIP's length);
      longer is `CreationNotOffered`. The v1 table priced them in creations;
    - a talking presenter: by its length — the operator's own script's estimate, else the
      length asked; longer than the table's longest row is `CreationNotOffered` (v2:
      5, 10, 15 and 30 s only).
    """
    table = weights or load_weights()
    if kind == ContentKind.CREATOR_SCRIPT.value:
        return CreationPrice(REQUEST_SCRIPT, table.flat_weight("script"))
    if kind == ContentKind.TEMPLATE.value:
        return CreationPrice(REQUEST_TEMPLATE, table.flat_weight("template"))
    if kind == ContentKind.STATIC_FLYER.value:
        if carousel_images > 1:
            return CreationPrice(REQUEST_CAROUSEL, table.carousel(carousel_images))
        key = REQUEST_IMAGE_REDO if redo else REQUEST_IMAGE
        return CreationPrice(key, table.flat_weight(key))
    # the reference videos, their length and the sound no longer change what a video
    # uses (v2: 1 each); they still price the team's USD (`generated_video_usd`)
    del animated_slide_references, reference_videos, reference_video_seconds, audio
    if kind == ContentKind.CAROUSEL.value:
        weight = table.carousel(generated_slides)
        if table.videos is None:
            weight += sum(table.generated_video(s) for s in animated_slide_seconds)
            return CreationPrice(REQUEST_CAROUSEL, weight)
        videos = sum(table.video(s) for s in animated_slide_seconds)
        return CreationPrice(REQUEST_CAROUSEL, weight, videos=videos)
    if kind == ContentKind.CLIP.value:
        return _generated_video_price(table, duration_seconds)
    if is_presenter_request(kind, video_engine):
        seconds = own_script_seconds(own_script_chars) if own_script_chars else duration_seconds
        # priced at the row it falls in: a 22 s script is a 30 s presenter
        weight = table.presenter(seconds)
        bucket = next(s.up_to for s in table.presenter_by_seconds if seconds <= s.up_to)
        return CreationPrice(REQUEST_PRESENTER, weight, presenter_seconds=bucket)
    if kind in _AVATAR_KINDS:
        return _generated_video_price(table, duration_seconds)
    raise CreationNotOffered(f"no weight for kind {kind!r}")


def _generated_video_price(table: CreationWeights, seconds: int) -> CreationPrice:
    """One Seedance video: v2 one of the month's videos (no creations); v1 creations."""
    if table.videos is None:
        return CreationPrice(REQUEST_GENERATED_VIDEO, table.generated_video(seconds))
    return CreationPrice(REQUEST_GENERATED_VIDEO, 0, videos=table.video(seconds))


def weight_for(
    brief: ContentBrief, *, redo: bool = False, weights: CreationWeights | None = None
) -> CreationPrice:
    """`weight_for_request` read off a stored brief — what the service charges."""
    media = brief.media
    kind = brief.kind
    carousel_images = (
        max(len(media.product_keys), 1)
        if kind is ContentKind.STATIC_FLYER and media.carousel
        else 0
    )
    slides = media.slides if kind is ContentKind.CAROUSEL else ()
    animated = tuple(s for s in slides if s.source is SlideSource.ANIMATED)
    clip = kind is ContentKind.CLIP
    return weight_for_request(
        kind.value,
        duration_seconds=media.duration_seconds,
        video_engine=media.video_engine.value,
        own_script_chars=len(media.own_script.strip()) if kind.is_video else 0,
        carousel_images=carousel_images,
        generated_slides=sum(1 for s in slides if s.source is SlideSource.GENERATED),
        animated_slide_seconds=tuple(s.seconds or _SLIDE_SECONDS for s in animated),
        animated_slide_references=tuple(bool(s.reference_video_key) for s in animated),
        reference_videos=len(media.clip_video_keys) if clip else 0,
        audio=media.clip_audio if clip else False,
        redo=redo,
        weights=weights,
    )


__all__ = [
    "CHARS_PER_SECOND",
    "CREATIONS_WEIGHTS_VERSION",
    "REQUEST_CAROUSEL",
    "REQUEST_GENERATED_VIDEO",
    "REQUEST_IMAGE",
    "REQUEST_IMAGE_REDO",
    "REQUEST_PRESENTER",
    "REQUEST_SCRIPT",
    "REQUEST_TEMPLATE",
    "CreationNotOffered",
    "CreationPrice",
    "CreationWeights",
    "VideoQuota",
    "VideoRates",
    "is_presenter_request",
    "load_weights",
    "own_script_seconds",
    "weight_for",
    "weight_for_request",
]
