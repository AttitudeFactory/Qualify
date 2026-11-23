"""«A cuántas personas llegarías» on the budget step (m-25091388): pure display projections.

The arithmetic is the backend's (`qualify_api.ads.market_size.estimate`) on Meta's range and
the CPM the audience step already read; this file only words it. Never a number without
Meta's range, never «0 personas», never more than Meta's upper bound.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from qualify_api.ads.market_size import Cpm, MarketEstimate, estimate, load_table

from .promotion_audience_vm import AudienceReachVM, approx_people, audience_range
from .promotion_vm import (
    COUNTRY_LABELS,
    PromotionDraftVM,
    budget_minor,
    budget_money,
    local_datetime,
)

CHOOSE_AUDIENCE = "Elige a quién quieres llegar y te decimos a cuántas personas llegaría tu dinero."
NO_RANGE = (
    "Meta no nos dio el tamaño de tu público, así que no podemos calcular a cuántas personas "
    "llegarías. Puedes seguir: el anuncio se crea igual."
)
FAILED = "No pudimos calcular a cuántas personas llegarías. Puedes seguir de todos modos."
WRITE_AMOUNT = "Escribe el monto y te decimos a cuántas personas podrías llegar."
CHECK_DATES = "Revisa las fechas y te decimos a cuántas personas llegarías."
SATURATED = (
    "Con este monto ya llegarías a casi todo tu público. "
    "Invertir más solo mostraría el anuncio más veces a las mismas personas."
)
NO_RANGE_REVIEW = "Sin estimación de Meta para este público"
PENDING_REVIEW = "Sin calcular"
FAILED_REVIEW = "No pudimos calcularlo; puedes seguir igual"


@dataclass(frozen=True)
class MarketVM:
    line: str = CHOOSE_AUDIENCE
    note: str = ""  # «Es un cálculo aproximado…», only under a number
    saturated: bool = False
    retry: bool = False
    review: str = PENDING_REVIEW


def _country(code: str) -> str:
    return COUNTRY_LABELS.get(code, "ese país")


def promotion_days(draft: PromotionDraftVM, timezone_name: str) -> int | None:
    """Whole days the promotion runs (a part day counts), or None while the dates are wrong."""
    try:
        start = local_datetime(draft.start_local, timezone_name)
        end = local_datetime(draft.end_local, timezone_name)
    except ValueError:
        return None
    seconds = (end - start).total_seconds()
    return math.ceil(seconds / 86_400) if seconds > 0 else None


def market_estimate(
    reach: AudienceReachVM, draft: PromotionDraftVM, timezone_name: str
) -> MarketEstimate | None:
    """The estimate this screen shows, also kept with the prepared promotion. None without
    Meta's range; `people` None without an amount, dates or a CPM."""
    if not reach.available or reach.market_failed or not reach.market_class:
        return None
    days = promotion_days(draft, timezone_name)
    currency = draft.currency
    budget = budget_minor(draft.budget, currency) if days and _valid_budget(draft) else None
    return estimate(
        lower=reach.lower,
        upper=reach.upper,
        budget_minor=budget,
        days=days if budget else None,
        currency=currency,
        cpm=Cpm(reach.cpm_minor, currency, reach.cpm_source) if reach.cpm_minor else None,
        table=load_table(),
        audience_hash=reach.audience_hash,
    )


def market_view(reach: AudienceReachVM, draft: PromotionDraftVM, timezone_name: str) -> MarketVM:
    if reach.status == "failed" or (reach.available and reach.market_failed):
        return MarketVM(FAILED, retry=True, review=FAILED_REVIEW)
    if not reach.available:
        if reach.status == "unavailable":
            return MarketVM(NO_RANGE, review=NO_RANGE_REVIEW)
        return MarketVM()
    country = _country(draft.location_country)
    if not reach.cpm_minor:
        return MarketVM(
            f"Todavía no tenemos datos de anuncios en {country} para calcular a cuántas "
            "personas llegarías. Puedes seguir de todos modos.",
            review=f"No lo calculamos: aún no tenemos datos de anuncios en {country}",
        )
    if not _valid_budget(draft):
        return MarketVM(WRITE_AMOUNT)
    days = promotion_days(draft, timezone_name)
    if days is None:
        return MarketVM(CHECK_DATES)
    found = market_estimate(reach, draft, timezone_name)
    if found is None or found.people is None:
        return MarketVM(FAILED, retry=True, review=FAILED_REVIEW)
    money = budget_money(draft.budget, draft.currency)
    period = "en 1 día" if days == 1 else f"en {days} días"
    people = approx_people(found.people)
    if found.people >= found.audience_upper:
        line = (
            f"Con {money} {period} llegarías a casi todas las personas de tu público "
            f"({approx_people(found.audience_upper)})."
        )
    else:
        line = f"Con {money} {period} llegarías a {people} de tu público (aproximado)."
    # «Unas 9.400, de un público de …»: the word «personas» once (UX review).
    short = people.removesuffix(" de personas").removesuffix(" personas")
    short = short if short.startswith("unas") else people
    review = f"{short[0].upper()}{short[1:]}, de un público de " + audience_range(
        found.audience_lower, found.audience_upper, "a"
    )
    return MarketVM(
        line,
        note=(
            "Es un cálculo aproximado de Qualify con lo que suelen costar los anuncios en "
            f"{country}. No es una promesa: Meta decide a quién y cuántas veces lo muestra."
        ),
        saturated=found.saturated,
        review=review,
    )


def _valid_budget(draft: PromotionDraftVM) -> bool:
    try:
        budget_minor(draft.budget, draft.currency)
    except ValueError:
        return False
    return True
