"""«Tu plan del mes» on Anuncios (m-25091392 part 1): pure display projections.

The split is the backend's (`qualify_api.ads.month_plan`, the monthly cap of the investment
profile spread over the weeks); this file only words it: the week's dates, its amount and why
it gets more. Nothing here changes money, and nothing is sent to Meta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from qualify_api.ads.money import money_display
from qualify_api.ads.month_plan import MonthPlan, PlanDate, PlanWeek

MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

LOAD_FAILED = "No pudimos preparar tu plan del mes. Vuelve a entrar en un momento."
EXPLAIN = (
    "Es una sugerencia: ponemos más en las semanas en que la gente compra más. Tú decides "
    "cuándo promocionar; Qualify no lanza anuncios por su cuenta."
)
EMPTY_TITLE = "Planea cuánto invertir cada semana"
EMPTY_TEXT = (
    "Dinos cuánto quieres invertir al mes y te sugerimos cuánto usar cada semana, con más "
    "en quincenas y fechas especiales."
)
NORMAL_WEEK = "Semana sin fechas especiales"
ESTIMATED = ", fecha por confirmar"
# shortcut: their day is fixed; only their weight is a hypothesis (UX review). Move to the
# calendar table as a field if the list grows.
_FIXED_DAY = frozenset({"quincena", "halloween"})
# UX review, 2026-11-23: keep the names owners use, with a gloss where it is not obvious.
_SHOWN = {
    "Hot Sale": "Hot Sale (descuentos en línea)",
    "Cyber Monday": "Cyber Monday (lunes de descuentos)",
    "Black Week": "Semana del Black Friday",
}
# «Se acerca la Navidad», «Se acerca el Día de la Madre»; the rest takes «el».
_ARTICLE = {"Navidad": "la ", "Semana del Black Friday": "la ", "Amor y Amistad": ""}


@dataclass(frozen=True)
class PlanWeekVM:
    label: str = ""  # «Del 3 al 9 de mayo»
    amount: str = ""  # «$414.000 COP»
    reason: str = ""  # «Quincena · Se acerca el Día de la Madre, el 9 de mayo»
    raised: bool = False  # gets more than a normal week


@dataclass(frozen=True)
class MonthPlanVM:
    exists: bool = False  # False: no investment profile or no monthly cap
    tab: str = ""  # «Mayo»
    title: str = ""  # «Tu plan de mayo de 2027»
    cap: str = ""  # «Tu tope: $1.200.000 COP al mes»
    weeks: list[PlanWeekVM] = field(default_factory=list)


def month_pair(today: date) -> tuple[tuple[int, int], tuple[int, int]]:
    """(year, month) of this month and the next one."""
    return (today.year, today.month), (today.year + today.month // 12, today.month % 12 + 1)


def week_label(start: date, end: date) -> str:
    month = MONTHS[start.month - 1]  # weeks never cross the month
    if start == end:
        return f"El {start.day} de {month}"
    return f"Del {start.day} al {end.day} de {month}"


def date_reason(item: PlanDate, week: PlanWeek) -> str:
    """«Quincena», or «Se acerca el Día de la Madre, el 9 de mayo» when the date lies ahead
    of the week; a date not announced yet says so."""
    name = _SHOWN.get(item.name, item.name)
    if item.start > week.end:
        when = f"{item.start.day} de {MONTHS[item.start.month - 1]}"
        text = f"Se acerca {_ARTICLE.get(name, 'el ')}{name}, el {when}"
    else:
        text = name
    estimated = item.status == "hypothesis" and item.id not in _FIXED_DAY
    return text + (ESTIMATED if estimated else "")


def week_reason(week: PlanWeek) -> str:
    reasons = dict.fromkeys(date_reason(item, week) for item in week.dates)
    return " · ".join(reasons) or NORMAL_WEEK


def month_plan_vm(plan: MonthPlan | None, year: int, month: int) -> MonthPlanVM:
    name = MONTHS[month - 1]
    if plan is None:
        return MonthPlanVM(tab=name.capitalize(), title=f"Tu plan de {name} de {year}")
    return MonthPlanVM(
        exists=True,
        tab=name.capitalize(),
        title=f"Tu plan de {name} de {year}",
        cap=f"Hasta {money_display(plan.monthly_cap_minor, plan.currency)} al mes en anuncios, "
        "repartidos así:",
        weeks=[
            PlanWeekVM(
                label=week_label(week.start, week.end),
                amount=money_display(week.amount_minor, plan.currency),
                reason=week_reason(week),
                raised=week.tier != "normal",
            )
            for week in plan.weeks
        ],
    )
