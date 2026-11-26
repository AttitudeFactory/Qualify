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
from collections.abc import Mapping, Sequence
from typing import Any

#: The magnet (§3.3): every edge lands on a half second.
STEP_S = 0.5
#: «Cada bloque dura al menos 1 segundo.»
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


def tail_length(item: dict[str, Any]) -> float:
    """Seconds the block's end overlaps the next block's transition (`tail_s`, m-25114465;
    0 = a cut)."""
    try:
        return max(float(item.get("tail_s") or 0.0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def shown_length(item: dict[str, Any]) -> float:
    """Seconds the block takes on the track: its length less its `tail_length` — the next
    block starts where its transition starts (m-25114465)."""
    return max(media_length(item) - tail_length(item), 0.0)


def total_seconds(media: list[dict[str, Any]]) -> float:
    """The video's length: the media track has no gaps, so it is the sum of its blocks
    (each less the transition into the next one, m-25114465)."""
    return sum(shown_length(item) for item in media)


def media_label(item: Mapping[str, Any], n: int) -> str:
    """A «Fotos y videos» block's short name, as the track shows it: «Foto 2», «Video 1»
    (`n`: its place on the track, from 1). The joins' words name blocks with it."""
    return f"Foto {n}" if item.get("kind") == "photo" else f"Video {n}"


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


#: A row with no frame strip (`strip_style`'s fields, empty).
_NO_STRIP = {"strip": "", "strip_size": "", "strip_ratio": "", "strip_w": ""}


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
        shown = shown_length(item)
        # its own transition in (`join_s`, on the block that comes in: the block before it
        # may be one of no length, skipped by the recipe — review)
        join_in = max(float(item.get("join_s") or 0.0), 0.0) if item.get("join") else 0.0
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
                # ED-11b: its frame strip ("" until the screen lays one, `strip_style`)
                **_NO_STRIP,
                "secs": f"{amount(length)} s",
                "speed": _speed_value(item),
                "speed_tag": f"×{_speed_value(item)}" if speed_of(item) > 1 else "",
                "place": "",
                "warn": "",
                # ED-03: laid end to end to the hundredth, from the same running sum, so
                # a block always ends exactly where the next one starts (no gap).
                # m-25114465 (Deivid 2026-11-26, «bloques enteros, encimados»): each
                # block is drawn WHOLE; with a transition into the next one, that next
                # block starts where it really starts (its end less the transition) and
                # is drawn over this one's end — the overlap is the transition
                "start": exact(at),
                "length": exact(round(at + length, 2) - round(at, 2)),
                # the seconds of its start laid over the block before (its transition
                # in, "0" for a cut) and which transition it is (`join_kind`)
                "join_in": exact(join_in),
                "join_kind": str(item.get("join") or "") if join_in > 0 else "",
                # ED-03: «Inicio de video 2» / «Final de video 2» (the noun in lower case)
                "start_handle": f"Inicio de {label[:1].lower()}{label[1:]}",
                "end_handle": f"Final de {label[:1].lower()}{label[1:]}",
                # ED-14: the id of a line saying why a handle stops ("" = none; a photo's
                # row gets one at 1 s or 5 s, `clip_photos_vm.photo_row_fields`)
                "start_why": "",
                "end_why": "",
                # ED-14: the first block starts the track, the last ends it — that handle
                # sits inside the block, never past the track (`.q-tl__item[data-tl-at-*]`)
                "at_start": "1" if n == 1 else "",
                "at_end": "1" if n == m else "",
                **handles,
            }
        )
        at += shown
    return rows


# -- ED-11b (m-25029110): the frame strip under a video block ---------------------------
#
# The server makes ONE JPEG per uploaded video: a tile per second of the video, `56` px
# high, `columns` tiles a row (`qualify_api.creative.upload_previews.FrameStrip`). Tile `i`
# shows the video at second `i * interval_s + offset_s` (the middle of `[i, i+1)`).
#
# The block shows the tiles of the stretch it uses, at its speed: a CELL per stretch of
# `interval_s × speed` seconds of the video (one second of the ruler; at ×1 exactly the
# tile's own second), each showing the tile nearest its middle. Everything is in SECONDS
# from the block's start and the CSS turns them into a share of the block's own width
# (`--c-at` / `--b-len`), so the cells follow the phone's 44 px a second, the desktop's
# fitted width and any later scale without being computed again.

#: The «Fotos y videos» track's height (`.q-tl__lane--media`): a tile is drawn this high.
MEDIA_TRACK_PX = 56
#: At most this many cells a block (review: a 5 min video before any cut, at ×1): past it,
#: each cell takes several seconds of the ruler and shows the tile of its middle.
MAX_STRIP_CELLS = 60


def _pct(value: float) -> str:
    """A CSS percentage, to the ten-thousandth («33.3333%», «0%»)."""
    value = round(float(value), 4)
    return f"{int(value)}%" if value == int(value) else f"{value:g}%"


