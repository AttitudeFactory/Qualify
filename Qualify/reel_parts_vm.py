"""«Tu video, parte por parte» on «Qué mostrar» (step 1) of the create flow (ADR 44 UI-3,
m-24921077) — pure.

Once the reel's analysis is `ok` (UI-2), «Qué mostrar» lists the parts its plan proposes
(`qualify_api.creative.parts.plan_from_analysis`). This module holds everything about that
list that is not I/O nor Reflex:

- `entries_from_plan` turns the plan and its analysis into the state's ENTRIES: the
  `VideoPartPlan` as JSON (what UI-6 will send) plus what the row needs and the plan does
  not carry — whether someone is seen (`person`) and why the part is not «Igual al
  original» (`reason`);
- `remove_part` takes a part out (UI-4's sheet owns description, mode and media);
  an `extend` part left without
  the part it continued becomes new (`reason` = `orphan`), said in its row;
- `part_rows` gives the rows the view draws (strings only, for `rx.foreach`);
- `usage_lines` says what the parts use of the month — vistas previas when created, seconds
  of video when the whole video is approved (ADR 44 F1 = b) — never money, never a block;
- `review_actions` is step 5 («Revisa y crea») in parts mode (UI-6, m-24921081): the
  summary in words, «Crear las n partes» / «Probar solo la parte 1» and why either is
  disabled (all or nothing).

Copy: `docs/ux-video-por-planos.md` §2, §3b and §4 (`qualify-copy-es`).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from qualify_api.creative.parts import NOTICE_TEXTS, PartsExtendUnavailable, is_vertical
from qualify_api.referentes.reel_analysis_types import OBSERVED, ReelAnalysis
from qualify_creative.schemas import (
    PART_GENERATION_MIN_SECONDS,
    VideoPartPlan,
)

from .ask_more_vm import PREVIEWS as EXHAUSTED_PREVIEWS
from .ask_more_vm import VIDEOS as EXHAUSTED_VIDEOS
from .ask_more_vm import exhausted_text
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
UNDO_LABEL = "Deshacer"

#: Every part was taken out: «Deshacer» (above the list) brings back the last one.
EMPTY_TITLE = "Tu video se quedó sin partes."
EMPTY_BODY = "Toca «Deshacer» para recuperar la última que quitaste."

USAGE_TITLE = "Lo que usa de tu mes"

#: The form of a part, as the owner reads it (§2), and its pill's tone.
FORM_EDIT = "Igual al original, con tu producto"
FORM_INSPIRED = "Nueva, inspirada en el original"
FORM_NEW = "Nueva, con tu producto"
#: m-24985141: without a product a new part is made from the brand.
FORM_NEW_BRAND = "Nueva, con tu marca"
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

#: A part the analysis could not see (`describe_it`): UI-4's sheet («Cambiar») is where
#: the owner writes what it shows.
DESCRIBE_REEL_TEXT = (
    "No pudimos ver qué pasa en esta parte. Toca «Cambiar» y cuéntanos qué muestra."
)
#: The same, for a part made without a reel (m-24921079).
DESCRIBE_NEW_TEXT = "Falta contar qué pasa en esta parte."

# m-24992893: a part's scene plays its stretch of the original reel, in place.
#: ▶ on the scene, and the playing scene (it pauses); `{n}` is the part's number.
PLAY_ORIGINAL_TEXT = "Ver la parte {n} del original"
PAUSE_PART_TEXT = "Pausar la parte {n}"
#: Said once to screen readers when the stored reel cannot be played any more.
ORIGINAL_GONE_TEXT = "Ya no podemos mostrar el reel original. Tus partes siguen aquí."


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
    analysis: ReelAnalysis | None, plan: Sequence[VideoPartPlan]
) -> list[dict[str, Any]]:
    """The state's entries for a reel's plan: each part's plan as JSON, whether someone
    is SEEN in its cuts (never «sin personas»: not seen is not certified absent) and
    why it is not «Igual al original». Without a reel (`analysis` None, m-24921079)
    nobody was seen and there is no why: the form («Nueva, con tu producto») says it."""
    shots = {shot.shot_index: shot for shot in analysis.shots} if analysis is not None else {}
    entries: list[dict[str, Any]] = []
    for part in plan:
        covered = [shots[i] for i in part.shot_indexes if i in shots]
        person = any(_seen(s.people_presence) or _seen(s.visible_faces) for s in covered)
        entries.append(
            {
                "key": _new_key(),
                "plan": part.model_dump(mode="json"),
                "person": person,
                "reason": _reason(part, analysis, person) if analysis is not None else "",
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


def form_label(plan: Mapping[str, Any], *, has_product: bool = True) -> str:
    mode = plan.get("mode")
    if mode == "edit":
        return FORM_EDIT
    if mode == "extend":
        return FORM_EXTEND
    if plan.get("analysis_id"):
        return FORM_INSPIRED
    return FORM_NEW if has_product else FORM_NEW_BRAND


def _seconds_words(seconds: int) -> str:
    return "1 segundo" if seconds == 1 else f"{seconds} segundos"


def _seconds_text(value: Any) -> str:
    """A stretch's bound as the media fragment takes it («1.5», «0»); "0" when absent."""
    try:
        seconds = float(value or 0.0)
    except (TypeError, ValueError):
        seconds = 0.0
    return f"{max(seconds, 0.0):g}"


