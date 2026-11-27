"""m-25142725: how many references an AI part may follow, per video model.

Deivid (2026-11-27): each model declares its own limits. These are the PRODUCT's caps —
what one AI part of a Clip may take from the reference tracks (photos, videos, audios) —
not the vendor's API maxima: Seedance 2.5's API takes 30/10/10
(`adapters.byteplus_ark.SeedanceFamily.max_references`), and the product keeps every
Seedance model at 9/3/3 today. A new model is a new row (Magi-2 is planned at 10/5/5;
not added until it lands). A model with no row has no known caps: never guessed.

Pure data, no I/O. Which model a part uses (the active video model by default) is the
caller's: `qualify_api.creative.video_pipeline.ai_parts.reference_caps`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ReferenceCaps:
    """At most this many photos, videos and audios under one AI part."""

    photo: int
    video: int
    audio: int

    def of(self, kind: str) -> int:
        """The cap of one `ReferenceKind`."""
        return {"photo": self.photo, "video": self.video, "audio": self.audio}[kind]

    def as_mapping(self) -> Mapping[str, int]:
        """`{"photo": …, "video": …, "audio": …}`, read-only."""
        return MappingProxyType({"photo": self.photo, "video": self.video, "audio": self.audio})


#: Seedance 2.x, every family (Deivid, 2026-11-27: «Today Seedance is 9 photos, 3 videos,
#: 3 audios»).
SEEDANCE_REFERENCE_CAPS = ReferenceCaps(photo=9, video=3, audio=3)

#: Model FAMILY id (the id without its `-YYMMDD` date) → its caps. Only models that take
#: references (Seedance 1.x takes none).
REFERENCE_CAPS_BY_MODEL: Mapping[str, ReferenceCaps] = MappingProxyType(
    {
        "dreamina-seedance-2-0": SEEDANCE_REFERENCE_CAPS,
        "dreamina-seedance-2-0-fast": SEEDANCE_REFERENCE_CAPS,
        "dreamina-seedance-2-0-mini": SEEDANCE_REFERENCE_CAPS,
        "dreamina-seedance-2-5": SEEDANCE_REFERENCE_CAPS,
    }
)


def _family(model_id: str) -> str:
    """`dreamina-seedance-2-0-mini-260615` → `dreamina-seedance-2-0-mini`: only a six-digit
    `YYMMDD` suffix is a date (as `byteplus_ark.seedance_family` reads it)."""
    if model_id in REFERENCE_CAPS_BY_MODEL:
        return model_id
    base, _, suffix = model_id.rpartition("-")
    return base if suffix.isdigit() and len(suffix) == 6 else model_id


def reference_caps_for(model_id: str) -> ReferenceCaps:
    """The caps of `model_id`, dated or not. An unknown model raises `ValueError`: a
    model whose limits nobody wrote down is not guessed."""
    try:
        return REFERENCE_CAPS_BY_MODEL[_family(model_id)]
    except KeyError:
        raise ValueError(
            f"no reference caps for video model {model_id!r};"
            f" known: {sorted(REFERENCE_CAPS_BY_MODEL)}"
        ) from None


__all__ = [
    "REFERENCE_CAPS_BY_MODEL",
    "SEEDANCE_REFERENCE_CAPS",
    "ReferenceCaps",
    "reference_caps_for",
]
