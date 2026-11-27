# ruff: noqa: E501  (Spanish prompt text kept verbatim; changing it changes PROMPT_VERSION)
"""SISVIS-002 (spike m-25042530): constrained proposals (schema v1) for real businesses with poor data.

For each business (read-only extract of production kept OUTSIDE the repo, see ``--inputs``) and each
model, ask for 3 ``ProposalV1`` documents, validate them (schema, bounds, closed lists, contrast),
compile the valid ones to the v0 document ``brand_still`` draws, and write the render jobs. Business
data (names, prices, photos) is filled at compose time from the extract, never by the model.

HARD CAP: a running meter refuses a call if the worst case (counted input + max_tokens, at the
most expensive price a fallback could bill) would take the total past ``CAP_USD``. The ledger is a
file, so re-runs count what was already spent.

    PYTHONPATH=packages/creative/src /Users/herwin/dev/Qualify/.venv/bin/python \
        packages/api/evals/sistema_visual/propose_v1.py run
    ... propose_v1.py jobs      # compile valid proposals + write jobs.json (no model calls)
    ... propose_v1.py collect   # read render reports, discard overflow, write metrics + sheets

Client data and images stay under ``/Users/herwin/dev/qualify-eval-out/sistema-visual/sisvis-002/``.
Only anonymous metrics (``metrics.json``) are committed.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import anthropic
from qualify_creative.brand_system.model import BrandVisualSystem
from qualify_creative.brand_system.model_v1 import (
    BACKGROUND_VARIANTS,
    VARIANTS,
    compile_to_v0,
    prompt_reference,
    validate_proposal,
)

HERE = Path(__file__).parent
ENV = Path("/Users/herwin/dev/Qualify/.env")
OUT = Path("/Users/herwin/dev/qualify-eval-out/sistema-visual/sisvis-002")
INPUTS = OUT / "_inputs"
PUBLIC = OUT / "_public"  # Remotion publicDir for these renders
LEDGER = OUT / "_spend.json"
PROMPT_VERSION = "sistema-visual-propose-v1c"  # v1 schema, constrained
CAP_USD = 15.0
MAX_TOKENS = 24000
MODELS = {"fable": ("claude-fable-5-2", 8.0, 40.0), "opus": ("claude-opus-5-5", 4.0, 20.0)}
# fallbacks "default" may bill another model; the meter's worst case uses the dearest price
WORST_IN, WORST_OUT = 8.0, 40.0
# Which businesses and how their extract maps to local folders lives OUTSIDE the repo
# (client names are client data): _inputs/businesses.json, written when the extract was taken.
# SISVIS-002 (founder 2026-11-26): two businesses; the second has only its name stored in «Tu marca»
# (onboarding stopped at «redes», the Instagram prefill was proposed and never accepted).
_LOCAL = (
    json.loads((INPUTS / "businesses.json").read_text())
    if (INPUTS / "businesses.json").exists()
    else {}
)
SLUGS: dict[str, str] = _LOCAL.get("tenant_to_dir", {})
BUSINESSES: list[str] = _LOCAL.get("businesses", [])
NAME_ONLY: dict[str, str] = _LOCAL.get("name_only", {})


# ------------------------------------------------------------------ key + meter
def _key() -> str:
    env = dict(
        line.split("=", 1)
        for line in ENV.read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    for name in ("QUALIFY_ANTHROPIC_EVAL_API_KEY", "QUALIFY_ANTHROPIC_API_KEY"):
        v = env.get(name, "").strip().strip('"').strip("'")
        if v:
            print(f"using {name}")
            return v
    raise SystemExit("no Anthropic key in .env")


def _ledger() -> dict:
    return (
        json.loads(LEDGER.read_text())
        if LEDGER.exists()
        else {"cap_usd": CAP_USD, "spent_usd": 0.0, "calls": []}
    )


def _guard(ledger: dict, input_tokens: int) -> float:
    worst = (input_tokens * WORST_IN + MAX_TOKENS * WORST_OUT) / 1e6
    if ledger["spent_usd"] + worst > CAP_USD:
        raise SystemExit(
            f"METER: refused — spent {ledger['spent_usd']:.4f} + worst {worst:.4f} > cap {CAP_USD}"
        )
    return worst


# ------------------------------------------------------------------ business inputs
def _price(amount: float, currency: str) -> dict:
    if abs(amount - round(amount)) < 1e-9:
        s = f"{int(round(amount)):,}".replace(",", ".")
    else:
        s = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return {"amount": s, "symbol": "$", "code": currency}


def _raster(src: Path, dst: Path, size: int = 1024) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix == ".svg":
        tmp = dst.parent / "_ql"
        tmp.mkdir(exist_ok=True)
        subprocess.run(
            ["qlmanage", "-t", "-s", str(size), "-o", str(tmp), str(src)],
            capture_output=True,
            check=False,
        )
        shutil.move(str(tmp / (src.name + ".png")), dst)
    else:
        fmt = "png" if dst.suffix == ".png" else "jpeg"
        subprocess.run(
            ["sips", "-Z", str(size), "-s", "format", fmt, str(src), "--out", str(dst)],
            capture_output=True,
            check=True,
        )
    return dst


def business(slug_wanted: str) -> dict:
    """The minimum «Tu marca» data, from the read-only extract (local disk only)."""
    if slug_wanted in NAME_ONLY:
        d = json.loads((INPUTS / NAME_ONLY[slug_wanted]).read_text())
        return {
            "slug": slug_wanted,
            "name": d["tenant"],
            "rubro": "",
            "country": d["country"],
            "palette": [],
            "fonts": [],
            "logo": None,
            "handle": None,
            "products": [],
            "hours": None,
            "payments": [],
        }
    files = json.loads((INPUTS / "files.json").read_text())
    for line in (INPUTS / "tenants.jsonl").read_text().splitlines():
        d = json.loads(line)
        slug = SLUGS[d["tenant"]]
        if slug != slug_wanted:
            continue
        f = files[slug]
        prof = d.get("profile") or {}
        prods = []
        for i, p in enumerate(d.get("products") or []):
            photos = [INPUTS / f[k] for k in sorted(f) if k.startswith(f"p{i}-")]
            if not photos or not p.get("price"):
                continue
            prods.append(
                {
                    "name": p["name"],
                    "description": p.get("description") or "",
                    "price": _price(float(p["price"]), p["currency"]),
                    "photos": photos,
                }
            )
        # the same product loaded twice with different capitalization: keep one
        seen, uniq = set(), []
        for p in prods:
            k = p["name"].strip().lower()
            if k not in seen:
                seen.add(k)
                uniq.append(p)
        logo = INPUTS / f["logo"] if "logo" in f else None
        return {
            "slug": slug,
            "name": d["tenant"],
            "rubro": " · ".join(
                x for x in [d.get("positioning") or "", prof.get("category") or ""] if x
            ),
            "country": d["country"],
            "palette": d.get("palette") or [],
            "fonts": [x for x in [d.get("font_heading"), d.get("font_body")] if x],
            "logo": logo,
            "handle": prof.get("username"),
            "products": uniq[:3],
            "hours": None,
            "payments": [],
        }
    raise SystemExit(f"unknown business {slug_wanted}")


SYSTEM = """Eres director de arte para pequeños negocios de Colombia, Venezuela y Uruguay. Propones la IDENTIDAD VISUAL de un negocio como DATOS para un motor de composición (Remotion) que ya tiene la geometría resuelta por el equipo de diseño.

