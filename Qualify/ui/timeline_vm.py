"""Pure view model of the «Arma tu video» timeline (ED-00b m-25029104, pattern for ED-10).

No Reflex import: everything here is plain data in, plain data out, so the rules of the
pattern (docs: `.claude/epica-efectos-propuesta-linea-de-tiempo.md` §3, §4) are tested
offline and `ui.timeline` only draws what this module computes.

Two raw lists describe a video:

- **media** — the «Fotos y videos» track, in the video's order, never with a gap:
  ``{"id", "kind": "video", "src_start", "src_end", "src_len"}`` (seconds of the source
  the owner uses, and the source's length) or ``{"id", "kind": "photo", "dur"}`` (a
  still photo shown ``dur`` seconds, D-T1 = A).
- **overlays** — the «Textos» and «Efectos» tracks:
  ``{"id", "kind": "text" | "effect", "label", "start", "end"}`` in seconds of the final
  video.

`media_blocks` / `overlay_blocks` turn them into rows of strings the component renders
(serialisable, so they can live in a Reflex state var); `nudge`, `move` and `shift` are
the keyboard edits of §3.7 (½ s steps, 1 s minimum, no gaps).
"""

from __future__ import annotations

import math
from typing import Any

#: The magnet (§3.3): every edge lands on a half second.
STEP_S = 0.5
#: «Cada pedazo dura al menos 1 segundo.»
MIN_S = 1.0
#: A photo's length (§1.2: from 1 to 5 s, 2 s by default — hypothesis to measure).
PHOTO_MIN_S = 1.0
PHOTO_MAX_S = 5.0
#: Phone scale (§3.2): 1 s = 44 px, so a 1 s block is already a 44 px target.
PX_PER_SECOND = 44

TRACK_MEDIA = "media"
TRACK_TEXT = "text"
TRACK_EFFECT = "effect"

#: Copy (§4, exact).
GROUP_LABEL = "Línea de tiempo de tu video"
TRACK_LABELS = {TRACK_MEDIA: "Fotos y videos", TRACK_TEXT: "Textos", TRACK_EFFECT: "Efectos"}
#: An empty track's accessible name (review of ED-10: «Textos, vacía» read as a list).
EMPTY_TRACK_NAMES = {
    TRACK_MEDIA: "Pista de fotos y videos vacía",
    TRACK_TEXT: "Pista de textos vacía",
    TRACK_EFFECT: "Pista de efectos vacía",
}
PLAYHEAD_LABEL = "Momento del video"
MOVE_HELP = "Usa las flechas para cambiarlo de lugar."
#: A text's or an effect's help: the arrows move it in time (ED-10 UX review).
TIME_HELP = "Usa las flechas para cambiar cuándo sale."
#: Each help lives once, in a hidden span of the timeline; a block points at it with
#: `aria-describedby` (as «Velocidad»'s reasons do), never `aria-description`.
#: ED-04: an effect also changes row with ↑/↓ (Deivid 2026-11-20: «moverlos entre pistas»).
EFFECT_HELP = (
    "Usa las flechas izquierda y derecha para cambiar cuándo sale, y arriba y abajo para "
    "pasarlo a otra pista."
)
HELP_IDS = {
    MOVE_HELP: "q-tl-help-move",
    TIME_HELP: "q-tl-help-time",
    EFFECT_HELP: "q-tl-help-effect",
}
DONE_LABEL = "Listo"
MINUS_HALF = "− ½ s"
PLUS_HALF = "+ ½ s"

#: «Agregar» with nothing chosen: the `orbit_menu` (Deivid, 2026-11-14) — key, lucide
#: icon, text (≤ 16 characters). Each option OPENS a flow, never adds by itself.
ADD_LABEL = "Agregar"
ADD_OPTIONS: tuple[tuple[str, str, str], ...] = (
    ("media", "image-plus", "Foto o video"),
    ("text", "type", "Texto"),
    ("effect", "sparkles", "Efecto"),
    # ED-10: «Pedir una idea» fits the orbit's pill (≤ 16 characters, 44 px tall)
    ("idea", "lightbulb", "Pedir una idea"),
)

