"""The Clip's realistic character drawn FROM A PHOTO of a real person (ADR 50 §12.12,
m-25129385 / m-25128784, Deivid 2026-11-26) — the pure part.

The owner uploads the photo of a real person who gave written permission; Seedream 5.0 pro
draws the character from it, and ONLY that drawing goes to Seedance 2.5 as the character
of the scene. Seedance never receives the photo: Seedance 2.x refuses real human faces and
accepts, as a character, an output of Seedream from our own account, unedited and under 30
days old (`docs/byteplus-datos-de-clientes.md` §1.4). That document names Seedream
TEXT-to-image outputs; a drawing made from a photo is image-to-image, so whether Seedance
accepts it is the key question.

The questions, and the smallest matrix that answers them (about 3 photos):

1. Does Seedream accept the photo and draw the character (or refuse it, e.g. the public
   figures filter)? → 2 options per photo, prompt `personaje-desde-foto-v1`.
2. Does Seedance accept that drawing as the character, and if not, with what error?
   → 1 scene per photo: AVESC-001's scene 1 (5 s, 480p draft) with the product and the
   background drawn in AVESC-001, the chosen option (1 unless `eleccion.json` says else).
3. How much does the character look like the person? → Deivid scores 1-3 on a sheet.

Reused from AVESC-001 (`avatar_scene_bench`): the business, the scene and its prompt, the
cost formulas, the spend guards, the refusal kinds. The runner is
`packages/api/evals/avatar_escena/personaje_foto.py`.

No photo of a real person is ever in the repository; the material file lists them with
`permiso_escrito: true` and the bench refuses the whole run when one lacks it.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from qualify_creative.pricing import JsonPricingTable, seedream_image_cost

from qualify_api.evals import avatar_scene_bench as scene_bench
from qualify_api.evals.avatar_scene_bench import (
    IMAGE_SIZE,
    NIBBLES,
    SEEDREAM_MODEL,
    Brand,
    Case,
    Character,
    PlanItem,
    brand_line,
    refusal_kind,
    scene_quote,
)

BENCH_TICKET = "m-25129385"
BENCH_ID = "AVFOTO-001"
BENCH_VERSION = 1
#: The drawing prompt's version; the scene keeps AVESC-001's (`SCENE_PROMPT_VERSION`).
PROMPT_VERSION = "personaje-desde-foto-v1"
SCENE_PROMPT_VERSION = scene_bench.PROMPT_VERSION
PRICING_VERSION = scene_bench.PRICING_VERSION
SEEDANCE_MODEL = scene_bench.SEEDANCE_MODEL
#: Every drawing sends ONE input image (the person's photo): the first is free on 5.0 pro.
REFERENCES_PER_DRAWING = 1
DEFAULT_OPTIONS = 2
#: AVESC-001's scene 1 (5 s): the cheapest scene that still has an action and a line.
SCENE_ID = "e1"
BACKGROUND_ID = "dibujado"
#: The draft is the only mode: it is the cheapest, and acceptance does not depend on it.
RESOLUTION_MODE = "borrador"
#: About 3 photos; never more than 5 (the same cap as a business's saved characters).
MAX_PEOPLE = 5
#: The ceiling proposed for the paid run: the plan reserves about US$1.99 (10 % margin);
#: the room left pays for asking one scene again with option 2 when option 1 is refused.
PROPOSED_MAX_USD = Decimal("3")
JUDGE = "deivid"
_PERSON_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,19}$")


# -- the people and their permission ---------------------------------------------------


class PermissionRefused(ValueError):
    """A material the bench refuses before anything leaves the machine."""


@dataclass(frozen=True)
class Person:
    """One person of the sample: an opaque id (never a name) and the written permission."""

    id: str
    permiso_escrito: bool


def check_people(raw: object) -> list[Person]:
    """The material's `personas`, validated. Refuses the WHOLE list when any person lacks
    `permiso_escrito: true` (the JSON boolean, nothing else counts), when an id is not a
    short lowercase slug or repeats, or when there are none or more than `MAX_PEOPLE`."""
    if not isinstance(raw, list) or not raw:
        raise PermissionRefused("personas: hace falta una lista con al menos una persona")
    if len(raw) > MAX_PEOPLE:
        raise PermissionRefused(f"personas: como mucho {MAX_PEOPLE} fotos por corrida")
    people: list[Person] = []
    without: list[str] = []
    for n, entry in enumerate(raw, start=1):
        if not isinstance(entry, Mapping):
            raise PermissionRefused(f"personas[{n}]: tiene que ser un objeto")
        pid = str(entry.get("id") or "")
        if not _PERSON_ID.match(pid):
            raise PermissionRefused(
                f"personas[{n}]: el id tiene que ser corto, en minúsculas, sin espacios "
                "(p1, p2…) y nunca el nombre de la persona"
            )
        if any(p.id == pid for p in people):
            raise PermissionRefused(f"personas: el id {pid} está repetido")
        if entry.get("permiso_escrito") is not True:
            without.append(pid)
        people.append(Person(id=pid, permiso_escrito=entry.get("permiso_escrito") is True))
    if without:
        raise PermissionRefused(
            f"Sin permiso escrito: {', '.join(without)}. No se usa ninguna foto sin "
            "«permiso_escrito»: true. No se manda nada."
        )
    return people


# -- prompts ---------------------------------------------------------------------------


def drawing_prompt(brand: Brand = NIBBLES) -> str:
    """`personaje-desde-foto-v1`: a realistic character that looks like the person of the
    reference photo, dressed and lit for the brand, posed like AVESC-001's characters so
    the same scene prompt works with it."""
    green, _, cream, _ = brand.palette
    return (
        "Image 1 is a reference photo of a person. Create a "
        "realistic portrait of a NEW character that clearly resembles this person: keep "
        "the same face shape, facial features, skin tone, hair color and hairstyle, "
        "apparent age and build, so people who know this person recognize them. Do not "
        "copy the photo: new pose, new clothes, new light, new background. "
        f"The character works at {brand.name}, a neighborhood burger restaurant: wearing a "
        f"dark green ({green}) apron over a cream ({cream}) t-shirt. Full body from the "
        "knees up, standing and facing the camera, arms relaxed, hands empty and visible, "
        "warm friendly smile. Plain light grey studio background, soft even light, sharp "
        "focus, vertical 9:16. No text, no logos, no watermark. "
        f"{brand_line(brand)}"
    )


def drawing_params(photo_url: str, brand: Brand = NIBBLES) -> dict[str, Any]:
    """`request.params` for `SeedreamImageAdapter`: image to image, the photo as the
    only reference, the same size as AVESC-001's characters (1K tier, 9:16)."""
    return {
        "model": SEEDREAM_MODEL,
        "prompt": drawing_prompt(brand),
        "size": IMAGE_SIZE,
        "images": [photo_url],
    }


