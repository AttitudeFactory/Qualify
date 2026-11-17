"""«Arma tu video» (ED-02 m-25026621, ED-03 m-25026623, ED-05 m-25026630, ED-10
m-25026648; epic «Video automático con efectos, por pasos»): the words and the pure
rules of the normal Clip's first step as an editor — the preview in sequence on top,
the timeline under it (`ui.timeline`: ruler, playhead, three tracks), its action bar
and the chosen block's panel. One block chosen at a time (`?bloque=video-2`). Nothing
is generated here; every change is kept at once with «Deshacer» (D-E6, no «Guardar»).

The state (`CreativeState`, «clip editor» block) holds the owner's choices as plain
fields; `snapshot` / `change_message` / `push_undo` here decide what «Deshacer» brings
back and what the live line says, and `recipe_of` turns the fields into the
`editor_preview_contract.PartRecipe` (EF-02's shape) the brief carries.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence

from . import editor_preview_contract as contract
from .ui import timeline_vm

# -- the switch ----------------------------------------------------------------------------

#: The editor is behind `QUALIFY_CLIP_EDITOR`: `off` (the default, as in `.env.example`
#: and `deploy/.env.prod.example`) keeps the Clip's step 1 as «Qué mostrar», exactly as
#: before; `1` (or `on`/`true`) turns it on. Anything else is off. Read once, at import,
#: like the other `QUALIFY_*` of `Qualify/`; tests patch `CLIP_EDITOR_ON`.
#: B6 (m-25048789): «Crear» now sends the recipe the backend makes (EF-06's `local` Clip:
#: `segments` / `text_layers` / `effects` of `MediaInputs`), so what the preview shows is
#: what comes out. Turning it on in production still needs Deivid's OK, with A9
#: (m-25042483) on main and the production `.env.prod` changed through `just env-push`
#: (`qualify-prod-ops`); the generation queue (`QUALIFY_CREATIVE_DISPATCHER=queue`) is
#: required — with threads a `local` Clip is refused (`local_unavailable`).
CLIP_EDITOR_SWITCH = "QUALIFY_CLIP_EDITOR"
_ON_VALUES = ("1", "on", "true")


def switch_on(value: str | None) -> bool:
    """The house convention: `1`/`on`/`true` turn a switch on; ``off``, `0`, "" or any
    other value leave it off (a typo never turns it on)."""
    return (value or "").strip().lower() in _ON_VALUES


CLIP_EDITOR_ON = switch_on(os.environ.get(CLIP_EDITOR_SWITCH))

# -- the step ----------------------------------------------------------------------------

STEP_TITLE = "Arma tu video"
#: In the fixed zone, after «{t} de {total} · ».
PREVIEW_NOTE = "Así va quedando"
#: Under the card, in the part that scrolls.
PREVIEW_FREE = "Esta vista previa es gratis."
#: ONE line for a video the preview cannot show — known beforehand (no usable address)
#: or a real playback error (UX review 2026-11-14). It promises nothing EF-06 has not
#: defined yet.
PREVIEW_UNAVAILABLE = (
    "No pudimos mostrar tu video aquí, así que no puedes cortarlo. Lo verás listo antes de "
    "aprobarlo."
)
PREVIEW_REMOTE = PREVIEW_UNAVAILABLE
PREVIEW_BROKEN = PREVIEW_UNAVAILABLE
PREVIEW_SLOWER = "En la vista previa se ve más lento que en el video final."
PREVIEW_EMPTY = "Agrega una foto o un video para ver cómo va quedando."
PREVIEW_PLAY = "Ver cómo va quedando"
PREVIEW_PAUSE = "Pausar la vista previa"
PREVIEW_REGION = "Vista previa de tu video"
PARTS_LINK = "Armar mi video por partes"

# -- what «Agregar» opens (ED-10: the timeline's orbit, `timeline_vm.ADD_OPTIONS`) ------

FLOW_MEDIA = "media"
FLOW_TEXT = "text"
FLOW_EFFECT = "effect"
FLOW_IDEA = "idea"
FLOWS: tuple[str, ...] = (FLOW_MEDIA, FLOW_TEXT, FLOW_EFFECT, FLOW_IDEA)
#: A flow open in the panel is held where a chosen block's id would be, with this mark
#: (`+media`): one thing at a time under the timeline.
FLOW_MARK = "+"
FLOW_QUESTIONS = {
    FLOW_MEDIA: "¿Con qué lo armamos?",
    FLOW_TEXT: "¿Qué dice tu video?",
    FLOW_EFFECT: "¿Qué le pones a tu video?",
    FLOW_IDEA: "¿De qué trata tu video?",
}
#: Deivid 2026-11-17 («que se junten todo en un solo slide panel»): every flow is a tab of
#: ONE side panel — (flow, lucide icon, the tab's name). The chosen tab shows its icon and
#: name, the others their icon (`.q-source-seg`, the name in `aria-label`/`title`).
FLOW_TABS: tuple[tuple[str, str, str], ...] = (
    (FLOW_MEDIA, "image-plus", "¿Con qué lo armamos?"),
    (FLOW_TEXT, "type", "Texto"),
    (FLOW_EFFECT, "sparkles", "Efecto"),
    (FLOW_IDEA, "lightbulb", "Pedir una idea"),
)
#: The side panel's title (the tab's question goes under it, over its fields).
FLOW_PANEL_TITLE = "Agregar a tu video"
FLOW_TABS_LABEL = "Qué agregar"
#: Shown only when no effect loop exists under `assets/effects/` (EF-08 made all three):
#: «+ Efecto» says so and what to do in the meantime, with a button to the «Texto» tab
#: (ED-10 UX review).
NO_EFFECTS_YET = "Todavía no hay efectos para tu video. Mientras tanto, agrega un texto."
NO_EFFECTS_GO_TEXT = "Agregar un texto"

# -- «Fotos y videos» ---------------------------------------------------------------------

#: «Orden de tu video»: the first and the last file (the off-switch keeps «…el clip»).
STRIP_OPENS = "Abre tu video"
STRIP_CLOSES = "Cierra tu video"
#: Under a second video of the order. B6 (m-25048789): it is a stretch of the video that
#: comes out — its first 15 s at most, as the timeline shows it — no longer a guide for
#: the AI's movement.
SECOND_VIDEO_NOTE = "De este video usamos hasta 15 s, como se ve en la línea de tiempo."
#: The tag under the video the editor plays and cuts (other videos stay «Movimiento»).
OWN_VIDEO_TAG = "Tu video"
ORDER_TITLE = "Orden de tu video"
ORDER_HINT = (
    "Arrastra las fotos y los videos para ordenarlos: el primero abre tu video y el último "
    "lo cierra."
)

# -- «Idea» --------------------------------------------------------------------------------

IDEA_HELP = "Esto guía el texto de todo tu video."
#: In the help only, never as a placeholder.
IDEA_EXAMPLE = "Ej.: «Promoción de 2×1 los martes»."

# -- «Efectos» -----------------------------------------------------------------------------

TEXT_TITLE = "Texto sobre el video"
TEXT_EXAMPLE = "Ej.: 2×1 solo este fin de semana"
TEXT_PLACES = {"top": "Arriba", "middle": "En el medio", "bottom": "Abajo"}
TEXT_PLACE_LABEL = "Dónde va el texto"
FREE = "Gratis"
SPEED_TITLE = "Velocidad"
EFFECTS_LIST_LABEL = "Efectos para tu video"


def speed_label(speed: int) -> str:
    return f"×{int(speed)}"


def speed_aria(speed: int) -> str:
    """«Velocidad»'s button name: «5 veces más rápido»."""
    return f"{int(speed)} veces más rápido"


