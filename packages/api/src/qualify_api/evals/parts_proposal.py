"""Scoring «Proponerme las partes» (VE-14 m-24921071) — the pure half of
`packages/api/evals/proponer_partes/`: load the real briefs, run the production path
(`parts_ai.propose_parts`, price guard included) and score each proposal.

Per item: `partes_en_rango` (3-6), `segundos_totales` and `desvio_duracion` (vs the
target), `sin_precios`, `sin_texto_en_pantalla`, `partes_distintas` (no two parts with
token Jaccard >= 0.6), `cierre_invita` (a PROXY of the beginning→closing arc: the last
part shows an invitation cue — the arc itself is for the human review queue), `costo_usd`,
`latencia_s`, `fallo`. Per run: the share of usable proposals, mean and max cost, p95
latency.

Cases are REAL one-sentence briefs of real tenants (qualify-measure): no invented ones.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_creative.angles import AngleBrand, AngleProduct, price_mentions
from qualify_creative.schemas import PARTS_MAX
from qualify_shared import observability
from qualify_shared.observability import ItemOutcome, Score

from qualify_api.creative.parts_ai import (
    PARTS_MIN,
    PartsBrief,
    PartsProposalUnavailable,
    propose_parts,
)

DATASET = "proponer-partes"
_NIL = UUID(int=0)  # an eval product has no catalog row
SIMILAR = 0.6

#: Words that mean something is written or branded on screen — the parts must not.
_ON_SCREEN = re.compile(
    r"\b(texto|letrero|cartel|letras|tipograf\w*|subt[ií]tulo\w*|logo\w*|escrito|escrita"
    r"|leyenda|etiqueta con|que dice)\b",
    re.IGNORECASE,
)
#: Cues that the closing part invites to act (proxy, see the module docstring).
_INVITES = re.compile(
    r"\b(pedi\w*|pide\w*|ordena\w*|entrega\w*|domicilio\w*|mostrador|puerta|entrada"
    r"|local|visita\w*|reserva\w*|llev\w*|recib\w*|compr\w*|whatsapp|tel[eé]fono|celular"
    r"|invita\w*|esper\w*|ven\b|vengan?)\b",
    re.IGNORECASE,
)


class SpendCapReached(RuntimeError):
    """The run's hard stop: no more paid calls once this much was spent."""


@dataclass
class SpendMeter:
    """What the run spent, summed from each proposal's provenance (and each failure's
    stats); `check` refuses the next call once `cap_usd` is reached."""

    cap_usd: Decimal
    spent_usd: Decimal = Decimal(0)

    def check(self) -> None:
        if self.spent_usd >= self.cap_usd:
            raise SpendCapReached(f"spent {self.spent_usd} USD of the {self.cap_usd} cap")

    def add(self, usd: Decimal | float) -> None:
        self.spent_usd += Decimal(str(usd))


