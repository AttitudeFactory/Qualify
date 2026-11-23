"""The business's investment profile, in the owner's words (m-25091387).

Pure: parsing what the owner types (whole units with thousands dots, no cents), turning the
margin answered in money into the percent the backend stores, and the result's copy.
Design: `.claude/ux-perfil-inversion-2026-11-22.md`. Amounts are in the brand's ad account
currency (COP, USD or UYU, m-25091394); others are refused with `CURRENCY_UNSUPPORTED`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import ROUND_DOWN, Decimal

from qualify_api.ads.investment_profile import ESTIMATED_MARGIN_PERCENT
from qualify_api.ads.money import budget_field, money_display

PROFILE_ROUTE = "/promotions/perfil"
TOTAL_STEPS = 5
STEP_TITLES = (
    "¿Qué quieres que haga la gente?",  # the wizard's own words (promotion_vm.STEP_TITLES)
    "¿Cuánto te paga un cliente en una compra?",
    "¿Cuánto te queda de cada venta?",
    "¿Cuántos clientes nuevos más podrías atender por semana?",
    "¿Cuánto podrías poner en anuncios al mes sin apretarte?",
)
# (backend objective, title, detail): the promotion wizard's three goals, same titles.
OBJECTIVES = (
    (
        "chat",
        "Que te escriban",
        "Te llegan mensajes por WhatsApp o Instagram y tú cierras la venta.",
    ),
    ("website", "Que visite tu página", "Vendes o reservas en tu página web."),
    (
        "lead",
        "Que te deje sus datos para contactarla",
        "La persona llena un formulario corto y tú la contactas.",
    ),
)
OBJECTIVE_TITLES = {key: title for key, title, _ in OBJECTIVES}

# Margin answered as a money range over the owner's own price: (choice, stored percent).
# Bounds at 20/40/60 % of the price; each range stores a value inside it.
MARGIN_RANGES = (("low", 15), ("mid", 30), ("high", 50), ("top", 65))
MARGIN_EXACT = "exact"
MARGIN_UNKNOWN = "unknown"  # «No lo sé todavía»: the backend stores 30 %, estimated
MARGIN_CHOICES = {key for key, _ in MARGIN_RANGES} | {MARGIN_EXACT, MARGIN_UNKNOWN}

MAX_WHOLE_AMOUNT = 10**12  # whole units; the backend's bound is 10**15 hundredths
MAX_WEEKLY_CLIENTS = 100_000

PICK_OBJECTIVE = "Elige una opción para seguir."
TICKET_EMPTY = "Escribe cuánto paga un cliente para seguir."
CAP_EMPTY = "Escribe cuánto podrías poner al mes para seguir."
AMOUNT_ZERO = "Escribe un valor mayor que cero."
AMOUNT_CENTS = "Escribe el valor sin centavos. Por ejemplo: 20.000."
AMOUNT_LETTERS = "Usa solo números. Por ejemplo: 20.000."
AMOUNT_TOO_BIG = "Revisa el valor: es demasiado grande."
PICK_MARGIN = "Elige cuánto te queda para seguir."
EXACT_EMPTY = "Escribe cuánto te queda o elige otra opción."
EXACT_ZERO = (
    "Si no te queda nada, un anuncio no te dejaría ganancia. "
    "Revisa el valor o elige «No lo sé todavía»."
)
CLIENTS_EMPTY = "Escribe un número para seguir."
CLIENTS_ZERO = "Escribe al menos 1."
CLIENTS_DECIMALS = "Escribe un número entero."
CLIENTS_LETTERS = "Usa solo números. Por ejemplo: 15."
CLIENTS_TOO_BIG = "Escribe un número de hasta 100.000."

SAVED_NOTICE = "Listo, lo actualizamos."
REVIEW_MARGIN = "Revisa cuánto te queda con el precio nuevo."
LOAD_FAILED = "No pudimos consultar lo que sabemos de tu negocio. Vuelve a intentarlo."
SAVE_FAILED = "No pudimos guardar tus respuestas. Vuelve a intentarlo."
NO_SESSION = "Vuelve a iniciar sesión para calcular cuánto te conviene pagar por un cliente."

_DIGITS = re.compile(r"\d+")
_GROUPED = re.compile(r"\d{1,3}([.,]\d{3})+")
_CENTS = re.compile(r"(\d+|\d{1,3}([.,]\d{3})+)[.,]\d{1,2}")
# `?volver=`: only the promotion wizard of one publication, with its own parameters.
_PROMOTE_RETURN = re.compile(r"/drafts/[0-9a-fA-F-]{36}/promote(\?[A-Za-z0-9=&%_.~+-]*)?")


def _plain_number(raw: str) -> tuple[int | None, str]:
    """(value, "") for «20000», «20.000», «$20.000», «20 000»; (None, kind) otherwise,
    kind being "empty", "cents" or "letters". Never rounds."""
    value = re.sub(r"[\s$]", "", raw or "")
    if not value:
        return None, "empty"
    if _DIGITS.fullmatch(value) or _GROUPED.fullmatch(value):
        return int(re.sub(r"[.,]", "", value)), ""
    if _CENTS.fullmatch(value):
        return None, "cents"
    return None, "letters"


def read_amount(raw: str, empty: str = TICKET_EMPTY) -> tuple[int, str]:
    """(whole pesos, "") or (0, the reason to show)."""
    value, problem = _plain_number(raw)
    if value is None:
        return 0, {"empty": empty, "cents": AMOUNT_CENTS}.get(problem, AMOUNT_LETTERS)
    if value <= 0:
        return 0, AMOUNT_ZERO
    if value > MAX_WHOLE_AMOUNT:
        return 0, AMOUNT_TOO_BIG
    return value, ""


def read_clients(raw: str) -> tuple[int, str]:
    value, problem = _plain_number(raw)
    if value is None:
        return 0, {
            "empty": CLIENTS_EMPTY,
            "cents": CLIENTS_DECIMALS,
        }.get(problem, CLIENTS_LETTERS)
    if value <= 0:
        return 0, CLIENTS_ZERO
    if value > MAX_WEEKLY_CLIENTS:
        return 0, CLIENTS_TOO_BIG
    return value, ""


def whole_money(whole: int, currency: str) -> str:
    """«$20.000 COP», «$10 USD»: whole units in the app-wide format (qualify-copy-es §5)."""
    return money_display(whole * 100, currency)


# Field examples in each currency, so a dollar account never reads «Ejemplo: 200.000».
_EXAMPLES = {
    "COP": ("20.000", "12.000", "200.000", "$20.000", "$1.500.000", "$150.000", "$8.000"),
    "USD": ("10", "6", "100", "$10", "$500", "$50", "$4"),
    "UYU": ("400", "240", "4.000", "$400", "$40.000", "$3.000", "$160"),
}


def money_copy(currency: str) -> dict[str, str]:
    """Labels, placeholders and examples of the money questions in the account currency."""
    unit = budget_field(currency)
    code = currency if currency in _EXAMPLES else "COP"
    ticket, kept, cap, combo, trip, advice, cost = _EXAMPLES[code]
    unit_name = unit.unit_name if unit else "pesos colombianos"
    return {
        "ticket_label": f"Lo que paga en una compra, en {unit_name}",
        "ticket_placeholder": f"Ejemplo: {ticket}",
        "ticket_hint": f"Por ejemplo: un combo de comida, {combo} · un paquete de viaje, {trip} "
        f"· una asesoría, {advice}.",
        "margin_hint": f"Por ejemplo: vendes un combo en {combo}. Los ingredientes y el empaque "
        f"te cuestan {cost}. Te quedan ${kept}.",
        "kept_label": f"Me quedan, en {unit_name}",
        "kept_placeholder": f"Ejemplo: {kept}",
        "cap_label": f"Tope al mes, en {unit_name}",
        "cap_placeholder": f"Ejemplo: {cap}",
    }


def amount_echo(raw: str, currency: str) -> str:
    """«Son $20.000 COP» under a money field once it reads, else ""."""
    value, problem = read_amount(raw)
    return "" if problem else f"Son {whole_money(value, currency)}"


def cap_echo(raw: str, currency: str) -> str:
    value, problem = read_amount(raw, CAP_EMPTY)
    if problem:
        return ""
    weekly = _round(value * 12 // 52, _step(value))
    return (
        f"Son {whole_money(value, currency)} al mes, "
        f"unos {whole_money(weekly, currency)} por semana."
    )


def _step(price: int) -> int:
    """Rounding of the shown amounts: to $1.000 for usual prices, finer for small ones,
    so the ranges never read «Entre $1.000 y $1.000»."""
    return 1000 if price >= 20_000 else 100 if price >= 2_000 else 1


def _round(value: int, step: int) -> int:
    return max(step, (value + step // 2) // step * step) if value > 0 else 0


def margin_bounds(price: int) -> tuple[int, int, int]:
    """The money at 20, 40 and 60 % of the price, rounded for reading."""
    step = _step(price)
    return tuple(_round(price * pct // 100, step) for pct in (20, 40, 60))  # type: ignore[return-value]


def margin_options(ticket_raw: str, currency: str) -> list[tuple[str, str]]:
    """(choice, label) of step 3, computed over the owner's own price."""
    price, problem = read_amount(ticket_raw)
    exact = [(MARGIN_EXACT, "Lo sé exacto"), (MARGIN_UNKNOWN, "No lo sé todavía")]
    if problem:
        return exact
    low, mid, high = (whole_money(value, currency) for value in margin_bounds(price))
    return [
        ("low", f"Poco: menos de {low}"),
        ("mid", f"Entre {low} y {mid}"),
        ("high", f"Entre {mid} y {high}"),
        ("top", f"Más de {high}"),
        *exact,
    ]


