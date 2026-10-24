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
- ``flat`` — the same logos with the same textures, as a flat finish made by Pillow
  (`image_metrics.flat_texture_fill`: the silhouette at 1080 px filled with the
  texture): deterministic, free, the baseline the generated textures have to beat.

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

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

from qualify_creative.enums import GenerationTask
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, RenderedPrompt

from qualify_api.evals.spend_control import (
    DEFAULT_EXPECTED_LAYERS,
    PriceQuote,
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
FLAT_PROVIDER = "pillow-flat-texture"
#: Bumped whenever the flat finish or its checks change (provenance of the flat block).
FLAT_VERSION = "flat-texture-v1"
#: The only repository folder a `fixture: true` case may read (relative to the repo
#: root): the eval's own generated fixtures. Never uploads, the Reflex app, its build
#: output, the app's assets or the render samples.
FIXTURE_ROOTS: tuple[str, ...] = ("packages/api/evals/plantillas_ai/fixtures",)

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
    #: Color cases only: the object's mask (white = object), same path rules as `image`.
    mask: ImageRef | None = None


@dataclass(frozen=True)
class CaseSet:
    color: tuple[Case, ...]
    color_references: tuple[ImageRef, ...]
    texture: tuple[Case, ...]
    texture_references: tuple[ImageRef, ...]


@dataclass(frozen=True)
class MatrixItem:
    block: str
    case_id: str
    reference_id: str | None
    images: tuple[ImageRef, ...]
    expected_text: str | None
    fixture: bool
    #: The object's mask of a color item (None: the metrics fall back, see image_metrics).
    mask: ImageRef | None = None

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


def _mask(raw: Mapping[str, Any], where: str, case_id: str, *, fixture: bool) -> ImageRef | None:
    """A color case's optional `mask`: a path string under the same rules as the image."""
    path = raw.get("mask")
    if path is None:
        return None
    if not isinstance(path, str):
        raise CasesError(f"{where} ({case_id}): 'mask' must be a path")
    return _image_ref({"id": f"{case_id}.mask", "path": path}, f"{where} mask", fixture=fixture)


def _cases(
    block: Mapping[str, Any],
    name: str,
    *,
    needs_text: bool,
    takes_mask: bool = False,
    shared_are_fixtures: bool = False,
) -> tuple[Case, ...]:
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
        if fixture and not refs and not shared_are_fixtures:
            raise CasesError(
                f"{where} ({image.id}): a fixture case needs its own references, or a block "
                "whose references are fixtures"
            )
        if "mask" in raw and not takes_mask:
            raise CasesError(f"{where} ({image.id}): only a color case takes a 'mask'")
        cases.append(
            Case(
                id=image.id,
                image=image,
                expected_text=text if isinstance(text, str) else None,
                references=refs,
                fixture=fixture,
                mask=_mask(raw, where, image.id, fixture=fixture),
            )
        )
    _unique(cases, f"block {name!r}")
    return tuple(cases)


def _fixture_references(block: Mapping[str, Any], name: str) -> bool:
    """The block-level `fixture_references`: true when every block reference is a repo
    fixture (under `FIXTURE_ROOTS`, checked like any fixture path). A reference entry
    itself still may not carry `fixture`."""
    flag = block.get("fixture_references", False)
    if not isinstance(flag, bool):
        raise CasesError(f"block {name!r}: 'fixture_references' must be true or false")
    return flag


def _references(block: Mapping[str, Any], name: str) -> tuple[ImageRef, ...]:
    raw = block.get("references")
    if not isinstance(raw, list) or not raw:
        raise CasesError(f"block {name!r}: 'references' must be a non-empty list")
    fixture = _fixture_references(block, name)
    refs = tuple(
        _image_ref(r, f"block {name!r} reference #{i}", fixture=fixture) for i, r in enumerate(raw)
    )
    _unique(refs, f"block {name!r} references")
    return refs


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
        raise CasesError("flat: 'source_block' must be 'texture' (the same logos and textures)")
    if "fill" in flat:
        raise CasesError("flat: 'fill' is gone — the flat finish uses the texture references")
    return CaseSet(
        color=_cases(
            color,
            "color",
            needs_text=False,
            takes_mask=True,
            shared_are_fixtures=_fixture_references(color, "color"),
        ),
        color_references=_references(color, "color"),
        texture=_cases(
            texture,
            "texture",
            needs_text=True,
            shared_are_fixtures=_fixture_references(texture, "texture"),
        ),
        texture_references=_references(texture, "texture"),
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
    """Every item of the chosen blocks: object × color reference, logo × texture, and the
    same logo × texture pairs as flat finishes. `skip_fixtures` drops the `fixture: true`
    cases first (their own references go with them; a block's fixture references stay,
    the real cases use them); `limit` then keeps the first N remaining cases of each
    block (fixtures come first in `cases.json`)."""
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
            shared = cases.color_references if block == "color" else cases.texture_references
            for ref in case.references or shared:
                items.append(
                    MatrixItem(
                        block,
                        case.id,
                        ref.id,
                        (case.image, ref),
                        case.expected_text,
                        case.fixture,
                        case.mask if block == "color" else None,
                    )
                )
    return items


def missing_files(items: Iterable[MatrixItem], images_dir: Path, repo_root: Path) -> list[Path]:
    """The input files that are not on disk, each once, in matrix order."""
    missing: dict[Path, None] = {}
    for item in items:
        for image in (*item.images, *((item.mask,) if item.mask else ())):
            path = image.resolve(images_dir, repo_root)
            if not path.is_file():
                missing[path] = None
    return list(missing)


#: What each input of an item is, for the missing-files report (by block and position).
INPUT_ROLES: Mapping[str, tuple[str, str]] = {
    "color": ("objetos", "referencias de color"),
    "texture": ("logos", "texturas"),
    "flat": ("logos", "texturas"),
}
MASK_ROLE = "máscaras"


def missing_by_role(
    items: Iterable[MatrixItem], images_dir: Path, repo_root: Path
) -> dict[str, list[Path]]:
    """The input files that are not on disk, each once, grouped by what they are
    (objects, color references, masks, logos, textures), in matrix order."""
    groups: dict[str, dict[Path, None]] = {}
    seen: set[Path] = set()
    for item in items:
        roles = INPUT_ROLES[item.block]
        pairs = [(image, roles[min(i, 1)]) for i, image in enumerate(item.images)]
        if item.mask:
            pairs.append((item.mask, MASK_ROLE))
        for image, role in pairs:
            path = image.resolve(images_dir, repo_root)
            if path not in seen and not path.is_file():
                seen.add(path)
                groups.setdefault(role, {})[path] = None
    return {role: list(paths) for role, paths in groups.items()}


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
        "prompt_version": PROMPT_VERSION if call.quote else FLAT_VERSION,
        "pricing_version": call.quote.pricing_version if call.quote else None,
        "estimated_usd": str(call.cost_usd),
    }
