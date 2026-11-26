"""Path A of the Clip's avatar-as-character (m-25112921, Deivid 2026-11-26) — the pure part.

The avatar is no longer a presenter in a corner: it is a CHARACTER that acts and speaks
inside a scene with the business's place and products (picks the product up, shows it,
eats it, says its line with lip-sync). Path A asks Seedance 2.5 for the whole scene in
one omni-reference task: the character's image (drawn by Seedream), the product photo,
the background and the spoken line in double quotes. Path B (OmniHuman + Seed Speech)
cannot be measured yet (no keys).

This module holds what needs no network and no file: the business (nibbles, ours), the
two characters (realistic and cartoon — Seedance 2.x tends to refuse faces that look
real), the two backgrounds (the owner's real photo of the place, and one drawn by
Seedream), the three scenes, the case matrix, the prompts, the cost of the whole plan
from the versioned pricing table, the spend ceiling, and the judgment sheet. The runner
is `packages/api/evals/avatar_escena/run_experiment.py`.

The questions, and the smallest matrix that answers them:

1. Does Seedance accept the character as a reference, or refuse it (and with what error)?
   → both characters in every scene.
2. Does the character stay the same between scenes? → each character in the 3 scenes,
   on the same background (the drawn one, always available).
3. Is the product recognizable? → every scene carries the product photo.
4. Voice and lips in Spanish? → every scene has a short spoken line.
5. Real photo of the place vs a drawn background? → scene 1 again on the real photo, per
   character (only when the photo exists: a slot that waits for it is left out).
Time and cost are measured on every task.

Two people judge (Deivid, Herwin), each on their own CSV; the automatic columns
(accepted, error, seconds, cost) are filled by the runner.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_UP, Decimal
from typing import Any

from qualify_creative.adapters.byteplus_ark import (
    DRAFT_RESOLUTION,
    estimate_video_tokens,
    video_cost_usd,
)
from qualify_creative.pricing import SEEDREAM_PRO_MODEL, JsonPricingTable, seedream_image_cost

from qualify_api.evals.spend_control import MAX_USD_CEILING

BENCH_TICKET = "m-25112921"
#: The version of this bench's method (matrix, criteria).
BENCH_VERSION = 1
#: Version of every prompt below (character, background, scene).
PROMPT_VERSION = "avatar-escena-v1"
PRICING_VERSION = "v10"
SEEDANCE_MODEL = "dreamina-seedance-2-5-260628"
SEEDREAM_MODEL = SEEDREAM_PRO_MODEL
#: Seedream 5.0 pro at 1080x1920 = 2.07 MP: the 1K price tier (<= 2.36 MP), 9:16.
IMAGE_SIZE = "1080x1920"
RATIO = "9:16"
#: How the scenes render: the 2.5 draft (480p, cheapest) or a 720p task.
RESOLUTION_MODES: tuple[str, ...] = ("borrador", "720p")
DEFAULT_RESOLUTION_MODE = "borrador"
#: Billed tokens ran ~1 % over the formula (SD25-002, EF11-001): every task is reserved
#: 10 % over its quote, and the whole plan must fit with that margin before the first.
RESERVE_MARGIN = Decimal("1.10")
#: The ceiling proposed for the paid run, and the hard one (spend_control's per run).
PROPOSED_MAX_USD = Decimal("8")
HARD_CEILING_USD = MAX_USD_CEILING
#: Options Seedream draws per character / drawn background (the owner picks one of 2-3).
DEFAULT_OPTIONS = 2
JUDGES: tuple[str, ...] = ("deivid", "herwin")


# -- the business ----------------------------------------------------------------------


@dataclass(frozen=True)
class Brand:
    name: str
    product: str
    palette: tuple[str, ...]
    font_heading: str
    font_body: str


#: nibbles («Nibbles' Burgers»), ours: palette and typefaces of its Brand Kit (the same
#: ones the EF-12 bench and the clip audit used).
NIBBLES = Brand(
    name="Nibbles' Burgers",
    product="super smash",
    palette=("#305046", "#da2220", "#f9ecc9", "#1d1f1e"),
    font_heading="Baloo 2",
    font_body="Nunito",
)


# -- characters, backgrounds, scenes ---------------------------------------------------


@dataclass(frozen=True)
class Character:
    id: str
    label: str
    style: str  # "realista" | "animado"
    prompt: str


@dataclass(frozen=True)
class Background:
    id: str
    label: str
    kind: str  # "foto" (the owner's real photo) | "dibujado" (Seedream)
    prompt: str | None = None


@dataclass(frozen=True)
class Scene:
    id: str
    seconds: int
    label: str
    action: str
    line: str


CHARACTERS: tuple[Character, ...] = (
    Character(
        id="realista",
        label="Personaje realista",
        style="realista",
        prompt=(
            "Photorealistic photo of an original, fictional young Latin American burger "
            "cook in his late twenties (not a celebrity, not a real person), short curly "
            "dark hair, warm friendly smile, wearing a dark green (#305046) apron over a "
            "cream (#f9ecc9) t-shirt. Full body from the knees up, standing and facing the "
            "camera, arms relaxed, hands empty and visible. Plain light grey studio "
            "background, soft even light, sharp focus, vertical 9:16. No text, no logos, "
            "no watermark."
        ),
    ),
    Character(
        id="animado",
        label="Personaje animado",
        style="animado",
        prompt=(
            "Stylized 3D animated cartoon character, original design: a cheerful young "
            "woman burger cook with big expressive eyes, a dark ponytail, a red (#da2220) "
            "cap and a dark green (#305046) apron over a cream (#f9ecc9) t-shirt, friendly "
            "smile. Full body from the knees up, standing and facing the camera, hands "
            "empty and visible. Plain light background, soft studio light, vertical 9:16, "
            "clean animated film look. No text, no logos, no watermark."
        ),
    ),
)

BACKGROUNDS: tuple[Background, ...] = (
    Background(id="local", label="Foto real del local", kind="foto"),
    Background(
        id="dibujado",
        label="Fondo dibujado",
        kind="dibujado",
        prompt=(
            "Photorealistic interior of a small, cozy neighborhood smash burger restaurant "
            "in Latin America, seen from the customer side of the counter: a flat-top "
            "grill and a menu board without legible text in the back, warm lights, dark "
            "green (#305046) and cream (#f9ecc9) walls with red (#da2220) accents, a "
            "wooden counter in the foreground with free space in the center where a person "
            "can stand. No people, no text, no logos, no watermark. Vertical 9:16."
        ),
    ),
)

#: Short lines in neutral Spanish, about 2 words a second, said inside the scene.
SCENES: tuple[Scene, ...] = (
    Scene(
        id="e1",
        seconds=5,
        label="Toma el producto y lo muestra",
        action=(
            "The character picks up the super smash burger from the counter with both "
            "hands and lifts it toward the camera to show it, smiling."
        ),
        line="¡Mira esta super smash, recién hecha!",
    ),
    Scene(
        id="e2",
        seconds=8,
        label="Lo prueba y reacciona",
        action=(
            "The character holds the super smash burger, takes a real bite, chews with "
            "visible pleasure, then lowers it a little and speaks to the camera."
        ),
        line="Mmm, crujiente por fuera y jugosa por dentro.",
    ),
    Scene(
        id="e3",
        seconds=10,
        label="La muestra e invita",
        action=(
            "The character turns the super smash burger in one hand so the camera sees "
            "its layers, then points at it with the other hand and invites the viewer, "
            "looking straight at the camera."
        ),
        line="Esta es la super smash de Nibbles. Ven hoy por la tuya.",
    ),
)

CHARACTER_IDS = tuple(c.id for c in CHARACTERS)
BACKGROUND_IDS = tuple(b.id for b in BACKGROUNDS)
SCENE_IDS = tuple(s.id for s in SCENES)
#: The scene repeated on the real photo of the place (question 5).
BACKGROUND_ARM_SCENE = "e1"
#: The background every character runs all its scenes on (question 2): always available.
CONSISTENCY_BACKGROUND = "dibujado"


def character(cid: str) -> Character:
    return next(c for c in CHARACTERS if c.id == cid)


def background(bid: str) -> Background:
    return next(b for b in BACKGROUNDS if b.id == bid)


def scene(sid: str) -> Scene:
    return next(s for s in SCENES if s.id == sid)


@dataclass(frozen=True)
class Case:
    """One Seedance task: character × background × scene."""

    character: Character
    background: Background
    scene: Scene

    @property
    def label(self) -> str:
        return f"{self.character.id}/{self.background.id}/{self.scene.id}"

    @property
    def file_stem(self) -> str:
        return self.label.replace("/", "__")


def case_matrix(*, local_photo: bool, characters: Iterable[str] | None = None) -> list[Case]:
    """The smallest matrix that answers the bench's questions (module docstring): every
    character in every scene on the drawn background, then scene 1 on the real photo of
    the place per character — only when that photo exists. Character by character, so a
    refused character shows up on its first task."""
    wanted = set(characters) if characters else set(CHARACTER_IDS)
    unknown = wanted - set(CHARACTER_IDS)
    if unknown:
        raise ValueError(f"unknown characters: {sorted(unknown)}")
    cases: list[Case] = []
    for char in CHARACTERS:
        if char.id not in wanted:
            continue
        for sc in SCENES:
            cases.append(Case(char, background(CONSISTENCY_BACKGROUND), sc))
        if local_photo:
            cases.append(Case(char, background("local"), scene(BACKGROUND_ARM_SCENE)))
    return cases


# -- prompts ---------------------------------------------------------------------------


def brand_line(brand: Brand = NIBBLES) -> str:
    """Brand fidelity (rule 7): palette and typefaces in every prompt."""
    return (
        f"Brand colors for any accents: {', '.join(brand.palette)}; brand typefaces "
        f"{brand.font_heading} and {brand.font_body} (no on-screen text is wanted)."
    )


def character_image_prompt(char: Character) -> str:
    return char.prompt


def background_image_prompt(bg: Background) -> str:
    if bg.prompt is None:
        raise ValueError(f"{bg.id} is the owner's photo: nothing to draw")
    return bg.prompt


def scene_prompt(case: Case, brand: Brand = NIBBLES) -> str:
    """The scene's prompt. The spoken line is NOT in it: it goes as the adapter's
    `dialogue`, which appends it in double quotes (what 2.x speaks with lip-sync)."""
    place = (
        "the owner's real restaurant, exactly as in Image 3"
        if case.background.kind == "foto"
        else "the restaurant of Image 3"
    )
    return (
        "A vertical 9:16 video, one continuous shot, natural light and realistic motion. "
        "Image 1 is the character: keep the same face, hair, body, clothes and style "
        "through the whole video. "
        f'Image 2 is the client\'s real product, "{brand.product}" from {brand.name}: keep '
        "its exact shape, layers and colors, never another burger. "
        f"Image 3 is the place: the scene happens in {place}. "
        f"Action: {case.scene.action} "
        "The character speaks in neutral Latin American Spanish, lips in sync with the "
        "words, a friendly natural voice, no background music. "
        "No captions, no subtitles, no logos, no watermark. "
        f"{brand_line(brand)}"
    )


def scene_params(
    case: Case,
    *,
    character_url: str,
    product_url: str,
    background_url: str,
    resolution_mode: str = DEFAULT_RESOLUTION_MODE,
    model: str = SEEDANCE_MODEL,
) -> dict[str, Any]:
    """`request.params` for `SeedanceVideoAdapter`: one omni-reference task with the
    three images in order (character, product, place), sound on, the line as dialogue."""
    if resolution_mode not in RESOLUTION_MODES:
        raise ValueError(f"resolution mode must be one of {RESOLUTION_MODES}")
    params: dict[str, Any] = {
        "model": model,
        "prompt": scene_prompt(case),
        "dialogue": case.scene.line,
        "reference_images": [character_url, product_url, background_url],
        "omni_reference_task_type": "reference",
        "ratio": RATIO,
        "duration_seconds": case.scene.seconds,
        "generate_audio": True,
    }
    if resolution_mode == "borrador":
        params.update(draft=True, resolution=DRAFT_RESOLUTION)
    else:
        params["resolution"] = "720p"
    return params


def image_params(prompt: str) -> dict[str, Any]:
    """`request.params` for `SeedreamImageAdapter`: text to image, no references."""
    return {"model": SEEDREAM_MODEL, "prompt": prompt, "size": IMAGE_SIZE}


# -- cost ------------------------------------------------------------------------------


def reserved(quote: Decimal) -> Decimal:
    return (quote * RESERVE_MARGIN).quantize(Decimal("0.0001"), ROUND_UP)


def scene_resolution(resolution_mode: str) -> str:
    return DRAFT_RESOLUTION if resolution_mode == "borrador" else "720p"


def scene_quote(case: Case, pricing: JsonPricingTable, resolution_mode: str) -> Decimal:
    """ModelArk's token formula at the output size (no reference video: the
    without-video rate), priced from the versioned table."""
    resolution = scene_resolution(resolution_mode)
    tokens = estimate_video_tokens(SEEDANCE_MODEL, resolution, RATIO, case.scene.seconds)
    return video_cost_usd(pricing, SEEDANCE_MODEL, resolution, tokens)


def image_quote(pricing: JsonPricingTable) -> Decimal:
    return seedream_image_cost(pricing, model_id=SEEDREAM_MODEL, size=IMAGE_SIZE, references=0)


@dataclass(frozen=True)
class PlanItem:
    phase: str  # "dibujar" | "escenas"
    label: str
    quote_usd: Decimal

    @property
    def reserved_usd(self) -> Decimal:
        return reserved(self.quote_usd)


def drawing_items(
    pricing: JsonPricingTable,
    *,
    options: int = DEFAULT_OPTIONS,
    characters: Iterable[str] | None = None,
) -> list[PlanItem]:
    """Seedream: `options` drawings per character and per drawn background."""
    if not 1 <= options <= 3:
        raise ValueError("the owner picks among 1 to 3 options")
    wanted = set(characters) if characters else set(CHARACTER_IDS)
    each = image_quote(pricing)
    items = [
        PlanItem("dibujar", f"personaje/{c.id}/opcion-{n}", each)
        for c in CHARACTERS
        if c.id in wanted
        for n in range(1, options + 1)
    ]
    items += [
        PlanItem("dibujar", f"fondo/{b.id}/opcion-{n}", each)
        for b in BACKGROUNDS
        if b.kind == "dibujado"
        for n in range(1, options + 1)
    ]
    return items


def scene_items(
    cases: Sequence[Case], pricing: JsonPricingTable, resolution_mode: str
) -> list[PlanItem]:
    return [PlanItem("escenas", c.label, scene_quote(c, pricing, resolution_mode)) for c in cases]


def plan_totals(items: Sequence[PlanItem]) -> dict[str, Any]:
    """Quote and reservation (with margin) per phase and in all, as strings."""
    out: dict[str, Any] = {}
    for phase in ("dibujar", "escenas"):
        mine = [i for i in items if i.phase == phase]
        out[phase] = {
            "items": len(mine),
            "quote_usd": str(sum((i.quote_usd for i in mine), Decimal(0))),
            "reserved_usd": str(sum((i.reserved_usd for i in mine), Decimal(0))),
        }
    out["total_quote_usd"] = str(sum((i.quote_usd for i in items), Decimal(0)))
    out["total_reserved_usd"] = str(sum((i.reserved_usd for i in items), Decimal(0)))
    return out


# -- guards ----------------------------------------------------------------------------


class SpendRefused(RuntimeError):
    """A paid step the bench refuses before sending anything."""


def validate_max_usd(value: Decimal | str) -> Decimal:
    """`--max-usd`: positive and at most `HARD_CEILING_USD`."""
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0:
        raise SpendRefused(f"--max-usd tiene que ser un monto positivo, no {value}")
    if amount > HARD_CEILING_USD:
        raise SpendRefused(f"--max-usd es como mucho US${HARD_CEILING_USD} por corrida")
    return amount


def mode_refusal(*, paid: bool, dry_run: bool) -> str | None:
    """Exactly one of `--dry-run` and `--i-have-spend-authorization`."""
    if paid and dry_run:
        return "Elige uno: --dry-run o --i-have-spend-authorization."
    if not paid and not dry_run:
        return (
            "Sin --i-have-spend-authorization no se gasta: usa --dry-run para ver el plan y "
            "el costo estimado."
        )
    return None


def fits_ceiling(
    items: Sequence[PlanItem], *, max_usd: Decimal, spent_before: Decimal
) -> str | None:
    """None when every item, reserved with its margin, fits under the ceiling minus what
    earlier phases of the same run spent; otherwise the refusal (nothing is sent)."""
    if not items:
        return None  # nothing left to pay
    need = sum((i.reserved_usd for i in items), Decimal(0))
    room = max_usd - spent_before
    if room <= 0:
        return (
            f"Ya se gastó US${spent_before} y el tope es US${max_usd}: no queda nada para "
            f"las {len(items)} llamadas que faltan. No se manda nada; para seguir hace falta "
            "un tope mayor aprobado por Deivid."
        )
    if need > room:
        return (
            f"El plan reserva US${need} (con 10 % de margen) y quedan US${room} del tope "
            f"de US${max_usd} (ya gastado: US${spent_before}). No se manda nada."
        )
    return None


# -- outcomes and the judgment sheet ---------------------------------------------------

#: Error codes ModelArk gives a reference it refuses for a real face (2.x).
FACE_REFUSAL_MARKERS: tuple[str, ...] = ("PrivacyInformation", "SensitiveContentDetected")


def refusal_kind(error: str | None) -> str | None:
    """None (accepted), «rostro» (a real face refused), «moderacion» (other content
    filter) or «otro» (any other failure)."""
    if not error:
        return None
    if any(marker in error for marker in FACE_REFUSAL_MARKERS):
        return "rostro" if "PrivacyInformation" in error else "moderacion"
    if "Moderat" in error or "Sensitive" in error:
        return "moderacion"
    return "otro"


#: Columns filled by the runner (the judges leave them as they are).
AUTO_COLUMNS: tuple[str, ...] = (
    "video",
    "personaje",
    "fondo",
    "escena",
    "se_pidio",
    "linea",
    "acepto_referencia",
    "error",
    "segundos_reales",
    "costo_usd",
)
#: Columns each judge fills: si / no / dudoso (dudoso counts as no), creible 1-3.
JUDGE_COLUMNS: tuple[str, ...] = (
    "personaje_igual",
    "producto_reconocible",
    "accion_cumplida",
    "voz_espanol_bien",
    "labios_sincronizados",
    "sin_letras",
    "creible",
    "nota",
)
SHEET_COLUMNS: tuple[str, ...] = AUTO_COLUMNS + JUDGE_COLUMNS
_YES = frozenset({"si", "sí", "s", "yes", "y", "1", "true"})


def sheet_rows(results: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """One row per task from the run's results (`resultados.json` entries)."""
    rows: list[dict[str, str]] = []
    for r in results:
        sc = scene(str(r["scene"]))
        error = r.get("error")
        rows.append(
            {
                "video": str(r.get("video") or ""),
                "personaje": str(r["character"]),
                "fondo": str(r["background"]),
                "escena": sc.id,
                "se_pidio": f"{sc.label} ({sc.seconds} s)",
                "linea": sc.line,
                "acepto_referencia": "no"
                if refusal_kind(error) in ("rostro", "moderacion")
                else ("si" if r.get("video") else ""),
                "error": str(error or ""),
                "segundos_reales": str(r.get("seconds_taken") or ""),
                "costo_usd": str(r.get("cost_usd") or ""),
                **{c: "" for c in JUDGE_COLUMNS},
            }
        )
    return rows