def margin_percent(choice: str, ticket_raw: str, exact_raw: str) -> tuple[Decimal | None, str]:
    """(percent for the backend, "") — None for «No lo sé todavía» — or (None, reason).
    The exact amount becomes kept / price, cut (never rounded up) to 2 decimals."""
    if choice == MARGIN_UNKNOWN:
        return None, ""
    for key, percent in MARGIN_RANGES:
        if choice == key:
            return Decimal(percent), ""
    if choice != MARGIN_EXACT:
        return None, PICK_MARGIN
    price, problem = read_amount(ticket_raw)
    if problem:
        return None, problem
    kept, problem = read_amount(exact_raw, EXACT_EMPTY)
    if problem == AMOUNT_ZERO:
        return None, EXACT_ZERO
    if problem:
        return None, problem
    if kept >= price:
        return None, "Lo que te queda tiene que ser menor que lo que paga tu cliente."
    percent = (Decimal(kept) * 100 / Decimal(price)).quantize(Decimal("0.01"), ROUND_DOWN)
    return (percent, "") if percent > 0 else (None, EXACT_ZERO)


@dataclass(frozen=True)
class ProfileAnswersVM:
    """What the owner typed or chose, as typed (N6: leaving never clears it)."""

    objective: str = ""
    ticket: str = ""
    margin_choice: str = ""
    margin_exact: str = ""
    clients: str = ""
    cap: str = ""