#: The chosen block's action bar (§4): label and lucide icon, at most 4, by its kind.
#: «Velocidad» and «Duración» live in the block's panel only (ED-10 UX note: one place).
ACTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "video": (
        ("Cortar aquí", "scissors"),
        ("Girar", "rotate-cw"),
        ("Quitar", "trash-2"),
    ),
    "photo": (("Girar", "rotate-cw"), ("Quitar", "trash-2")),
    "text": (("Editar texto", "pencil"), ("Quitar", "trash-2")),
    "effect": (("Cambiar efecto", "sparkles"), ("Quitar", "trash-2")),
}
#: The bar's accessible name: «Acciones de Video 1» (ED-10 UX note).
ACTIONS_PREFIX = "Acciones de "
#: Said in the live line while a block is lifted (phone, §4).
LIFT_HINT = "Suelta donde quieras ponerlo."


def actions_label(label: str) -> str:
    """The chosen block's bar name: «Acciones de Video 1» («Acciones» alone without one)."""
    return f"{ACTIONS_PREFIX}{label}" if label else "Acciones"


def snap(seconds: float) -> float:
    """The nearest half second (the magnet)."""
    return round(seconds / STEP_S) * STEP_S


def clock(seconds: float) -> str:
    """«0:04», «0:04,5», «1:02» — minutes, two-digit seconds, a Spanish decimal comma
    only when there is a half."""
    seconds = max(snap(seconds), 0.0)
    whole = math.floor(seconds)
    minutes, secs = divmod(whole, 60)
    half = ",5" if seconds - whole >= STEP_S else ""
    return f"{minutes}:{secs:02d}{half}"


def clock_exact(seconds: float) -> str:
    """«0:04», «0:03,7», «0:03,25» — a video's handle to the hundredth (ED-03 UX review:
    never the ½ s `clock`, the handle may rest on the ¼ s magnet)."""
    seconds = max(round(float(seconds), 2), 0.0)
    whole = math.floor(seconds + 1e-9)
    minutes, secs = divmod(whole, 60)
    rest = round(seconds - whole, 2)
    tail = f"{rest:.2f}"[2:].rstrip("0") if rest >= 0.005 else ""
    return f"{minutes}:{secs:02d}" + (f",{tail}" if tail else "")


def amount(seconds: float) -> str:
    """«5», «4,5» — a length in seconds, for «dura {s} s»."""
    seconds = snap(seconds)
    if seconds == int(seconds):
        return str(int(seconds))
    return f"{seconds:.1f}".replace(".", ",")


def playhead_text(t: float, total: float) -> str:
    """The playhead's `aria-valuetext`: «0:05 de 0:12»."""
    return f"{clock(t)} de {clock(total)}"


def exact(value: float) -> str:
    """A number for CSS and ARIA attributes, to the hundredth (dot decimal), never on the
    ½ s grid: where a block of «Fotos y videos» sits and how long it is (ED-03 — two
    neighbours each rounded on their own to ½ s left a gap or an overlap between them,
    e.g. after a speed went up and back down)."""
    value = round(float(value), 2)
    return str(int(value)) if value == int(value) else f"{value:g}"


def num(value: float) -> str:
    """A number for CSS and ARIA attributes (dot decimal)."""
    value = snap(value)
    return str(int(value)) if value == int(value) else f"{value:.1f}"


#: «Velocidad» of a video block (D-T3 = A): value, visible text, accessible name. Normal
#: reads «×1» (six equal columns fit a 375 px panel; «Normal» was cut — ED-10 UX review)
#: and is named «Velocidad normal».
SPEEDS: tuple[tuple[str, str, str], ...] = (
    ("1", "×1", "Velocidad normal"),
    ("2", "×2", "2 veces más rápido"),
    ("3", "×3", "3 veces más rápido"),
    ("5", "×5", "5 veces más rápido"),
    ("10", "×10", "10 veces más rápido"),
    ("20", "×20", "20 veces más rápido"),
)
SPEED_LABEL = "Velocidad"
#: Where a text goes (the editor's three places).
PLACES: tuple[tuple[str, str], ...] = (
    ("top", "Arriba"),
    ("middle", "En el medio"),
    ("bottom", "Abajo"),
)
PLACE_LABEL = "Lugar del texto"


def speed_of(item: dict[str, Any]) -> float:
    """A video's speed (1 = normal); photos always 1."""
    if item.get("kind") != "video":
        return 1.0
    return float(item.get("speed", 1) or 1)


def media_length(item: dict[str, Any]) -> float:
    """Seconds the block lasts in the final video: a photo its duration, a video its
    stretch of the source divided by its speed (the block gets shorter at ×10)."""
    if item["kind"] == "photo":
        return float(item["dur"])
    return (float(item["src_end"]) - float(item["src_start"])) / speed_of(item)


