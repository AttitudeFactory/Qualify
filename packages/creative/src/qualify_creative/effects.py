"""The effects library (EF-02, ADR 50 §1.4): what each effect is, in which step it acts
and which parameters it takes — versioned JSON in the repo (`effects_data/vN.json`),
validated once at load like `pricing_data/`. No table and no migration: we write the
effects, and git gives them review and exact provenance.

An entry is never edited in place. A change of parameters, prompt or asset is a new
entry at `version + 1` (a brief keeps the `version` it was made with); only `measured`
moves, once, from null to the paid bench's result (EF-12).

`preview_asset` is what the live preview in the browser lays over the `<video>`
(editor contract §4.1): the pre-recorded loop of a layer (D2 = A, `mix-blend-mode:
screen`), the example video of a «Con IA» effect. Every entry says whether the screen may
offer it (`offered`). The preview may be null ONLY where the browser simulates the effect
with no file (`texto` = an HTML layer, the transitions =
CSS: `EffectEntry.simulated_in_browser`) or where the effect is not offered — in v1
`camara_rapida` (D-T3: fast motion is `SourceSegment.speed`, not an effect on the track; the
entry stays because EF-04, `video/speed.py`, records its id and version as provenance), the
layers `humo_capa`/`brasas_capa`/`vapor_capa` (their loops are not recorded yet; a later
ticket records them and offers them) and the Seedance templates (`measured` null, D5).
Every non-null preview is a global, read-only relative path under
`effects/<id>/v<version>/` — never a URL, never `..`, never a tenant's `t/` prefix — and
its file must exist in the packaged `effects_assets/` folder (`preview_file`: the leading
`effects/` is that folder) or the library does not load (`MissingPreviewAsset`).

The pure checks of an `EffectUse` against the library live here too
(`effect_use_problems`, `part_effect_problems`): they return every problem as a
`RecipeProblem` with a stable `RecipeRefusal` code, never raise and never read a file
after the first load — cheap enough for the screen to call on each change of the owner.
"""

from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from qualify_creative.layer_spec.schema import catalog
from qualify_creative.schemas import (
    EFFECT_ID_PATTERN,
    TEXT_LAYERS_MAX,
    EffectUse,
    RecipeRefusal,
    VideoTextLayer,
)

_DATA_DIR = Path(__file__).parent / "effects_data"
#: The files `preview_asset` names (`preview_file`): `effects/<id>/v<n>/x` → here `<id>/v<n>/x`.
_ASSETS_DIR = Path(__file__).parent / "effects_assets"

#: The library a new request is checked against. ED-15: v2 — v1's entries, with the
#: layers repeatable (`max_per_part` 3); v1 still loads and reads exactly as before.
EFFECTS_LIBRARY_VERSION = "v2"

EffectStage = Literal["prepare", "local", "seedance_prompt", "compose", "transition"]
EffectScope = Literal["part", "between_parts"]
EffectNeed = Literal["video", "own_video"]
EffectBlend = Literal["screen", "add", "normal"]

#: The placeholders a `seedance_prompt` template fills: where in the frame, and what.
PROMPT_SLOTS = frozenset({"zone", "subject"})
_SLOT = re.compile(r"\{([a-z_]+)\}")


def _asset_path_problem(path: str, effect_id: str, version: int) -> str | None:
    """A global read-only path of the library: `effects/<id>/v<version>/…`, relative,
    POSIX, no scheme, no `..`, no empty segment, no backslash."""
    prefix = f"effects/{effect_id}/v{version}/"
    if "\\" in path or ":" in path or path.startswith("/"):
        return f"{path!r} is a relative POSIX path with no scheme"
    if not path.startswith(prefix):
        return f"{path!r} lives under {prefix}"
    segments = path.split("/")
    inner = segments[:-1] if path.endswith("/") else segments
    if any(segment in ("", ".", "..") for segment in inner):
        return f"{path!r} has no empty, '.' or '..' segment"
    return None


