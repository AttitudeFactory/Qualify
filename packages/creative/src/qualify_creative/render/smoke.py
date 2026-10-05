"""End-to-end smoke of the Python half against a RUNNING render service: build props from
real photos and a stand-in brand kit, validate them against the published manifest, upload,
render, download every output. Prints what the operator would see (ETA, per-port status,
sizes) and writes the files next to the photos.

    uv run --no-sync python -m qualify_creative.render.smoke \\
        --base-url http://localhost:3200 --template promo_producto \\
        --brand "Polette" --hook "El yogurt que se come con cuchara" --price "$4" \\
        --cta "Pide el tuyo" --out /tmp/smoke photo1.jpg photo2.jpg

Not a test (it needs the container and real files); `just render-smoke` covers the Node
side alone, this covers the seam.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from uuid import uuid4

from qualify_creative.enums import (
    BriefObjective,
    ContentKind,
    ContentType,
    GenerationTask,
    ImageRoute,
)
from qualify_creative.providers import GenerationRequest, RenderedPrompt
from qualify_creative.render.adapter import RemotionTemplateAdapter
from qualify_creative.render.client import RemotionRenderClient
from qualify_creative.render.props import build_props, validate_props
from qualify_creative.render.registry import TemplateRegistry
from qualify_creative.schemas import BrandKit, ContentBrief, CopyPayload, MediaInputs, ToneAxes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("photos", nargs="+", type=Path)
    parser.add_argument("--base-url", default="http://localhost:3200")
    parser.add_argument("--template", default="promo_producto")
    parser.add_argument("--brand", default="Qualify")
    parser.add_argument("--hook", default="Hoy sí se antoja")
    parser.add_argument("--price", default="")
    parser.add_argument("--cta", default="Pide el tuyo")
    parser.add_argument("--palette", default="#F4C2C2,#5A2A27,#FFFFFF")
    parser.add_argument("--logo", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("smoke-out"))
    args = parser.parse_args(argv)

    registry = TemplateRegistry.from_dir()
    manifest = registry.get(args.template)
    files: dict[str, bytes] = {p.name: p.read_bytes() for p in args.photos}
    if args.logo is not None:
        files[args.logo.name] = args.logo.read_bytes()

    kit = BrandKit(
        brand_id=uuid4(),
        positioning="smoke",
        audience="smoke",
        tone_axes=ToneAxes(
            formal_casual=70, sober_enthusiastic=70, technical_plain=80, brief_elaborate=30
        ),
        palette_rgb=tuple(c.strip() for c in args.palette.split(",") if c.strip()),
        logo_asset_key=args.logo.name if args.logo is not None else None,
    )
    brief = ContentBrief(
        brand_id=kit.brand_id,
        objective=BriefObjective.SALE,
        content_type=ContentType.PROMOTION,
        topic="smoke",
        image_route=ImageRoute.FROM_UPLOAD,
        source_media_key=args.photos[0].name,
        kind=ContentKind.TEMPLATE,
        media=MediaInputs(product_keys=tuple(p.name for p in args.photos)),
    )
    copy = CopyPayload(hook=args.hook, caption="smoke", cta=args.cta)
    draft_id = uuid4()
    props = build_props(
        manifest=manifest,
        brief=brief,
        copy=copy,
        kit=kit,
        brand_name=args.brand,
        products=[],
        tenant_id=uuid4(),
        draft_id=draft_id,
        price_line=args.price or None,
    )
    problems = validate_props(manifest, props)
    if problems:
        for p in problems:
            print(f"  ✗ {p.port}: {p.message}")
        return 2
    eta = manifest.cost_model.eta_seconds(manifest.outputs, 15.0)
    print(f"template {manifest.key}: {len(manifest.outputs)} outputs, ETA ~{eta:.0f}s")

    client = RemotionRenderClient(args.base_url)
    health = client.health()
    print(f"service ok={health.get('ok')} bundleReady={health.get('bundleReady')}")

    def progress(job):  # noqa: ANN001
        states = ", ".join(
            f"{p}={o.status.value}({o.progress:.0%})" for p, o in job.outputs.items()
        )
        print(f"  {job.status.value}: {states}")

    adapter = RemotionTemplateAdapter(client, read_media=files.__getitem__, on_progress=progress)
    request = GenerationRequest(
        task=GenerationTask.TEMPLATE_RENDER,
        rendered_prompt=RenderedPrompt("", "", ""),
        params={
            "job_id": str(draft_id),
            "template_id": manifest.id,
            "version": manifest.version,
            "props": props,
            "render_count": manifest.render_count,
        },
    )
    started = time.monotonic()
    result = adapter.generate(request, api_key="")
    elapsed = time.monotonic() - started
    payload = result.payload
    assert isinstance(payload, dict)
    args.out.mkdir(parents=True, exist_ok=True)
    for port, out in payload["outputs"].items():
        ext = "mp4" if out["kind"] == "video" else "png"
        target = args.out / f"{port}.{ext}"
        target.write_bytes(out["bytes"])
        size_kb = len(out["bytes"]) / 1024
        dims = f"{out.get('width')}x{out.get('height')}"
        print(f"  ✓ {port}: {size_kb:.0f} KB {dims} → {target}")
    for port, info in payload.get("failed_ports", {}).items():
        print(f"  ✗ {port}: {info.get('failure_reason')} {info.get('error_message') or ''}")
    print(f"job {payload['job_id']} {payload['status']} in {elapsed:.1f}s")
    print(f"warnings: {payload['warnings']}")
    return 0 if payload["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
