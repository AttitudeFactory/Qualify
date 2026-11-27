# ruff: noqa: E501
"""SISVIS-002 (spike m-25042530): time and peak memory of `brand_still` in the production render image.

Expects the render image running under the production limits, e.g.:

    docker build -t qualify-render:sisvis packages/render
    docker run -d --name rsis --memory 1536m --memory-swap 1536m -e RENDER_CONCURRENCY=1 \
        -p 3299:3200 qualify-render:sisvis

Uploads the assets (POST /assets), renders each piece N times through the real HTTP API
(POST /render, poll GET /jobs/{id}) and reads the container's cgroup ``memory.peak`` before and
after. Usage:

    python render_memprobe.py <base_url> <container> <public_dir> <system.json> <recipe> <content.json> [N]
"""

from __future__ import annotations

import json
import mimetypes
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path


def _req(url: str, data: bytes | None = None, ctype: str = "application/json") -> dict:
    r = urllib.request.Request(
        url, data=data, headers={"Content-Type": ctype} if data is not None else {}
    )
    with urllib.request.urlopen(r, timeout=120) as resp:
        return json.loads(resp.read())


def _peak(container: str) -> int:
    out = subprocess.run(
        ["docker", "exec", container, "cat", "/sys/fs/cgroup/memory.peak"],
        capture_output=True,
        text=True,
        check=False,
    )
    return int(out.stdout.strip() or 0)


def _current(container: str) -> int:
    out = subprocess.run(
        ["docker", "exec", container, "cat", "/sys/fs/cgroup/memory.current"],
        capture_output=True,
        text=True,
        check=False,
    )
    return int(out.stdout.strip() or 0)


def main() -> None:
    base, container, public, sysf, recipe, contentf = sys.argv[1:7]
    n = int(sys.argv[7]) if len(sys.argv) > 7 else 3
    public_dir = Path(public)
    system = json.loads(Path(sysf).read_text())
    content = json.loads(Path(contentf).read_text())
    cache: dict[str, str] = {}

    def upload(rel: str) -> str:
        if rel in cache:
            return cache[rel]
        f = public_dir / rel
        ctype = mimetypes.guess_type(f.name)[0] or (
            "font/woff2" if f.suffix == ".woff2" else "application/octet-stream"
        )
        res = _req(f"{base}/assets", f.read_bytes(), ctype)
        cache[rel] = f"asset://{res['assetId']}"
        return cache[rel]

    def walk(v: object) -> object:
        if isinstance(v, str) and (public_dir / v).is_file() and "/" in v:
            return upload(v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v

    system, content = walk(system), walk(content)
    port = {"4:5": "feed", "1:1": "square", "9:16": "story"}[system["recipes"][recipe]["format"]]
    props = {
        "meta": {"templateId": "brand_still", "version": 0, "port": port},
        "system": system,
        "recipe": recipe,
        "content": content,
    }
    idle = _current(container)
    peak_before = _peak(container)
    results = []
    for _ in range(n):
        job = str(uuid.uuid4())
        t0 = time.time()
        _req(
            f"{base}/render",
            json.dumps(
                {
                    "jobId": job,
                    "templateId": "brand_still",
                    "version": 0,
                    "props": props,
                    "outputs": [port],
                }
            ).encode(),
        )
        while True:
            j = _req(f"{base}/jobs/{job}")
            if j["status"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(0.25)
        results.append(
            {
                "status": j["status"],
                "seconds": round(time.time() - t0, 2),
                "error": j["outputs"][port].get("errorMessage"),
            }
        )
    print(
        json.dumps(
            {
                "recipe": recipe,
                "port": port,
                "runs": results,
                "idle_mb": round(idle / 2**20, 1),
                "peak_before_mb": round(peak_before / 2**20, 1),
                "cgroup_peak_mb": round(_peak(container) / 2**20, 1),
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
