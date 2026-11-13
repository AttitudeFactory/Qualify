"""m-25017275 — Seedream scene text rule: prompt compiler 3 vs 4, paired.

For every case in `cases.json` the same brief, the same reference images and the same
size are compiled under `prompt_compiler_version` 3 and 4 with the production functions
(`ad_scene_prompt` for an advertising image, `carousel_scene_prompt` for each gallery
slide) and sent to the production Seedream model through `SeedreamImageAdapter`. Only the
RAW scene is generated: nothing is composited, nothing is stored in R2 or the database.
Images, prompts and a ledger go to `--out` on local disk.

Money: every POST goes through `LedgerTransport`, which reserves the quoted worst case
before the bytes leave and refuses the call that would cross `--max-usd`.

    uv run --no-sync python packages/api/evals/scene_text_v4/run.py \
        --inputs <dir>/manifest.json --out <dir> [--reps 1] [--only F1-ubicacion] [--dry-run]

`manifest.json` maps each photo role of the cases (`shawarma_carne`, `isotipo`, ...) to a
local file. Client photos never enter git.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from qualify_creative.adapters.byteplus_ark import DEFAULT_SEEDREAM_MODEL, SeedreamImageAdapter
from qualify_creative.pricing import JsonPricingTable
from qualify_creative.providers import GenerationRequest, GenerationTask, RenderedPrompt
from qualify_creative.scene_plan import ad_mode_for, carousel_scene_plans, flyer_scene_plans
from qualify_creative.schemas import BrandKit, ContentBrief

from qualify_api.creative.brand_references import BrandReference
from qualify_api.creative.media import (
    SCENE_SIZES,
    _data_url,
    ad_scene_prompt,
    carousel_scene_prompt,
)
from qualify_api.evals.byteplus_eval_guard import resolve_eval_key
from qualify_api.evals.spend_control import LedgerTransport, SpendLedger, quote

HERE = Path(__file__).parent
TENANT = UUID("00000000-0000-0000-0000-000000000001")
BRAND_ID = "00000000-0000-0000-0000-000000000002"
VERSIONS = (3, 4)
LOGO_ROLE = "isotipo"


@dataclass(frozen=True)
class Job:
    """One Seedream call: a case (or one slide of it) at one compiler version."""

    case_id: str
    slide: int | None
    version: int
    rep: int
    prompt: str
    references: tuple[str, ...]  # photo roles, in the order sent
    size: str

    @property
    def name(self) -> str:
        slide = f"-s{self.slide}" if self.slide is not None else ""
        return f"{self.case_id}{slide}-r{self.rep}-v{self.version}"


def _key(role: str) -> str:
    """A fake storage key per role: the compiler reads only its shape (catalog photo)."""
    return f"uploads/{TENANT}/catalog/p/{role}.jpg"


def _logo_ref() -> BrandReference:
    return BrandReference.model_validate(
        {
            "rol": "elemento_de_marca",
            "asset_key": f"t/{TENANT}/brand/{BRAND_ID}/logo_version/isotipo/l.png",
            "label": "isotipo.png",
            "content_type": "image/png",
            "asset_kind": "logo_version",
            "asset_slot": "isotipo",
            "selected_logo": True,
            "instruction_version": 9,
        }
    )


def _kit(data: dict[str, Any]) -> BrandKit:
    return BrandKit.model_validate({"brand_id": BRAND_ID, **data})


def _brief(case: dict[str, Any], version: int) -> ContentBrief:
    products = list(case.get("products") or [])
    media: dict[str, Any] = {
        "product_keys": [_key(p) for p in products],
        "product_image_roles": ["product"] * len(products),
        "brand_logo_key": f"t/{TENANT}/brand/{BRAND_ID}/logo_version/isotipo/l.png"
        if case["logo"]
        else None,
        "brand_logo_in_scene": bool(case["logo"]),
        "brand_application_version": 2,
        "prompt_compiler_version": version,
    }
    payload: dict[str, Any] = {
        "brand_id": BRAND_ID,
        "objective": "consideration",
        "topic": case["topic"],
        "kind": case["kind"],
        "format": case["format"],
    }
    if case["kind"] == "carousel":
        media["slides"] = [
            {
                "text": s["text"],
                "source": "generated",
                "product_index": s["product_index"],
                "use_background": False,
                "scene_prompt": s["scene_prompt"],
            }
            for s in case["slides"]
        ]
        payload["image_route"] = "from_upload"
        payload["source_media_key"] = _key(products[0])
    else:
        media["scene_prompt"] = case["topic"]
        payload["image_route"] = "template_only"
        payload["constraints"] = {
            "highlights": [list(h) for h in case.get("highlights") or []],
            "must_mention": case.get("must_mention") or [],
            "must_avoid": [],
        }
    payload["media"] = media
    return ContentBrief.model_validate(payload)


def jobs_for(case: dict[str, Any], kit: BrandKit, brand: str, rep: int) -> Iterator[Job]:
    """The jobs of one case at both compiler versions, references in production order:
    the scene's product photos, then the brand references (`_ad_image`, `_carousel_slides`)."""
    refs = (_logo_ref(),) if case["logo"] else ()
    logo_roles = (LOGO_ROLE,) if case["logo"] else ()
    for version in VERSIONS:
        brief = _brief(case, version)
        ratio = brief.format.aspect_ratio
        if case["kind"] == "carousel":
            plans = {p.output_index: p for p in carousel_scene_plans(brief.media)}
            total = len(brief.media.slides)
            for position, slide in enumerate(brief.media.slides):
                plan = plans.get(position)
                photos = (
                    [case["products"][p.global_index] for p in plan.photos]
                    if plan is not None
                    else [case["products"][slide.product_index]]
                )
                prompt = carousel_scene_prompt(
                    brief=brief,
                    kit=kit,
                    brand=brand,
                    scene=slide.scene_prompt,
                    ratio=ratio,
                    has_product=True,
                    product_role="product",
                    has_background=False,
                    has_text=slide.text.value != "none",
                    background_index=plan.background_number if plan and refs else None,
                    brand_refs=refs,
                    scene_plan=plan,
                    hook=slide.text.value == "hook",
                    cta=slide.text.value == "cta",
                    slide_number=position + 1,
                    slides=total,
                    animated=False,
                )
                yield Job(
                    case["id"],
                    position + 1,
                    version,
                    rep,
                    prompt,
                    (*photos, *logo_roles),
                    SCENE_SIZES[ratio],
                )
        else:
            mode = ad_mode_for(brief.media)
            plan = flyer_scene_plans(brief.media, mode)[0]
            prompt = ad_scene_prompt(
                brief=brief,
                kit=kit,
                brand=brand,
                mode=mode,
                products=len(plan.photos),
                has_background=bool(plan.background_key),
                background_index=plan.background_number if refs else None,
                brand_refs=refs,
                scene_plan=plan,
            )
            photos = [case["products"][p.global_index] for p in plan.photos]
            yield Job(
                case["id"], None, version, rep, prompt, (*photos, *logo_roles), SCENE_SIZES[ratio]
            )