def duration_line(seconds: float) -> str:
    """«Tu video durará {s} s.» (under «Velocidad»)."""
    return f"Tu video durará {contract.seconds_text(seconds)} s."


#: Under 3 s a reel is too short (EF-04 refuses under 3 s).
FAST_MIN_SECONDS = 3.0
#: Past 60 s it is too long (EF-04 `MAX_TOTAL_S`).
FAST_MAX_SECONDS = 60.0
#: «Cámara rápida» proposes the speed whose result is closest to this.
FAST_TARGET_SECONDS = 5.0


def fast_too_short_line(seconds: float) -> str:
    """The warning when «Cámara rápida» leaves less than 3 s."""
    return (
        f"Tu video durará {contract.seconds_text(seconds)} s: muy poco para un reel. "
        "Elige un pedazo más largo o una velocidad menor."
    )


def fast_too_long_line(seconds: float) -> str:
    """The words when «Cámara rápida» leaves more than 60 s (EF-04 refuses past 60 s)."""
    return (
        f"Con esa velocidad tu video duraría {contract.seconds_text(seconds)} s: muy largo "
        "para un reel. Elige una velocidad mayor o corta un pedazo más corto."
    )


#: «Cámara rápida» needs a video of at least this length: what ×2 needs to last 3 s
#: (Deivid 2026-11-17, with ×2 and ×3; it was 15 s while ×5 was the slowest).
FAST_MIN_SOURCE_SECONDS = 6.0
FAST_NEEDS_LONGER = "Para hacerlo más rápido, tu video tiene que durar al menos 6 s."


def speed_result_line(speed: int, seconds: float) -> str:
    """Why a speed is off: «Con ×10 tu video duraría 1,2 s.»."""
    return f"Con ×{int(speed)} tu video duraría {contract.seconds_text(seconds)} s."


def speed_reasons(duration: float, *, known: bool = True) -> dict[str, str]:
    """«Velocidad»'s speeds for the whole video of `duration` s: value → why it is off
    ("" = on). A speed is on only when the video at that speed lasts 3–60 s; under 6 s
    every one is off with `FAST_NEEDS_LONGER`; while the length is not read yet, with
    `CUT_WAITING`. «Normal» (`SPEED_NORMAL`) is always on."""
    reasons = {SPEED_NORMAL: ""}
    end = contract.grid_end(duration) if known and duration > 0 else 0.0
    for speed in contract.FAST_MOTION_SPEEDS:
        if not known or duration <= 0:
            why = CUT_WAITING
        elif duration < FAST_MIN_SOURCE_SECONDS - 1e-6:
            why = FAST_NEEDS_LONGER
        else:
            seconds = end / speed
            fits = FAST_MIN_SECONDS - 1e-6 <= seconds <= FAST_MAX_SECONDS + 1e-6
            why = "" if fits else speed_result_line(speed, seconds)
        reasons[str(speed)] = why
    return reasons


def fast_impossible_line(seconds: float) -> str:
    """Even the whole video at the slowest speed lasts under 3 s: no cut can fix it."""
    return (
        f"Tu video duraría {contract.seconds_text(seconds)} s: muy poco para un reel. "
        "Vuelve a la velocidad normal o usa un video más largo."
    )


def fast_on_line(speed: int, *, had_cut: bool) -> str:
    """The live line when «Cámara rápida» is marked: what it did to the stretch, in the
    words of the control the owner sees («Velocidad», ED-10 UX review)."""
    line = f"Pusiste tu video ×{int(speed)}: usamos todo tu video."
    return f"{line} Si vuelves a la velocidad normal, recuperas tu pedazo." if had_cut else line


def fast_check(*, key: str, start: float, end: float, speed: float) -> tuple[float, str]:
    """«Cámara rápida» judged by the backend's own rule (EF-04 `plan_speed`, pure: no
    file, no PyAV): `(seconds, warning)` — how long the video lasts at that speed, to the
    frame, and the owner's words when it falls outside a reel's 3–60 s
    (`speed_duration_out_of_range`) or cannot be planned (the generic line)."""
    from qualify_creative.video.speed import (  # noqa: PLC0415 — light, pure path only
        SpeedDurationOutOfRange,
        SpeedError,
        SpeedSegment,
        plan_speed,
    )

    try:
        plan = plan_speed([SpeedSegment(key or "preview", float(start), float(end), float(speed))])
    except SpeedDurationOutOfRange as refused:
        seconds = float(refused.duration_s)
        if seconds < FAST_MIN_SECONDS:
            return seconds, fast_too_short_line(seconds)
        return seconds, fast_too_long_line(seconds)
    except SpeedError:
        return 0.0, REFUSAL_GENERIC
    return plan.duration_s, ""