def sheet_csv(rows: Sequence[Mapping[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=SHEET_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _yes(value: str | None) -> bool:
    return (value or "").strip().lower() in _YES


def summarize_sheet(text: str) -> dict[str, Any]:
    """Per character: tasks accepted, and of the judged videos how many kept the
    character, showed the product, spoke Spanish well and kept the lips in sync."""
    out: dict[str, Any] = {}
    for row in csv.DictReader(text.splitlines()):
        who = out.setdefault(
            row["personaje"],
            {"tareas": 0, "aceptadas": 0, "juzgadas": 0, **{c: 0 for c in JUDGE_COLUMNS[:6]}},
        )
        who["tareas"] += 1
        if _yes(row.get("acepto_referencia")):
            who["aceptadas"] += 1
        if not any((row.get(c) or "").strip() for c in JUDGE_COLUMNS[:6]):
            continue
        who["juzgadas"] += 1
        for c in JUDGE_COLUMNS[:6]:
            who[c] += int(_yes(row.get(c)))
    return out


__all__ = [
    "BACKGROUNDS",
    "BENCH_TICKET",
    "CHARACTERS",
    "Case",
    "NIBBLES",
    "PROMPT_VERSION",
    "PlanItem",
    "SCENES",
    "SHEET_COLUMNS",
    "SpendRefused",
    "case_matrix",
    "drawing_items",
    "fits_ceiling",
    "mode_refusal",
    "plan_totals",
    "refusal_kind",
    "scene_items",
    "scene_params",
    "scene_prompt",
    "sheet_csv",
    "sheet_rows",
    "summarize_sheet",
    "validate_max_usd",
]