def _describe_text(entry: Mapping[str, Any]) -> str:
    plan = entry["plan"]
    if str(plan.get("description") or "").strip():
        return ""
    return DESCRIBE_REEL_TEXT if plan.get("analysis_id") else DESCRIBE_NEW_TEXT


def part_rows(
    entries: Sequence[dict[str, Any]], *, has_product: bool = True
) -> list[dict[str, str]]:
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
        form = FORM_EXTEND_OF if stuck else form_label(plan, has_product=has_product)
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
                # m-24992893: the original reel's signed path ("" = no copy to play) and
                # the part's stretch of it, in seconds ("#t=start,end" on the screen)
                "source": str(entry.get("source") or ""),
                "start_s": _seconds_text(entry.get("start_s")),
                "end_s": _seconds_text(entry.get("end_s")),
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


def _seconds_left_text(seconds: int) -> str:
    return f"te queda {seconds} s" if seconds == 1 else f"te quedan {seconds} s"


def seconds_line(
    seconds: int,
    joined_seconds: int,
    seconds_left: int,
    seconds_quota: int,
    *,
    renews: str = "",
) -> str:
    """What approving the whole video uses of the month's seconds (UX review
    2026-11-09). `seconds` is what it uses (`generated_seconds`: a 1-3 s part counts as
    4), `joined_seconds` how long it really lasts; never the video's length set against
    what is left as if one were the other:

    - it fits: «Este video dura 20 s y este mes te quedan 40 s de video. Al aprobarlo
      te quedarían 20 s.» (1: «te quedaría 1 s.»; 0: «Al aprobarlo usas todos los
      segundos de video de este mes.»);
    - it does not: «Este video dura 44 s y este mes te quedan 35 s de video. Para
      aprobarlo, quita partes o espera al 1 de diciembre, cuando vuelven tus 40
      segundos.»;
    - none left: «Este video dura 44 s y ya usaste tus 40 segundos de video de este mes.
      Para aprobarlo, espera al 1 de diciembre, cuando vuelven.»

    With a 1-3 s part it lasts less than it uses, said in one sentence: «Este video dura
    7 s, pero usa 10 s de tu mes porque las partes de menos de 4 s cuentan como 4 s.»,
    then what is left. `renews` is the day as the owner reads it («1 de diciembre»,
    `creative_vm.renewal_day_label`). "" without seconds or a quota."""
    if seconds <= 0 or seconds_quota <= 0:
        return ""
    quota = seconds_label(seconds_quota)
    day = renews or "próximo mes"
    short_parts = joined_seconds < seconds
    if seconds_left > 0 and seconds <= seconds_left:
        after = seconds_left - seconds
        if after == 0:
            approve = "Al aprobarlo usas todos los segundos de video de este mes."
        else:
            approve = f"Al aprobarlo {'te quedaría' if after == 1 else 'te quedarían'} {after} s."
    elif seconds_left > 0:
        approve = f"Para aprobarlo, quita partes o espera al {day}, cuando vuelven tus {quota}."
    else:
        approve = f"Para aprobarlo, espera al {day}, cuando vuelven."
    if short_parts:
        head = (
            f"Este video dura {joined_seconds} s, pero usa {seconds} s de tu mes porque las "
            f"partes de menos de {PART_GENERATION_MIN_SECONDS} s cuentan como "
            f"{PART_GENERATION_MIN_SECONDS} s."
        )
        if seconds_left <= 0:
            return f"{head} Ya usaste tus {quota} de video de este mes. {approve}"
        if seconds > seconds_left:
            left = _seconds_left_text(seconds_left)
            return f"{head} Este mes {left}. {approve}"
        return f"{head} {approve}"
    if seconds_left <= 0:
        return (
            f"Este video dura {seconds} s y ya usaste tus {quota} de video de este mes. {approve}"
        )
    left = _seconds_left_text(seconds_left)
    return f"Este video dura {seconds} s y este mes {left} de video. {approve}"


