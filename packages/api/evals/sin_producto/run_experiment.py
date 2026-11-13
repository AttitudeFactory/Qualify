"""Pieces without a catalog product (m-24985141): prompt compiler 5 on two fictional brands.

Twelve cases: a food brand («hamburguesas») and one of another trade («inmobiliaria»), each
with Clip, carousel and avatar, each with and without a product. For every case it renders
the copy prompt and compiles the media prompts exactly as production does at compiler 5,
and checks offline that no prompt of a case without a product names one. Nothing is sent
unless `--i-have-spend-authorization` is given (Deivid authorizes each paid run):

- copy: one variant per case through the production copy adapter (Claude Opus 5.5) —
  is a product invented when none was chosen?
- image: one Seedream 5.0 pro still per carousel and avatar case (the carousel's first
  slide; the avatar's opening frame). The Clip's video is NOT generated: its Seedance
  prompt is compiled and saved (no long video in this run).

Fictional brands only (`evals/copy_ai/cases.json`): no client data reaches BytePlus.
Prices from the versioned table (`composition.PRICING_VERSION`), quoted before anything is
sent; the run stops at `--max-usd`. Outputs go to `results/<stamp>/` (git-ignored).

    uv run --no-sync python packages/api/evals/sin_producto/run_experiment.py
    uv run --no-sync python packages/api/evals/sin_producto/run_experiment.py \\
        --i-have-spend-authorization --max-usd 2
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from decimal import ROUND_UP, Decimal
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BRANDS_FILE = HERE.parent / "copy_ai" / "cases.json"
#: The food brand and the one of another trade (Deivid: prompts general, no trade).
BRANDS = {"hamburguesas": "Brasa Norte", "inmobiliaria": "Hábitat Inmobiliaria"}
PRODUCTS = {
    "hamburguesas": "Hamburguesa doble con queso",
    "inmobiliaria": "Apartamento en Envigado",
}
TOPICS = {
    "hamburguesas": "Cumplimos cinco años en el barrio y queremos dar las gracias",
    "inmobiliaria": "Te acompañamos a buscar tu primera vivienda, sin presiones",
}
KINDS = ("clip", "carousel", "avatar")
SEEDREAM_MODEL = "dola-seedream-5-0-pro-260628"
#: The copy call's output, for the quote: the adapter's allowance doubled (one repair turn).
COPY_OUTPUT_TOKENS = 4000
PRODUCT_WORD = re.compile(r"\bproducts?\b", re.IGNORECASE)


def _load_env(path: str | None) -> None:
    if not path or not Path(path).is_file():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def build_cases() -> list[dict[str, Any]]:
    """The twelve cases: (brand, kind, with/without product), each with its kit, voice and
    a compiler-5 brief."""
    from qualify_creative.enums import ContentKind, ImageRoute, SlideSource
    from qualify_creative.schemas import (
        BrandKit,
        BrandVoiceProfile,
        CarouselSlide,
        ContentBrief,
        ContentFormat,
        MediaInputs,
    )

    from qualify_api.creative.media import PROMPT_COMPILER_VERSION

    brands = json.loads(BRANDS_FILE.read_text(encoding="utf-8"))["brands"]
    cases = []
    for brand in BRANDS:
        kit = BrandKit.model_validate(brands[brand]["kit"])
        voice = BrandVoiceProfile.model_validate(brands[brand]["voice"])
        for kind in KINDS:
            for with_product in (True, False):
                media: dict[str, Any] = {
                    "prompt_compiler_version": PROMPT_COMPILER_VERSION,
                    "brand_application_version": 2,
                    "resource_plan_version": 2,
                }
                if kind == "clip":
                    media["duration_seconds"] = 10
                    content_kind, fmt = ContentKind.CLIP, ContentFormat.REELS_9_16
                elif kind == "carousel":
                    media["slides"] = (CarouselSlide(source=SlideSource.GENERATED),) * 2
                    content_kind, fmt = ContentKind.CAROUSEL, ContentFormat.FEED_4_5
                else:
                    media.update(voice_id="v1", avatar_source="ai", avatar_prompt="una persona")
                    content_kind, fmt = ContentKind.AVATAR_VIDEO, ContentFormat.REELS_9_16
                brief = ContentBrief(
                    brand_id=kit.brand_id,
                    objective="awareness",
                    topic=TOPICS[brand],
                    product_ref=PRODUCTS[brand] if with_product else None,
                    kind=content_kind,
                    format=fmt,
                    image_route=ImageRoute.GENERATE,
                    variants_requested=1,
                    media=MediaInputs(**media),
                )
                cases.append(
                    {
                        "id": f"{brand}-{kind}-{'con' if with_product else 'sin'}-producto",
                        "brand": brand,
                        "kind": kind,
                        "with_product": with_product,
                        "kit": kit,
                        "voice": voice,
                        "brief": brief,
                    }
                )
    return cases


def compile_media(case: dict[str, Any]) -> dict[str, Any]:
    """The case's media prompt, as production compiles it (no reference photo: the eval
    has none of a real client), with the Seedream size when an image is generated."""
    from qualify_creative.schemas import CopyPayload, ScriptShot

    from qualify_api.creative import media as m

    brief, kit = case["brief"], case["kit"]
    if case["kind"] == "clip":
        copy = CopyPayload(
            hook="Mira esto",
            caption="-",
            cta="Escríbenos",
            shots=tuple(
                ScriptShot(visual=f"Momento {i}.", seconds=s) for i, s in ((1, 4), (2, 4), (3, 2))
            ),
        )
        prompt = m.clip_prompt(
            brief=brief,
            kit=kit,
            first_frame=False,
            last_frame=False,
            images=0,
            videos=0,
            audios=0,
            copy=copy,
            model="dreamina-seedance-2-5-260628",
        )
        return {"prompt": prompt, "size": None}
    if case["kind"] == "carousel":
        prompt = m.carousel_scene_prompt(
            brief=brief,
            kit=kit,
            brand=BRANDS[case["brand"]],
            scene="",
            ratio="4:5",
            has_product=False,
            has_background=False,
            has_text=True,
            slide_number=1,
            slides=2,
        )
        return {"prompt": prompt, "size": m.SCENE_SIZES["4:5"]}
    prompt = m.first_frame_prompt(
        brief=brief, kit=kit, has_character_image=False, products=0, has_background=False
    )
    return {"prompt": prompt, "size": m.SCENE_SIZES["9:16"]}


def copy_request(case: dict[str, Any]) -> Any:
    from qualify_creative.brand.render import printed_limits, render_prompt
    from qualify_creative.enums import GenerationTask
    from qualify_creative.providers import GenerationRequest
    from qualify_creative.schemas import CopyPayload

    brief = case["brief"]
    limits = printed_limits(brief.kind)
    return GenerationRequest(
        task=GenerationTask.COPY,
        rendered_prompt=render_prompt(
            kit=case["kit"], voice=case["voice"], brief=brief, task=GenerationTask.COPY, variant=0
        ),
        output_schema=CopyPayload.model_json_schema(),
        params={"max_lengths": limits} if limits else {},
    )


def quote(cases: list[dict[str, Any]]) -> tuple[Decimal, list[tuple[str, str, Decimal]]]:
    """Every paid call's upper price, from the versioned table, before anything is sent."""
    from qualify_creative.adapters.anthropic_copy import DEFAULT_MODEL_ID
    from qualify_creative.pricing import JsonPricingTable

    from qualify_api.creative.composition import PRICING_VERSION
    from qualify_api.evals.spend_control import size_tier

    pricing = JsonPricingTable(PRICING_VERSION)
    per_in = pricing.unit_price(model_id=DEFAULT_MODEL_ID, unit="per_mtok_in")
    per_out = pricing.unit_price(model_id=DEFAULT_MODEL_ID, unit="per_mtok_out")
    lines: list[tuple[str, str, Decimal]] = []
    for case in cases:
        prompt = case["copy_request"].rendered_prompt
        tokens_in = (len(prompt.stable_prefix) + len(prompt.volatile_suffix)) // 3 + 1
        copy_usd = (Decimal(tokens_in) * per_in + COPY_OUTPUT_TOKENS * per_out) / 1_000_000
        lines.append((case["id"], f"copy {DEFAULT_MODEL_ID}", copy_usd))
        size = case["media"]["size"]
        if size:
            tier = size_tier(size, model_id=SEEDREAM_MODEL)
            image_usd = pricing.unit_price(model_id=SEEDREAM_MODEL, unit=f"per_image_{tier}")
            lines.append((case["id"], f"imagen {SEEDREAM_MODEL} {size} ({tier})", image_usd))
    total = sum((amount for *_, amount in lines), Decimal(0))
    return total, lines


