"""The POST's thermal animations, as code (docs/ux-post-journey-termico.md §3).

Six hand-made Lottie files — flame, steam, freeze, thaw, scheduled, published — built here as
plain dicts and written to ``assets/lottie/*.json``. Nothing is downloaded from
LottieFiles: every animation is a shape layer (``ty: 4``) with a few keyframes, so each
file stays well under 5 KB and carries exactly the colours of the design tokens.

Why generate instead of hand-edit JSON: a Lottie file is keyframes and bezier tangents,
unreadable in a diff. The *shape* of each animation (what moves, how long, which tone)
is readable here; ``test_lottie_assets.py`` pins that the committed files equal this
module's output, so the JSON can never drift from the source that explains it.

Colours are Radix **step 9** of the tone's scale (``ui.tokens.TONE_SCALE``). Step 9 is
the one step Radix keeps identical in light and dark for every scale used here (amber,
blue, grass, tomato) — verified against ``@radix-ui/colors`` 2026-10-05 — so a baked
colour reads the same in both themes without a CSS override. ``slate`` is the exception
(``#8b8d98`` light / ``#696e77`` dark), which is why the neutral states have no
animation at all: they are static lucide icons.

Format notes (lottie-web ≥ 5.7, the engine ``lottie-react`` ships):
- a keyframe is ``{"t", "s", "i", "o"}``; the last keyframe carries only ``t`` and ``s``;
- ``i``/``o`` easing handles are per dimension, so a 2-D property gets 2-element arrays;
- shapes use relative bezier tangents (``i``/``o`` offsets from each vertex ``v``);
- ``tm`` (trim paths) is what "draws" a stroke: ``e`` animated 0 → 100.

Regenerate: ``python -m Qualify.ui.lottie_shapes`` from the repo root (no Reflex needed).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------------------
# Tokens, as numbers. The hex values are Radix step 9 (see module docstring); the RGB
# floats are what Lottie wants. `TONE_HEX` is the public table the tests and the doc use.
# ---------------------------------------------------------------------------------------

TONE_HEX: dict[str, str] = {
    "warn": "#ffc53d",  # amber-9 — the hot side (caliente, humeante)
    "info": "#0090ff",  # blue-9 — the cold side (congelado, programado)
    "ok": "#46a758",  # grass-9 — publicado
    "error": "#e54d2e",  # tomato-9 — fallido (declared; no animation uses it, by rule)
}

CANVAS = 48
FPS = 60
CENTER = CANVAS / 2

# Easing presets — the design system's two curves, as Lottie handles. `EASE` is
# `--q-ease` (.22,.8,.25,1) and `SPRING` approximates `--q-spring`'s overshoot with a
# steep out-handle (Lottie cannot express y > 1 on the in-handle of a 1-D property
# without a second keyframe, so the overshoot is written as an explicit keyframe where
# it matters — see `freeze`).
EASE = ((0.22, 0.8), (0.25, 1.0))
LINEAR = ((0.0, 0.0), (1.0, 1.0))
# (out handle, in handle) as (x, y) pairs — lottie's `o` is the handle leaving the
# keyframe, `i` the handle arriving at the next one.


def _rgb(hex_colour: str) -> list[float]:
    h = hex_colour.lstrip("#")
    return [round(int(h[i : i + 2], 16) / 255, 4) for i in (0, 2, 4)] + [1]


def _static(value: Any) -> dict[str, Any]:
    return {"a": 0, "k": value}


def _kf(
    frames: list[tuple[int, list[float]]], easing: tuple[tuple[float, float], ...] = EASE
) -> dict[str, Any]:
    """An animated property from ``[(frame, value), ...]``. Every segment gets the same
    easing; the last keyframe is a plain ``{"t", "s"}``."""
    (ox, oy), (ix, iy) = easing
    keys: list[dict[str, Any]] = []
    for n, (t, value) in enumerate(frames):
        dims = len(value)
        key: dict[str, Any] = {"t": t, "s": value}
        if n < len(frames) - 1:
            key["o"] = {"x": [ox] * dims, "y": [oy] * dims}
            key["i"] = {"x": [ix] * dims, "y": [iy] * dims}
        keys.append(key)
    return {"a": 1, "k": keys}


def _transform(
    *,
    position: Any = None,
    scale: Any = None,
    rotation: Any = None,
    opacity: Any = None,
    anchor: list[float] | None = None,
) -> dict[str, Any]:
    """A shape-group transform (``ty: tr``). Animated values are passed already wrapped
    (``_kf``); plain values are wrapped static."""

    def wrap(value: Any, default: Any) -> dict[str, Any]:
        if value is None:
            return _static(default)
        return value if isinstance(value, dict) and "a" in value else _static(value)

    return {
        "ty": "tr",
        "p": wrap(position, [0, 0]),
        "a": _static(anchor or [0, 0]),
        "s": wrap(scale, [100, 100]),
        "r": wrap(rotation, 0),
        "o": wrap(opacity, 100),
        "sk": _static(0),
        "sa": _static(0),
    }


def _fill(tone: str, opacity: float = 100) -> dict[str, Any]:
    return {"ty": "fl", "c": _static(_rgb(TONE_HEX[tone])), "o": _static(opacity), "r": 1}


def _stroke(tone: str, width: float, opacity: float = 100) -> dict[str, Any]:
    # lc/lj 2 = round caps and joins: the only line ending the icon set (lucide) uses.
    return {
        "ty": "st",
        "c": _static(_rgb(TONE_HEX[tone])),
        "o": _static(opacity),
        "w": _static(width),
        "lc": 2,
        "lj": 2,
    }


def _trim(start: Any, end: Any) -> dict[str, Any]:
    return {"ty": "tm", "s": start, "e": end, "o": _static(0), "m": 1}


def _path(
    vertices: list[list[float]],
    in_tangents: list[list[float]] | None = None,
    out_tangents: list[list[float]] | None = None,
    closed: bool = False,
) -> dict[str, Any]:
    n = len(vertices)
    zeros = [[0, 0] for _ in range(n)]
    return {
        "ty": "sh",
        "d": 1,
        "ks": _static(
            {"i": in_tangents or zeros, "o": out_tangents or zeros, "v": vertices, "c": closed}
        ),
    }


def _ellipse(size: float, at: list[float] | None = None) -> dict[str, Any]:
    return {"ty": "el", "d": 1, "s": _static([size, size]), "p": _static(at or [0, 0])}


def _group(*items: dict[str, Any], name: str = "g") -> dict[str, Any]:
    return {"ty": "gr", "nm": name, "it": list(items)}


def _layer(
    name: str, shapes: list[dict[str, Any]], *, end: int, ks: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One shape layer (``ty: 4``) centred on the canvas."""
    transform = {
        "o": _static(100),
        "r": _static(0),
        "p": _static([CENTER, CENTER, 0]),
        "a": _static([0, 0, 0]),
        "s": _static([100, 100, 100]),
    }
    if ks:
        transform.update(ks)
    return {
        "ddd": 0,
        "ind": 1,
        "ty": 4,
        "nm": name,
        "sr": 1,
        "ks": transform,
        "ao": 0,
        "shapes": shapes,
        "ip": 0,
        "op": end,
        "st": 0,
        "bm": 0,
    }


