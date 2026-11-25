"""«Arma tu video» (ED-02 m-25026621, ED-03 m-25026623, ED-05 m-25026630, ED-10
m-25026648; epic «Video automático con efectos, por pasos»): the words and the pure
rules of the normal Clip's first step as an editor — the preview in sequence on top,
the timeline under it (`ui.timeline`: ruler, playhead, three tracks), its action bar
and the chosen block's panel. One block chosen at a time (`?bloque=video-2`). Nothing
is generated here; every change is kept at once (D-E6, no «Guardar»).

The state (`CreativeState`, «clip editor» block) holds the owner's choices as plain
fields; `snapshot` / `change_message` here decide what the live line says (Deivid
2026-11-19: no «Deshacer» any more), and `recipe_of` turns the fields into the
`editor_preview_contract.PartRecipe` (EF-02's shape) the brief carries.
"""

from __future__ import annotations

import json
import math
import os
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from urllib.parse import quote

from . import clip_gallery_vm
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
    (FLOW_TEXT, "type", "Texto en pantalla"),
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

#: ED-13 (m-25029108, Deivid): the tab and the panel are «Texto en pantalla» (its other
#: words live in `clip_texts_vm`); the track's row still says «Textos».
TEXT_TITLE = "Texto en pantalla"
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


def whole_end(duration: float) -> float:
    """The stretch «Cámara rápida» takes of a video of `duration` s: all of it, on the
    ½ s grid — at most its first minute (A9, m-25042483: a stretch never takes more)."""
    return min(contract.grid_end(duration), SOURCE_MAX_SECONDS)


def speed_reasons(duration: float, *, known: bool = True) -> dict[str, str]:
    """«Cámara rápida»'s speeds for the whole video of `duration` s (its first minute at
    most, `whole_end`): value → why it is off ("" = on). A speed is on only when the
    video at that speed lasts 3–60 s; under 6 s every one is off with
    `FAST_NEEDS_LONGER`; while the length is not read yet, with `CUT_WAITING`. «Normal»
    (`SPEED_NORMAL`) is always on. The panel's «Velocidad» of ONE piece is
    `piece_speed_reasons`."""
    reasons = {SPEED_NORMAL: ""}
    end = whole_end(duration) if known and duration > 0 else 0.0
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


def piece_too_short_line(speed: int, seconds: float) -> str:
    """Why a speed is off for a piece too short for it: «Con ×20 este pedazo duraría
    0,3 s: es muy poco.»."""
    shown = contract.seconds_text(seconds)
    return (
        f"Con ×{int(speed)} este pedazo duraría {shown} s: es muy poco. Alárgalo o elige "
        "una velocidad menor."
    )


def speed_changed_line(n: int, speed: float) -> str:
    """The live line when «Velocidad» changes a piece: «Pusiste el video 2 ×10.» or
    «Volviste el video 2 a la velocidad normal.»."""
    if float(speed) > 1.0 + 1e-6:
        return f"Pusiste el video {int(n)} ×{int(speed)}."
    return f"Volviste el video {int(n)} a la velocidad normal."


def piece_speed_reasons(
    media: Sequence[Mapping[str, object]], block_id: str, *, known: bool = True
) -> dict[str, str]:
    """«Velocidad» of ONE piece (Deivid 2026-11-19, «Por pedazo»): value → why it is off
    ("" = on). A speed is on only when (1) the piece takes at most A9's minute of its
    video (`SOURCE_TOO_LONG` otherwise: no speed fixes it), (2) the WHOLE video — every
    other block as it is, this piece at that speed — lasts 3–60 s (`speed_result_line`),
    and (3) the piece still keeps the least a piece takes at that speed
    (`trim_min_source`: 1 s of its video, ½ s of the final one). «Normal» is always on;
    while the length is not read yet every speed waits (`CUT_WAITING`)."""
    reasons = {SPEED_NORMAL: ""}
    item = next((m for m in media if m.get("id") == block_id and m.get("kind") == "video"), None)
    if not known or item is None:
        for speed in contract.FAST_MOTION_SPEEDS:
            reasons[str(speed)] = CUT_WAITING
        return reasons
    start = float(item.get("src_start") or 0.0)  # type: ignore[arg-type]
    end = float(item.get("src_end") or 0.0)  # type: ignore[arg-type]
    source = max(end - start, 0.0)
    others = media_total(media) - _shown_length(item)
    for speed in contract.FAST_MOTION_SPEEDS:
        total = others + source / speed
        if source_too_long(start, end):
            why = SOURCE_TOO_LONG
        elif not FAST_MIN_SECONDS - 1e-6 <= total <= FAST_MAX_SECONDS + 1e-6:
            why = speed_result_line(speed, total)
        elif source < trim_min_source(speed) - 1e-6:
            why = piece_too_short_line(speed, source / speed)
        else:
            why = ""
        reasons[str(speed)] = why
    return reasons


def piece_speed(piece: Sequence[float], default: float = 1.0) -> float:
    """A stored piece's speed: `[start, end, speed]` (ED-03); an older `[start, end]`
    takes `default` (the one stretch's speed)."""
    speed = float(piece[2]) if len(piece) > 2 else float(default)
    return speed if speed > 0 else 1.0


def fast_impossible_line(seconds: float) -> str:
    """Even the whole video at the slowest speed lasts under 3 s: no cut can fix it."""
    return (
        f"Tu video duraría {contract.seconds_text(seconds)} s: muy poco para un reel. "
        "Vuelve a la velocidad normal o usa un video más largo."
    )


def fast_on_line(speed: int, *, had_cut: bool, capped: bool = False) -> str:
    """The live line when «Cámara rápida» is marked: what it did to the stretch, in the
    words of the control the owner sees («Velocidad», ED-10 UX review). `capped`: the
    video is over a minute, so only its first minute is used (A9)."""
    used = "su primer minuto" if capped else "todo tu video"
    line = f"Pusiste tu video ×{int(speed)}: usamos {used}."
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
    """Marking «Cámara rápida»: the whole video (no 15 s cap: it is sped up; at most its
    first minute, A9 — `whole_end`) and, of the speeds that are on (`speed_reasons`), the
    one whose result is closest to 5 s — `(start, end, speed)`."""
    end = whole_end(duration)
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
#: ED-03: «Cortar» adds a block; the recipe takes `contract.SEGMENTS_MAX` stretches in
#: all (photos, other videos and the own video's pieces): with that many it is off.
#: ED-12 UX review: each place says what is true there and what to do — «Agregar»
#: (`FULL_LINE`), «Cortar» (`CUT_FULL`), «Crear» with too many (`TOO_MANY_PIECES`) —,
#: never the same sentence twice.
_FULL_NOW = f"Tu video ya tiene {contract.SEGMENTS_MAX} fotos o videos."
FULL_LINE = f"{_FULL_NOW} Quita una para agregar otra."
CUT_FULL = f"{_FULL_NOW} Quita una para cortar de nuevo."
#: Fallback lines of `change_message` (the screen says which block: `cut_line`, …).
CUT_DONE_LINE = "Cortaste tu video."
PIECE_REMOVED_LINE = "Quitaste un pedazo de tu video."


#: ED-03 (Deivid 2026-11-19: «lo de los tiradores no lo entendí»): beside the live line
#: while a video with handles is chosen, until the first trim.
TRIM_HINT = "Arrastra las barras de color: hacia adentro recortas, hacia afuera alargas."


def cut_line(n: int) -> str:
    """ED-03: «Cortaste el video {n} en dos.» (`n`: its place on the timeline)."""
    return f"Cortaste el video {int(n)} en dos."


def removed_line(kind: str, n: int) -> str:
    """ED-03: «Quitaste el video {n}.» / «Quitaste la foto {n}.»."""
    noun = "la foto" if kind == "photo" else "el video"
    return f"Quitaste {noun} {int(n)}."


def trim_line(n: int, *, longer: bool) -> str:
    """ED-03: a handle released — «Recortaste el video {n}.» or, when the piece now takes
    more of the video, «Alargaste el video {n}.»."""
    return f"{'Alargaste' if longer else 'Recortaste'} el video {int(n)}."


def fitted_line(names: Sequence[str]) -> str:
    """ED-03 (§3.5): the texts and effects a shorter video cut to its new end, said in the
    live line — «El texto ahora termina con tu video.», «El texto y Vapor ahora terminan
    con tu video.» ("" = none)."""
    shown = [str(name) for name in names if name]
    if not shown:
        return ""
    joined = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " y " + shown[-1]
    verb = "termina" if len(shown) == 1 else "terminan"
    return f"{joined[0].upper()}{joined[1:]} ahora {verb} con tu video."