def fast_proposal(duration: float) -> tuple[float, float, int]:
    """Marking «Cámara rápida»: the whole video (no 15 s cap: it is sped up) and, of
    the speeds that are on (`speed_reasons`), the one whose result is closest to 5 s —
    `(start, end, speed)`."""
    end = contract.grid_end(duration)
    reasons = speed_reasons(duration)
    on = [s for s in contract.FAST_MOTION_SPEEDS if not reasons[str(s)]]
    speed = min(
        on or contract.FAST_MOTION_SPEEDS,
        key=lambda s: (abs(end / s - FAST_TARGET_SECONDS), s),
    )
    return 0.0, end, speed


# -- «Cortar» ------------------------------------------------------------------------------

FROM_LABEL = "Desde"
TO_LABEL = "Hasta"
EARLIER = "Medio segundo antes"
LATER = "Medio segundo después"
EARLIER_TEXT = "− ½ s"
LATER_TEXT = "+ ½ s"
ROTATE = "Girar"
ROTATE_LABEL = "Girar el video un cuarto de vuelta"
WHOLE_VIDEO = "Usar el video entero"
FIRST_SECONDS = "Usar los primeros 15 s"


def whole_label(duration: float) -> str:
    """«Usar el video entero», or «Usar los primeros 15 s» past 15 s."""
    return FIRST_SECONDS if duration > contract.DEFAULT_STRETCH_SECONDS else WHOLE_VIDEO


#: Deivid 2026-11-17: ONE button cuts the chosen video where the marker is (no
#: «Desde/Hasta», no «Usar el video entero»): the video becomes two blocks.
CUT = "Cortar"
CUT_LABEL = "Cortar el video donde está el marcador"
CUT_NOT_HERE = "Mueve el marcador dentro de tu video para cortar."
CUT_TOO_CLOSE = "Muy cerca del borde: mueve el marcador al menos 1 s."
CUT_FULL = "Tu video ya tiene todos los cortes que se pueden hacer."
CUT_DONE_LINE = "Cortaste tu video."
PIECE_REMOVED_LINE = "Quitaste un pedazo de tu video."
#: How close to a block's edge the marker may be and still cut it (seconds of the final
#: video); a piece also keeps at least `contract.SEGMENT_MIN_SECONDS` of the source.
CUT_EDGE_SECONDS = 0.5
TOO_SHORT = "El pedazo tiene que durar al menos 1 segundo."
CUT_WAITING = "Espera unos segundos: estamos leyendo cuánto dura tu video."
#: Any refusal code (EF-03 «Preparar», PR #679) with no words of its own.
REFUSAL_GENERIC = "No pudimos usar ese pedazo de tu video. Prueba con otro."
UNREADABLE = "No pudimos leer tu video. Prueba con otro archivo."
#: EF-03's `PrepareRejected.reason` codes (and this screen's `segment_problems` codes) →
#: EF-07's words.
_REFUSAL_TEXTS = {
    "segment_too_short": TOO_SHORT,
    "too_short": TOO_SHORT,
    "ends_before_start": TOO_SHORT,
    "unreadable": UNREADABLE,
    "no_video": UNREADABLE,
}


def refusal_text(code: str) -> str:
    """The owner's words for a stretch's refusal code; the generic line for the rest."""
    return _REFUSAL_TEXTS.get(code, REFUSAL_GENERIC)


LOW_RES_HORIZONTAL = "Si puedes, grábalo en vertical."
LOW_RES_UPLOAD = "Sube el video original desde tu teléfono."


def low_resolution_line(*, horizontal: bool = False) -> str:
    """EF-03's `low_resolution` warning, without pixels (UX review 2026-11-14). The
    advice depends on the video: a horizontal one is cut down to a narrow strip."""
    advice = LOW_RES_HORIZONTAL if horizontal else LOW_RES_UPLOAD
    return f"Al ponerlo vertical, tu video se vería borroso. {advice}"


def prepare_check(
    *,
    key: str,
    start: float,
    end: float,
    rotate: int,
    speed: float,
    width: int,
    height: int,
    duration: float,
) -> tuple[str, str]:
    """«Cortar» judged by the backend's own rule (EF-03 `plan_prepare`, pure: no file, no
    decoding): `(refusal, warning)` in the owner's words, "" each when there is none.
    `width`×`height` is what the browser reports (`videoWidth`/`videoHeight`, already
    upright), so the display rotation passed is 0. Nothing to judge until the browser has
    measured the video. `apply_prepare` / `prepared_frame` decode: never called here
    (EF-06 and the worker)."""
    if width < 2 or height < 2 or duration <= 0 or not key:
        return "", ""
    from qualify_creative.video.prepare import (  # noqa: PLC0415 — light, pure path only
        PrepareRejected,
        PrepareSegment,
        plan_prepare,
    )

    segment = PrepareSegment(
        key=key, start_s=float(start), end_s=float(end), speed=float(speed), rotate=int(rotate)
    )
    try:
        plan = plan_prepare(int(width), int(height), 0, segment, float(duration))
    except PrepareRejected as rejected:
        return refusal_text(str(rejected.reason)), ""
    for warning in plan.warnings:
        if warning.code == "low_resolution":
            # «horizontal» = wider than tall once turned as the owner asked
            turned = int(rotate) % 180 == 90
            upright_w, upright_h = (height, width) if turned else (width, height)
            return "", low_resolution_line(horizontal=upright_w > upright_h)
    return "", ""


def usage_line(seconds: float) -> str:
    """«Usas {s} s de tu video.» — rounded as the chosen block's heading and the
    timeline round it (`timeline_vm.amount`, the ½ s magnet): the same stretch never
    reads «6,5 s» above and «6,6 s» below (Deivid, 2026-11-16)."""
    return f"Usas {timeline_vm.amount(seconds)} s de tu video."


def range_line(start: float, end: float) -> str:
    """«Desde 0:04 · Hasta 0:12»."""
    return f"Desde {contract.clock_text(start)} · Hasta {contract.clock_text(end)}"


def time_of_total(t: float, total: float) -> str:
    """«{t} de {total}» under the preview."""
    return f"{contract.clock_text(t)} de {contract.clock_text(total)}"


# -- «Deshacer» (D-E6) -----------------------------------------------------------------------

#: «Deshacer» has no timer (WCAG 2.2.1): it stays until the next change or until the
#: owner leaves the step.
UNDO = "Deshacer"
#: How many earlier states «Deshacer» can go back (at least one, D-E6).
UNDO_DEPTH = 10

