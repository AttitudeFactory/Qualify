# ruff: noqa: E501  (Spanish prompt text kept verbatim; changing it changes PROMPT_VERSION)
"""Spike m-25042530 — ask Claude for 3 BrandVisualSystem proposals for a brand, from scratch.

Input: ONLY what a Qualify client has after completing «Tu marca» (``brand_input.json``: name,
rubro, logo, colours/fonts if any, 1–3 products with photo and price, hours/address/payments if
known). Output: ``out/<run>/proposals.json`` + one ``propuesta-N.system.json`` per proposal, each
validated against the pydantic model (the JSON Schema's source). A proposal that does not
validate is KEPT (``propuesta-N.invalid.json`` + the errors) — never hand-edited.

Live call (paid). Run by hand only:

    PYTHONPATH=packages/creative/src /Users/herwin/dev/Qualify/.venv/bin/python \
        packages/api/evals/sistema_visual/propose.py polette

The key is read from the main checkout's .env (QUALIFY_ANTHROPIC_EVAL_API_KEY if present, else
QUALIFY_ANTHROPIC_API_KEY) and never printed. Tokens and USD are written to ``usage.json``.
"""

from __future__ import annotations

import base64
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import anthropic
from pydantic import ValidationError
from qualify_creative.brand_system.model import BrandVisualSystem, export_schema