def usage_lines(
    entries: Sequence[dict[str, Any]],
    *,
    previews_left: int,
    previews_quota: int,
    seconds_left: int,
    seconds_quota: int,
    renews: str = "",
    previews: bool = True,
    seconds: bool = True,
) -> list[str]:
    """The month's lines under the list (none when no quota is wired). `previews`
    False leaves out the vistas previas line — step 5 says it under its buttons when
    they fall short (UI-6: never twice); `seconds` False the seconds line, when step 5's
    reason already says none is left."""
    lines = [
        previews_line(len(entries), previews_left, previews_quota) if previews else "",
        seconds_line(
            generated_seconds(entries),
            total_seconds(entries),
            seconds_left,
            seconds_quota,
            renews=renews,
        )
        if seconds
        else "",
    ]
    return [line for line in lines if line]


# -- «Revisa y crea» por partes (ADR 44 UI-6, m-24921081) --------------------------------

#: The secondary action: only the first part, to see how it comes out (§3d).
TRY_FIRST_LABEL = "Probar solo la parte 1"
TRY_FIRST_NOTE = "Usa 1 vista previa. Las demás las creas después."
#: What the piece is, wherever the screen names its kind (summary, panel, result).
PARTS_PIECE_LABEL = "Video por partes"
#: Back to the parts list («Qué mostrar», step 1 since m-24985141) when a part blocks
#: creating them, or they fall short — named, never numbered.
BACK_TO_PARTS_LABEL = "Volver a «Qué mostrar»"
#: Every part was taken out on «Qué mostrar».
NO_PARTS_TEXT = "Tu video se quedó sin partes. Vuelve a «Qué mostrar» para recuperar alguna."
#: Creating the parent failed for a reason the owner cannot fix here (never raw text).
#: True on that path: the parent is priced at 0 (`REQUEST_SHOT_VIDEO`) and the parts —
#: what uses vistas previas — are only created by the worker after it exists.
PARTS_UNAVAILABLE_TEXT = (
    "No pudimos crear las partes de tu video y no se usó ninguna vista previa. Inténtalo más tarde."
)
#: The generation queue is off (`QUALIFY_CREATIVE_DISPATCHER` is not `queue`, m-24993023):
#: only the creative worker creates the parts, so a parent created now would wait forever.
#: Nothing is created and nothing of the month is used.
QUEUE_OFF_TEXT = (
    "Por ahora no podemos crear videos por partes. No se usó nada de tu mes. Inténtalo más tarde."
)

