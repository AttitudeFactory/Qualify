"""A traffic light and one recommended action on each promotion (m-25091390).

Meta says whether the ad set is still learning (`learning_stage_info`, its threshold per ad
set: never a hard-coded «50 in 7 days»), how often people saw the ad (`frequency`, which only
a whole-period Insights query gives: daily reach does not add up) and what Meta itself
suggests (`act_<id>/recommendations`); docs/discovery-asesor-inversion-meta.md §3, §6, §7.
Everything else — how much to raise, what counts as cheap, tired or saturated — is our rule,
in the versioned, PROVISIONAL table `data/semaforo-v1.json`.

Rules, first match wins (`advise`, pure):

1. learning `FAIL` → «no subas, cambia la pieza o el público» (red);
2. learning `LEARNING` → «espera» (yellow), with Meta's own threshold when it gives one;
3. fewer results than `min_results` → «espera» (yellow);
4. frequency ≥ `fatigue_frequency` and cost per click up ≥ `fatigue_cost_rise` between the
   first and last `fatigue_window_days` closed days → «haz una pieza nueva» (red, Crear pieza);
5. reach ≥ `saturation_share_of_audience_lower` × Meta's audience lower bound saved before
   approval → «amplía la zona» (yellow);
6. no investment profile in the account's currency → «mantén» and ask for it (yellow);
7. cost per result ≤ `cheap_share_of_max_cost` × what a client can cost → «súbele X %»
   (green); ≤ that maximum → «mantén» (yellow); above → «no subas» (red).

Meta's `SCALE_GOOD_CAMPAIGN` / `BUDGET_LIMITED` are shown as «Meta sugiere…» and may be applied
only as our own budget raise (`prepare_advised_raise` → the consented two-step edit of
`live_management`); `CREATIVE_FATIGUE` is only ever a notice. Nothing here writes to Meta.

Assisted, never autonomous: the advice is computed on each results read and stored with its
rules version and the Meta data it used (`ad_promotion_observations.advice`, 0189). While
`QUALIFY_ADS_TRAFFIC_LIGHT` is off (the default) no extra Meta read happens and nothing is
shown: the shapes below follow Meta's documentation and wait for the live test m-24828971.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_api.ads.investment_profile import display_step_minor
from qualify_api.ads.money import money_display
from qualify_api.ads.results import DailyInsight, ResultsUnavailable, nonnegative

RULES_VERSION = "semaforo-v1"
PIPELINE_VERSION = "ad-traffic-light-v1"
_DATA = Path(__file__).parent / "data"
# shortcut: off by default because none of these reads was measured against a real account;
# turn on in production after m-24828971 (same pattern as QUALIFY_ADS_CHAT_GOAL).
TRAFFIC_LIGHT_ENV = "QUALIFY_ADS_TRAFFIC_LIGHT"

ACTIONS = ("wait", "raise", "keep", "change", "fatigue", "widen")
LIGHTS = {
    "raise": "green",
    "keep": "yellow",
    "wait": "yellow",
    "widen": "yellow",
    "change": "red",
    "fatigue": "red",
}
# Meta's types we translate; any other type is ignored, its text is never shown (§7).
BUDGET_SUGGESTIONS = ("SCALE_GOOD_CAMPAIGN", "BUDGET_LIMITED")
META_TYPES = (*BUDGET_SUGGESTIONS, "CREATIVE_FATIGUE")
LEARNING = ("LEARNING", "SUCCESS", "FAIL")

META_TEXT = {
    "SCALE_GOOD_CAMPAIGN": "Meta sugiere subir el presupuesto: tu anuncio está funcionando bien.",
    "BUDGET_LIMITED": (
        "Meta sugiere subir el presupuesto: con un poco más podrías conseguir más resultados."
    ),
    "CREATIVE_FATIGUE": (
        "Meta sugiere una pieza nueva: cada resultado podría estar saliendo más caro "
        "que en tus anuncios anteriores."
    ),
}
STALE = "Actualiza los resultados para ver la recomendación de hoy."
NO_RAISE = "Esta promoción no tiene una subida recomendada ahora."


def traffic_light_on() -> bool:
    return os.environ.get(TRAFFIC_LIGHT_ENV, "").strip().lower() in {"1", "true"}


@dataclass(frozen=True)
class Rules:
    version: str
    raise_percent: int
    cheap_share: Decimal
    min_results: int
    fatigue_frequency: Decimal
    fatigue_cost_rise: Decimal
    fatigue_window_days: int
    saturation_share: Decimal


@lru_cache(maxsize=4)
def load_rules(version: str = RULES_VERSION) -> Rules:
    raw = json.loads((_DATA / f"{version}.json").read_text(encoding="utf-8"))
    if raw["version"] != version:
        raise ValueError(f"traffic-light table declares {raw['version']!r}, expected {version!r}")
    rules = Rules(
        version,
        int(raw["raise_percent"]),
        Decimal(raw["cheap_share_of_max_cost"]),
        int(raw["min_results"]),
        Decimal(raw["fatigue_frequency"]),
        Decimal(raw["fatigue_cost_rise"]),
        int(raw["fatigue_window_days"]),
        Decimal(raw["saturation_share_of_audience_lower"]),
    )
    if not (
        0 < rules.raise_percent <= 100
        and 0 < rules.cheap_share < 1
        and rules.min_results > 0
        and rules.fatigue_frequency > 1
        and rules.fatigue_cost_rise > 0
        and rules.fatigue_window_days > 0
        and 0 < rules.saturation_share <= 1
    ):
        raise ValueError(f"traffic-light table {version!r} is out of bounds")
    return rules


# --- Meta reads (pure parsers; shapes from Meta's reference, unmeasured until m-24828971) ---


def parse_learning(row: dict[str, Any], *, adset_id: str) -> dict[str, Any]:
    """`GET <adset>?fields=id,learning_stage_info` — node `AdCampaignLearningStageInfo`
    (discovery §3): `status` LEARNING/SUCCESS/FAIL, `conversions`, `last_sig_edit_ts`,
    `dynamic_lp_conversions_threshold`, `dynamic_lp_days_threshold`. «Only returned for active
    ad sets»: absent → {} (unknown, not «learning»)."""
    if row.get("id") != adset_id:
        raise ResultsUnavailable("No pudimos comprobar a qué conjunto pertenece este anuncio.")
    info = row.get("learning_stage_info")
    if not isinstance(info, dict) or info.get("status") not in LEARNING:
        return {}
    count = {
        key: nonnegative(info.get(source), integer=True)
        for key, source in (
            ("conversions", "conversions"),
            ("conversions_threshold", "dynamic_lp_conversions_threshold"),
            ("days_threshold", "dynamic_lp_days_threshold"),
            ("last_sig_edit_ts", "last_sig_edit_ts"),
        )
    }
    return {"status": info["status"], **count}


def _first_value(items: Any) -> Decimal | None:
    """Insights `results` / `cost_per_result`: a list of `{indicator, values: [{value}]}`
    (Insights reference, discovery §6). One indicator per ad; anything else is unknown."""
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        return None
    values = items[0].get("values")
    if not isinstance(values, list) or len(values) != 1 or not isinstance(values[0], dict):
        return None
    return nonnegative(values[0].get("value"))


def parse_period(
    rows: tuple[dict[str, Any], ...], *, ad_id: str, account_id: str, currency: str
) -> dict[str, Any]:
    """The whole-period Insights row (no `time_increment`), the only source of a total
    frequency and reach. No row = no delivery yet → {}."""
    if not rows:
        return {}
    row = rows[0]
    if (
        len(rows) != 1
        or row.get("ad_id") != ad_id
        or row.get("account_id") != account_id
        or row.get("account_currency") != currency
    ):
        raise ResultsUnavailable("Meta devolvió resultados de otra cuenta o de otro período.")
    results = _first_value(row.get("results"))
    return {
        "spend": nonnegative(row.get("spend")),
        "reach": nonnegative(row.get("reach"), integer=True),
        "impressions": nonnegative(row.get("impressions"), integer=True),
        "frequency": nonnegative(row.get("frequency")),
        "results": int(results) if results is not None and results == int(results) else None,
        "cost_per_result": _first_value(row.get("cost_per_result")),
    }


def parse_recommendations(
    rows: tuple[dict[str, Any], ...], *, object_ids: tuple[str, ...]
) -> tuple[dict[str, Any], ...]:
    """`GET act_<id>/recommendations` (discovery §7): only the types we translate and only
    those naming this promotion's ad, ad set or campaign in `object_ids`. Meta's own text and
    lift estimate are never kept nor shown."""
    kept: dict[str, dict[str, Any]] = {}
    for row in rows:
        kind, ids = row.get("type"), row.get("object_ids")
        if kind not in META_TYPES or kind in kept or not isinstance(ids, list):
            continue
        if set(object_ids) & {str(item) for item in ids}:
            signature = row.get("recommendation_signature")
            kept[kind] = {
                "type": kind,
                "signature": signature if isinstance(signature, str) else "",
                "object_ids": sorted(set(object_ids) & {str(item) for item in ids}),
            }
    return tuple(kept[kind] for kind in META_TYPES if kind in kept)


# --- The rules ---


@dataclass(frozen=True)
class Advice:
    action: str
    reason: str
    observed_at: str
    rules_version: str = RULES_VERSION
    raise_percent: int | None = None
    cost_per_result_minor: int | None = None
    max_cost_minor: int | None = None
    learning_conversions: int | None = None
    learning_threshold: int | None = None
    meta: tuple[str, ...] = ()
    # Provenance: the Meta data and our inputs the rules read.
    inputs: dict[str, Any] = field(default_factory=dict)
    pipeline_version: str = PIPELINE_VERSION

    @property
    def light(self) -> str:
        return LIGHTS[self.action]

    @property
    def can_raise(self) -> bool:
        """One raise button: our rule, or Meta's budget suggestion when our light does not
        say wait or change (a raise while learning restarts it)."""
        return self.action == "raise" or (
            self.action in {"keep", "widen"} and any(m in BUDGET_SUGGESTIONS for m in self.meta)
        )

    @property
    def raise_source(self) -> str:
        if self.action == "raise":
            return "rules"
        return next((f"meta:{m}" for m in self.meta if m in BUDGET_SUGGESTIONS), "")

    def record(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), default=str))

    @classmethod
    def from_record(cls, raw: Any) -> Advice | None:
        """None for anything another rules version or pipeline wrote, or malformed."""
        if (
            not isinstance(raw, dict)
            or raw.get("rules_version") != RULES_VERSION
            or raw.get("pipeline_version") != PIPELINE_VERSION
            or raw.get("action") not in ACTIONS
            or not isinstance(raw.get("meta"), list)
            or not set(raw["meta"]) <= set(META_TYPES)
        ):
            return None
        try:
            return cls(**{**raw, "meta": tuple(raw["meta"])})
        except TypeError:
            return None


def _minor(value: Decimal) -> int:
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_UP))


def cost_rise(daily: tuple[DailyInsight, ...], window: int) -> Decimal | None:
    """Cost per click of the last `window` closed days over the first `window` (Σ spend /
    Σ clicks, never a mean of daily ratios) minus one; None without 2 × `window` days."""
    days = sorted((d for d in daily if d.spend is not None and d.clicks), key=lambda d: d.day)
    if len(days) < 2 * window:
        return None

    def rate(rows: list[DailyInsight]) -> Decimal:
        return sum((d.spend for d in rows), Decimal(0)) / sum(d.clicks for d in rows)

    first = rate(days[:window])
    return rate(days[-window:]) / first - 1 if first > 0 else None


def advise(
    *,
    learning: dict[str, Any],
    period: dict[str, Any],
    recommendations: tuple[dict[str, Any], ...],
    daily: tuple[DailyInsight, ...],
    max_cost_minor: int | None,
    audience_lower: int | None,
    observed_at: datetime,
    rules: Rules | None = None,
) -> Advice:
    rules = rules or load_rules()
    results, spend = period.get("results"), period.get("spend")
    cost = period.get("cost_per_result")
    if cost is None and results and spend is not None:
        cost = spend / results
    rise = cost_rise(daily, rules.fatigue_window_days)
    inputs = {
        "learning": learning,
        "period": period,
        "recommendations": list(recommendations),
        "cost_rise": rise,
        "max_cost_minor": max_cost_minor,
        "audience_lower": audience_lower,
        "daily_days": len(daily),
    }
    base = {
        "observed_at": observed_at.isoformat(),
        "rules_version": rules.version,
        "cost_per_result_minor": _minor(cost) if cost is not None else None,
        "max_cost_minor": max_cost_minor,
        "learning_conversions": learning.get("conversions"),
        "learning_threshold": learning.get("conversions_threshold"),
        "meta": tuple(r["type"] for r in recommendations),
        "inputs": json.loads(json.dumps(inputs, default=str)),
    }
    frequency, reach = period.get("frequency"), period.get("reach")

    def pick(action: str, reason: str) -> Advice:
        percent = rules.raise_percent if action == "raise" else None
        return Advice(action, reason, raise_percent=percent, **base)

    if learning.get("status") == "FAIL":
        return pick("change", "learning_failed")
    if learning.get("status") == "LEARNING":
        return pick("wait", "learning")
    if results is None or results < rules.min_results or cost is None:
        return pick("wait", "few_results")
    if (
        frequency is not None
        and frequency >= rules.fatigue_frequency
        and rise is not None
        and rise >= rules.fatigue_cost_rise
    ):
        return pick("fatigue", "fatigue")
    if audience_lower and reach is not None and reach >= rules.saturation_share * audience_lower:
        return pick("widen", "saturated")
    if not max_cost_minor:
        return pick("keep", "no_profile")
    if _minor(cost) <= rules.cheap_share * max_cost_minor:
        return pick("raise", "cheap")
    if _minor(cost) <= max_cost_minor:
        return pick("keep", "close")
    return pick("change", "expensive")


def raised_budget(current_minor: int, percent: int, currency: str) -> int:
    """`current` + `percent` %, rounded down to the shown step ($1.000 COP, the whole unit
    elsewhere) and at least one step above the current budget."""
    step = display_step_minor(currency)
    raised = current_minor * (100 + percent) // 100 // step * step
    return raised if raised > current_minor else current_minor + step


def suggested_budget(advice: Advice, current_minor: int, currency: str) -> int | None:
    if not advice.can_raise:
        return None
    return raised_budget(current_minor, load_rules().raise_percent, currency)


# --- What the owner reads (Spanish, qualify-copy-es) ---


def message(advice: Advice, currency: str) -> str:
    def money(minor: int | None) -> str:
        return money_display(minor, currency) if minor is not None else ""

    cost, top = money(advice.cost_per_result_minor), money(advice.max_cost_minor)
    if advice.reason == "learning":
        done = advice.learning_conversions
        need = advice.learning_threshold
        progress = (
            f" Lleva {done} de los {need} resultados que necesita."
            if done is not None and need
            else ""
        )
        return "Espera unos días. Meta todavía está aprendiendo a quién mostrar tu anuncio." + (
            progress
        )
    return {
        "learning_failed": (
            "No subas. Meta no consigue suficientes resultados con este anuncio. "
            "Cambia la pieza o el público."
        ),
        "few_results": (
            "Espera unos días. Todavía hay pocos resultados para saber si conviene subir."
        ),
        "fatigue": (
            "Tu público se cansó: ya vio tu anuncio muchas veces y cada clic sale más caro. "
            "Haz una pieza nueva."
        ),
        "saturated": (
            "Ya llegaste a casi toda la gente de tu zona. "
            "Amplía la zona para llegar a más personas."
        ),
        "no_profile": (
            "Mantén el presupuesto por ahora. Cuéntanos cuánto te deja cada cliente "
            "y te diremos si conviene subir."
        ),
        "cheap": (
            f"Súbele {advice.raise_percent} %. Cada persona interesada te cuesta {cost}, "
            f"bastante menos de lo que puedes pagar ({top})."
        ),
        "close": (
            f"Mantén el presupuesto. Cada persona interesada te cuesta {cost}, "
            f"cerca de lo que puedes pagar ({top})."
        ),
        "expensive": (
            f"No subas. Cada persona interesada te cuesta {cost}, "
            f"más de lo que puedes pagar ({top}). Cambia la pieza o el público."
        ),
    }[advice.reason]


def meta_notices(advice: Advice) -> tuple[str, ...]:
    return tuple(META_TEXT[kind] for kind in advice.meta)


# --- Applying a raise: only through the owner's two-step consent ---


async def prepare_advised_raise(*, tenant_id: UUID, promotion_id: UUID, request_key: str) -> Any:
    """Prepare (never send) the recommended raise as the ordinary consented budget edit.

    The owner still reviews and confirms it (`results_service.confirm_promotion_edit` with
    `confirm_change=True` by the signed-in member, saved as the operation's actor); the
    4-per-hour and decrease floors of `live_management` apply as to any edit. Refused when
    the stored advice is stale or has no raise (`CREATIVE_FATIGUE` never has one)."""
    from qualify_api.ads import results_service

    results = results_service.load_promotion_results(tenant_id=tenant_id, promotion_id=promotion_id)
    advice = results.advice
    if advice is None or results.insights_stale:
        raise ResultsUnavailable(STALE)
    current = results.promotion.current_budget_minor
    amount = (
        suggested_budget(advice, current, results.promotion.currency)
        if type(current) is int
        else None
    )
    if amount is None:
        raise ResultsUnavailable(NO_RAISE)
    return await results_service.prepare_promotion_edit(
        tenant_id=tenant_id,
        promotion_id=promotion_id,
        request_key=request_key,
        action="budget",
        budget_minor=amount,
        advice={"source": advice.raise_source, **advice.record()},
    )
