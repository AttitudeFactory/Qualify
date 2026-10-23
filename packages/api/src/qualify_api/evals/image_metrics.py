"""Deterministic, offline image checks for the Seedream color/texture eval (m-24849234).

Nothing here calls a vendor: Pillow + numpy only (no scipy, scikit-image or OpenCV).

- **Flat finish** (`flat_texture_fill`): the logo's silhouette at 1080 px on the long side,
  filled with the texture image, on a transparent background, with the checks of the
  ticket's criterion «Aplicar textura en acabado plano»: the silhouette matches the
  logo's and nothing of the stroke is lost (the texture fills the silhouette by
  construction).
- **Color transfer** (`color_transfer_metrics`): the result's dominant colors inside the
  object mask against the reference palette, in CIE Lab, both ways; how far the model
  drifted outside the mask before recomposition; and the recomposed image's soft edge.
  Outside the mask the recomposed image is the original by construction.
- **Legibility** (local part only): a `LegibilityReader` protocol, the exact-match rules
  and a deterministic `FakeReader`. The reader backed by Claude's vision is PR 3.
"""

from __future__ import annotations

import functools
import hashlib
import io
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
from PIL import Image, ImageChops, ImageCms, ImageOps

from qualify_api.evals.spend_control import has_transparency, png_bytes

#: The flat finish is made at this size on the long side (the ticket's 1080 px).
FLAT_LONG_SIDE = 1080
#: An opaque logo's silhouette: the largest per-channel difference from the corner color,
#: ramped from 0 (difference <= 32) to 255 (difference >= 64) — a soft 8-bit mask centred
#: on the previous hard threshold of 48.
SILHOUETTE_THRESHOLD = 48
SILHOUETTE_RAMP = 16
#: Pass marks of the flat finish. The ticket asks for a mask difference under 1 % of the
#: pixels; IoU >= 0.98 is the same requirement read on the silhouette alone.
MIN_MASK_IOU = 0.98
MAX_MASK_DIFF_FRACTION = 0.01
#: A stroke thinner than this at 1080 px counts as lost (it no longer reads as a line).
MIN_STROKE_PX = 2
#: Components smaller than this many px AT THE OUTPUT SIZE are antialiasing specks, not
#: strokes, and are not counted (at native size the bar is scaled by the area ratio).
MIN_COMPONENT_AREA = 4
#: `min_stroke_width` is exact up to this many px (one 2x2 erosion per px); thicker reads
#: as the cap.
STROKE_PROBE_CAP = 80
#: Provenance of the color and legibility records (the flat block has `FLAT_VERSION`).
METRICS_VERSION = "metricas-v1"

#: Palette extraction: k-means in Lab with a fixed seed, on at most this many pixels.
PALETTE_COLORS = 3
PALETTE_SEED = 0
PALETTE_SAMPLE = 20_000
#: Provisional threshold (CIE76 ΔE) for «dominant colors close to the reference
#: palette». The ticket leaves it to be agreed; PR 3 calibrates it on the real run.
PALETTE_DELTA_E_MAX = 10.0


# ---------------------------------------------------------------------------
# Masks: silhouette, IoU, connected components, stroke width


def _open(data: bytes) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(io.BytesIO(data)))


def silhouette(image: Image.Image) -> tuple[Image.Image, str]:
    """The logo's 8-bit mask and where it came from: its alpha (`"alpha"`), or for an
    opaque logo the soft per-channel max difference from the top-left corner color
    (`"corner"`)."""
    if has_transparency(image):
        return image.convert("RGBA").getchannel("A"), "alpha"
    rgb = image.convert("RGB")
    background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    r, g, b = ImageChops.difference(rgb, background).split()
    # the largest channel difference: a luminance mix would lose yellow on white
    diff = np.asarray(ImageChops.lighter(ImageChops.lighter(r, g), b), dtype=np.float32)
    low = SILHOUETTE_THRESHOLD - SILHOUETTE_RAMP
    soft = np.clip((diff - low) * 255.0 / (2 * SILHOUETTE_RAMP), 0, 255)
    return Image.fromarray(soft.astype(np.uint8), mode="L"), "corner"


