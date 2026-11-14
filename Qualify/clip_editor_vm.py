"""«Arma tu video» (ED-02 m-25026621, ED-03 m-25026623, ED-05 m-25026630; epic «Video
automático con efectos, por pasos»): the
words and the pure rules of the normal Clip's first step as an editor — a live preview
on top, the card «Tu video», and four tools, one open at a time, each asking one
question. Nothing is generated here; every change is kept at once with «Deshacer»
(D-E6, no «Guardar»).

The state (`CreativeState`, «clip editor» block) holds the owner's choices as plain
fields; `snapshot` / `change_message` / `push_undo` here decide what «Deshacer» brings
back and what the live line says, and `recipe_of` turns the fields into the
`editor_preview_contract.PartRecipe` (EF-02's shape) the brief carries.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence

from . import editor_preview_contract as contract

# -- the switch ----------------------------------------------------------------------------

#: The editor is behind `QUALIFY_CLIP_EDITOR`: `off` (the default, as in `.env.example`)
#: keeps the Clip's step 1 as «Qué mostrar», exactly as before, so this merges without
#: promising what the backend does not do yet; `1` (or `on`/`true`) turns it on — once
#: EF-06 (m-25026574) reads the editor's recipe. Anything else is off. Read once, at
#: import, like the other `QUALIFY_*` of `Qualify/`; tests patch `CLIP_EDITOR_ON`.
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

# -- the tools (`rx.segmented_control`, one open at a time) ------------------------------

TOOL_MEDIA = "media"
TOOL_IDEA = "idea"
TOOL_EFFECTS = "effects"
TOOL_CUT = "cut"
TOOLS: tuple[str, ...] = (TOOL_MEDIA, TOOL_IDEA, TOOL_EFFECTS, TOOL_CUT)
TOOL_LABELS = {
    TOOL_MEDIA: "Fotos y videos",
    TOOL_IDEA: "Idea",
    TOOL_EFFECTS: "Efectos",
    TOOL_CUT: "Cortar",
}
TOOL_ICONS = {
    TOOL_MEDIA: "images",
    TOOL_IDEA: "lightbulb",
    TOOL_EFFECTS: "sparkles",
    TOOL_CUT: "scissors",
}
TOOL_QUESTIONS = {
    TOOL_MEDIA: "¿Con qué lo armamos?",
    TOOL_IDEA: "¿De qué trata tu video?",
    TOOL_EFFECTS: "¿Qué le pones a tu video?",
    TOOL_CUT: "¿Qué pedazo de tu video usas?",
}
TOOLS_LABEL = "Herramientas"
#: The address's word for each tool (`/create?paso=1&herramienta=cortar`, N3).
TOOL_SLUGS = {
    TOOL_MEDIA: "fotos",
    TOOL_IDEA: "idea",
    TOOL_EFFECTS: "efectos",
    TOOL_CUT: "cortar",
}
TOOL_PARAM = "herramienta"

# -- «Fotos y videos» ---------------------------------------------------------------------

ADD_MEDIA = "Agregar fotos o videos"
#: «Orden de tu video»: the first and the last file (the off-switch keeps «…el clip»).
STRIP_OPENS = "Abre tu video"
STRIP_CLOSES = "Cierra tu video"
#: Under a second video of the order: it only lends its movement (joining several is a
#: video by parts; the background is ED-10's).
MOTION_ONLY_NOTE = (
    "Este video solo guía el movimiento. Para unir varios, usa «Armar mi video por partes»."
)
#: The tag under the video the editor plays and cuts (other videos stay «Movimiento»).
OWN_VIDEO_TAG = "Tu video"
ORDER_TITLE = "Orden de tu video"
ORDER_HINT = (
    "Arrastra las fotos y los videos para ordenarlos: el primero abre tu video y el último "
    "lo cierra."
)
PRODUCT_PREFIX = "Tu producto: "
PRODUCT_CHANGE = "Cambiar"
PRODUCT_CHOOSE = "Elegir un producto"
PRODUCT_CHANGE_LABEL = "Cambiar el producto"

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


#: «Cámara rápida» is offered on a video of at least this length (UX review 2026-11-14).
FAST_MIN_SOURCE_SECONDS = 15.0
FAST_NEEDS_LONGER = "Para usar cámara rápida tu video tiene que durar al menos 15 s."


def fast_impossible_line(seconds: float) -> str:
    """Even the whole video at ×5 lasts under 3 s: nothing the owner can fix by cutting."""
    return (
        f"Tu video duraría {contract.seconds_text(seconds)} s: muy poco para un reel. "
        "Quita la cámara rápida o usa un video más largo."
    )


def fast_on_line(speed: int, *, had_cut: bool) -> str:
    """The live line when «Cámara rápida» is marked: what it did to the stretch."""
    line = f"Pusiste cámara rápida: usamos todo tu video a ×{int(speed)}."
    return f"{line} Si la quitas, vuelve tu pedazo." if had_cut else line


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
    """Marking «Cámara rápida»: the whole video (no 15 s cap: it is sped up) and the
    speed of ×5/×10/×20 whose result is closest to 5 s — `(start, end, speed)`."""
    end = contract.grid_end(duration)
    speed = min(
        contract.FAST_MOTION_SPEEDS,
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


TOO_SHORT = "El pedazo tiene que durar al menos 1 segundo."
CUT_WAITING = "Estamos leyendo cuánto dura tu video."
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
    """«Usas {s} s de tu video.»"""
    return f"Usas {contract.seconds_text(seconds)} s de tu video."


def range_line(start: float, end: float) -> str:
    """«Desde 0:04 · Hasta 0:12»."""
    return f"Desde {contract.clock_text(start)} · Hasta {contract.clock_text(end)}"


# -- the card «Tu video» -------------------------------------------------------------------


def card_title(seconds: float) -> str:
    """«Tu video · {s} s»."""
    return f"Tu video · {contract.seconds_text(seconds)} s"


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
) -> dict[str, object]:
    """The editor's choices as one plain value (what «Deshacer» restores exactly)."""
    return {
        "start": float(start),
        "end": float(end),
        "rotate": int(rotate),
        "effects": list(effects),
        "speed": int(speed),
        "text": str(text),
        "place": str(place),
    }