def _animation(name: str, layers: list[dict[str, Any]], *, end: int) -> dict[str, Any]:
    return {
        "v": "5.7.4",
        "fr": FPS,
        "ip": 0,
        "op": end,
        "w": CANVAS,
        "h": CANVAS,
        "nm": name,
        "ddd": 0,
        "assets": [],
        "layers": layers,
        "markers": [],
    }


# ---------------------------------------------------------------------------------------
# The five animations
# ---------------------------------------------------------------------------------------


def flame() -> dict[str, Any]:
    """Caliente — loops. A teardrop that breathes (taller/narrower, then back) with a
    smaller inner tongue breathing out of phase. 1 s per cycle; first and last keyframes
    equal, so the loop has no seam."""
    end = FPS
    outer = _path(
        vertices=[[0, -17], [12, 3], [0, 15], [-12, 3]],
        in_tangents=[[-6, 0], [0, -8], [7, 0], [0, 6]],
        out_tangents=[[6, 0], [0, 6], [-7, 0], [0, -8]],
        closed=True,
    )
    inner = _path(
        vertices=[[0, -4], [5.5, 7], [0, 13], [-5.5, 7]],
        in_tangents=[[-3, 0], [0, -4], [3, 0], [0, 3]],
        out_tangents=[[3, 0], [0, 3], [-3, 0], [0, -4]],
        closed=True,
    )
    breathe = _kf([(0, [100, 100]), (30, [91, 108]), (end, [100, 100])])
    sway = _kf([(0, [0]), (30, [-4]), (end, [0])])
    inner_breathe = _kf([(0, [96, 104]), (30, [104, 96]), (end, [96, 104])])
    shapes = [
        _group(
            outer,
            _fill("warn"),
            _transform(scale=breathe, rotation=sway, anchor=[0, 15]),
            name="outer",
        ),
        _group(
            inner, _fill("warn", 55), _transform(scale=inner_breathe, anchor=[0, 13]), name="inner"
        ),
    ]
    return _animation("flame", [_layer("flame", shapes, end=end)], end=end)