#: What a snapshot holds, and the line each change says — in this order of precedence
#: when one change touches several fields (the stretch's handles move together).
_CHANGE_LINES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("start", "end"), "Cambiaste el pedazo de tu video."),
    (("rotate",), "Giraste tu video."),
    (("effects",), "Cambiaste el efecto de tu video."),
    (("speed",), "Cambiaste la velocidad de tu video."),
    # the place first: choosing it also keeps the text being typed (one line says it)
    (("place",), "Cambiaste el lugar del texto."),
    (("text",), "Cambiaste el texto de tu video."),
)
SNAPSHOT_FIELDS: tuple[str, ...] = tuple(f for fields, _ in _CHANGE_LINES for f in fields)


def snapshot(
    *,
    start: float,
    end: float,
    rotate: int,
    effects: Sequence[str],
    speed: int,
    text: str,
    place: str,
    order: Sequence[str] = (),
    text_start: float = 0.0,
    text_end: float = -1.0,
    effect_times: Mapping[str, Sequence[float]] | None = None,
    pieces: Sequence[Sequence[float]] = (),
) -> dict[str, object]:
    """The editor's choices as one plain value (what «Deshacer» restores exactly).
    ED-10: the order of «Fotos y videos» (`order`, the files' keys) and when the text
    and each effect show (`text_end` -1 = to the end; an effect absent from
    `effect_times` covers the whole video). «Cortar»: the own video's `pieces`
    (`[start, end]` of the source each, in the video's order; empty = one piece, the
    stretch `start`-`end`)."""
    return {
        "start": float(start),
        "end": float(end),
        "rotate": int(rotate),
        "effects": list(effects),
        "speed": int(speed),
        "text": str(text),
        "place": str(place),
        "order": [str(key) for key in order],
        "text_start": float(text_start),
        "text_end": float(text_end),
        "effect_times": {
            str(k): [float(v) for v in times] for k, times in (effect_times or {}).items()
        },
        "pieces": [[float(a), float(b)] for a, b in pieces],
    }


FAST_ON_LINE = "Pusiste tu video más rápido."
FAST_OFF_LINE = "Volviste tu video a la velocidad normal."
#: ED-10: the order changed (the screen says which block, `timeline_vm.moved_text`).
ORDER_LINE = "Cambiaste el orden de tu video."
TEXT_TIME_LINE = "Cambiaste cuándo sale el texto."
TEXT_REMOVED_LINE = "Quitaste el texto de tu video."


def _effect_label(effect_id: str) -> str:
    effect = contract.effect_of(effect_id)
    return effect.label if effect is not None else effect_id


def effect_time_line(effect_id: str) -> str:
    """«Cambiaste cuándo sale Vapor.» (§4)."""
    return f"Cambiaste cuándo sale {_effect_label(effect_id)}."


def effect_removed_line(effect_id: str) -> str:
    """«Quitaste Vapor.» (§4)."""
    return f"Quitaste {_effect_label(effect_id)}."


def change_message(before: Mapping[str, object], after: Mapping[str, object]) -> str:
    """The live line for a change ("" = nothing changed). «Cámara rápida» marked or
    unmarked says so, even though it also moves the stretch and the speed."""
    fast_before = contract.FAST_MOTION in list(before.get("effects") or [])  # type: ignore[call-overload]
    fast_after = contract.FAST_MOTION in list(after.get("effects") or [])  # type: ignore[call-overload]
    if fast_after and not fast_before:
        return FAST_ON_LINE
    if fast_before and not fast_after:
        return FAST_OFF_LINE
    pieces_before = list(before.get("pieces") or [])  # type: ignore[call-overload]
    pieces_after = list(after.get("pieces") or [])  # type: ignore[call-overload]
    if pieces_before != pieces_after:
        # a piece more is a cut; a piece less, one taken out; the same ones, moved
        if len(pieces_after) > len(pieces_before):
            return CUT_DONE_LINE
        if len(pieces_after) < len(pieces_before):
            return PIECE_REMOVED_LINE
        return ORDER_LINE
    for fields, line in _CHANGE_LINES:
        if any(before.get(name) != after.get(name) for name in fields):
            return line
    if before.get("order", []) != after.get("order", []):
        return ORDER_LINE
    if (before.get("text_start", 0.0), before.get("text_end", -1.0)) != (
        after.get("text_start", 0.0),
        after.get("text_end", -1.0),
    ):
        return TEXT_TIME_LINE
    times_before = dict(before.get("effect_times") or {})  # type: ignore[call-overload]
    times_after = dict(after.get("effect_times") or {})  # type: ignore[call-overload]
    for effect_id in sorted(set(times_before) | set(times_after)):
        if times_before.get(effect_id) != times_after.get(effect_id):
            return effect_time_line(effect_id)
    return ""


def push_undo(
    stack: Sequence[Mapping[str, object]], before: Mapping[str, object]
) -> list[dict[str, object]]:
    """The stack with `before` on top, at most `UNDO_DEPTH` deep."""
    return [*(dict(item) for item in stack), dict(before)][-UNDO_DEPTH:]