#: m-25042483 (A9): a video stretch takes at most this much of its source
#: (`qualify_creative.schemas.SEGMENT_SOURCE_MAX_S`; a test pins they agree), whatever
#: its speed — the backend refuses it as `segment_source_too_long`.
SOURCE_MAX_SECONDS = 60.0
#: …with the float noise the backend allows (`recipe._SOURCE_SLACK_S`).
SOURCE_SLACK_SECONDS = 0.03
#: In the video's panel, where a handle stops and before «Crear» (UX review ED-03: the
#: way out is right there, nothing to create again yet).
SOURCE_TOO_LONG = (
    "Cada pedazo puede tomar hasta 1 minuto de tu video, aunque lo aceleres. Acorta el "
    "pedazo más largo o pártelo en dos con «Cortar»."
)
#: A9's own words (`LOCAL_SOURCE_TOO_LONG_TEXT` of `video_pipeline.local`; a test pins
#: they agree), for the backend's refusal after «Crear».
SOURCE_TOO_LONG_REFUSED = (
    "Cada pedazo puede tomar hasta 1 minuto de tu video, aunque lo aceleres. Acorta el "
    "pedazo más largo o pártelo en dos con «Cortar», y vuelve a crear el video."
)


def source_too_long(start: float, end: float) -> bool:
    """A stretch takes more than `SOURCE_MAX_SECONDS` of its video (A9)."""
    return float(end) - float(start) > SOURCE_MAX_SECONDS + SOURCE_SLACK_SECONDS


# -- the trim handles (ED-03 m-25026623) ------------------------------------------------------


def trim_min_source(speed: float) -> float:
    """The least a piece may take of its video: 1 s, and — sped up — at least ½ s of the
    final video (`CUT_EDGE_SECONDS`), as «Cortar» keeps its pieces (`split_check`)."""
    speed = float(speed) if float(speed or 0) > 0 else 1.0
    return max(contract.SEGMENT_MIN_SECONDS, CUT_EDGE_SECONDS * speed)


def trim_bounds(
    *, edge: str, start: float, end: float, length: float, speed: float = 1.0
) -> tuple[float, float]:
    """Where a handle of the piece `[start, end)` (seconds of its video, `length` long) may
    go: `(lowest, highest)` source second. Inside the video's own material (0 … its
    length: lengthening past it is «extend», m-25049586), never a piece under
    `trim_min_source`, never one over `SOURCE_MAX_SECONDS` of source (A9). The same rule
    as `assets/timeline-drag-core.js` `trimBounds`."""
    least = trim_min_source(speed)
    start, end, length = float(start), float(end), max(float(length), float(end))
    if edge == "start":
        low = max(0.0, end - SOURCE_MAX_SECONDS)
        return round(low, 2), round(max(end - least, low), 2)
    high = min(length, start + SOURCE_MAX_SECONDS)
    return round(min(start + least, high), 2), round(high, 2)


def trim_value(value: float, bounds: tuple[float, float]) -> float:
    """A handle's new source second, to the hundredth, inside `bounds`."""
    low, high = bounds
    return round(min(max(float(value), low), high), 2)


def too_short_text(speed: float) -> str:
    """Why a handle stops before the piece gets too short: «El pedazo tiene que durar al
    menos 1 segundo.», or — sped up — «…al menos ½ s.» (of the final video)."""
    shown = trim_min_source(speed) / (float(speed) if float(speed or 0) > 0 else 1.0)
    if shown >= 1.0 - 1e-6:
        return TOO_SHORT
    text = "½" if abs(shown - 0.5) < 1e-6 else f"{shown:.1f}".replace(".", ",")
    return f"El pedazo tiene que durar al menos {text} s."


#: How close to a block's edge the marker may be and still cut it (seconds of the final
#: video); a piece also keeps at least `contract.SEGMENT_MIN_SECONDS` of the source.
CUT_EDGE_SECONDS = 0.5
TOO_SHORT = "El pedazo tiene que durar al menos 1 s."
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


# -- the live line (D-E6; no «Deshacer» since Deivid 2026-11-19) ---------------------------

#: What a snapshot holds, and the line each change says — in this order of precedence
#: when one change touches several fields (the stretch's handles move together).
_CHANGE_LINES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("start", "end"), "Cambiaste el pedazo de tu video."),
    (("rotate",), "Giraste tu video."),
    (("effects",), "Cambiaste el efecto de tu video."),
    (("speed",), "Cambiaste la velocidad de tu video."),
)
SNAPSHOT_FIELDS: tuple[str, ...] = tuple(f for fields, _ in _CHANGE_LINES for f in fields)


def _text_snap(use: Mapping[str, object]) -> dict[str, object]:
    """One written text as a snapshot keeps it (its seconds as resolved now)."""
    return {
        "uid": str(use.get("uid") or ""),
        "text": str(use.get("text") or "").strip(),
        "place": str(use.get("place") or ""),
        "start": round(float(use.get("start") or 0.0), 2),  # type: ignore[arg-type]
        "end": round(float(use.get("end") or 0.0), 2),  # type: ignore[arg-type]
        "fade": round(float(use.get("fade") or 0.0), 1),  # type: ignore[arg-type]
        # ED-13 C/D: its background and how it enters and leaves
        "layout": str(use.get("layout") or ""),
        "motion_in": str(use.get("motion_in") or ""),
        "motion_out": str(use.get("motion_out") or ""),
    }


def snapshot(
    *,
    start: float,
    end: float,
    rotate: int,
    effects: Sequence[str],
    speed: int,
    order: Sequence[str] = (),
    texts: Sequence[Mapping[str, object]] = (),
    pieces: Sequence[Sequence[float]] = (),
) -> dict[str, object]:
    """The editor's choices as one plain value: two of them, before and after a change,
    give the live line (`change_message`). ED-10: the order of «Fotos y videos»
    (`order`, the files' keys); ED-13 (m-25029108): the written texts (`texts`, the
    `clip_texts_vm` uses at their seconds now — one being typed and still empty is not a
    text yet); the effects' own lines are said where they change (ED-04). «Cortar»: the
    own video's `pieces` (`[start, end, speed]` of the source each, in the video's order;
    empty = one piece, the stretch `start`-`end`)."""
    return {
        "start": float(start),
        "end": float(end),
        "rotate": int(rotate),
        "effects": list(effects),
        "speed": int(speed),
        "order": [str(key) for key in order],
        "texts": [_text_snap(use) for use in texts if str(use.get("text") or "").strip()],
        # `[start, end, speed]` each (ED-03: the speed is the piece's own)
        "pieces": [[float(x) for x in piece] for piece in pieces],
    }


FAST_ON_LINE = "Pusiste tu video más rápido."
FAST_OFF_LINE = "Volviste tu video a la velocidad normal."
#: ED-10: the order changed (the screen says which block, `timeline_vm.moved_text`).
ORDER_LINE = "Cambiaste el orden de tu video."
#: ED-13: the texts' lines (`_texts_line`).
TEXT_PUT_LINE = "Pusiste un texto."
TEXT_REMOVED_LINE = "Quitaste un texto de tu video."
TEXT_CHANGED_LINE = "Cambiaste el texto de tu video."
TEXT_PLACE_LINE = "Cambiaste el lugar del texto."
TEXT_FADE_LINE = "Cambiaste cuánto tarda en entrar y salir el texto."
TEXT_TIME_LINE = "Cambiaste cuándo sale el texto."
#: ED-13 C/D (Deivid 2026-11-23): its background, and how it enters and leaves.
TEXT_LAYOUT_LINE = "Cambiaste el fondo de las letras."
TEXT_MOTION_LINE = "Cambiaste cómo entra y sale el texto."


def _texts_line(before: Sequence[object], after: Sequence[object]) -> str:
    """The live line for the written texts ("" = they did not change): one more is put,
    one less is taken out; else the first text that changed says what — its place (a
    place chosen while typing keeps the words too: one line says it), its words, its
    fade, its seconds."""
    was = [dict(t) for t in before if isinstance(t, Mapping)]
    now = [dict(t) for t in after if isinstance(t, Mapping)]
    if len(now) > len(was):
        return TEXT_PUT_LINE
    if len(now) < len(was):
        return TEXT_REMOVED_LINE
    old = {str(t.get("uid")): t for t in was}
    for text in now:
        prior = old.get(str(text.get("uid")))
        if prior is None or prior == text:
            continue
        for field, line in (
            ("place", TEXT_PLACE_LINE),
            ("text", TEXT_CHANGED_LINE),
            ("fade", TEXT_FADE_LINE),
            ("layout", TEXT_LAYOUT_LINE),
            ("motion_in", TEXT_MOTION_LINE),
            ("motion_out", TEXT_MOTION_LINE),
        ):
            if prior.get(field) != text.get(field):
                return line
        return TEXT_TIME_LINE
    return ""


def _effect_label(effect_id: str) -> str:
    effect = contract.effect_of(effect_id)
    return effect.label if effect is not None else effect_id