def binary(mask: Image.Image, threshold: int = 128) -> np.ndarray:
    """The mask as booleans: a pixel belongs to the shape from `threshold` up."""
    return np.asarray(mask.convert("L")) >= threshold


def mask_iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    if union == 0:
        return 1.0
    return float(np.logical_and(a, b).sum() / union)


def _runs(shape: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Horizontal runs of True pixels: rows, starts and (exclusive) ends, row-major."""
    h, w = shape.shape
    padded = np.zeros((h, w + 2), dtype=np.int8)
    padded[:, 1:-1] = shape
    step = np.diff(padded, axis=1)
    rows, starts = np.nonzero(step == 1)
    _, ends = np.nonzero(step == -1)
    return rows, starts, ends


def label_components(shape: np.ndarray) -> tuple[np.ndarray, int]:
    """8-connected components of a boolean mask: (labels 1..n, 0 = background; n).
    Run-length union-find, fast enough for a 1080 px logo."""
    rows, starts, ends = _runs(shape)
    count = len(rows)
    parent = list(range(count))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    row_first = np.searchsorted(rows, np.arange(shape.shape[0] + 1))
    for r in range(1, shape.shape[0]):
        i, i_end = int(row_first[r]), int(row_first[r + 1])
        j, j_end = int(row_first[r - 1]), int(row_first[r])
        while i < i_end and j < j_end:
            # [s, e) on row r touches [ps, pe) on row r - 1, diagonals included
            if starts[i] <= ends[j] and starts[j] <= ends[i]:
                a, b = find(i), find(int(j))
                if a != b:
                    parent[max(a, b)] = min(a, b)
            if ends[j] < ends[i]:
                j += 1
            else:
                i += 1
    labels = np.zeros(shape.shape, dtype=np.int32)
    ids: dict[int, int] = {}
    for k in range(count):
        root = find(k)
        label = ids.setdefault(root, len(ids) + 1)
        labels[rows[k], starts[k] : ends[k]] = label
    return labels, len(ids)


def count_components(shape: np.ndarray, *, min_area: int = MIN_COMPONENT_AREA) -> int:
    labels, n = label_components(shape)
    if n == 0:
        return 0
    areas = np.bincount(labels.ravel(), minlength=n + 1)[1:]
    return int((areas >= min_area).sum())


def erode_2x2(shape: np.ndarray) -> np.ndarray:
    """One 2x2 binary erosion: a pixel stays when it and its right, lower and lower-right
    neighbours are set (outside the image is background). Each one takes exactly one
    pixel off a stroke's thickness, so a w px stroke vanishes at the w-th."""
    padded = np.pad(shape, ((0, 1), (0, 1)), constant_values=False)
    h, w = shape.shape
    return shape & padded[1 : h + 1, :w] & padded[:h, 1 : w + 1] & padded[1 : h + 1, 1 : w + 1]


def min_stroke_width(
    shape: np.ndarray, *, min_area: int = MIN_COMPONENT_AREA, cap: int = STROKE_PROBE_CAP
) -> int:
    """The thinnest component's thickness in px (0 for an empty mask), exact up to
    `cap` px: a result equal to `cap` means «at least `cap`».

    The mask is eroded with 2x2 erosions (`erode_2x2`) until a component vanishes;
    vanishing at the k-th erosion means its thickest part is k px wide (a 2 px stroke
    reads 2, a 3 px one 3). A thin part attached to a thick one is not seen here — the
    IoU and the component count catch that loss.
    """
    labels, n = label_components(shape)
    if n == 0:
        return 0
    areas = np.bincount(labels.ravel(), minlength=n + 1)
    alive = areas >= min_area
    alive[0] = False
    if not alive.any():
        return 0
    current = shape
    for k in range(1, cap + 1):
        current = erode_2x2(current)
        left = np.bincount(labels[current], minlength=n + 1)
        if np.any(alive & (left == 0)):
            return k
    return cap


def silhouette_match(native: np.ndarray, alpha: Image.Image) -> tuple[float, float, np.ndarray]:
    """(IoU, fraction of differing pixels, the output's shape at native size): the output
    alpha is area-resampled back to the native size and binarized, then compared with the
    native binarized silhouette — one resolution, one resampler, so a small logo does not
    fail on resampling disagreement."""
    back = binary(alpha.resize((native.shape[1], native.shape[0]), Image.BOX))
    return mask_iou(native, back), float(np.logical_xor(native, back).mean()), back


# ---------------------------------------------------------------------------
# Flat finish


@dataclass(frozen=True)
class FlatResult:
    """The flat finish of one logo with one texture, and its checks."""

    png: bytes = field(repr=False)
    size: tuple[int, int]
    mask_source: str
    mask_iou: float
    mask_diff_fraction: float
    min_stroke_px: int
    components_before: int
    components_after: int

    @property
    def stroke_lost(self) -> bool:
        return self.components_after < self.components_before or (
            self.min_stroke_px < MIN_STROKE_PX
        )

    @property
    def passed(self) -> bool:
        return (
            self.mask_iou >= MIN_MASK_IOU
            and self.mask_diff_fraction < MAX_MASK_DIFF_FRACTION
            and not self.stroke_lost
        )

    def as_record(self) -> dict[str, object]:
        return {
            "tamano": list(self.size),
            "origen_mascara": self.mask_source,
            "iou_mascara": round(self.mask_iou, 6),
            "diferencia_mascara": round(self.mask_diff_fraction, 6),
            "trazo_minimo_px": self.min_stroke_px,
            "componentes_antes": self.components_before,
            "componentes_despues": self.components_after,
            "trazo_perdido": self.stroke_lost,
            "aprobado": self.passed,
        }


def fit_long_side(size: tuple[int, int], long_side: int = FLAT_LONG_SIDE) -> tuple[int, int]:
    w, h = size
    scale = long_side / max(w, h)
    return max(1, round(w * scale)), max(1, round(h * scale))


def tile_texture(
    texture: Image.Image, size: tuple[int, int], glyph_box: tuple[int, int]
) -> Image.Image:
    """The texture scaled to the glyphs' height (keeping its aspect) and tiled over a
    canvas of `size`, rows aligned on the glyphs' top edge (`glyph_box` = top, bottom)."""
    top, bottom = glyph_box
    tile_h = max(1, bottom - top)
    tile_w = max(1, round(texture.width * tile_h / texture.height))
    tile = texture.convert("RGB").resize((tile_w, tile_h), Image.LANCZOS)
    canvas = Image.new("RGB", size)
    first_y = top - math.ceil(top / tile_h) * tile_h
    for y in range(first_y, size[1], tile_h):
        for x in range(0, size[0], tile_w):
            canvas.paste(tile, (x, y))
    return canvas


def flat_texture_fill(
    logo_bytes: bytes, texture_bytes: bytes, *, long_side: int = FLAT_LONG_SIDE
) -> FlatResult:
    """The logo at `long_side` px on its long side, every mark pixel filled with the
    texture, on a transparent background (RGBA PNG).

    The texture is scaled to the glyphs' height and tiled (one tile per text line, the
    same look whatever the texture's resolution). The output keeps the texture's own
    RGB and takes the silhouette as its alpha (`putalpha`): pasting onto a transparent
    canvas would darken the antialiased edges.

    Checks, all at the logo's native size: the native binarized silhouette against the
    output alpha area-resampled back (IoU and the fraction of pixels that differ) and the
    component count of both (specks under `MIN_COMPONENT_AREA` px at the output size are
    not counted); then the thinnest stroke at the output size.
    """
    logo = _open(logo_bytes)
    mask, source = silhouette(logo)
    size = fit_long_side(logo.size, long_side)
    alpha = mask.resize(size, Image.LANCZOS)
    native = binary(mask)
    iou, diff, back = silhouette_match(native, alpha)
    native_area = math.ceil(
        MIN_COMPONENT_AREA * (logo.size[0] * logo.size[1]) / (size[0] * size[1])
    )
    box = alpha.point(lambda v: 255 if v >= 128 else 0).getbbox()
    glyphs = (box[1], box[3]) if box else (0, size[1])
    out = tile_texture(_open(texture_bytes), size, glyphs).convert("RGBA")
    out.putalpha(alpha)
    return FlatResult(
        png=png_bytes(out),
        size=size,
        mask_source=source,
        mask_iou=iou,
        mask_diff_fraction=diff,
        min_stroke_px=min_stroke_width(binary(alpha)),
        components_before=count_components(native, min_area=native_area),
        components_after=count_components(back, min_area=native_area),
    )


# ---------------------------------------------------------------------------
# Color transfer: Lab palettes, background drift, recomposition


@functools.cache
def _lab_transform() -> ImageCms.ImageCmsTransform:
    return ImageCms.buildTransformFromOpenProfiles(
        ImageCms.createProfile("sRGB"), ImageCms.createProfile("LAB"), "RGB", "LAB"
    )


def to_lab(image: Image.Image) -> np.ndarray:
    """CIE Lab (D50, LittleCMS' built-in LAB profile) of an sRGB image, as floats
    (H, W, 3): L in 0..100, a and b signed."""
    lab = np.asarray(ImageCms.applyTransform(image.convert("RGB"), _lab_transform()))
    out = np.empty(lab.shape, dtype=np.float64)
    out[..., 0] = lab[..., 0] * (100.0 / 255.0)
    out[..., 1:] = np.ascontiguousarray(lab[..., 1:]).view(np.int8)  # a, b are int8
    return out


def kmeans_palette(
    points: np.ndarray,
    k: int = PALETTE_COLORS,
    *,
    seed: int = PALETTE_SEED,
    sample: int = PALETTE_SAMPLE,
    iterations: int = 50,
) -> np.ndarray:
    """`k` Lab centroids of `points` (N, 3): k-means++ start and Lloyd steps with a fixed
    seed, on at most `sample` pixels; fewer centroids when there are fewer distinct
    colors. Sorted by L, then a, then b, so the same input gives the same palette."""
    if not 1 <= k <= 8:
        raise ValueError("k must be within 1..8")
    if len(points) == 0:
        raise ValueError("no pixels to extract a palette from")
    rng = np.random.default_rng(seed)
    if len(points) > sample:
        points = points[rng.choice(len(points), size=sample, replace=False)]
    k = min(k, len(np.unique(points, axis=0)))
    centroids = [points[rng.integers(len(points))]]
    for _ in range(1, k):
        dist = np.min([((points - c) ** 2).sum(axis=1) for c in centroids], axis=0)
        if dist.sum() == 0:
            break
        centroids.append(points[rng.choice(len(points), p=dist / dist.sum())])
    centers = np.array(centroids, dtype=np.float64)
    for _ in range(iterations):
        nearest = np.argmin(((points[:, None, :] - centers[None]) ** 2).sum(axis=2), axis=1)
        moved = np.array(
            [
                points[nearest == i].mean(axis=0) if (nearest == i).any() else centers[i]
                for i in range(len(centers))
            ]
        )
        if np.allclose(moved, centers):
            break
        centers = moved
    return centers[np.lexsort((centers[:, 2], centers[:, 1], centers[:, 0]))]


def nearest_delta_e(source: np.ndarray, target: np.ndarray) -> float:
    """Mean over `source`'s centroids of the CIE76 ΔE to the nearest `target` centroid."""
    dist = np.sqrt(((source[:, None, :] - target[None]) ** 2).sum(axis=2))
    return float(dist.min(axis=1).mean())


def palette_delta_e(result: np.ndarray, reference: np.ndarray) -> float:
    """The palette distance, both ways: the larger of result → reference (every result
    color is in the reference) and reference → result (every reference color shows up in
    the result). One direction alone would let a result painted in a single reference
    color score 0."""
    return max(nearest_delta_e(result, reference), nearest_delta_e(reference, result))


def psnr_db(a: np.ndarray, b: np.ndarray) -> float:
    """PSNR in dB of two uint8 pixel sets of the same shape; `inf` when identical."""
    if a.size == 0:
        raise ValueError("no pixels to compare")
    mse = float(((a.astype(np.float64) - b.astype(np.float64)) ** 2).mean())
    return math.inf if mse == 0 else 10 * math.log10(255.0**2 / mse)


@dataclass(frozen=True)
class ColorMetrics:
    """`mask_source`: `"mask"` (the case's mask), `"alpha"` (the object image's own
    alpha) or `"none"` (no mask: the palette is the whole image, and the background
    numbers do not apply — PR 3 flags these).

    Outside the mask (== 0) the recomposed image IS the original, by construction, so it
    is not measured; `background_psnr_db` is the drift there BEFORE recomposition, and
    `edge_psnr_db` compares the recomposed image with the original on the mask's soft
    edge (0 < mask < 255), None for a hard mask."""

    mask_source: str
    reference_palette: tuple[tuple[float, float, float], ...]
    result_palette: tuple[tuple[float, float, float], ...]
    palette_delta_e: float
    result_to_reference_delta_e: float
    reference_to_result_delta_e: float
    background_psnr_db: float | None
    edge_psnr_db: float | None
    recomposed_png: bytes | None = field(repr=False)
    result_resized: bool

    @property
    def palette_ok(self) -> bool:
        return self.palette_delta_e <= PALETTE_DELTA_E_MAX

    def as_record(self) -> dict[str, object]:
        def rounded(palette: tuple[tuple[float, float, float], ...]) -> list[list[float]]:
            return [[round(v, 2) for v in color] for color in palette]

        return {
            "metricas_version": METRICS_VERSION,
            "origen_mascara": self.mask_source,
            "paleta_referencia_lab": rounded(self.reference_palette),
            "paleta_resultado_lab": rounded(self.result_palette),
            "delta_e_paleta": round(self.palette_delta_e, 3),
            "delta_e_resultado_a_referencia": round(self.result_to_reference_delta_e, 3),
            "delta_e_referencia_a_resultado": round(self.reference_to_result_delta_e, 3),
            "paleta_dentro_del_umbral": self.palette_ok,
            "psnr_fondo_db": _psnr_value(self.background_psnr_db),
            "borde_recompuesto_psnr_db": _psnr_value(self.edge_psnr_db),
            "resultado_redimensionado": self.result_resized,
        }


def _psnr_value(psnr: float | None) -> float | str | None:
    """JSON has no infinity: an identical background is recorded as the string `"inf"`."""
    if psnr is None:
        return None
    return "inf" if math.isinf(psnr) else round(psnr, 3)


def _palette(image: Image.Image, where: np.ndarray | None, k: int) -> np.ndarray:
    """The palette of `image` (inside `where`, if given): at most `PALETTE_SAMPLE` pixels
    are drawn first (fixed seed) and only those are converted to Lab, so a 12 MP photo
    never becomes a float64 copy."""
    rgb = np.asarray(image.convert("RGB")).reshape(-1, 3)
    index = np.flatnonzero(where) if where is not None else np.arange(len(rgb))
    if len(index) > PALETTE_SAMPLE:
        rng = np.random.default_rng(PALETTE_SEED)
        index = np.sort(rng.choice(index, size=PALETTE_SAMPLE, replace=False))
    if len(index) == 0:
        raise ValueError("no pixels to extract a palette from")
    strip = Image.fromarray(np.ascontiguousarray(rgb[index]).reshape(1, -1, 3), mode="RGB")
    return kmeans_palette(to_lab(strip).reshape(-1, 3), k)


def _distances(result: np.ndarray, reference: np.ndarray) -> dict[str, float]:
    forward, backward = nearest_delta_e(result, reference), nearest_delta_e(reference, result)
    return {
        "palette_delta_e": max(forward, backward),
        "result_to_reference_delta_e": forward,
        "reference_to_result_delta_e": backward,
    }


def color_transfer_metrics(
    original_bytes: bytes,
    result_bytes: bytes,
    reference_bytes: bytes,
    mask_bytes: bytes | None = None,
    *,
    k: int = PALETTE_COLORS,
) -> ColorMetrics:
    """The color-transfer checks of one generated image.

    The mask is the case's mask, else the object image's alpha, else none. A result of
    another size is resized to the original's first (`result_resized`). Inside the mask
    (>= 128) the result's palette is compared with the reference's (its opaque pixels);
    outside it (== 0) the PSNR between original and result says how far the model drifted
    BEFORE recomposition. The recomposed image (the result through the mask over the
    original) is the original there by construction; its soft edge is measured instead.
    """
    original_image = _open(original_bytes)
    original = original_image.convert("RGB")
    result = _open(result_bytes).convert("RGB")
    resized = result.size != original.size
    if resized:
        result = result.resize(original.size, Image.LANCZOS)
    reference_image = _open(reference_bytes)
    ref_where = binary(reference_image.convert("RGBA").getchannel("A"))
    reference_palette = _palette(reference_image, ref_where if ref_where.any() else None, k)

    mask: Image.Image | None
    if mask_bytes is not None:
        mask, source = _open(mask_bytes).convert("L"), "mask"
        if mask.size != original.size:
            raise ValueError(f"mask is {mask.size}, the object image is {original.size}")
    elif has_transparency(original_image):
        mask, source = original_image.convert("RGBA").getchannel("A"), "alpha"
    else:
        mask, source = None, "none"

    if mask is None:
        result_palette = _palette(result, None, k)
        return ColorMetrics(
            mask_source=source,
            reference_palette=_tuples(reference_palette),
            result_palette=_tuples(result_palette),
            **_distances(result_palette, reference_palette),
            background_psnr_db=None,
            edge_psnr_db=None,
            recomposed_png=None,
            result_resized=resized,
        )
    inside = binary(mask)
    outside = np.asarray(mask) == 0
    result_palette = _palette(result, inside, k)
    original_arr, result_arr = np.asarray(original), np.asarray(result)
    psnr = psnr_db(original_arr[outside], result_arr[outside]) if outside.any() else None
    recomposed = Image.composite(result, original, mask)
    mask_arr = np.asarray(mask)
    edge = (mask_arr > 0) & (mask_arr < 255)
    edge_psnr = psnr_db(np.asarray(recomposed)[edge], original_arr[edge]) if edge.any() else None
    return ColorMetrics(
        mask_source=source,
        reference_palette=_tuples(reference_palette),
        result_palette=_tuples(result_palette),
        **_distances(result_palette, reference_palette),
        background_psnr_db=psnr,
        edge_psnr_db=edge_psnr,
        recomposed_png=png_bytes(recomposed),
        result_resized=resized,
    )


def _tuples(palette: np.ndarray) -> tuple[tuple[float, float, float], ...]:
    return tuple((float(c[0]), float(c[1]), float(c[2])) for c in palette)


# ---------------------------------------------------------------------------
# Legibility (local part: the reader backed by Claude's vision is PR 3)


class LegibilityReader(Protocol):
    def read_text(self, image_bytes: bytes) -> str:
        """The text the image shows, as read."""
        ...


def normalize_text(text: str) -> str:
    """The comparison form of a text: Unicode NFC (a composed and a decomposed «Ñ» are
    the same), case-folded, every run of whitespace (line breaks included) collapsed to
    one space, trimmed. Accents, «ñ» and punctuation («¡», «!») stay significant: «ÑAPA»
    read as «NAPA» is a different word."""
    folded = unicodedata.normalize("NFC", text).casefold()
    return re.sub(r"\s+", " ", folded).strip()


def exact_match(expected: str, read: str) -> bool:
    return normalize_text(expected) == normalize_text(read)


def legibility_record(
    reader: LegibilityReader | None, image_bytes: bytes, expected: str | None
) -> dict[str, object]:
    """What the run records for a texture item: `pendiente` without a reader."""
    if reader is None or expected is None:
        return {"metricas_version": METRICS_VERSION, "estado": "pendiente"}
    read = reader.read_text(image_bytes)
    return {
        "metricas_version": METRICS_VERSION,
        "estado": "leido",
        "leido": read,
        "coincide": exact_match(expected, read),
    }


class FakeReader:
    """A deterministic reader for tests: the text for an image's SHA-256, else `default`.
    Records every image it was asked to read."""

    def __init__(self, default: str = "", by_digest: Mapping[str, str] | None = None) -> None:
        self.default = default
        self.by_digest = dict(by_digest or {})
        self.calls: list[str] = []

    def read_text(self, image_bytes: bytes) -> str:
        digest = hashlib.sha256(image_bytes).hexdigest()
        self.calls.append(digest)
        return self.by_digest.get(digest, self.default)