def pop_undo(
    stack: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """The state to go back to and the stack without it (None = nothing to undo)."""
    if not stack:
        return None, []
    return dict(stack[-1]), [dict(item) for item in stack[:-1]]


# -- which screen and which video ----------------------------------------------------------

#: The Clip's video the editor works on: the owner's (an upload, the catalog, the
#: Galería, a publication), never the reel's original, Pinterest nor — Deivid 2026-11-14 —
#: Inspiración stock, which stays a reference for the AI only (never cut, never a stretch).
#: «stock» (Pixabay's photos and videos) is shown to the owner as «Inspiración» too
#: (`PICKER_TAB_LABELS`, «Video de inspiración»), so `NOT_IN_VIDEO` names it that way.
_NOT_OWN = ("reel", "pinterest", "stock", "inspiration")


#: The sources of a video Qualify itself made (a publication): no low-resolution
#: advice — it never came from the owner's phone.
MADE_HERE = ("pieces",)


def video_source(videos: Sequence[Mapping[str, str]], key: str) -> str:
    """Where the Clip's video `key` was chosen from ("" when it is not there)."""
    for item in videos:
        if item.get("key") == key:
            return str(item.get("source") or "")
    return ""


def own_video(videos: Sequence[Mapping[str, str]]) -> dict[str, str]:
    """The owner's first own video of the Clip ({} = none: only photos)."""
    for item in videos:
        if str(item.get("source") or "") not in _NOT_OWN and item.get("key"):
            return {"key": str(item["key"]), "name": str(item.get("name") or "")}
    return {}


def ai_only(
    images: Sequence[Mapping[str, str]],
    videos: Sequence[Mapping[str, str]],
    audios: Sequence[Mapping[str, str]] = (),
) -> bool:
    """B6 (m-25048789): the Clip holds something only an AI reads — an Inspiración or
    Pinterest image or video (never on the timeline) or a reference audio. The video made
    from the owner's photos and videos has no place for them."""
    foreign = any(
        str(item.get("source") or "") in _NOT_OWN and item.get("key") for item in (*images, *videos)
    )
    return foreign or any(item.get("key") for item in audios)


def editor_shown(
    *,
    category: str,
    kind: str,
    from_reel: bool,
    has_plan: bool,
    reel_video: bool,
    enabled: bool | None = None,
) -> bool:
    """«Arma tu video» replaces «Qué mostrar» on a normal Clip only — with the switch on
    (`CLIP_EDITOR_ON`, read at call time so tests can patch it) — and never on a video by
    parts (a plan on screen), «Hacer uno parecido» or a reel's replica."""
    on = CLIP_EDITOR_ON if enabled is None else enabled
    return (
        on
        and category == "clip"
        and kind == "clip"
        and not from_reel
        and not has_plan
        and not reel_video
    )


def recipe_of(
    *,
    video_key: str,
    start: float,
    end: float,
    rotate: int,
    effects: Sequence[str],
    speed: int,
    text: str,
    place: str,
    text_start: float = 0.0,
    text_end: float | None = None,
    effect_times: Mapping[str, Sequence[float]] | None = None,
    pieces: Sequence[Sequence[float]] = (),
    timeline: Sequence[Mapping[str, object]] | None = None,
) -> contract.PartRecipe:
    """The Clip's recipe of one part, in EF-02's shape. «Cámara rápida»'s speed goes in
    the stretch only (`segments[].speed`): the `camara_rapida` effect never travels — the
    backend makes no such effect (B6 m-25048789: it would refuse the Clip as
    `recipe_unavailable`). An unset stretch is left out.

    ED-10: when the owner moved the text or an effect on the timeline, its seconds of
    the final video (`text_start`/`text_end`, `effect_times[id]` = `[start, end]`);
    untouched, the recipe is exactly ED-02's (the text from 0 with no end, effects with
    no span).

    «Cortar» (Deivid 2026-11-17): the own video cut in `pieces` is one `SourceSegment`
    per piece, in the video's order — the same `key`, each with its own `start_s`/`end_s`
    of the source, all at the video's speed and turn (contract v2 takes up to
    `SEGMENTS_MAX`). Without pieces, the one stretch `start`-`end`.

    B6 (m-25048789): with `timeline` (`timeline_media`'s blocks, what the preview plays)
    the stretches are EVERY block, in its order — the photos as still stretches of their
    seconds (`kind` photo), the own video's pieces at its speed and turn, any other video
    from 0:00 — so the video that comes out is the one the preview shows. The texts' and
    effects' seconds are then kept inside that video's length (as the backend reads it:
    the stretches at their speed, to the hundredth), an end at the end left open."""
    fast = contract.FAST_MOTION in effects and bool(video_key)
    segments: tuple[contract.SourceSegment, ...] = ()
    if timeline is not None:
        segments = timeline_segments(timeline)
    elif video_key:
        stretches = [(float(a), float(b)) for a, b in pieces] or [(float(start), float(end))]
        segments = tuple(
            contract.SourceSegment(
                key=video_key,
                start_s=a,
                end_s=b,
                speed=float(speed) if fast else 1.0,
                rotate=int(rotate),
            )
            for a, b in stretches
            if b > a
        )
    total = recipe_seconds(segments) if timeline is not None else None
    uses: list[contract.EffectUse] = []
    for effect_id in effects:
        effect = contract.effect_of(effect_id)
        if effect is None or effect_id == contract.FAST_MOTION:
            continue
        span = (effect_times or {}).get(effect_id)
        bounds = _inside(span, total) if span and len(span) == 2 else None
        if bounds is not None:
            uses.append(
                contract.EffectUse(effect_id, effect.version, start_s=bounds[0], end_s=bounds[1])
            )
        else:
            uses.append(contract.EffectUse(effect_id, effect.version))
    begin = round(max(float(text_start), 0.0), 2)
    finish = None if text_end is None else round(float(text_end), 2)
    if total is not None:
        top = _floor2(total)
        begin = min(begin, max(top - contract.SEGMENT_MIN_SECONDS, 0.0))
        if finish is not None and finish >= top - 0.01:
            finish = None  # it runs to the end: left open, as ED-02's
    layer = (
        contract.VideoTextLayer(
            text=text.strip(),
            place=place,
            start_s=begin,
            end_s=finish,
            layout_id=contract.TEXT_LAYOUT_ID,
            layout_version=contract.TEXT_LAYOUT_VERSION,
        )
        if text.strip()
        else None
    )
    return contract.PartRecipe(effects=tuple(uses), text_layer=layer, segments=segments)


def _floor2(value: float) -> float:
    """`value` down to the hundredth (a time never past the video's rounded length)."""
    return math.floor(float(value) * 100 + 1e-6) / 100


def _inside(span: Sequence[float], total: float | None) -> tuple[float, float] | None:
    """An effect's `[start, end]` to the hundredth, inside a video of `total` s (None =
    not known: as given). None = no span: it covers the whole video, or nothing is left."""
    start, end = round(float(span[0]), 2), round(float(span[1]), 2)
    if total is not None:
        top = _floor2(total)
        if start <= 0.01 and end >= top - 0.01:
            return None  # the whole video: no span, as ED-02's
        start, end = max(start, 0.0), min(end, top)
    return (start, end) if end > start else None


def timeline_segments(media: Sequence[Mapping[str, object]]) -> tuple[contract.SourceSegment, ...]:
    """B6 (m-25048789): the recipe's stretches from the timeline's blocks
    (`timeline_media`), in their order — a photo is a still stretch (`kind` photo, from 0
    to its seconds, speed 1); a video, its `[src_start, src_end)` of the source at its
    speed and turn. Seconds to the hundredth, as `to_dict` keeps them."""
    out: list[contract.SourceSegment] = []
    for item in media:
        key = str(item.get("key") or "")
        if not key:
            continue
        if item.get("kind") == "photo":
            seconds = round(float(item.get("dur") or 0.0), 2)  # type: ignore[arg-type]
            if seconds > 0:
                out.append(contract.SourceSegment(key, 0.0, seconds, 1.0, 0, "photo"))
            continue
        start = round(float(item.get("src_start") or 0.0), 2)  # type: ignore[arg-type]
        end = round(float(item.get("src_end") or 0.0), 2)  # type: ignore[arg-type]
        speed = float(item.get("speed") or 1.0) or 1.0  # type: ignore[arg-type]
        if end > start:
            out.append(
                contract.SourceSegment(
                    key,
                    start,
                    end,
                    round(speed, 2),
                    int(item.get("rotate") or 0),  # type: ignore[call-overload]
                )
            )
    return tuple(out)


def recipe_seconds(segments: Sequence[contract.SourceSegment]) -> float:
    """How long the video of `segments` lasts, as the backend reads it (EF-06
    `segments_seconds`: each stretch at its speed; a photo its seconds)."""
    return sum((s.end_s - s.start_s) / (s.speed or 1.0) for s in segments)


# -- B6 (m-25048789): what «Crear» needs on «Arma tu video» ----------------------------------

#: EF-06's bounds for a Clip made from the owner's photos and videos (`LOCAL_TOTAL_MIN_S`
#: / `LOCAL_TOTAL_MAX_S` of `qualify_creative.schemas`; a test pins they agree).
LOCAL_MIN_SECONDS = 3.0
LOCAL_MAX_SECONDS = 60.0
#: A text or an effect needs something to go over.
NEEDS_MEDIA = "Para poner un texto o un efecto, primero agrega una foto o un video tuyo."
#: A video whose length the browser has not read: it cannot be cut to the second yet.
LENGTH_UNKNOWN = (
    "No pudimos abrir uno de tus videos y no sabemos cuánto dura. Quítalo o cámbialo por otro."
)
TOO_MANY_PIECES = (
    f"Tu video puede tener hasta {contract.SEGMENTS_MAX} fotos y pedazos de video. Quita alguno."
)
#: What the preview cannot show and the video made here does not take: the AI's
#: references — «Inspiración» (its banks' photos and videos, `stock` too) and Pinterest —
#: and the music (`clip_gallery_vm.AUDIO_TAG`). Said where they are taken out: their
#: tiles, with their ✕, in «Agregar» (`timeline_vm.ADD_LABEL`).
NOT_IN_VIDEO = (
    "Tu video se arma solo con tus fotos y videos. En «Agregar», quita las fotos y videos "
    "de Inspiración o Pinterest y la música para poder crearlo."
)
#: The generation queue is off (`local_unavailable`): only the creative worker builds it.
LOCAL_UNAVAILABLE = (
    "Por ahora no podemos armar tu video. Tus cambios siguen aquí: inténtalo más tarde."
)
#: Any other refusal of the recipe (a bug of ours: the screen only sends what it offers).
RECIPE_REFUSED = (
    "No pudimos crear tu video con esos cambios. Quita el último texto o efecto e "
    "inténtalo de nuevo."
)


def length_out_of_range_line(seconds: float, *, fast: bool = False, video: bool = False) -> str:
    """EF-06 option A (Deivid 2026-11-16, «avisar y no crear»): the video would last under
    3 s or over 60 s — how long, and what to change. Only what the owner can do on the
    screen is offered, in the words of the control (`SPEED_TITLE`, «más rápido»): `fast`,
    a stretch is already faster (lower it when too short, raise it when too long);
    `video`, the timeline holds a video that «Velocidad» could make faster."""
    shown = contract.seconds_text(seconds)
    if seconds < LOCAL_MIN_SECONDS:
        line = f"Tu video dura {shown} s y necesita al menos 3 s. Agrega otra foto o video"
        return f"{line}, o baja la velocidad." if fast else f"{line}."
    line = f"Tu video dura {shown} s y puede durar hasta 60 s. Quita alguna foto o pedazo de video"
    if fast:
        return f"{line}, o sube la velocidad."
    return f"{line}, o hazlo más rápido en «{SPEED_TITLE}»." if video else f"{line}."


def speed_facts(
    segments: Sequence[contract.SourceSegment], *, speed_offered: bool = True
) -> tuple[bool, bool]:
    """`(fast, video)` of a recipe's stretches, for `length_out_of_range_line`: a stretch
    faster than recorded; a video stretch «Velocidad» could make faster — none when no
    speed is on for the own video (`speed_offered` False, e.g. under 6 s)."""
    fast = any(float(s.speed or 1.0) > 1.0 + 1e-6 for s in segments)
    video = speed_offered and any(s.kind != "photo" for s in segments)
    return fast, video


def recipe_problem(
    recipe: contract.PartRecipe,
    *,
    unmeasured: Sequence[str] = (),
    waiting: bool = False,
    not_in_video: bool = False,
    speed_offered: bool = True,
) -> tuple[str, str]:
    """B6 (m-25048789): why «Crear» cannot make the editor's video yet — `(words, tone)`,
    ("", "") when it can. Said in the editor before «Crear» and by «Crear» itself, with
    what the editor already knows: the backend would refuse the same (EF-06).

    `unmeasured`: the timeline's videos whose length the browser has not read (their
    stretch is a guess); `waiting`: …and it is still reading them (`CUT_WAITING`, info),
    else it cannot (`LENGTH_UNKNOWN`). `not_in_video`: the Clip also holds what only an
    AI reads (a reference image, an audio) — it would not come out."""
    has_overlay = bool(recipe.text_layers or recipe.effects)
    if not recipe.segments:
        return (NEEDS_MEDIA, "warn") if has_overlay else ("", "")
    if unmeasured:
        return (CUT_WAITING, "info") if waiting else (LENGTH_UNKNOWN, "warn")
    if len(recipe.segments) > contract.SEGMENTS_MAX:
        return TOO_MANY_PIECES, "warn"
    seconds = recipe_seconds(recipe.segments)
    if not LOCAL_MIN_SECONDS - 1e-6 <= seconds <= LOCAL_MAX_SECONDS + 1e-6:
        fast, video = speed_facts(recipe.segments, speed_offered=speed_offered)
        return length_out_of_range_line(round(seconds, 1), fast=fast, video=video), "warn"
    if not_in_video:
        return NOT_IN_VIDEO, "warn"
    return "", ""


def refusal_line(
    codes: Sequence[str],
    duration_s: float | None = None,
    segments: Sequence[contract.SourceSegment] = (),
    *,
    speed_offered: bool = True,
) -> str:
    """The backend's refusal of the editor's video (`RecipeRefused` codes), in the owner's
    words: the length with its seconds (`local_length_out_of_range`, `duration_s`; what
    to change read from the editor's `segments`), the queue off (`local_unavailable`),
    anything else the generic line."""
    if "local_unavailable" in codes:
        return LOCAL_UNAVAILABLE
    if "local_length_out_of_range" in codes and duration_s is not None:
        fast, video = speed_facts(segments, speed_offered=speed_offered)
        return length_out_of_range_line(float(duration_s), fast=fast, video=video)
    return RECIPE_REFUSED


# -- the timeline (ED-10 m-25026648) ---------------------------------------------------------

#: The address's word for the chosen block (`/create?paso=1&bloque=video-2`, N3).
BLOCK_PARAM = "bloque"
#: How long a photo shows on the timeline (D-T1 = A; 2 s is the hypothesis of §3.1).
PHOTO_SECONDS = 2.0
#: The text's block id (one text today; ED-13 brings up to three).
TEXT_ID = "texto-1"
#: An effect's block id is this plus its library id (`efecto-vapor_capa`).
EFFECT_ID_PREFIX = "efecto-"
#: The chosen block's bar in the editor: only what works on this screen today. «Girar»
#: of a photo and «Duración» (ED-14) come with their tickets; «Cortar» (where the
#: marker is), «Girar» and «Velocidad» of the video are in its panel (one place each).
REMOVE = "Quitar"
EDITOR_ACTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "video": ((REMOVE, "trash-2"),),
    "photo": ((REMOVE, "trash-2"),),
    "text": ((REMOVE, "trash-2"),),
    "effect": ((REMOVE, "trash-2"),),
}
#: «Velocidad» of the editor's video: «Normal» or one of «Cámara rápida»'s speeds.
SPEED_NORMAL = "1"
#: Where the browser's backend origin goes in a preview address: the server does not
#: know the origin the browser sees, so `clip_editor_view` puts `BACKEND_BASE` there.
SEQ_BASE = "__QB__"