def offline_check(cases: list[dict[str, Any]]) -> list[str]:
    """Compiler 4: a case without a product names none — in its media prompt, and in the
    copy prompt's assignment (the copy prompt's own «no product» line aside)."""
    problems = []
    for case in cases:
        if case["with_product"]:
            continue
        if PRODUCT_WORD.search(case["media"]["prompt"]):
            problems.append(f"{case['id']}: the media prompt names a product")
    return problems


def run_paid(cases: list[dict[str, Any]], out: Path, max_usd: Decimal) -> int:
    from qualify_creative.adapters import AnthropicCopyAdapter
    from qualify_creative.adapters.byteplus_ark import SeedreamImageAdapter
    from qualify_creative.enums import GenerationTask
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.providers import GenerationRequest, RenderedPrompt

    from qualify_api.creative.composition import PLATFORM_KEY_ENV, PRICING_VERSION
    from qualify_api.creative.observed import _copy_usage
    from qualify_api.evals.byteplus_eval_guard import EvalKeyError, resolve_eval_key
    from qualify_api.evals.spend_control import CeilingExceededError, SpendLedger

    try:
        byteplus = resolve_eval_key()
    except EvalKeyError as exc:
        print(exc, file=sys.stderr)
        return 2
    claude_key = os.environ.get(PLATFORM_KEY_ENV, "").strip()
    if not claude_key:
        print(f"{PLATFORM_KEY_ENV} is not set", file=sys.stderr)
        return 2
    print(byteplus.describe())
    pricing = JsonPricingTable(PRICING_VERSION)
    ledger = SpendLedger(max_usd)
    copy_adapter = AnthropicCopyAdapter()
    image_adapter = SeedreamImageAdapter(model=SEEDREAM_MODEL)
    _total, lines = quote(cases)
    price = {(case_id, what.split()[0]): amount for case_id, what, amount in lines}
    report: dict[str, Any] = {"pricing_version": PRICING_VERSION, "cases": {}}
    failures = 0
    for case in cases:
        entry: dict[str, Any] = {
            "with_product": case["with_product"],
            "media_prompt": case["media"]["prompt"],
        }
        try:
            hold = ledger.reserve(price[(case["id"], "copy")], label=f"{case['id']} copy")
        except CeilingExceededError as exc:
            print(exc, file=sys.stderr)
            return 5
        try:
            result = copy_adapter.generate(case["copy_request"], api_key=claude_key)
        except Exception as exc:  # noqa: BLE001 — a failure is a measurement
            ledger.settle(hold)
            entry["copy_error"] = f"{type(exc).__name__}: {exc}"[:300]
            failures += 1
        else:
            _usage, cost = _copy_usage(pricing, case["copy_request"], result)
            spent = ledger.settle(hold, Decimal(str(round(sum(cost.values()), 6))))
            entry.update(copy=dict(result.payload), copy_model=result.model_id, copy_usd=str(spent))
        size = case["media"]["size"]
        if size:
            try:
                hold = ledger.reserve(price[(case["id"], "imagen")], label=f"{case['id']} imagen")
            except CeilingExceededError as exc:
                print(exc, file=sys.stderr)
                return 5
            request = GenerationRequest(
                task=GenerationTask.PRODUCT_IMAGE,
                rendered_prompt=RenderedPrompt("", "", ""),
                params={
                    "prompt": case["media"]["prompt"],
                    "images": [],
                    "size": size,
                    "model": SEEDREAM_MODEL,
                },
            )
            try:
                image = image_adapter.generate(request, api_key=byteplus.value)
            except Exception as exc:  # noqa: BLE001
                ledger.settle(hold)
                entry["image_error"] = f"{type(exc).__name__}: {exc}"[:300]
                failures += 1
            else:
                ledger.settle(hold)
                name = f"{case['id']}.png"
                (out / name).write_bytes(bytes(image.payload["images"][0]))
                entry.update(image=name, image_model=image.model_id)
        report["cases"][case["id"]] = entry
        print(f"  {case['id']}: {'ok' if 'copy' in entry else 'falló'}")
    report["ledger"] = ledger.snapshot()
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(f"\nGastado: USD {ledger.spent_usd} · informe en {out}")
    return 6 if failures == len(cases) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--i-have-spend-authorization", action="store_true")
    parser.add_argument("--max-usd", type=Decimal, default=Decimal("3"))
    parser.add_argument("--show-prompts", action="store_true")
    args = parser.parse_args(argv)
    _load_env(args.env_file)

    cases = build_cases()
    for case in cases:
        case["media"] = compile_media(case)
        case["copy_request"] = copy_request(case)
    total, lines = quote(cases)
    print(f"{len(cases)} casos · {len(lines)} llamadas pagadas como máximo")
    for case_id, what, amount in lines:
        print(f"  {case_id:<38} {what:<52} USD {amount.quantize(Decimal('0.0001'), ROUND_UP)}")
    print(
        f"Tope estimado: USD {total.quantize(Decimal('0.01'), ROUND_UP)}"
        f" (límite --max-usd {args.max_usd})"
    )
    if args.show_prompts:
        for case in cases:
            print(f"\n== {case['id']}\n{case['media']['prompt']}")
    problems = offline_check(cases)
    for problem in problems:
        print(f"PROBLEMA: {problem}", file=sys.stderr)
    if problems:
        return 1
    print("Comprobación sin costo: ningún prompt de un caso sin producto nombra uno.")
    if not args.i_have_spend_authorization:
        print("Corrida en seco: no se envió nada (usa --i-have-spend-authorization).")
        return 0
    if total > args.max_usd:
        print(f"El tope estimado pasa --max-usd {args.max_usd}: no se envió nada.", file=sys.stderr)
        return 2
    out = HERE / "results" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    return run_paid(cases, out, args.max_usd)


if __name__ == "__main__":
    sys.exit(main())