def _sample(frames: list[tuple[int, list[float]]], at: float) -> list[float]:
    """Linear interpolation of a keyframe list at frame ``at``."""
    for (t0, v0), (t1, v1) in zip(frames, frames[1:], strict=False):
        if t0 <= at <= t1:
            f = 0 if t1 == t0 else (at - t0) / (t1 - t0)
            return [round(a + (b - a) * f, 2) for a, b in zip(v0, v1, strict=True)]
    return list(frames[-1][1])


def _phase_shift(
    frames: list[tuple[int, list[float]]], offset: int, end: int
) -> list[tuple[int, list[float]]]:
    """The same cyclic keyframes started ``offset`` frames into their cycle, so that
    several copies of one motion run staggered. Lottie has no per-shape time offset, so
    the cycle is rotated: it wraps once, in a single-frame seam at ``end - offset`` —
    invisible as long as the value at frame 0 and at ``end`` are both "off" (opacity 0),
    which every use here guarantees."""
    if offset == 0:
        return frames
    before = [(t - offset, v) for t, v in frames if offset < t < end]
    after = [(t + end - offset, v) for t, v in frames if 0 < t < offset]
    return [
        (0, _sample(frames, offset)),
        *before,
        (end - offset, _sample(frames, end)),
        (end - offset + 1, _sample(frames, 0)),
        *after,
        (end, _sample(frames, offset)),
    ]


