"""«Sugerencia» on the budget step (m-25091389): pure display projections.

The amounts, days, pieces and reasons are the backend's (`qualify_api.ads.budget_suggestion`,
already in Spanish and bounded by Meta's minimum and the owner's cap); this file only decides
which form of the card shows and words the button, the confirmation and the two lines under
«Total». It never changes money by itself: the field only changes on «Usar este monto».
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from qualify_api.ads.budget_suggestion import BudgetSuggestion, money

from .promotion_market_vm import promotion_days
from .promotion_vm import PromotionDraftVM, cop_minor, local_datetime

LOADING = "Preparando tu sugerencia…"
UNAVAILABLE = "No pudimos preparar una sugerencia. Escribe el monto que quieras."
GENERAL_VALUES = "Usamos valores generales porque aún no nos contaste de tu negocio."


@dataclass(frozen=True)
class BudgetHintVM:
    # "" nothing, "loading", "none" (only `line`), "blocked" (no amount fits the cap),
    # "full" (the card), "compact" (the owner typed another amount), "applied".
    mode: str = ""
    headline: str = ""
    reasons: list[str] = field(default_factory=list)
    pieces_note: str = ""
    general_values: bool = False
    button: str = ""
    line: str = ""


def _days(n: int) -> str:
    return "1 día" if n == 1 else f"{n} días"


def field_amount(suggestion: BudgetSuggestion) -> str:
    """What «Usar este monto» writes: whole units, rounded UP so a cents minimum from
    Meta is never written below itself. shortcut: can pass the cap by under one unit."""
    return str(-(-(suggestion.piece_total_minor or 0) // 100))


def _typed_minor(draft: PromotionDraftVM) -> int | None:
    try:
        return cop_minor(draft.budget)
    except ValueError:
        return None


def budget_hint(
    suggestion: BudgetSuggestion | None,
    status: str,
    message: str,
    draft: PromotionDraftVM,
    timezone_name: str,
) -> BudgetHintVM:
    if status == "loading":
        return BudgetHintVM("loading", line=LOADING)
    if status == "failed":
        return BudgetHintVM("none", line=message or UNAVAILABLE)
    if suggestion is None:
        return BudgetHintVM()
    if not suggestion.fits or suggestion.daily_minor is None:
        return BudgetHintVM("blocked", line=suggestion.reasons[0] if suggestion.reasons else "")
    cur = suggestion.currency
    days = suggestion.days
    one = suggestion.pieces == 1
    moves_dates = promotion_days(draft, timezone_name) != days
    button = ("Usar este monto" if one else "Usar la parte de esta publicación") + (
        f" y {_days(days)}" if moves_dates else ""
    )
    pieces_note = suggestion.pieces_note or ""
    typed = _typed_minor(draft)
    if typed is not None and draft.budget.strip() == field_amount(suggestion) and not moves_dates:
        what = "la sugerencia" if one else "la parte de esta publicación"
        return BudgetHintVM(
            "applied",
            line=f"Pusimos {what}: {money(int(field_amount(suggestion)) * 100, cur)} en "
            f"{_days(days)}. Puedes cambiarlo abajo.",
        )
    amounts = (
        f"{money(suggestion.daily_minor, cur)} al día durante {_days(days)} "
        f"(total {money(suggestion.total_minor or 0, cur)})."
    )
    if typed is not None:
        return BudgetHintVM(
            "compact",
            headline=f"Sugerencia: {amounts}",
            pieces_note="" if one else pieces_note,
            button=button,
        )
    return BudgetHintVM(
        "full",
        headline=f"Te sugerimos {amounts}",
        reasons=list(suggestion.reasons[:2]),
        pieces_note=pieces_note,
        general_values=suggestion.general_values,
        button=button,
    )


def suggested_end(draft: PromotionDraftVM, timezone_name: str, days: int) -> str:
    """The end date «Usar este monto y N días» writes: start + N days, or "" when the
    start cannot be read (then the dates stay as they are)."""
    try:
        start = local_datetime(draft.start_local, timezone_name)
    except ValueError:
        return ""
    return (start + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


def daily_line(draft: PromotionDraftVM, timezone_name: str, currency: str) -> str:
    """«Son unos $5.000 COP al día durante 7 días.» for any amount; rounded down to the
    unit, never to thousands, so it never looks like we changed the owner's amount."""
    typed = _typed_minor(draft)
    days = promotion_days(draft, timezone_name)
    if typed is None or not days:
        return ""
    return f"Son unos {money(typed // days // 100 * 100, currency)} al día durante {_days(days)}."


def over_cap_line(
    suggestion: BudgetSuggestion | None, draft: PromotionDraftVM, timezone_name: str
) -> str:
    """Under «Total», never in the card: information, never a block."""
    typed = _typed_minor(draft)
    if suggestion is None or suggestion.cap_remaining_minor is None or typed is None:
        return ""
    days = promotion_days(draft, timezone_name)
    monthly = typed if not days or days <= 30 else typed * 30 // days  # the cap is per month
    if monthly <= suggestion.cap_remaining_minor:
        return ""
    cur = suggestion.currency
    if suggestion.inputs.get("spent_this_month_minor"):
        limit = (
            f"lo que te queda de tu tope este mes ({money(suggestion.cap_remaining_minor, cur)})"
        )
    else:
        cap = (suggestion.inputs.get("profile") or {}).get("monthly_cap_minor")
        limit = f"tu tope de {money(cap or suggestion.cap_remaining_minor, cur)} al mes"
    return f"Este monto pasa {limit}. Puedes seguir si lo decidiste."