#: A piece of the own video after «Cortar» is a block of its own: the first keeps the
#: file's key as its id, the next ones `key#parte-2`, `key#parte-3`… (by position).
PIECE_MARK = "#parte-"


def piece_id(key: str, index: int) -> str:
    """The block id of the own video's piece `index` (0-based)."""
    return key if index <= 0 else f"{key}{PIECE_MARK}{index + 1}"


def piece_of(block_id: str) -> tuple[str, int]:
    """`(file key, piece index)` of a block id (index 0 for any block not a later piece)."""
    key, mark, number = block_id.rpartition(PIECE_MARK)
    if mark and key and number.isdigit() and int(number) >= 2:
        return key, int(number) - 1
    return block_id, 0


def too_close_text(edge: float) -> str:
    """«Muy cerca del borde…» with how far the marker must be from it (`edge`, seconds
    of the final video: 1 s at normal speed, less in «Cámara rápida»)."""
    if edge >= 1.0 - 1e-6:
        return CUT_TOO_CLOSE
    shown = "½" if abs(edge - 0.5) < 1e-6 else f"{edge:.1f}".replace(".", ",")
    return f"Muy cerca del borde: mueve el marcador al menos {shown} s."


def _shown_length(item: Mapping[str, object]) -> float:
    """Seconds a media block lasts in the final video (a video at its speed)."""
    if item.get("kind") == "photo":
        return float(item.get("dur") or 0.0)  # type: ignore[arg-type]
    speed = float(item.get("speed") or 1.0) or 1.0  # type: ignore[arg-type]
    src_start = float(item.get("src_start") or 0.0)  # type: ignore[arg-type]
    src_end = float(item.get("src_end") or 0.0)  # type: ignore[arg-type]
    return max(src_end - src_start, 0.0) / speed


