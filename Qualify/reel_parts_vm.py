"""«Tu video, parte por parte» on step 2 of the create flow (ADR 44 UI-3, m-24921077) — pure.

Once the reel's analysis is `ok` (UI-2), step 2 lists the parts its plan proposes
(`qualify_api.creative.parts.plan_from_analysis`). This module holds everything about that
list that is not I/O nor Reflex:

- `entries_from_plan` turns the plan and its analysis into the state's ENTRIES: the
  `VideoPartPlan` as JSON (what UI-6 will send) plus what the row needs and the plan does
  not carry — whether someone is seen (`person`) and why the part is not «Igual al
  original» (`reason`);
- `remove_part` takes a part out («Quitar» is the list's only edit until UI-4's sheet:
  Deivid hid «Cambiar» and «Añadir parte», 2026-11-09); an `extend` part left without
  the part it continued becomes new (`reason` = `orphan`), said in its row;
- `part_rows` gives the rows the view draws (strings only, for `rx.foreach`);
- `usage_lines` says what the parts use of the month — vistas previas when created, seconds
  of video when the whole video is approved (ADR 44 F1 = b) — never money, never a block.

Copy: `docs/ux-video-por-planos.md` §2, §3b and §4 (`qualify-copy-es`).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from qualify_api.creative.parts import NOTICE_TEXTS, is_vertical
from qualify_api.referentes.reel_analysis_types import OBSERVED, ReelAnalysis
from qualify_creative.schemas import (
    PART_GENERATION_MIN_SECONDS,
    VideoPartPlan,
)

from .creative_vm import seconds_label

# -- copy -----------------------------------------------------------------------------

#: The parts live in the clip's own «Orden del clip» block (Deivid, 2026-11-09).
LIST_TITLE = "Orden del clip"
LIST_HELP = (
    "Tu video va en este orden. Arrastra las partes para cambiarlo; quita las que no quieras."
)
REEL_LINK_SHORT = "Ver el reel"
PERSON_TAG = "Aparece una persona"

REMOVE_LABEL = "Quitar"
#: Said once under «Lo que usa de tu mes» when a part is generated longer than it lasts.
SHORT_PARTS_NOTE = (
    f"Las partes de menos de {PART_GENERATION_MIN_SECONDS} s cuentan como "
    f"{PART_GENERATION_MIN_SECONDS}."
)
UNDO_LABEL = "Deshacer"

#: Every part was taken out: «Deshacer» (above the list) brings back the last one.
EMPTY_TITLE = "Tu video se quedó sin partes."
EMPTY_BODY = "Toca «Deshacer» para recuperar la última que quitaste."

USAGE_TITLE = "Lo que usa de tu mes"

#: The form of a part, as the owner reads it (§2), and its pill's tone.
FORM_EDIT = "Igual al original, con tu producto"
FORM_INSPIRED = "Nueva, inspirada en el original"
FORM_NEW = "Nueva, con tu producto"
FORM_EXTEND = "Sigue a la anterior"
#: An `extend` row names the part it is stuck to instead (it moves with it).
#: An `extend` row's pill: §2's name, marked as stuck to the part above it.
FORM_EXTEND_OF = "↳ Sigue a la anterior"

# -- why a part is not «Igual al original» (the grey line, §3b) -------------------------

#: Someone is seen in the part's cuts (F6).
REASON_PERSON = "person"
#: The analysis could not tell whether someone is in it (`people_unclear`).
REASON_UNCLEAR = "unclear"
#: The reel is not vertical (N5): no part of it is edited.
REASON_NOT_VERTICAL = "not_vertical"
#: The original video cannot be used (no source kept, or not editable).
REASON_NO_SOURCE = "no_source"
#: An `extend` part: it continues the one before.
REASON_EXTEND = "extend"
#: An `extend` part whose previous part was taken out: it is now made new.
REASON_ORPHAN = "orphan"

REASON_TEXTS: Mapping[str, str] = {
    REASON_PERSON: (
        "Aquí aparece una persona: la hacemos nueva con tu producto. La persona será otra."
    ),
    REASON_UNCLEAR: NOTICE_TEXTS["people_unclear"],
    REASON_NOT_VERTICAL: (
        "El reel no es vertical, así que hacemos esta parte nueva con tu producto."
    ),
    REASON_NO_SOURCE: (
        "No podemos usar el video original en esta parte: la hacemos nueva con tu producto."
    ),
    REASON_EXTEND: "Va pegada a la parte {n}: se mueve con ella.",
    REASON_ORPHAN: "Ya no está la parte anterior: la hacemos nueva, inspirada en el original.",
}

#: A part the analysis could not see (`describe_it`). Only the fact: until UI-4's sheet
#: this screen has no way to write what it shows (Deivid, 2026-11-09), so no «Cuéntanos…».
DESCRIBE_REEL_TEXT = "No pudimos ver qué pasa en esta parte del reel."


def removed_text(index: int) -> str:
    """«Quitaste la parte 3.» — said where the part was, with «Deshacer» (N3)."""
    return f"Quitaste la parte {index}."


def moved_text(index: int, place: int) -> str:
    """«Moviste la parte 3: ahora es la parte 2.» — the list's live line after a move."""
    return f"Moviste la parte {index}: ahora es la parte {place}."


