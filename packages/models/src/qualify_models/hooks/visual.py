"""Deterministic visual features of the opening window: cut rate, motion, brightness,
saturation, palette.

Tier: deterministic. These are computed from pixels with PIL, cost nothing, hit no
network, and are exactly reproducible — so they need no golden set and cannot drift when
a provider changes. They are the floor under the analysis: if the VLM tier turns out
unreliable, these still stand.

No numpy on purpose. `pillow` is a hard dependency of this package, numpy is only present
transitively via the `ml` group, and this module must import in a CI job that has no
torch installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from qualify_models.hooks.spec import CUT_DIFF_THRESHOLD

# Frames are compared at this size, not full 1080x1920: a cut is a global change, and
# downscaling suppresses the per-pixel noise (grain, compression) that would otherwise
# read as motion.
_DIFF_SIZE = (64, 64)
_PALETTE_CELL = (32, 32)


@dataclass
class DeterministicVisual:
    n_frames: int
    cut_count: int
    cuts_per_second: float
    motion_energy: float
    brightness: float
    saturation: float
    dominant_colors: list[str] = field(default_factory=list)


def analyze_frames(
    frame_paths: list[Path],
    window_seconds: float,
    cut_threshold: float = CUT_DIFF_THRESHOLD,
) -> DeterministicVisual:
    """Compute the deterministic tier over one window's sampled frames.

    `cut_count` is a *proxy*, and is labelled as such everywhere it appears: it counts
    consecutive-frame differences above a fixed threshold, which also fires on a fast
    whip-pan or a hard zoom. Calling it "cuts" is convenient, not validated — it has
    never been checked against hand-labelled cuts. See NOTES_hook_pattern_spike.md §B.3.
    """
    if not frame_paths:
        return DeterministicVisual(
            n_frames=0,
            cut_count=0,
            cuts_per_second=0.0,
            motion_energy=0.0,
            brightness=0.0,
            saturation=0.0,
        )

    images = [Image.open(p).convert("RGB") for p in frame_paths]

    brightness = _mean([ImageStat.Stat(img.convert("L")).mean[0] / 255.0 for img in images])
    saturation = _mean(
        [ImageStat.Stat(img.convert("HSV").getchannel("S")).mean[0] / 255.0 for img in images]
    )

    diffs = _frame_diffs(images)
    cut_count = sum(1 for d in diffs if d > cut_threshold)
    motion_energy = _mean(diffs) if diffs else 0.0
    cuts_per_second = cut_count / window_seconds if window_seconds > 0 else 0.0

    return DeterministicVisual(
        n_frames=len(images),
        cut_count=cut_count,
        cuts_per_second=cuts_per_second,
        motion_energy=motion_energy,
        brightness=brightness,
        saturation=saturation,
        dominant_colors=dominant_colors(images),
    )


def _frame_diffs(images: list[Image.Image]) -> list[float]:
    """Mean absolute luma difference between consecutive frames, normalized to 0-1."""
    small = [img.convert("L").resize(_DIFF_SIZE) for img in images]
    return [
        ImageStat.Stat(ImageChops.difference(a, b)).mean[0] / 255.0
        for a, b in zip(small, small[1:])
    ]


def dominant_colors(images: list[Image.Image], n_colors: int = 4) -> list[str]:
    """Top palette entries across the whole window, most-used first, as hex.

    All frames are tiled into one small strip before quantizing so the palette describes
    the *window*, not whichever frame happened to be sampled first.
    """
    if not images:
        return []
    cells = [img.resize(_PALETTE_CELL) for img in images]
    strip = Image.new("RGB", (_PALETTE_CELL[0] * len(cells), _PALETTE_CELL[1]))
    for index, cell in enumerate(cells):
        strip.paste(cell, (index * _PALETTE_CELL[0], 0))

    quantized = strip.quantize(colors=n_colors, method=Image.Quantize.FASTOCTREE)
    palette = quantized.getpalette() or []
    counts = sorted(quantized.getcolors() or [], key=lambda pair: pair[0], reverse=True)
    hexes: list[str] = []
    for _count, index in counts[:n_colors]:
        r, g, b = palette[index * 3 : index * 3 + 3]
        hexes.append(f"#{r:02x}{g:02x}{b:02x}")
    return hexes


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0
