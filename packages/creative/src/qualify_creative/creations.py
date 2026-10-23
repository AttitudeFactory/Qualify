"""«Creaciones del mes» (CREAR-5, m-24848531): what each request costs the owner, in
creations, never in money.

The owner sees «Te quedan 18 de 30 este mes»; the team sees the dollars. One creation is
USD 0.15 of vendor cost (a ceiling, not an average) and a request weighs
⌈p95 cost / 0.15⌉, at least 1 — measured in `docs/creaciones-del-mes-medicion.md` over
pricing table `v5`. The weights live in a versioned data file
(`creations_data/<version>.json`), never as literals here: a new weight is a new file
(`pesos-creaciones-v2`), and every charge records the version it was priced with.

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
from qualify_creative.schemas import ContentBrief

_DATA_DIR = Path(__file__).parent / "creations_data"

#: The weights in force. A new table is a new file and a new constant, never an edit.
CREATIONS_WEIGHTS_VERSION = "pesos-creaciones-v1"

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
#: The longest generated (Seedance) video a request is priced for: every Seedance family
#: the app calls caps at 12-15 s, so a longer ask is clamped by the vendor.
_GENERATED_VIDEO_MAX_SECONDS = 15
#: An animated carousel slide's default length (`CarouselSlide.seconds`).
_SLIDE_SECONDS = 5


class CreationNotOffered(ValueError):
    """The weights table has no row for this request (e.g. a 45 s presenter)."""


@dataclass(frozen=True)
class _Step:
    up_to: int
    weight: int


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

    def generated_video(self, seconds: int) -> int:
        clamped = min(max(seconds, 1), _GENERATED_VIDEO_MAX_SECONDS)
        return self._stepped(self.generated_video_by_seconds, clamped, "a generated video")

    def presenter(self, seconds: int) -> int:
        return self._stepped(self.presenter_by_seconds, max(seconds, 1), "a presenter")

    @property
    def presenter_max_seconds(self) -> int:
        return self.presenter_by_seconds[-1].up_to

    @property
    def shortest_presenter(self) -> tuple[int, int]:
        """(seconds, weight) of the cheapest presenter — what the screen offers when the
        month's balance cannot pay for the one asked (CREAR-5: 15 s, 13 creations)."""
        step = self.presenter_by_seconds[0]
        return step.up_to, step.weight


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
    return CreationWeights(
        version=version,
        pricing_table_version=str(raw["pricing_table_version"]),
        usd_per_creation=Decimal(str(raw["usd_per_creation"])),
        monthly_quota=int(raw["monthly_quota"]),
        flat={key: int(value) for key, value in raw["weights"].items()},
        carousel_by_images=_steps(raw["carousel_by_images"]),
        generated_video_by_seconds=_steps(raw["generated_video_by_seconds"]),
        presenter_by_seconds=_steps(raw["presenter_by_seconds"]),
    )


@dataclass(frozen=True)
class CreationPrice:
    """What one request costs in creations, and what it is (for the charge's row)."""

    request_kind: str
    weight: int
    #: The presenter's length the weight was read for (None for any other request).
    presenter_seconds: int | None = None

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
    redo: bool = False,
    weights: CreationWeights | None = None,
) -> CreationPrice:
    """The creations one request uses, from what the form (or the brief) says.

    - an image: 1 (its other version too); as a carousel, by how many images it makes;
    - a script for a real person, a template (still or video): 1;
    - a gallery: by its generated stills, plus each animated slide as a generated video;
    - a clip, or an avatar on Seedance: a generated video of its length (≤ 15 s);
    - a talking presenter: by its length — the operator's own script's estimate, else the
      length asked; longer than the table's longest row is `CreationNotOffered`.
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
    if kind == ContentKind.CAROUSEL.value:
        weight = table.carousel(generated_slides) + sum(
            table.generated_video(seconds) for seconds in animated_slide_seconds
        )
        return CreationPrice(REQUEST_CAROUSEL, weight)
    if kind == ContentKind.CLIP.value:
        return CreationPrice(REQUEST_GENERATED_VIDEO, table.generated_video(duration_seconds))
    if is_presenter_request(kind, video_engine):
        seconds = own_script_seconds(own_script_chars) if own_script_chars else duration_seconds
        # priced at the row it falls in: a 22 s script is a 30 s presenter
        weight = table.presenter(seconds)
        bucket = next(s.up_to for s in table.presenter_by_seconds if seconds <= s.up_to)
        return CreationPrice(REQUEST_PRESENTER, weight, presenter_seconds=bucket)
    if kind in (ContentKind.AVATAR_VIDEO.value, ContentKind.ANIMATED_AVATAR_VIDEO.value):
        return CreationPrice(REQUEST_GENERATED_VIDEO, table.generated_video(duration_seconds))
    raise CreationNotOffered(f"no weight for kind {kind!r}")


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
    return weight_for_request(
        kind.value,
        duration_seconds=media.duration_seconds,
        video_engine=media.video_engine.value,
        own_script_chars=len(media.own_script.strip()) if kind.is_video else 0,
        carousel_images=carousel_images,
        generated_slides=sum(1 for s in slides if s.source is SlideSource.GENERATED),
        animated_slide_seconds=tuple(
            s.seconds or _SLIDE_SECONDS for s in slides if s.source is SlideSource.ANIMATED
        ),
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
    "is_presenter_request",
    "load_weights",
    "own_script_seconds",
    "weight_for",
    "weight_for_request",
]