def block_at(media: Sequence[Mapping[str, object]], key: str, playhead: float) -> str:
    """The id of the block of file `key` under the marker at `playhead` ("" = the marker
    is on another file or past the end). On the very line between two blocks it is the
    one that starts there — right after «Cortar», the piece after the cut."""
    at = 0.0
    for item in media:
        length = _shown_length(item)
        if at - 1e-6 <= float(playhead) < at + length - 1e-6:
            return str(item.get("id") or "") if item.get("key") == key else ""
        at += length
    return ""


def split_check(
    media: Sequence[Mapping[str, object]], block_id: str, playhead: float
) -> tuple[float, str]:
    """«Cortar» on the video block `block_id` with the marker at `playhead` (seconds of
    the final video): `(source second to cut at, "")`, or `(0.0, why not)` in the owner's
    words — the marker is not on that video, or it is closer to one of its edges than a
    piece may be (1 s of the source, at least ½ s of the final video): «Muy cerca del
    borde…». The speed is respected: a second of the final video is `speed` seconds of
    the source."""
    at = 0.0
    for item in media:
        speed = float(item.get("speed") or 1.0) or 1.0  # type: ignore[arg-type]
        length = _shown_length(item)
        src_start = float(item.get("src_start") or 0.0)  # type: ignore[arg-type]
        if item.get("id") != block_id:
            at += length
            continue
        if item.get("kind") == "photo":
            return 0.0, CUT_NOT_HERE
        offset = float(playhead) - at
        if offset < -0.01 or offset > length + 0.01:
            return 0.0, CUT_NOT_HERE
        edge = max(CUT_EDGE_SECONDS, contract.SEGMENT_MIN_SECONDS / speed)
        if offset < edge - 1e-6 or length - offset < edge - 1e-6:
            return 0.0, too_close_text(edge)
        return round(src_start + offset * speed, 2), ""
    return 0.0, CUT_NOT_HERE


def is_flow(block: str) -> bool:
    """Whether the panel holds a flow «Agregar» opened (`+media`), not a block."""
    return block.startswith(FLOW_MARK)


def flow_of(block: str) -> str:
    """The flow a `+media` value names ("" = a block or nothing)."""
    name = block[len(FLOW_MARK) :] if is_flow(block) else ""
    return name if name in FLOWS else ""


