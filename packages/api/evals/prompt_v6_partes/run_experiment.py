"""EF-11 part prompt v6 vs its baseline, paid on Seedance (m-25078702).

A `reference` part of a video by parts that carries product photos, made two ways by the
REAL `MediaProducer.produce` and the REAL `SeedanceVideoAdapter`:

- `v6`: the part has a stretch of the owner's own video and
  `QUALIFY_PARTS_PREPARED_FRAME_REFS=on` in THIS process — the prepared opening frame
  travels as reference «Image 1», the photos from «Image 2», part prompt version 6
  (`part_reference_prompt(opening_frame=True)`).
- `base`: the same part without stretches (what main does today with the switch off):
  the photos alone, the part prompt of its compiler.

Same model, resolution (the 2.5 draft, 480p), seconds, product photo, description and
brand in both. Without `--cases`: repo material only — the generator's sample product
photos (`packages/render/public/sample/`) and its own effect videos as the «own video»
(`assets/effects/*/v1/preview.webm`). With `--cases <file.json>` (OUTSIDE the repo,
`{"kit": {...}, "cases": [...]}`, paths relative to the file): real material of one of our
businesses, read beforehand and kept out of the repository. No Claude call: the copy is
fixed (a part's prompt does not use it).

Prices from the versioned table (`composition.PRICING_VERSION`): every task is quoted
with the adapter's own token formula BEFORE it is sent, reserved with a margin in a
`SpendLedger` whose ceiling is `--max-usd`, and settled with the tokens ModelArk bills.
A reservation that would pass the ceiling stops the run (retries included). Video evals
run only in the off-hours window (`byteplus_eval_guard.off_hours_refusal`), one task at a
time; `--allow-daytime` is the guard's override, only with a decision on record. Outputs
(videos, reference images sent, prompts, 3 keyframes per video and a
contact sheet per case) go OUTSIDE the repo: `%TEMP%/m-25078702/<stamp>/` by default.

    # dry run: compiles both requests through the real producer, quotes, sends nothing
    uv run --no-sync python packages/api/evals/prompt_v6_partes/run_experiment.py \\
        --env-file ../../.env
    # paid (Deivid authorized USD 2 in all on 2026-11-20); results: EF11-001 in
    # docs/modelos-generativos/seedance-2-5.md
    uv run --no-sync python packages/api/evals/prompt_v6_partes/run_experiment.py \\
        --env-file ../../.env --cases <outside>/casos.json --i-have-spend-authorization \\
        --max-usd 2
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import tempfile
from datetime import datetime
from decimal import ROUND_UP, Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
#: A fictitious business: the keys only need to be «this tenant's» (`owned_by`).
TENANT_ID = UUID("7e7e0000-0000-4000-8000-0000000000f6")
BRAND_ID = UUID("7e7e0000-0000-4000-8000-0000000000f7")
MODEL = "dreamina-seedance-2-5-260628"
#: A part of 4 s: Seedance's minimum and the cheapest length (`PART_GENERATION_MIN_SECONDS`).
SECONDS = 4
#: The quote is ModelArk's formula; billed tokens ran ~2 % over it on 2026-10-23
#: (49,673 vs 48.6k): each task is reserved 10 % over its quote.
RESERVE_MARGIN = Decimal("1.10")
VARIANTS = ("base", "v6")

CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "fresa-brasas",
        "product": "Dona glaseada de fresa",
        "photo": "packages/render/public/sample/photo-1.jpg",
        "own": "assets/effects/brasas_capa/v1/preview.webm",
        "start_s": 1.0,
        "end_s": 4.0,
        "description": (
            "Chispas de brasa suben en la oscuridad y la dona de fresa aparece en primer "
            "plano, girando despacio."
        ),
    },
    {
        "id": "mango-vapor",
        "product": "Dona glaseada de mango",
        "photo": "packages/render/public/sample/photo-2.jpg",
        "own": "assets/effects/vapor_capa/v1/preview.webm",
        "start_s": 1.0,
        "end_s": 4.0,
        "description": (
            "Entre el vapor sobre un fondo oscuro aparece la dona de mango en primer plano, "
            "recién hecha."
        ),
    },
)


class DryRun(Exception):
    """Raised instead of sending: the request was captured and quoted."""


def _load_env(path: str | None) -> None:
    if not path or not Path(path).is_file():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


#: The sample brand of the repo cases; a `--cases` file may bring its own `kit`.
SAMPLE_KIT: dict[str, Any] = {
    "positioning": "Donas glaseadas hechas cada mañana",
    "audience": "Familias y jóvenes del barrio",
    "palette_rgb": ["#5A2826", "#F3C1C2", "#FDE0B4"],
    "font_heading": "Poppins",
    "font_body": "Inter",
}


def _kit(fields: dict[str, Any]) -> Any:
    from qualify_creative.schemas import BrandKit, ToneAxes

    return BrandKit(
        brand_id=BRAND_ID,
        tone_axes=ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        ),
        **{**SAMPLE_KIT, **fields},
    )


def _load_cases(path: str | None) -> tuple[list[dict[str, Any]], dict[str, Any], Path]:
    """The repo sample cases, or a JSON file OUTSIDE the repo (`{"kit": {...}, "cases":
    [...]}`, paths relative to the file) — how real material of one of our businesses is
    measured without entering the repository."""
    if not path:
        return list(CASES), {}, REPO
    file = Path(path).resolve()
    data = json.loads(file.read_text(encoding="utf-8"))
    return list(data["cases"]), dict(data.get("kit") or {}), file.parent


def _keys(case: dict[str, Any]) -> tuple[str, str]:
    photo = f"uploads/{TENANT_ID}/{case['id']}-producto.jpg"
    suffix = Path(case["own"]).suffix.lower() or ".mp4"
    own = f"uploads/{TENANT_ID}/{case['id']}-propio{suffix}"
    return photo, own


def _brief(case: dict[str, Any], variant: str) -> Any:
    """The part's child Clip: the same in both variants except the own stretch."""
    from qualify_creative.enums import BriefObjective, ContentFormat, ContentKind, ImageRoute
    from qualify_creative.schemas import ContentBrief, MediaInputs, PartRef, SourceSegment

    from qualify_api.creative.media import PROMPT_COMPILER_VERSION

    photo, own = _keys(case)
    segments = (
        (SourceSegment(key=own, start_s=case["start_s"], end_s=case["end_s"], kind="video"),)
        if variant == "v6"
        else ()
    )
    part = PartRef(
        index=2,
        mode="reference",
        seconds=SECONDS,
        description=case["description"],
        segments=segments,
    )
    return ContentBrief(
        brand_id=BRAND_ID,
        objective=BriefObjective.SALE,
        topic=case["product"],
        product_ref=case["product"],
        image_route=ImageRoute.TEMPLATE_ONLY,
        kind=ContentKind.CLIP,
        format=ContentFormat.REELS_9_16,
        media=MediaInputs(
            part=part,
            duration_seconds=part.generation_seconds,
            clip_reference_mode="motion",
            clip_image_keys=(photo,),
            clip_image_roles=("product",),
            prompt_compiler_version=PROMPT_COMPILER_VERSION,
        ),
    )