def effect_label(effect_id: str) -> str:
    """An effect's name as the owner reads it («Vapor»; its id when unknown)."""
    return _effect_label(effect_id)


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
    return _texts_line(
        list(before.get("texts") or []),  # type: ignore[call-overload]
        list(after.get("texts") or []),  # type: ignore[call-overload]
    )


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
    text: str = "",
    place: str = "bottom",
    text_start: float = 0.0,
    text_end: float | None = None,
    pieces: Sequence[Sequence[float]] = (),
    timeline: Sequence[Mapping[str, object]] | None = None,
    effect_uses: Sequence[Mapping[str, object]] = (),
) -> contract.PartRecipe:
    """The Clip's recipe of one part, in EF-02's shape. «Cámara rápida»'s speed goes in
    the stretch only (`segments[].speed`): the `camara_rapida` effect never travels — the
    backend makes no such effect (B6 m-25048789: it would refuse the Clip as
    `recipe_unavailable`). An unset stretch is left out.

    ED-10: ONE text (`text`, `place`, its seconds `text_start`/`text_end`); untouched,
    the recipe is exactly ED-02's (the text from 0 with no end). ED-13 (m-25029108): the
    editor gives no text here — its up to 3 texts go on with
    `clip_texts_vm.with_texts(recipe_of(...), text_layers_for_recipe(...))`, which a test
    pins equal to this one text over the whole video.

    «Cortar» (Deivid 2026-11-17): the own video cut in `pieces` is one `SourceSegment`
    per piece, in the video's order — the same `key`, each with its own `start_s`/`end_s`
    of the source and its own speed (ED-03, «Por pedazo»), at the video's turn (contract v2
    takes up to `SEGMENTS_MAX`). Without pieces, the one stretch `start`-`end`.

    B6 (m-25048789): with `timeline` (`timeline_media`'s blocks, what the preview plays)
    the stretches are EVERY block, in its order — the photos as still stretches of their
    seconds (`kind` photo), the own video's pieces at its speed and turn, any other video
    from 0:00 — so the video that comes out is the one the preview shows. The texts' and
    effects' seconds are then kept inside that video's length (as the backend reads it:
    the stretches at their speed, to the hundredth), an end at the end left open.

    ED-04 (m-25026627): `effect_uses` (`resolve_effect_uses`) are one `EffectUse` each,
    at their seconds, in time order — the same effect as many times as the owner put it.
    Their row on the screen never travels: the local build lays every use over the video
    whatever row it sat on."""
    fast = contract.FAST_MOTION in effects and bool(video_key)
    segments: tuple[contract.SourceSegment, ...] = ()
    if timeline is not None:
        segments = timeline_segments(timeline)
    elif video_key:
        default = float(speed) if fast else 1.0
        stretches = [(float(p[0]), float(p[1]), piece_speed(p, default)) for p in pieces] or [
            (float(start), float(end), default)
        ]
        segments = tuple(
            contract.SourceSegment(
                key=video_key,
                start_s=a,
                end_s=b,
                speed=round(v, 2),
                rotate=int(rotate),
            )
            for a, b, v in stretches
            if b > a
        )
    total = recipe_seconds(segments) if timeline is not None else None
    uses: list[contract.EffectUse] = []
    for use in sorted(
        effect_uses,
        key=lambda u: (float(u.get("start") or 0.0), int(u.get("lane") or 0)),  # type: ignore[arg-type, call-overload]
    ):
        effect = contract.effect_of(str(use.get("effect_id") or ""))
        if effect is None or not effect.preview_asset:
            continue
        start = max(round(float(use.get("start") or 0.0), 2), 0.0)  # type: ignore[arg-type]
        end = round(float(use.get("end") or 0.0), 2)  # type: ignore[arg-type]
        if total is not None:
            end = min(end, _floor2(total))
        if end <= start:
            continue  # nothing of it is left inside the video
        bounds = _inside((start, end), total)
        uses.append(
            contract.EffectUse(effect.effect_id, effect.version, start_s=bounds[0], end_s=bounds[1])
            if bounds is not None
            else contract.EffectUse(effect.effect_id, effect.version)
        )
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
            try:
                turn = int(item.get("rotate") or 0)  # type: ignore[call-overload]
            except (TypeError, ValueError):
                turn = 0
            if turn not in contract.ROTATIONS:
                turn = 0  # ED-14: only a quarter turn travels; anything else is upright
            if seconds > 0:
                out.append(contract.SourceSegment(key, 0.0, seconds, 1.0, turn, "photo"))
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
    f"Tu video tiene más de {contract.SEGMENTS_MAX} fotos o videos. Quita una para poder crearlo."
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
    texts_line: str = "",
) -> tuple[str, str]:
    """B6 (m-25048789): why «Crear» cannot make the editor's video yet — `(words, tone)`,
    ("", "") when it can. Said in the editor before «Crear» and by «Crear» itself, with
    what the editor already knows: the backend would refuse the same (EF-06).

    `unmeasured`: the timeline's videos whose length the browser has not read (their
    stretch is a guess); `waiting`: …and it is still reading them (`CUT_WAITING`, info),
    else it cannot (`LENGTH_UNKNOWN`). `not_in_video`: the Clip also holds what only an
    AI reads (a reference image, an audio) — it would not come out. `texts_line`: what
    stops the texts (ED-13, `clip_texts_vm.texts_problem`: two in one place at once, or
    more than 3) — it stops «Siguiente» too."""
    has_overlay = bool(recipe.text_layers or recipe.effects)
    if not recipe.segments:
        return (NEEDS_MEDIA, "warn") if has_overlay else ("", "")
    if unmeasured:
        return (CUT_WAITING, "info") if waiting else (LENGTH_UNKNOWN, "warn")
    if len(recipe.segments) > contract.SEGMENTS_MAX:
        return TOO_MANY_PIECES, "warn"
    if any(s.kind != "photo" and source_too_long(s.start_s, s.end_s) for s in recipe.segments):
        return SOURCE_TOO_LONG, "warn"  # A9 (m-25042483): the backend would refuse it
    seconds = recipe_seconds(recipe.segments)
    if not LOCAL_MIN_SECONDS - 1e-6 <= seconds <= LOCAL_MAX_SECONDS + 1e-6:
        fast, video = speed_facts(recipe.segments, speed_offered=speed_offered)
        return length_out_of_range_line(round(seconds, 1), fast=fast, video=video), "warn"
    effects_line = effects_problem(recipe.effects)
    if effects_line:
        return effects_line, "warn"
    if texts_line:
        return texts_line, "warn"
    if not_in_video:
        return NOT_IN_VIDEO, "warn"
    return "", ""


