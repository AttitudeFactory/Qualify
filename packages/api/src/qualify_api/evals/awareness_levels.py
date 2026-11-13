"""Measuring the awareness levels (Eugene Schwartz) and the business perks (m-25026482) —
the pure half of `packages/api/evals/niveles_consciencia/`.

Three suites, each a baseline against the change on the same cases:

- `angles` — «10 variaciones» (`qualify_creative.angles` + the call of
  `qualify_api.creative.angles_ai.generate_angles`). Baseline = the prompt of a git ref
  before the change (`load_module_at`), run on the same products; the new prompt runs
  each product with its perks and with none.
- `copy` — the copy prompt (`brand.render.render_prompt`) for briefs built by
  `angle_brief` from one hand-written angle per level: new = level + perks, baseline =
  the same angle through the baseline ref's `angle_brief`, kit without perks.
- `parts` — «Proponerme las partes» (`parts_ai.propose_parts`): new = angle with level +
  brand perks, baseline = the same brief and angle, level and perks stripped (the v3.2
  prompt is byte-identical to v3.1 then — `parts_prompt_identical`).

Deterministic checks (`fact_mentions`, `invented_facts`, `level_rule`, `perks_used`,
`level_spread`) run on the customer-facing words: hook and CTA of an angle; hook,
caption, CTA and script of a copy; the part descriptions of a video. The judge
(`JUDGE_RUBRIC`, Claude Haiku 5.5) is a second reading, written down before any run:
blind (it infers the level and scores quality without seeing the declared level) and
informed (does the idea follow ITS declared level's rule).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

from qualify_creative.angles import price_mentions
from qualify_creative.enums import AwarenessLevel
from qualify_creative.pricing import JsonPricingTable

from qualify_api.claude_tools import (
    Attribution,
    CallStats,
    ClaudeToolError,
    Meter,
    ModelConfig,
    create_turn,
    default_client,
    forced_or_auto,
    tool_uses,
)

#: The commit before the change (main at a6667370): what «baseline» means here.
BASELINE_REF = "a6667370"
#: The versioned price sheet every cost here is computed with.
PRICING_VERSION = "v9"
JUDGE_CONFIG = ModelConfig("claude-haiku-5-5", "low")
JUDGE_TOOL = "calificar_ideas"
JUDGE_MAX_TOKENS = 6000
JUDGE_PROMPT_VERSION = "juez-niveles-v2"
LEVELS: tuple[str, ...] = tuple(level.value for level in AwarenessLevel)
_NIL = UUID(int=0)

#: The bar a level must reach on TEST to be called reliable (written before the run).
BAR_JUDGE_FIT = 0.80
BAR_INVENTED = 0.05
#: most_aware: «hook y cta muy breves» made countable (pre-registered).
MOST_AWARE_HOOK_WORDS = 8
MOST_AWARE_CTA_WORDS = 5


# -- text helpers ------------------------------------------------------------------------


def fold(text: str) -> str:
    """Casefolded, accents stripped, single-spaced — what every comparison runs on."""
    decomposed = unicodedata.normalize("NFKD", (text or "").casefold())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(plain.split())


def words(text: str) -> int:
    return len(re.findall(r"[^\W_]+", text or ""))


def _numbers(text: str) -> set[str]:
    """Digit runs with separators removed ("25.000" → "25000", "11 p. m." → "11")."""
    return {re.sub(r"[.,]", "", n) for n in re.findall(r"\d[\d.,]*\d|\d", text or "")}


# -- fact extraction ---------------------------------------------------------------------

_HOURS = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?\s?m\.?|p\.?\s?m\.?|m\.)(?![a-z])"
    r"|\b(?:hasta|desde|de|entre)\s+las?\s+\d{1,2}(?::\d{2})?\b"
    r"|\b\d{1,2}\s*(?:hrs?|horas)\b"
    r"|\b(?:lunes|martes|miercoles|jueves|viernes|sabados?|domingos?)\s+(?:a|al)\s+"
    r"(?:lunes|martes|miercoles|jueves|viernes|sabados?|domingos?)\b"
    r"|\btodos los dias\b|\b24/7\b|\babiertos?\b"
)
_MONEY_EXTRA = re.compile(r"\b\d{1,3}(?:[.,]\d{3})+\b|\b\d+\s?mil\b|\b\d+\s?millones\b")
_PAYMENT = re.compile(
    r"\b(?:efectivo|tarjetas?|nequi|daviplata|transferencias?|pago movil|zelle|bancolombia"
    r"|datafono|codigo qr|qr|paypal|cuotas|contra ?entrega|pse|binance|credito|debito)\b"
)
_ADDRESS = re.compile(
    r"\b(?:calle|carrera|cra\.?|avenida|av\.|diagonal|transversal)\s*\d+"
    r"|#\s?\d+|\ben la \d+\b|\blocal \d+\b|\bdireccion\b|\ba \w+ cuadras?\b"
)
_DELIVERY = re.compile(r"\b(?:domicilios?|delivery|a domicilio|envios?|te lo llevamos)\b")
_DISCOUNT = re.compile(
    r"\d+\s?%|\bdescuentos?\b|\b2\s?x\s?1\b|\bpromo(?:cion)?(?:es)?\b|\bmitad de precio\b"
    r"|\bgratis\b|\bde regalo\b|\bofertas?\b|\brebajas?\b|\bcupon(?:es)?\b|\bva por la casa\b"
    r"|\bsin costo\b"
)
FACT_KINDS: tuple[str, ...] = ("horario", "precio", "pago", "direccion", "domicilio", "descuento")
_WORD_KINDS: Mapping[str, re.Pattern[str]] = {
    "pago": _PAYMENT,
    "direccion": _ADDRESS,
    "domicilio": _DELIVERY,
    "descuento": _DISCOUNT,
}


def fact_mentions(text: str) -> dict[str, list[str]]:
    """Every hour, price, payment method, address, delivery or discount stated in
    `text`, by kind (folded). Empty kinds are left out."""
    folded = fold(text)
    out: dict[str, list[str]] = {}
    hours = [m.group(0) for m in _HOURS.finditer(folded)]
    if hours:
        out["horario"] = hours
    prices = [fold(p) for p in price_mentions(text)]
    covered = set().union(*(_numbers(p) for p in prices)) if prices else set()
    for m in _MONEY_EXTRA.finditer(folded):
        if not _numbers(m.group(0)) <= covered:
            prices.append(m.group(0))
            covered |= _numbers(m.group(0))
    if prices:
        out["precio"] = prices
    for kind, pattern in _WORD_KINDS.items():
        found = [m.group(0) for m in pattern.finditer(folded)]
        if found:
            out[kind] = found
    return out


def invented_facts(text: str, sources: str) -> list[tuple[str, str]]:
    """The facts of `text` that `sources` (perks + product + brand) do not back, as
    (kind, mention). A number-carrying mention is backed when every number in it is
    among the sources' numbers; a word mention when its words appear in the sources."""
    folded_sources = fold(sources)
    source_numbers = _numbers(folded_sources)
    source_stems = _stems(folded_sources)
    out: list[tuple[str, str]] = []
    for kind, mentions in fact_mentions(text).items():
        for mention in mentions:
            numbers = _numbers(mention)
            if numbers:
                backed = numbers <= source_numbers
            else:
                stems = _stems(mention) or {mention.strip(" .#")}
                backed = mention.strip(" .#") in folded_sources or stems <= source_stems
            if not backed:
                out.append((kind, mention))
    return out