Tú solo eliges, de listas cerradas:
- la paleta por ROLES (hex solo aquí): background, background_alt (segundo tono del fondo), surface (tarjetas, sellos), on_surface (texto sobre surface), ink (texto sobre el fondo), accent (resaltado: segunda línea del titular, precio, etiqueta), on_accent (texto sobre accent), shadow (sombras), pop (decoración);
- tipografías de la lista cerrada (familia y uno de sus pesos): display (titulares y precio), body (descripciones), label (etiquetas y cinta);
- una variante de fondo con parámetros acotados;
- variantes de componentes (etiqueta, titular a dos colores, precio, sello, cinta, marco del producto, tarjeta, logo, destello), cada color como ROL;
- una variante de receta (composición) por tipo de pieza, de la biblioteca;
- el tono: una línea de voz, una etiqueta corta por pieza (≤ 26 caracteres) y hasta 3 frases cortas para la cinta (≤ 28).

No escribes nombres de productos, precios, descripciones, horarios, direcciones ni rutas de imágenes: el motor los toma de los datos del negocio. Nada de hex fuera de `colors`, nada de cajas ni píxeles.

Reglas:
- Contraste alto (WCAG): ink sobre background ≥ 3:1; on_surface sobre surface ≥ 4,5:1; on_accent sobre accent ≥ 3:1; la segunda línea del titular (second_color) sobre background ≥ 3:1. Las propuestas que no lo cumplan se descartan.
- Si el negocio trae colores o logo, respétalos; si no trae, propón una paleta que le siente al rubro.
- Las fotos del negocio son de teléfono y con fondo: el marco del producto debe ser disc, arch, rounded o blob (los cutout_* solo sirven con recortes).
- Español neutro, sin anglicismos ni jerga de un país; nada de promesas que el negocio no hizo (precios, envíos, descuentos, horarios).
- Las tres propuestas deben ser de FAMILIAS DE ESTILO claramente distintas."""


def build_user(b: dict, images: list[Path]) -> list[dict]:
    data = {
        "nombre": b["name"],
        "rubro_y_descripcion": b["rubro"] or "(sin descripción)",
        "pais": b["country"],
        "colores_de_marca": b["palette"] or "(no cargó colores)",
        "tipografias_cargadas": b["fonts"] or "(no cargó)",
        "logo": "sí (primera imagen)" if b["logo"] else "no tiene logo cargado",
        "productos": [
            {
                "nombre": p["name"],
                "descripcion": p["description"] or "(sin descripción)",
                "precio": f"{p['price']['symbol']}{p['price']['amount']} {p['price']['code']}",
                "fotos": len(p["photos"]),
            }
            for p in b["products"]
        ],
        "horario": "no lo cargó",
        "direccion": "no la cargó",
        "medios_de_pago": "no los cargó",
    }
    ex = {
        "id": f"{b['slug']}-ejemplo",
        "name": "Nombre corto",
        "style_family": "familia de estilo",
        "rationale": "Dos frases: por qué le sirve a este negocio.",
        "colors": {
            r: "#RRGGBB"
            for r in (
                "background",
                "background_alt",
                "surface",
                "on_surface",
                "ink",
                "accent",
                "on_accent",
                "shadow",
                "pop",
            )
        },
        "typography": {
            "display": {
                "family": "…",
                "weight": 800,
                "letter_spacing_em": -0.03,
                "uppercase": False,
            },
            "body": {"family": "…", "weight": 600},
            "label": {"family": "…", "weight": 800, "letter_spacing_em": 0.08, "uppercase": True},
        },
        "background": {
            "variant": "rays",
            "color": "pop",
            "opacity": 0.25,
            "scale": 1.0,
            "angle_deg": 0,
        },
        "shapes": {"radius_px": 24, "tilt_deg": -2, "shadow": "hard", "shadow_offset_px": 8},
        "components": {
            "tag": {
                "variant": "tilted_block|pill|outline|underline|plain",
                "fill": "accent",
                "ink": "on_accent",
            },
            "headline": {
                "variant": "two_tone_stacked|single_color|outline_second|highlight_second",
                "split": "first_word|last_word|none",
                "first_color": "ink",
                "second_color": "accent",
                "shadow": True,
            },
            "price": {
                "variant": "flag|badge|circle|ticket|plain",
                "fill": "accent",
                "ink": "on_accent",
                "show_code": True,
            },
            "stamp": {
                "variant": "circle_ring|starburst|scallop|none",
                "fill": "surface",
                "ink": "background",
                "ring": "accent",
            },
            "ticker": {"enabled": True, "fill": "accent", "ink": "on_accent"},
            "product_frame": {
                "variant": "disc|arch|rounded|blob",
                "ring": "surface",
                "glow": "accent",
            },
            "info_card": {
                "variant": "card|chip|outline|plain",
                "fill": "surface",
                "ink": "on_surface",
            },
            "logo": {"variant": "plain|on_badge", "badge": "surface"},
            "sparkle": {"enabled": True, "color": "surface"},
        },
        "tone": {
            "voice": "una línea",
            "tags": {"product_hero": "…", "product_alt": "…", "story": "…"},
            "ticker": ["…", "…"],
        },
        "recipes": {
            "product_hero": "product_hero.… (4:5)",
            "product_alt": "product_hero.… (4:5, otra pieza de producto)",
            "story": "story.… (9:16)",
        },
    }
    text = f"""Datos del negocio (lo que el dueño cargó en «Tu marca»):
{json.dumps(data, ensure_ascii=False, indent=1)}

