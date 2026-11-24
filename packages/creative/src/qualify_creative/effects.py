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
layers `humo_capa`/`brasas_capa`/`vapor_capa` in v1 and v2 (recorded and offered from v3,
EF-08 / m-25029102) and the Seedance templates (`measured` null, D5).
Every non-null preview is a global, read-only relative path under
`effects/<id>/v<version>/` — never a URL, never `..`, never a tenant's `t/` prefix — and
its file must exist in the packaged `effects_assets/` folder (`preview_file`: the leading
`effects/` is that folder) or the library does not load (`MissingPreviewAsset`).

The pure checks of an `EffectUse` against the library live here too
(`effect_use_problems`, `part_effect_problems`): they return every problem as a
`RecipeProblem` with a stable `RecipeRefusal` code, never raise and never read a file
after the first load — cheap enough for the screen to call on each change of the owner.

EF-08 (m-25029102): a layer's recorded loop (`<asset>preview.webm`, a VP9 WebM on pure
black) is BOTH what the browser lays and what the compose lays (`video/layer_overlay.py`):
the same pixels in the preview and in the final video. The compose reads it only through
`layer_loop_file`, a read-only door into the packaged `effects_assets/` (global, inside the
image, never under a tenant's `t/`, never in R2: nothing can purge it). Nothing writes there
at runtime; `packages/creative/scripts/make_effect_loops.py` records the loops.

An explicit exception to «never edited in place»: v3 offers `humo_capa`, `brasas_capa` and
`vapor_capa` at entry version 1 — it only flips `offered`, fills their empty
`preview_asset` and adds `categories`; their params and their asset folder `v1/` did not
change. Nobody could use version 1 while it was not offered, and the editor sends version
1. A future change of a loop (other bytes in `v1/`) does require `v2/` and an entry at
version 2.

ADR 50 D9 (Deivid 2026-11-20): v4 stops offering `fundido` and `barrido` at entry version
1. That is not an edit of the entry in place: v3 still reads exactly as it was, and
`offered` is what a library version says about an entry (whether the screen may offer it
now), not part of the effect — its params, prompt and asset did not change, so neither did
its version. The join did not draw them (a recipe that chose them was refused at creation
as `recipe_unavailable`), so the screen must not offer them; until EF-16 (m-25026594) the
only transition offered is `corte`. EF-16 made the join draw them (the two parts overlap for
the transition's `duration_s`, 0.3–0.8 s), so v5 offers them again as NEW entries at version
2 — their parameters' ranges changed — and keeps their unoffered version 1.
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
from qualify_creative.prompt_text import visual_text
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
#: layers repeatable (`max_per_part` 3). EF-08: v3 — v2's entries, with the smoke, ember
#: and steam layers recorded and offered. ADR 50 D9: v4 — v3's entries, with `fundido` and
#: `barrido` no longer offered until the join draws them (EF-16): `corte` is the only
#: transition offered. EF-16 (m-25026594): v5 — v4's entries plus `fundido` and `barrido`
#: at version 2 (0.3–0.8 s), offered again now that the join draws them
#: (`video.join.JoinTransition`). v1–v4 still load and read exactly as before.
EFFECTS_LIBRARY_VERSION = "v5"
#: The file of a layer's recorded loop inside its asset folder (`effects/<id>/v1/`).
LAYER_LOOP_FILE = "preview.webm"

EffectStage = Literal["prepare", "local", "seedance_prompt", "compose", "transition"]
EffectScope = Literal["part", "between_parts"]
EffectNeed = Literal["video", "own_video"]
EffectBlend = Literal["screen", "add", "normal"]
#: What an effect is about, for the screen to FILTER by (Deivid, 2026-11-16): a closed set
#: of stable Spanish ids without accents. A category never hides an effect: every business
#: may use every effect; `offered` alone says what the screen offers. Required from the
#: library v3 on (at least one, none repeated); v1 and v2 have none.
EffectCategory = Literal["comida", "texto", "transicion", "movimiento", "general"]
EFFECT_CATEGORIES: tuple[str, ...] = ("comida", "texto", "transicion", "movimiento", "general")

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


#: ADR 50 D5: a «Con IA» effect is offered only when the paid bench (EF-12) measured it
#: at a success rate of at least `MEASURED_MIN_SUCCESSES_OF` = 2 of 3, over at least
#: `MEASURED_MIN_N` = 4 tries. Kept as a pair of integers so 2/3 is exact (never 0.666…).
MEASURED_MIN_N = 4
MEASURED_MIN_SUCCESSES_OF: tuple[int, int] = (2, 3)


class Measured(BaseModel):
    """The paid bench's result for a «Con IA» effect (EF-12): successes of `n`, the
    Wilson interval, the day it ran and the Seedance `model` it ran on. Offered only when
    present AND over D5's bar (`passes`), and asked only of that same model
    (`measured_on_model`): a result on one model says nothing of another."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    successes: int = Field(ge=0)
    n: int = Field(ge=1)
    wilson_low: float = Field(ge=0, le=1)
    wilson_high: float = Field(ge=0, le=1)
    measured_on: date
    #: The ModelArk model id the bench ran on (`dreamina-seedance-2-5-260628`, say).
    model: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def _coherent(self) -> Measured:
        if self.successes > self.n or self.wilson_low > self.wilson_high:
            raise ValueError("a measurement has successes ≤ n and low ≤ high")
        return self

    @property
    def passes(self) -> bool:
        """D5's bar (EF-13): at least `MEASURED_MIN_N` tries and a success rate of at
        least 2/3 (`MEASURED_MIN_SUCCESSES_OF`), compared in integers."""
        num, den = MEASURED_MIN_SUCCESSES_OF
        return self.n >= MEASURED_MIN_N and self.successes * den >= num * self.n


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
    #: For filtering only (never for hiding): see `EffectCategory`. () in v1 and v2.
    categories: tuple[EffectCategory, ...] = ()
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
            if self.offered and self.measured is not None and not self.measured.passes:
                raise ValueError(
                    "D5: a Seedance effect is offered only when measured at ≥ 2/3 with n ≥ 4"
                )
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
        if self.version >= 3:
            for entry in self.entries:
                if not entry.categories:
                    raise ValueError(
                        f"{entry.id}: from the library v3 on, an effect has a category"
                    )
                if len(set(entry.categories)) != len(entry.categories):
                    raise ValueError(f"{entry.id}: a category appears once")
        return self

    def get(self, effect_id: str, version: int) -> EffectEntry | None:
        return next((e for e in self.entries if e.id == effect_id and e.version == version), None)

    def has(self, effect_id: str) -> bool:
        return any(e.id == effect_id for e in self.entries)

    def offered(self, *, model: str | None = None) -> tuple[EffectEntry, ...]:
        """What the screen may offer (D5), in the file's order — the same for every
        business: categories only help the screen filter, they never hide an effect.
        `model`: the Seedance model the piece will be asked of — a «Con IA» effect
        measured on another one is left out (None: not known here, not filtered; the
        producer checks it again before anything is paid)."""
        return tuple(e for e in self.entries if e.offered and _clears_bench(e, model))


def _clears_bench(entry: EffectEntry, model: str | None = None) -> bool:
    """EF-13: a «Con IA» effect reaches a screen only with a bench result over D5's bar —
    the validator already refuses an offered one without it; this keeps `offered()`
    honest even for an entry built around the validator (`model_construct`) — and, given
    a `model`, only when it was measured on that model."""
    if entry.stage != "seedance_prompt":
        return True
    return measured_on_model(entry, model) if model is not None else _passes(entry)


def _passes(entry: EffectEntry) -> bool:
    return entry.measured is not None and entry.measured.passes


def measured_on_model(entry: EffectEntry, model: str | None) -> bool:
    """Whether a «Con IA» `entry` was measured over D5's bar ON `model` — the Seedance
    model it is about to be asked of (EF-13). A non-Seedance entry: True. Pure."""
    if entry.stage != "seedance_prompt":
        return True
    measured = entry.measured
    return (
        measured is not None and measured.passes and model is not None and (measured.model == model)
    )


# -- «objeto en una zona del cuadro» (EF-13, m-25026589) ------------------------------------

#: The version of how a Seedance template is FILLED (`seedance_effect_line`): the words a
#: zone becomes and the subject when the piece names no product. The template itself is
#: versioned by its entry (`prompt_version`); both go into the provenance, so the paid
#: bench (EF-12) and production fill a template the same way, and a change of either is
#: a new version.
SEEDANCE_EFFECT_FILL_VERSION = 1
#: Where in the frame (`zone` param: the three bands of the frame, `top`/`middle`/
#: `bottom`, as a video text's `place`), in the words «in the {zone} of the frame» takes.
ZONE_WORDS: dict[str, str] = {"top": "upper third", "middle": "middle", "bottom": "lower third"}
#: `{subject}` when the piece names no product.
DEFAULT_EFFECT_SUBJECT = "the main subject of the shot"
#: The longest product name put into `{subject}` (the rest of the prompt carries it whole).
_SUBJECT_MAX_CHARS = 80

#: EF-13 copy the screen shows for a «Con IA» effect (`qualify-copy-es`): its tag, and the
#: line that says what the part will cost of the plan's video seconds.
#: The effect itself costs nothing extra: what uses the plan's seconds is that the part is
#: made with AI (UX review, 2026-11-24).
AI_EFFECT_COST_NOTE = "Hecho con IA: usa segundos de video de tu plan"
AI_EFFECT_COST_LINE = "Esta parte usa {seconds} de video cuando la apruebes."


def seconds_label(seconds: int) -> str:
    """«1 segundo» / «5 segundos»: the same rule as the screen's `seconds_label`
    (`Qualify/creative_vm.py`), which this package cannot import."""
    return "1 segundo" if seconds == 1 else f"{seconds} segundos"


def ai_effect_cost_text(seconds: int) -> str:
    """`AI_EFFECT_COST_LINE` for a part of `seconds` (whole seconds, as the plan counts)."""
    return AI_EFFECT_COST_LINE.format(seconds=seconds_label(int(seconds)))


def effect_subject(product: str | None) -> str:
    """What `{subject}` says: the piece's product name in quotes (no emoji — `visual_text`,
    as every prompt text —, no quotes or braces of its own, at most `_SUBJECT_MAX_CHARS`),
    else `DEFAULT_EFFECT_SUBJECT`. Pure."""
    text = visual_text(product or "")
    for mark in ('"', "{", "}"):
        text = text.replace(mark, " ")
    name = " ".join(text.split())
    if not name:
        return DEFAULT_EFFECT_SUBJECT
    if len(name) > _SUBJECT_MAX_CHARS:
        name = name[:_SUBJECT_MAX_CHARS].rsplit(" ", 1)[0] or name[:_SUBJECT_MAX_CHARS]
    return f'"{name}"'


def effect_zone(entry: EffectEntry, use: EffectUse) -> str:
    """The zone the owner chose for `use` (its `zone` param), else the entry's default."""
    spec = entry.params.get("zone")
    chosen = use.param_values.get("zone")
    if isinstance(chosen, str) and (spec is None or spec.accepts(chosen)):
        return chosen
    if spec is not None and isinstance(spec.default, str):
        return spec.default
    return "middle"


class NotASeedanceEffect(ValueError):
    """`seedance_effect_line` was asked to fill an entry that is not a Seedance template."""


def seedance_effect_line(entry: EffectEntry, use: EffectUse, *, subject: str) -> str:
    """The line a Seedance template adds to the part's prompt (EF-13): its
    `prompt_template` with `{zone}` in `ZONE_WORDS` and `{subject}` as given
    (`effect_subject`). The one place a template is filled — production and the paid
    bench call it alike. Pure."""
    if entry.stage != "seedance_prompt" or not entry.prompt_template:
        raise NotASeedanceEffect(f"{entry.id} v{entry.version} is not a Seedance template")
    zone = ZONE_WORDS.get(effect_zone(entry, use), ZONE_WORDS["middle"])
    return entry.prompt_template.replace("{zone}", zone).replace("{subject}", subject)


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


class NotALibraryLayer(ValueError):
    """`layer_loop_file` was asked for something that is not a recorded layer of the
    library (a compose entry with an asset folder and a blend), or its loop is not a file
    inside the packaged assets folder."""


def layer_loop_file(entry: EffectEntry) -> Path:
    """The read-only door to a layer's recorded loop (EF-08): `<entry.asset>preview.webm`
    inside the packaged `effects_assets/` — the file the browser lays (its `preview_asset`
    in v3) and the compose lays. Refuses (`NotALibraryLayer`) an entry that is not a layer
    (stage `compose` with an `asset` and a `blend`), a path that resolves outside the
    assets folder, and a loop that is not there. Opens nothing; the caller only reads."""
    if entry.stage != "compose" or entry.asset is None or entry.blend is None:
        raise NotALibraryLayer(f"{entry.id} v{entry.version} is not a layer of the library")
    problem = _asset_path_problem(entry.asset, entry.id, entry.version)
    if problem:
        raise NotALibraryLayer(problem)
    path = preview_file(entry.asset + LAYER_LOOP_FILE)
    root = _ASSETS_DIR.resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise NotALibraryLayer(f"{entry.id}'s loop resolves outside {root}")
    if not resolved.is_file():
        raise NotALibraryLayer(f"{entry.id} v{entry.version} has no recorded loop at {path}")
    return resolved


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
    `transition_in`, `segments[0].key`, `mode`) and the effect it is about, if any.

    EF-06 (Deivid, 2026-11-16, option A): a length problem of a `local` piece
    (`local_length_out_of_range`, `segments_length_mismatch`) also says how long the
    stretches last at their speed, `duration_s`, rounded to 0.1 s — so the screen can say
    «tu video dura 2,0 s». None on every other problem."""

    model_config = ConfigDict(frozen=True)

    code: RecipeRefusal
    part: int | None = None
    field: str = ""
    effect_id: str | None = None
    duration_s: float | None = None


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
    that slot — and that the video's text layer draws (EF-05: `video_text` v1 draws only
    `scrim`, `render.video_text.SUPPORTED_LAYOUTS`) (`unknown_layout`). `field` names it
    in the problems (`text_layers[1]`)."""
    if layer is None:
        return ()
    found: list[RecipeProblem] = []
    if not _inside(layer.start_s, layer.end_s, window):
        found.append(RecipeProblem(code="span_outside_part", part=part, field=field))
    if layer.layout_id is None:
        return tuple(found)
    from qualify_creative.render.video_text import SUPPORTED_LAYOUTS  # noqa: PLC0415

    data = catalog()
    layout = data["layouts"].get(layer.layout_id.value, {})
    title = (layout.get("slots", {}).get("title") or {}).get("9:16")
    if (
        layer.layout_version != data["layout_version"]
        or "9:16" not in layout.get("formats", ())
        or not title
        # EF-05: only a design the video's text layer draws (`video_text` v1: the scrim)
        or layer.layout_id.value not in SUPPORTED_LAYOUTS
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
    "AI_EFFECT_COST_LINE",
    "AI_EFFECT_COST_NOTE",
    "DEFAULT_EFFECT_SUBJECT",
    "EFFECTS_LIBRARY_VERSION",
    "EFFECT_CATEGORIES",
    "EffectCategory",
    "EffectEntry",
    "EffectsLibrary",
    "LAYER_LOOP_FILE",
    "MEASURED_MIN_N",
    "MEASURED_MIN_SUCCESSES_OF",
    "Measured",
    "MissingPreviewAsset",
    "NotALibraryLayer",
    "NotASeedanceEffect",
    "ParamSpec",
    "RecipeProblem",
    "SEEDANCE_EFFECT_FILL_VERSION",
    "ZONE_WORDS",
    "ai_effect_cost_text",
    "effect_subject",
    "effect_use_problems",
    "effect_zone",
    "layer_loop_file",
    "load_effects",
    "measured_on_model",
    "parse_library",
    "part_effect_problems",
    "preview_file",
    "seconds_label",
    "seedance_effect_line",
    "text_layer_problems",
    "text_layers_problems",
    "transition_problems",
]