def based_on_text(handle: str) -> str:
    """«Basado en un reel de @smash_hiro» (desktop head of the list)."""
    handle = handle.strip()
    return f"Basado en un reel de {handle}" if handle else "Basado en un reel"


def summary_text(parts: int, seconds: int) -> str:
    """«4 partes · 18 s» — how many parts and how long the joined video lasts."""
    noun = "1 parte" if parts == 1 else f"{parts} partes"
    return f"{noun} · {seconds} s"


# -- entries (the state's plan) ---------------------------------------------------------


def _new_key() -> str:
    return uuid.uuid4().hex[:12]


def _seen(value: str) -> bool:
    return value == OBSERVED


def _is_vertical(analysis: ReelAnalysis) -> bool:
    return is_vertical(analysis.width, analysis.height)


def _reason(plan: VideoPartPlan, analysis: ReelAnalysis, person: bool) -> str:
    """Why the AI did not choose «Igual al original» ("" when it did)."""
    if plan.mode == "edit":
        return ""
    if plan.mode == "extend":
        return REASON_EXTEND
    if person:
        return REASON_PERSON
    if "people_unclear" in plan.notices:
        return REASON_UNCLEAR
    if not _is_vertical(analysis):
        return REASON_NOT_VERTICAL
    return REASON_NO_SOURCE


def entries_from_plan(
    analysis: ReelAnalysis, plan: Sequence[VideoPartPlan]
) -> list[dict[str, Any]]:
    """The state's entries for a reel's plan: each part's plan as JSON, whether someone
    is SEEN in its cuts (never «sin personas»: not seen is not certified absent) and
    why it is not «Igual al original»."""
    shots = {shot.shot_index: shot for shot in analysis.shots}
    entries: list[dict[str, Any]] = []
    for part in plan:
        covered = [shots[i] for i in part.shot_indexes if i in shots]
        person = any(_seen(s.people_presence) or _seen(s.visible_faces) for s in covered)
        entries.append(
            {
                "key": _new_key(),
                "plan": part.model_dump(mode="json"),
                "person": person,
                "reason": _reason(part, analysis, person),
            }
        )
    return entries


def _continues(previous: Mapping[str, Any] | None, plan: Mapping[str, Any]) -> bool:
    """An `extend` still has the part it continues: not the first one, and — when it
    comes from a reel's cut — right after the part that ends on that cut (VE-06)."""
    if previous is None:
        return False
    cuts = list(plan.get("shot_indexes") or ())
    if not cuts:
        return True
    before = previous["plan"]
    before_cuts = list(before.get("shot_indexes") or ())
    return (
        bool(before_cuts)
        and before.get("analysis_id") == plan.get("analysis_id")
        and before_cuts[-1] == cuts[0]
    )