def character_for(person: Person) -> Character:
    """The person's drawing as AVESC-001's `Character`, so its scene prompt and params
    apply unchanged (the drawing is «Image 1», the character)."""
    return Character(
        id=f"foto-{person.id}",
        label=f"Personaje desde la foto {person.id}",
        style="realista",
        prompt=drawing_prompt(),
    )


def case_for(person: Person) -> Case:
    return Case(
        character_for(person),
        scene_bench.background(BACKGROUND_ID),
        scene_bench.scene(SCENE_ID),
    )


def person_of(case: Case) -> str:
    return case.character.id.removeprefix("foto-")


def drawing_label(person_id: str, option: int) -> str:
    """`personaje-foto/<id>/opcion-<n>`: the runner's file name and `eleccion.json` key
    follow from it (`personaje-foto__<id>__opcion-<n>.jpg`, key `<id>`)."""
    return f"personaje-foto/{person_id}/opcion-{option}"


# -- cost ------------------------------------------------------------------------------


def drawing_quote(pricing: JsonPricingTable) -> Decimal:
    return seedream_image_cost(
        pricing, model_id=SEEDREAM_MODEL, size=IMAGE_SIZE, references=REFERENCES_PER_DRAWING
    )


def drawing_items(
    pricing: JsonPricingTable, people: Iterable[Person], *, options: int = DEFAULT_OPTIONS
) -> list[PlanItem]:
    if not 1 <= options <= 3:
        raise ValueError("the owner picks among 1 to 3 options")
    each = drawing_quote(pricing)
    return [
        PlanItem("dibujar", drawing_label(p.id, n), each)
        for p in people
        for n in range(1, options + 1)
    ]


def scene_items(pricing: JsonPricingTable, people: Iterable[Person]) -> list[PlanItem]:
    out = []
    for p in people:
        case = case_for(p)
        out.append(PlanItem("escenas", case.label, scene_quote(case, pricing, RESOLUTION_MODE)))
    return out


# -- outcomes and the judgment sheet ---------------------------------------------------

AUTO_COLUMNS: tuple[str, ...] = (
    "persona",
    "seedream_acepto_opcion_1",
    "seedream_acepto_opcion_2",
    "dibujo_opcion_1",
    "dibujo_opcion_2",
    "error_seedream",
    "opcion_en_video",
    "seedance_acepto",
    "tipo_rechazo",
    "error_seedance",
    "video",
    "costo_usd",
)
#: Deivid scores the likeness 1 (no se parece) · 2 (algo) · 3 (se reconoce a la persona).
JUDGE_COLUMNS: tuple[str, ...] = (
    "parecido_opcion_1",
    "parecido_opcion_2",
    "parecido_video",
    "nota",
)
SHEET_COLUMNS: tuple[str, ...] = AUTO_COLUMNS + JUDGE_COLUMNS
SCORE_COLUMNS: tuple[str, ...] = JUDGE_COLUMNS[:3]