def step_problem(answers: ProfileAnswersVM, step: int) -> str:
    """Why step ``step`` (1..5) cannot go on yet, or ""."""
    if step == 1:
        return "" if answers.objective in OBJECTIVE_TITLES else PICK_OBJECTIVE
    if step == 2:
        return read_amount(answers.ticket)[1]
    if step == 3:
        return margin_percent(answers.margin_choice, answers.ticket, answers.margin_exact)[1]
    if step == 4:
        return read_clients(answers.clients)[1]
    if step == 5:
        return read_amount(answers.cap, CAP_EMPTY)[1]
    return ""


def first_problem(answers: ProfileAnswersVM) -> tuple[int, str]:
    """(step, reason) of the first unanswered step, or (0, "")."""
    for step in range(1, TOTAL_STEPS + 1):
        if reason := step_problem(answers, step):
            return step, reason
    return 0, ""


def save_values(answers: ProfileAnswersVM) -> dict[str, object]:
    """The keyword arguments of `save_investment_profile`, money in hundredths.
    Call only when `first_problem` is (0, "")."""
    return {
        "objective": answers.objective,
        "average_ticket_minor": read_amount(answers.ticket)[0] * 100,
        "margin_percent": margin_percent(
            answers.margin_choice, answers.ticket, answers.margin_exact
        )[0],
        "weekly_new_clients": read_clients(answers.clients)[0],
        "monthly_cap_minor": read_amount(answers.cap, CAP_EMPTY)[0] * 100,
    }