# -- perks -------------------------------------------------------------------------------

_STOP = frozenset(
    "para con los las del una uno unos unas que por sin hasta desde este esta "
    "nuestro nuestra tus sus mas muy todo toda todos todas cada".split()
)


def _stems(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z0-9]+", fold(text)) if len(w) >= 4 and w not in _STOP}


def perks_used(text: str, perks: Sequence[str], *, share: float = 0.6) -> list[int]:
    """1-based numbers of the perks `text` uses: at least `share` of a perk's content
    words (5-letter stems) appear in it."""
    have = _stems(text)
    used = []
    for number, perk in enumerate(perks, start=1):
        stems = _stems(perk)
        if stems and len(stems & have) / len(stems) >= share:
            used.append(number)
    return used


# -- level rules -------------------------------------------------------------------------


def level_rule(level: str | None, hook: str, cta: str, sources: str, body: str = "") -> bool | None:
    """The deterministic half of «does this idea follow its level»; None where only the
    judge can tell (problem_aware, solution_aware) or the level is missing.

    - unaware: no price, money or offer in hook or CTA;
    - product_aware: hook or CTA state at least one friction fact (an hour, price,
      payment method, address, delivery) that the sources back;
    - most_aware: hook ≤ `MOST_AWARE_HOOK_WORDS` words and CTA ≤ `MOST_AWARE_CTA_WORDS`.

    `body` is the rest of what the customer reads (a copy's caption and script): the
    unaware and product_aware rules read it too.
    """
    text = f"{hook}\n{cta}\n{body}"
    if level == AwarenessLevel.UNAWARE.value:
        facts = fact_mentions(text)
        return not (facts.get("precio") or facts.get("descuento"))
    if level == AwarenessLevel.PRODUCT_AWARE.value:
        facts = fact_mentions(text)
        invented = {m for _k, m in invented_facts(text, sources)}
        friction = [
            m
            for kind in ("horario", "precio", "pago", "direccion", "domicilio")
            for m in facts.get(kind, ())
            if m not in invented
        ]
        return bool(friction)
    if level == AwarenessLevel.MOST_AWARE.value:
        return words(hook) <= MOST_AWARE_HOOK_WORDS and words(cta) <= MOST_AWARE_CTA_WORDS
    return None


