"""Downloads the scene experiment's images from Langfuse to `imagenes/` (git-ignored), to
look at them without opening every trace, plus a contact sheet of the finished pieces.

The images live in Langfuse as media attached to each `experiment-item-run` of the
`escenas-imagen` dataset; the scores are still given in the annotation queue «Revisión
de imagen y video». Reads `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and
`LANGFUSE_BASE_URL` from the environment or `--env-file`:

    just eval-escenas-imagenes
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
_MEDIA = re.compile(r"@@@langfuseMedia:type=image/jpeg\|id=([^|]+)\|")


def _load_env(path: str | None) -> None:
    if not path or not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def _get(url: str, auth: str | None = None) -> bytes:
    request = urllib.request.Request(url, headers={"Authorization": auth} if auth else {})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 — our server
        return response.read()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def contact_sheet(images: list[Path], out: Path, height: int = 640, columns: int = 5) -> None:
    from PIL import Image, ImageDraw, ImageFont

    thumbs = []
    for path in images:
        image = Image.open(path)
        image.thumbnail((10_000, height))
        thumbs.append((path.stem.removesuffix("-final"), image))
    rows = [thumbs[i : i + columns] for i in range(0, len(thumbs), columns)]
    width = max(sum(t.width for _, t in row) + 20 * (len(row) + 1) for row in rows)
    sheet = Image.new("RGB", (width, len(rows) * (height + 70) + 20), "white")
    draw = ImageDraw.Draw(sheet)
    try:
        font: Any = ImageFont.truetype("arial.ttf", 26)
    except OSError:
        font = ImageFont.load_default()
    y = 20
    for row in rows:
        x = 20
        for name, thumb in row:
            sheet.paste(thumb, (x, y))
            draw.text((x, y + height + 10), name, fill="black", font=font)
            x += thumb.width + 20
        y += height + 70
    sheet.save(out, quality=85)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    _load_env(args.env_file)
    base = os.environ.get("LANGFUSE_BASE_URL", "http://localhost:3100").rstrip("/")
    public, secret = os.environ.get("LANGFUSE_PUBLIC_KEY"), os.environ.get("LANGFUSE_SECRET_KEY")
    if not (public and secret):
        print("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set", file=sys.stderr)
        return 2
    auth = "Basic " + base64.b64encode(f"{public}:{secret}".encode()).decode()
    cases = {c["id"] for c in json.loads((HERE / "cases.json").read_text("utf-8"))["cases"]}
    url = (
        f"{base}/api/public/v2/observations?limit=200&fields=core,basic,io"
        "&environment=sdk-experiment&name=experiment-item-run"
    )
    newest: dict[str, tuple[str, dict[str, Any], list[str]]] = {}
    for observation in json.loads(_get(url, auth))["data"]:
        output, case = _as_dict(observation.get("output")), _as_dict(observation.get("input"))
        ids = _MEDIA.findall(json.dumps(output))
        started = observation.get("startTime") or ""
        if case.get("id") in cases and ids and started > newest.get(case["id"], ("",))[0]:
            newest[case["id"]] = (started, output, ids)
    out = HERE / "imagenes"
    out.mkdir(exist_ok=True)
    finals = []
    for case, (_started, output, ids) in sorted(newest.items()):
        for kind, media_id in zip(("final", "escena"), ids, strict=False):
            signed = json.loads(_get(f"{base}/api/public/media/{media_id}", auth))["url"]
            path = out / f"{case}-{output.get('formato')}-{kind}.jpg"
            path.write_bytes(_get(signed))
            if kind == "final":
                finals.append(path)
    if finals:
        contact_sheet(finals, out / "_hoja-de-contacto.jpg")
    print(f"{len(newest)} casos en {out.relative_to(HERE.parents[3]).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