def safe_return(raw: object) -> str:
    """`?volver=` only when it is a publication's «Promocionar» wizard; anything else
    (another site, another screen) is dropped: it is later a redirect target."""
    value = str(raw or "").strip()
    return value if len(value) <= 512 and _PROMOTE_RETURN.fullmatch(value) else ""


@dataclass(frozen=True)
class ProfileVM:
    """A saved profile, ready to read. ``exists`` False: never answered."""

    exists: bool = False
    objective: str = ""
    ticket: int = 0  # whole pesos
    margin_points: int = 0  # 3550 = 35,5 %
    estimated: bool = False
    clients: int = 0
    cap: int = 0  # whole pesos
    kept: int = 0  # whole pesos left of one sale
    max_cost: int = 0  # whole pesos, rounded down by the backend
    currency: str = "COP"


def headline(profile: ProfileVM) -> str:
    return f"Hasta {whole_money(profile.max_cost, profile.currency)}"


def card_title(profile: ProfileVM) -> str:
    """The Anuncios list card, once answered."""
    return f"Hasta {whole_money(profile.max_cost, profile.currency)} por cliente nuevo"


def meaning(profile: ProfileVM) -> str:
    amount = whole_money(profile.max_cost, profile.currency)
    return (
        f"Si un anuncio te trae un cliente por menos de {amount}, esa venta te deja "
        "ganancia. Si te cuesta más, la pierdes."
    )


def how_computed(profile: ProfileVM) -> str:
    return (
        f"Tu cliente paga unos {whole_money(profile.ticket, profile.currency)} y de eso "
        f"te quedan unos {whole_money(profile.kept, profile.currency)}."
    )


def answer_rows(profile: ProfileVM) -> list[tuple[int, str, str]]:
    """(step, label, value) of «Tus respuestas», each with its «Cambiar»."""
    kept = f"Unos {whole_money(profile.kept, profile.currency)}" + (
        " (aproximado)" if profile.estimated else ""
    )
    return [
        (1, "Lo que quieres", OBJECTIVE_TITLES.get(profile.objective, "")),
        (2, "Lo que paga un cliente", whole_money(profile.ticket, profile.currency)),
        (3, "Lo que te queda", kept),
        (4, "Clientes nuevos por semana", f"{profile.clients:,}".replace(",", ".")),
        (5, "Tope al mes", whole_money(profile.cap, profile.currency)),
    ]


def answers_from(profile: ProfileVM) -> ProfileAnswersVM:
    """The saved profile as the steps show it, so «Cambiar» opens with the value in."""
    if not profile.exists:
        return ProfileAnswersVM()
    choice, exact = MARGIN_UNKNOWN, ""
    if not profile.estimated:
        ranges = {percent * 100: key for key, percent in MARGIN_RANGES}
        choice = ranges.get(profile.margin_points, MARGIN_EXACT)
        if choice == MARGIN_EXACT:
            exact = f"{profile.kept:,}".replace(",", ".")
    return ProfileAnswersVM(
        objective=profile.objective,
        ticket=f"{profile.ticket:,}".replace(",", "."),
        margin_choice=choice,
        margin_exact=exact,
        clients=str(profile.clients),
        cap=f"{profile.cap:,}".replace(",", "."),
    )


def with_answer(answers: ProfileAnswersVM, name: str, value: str) -> ProfileAnswersVM:
    """One typed or chosen answer; unknown fields and absurd lengths are ignored."""
    if name not in {"objective", "ticket", "margin_choice", "margin_exact", "clients", "cap"}:
        return answers
    if len(value) > 40:
        return answers
    if name == "objective" and value not in OBJECTIVE_TITLES:
        return answers
    if name == "margin_choice" and value not in MARGIN_CHOICES:
        return answers
    return replace(answers, **{name: value})


def unknown_note(ticket_raw: str, currency: str) -> str:
    """What «No lo sé todavía» means, in the owner's own price."""
    price, problem = read_amount(ticket_raw)
    if problem:
        return "Usaremos un valor prudente. Puedes cambiarlo cuando lo sepas."
    kept = price * ESTIMATED_MARGIN_PERCENT // 100
    return (
        f"Usaremos un valor prudente: unos {whole_money(kept, currency)} de cada "
        f"{whole_money(price, currency)}. "
        "Puedes cambiarlo cuando lo sepas."
    )