class MemoryStore:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)

    def read(self, key: str) -> bytes:
        if key not in self.files:
            raise FileNotFoundError(key)
        return self.files[key]

    def write(self, key: str, data: bytes) -> None:
        self.files[key] = data


class EvalKeys:
    """The eval key for every BytePlus call (`resolve_eval_key`); never printed."""

    def __init__(self, key: Any) -> None:
        self._key = key

    def resolve(self, *, tenant_id: UUID, brand_id: UUID, provider: str) -> Any:
        from qualify_creative.enums import PaidBy
        from qualify_creative.providers import ResolvedKey

        return ResolvedKey(
            api_key=self._key.value, paid_by=PaidBy.PLATFORM, fingerprint=self._key.fingerprint
        )


class GuardedSeedance:
    """The real adapter behind the run's ledger: every attempt (a producer retry too) is
    quoted with the adapter's formula and reserved before it is sent; settled with the
    tokens ModelArk billed. Dry: captures the request and raises `DryRun`."""

    name = "seedance"

    def __init__(self, inner: Any, ledger: Any, pricing: Any, *, dry: bool) -> None:
        self.inner = inner
        self.supports = inner.supports
        self.ledger = ledger
        self.pricing = pricing
        self.dry = dry
        self.label = ""
        self.calls: list[dict[str, Any]] = []

    def estimate_cost_usd(self, request: Any, pricing: Any, **kwargs: Any) -> Any:
        return self.inner.estimate_cost_usd(request, pricing, **kwargs)

    def generate(self, request: Any, *, api_key: str) -> Any:
        from qualify_creative.adapters.byteplus_ark import video_cost_usd

        quote = self.inner.estimate_cost_usd(request, self.pricing)
        call: dict[str, Any] = {"label": self.label, "quote_usd": str(quote), "request": request}
        self.calls.append(call)
        if self.dry:
            raise DryRun(self.label)
        reserve = (quote * RESERVE_MARGIN).quantize(Decimal("0.0001"), ROUND_UP)
        hold = self.ledger.reserve(reserve, label=self.label)
        try:
            result = self.inner.generate(request, api_key=api_key)
        except Exception as exc:
            # a failed task may still have been billed: the reservation counts as spent
            call["error"] = f"{type(exc).__name__}: {exc}"[:400]
            call["cost_usd"] = str(self.ledger.settle(hold))
            call["cost_kind"] = "reservado (falló)"
            raise
        tokens = result.usage.output_tokens
        resolution = str(result.payload.get("resolution") or request.params.get("resolution"))
        actual = (
            video_cost_usd(self.pricing, result.model_id, resolution, int(tokens))
            if tokens
            else None
        )
        call.update(
            task_id=result.payload.get("task_id"),
            model_id=result.model_id,
            resolution=resolution,
            billed_tokens=tokens,
            cost_usd=str(self.ledger.settle(hold, actual)),
            cost_kind="facturado (tokens)" if actual is not None else "reservado",
        )
        return result