#: «Dos conservan el original…» — how many parts, in words up to ten (parts are «ellas»).
_PART_WORDS = ("una", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez")

#: What happens to a part of each form, said in plain words (§2): (one, several).
_FATE_EDIT = ("conserva el original", "conservan el original")
_FATE_NEW = ("se hace nueva", "se hacen nuevas")
_FATE_EXTEND = ("sigue a la anterior", "siguen cada una a la anterior")


#: m-24921079: without a reel every part is made new, from the product and the brand.
NO_REEL_FATE_ONE = "La parte se hace con tu producto y tu marca."
NO_REEL_FATE_MANY = "Las {n} partes se hacen con tu producto y tu marca."
#: m-24985141: the product is optional — without one, the parts come from the brand alone.
NO_REEL_FATE_ONE_BRAND = "La parte se hace con tu marca."
NO_REEL_FATE_MANY_BRAND = "Las {n} partes se hacen con tu marca."


def _from_reel(entries: Sequence[dict[str, Any]]) -> bool:
    """Some part comes from an analysed reel (a plan made without one has none)."""
    return any(e["plan"].get("analysis_id") for e in entries)


def _part_word(count: int) -> str:
    return _PART_WORDS[count - 1] if 1 <= count <= len(_PART_WORDS) else str(count)


def _fate(mode: str) -> tuple[str, str]:
    if mode == "edit":
        return _FATE_EDIT
    if mode == "extend":
        return _FATE_EXTEND
    return _FATE_NEW


def _join(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} y {items[-1]}"


def review_summary_text(entries: Sequence[dict[str, Any]], product: str = "") -> str:
    """Step 5's summary in words (§3d): «Un reel de 18 s en 4 partes, con tu smash
    doble. Dos conservan el original y dos se hacen nuevas.» Without a product the first
    sentence ends at the parts; a «Sigue a la anterior» part «sigue a la anterior»
    (several: «siguen cada una a la anterior»). "" without parts."""
    count = len(entries)
    if count <= 0:
        return ""
    noun = "1 parte" if count == 1 else f"{count} partes"
    product = " ".join(product.split())
    # m-24921079: a plan made without a reel is the owner's video, not a reel's copy
    from_reel = _from_reel(entries)
    head = f"{'Un reel' if from_reel else 'Tu video'} de {total_seconds(entries)} s en {noun}"
    head += f", con tu {product}." if product else "."
    if not from_reel:
        one, many = (
            (NO_REEL_FATE_ONE, NO_REEL_FATE_MANY)
            if product
            else (NO_REEL_FATE_ONE_BRAND, NO_REEL_FATE_MANY_BRAND)
        )
        tail = one if count == 1 else many.format(n=count)
        return f"{head} {tail}"
    tally = {_FATE_EDIT: 0, _FATE_NEW: 0, _FATE_EXTEND: 0}
    for entry in entries:
        tally[_fate(str(entry["plan"].get("mode") or ""))] += 1
    used = [(fate, n) for fate, n in tally.items() if n]
    if len(used) == 1:
        one, many = used[0][0]
        tail = f"La parte {one}." if count == 1 else f"Las {_part_word(count)} {many}."
    else:
        said = _join([f"{_part_word(n)} {one if n == 1 else many}" for (one, many), n in used])
        tail = f"{said[0].upper()}{said[1:]}."
    return f"{head} {tail}"


def create_all_label(parts: int) -> str:
    """The main action (§3d): «Crear las 4 partes»; «Crear la parte» with one."""
    return "Crear la parte" if parts == 1 else f"Crear las {parts} partes"


def blocked_parts(entries: Sequence[dict[str, Any]]) -> list[int]:
    """The 1-based parts the analysis could not see (`describe_it`) that still have no
    description: the backend refuses them (`PartNeedsDescription`), so nothing is
    created while one is in the plan (Deivid, 2026-11-09: «Sí, bloquear»)."""
    return [
        at
        for at, entry in enumerate(entries, start=1)
        if "describe_it" in (entry["plan"].get("notices") or ())
        and not str(entry["plan"].get("description") or "").strip()
    ]


def unsupported_parts(entries: Sequence[dict[str, Any]]) -> list[int]:
    """Preserve stored extends, but never charge/create a plan VE-13 cannot produce."""
    return [at for at, entry in enumerate(entries, 1) if entry["plan"].get("mode") == "extend"]


def parts_blocked_text(entries: Sequence[dict[str, Any]]) -> str:
    """«Falta contar qué pasa en la parte 3. Escríbelo para crear tu video.» — "" when
    every part can be created. Several: «…en las partes 2 y 4. …». Seen or not in a
    reel, the way out is the same: describe it in UI-4's sheet."""
    blocked = blocked_parts(entries)
    if not blocked:
        return ""
    if len(blocked) == 1:
        return f"Falta contar qué pasa en la parte {blocked[0]}. Escríbelo para crear tu video."
    which = _join([str(at) for at in blocked])
    return f"Falta contar qué pasa en las partes {which}. Escríbelo para crear tu video."


def parts_previews_short_text(
    parts: int, previews_left: int, previews_quota: int, *, renews: str = ""
) -> str:
    """The month cannot pay a vista previa for every part (§4, all or nothing): «Crear
    las 4 partes usa 4 vistas previas y este mes te quedan 2. Quita 2 partes en el paso
    2, prueba solo la parte 1 o espera al 1 de diciembre, cuando vuelven tus 20 vistas
    previas.» — "" when it fits, without a quota, or at 0 (the counter's zero state says
    it: `exhausted_text`; trying part 1 is not offered there)."""
    if previews_quota <= 0 or parts <= previews_left or previews_left <= 0:
        return ""
    day = renews or "próximo mes"
    left = "te queda 1" if previews_left == 1 else f"te quedan {previews_left}"
    drop = parts - previews_left
    remove = "Quita 1 parte" if drop == 1 else f"Quita {drop} partes"
    return (
        f"Crear las {parts} partes usa {parts} vistas previas y este mes {left}. "
        f"{remove} en «Qué mostrar», prueba solo la parte 1 o espera al {day}, cuando vuelven "
        f"tus {previews_quota} vistas previas."
    )


@dataclass(frozen=True)
class ReviewActions:
    """What step 5 says and allows in parts mode. A reason is why its button is
    disabled ("" = active) — the text its `aria-describedby` points to."""

    summary: str
    all_label: str
    #: «Probar solo la parte 1» is offered (more than one part).
    try_first: bool
    all_reason: str
    first_reason: str
    #: The counter at 0 (`ask_more_vm` kind, "" = none): the screen offers to ask more.
    exhausted: str
    #: «Volver a «Qué mostrar»» is offered: the fix is in the parts list.
    back_to_parts: bool
    #: The short reason beside the frame's primary («Crear las n partes»), "" = active.
    foot_reason: str = ""
    #: The reason is about the vistas previas (short or at 0): «Lo que usa de tu mes»
    #: leaves its vistas previas line out, so it is not said twice.
    previews_said: bool = False
    #: No part can be created: «‹ Ideas para tus reels» instead of «Volver a «Qué mostrar»».
    to_ideas: bool = False
    #: The reason says no second of video is left: the seconds line is left out.
    seconds_said: bool = False


def review_actions(
    entries: Sequence[dict[str, Any]],
    *,
    product: str = "",
    problem: str = "",
    previews_left: int = 0,
    previews_quota: int = 0,
    seconds_left: int = 0,
    seconds_quota: int = 0,
    renews: str = "",
    queue_on: bool = True,
) -> ReviewActions:
    """Step 5 in parts mode: the summary, «Crear las n partes» and «Probar solo la
    parte 1», and why either is disabled — all or nothing: nothing is created while a
    part cannot be (`describe_it`), the form still lacks something (`problem`), or the
    month cannot pay it. Vistas previas are used when the parts are created (one each);
    the seconds of video when the whole video is approved, so only a month with no
    second left holds creation (as Crear does today). A quota of 0 = none wired: never
    a block.

    An `extend` part is never first nor torn from the part it continues here: «Qué mostrar»'s
    every edit (`remove_part`, `move_unit`) runs `_settle`, which makes such a part new,
    with the same order rule as the backend's `check_extend_parts`.

    `queue_on` False (m-24993023: the generation queue is off, so the parts would never
    be created) holds both buttons before any other reason: nothing on this screen or on
    step 2 fixes it, so «Volver al paso 2» is not offered."""
    count = len(entries)
    if not queue_on:
        return ReviewActions(
            summary=review_summary_text(entries, product),
            all_label=create_all_label(count),
            try_first=count > 1,
            all_reason=QUEUE_OFF_TEXT,
            first_reason=QUEUE_OFF_TEXT,
            exhausted="",
            back_to_parts=False,
            # the body's callout says it all: no short reason in the foot (Deivid,
            # 2026-11-13 — it crowded «Atrás» in the fixed bar)
            foot_reason="",
        )
    blocked = blocked_parts(entries)
    to_ideas = False  # UI-4 lets the owner describe every part, including an unseen reel.
    exhausted = ""
    back = False
    reason = ""
    if count <= 0:
        reason, back = NO_PARTS_TEXT, True
    elif blocked:
        reason, back = parts_blocked_text(entries), not to_ideas
    elif unsupported_parts(entries):
        reason, back = PartsExtendUnavailable().text, True
    elif problem:
        reason = problem
    elif seconds_quota > 0 and seconds_left <= 0:
        exhausted = EXHAUSTED_VIDEOS
        reason = exhausted_text(EXHAUSTED_VIDEOS, seconds_quota)
    elif previews_quota > 0 and previews_left <= 0:
        exhausted = EXHAUSTED_PREVIEWS
        reason = exhausted_text(EXHAUSTED_PREVIEWS, previews_quota)
    short = (
        ""
        if reason
        else parts_previews_short_text(count, previews_left, previews_quota, renews=renews)
    )
    return ReviewActions(
        summary=review_summary_text(entries, product),
        all_label=create_all_label(count),
        try_first=count > 1,
        all_reason=reason or short,
        first_reason=reason,
        exhausted=exhausted,
        back_to_parts=back or bool(short),
        foot_reason=(
            FOOT_UNSUPPORTED
            if unsupported_parts(entries) and not blocked
            else _foot_reason(count, len(blocked), problem, exhausted, short)
        ),
        previews_said=bool(short) or exhausted == EXHAUSTED_PREVIEWS,
        to_ideas=to_ideas,
        seconds_said=exhausted == EXHAUSTED_VIDEOS,
    )


#: The foot's short reasons (the body says the whole sentence and the next step).
FOOT_NO_PARTS = "Tu video no tiene partes."
#: A part still missing what it shows (unseen in the reel, added by hand, or planned
#: without a reel): the foot only asks for its description.
FOOT_DESCRIBE = "Falta contar qué pasa en una parte."
FOOT_DESCRIBE_MANY = "Falta contar qué pasa en algunas partes."
FOOT_NO_PREVIEWS = "Ya usaste tus vistas previas del mes."
FOOT_NO_SECONDS = "Ya usaste tus segundos de video del mes."
FOOT_SHORT = "No te alcanzan las vistas previas."
FOOT_UNSUPPORTED = "Hay partes que siguen a la anterior. Hazlas nuevas para crear tu video."


def _foot_reason(count: int, blocked: int, problem: str, exhausted: str, short: str) -> str:
    if count <= 0:
        return FOOT_NO_PARTS
    if blocked:
        return FOOT_DESCRIBE if blocked == 1 else FOOT_DESCRIBE_MANY
    if problem:
        return problem
    if exhausted == EXHAUSTED_VIDEOS:
        return FOOT_NO_SECONDS
    if exhausted == EXHAUSTED_PREVIEWS:
        return FOOT_NO_PREVIEWS
    return FOOT_SHORT if short else ""


def previews_short_reason(parts: int, previews_left: int, previews_quota: int, renews: str) -> str:
    """What step 5 says when the vistas previas read just before creating do not reach
    the `parts` asked for and the screen's own counters did not know it yet: at 0 the
    counter's zero state, else `parts_previews_short_text`."""
    if previews_left <= 0:
        return exhausted_text(EXHAUSTED_PREVIEWS, previews_quota)
    return parts_previews_short_text(parts, previews_left, previews_quota, renews=renews)


__all__ = [
    "BACK_TO_PARTS_LABEL",
    "EMPTY_BODY",
    "EMPTY_TITLE",
    "FORM_EDIT",
    "FORM_EXTEND",
    "FORM_INSPIRED",
    "FORM_NEW",
    "FORM_NEW_BRAND",
    "LIST_HELP",
    "NO_PARTS_TEXT",
    "ORIGINAL_GONE_TEXT",
    "PAUSE_PART_TEXT",
    "PLAY_ORIGINAL_TEXT",
    "PARTS_PIECE_LABEL",
    "PARTS_UNAVAILABLE_TEXT",
    "QUEUE_OFF_TEXT",
    "TRY_FIRST_LABEL",
    "TRY_FIRST_NOTE",
    "ReviewActions",
    "LIST_TITLE",
    "PERSON_TAG",
    "REASON_TEXTS",
    "REMOVE_LABEL",
    "UNDO_LABEL",
    "USAGE_TITLE",
    "based_on_text",
    "blocked_parts",
    "create_all_label",
    "parts_blocked_text",
    "parts_previews_short_text",
    "previews_short_reason",
    "review_actions",
    "review_summary_text",
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