HERE = Path(__file__).parent
ENV = Path("/Users/herwin/dev/Qualify/.env")
MODEL = "claude-fable-5-2"
PROMPT_VERSION = "sistema-visual-propose-v1"
# USD per million tokens (claude-api skill table, cached 2026-11-03).
PRICE = {
    "claude-fable-5-2": (8.0, 40.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-4-8": (5.0, 25.0),
}


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


SYSTEM = """Eres director de arte para pequeños negocios de comida en Colombia, Venezuela y Uruguay.
Diseñas SISTEMAS VISUALES DE MARCA como DATOS: un documento JSON que un motor de composición
(Remotion) convierte en piezas para Instagram. No escribes código ni HTML: eliges tokens,
variantes de componentes y recetas (composiciones con huecos) dentro del esquema dado.

Cómo dibuja el motor (léelo como un manual de la biblioteca de componentes):
- Lienzo de 1080 px de ancho; alto 1350 (4:5), 1080 (1:1) o 1920 (9:16). `box` = [x, y, ancho, alto]
  en FRACCIONES del lienzo (puede salirse de 0..1 para sangrar). `z` ordena las capas.
- Colores: cada componente pinta con un ROL de `colors` o con un hex literal. Contraste alto: el texto
  sobre `background` usa `ink`; sobre `surface`, `on_surface`; sobre `accent`, `on_accent`.
- Tipografía: `display` (titulares y precio), `body` (descripciones), `label` (etiquetas, cinta).
  Familias de Google Fonts escritas exactamente como en su catálogo. `size` de cada texto es el MÁXIMO
  a 1080 px: el motor mide y reduce cada línea para que quepa en el ancho de su bloque.
- Fondo: `base` solid | radial (background_alt al centro → background → background_edge) | linear;
  `layers` (máx. 4): rays (rayos cónicos desde `center`), rings (aros concéntricos), dots, stripes,
  grid, waves, pattern_image (repite un recurso de la marca, p. ej. una trama), blobs, grain, confetti;
  cada una con color, opacity, scale, angle_deg, center.
- Bloques (`blocks` de una receta):
  · photo: foto del hueco `slot` (cover o `zoom`, `focus`), `veil` = degradado vertical sobre TODO el
    lienzo con paradas {color, alpha, at %}; `framed`: true la pone como tarjeta con borde y sombra.
  · logo: el logo (hueco `brand.logo`), ancho = ancho del box, alto proporcional.
  · product: la foto del producto del hueco. Si la foto NO es un recorte con transparencia, el marco
    `cutout_*` cae a `disc`; elige `disc`, `arch`, `rounded` o `blob` para fotos con fondo.
  · stamp: sello circular (hueco con {big, small}); variantes circle_ring | starburst | scallop | none.
  · text_stack: columna de textos en su box: tag (texto literal corto o hueco), headline (hueco; se parte
    en dos líneas según `components.headline.split`, o donde haya «|»), body (hueco; `[[x]]` = chip,
    `**x**` = destacado, `__x__` = negrita), price (hueco {amount, symbol, code}: se imprime ENTERO o no
    se imprime), flag (banderín con texto, `<<x>>` = parte pequeña; forma pennant|double|arrow|rect),
    chips (lista), note. `space_before` = px sobre cada ítem. `align` y `valign` del bloque.
  · ticker: cinta de lado a lado con la lista del hueco. info_list: grupos de chips (pagos).
  · icon_feature: ícono grande (clock, pin, card, chat, bag, star, heart). sun: disco de rayos de dos
    colores. glow: halo. sparkle: destello.
- En 9:16 (historia) deja libres de texto los 250 px de arriba y los 300 de abajo (interfaz de Instagram).
- Componentes (`components`): tag, headline, price, stamp, ticker, product_frame, info_card, logo,
  sparkle, body. `shapes`: radius_px, tilt_deg, shadow (hard|soft|none), shadow_offset_px, stroke_px.

Reglas de marca:
- Respeta lo que la marca ya tiene (logo, colores, tipografías) cuando lo trae; una propuesta puede
  reinterpretar la jerarquía de colores, nunca inventar una marca distinta.
- Todo texto que leerá el dueño o su cliente, en español neutro, sin anglicismos ni jerga de un solo
  país («publicación», no «post»). Etiquetas cortas (≤ 26 caracteres).
- El precio se imprime entero, tal como viene en el hueco.
- Nada de texto inventado sobre el producto: los títulos, descripciones, precios, horarios y
  direcciones vienen de los huecos. Solo las etiquetas (`tag`) y la cinta pueden ser texto tuyo.
"""


def _image_block(path: Path) -> dict:
    media = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[
        path.suffix.lower().lstrip(".")
    ]
    data = base64.b64encode(path.read_bytes()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}


def build_user(brand: dict, slots: dict, images: list[Path]) -> list[dict]:
    schema = json.dumps(export_schema(), ensure_ascii=False)
    text = f"""Marca (lo que el dueño cargó en «Tu marca»):
{json.dumps(brand, ensure_ascii=False, indent=1)}

Huecos con el contenido REAL del dueño (las recetas apuntan a estas rutas; no las cambies):
{json.dumps(slots, ensure_ascii=False, indent=1)}

Recursos de la marca disponibles para `pattern_image` o `logo`: {json.dumps(brand.get("assets", []), ensure_ascii=False)}

Esquema JSON de un BrandVisualSystem v0 (cúmplelo al pie de la letra; no agregues campos):
{schema}

Tarea: propón TRES sistemas visuales para esta marca, cada uno de una FAMILIA DE ESTILO claramente
distinta (por ejemplo: pop gráfico de alto contraste · artesanal/editorial cálido · lúdico ilustrado;
elige las tres que mejor sirvan a esta marca y a su público). Cada sistema debe traer al menos estas
tres recetas, que se dibujarán con los mismos huecos:
- `product_hero` en formato "4:5": el producto estrella con su precio (huecos `product.*`).
- `hours` en formato "4:5": el horario y la dirección (huecos `hours.*`).
- `story` en formato "9:16": una historia de apertura (huecos `story.*`).
Puedes agregar `payments` (4:5, hueco `payments`).

Para cada sistema: `schema_version` 0, `version` 1, `parent_version` null, `id` en minúsculas con
guiones que empiece por "{brand["slug"]}-", `brand` "{brand["name"]}", `name` corto en español para
mostrárselo al dueño, `style_family`, `rationale` (2–3 frases en español: por qué le sirve),
`provenance` {{"source": "ai_proposal", "model": "{MODEL}", "prompt_version": "{PROMPT_VERSION}",
"created_at": "{datetime.now(UTC).isoformat(timespec="seconds")}"}}.

Responde SOLO con un objeto JSON {{"proposals": [sistema1, sistema2, sistema3]}}, sin texto alrededor
y sin bloque de código."""
    content: list[dict] = [_image_block(p) for p in images]
    content.append({"type": "text", "text": text})
    return content


def _json_from(text: str) -> dict:
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if fence:
        t = fence.group(1)
    start, end = t.find("{"), t.rfind("}")
    return json.loads(t[start : end + 1])


def main(brand_dir: str) -> None:
    base = HERE / brand_dir
    brand = json.loads((base / "brand_input.json").read_text())
    slots = json.loads((base / "slots.json").read_text())
    images = [Path(p) for p in brand.pop("images_for_model")]
    run = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = base / "out" / run
    out.mkdir(parents=True, exist_ok=True)

    client = anthropic.Anthropic(api_key=_key(), max_retries=2)
    t0 = time.time()
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "high"},
        system=SYSTEM,
        messages=[{"role": "user", "content": build_user(brand, slots, images)}],
    ) as stream:
        msg = stream.get_final_message()
    secs = time.time() - t0

    served_by = msg.model
    pin, pout = PRICE.get(served_by, PRICE[MODEL])
    u = msg.usage
    usd = (u.input_tokens * pin + u.output_tokens * pout) / 1e6
    usage = {
        "run": run,
        "model_requested": MODEL,
        "model_served": served_by,
        "prompt_version": PROMPT_VERSION,
        "stop_reason": msg.stop_reason,
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "usd": round(usd, 4),
        "seconds": round(secs, 1),
    }
    (out / "usage.json").write_text(json.dumps(usage, indent=1))
    print(json.dumps(usage))
    if msg.stop_reason == "refusal":
        raise SystemExit("refused")

    text = "".join(b.text for b in msg.content if b.type == "text")
    (out / "raw.txt").write_text(text)
    data = _json_from(text)
    (out / "proposals.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
    report = []
    for i, p in enumerate(data.get("proposals", []), 1):
        try:
            BrandVisualSystem.model_validate(p)
            (out / f"propuesta-{i}.system.json").write_text(
                json.dumps(p, ensure_ascii=False, indent=1)
            )
            report.append({"n": i, "id": p.get("id"), "name": p.get("name"), "valid": True})
        except ValidationError as e:
            (out / f"propuesta-{i}.invalid.json").write_text(
                json.dumps(p, ensure_ascii=False, indent=1)
            )
            (out / f"propuesta-{i}.errors.txt").write_text(str(e))
            report.append({"n": i, "id": p.get("id"), "valid": False, "errors": e.error_count()})
    (out / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report, ensure_ascii=False))
    print(f"out: {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "polette")