def steam() -> dict[str, Any]:
    """Humeante — loops. Three wisps (stroked S-curves) rise and fade, staggered by a
    third of the cycle each. 2 s per cycle."""
    end = 2 * FPS
    wisps: list[dict[str, Any]] = []
    for n, x in enumerate((-9, 0, 9)):
        offset = n * (end // 3)
        rise = [(0, [x, 10.0]), (end, [x, -14.0])]
        fade = [(0, [0.0]), (end // 3, [85.0]), ((2 * end) // 3, [60.0]), (end, [0.0])]
        wisp = _path(
            vertices=[[0, 8], [0, 0], [0, -8]],
            in_tangents=[[0, 0], [-4, 2], [0, 0]],
            out_tangents=[[4, -2], [0, 0], [0, 0]],
        )
        wisps.append(
            _group(
                wisp,
                _stroke("warn", 2.6),
                _transform(
                    position=_kf(_phase_shift(rise, offset, end), LINEAR),
                    opacity=_kf(_phase_shift(fade, offset, end), LINEAR),
                ),
                name=f"wisp{n}",
            )
        )
    return _animation("steam", [_layer("steam", wisps, end=end)], end=end)


def freeze() -> dict[str, Any]:
    """Congelar — plays once (0.8 s). A six-arm snowflake grows from its centre: three
    stroked lines drawn outwards from the middle by a trim path, while the whole flake
    scales up with a small overshoot and settles. Played in reverse it melts — that is
    the "descongelar" animation, the same file."""
    end = 48
    arms: list[dict[str, Any]] = []
    for angle in (0, 60, 120):
        line = _path(vertices=[[0, -17], [0, 17]])
        arms.append(
            _group(
                line,
                _stroke("info", 3),
                _trim(
                    _kf([(0, [50]), (30, [0])]),
                    _kf([(0, [50]), (30, [100])]),
                ),
                _transform(rotation=angle),
                name=f"arm{angle}",
            )
        )
    # Small ticks near each arm's tip, so it reads as a snowflake and not an asterisk.
    ticks: list[dict[str, Any]] = []
    for angle in range(0, 360, 60):
        tick = _path(vertices=[[-4, -10], [0, -14], [4, -10]])
        ticks.append(
            _group(
                tick,
                _stroke("info", 2.4),
                _trim(_static(0), _kf([(18, [0]), (40, [100])])),
                _transform(rotation=angle),
                name=f"tick{angle}",
            )
        )
    core = _group(
        _ellipse(5),
        _fill("info"),
        _transform(scale=_kf([(0, [0, 0]), (14, [100, 100])])),
        name="core",
    )
    whole = _group(
        *arms,
        *ticks,
        core,
        _transform(
            scale=_kf([(0, [60, 60]), (34, [106, 106]), (end, [100, 100])]),
            rotation=_kf([(0, [-30]), (end, [0])]),
        ),
        name="flake",
    )
    return _animation("freeze", [_layer("freeze", [whole], end=end)], end=end)


def scheduled() -> dict[str, Any]:
    """Programado — plays once (1 s). A clock face; the minute hand sweeps a full turn
    and the hour hand follows a twelfth of it, as a real clock would."""
    end = FPS
    face = _group(_ellipse(34), _stroke("info", 3), _transform(), name="face")
    minute = _group(
        _path(vertices=[[0, 0], [0, -12]]),
        _stroke("info", 3),
        _transform(rotation=_kf([(0, [0]), (end, [360])])),
        name="minute",
    )
    hour = _group(
        _path(vertices=[[0, 0], [0, -8]]),
        _stroke("info", 3),
        _transform(rotation=_kf([(0, [60]), (end, [90])])),
        name="hour",
    )
    pin = _group(_ellipse(4), _fill("info"), _transform(), name="pin")
    return _animation("scheduled", [_layer("clock", [face, minute, hour, pin], end=end)], end=end)


def published() -> dict[str, Any]:
    """Publicado — plays once (0.8 s). The ring draws itself, then the check, then a
    tiny pop at the end so the eye lands on it."""
    end = 48
    ring = _group(
        _ellipse(34),
        _stroke("ok", 3),
        _trim(_static(0), _kf([(0, [0]), (28, [100])])),
        _transform(rotation=-90),
        name="ring",
    )
    check = _group(
        _path(vertices=[[-8, 1], [-2, 7], [9, -6]]),
        _stroke("ok", 3.2),
        _trim(_static(0), _kf([(18, [0]), (40, [100])])),
        _transform(),
        name="check",
    )
    whole = _group(
        ring,
        check,
        _transform(scale=_kf([(36, [100, 100]), (42, [108, 108]), (end, [100, 100])])),
        name="published",
    )
    return _animation("published", [_layer("published", [whole], end=end)], end=end)


def _reversed_keyframes(keys: list[dict[str, Any]], end: int) -> list[dict[str, Any]]:
    """The same keyframes played backwards over ``[0, end]``: times mirrored, order
    reversed, and each segment's easing handles swapped and mirrored (the handle that
    left a keyframe now arrives at it)."""
    out: list[dict[str, Any]] = []
    for n, key in enumerate(reversed(keys)):
        new: dict[str, Any] = {"t": end - key["t"], "s": key["s"]}
        if n < len(keys) - 1:
            # The segment that now LEAVES this keyframe is the old segment that ARRIVED
            # here, i.e. the one starting at the previous original keyframe.
            prev = keys[len(keys) - 2 - n]
            o, i = prev["o"], prev["i"]
            new["o"] = {"x": [1 - v for v in i["x"]], "y": [1 - v for v in i["y"]]}
            new["i"] = {"x": [1 - v for v in o["x"]], "y": [1 - v for v in o["y"]]}
        out.append(new)
    return out


def _time_reversed(node: Any, end: int) -> Any:
    if isinstance(node, dict):
        if node.get("a") == 1 and isinstance(node.get("k"), list):
            return {"a": 1, "k": _reversed_keyframes(node["k"], end)}
        return {key: _time_reversed(value, end) for key, value in node.items()}
    if isinstance(node, list):
        return [_time_reversed(value, end) for value in node]
    return node


def thaw() -> dict[str, Any]:
    """Descongelar — plays once (0.8 s). Exactly `freeze` played backwards, shipped as
    its own file: a reversed *autoplay* is unreliable in lottie-web (verified 2026-10-05
    — `initialSegment` with a descending range draws nothing, and `setDirection(-1)` on
    a fresh load completes at frame 0 before drawing), so the reversal is done here,
    where it is a pure function of the forward file."""
    data = _time_reversed(freeze(), 48)
    data["nm"] = "thaw"
    data["layers"][0]["nm"] = "thaw"
    return data


#: name -> builder. The file is ``assets/lottie/<name>.json``.
ANIMATIONS: dict[str, Any] = {
    "flame": flame,
    "steam": steam,
    "freeze": freeze,
    "thaw": thaw,
    "scheduled": scheduled,
    "published": published,
}

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "lottie"


def render(name: str) -> str:
    """The exact text written for ``name`` — compact JSON, stable key order."""
    return json.dumps(ANIMATIONS[name](), separators=(",", ":"), sort_keys=True) + "\n"


def write_all(target: Path = ASSETS_DIR) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in ANIMATIONS:
        path = target / f"{name}.json"
        path.write_text(render(name), encoding="utf-8")
        written.append(path)
    return written


if __name__ == "__main__":
    for written_path in write_all():
        print(f"{written_path.relative_to(ASSETS_DIR.parents[1])}  {written_path.stat().st_size} B")