def strip_style(
    url: str, *, columns: int, rows: int, tile_width: int, tile_height: int
) -> dict[str, str]:
    """The fields a video row gains when its file has a strip (strings, as every row's):
    the picture's path (``strip``, prefixed with the backend's origin by the screen),
    ``strip_size`` (the whole image over one tile: ``columns×100% rows×100%``),
    ``strip_ratio`` (a tile's width over its height) and ``strip_w`` (a tile's width at
    the track's height). Empty values for a strip that does not add up."""
    if not url or columns < 1 or rows < 1 or tile_width < 1 or tile_height < 1:
        return dict(_NO_STRIP)
    ratio = tile_width / tile_height
    return {
        "strip": url,
        "strip_size": f"{columns * 100}% {rows * 100}%",
        "strip_ratio": f"{round(ratio, 4):g}",
        "strip_w": f"{round(ratio * MEDIA_TRACK_PX, 2):g}px",
    }


def strip_cells(
    src_start: float,
    src_end: float,
    speed: float,
    *,
    frames: int,
    columns: int,
    rows: int,
    interval_s: float = 1.0,
    offset_s: float = 0.5,
    max_cells: int = MAX_STRIP_CELLS,
) -> list[dict[str, str]]:
    """What the screen draws of `strip_plan`: each cell's ``at``, ``len`` and ``pos``."""
    plan = strip_plan(
        src_start,
        src_end,
        speed,
        frames=frames,
        columns=columns,
        rows=rows,
        interval_s=interval_s,
        offset_s=offset_s,
        max_cells=max_cells,
    )
    return [{"at": c["at"], "len": c["len"], "pos": c["pos"]} for c in plan]


def strip_plan(
    src_start: float,
    src_end: float,
    speed: float,
    *,
    frames: int,
    columns: int,
    rows: int,
    interval_s: float = 1.0,
    offset_s: float = 0.5,
    max_cells: int = MAX_STRIP_CELLS,
) -> list[dict[str, str]]:
    """The cells of a video block's strip — which tile goes where — for the stretch
    ``src_start``…``src_end`` (seconds of the video) played at ``speed``.

    Each cell: ``at`` and ``len`` (seconds of the ruler from the block's start, to the
    hundredth), ``pos`` (the tile's ``background-position`` in the image, percentages
    that hold at any drawn size), ``tile`` (its index) and ``shows`` (the second of the
    video its picture is). The cells lie end to end over the whole block, never a gap;
    each one's picture is the tile nearest its middle, so the frame of second *s* falls
    on the ruler within ½ s of where the block plays it. A cell is one second of the
    ruler; a block that would need more than ``max_cells`` groups several seconds a cell
    (same rule: the tile of its middle).

    A stretch past the strip (a video longer than the strip's hour, or the last part of a
    second the strip has no tile for) takes the last tile when it is close (the tail of a
    20,4 s video joins the cell before it) and no cell when it is far: never a wrong
    frame. Pure."""
    start, end = float(src_start), float(src_end)
    speed = max(float(speed or 1.0), 1e-6)
    if end - start <= 1e-6 or frames < 1 or columns < 1 or rows < 1 or interval_s <= 0:
        return []
    step = float(interval_s) * max(speed, 1.0)
    needed = math.ceil(end / step - 1e-9) - math.floor(start / step + 1e-9)
    if max_cells > 0 and needed > max_cells:
        step *= math.ceil(needed / max_cells)
    last = frames - 1
    cells: list[dict[str, Any]] = []
    k = math.floor(start / step + 1e-9)
    while k * step < end - 1e-9:
        a, b = max(k * step, start), min((k + 1) * step, end)
        k += 1
        if b - a <= 1e-9:
            continue
        middle = (a + b) / 2
        tile = math.floor((middle - offset_s) / interval_s + 0.5)
        tile = min(max(tile, 0), last)
        shows = tile * interval_s + offset_s
        off = abs(shows - middle)
        if off > interval_s / 2 + 1e-9:  # the nearest tile is past the strip's end
            if off > interval_s + 1e-9:
                continue  # far past the strip: no frame rather than a wrong one
            if cells and cells[-1]["tile"] == tile and abs(cells[-1]["b"] - a) < 1e-9:
                cells[-1]["b"] = b  # a short tail joins the cell that shows its tile
                continue
        cells.append({"a": a, "b": b, "tile": tile, "shows": shows})
    out: list[dict[str, str]] = []
    for cell in cells:
        tile = int(cell["tile"])
        col, row = tile % columns, tile // columns
        x = col / (columns - 1) * 100 if columns > 1 else 0.0
        y = row / (rows - 1) * 100 if rows > 1 else 0.0
        at = round((cell["a"] - start) / speed, 2)
        out.append(
            {
                "at": exact(at),
                "len": exact(round((cell["b"] - start) / speed, 2) - at),
                "pos": f"{_pct(x)} {_pct(y)}",
                "tile": str(tile),
                "shows": exact(cell["shows"]),
            }
        )
    return out