def total_seconds(media: list[dict[str, Any]]) -> float:
    """The video's length: the media track has no gaps, so it is the sum of its blocks."""
    return sum(media_length(item) for item in media)


def _media_name(item: dict[str, Any], n: int, m: int) -> tuple[str, str, str]:
    """(short label, full accessible name, panel title)."""
    length = amount(media_length(item))
    if item["kind"] == "photo":
        return (
            f"Foto {n}",
            f"Foto {n} de {m}, se ve {length} s",
            f"Foto {n} · {length} s",
        )
    start, end = clock(item["src_start"]), clock(item["src_end"])
    return (
        f"Video {n}",
        f"Video {n} de {m}, usas de {start} a {end}, dura {length} s",
        f"Video {n} · usas {start} a {end} · {length} s",
    )


def media_blocks(media: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The «Fotos y videos» track as rendered rows, laid end to end from 0:00.

    Every value is a string: ``start``/``length`` (seconds of the final video, for the
    CSS), ``label``/``name``/``panel`` (copy), and the two handles (``*_handle`` name,
    ``*_text`` value text, ``*_now``/``*_min``/``*_max`` for ARIA; a photo has no start
    handle: ``has_start`` is "")."""
    rows: list[dict[str, str]] = []
    at = 0.0
    m = len(media)
    for n, item in enumerate(media, start=1):
        length = media_length(item)
        label, name, panel = _media_name(item, n, m)
        if item["kind"] == "photo":
            handles = {
                "has_start": "",
                "start_label": "",
                "end_label": "Duración",
                "start_text": "",
                "end_text": f"Se ve {amount(length)} s",
                "start_value": "",
                "end_value": f"Se ve {amount(length)} s",
                "start_now": "0",
                "start_min": "0",
                "start_max": "0",
                "end_now": num(length),
                "end_min": num(PHOTO_MIN_S),
                "end_max": num(PHOTO_MAX_S),
            }
        else:
            src_len = float(item["src_len"])
            handles = {
                "has_start": "1",
                "start_label": "Desde",
                "end_label": "Hasta",
                "start_text": clock(item["src_start"]),
                "end_text": clock(item["src_end"]),
                # the handles' `aria-valuetext` and the drag's bubble (ED-03 UX review)
                "start_value": f"Desde {clock_exact(item['src_start'])}",
                "end_value": f"Hasta {clock_exact(item['src_end'])}",
                "start_now": num(item["src_start"]),
                "start_min": "0",
                "start_max": num(float(item["src_end"]) - MIN_S),
                "end_now": num(item["src_end"]),
                "end_min": num(float(item["src_start"]) + MIN_S),
                "end_max": num(src_len),
            }
        rows.append(
            {
                "id": str(item["id"]),
                "track": TRACK_MEDIA,
                "kind": str(item["kind"]),
                "label": label,
                "name": name,
                "panel": panel,
                "help": MOVE_HELP,
                "help_id": HELP_IDS[MOVE_HELP],
                # ED-11 (m-25026650): its picture, a path the screen prefixes with the
                # backend's origin ("" = the film / photo icon), and its seconds over it
                "thumb": str(item.get("thumb", "")),
                "secs": f"{amount(length)} s",
                "speed": _speed_value(item),
                "speed_tag": f"×{_speed_value(item)}" if speed_of(item) > 1 else "",
                "place": "",
                # ED-03: laid end to end to the hundredth, from the same running sum, so
                # a block always ends exactly where the next one starts (no gap)
                "start": exact(at),
                "length": exact(round(at + length, 2) - round(at, 2)),
                # ED-03: «Inicio de video 2» / «Final de video 2» (the noun in lower case)
                "start_handle": f"Inicio de {label[:1].lower()}{label[1:]}",
                "end_handle": f"Final de {label[:1].lower()}{label[1:]}",
                **handles,
            }
        )
        at += length
    return rows


def _overlay_names(item: dict[str, Any]) -> tuple[str, str, str]:
    start, end = clock(item["start"]), clock(item["end"])
    if item["kind"] == "text":
        short = f"«{item['label']}»"
        return short, f"Texto {short}, de {start} a {end}", f"Texto {short} · de {start} a {end}"
    label = str(item["label"])
    return label, f"{label}, de {start} a {end}", f"{label} · de {start} a {end}"


def overlay_blocks(overlays: list[dict[str, Any]], kind: str, total: float) -> list[dict[str, str]]:
    """The «Textos» (``kind="text"``) or «Efectos» (``"effect"``) track as rendered rows.
    ED-04: ``lane`` is the row of «Efectos» an effect sits on ("0" for the first)."""
    rows: list[dict[str, str]] = []
    for item in overlays:
        if item["kind"] != kind:
            continue
        label, name, panel = _overlay_names(item)
        start, end = float(item["start"]), float(item["end"])
        rows.append(
            {
                "id": str(item["id"]),
                "track": kind,
                "kind": kind,
                "label": label,
                "name": name,
                "panel": panel,
                "help": EFFECT_HELP if kind == "effect" else TIME_HELP,
                "help_id": HELP_IDS[EFFECT_HELP if kind == "effect" else TIME_HELP],
                "thumb": "",
                "secs": "",
                "speed": "1",
                "speed_tag": "",
                "place": str(item.get("place", "")),
                # ED-04: an effect stuck to its blocks starts and ends where they do (to
                # the hundredth, as «Fotos y videos» lays them), never ½ s off
                "start": exact(start),
                "length": exact(round(end, 2) - round(start, 2)),
                # ED-04: the row of «Efectos» it sits on (0 for a text)
                "lane": str(int(item.get("lane") or 0)),
                "start_handle": f"Inicio de {label}",
                "end_handle": f"Final de {label}",
                "has_start": "1",
                "start_label": "Empieza",
                "end_label": "Termina",
                "start_text": clock(start),
                "end_text": clock(end),
                "start_value": f"Empieza {clock(start)}",
                "end_value": f"Termina {clock(end)}",
                "start_now": num(start),
                "start_min": "0",
                "start_max": num(end - MIN_S),
                "end_now": num(end),
                "end_min": num(start + MIN_S),
                "end_max": num(total),
            }
        )
    return rows


def _speed_value(item: dict[str, Any]) -> str:
    speed = speed_of(item)
    return str(int(speed)) if speed == int(speed) else str(speed)


def set_speed(media: list[dict[str, Any]], block_id: str, value: str) -> list[dict[str, Any]]:
    """«Velocidad» of one video: only the offered speeds; anything else leaves it."""
    allowed = {v for v, _, _ in SPEEDS}
    return [
        {**item, "speed": float(value)}
        if item["id"] == block_id and item["kind"] == "video" and value in allowed
        else dict(item)
        for item in media
    ]


def set_place(overlays: list[dict[str, Any]], block_id: str, value: str) -> list[dict[str, Any]]:
    """Where one text goes: «Arriba», «En el medio» or «Abajo»."""
    allowed = {v for v, _ in PLACES}
    return [
        {**item, "place": value}
        if item["id"] == block_id and item["kind"] == "text" and value in allowed
        else dict(item)
        for item in overlays
    ]


def ticks(total: float) -> list[dict[str, str]]:
    """The ruler: one mark per whole second, «0:00» … the end."""
    return [{"at": str(s), "text": clock(s)} for s in range(int(math.floor(total)) + 1)]


def find_block(rows: list[dict[str, str]], block_id: str) -> dict[str, str]:
    """The row with that id, or an empty row (nothing chosen)."""
    return next((row for row in rows if row["id"] == block_id), {})


# ---------------------------------------------------------------------------------------
# Edits (keyboard of §3.7 and the panel's «− ½ s / + ½ s»)
# ---------------------------------------------------------------------------------------


def _fit_overlays(overlays: list[dict[str, Any]], total: float) -> list[dict[str, Any]]:
    """Texts and effects stay at their time; one that ends after the video is cut to the
    new end (§3.5), never shorter than the minimum."""
    fitted = []
    for item in overlays:
        end = min(float(item["end"]), total)
        start = min(float(item["start"]), max(end - MIN_S, 0.0))
        fitted.append({**item, "start": start, "end": end})
    return fitted


def nudge(
    media: list[dict[str, Any]],
    overlays: list[dict[str, Any]],
    block_id: str,
    edge: str,
    delta: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Move one edge (``"start"``/``"end"``) of a block by ``delta`` seconds, snapped
    and clamped: a video stays inside its source and at least 1 s long; a photo lasts
    1–5 s (only its end moves); a text or effect stays inside the video. The media track
    closes up (no gaps) and the overlays are fitted to the new length."""
    media = [dict(item) for item in media]
    overlays = [dict(item) for item in overlays]
    for item in media:
        if item["id"] != block_id:
            continue
        if item["kind"] == "photo":
            if edge == "end":
                item["dur"] = min(max(snap(item["dur"] + delta), PHOTO_MIN_S), PHOTO_MAX_S)
        elif edge == "start":
            item["src_start"] = min(
                max(snap(item["src_start"] + delta), 0.0), item["src_end"] - MIN_S
            )
        else:
            item["src_end"] = min(
                max(snap(item["src_end"] + delta), item["src_start"] + MIN_S),
                float(item["src_len"]),
            )
        return media, _fit_overlays(overlays, total_seconds(media))
    total = total_seconds(media)
    for item in overlays:
        if item["id"] != block_id:
            continue
        if edge == "start":
            item["start"] = min(max(snap(item["start"] + delta), 0.0), item["end"] - MIN_S)
        else:
            item["end"] = min(max(snap(item["end"] + delta), item["start"] + MIN_S), total)
    return media, overlays


def shift(
    overlays: list[dict[str, Any]], block_id: str, delta: float, total: float
) -> list[dict[str, Any]]:
    """←/→ on a text or effect: the whole block moves ½ s, same length, inside the video."""
    moved = []
    for item in overlays:
        if item["id"] == block_id:
            length = float(item["end"]) - float(item["start"])
            start = min(max(snap(item["start"] + delta), 0.0), max(total - length, 0.0))
            item = {**item, "start": start, "end": start + length}
        moved.append(item)
    return moved


def move_to(media: list[dict[str, Any]], block_id: str, index: int) -> list[dict[str, Any]]:
    """A video or photo dropped at ``index`` (drag and drop, ED-10): it leaves its place
    and the others close up (remove-then-insert, `assets/timeline-drag-core.js`'s
    `layoutShifts`); an index past either end lands at that end. Never a gap."""
    order = [dict(item) for item in media]
    at = next((i for i, item in enumerate(order) if item["id"] == block_id), None)
    if at is None:
        return order
    item = order.pop(at)
    order.insert(min(max(int(index), 0), len(order)), item)
    return order


def px_to_seconds(px: float, px_per_second: float) -> float:
    """A horizontal drag of ``px`` pixels in seconds at the track's scale (0 without one)."""
    return float(px) / float(px_per_second) if px_per_second > 0 else 0.0


def track_scale(*, phone: bool, width: float = 0.0, total: float = 0.0) -> float:
    """Pixels per second: a phone's fixed 44 px (D-T5); a desktop's tracks fill the width,
    so the width over the video's seconds."""
    if phone or total <= 0 or width <= 0:
        return float(PX_PER_SECOND)
    return float(width) / float(total)


def seconds_from_drag(
    start: float, px: float, px_per_second: float, *, length: float, total: float
) -> float:
    """A text or effect dragged ``px`` pixels: its new start on the ½ s magnet (a half
    rounds up, like the script), never before 0:00 nor ending after the video — the same
    number `assets/timeline-drag-core.js` `shiftedStart` shows in the bubble."""
    moved = math.floor((float(start) + px_to_seconds(px, px_per_second)) / STEP_S + 0.5)
    return min(max(moved * STEP_S, 0.0), max(float(total) - float(length), 0.0))


def move(media: list[dict[str, Any]], block_id: str, step: int) -> list[dict[str, Any]]:
    """←/→ on a video or photo: it swaps places with its neighbour (D-T6, like UI-3)."""
    order = [dict(item) for item in media]
    index = next((i for i, item in enumerate(order) if item["id"] == block_id), None)
    if index is None:
        return order
    target = index + step
    if 0 <= target < len(order):
        order[index], order[target] = order[target], order[index]
    return order


def moved_text(media: list[dict[str, Any]], block_id: str) -> str:
    """The live line after a move (§4): «Moviste el video {n}.» / «Moviste la foto {n}.»,
    with ``n`` its new place."""
    for n, item in enumerate(media, start=1):
        if item["id"] == block_id:
            noun = "la foto" if item["kind"] == "photo" else "el video"
            return f"Moviste {noun} {n}."
    return ""


def timed_text(overlays: list[dict[str, Any]], block_id: str) -> str:
    """The live line after a text or effect changed its time (§4)."""
    for item in overlays:
        if item["id"] == block_id:
            if item["kind"] == "text":
                return "Cambiaste cuándo sale el texto."
            return f"Cambiaste cuándo sale {item['label']}."
    return ""