FAST_ON_LINE = "Pusiste cámara rápida a tu video."
FAST_OFF_LINE = "Quitaste la cámara rápida de tu video."


def change_message(before: Mapping[str, object], after: Mapping[str, object]) -> str:
    """The live line for a change ("" = nothing changed). «Cámara rápida» marked or
    unmarked says so, even though it also moves the stretch and the speed."""
    fast_before = contract.FAST_MOTION in list(before.get("effects") or [])  # type: ignore[call-overload]
    fast_after = contract.FAST_MOTION in list(after.get("effects") or [])  # type: ignore[call-overload]
    if fast_after and not fast_before:
        return FAST_ON_LINE
    if fast_before and not fast_after:
        return FAST_OFF_LINE
    for fields, line in _CHANGE_LINES:
        if any(before.get(name) != after.get(name) for name in fields):
            return line
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
_NOT_OWN = ("reel", "pinterest", "stock")


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


def tools_shown(*, has_own_video: bool) -> list[str]:
    """«Cortar» only with an own video the browser can play here (no empty tools)."""
    return [t for t in TOOLS if t != TOOL_CUT or has_own_video]


def tool_from_slug(slug: str) -> str:
    """The tool an address names ("" = none / unknown)."""
    for tool, word in TOOL_SLUGS.items():
        if word == slug:
            return tool
    return ""


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
) -> contract.PartRecipe:
    """The Clip's recipe of one part, in EF-02's shape. «Cámara rápida»'s speed goes in
    the stretch only (`segments[].speed`); the `camara_rapida` effect carries empty
    params (provisional, see `editor_preview_contract`). An unset stretch is left out."""
    fast = contract.FAST_MOTION in effects and bool(video_key)
    segments: tuple[contract.SourceSegment, ...] = ()
    if video_key and end > start:
        segments = (
            contract.SourceSegment(
                key=video_key,
                start_s=float(start),
                end_s=float(end),
                speed=float(speed) if fast else 1.0,
                rotate=int(rotate),
            ),
        )
    uses: list[contract.EffectUse] = []
    for effect_id in effects:
        effect = contract.effect_of(effect_id)
        if effect is None or (effect.needs_own_video and not video_key):
            continue
        uses.append(contract.EffectUse(effect_id, effect.version))
    layer = (
        contract.VideoTextLayer(
            text=text.strip(),
            place=place,
            layout_id=contract.TEXT_LAYOUT_ID,
            layout_version=contract.TEXT_LAYOUT_VERSION,
        )
        if text.strip()
        else None
    )
    return contract.PartRecipe(effects=tuple(uses), text_layer=layer, segments=segments)


def card_line(effects: Sequence[str], text: str) -> str:
    """The card's one line: the effects chosen and the text («Vapor · «Shawarma…»»)."""
    labels = [e.label for e in contract.CLIP_EFFECTS if e.effect_id in effects]
    parts = [", ".join(labels)] if labels else []
    if text.strip():
        parts.append(f"«{text.strip()}»")
    return " · ".join(parts)