def effects_problem(uses: Sequence[contract.EffectUse]) -> str:
    """ED-04: what the backend would refuse in the effects ("" = nothing) — more than
    `EFFECTS_MAX`, one effect more times than the library lets it repeat, or one effect
    twice at the same time. The screen never puts them so; a block moved under an effect
    that is stuck to it can leave them so (`follow_media`)."""
    problems = contract.recipe_problems(contract.PartRecipe(effects=tuple(uses)))
    if "too_many_effects" in problems:
        return too_many_effects_line(len(uses))
    counts: dict[str, int] = {}
    for use in uses:
        counts[use.effect_id] = counts.get(use.effect_id, 0) + 1
    for effect_id, count in counts.items():
        if count > effect_max_uses(effect_id):
            return effect_repeat_over_line(
                _effect_label(effect_id), count, effect_max_uses(effect_id)
            )
    if "effect_uses_overlap" in problems:
        return EFFECT_TWICE_LINE
    return ""


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
    a stretch over 1 minute of its video (`segment_source_too_long`, A9's words), a text
    «Abajo» under the subtitles (ED-13, `text_bottom_with_subtitles`: the screen's own
    words, `clip_texts_vm.SUBTITLES_BOTTOM_LINE`), a text's motion the server does not
    know or «Letra por letra» over 40 characters (ED-13, `unknown_text_motion`,
    `typewriter_text_too_long`), a text's background colour it refused (ED-13,
    `bad_text_box_color`) or its letters' colour (round 3, `bad_text_color`), anything else
    the generic line."""
    from . import clip_texts_vm  # noqa: PLC0415 — it imports this module

    if "local_unavailable" in codes:
        return LOCAL_UNAVAILABLE
    if clip_texts_vm.SUBTITLES_CODE in codes:
        return clip_texts_vm.SUBTITLES_BOTTOM_LINE
    # ED-13: how a text enters and leaves
    if clip_texts_vm.TYPEWRITER_CODE in codes:
        return clip_texts_vm.TYPEWRITER_TOO_LONG_LINE
    if clip_texts_vm.MOTION_CODE in codes:
        return clip_texts_vm.MOTION_REFUSED_LINE
    if clip_texts_vm.BOX_COLOR_CODE in codes:
        return clip_texts_vm.BOX_COLOR_REFUSED_LINE
    if clip_texts_vm.TEXT_COLOR_CODE in codes:  # round 3: «Sin fondo»'s letters
        return clip_texts_vm.TEXT_COLOR_REFUSED_LINE
    if clip_texts_vm.LARGE_CODE in codes:  # round 4: «Grande» on a long text
        return clip_texts_vm.LARGE_REFUSED_LINE
    if clip_texts_vm.SIZE_CODE in codes:  # round 4: a size that is not one of the three
        return clip_texts_vm.SIZE_REFUSED_LINE
    if "segment_source_too_long" in codes:
        return SOURCE_TOO_LONG_REFUSED
    if "local_length_out_of_range" in codes and duration_s is not None:
        fast, video = speed_facts(segments, speed_offered=speed_offered)
        return length_out_of_range_line(float(duration_s), fast=fast, video=video)
    return RECIPE_REFUSED


# -- the timeline (ED-10 m-25026648) ---------------------------------------------------------

#: The address's word for the chosen block (`/create?paso=1&bloque=video-2`, N3).
BLOCK_PARAM = "bloque"
#: How long a photo shows on the timeline (D-T1 = A; 2 s is the hypothesis of §3.1).
PHOTO_SECONDS = 2.0
#: An effect's block id is this plus its library id (`efecto-vapor_capa`).
EFFECT_ID_PREFIX = "efecto-"
#: The chosen block's bar in the editor: only what works on this screen today. A photo's
#: bar is «Girar · Quitar» (ED-14); its seconds change only by dragging its end handle
#: (Deivid 2026-11-20: no «Duración» in the bar; 2026-11-24: no «− ½ s / + ½ s»). «Cortar» (where
#: the marker is), «Girar» and «Velocidad» of the video are in its panel (one place each).
#: ED-13: a text's bar is «Editar texto» (to its field) · «Quitar».
REMOVE = "Quitar"
TEXT_EDIT = "Editar texto"
EDITOR_ACTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "video": ((REMOVE, "trash-2"),),
    "photo": ((ROTATE, "rotate-cw"), (REMOVE, "trash-2")),
    "text": ((TEXT_EDIT, "pencil"), (REMOVE, "trash-2")),
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


# -- ED-12 m-25029107: media put in at a place of the timeline ------------------------------

#: ED-12 UX review S7: the editor's live line said again with the same words ends in
#: this thin space (or loses it), so the `role=status` changes and is read once more.
SAY_AGAIN = "\u2009"
#: A file dropped on the timeline that is neither a photo nor a video (criterion 4).
BAD_FILE_LINE = "Ese archivo no es una foto ni un video. Prueba con otro."
#: What the timeline takes from the computer: the Clip's «Subir» photos and videos
#: (`content_generator._CLIP_IMAGE_ACCEPT` / `_CLIP_VIDEO_ACCEPT`), up to 200 MB each.
TIMELINE_UPLOAD_ID = "clip_timeline_drop"
TIMELINE_ACCEPT: dict[str, list[str]] = {
    "image/*": [".png", ".jpg", ".jpeg", ".webp"],
    "video/mp4": [".mp4"],
    "video/quicktime": [".mov"],
}
TIMELINE_MAX_BYTES = clip_gallery_vm.MAX_MB * 1024 * 1024


def timeline_full(media: Sequence[Mapping[str, object]]) -> bool:
    """The timeline holds `contract.SEGMENTS_MAX` blocks: nothing more goes in."""
    return len(media) >= contract.SEGMENTS_MAX


def media_room(media: Sequence[Mapping[str, object]]) -> int:
    """How many more photos or videos the timeline takes."""
    return max(contract.SEGMENTS_MAX - len(media), 0)


def keep_within_cap(
    fresh: Sequence[str], media: Sequence[Mapping[str, object]]
) -> tuple[list[str], list[str]]:
    """Which of the `fresh` files (in the order they were chosen) stay so the timeline
    (`media`, with them already in) holds at most `contract.SEGMENTS_MAX` blocks: the
    first ones, while they fit; the rest, from the end of what was chosen, do not go in.
    A block is what the timeline shows — the own video cut with «Cortar» counts one per
    piece —, so a fresh file the timeline does not show (a reference for the AI only)
    neither counts nor is left out. Returns (kept, left out)."""
    new = set(fresh)
    blocks: dict[str, int] = {}
    for item in media:
        key = str(item.get("key") or "")
        blocks[key] = blocks.get(key, 0) + 1
    used = sum(n for key, n in blocks.items() if key not in new)
    kept: list[str] = []
    out: list[str] = []
    for key in dict.fromkeys(fresh):
        count = blocks.get(key, 0)
        if not count:
            continue
        if used + count <= contract.SEGMENTS_MAX:
            used += count
            kept.append(key)
        else:
            out.append(key)
    return kept, out


def _what(left_out: Sequence[str]) -> str:
    """«la foto» / «las fotos» / «el video» / «los videos» / «las fotos ni los videos»."""
    kinds = set(left_out)
    one = len(left_out) == 1
    if kinds == {"photo"}:
        return "la foto" if one else "las fotos"
    if kinds == {"video"}:
        return "el video" if one else "los videos"
    return "las fotos ni los videos"


def cap_line(added: int, left_out: Sequence[str], *, full: bool = False) -> str:
    """The live line when the timeline's 8 photos or videos left some of what was chosen
    out (`left_out`: each one's kind, «photo» or «video»; ED-12 UX review S2):
    «Agregamos 1 de 2. La última foto no entró: tu video puede tener hasta 8 fotos o
    videos.» — «La última foto» / «Las últimas 2 fotos» / «El último video» / «Los
    últimos 2 videos» agree with what did not go in; photos and videos mixed say only
    how many («Los últimos 3 no entraron…»). Nothing added: «No agregamos la foto: tu
    video ya tiene 8 fotos o videos. Quita una para agregar otra.» — that only when the
    timeline is really `full`; else «No agregamos la foto: tu video puede tener hasta 8
    fotos o videos.» "" when nothing was left out."""
    out = len(left_out)
    if out <= 0:
        return ""
    cap = contract.SEGMENTS_MAX
    limit = f"tu video puede tener hasta {cap} fotos o videos."
    if added <= 0:
        why = (
            f"tu video ya tiene {cap} fotos o videos. Quita una para agregar otra."
            if full
            else limit
        )
        return f"No agregamos {_what(left_out)}: {why}"
    kinds = set(left_out)
    if kinds == {"photo"}:
        rest = "La última foto no entró" if out == 1 else f"Las últimas {out} fotos no entraron"
    elif kinds == {"video"}:
        rest = "El último video no entró" if out == 1 else f"Los últimos {out} videos no entraron"
    else:
        rest = f"Los últimos {out} no entraron"
    return f"Agregamos {added} de {added + out}. {rest}: {limit}"


def video_cap_line(count: int, *, most: int) -> str:
    """ED-12 UX review S1: the Clip's own limit of `most` videos refused `count` videos
    of one drop (those the 8 photos or videos left out are summed in: one sentence that
    is true): «No agregamos los 2 videos: ya tienes 3 videos, el máximo. Quita uno para
    agregar otro.» "" for none."""
    if count <= 0:
        return ""
    what = "el video" if count == 1 else f"los {count} videos"
    return f"No agregamos {what}: ya tienes {most} videos, el máximo. Quita uno para agregar otro."


def index_after_playhead(media: Sequence[Mapping[str, object]], playhead: float) -> int:
    """Where «+ Foto o video» puts what is chosen (criterion: «después del bloque que está
    bajo el cabezal»): the place right after the block under the marker — on the line
    between two blocks, after the one that starts there (as `block_at`); past the end or
    on an empty timeline, at the end."""
    at = 0.0
    for index, item in enumerate(media):
        length = _shown_length(item)
        if at - 1e-6 <= float(playhead) < at + length - 1e-6:
            return index + 1
        at += length
    return len(media)


def block_start(media: Sequence[Mapping[str, object]], index: int) -> float:
    """The second of the final video block `index` starts at (the end past the last)."""
    return round(sum(_shown_length(item) for item in list(media)[: max(int(index), 0)]), 2)


def insert_order(
    keys: Sequence[str],
    media: Sequence[Mapping[str, object]],
    fresh: Sequence[str],
    index: int,
) -> list[str]:
    """The Clip's whole order of files (`keys`, the `fresh` ones among them, wherever
    `CreativeState._clip_strip` put them) with the `fresh` files that are blocks of the
    timeline (`media`, `timeline_media`) put at block `index` of the timeline as it was
    without them, in the order given. Never between two pieces of the same video
    (`Cortar`'s pieces stay side by side, as `_clip_move_media` keeps them): such an
    index goes after the last piece. A file the timeline does not show keeps its place."""
    new = set(fresh)
    blocks = [str(item.get("key") or "") for item in media if str(item.get("key")) not in new]
    on = {str(item.get("key") or "") for item in media}
    at = min(max(int(index), 0), len(blocks))
    while 0 < at < len(blocks) and blocks[at - 1] == blocks[at]:
        at += 1
    going = [key for key in fresh if key in on]
    shown = list(dict.fromkeys([*blocks[:at], *going, *blocks[at:]]))
    return reorder_keys(list(keys), shown)


def added_line(media: Sequence[Mapping[str, object]], spots: Sequence[int]) -> str:
    """The live line once files went in (§4): one — «Agregaste la foto 2.» / «Agregaste
    el video 2.» (its place) —, several — «Agregaste 3 fotos o videos.» ("" = none)."""
    places = [i for i in spots if 0 <= i < len(media)]
    if not places:
        return ""
    if len(places) == 1:
        noun = "la foto" if media[places[0]].get("kind") == "photo" else "el video"
        return f"Agregaste {noun} {places[0] + 1}."
    return f"Agregaste {len(places)} fotos o videos."


def timeline_rejected_line(rejected: Sequence[object] | None) -> str:
    """What the timeline's drop refused in the browser (react-dropzone's
    `fileRejections`): a file of another type says `BAD_FILE_LINE` (criterion 4); one over
    the size cap, the Clip's own size note (`clip_gallery_vm.rejected_text`)."""
    too_big: list[object] = []
    other = False
    for row in rejected or ():
        errors = row.get("errors", []) if isinstance(row, dict) else []
        codes = {str(e.get("code", "")) for e in errors or () if isinstance(e, dict)}
        if "file-too-large" in codes:
            too_big.append(row)
        else:
            other = True
    notes = [BAD_FILE_LINE] if other else []
    if too_big:
        notes.append(clip_gallery_vm.rejected_text(too_big, clip_gallery_vm.VIDEO))
    return " ".join(note for note in notes if note)