class ParamSpec(BaseModel):
    """One parameter an effect takes: a number in `[min, max]`, one of `values`, or a
    yes/no — and the value used when the owner says nothing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["float", "int", "enum", "bool"]
    min: float | None = None
    max: float | None = None
    values: tuple[str, ...] = ()
    default: bool | int | float | str

    @model_validator(mode="after")
    def _coherent(self) -> ParamSpec:
        if self.type in ("float", "int"):
            if self.min is None or self.max is None or self.min > self.max or self.values:
                raise ValueError("a number parameter has its min ≤ max and no values")
            if not self.accepts(self.default):
                raise ValueError("a parameter's default is within its range")
        elif self.type == "enum":
            if not self.values or self.min is not None or self.max is not None:
                raise ValueError("an enum parameter lists its values and has no range")
            if self.default not in self.values:
                raise ValueError("an enum parameter's default is one of its values")
        elif not isinstance(self.default, bool) or self.values or self.min is not None:
            raise ValueError("a yes/no parameter defaults to true or false")
        return self

    def accepts(self, value: object) -> bool:
        """Whether `value` is a valid value of this parameter (type and range)."""
        if self.type == "bool":
            return isinstance(value, bool)
        if self.type == "enum":
            return isinstance(value, str) and value in self.values
        if isinstance(value, bool) or not isinstance(value, int | float):
            return False
        if self.type == "int" and not float(value).is_integer():
            return False
        assert self.min is not None and self.max is not None
        return self.min <= float(value) <= self.max


class Measured(BaseModel):
    """The paid bench's result for a «Con IA» effect (EF-12): successes of `n`, the
    Wilson interval and the day it ran. Offered only when present (D5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    successes: int = Field(ge=0)
    n: int = Field(ge=1)
    wilson_low: float = Field(ge=0, le=1)
    wilson_high: float = Field(ge=0, le=1)
    measured_on: date

    @model_validator(mode="after")
    def _coherent(self) -> Measured:
        if self.successes > self.n or self.wilson_low > self.wilson_high:
            raise ValueError("a measurement has successes ≤ n and low ≤ high")
        return self


class EffectEntry(BaseModel):
    """One effect of the library (ADR 50 §1.4). `label` and `cost_note` are what the
    screen shows, in Spanish («Gratis», «Con IA»). `offered` says, explicitly, whether the
    screen may offer it (D5; a layer waits for its recorded loop, a «Con IA» effect for
    the paid bench). `extra="forbid"`: an unknown key — a `seed`, say, which the 2.x
    adapter never sends — is a broken file, not a silent one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=EFFECT_ID_PATTERN)
    version: int = Field(ge=1)
    stage: EffectStage
    scope: EffectScope
    label: str = Field(min_length=1, max_length=40)
    cost_note: str = Field(min_length=1, max_length=40)
    offered: bool
    params: dict[str, ParamSpec] = Field(default_factory=dict)
    asset: str | None = None
    preview_asset: str | None = None
    blend: EffectBlend | None = None
    needs: tuple[EffectNeed, ...] = ()
    max_per_part: int = Field(default=1, ge=1)
    measured: Measured | None = None
    prompt_version: str | None = None
    prompt_template: str | None = None

    @property
    def simulated_in_browser(self) -> bool:
        """The live preview shows it with no file (editor contract §4.1): fast motion with
        `playbackRate`, the transitions with CSS, a compose effect without a layer (the
        text) as an HTML layer."""
        return self.stage in ("local", "transition") or (
            self.stage == "compose" and self.asset is None
        )

    @model_validator(mode="after")
    def _coherent(self) -> EffectEntry:
        if (self.stage == "transition") != (self.scope == "between_parts"):
            raise ValueError("a transition, and only a transition, is between parts")
        if self.stage == "seedance_prompt":
            if not self.prompt_version or not self.prompt_template:
                raise ValueError("a Seedance effect has its prompt and its prompt version")
            if set(_SLOT.findall(self.prompt_template)) != PROMPT_SLOTS:
                raise ValueError("a Seedance effect's prompt fills {zone} and {subject}")
            if self.offered and self.measured is None:
                raise ValueError("D5: a Seedance effect is offered only once measured")
        elif self.prompt_version is not None or self.prompt_template is not None:
            raise ValueError("only a Seedance effect has a prompt")
        elif self.measured is not None:
            raise ValueError("only a Seedance effect is measured by the bench")
        for path in (self.asset, self.preview_asset):
            problem = None if path is None else _asset_path_problem(path, self.id, self.version)
            if problem:
                raise ValueError(problem)
        if self.asset is not None and (not self.asset.endswith("/") or self.blend is None):
            raise ValueError("a layer's asset is its folder, laid with a blend mode")
        if self.preview_asset is None and self.offered and not self.simulated_in_browser:
            # an offered layer or «Con IA» effect: the browser lays its loop or example
            raise ValueError(f"{self.id} needs the preview the screen lays over the video")
        if self.preview_asset is not None and self.preview_asset.endswith("/"):
            raise ValueError("a preview is a file, not a folder")
        return self


class EffectsLibrary(BaseModel):
    """A whole library file: its version and its entries, `(id, version)` unique."""

    model_config = ConfigDict(frozen=True)

    version: int = Field(ge=1)
    notes: str = ""
    entries: tuple[EffectEntry, ...]

    @model_validator(mode="after")
    def _unique(self) -> EffectsLibrary:
        keys = [(e.id, e.version) for e in self.entries]
        if len(set(keys)) != len(keys):
            raise ValueError("an effect appears once per version")
        return self

    def get(self, effect_id: str, version: int) -> EffectEntry | None:
        return next((e for e in self.entries if e.id == effect_id and e.version == version), None)

    def has(self, effect_id: str) -> bool:
        return any(e.id == effect_id for e in self.entries)

    def offered(self) -> tuple[EffectEntry, ...]:
        """What the screen may offer (D5), in the file's order."""
        return tuple(e for e in self.entries if e.offered)


def preview_file(preview_asset: str, assets_root: Path | None = None) -> Path:
    """Where a `preview_asset` lives on disk: `effects/<id>/v<n>/<file>` is
    `<assets_root>/<id>/v<n>/<file>` — the leading `effects/` names the root itself,
    `qualify_creative/effects_assets/` (packaged with the module), unless a test passes
    another. The shape was already checked (`_asset_path_problem`)."""
    root = _ASSETS_DIR if assets_root is None else assets_root
    return root.joinpath(*preview_asset.split("/")[1:])


class MissingPreviewAsset(ValueError):
    """A library names a `preview_asset` whose file is not in the assets folder: the
    screen would lay nothing over the video. The library does not load."""


def parse_library(raw: object, *, assets_root: Path | None = None) -> EffectsLibrary:
    """Validate a library document (a parsed JSON object) and that every non-null
    `preview_asset` is a file under `assets_root` (`preview_file`; default the packaged
    `effects_assets/`). A missing one is `MissingPreviewAsset`, naming every one."""
    library = EffectsLibrary.model_validate(raw)
    missing = [
        f"{entry.id} v{entry.version}: {entry.preview_asset}"
        for entry in library.entries
        if entry.preview_asset is not None
        and not preview_file(entry.preview_asset, assets_root).is_file()
    ]
    if missing:
        root = _ASSETS_DIR if assets_root is None else assets_root
        raise MissingPreviewAsset(f"preview files missing under {root}: {'; '.join(missing)}")
    return library


def load_effects(version: str = EFFECTS_LIBRARY_VERSION) -> EffectsLibrary:
    """Read and validate one library file — once per process (module-level cache), so a
    check on each change of the owner reads nothing from disk. An unknown version is a
    `KeyError` naming it; a file that declares another version is a `ValueError`."""
    return _load_effects(version)


@lru_cache(maxsize=4)
def _load_effects(version: str) -> EffectsLibrary:
    path = _DATA_DIR / f"{version}.json"
    if not path.is_file():
        raise KeyError(f"unknown effects library {version!r}: no data file at {path}")
    library = parse_library(json.loads(path.read_text(encoding="utf-8")))
    if f"v{library.version}" != version:
        raise ValueError(f"effects file {path.name} declares version {library.version}")
    return library


class RecipeProblem(BaseModel):
    """One problem of a recipe: its stable `code`, the 1-based `part` it is in (None =
    the Clip, or the whole video by parts), the `field` (`effects[1].params.speed`,
    `transition_in`, `segments[0].key`, `mode`) and the effect it is about, if any."""

    model_config = ConfigDict(frozen=True)

    code: RecipeRefusal
    part: int | None = None
    field: str = ""
    effect_id: str | None = None


def effect_use_problems(
    use: EffectUse, library: EffectsLibrary, *, part: int | None, field: str
) -> tuple[RecipeProblem, ...]:
    """Whether `use` is an effect of `library` the owner may choose: it exists at its
    version, is offered (D5) and its parameters are known and in range. Pure."""

    def problem(code: RecipeRefusal, where: str = field) -> RecipeProblem:
        return RecipeProblem(code=code, part=part, field=where, effect_id=use.effect_id)

    entry = library.get(use.effect_id, use.version)
    if entry is None:
        code: RecipeRefusal = "unknown_version" if library.has(use.effect_id) else "unknown_effect"
        return (problem(code),)
    found: list[RecipeProblem] = []
    if not entry.offered:
        found.append(problem("not_offered"))
    for name, value in use.params:
        spec = entry.params.get(name)
        if spec is None:
            found.append(problem("unknown_param", f"{field}.params.{name}"))
        elif not spec.accepts(value):
            found.append(problem("param_out_of_range", f"{field}.params.{name}"))
    return tuple(found)


#: Seconds of slack when comparing times (float sums of part lengths).
_EPSILON = 1e-6


def _inside(start: float | None, end: float | None, window: tuple[float, float] | None) -> bool:
    """Whether explicit times fall in `window` (`[0, length]` of a part or Clip, in seconds
    of its own output). None times are its edges; no window = nothing to check."""
    if window is None:
        return True
    low, high = window
    return (start is None or low - _EPSILON <= start <= high + _EPSILON) and (
        end is None or low - _EPSILON <= end <= high + _EPSILON
    )


def _span(
    start: float | None, end: float | None, window: tuple[float, float] | None
) -> tuple[float, float]:
    """The seconds a block covers: None times are its window's edges (no window: from 0,
    and without end)."""
    low, high = window if window is not None else (0.0, float("inf"))
    return (low if start is None else start, high if end is None else end)


def _overlapping(spans: list[tuple[int, tuple[float, float]]]) -> list[int]:
    """The positions whose span starts before an earlier-starting one ends (meeting at a
    second is not overlapping), in the order given."""
    found: list[int] = []
    ordered = sorted(spans, key=lambda item: (item[1][0], item[0]))
    reach = float("-inf")
    for at, (start, end) in ordered:
        if start < reach - _EPSILON:
            found.append(at)
        reach = max(reach, end)
    return sorted(found)


def part_effect_problems(
    effects: tuple[EffectUse, ...],
    library: EffectsLibrary,
    *,
    part: int | None,
    mode: str,
    has_own_video: bool,
    window: tuple[float, float] | None = None,
    in_clip: bool = False,
) -> tuple[RecipeProblem, ...]:
    """Every problem of one part's (or Clip's) effects against the library — each use on
    its own (`effect_use_problems`), then together: at most one `seedance_prompt` (one
    object in one zone per part), at most `max_per_part` of each, no transition among
    them (that is `transition_in`'s), an effect that needs the owner's own video only
    with one, a `local` part with no Seedance effect, and every span inside `window` —
    `[0, length]` of the part (or Clip), in seconds of its own output (None: not
    checked).
    ED-15: an effect the library lets repeat (`max_per_part` > 1) may be used again only
    where no other use of it is — two uses covering the same seconds are
    `effect_uses_overlap` (a use with no span covers the whole part, so a repeated effect
    names its start and end). Over `max_per_part` is `too_many_of_effect` alone.
    `in_clip`: a normal Clip, where a transition is `transition_on_clip`. Pure."""
    found: list[RecipeProblem] = []
    ai = 0
    counts: dict[tuple[str, int], int] = {}
    spans: dict[tuple[str, int], list[tuple[int, tuple[float, float]]]] = {}
    limits: dict[tuple[str, int], int] = {}
    for at, use in enumerate(effects):
        field = f"effects[{at}]"
        found.extend(effect_use_problems(use, library, part=part, field=field))
        entry = library.get(use.effect_id, use.version)
        if not _inside(use.start_s, use.end_s, window):
            found.append(
                RecipeProblem(
                    code="span_outside_part", part=part, field=field, effect_id=use.effect_id
                )
            )
        if entry is None:
            continue

        def problem(code: RecipeRefusal, where: str = field, of: str = use.effect_id) -> None:
            found.append(RecipeProblem(code=code, part=part, field=where, effect_id=of))

        if entry.scope == "between_parts":
            # a transition blends two parts: in a normal Clip there is no second one
            problem("transition_on_clip" if in_clip else "transition_in_effects")
        if entry.stage == "seedance_prompt":
            ai += 1
            if ai == 2:
                problem("too_many_ai_effects")
            if mode == "local":
                problem("local_with_ai_effect")
        key = (entry.id, entry.version)
        counts[key] = counts.get(key, 0) + 1
        if counts[key] == entry.max_per_part + 1:
            problem("too_many_of_effect")
        spans.setdefault(key, []).append((at, _span(use.start_s, use.end_s, window)))
        limits[key] = entry.max_per_part
        if "own_video" in entry.needs and not has_own_video:
            problem("effect_needs_own_video")
    for key, uses in spans.items():
        if len(uses) > limits[key]:
            continue  # already `too_many_of_effect`
        for at in _overlapping(uses):
            found.append(
                RecipeProblem(
                    code="effect_uses_overlap", part=part, field=f"effects[{at}]", effect_id=key[0]
                )
            )
    return tuple(found)


def text_layer_problems(
    layer: VideoTextLayer | None,
    *,
    part: int | None,
    window: tuple[float, float] | None = None,
    field: str = "text_layer",
) -> tuple[RecipeProblem, ...]:
    """A video text (pure; the catalog is cached): its times inside `window` — its part's
    or Clip's `[0, length]` in seconds of its own output, None = not checked —
    (`span_outside_part`), and, D1, a design it names is one of the current catalog's
    (`layer_spec`, `layout_version`) that exists in 9:16 with a title slot — the text is
    that slot (`unknown_layout`). `field` names it in the problems (`text_layers[1]`)."""
    if layer is None:
        return ()
    found: list[RecipeProblem] = []
    if not _inside(layer.start_s, layer.end_s, window):
        found.append(RecipeProblem(code="span_outside_part", part=part, field=field))
    if layer.layout_id is None:
        return tuple(found)
    data = catalog()
    layout = data["layouts"].get(layer.layout_id.value, {})
    title = (layout.get("slots", {}).get("title") or {}).get("9:16")
    if (
        layer.layout_version != data["layout_version"]
        or "9:16" not in layout.get("formats", ())
        or not title
    ):
        found.append(RecipeProblem(code="unknown_layout", part=part, field=f"{field}.layout_id"))
    return tuple(found)


def text_layers_problems(
    layers: tuple[VideoTextLayer, ...],
    *,
    part: int | None,
    window: tuple[float, float] | None = None,
    field: str = "text_layers",
) -> tuple[RecipeProblem, ...]:
    """The texts over one part, Clip or whole video (ED-15, pure): each one on its own
    (`text_layer_problems`, field `text_layers[i]`), at most `TEXT_LAYERS_MAX`
    (`too_many_texts` — the types refuse more already; this keeps a recipe built around
    them honest), and no two in the same `place` showing at the same time
    (`texts_overlap`, on the later one; `end_s` None = until the window's end, meeting at
    a second is fine). Texts in different places may show together."""
    found: list[RecipeProblem] = []
    if len(layers) > TEXT_LAYERS_MAX:
        found.append(
            RecipeProblem(code="too_many_texts", part=part, field=f"{field}[{TEXT_LAYERS_MAX}]")
        )
    by_place: dict[str, list[tuple[int, tuple[float, float]]]] = {}
    for at, layer in enumerate(layers):
        found.extend(text_layer_problems(layer, part=part, window=window, field=f"{field}[{at}]"))
        by_place.setdefault(layer.place, []).append((at, _span(layer.start_s, layer.end_s, window)))
    for spans in by_place.values():
        for at in _overlapping(spans):
            found.append(RecipeProblem(code="texts_overlap", part=part, field=f"{field}[{at}]"))
    return tuple(found)


def transition_problems(
    transition: EffectUse | None,
    library: EffectsLibrary,
    *,
    part: int | None,
    first: bool,
    in_clip: bool,
) -> tuple[RecipeProblem, ...]:
    """A part's `transition_in` (pure): only between parts — never in a normal Clip, nor
    on the first part —, and only an effect of stage `transition`."""
    if transition is None:
        return ()

    def problem(code: RecipeRefusal) -> RecipeProblem:
        return RecipeProblem(
            code=code, part=part, field="transition_in", effect_id=transition.effect_id
        )

    if in_clip:
        return (problem("transition_on_clip"),)
    found = list(effect_use_problems(transition, library, part=part, field="transition_in"))
    entry = library.get(transition.effect_id, transition.version)
    if entry is not None and entry.stage != "transition":
        found.append(problem("transition_not_a_transition"))
    if first:
        found.append(problem("transition_on_first_part"))
    return tuple(found)


__all__ = [
    "EFFECTS_LIBRARY_VERSION",
    "EffectEntry",
    "EffectsLibrary",
    "Measured",
    "MissingPreviewAsset",
    "ParamSpec",
    "RecipeProblem",
    "effect_use_problems",
    "load_effects",
    "parse_library",
    "preview_file",
    "part_effect_problems",
    "text_layer_problems",
    "text_layers_problems",
    "transition_problems",
]
