"""Subject segmentation — one inference, many consumers.

The output of this stage is a MASK, not a cut-out photo. The mask is persisted next to
the asset and read by every derived feature (cutout, shadow, subject-only enhancement,
subject-aware reframing, text placement). Running segmentation once and keeping the mask
is the pixel-level form of the module's governing rule: pay to discover, not to repeat.

License guard: the model name is pinned here and MUST NOT be `bria-rmbg` — it is rembg's
current default and works perfectly, but its weights require a paid agreement for
commercial use. A silent foot-gun, caught by a static test. `birefnet-general-lite` is
MIT and state of the art. Upgrade path (no new architecture): `fal-ai/birefnet/v2`
through the existing FalAdapter; edge refinement escalates -matting → _HR before any
vendor call. See docs/research-features-tratamiento-foto.md §1 + adenda.
"""

from __future__ import annotations

from typing import Protocol

from PIL import Image

SEGMENTATION_MODEL = "birefnet-general-lite"

_FORBIDDEN_MODELS = frozenset({"bria-rmbg"})


class Segmenter(Protocol):
    """Seam so the heavy model dependency stays out of import time — the same rule the
    vendor SDKs follow. Business code depends on this Protocol; tests inject a fake."""

    def mask(self, image: Image.Image) -> Image.Image:
        """Return an 8-bit alpha mask ("L"), same size as `image`."""
        ...


class LocalBiRefNetSegmenter:
    """rembg + BiRefNet lite, on-CPU. ~2s per photo; photos never leave the machine."""

    def __init__(self, model_name: str = SEGMENTATION_MODEL) -> None:
        if model_name in _FORBIDDEN_MODELS:
            raise ValueError(
                f"{model_name!r} requires a paid agreement for commercial use; "
                f"use {SEGMENTATION_MODEL!r}"
            )
        self._model_name = model_name
        self._session = None

    def mask(self, image: Image.Image) -> Image.Image:
        if self._session is None:
            from rembg import new_session  # noqa: PLC0415

            self._session = new_session(self._model_name)
        from rembg import remove  # noqa: PLC0415

        cut = remove(image, session=self._session)
        return cut.split()[3] if cut.mode == "RGBA" else cut.convert("L")