def _producer(store: MemoryStore, router: Any, keys: EvalKeys, pricing: Any) -> Any:
    from qualify_api.creative.media import MediaProducer

    return MediaProducer(
        store=store,
        router=router,
        credentials=keys,
        pricing=pricing,
        seedance_model=MODEL,
        seedance_reference_model=MODEL,
    )


def _copy() -> Any:
    from qualify_creative.schemas import CopyPayload

    return CopyPayload(hook="Recién hechas", caption="-", cta="Pide la tuya")


def _decode_data_url(url: str) -> bytes:
    return base64.b64decode(url.partition(",")[2])


def _keyframes(video: bytes) -> list[Any]:
    """First, middle and last frame of `video` as PIL images."""
    import av

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as handle:
        handle.write(video)
        path = handle.name
    try:
        with av.open(path) as container:
            frames = [frame.to_image().convert("RGB") for frame in container.decode(video=0)]
    finally:
        os.unlink(path)
    return [frames[0], frames[len(frames) // 2], frames[-1]]


def _distance(a: Any, b: Any) -> float:
    """Mean absolute difference (0-255) of two images at 90x160, a rough «how far is the
    video's first frame from the opening frame»."""
    from PIL import ImageChops, ImageStat

    size = (90, 160)
    diff = ImageChops.difference(a.convert("RGB").resize(size), b.convert("RGB").resize(size))
    return round(sum(ImageStat.Stat(diff).mean) / 3, 1)


def _sheet(rows: list[list[Any]], path: Path) -> None:
    from PIL import Image

    height = 427
    cells = [
        [img.resize((round(img.width * height / img.height), height)) for img in row]
        for row in rows
    ]
    width = max(sum(img.width for img in row) + 8 * (len(row) - 1) for row in cells)
    sheet = Image.new("RGB", (width, height * len(cells) + 8 * (len(cells) - 1)), (255, 255, 255))
    y = 0
    for row in cells:
        x = 0
        for img in row:
            sheet.paste(img, (x, y))
            x += img.width + 8
        y += height + 8
    sheet.save(path, quality=88)


def run(args: argparse.Namespace) -> int:
    from qualify_creative.adapters.byteplus_ark import SeedanceVideoAdapter
    from qualify_creative.pricing import JsonPricingTable
    from qualify_creative.router import BudgetContext, CreativeRouter

    from qualify_api.creative.composition import PRICING_VERSION
    from qualify_api.creative.media import part_prompt_version
    from qualify_api.creative.video_pipeline.prepared_frame import PREPARED_FRAME_REFS_SWITCH
    from qualify_api.evals.byteplus_eval_guard import (
        EvalKeyError,
        off_hours_refusal,
        resolve_eval_key,
    )
    from qualify_api.evals.spend_control import CeilingExceededError, SpendLedger

    paid = args.i_have_spend_authorization
    try:
        key = resolve_eval_key()
    except EvalKeyError as exc:
        print(exc, file=sys.stderr)
        return 2
    print(key.describe())
    if paid:
        # `--allow-daytime`: the guard's own override, only with a decision on record
        refusal = off_hours_refusal(allow_daytime=args.allow_daytime)
        if refusal:
            print(refusal, file=sys.stderr)
            return 3
    pricing = JsonPricingTable(PRICING_VERSION)
    ledger = SpendLedger(args.max_usd)
    guarded = GuardedSeedance(SeedanceVideoAdapter(model=MODEL), ledger, pricing, dry=not paid)
    keys = EvalKeys(key)
    router = CreativeRouter({"seedance": guarded}, pricing, keys)
    out = Path(args.out) / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    all_cases, kit_fields, base = _load_cases(args.cases)
    kit = _kit(kit_fields)
    report: dict[str, Any] = {
        "ticket": "m-25078702",
        "model": MODEL,
        "seconds": SECONDS,
        "pricing_version": PRICING_VERSION,
        "paid": paid,
        "daytime_override": bool(paid and args.allow_daytime),
        "cases": {},
    }
    cases = [c for c in all_cases if not args.case or c["id"] in args.case]
    for case in cases:
        photo, own = _keys(case)
        files = {
            photo: (base / case["photo"]).read_bytes(),
            own: (base / case["own"]).read_bytes(),
        }
        case_dir = out / case["id"]
        case_dir.mkdir()
        entry: dict[str, Any] = {"product": case["product"], "variants": {}}
        report["cases"][case["id"]] = entry
        for variant in VARIANTS:
            os.environ[PREPARED_FRAME_REFS_SWITCH] = "on" if variant == "v6" else "off"
            brief = _brief(case, variant)
            store = MemoryStore(files)
            producer = _producer(store, router, keys, pricing)
            guarded.label = f"{case['id']}/{variant}"
            calls_before = len(guarded.calls)
            budget = BudgetContext(remaining_usd=ledger.remaining_usd)
            try:
                outcome = producer.produce(
                    tenant_id=TENANT_ID,
                    draft_id=uuid4(),
                    brief=brief,
                    kit=kit,
                    copy=_copy(),
                    budget=budget,
                )
            except CeilingExceededError as exc:
                print(f"TOPE: {exc}", file=sys.stderr)
                report["stopped"] = str(exc)
                break
            calls = guarded.calls[calls_before:]
            item: dict[str, Any] = {
                "failure": outcome.failure,
                "detail": outcome.detail,
                "attempts": [],
            }
            for i, call in enumerate(calls, 1):
                params = dict(call["request"].params)
                prompt = str(params.get("prompt", ""))
                (case_dir / f"{variant}-prompt-{i}.txt").write_text(prompt, encoding="utf-8")
                sent = [str(u) for u in params.get("reference_images", ()) or ()]
                for n, url in enumerate(sent, 1):
                    (case_dir / f"{variant}-enviada-{i}-image{n}.jpg").write_bytes(
                        _decode_data_url(url)
                    )
                item["attempts"].append(
                    {
                        **{k: v for k, v in call.items() if k != "request"},
                        "prompt_words": len(prompt.split()),
                        "reference_images": len(sent),
                        "first_frame": "first_frame" in params,
                        "params": {
                            k: v
                            for k, v in params.items()
                            if k not in {"prompt", "reference_images", "first_frame"}
                        },
                    }
                )
            if outcome.media:
                video = outcome.media[0]
                item["prompt_version"] = video.params.get("part_prompt_version")
                item["reference_manifest"] = video.params.get("reference_manifest")
                data = store.read(video.object_key)
                (case_dir / f"{variant}.mp4").write_bytes(data)
                frames = _keyframes(data)
                for name, frame in zip(("inicio", "medio", "final"), frames, strict=True):
                    frame.save(case_dir / f"{variant}-{name}.jpg", quality=90)
                item["video_size"] = list(frames[0].size)
            else:
                item["prompt_version"] = part_prompt_version(brief, opening_frame=variant == "v6")
            entry["variants"][variant] = item
            print(
                f"  {guarded.label}: "
                + (
                    "ok"
                    if outcome.media
                    else ("compilado (seco)" if not paid else f"falló: {outcome.detail}")
                )
                + "".join(f" · cotizado USD {a['quote_usd']}" for a in item["attempts"])
            )
        else:
            _case_sheet(case_dir, entry)
            continue
        break
    os.environ.pop(PREPARED_FRAME_REFS_SWITCH, None)
    report["ledger"] = ledger.snapshot()
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    quoted = sum(
        (
            Decimal(a["quote_usd"])
            for c in report["cases"].values()
            for v in c["variants"].values()
            for a in v["attempts"]
        ),
        Decimal(0),
    )
    print(f"\nCotizado: USD {quoted} · gastado: USD {ledger.spent_usd} · informe en {out}")
    return 0


def _case_sheet(case_dir: Path, entry: dict[str, Any]) -> None:
    """Row 1: v6's opening frame sent + its 3 keyframes; row 2: the product photo + the
    baseline's 3 keyframes. And the continuity distance of each first frame."""
    from PIL import Image

    opening = case_dir / "v6-enviada-1-image1.jpg"
    rows = []
    for variant, first_cell in (("v6", opening), ("base", case_dir / "base-enviada-1-image1.jpg")):
        names = [case_dir / f"{variant}-{n}.jpg" for n in ("inicio", "medio", "final")]
        if not first_cell.exists() or not all(p.exists() for p in names):
            return
        rows.append([Image.open(first_cell), *(Image.open(p) for p in names)])
    _sheet(rows, case_dir / "comparacion.jpg")
    if opening.exists():
        frame = Image.open(opening)
        for variant in VARIANTS:
            first = Image.open(case_dir / f"{variant}-inicio.jpg")
            entry["variants"][variant]["distance_to_opening_frame"] = _distance(first, frame)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--i-have-spend-authorization", action="store_true")
    parser.add_argument("--max-usd", type=Decimal, default=Decimal("2"))
    parser.add_argument("--case", action="append", help="only these case ids")
    parser.add_argument("--cases", help="JSON of cases outside the repo (real material)")
    parser.add_argument(
        "--allow-daytime",
        action="store_true",
        help="run outside 23:00-05:00 Bogotá (byteplus_eval_guard): only with a decision on record",
    )
    parser.add_argument(
        "--out", default=str(Path(tempfile.gettempdir()) / "m-25078702"), help="outside the repo"
    )
    args = parser.parse_args(argv)
    _load_env(args.env_file)
    for path in (args.out, args.cases):
        if path and Path(path).resolve().is_relative_to(REPO):
            print("--out and --cases must be outside the repository", file=sys.stderr)
            return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