def level_spread(levels: Sequence[str | None], count: int = 10) -> dict[str, Any]:
    """How a set's declared levels compare with the even split asked for (10 → 2 each)."""
    counts = Counter(level if level in LEVELS else None for level in levels)
    base, extra = divmod(count, len(LEVELS))
    expected = {lv: base + (1 if i < extra else 0) for i, lv in enumerate(LEVELS)}
    return {
        "por_nivel": {lv: counts.get(lv, 0) for lv in LEVELS},
        "sin_nivel": counts.get(None, 0),
        "exacto": len(levels) == count and all(counts.get(lv, 0) == expected[lv] for lv in LEVELS),
        "desvio": sum(abs(counts.get(lv, 0) - expected[lv]) for lv in LEVELS),
    }


# -- loading the baseline ----------------------------------------------------------------


def load_module_at(ref: str, repo_path: str, module_name: str, repo_root: Path) -> ModuleType:
    """A module as it was at git `ref` (`git show ref:repo_path`), imported under
    `module_name` (a dotted name inside its package, so relative imports resolve)."""
    source = subprocess.run(
        ["git", "show", f"{ref}:{repo_path}"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    directory = Path(tempfile.mkdtemp(prefix="qualify-baseline-"))
    path = directory / Path(repo_path).name
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:  # pragma: no cover — a file always has one
        raise ImportError(module_name)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module  # dataclasses look their module up while defined
    spec.loader.exec_module(module)
    return module


def parts_prompt_identical(old: ModuleType, new: ModuleType, briefs: Iterable[Any]) -> int:
    """How many (brief, angle) pairs render the same system prompt, tool and user prompt
    under `old` and `new` parts_ai with no perks and no level; raises AssertionError on
    the first difference. `briefs` are `new.PartsBrief`s with an empty `brand.perks`."""
    from qualify_creative.angles import CreativeAngle

    assert old.propose_system_prompt() == new.propose_system_prompt(), "system prompt"
    assert old.propose_tool() == new.propose_tool(), "tool"
    angle = CreativeAngle(position=1, title="Ángulo", scene="Escena", hook="Gancho", cta="Ven")
    checked = 0
    for brief in briefs:
        assert not brief.brand.perks, "the identity holds only without perks"
        old_brief = old.PartsBrief(
            story=brief.story,
            brand=brief.brand,
            product=brief.product,
            target_seconds=brief.target_seconds,
        )
        for each in (None, angle):
            assert old.propose_user_prompt(old_brief, each) == new.propose_user_prompt(
                brief, each
            ), f"user prompt differs for {brief.story!r}"
            checked += 1
    return checked


# -- cases -------------------------------------------------------------------------------


@dataclass(frozen=True)
class AngleCase:
    id: str
    split: str
    sector: str
    brand: Mapping[str, Any]
    product: Mapping[str, Any]
    perks: tuple[str, ...]


def load_angle_cases(path: Path) -> list[AngleCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for case in raw["angle_cases"]:
        brand = raw["brands"][case["brand"]]
        cases.append(
            AngleCase(
                id=case["id"],
                split=case["split"],
                sector=brand["sector_eval"],
                brand=brand["angle_brand"],
                product=case["product"],
                perks=tuple(brand.get("perks", ())),
            )
        )
    return cases


def sources_text(brand: Mapping[str, Any], product: Mapping[str, Any], perks: Sequence[str]) -> str:
    """Everything a stated fact may come from: perks, product and brand."""
    parts = [*perks, *(str(v) for v in product.values() if isinstance(v, str))]
    parts += [str(v) for v in brand.values() if isinstance(v, str)]
    return "\n".join(parts)


def build_inputs(module: ModuleType, case: AngleCase, *, with_perks: bool) -> tuple[Any, Any]:
    """The case's `AngleProduct` and `AngleBrand` in `module`'s own classes (the
    baseline's `AngleBrand` has no `perks`)."""
    product = module.AngleProduct(
        product_id=_NIL,
        name=case.product["name"],
        description=case.product.get("description", ""),
        category=case.product.get("category", ""),
        tags=tuple(case.product.get("tags", ())),
        price_label=case.product.get("price_label", ""),
        photo_keys=tuple(f"foto-{i}" for i in range(int(case.product.get("photos", 2)))),
    )
    names = {f.name for f in dataclasses.fields(module.AngleBrand)}
    values: dict[str, Any] = {
        k: (tuple(v) if isinstance(v, list) else v) for k, v in case.brand.items() if k in names
    }
    if "perks" in names:
        values["perks"] = case.perks if with_perks else ()
    return product, module.AngleBrand(**values)


# -- the angle call ----------------------------------------------------------------------


def cost_usd(stats: CallStats) -> Decimal:
    """A call's cost at the `PRICING_VERSION` sheet (cache reads and writes included)."""
    table = JsonPricingTable(PRICING_VERSION)

    def price(unit: str) -> Decimal:
        return table.unit_price(model_id=stats.model_id, unit=unit)

    total = (
        stats.input_tokens * price("per_mtok_in")
        + stats.output_tokens * price("per_mtok_out")
        + stats.cache_read_tokens * price("per_mtok_cache_read")
        + stats.cache_creation_tokens * price("per_mtok_cache_write")
    )
    return (total / Decimal(1_000_000)).quantize(Decimal("0.000001"))


def call_angles(
    module: ModuleType,
    product: Any,
    brand: Any,
    preset: Any,
    *,
    api_key: str,
    config: ModelConfig,
    max_tokens: int,
    feature: str,
    client: Any = None,
) -> tuple[list[dict[str, Any]], CallStats]:
    """One angle set through `module`'s prompt, exactly as `generate_angles` asks it
    (same system/user/tool, same forced-or-auto choice, one re-ask without a tool call).
    Returns the parsed angles as dicts and the call's stats."""
    system = module.angles_system_prompt()
    user = module.angles_user_prompt(product, brand, preset, count=module.DEFAULT_ANGLE_COUNT)
    tool = module.angles_tool(module.DEFAULT_ANGLE_COUNT)
    meter = Meter(config)
    client = client or default_client(api_key)
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    for attempt in range(2):
        response = create_turn(
            client,
            config,
            meter,
            system=system,
            messages=messages,
            tools=[tool],
            tool_choice=forced_or_auto(config, module.ANGLES_TOOL),
            max_tokens=max_tokens,
            attribution=Attribution.no_business(feature),
        )
        calls = [u for u in tool_uses(response) if u.name == module.ANGLES_TOOL]
        if calls:
            meter.tool_calls += 1
            raw = calls[0].input or {}
            angles = module.parse_angles(raw, count=module.DEFAULT_ANGLE_COUNT)
            # the level as ANSWERED (before parsing drops an unknown one), for the tag rate
            answered = [
                (row.get("title"), row.get("awareness_level"))
                for row in (raw.get("angles") or [])
                if isinstance(row, Mapping)
            ]
            raw_level = {str(t or "").strip().casefold(): lv for t, lv in answered}
            out = []
            for angle in angles:
                row = angle.model_dump(mode="json")
                row["nivel_respondido"] = raw_level.get(angle.title.casefold())
                out.append(row)
            return out, meter.stats()
        if attempt == 0:
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {"role": "user", "content": f"Entrega la respuesta con {tool['name']}."}
            )
    raise ClaudeToolError(
        f"{config.model_id} did not call {module.ANGLES_TOOL}", stats=meter.stats()
    )


# -- the judge ---------------------------------------------------------------------------

#: Written down before any judged run (qualify-measure). Spanish, as the ideas are.
JUDGE_RUBRIC = """\
Eres un evaluador estricto de ideas de publicidad para negocios pequeños de Colombia, \
Venezuela y Uruguay. Calificas con la herramienta calificar_ideas, una vez, una fila por \
idea, en el mismo orden y con el mismo número.

Los cinco niveles de consciencia (Eugene Schwartz) y su regla:
- unaware: el público aún no piensa en el producto. La idea muestra el lugar y la \
experiencia (ambiente, momento, compañía). Regla: ni precio ni oferta.
- problem_aware: el público ya siente la necesidad. Regla: el gancho nombra ese dilema \
y la idea presenta el producto como la respuesta.
- solution_aware: sabe qué tipo de cosa quiere pero no dónde. Regla: muestra por qué este \
negocio lo resuelve mejor, con datos concretos del producto (porción, ingredientes, \
variedad) que estén en los datos dados.
- product_aware: conoce el negocio pero duda. Regla: quita la fricción con datos dados \
(precio claro, horario, cómo pagar, dónde queda).
- most_aware: listo para comprar. Regla: el camino más corto a la compra; gancho y \
llamada a la acción muy breves y directos.

Datos reales: solo cuentan los que aparecen en «Datos del negocio». Un dato inventado es \
un horario, precio, forma de pago, dirección, domicilio, descuento o promoción que la \
idea afirma y que NO está en esos datos. Solo esas siete clases cuentan: un atributo del \
producto (sabor, tamaño, ingrediente) o una escena imaginada (luz, mesa, momento) no es \
un dato inventado aquí.

Calidad (1 a 5), una sola nota por idea:
5 = escena concreta y fotografiable, gancho natural en español latinoamericano, claro y \
en el tono de la marca, llamada a la acción clara, distinta de las demás;
4 = buena con un detalle flojo; 3 = correcta pero genérica; 2 = confusa, forzada o con \
anglicismos; 1 = no sirve para publicar.
"""


def judge_tool(blind: bool) -> dict[str, Any]:
    row: dict[str, Any] = {"numero": {"type": "integer"}}
    if blind:
        row.update(
            {
                "nivel_inferido": {"type": "string", "enum": list(LEVELS)},
                "calidad": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
                "datos_inventados": {"type": "array", "items": {"type": "string"}},
                "ventajas_usadas": {"type": "array", "items": {"type": "integer"}},
            }
        )
    else:
        row.update({"cumple_su_nivel": {"type": "boolean"}, "motivo": {"type": "string"}})
    return {
        "name": JUDGE_TOOL,
        "description": "Una fila por idea, en orden.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ideas": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": row,
                        "required": list(row),
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["ideas"],
            "additionalProperties": False,
        },
    }


def judge_user_prompt(
    ideas: Sequence[Mapping[str, str]], facts: str, perks: Sequence[str], *, blind: bool
) -> str:
    """`ideas`: dicts with the idea's text fields (and `nivel` when not blind)."""
    lines = ["== Datos del negocio ==", facts.strip() or "(ninguno)", ""]
    lines.append("== Ventajas del negocio (numeradas) ==")
    lines.extend(f"{i}. {p}" for i, p in enumerate(perks, start=1)) if perks else lines.append(
        "(ninguna)"
    )
    lines.append("")
    lines.append("== Ideas ==")
    for number, idea in enumerate(ideas, start=1):
        fields = "; ".join(f"{k}: {v}" for k, v in idea.items() if k != "nivel" and v)
        level = "" if blind else f" [nivel declarado: {idea.get('nivel')}]"
        lines.append(f"{number}.{level} {fields}")
    lines.append("")
    if blind:
        lines.append(
            "Para cada idea: el nivel al que mejor le habla (nivel_inferido), su calidad, "
            "los datos inventados (texto corto; lista vacía si ninguno) y los números de "
            "las ventajas que usa (lista vacía si ninguna)."
        )
    else:
        lines.append(
            "Para cada idea: ¿cumple la regla de SU nivel declarado? (cumple_su_nivel) y "
            "por qué, en una frase (motivo)."
        )
    return "\n".join(lines)


def call_judge(
    ideas: Sequence[Mapping[str, str]],
    facts: str,
    perks: Sequence[str],
    *,
    blind: bool,
    api_key: str,
    client: Any = None,
) -> tuple[list[dict[str, Any]], CallStats]:
    meter = Meter(JUDGE_CONFIG)
    client = client or default_client(api_key)
    response = create_turn(
        client,
        JUDGE_CONFIG,
        meter,
        system=JUDGE_RUBRIC,
        messages=[{"role": "user", "content": judge_user_prompt(ideas, facts, perks, blind=blind)}],
        tools=[judge_tool(blind)],
        tool_choice=forced_or_auto(JUDGE_CONFIG, JUDGE_TOOL),
        max_tokens=JUDGE_MAX_TOKENS,
        attribution=Attribution.no_business(
            "eval-niveles-juez", prompt_version=JUDGE_PROMPT_VERSION
        ),
    )
    calls = [u for u in tool_uses(response) if u.name == JUDGE_TOOL]
    rows = list((calls[0].input or {}).get("ideas") or []) if calls else []
    by_number = {int(r.get("numero", 0)): r for r in rows if isinstance(r, Mapping)}
    return [dict(by_number.get(i, {})) for i in range(1, len(ideas) + 1)], meter.stats()


# -- scoring -----------------------------------------------------------------------------


@dataclass
class IdeaScore:
    """One idea (angle, copy or video), every check, for the per-level tables."""

    arm: str
    case: str
    split: str
    sector: str
    with_perks: bool
    level: str | None
    level_answered: str | None = None
    rule_det: bool | None = None
    invented_det: list[tuple[str, str]] = field(default_factory=list)
    perks_det: list[int] = field(default_factory=list)
    judge_level: str | None = None
    judge_quality: int | None = None
    judge_invented: list[str] = field(default_factory=list)
    judge_perks: list[int] = field(default_factory=list)
    judge_fit: bool | None = None
    judge_reason: str = ""
    words_hook: int = 0
    words_cta: int = 0


def score_idea(
    *,
    arm: str,
    case: str,
    split: str,
    sector: str,
    with_perks: bool,
    level: str | None,
    hook: str,
    cta: str,
    full_text: str,
    sources: str,
    perks: Sequence[str],
    level_answered: str | None = None,
    facts_text: str | None = None,
    body: str = "",
) -> IdeaScore:
    """The deterministic checks of one idea. `facts_text` is what facts are read from
    (default hook + CTA), `full_text` what perks are looked for in."""
    stated = facts_text if facts_text is not None else f"{hook}\n{cta}"
    return IdeaScore(
        arm=arm,
        case=case,
        split=split,
        sector=sector,
        with_perks=with_perks,
        level=level,
        level_answered=level_answered,
        rule_det=level_rule(level, hook, cta, sources, body),
        invented_det=invented_facts(stated, sources),
        perks_det=perks_used(full_text, perks) if perks else [],
        words_hook=words(hook),
        words_cta=words(cta),
    )


def apply_judge(
    scores: Sequence[IdeaScore],
    blind: Sequence[Mapping[str, Any]],
    informed: Sequence[Mapping[str, Any]] | None,
) -> None:
    for i, score in enumerate(scores):
        row = blind[i] if i < len(blind) else {}
        if row:
            score.judge_level = row.get("nivel_inferido")
            score.judge_quality = row.get("calidad")
            score.judge_invented = [str(x) for x in row.get("datos_inventados") or []]
            score.judge_perks = [int(x) for x in row.get("ventajas_usadas") or []]
        if informed is not None and i < len(informed) and informed[i]:
            score.judge_fit = informed[i].get("cumple_su_nivel")
            score.judge_reason = str(informed[i].get("motivo") or "")[:200]


def _rate(values: Sequence[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def summarize(scores: Sequence[IdeaScore], *, group_level: str = "declared") -> dict[str, Any]:
    """Per level (`declared` level, or the judge's `inferred` one for a baseline without
    tags), the share of ideas passing each check, and the same over all ideas."""
    groups: dict[str, list[IdeaScore]] = defaultdict(list)
    for s in scores:
        key = s.level if group_level == "declared" else s.judge_level
        groups[key or "sin_nivel"].append(s)
    groups["_todas"] = list(scores)

    def stats(items: list[IdeaScore]) -> dict[str, Any]:
        perked = [s for s in items if s.with_perks]
        quality = [s.judge_quality for s in items if isinstance(s.judge_quality, int)]
        return {
            "n": len(items),
            "regla_det": _rate([s.rule_det for s in items if s.rule_det is not None]),
            "regla_juez": _rate([s.judge_fit for s in items if s.judge_fit is not None]),
            "nivel_juez_coincide": _rate(
                [s.judge_level == s.level for s in items if s.level and s.judge_level]
            ),
            "inventa_det": _rate([bool(s.invented_det) for s in items]),
            "inventa_juez": _rate([bool(s.judge_invented) for s in items if s.judge_level]),
            "usa_ventaja_det": _rate([bool(s.perks_det) for s in perked]),
            "usa_ventaja_juez": _rate([bool(s.judge_perks) for s in perked if s.judge_level]),
            "calidad_juez": round(sum(quality) / len(quality), 2) if quality else None,
            "palabras_gancho": round(sum(s.words_hook for s in items) / len(items), 1)
            if items
            else None,
            "palabras_cta": round(sum(s.words_cta for s in items) / len(items), 1)
            if items
            else None,
        }

    order = [*LEVELS, "sin_nivel", "_todas"]
    return {key: stats(groups[key]) for key in order if key in groups}


def reliability(summary: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """«fiable» / «no fiable» per level against the pre-registered bar."""
    out = {}
    for level in LEVELS:
        row = summary.get(level)
        if not row or not row["n"]:
            out[level] = "sin datos"
            continue
        fit = row["regla_juez"]
        invented = max(v for v in (row["inventa_det"], row["inventa_juez"]) if v is not None)
        ok = fit is not None and fit >= BAR_JUDGE_FIT and invented <= BAR_INVENTED
        out[level] = "fiable" if ok else "no fiable"
    return out


__all__ = [
    "BASELINE_REF",
    "FACT_KINDS",
    "JUDGE_RUBRIC",
    "LEVELS",
    "AngleCase",
    "IdeaScore",
    "apply_judge",
    "build_inputs",
    "call_angles",
    "call_judge",
    "cost_usd",
    "fact_mentions",
    "fold",
    "invented_facts",
    "judge_tool",
    "judge_user_prompt",
    "level_rule",
    "level_spread",
    "load_angle_cases",
    "load_module_at",
    "parts_prompt_identical",
    "perks_used",
    "reliability",
    "score_idea",
    "sources_text",
    "summarize",
]
