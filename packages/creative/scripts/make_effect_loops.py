"""Record the smoke, ember and steam loops of the effects library (EF-08, m-25029102) — US$0,
procedural, reproducible: numpy + PyAV only, fixed seeds, no vendor and no download.

    uv run --no-sync python packages/creative/scripts/make_effect_loops.py [--out DIR]
        [--only ID ...] [--force]

Writes `<DIR>/<id>/v1/preview.webm` for `humo_capa`, `brasas_capa` and `vapor_capa` (default
DIR: the packaged `qualify_creative/effects_assets/`) and copies each byte for byte to the
repo-root `assets/effects/<id>/v1/preview.webm` the editor screen serves (unless `--out` is
given). It REFUSES to overwrite a `preview.webm` that already exists unless `--force` is
given: the published `v1/` bytes are what every composed video's provenance names
(`loop_sha256`), and another libvpx would write other bytes — a new look is a `v2/` folder
and a new library entry, never new bytes in `v1/`. Each loop is a VP9 WebM, 720×1280
(9:16), 30 fps, 4 s, yuv420p BT.709 limited range
(tagged), on a PURE BLACK background: laid with a screen blend, black changes nothing, so no
alpha channel is needed and the browser (`mix-blend-mode: screen`) and the compose
(`video/layer_overlay.py`) lay the same pixels.

Every loop is EXACTLY periodic in time (frame N would be frame 0), so it repeats with no jump:

- **Humo** — a 2-D noise built in the Fourier domain whose every component turns a WHOLE
  number of times per loop (its rise rounded to whole cycles, plus a slow whole-cycle
  evolution), soft-thresholded into wisps, neutral grey, held to the top of the frame.
- **Vapor** — the same kind of field, isotropic and steep (rounded puffs, no strands), over
  a dominant diffuse veil, in a soft white column that starts at the middle (a hot plate)
  and comes apart as it rises (the puffs' threshold climbs with the height).
- **Brasas** — particles: each one rises a whole number of times per loop, wobbles sideways
  and flickers at whole-number frequencies, glowing orange-yellow, fading as it rises from
  the bottom.

Greys are written as R = G = B and converted to YUV here, in numpy, with the BT.709 limited
matrix: a neutral grey is U = V = 128 exactly, so nothing tints.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from collections.abc import Callable, Iterator
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

WIDTH, HEIGHT = 720, 1280
FPS = 30
SECONDS = 4
FRAMES = FPS * SECONDS
#: libvpx-vp9 settings: constant quality, one thread (the same bytes run to run).
VP9_OPTIONS = {
    "crf": "34",
    "b": "0",
    "deadline": "good",
    "cpu-used": "1",
    "row-mt": "0",
    "threads": "1",
    "g": str(FRAMES),
}
EFFECTS = ("humo_capa", "brasas_capa", "vapor_capa")

_ROOT = Path(__file__).resolve().parents[3]
PACKAGED = _ROOT / "packages" / "creative" / "src" / "qualify_creative" / "effects_assets"
SERVED = _ROOT / "assets" / "effects"


def _smoothstep(edge0: float, edge1: float, x: Any) -> Any:
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


class PeriodicField:
    """A real 2-D noise field over the frame whose every Fourier component turns a whole
    number of times per loop: `frame(i)` is periodic in `i` with period `frames`, exactly.

    `rise_px`: how far the field moves up over one loop; each component's temporal
    frequency is that rise rounded to whole cycles (large shapes rise a little less or more
    than fine ones, as real smoke does). `evolve`: an extra random whole-cycle turn per
    component in [-evolve, evolve], so the shapes change as they rise. `scale_y`/`scale_x`
    stretch the spectrum (larger = finer detail along that axis); `slope` its fall-off."""

    def __init__(
        self,
        rng: np.random.Generator,
        *,
        h: int,
        w: int,
        frames: int,
        rise_px: float,
        scale_y: float,
        scale_x: float,
        slope: float,
        evolve: int,
        cutoff: float = 1.0,
    ) -> None:
        self.h, self.w, self.frames = h, w, frames
        ky = np.fft.fftfreq(h, d=1.0 / h)[:, None]  # signed whole cycles over the height
        kx = np.fft.rfftfreq(w, d=1.0 / w)[None, :]
        k = np.sqrt((ky / scale_y) ** 2 + (kx / scale_x) ** 2)
        amp = np.where(k > 0, (k + 1e-9) ** (-slope), 0.0) * (k <= cutoff * 12.0)
        phase = rng.uniform(0.0, 2.0 * np.pi, size=amp.shape)
        self.spectrum = amp * np.exp(1j * phase)
        # rising: G(y + v t) → each component turns ky·rise/h times per loop (rounded)
        turns = np.rint(ky * rise_px / h) + rng.integers(-evolve, evolve + 1, size=amp.shape)
        self.turns = np.broadcast_to(turns, amp.shape).astype(np.float64)
        self.norm = 1.0
        self.norm = float(np.std(self.frame(0))) or 1.0

    def frame(self, index: int) -> Any:
        rotate = np.exp(2j * np.pi * self.turns * (index % self.frames) / self.frames)
        return np.fft.irfft2(self.spectrum * rotate, s=(self.h, self.w)) / self.norm


def _upsample(field: Any, h: int, w: int) -> Any:
    """A low-resolution intensity (float) resized to (h, w), bicubic, clipped to [0, 1]."""
    from PIL import Image  # noqa: PLC0415

    image = Image.fromarray(np.ascontiguousarray(field, dtype=np.float32), mode="F")
    return np.clip(np.asarray(image.resize((w, h), Image.Resampling.BICUBIC)), 0.0, 1.0)


# -- the three looks -----------------------------------------------------------------------


def smoke_frames(seed: int = 801) -> Iterator[Any]:
    """Grey wisps drifting up, slow, over the top half of the frame (visible on a phone)."""
    rng = np.random.default_rng(seed)
    gh, gw = HEIGHT // 4, WIDTH // 4
    big = PeriodicField(
        rng,
        h=gh,
        w=gw,
        frames=FRAMES,
        rise_px=gh * 0.25,
        scale_y=2.2,
        scale_x=1.6,
        slope=1.6,
        evolve=1,
    )
    fine = PeriodicField(
        rng,
        h=gh,
        w=gw,
        frames=FRAMES,
        rise_px=gh * 0.5,
        scale_y=5.0,
        scale_x=4.0,
        slope=1.4,
        evolve=1,
    )
    y = np.linspace(0.0, 1.0, gh)[:, None]
    # dense at the top, gone by 62 % of the height
    envelope = (1.0 - _smoothstep(0.18, 0.62, y)) * (0.8 + 0.2 * _smoothstep(0.0, 0.08, y))
    for i in range(FRAMES):
        n = 0.85 * big.frame(i) + 0.30 * fine.frame(i)
        density = _smoothstep(-0.25, 2.0, n)
        grey = _upsample(0.85 * density**1.2 * envelope, HEIGHT, WIDTH)
        yield np.repeat(grey[:, :, None], 3, axis=2)


def steam_frames(seed: int = 803) -> Iterator[Any]:
    """A soft white cloud rising from the middle (a hot plate), coming apart as it rises:
    rounded puffs over a diffuse veil — no thin strands (v3, EF-08)."""
    rng = np.random.default_rng(seed)
    gh, gw = HEIGHT // 4, WIDTH // 4
    # rounded puffs: an isotropic, steep spectrum (no vertical stretch)
    puffs = PeriodicField(
        rng,
        h=gh,
        w=gw,
        frames=FRAMES,
        rise_px=gh * 0.6,
        scale_y=1.6,
        scale_x=1.6,
        slope=2.2,
        evolve=1,
    )
    sway = PeriodicField(
        rng,
        h=gh,
        w=gw,
        frames=FRAMES,
        rise_px=gh * 0.6,
        scale_y=1.2,
        scale_x=1.2,
        slope=2.4,
        evolve=1,
    )
    # the diffuse veil that dominates: very low frequencies only
    veil = PeriodicField(
        rng,
        h=gh,
        w=gw,
        frames=FRAMES,
        rise_px=gh * 0.6,
        scale_y=1.0,
        scale_x=1.0,
        slope=2.6,
        evolve=1,
    )
    y = np.linspace(0.0, 1.0, gh)[:, None]
    x = np.linspace(0.0, 1.0, gw)[None, :]
    # starts just above the plate (64 %), gone by 14 %
    vertical = _smoothstep(0.66, 0.54, y) * _smoothstep(0.14, 0.50, y)
    rise = np.clip((0.64 - y) / 0.46, 0.0, 1.0)
    width = 0.20 + 0.20 * rise
    for i in range(FRAMES):
        # a column around the centre, bending with the slow `sway` field, wider as it rises
        centre = 0.5 + 0.07 * sway.frame(i) * (0.3 + rise)
        column = np.exp(-0.5 * ((x - centre) / width) ** 2)
        # the puffs come apart as they rise (their threshold climbs with the height)
        puff = _smoothstep(-0.3 + 0.9 * rise, 1.9, puffs.frame(i))
        haze = _smoothstep(-1.4, 1.4, veil.frame(i))
        density = 0.4 * puff + 0.6 * haze
        white = _upsample(1.6 * density**1.2 * column * vertical, HEIGHT, WIDTH)
        yield np.repeat(white[:, :, None], 3, axis=2)


def ember_frames(seed: int = 802, count: int = 70) -> Iterator[Any]:
    """Large glowing orange-yellow sparks rising from the bottom, wobbling and flickering,
    fading as they rise. Each motion turns a whole number of times per loop."""
    rng = np.random.default_rng(seed)
    rises = rng.choice([1, 2], size=count, p=[0.55, 0.45])  # rises per loop
    phase = rng.uniform(0.0, 1.0, size=count)
    x0 = rng.uniform(0.06, 0.94, size=count) * WIDTH
    y0 = rng.uniform(0.90, 1.02, size=count) * HEIGHT
    height = rng.uniform(0.22, 0.42, size=count) * HEIGHT
    wobble_amp = rng.uniform(5.0, 18.0, size=count)
    wobble_turns = rng.integers(1, 4, size=count)
    wobble_phase = rng.uniform(0.0, 1.0, size=count)
    flicker_turns = rng.integers(4, 11, size=count)
    flicker_phase = rng.uniform(0.0, 1.0, size=count)
    size = rng.uniform(3.0, 5.4, size=count)
    gain = rng.uniform(0.9, 1.0, size=count)
    core = np.array([1.0, 0.86, 0.55])
    halo = np.array([1.0, 0.42, 0.08])
    for i in range(FRAMES):
        t = i / FRAMES
        frame = np.zeros((HEIGHT, WIDTH, 3))
        p = (rises * t + phase) % 1.0
        ys = y0 - p * height
        xs = x0 + wobble_amp * np.sin(2 * np.pi * (wobble_turns * t + wobble_phase))
        xs = xs + 0.25 * p * height * 0.15 * np.sin(2 * np.pi * (t + phase))
        flicker = 0.75 + 0.25 * np.sin(2 * np.pi * (flicker_turns * t + flicker_phase))
        alive = _smoothstep(0.0, 0.08, p) * (1.0 - p) ** 1.4
        level = gain * flicker * alive
        for k in range(count):
            if level[k] <= 0.01:
                continue
            r = int(size[k] * 6) + 2
            cx, cy = xs[k], ys[k]
            xa, xb = max(int(cx) - r, 0), min(int(cx) + r + 1, WIDTH)
            ya, yb = max(int(cy) - r, 0), min(int(cy) + r + 1, HEIGHT)
            if xa >= xb or ya >= yb:
                continue
            gx = np.arange(xa, xb)[None, :] - cx
            gy = np.arange(ya, yb)[:, None] - cy
            d2 = gx * gx + gy * gy
            c = np.exp(-0.5 * d2 / (size[k] * 0.6) ** 2)[:, :, None]
            g = np.exp(-0.5 * d2 / (size[k] * 2.2) ** 2)[:, :, None]
            frame[ya:yb, xa:xb] += level[k] * (1.4 * c * core + 0.9 * g * halo)
        yield np.clip(frame, 0.0, 1.0)


LOOKS: dict[str, Callable[[], Iterator[Any]]] = {
    "humo_capa": smoke_frames,
    "brasas_capa": ember_frames,
    "vapor_capa": steam_frames,
}

# -- encoding ------------------------------------------------------------------------------


def rgb_to_yuv420p(rgb: Any) -> Any:
    """Float RGB in [0, 1] (H, W, 3) → yuv420p planes stacked as (H·3/2, W) uint8, BT.709
    limited range. Exactly-black stays Y 16 / UV 128; R = G = B gives UV 128."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    cb = (b - y) / 1.8556
    cr = (r - y) / 1.5748

    def half(plane: Any) -> Any:
        return 0.25 * (
            plane[0::2, 0::2] + plane[1::2, 0::2] + plane[0::2, 1::2] + plane[1::2, 1::2]
        )

    y8 = np.clip(np.rint(16.0 + 219.0 * y), 16, 235).astype(np.uint8)
    u8 = np.clip(np.rint(128.0 + 224.0 * half(cb)), 16, 240).astype(np.uint8)
    v8 = np.clip(np.rint(128.0 + 224.0 * half(cr)), 16, 240).astype(np.uint8)
    h, w = y8.shape
    return np.concatenate([y8, u8.reshape(h // 4, w), v8.reshape(h // 4, w)], axis=0)


def encode_loop(frames: Iterator[Any], out: Path) -> None:
    import av  # noqa: PLC0415

    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(out.name + ".partial")
    with av.open(str(partial), mode="w", format="webm") as sink:
        stream = sink.add_stream("libvpx-vp9", rate=FPS)
        stream.width, stream.height = WIDTH, HEIGHT
        stream.pix_fmt = "yuv420p"
        stream.options = dict(VP9_OPTIONS)
        ctx = stream.codec_context
        ctx.time_base = Fraction(1, FPS)
        ctx.color_range = 1  # MPEG / limited («tv»)
        ctx.colorspace = 1  # BT.709
        ctx.color_primaries = 1
        ctx.color_trc = 1
        for index, rgb in enumerate(frames):
            frame = av.VideoFrame.from_ndarray(rgb_to_yuv420p(rgb), format="yuv420p")
            frame.pts = index
            frame.time_base = Fraction(1, FPS)
            frame.color_range = 1
            frame.colorspace = 1
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    partial.replace(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=None, help="folder (default: packaged)")
    parser.add_argument("--only", choices=EFFECTS, action="append", help="one effect")
    parser.add_argument(
        "--force", action="store_true", help="overwrite a preview.webm that already exists"
    )
    args = parser.parse_args(argv)
    root = args.out or PACKAGED
    effects = args.only or EFFECTS
    existing = [root / e / "v1" / "preview.webm" for e in effects]
    existing = [path for path in existing if path.exists()]
    if existing and not args.force:
        print(
            "refusing to overwrite published loops (use --force, or --out DIR): "
            + ", ".join(str(path) for path in existing),
            file=sys.stderr,
        )
        return 2
    for effect in effects:
        target = root / effect / "v1" / "preview.webm"
        encode_loop(LOOKS[effect](), target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        print(f"{effect}: {target} {target.stat().st_size} B sha256={digest}")
        if args.out is None:
            served = SERVED / effect / "v1" / "preview.webm"
            served.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target, served)
            print(f"  copied to {served}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