def _settle(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """An `extend` that lost the part it continued is made new, inspired by the original
    (the plan would not be valid otherwise); its row says why."""
    out: list[dict[str, Any]] = []
    for entry in entries:
        plan = entry["plan"]
        previous = out[-1] if out else None
        if plan.get("mode") == "extend" and not _continues(previous, plan):
            entry = {
                **entry,
                "plan": {**plan, "mode": "reference"},
                "reason": REASON_ORPHAN,
            }
        out.append(entry)
    return out


def remove_part(entries: Sequence[dict[str, Any]], key: str) -> tuple[list[dict[str, Any]], int]:
    """The entries without the part `key`, and its 1-based position (0 when unknown)."""
    at = next((i for i, e in enumerate(entries) if e["key"] == key), -1)
    if at < 0:
        return list(entries), 0
    rest = [dict(e) for i, e in enumerate(entries) if i != at]
    return _settle(rest), at + 1


def _units(entries: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """The plan in movable units: a part and the `extend` parts stuck after it («Sigue
    a la anterior» goes where its part goes). After `_settle` no unit starts with an
    `extend`."""
    units: list[list[dict[str, Any]]] = []
    for entry in entries:
        if entry["plan"].get("mode") == "extend" and units:
            units[-1].append(entry)
        else:
            units.append([entry])
    return units


def unit_count(entries: Sequence[dict[str, Any]]) -> int:
    return len(_units(entries))


def move_unit(
    entries: Sequence[dict[str, Any]], start: int, target: int
) -> tuple[list[dict[str, Any]], int, int]:
    """Unit `start` (0-based, as dragged) put at unit place `target`, its `extend`
    parts with it. Returns the entries and the moved part's 1-based position before and
    after (0, 0 when nothing moved). Never re-plans: the parts stay as they are."""
    units = _units([dict(e) for e in entries])
    if start == target or not (0 <= start < len(units) and 0 <= target < len(units)):
        return list(entries), 0, 0
    head_key = units[start][0]["key"]
    before = next(i for i, e in enumerate(entries) if e["key"] == head_key) + 1
    units.insert(target, units.pop(start))
    moved = _settle([e for unit in units for e in unit])
    after = next(i for i, e in enumerate(moved) if e["key"] == head_key) + 1
    return moved, before, after


def move_part(
    entries: Sequence[dict[str, Any]], key: str, step: int
) -> tuple[list[dict[str, Any]], int, int]:
    """«Antes» (`step` -1) / «Después» (+1) of the part `key`: its unit one place up or
    down. An `extend` part does not move on its own (0, 0)."""
    units = _units(entries)
    at = next((i for i, unit in enumerate(units) if unit[0]["key"] == key), -1)
    if at < 0 or step not in (-1, 1):
        return list(entries), 0, 0
    return move_unit(entries, at, at + step)


def plans(entries: Sequence[dict[str, Any]]) -> tuple[VideoPartPlan, ...]:
    """The entries as the brief's `MediaInputs.parts` (UI-6 sends them)."""
    return tuple(VideoPartPlan.model_validate(e["plan"]) for e in entries)


# -- rows (what the view draws) ---------------------------------------------------------


def form_label(plan: Mapping[str, Any]) -> str:
    mode = plan.get("mode")
    if mode == "edit":
        return FORM_EDIT
    if mode == "extend":
        return FORM_EXTEND
    return FORM_INSPIRED if plan.get("analysis_id") else FORM_NEW


def _seconds_words(seconds: int) -> str:
    return "1 segundo" if seconds == 1 else f"{seconds} segundos"


def _describe_text(entry: Mapping[str, Any]) -> str:
    plan = entry["plan"]
    return "" if str(plan.get("description") or "").strip() else DESCRIBE_REEL_TEXT


def part_rows(entries: Sequence[dict[str, Any]]) -> list[dict[str, str]]:
    """One row per part, strings only: «Parte n · s s», what it shows, its form (pill
    and tone), «Aparece una persona» when someone is seen, the why line, the line that
    asks for a description, and the sentence a screen reader announces."""
    total = len(entries)
    rows: list[dict[str, str]] = []
    unit = -1
    head = 0  # 1-based position of the part an `extend` is stuck to
    for at, entry in enumerate(entries, start=1):
        plan = entry["plan"]
        seconds = int(plan.get("seconds") or 0)
        stuck = plan.get("mode") == "extend" and at > 1
        if not stuck:
            unit += 1
            head = at
        form = FORM_EXTEND_OF if stuck else form_label(plan)
        why = REASON_TEXTS.get(str(entry.get("reason") or ""), "")
        if stuck:
            why = REASON_TEXTS[REASON_EXTEND].format(n=head)
        person = bool(entry.get("person"))
        aria = f"Parte {at} de {total}, {_seconds_words(seconds)}, {form.lstrip('↳ ').lower()}"
        if person:
            aria += f", {PERSON_TAG.lower()}"
        rows.append(
            {
                "key": str(entry["key"]),
                "index": str(at),
                # signed `/avatar/frame/…` path set by the provider; "" = placeholder
                "thumb": str(entry.get("thumb") or ""),
                # «↳» marks a part stuck to the one before (its group moves it)
                "label": f"{'↳ ' if stuck else ''}Parte {at} · {seconds} s",
                "aria": aria,
                "description": str(plan.get("description") or ""),
                "why": why,
                "describe": _describe_text(entry),
                "remove_label": f"{REMOVE_LABEL} la parte {at}",
                # moving: a unit's head moves (drag, «Antes», «Después»); its `extend`
                # parts go with it and show no buttons of their own
                "movable": "" if stuck else "1",
                "unit": str(unit),
            }
        )
    return rows


def part_units(rows: Sequence[dict[str, str]]) -> list[list[dict[str, str]]]:
    """The rows grouped by unit (a part and the «Sigue a la anterior» rows stuck to it):
    what one drag card carries, so a pair travels together on screen."""
    units: list[list[dict[str, str]]] = []
    for row in rows:
        if row["movable"] or not units:
            units.append([row])
        else:
            units[-1].append(row)
    return units


def total_seconds(entries: Sequence[dict[str, Any]]) -> int:
    """How long the joined video lasts (each part's own seconds)."""
    return sum(int(e["plan"].get("seconds") or 0) for e in entries)


def generated_seconds(entries: Sequence[dict[str, Any]]) -> int:
    """The month's seconds of video the parts use at approval: what each asks the
    generator for (`generation_seconds`: a 1-3 s part is made at 4)."""
    return sum(
        max(int(e["plan"].get("seconds") or 0), PART_GENERATION_MIN_SECONDS) for e in entries
    )


# -- «Lo que usa de tu mes» (never money, never a block) --------------------------------


def previews_line(parts: int, previews_left: int, previews_quota: int) -> str:
    """«Crear las 4 partes usa 4 vistas previas. Te quedan 12.» — "" without parts or
    without a quota of vistas previas."""
    if parts <= 0 or previews_quota <= 0:
        return ""
    what = (
        "Crear la parte usa 1 vista previa"
        if parts == 1
        else (f"Crear las {parts} partes usa {parts} vistas previas")
    )
    if previews_left <= 0:
        return f"{what}, y ya usaste tus {previews_quota} de este mes."
    if parts > previews_left:
        left = "te queda 1" if previews_left == 1 else f"te quedan {previews_left}"
        return f"{what}, y este mes {left}."
    return f"{what}. " + ("Te queda 1." if previews_left == 1 else f"Te quedan {previews_left}.")


def seconds_line(
    seconds: int,
    joined_seconds: int,
    seconds_left: int,
    seconds_quota: int,
    *,
    renews: str = "",
) -> str:
    """What approving the whole video uses of the month's seconds, said like
    `creative_vm.approval_videos_notice` (what is left AFTER approving): «Al aprobar el
    video usas 20 de tus 40 segundos de video del mes. Te quedarían 20 segundos.» — the
    seconds asked of the generator (a 1-3 s part counts as 4, said in its own sentence).
    When the month falls short, the next step (§4): take parts out or wait for `renews`
    («1 de diciembre»). "" without seconds or a quota."""
    if seconds <= 0 or seconds_quota <= 0:
        return ""
    quota = seconds_label(seconds_quota)
    day = renews or "próximo mes"
    if seconds_left <= 0:
        text = (
            f"Al aprobar el video usas {seconds_label(seconds)} de video del mes, y ya "
            f"usaste tus {quota} de este mes. Espera al {day}, cuando vuelven tus {quota}."
        )
    elif seconds > seconds_left:
        left = ("te queda " if seconds_left == 1 else "te quedan ") + seconds_label(seconds_left)
        text = (
            f"Al aprobar el video usas {seconds} de tus {quota} de video del mes, y este mes "
            f"{left}. Quita partes o espera al {day}, cuando vuelven tus {quota}."
        )
    else:
        after = seconds_left - seconds
        remain = "Te quedaría" if after == 1 else "Te quedarían"
        text = (
            f"Al aprobar el video usas {seconds} de tus {quota} de video del mes. "
            f"{remain} {seconds_label(after)}."
        )
    if seconds > joined_seconds:
        text += f" {SHORT_PARTS_NOTE}"
    return text


def usage_lines(
    entries: Sequence[dict[str, Any]],
    *,
    previews_left: int,
    previews_quota: int,
    seconds_left: int,
    seconds_quota: int,
    renews: str = "",
) -> list[str]:
    """The month's lines under the list (none when no quota is wired)."""
    lines = [
        previews_line(len(entries), previews_left, previews_quota),
        seconds_line(
            generated_seconds(entries),
            total_seconds(entries),
            seconds_left,
            seconds_quota,
            renews=renews,
        ),
    ]
    return [line for line in lines if line]


__all__ = [
    "EMPTY_BODY",
    "EMPTY_TITLE",
    "FORM_EDIT",
    "FORM_EXTEND",
    "FORM_INSPIRED",
    "FORM_NEW",
    "LIST_HELP",
    "LIST_TITLE",
    "SHORT_PARTS_NOTE",
    "PERSON_TAG",
    "REASON_TEXTS",
    "REMOVE_LABEL",
    "UNDO_LABEL",
    "USAGE_TITLE",
    "based_on_text",
    "entries_from_plan",
    "form_label",
    "generated_seconds",
    "move_part",
    "move_unit",
    "moved_text",
    "unit_count",
    "part_rows",
    "part_units",
    "plans",
    "previews_line",
    "remove_part",
    "removed_text",
    "seconds_line",
    "summary_text",
    "total_seconds",
    "usage_lines",
]