def load_cases(path: Path) -> list[dict[str, Any]]:
    """`{"cases": [{"id", "business", "story", "target_seconds"?, "product"?, "brand"?}]}`
    as dataset items."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for case in raw["cases"]:
        items.append(
            {
                "id": case["id"],
                "input": {
                    "case": case["id"],
                    "business": case.get("business", ""),
                    "story": case["story"],
                    "target_seconds": case.get("target_seconds", 20),
                    "product": case.get("product"),
                    "brand": case.get("brand") or {},
                },
                "metadata": {"business": case.get("business", "")},
            }
        )
    return items


def brief_of(case: Mapping[str, Any]) -> PartsBrief:
    product = case.get("product") or None
    brand = case.get("brand") or {}
    return PartsBrief(
        story=str(case["story"]),
        target_seconds=int(case.get("target_seconds") or 20),
        brand=AngleBrand(
            name=str(brand.get("name", "")),
            sector=str(brand.get("sector", "")),
            location=str(brand.get("location", "")),
            positioning=str(brand.get("positioning", "")),
            audience=str(brand.get("audience", "")),
            palette=tuple(brand.get("palette", ())),
            typeface=str(brand.get("typeface", "")),
        ),
        product=(
            AngleProduct(
                product_id=_NIL,
                name=str(product.get("name", "")),
                description=str(product.get("description", "")),
                category=str(product.get("category", "")),
                photo_keys=tuple(f"photo-{i}" for i in range(int(product.get("photos", 1)))),
            )
            if product
            else None
        ),
    )


def propose(case: Mapping[str, Any], *, api_key: str, meter: SpendMeter) -> dict[str, Any]:
    """The production call for one case; a failure is an output, never an exception."""
    meter.check()
    trace_id = observability.current_trace_id()
    started = time.monotonic()
    try:
        proposal = propose_parts(brief_of(case), api_key=api_key)
    except PartsProposalUnavailable as exc:
        cost = exc.stats.cost_usd if exc.stats is not None else 0.0
        meter.add(cost)
        return {
            "failed": str(exc),
            "trace_id": trace_id,
            "cost_usd": float(cost),
            "latency_s": round(time.monotonic() - started, 2),
        }
    meter.add(proposal.provenance.cost_usd)
    return {
        "parts": [{"description": p.description, "seconds": p.seconds} for p in proposal.parts],
        "provenance": proposal.provenance.model_dump(mode="json"),
        "trace_id": trace_id,
        "cost_usd": float(proposal.provenance.cost_usd),
        "latency_s": round(time.monotonic() - started, 2),
    }


def _tokens(text: str) -> frozenset[str]:
    folded = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(c for c in folded if not unicodedata.combining(c))
    return frozenset(w for w in re.findall(r"[a-z0-9]+", plain) if len(w) > 3)


def most_similar(descriptions: Sequence[str]) -> float:
    best = 0.0
    tokens = [_tokens(d) for d in descriptions]
    for i, a in enumerate(tokens):
        for b in tokens[i + 1 :]:
            if a or b:
                best = max(best, len(a & b) / len(a | b))
    return best


def proposal_scores(
    input: Any, output: Any, _expected: Any = None, _metadata: Any = None
) -> list[Score]:
    out = output or {}
    scores = [
        Score("costo_usd", float(out.get("cost_usd") or 0.0)),
        Score("latencia_s", float(out.get("latency_s") or 0.0)),
    ]
    if out.get("failed"):
        return [*scores, Score("fallo", True, str(out["failed"])[:300])]
    parts = out.get("parts") or []
    texts = [str(p.get("description", "")) for p in parts]
    total = sum(int(p.get("seconds", 0)) for p in parts)
    target = int((input or {}).get("target_seconds") or 20)
    priced = [m for t in texts for m in price_mentions(t)]
    written = sorted({m.group(0).lower() for t in texts for m in _ON_SCREEN.finditer(t)})
    similar = most_similar(texts)
    return [
        *scores,
        Score("fallo", False),
        Score("partes_en_rango", PARTS_MIN <= len(parts) <= PARTS_MAX, f"{len(parts)} partes"),
        Score("segundos_totales", float(total)),
        Score("desvio_duracion", abs(total - target) / target),
        Score("sin_precios", not priced, ", ".join(priced) or None),
        Score("sin_texto_en_pantalla", not written, ", ".join(written) or None),
        Score("partes_distintas", similar < SIMILAR, f"Jaccard máx {similar:.2f}"),
        Score("cierre_invita", bool(texts) and bool(_INVITES.search(texts[-1]))),
    ]


ITEM_EVALUATORS = (proposal_scores,)


def run_summary(outcomes: Sequence[ItemOutcome]) -> list[Score]:
    usable = [
        o
        for o in outcomes
        if o.scores.get("fallo") is False
        and all(
            o.scores.get(k) is True
            for k in ("partes_en_rango", "sin_precios", "sin_texto_en_pantalla", "partes_distintas")
        )
    ]
    costs = sorted(float(o.scores.get("costo_usd") or 0.0) for o in outcomes)
    latencies = sorted(float(o.scores.get("latencia_s") or 0.0) for o in outcomes)
    n = len(outcomes) or 1
    p95 = latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))] if latencies else 0.0
    return [
        Score("propuestas_usables", len(usable) / n),
        Score("fallos", float(sum(1 for o in outcomes if o.scores.get("fallo") is True))),
        Score("costo_medio_usd", sum(costs) / n),
        Score("costo_max_usd", costs[-1] if costs else 0.0),
        Score("costo_total_usd", sum(costs)),
        Score("latencia_p95_s", p95),
    ]


RUN_EVALUATORS = (run_summary,)
