"""Color transfer and logo texture with Seedream 5.0 pro (Meegle m-24849234): cases,
matrix, the plan of calls and the requests, importable so they are tested offline. Prices,
the spending ceiling, reference encoding and path safety come from
`qualify_api.evals.spend_control`. The runnable side is
`packages/api/evals/plantillas_ai/run_experiment.py`.

Three blocks:

- ``color`` — an object photo plus a color-reference image: recolor the object with the
  reference's palette, keep everything else.
- ``texture`` — a logo or a word plus a texture image: give the letters that material,
  keep the letters (``expected_text`` is what a later legibility check reads back).
- ``flat`` — the same logos filled with one flat color by Pillow: deterministic, free,
  the baseline the generated textures have to beat.

Money rules (enforced by `spend_control`):

1. **No price, no call.** `plan_calls` quotes every paid item from the versioned pricing
   table (`v6`, selected explicitly — production stays on its own version) BEFORE anything
   is sent. A missing row raises `MissingPriceError` and the run never starts.
2. **The ceiling is checked before every request.** `SpendLedger` reserves the quote under
   a lock before the bytes leave (`LedgerTransport` sits under the adapter, so the
   adapter's own retries are reservations too) and refuses the one that would cross the
   ceiling. The ceiling itself can never be set above `MAX_USD_CEILING`.
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image, ImageChops, ImageOps
from qualify_creative.enums import GenerationTask
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, RenderedPrompt

from qualify_api.evals.spend_control import (
    DEFAULT_EXPECTED_LAYERS,
    PriceQuote,
    has_transparency,
    png_bytes,
    quote,
    resolve_within,
    unsafe_relative_path,
)

#: The eval's own pricing version. Production's `composition.PRICING_VERSION` is untouched.
PRICING_VERSION = "v6"
#: Bumped whenever a block's prompt changes; recorded with every output (provenance).
PROMPT_VERSION = "plantillas-ai-v1"
BLOCKS: tuple[str, ...] = ("color", "texture", "flat")
PAID_BLOCKS = frozenset({"color", "texture"})
#: The deterministic block: no vendor, no price lookup, cost 0 by construction.
FLAT_PROVIDER = "pillow-flat-fill"
#: The only repository folders a `fixture: true` case may read (relative to the repo
#: root): Qualify's own email assets and the render samples. Never uploads, the Reflex
#: app or its build output.
FIXTURE_ROOTS: tuple[str, ...] = ("assets", "packages/render/public/sample")

PROMPTS: Mapping[str, str] = {
    "color": (
        "Image 1 is a product photo. Image 2 is a color reference. Recolor the object in "
        "Image 1 with the color palette of Image 2. Keep the object's shape, material, "
        "printed text, lighting, shadows and the background of Image 1 unchanged."
    ),
    "texture": (
        'Image 1 is a logo with the text "{expected_text}". Image 2 is a material texture. '
        "Apply the material of Image 2 to the letters and shapes of the logo in Image 1. "
        'Keep the exact text "{expected_text}", the letter shapes, the layout and the '
        "background of Image 1 unchanged."
    ),
}


class CasesError(ValueError):
    """`cases.json` does not describe a valid matrix."""


def fixture_root(path: str) -> tuple[str, str] | None:
    """(root, path inside it) when `path` (repo-relative) sits under one of
    `FIXTURE_ROOTS`; None otherwise."""
    parts = PurePosixPath(path.replace("\\", "/")).parts
    for root in FIXTURE_ROOTS:
        root_parts = PurePosixPath(root).parts
        if len(parts) > len(root_parts) and parts[: len(root_parts)] == root_parts:
            return root, PurePosixPath(*parts[len(root_parts) :]).as_posix()
    return None


# ---------------------------------------------------------------------------
# Cases and matrix


@dataclass(frozen=True)
class ImageRef:
    """One input image: `path` is relative to `imagenes/`, or to the repository root when
    `fixture` is set (a file that is in git, so a dry run can resolve it)."""

    id: str
    path: str
    fixture: bool = False

    def resolve(self, images_dir: Path, repo_root: Path) -> Path:
        """The file on disk, refusing a path that resolves outside its base:
        `imagenes/`, or for a fixture one of `FIXTURE_ROOTS` (`CasesError` otherwise)."""
        if not self.fixture:
            return resolve_within(images_dir, self.path, what=f"image {self.id!r}:")
        found = fixture_root(self.path)
        if found is None:
            raise CasesError(
                f"fixture image {self.id!r}: {self.path!r} is outside the fixture roots "
                f"{list(FIXTURE_ROOTS)}"
            )
        root, inner = found
        return resolve_within(repo_root / root, inner, what=f"fixture image {self.id!r}:")


@dataclass(frozen=True)
class Case:
    id: str
    image: ImageRef
    expected_text: str | None = None
    #: Fixture cases carry their own references; the rest use the block's.
    references: tuple[ImageRef, ...] = ()
    fixture: bool = False


@dataclass(frozen=True)
class CaseSet:
    color: tuple[Case, ...]
    color_references: tuple[ImageRef, ...]
    texture: tuple[Case, ...]
    texture_references: tuple[ImageRef, ...]
    flat_fill: tuple[int, int, int]


@dataclass(frozen=True)
class MatrixItem:
    block: str
    case_id: str
    reference_id: str | None
    images: tuple[ImageRef, ...]
    expected_text: str | None
    fixture: bool

    @property
    def id(self) -> str:
        return f"{self.block}:{self.case_id}" + (
            f"+{self.reference_id}" if self.reference_id else ""
        )

    @property
    def paid(self) -> bool:
        return self.block in PAID_BLOCKS


#: Ids become output file names, so no separators or `..`.
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]+")


def _image_ref(
    raw: object, where: str, *, fixture: bool = False, is_case: bool = False
) -> ImageRef:
    """One image entry. Only a case may carry `fixture`; its references inherit it."""
    if not isinstance(raw, Mapping):
        raise CasesError(f"{where}: expected an object with 'id' and 'path'")
    ident, path = raw.get("id"), raw.get("path")
    if not isinstance(ident, str) or not ident.strip():
        raise CasesError(f"{where}: missing 'id'")
    if not _SAFE_ID.fullmatch(ident) or ident.strip(".") == "":
        raise CasesError(f"{where} ({ident!r}): 'id' may only use letters, digits, . _ -")
    if not isinstance(path, str) or not path.strip():
        raise CasesError(f"{where} ({ident}): missing 'path'")
    if unsafe_relative_path(path):
        raise CasesError(f"{where} ({ident}): 'path' must be relative and stay inside")
    if "fixture" in raw and not is_case:
        raise CasesError(f"{where} ({ident}): only a case may set 'fixture'")
    if fixture and fixture_root(path) is None:
        raise CasesError(
            f"{where} ({ident}): a fixture path must be under one of {list(FIXTURE_ROOTS)}"
        )
    return ImageRef(id=ident, path=path, fixture=fixture)


def _unique(items: Sequence[Any], where: str) -> None:
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            raise CasesError(f"{where}: duplicate id {item.id!r}")
        seen.add(item.id)


def _cases(block: Mapping[str, Any], name: str, *, needs_text: bool) -> tuple[Case, ...]:
    raw_cases = block.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise CasesError(f"block {name!r}: 'cases' must be a non-empty list")
    cases: list[Case] = []
    for i, raw in enumerate(raw_cases):
        where = f"block {name!r} case #{i}"
        if not isinstance(raw, Mapping):
            raise CasesError(f"{where}: expected an object")
        fixture = raw.get("fixture", False)
        if not isinstance(fixture, bool):
            raise CasesError(f"{where}: 'fixture' must be true or false")
        image = _image_ref(raw, where, fixture=fixture, is_case=True)
        text = raw.get("expected_text")
        if needs_text and (not isinstance(text, str) or not text.strip()):
            raise CasesError(f"{where} ({image.id}): missing 'expected_text'")
        refs = tuple(
            _image_ref(r, f"{where} reference", fixture=fixture)
            for r in raw.get("references") or ()
        )
        if fixture and not refs:
            raise CasesError(f"{where} ({image.id}): a fixture case needs its own references")
        cases.append(
            Case(
                id=image.id,
                image=image,
                expected_text=text if isinstance(text, str) else None,
                references=refs,
                fixture=fixture,
            )
        )
    _unique(cases, f"block {name!r}")
    return tuple(cases)


def _references(block: Mapping[str, Any], name: str) -> tuple[ImageRef, ...]:
    raw = block.get("references")
    if not isinstance(raw, list) or not raw:
        raise CasesError(f"block {name!r}: 'references' must be a non-empty list")
    refs = tuple(_image_ref(r, f"block {name!r} reference #{i}") for i, r in enumerate(raw))
    _unique(refs, f"block {name!r} references")
    return refs


def _hex(value: object) -> tuple[int, int, int]:
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        raise CasesError(f"flat: 'fill' must be a #RRGGBB color, got {value!r}")
    try:
        return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))
    except ValueError:
        raise CasesError(f"flat: 'fill' must be a #RRGGBB color, got {value!r}") from None


def parse_cases(raw: Mapping[str, Any]) -> CaseSet:
    """Validate the parsed `cases.json`. Raises `CasesError` naming the first problem."""
    blocks = raw.get("blocks")
    if not isinstance(blocks, Mapping) or set(blocks) != set(BLOCKS):
        raise CasesError(f"'blocks' must hold exactly {list(BLOCKS)}")
    for name in BLOCKS:
        if not isinstance(blocks[name], Mapping):
            raise CasesError(f"block {name!r} must be an object")
    color, texture, flat = blocks["color"], blocks["texture"], blocks["flat"]
    if flat.get("source_block") != "texture":
        raise CasesError("flat: 'source_block' must be 'texture' (the same logos)")
    return CaseSet(
        color=_cases(color, "color", needs_text=False),
        color_references=_references(color, "color"),
        texture=_cases(texture, "texture", needs_text=True),
        texture_references=_references(texture, "texture"),
        flat_fill=_hex(flat.get("fill")),
    )


def load_cases(path: Path) -> CaseSet:
    return parse_cases(json.loads(path.read_text(encoding="utf-8")))


def build_matrix(
    cases: CaseSet,
    *,
    blocks: Iterable[str] = BLOCKS,
    limit: int | None = None,
    skip_fixtures: bool = False,
) -> list[MatrixItem]:
    """Every item of the chosen blocks: object × color reference, logo × texture, and one
    flat fill per logo. `skip_fixtures` drops the `fixture: true` cases and references
    first; `limit` then keeps the first N remaining cases of each block (fixtures come
    first in `cases.json`)."""
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")
    chosen = list(dict.fromkeys(blocks))
    unknown = [b for b in chosen if b not in BLOCKS]
    if unknown:
        raise ValueError(f"unknown block(s) {unknown}; choose from {list(BLOCKS)}")
    items: list[MatrixItem] = []
    for block in BLOCKS:
        if block not in chosen:
            continue
        source = cases.color if block == "color" else cases.texture
        if skip_fixtures:
            source = tuple(c for c in source if not c.fixture)
        for case in source[:limit]:
            if block == "flat":
                items.append(
                    MatrixItem(
                        block, case.id, None, (case.image,), case.expected_text, case.fixture
                    )
                )
                continue
            shared = cases.color_references if block == "color" else cases.texture_references
            refs = case.references or shared
            if skip_fixtures:
                refs = tuple(r for r in refs if not r.fixture)
            for ref in refs:
                items.append(
                    MatrixItem(
                        block, case.id, ref.id, (case.image, ref), case.expected_text, case.fixture
                    )
                )
    return items


def missing_files(items: Iterable[MatrixItem], images_dir: Path, repo_root: Path) -> list[Path]:
    """The input files that are not on disk, each once, in matrix order."""
    missing: dict[Path, None] = {}
    for item in items:
        for image in item.images:
            path = image.resolve(images_dir, repo_root)
            if not path.is_file():
                missing[path] = None
    return list(missing)


# ---------------------------------------------------------------------------
# Price quotes


@dataclass(frozen=True)
class PlannedCall:
    item: MatrixItem
    model_id: str
    quote: PriceQuote | None  # None: the free deterministic block

    @property
    def cost_usd(self) -> Decimal:
        return self.quote.total_usd if self.quote else Decimal(0)


def plan_calls(
    items: Sequence[MatrixItem],
    pricing: JsonPricingTable,
    *,
    model_ids: Sequence[str],
    size: str,
    layer_decomposition: bool = False,
    expected_layers: int = DEFAULT_EXPECTED_LAYERS,
) -> list[PlannedCall]:
    """Quote the whole run up front. Paid items run once per model; flat items once.
    Raises `MissingPriceError` on the first unpriced component — before any call."""
    if not model_ids:
        raise ValueError("at least one model id is required")
    planned: list[PlannedCall] = []
    for item in items:
        if not item.paid:
            planned.append(PlannedCall(item, FLAT_PROVIDER, None))
            continue
        for model_id in model_ids:
            q = quote(
                pricing,
                model_id=model_id,
                size=size,
                references=len(item.images),
                layer_decomposition=layer_decomposition,
                expected_layers=expected_layers,
            )
            planned.append(PlannedCall(item, model_id, q))
    return planned


def total_usd(planned: Iterable[PlannedCall]) -> Decimal:
    return sum((p.cost_usd for p in planned), Decimal(0))


# ---------------------------------------------------------------------------
# Flat fill (the free block)


def flat_fill(data: bytes, fill: tuple[int, int, int], *, threshold: int = 48) -> bytes:
    """The logo with every mark pixel painted `fill`, as a PNG with alpha.

    A transparent logo keeps its own alpha as the mask. An opaque one is masked by its
    largest per-channel distance from the top-left corner color (the background),
    above `threshold`.
    """
    image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if has_transparency(image):
        mask = image.convert("RGBA").getchannel("A")
    else:
        rgb = image.convert("RGB")
        bg = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
        r, g, b = ImageChops.difference(rgb, bg).split()
        # the largest channel difference: a luminance mix would lose yellow on white
        diff = ImageChops.lighter(ImageChops.lighter(r, g), b)
        mask = diff.point(lambda v: 255 if v > threshold else 0)
    out = Image.new("RGBA", image.size, (*fill, 0))
    out.putalpha(mask)
    return png_bytes(out)


# ---------------------------------------------------------------------------
# Paid request


def prompt_for(item: MatrixItem) -> str:
    template = PROMPTS[item.block]
    return template.format(expected_text=item.expected_text or "")


def request_params(
    item: MatrixItem, *, model_id: str, size: str, images: Sequence[str]
) -> dict[str, object]:
    """`SeedreamImageAdapter` params: the model is always explicit."""
    return {"prompt": prompt_for(item), "model": model_id, "size": size, "images": list(images)}


def build_request(
    item: MatrixItem, *, model_id: str, size: str, images: Sequence[str]
) -> GenerationRequest:
    return GenerationRequest(
        task=GenerationTask.PRODUCT_IMAGE,
        rendered_prompt=RenderedPrompt("", "", ""),
        params=request_params(item, model_id=model_id, size=size, images=images),
    )


def provenance(call: PlannedCall) -> dict[str, object]:
    return {
        "provider": "seedream" if call.quote else FLAT_PROVIDER,
        "model_id": call.model_id,
        "prompt_version": PROMPT_VERSION,
        "pricing_version": call.quote.pricing_version if call.quote else None,
        "estimated_usd": str(call.cost_usd),
    }