def _accepted(row: Mapping[str, Any] | None) -> str:
    """«si» (made), «no» (refused by a content filter), «error» (other failure), «» (not
    asked yet)."""
    if not row:
        return ""
    if row.get("file") or row.get("video"):
        return "si"
    kind = refusal_kind(row.get("error"))
    if kind in ("rostro", "moderacion"):
        return "no"
    return "error" if row.get("error") else ""


def sheet_rows(
    people: Sequence[str],
    drawings: Mapping[str, Mapping[str, Any]],
    results: Mapping[str, Mapping[str, Any]],
    *,
    choices: Mapping[str, Any] | None = None,
) -> list[dict[str, str]]:
    """One row per person, from the run's `dibujos.json` and `resultados.json`."""
    rows: list[dict[str, str]] = []
    for pid in people:
        d1 = drawings.get(drawing_label(pid, 1))
        d2 = drawings.get(drawing_label(pid, 2))
        scene_row = results.get(case_for(Person(pid, True)).label) or {}
        cost = sum(
            (Decimal(str(r.get("cost_usd") or "0")) for r in (d1, d2, scene_row) if r),
            Decimal(0),
        )
        seedream_errors = " | ".join(str(r["error"]) for r in (d1, d2) if r and r.get("error"))
        rows.append(
            {
                "persona": pid,
                "seedream_acepto_opcion_1": _accepted(d1),
                "seedream_acepto_opcion_2": _accepted(d2),
                "dibujo_opcion_1": str((d1 or {}).get("file") or ""),
                "dibujo_opcion_2": str((d2 or {}).get("file") or ""),
                "error_seedream": seedream_errors,
                "opcion_en_video": str(scene_row.get("drawing_option") or "")
                if scene_row
                else str((choices or {}).get(pid, "")),
                "seedance_acepto": _accepted(scene_row),
                "tipo_rechazo": str(refusal_kind(scene_row.get("error")) or ""),
                "error_seedance": str(scene_row.get("error") or ""),
                "video": str(scene_row.get("video") or ""),
                "costo_usd": str(cost),
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


def _score(value: str | None) -> int | None:
    text = (value or "").strip()
    return int(text) if text in ("1", "2", "3") else None


def summarize_sheet(text: str) -> dict[str, Any]:
    """The three answers: how many photos Seedream drew (per option asked), how many
    drawings Seedance accepted (and the refusal kinds), and the likeness scores (1-3)
    with their mean; a score outside 1-3 is listed as invalid, never counted."""
    rows = list(csv.DictReader(text.splitlines()))
    out: dict[str, Any] = {"personas": len(rows)}
    asked = [r[c] for r in rows for c in AUTO_COLUMNS[1:3] if r.get(c)]
    out["seedream"] = {"pedidos": len(asked), "aceptados": asked.count("si")}
    scenes = [r for r in rows if r.get("seedance_acepto")]
    kinds: dict[str, int] = {}
    for r in scenes:
        if r.get("tipo_rechazo"):
            kinds[r["tipo_rechazo"]] = kinds.get(r["tipo_rechazo"], 0) + 1
    out["seedance"] = {
        "pedidos": len(scenes),
        "aceptados": sum(r["seedance_acepto"] == "si" for r in scenes),
        "rechazos": kinds,
    }
    invalid: list[str] = []
    for column in SCORE_COLUMNS:
        scores = []
        for r in rows:
            raw = (r.get(column) or "").strip()
            score = _score(raw)
            if score is not None:
                scores.append(score)
            elif raw:
                invalid.append(f"{r['persona']}/{column}={raw}")
        out[column] = {
            "juzgados": len(scores),
            "media": str(round(Decimal(sum(scores)) / len(scores), 2)) if scores else None,
            "por_valor": {str(v): scores.count(v) for v in (1, 2, 3)},
        }
    out["invalidos"] = invalid
    return out


__all__ = [
    "BENCH_ID",
    "BENCH_TICKET",
    "PROMPT_VERSION",
    "PROPOSED_MAX_USD",
    "PermissionRefused",
    "Person",
    "case_for",
    "check_people",
    "drawing_items",
    "drawing_label",
    "drawing_params",
    "drawing_prompt",
    "scene_items",
    "sheet_csv",
    "sheet_rows",
    "summarize_sheet",
]