def _overlay_names(item: dict[str, Any]) -> tuple[str, str, str]:
    start, end = clock(item["start"]), clock(item["end"])
    if item["kind"] == "text":
        short = f"«{item['label']}»"
        return short, f"Texto {short}, de {start} a {end}", f"Texto {short} · de {start} a {end}"
    label = str(item["label"])
    return label, f"{label}, de {start} a {end}", f"{label} · de {start} a {end}"


def overlay_blocks(overlays: list[dict[str, Any]], kind: str, total: float) -> list[dict[str, str]]:
    """The «Textos» (``kind="text"``) or «Efectos» (``"effect"``) track as rendered rows.
    ED-04: ``lane`` is the row of «Efectos» an effect sits on ("0" for the first).
    ED-13: ``warn`` "1" = the block is in a clash (two texts in one place at once): it
    shows the warning tone; its name stays «Texto «…», de … a …»."""
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
                **_NO_STRIP,
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
                "warn": "1" if item.get("warn") else "",
                # ED-13 (A1): its times change only here, with its two handles
                "handles": "1",
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
                # ED-14: the id of a line saying why a handle stops ("" = none)
                "start_why": "",
                "end_why": "",
                # ED-14: it starts or ends less than a handle's width (1 s on a phone) from
                # an end of the track — that handle sits inside the block, never past the
                # track (`.q-tl__item[data-tl-at-*]`)
                "at_start": "1" if start < MIN_S - 0.005 else "",
                "at_end": "1" if end > total - MIN_S + 0.005 else "",
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


# -- where something new goes (m-25114465: «si hay espacio, que se ponga ahí solo») -------
#
# Deivid 2026-11-24: a new text, effect or other component lands by itself in the FIRST
# free gap where it fits, looking at EVERY row of its kind — never on top of another, never
# refused while there is room. «First» is deterministic:
#
# 1. from the playhead: among the gaps that still have room after the playhead, the one
#    whose usable start (the playhead when it is inside the gap, else the gap's start) is
#    the earliest; a tie goes to the upper row;
# 2. when nothing fits from the playhead: the earliest gap of the whole timeline (from
#    0:00), upper row first on a tie;
# 3. when nothing fits anywhere: None — the caller keeps its rule of before (trimmed to
#    the free room, a new row, or the usual warning).


def free_gaps(obstacles: Sequence[Sequence[float]], total: float) -> list[tuple[float, float]]:
    """The free stretches of a row of a video of `total` s, around `obstacles`."""
    gaps: list[tuple[float, float]] = []
    at = 0.0
    for a, b in sorted((float(a), float(b)) for a, b in obstacles):
        if a > at + 1e-6:
            gaps.append((at, min(a, float(total))))
        at = max(at, b)
    if float(total) > at + 1e-6:
        gaps.append((at, float(total)))
    return [(round(a, 2), round(b, 2)) for a, b in gaps if b - a > 1e-6]


def first_free_slot(
    rows: Sequence[Sequence[Sequence[float]]],
    *,
    total: float,
    playhead: float = 0.0,
    length: float | None = None,
    least: float = MIN_S,
) -> tuple[int, float, float] | None:
    """`(row, start, end)` of the first free gap where something new fits, among `rows`
    (each the spans already on that row) of a video of `total` s — the rule above.

    `length`: the seconds it needs whole; None = it takes the free gap it lands in from
    its start to the gap's end (a text lasts until the next one, or to the end), at
    least `least`. The playhead is first pulled back so that what is needed still fits
    before the end (a text put at the last second still lasts 1 s). Pure."""
    total = float(total)
    need = float(length) if length is not None else float(least)
    if total <= 0 or need <= 0 or need > total + 1e-6:
        return None
    head = min(max(float(playhead), 0.0), max(total - need, 0.0))
    gaps = [(row, gap) for row, spans in enumerate(rows) for gap in free_gaps(spans, total)]

    def earliest(from_head: bool) -> tuple[int, float, float] | None:
        found: tuple[float, int, float] | None = None
        for row, (a, b) in gaps:
            start = max(a, head) if from_head else a
            if b - start < need - 1e-6:
                continue
            key = (round(start, 2), row, b)
            if found is None or key[:2] < found[:2]:
                found = key
        if found is None:
            return None
        start, row, gap_end = found
        return row, start, round(start + need, 2) if length is not None else gap_end

    return earliest(from_head=True) or earliest(from_head=False)


def first_free_row(rows: Sequence[Sequence[Sequence[float]]], span: Sequence[float]) -> int | None:
    """The upper row where `span` — fixed seconds, e.g. an effect on the parts the owner
    marked — is free, or None when it is taken on every row (meeting at a second is
    fine). Pure."""
    start, end = float(span[0]), float(span[1])
    for row, spans in enumerate(rows):
        if not any(start < float(b) - 1e-6 and float(a) < end - 1e-6 for a, b in spans):
            return row
    return None