def timeline_media(
    strip: Sequence[Mapping[str, str]],
    *,
    own_key: str,
    cut_start: float,
    cut_end: float,
    speed: float,
    rotate: int,
    lengths: Mapping[str, float],
    pieces: Sequence[Sequence[float]] = (),
) -> list[dict[str, object]]:
    """«Fotos y videos» on the timeline (`ui.timeline_vm`'s raw media), in the order of
    «Orden de tu video» (`strip`, `CreativeState._clip_strip`), everything already in
    place (E3): a photo shows 2 s; the editor's own video its stretch, at its speed,
    turned; any other video from 0:00, up to 15 s of it (its length once the browser
    measured it, `lengths`). Only the owner's files: a reel, Pinterest or Inspiración
    stays a reference for the AI and is not on the timeline. A block's id is its file's
    key (stable when blocks move). The own video cut with «Cortar» is one block per piece
    (`pieces`, `piece_id`), side by side, each its stretch of the source."""
    media: list[dict[str, object]] = []
    for item in strip:
        key = str(item.get("key") or "")
        if not key or str(item.get("source") or "") in _NOT_OWN:
            continue
        if item.get("kind") == "image":
            media.append({"id": key, "key": key, "kind": "photo", "dur": PHOTO_SECONDS})
            continue
        length = float(lengths.get(key) or 0.0)
        if key == own_key and cut_end > cut_start:
            stretches = [(float(a), float(b)) for a, b in pieces] or [
                (float(cut_start), float(cut_end))
            ]
            for index, (start, end) in enumerate(stretches):
                media.append(
                    {
                        "id": piece_id(key, index),
                        "key": key,
                        "kind": "video",
                        "src_start": start,
                        "src_end": end,
                        "src_len": max(length, end),
                        "speed": float(speed) if speed > 0 else 1.0,
                        "rotate": int(rotate),
                    }
                )
            continue
        default = contract.DEFAULT_STRETCH_SECONDS
        end = min(length, default) if length > 0 else default
        media.append(
            {
                "id": key,
                "key": key,
                "kind": "video",
                "src_start": 0.0,
                "src_end": end,
                "src_len": length or end,
            }
        )
    return media


def media_total(media: Sequence[Mapping[str, object]]) -> float:
    """The video's length on the timeline: the media track has no gaps."""
    total = 0.0
    for item in media:
        if item.get("kind") == "photo":
            total += float(item.get("dur") or 0.0)  # type: ignore[arg-type]
            continue
        start = float(item.get("src_start") or 0.0)  # type: ignore[arg-type]
        end = float(item.get("src_end") or 0.0)  # type: ignore[arg-type]
        speed = float(item.get("speed") or 1.0) or 1.0  # type: ignore[arg-type]
        total += max(end - start, 0.0) / speed
    return total


def _span(start: float, end: float | None, total: float) -> tuple[float, float]:
    """A text's or effect's seconds inside the video (an open end runs to the end; one
    the video no longer reaches is cut to its end, never under 1 s — §3.5)."""
    finish = total if end is None or end < 0 else min(float(end), total)
    begin = min(max(float(start), 0.0), max(finish - contract.SEGMENT_MIN_SECONDS, 0.0))
    return begin, max(finish, begin)


def timeline_overlays(
    *,
    text: str,
    place: str,
    text_start: float,
    text_end: float,
    effects: Sequence[str],
    effect_times: Mapping[str, Sequence[float]],
    total: float,
) -> list[dict[str, object]]:
    """«Textos» and «Efectos» on the timeline (`ui.timeline_vm`'s raw overlays): the
    text (from 0:00 to the end unless the owner moved it) and each layer effect chosen
    («Cámara rápida» is the video's «Velocidad», never a block — D-T3)."""
    rows: list[dict[str, object]] = []
    if text.strip():
        start, end = _span(text_start, None if text_end < 0 else text_end, total)
        rows.append(
            {
                "id": TEXT_ID,
                "kind": "text",
                "label": text.strip(),
                "start": start,
                "end": end,
                "place": place,
            }
        )
    for effect_id in effects:
        effect = contract.effect_of(effect_id)
        if effect is None or not effect.preview_asset:
            continue
        times = list(effect_times.get(effect_id) or [])
        begin, finish = (
            _span(times[0], times[1], total) if len(times) == 2 else _span(0.0, None, total)
        )
        rows.append(
            {
                "id": EFFECT_ID_PREFIX + effect_id,
                "kind": "effect",
                "effect_id": effect_id,
                "label": effect.label,
                "start": begin,
                "end": finish,
            }
        )
    return rows


def block_slug(
    media: Sequence[Mapping[str, object]],
    overlays: Sequence[Mapping[str, object]],
    block_id: str,
) -> str:
    """The address's word for a block (`video-2`, `foto-1`, `texto-1`, `efecto-1`): its
    kind and its number as the owner reads it («Video 2 de 3» is `video-2`)."""
    for n, item in enumerate(media, start=1):
        if item.get("id") == block_id:
            return f"{'foto' if item.get('kind') == 'photo' else 'video'}-{n}"
    counts = {"text": 0, "effect": 0}
    for item in overlays:
        kind = str(item.get("kind"))
        if kind not in counts:
            continue
        counts[kind] += 1
        if item.get("id") == block_id:
            return f"{'texto' if kind == 'text' else 'efecto'}-{counts[kind]}"
    return ""


def block_from_slug(
    media: Sequence[Mapping[str, object]],
    overlays: Sequence[Mapping[str, object]],
    slug: str,
) -> str:
    """The block an address names ("" = none: unknown, or that place is not there)."""
    for item in [*media, *overlays]:
        block_id = str(item.get("id") or "")
        if slug and block_slug(media, overlays, block_id) == slug:
            return block_id
    return ""


def reorder_keys(keys: Sequence[str], shown: Sequence[str]) -> list[str]:
    """`keys` (the whole order of the Clip's files) with the ones on the timeline put in
    the order `shown` gives them; a file the timeline does not show keeps its place."""
    on = set(shown)
    queue = [key for key in shown if key in keys]
    return [queue.pop(0) if key in on and queue else key for key in keys]


def speed_value(*, fast: bool, speed: int) -> str:
    """«Velocidad»'s value: «1» (normal) or the speed of «Cámara rápida»."""
    return str(int(speed)) if fast else SPEED_NORMAL