def jump_script(seconds: float) -> str:
    """The preview in sequence goes to `seconds` (criterion: «la vista previa salta
    ahí»), once the timeline re-rendered with what went in (`assets/edit-preview.js`
    `seq.goTo`)."""
    return (
        "window.setTimeout(function () {"
        " var h = document.querySelector('[data-edit-sync] [data-edit-seq-host]');"
        " var p = window.__qEditPreview;"
        f" if (h && p && p.seq) p.seq.goTo(h, {max(float(seconds), 0.0):.2f}); }}, 150)"
    )


def reveal_new_script(block_id: str) -> str:
    """m-25114465 (UX review): the tracks scroll sideways to a text or effect just added,
    once its block is drawn (`assets/timeline-drag.js` `__qTimelineRevealNew`; up and
    down stays `__qTimeline.reveal`'s)."""
    return f"window.__qTimelineRevealNew && window.__qTimelineRevealNew({json.dumps(block_id)})"


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
            default = float(speed) if speed > 0 else 1.0
            stretches = [(float(p[0]), float(p[1]), piece_speed(p, default)) for p in pieces] or [
                (float(cut_start), float(cut_end), default)
            ]
            for index, (start, end, piece_rate) in enumerate(stretches):
                media.append(
                    {
                        "id": piece_id(key, index),
                        "key": key,
                        "kind": "video",
                        "src_start": start,
                        "src_end": end,
                        "src_len": max(length, end),
                        "speed": piece_rate,
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


#: Where the backend serves an owner's upload (the strip's `rx.get_upload_url`).
UPLOAD_ROUTE = "/_upload/"


def upload_path(key: str) -> str:
    """The upload route's path for `key`, encoded (`/_upload/<key>`): the same address for
    a block's picture (`block_thumbs`) and the preview in sequence (`_clip_seq_sources`)."""
    return UPLOAD_ROUTE + quote(key, safe="/")


def block_thumbs(
    strip: Sequence[Mapping[str, str]],
    *,
    views: Mapping[str, str],
    posters: Mapping[str, str],
    is_served: Callable[[str], bool],
) -> dict[str, str]:
    """ED-11 (m-25026650): the picture each file's blocks show on «Fotos y videos» — a
    backend path (`clip_editor_view` puts the browser's backend origin before it), "" =
    none: the block shows the film / photo icon and its name. Only pictures the screen
    already holds (D-T4: no new frame from the server, none drawn in the browser):

    - a publication or a stock file: its `/r2media` view (`views`, `piece_views`) — a
      video's is its poster, the one the preview shows;
    - a Galería video: the poster its tile showed when it was added (`posters`);
    - any other photo: the file itself through the upload route when it serves the key
      (`is_served`: a local key, an owner upload `t/{tenant}/uploads/…` — every upload
      since CM-9 and every photo the Galería copied — or an old catalog key
      `uploads/{tenant}/catalog/…`) — never another R2 key without a view, which cannot
      be read;
    - an uploaded or catalog video has no picture yet (ED-11b brings its frames).

    Every block of a file shares its picture: the own video's pieces after «Cortar»,
    trimmed or sped up, show the same one."""
    out: dict[str, str] = {}
    for item in strip:
        key = str(item.get("key") or "")
        if not key:
            continue
        view = str(views.get(key) or posters.get(key) or "")
        if view:
            out[key] = view
        elif item.get("kind") == "image" and is_served(key):
            out[key] = upload_path(key)
        else:
            out[key] = ""
    return out


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
    """An effect's seconds inside the video (an open end runs to the end; one the video
    no longer reaches is cut to its end, never under 1 s — §3.5)."""
    finish = total if end is None or end < 0 else min(float(end), total)
    begin = min(max(float(start), 0.0), max(finish - contract.SEGMENT_MIN_SECONDS, 0.0))
    return begin, max(finish, begin)


def timeline_overlays(
    *,
    texts: Sequence[Mapping[str, object]] = (),
    effect_uses: Sequence[Mapping[str, object]] = (),
) -> list[dict[str, object]]:
    """«Textos» and «Efectos» on the timeline (`ui.timeline_vm`'s raw overlays), the
    texts first: ED-13 (m-25029108) `texts` are `clip_texts_vm.timeline_text_overlays`
    (up to 3, at their seconds, in time order) and, ED-04 (m-25026627), the effects as
    blocks (`resolve_effect_uses`: already at their seconds), one block each — the same
    effect may be there several times — on its row (`lane`), with its preview opacity.
    «Cámara rápida» is the video's «Velocidad», never a block (D-T3)."""
    rows: list[dict[str, object]] = [dict(text) for text in texts]
    ordered = sorted(
        effect_uses,
        key=lambda u: (int(u.get("lane") or 0), float(u.get("start") or 0)),  # type: ignore[call-overload, arg-type]
    )
    for use in ordered:
        effect_id = str(use.get("effect_id") or "")
        effect = contract.effect_of(effect_id)
        if effect is None or not effect.preview_asset:
            continue
        rows.append(
            {
                "id": effect_block_id(str(use.get("uid") or "")),
                "kind": "effect",
                "effect_id": effect_id,
                "uid": str(use.get("uid") or ""),
                "label": effect.label,
                "start": float(use.get("start") or 0.0),  # type: ignore[arg-type]
                "end": float(use.get("end") or 0.0),  # type: ignore[arg-type]
                "lane": int(use.get("lane") or 0),  # type: ignore[call-overload]
                "opacity": effect_opacity(effect_id),
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


# -- ED-04 (m-25026627): the effects as blocks, on rows ----------------------------------------
#
# A layer effect the owner put is a USE: `{uid, effect_id, start, end, lane, blocks}` —
# seconds of the final video, the row of «Efectos» it sits on (screen only: the recipe
# never carries it; Deivid 2026-11-17, «+ Pista») and the «Fotos y videos» blocks it is
# stuck to («¿En qué partes va?», Deivid 2026-11-17). Stuck, its seconds are always its
# blocks' own (they move, are cut or trimmed: it follows); [] = its own seconds, after a
# drag or ±½ s. The same effect may be put several times (ED-15), never twice at the
# same time, and at most `max_per_part` times (the library); at most `EFFECTS_MAX` in all.

#: The recipe takes at most this many effects in a part (contract v2).
EFFECTS_MAX = contract.EFFECTS_MAX
EFFECTS_FULL = f"Ya usas {EFFECTS_MAX} efectos. Quita uno para poner otro."
PARTS_TITLE = "¿En qué partes va?"
PARTS_NONE = "Marca al menos una parte de tu video para poner un efecto."
EFFECT_TWICE_LINE = (
    "Un mismo efecto quedó dos veces al mismo tiempo. Muévelo o quita uno de los dos."
)
#: The filter of «+ Efecto» (Deivid 2026-11-16: by rubro, never hiding an effect).
FILTER_LABEL = "Ver efectos por rubro"
FILTER_ALL = "todos"
FILTER_ALL_TEXT = "Todos"
#: The library's categories (`qualify_creative.effects.EFFECT_CATEGORIES`) as the owner
#: reads them.
CATEGORY_LABELS: dict[str, str] = {
    "comida": "Comida",
    "texto": "Texto",
    "transicion": "Transiciones",
    "movimiento": "Movimiento",
    "general": "Para todo",
}
#: The tag of an effect of the business's own rubro (why it is listed first).
YOUR_RUBRO = "De tu rubro"
#: Deivid 2026-11-20 («nunca se solape encima del otro»): an effect dropped, stretched or
#: moved onto a row where another is takes only the free room there; under 1 s of room it
#: goes back to its place and the live line says why.
EFFECT_NO_ROOM_LINE = (
    "Ahí ya hay otro efecto y no queda espacio libre. Llévalo a un hueco libre de la pista."
)
#: UX review of ED-04: beside the live line while an effect is chosen, until it first
#: changes row (as `TRIM_HINT` for a video's handles).
LANE_HINT = "Arrástralo arriba o abajo para pasarlo a otra pista."
EFFECT_TRIMMED_TAIL = "Lo acortamos al espacio libre."


def too_many_effects_line(count: int) -> str:
    """Before «Crear»: more effects than the recipe takes."""
    return f"Tu video tiene {int(count)} efectos y puede tener hasta {EFFECTS_MAX}. Quita alguno."


def effects_room_line(groups: int, room: int) -> str:
    """The parts marked would be more effects than still fit (one per group of parts
    side by side)."""
    fit = "solo cabe 1 más" if room == 1 else f"solo caben {int(room)} más"
    return f"Así serían {int(groups)} efectos y {fit}. Marca partes seguidas o quita un efecto."


def _times(n: int) -> str:
    return "1 vez" if int(n) == 1 else f"{int(n)} veces"


def effect_repeat_full_line(label: str, most: int) -> str:
    """One effect more times than the library lets it repeat (`max_per_part`)."""
    return f"Ya pusiste {label} {_times(most)}. Quítalo de una parte para ponerlo en otra."


def effect_repeat_over_line(label: str, count: int, most: int) -> str:
    """Before «Crear»: the effect is on more times than it may be (a block moved under it
    split it) — how many, and how many fit."""
    fit = "solo cabe 1" if int(most) == 1 else f"solo caben {int(most)}"
    return f"Pusiste {label} {_times(count)} y {fit}. Quítalo de una parte."


def effect_same_time_line(label: str) -> str:
    """The same effect twice at the same time: the recipe refuses it."""
    return f"{label} ya está en esa parte. Un mismo efecto no puede ir dos veces a la vez."


def effect_put_line(label: str, groups: int = 1) -> str:
    """«Pusiste Vapor.» / «Pusiste Vapor en 2 partes.»."""
    return f"Pusiste {label}." if groups <= 1 else f"Pusiste {label} en {int(groups)} partes."


def lane_name(n: int, lanes: int) -> str:
    """A row's name: «Efectos» while there is one, else «Efectos 1», «Efectos 2»…"""
    return "Efectos" if lanes <= 1 else f"Efectos {int(n)}"


def lane_empty_name(n: int, lanes: int) -> str:
    """An empty row's accessible name (never read as a list)."""
    return "Pista de efectos vacía" if lanes <= 1 else f"Pista de efectos {int(n)} vacía"


def lane_moved_line(label: str, lane_title: str) -> str:
    """Dragged onto another row, named as the row shows it: «Pasaste Vapor a Efectos 2.»."""
    return f"Pasaste {label} a {lane_title}."


def lane_stepped_line(label: str, *, up: bool) -> str:
    """↑/↓ on the block: «Subiste Vapor una pista.» / «Bajaste Vapor una pista.»."""
    return f"{'Subiste' if up else 'Bajaste'} {label} una pista."


def lane_busy_line(lane_title: str) -> str:
    return (
        f"En {lane_title} no queda espacio libre en ese momento. Llévalo a otra pista o a "
        "un hueco libre."
    )


def lane_top_line(label: str) -> str:
    """↑ on the first row."""
    return f"{label} ya está en la primera pista."


def lane_bottom_line(label: str) -> str:
    """↓ on the only effect of the last row."""
    return f"{label} ya está solo en la última pista."


def effects_gone_line(labels: Sequence[str]) -> str:
    """After a block left: the effects that went only on it left too ("" = none)."""
    shown = list(dict.fromkeys(str(label) for label in labels if label))
    if not shown:
        return ""
    joined = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " y " + shown[-1]
    verb = "iba" if len(shown) == 1 else "iban"
    return f"También quitamos {joined}, que {verb} solo en esa parte."


# -- the library's facts (EF-08, the default `effects_data/vN.json`) ------------------------


def _library_facts() -> dict[str, tuple[float, tuple[str, ...], int]]:
    """`{effect_id: (intensity, categories, max_per_part)}` of the effects the Clip
    offers, read from the effects library the backend checks against (the default
    library, read-only and cached by `load_effects`). {} when it cannot be read: the
    preview then draws a layer at full strength and lists it under «Todos»."""
    try:
        from qualify_creative.effects import (  # noqa: PLC0415 — pure, cached read
            load_effects,
        )

        library = load_effects()
    except Exception:  # noqa: BLE001 — the screen keeps working without the filter
        return {}
    out: dict[str, tuple[float, tuple[str, ...], int]] = {}
    for effect in contract.CLIP_EFFECTS:
        entry = library.get(effect.effect_id, effect.version)
        if entry is None:
            continue
        spec = entry.params.get("intensity")
        intensity = 1.0
        if spec is not None and not isinstance(spec.default, bool | str):
            intensity = float(spec.default)
        out[effect.effect_id] = (intensity, tuple(entry.categories), int(entry.max_per_part))
    return out


_FACTS: dict[str, tuple[float, tuple[str, ...], int]] = {}


def _facts() -> dict[str, tuple[float, tuple[str, ...], int]]:
    """`_library_facts`, read once per process (like `load_effects` itself)."""
    if not _FACTS:
        _FACTS.update(_library_facts())
    return _FACTS


def effect_opacity(effect_id: str) -> float:
    """The preview layer's CSS `opacity`: the library's default `intensity` (humo 0,6,
    brasas 0,5, vapor 0,5). With a «screen» blend it is what PyAV's intensity does to the
    final video, so the preview is as strong as the video (UX review of EF-08)."""
    facts = _facts().get(effect_id)
    return facts[0] if facts is not None else 1.0


def effect_categories(effect_id: str) -> tuple[str, ...]:
    facts = _facts().get(effect_id)
    return facts[1] if facts is not None else ()


def effect_max_uses(effect_id: str) -> int:
    """How many times one part may use the effect (`max_per_part`; 1 if unknown)."""
    facts = _facts().get(effect_id)
    return facts[2] if facts is not None else 1


def effect_opacity_by_url(urls: Mapping[str, str]) -> dict[str, float]:
    """`{loop url: opacity}` from `{effect_id: loop url}`, for the single-stretch preview
    (`ui.edit_preview.edit_preview`), whose layers only know their address."""
    return {url: effect_opacity(effect_id) for effect_id, url in urls.items() if url}


# -- the business's rubro and the filter (Deivid 2026-11-16) --------------------------------

#: The niches (`discovery_seed.NICHE_LABELS` keys, Brand Kit `connect.sector`) with a
#: category of their own in the library.
SECTOR_CATEGORIES: dict[str, str] = {"food_drink": "comida"}
#: Words of the rubro as the owner wrote it (`connect.rubro_text`) that make it food.
_FOOD_WORDS: tuple[str, ...] = (
    "comida",
    "restaurant",
    "cafe",
    "panader",
    "pasteler",
    "reposter",
    "helad",
    "yogur",
    "pizz",
    "hamburgues",
    "shawarma",
    "arepa",
    "empanad",
    "bebida",
    "cocina",
    "parrill",
    "asado",
    "sushi",
    "postre",
    "gastronom",
    "ensalad",
    "jugo",
    "batido",
    "cervece",
    "licor",
    "food",
)


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def business_category(*, sector: str, rubro: str) -> str:
    """The library category of the business ("" = none of its own): by the words of
    its rubro first, then by its niche."""
    plain = _plain(rubro)
    if any(word in plain for word in _FOOD_WORDS):
        return "comida"
    return SECTOR_CATEGORIES.get(str(sector or "").strip(), "")


def effect_filters(
    effect_ids: Sequence[str], categories: Mapping[str, Sequence[str]], business: str
) -> list[tuple[str, str]]:
    """«Todos» and every category the offered effects have — the business's first —
    as `(value, text)`."""
    found: list[str] = []
    for effect_id in effect_ids:
        for category in categories.get(effect_id, ()):
            if category not in found:
                found.append(category)
    found.sort(key=lambda category: category != business)
    return [
        (FILTER_ALL, FILTER_ALL_TEXT),
        *((c, CATEGORY_LABELS.get(c, c.capitalize())) for c in found),
    ]


def default_filter(
    effect_ids: Sequence[str], categories: Mapping[str, Sequence[str]], business: str
) -> str:
    """The filter «+ Efecto» opens on: the business's category when some effect has it,
    else «Todos»."""
    if business and any(business in categories.get(e, ()) for e in effect_ids):
        return business
    return FILTER_ALL


def filter_effects(
    effect_ids: Sequence[str],
    categories: Mapping[str, Sequence[str]],
    *,
    business: str,
    chosen: str,
) -> list[str]:
    """The effects listed under the filter `chosen` — every one under «Todos» (none is
    ever hidden from a business: smoke in a technology video is fine) — the business's
    own first, then the library's order."""
    shown = [e for e in effect_ids if chosen in ("", FILTER_ALL) or chosen in categories.get(e, ())]
    return sorted(shown, key=lambda e: not business or business not in categories.get(e, ()))


# -- uses: their seconds, their blocks, their rows -------------------------------------------


def effect_block_id(uid: str) -> str:
    """The timeline block of a use: `efecto-u3`."""
    return EFFECT_ID_PREFIX + str(uid)


def use_uid(block_id: str) -> str:
    """The use a block id names ("" = not an effect block)."""
    return block_id[len(EFFECT_ID_PREFIX) :] if block_id.startswith(EFFECT_ID_PREFIX) else ""


def new_effect_uid(uses: Sequence[Mapping[str, object]], taken: Sequence[str] = ()) -> str:
    """The next free use id (`u1`, `u2`…)."""
    used = {str(u.get("uid") or "") for u in uses} | set(taken)
    n = 1
    while f"u{n}" in used:
        n += 1
    return f"u{n}"


def block_spans(media: Sequence[Mapping[str, object]]) -> dict[str, tuple[float, float]]:
    """Each «Fotos y videos» block's seconds of the final video, end to end."""
    out: dict[str, tuple[float, float]] = {}
    at = 0.0
    for item in media:
        length = _shown_length(item)
        out[str(item.get("id") or "")] = (round(at, 2), round(at + length, 2))
        at += length
    return out


def part_groups(media: Sequence[Mapping[str, object]], chosen: Sequence[str]) -> list[list[str]]:
    """The blocks `chosen`, in the video's order, as groups of blocks side by side: each
    group is one effect («¿En qué partes va?»: blocks 1 and 3 are two)."""
    on = set(chosen)
    groups: list[list[str]] = []
    run: list[str] = []
    for item in media:
        block_id = str(item.get("id") or "")
        if block_id in on:
            run.append(block_id)
        elif run:
            groups.append(run)
            run = []
    if run:
        groups.append(run)
    return groups


def group_span(
    spans: Mapping[str, tuple[float, float]], group: Sequence[str]
) -> tuple[float, float]:
    """A group's seconds: from its first block's start to its last block's end."""
    return (min(spans[b][0] for b in group), max(spans[b][1] for b in group))


def _stuck(use: Mapping[str, object]) -> list[str]:
    return [str(b) for b in list(use.get("blocks") or [])]  # type: ignore[call-overload]


def resolve_effect_uses(
    uses: Sequence[Mapping[str, object]], media: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    """Each use at its seconds NOW: a stuck one from its blocks' places (a block moved,
    cut or trimmed moves it), one with its own seconds kept inside the video (an end the
    video no longer reaches is cut to it, never under 1 s). A stuck use whose blocks
    all left the timeline is gone. Only layer effects with a loop."""
    spans = block_spans(media)
    total = media_total(media)
    out: list[dict[str, object]] = []
    for use in uses:
        effect = contract.effect_of(str(use.get("effect_id") or ""))
        if effect is None or not effect.preview_asset:
            continue
        stuck = _stuck(use)
        present = [b for b in stuck if b in spans]
        if stuck and not present:
            continue
        if present:
            start, end = group_span(spans, present)
        else:
            start, end = _span(
                float(use.get("start") or 0.0),  # type: ignore[arg-type]
                float(use.get("end") or 0.0),  # type: ignore[arg-type]
                total,
            )
        out.append(
            {
                "uid": str(use.get("uid") or ""),
                "effect_id": effect.effect_id,
                "start": round(start, 2),
                "end": round(end, 2),
                "lane": int(use.get("lane") or 0),  # type: ignore[call-overload]
                "blocks": present,
            }
        )
    return compact_lanes(out)


def follow_media(
    uses: Sequence[Mapping[str, object]], media: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    """The uses after the blocks changed (moved, cut, trimmed, removed): a stuck use
    whose blocks are no longer side by side becomes one use per group (the first keeps
    its id and row); one whose blocks all left is gone; every stuck use's kept seconds
    are its blocks' again."""
    spans = block_spans(media)
    out: list[dict[str, object]] = []
    taken: list[str] = [str(u.get("uid") or "") for u in uses]
    for use in uses:
        stuck = _stuck(use)
        if not stuck:
            out.append(dict(use))
            continue
        for n, group in enumerate(part_groups(media, stuck)):
            uid = str(use.get("uid") or "")
            if n:
                uid = new_effect_uid(out, taken)
                taken.append(uid)
            start, end = group_span(spans, group)
            out.append({**use, "uid": uid, "blocks": group, "start": start, "end": end})
    return out


def remap_effect_blocks(
    uses: Sequence[Mapping[str, object]], mapping: Mapping[str, Sequence[str]]
) -> list[dict[str, object]]:
    """The uses with their blocks renamed (`old id → new ids`): the own video's pieces
    are named by their place (`piece_id`), so a cut, a piece taken out or a move renames
    them — an effect stuck to a piece stays on the same stretch of video."""
    out: list[dict[str, object]] = []
    for use in uses:
        renamed: list[str] = []
        for block_id in _stuck(use):
            for new in mapping.get(block_id, [block_id]):
                if new not in renamed:
                    renamed.append(new)
        out.append({**use, "blocks": renamed})
    return out


def _clash(a: Sequence[float], b: Sequence[float]) -> bool:
    """Two spans cover the same seconds (meeting at a second is fine)."""
    return float(a[0]) < float(b[1]) - 1e-6 and float(b[0]) < float(a[1]) - 1e-6


def _use_span(use: Mapping[str, object]) -> tuple[float, float]:
    return float(use.get("start") or 0.0), float(use.get("end") or 0.0)  # type: ignore[arg-type]


def lane_fits(
    uses: Sequence[Mapping[str, object]], span: Sequence[float], lane: int, uid: str = ""
) -> bool:
    """`span` fits on row `lane`: no other use there at the same time."""
    return not any(
        int(u.get("lane") or 0) == lane  # type: ignore[call-overload]
        and str(u.get("uid") or "") != uid
        and _clash(span, _use_span(u))
        for u in uses
    )


def same_effect_clash(
    uses: Sequence[Mapping[str, object]], effect_id: str, span: Sequence[float], uid: str = ""
) -> bool:
    """`effect_id` is already on at some second of `span` (the recipe refuses it)."""
    return any(
        str(u.get("effect_id")) == effect_id
        and str(u.get("uid") or "") != uid
        and _clash(span, _use_span(u))
        for u in uses
    )


def pick_lane(
    uses: Sequence[Mapping[str, object]], span: Sequence[float], *, lanes: int, prefer: int = 0
) -> int:
    """The row a new use of `span` goes on: `prefer` when it fits there, else the first
    one where it fits, else a new row (`lanes`) — two effects at the same time never
    share a row. m-25114465: «the first one where it fits» is the shared rule of
    `timeline_vm.first_free_row`, over every row of «Efectos»."""
    if 0 <= prefer < lanes and lane_fits(uses, span, prefer):
        return prefer
    rows = [
        [_use_span(u) for u in uses if int(u.get("lane") or 0) == lane]  # type: ignore[call-overload]
        for lane in range(max(lanes, 0))
    ]
    row = timeline_vm.first_free_row(rows, span)
    return max(lanes, 0) if row is None else row


def effect_obstacles(
    uses: Sequence[Mapping[str, object]], *, uid: str, effect_id: str, lane: int
) -> list[tuple[float, float]]:
    """What a use may not overlap when it moves: the other uses on its row, and the
    other uses of the same effect on any row."""
    return [
        _use_span(u)
        for u in uses
        if str(u.get("uid") or "") != uid
        and (
            int(u.get("lane") or 0) == lane  # type: ignore[call-overload]
            or str(u.get("effect_id")) == effect_id
        )
    ]


#: The free stretches of a row (m-25114465: moved to `timeline_vm`, shared with
#: `first_free_slot`).
free_gaps = timeline_vm.free_gaps


def fit_in_gap(
    span: Sequence[float],
    obstacles: Sequence[Sequence[float]],
    total: float,
    least: float = contract.SEGMENT_MIN_SECONDS,
) -> tuple[float, float] | None:
    """Deivid 2026-11-20 («quiero que se acorte al tamaño que sobre en la pista, que nunca
    se solape encima del otro»): an effect put at `span` on a row takes the free room of
    that row it overlaps most (the nearest one on a tie) — trimmed to it, never over
    another effect. None when that room is under `least` (1 s): it goes back."""
    start, end = float(span[0]), float(span[1])
    best: tuple[float, float] | None = None
    best_key: tuple[float, float] | None = None
    for a, b in free_gaps(obstacles, total):
        piece = (max(a, start), min(b, end))
        overlap = piece[1] - piece[0]
        if overlap <= 1e-6:
            continue
        key = (-overlap, abs(piece[0] - start))
        if best_key is None or key < best_key:
            best, best_key = piece, key
    if best is None or best[1] - best[0] < float(least) - 1e-6:
        return None
    return round(best[0], 2), round(best[1], 2)


def clamp_edge(
    edge: str, value: float, span: Sequence[float], obstacles: Sequence[Sequence[float]]
) -> float:
    """A handle stops at the edge of what is in its way (the ticket: «el tirador se
    detiene en el borde del otro uso»)."""
    start, end = float(span[0]), float(span[1])
    if edge == "start":
        walls = [float(b) for a, b in obstacles if float(b) <= start + 1e-6]
        return max(float(value), max(walls, default=-math.inf))
    walls = [float(a) for a, b in obstacles if float(a) >= end - 1e-6]
    return min(float(value), min(walls, default=math.inf))


# -- the own video's pieces renamed (they are named by their place, `piece_id`) -------------


def cut_mapping(key: str, count: int, index: int) -> dict[str, list[str]]:
    """«Cortar» split piece `index` of `count`: it is now two, the later ones move up."""
    out: dict[str, list[str]] = {}
    for n in range(max(int(count), 1)):
        if n < index:
            out[piece_id(key, n)] = [piece_id(key, n)]
        elif n == index:
            out[piece_id(key, n)] = [piece_id(key, n), piece_id(key, n + 1)]
        else:
            out[piece_id(key, n)] = [piece_id(key, n + 1)]
    return out


def removed_mapping(key: str, count: int, index: int) -> dict[str, list[str]]:
    """Piece `index` of `count` left: it is nothing now, the later ones move down."""
    out: dict[str, list[str]] = {}
    for n in range(max(int(count), 1)):
        if n == index:
            out[piece_id(key, n)] = []
        else:
            out[piece_id(key, n)] = [piece_id(key, n if n < index else n - 1)]
    return out


def order_mapping(key: str, order: Sequence[int]) -> dict[str, list[str]]:
    """The pieces moved: place `p` now holds the piece that was at `order[p]`."""
    return {piece_id(key, int(old)): [piece_id(key, place)] for place, old in enumerate(order)}


def collapse_mapping(key: str, count: int) -> dict[str, list[str]]:
    """The pieces became the one stretch again (sped up whole, or a new length)."""
    return {piece_id(key, n): [piece_id(key, 0)] for n in range(max(int(count), 1))}


# -- rows: several effects one after another, and a move from row to row ---------------------


def _place_free(
    placed: list[dict[str, object]], use: Mapping[str, object], *, count: int, total: float
) -> tuple[dict[str, object], int]:
    """A use with its own seconds, among the ones already `placed`: where it is when
    nothing is in its way; else trimmed to the free room of its row (`fit_in_gap`); else
    whole on the first row where it fits, or a new one. The use as placed, and the rows."""
    least = contract.SEGMENT_MIN_SECONDS
    effect_id = str(use.get("effect_id") or "")
    start, end = _use_span(use)
    end = min(end, total)
    start = min(start, max(end - least, 0.0))
    lane = int(use.get("lane") or 0)  # type: ignore[call-overload]

    def walls(row: int) -> list[tuple[float, float]]:
        return [
            _use_span(u)
            for u in placed
            if int(u.get("lane") or 0) == row  # type: ignore[call-overload]
            or str(u.get("effect_id")) == effect_id
        ]

    span = (round(start, 2), round(end, 2))
    if not any(_clash(span, w) for w in walls(lane)):
        return {**use, "start": span[0], "end": span[1], "lane": lane}, count
    fit = fit_in_gap(span, walls(lane), total, least)
    if fit is not None:
        return {**use, "start": fit[0], "end": fit[1], "lane": lane}, count
    for row in range(count + 1):
        if not any(_clash(span, w) for w in walls(row)):
            return {**use, "start": span[0], "end": span[1], "lane": row}, max(count, row + 1)
    # the same effect is on then on every row: the most room on a new row (`effects_problem`
    # says so before «Crear» if even that overlaps)
    fit = fit_in_gap(span, walls(count), total, least) or span
    return {**use, "start": fit[0], "end": fit[1], "lane": count}, count + 1


def settle_lanes(
    uses: Sequence[Mapping[str, object]], *, lanes: int, total: float | None = None
) -> tuple[list[dict[str, object]], int]:
    """After «Fotos y videos» changed (a move, a cut, a trim, a block taken out, a speed):
    on a row nothing ever overlaps. A use with its own seconds keeps its row and its
    seconds when it can — kept inside the video (`total`), and trimmed to the free room of
    its row or moved to another when the shorter video squeezed it onto a neighbour
    (`_place_free`); a use stuck to its blocks — it moved with them — that now overlaps
    another on its row goes to the first row where it fits, else a new one. The uses in
    their order, and how many rows."""
    count = max(int(lanes), 1)
    top = float(total) if total is not None else max((_use_span(u)[1] for u in uses), default=0.0)
    placed: list[dict[str, object]] = []
    for use in uses:
        if _stuck(use):
            continue
        settled, count = _place_free(placed, use, count=count, total=top)
        placed.append(settled)
    for use in uses:
        if not _stuck(use):
            continue
        span = _use_span(use)
        lane = int(use.get("lane") or 0)  # type: ignore[call-overload]
        if not lane_fits(placed, span, lane):
            lane = pick_lane(placed, span, lanes=count, prefer=lane)
            count = max(count, lane + 1)
        placed.append({**use, "lane": lane})
    by_uid = {str(u.get("uid") or ""): u for u in placed}
    return [by_uid[str(u.get("uid") or "")] for u in uses], count


def compact_lanes(uses: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Deivid 2026-11-20 («el botón de añadir pista no le veo sentido»): the rows come and
    go on their own — an empty row disappears and the ones under it move up."""
    used = sorted({int(u.get("lane") or 0) for u in uses})  # type: ignore[call-overload]
    place = {lane: n for n, lane in enumerate(used)}
    return [{**u, "lane": place[int(u.get("lane") or 0)]} for u in uses]  # type: ignore[call-overload]


def block_url_script(param: str, slug: str, *, flow: bool) -> str:
    """The address says which block is chosen (`?bloque=video-2`, N3). Choosing the first
    one adds a history entry, so the phone's «atrás» lets it go before it leaves the step
    (N5); choosing another replaces it; letting go walks back through that entry.

    The entry this page pushed carries `qBloque` = this page load's own mark
    (`window.__qBloqueDoc`): after a reload the browser keeps the entry and its state,
    but walking back from it would leave the reloaded page — a whole page load (the
    «recarga» Deivid saw, 2026-11-20). So letting go walks back only through an entry
    THIS page load pushed; any other one just drops the word (`replaceState`)."""
    key = json.dumps(param)
    doc = (
        "(window.__qBloqueDoc = window.__qBloqueDoc ||"
        " ('d' + Date.now().toString(36) + Math.random().toString(36).slice(2)))"
    )
    mine = f"(!!window.history.state && window.history.state.qBloque === {doc})"
    if slug or flow:
        write = (
            f" u.searchParams.set({key}, {json.dumps(slug)});"
            if slug
            else (f" u.searchParams.delete({key});")
        )
        return (
            "(() => { const u = new URL(window.location.href);"
            f" const had = u.searchParams.has({key}) || {mine};"
            f"{write}"
            " const url = u.pathname + u.search + u.hash;"
            " if (had) window.history.replaceState(window.history.state, '', url);"
            " else window.history.pushState({ ...(window.history.state || {}),"
            f" qBloque: {doc} }}, '', url); }})()"
        )
    return (
        "(() => { const u = new URL(window.location.href);"
        f" if ({mine}) {{ window.history.back(); return; }}"
        f" const state = {{ ...(window.history.state || {{}}) }}; delete state.qBloque;"
        f" if (!u.searchParams.has({key}) && !window.history.state?.qBloque) return;"
        f" u.searchParams.delete({key});"
        " window.history.replaceState(state, '', u.pathname + u.search + u.hash); })()"
    )


def put_label(label: str, *, mine: bool = False) -> str:
    """An effect's button name in «+ Efecto» (UX review): «Poner Vapor, gratis», and
    «, de tu rubro» when it is the business's."""
    return f"Poner {label}, gratis" + (", de tu rubro" if mine else "")
