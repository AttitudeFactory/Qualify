"""m-25017275 — contact sheet: compiler 3 and compiler 4 side by side per brief.

    uv run --no-sync python packages/api/evals/scene_text_v4/contact_sheet.py <out dir> \
        [--rep 1] [--sheet <file.jpg>] [--height 900]

One row per case (and slide), labelled; a missing image leaves a grey cell that says so.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

NAME = re.compile(r"^(?P<base>.+)-r(?P<rep>\d+)-v(?P<version>\d+)\.jpg$")


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
    except OSError:
        return ImageFont.load_default()


def build(out: Path, rep: int | None, height: int) -> Image.Image:
    rows: dict[str, dict[int, Path]] = {}
    for path in sorted(out.glob("*.jpg")):
        match = NAME.match(path.name)
        if not match or (rep is not None and int(match["rep"]) != rep):
            continue
        key = f"{match['base']} r{match['rep']}"
        rows.setdefault(key, {})[int(match["version"])] = path
    width = height * 9 // 16 + 40
    label_h = 44
    font = _font(26)
    sheet = Image.new("RGB", (width * 2, (height + label_h) * len(rows)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (key, versions) in enumerate(rows.items()):
        y = i * (height + label_h)
        for j, version in enumerate((3, 4)):
            x = j * width
            draw.text((x + 8, y + 8), f"{key}  ·  compilador {version}", fill="black", font=font)
            path = versions.get(version)
            if path is None:
                draw.rectangle((x, y + label_h, x + width - 4, y + label_h + height), fill="grey")
                draw.text((x + 20, y + label_h + 20), "sin imagen", fill="white", font=font)
                continue
            image = Image.open(path).convert("RGB")
            image.thumbnail((width - 8, height))
            sheet.paste(image, (x + 4, y + label_h))
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--rep", type=int)
    parser.add_argument("--sheet", type=Path)
    parser.add_argument("--height", type=int, default=900)
    args = parser.parse_args()
    target = args.sheet or args.out / "hoja-de-contacto.jpg"
    build(args.out, args.rep, args.height).save(target, quality=82)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