def _env_from_dotenv(path: Path) -> dict[str, str]:
    env = dict(os.environ)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() and not name.lstrip().startswith("#"):
                env.setdefault(name.strip(), value.strip().strip('"').strip("'"))
    return env


def run(args: argparse.Namespace) -> int:
    spec = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    kit = _kit(spec["kit"])
    manifest = json.loads(Path(args.inputs).read_text(encoding="utf-8"))
    base = Path(args.inputs).parent
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cases = [c for c in spec["cases"] if not args.only or c["id"] in args.only]
    jobs = [
        j
        for rep in range(args.rep_start, args.rep_start + args.reps)
        for c in cases
        for j in jobs_for(c, kit, spec["brand"], rep)
    ]
    pricing = JsonPricingTable("v9")
    model = args.model
    planned = sum(
        (quote(pricing, model_id=model, size=j.size, references=len(j.references)).total_usd)
        for j in jobs
    )
    print(f"{len(jobs)} images planned, US${planned} (model {model}, pricing {pricing.version})")
    for j in jobs:
        (out / f"{j.name}.prompt.txt").write_text(j.prompt, encoding="utf-8")
    if args.dry_run:
        return 0
    key = resolve_eval_key(_env_from_dotenv(Path(args.env_file)))
    print(f"key: {key.env_name} {key.fingerprint}", file=sys.stderr)
    ledger_path = out / "ledger.jsonl"
    already = Decimal(0)
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            already += Decimal(json.loads(line)["cost_usd"])
    ledger = SpendLedger(ceiling_usd=Decimal(args.max_usd) - already)
    print(f"already spent US${already}; ceiling left US${ledger.remaining_usd}")
    images: dict[str, str] = {}
    for role, rel in manifest.items():
        images[role] = _data_url((base / rel).read_bytes())
    inner = httpx.HTTPTransport()
    for j in jobs:
        target = out / f"{j.name}.jpg"
        if target.exists():
            continue
        q = quote(pricing, model_id=model, size=j.size, references=len(j.references))
        transport = LedgerTransport(inner, ledger, q, label=j.name)
        adapter = SeedreamImageAdapter(model=model, transport=transport)
        request = GenerationRequest(
            task=GenerationTask.PRODUCT_IMAGE,
            rendered_prompt=RenderedPrompt("", "", ""),
            params={
                "prompt": j.prompt,
                "images": [images[r] for r in j.references],
                "size": j.size,
            },
        )
        before = ledger.spent_usd
        started = time.monotonic()
        row: dict[str, Any] = {
            "job": j.name,
            "case": j.case_id,
            "slide": j.slide,
            "version": j.version,
            "rep": j.rep,
            "model": model,
            "size": j.size,
            "references": list(j.references),
            "pricing": pricing.version,
            "prompt_chars": len(j.prompt),
        }
        try:
            result = adapter.generate(request, api_key=key.value)
            target.write_bytes(result.payload["images"][0])
            row.update(ok=True, model_revision=result.model_revision)
        except Exception as exc:  # noqa: BLE001 - recorded, the run goes on
            row.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:300]}")
            if "Ceiling" in type(exc).__name__ or "ceiling" in str(exc):
                print("ceiling reached, stopping", file=sys.stderr)
                break
        row["seconds"] = round(time.monotonic() - started, 1)
        row["cost_usd"] = str(ledger.spent_usd - before)
        with ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(
            j.name,
            "ok" if row["ok"] else row["error"],
            row["cost_usd"],
            f"total {already + ledger.spent_usd}",
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inputs", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--reps", type=int, default=1)
    parser.add_argument("--rep-start", type=int, default=1)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--model", default=DEFAULT_SEEDREAM_MODEL)
    parser.add_argument("--max-usd", default="3")
    parser.add_argument("--env-file", default=str(Path.cwd() / ".env"))
    parser.add_argument("--dry-run", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