{prompt_reference()}

{"ATENCIÓN: el negocio no tiene productos ni fotos cargados; las piezas mostrarán solo el nombre del negocio. " if not b["products"] else ""}Piezas que se dibujarán: product_hero (producto estrella con su precio, 4:5), product_alt (segundo producto o el mismo con otra foto, 4:5; elige otra variante si quieres variedad), story (historia 9:16 con una foto del producto). No hay horario cargado: no elijas receta de horario.

Forma de cada propuesta (cumple tipos y rangos: opacity 0,05–0,6; scale 0,5–2; angle_deg −45–45; radius_px 0–60; tilt_deg −6–6; shadow_offset_px 0–16; letter_spacing_em −0,08–0,2; variantes de fondo: {", ".join(BACKGROUND_VARIANTS)}):
{json.dumps(ex, ensure_ascii=False, indent=1)}

Responde SOLO con un objeto JSON {{"proposals": [p1, p2, p3]}}, sin texto alrededor."""
    content: list[dict] = []
    for p in images:
        media = "image/png" if p.suffix == ".png" else "image/jpeg"
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media,
                    "data": base64.b64encode(p.read_bytes()).decode(),
                },
            }
        )
    content.append({"type": "text", "text": text})
    return content


def _json_from(text: str) -> dict:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1)
    return json.loads(t[t.find("{") : t.rfind("}") + 1])


def run(slugs: list[str], models: list[str]) -> None:
    client = anthropic.Anthropic(api_key=_key(), max_retries=2)
    ledger = _ledger()
    for slug in slugs:
        b = business(slug)
        imgs: list[Path] = []
        if b["logo"]:
            imgs.append(_raster(b["logo"], OUT / slug / "_model" / "logo.png", 600))
        for i, p in enumerate(b["products"][:2]):
            imgs.append(_raster(p["photos"][0], OUT / slug / "_model" / f"p{i}.jpg", 1024))
        content = build_user(b, imgs)
        for mk in models:
            model, pin, pout = MODELS[mk]
            run_dir = OUT / slug / mk
            run_dir.mkdir(parents=True, exist_ok=True)
            counted = client.messages.count_tokens(
                model=model, system=SYSTEM, messages=[{"role": "user", "content": content}]
            ).input_tokens
            worst = _guard(ledger, counted)
            print(
                f"{slug}/{mk}: input {counted} tok, worst case US${worst:.3f}, spent so far US${ledger['spent_usd']:.4f}"
            )
            t0 = time.time()
            with client.beta.messages.stream(
                model=model,
                max_tokens=MAX_TOKENS,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": "high"},
                system=SYSTEM,
                messages=[{"role": "user", "content": content}],
            ) as stream:
                msg = stream.get_final_message()
            secs = time.time() - t0
            served = msg.model
            sin, sout = next(
                ((a, c) for (m, a, c) in MODELS.values() if m == served), (WORST_IN, WORST_OUT)
            )
            usd = (msg.usage.input_tokens * sin + msg.usage.output_tokens * sout) / 1e6
            ledger["spent_usd"] = round(ledger["spent_usd"] + usd, 6)
            call = {
                "business": slug,
                "model_key": mk,
                "model_requested": model,
                "model_served": served,
                "prompt_version": PROMPT_VERSION,
                "input_tokens": msg.usage.input_tokens,
                "output_tokens": msg.usage.output_tokens,
                "usd": round(usd, 4),
                "seconds": round(secs, 1),
                "stop_reason": msg.stop_reason,
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            ledger["calls"].append(call)
            LEDGER.write_text(json.dumps(ledger, indent=1))
            print(json.dumps(call))
            text = "".join(bl.text for bl in msg.content if bl.type == "text")
            (run_dir / "raw.txt").write_text(text)
            try:
                props = _json_from(text).get("proposals", [])
            except Exception as e:  # noqa: BLE001 — a broken answer is a result, recorded
                props = []
                (run_dir / "parse_error.txt").write_text(repr(e))
            (run_dir / "proposals.json").write_text(json.dumps(props, ensure_ascii=False, indent=1))
    print(f"TOTAL spent US${ledger['spent_usd']:.4f} of cap {CAP_USD}")


# ------------------------------------------------------------------ compile + jobs
def _asset(src: Path, slug: str) -> str:
    dst = PUBLIC / slug / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy(src, dst)
    return f"{slug}/{src.name}"


def contents(b: dict, tags: dict, ticker: list[str]) -> dict[str, dict]:
    slug = b["slug"]
    logo = _asset(b["logo"], slug) if b["logo"] else None
    brand = {
        "name": b["name"],
        "logo": logo,
        "handle": f"@{b['handle']}" if b["handle"] else b["name"],
    }
    if not b["products"]:
        # nothing to sell on the piece: only the business name, no price, no photo (a finding)
        empty = {
            "title": b["name"],
            "description": "",
            "price": None,
            "photo": None,
            "cutout": False,
        }
        base = {"brand": brand, "ticker": ticker}
        return {
            "product_hero": {**base, "product": empty},
            "product_alt": {**base, "product": empty},
            "story": {
                **base,
                "story": {
                    "photo": None,
                    "kicker": tags.get("story", ""),
                    "title": b["name"],
                    "place": brand["handle"],
                    "ticker": ticker,
                },
            },
        }
    p0 = b["products"][0]
    alt = b["products"][1] if len(b["products"]) > 1 else None

    def prod(p: dict, photo_idx: int = 0) -> dict:
        ph = p["photos"][min(photo_idx, len(p["photos"]) - 1)]
        return {
            "title": p["name"],
            "description": p["description"],
            "price": p["price"],
            "photo": _asset(ph, slug),
            "cutout": False,
        }

    alt_prod = prod(alt) if alt else prod(p0, 1)
    story_photo = p0["photos"][1] if len(p0["photos"]) > 1 else p0["photos"][0]
    base = {"brand": brand, "ticker": ticker}
    return {
        "product_hero": {**base, "product": prod(p0)},
        "product_alt": {**base, "product": alt_prod},
        "story": {
            **base,
            "story": {
                "photo": _asset(story_photo, slug),
                "kicker": tags.get("story", ""),
                "title": p0["name"],
                "place": brand["handle"],
                "ticker": ticker,
            },
        },
    }


def jobs(slugs: list[str]) -> None:
    out_jobs = []
    summary = {}
    for slug in slugs:
        b = business(slug)
        for mk in MODELS:
            run_dir = OUT / slug / mk
            pf = run_dir / "proposals.json"
            if not pf.exists():
                continue
            props = json.loads(pf.read_text())
            res = []
            for n, raw in enumerate(props, 1):
                p, problems = validate_proposal(raw)
                entry = {
                    "n": n,
                    "name": raw.get("name"),
                    "style_family": raw.get("style_family"),
                    "valid": p is not None,
                    "problems": problems,
                }
                if p is not None:
                    v0 = compile_to_v0(
                        p,
                        brand=b["name"],
                        model=MODELS[mk][0],
                        prompt_version=PROMPT_VERSION,
                        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
                    )
                    BrandVisualSystem.model_validate(
                        v0
                    )  # the compiled document is a valid v0 system
                    sysf = run_dir / f"p{n}.system.json"
                    sysf.write_text(json.dumps(v0, ensure_ascii=False, indent=1))
                    for piece, content in contents(b, p.tone.tags, p.tone.ticker).items():
                        cf = run_dir / f"p{n}.{piece}.content.json"
                        cf.write_text(json.dumps(content, ensure_ascii=False, indent=1))
                        out_jobs.append(
                            {
                                "system": str(sysf),
                                "recipe": piece,
                                "content": str(cf),
                                "out": str(run_dir / f"p{n}-{piece}.png"),
                            }
                        )
                    entry["recipes"] = dict(p.recipes)
                    entry["fonts"] = [p.typography.display.family, p.typography.body.family]
                    entry["background"] = p.background.variant
                res.append(entry)
            (run_dir / "validation.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
            summary[f"{slug}/{mk}"] = [(e["n"], e["valid"], e["problems"][:2]) for e in res]
    (OUT / "jobs.json").write_text(
        json.dumps({"publicDir": str(PUBLIC), "jobs": out_jobs}, indent=1)
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"{len(out_jobs)} jobs -> {OUT / 'jobs.json'}")


# ------------------------------------------------------------------ collect: discards, metrics, sheets
PIECE_COLS = [
    ("product_hero", "Producto estrella (4:5)", 675),
    ("product_alt", "Segundo producto (4:5)", 675),
    ("story", "Historia (9:16)", 960),
]


def collect(slugs: list[str]) -> None:
    ledger = _ledger()
    metrics: dict = {
        "spike": "m-25042530",
        "test": "SISVIS-002",
        "prompt_version": PROMPT_VERSION,
        "cap_usd": CAP_USD,
        "spent_usd": ledger["spent_usd"],
        "businesses": {},
    }
    sheet_jobs = []
    for bi, slug in enumerate(slugs, 1):
        anon = f"negocio-{bi}"
        rows = []
        bm = {}
        for mk in MODELS:
            run_dir = OUT / slug / mk
            vf = run_dir / "validation.json"
            if not vf.exists():
                continue
            val = json.loads(vf.read_text())
            call = next(
                (
                    c
                    for c in reversed(ledger["calls"])
                    if c["business"] == slug and c["model_key"] == mk
                ),
                {},
            )
            kept, discarded_render = 0, []
            for e in val:
                label = f"{mk.capitalize()} · P{e['n']} · {e.get('name') or '?'}"
                if not e["valid"]:
                    rows.append(
                        {
                            "label": label,
                            "note": "DESCARTADA (validación): "
                            + "; ".join(e["problems"][:2])[:160],
                            "cells": [None, None, None],
                        }
                    )
                    continue
                warns = []
                for piece, _, _ in PIECE_COLS:
                    rf = run_dir / f"p{e['n']}-{piece}.png.report.json"
                    if rf.exists():
                        warns += [w for w in json.loads(rf.read_text())["warnings"]]
                bad = [
                    w
                    for w in warns
                    if "dropped" in w
                    or (w.startswith("text_stack scaled to") and float(w.split()[3]) < 0.85)
                ]
                if bad:
                    discarded_render.append({"n": e["n"], "warnings": bad})
                else:
                    kept += 1
                note = f"{e.get('style_family')} · {' + '.join(e.get('fonts', []))} · fondo {e.get('background')}"
                if bad:
                    note = "DESCARTADA (render): " + "; ".join(bad)[:140]
                elif warns:
                    note += " · ajuste: " + "; ".join(warns)[:80]
                rows.append(
                    {
                        "label": label,
                        "note": note,
                        "cells": [
                            {"src": f"{slug}/{mk}/p{e['n']}-{piece}.png", "cellH": h}
                            for piece, _, h in PIECE_COLS
                        ],
                    }
                )
            families = {(e.get("style_family") or "").lower() for e in val}
            bm[mk] = {
                "input_tokens": call.get("input_tokens"),
                "output_tokens": call.get("output_tokens"),
                "usd": call.get("usd"),
                "seconds": call.get("seconds"),
                "model_served": call.get("model_served"),
                "proposals": len(val),
                "valid_first_try": sum(1 for e in val if e["valid"]),
                "discarded_validation": [
                    {"n": e["n"], "problems": e["problems"]} for e in val if not e["valid"]
                ],
                "discarded_render": discarded_render,
                "kept": kept,
                "distinct_families": len(families),
                "recipes": [e.get("recipes") for e in val if e["valid"]],
                "fonts": [e.get("fonts") for e in val if e["valid"]],
            }
        metrics["businesses"][anon] = bm
        props = {
            "title": f"SISVIS-002 · {slug} · Fable 5.2 (arriba) vs Opus 5.5 (abajo)",
            "subtitle": "Esquema v1 restringido · geometría de la biblioteca v1 · datos y fotos del negocio tal cual",
            "cell": {"w": 400, "h": 500},
            "columns": [c for _, c, _ in PIECE_COLS],
            "rows": [
                {
                    **r,
                    "cells": [
                        ({**c, "cellH": int(c["cellH"] * 400 / 540)} if c else None)
                        for c in r["cells"]
                    ],
                }
                for r in rows
            ],
        }
        pf = OUT / slug / "sheet.props.json"
        pf.write_text(json.dumps(props, ensure_ascii=False, indent=1))
        sheet_jobs.append(
            {
                "composition": "brand-still-contact-sheet",
                "props": str(pf),
                "out": str(OUT / slug / f"vista-general-{slug}.jpg"),
            }
        )
    (OUT / "sheets.jobs.json").write_text(
        json.dumps({"publicDir": str(OUT), "jobs": sheet_jobs}, indent=1)
    )
    (HERE / "sisvis002_metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1))
    print(json.dumps(metrics, ensure_ascii=False, indent=1)[:4000])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    biz = BUSINESSES
    if cmd == "run":
        run(
            biz if len(sys.argv) < 3 else sys.argv[2].split(","),
            list(MODELS) if len(sys.argv) < 4 else sys.argv[3].split(","),
        )
    elif cmd == "jobs":
        jobs(biz)
    elif cmd == "collect":
        collect(biz)
    _ = VARIANTS
